# OWNED BY G7
"""Target-window picker: list of win32.windows.list_windows() (exe icon via
QFileIconProvider, title, exe name, 「系統管理員」 badge when elevation.input_permission is
BLOCKED_ELEVATED, 「可能無法輸入」 when UNKNOWN - warning badges in the warning colour), search,
refresh, and 「點選視窗」 (overlays.pick "window" crosshair). Windows of
models.FORBIDDEN_TARGET_EXES are shown disabled with 「系統程式，不能當目標」; the profile's
``suggested_exe`` (imports) is listed first and marked 「建議」 in the program column. When the
selected window runs as administrator and this user can elevate, the button
「以系統管理員身分重新啟動」 appears at the bottom left (run_actions.restart_as_admin_flow).
Returns the chosen WindowInfo; the caller stores info.to_target() (browser targets keep the title
keyword it contains; the user may shorten it, but not to empty)."""

from __future__ import annotations

import logging

from PyQt6.QtCore import QFileInfo, QSize, Qt
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
from . import icons, theme
from . import widgets as w

log = logging.getLogger(__name__)

ROLE_INDEX = Qt.ItemDataRole.UserRole + 1
ROW_H = 36  # list row height, set on the items (the QSS item min-height does not reach these rows)


def elevated_text() -> str:
    """SPEC 7.1 'target elevated' text (the pre-flight list, whose row has that button)."""
    return tr("目標程式以系統管理員權限執行，Windows 會無聲阻擋一般權限程式的模擬輸入。"
              "請按「以系統管理員身分重新啟動」。",
              "The target runs as administrator; Windows silently blocks simulated input from normal "
              "programs. Click \"Restart as administrator\".")


def can_elevate() -> bool:
    """This Windows account can restart AutoPress as administrator (a consent prompt);
    False when the win32 layer cannot tell."""
    try:
        from ..win32 import elevation

        return bool(elevation.can_elevate())
    except Exception as exc:
        log.debug("can_elevate unavailable: %s", exc)
        return False


def _restart_label() -> str:
    from .run_actions import action_label

    return action_label("restart_admin")


def _standard_user_text() -> str:
    from ..runner import messages  # the pre-flight wording for the same case

    return messages.pf_target_elevated_standard_user()


def elevated_picker_text(elevate: bool | None = None) -> str:
    """The picker's text for a window that runs as administrator: names the button at the
    bottom left of the picker (it appears while such a window is selected); for an account
    that cannot elevate, the standard-user advice instead (no button)."""
    if not (can_elevate() if elevate is None else elevate):
        return _standard_user_text()
    return tr("目標程式以系統管理員權限執行，Windows 會無聲阻擋一般權限程式的模擬輸入。"
              f"選取這個視窗後，按左下角的「{_restart_label()}」。",
              "The target runs as administrator; Windows silently blocks simulated input from normal programs. "
              f"Select this window, then click \"{_restart_label()}\" at the bottom left.")


def elevated_card_text(elevate: bool | None = None) -> str:
    """The same for the Profiles target card, which has no restart button: points to
    「選擇視窗…」, whose list offers it."""
    if not (can_elevate() if elevate is None else elevate):
        return _standard_user_text()
    return tr("目標程式以系統管理員權限執行，Windows 會無聲阻擋一般權限程式的模擬輸入。"
              f"請按「選擇視窗…」，再按「{_restart_label()}」。",
              "The target runs as administrator; Windows silently blocks simulated input from normal programs. "
              f"Click \"Choose window…\", then \"{_restart_label()}\".")


def unknown_badge() -> str:
    """Badge for a window whose privileges cannot be read (UNKNOWN): what it means for the user."""
    return tr("可能無法輸入", "Input may be blocked")


