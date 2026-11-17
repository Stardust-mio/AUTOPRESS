# OWNED BY ORCH (UI polish of the screenshot review, SPEC 3.2; written by the G7 fix group)
"""UI polish of the Profiles screens (review items U4, U21, U24, U29, U30, U31, U35, U39, U40):
the profile editor never needs sideways scrolling, the empty profile list explains what to do,
the window picker offers the restart button its text names, the import card aligns its lines
and drops the empty band, codes formats and click-text patterns read as words, the editor cards
share one label column, the setup wizard shows its progress and the picker rows breathe.

Offscreen (no real fonts): widths are checked against the layout rules, not exact pixels."""

from __future__ import annotations

from typing import Any

import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import QApplication, QComboBox, QFormLayout, QLabel

from autopress import i18n
from autopress.codes import presets
from autopress.models import (
    ClickPointParams,
    ClickTextParams,
    OcrCheckParams,
    Profile,
    StepType,
    TemplateInfo,
    TextMatch,
    TimeoutAction,
    TypeCodeParams,
    TypeTextParams,
    WaitTextParams,
    make_step,
    record_point,
    record_region,
)
from autopress.ui import profiles_dialogs, profiles_wizard as pw, theme
from autopress.ui import widgets as w
from autopress.ui.profiles_page import STEP_LIST_MIN_W, ProfilesPage
from autopress.ui.step_forms import PositionField
from tests.data.ui_run.g7_helpers import attach_main_window, patch_dialogs, patch_target, window

CLIENT = (100, 50, 1280, 720)


@pytest.fixture
def page(demo_ctx: Any, qtbot: Any, monkeypatch: pytest.MonkeyPatch) -> ProfilesPage:
    attach_main_window(demo_ctx)
    monkeypatch.setattr(ProfilesPage, "start_wizard", lambda self, pid, realign=False: None)
    p = ProfilesPage(demo_ctx)
    qtbot.addWidget(p)
    return p


def _every_step_type(profile: Profile) -> Profile:
    """The demo profile plus one step of every type with every position recorded (the widest
    forms: long recorded values, fallback point, verify region)."""
    for st in StepType:
        if st is StepType.UNKNOWN:
            continue
        s = make_step(st)
        p = s.params
        if isinstance(p, ClickPointParams):
            p.point = record_point(CLIENT, 740, 410)
        elif isinstance(p, ClickTextParams):
            p.text = "兌換|Redeem"
            p.region = record_region(CLIENT, 400, 500, 600, 120)
            p.fallback_point = record_point(CLIENT, 1300, 700)
        elif isinstance(p, TypeCodeParams):
            p.verify_region = record_region(CLIENT, 400, 500, 600, 120)
        elif isinstance(p, TypeTextParams):
            p.text = "/redeem {code}"
        elif isinstance(p, WaitTextParams):
            p.text = "兌換結果|完成"
            p.region = record_region(CLIENT, 300, 200, 700, 300)
        elif isinstance(p, OcrCheckParams):
            p.region = record_region(CLIENT, 300, 200, 700, 300)
        profile.steps.append(s)
    return profile


def _x(widget: Any, root: Any) -> int:
    return widget.mapTo(root, QPoint(0, 0)).x()


# ----------------------------------------------------------------------------- U4 no sideways scrolling


def test_u4_step_forms_wrap_instead_of_widening_the_editor(page: ProfilesPage) -> None:
    ctx = page.ctx
    prof = _every_step_type(ctx.active_profile())
    ctx.profiles.save(prof)
    page.open_profile(prof.id)
    page._load(prof.id)
    assert page.step_list.minimumWidth() == STEP_LIST_MIN_W == 240  # was a fixed 300
    assert isinstance(page.title, w.ElidedLabel) and isinstance(page.target_card.status, w.ElidedLabel)
    assert page.test_row.rowWrapPolicy() is QFormLayout.RowWrapPolicy.WrapLongRows
    for i in range(len(prof.steps)):
        page.step_list.set_current(i)
        form = page.step_editor.form
        assert form.main.rowWrapPolicy() is QFormLayout.RowWrapPolicy.WrapLongRows
        assert form.adv.rowWrapPolicy() is QFormLayout.RowWrapPolicy.WrapLongRows
        for combo in form.findChildren(QComboBox):
            if combo.parent() is not None and not isinstance(combo.parent(), PositionField):
                assert combo.sizeAdjustPolicy() is QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        for fld in form.findChildren(PositionField):
            # the value has a line of its own and wraps; the buttons sit under it
            assert fld.value_label.wordWrap()
            assert fld.layout().itemAt(0).widget() is fld.value_label


