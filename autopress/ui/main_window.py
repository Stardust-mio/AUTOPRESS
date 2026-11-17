# OWNED BY G5
"""Main window shell: 220 px sidebar (logo, 序號 / 設定檔 / 執行 / 紀錄, bottom 設定 / 說明),
QStackedWidget of pages, always-on status bar, toasts (SPEC section 6.3).

Pages are built in PAGE_IDS order; a page whose constructor raises NotImplementedError becomes a
「尚未實作」 placeholder (``page()`` returns None for it), any other error an 「此頁面無法載入」
placeholder (logged), so one broken page never takes the whole app down. The sidebar and the
status bar live in shell_sidebar.py / shell_statusbar.py.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Callable

from PyQt6.QtCore import QByteArray, QTimer
from PyQt6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QMainWindow, QStackedWidget, QVBoxLayout, QWidget

from .. import APP_NAME, paths
from ..context import PAGE_IDS, AppContext
from ..i18n import format_count, tr
from ..models import CodeStatus, Profile, RunState, ThemeName
from . import icons, theme
from .shell_common import change_theme, failsafe_corner_text, open_folder
from .shell_sidebar import Sidebar
from .shell_statusbar import StatusBar
from .toast import ToastManager
from .widgets import Banner, EmptyState, push_button

log = logging.getLogger(__name__)

PAGE_CLASSES: dict[str, tuple[str, str]] = {
    "codes": ("autopress.ui.codes_page", "CodesPage"),
    "profiles": ("autopress.ui.profiles_page", "ProfilesPage"),
    "run": ("autopress.ui.run_page", "RunPage"),
    "history": ("autopress.ui.history_page", "HistoryPage"),
    "settings": ("autopress.ui.settings_page", "SettingsPage"),
    "help": ("autopress.ui.help_page", "HelpPage"),
}
MIN_SIZE = (1100, 700)
DEFAULT_SIZE = (1280, 800)
TARGET_REFRESH_MS = 2000
_OCR_TEXT = {
    "not_started": (("文字辨識：未啟動", "OCR: not started"), "neutral"),
    "loading": (("文字辨識：載入中", "OCR: loading"), "info"),
    "ready": (("文字辨識：就緒", "OCR: ready"), "success"),
    "failed": (("文字辨識：無法使用", "OCR: unavailable"), "error"),
    "disabled": (("文字辨識：已關閉", "OCR: off"), "neutral"),
}


def _request_quit() -> None:
    """Quit the application after the current event (tests replace this)."""
    app = QApplication.instance()
    if app is not None:
        QTimer.singleShot(0, app.quit)


def _fmt_s(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


class _PlaceholderPage(QWidget):
    """「尚未實作」 (stub page) or 「此頁面無法載入」 (constructor error)."""

    def __init__(self, page_id: str, error: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.page_id = page_id
        self.error = error
        lay = QVBoxLayout(self)
        lay.setContentsMargins(*theme.PAGE_MARGINS)
        if error:
            btn = push_button(tr("開啟紀錄資料夾", "Open log folder"), "secondary", "folder")
            btn.clicked.connect(lambda: open_folder(paths.logs_dir()))
            state = EmptyState("alert", tr("此頁面無法載入", "This page could not be loaded"),
                               tr("發生未預期的錯誤，已記錄在紀錄檔。", "An unexpected error occurred and was logged."),
                               [btn], parent=self)
        else:
            state = EmptyState("flask", tr("尚未實作", "Not implemented yet"),
                               tr("這個頁面還在製作中。", "This page is still being built."), parent=self)
        lay.addWidget(state)


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext) -> None:
        """Builds the pages: CodesPage(ctx), ProfilesPage(ctx), RunPage(ctx), HistoryPage(ctx),
        SettingsPage(ctx), HelpPage(ctx). A page whose constructor raises NotImplementedError
        is replaced by a "尚未實作 / Not implemented yet" placeholder. Connects
        ctx.signals.navigate, sets ctx.main_window, attaches ctx.hotkeys to its winId().
        closeEvent quits the application explicitly (the app does not quit on the last window,
        T02); during a run it asks first and then calls ctx.session.stop() before quitting."""
        super().__init__()
        self.ctx = ctx
        ctx.main_window = self
        self._closing = False
        self._run_mode = False
        self._saved_geometry: QByteArray | None = None
        self._profile: Profile | None = None
        self._run_progress = ""
        self._unsubscribe: list[Callable[[], object]] = []
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(icons.app_icon())
        self.setMinimumSize(*MIN_SIZE)
        self.resize(*DEFAULT_SIZE)

        root = QWidget(self)
        root.setObjectName("Root")
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self.sidebar = Sidebar(theme.current_theme() == "dark", root)
        self.sidebar.pageRequested.connect(self.navigate)
        self.sidebar.themeToggled.connect(self._on_theme_toggled)
        h.addWidget(self.sidebar)
        right = QWidget(root)
        right.setObjectName("Main")
        col = QVBoxLayout(right)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        self.banner_area = QWidget(right)
        self._banner_lay = QVBoxLayout(self.banner_area)
        self._banner_lay.setContentsMargins(theme.PAGE_MARGINS[0], theme.SP[3], theme.PAGE_MARGINS[2], 0)
        self._banner_lay.setSpacing(theme.SP[2])
        self.banner_area.hide()
        col.addWidget(self.banner_area)
        self.stack = QStackedWidget(right)
        col.addWidget(self.stack, 1)
        self.status_bar = StatusBar(right)
        col.addWidget(self.status_bar)
        h.addWidget(right, 1)
        self.setCentralWidget(root)
        self.toasts = ToastManager(root)
        self.toasts.attach_signals(ctx.signals)

        self._pages: dict[str, QWidget] = {}
        self._real: dict[str, bool] = {}
        for page_id in PAGE_IDS:
            widget, real = self._build_page(page_id)
            self._pages[page_id] = widget
            self._real[page_id] = real
            self.stack.addWidget(widget)
        self._current = ""

        ctx.signals.navigate.connect(self.navigate)
        ctx.signals.theme_changed.connect(self._on_theme_changed)
        try:  # "system" theme: the OS switched dark / light (theme re-applies itself first)
            QApplication.styleHints().colorSchemeChanged.connect(
                lambda *_a: QTimer.singleShot(0, self._sync_theme_switch))
        except (AttributeError, RuntimeError):
            pass
        ctx.signals.settings_changed.connect(self._on_settings_changed)
        ctx.signals.profiles_changed.connect(self._on_profiles_changed)
        ctx.signals.active_profile_changed.connect(self._on_profiles_changed)
        self._connect_services()
        self._shortcuts()
        self._startup_banners()
        self._restore_geometry()
        try:
            ctx.hotkeys.attach(int(self.winId()))
        except Exception:  # noqa: BLE001 - G3 must not raise on an invalid handle; never block the UI
            log.exception("attaching the hotkeys failed")

        self._target_timer = QTimer(self)
        self._target_timer.setInterval(TARGET_REFRESH_MS)
        self._target_timer.timeout.connect(self._refresh_target)
        self._target_timer.start()
        self._on_profiles_changed()
        self._on_settings_changed(ctx.settings)
        self._refresh_badges()
        self.navigate(str(ctx.extras.pop("start_page", "") or "codes"))

    # -- pages ----------------------------------------------------------------------------
    def _build_page(self, page_id: str) -> tuple[QWidget, bool]:
        modname, cls_name = PAGE_CLASSES[page_id]
        try:
            cls = getattr(importlib.import_module(modname), cls_name)
            return cls(self.ctx), True
        except NotImplementedError:
            log.info("page %s is not implemented yet", page_id)
            return _PlaceholderPage(page_id), False
        except Exception:  # noqa: BLE001 - one broken page must not stop the app
            log.exception("building page %s failed", page_id)
            return _PlaceholderPage(page_id, error=True), False

    def navigate(self, page_id: str) -> None:
        """Show a page from context.PAGE_IDS (unknown ids are ignored)."""
        if page_id not in self._pages:
            log.debug("navigate: unknown page %r", page_id)
            return
        self._current = page_id
        self.stack.setCurrentWidget(self._pages[page_id])
        self.sidebar.set_current(page_id)
        # the shown page may look the window up right now (the Run page does on show): the status
        # bar looks too, so both say the same instead of the status bar lagging up to 2 s (U6)
        self._refresh_target()

    def current_page(self) -> str:
        return self._current

    def page(self, page_id: str) -> QWidget | None:
        """The page widget, or None for unknown ids and for 「尚未實作」 placeholders."""
        if not self._real.get(page_id):
            return None
        return self._pages.get(page_id)

    def is_placeholder(self, page_id: str) -> bool:
        """Extra: True when ``page_id`` shows a placeholder."""
        return page_id in self._pages and not self._real.get(page_id, False)

    # -- badges / status ------------------------------------------------------------------
    def set_badge(self, page_id: str, text: str, tooltip: str = "") -> None:
        """Count pill on a sidebar item ("" hides it); ``tooltip`` says what the number counts."""
        self.sidebar.set_badge(page_id, text, tooltip)

    def set_status(self, key: str, text: str, tone: str = "neutral", tooltip: str | None = None) -> None:
        """Status-bar item: key "target" | "ocr" | "guard" | "interval" | "run" (G5 creates them);
        also "failsafe", "version" (the sidebar's version line) and any new key (added on the
        right). "" hides an item."""
        if key == "version":
            self.sidebar.version_label.setText(text)
            return
        if key == "hotkeys":
            parts = [p.strip() for p in text.split("|")]
            if len(parts) == 2:
                self.status_bar.hotkeys.set_combos(parts[0], parts[1])
            return
        self.status_bar.item(key).set(text, tone, tooltip)

    def status_text(self, key: str) -> str:
        """Extra (tests): the text of a status-bar item."""
        if key == "version":
            return self.sidebar.version_label.text()
        it = self.status_bar.items.get(key)
        return it.text() if it is not None else ""

    def _connect_services(self) -> None:
        ctx = self.ctx
        try:
            ctx.ocr.state_changed.connect(self._on_ocr_state)
            self._on_ocr_state(str(getattr(ctx.ocr.state, "value", ctx.ocr.state)))
        except Exception:  # noqa: BLE001 - OCR service stub: leave the item empty
            log.debug("OCR status unavailable", exc_info=True)
        try:
            ctx.session.state_changed.connect(self._on_run_state)
            ctx.session.progress.connect(self._on_run_progress)
        except Exception:  # noqa: BLE001
            log.debug("run status unavailable", exc_info=True)
        for store in (ctx.queue, ctx.history):
            try:
                self._unsubscribe.append(store.subscribe(lambda *_a: self._schedule_badges()))
            except Exception:  # noqa: BLE001 - store stub
                log.debug("store subscription unavailable", exc_info=True)
        unsubs = self._unsubscribe
        self.destroyed.connect(lambda *_a, u=unsubs: [f() for f in u])
        self._badge_timer = QTimer(self)
        self._badge_timer.setSingleShot(True)
        self._badge_timer.setInterval(0)
        self._badge_timer.timeout.connect(self._refresh_badges)

    def _schedule_badges(self) -> None:
        try:
            self._badge_timer.start()
        except RuntimeError:  # window already deleted
            pass

    def _refresh_badges(self) -> None:
        """Sidebar count pills (SPEC 6.3): 序號 = codes still to do (runnable + review), 設定檔 and
        紀錄 = totals. Each pill's tooltip says what its number counts (UI review U43)."""
        ctx = self.ctx
        try:
            counts = ctx.queue.counts()
            todo = [(s, int(counts.get(s, 0) or 0))
                    for s in (CodeStatus.PENDING, CodeStatus.COOLDOWN, CodeStatus.REVIEW)]
            n = sum(c for _s, c in todo)
            tip = ""
            if n:
                detail = tr("、", ", ").join(f"{s.label()} {c}" for s, c in todo if c)
                tip = tr("待處理的序號 {count}：{detail}", "{count} to do: {detail}").format(
                    count=format_count(n), detail=detail)
            self.set_badge("codes", str(n) if n else "", tip)
        except Exception:  # noqa: BLE001
            log.debug("codes badge unavailable", exc_info=True)
        try:
            n = len(ctx.profiles.list())
            self.set_badge("profiles", str(n) if n else "",
                           tr("共 {count}", "{count}").format(count=format_count(n, "個設定檔", "profile")) if n else "")
        except Exception:  # noqa: BLE001
            log.debug("profiles badge unavailable", exc_info=True)
        try:
            n = len(ctx.history.records())
            self.set_badge("history", (str(n) if n < 10000 else "9999+") if n else "",
                           tr("共 {count}", "{count}").format(count=format_count(n, "筆紀錄", "history record"))
                           if n else "")
        except Exception:  # noqa: BLE001
            log.debug("history badge unavailable", exc_info=True)

    def _on_ocr_state(self, state: str) -> None:
        (zh_en, tone) = _OCR_TEXT.get(str(state), _OCR_TEXT["not_started"])
        tip = None
        if state == "failed":
            reason = ""
            try:
                reason = self.ctx.ocr.error
            except Exception:  # noqa: BLE001
                pass
            tip = tr(f"文字辨識引擎無法啟動：{reason}。請重新下載完整的壓縮檔並解壓縮，或檢查防毒軟體是否隔離了檔案。",
                     f"The OCR engine could not start: {reason}. Download and unzip the full package again, "
                     "or check whether antivirus quarantined files.")
        self.set_status("ocr", tr(*zh_en), tone, tip if tip is not None else "")

    def _on_run_state(self, state: str, reason: str) -> None:
        try:
            st = RunState(state)
        except ValueError:
            return
        if st in (RunState.IDLE, RunState.FINISHED):
            self._run_progress = ""
            self.set_status("run", "")
            return
        tone = {RunState.PAUSED: "warning", RunState.PAUSING: "warning", RunState.COOLDOWN: "info",
                RunState.STOPPING: "warning"}.get(st, "accent")
        text = st.label()
        if st is RunState.PAUSED and reason:
            from ..models import PauseReason

            try:
                text = f"{text}{tr('：', ': ')}{PauseReason(reason).label()}" if reason != "user" else text
            except ValueError:
                pass
        if self._run_progress and st in (RunState.RUNNING, RunState.COOLDOWN, RunState.PAUSING):
            text = f"{text} {self._run_progress}"
        self.set_status("run", text, tone)

    def _on_run_progress(self, done: int, total: int, _eta: float) -> None:
        self._run_progress = f"{done}/{total}" if total else ""
        try:
            state = self.ctx.session.state
            self._on_run_state(str(getattr(state, "value", state)), "")
        except Exception:  # noqa: BLE001
            pass

    def _on_settings_changed(self, settings: object) -> None:
        s = self.ctx.settings
        self.set_status("guard", tr("前景保護：開", "Guard: on"), "success",
                        tr("每次按鍵、點擊前都會確認目標視窗在最前面；不是就立刻暫停。",
                           "Before every key and click AutoPress checks that the target is in front; "
                           "otherwise it pauses."))
        self.status_bar.hotkeys.set_combos(s.hotkeys.pause_resume, s.hotkeys.stop)
        tip = failsafe_corner_text()
        if s.failsafe_enabled:
            self.set_status("failsafe", tr("左上角緊急停止：開", "Corner stop: on"), "success", tip)
        else:
            self.set_status("failsafe", tr("左上角緊急停止：關", "Corner stop: off"), "warning",
                            tr("已在設定中關閉；執行時請用停止快捷鍵。", "Turned off in Settings; use the stop hotkey."))

    def _on_profiles_changed(self, *_args: object) -> None:
        try:
            self._profile = self.ctx.active_profile()
        except Exception:  # noqa: BLE001
            self._profile = None
        p = self._profile
        if p is None:
            self.set_status("interval", tr("間隔 —", "Interval —"), "neutral",
                            tr("尚未選擇設定檔", "No profile selected"))
        else:
            a, b = p.policy.interval_min_s, p.policy.interval_max_s
            text = tr(f"間隔 {_fmt_s(a)}–{_fmt_s(b)} 秒", f"Interval {_fmt_s(a)}-{_fmt_s(b)} s")
            self.set_status("interval", text, "neutral", tr(f"設定檔「{p.name}」每筆序號之間的等待時間",
                                                            f"Wait between codes of profile '{p.name}'"))
        self._refresh_badges()
        self._refresh_target()

    def _refresh_target(self) -> None:
        """The target item states first whether the window was found, then names it: the item
        elides on the right, so a long window title never hides the state (UI review U7)."""
        if self._run_mode or not self.isVisible() and self._current:
            return
        p = self._profile
        if p is None:
            self.set_status("target", tr("目標視窗：未選擇設定檔", "Target: no profile"), "neutral", "")
            return
        if p.target.is_empty():
            self.set_status("target", tr("目標視窗：尚未設定", "Target: not set"), "warning", "")
            return
        try:
            from ..win32 import windows

            info = windows.find_window(p.target)
        except Exception:  # noqa: BLE001 - G3 stub or Win32 error: unknown, not an error
            log.debug("find_window failed", exc_info=True)
            self.set_status("target", tr("目標視窗：{target}", "Target: {target}").format(target=p.target.describe()),
                            "neutral", "")
            return
        if info is None:
            self.set_status("target", tr("找不到目標視窗", "Target window not found"), "warning",
                            tr("找不到目標視窗：{target}", "Target window not found: {target}").format(
                                target=p.target.describe()))
        else:
            title = info.title or info.exe_name
            self.set_status("target", tr("已找到目標視窗：{title}", "Target found: {title}").format(title=title),
                            "success", title)

    # -- theme ------------------------------------------------------------------------------
    def _on_theme_toggled(self, dark: bool) -> None:
        change_theme(self.ctx, ThemeName.DARK if dark else ThemeName.LIGHT)

    def _on_theme_changed(self, resolved: str) -> None:
        self.sidebar.set_dark(resolved == "dark")

    def _sync_theme_switch(self) -> None:
        try:
            self.sidebar.set_dark(theme.current_theme() == "dark")
        except RuntimeError:  # window already deleted
            pass

    # -- banners ----------------------------------------------------------------------------
    def add_banner(self, text: str, tone: str = "warning", action_text: str = "",
                   action: Callable[[], None] | None = None) -> Banner:
        """Extra: a closable banner above the pages (startup notices)."""
        b = Banner(tone, text, action_text, True, self.banner_area)
        if action is not None:
            b.actionClicked.connect(action)
        b.closed.connect(self._update_banner_area)
        self._banner_lay.addWidget(b)
        self.banner_area.show()
        return b

    def banners(self) -> list[Banner]:
        return [b for b in self.banner_area.findChildren(Banner) if not b.isHidden()]

    def _update_banner_area(self) -> None:
        self.banner_area.setVisible(bool(self.banners()))

    def _startup_banners(self) -> None:
        try:
            path, intended = paths.resolve_data_dir()
        except Exception:  # noqa: BLE001
            path, intended = None, None
        if intended is not None:
            self.add_banner(tr(f"無法寫入資料資料夾 {intended}，改用 {path}。",
                               f"Cannot write to {intended}; using {path}."), "warning")
        recovered = int(self.ctx.extras.pop("recovered", 0) or 0)
        if recovered:
            self.add_banner(tr(f"上次執行中斷：{recovered} 筆序號已標為「需確認」，請到序號頁檢查是否已兌換。",
                               f"The last run was interrupted: {recovered} codes are marked 'Needs review'; "
                               "check them on the Codes page."), "info", tr("前往序號頁", "Go to Codes"),
                            lambda: self.navigate("codes"))

    def show_crash_toast(self, _summary: str = "") -> None:
        """The crash notice (SPEC 7.1): never the raw exception text."""
        self.toasts.show_toast(tr("發生未預期的錯誤，已記錄在紀錄檔。", "An unexpected error occurred and was logged."),
                               "error", tr("開啟資料夾", "Open folder"), lambda: open_folder(paths.logs_dir()),
                               timeout_ms=8000)

    # -- keyboard -----------------------------------------------------------------------------
    def _shortcuts(self) -> None:
        for n, page_id in enumerate(PAGE_IDS, 1):
            sc = QShortcut(QKeySequence(f"Ctrl+{n}"), self)
            sc.activated.connect(lambda pid=page_id: self.navigate(pid))
        QShortcut(QKeySequence("F1"), self).activated.connect(lambda: self.navigate("help"))

    # -- geometry / run mode ------------------------------------------------------------------
    def _restore_geometry(self) -> None:
        hexstr = self.ctx.settings.window_geometry
        if hexstr:
            try:
                if self.restoreGeometry(QByteArray.fromHex(hexstr.encode("ascii"))):
                    return
            except (UnicodeEncodeError, ValueError):
                pass
        self.resize(*DEFAULT_SIZE)

    def geometry_hex(self) -> str:
        """The geometry to remember (the one saved before run mode while hidden)."""
        data = self._saved_geometry if (self._run_mode and self._saved_geometry is not None) else self.saveGeometry()
        return bytes(data.toHex()).decode("ascii")

    def remember_geometry(self) -> None:
        self.ctx.settings.window_geometry = self.geometry_hex()

    def set_run_mode(self, active: bool, minimize: bool = False) -> None:
        """True: remember geometry and hide (the mini bar takes over) - or, with ``minimize``,
        showMinimized() so the taskbar button stays (used when the mini bar is disabled);
        False: restore + raise (RunFlow does this for decisions during a paused run)."""
        if active:
            if not self._run_mode and self.isVisible() and not self.isMinimized():
                self._saved_geometry = self.saveGeometry()
            self._run_mode = True
            self.toasts.clear()
            if minimize:
                self.showMinimized()
            else:
                self.hide()
            return
        was = self._run_mode
        self._run_mode = False
        if self.isMinimized():
            self.showNormal()
        if not self.isVisible():
            if was and self._saved_geometry is not None:
                self.restoreGeometry(self._saved_geometry)
            self.show()
        self.raise_()
        self.activateWindow()

    def is_run_mode(self) -> bool:
        return self._run_mode

    # -- close ----------------------------------------------------------------------------------
    def closeEvent(self, event: QCloseEvent | None) -> None:
        if event is None:
            return
        if self._closing:
            event.accept()
            return
        profiles = self.page("profiles")  # unsaved profile edits: Save / Discard / Cancel (G7)
        maybe_leave = getattr(profiles, "maybe_leave", None)
        if callable(maybe_leave):
            try:
                if not maybe_leave():
                    event.ignore()
                    return
            except Exception:  # noqa: BLE001 - never block quitting on a page error
                log.exception("asking about unsaved profile changes failed")
        session = self.ctx.session
        active = False
        try:
            active = bool(session.is_active())
        except Exception:  # noqa: BLE001
            active = False
        if active:
            from . import widgets

            if not widgets.confirm(self, tr("要結束 AutoPress 嗎？", "Quit AutoPress?"),
                                   tr("正在兌換序號。結束前會先停止執行；目前這筆會標為待兌換或需確認。",
                                      "Codes are being redeemed. AutoPress stops the run first; the current "
                                      "code becomes pending or needs review."),
                                   tr("停止並結束", "Stop and quit"), tr("繼續執行", "Keep running"), danger=True):
                event.ignore()
                return
            try:
                session.stop()
            except Exception:  # noqa: BLE001
                log.exception("stopping the run failed")
        try:
            self.remember_geometry()
        except Exception:  # noqa: BLE001
            log.debug("remembering the geometry failed", exc_info=True)
        self._closing = True
        self._target_timer.stop()
        event.accept()
        _request_quit()