def unknown_text() -> str:
    """Tooltip of :func:`unknown_badge` (the pre-flight wording, SPEC 7.1 'elevation unknown')."""
    from ..runner import messages

    return messages.pf_elevation_unknown()


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
                 suggested_exe: str = "", caption: str = "") -> None:
        """``caption``: a small line above the title, e.g. the setup wizard's 「設定精靈 1/5」."""
        super().__init__(parent)
        self.ctx = ctx
        self.current = current
        self.suggested_exe = (suggested_exe or "").strip()
        self._windows: list[WindowInfo] = []
        self._perms: dict[int, str] = {}
        self._selected: WindowInfo | None = None
        self._icons = QFileIconProvider()
        self._icon_cache: dict[str, QIcon] = {}
        self._can_elevate = can_elevate()
        self.setWindowTitle(tr("選擇目標視窗", "Choose the target window"))
        self.setMinimumSize(720, 480)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)
        head = QVBoxLayout()
        head.setSpacing(2)
        self.caption = w.label(caption, "caption")
        self.caption.setVisible(bool(caption))
        head.addWidget(self.caption)
        head.addWidget(w.label(tr("選擇要自動輸入序號的遊戲或兌換網頁視窗", "Pick the game or redeem-page window"),
                               "title"))
        lay.addLayout(head)
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
        self.tree.setIconSize(QSize(16, 16))
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
        # the button elevated_picker_text() points to (U24); shown while such a window is selected
        self.restart_btn = w.push_button(_restart_label(), "secondary", "shield")
        self.restart_btn.setToolTip(tr("Windows 會詢問是否允許；重新啟動後再選一次這個視窗。",
                                       "Windows asks for permission; pick this window again after the restart."))
        self.restart_btn.clicked.connect(self._restart_as_admin)
        self.restart_btn.hide()
        btns.addWidget(self.restart_btn)
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
            warn = False  # a badge that can stop the input: warning colour + icon
            forbidden = is_forbidden_window(info)
            if forbidden:
                badges.append(tr("系統程式，不能當目標", "System program, cannot be the target"))
                tip = forbidden_text(info.exe_name)
            else:
                perm = self._perms.get(info.hwnd, "ok")
                if perm == "blocked_elevated":
                    badges.append(tr("系統管理員", "Administrator"))
                    tip, warn = elevated_picker_text(self._can_elevate), True
                elif perm == "unknown":
                    badges.append(unknown_badge())
                    tip, warn = unknown_text(), True
            if info.minimized:
                badges.append(tr("已最小化", "Minimized"))
            program = info.exe_name or "?"
            suggested = bool(self.suggested_exe) and info.exe_name.casefold() == self.suggested_exe.casefold()
            if suggested:  # a recommendation, kept apart from the warning badges (U40)
                program = tr(f"{program} · 建議", f"{program} · suggested")
            item = QTreeWidgetItem([info.title or tr("（無標題）", "(no title)"), program, " · ".join(badges)])
            item.setIcon(0, self._icon(info.exe_path))
            item.setData(0, ROLE_INDEX, n)
            item.setSizeHint(0, QSize(0, ROW_H))  # uniform rows: the first row sets every row's height
            title_tip = info.title + (tr(f"\n視窗類別：{info.class_name}", f"\nWindow class: {info.class_name}")
                                      if info.class_name else "")
            item.setToolTip(0, f"{title_tip}\n{tip}" if tip else title_tip)
            if tip:
                for col in (1, 2):
                    item.setToolTip(col, tip)
            if suggested:
                item.setForeground(1, theme.color("accent_text"))
            if warn:
                item.setForeground(2, theme.color("warning_text"))
                item.setIcon(2, icons.icon("alert", "warning", 16))
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
        elevated = info is not None and self._perms.get(info.hwnd) == "blocked_elevated"
        self.restart_btn.setVisible(elevated and self._can_elevate)
        if info is None:
            self.detail.setText("")
            return
        cw, ch = info.client[2], info.client[3]
        # the window class is a developer detail: it is in the title cell's tooltip (U30)
        lines = [tr(f"程式：{info.exe_path or info.exe_name}", f"Program: {info.exe_path or info.exe_name}"),
                 tr(f"內容區大小：{cw} × {ch}", f"Client area: {cw} × {ch}")]
        if elevated:
            lines.append(elevated_picker_text(self._can_elevate))
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

    def _restart_as_admin(self) -> None:
        """「以系統管理員身分重新啟動」: the same confirmation and restart as the pre-flight button."""
        from . import run_actions

        run_actions.restart_as_admin_flow(self, self.ctx)

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
                       parent: QWidget | None = None, suggested_exe: str = "", caption: str = "") -> WindowInfo | None:
    """Modal convenience wrapper; None when cancelled. ``caption``: see WindowPickerDialog."""
    dlg = WindowPickerDialog(ctx, current, parent, suggested_exe=suggested_exe, caption=caption)
    try:
        if dlg.exec() == QDialog.DialogCode.Accepted:
            return dlg.selected()
        return None
    finally:
        dlg.deleteLater()


__all__ = ["WindowPickerDialog", "can_elevate", "elevated_card_text", "elevated_picker_text", "elevated_text",
           "forbidden_text", "input_permission_of", "is_forbidden_window", "pick_target_window", "unknown_badge",
           "unknown_text"]

