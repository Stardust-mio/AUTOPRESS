"""G5: help page content (both languages, failsafe drawing for this PC's left-of-primary layout)
and the first-run welcome dialog (language applies at once, theme live, navigation choice)."""

from __future__ import annotations

import gc
from typing import Any

import pytest
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtWidgets import QApplication, QLabel

from autopress import i18n, storage
from autopress.models import Language, ThemeName
from autopress.ui import theme
from autopress.ui import welcome as welcome_mod
from autopress.ui.help_page import FailsafeMap, HelpPage
from autopress.ui.shell_common import failsafe_corner_text
from autopress.ui.welcome import WelcomeDialog, show_welcome_if_needed

LEFT_OF_PRIMARY = [(0, 0, 1920, 1080), (-1920, 0, 1920, 1080)]


@pytest.fixture(autouse=True)
def _free_widgets(qapp: QApplication):
    yield
    gc.collect()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


def _all_text(w: Any) -> str:
    return "\n".join(lb.text() for lb in w.findChildren(QLabel))


def test_help_sections_zh(demo_ctx: Any, qtbot: Any) -> None:
    page = HelpPage(demo_ctx)
    qtbot.addWidget(page)
    assert list(page.sections) == ["about", "safety", "troubleshooting", "hotkeys", "privacy"]
    text = _all_text(page)
    for phrase in ("只輸入你自己的序號", "只匯入你信任的人分享的設定檔", "/redeem", "不是法律建議",
                   "系統管理員", "拖曳", "無邊框視窗", "縮放比例", "注音", "模擬鍵入", "找不到按鈕上的文字",
                   "其他資訊", "仍要執行", "防毒軟體", "隔離", "鎖住滑鼠游標", "帳號或角色名稱", "離線運作"):
        assert phrase in text, phrase
    assert page.pause_key.text() == "F8" and page.stop_key.text() == "F9"
    page.scroll_to("privacy")
    page.scroll_to("unknown")


def test_help_follows_settings(demo_ctx: Any, qtbot: Any) -> None:
    page = HelpPage(demo_ctx)
    qtbot.addWidget(page)
    demo_ctx.settings.hotkeys.stop = "F10"
    demo_ctx.settings.failsafe_enabled = False
    demo_ctx.save_settings()
    assert page.stop_key.text() == "F10" and "關閉" in page.failsafe_text.text()


def test_help_english(demo_ctx: Any, qtbot: Any) -> None:
    i18n.set_language("en")
    page = HelpPage(demo_ctx)
    qtbot.addWidget(page)
    text = _all_text(page)
    for phrase in ("Enter only your own codes", "administrator", "Explorer", "borderless", "SmartScreen",
                   "Run anyway", "antivirus", "/redeem", "not legal advice", "stop hotkey"):
        assert phrase in text, phrase


def test_failsafe_map_left_of_primary(qtbot: Any) -> None:
    fm = FailsafeMap(LEFT_OF_PRIMARY)
    qtbot.addWidget(fm)
    assert fm.corners == [(-1920, 0)]  # only the left monitor's corner is an outer corner
    assert not fm.grab().isNull()
    text = failsafe_corner_text(LEFT_OF_PRIMARY)
    assert "-1920" in text and "最左邊" in text
    single = failsafe_corner_text([(0, 0, 2560, 1440)])
    assert "左上角" in single
    fm.set_rects([])
    assert fm.corners == [(0, 0)]


def test_welcome_content_and_buttons(demo_ctx: Any, qtbot: Any) -> None:
    dlg = WelcomeDialog(demo_ctx)
    qtbot.addWidget(dlg)
    text = _all_text(dlg)
    for phrase in ("只輸入你自己的序號", "優先使用官方兌換網頁", "各遊戲條款由你自己負責", "只匯入你信任的人分享的設定檔"):
        assert phrase in text
    assert dlg.windowTitle() == "歡迎使用 AutoPress" and dlg.templates_button.isDefault()
    dlg.show()
    qtbot.mouseClick(dlg.templates_button, Qt.MouseButton.LeftButton)
    assert dlg.choice == "templates" and dlg.result() == 1


def test_welcome_language_applies_at_once(demo_ctx: Any, qtbot: Any, qapp: QApplication) -> None:
    dlg = WelcomeDialog(demo_ctx)
    qtbot.addWidget(dlg)
    try:
        dlg.language.setCurrentIndex(2)  # English
        assert i18n.get_language() == "en" and demo_ctx.settings.language is Language.EN
        qtbot.waitUntil(lambda: dlg.windowTitle() == "Welcome to AutoPress")
        assert "Enter only your own codes" in _all_text(dlg)
    finally:
        from autopress.ui.shell_common import install_translator

        install_translator(qapp, "zh-TW")


def test_welcome_theme_live(demo_ctx: Any, qtbot: Any, qapp: QApplication) -> None:
    theme.apply_theme(qapp, "dark")
    dlg = WelcomeDialog(demo_ctx)
    qtbot.addWidget(dlg)
    try:
        dlg.theme_seg.setCurrentIndex(1)
        assert theme.current_theme() == "light" and demo_ctx.settings.theme is ThemeName.LIGHT
    finally:
        theme.apply_theme(qapp, "dark")


def test_show_welcome_if_needed(demo_ctx: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    shown: list[Any] = []

    def fake_exec(dlg: Any) -> int:
        shown.append(dlg)
        dlg._templates()
        return 1

    monkeypatch.setattr(welcome_mod, "_exec_dialog", fake_exec)
    show_welcome_if_needed(demo_ctx, None)  # first_run_done is True in the demo context
    assert shown == []
    demo_ctx.settings.first_run_done = False
    show_welcome_if_needed(demo_ctx, None)
    assert len(shown) == 1 and demo_ctx.settings.first_run_done
    assert storage.load_settings().first_run_done is True
    assert demo_ctx.extras["start_page"] == "profiles"  # no main window yet: MainWindow opens Profiles


def test_show_welcome_with_main_window_navigates(demo_ctx: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(welcome_mod, "_exec_dialog", lambda dlg: dlg._templates() or 1)
    demo_ctx.main_window = object()
    pages: list[str] = []
    demo_ctx.signals.navigate.connect(pages.append)
    demo_ctx.settings.first_run_done = False
    show_welcome_if_needed(demo_ctx, None)
    assert pages == ["profiles"] and "start_page" not in demo_ctx.extras


def test_headless_welcome_never_blocks(demo_ctx: Any) -> None:
    demo_ctx.settings.first_run_done = False
    show_welcome_if_needed(demo_ctx, None)  # offscreen: skipped, marked done, no hang
    assert demo_ctx.settings.first_run_done and "start_page" not in demo_ctx.extras
