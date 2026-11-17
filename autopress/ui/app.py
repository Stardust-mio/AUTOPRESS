# OWNED BY G5
"""Application entry: process setup, QApplication, context wiring, shutdown (SPEC section 2.8).

Order (each step is a module-level function, so tests can replace one step):
1. ``--selftest <report.json>`` -> autopress.selftest.run (G8) BEFORE any QApplication exists;
2. logging + excepthook (crash toast 「發生未預期的錯誤，已記錄在紀錄檔。」 with 開啟資料夾);
3. settings + language, then ``create_application`` (per-monitor-v2 QApplication, Fusion, font,
   qtbase_zh_TW, ``setQuitOnLastWindowClosed(False)``) - before any capture / mss / dpi call;
4. single instance: ``QLockFile(paths.lock_path())`` (``--wait-lock``: tryLock(10000)), else
   「AutoPress 已在執行中。」 and exit 1;
5. theme, ``build_context`` (stores and services, created once), welcome dialog BEFORE the main
   window, ``MainWindow(ctx)``, show, OCR start;
6. ``aboutToQuit``: session.shutdown, hotkeys.unregister_all, input.release_all_modifiers,
   ocr.shutdown, settings (window geometry) and queue saved.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QLockFile, QObject, Qt, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QApplication

from .. import APP_ID, ORG_NAME, __version__, i18n, logsetup, paths, storage
from ..context import AppContext
from ..i18n import tr
from ..models import Settings

log = logging.getLogger(__name__)

LOCK_WAIT_MS = 10000  # --wait-lock (restart_as_admin hands over the lock, T32)


# =============================================================================== arguments


def parse_args(argv: Sequence[str]) -> dict[str, Any]:
    """{"selftest": report path or None, "wait_lock": bool, "rest": [other args]}."""
    out: dict[str, Any] = {"selftest": None, "wait_lock": False, "rest": []}
    args = list(argv)
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--selftest":
            out["selftest"] = args[i + 1] if i + 1 < len(args) else "selftest.json"
            i += 2
            continue
        if a.startswith("--selftest="):
            out["selftest"] = a.split("=", 1)[1] or "selftest.json"
        elif a == "--wait-lock":
            out["wait_lock"] = True
        else:
            out["rest"].append(a)
        i += 1
    return out


# =============================================================================== application


def create_application(argv: Sequence[str]) -> QApplication:
    """QApplication (BEFORE any capture / mss use; OPENBLAS_NUM_THREADS=1 is already set by
    main.py / __main__.py before anything imports numpy), app/org name = APP_ID, Fusion style,
    default font, Qt's qtbase_zh_TW translator when the language is zh-TW, and
    ``setQuitOnLastWindowClosed(False)``: during runs the main window is hidden and only Tool
    windows remain, so closing any dialog would otherwise quit the app mid-run (measured, T02).
    The app quits explicitly from MainWindow.closeEvent (and the tray-less exit paths).
    An existing QApplication (tests, the self-test) is reused and configured the same way."""
    from . import icons, theme
    from .shell_common import install_translator

    app = QApplication.instance()
    if app is None:
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
        app = QApplication([sys.argv[0] if sys.argv else "AutoPress", *list(argv)])
    assert isinstance(app, QApplication)
    app.setApplicationName(APP_ID)
    app.setOrganizationName(ORG_NAME)
    app.setApplicationVersion(__version__)
    theme.install_style(app)
    app.setFont(theme.font(theme.FS_BODY))
    app.setWindowIcon(icons.app_icon())
    install_translator(app, i18n.get_language())
    app.setQuitOnLastWindowClosed(False)
    return app


def acquire_instance_lock(wait_ms: int = 0, path: Path | None = None) -> QLockFile | None:
    """The single-instance lock (``paths.lock_path()``), or None when another AutoPress holds
    it. Age-based staleness is off (a running instance's lock never expires); a lock left by a
    crashed process is detected by its dead PID and taken over."""
    lock = QLockFile(str(path or paths.lock_path()))
    lock.setStaleLockTime(0)
    if lock.tryLock(max(0, int(wait_ms))):
        return lock
    log.info("instance lock busy (%s)", lock.error())
    return None


def build_context(app: QApplication, settings: Settings | None = None) -> AppContext:
    """Create stores and services (ProfileStore, CodeQueue.load + recover_after_crash,
    HistoryStore.load + prune_evidence, OcrService, RunSession, GlobalHotkeys) and return the
    AppContext. Does not start OCR or show windows. Services are never replaced later."""
    from ..codes.history import HistoryStore
    from ..codes.queue import CodeQueue
    from ..ocr.service import OcrService
    from ..runner.engine import RunSession
    from ..win32.hotkeys import GlobalHotkeys

    settings = settings if settings is not None else storage.load_settings()
    profiles = storage.ProfileStore()
    queue = CodeQueue(paths.queue_path())
    queue.load()
    recovered = queue.recover_after_crash()
    history = HistoryStore(paths.history_path())
    history.load()
    if settings.evidence_keep_days > 0:
        try:
            pruned = history.prune_evidence(settings.evidence_keep_days)
            if pruned:
                log.info("pruned %d evidence files older than %d days", pruned, settings.evidence_keep_days)
        except OSError as exc:
            log.warning("pruning evidence failed: %s", exc)
    ocr = OcrService(settings.ocr, parent=app)
    session = RunSession(queue, history, ocr, parent=app)
    hotkeys = GlobalHotkeys(app)
    ctx = AppContext(settings=settings, profiles=profiles, queue=queue, history=history, ocr=ocr,
                     session=session, hotkeys=hotkeys)
    if recovered:
        ctx.extras["recovered"] = int(recovered)
    return ctx


# =============================================================================== crash reporting


class CrashReporter(QObject):
    """Thread-safe bridge from logsetup.install_excepthook to the UI: ``crashed(summary)`` is
    delivered on the GUI thread; the main window shows the crash toast (never the raw text)."""

    crashed = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.count = 0

    def report(self, summary: str) -> None:
        """excepthook callback (any thread)."""
        self.count += 1
        self.crashed.emit(summary)

    def attach(self, window: object) -> None:
        show = getattr(window, "show_crash_toast", None)
        if callable(show):
            self.crashed.connect(show)


_crash: dict[str, CrashReporter | None] = {"reporter": None}


def _on_uncaught(summary: str) -> None:
    reporter = _crash["reporter"]
    if reporter is not None:
        reporter.report(summary)


# =============================================================================== shutdown


def shutdown(ctx: AppContext, window: object | None = None) -> None:
    """``aboutToQuit`` (SPEC 2.8 step 8). Every step runs even when an earlier one fails."""

    def step(name: str, fn: Any) -> None:
        try:
            fn()
        except Exception:  # noqa: BLE001 - the remaining steps must still run
            log.exception("shutdown step %s failed", name)

    step("session", lambda: ctx.session.shutdown())
    step("hotkeys", lambda: ctx.hotkeys.unregister_all())

    def release() -> None:
        from ..win32 import input as win_input

        win_input.release_all_modifiers()

    step("modifiers", release)
    step("ocr", lambda: ctx.ocr.shutdown())
    if window is not None and hasattr(window, "remember_geometry"):
        step("geometry", window.remember_geometry)
    step("settings", lambda: storage.save_settings(ctx.settings))
    step("queue", lambda: ctx.queue.save())
    log.info("AutoPress stopped")


# =============================================================================== main


def _exec(app: QApplication) -> int:
    return app.exec()


def _already_running() -> None:
    from . import widgets

    widgets.message(None, "AutoPress", tr("AutoPress 已在執行中。", "AutoPress is already running."), "info")


def main(argv: Sequence[str] | None = None) -> int:
    """Start AutoPress; returns the exit code (SPEC 2.8). ``--selftest <report.json>`` is
    dispatched FIRST - before create_application - to autopress.selftest.run(report) (G8; it
    creates or reuses the QApplication itself). ``--wait-lock`` (from restart_as_admin) waits
    up to 10 s for the single-instance lock (``QLockFile.tryLock(10000)``)."""
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    if args["selftest"] is not None:
        from .. import selftest

        return int(selftest.run(str(args["selftest"])))

    log_file = logsetup.setup_logging()
    logsetup.install_excepthook(_on_uncaught)
    log.info("AutoPress %s starting (log %s)", __version__, log_file)
    settings = storage.load_settings()
    i18n.set_language(settings.language.value)
    app = create_application(args["rest"])
    reporter = CrashReporter(app)
    _crash["reporter"] = reporter
    lock = acquire_instance_lock(LOCK_WAIT_MS if args["wait_lock"] else 0)
    if lock is None:
        _already_running()
        return 1
    try:
        return _run(app, settings, reporter)
    finally:
        lock.unlock()


def _run(app: QApplication, settings: Settings, reporter: CrashReporter) -> int:
    from . import main_window, theme, welcome

    theme.apply_theme(app, settings.theme)
    ctx = build_context(app, settings)
    ctx.signals.theme_changed.emit(theme.current_theme())
    welcome.show_welcome_if_needed(ctx, None)  # before the main window: a language picked there applies now
    window = main_window.MainWindow(ctx)
    reporter.attach(window)
    app.aboutToQuit.connect(lambda: shutdown(ctx, window))
    window.show()
    if ctx.settings.ocr.enabled:
        try:
            ctx.ocr.start()
        except Exception:  # noqa: BLE001 - the status bar shows the OCR state
            log.exception("starting OCR failed")
    return int(_exec(app))