@pytest.mark.parametrize("size", [(1060, 740), (880, 640)])  # default window, smallest window (1100 x 700)
def test_u4_editor_cards_fit_the_page_width(page: ProfilesPage, size: tuple[int, int]) -> None:
    """Every card of the editor that this page builds (basics, target, format, steps, run rules)
    is at most as wide as the scroll viewport, for every step type with recorded positions, so
    the editor never scrolls sideways (the old step forms were up to ~400 px too wide)."""
    ctx = page.ctx
    prof = _every_step_type(ctx.active_profile())
    ctx.profiles.save(prof)
    page._load(prof.id)
    page.resize(*size)
    page.show()
    budget = page.editor_page.viewport().width() - page.editor_page.widget().layout().contentsMargins().right()
    cards = {"basics": page.basics, "target": page.target_card, "format": page.format_card,
             "policy": page.policy_card}
    for name, c in cards.items():
        assert c.minimumSizeHint().width() <= budget, name
    for i in range(len(prof.steps)):
        page.step_list.set_current(i)
        QApplication.processEvents()  # the new step form is shown (and counted by the layout) by a queued call
        assert page.step_editor.form.isVisible()
        assert page.steps_card.minimumSizeHint().width() <= budget, prof.steps[i].type


def test_u4_long_window_title_and_profile_name_never_widen_the_editor(page: ProfilesPage,
                                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    long_title = "很長的視窗標題 " * 30
    patch_target(monkeypatch, window(9, "chrome.exe", long_title))
    page._refresh_target_status()
    assert page.target_card.status.text().startswith("已找到：很長的視窗標題")
    assert page.target_card.minimumSizeHint().width() < 600
    page.basics.name.setText("名字" * 40)
    assert page.title.text() == "名字" * 40 and page.title.minimumSizeHint().width() < 100


# ----------------------------------------------------------------------------- U21 empty list


def test_u21_empty_profile_list_points_to_the_templates(demo_ctx: Any, qtbot: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from autopress import storage

    for p in demo_ctx.profiles.list():
        demo_ctx.profiles.delete(p.id)
    demo_ctx.settings.active_profile_id = ""
    tpl = Profile(name="web", template=TemplateInfo(key="web_generic", title_zh="網頁兌換（通用）", title_en="Web redeem"))
    tpl.steps = [make_step(StepType.TYPE_CODE)]
    monkeypatch.setattr(storage, "load_templates", lambda directory=None: [tpl])
    monkeypatch.setattr(ProfilesPage, "start_wizard", lambda self, pid, realign=False: None)
    page = ProfilesPage(demo_ctx)
    qtbot.addWidget(page)
    assert page.stack.currentWidget() is page.gallery_page
    assert page.list_empty.isVisibleTo(page)
    assert "範本" in page.list_empty_hint.text() and "匯入" in page.list_empty_hint.text()
    page.gallery.buttons[0].click()  # 使用這個範本
    assert page.working_profile() is not None and page.list.count() == 1
    assert not page.list_empty.isVisibleTo(page)


def test_u21_empty_state_is_hidden_with_profiles(page: ProfilesPage) -> None:
    assert page.list.count() >= 1 and not page.list_empty.isVisibleTo(page)


def test_u21_empty_state_english(demo_ctx: Any, qtbot: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    i18n.set_language("en")
    for p in demo_ctx.profiles.list():
        demo_ctx.profiles.delete(p.id)
    page = ProfilesPage(demo_ctx)
    qtbot.addWidget(page)
    assert "template" in page.list_empty_hint.text() and "Import" in page.list_empty_hint.text()


# ----------------------------------------------------------------------------- U24 / U40 window picker


@pytest.fixture
def picker_windows(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    from autopress.win32 import elevation, windows

    wins = [window(1, "explorer.exe", "檔案總管"), window(2, "chrome.exe", "示範遊戲 兌換頁 - Google Chrome", cls="Chrome_WidgetWin_1"),
            window(3, "DemoGame.exe", "Demo Game", cls="UnityWndClass"), window(4, "notepad.exe", "記事本"),
            window(5, "launcher.exe", "Launcher", minimized=True)]
    monkeypatch.setattr(windows, "list_windows", lambda alt_tab_only=True: list(wins))
    monkeypatch.setattr(elevation, "input_permission", lambda hwnd: {3: "blocked_elevated", 4: "unknown"}.get(hwnd, "ok"))
    state = {"can_elevate": True}
    monkeypatch.setattr(elevation, "can_elevate", lambda: state["can_elevate"])
    return state


def _picker(demo_ctx: Any, qtbot: Any, **kw: Any) -> Any:
    from autopress.ui.window_picker import WindowPickerDialog

    dlg = WindowPickerDialog(demo_ctx, None, None, suggested_exe="DemoGame.exe", **kw)
    qtbot.addWidget(dlg)
    return dlg


def test_u24_restart_button_where_the_text_points(demo_ctx: Any, qtbot: Any, picker_windows: dict,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    from autopress.ui import run_actions

    dlg = _picker(demo_ctx, qtbot)
    assert dlg.select_hwnd(3)  # runs as administrator
    assert dlg.restart_btn.isVisibleTo(dlg)
    assert dlg.restart_btn.text() == run_actions.action_label("restart_admin") == "以系統管理員身分重新啟動"
    assert f"「{dlg.restart_btn.text()}」" in dlg.detail.text()  # the text names this very button
    assert "AutoPress」" not in dlg.detail.text()  # not the missing 「…重新啟動 AutoPress」 button
    assert dlg.select_hwnd(2)
    assert not dlg.restart_btn.isVisibleTo(dlg)
    calls: list[tuple[Any, Any]] = []
    monkeypatch.setattr(run_actions, "restart_as_admin_flow", lambda parent, ctx=None: calls.append((parent, ctx)) or False)
    dlg.select_hwnd(3)
    dlg.restart_btn.click()
    assert calls == [(dlg, demo_ctx)]


def test_u24_account_that_cannot_elevate_gets_no_button(demo_ctx: Any, qtbot: Any, picker_windows: dict) -> None:
    picker_windows["can_elevate"] = False
    dlg = _picker(demo_ctx, qtbot)
    dlg.select_hwnd(3)
    assert not dlg.restart_btn.isVisibleTo(dlg)
    assert "此帳戶沒有系統管理員權限" in dlg.detail.text() and "重新啟動" not in dlg.detail.text()


def test_u24_restart_flow_confirms_then_restarts(page: ProfilesPage, monkeypatch: pytest.MonkeyPatch) -> None:
    from autopress.ui import run_actions
    from autopress.win32 import elevation

    ctx = page.ctx
    ctx.main_window.pages["profiles"] = page
    restarts: list[int] = []
    quits: list[int] = []
    monkeypatch.setattr(elevation, "restart_as_admin", lambda argv=None: restarts.append(1) or True)
    monkeypatch.setattr(QApplication, "quit", staticmethod(lambda: quits.append(1)))
    dialogs = patch_dialogs(monkeypatch, answers=[False])
    assert run_actions.restart_as_admin_flow(None, ctx) is False  # 取消 at the confirmation
    assert dialogs.confirms and restarts == []
    # no Save / Discard question of its own (repair round 2: it went beyond the listed issue), as the
    # pre-flight action before the UI polish
    page.basics.name.setText("改過但還沒存")
    asked: list[str] = []
    monkeypatch.setattr(profiles_dialogs, "ask_save_changes", lambda parent, name: asked.append(name) or "cancel")
    dialogs.answers = [True]
    assert run_actions.restart_as_admin_flow(None, ctx) is True
    assert restarts == [1] and quits == [1] and asked == []
    # the pre-flight action button uses the same flow
    seen: list[Any] = []
    monkeypatch.setattr(run_actions, "restart_as_admin_flow", lambda parent, ctx=None: seen.append(ctx) or True)
    assert run_actions.perform_action(ctx, "restart_admin", page.working_profile()) is False
    assert seen == [ctx]


def test_u24_target_card_tooltip_points_to_the_picker(page: ProfilesPage, monkeypatch: pytest.MonkeyPatch) -> None:
    from autopress.win32 import elevation

    patch_target(monkeypatch, window(9, "chrome.exe", "兌換 - Google Chrome"))
    monkeypatch.setattr(elevation, "input_permission", lambda hwnd: "blocked_elevated")
    monkeypatch.setattr(elevation, "can_elevate", lambda: True)
    page._refresh_target_status()
    tip = page.target_card.status.toolTip()
    assert "「選擇視窗…」" in tip and "「以系統管理員身分重新啟動」" in tip
    monkeypatch.setattr(elevation, "can_elevate", lambda: False)
    page._refresh_target_status()
    assert "此帳戶沒有系統管理員權限" in page.target_card.status.toolTip()


def test_u40_rows_have_a_real_height_and_warnings_stand_apart(demo_ctx: Any, qtbot: Any, picker_windows: dict) -> None:
    from autopress.ui.window_picker import ROW_H

    dlg = _picker(demo_ctx, qtbot)
    dlg.show()
    items = {dlg.tree.topLevelItem(i).text(1).split(" · ")[0]: dlg.tree.topLevelItem(i)
             for i in range(dlg.tree.topLevelItemCount())}
    first = dlg.tree.topLevelItem(0)
    assert first.sizeHint(0).height() == ROW_H >= 32
    assert dlg.tree.visualItemRect(first).height() >= ROW_H  # font-independent (was 18 px)
    game = items["DemoGame.exe"]
    assert game.text(1) == "DemoGame.exe · 建議" and game.text(2) == "系統管理員"  # suggestion apart from the warning
    assert game.foreground(2).color() == theme.color("warning_text") and not game.icon(2).isNull()
    assert items["notepad.exe"].text(2) == "可能無法輸入"
    assert items["notepad.exe"].foreground(2).color() == theme.color("warning_text")
    assert items["launcher.exe"].text(2) == "已最小化" and items["launcher.exe"].icon(2).isNull()


def test_u30_picker_detail_without_window_class(demo_ctx: Any, qtbot: Any, picker_windows: dict) -> None:
    dlg = _picker(demo_ctx, qtbot)
    dlg.select_hwnd(3)
    assert "UnityWndClass" not in dlg.detail.text() and "類別" not in dlg.detail.text()
    assert "內容區大小：1280 × 720" in dlg.detail.text()
    item = dlg.tree.currentItem()
    assert "UnityWndClass" in item.toolTip(0)  # still there for the curious, in the tooltip


def test_u39_picker_caption(demo_ctx: Any, qtbot: Any, picker_windows: dict) -> None:
    dlg = _picker(demo_ctx, qtbot, caption="設定精靈 1/5")
    assert dlg.caption.isVisibleTo(dlg) and dlg.caption.text() == "設定精靈 1/5"
    plain = _picker(demo_ctx, qtbot)
    assert not plain.caption.isVisibleTo(plain)


# ----------------------------------------------------------------------------- U29 import card


def _shared_profile() -> Profile:
    p = Profile(name="朋友分享的兌換流程", game="示範遊戲", author="示範作者", description="網頁兌換用",
                suggested_exe="chrome.exe")
    key = make_step(StepType.KEY)
    key.params.keys = "Ctrl+L"
    text = make_step(StepType.TYPE_TEXT)
    text.params.text = "hello"
    ct = make_step(StepType.CLICK_TEXT)
    ct.params.text = "確定|OK"
    ct.params.on_not_found = TimeoutAction.CONTINUE
    p.steps = [make_step(StepType.FOCUS_WINDOW), make_step(StepType.CLICK_POINT), make_step(StepType.TYPE_CODE),
               key, text, make_step(StepType.OCR_CHECK), ct]
    return p


def test_u29_import_card_aligns_numbers_and_labels_the_facts(qtbot: Any) -> None:
    prof = _shared_profile()
    dlg = profiles_dialogs.ImportCardDialog(prof, "share.autopress.json")
    qtbot.addWidget(dlg)
    dlg.show()
    assert dlg.action_labels == prof.action_lines()
    assert len(dlg.action_rows) == len(prof.action_lines())
    xs = {_x(text, dlg) for _icon, text in dlg.action_rows}
    assert len(xs) == 1  # every number starts at the same x (the warning icon has its own column)
    for (icon, text), (line, risky) in zip(dlg.action_rows, prof.action_lines()):
        assert icon.width() == dlg.ICON_W and text.text() == line and not text.text().startswith("⚠")
        assert (icon.pixmap() is not None and not icon.pixmap().isNull()) is risky
        assert text.textFormat() is Qt.TextFormat.PlainText  # literal, never rendered as HTML
    assert dlg.fact_labels["說明"] == "網頁兌換用" and dlg.fact_labels["作者"] == "示範作者"
    assert "chrome.exe" in dlg.fact_labels["作者使用的程式"]
    assert "A-Za" not in dlg.fact_labels["序號格式"] and "英文字母與數字" in dlg.fact_labels["序號格式"]
    assert "「確定」或「OK」" in dlg.action_labels[-1][0] and "|" not in dlg.action_labels[-1][0]


def test_u29_import_card_has_no_empty_band(qtbot: Any) -> None:
    dlg = profiles_dialogs.ImportCardDialog(_shared_profile(), "share.autopress.json")
    qtbot.addWidget(dlg)
    dlg.show()
    assert dlg.minimumSize().height() < 520  # no forced 520 px height any more
    last = dlg.action_rows[-1][1]
    bottom = last.mapTo(dlg, QPoint(0, last.height())).y()
    gap = dlg.check.mapTo(dlg, QPoint(0, 0)).y() - bottom
    assert 0 <= gap < 60, gap  # was ~230 px of nothing between the actions and the check box


def test_u29_click_text_alternatives_in_action_lines() -> None:
    p = Profile()
    ct = make_step(StepType.CLICK_TEXT)
    ct.params.text = "確定|OK|關閉"
    rx = make_step(StepType.CLICK_TEXT)
    rx.params.text = "^(確定|OK)$"
    rx.params.match = TextMatch.REGEX
    lit = make_step(StepType.CLICK_TEXT)
    lit.params.text = r"A\|B"
    p.steps = [ct, rx, lit]
    lines = [t for t, _r in p.action_lines()]
    assert lines[0] == "1. 點擊文字：「確定」、「OK」或「關閉」"
    assert lines[1] == "2. 點擊文字：「^(確定|OK)$」"  # a regex is one pattern, shown verbatim
    assert lines[2] == "3. 點擊文字：「A|B」"  # an escaped bar is a literal bar
    i18n.set_language("en")
    assert [t for t, _r in p.action_lines()][0] == "1. Click text：'確定', 'OK' or '關閉'"


# ----------------------------------------------------------------------------- U30 / U31 plain words


@pytest.mark.parametrize("lang", ["zh-TW", "en"])
def test_u31_format_summary_reads_as_words(lang: str) -> None:
    i18n.set_language(lang)
    for fmt in presets.list_formats():
        s = profiles_dialogs.format_summary(fmt)
        assert "）（" not in s and ") (" not in s and "（字元" not in s, s  # no back-to-back brackets
        assert "A-Z" not in s and "a-z" not in s and "0-9" not in s, s  # never the raw character class
        assert " ·\u00a0" in s  # no-break space after the dot: no line ends on a hanging 「·」
    hoyo = profiles_dialogs.format_summary(presets.get_format("hoyoverse"))
    if lang == "zh-TW":
        assert hoyo == "HoYoverse（原神／星鐵／絕區零） ·\u00a0英文字母與數字 ·\u00a06–\u206016\u00a0碼"
    else:
        assert hoyo == "HoYoverse (Genshin / Star Rail / ZZZ) ·\u00a0letters and digits ·\u00a06–\u206016\u00a0characters"


def test_u30_charset_label() -> None:
    assert presets.charset_label("A-Za-z0-9") == "英文字母與數字"
    assert presets.charset_label("A-Za-z0-9", case_sensitive=False) == "大寫英文與數字"  # upper-cased at import
    assert presets.charset_label("A-Z0-9", False) == "大寫英文與數字"
    assert presets.charset_label("A-HJ-NP-Y0-9", False) == "大寫英文與數字，不含 I、O、Z"
    assert presets.charset_label("0-9") == "數字"
    raw = presets.charset_label("A-F0-9")  # no plain words: as written, never wrapping at a hyphen
    assert raw == "A\u2011F0\u20119" and "-" not in raw
    i18n.set_language("en")
    assert presets.charset_label("A-Za-z0-9") == "letters and digits"
    assert presets.charset_label("A-HJ-NP-Y0-9", False) == "capital letters and digits except I, O and Z"
    assert presets.length_label(presets.get_format("steam")) == "15\u00a0characters"


def test_u30_click_text_step_is_named_without_ocr() -> None:
    assert StepType.CLICK_TEXT.label() == "點擊文字"
    i18n.set_language("en")
    assert StepType.CLICK_TEXT.label() == "Click text"


def test_u30_click_text_summary_lists_the_alternatives() -> None:
    ct = make_step(StepType.CLICK_TEXT)
    ct.params.text = "兌換|Redeem"
    assert ct.summary() == "「兌換」或「Redeem」"
    wt = make_step(StepType.WAIT_TEXT)
    wt.params.text = "兌換成功|完成"
    assert wt.summary() == "等「兌換成功」或「完成」出現"
    ct.params.match = TextMatch.REGEX
    assert ct.summary() == "「兌換|Redeem」"
    i18n.set_language("en")
    ct.params.match = TextMatch.EXACT
    assert ct.summary() == "'兌換' or 'Redeem'"


def test_u30_click_text_hint_mentions_text_recognition(demo_ctx: Any, qtbot: Any) -> None:
    from autopress.ui.step_editor import StepEditor

    ed = StepEditor(demo_ctx)
    qtbot.addWidget(ed)
    ed.set_step(make_step(StepType.CLICK_TEXT), demo_ctx.active_profile(), 3)
    texts = " ".join(lb.text() for lb in ed.form.findChildren(QLabel))
    assert "文字辨識" in texts and "（OCR）" not in ed.header.text()


def test_u30_format_card_shows_the_charset_in_words(page: ProfilesPage) -> None:
    fc = page.format_card
    assert fc.charset.text() == "A-Za-z0-9" and fc.charset_hint.text() == "英文字母與數字"
    fc.case.setChecked(False)
    assert fc.charset_hint.text() == "大寫英文與數字"
    fc.charset.setText("A-F0-9")
    assert "A-Z0-9" in fc.charset_hint.text()  # no words for it: the range rule instead


def test_u30_unknown_privileges_in_the_users_terms(page: ProfilesPage, monkeypatch: pytest.MonkeyPatch) -> None:
    from autopress.win32 import elevation

    patch_target(monkeypatch, window(9, "chrome.exe", "兌換 - Google Chrome"))
    monkeypatch.setattr(elevation, "input_permission", lambda hwnd: "unknown")
    page._refresh_target_status()
    assert page.target_card.status.text() == "已找到：兌換 - Google Chrome · 可能無法輸入"
    assert "無法讀取目標程式的權限" in page.target_card.status.toolTip()


def test_u30_target_summary_keeps_the_window_class_in_the_tooltip(page: ProfilesPage) -> None:
    p = page.working_profile()
    p.target.class_name = "Chrome_WidgetWin_1"
    page.target_card.load(p)
    assert page.target_card.summary.text() == "chrome.exe"
    assert "Chrome_WidgetWin_1" in page.target_card.summary.toolTip()


# ----------------------------------------------------------------------------- U35 editor cards


def test_u35_cards_share_one_label_column(page: ProfilesPage) -> None:
    from autopress.ui.profiles_editor import form_labels

    forms = [c.form for c in (page.basics, page.target_card, page.format_card, page.policy_card)]
    widths = {lb.minimumWidth() for lb in form_labels(forms)}
    assert widths == {page.label_width} and page.label_width > 0
    page.resize(1060, 740)
    page.show()
    body = page.editor_page.widget()
    xs = set()
    for f in forms:
        for r in range(f.rowCount()):
            item = f.itemAt(r, QFormLayout.ItemRole.FieldRole)
            if item is not None and item.widget() is not None:
                xs.add(_x(item.widget(), body))
    assert len(xs) == 1, xs  # every field of the four cards starts at the same x
    texts = [lb.text() for lb in form_labels([page.format_card.form])]
    assert "長度" in texts and not any("不含分隔符號" in t for t in texts)  # the outlier label is short now


def test_u35_active_badge_is_green_and_basics_have_placeholders(page: ProfilesPage) -> None:
    row = page.list.itemWidget(page.list.item(0))
    assert row.badge is not None and row.badge.property("role") == "success"
    assert page.basics.description.placeholderText().endswith("（可留空）")
    assert page.basics.author.placeholderText().endswith("（可留空）")


def test_u35_placeholders_english(demo_ctx: Any, qtbot: Any) -> None:
    from autopress.ui.profiles_editor import BasicsCard

    i18n.set_language("en")
    card = BasicsCard(demo_ctx, lambda: None)
    qtbot.addWidget(card)
    assert "optional" in card.description.placeholderText() and "optional" in card.author.placeholderText()


# ----------------------------------------------------------------------------- U39 wizard progress


def _all_labels(dlg: Any) -> str:
    return " ".join(lb.text() for lb in dlg.findChildren(QLabel)) + " " + dlg.windowTitle()


def test_u39_position_dialog_caption_heading_and_wording(qtbot: Any) -> None:
    item = pw.PositionItem(1, "point", "point", "點一下序號輸入框的位置", False, "點擊位置")
    dlg = pw._PositionDialog(1, 3, item, False, None, progress=(2, 6))
    qtbot.addWidget(dlg)
    assert dlg.caption.isVisibleTo(dlg) and dlg.caption.text() == "設定精靈 2/6"
    assert dlg.heading.text() == "點一下序號輸入框的位置"  # the instruction is the heading
    assert dlg.step_line.text() == "設定檔的第 2 步：點擊位置"
    assert dlg.windowTitle() == "設定精靈"  # no second numbering in the title bar
    assert "凍結" not in _all_labels(dlg) and "暫時定格" in _all_labels(dlg)
    region = pw._PositionDialog(1, 1, pw.PositionItem(4, "region", "region", "框出結果範圍", False), True, None)
    qtbot.addWidget(region)
    assert region.caption.text() == "重新對準 1/1" and "暫時定格" in _all_labels(region)


def test_u39_every_wizard_dialog_has_the_same_head(qtbot: Any, demo_ctx: Any) -> None:
    prof = demo_ctx.active_profile()
    for dlg in (pw._CloseDialog(pw.CLOSE_ESC, None, progress=(3, 5)), pw._KeywordDialog("兌換", None, progress=(1, 5)),
                pw._TestDialog(prof, "MX4T9PK2JR7D", None, progress=(5, 5))):
        qtbot.addWidget(dlg)
        assert dlg.caption.isVisibleTo(dlg) and dlg.caption.text().startswith("設定精靈 ")
        assert dlg.heading.property("role") == "title"
        assert "凍結" not in _all_labels(dlg)
    bare = pw._CloseDialog(pw.CLOSE_OK, None)
    qtbot.addWidget(bare)
    assert not bare.caption.isVisibleTo(bare)
    i18n.set_language("en")
    en = pw._PositionDialog(1, 2, pw.PositionItem(1, "point", "point", "Click the code box", False, "Click position"),
                            False, None)
    qtbot.addWidget(en)
    assert en.caption.text() == "Setup wizard 1/2" and "freezes" not in _all_labels(en)


def test_u39_wizard_counts_every_screen(demo_ctx: Any, qtbot: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from autopress.ui.profiles_page import blank_profile

    attach_main_window(demo_ctx)
    page = ProfilesPage(demo_ctx)
    qtbot.addWidget(page)
    prof = blank_profile(demo_ctx)
    prof.game = "新遊戲"
    demo_ctx.profiles.save(prof)
    page.refresh_list()
    page.open_profile(prof.id)
    shown: list[tuple[str, str]] = []

    def record(what: str, wiz: Any) -> None:
        shown.append((what, wiz.caption()))

    monkeypatch.setattr(pw.SetupWizard, "choose_window",
                        lambda self: record("target", self) or window(31, "game.exe", "My Game"))
    monkeypatch.setattr(pw.SetupWizard, "ask_position", lambda self, n, total, item: record("position", self) or "pick")
    monkeypatch.setattr(pw.SetupWizard, "pick_position",
                        lambda self, item: (record_point(CLIENT, 740, 410) if item.kind == "point"
                                            else record_region(CLIENT, 300, 200, 700, 300), ""))
    monkeypatch.setattr(pw.SetupWizard, "ask_close_choice", lambda self, current: record("close", self) or pw.CLOSE_ESC)
    monkeypatch.setattr(pw.SetupWizard, "preview", lambda self: None)
    monkeypatch.setattr(pw.SetupWizard, "ask_test", lambda self: record("test", self) or None)
    wiz = pw.SetupWizard(page, prof.id)
    assert wiz.run() is True
    assert shown == [("target", "設定精靈 1/5"), ("position", "設定精靈 2/5"), ("position", "設定精靈 3/5"),
                     ("close", "設定精靈 4/5"), ("test", "設定精靈 5/5")]
    assert wiz.progress_log == [(1, 5), (2, 5), (3, 5), (4, 5), (5, 5)]


def test_u39_real_ui_methods_pass_the_progress(demo_ctx: Any, qtbot: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from autopress.ui import window_picker

    attach_main_window(demo_ctx)
    page = ProfilesPage(demo_ctx)
    qtbot.addWidget(page)
    wiz = pw.SetupWizard(page, page.working_profile().id, realign=True)
    wiz.progress = (2, 4)
    seen: dict[str, Any] = {}
    monkeypatch.setattr(window_picker, "pick_target_window", lambda *a, **k: seen.update(k) or None)
    assert wiz.choose_window() is None and seen["caption"] == "重新對準 2/4"
    made: list[Any] = []

    def no_exec(self: Any) -> int:
        made.append(self)
        return 0

    monkeypatch.setattr(pw.QDialog, "exec", no_exec)
    wiz.ask_close_choice(pw.CLOSE_OK)
    wiz.ask_title_keyword("兌換")
    wiz.ask_position(1, 3, pw.PositionItem(1, "point", "point", "點一下", True, "點擊位置"))
    wiz.ask_test()
    assert [d.caption.text() for d in made] == ["重新對準 2/4"] * 4
