"""G5: app entry - argument parsing, QApplication setup, quit-on-last-window-closed off, single
instance lock (incl. --wait-lock), --selftest before any QApplication, welcome before the main
window, crash toast, shutdown sequence, build_context with the real stores."""

from __future__ import annotations

import gc
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Any

import pytest
from PyQt6.QtCore import QEvent, QTimer
from PyQt6.QtWidgets import QApplication, QDialog

from autopress import logsetup, paths, storage
from autopress.models import Settings
from autopress.ui import app as app_mod
from autopress.ui import main_window as mw_mod
from autopress.ui import shell_style
from tests.fakes import skip_if_stub

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _free_widgets(qapp: QApplication):
    yield
    gc.collect()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


@pytest.fixture
def no_quit(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    calls: list[bool] = []
    monkeypatch.setattr(mw_mod, "_request_quit", lambda: calls.append(True))
    return calls


def test_parse_args() -> None:
    a = app_mod.parse_args(["--selftest", "r.json", "--wait-lock", "-x"])
    assert a == {"selftest": "r.json", "wait_lock": True, "rest": ["-x"]}
    assert app_mod.parse_args(["--selftest=out.json"])["selftest"] == "out.json"
    assert app_mod.parse_args([]) == {"selftest": None, "wait_lock": False, "rest": []}


def test_create_application_reuses_and_configures(qapp: QApplication) -> None:
    app = app_mod.create_application([])
    assert app is qapp
    assert app.quitOnLastWindowClosed() is False
    assert app.applicationName() == "AutoPress" and app.organizationName() == "AutoPress"
    assert app.font().pixelSize() == 13
    from autopress.ui import theme

    assert isinstance(theme._state["style"], shell_style.AppStyle)
    from autopress.ui.shell_common import install_translator

    assert install_translator(app, "zh-TW") is True  # qtbase_zh_TW ships with PyQt6
    assert install_translator(app, "en") is False


def test_closing_a_dialog_while_hidden_does_not_quit(qapp: QApplication, demo_ctx: Any, qtbot: Any,
                                                     no_quit: list[bool]) -> None:
    """T02: in run mode only Tool windows remain; closing a parentless dialog must not quit."""
    app = app_mod.create_application([])
    win = mw_mod.MainWindow(demo_ctx)
    qtbot.addWidget(win)
    win.show()
    win.set_run_mode(True)  # hidden

    def run_once(quit_on_last: bool) -> int:
        app.setQuitOnLastWindowClosed(quit_on_last)
        dlg = QDialog()
        dlg.show()
        closer, stopper = QTimer(), QTimer()  # owned timers: a pending exit() must never outlive this test
        for t, ms, fn in ((closer, 50, dlg.close), (stopper, 600, lambda: app.exit(42))):
            t.setSingleShot(True)
            t.timeout.connect(fn)
            t.start(ms)
        try:
            return app.exec()
        finally:
            closer.stop()
            stopper.stop()
            dlg.deleteLater()

    try:
        assert run_once(False) == 42  # the event loop kept running until our own exit
        assert run_once(True) != 42  # control: with the Qt default the app quits early
    finally:
        app.setQuitOnLastWindowClosed(False)


def test_instance_lock_in_process(isolated_home: Path) -> None:
    first = app_mod.acquire_instance_lock(0)
    assert first is not None and paths.lock_path().is_file()
    try:
        t0 = time.monotonic()
        assert app_mod.acquire_instance_lock(0) is None
        assert time.monotonic() - t0 < 2
    finally:
        first.unlock()
    again = app_mod.acquire_instance_lock(0)
    assert again is not None
    again.unlock()


HOLDER = textwrap.dedent("""
    import sys, time
    from PyQt6.QtCore import QLockFile
    lock = QLockFile(sys.argv[1])
    lock.setStaleLockTime(0)
    assert lock.tryLock(0)
    print("LOCKED", flush=True)
    time.sleep(float(sys.argv[2]))
    lock.unlock()
""")


@pytest.mark.slow
def test_wait_lock_takes_over_after_the_holder_exits(isolated_home: Path, clean_env: dict[str, str],
                                                    python_exe: str) -> None:
    lock_file = paths.lock_path()
    proc = subprocess.Popen([python_exe, "-c", HOLDER, str(lock_file), "2.0"], stdout=subprocess.PIPE,
                            env=clean_env, text=True, encoding="utf-8", errors="replace")
    try:
        assert proc.stdout is not None and proc.stdout.readline().strip() == "LOCKED"
        assert app_mod.acquire_instance_lock(0) is None  # another instance holds it
        t0 = time.monotonic()
        lock = app_mod.acquire_instance_lock(app_mod.LOCK_WAIT_MS)  # --wait-lock
        waited = time.monotonic() - t0
        assert lock is not None and 0.5 < waited < 9.0
        lock.unlock()
    finally:
        proc.wait(timeout=20)


def test_main_exits_when_already_running(monkeypatch: pytest.MonkeyPatch, qapp: QApplication,
                                         isolated_home: Path) -> None:
    calls: list[str] = []
    monkeypatch.setattr(logsetup, "setup_logging", lambda *a, **k: isolated_home / "x.log")
    monkeypatch.setattr(logsetup, "install_excepthook", lambda cb=None: calls.append("hook"))
    monkeypatch.setattr(app_mod, "_already_running", lambda: calls.append("already"))
    monkeypatch.setattr(app_mod, "_run", lambda *a: calls.append("run") or 0)
    holder = app_mod.acquire_instance_lock(0)
    assert holder is not None
    try:
        assert app_mod.main([]) == 1
        assert calls == ["hook", "already"]
    finally:
        holder.unlock()
    calls.clear()
    assert app_mod.main(["--wait-lock"]) == 0 and calls == ["hook", "run"]


SELFTEST_PROBE = textwrap.dedent("""
    import sys
    sys.path.insert(0, sys.argv[1])
    import autopress.selftest as st
    from PyQt6.QtWidgets import QApplication

    def fake_run(path):
        print("APP_NONE" if QApplication.instance() is None else "APP_EXISTS", path, flush=True)
        return 7

    st.run = fake_run
    import main
    rc = main.main(["--selftest", "report.json"])
    print("RC", rc)
    import os
    print("OPENBLAS", os.environ.get("OPENBLAS_NUM_THREADS"))
""")


def test_selftest_dispatched_before_qapplication(clean_env: dict[str, str], python_exe: str,
                                                 tmp_path: Path) -> None:
    env = dict(clean_env)
    env.pop("OPENBLAS_NUM_THREADS", None)
    env["QT_QPA_PLATFORM"] = "offscreen"
    out = subprocess.run([python_exe, "-c", SELFTEST_PROBE, str(ROOT)], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
                         cwd=str(tmp_path), timeout=120)
    assert out.returncode == 0, out.stderr
    lines = out.stdout.split("\n")
    assert "APP_NONE report.json" in lines and "RC 7" in lines and "OPENBLAS 1" in lines


def test_launchers_set_openblas_before_numpy(clean_env: dict[str, str], python_exe: str) -> None:
    env = dict(clean_env)
    env.pop("OPENBLAS_NUM_THREADS", None)
    code = ("import sys; sys.path.insert(0, sys.argv[1]); import main, autopress.__main__, os; "
            "print(os.environ.get('OPENBLAS_NUM_THREADS'), 'numpy' in sys.modules)")
    out = subprocess.run([python_exe, "-c", code, str(ROOT)], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=60)
    assert out.stdout.strip() == "1 False", out.stderr


def test_run_shows_welcome_before_main_window(monkeypatch: pytest.MonkeyPatch, qapp: QApplication, demo_ctx: Any,
                                              no_quit: list[bool]) -> None:
    from autopress.ui import welcome

    order: list[str] = []
    demo_ctx.settings.first_run_done = False
    monkeypatch.setattr(app_mod, "build_context", lambda app, settings=None: demo_ctx)

    def fake_exec_dialog(dlg: Any) -> int:
        order.append(f"welcome main_window={demo_ctx.main_window}")
        dlg._templates()  # the user clicks 「從範本建立設定檔」
        return 1

    monkeypatch.setattr(welcome, "_exec_dialog", fake_exec_dialog)
    real_init = mw_mod.MainWindow.__init__

    def spy_init(self: Any, ctx: Any) -> None:
        order.append("MainWindow")
        real_init(self, ctx)

    monkeypatch.setattr(mw_mod.MainWindow, "__init__", spy_init)
    windows: list[Any] = []
    monkeypatch.setattr(app_mod, "_exec", lambda app: windows.append(demo_ctx.main_window) or 0)
    started: list[bool] = []
    demo_ctx.ocr.start = lambda: started.append(True)
    reporter = app_mod.CrashReporter()
    assert app_mod._run(qapp, demo_ctx.settings, reporter) == 0
    assert order == ["welcome main_window=None", "MainWindow"]
    win = windows[0]
    assert win.isVisible() and win.current_page() == "profiles"  # the welcome choice
    assert storage.load_settings().first_run_done is True and started == [True]
    win.close()
    win.deleteLater()


def test_crash_reporter_shows_friendly_toast(monkeypatch: pytest.MonkeyPatch, demo_ctx: Any, qtbot: Any,
                                             no_quit: list[bool]) -> None:
    import threading

    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    win = mw_mod.MainWindow(demo_ctx)
    qtbot.addWidget(win)
    win.show()
    reporter = app_mod.CrashReporter()
    monkeypatch.setitem(app_mod._crash, "reporter", reporter)
    reporter.attach(win)
    logsetup.install_excepthook(app_mod._on_uncaught)
    try:
        raise ValueError("secret ABCD-1234")
    except ValueError as exc:
        sys.excepthook(type(exc), exc, exc.__traceback__)
    assert reporter.count == 1
    toast = win.toasts.toasts()[0]
    assert toast.text() == "發生未預期的錯誤，已記錄在紀錄檔。" and "ABCD" not in toast.text()
    assert toast.action_button is not None and toast.action_button.text() == "開啟資料夾"


def test_shutdown_sequence(monkeypatch: pytest.MonkeyPatch, demo_ctx: Any, qtbot: Any, no_quit: list[bool]) -> None:
    from autopress.win32 import input as win_input

    released: list[bool] = []
    monkeypatch.setattr(win_input, "release_all_modifiers", lambda *a, **k: released.append(True) or [])
    saved: list[bool] = []
    monkeypatch.setattr(demo_ctx.queue, "save", lambda: saved.append(True))
    ocr_down: list[bool] = []
    monkeypatch.setattr(demo_ctx.ocr, "shutdown", lambda timeout_s=2.0: ocr_down.append(True))
    demo_ctx.hotkeys.register("stop", "F9")
    win = mw_mod.MainWindow(demo_ctx)
    qtbot.addWidget(win)
    win.show()
    win.resize(1200, 760)
    app_mod.shutdown(demo_ctx, win)
    assert ("shutdown", ()) in demo_ctx.session.calls
    assert demo_ctx.hotkeys.registered() == {} and released == [True] and ocr_down == [True] and saved == [True]
    s = storage.load_settings()
    assert s.window_geometry and s.window_geometry == demo_ctx.settings.window_geometry


def test_shutdown_continues_after_a_failing_step(monkeypatch: pytest.MonkeyPatch, demo_ctx: Any) -> None:
    from autopress.win32 import input as win_input

    monkeypatch.setattr(win_input, "release_all_modifiers", lambda *a, **k: [])

    def boom(*a: object, **k: object) -> None:
        raise RuntimeError("session broken")

    monkeypatch.setattr(demo_ctx.session, "shutdown", boom)
    saved: list[bool] = []
    monkeypatch.setattr(demo_ctx.queue, "save", lambda: saved.append(True))
    app_mod.shutdown(demo_ctx, None)
    assert saved == [True]


SMOKE = textwrap.dedent("""
    import json, os, sys
    sys.path.insert(0, sys.argv[1])
    from autopress.win32 import input as win_input
    win_input.release_all_modifiers = lambda *a, **k: []  # never send any input from a test
    from PyQt6.QtCore import QTimer
    from autopress.ui import app, main_window
    real_init = main_window.MainWindow.__init__
    seen = {}

    def init(self, ctx):
        real_init(self, ctx)
        seen["pages"] = [p for p in ("codes", "profiles", "run", "history", "settings", "help")
                         if self.page(p) is not None]
        QTimer.singleShot(2500, self.close)  # the user closes the window

    main_window.MainWindow.__init__ = init
    rc = app.main([])
    print("RC", rc)
    print("PAGES", ",".join(seen.get("pages", [])))
""")


@pytest.mark.slow
def test_app_main_smoke_with_real_services(clean_env: dict[str, str], python_exe: str, tmp_path: Path) -> None:
    """main() end to end on the offscreen platform with every real service: start, show, quit by
    closing the window, shutdown (settings + geometry saved, log written, lock released)."""
    skip_if_stub("autopress.codes.queue", "autopress.codes.history", "autopress.ocr.service",
                 "autopress.runner.engine", "autopress.win32.hotkeys")
    home = tmp_path / "home 資料"
    env = dict(clean_env)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["AUTOPRESS_HOME"] = str(home)
    out = subprocess.run([python_exe, "-c", SMOKE, str(ROOT)], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
                         cwd=str(tmp_path), timeout=180)
    assert "RC 0" in out.stdout.split("\n"), out.stdout + out.stderr
    pages = next(line for line in out.stdout.split("\n") if line.startswith("PAGES")).split(" ", 1)[-1]
    assert "settings" in pages and "help" in pages
    settings = storage.read_json(home / "settings.json", {})
    assert settings.get("first_run_done") is True and settings.get("window_geometry")
    log_text = (home / "logs" / "autopress.log").read_text(encoding="utf-8")
    assert "AutoPress stopped" in log_text
    assert not (home / "instance.lock").exists()


def test_build_context_with_real_stores(qapp: QApplication, isolated_home: Path) -> None:
    skip_if_stub("autopress.codes.queue", "autopress.codes.history", "autopress.ocr.service",
                 "autopress.runner.engine", "autopress.win32.hotkeys")
    from autopress.codes.history import HistoryStore
    from autopress.codes.queue import CodeQueue
    from autopress.models import CodeItem, CodeStatus, to_dict

    storage.write_json(paths.queue_path(), {"schema_version": 1, "items": [
        to_dict(CodeItem(code="LEFTOVER1234", status=CodeStatus.RUNNING)),
        to_dict(CodeItem(code="PENDING5678")),
    ]})
    ctx = app_mod.build_context(qapp, Settings())
    try:
        assert isinstance(ctx.queue, CodeQueue) and isinstance(ctx.history, HistoryStore)
        assert ctx.extras.get("recovered") == 1
        items = {i.code: i for i in ctx.queue.items()}
        assert items["LEFTOVER1234"].status is CodeStatus.REVIEW
        assert str(getattr(ctx.ocr.state, "value", ctx.ocr.state)) in ("not_started", "disabled")  # not started
        assert ctx.profiles.directory == paths.profiles_dir()
        assert not ctx.session.is_active()
    finally:
        ctx.ocr.shutdown()
        ctx.session.shutdown()

