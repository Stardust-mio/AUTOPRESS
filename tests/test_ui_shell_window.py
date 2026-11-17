"""G5: MainWindow shell - navigation, placeholders, badges, status bar, run mode, close, banners,
toasts (stacking, run-mode drop, crash text)."""

from __future__ import annotations

import gc
from pathlib import Path
from typing import Any

import pytest
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLabel, QWidget

from autopress import paths
from autopress.context import PAGE_IDS
from autopress.models import CodeCandidate, CodeSource, CodeStatus, RunSelection, ThemeName, WindowInfo
from autopress.ui import main_window as mw_mod
from autopress.ui import theme
from autopress.ui.toast import MAX_TOASTS, ToastManager

THIS = "tests.test_ui_shell_window"


@pytest.fixture(autouse=True)
def _free_widgets(qapp: QApplication):
    """Delete the windows of a test right away: leftover widgets make every later app-wide
    restyle (theme switch) slower."""
    yield
    gc.collect()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


class StandInPage(QWidget):
    """Replaces G6/G7 pages so these tests do not depend on other groups' work in progress."""

    def __init__(self, ctx: object) -> None:
        super().__init__()
        self.ctx = ctx


class StubPage(QWidget):
    def __init__(self, ctx: object) -> None:
        raise NotImplementedError


class BrokenPage(QWidget):
    def __init__(self, ctx: object) -> None:
        raise RuntimeError("boom")


@pytest.fixture
def quit_calls(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    calls: list[bool] = []
    monkeypatch.setattr(mw_mod, "_request_quit", lambda: calls.append(True))
    return calls


@pytest.fixture
def stand_in_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = dict(mw_mod.PAGE_CLASSES)
    for pid in ("codes", "profiles", "run", "history"):
        pages[pid] = (THIS, "StandInPage")
    monkeypatch.setattr(mw_mod, "PAGE_CLASSES", pages)


@pytest.fixture
def window(demo_ctx: Any, qtbot: Any, stand_in_pages: None, quit_calls: list[bool]) -> mw_mod.MainWindow:
    w = mw_mod.MainWindow(demo_ctx)
    qtbot.addWidget(w)
    return w


def test_builds_and_navigates(window: mw_mod.MainWindow, demo_ctx: Any, qtbot: Any) -> None:
    assert demo_ctx.main_window is window
    assert window.minimumWidth() == 1100 and window.minimumHeight() == 700
    assert window.current_page() == "codes"
    for pid in PAGE_IDS:
        window.navigate(pid)
        assert window.current_page() == pid and window.stack.currentWidget() is window.page(pid)
        assert window.sidebar.buttons[pid].isChecked()
    window.navigate("nope")
    assert window.current_page() == "help"
    demo_ctx.navigate("history")
    assert window.current_page() == "history"
    window.show()
    qtbot.mouseClick(window.sidebar.buttons["settings"], Qt.MouseButton.LeftButton)
    assert window.current_page() == "settings"
    from autopress.ui.help_page import HelpPage
    from autopress.ui.settings_page import SettingsPage

    assert isinstance(window.page("settings"), SettingsPage) and isinstance(window.page("help"), HelpPage)
    assert demo_ctx.hotkeys.hwnd == int(window.winId())  # attached to the main window HWND


def test_keyboard_shortcuts(window: mw_mod.MainWindow, qtbot: Any) -> None:
    window.show()
    window.activateWindow()
    window.sidebar.buttons["codes"].setFocus()
    qtbot.waitUntil(lambda: QApplication.focusWidget() is not None)
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)
    assert window.current_page() == "profiles"
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_F1)
    assert window.current_page() == "help"


