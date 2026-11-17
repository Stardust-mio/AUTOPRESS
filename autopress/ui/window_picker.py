# OWNED BY G7
"""Target-window picker: list of win32.windows.list_windows() (exe icon via
QFileIconProvider, title, exe name, 「系統管理員」 badge when elevation.input_permission is
BLOCKED_ELEVATED, 「未知權限」 when UNKNOWN), search, refresh, and 「點選視窗」 (overlays.pick
"window" crosshair). Windows of models.FORBIDDEN_TARGET_EXES are shown disabled with
「系統程式，不能當目標」; the profile's ``suggested_exe`` (imports) is listed first. Returns the
chosen WindowInfo; the caller stores info.to_target() (browser targets keep the title keyword
it contains; the user may shorten it, but not to empty)."""

from __future__ import annotations

import logging

from PyQt6.QtCore import QFileInfo, Qt
from PyQt6.QtGui import QIcon, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QDialog,
    QFileIconProvider,
    QHBoxLayout,
    QHeaderView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..context import AppContext
from ..i18n import tr
from ..models import FORBIDDEN_TARGET_EXES, TargetMatch, WindowInfo
from . import widgets as w

log = logging.getLogger(__name__)

ROLE_INDEX = Qt.ItemDataRole.UserRole + 1


def elevated_text() -> str:
    """SPEC 7.1 'target elevated' text."""
    return tr("目標程式以系統管理員權限執行，Windows 會無聲阻擋一般權限程式的模擬輸入。"
              "請按「以系統管理員身分重新啟動 AutoPress」。",
              "The target runs as administrator; Windows silently blocks simulated input from normal "
              "programs. Click \"Restart AutoPress as administrator\".")


def forbidden_text(exe: str) -> str:
    """SPEC 7.1 'forbidden target' text."""
    return tr(f"{exe} 是系統或命令列程式，AutoPress 不會對它輸入。請改選遊戲或兌換網頁的視窗。",
              f"{exe} is a system or command-line program; AutoPress never types into it. "
              "Pick the game or redeem page window instead.")


def is_forbidden_window(info: WindowInfo) -> bool:
    return info.exe_name.casefold() in FORBIDDEN_TARGET_EXES


def input_permission_of(hwnd: int) -> str:
    """"ok" | "blocked_elevated" | "unknown" ("ok" when the win32 layer is unavailable)."""
    try:
        from ..win32 import elevation

        return str(elevation.input_permission(hwnd))
    except Exception as exc:
        log.debug("input_permission unavailable: %s", exc)
        return "ok"


