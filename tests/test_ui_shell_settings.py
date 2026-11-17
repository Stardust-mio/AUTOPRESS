"""G5: settings page - binding and persistence, OCR restart (debounced + button), hotkey capture
with the conflict test, locks during a run, history clearing, external changes reload."""

from __future__ import annotations

import gc
from typing import Any

import pytest
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from autopress import paths, storage
from autopress.models import CodeStatus, Language, ThemeName, TypingMode
from autopress.ui import settings_page as sp_mod
from autopress.ui import theme
from autopress.ui.settings_hotkey import HotkeyEdit, combo_from_event, key_name
from autopress.ui.settings_page import SettingsPage


@pytest.fixture(autouse=True)
def _free_widgets(qapp: QApplication):
    yield
    gc.collect()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


@pytest.fixture
def page(demo_ctx: Any, qtbot: Any) -> SettingsPage:
    p = SettingsPage(demo_ctx)
    qtbot.addWidget(p)
    p.resize(1000, 900)
    return p


@pytest.fixture
def restarts(demo_ctx: Any, monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    calls: list[Any] = []
    monkeypatch.setattr(demo_ctx.ocr, "restart", lambda settings=None: calls.append(settings))
    return calls


def test_controls_show_settings(page: SettingsPage, demo_ctx: Any) -> None:
    s = demo_ctx.settings
    assert page.failsafe.isChecked() is s.failsafe_enabled
    assert page.countdown.value() == s.countdown_s == 3
    assert page.resume_countdown.value() == 2 and page.confirm_over.value() == 30
    assert page.daily_cap.value() == 0 and page.daily_cap.text() == "不限制"
    assert page.hotkey_pause.combo() == "F8" and page.hotkey_stop.combo() == "F9"
    assert page.typing_mode.currentIndex() == 0
    assert page.delay_spins["key_delay_ms"].value() == 15
    assert page.ocr_threads.value() == 4 and page.review_threshold.value() == pytest.approx(0.95)
    assert page.skip_boxes[CodeStatus.SUCCESS].isChecked() and not page.skip_boxes[CodeStatus.SUBMITTED].isChecked()
    assert page.keep_days.value() == 30
    assert page.data_path.text() == str(paths.resolve_data_dir()[0])
    assert page.version_label.text().startswith("AutoPress v")
    assert page.ocr_state_label.text() == "就緒"


def test_changes_are_saved(page: SettingsPage, demo_ctx: Any) -> None:
    saved: list[object] = []
    demo_ctx.signals.settings_changed.connect(saved.append)
    page.failsafe.click()
    page.user_input.click()
    page.countdown.setValue(5)
    page.resume_countdown.setValue(0)
    page.confirm_over.setValue(50)
    page.daily_cap.setValue(20)
    page.minibar.click()
    page.typing_mode.setCurrentIndex(2)
    page.delay_spins["after_click_ms"].setValue(300)
    page.review_threshold.setValue(0.9)
    page.skip_boxes[CodeStatus.SUBMITTED].click()
    page.skip_boxes[CodeStatus.USED].click()
    page.save_evidence.click()
    page.keep_days.setValue(0)
    page.skip_history.click()
    s = storage.load_settings()  # read back from settings.json in the test's data folder
    assert s.failsafe_enabled is False and s.pause_on_user_input is False
    assert (s.countdown_s, s.resume_countdown_s, s.confirm_run_over, s.daily_cap) == (5, 0, 50, 20)
    assert s.minibar_enabled is False and s.default_typing_mode is TypingMode.VK
    assert s.delays.after_click_ms == 300 and s.ocr.review_threshold == pytest.approx(0.9)
    assert s.history_skip_statuses == [CodeStatus.SUCCESS, CodeStatus.SUBMITTED]
    assert s.save_evidence is False and s.evidence_keep_days == 0 and s.skip_history_on_import is False
    assert len(saved) >= 15


def test_language_needs_restart(page: SettingsPage, demo_ctx: Any) -> None:
    page.language.setCurrentIndex(2)
    assert demo_ctx.settings.language is Language.EN and storage.load_settings().language is Language.EN
    assert "重新啟動" in page.language_note.text()
    from autopress import i18n

    assert i18n.get_language() == "zh-TW"  # not switched live


def test_theme_segment_applies_live(page: SettingsPage, demo_ctx: Any, qapp: QApplication) -> None:
    theme.apply_theme(qapp, "dark")
    seen: list[str] = []
    demo_ctx.signals.theme_changed.connect(seen.append)
    try:
        page.theme_seg.setCurrentIndex(1)
        assert theme.current_theme() == "light" and seen == ["light"]
        assert storage.load_settings().theme is ThemeName.LIGHT
        page.theme_seg.setCurrentIndex(2)
        assert demo_ctx.settings.theme is ThemeName.SYSTEM
    finally:
        theme.apply_theme(qapp, "dark")


def test_external_change_reloads(page: SettingsPage, demo_ctx: Any) -> None:
    demo_ctx.settings.failsafe_enabled = False
    demo_ctx.settings.theme = ThemeName.LIGHT
    demo_ctx.save_settings()
    assert not page.failsafe.isChecked() and page.theme_seg.currentIndex() == 1


def test_ocr_changes_restart_engine(page: SettingsPage, demo_ctx: Any, qtbot: Any, restarts: list[Any]) -> None:
    page.ocr_threads.setValue(2)
    page.ocr_threads.setValue(3)  # debounced: one restart
    assert restarts == []
    qtbot.waitUntil(lambda: len(restarts) == 1, timeout=3000)
    assert restarts[0] is demo_ctx.settings.ocr and restarts[0].threads == 3
    page.ocr_threads.setValue(0)
    assert demo_ctx.settings.ocr.threads == -1 and page.ocr_threads.text() == "全部核心"
    page.ocr_enabled.click()
    page.restart_ocr()  # the button: immediate, cancels the pending debounce
    assert len(restarts) == 2 and restarts[-1].enabled is False
    qtbot.wait(800)
    assert len(restarts) == 2
    assert storage.load_settings().ocr.enabled is False
    page.review_threshold.setValue(0.8)  # not an engine setting: no restart
    qtbot.wait(800)
    assert len(restarts) == 2
    qtbot.mouseClick(page.ocr_restart_button, Qt.MouseButton.LeftButton)
    assert len(restarts) == 3


def test_ocr_failed_state_shows_reason(demo_ctx: Any, qtbot: Any) -> None:
    from tests.fakes import FakeOcrService

    demo_ctx.ocr = FakeOcrService(state="failed", error="找不到模型檔")
    p = SettingsPage(demo_ctx)
    qtbot.addWidget(p)
    assert p.ocr_state_label.text() == "無法使用"
    assert not p.ocr_error.isHidden() and "找不到模型檔" in p.ocr_error.text()
    demo_ctx.ocr._state = type(demo_ctx.ocr.state)("ready")
    demo_ctx.ocr.state_changed.emit("ready")
    assert p.ocr_state_label.text() == "就緒" and p.ocr_error.isHidden()


def test_key_mapping() -> None:
    assert key_name(Qt.Key.Key_F7) == "F7" and key_name(Qt.Key.Key_F24) == "F24"
    assert key_name(Qt.Key.Key_K) == "K" and key_name(Qt.Key.Key_5) == "5"
    assert key_name(Qt.Key.Key_Return) == "Enter" and key_name(Qt.Key.Key_PageDown) == "PageDown"
    assert combo_from_event(Qt.Key.Key_F7, Qt.KeyboardModifier.NoModifier) == "F7"
    mods = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
    assert combo_from_event(Qt.Key.Key_K, mods) == "Ctrl+Shift+K"
    assert combo_from_event(Qt.Key.Key_P, Qt.KeyboardModifier.MetaModifier) == "Win+P"
    assert combo_from_event(Qt.Key.Key_Control, Qt.KeyboardModifier.ControlModifier) is None
    assert combo_from_event(Qt.Key.Key_Eacute, Qt.KeyboardModifier.NoModifier) is None


def _press(qtbot: Any, edit: HotkeyEdit, key: Qt.Key, mods: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier) -> None:
    edit.window().activateWindow()
    edit.setFocus()
    qtbot.waitUntil(lambda: QApplication.focusWidget() is edit)
    QTest.keyClick(QApplication.focusWidget(), key, mods)  # shortcut tests go to the focus widget


def test_hotkey_capture_and_conflict_test(page: SettingsPage, demo_ctx: Any, qtbot: Any) -> None:
    page.show()
    _press(qtbot, page.hotkey_pause, Qt.Key.Key_F7)
    assert demo_ctx.settings.hotkeys.pause_resume == "F7" and storage.load_settings().hotkeys.pause_resume == "F7"
    assert page.hotkey_pause.text() == "F7" and "已改成 F7" in page.hotkey_message.text()
    assert demo_ctx.hotkeys.registered() == {}  # the temporary registration was removed again
    _press(qtbot, page.hotkey_stop, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    assert demo_ctx.settings.hotkeys.stop == "Ctrl+Shift+K"
    _press(qtbot, page.hotkey_stop, Qt.Key.Key_K)  # a bare letter is refused (validate_hotkey)
    assert demo_ctx.settings.hotkeys.stop == "Ctrl+Shift+K" and "Ctrl 或 Alt" in page.hotkey_message.text()
    _press(qtbot, page.hotkey_stop, Qt.Key.Key_F12)
    assert demo_ctx.settings.hotkeys.stop == "Ctrl+Shift+K" and "F12" in page.hotkey_message.text()
    _press(qtbot, page.hotkey_stop, Qt.Key.Key_F7)  # same as pause
    assert demo_ctx.settings.hotkeys.stop == "Ctrl+Shift+K" and "同一個" in page.hotkey_message.text()
    demo_ctx.hotkeys.fail_combos = {"F6"}
    _press(qtbot, page.hotkey_stop, Qt.Key.Key_F6)  # 1409: used by another program
    assert demo_ctx.settings.hotkeys.stop == "Ctrl+Shift+K" and "已被其他程式使用" in page.hotkey_message.text()
    assert page.hotkey_stop.text() == "Ctrl+Shift+K"
    _press(qtbot, page.hotkey_pause, Qt.Key.Key_Escape)  # Esc cancels capture
    assert demo_ctx.settings.hotkeys.pause_resume == "F7" and not page.hotkey_pause.hasFocus()


def test_locked_during_run(page: SettingsPage, demo_ctx: Any, restarts: list[Any]) -> None:
    prof = demo_ctx.active_profile()
    demo_ctx.session.start(demo_ctx.session.build_plan(prof, demo_ctx.settings))
    for w in (page.hotkey_pause, page.hotkey_stop, page.ocr_enabled, page.ocr_threads, page.ocr_restart_button,
              page.clear_history_button):
        assert not w.isEnabled()
    assert page.set_hotkey("stop", "F10") is False and demo_ctx.settings.hotkeys.stop == "F9"
    page.restart_ocr()
    assert restarts == []
    demo_ctx.session.stop()
    assert page.hotkey_pause.isEnabled() and page.clear_history_button.isEnabled()


def test_clear_history(page: SettingsPage, demo_ctx: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from autopress.ui import widgets

    n = len(demo_ctx.history.records())
    assert n > 0
    monkeypatch.setattr(widgets, "confirm", lambda *a, **k: False)
    assert page.clear_history() == 0 and len(demo_ctx.history.records()) == n
    monkeypatch.setattr(widgets, "confirm", lambda *a, **k: True)
    toasts: list[tuple[str, str]] = []
    demo_ctx.signals.toast.connect(lambda kind, text: toasts.append((kind, text)))
    assert page.clear_history() == n and demo_ctx.history.records() == []
    assert toasts == [("success", f"已清除 {n} 筆紀錄。")]


def test_welcome_reset(page: SettingsPage, demo_ctx: Any) -> None:
    assert demo_ctx.settings.first_run_done
    page.welcome_button.click()
    assert storage.load_settings().first_run_done is False


def test_settings_page_english(demo_ctx: Any, qtbot: Any) -> None:
    from autopress import i18n

    i18n.set_language("en")
    p = SettingsPage(demo_ctx)
    qtbot.addWidget(p)
    assert p.ocr_restart_button.text() == "Restart engine" and p.daily_cap.text() == "No limit"
    assert sp_mod.HOTKEY_TEST_ACTION not in ("pause_resume", "stop")