def test_placeholder_for_not_implemented_and_broken_pages(demo_ctx: Any, qtbot: Any, monkeypatch: pytest.MonkeyPatch,
                                                          quit_calls: list[bool]) -> None:
    pages = dict(mw_mod.PAGE_CLASSES)
    pages["codes"] = (THIS, "StubPage")
    pages["profiles"] = (THIS, "BrokenPage")
    pages["run"] = ("autopress.ui.no_such_module", "X")
    pages["history"] = (THIS, "StandInPage")
    monkeypatch.setattr(mw_mod, "PAGE_CLASSES", pages)
    w = mw_mod.MainWindow(demo_ctx)
    qtbot.addWidget(w)
    assert w.page("codes") is None and w.is_placeholder("codes")
    texts = [lb.text() for lb in w.stack.widget(0).findChildren(QLabel)]
    assert "尚未實作" in texts
    assert w.page("profiles") is None and w.is_placeholder("profiles")
    assert "此頁面無法載入" in [lb.text() for lb in w.stack.widget(1).findChildren(QLabel)]
    assert w.is_placeholder("run") and not w.is_placeholder("history")
    w.navigate("codes")
    assert w.current_page() == "codes"  # placeholders still navigate


def test_real_pages_smoke(demo_ctx: Any, qtbot: Any, quit_calls: list[bool]) -> None:
    """With the other groups' real (or stub) pages: the window always builds."""
    w = mw_mod.MainWindow(demo_ctx)
    qtbot.addWidget(w)
    for pid in PAGE_IDS:
        assert w.page(pid) is not None or w.is_placeholder(pid)


def test_badges_follow_queue(window: mw_mod.MainWindow, demo_ctx: Any, qtbot: Any) -> None:
    counts = demo_ctx.queue.counts()
    expected = counts[CodeStatus.PENDING] + counts[CodeStatus.COOLDOWN] + counts[CodeStatus.REVIEW]
    assert window.sidebar.buttons["codes"].badge() == str(expected)
    assert window.sidebar.buttons["profiles"].badge() == "1"
    assert window.sidebar.buttons["history"].badge() == str(len(demo_ctx.history.records()))
    demo_ctx.queue.add_candidates([CodeCandidate(code="NEWCODE123"), CodeCandidate(code="NEWCODE456")],
                                  CodeSource.PASTE)
    qtbot.waitUntil(lambda: window.sidebar.buttons["codes"].badge() == str(expected + 2))
    window.set_badge("run", "1")
    assert window.sidebar.buttons["run"].badge() == "1"
    window.set_badge("run", "")
    assert window.sidebar.buttons["run"].badge() == ""