class WindowPickerDialog(QDialog):
    def __init__(self, ctx: AppContext, current: TargetMatch | None = None, parent: QWidget | None = None,
                 suggested_exe: str = "") -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.current = current
        self.suggested_exe = (suggested_exe or "").strip()
        self._windows: list[WindowInfo] = []
        self._perms: dict[int, str] = {}
        self._selected: WindowInfo | None = None
        self._icons = QFileIconProvider()
        self._icon_cache: dict[str, QIcon] = {}
        self.setWindowTitle(tr("選擇目標視窗", "Choose the target window"))
        self.setMinimumSize(720, 480)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)
        lay.addWidget(w.label(tr("選擇要自動輸入序號的遊戲或兌換網頁視窗", "Pick the game or redeem-page window"),
                              "title"))
        hint = tr("先開啟遊戲或兌換網頁，再從清單選擇；也可以按「點選視窗」直接在畫面上點它。",
                  "Open the game or redeem page first, then pick it from the list, or click \"Pick on screen\".")
        if self.suggested_exe:
            hint += tr(f"\n匯入的設定檔建議的程式：{self.suggested_exe}（已排在最前面）。",
                       f"\nThe imported profile suggests: {self.suggested_exe} (listed first).")
        hint_lb = w.label(hint, "muted")
        hint_lb.setWordWrap(True)
        lay.addWidget(hint_lb)

        bar = QHBoxLayout()
        self.search = w.SearchField(tr("搜尋視窗標題或程式名稱", "Search title or program"))
        self.search.textChanged.connect(self._fill)
        bar.addWidget(self.search, 1)
        self.refresh_btn = w.push_button(tr("重新整理", "Refresh"), "secondary", "refresh")
        self.refresh_btn.setToolTip(tr("重新整理視窗清單（F5）", "Refresh the window list (F5)"))
        self.refresh_btn.clicked.connect(self.refresh)
        bar.addWidget(self.refresh_btn)
        self.pick_btn = w.push_button(tr("點選視窗", "Pick on screen"), "secondary", "crosshair")
        self.pick_btn.setToolTip(tr("在畫面上點一下目標視窗", "Click the target window on the screen"))
        self.pick_btn.clicked.connect(self._pick_on_screen)
        bar.addWidget(self.pick_btn)
        lay.addLayout(bar)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels([tr("視窗標題", "Window title"), tr("程式", "Program"), tr("狀態", "Status")])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(False)
        hdr = self.tree.header()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.itemSelectionChanged.connect(self._on_selection)
        self.tree.itemDoubleClicked.connect(lambda *_a: self._accept_selected())
        lay.addWidget(self.tree, 1)

        self.empty = w.label("", "muted")
        self.empty.setWordWrap(True)
        self.empty.hide()
        lay.addWidget(self.empty)
        self.detail = w.label("", "secondary")
        self.detail.setWordWrap(True)
        lay.addWidget(self.detail)

        btns = QHBoxLayout()
        btns.addStretch(1)
        self.cancel_btn = w.push_button(tr("取消", "Cancel"), "secondary")
        self.cancel_btn.clicked.connect(self.reject)
        self.ok_btn = w.push_button(tr("選擇這個視窗", "Use this window"), "primary")
        self.ok_btn.setDefault(True)
        self.ok_btn.setEnabled(False)
        self.ok_btn.clicked.connect(self._accept_selected)
        btns.addWidget(self.cancel_btn)
        btns.addWidget(self.ok_btn)
        lay.addLayout(btns)

        QShortcut(QKeySequence(Qt.Key.Key_F5), self, activated=self.refresh)
        self.refresh()

    # -- data -----------------------------------------------------------------------------
    def windows(self) -> list[WindowInfo]:
        return list(self._windows)

    def refresh(self) -> None:
        error = ""
        try:
            from ..win32 import windows as win

            found = list(win.list_windows())
        except Exception as exc:
            log.warning("listing windows failed: %s", exc)
            found, error = [], tr("無法讀取視窗清單。", "Could not list the windows.")
        sug = self.suggested_exe.casefold()
        order = {id(info): n for n, info in enumerate(found)}
        found.sort(key=lambda i: (0 if sug and i.exe_name.casefold() == sug else 1, order[id(i)]))
        self._windows = found
        self._perms = {i.hwnd: input_permission_of(i.hwnd) for i in found if not is_forbidden_window(i)}
        self._fill()
        if error:
            self.empty.setText(error)
            self.empty.show()

    def _icon(self, path: str) -> QIcon:
        if not path:
            return QIcon()
        if path not in self._icon_cache:
            try:
                self._icon_cache[path] = self._icons.icon(QFileInfo(path))
            except Exception:  # pragma: no cover - defensive
                self._icon_cache[path] = QIcon()
        return self._icon_cache[path]

    def _fill(self) -> None:
        text = self.search.text().strip().casefold()
        keep = self._selected.hwnd if self._selected else 0
        self.tree.blockSignals(True)
        self.tree.clear()
        select_item = None
        for n, info in enumerate(self._windows):
            if text and text not in info.title.casefold() and text not in info.exe_name.casefold():
                continue
            badges = []
            tip = ""
            forbidden = is_forbidden_window(info)
            if forbidden:
                badges.append(tr("系統程式，不能當目標", "System program, cannot be the target"))
                tip = forbidden_text(info.exe_name)
            else:
                perm = self._perms.get(info.hwnd, "ok")
                if perm == "blocked_elevated":
                    badges.append(tr("系統管理員", "Administrator"))
                    tip = elevated_text()
                elif perm == "unknown":
                    badges.append(tr("未知權限", "Unknown privileges"))
                    tip = tr("無法讀取目標程式的權限（可能是系統或受保護程式）；若輸入沒有反應，請以系統管理員身分執行 AutoPress。",
                             "Cannot read the target's privileges (system or protected program). "
                             "If input has no effect, run AutoPress as administrator.")
            if info.minimized:
                badges.append(tr("已最小化", "Minimized"))
            if self.suggested_exe and info.exe_name.casefold() == self.suggested_exe.casefold():
                badges.append(tr("建議", "Suggested"))
            item = QTreeWidgetItem([info.title or tr("（無標題）", "(no title)"), info.exe_name or "?",
                                    " · ".join(badges)])
            item.setIcon(0, self._icon(info.exe_path))
            item.setData(0, ROLE_INDEX, n)
            item.setToolTip(0, info.title)
            if tip:
                for col in range(3):
                    item.setToolTip(col, tip)
            if forbidden:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled & ~Qt.ItemFlag.ItemIsSelectable)
            self.tree.addTopLevelItem(item)
            if not forbidden and select_item is None:
                if keep and info.hwnd == keep:
                    select_item = item
                elif not keep and self.current is not None and not self.current.is_empty() and \
                        self.current.matches(info.exe_path, info.title, info.class_name):
                    select_item = item
        self.tree.blockSignals(False)
        count = self.tree.topLevelItemCount()
        self.empty.setVisible(count == 0)
        if count == 0:
            self.empty.setText(tr("找不到符合的視窗。請先開啟遊戲或兌換網頁，再按「重新整理」。",
                                  "No matching window. Open the game or redeem page, then click Refresh."))
        if select_item is not None:
            self.tree.setCurrentItem(select_item)
        self._on_selection()

    def _info_for(self, item: QTreeWidgetItem | None) -> WindowInfo | None:
        if item is None:
            return None
        n = item.data(0, ROLE_INDEX)
        if isinstance(n, int) and 0 <= n < len(self._windows):
            return self._windows[n]
        return None

    def _on_selection(self) -> None:
        items = self.tree.selectedItems()
        info = self._info_for(items[0]) if items else None
        if info is not None and is_forbidden_window(info):
            info = None
        self._selected = info
        self.ok_btn.setEnabled(info is not None)
        if info is None:
            self.detail.setText("")
            return
        cw, ch = info.client[2], info.client[3]
        lines = [tr(f"程式：{info.exe_path or info.exe_name}", f"Program: {info.exe_path or info.exe_name}"),
                 tr(f"視窗類別：{info.class_name or '—'} · 內容區大小：{cw} × {ch}",
                    f"Window class: {info.class_name or '-'} · client size: {cw} × {ch}")]
        if self._perms.get(info.hwnd) == "blocked_elevated":
            lines.append(elevated_text())
        self.detail.setText("\n".join(lines))

    # -- actions --------------------------------------------------------------------------
    def select_hwnd(self, hwnd: int) -> bool:
        """Select the list row of ``hwnd`` (tests and the crosshair); False if not listed."""
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            info = self._info_for(item)
            if info is not None and info.hwnd == hwnd and not is_forbidden_window(info):
                self.tree.setCurrentItem(item)
                return True
        return False

    def _accept_selected(self) -> None:
        if self._selected is not None:
            self.accept()

    def _pick_on_screen(self) -> None:
        from . import overlays

        hide = [self]
        parent = self.parentWidget()
        while parent is not None:
            hide.append(parent.window())
            parent = parent.window().parentWidget()
        try:
            res = overlays.pick("window", instruction=tr("點一下目標視窗", "Click the target window"), hide_windows=hide)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("window pick failed: %s", exc)
            res = None
        self.raise_()
        self.activateWindow()
        if res is None or not res.hwnd:
            return
        info = None
        try:
            from ..win32 import windows as win

            info = win.window_info(res.hwnd)
        except Exception as exc:
            log.debug("window_info unavailable: %s", exc)
        if info is None:
            info = next((i for i in self._windows if i.hwnd == res.hwnd), None)
        if info is None:
            w.message(self, tr("選擇目標視窗", "Choose the target window"),
                      tr("無法讀取這個視窗，請改從清單選擇。", "This window cannot be read; pick it from the list."),
                      "warning")
            return
        if is_forbidden_window(info):
            w.message(self, tr("選擇目標視窗", "Choose the target window"), forbidden_text(info.exe_name), "warning")
            return
        if not self.select_hwnd(info.hwnd):
            self._windows.insert(0, info)
            self._perms[info.hwnd] = input_permission_of(info.hwnd)
            self._fill()
            self.select_hwnd(info.hwnd)
        self._selected = info
        self.accept()

    def selected(self) -> WindowInfo | None:
        return self._selected


def pick_target_window(ctx: AppContext, current: TargetMatch | None = None,
                       parent: QWidget | None = None, suggested_exe: str = "") -> WindowInfo | None:
    """Modal convenience wrapper; None when cancelled."""
    dlg = WindowPickerDialog(ctx, current, parent, suggested_exe=suggested_exe)
    try:
        if dlg.exec() == QDialog.DialogCode.Accepted:
            return dlg.selected()
        return None
    finally:
        dlg.deleteLater()


__all__ = ["WindowPickerDialog", "elevated_text", "forbidden_text", "input_permission_of", "is_forbidden_window",
           "pick_target_window"]