def test_status_bar_items(window: mw_mod.MainWindow, demo_ctx: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    assert window.status_text("guard") == "前景保護：開"
    assert window.status_text("interval") == "間隔 6–8 秒"
    assert window.status_bar.hotkeys.pause_key.text() == "F8" and window.status_bar.hotkeys.stop_key.text() == "F9"
    assert window.status_text("failsafe") == "左上角緊急停止：開"
    assert window.status_bar.items["failsafe"].toolTip()  # which corner counts on this layout
    assert window.status_text("ocr") == "文字辨識：就緒"
    demo_ctx.settings.hotkeys.pause_resume = "F6"
    demo_ctx.settings.failsafe_enabled = False
    demo_ctx.save_settings()
    assert window.status_bar.hotkeys.pause_key.text() == "F6"
    assert window.status_text("failsafe") == "左上角緊急停止：關"
    demo_ctx.ocr.state_changed.emit("failed")
    assert window.status_text("ocr") == "文字辨識：無法使用"
    assert "文字辨識引擎無法啟動" in window.status_bar.items["ocr"].toolTip()
    window.set_status("custom", "自訂", "info")
    assert window.status_text("custom") == "自訂" and window.status_bar.items["custom"].isVisibleTo(window)
    window.set_status("custom", "")
    assert not window.status_bar.items["custom"].isVisibleTo(window)
    window.set_status("version", "v9")
    assert window.sidebar.version_label.text() == "v9"


def test_status_target_refresh(window: mw_mod.MainWindow, demo_ctx: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from autopress.win32 import windows

    found = WindowInfo(hwnd=5, title="兌換中心 - Chrome", exe_path="C:/x/chrome.exe")
    monkeypatch.setattr(windows, "find_window", lambda match: found)
    window.show()  # the 2 s refresh is skipped while the window is hidden (run mode)
    window._refresh_target()
    assert window.status_text("target") == "已找到目標視窗：兌換中心 - Chrome"  # state first (UI review U7)
    monkeypatch.setattr(windows, "find_window", lambda match: None)
    window._refresh_target()
    assert window.status_text("target") == "找不到目標視窗"

    def broken(match: object) -> None:
        raise NotImplementedError

    monkeypatch.setattr(windows, "find_window", broken)
    window._refresh_target()
    assert "兌換" in window.status_text("target")  # describe() of the target, no crash
    demo_ctx.set_active_profile("")
    assert window.status_text("target") == "目標視窗：未選擇設定檔"
    assert window.status_text("interval") == "間隔 —"


def test_status_run_state(window: mw_mod.MainWindow, demo_ctx: Any) -> None:
    assert window.status_text("run") == ""
    prof = demo_ctx.active_profile()
    plan = demo_ctx.session.build_plan(prof, demo_ctx.settings, RunSelection.UNFINISHED)
    demo_ctx.session.start(plan)
    assert window.status_text("run").startswith("執行中")
    demo_ctx.session.pause()
    assert window.status_text("run").startswith("已暫停")
    demo_ctx.session.stop()
    assert window.status_text("run") == ""


def test_run_mode_hide_and_minimize(window: mw_mod.MainWindow, qtbot: Any) -> None:
    window.show()
    qtbot.waitExposed(window)
    window.set_run_mode(True)
    assert not window.isVisible() and window.is_run_mode()
    window.toasts.show_toast("執行中不顯示", "info")
    assert window.toasts.toasts() == [] and window.toasts.shown[-1] == ("info", "執行中不顯示")
    window.set_run_mode(False)
    assert window.isVisible() and not window.is_run_mode()
    window.set_run_mode(True, minimize=True)
    assert window.isVisible() and window.isMinimized()  # the taskbar button stays
    window.set_run_mode(False)
    assert window.isVisible() and not window.isMinimized()


def test_close_idle_quits_and_remembers_geometry(window: mw_mod.MainWindow, demo_ctx: Any, qtbot: Any,
                                                 quit_calls: list[bool]) -> None:
    window.show()
    window.resize(1300, 820)
    assert window.close()
    assert quit_calls == [True]
    assert demo_ctx.settings.window_geometry  # hex of saveGeometry, saved by ui.app at quit
    bytes.fromhex(demo_ctx.settings.window_geometry)


def test_close_during_run_asks(window: mw_mod.MainWindow, demo_ctx: Any, qtbot: Any, quit_calls: list[bool],
                               monkeypatch: pytest.MonkeyPatch) -> None:
    from autopress.ui import widgets

    prof = demo_ctx.active_profile()
    demo_ctx.session.start(demo_ctx.session.build_plan(prof, demo_ctx.settings))
    window.show()
    monkeypatch.setattr(widgets, "confirm", lambda *a, **k: False)
    assert not window.close()
    assert window.isVisible() and quit_calls == [] and ("stop", ) not in [c[:1] for c in demo_ctx.session.calls]
    monkeypatch.setattr(widgets, "confirm", lambda *a, **k: True)
    assert window.close()
    assert any(c[0] == "stop" for c in demo_ctx.session.calls) and quit_calls == [True]


def test_close_asks_about_unsaved_profile_edits(window: mw_mod.MainWindow, qtbot: Any, quit_calls: list[bool],
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    """Integration (G7 gap): quitting with unsaved profile edits asks Save / Discard / Cancel."""
    answers = [False, True]

    class DirtyProfiles:  # the real ProfilesPage.maybe_leave asks Save / Discard / Cancel
        def maybe_leave(self) -> bool:
            return answers.pop(0)

    real_page = window.page
    monkeypatch.setattr(window, "page", lambda pid: DirtyProfiles() if pid == "profiles" else real_page(pid))
    window.show()
    assert not window.close()
    assert window.isVisible() and quit_calls == []
    assert window.close()
    assert quit_calls == [True] and answers == []


def test_data_folder_fallback_banner(demo_ctx: Any, qtbot: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                     stand_in_pages: None, quit_calls: list[bool]) -> None:
    intended, fallback = tmp_path / "blocked", tmp_path / "fallback"
    monkeypatch.setattr(paths, "resolve_data_dir", lambda refresh=False: (fallback, intended))
    w = mw_mod.MainWindow(demo_ctx)
    qtbot.addWidget(w)
    texts = [b.text() for b in w.banners()]
    assert texts == [f"無法寫入資料資料夾 {intended}，改用 {fallback}。"]
    settings_page = w.page("settings")
    assert settings_page.fallback_note.text() == texts[0]


def test_recovered_banner_and_start_page(demo_ctx: Any, qtbot: Any, stand_in_pages: None,
                                         quit_calls: list[bool]) -> None:
    demo_ctx.extras["recovered"] = 2
    demo_ctx.extras["start_page"] = "profiles"
    w = mw_mod.MainWindow(demo_ctx)
    qtbot.addWidget(w)
    assert w.current_page() == "profiles"
    banner = w.banners()[0]
    assert "2 筆序號" in banner.text()
    banner.actionClicked.emit()
    assert w.current_page() == "codes"
    assert "recovered" not in demo_ctx.extras and "start_page" not in demo_ctx.extras


def test_sidebar_theme_switch(window: mw_mod.MainWindow, demo_ctx: Any, qapp: QApplication) -> None:
    from autopress import storage

    theme.apply_theme(qapp, "dark")
    seen: list[str] = []
    demo_ctx.signals.theme_changed.connect(seen.append)
    try:
        window.sidebar.theme_switch.setChecked(False)
        assert theme.current_theme() == "light" and seen == ["light"]
        assert demo_ctx.settings.theme is ThemeName.LIGHT
        assert storage.load_settings().theme is ThemeName.LIGHT  # persisted
        demo_ctx.signals.theme_changed.emit("dark")
        assert window.sidebar.theme_switch.isChecked()
    finally:
        theme.apply_theme(qapp, "dark")


# ----------------------------------------------------------------------------- toasts


def test_toast_stacking_max_three(qtbot: Any) -> None:
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(900, 600)
    host.show()
    tm = ToastManager(host)
    for n in range(4):
        tm.show_toast(f"訊息 {n}", "info", timeout_ms=60000)
    shown = tm.toasts()
    assert len(shown) == MAX_TOASTS == 3
    assert [t.text() for t in shown] == ["訊息 3", "訊息 2", "訊息 1"]  # newest on top, oldest dropped
    assert len(tm.shown) == 4
    ys = [t.y() for t in shown]
    assert ys == sorted(ys) and all(b - a >= shown[0].height() for a, b in zip(ys, ys[1:]))
    for t in shown:
        assert t.x() + t.width() <= host.width() - 10  # top-right corner
        assert t.y() < 300


def test_toast_signals_action_timeout_and_hidden_host(qtbot: Any, demo_ctx: Any) -> None:
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(800, 400)
    tm = ToastManager(host)
    tm.attach_signals(demo_ctx.signals)
    demo_ctx.notify("沒顯示", "warning")  # host hidden: recorded, not displayed
    assert tm.shown == [("warning", "沒顯示")] and tm.toasts() == []
    host.show()
    demo_ctx.notify("已加入 3 筆", "success")
    assert [t.text() for t in tm.toasts()] == ["已加入 3 筆"]
    hits: list[bool] = []
    tm.show_toast("錯誤", "error", "開啟資料夾", lambda: hits.append(True), timeout_ms=60000)
    toast = tm.toasts()[0]
    assert toast.action_button is not None and toast.action_button.text() == "開啟資料夾"
    qtbot.mouseClick(toast.action_button, Qt.MouseButton.LeftButton)
    assert hits == [True] and toast not in tm.toasts()
    tm.show_toast("很快消失", "info", timeout_ms=500)
    qtbot.waitUntil(lambda: all(t.text() != "很快消失" for t in tm.toasts()), timeout=3000)


def test_crash_toast_text(window: mw_mod.MainWindow) -> None:
    window.show()
    window.show_crash_toast("ValueError: secret-code-1234")
    t = window.toasts.toasts()[0]
    assert t.text() == "發生未預期的錯誤，已記錄在紀錄檔。" and t.kind == "error"
    assert t.action_button is not None and t.action_button.text() == "開啟資料夾"
    assert "secret" not in t.text()
