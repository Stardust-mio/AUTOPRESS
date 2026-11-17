# OWNED BY ORCH (UI polish of the screenshot review, SPEC 3.2; written by the G7 fix group)
"""Polish of the run screens before they go into the README (UI review items, offscreen). Each
test fails on the behaviour before the fix:

* U2  the ring, the running card's heading and the ring tooltips show one count (processed);
      the position 「第 i / N 筆」 comes from code_started and stays on the decided code
* U6 / U7  the target line is refreshed on show, synced with every preflight report, state first
* U8  a finished code shows its result instead of the last step (Run page and mini bar)
* U9  the setup card is locked during a run (combo, selection, check, refresh, buttons)
* U11 the decision card names its code, does not repeat the read text, is the only 繼續 / 停止
* U12 / U13  mini-bar lines: the info text elides (full text in the tooltip), the step takes the
      free width of a wider bar
* U18 the picker's instruction pill is opaque over the guides
* U19 marker titles carry no number and never cover their badge (edge placement)
* U22 the empty live log says what will appear
* U23 a blocking preflight error is explained next to 開始兌換
* U32 issue rows: level icons, even row heights; the sheet is as tall as its content
* U33 the summary does not repeat the stop reason
* U43 the Run page's profile combo shows the name (game as tooltip), like the Codes page
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QLabel, QLayout, QWidget

from autopress import i18n
from autopress.models import (
    AttemptRecord,
    Attention,
    CodeStatus,
    IssueLevel,
    LogEntry,
    PauseReason,
    PreflightIssue,
    PreflightReport,
    PreviewKind,
    PreviewMark,
    RunState,
    RunSummary,
    StopReason,
)
from autopress.runner import messages
from autopress.ui import run_sheet, theme
from autopress.ui.run_page import RunPage
from tests.data.ui_run.g7_helpers import attach_main_window, patch_target, window

DEMO_TITLE = "示範遊戲 兌換頁 - Google Chrome"


@pytest.fixture
def page(demo_ctx: Any, qtbot: Any) -> RunPage:
    attach_main_window(demo_ctx)
    demo_ctx.settings.countdown_s = 0
    demo_ctx.settings.resume_countdown_s = 0
    p = RunPage(demo_ctx)
    qtbot.addWidget(p)
    return p


@pytest.fixture
def bar(demo_ctx: Any, qtbot: Any) -> Any:
    from autopress.ui.minibar import MiniBar

    b = MiniBar(demo_ctx)
    qtbot.addWidget(b)
    return b


def runnable(ctx: Any) -> list[Any]:
    return ctx.queue.runnable(game_key=ctx.active_profile().game_key())


def shown(widget: QWidget, page: QWidget) -> bool:
    return widget.isVisibleTo(page)


def layout_of(root: QLayout, widget: QWidget) -> QLayout | None:
    """The (nested) layout that holds ``widget`` directly."""
    if root.indexOf(widget) >= 0:
        return root
    for i in range(root.count()):
        child = root.itemAt(i).layout()
        if child is not None:
            found = layout_of(child, widget)
            if found is not None:
                return found
    return None


def stretch_of(root: QLayout, widget: QWidget) -> int:
    lay = layout_of(root, widget)
    assert lay is not None, "widget not in the layout"
    return lay.stretch(lay.indexOf(widget))


# ----------------------------------------------------------------------------- U2


def test_ring_heading_and_position_agree_on_the_decision_screen(page: RunPage) -> None:
    ctx = page.ctx
    s = ctx.session
    first, second = runnable(ctx)[:2]
    s.state_changed.emit(RunState.RUNNING.value, "")
    s.progress.emit(0, 4, -1.0)
    s.code_started.emit(first.id, 0)
    s.code_finished.emit(first.id, AttemptRecord(code_id=first.id, status=CodeStatus.SUCCESS))
    s.progress.emit(1, 4, 30.0)
    s.code_started.emit(second.id, 1)
    card = page.running
    assert card.position.text() == "已處理 1 / 4 筆" and card.ring.done == 1
    assert card.index.text() == "第 2 / 4 筆" and card.code.text() == second.code
    # the runner counts an unknown result as processed BEFORE it pauses for the decision
    s.code_finished.emit(second.id, AttemptRecord(code_id=second.id, status=CodeStatus.REVIEW))
    s.progress.emit(2, 4, 20.0)
    s.state_changed.emit(RunState.PAUSED.value, PauseReason.UNKNOWN_RESULT.value)
    s.attention.emit(Attention(kind=PauseReason.UNKNOWN_RESULT, code_id=second.id, ocr_text="???",
                               message=messages.unknown_result("???")))
    assert card.ring.done == 2 and card.position.text() == "已處理 2 / 4 筆" == card.ring.toolTip()
    assert card.index.text() == "第 2 / 4 筆"  # still the code the decision is about, not the next one
    assert page.attention.code.text() == second.code == card.code.text()
    assert card.counts.counts == {CodeStatus.SUCCESS: 1, CodeStatus.REVIEW: 1}  # the chips sum to the ring


def test_ring_heading_and_position_in_english(page: RunPage) -> None:
    i18n.set_language("en")
    s = page.ctx.session
    item = runnable(page.ctx)[1]
    s.state_changed.emit(RunState.RUNNING.value, "")
    s.progress.emit(1, 4, 30.0)
    s.code_started.emit(item.id, 1)
    assert page.running.position.text() == "1 of 4 processed"
    assert page.running.index.text() == "Code 2 of 4"


def test_minibar_ring_tooltip_says_the_ring_count(bar: Any) -> None:
    bar.set_progress(7, 15, 95.0)
    assert bar.ring.toolTip() == "已處理 7 / 15 筆 · 預估剩餘 1 分 35 秒"
    i18n.set_language("en")
    bar.set_progress(7, 15, 95.0)
    assert bar.ring.toolTip() == "7 of 15 processed · about 1 min 35 s left"


def test_a_new_run_starts_with_an_empty_card(page: RunPage, monkeypatch: pytest.MonkeyPatch, qtbot: Any) -> None:
    monkeypatch.setattr(run_sheet, "show_preflight_sheet", lambda *a: "start")
    ctx = page.ctx
    assert page.start_run()
    item = ctx.session.plan.items[0]
    ctx.session.simulate_code(item.code_id, CodeStatus.SUCCESS, "兌換成功", index=0)
    assert page.running.counts.counts == {CodeStatus.SUCCESS: 1} and page.running.index.text() == "第 1 / 4 筆"
    ctx.session.stop()
    qtbot.waitUntil(page.start_btn.isEnabled, timeout=2000)
    assert page.start_run()
    card = page.running
    assert card.counts.counts == {} and card.index.text() == card.code.text() == card.step.text() == ""
    assert card.position.text() == "已處理 0 / 3 筆"  # the first code is done: 3 left
    ctx.session.stop()


# ----------------------------------------------------------------------------- U6 / U7 / U43


def test_target_line_is_refreshed_when_the_page_is_shown(page: RunPage, monkeypatch: pytest.MonkeyPatch) -> None:
    patch_target(monkeypatch, window(77, "chrome.exe", DEMO_TITLE))
    page.refresh_target()
    assert page.target_label.text() == f"已找到：{DEMO_TITLE}"  # state first: never the part that is cut
    patch_target(monkeypatch, None)  # the browser was closed while another page was shown
    page.show()
    assert page.target_label.text().startswith("找不到目標視窗：")


def test_target_line_says_what_the_preflight_list_says(page: RunPage, monkeypatch: pytest.MonkeyPatch) -> None:
    info = window(77, "chrome.exe", DEMO_TITLE)
    patch_target(monkeypatch, info)
    page.refresh_target()  # the line's own lookup still finds the window ...
    page.ctx.session.preflight_report = PreflightReport(issues=[
        PreflightIssue(IssueLevel.ERROR, "target_not_found", "找不到目標視窗", "", "pick_window")])
    page.recheck()  # ... the newer lookup of the preflight does not: both say "not found"
    assert page.target_label.text().startswith("找不到目標視窗：") and "pick_window" in page.issues.buttons
    patch_target(monkeypatch, None)
    page.ctx.session.preflight_report = PreflightReport(target=info)
    page.recheck()
    assert page.target_label.text() == f"已找到：{DEMO_TITLE}"
    i18n.set_language("en")
    page.recheck()
    assert page.target_label.text() == f"Found: {DEMO_TITLE}"


def test_profile_combo_shows_the_name_with_the_game_as_tooltip(page: RunPage) -> None:
    p = page.ctx.active_profile()
    combo = page.profile_combo
    i = combo.currentIndex()
    assert combo.itemText(i) == p.name  # like the Codes page header (no " · game")
    assert combo.itemData(i, Qt.ItemDataRole.ToolTipRole) == f"遊戲：{p.game}"


# ----------------------------------------------------------------------------- U8


def test_a_finished_code_shows_its_result_not_its_last_step(page: RunPage) -> None:
    s = page.ctx.session
    first, second = runnable(page.ctx)[:2]
    s.state_changed.emit(RunState.RUNNING.value, "")
    s.progress.emit(0, 4, -1.0)
    s.code_started.emit(first.id, 0)
    s.step_started.emit(first.id, 3, "點擊文字（OCR）")
    assert page.running.step.text() == "第 4 步：點擊文字（OCR）"
    s.code_finished.emit(first.id, AttemptRecord(code_id=first.id, status=CodeStatus.SUCCESS))
    s.waiting.emit(6.0)
    assert page.running.step.text() == "結果：成功" and page.running.info.text() == "下一筆 6 秒後"
    s.code_started.emit(second.id, 1)
    s.step_started.emit(second.id, 1, "點一下序號輸入框")
    s.code_finished.emit(second.id, AttemptRecord(code_id=second.id, status=CodeStatus.COOLDOWN))
    assert page.running.step.text() == ""  # rate-limited: retried later, no step runs meanwhile
    assert page.running.counts.counts == {CodeStatus.SUCCESS: 1}


def test_the_mini_bar_shows_the_result_of_a_finished_code(demo_ctx: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from autopress.ui.run_flow import RunFlow

    attach_main_window(demo_ctx)
    demo_ctx.settings.countdown_s = 0
    monkeypatch.setattr(run_sheet, "show_preflight_sheet", lambda *a: "start")
    s = demo_ctx.session
    flow = RunFlow(demo_ctx)
    assert flow.begin(demo_ctx.active_profile())
    first, second = s.plan.items[:2]
    s.code_started.emit(first.code_id, 0)
    s.step_started.emit(first.code_id, 3, "點擊文字（OCR）")
    assert flow.minibar.step_label.text() == "· 點擊文字（OCR）"
    s.code_finished.emit(first.code_id, AttemptRecord(code_id=first.code_id, status=CodeStatus.SUCCESS))
    assert flow.minibar.step_label.text() == "· 結果：成功" and flow.minibar.code_label.text() == first.code
    s.code_started.emit(second.code_id, 1)
    s.step_started.emit(second.code_id, 1, "點一下序號輸入框")
    s.code_finished.emit(second.code_id, AttemptRecord(code_id=second.code_id, status=CodeStatus.COOLDOWN))
    assert flow.minibar.step_label.text() == ""
    s.stop()


# ----------------------------------------------------------------------------- U9


def _setup_widgets(page: RunPage) -> tuple[QWidget, ...]:
    return (page.profile_combo, page.selection, page.recheck_btn, page.refresh_btn, page.start_btn, page.test_btn,
            page.preview_btn, page.change_target_btn, page.edit_btn)


def test_the_setup_card_is_locked_during_a_run(page: RunPage, monkeypatch: pytest.MonkeyPatch, qtbot: Any) -> None:
    monkeypatch.setattr(run_sheet, "show_preflight_sheet", lambda *a: "start")
    ctx = page.ctx
    assert page.start_run()
    assert not any(wd.isEnabled() for wd in _setup_widgets(page))
    page.recheck()  # e.g. the queue changed: still locked
    assert not any(wd.isEnabled() for wd in _setup_widgets(page))
    assert page.hint.text() == "執行中無法變更設定，要變更請先停止。"
    assert page.profile_combo.toolTip() == "執行中無法切換設定檔"
    ctx.session.pause()  # paused: the main window may be back, the run is not over
    page.recheck()
    assert not any(wd.isEnabled() for wd in _setup_widgets(page))
    ctx.session.stop()
    qtbot.waitUntil(lambda: all(wd.isEnabled() for wd in _setup_widgets(page)), timeout=2000)
    assert page.hint.text() == "" and page.profile_combo.toolTip() == ""


def test_the_lock_also_follows_the_run_state_signals(page: RunPage) -> None:
    s = page.ctx.session  # never started: is_active() stays False, only the signals say "running"
    s.state_changed.emit(RunState.RUNNING.value, "")
    page.recheck()
    assert not page.profile_combo.isEnabled() and not page.start_btn.isEnabled()
    s.state_changed.emit(RunState.FINISHED.value, StopReason.USER.value)
    page.recheck()
    assert page.profile_combo.isEnabled() and page.start_btn.isEnabled()


# ----------------------------------------------------------------------------- U11


def test_the_decision_card_names_its_code_and_owns_resume_and_stop(page: RunPage) -> None:
    s = page.ctx.session
    item = runnable(page.ctx)[1]
    read = "本活動序號每人限領一次"
    s.state_changed.emit(RunState.RUNNING.value, "")
    s.code_started.emit(item.id, 1)
    assert shown(page.running.pause_btn, page) and shown(page.running.stop_key, page)
    s.state_changed.emit(RunState.PAUSED.value, PauseReason.UNKNOWN_RESULT.value)
    s.attention.emit(Attention(kind=PauseReason.UNKNOWN_RESULT, code_id=item.id, ocr_text=read,
                               message=messages.unknown_result(read)))
    panel = page.attention
    assert panel.code.text() == item.code and shown(panel.code_row, page)
    texts = [lb.text() for lb in panel.findChildren(QLabel) if shown(lb, page)]
    assert sum(read in t for t in texts) == 1  # in the "text that was read" block only
    assert panel.message.text() == "請選擇這筆序號的結果，或把讀到的文字加入關鍵字。"
    card = page.running
    assert not any(shown(wd, page) for wd in (card.pause_btn, card.pause_key, card.stop_btn, card.stop_key))
    assert shown(panel.resume_btn, page) and shown(panel.stop_btn, page)
    s.state_changed.emit(RunState.RUNNING.value, "")  # resumed
    assert not shown(panel, page) and shown(card.pause_btn, page) and shown(card.stop_btn, page)


def test_a_decision_without_a_known_code_hides_the_code_line(page: RunPage) -> None:
    page.ctx.session.attention.emit(Attention(kind=PauseReason.ERROR, message="發生未預期的錯誤"))
    assert not shown(page.attention.code_row, page)
    assert page.attention.message.text() == "發生未預期的錯誤"


# ----------------------------------------------------------------------------- U12 / U13


def test_minibar_info_line_elides_and_keeps_the_full_text(bar: Any) -> None:
    from autopress.ui.widgets import ElidedLabel

    assert isinstance(bar.info_label, ElidedLabel)
    assert stretch_of(bar.line2.layout(), bar.info_label) == 1
    for st in (CodeStatus.SUCCESS, CodeStatus.USED, CodeStatus.INVALID):
        bar.add_result(st)
    bar.set_cooldown(287)
    assert bar.info_text() == "· 287 秒後重試"  # short next to the chips: the state already says 冷卻中
    full = "偵測到「操作過於頻繁」，287 秒後重試"
    assert bar.info_label.toolTip().startswith(full + "\n") and "F9" in bar.info_label.toolTip()
    bar.set_waiting(6)
    assert bar.info_text() == "· 下一筆 6 秒後" and bar.info_label.toolTip().startswith("下一筆 6 秒後\n")
    bar.show()
    plain = [lb for lb in bar.line2.findChildren(QLabel) if lb.isVisible() and not isinstance(lb, ElidedLabel)
             and lb.fontMetrics().horizontalAdvance(lb.text()) > lb.contentsRect().width() + 1]
    assert plain == []  # nothing on line 2 is cut without an ellipsis
    bar.set_state(RunState.PAUSED.value, PauseReason.FOCUS_LOST.value)
    assert "切回目標視窗後按「繼續」" in bar.info_label.toolTip()


def test_minibar_step_takes_the_free_width_of_a_wider_bar(bar: Any) -> None:
    from autopress.ui import minibar as mb

    assert bar.width() == mb.BAR_W > 600
    assert bar.step_label.maximumWidth() >= 16777215  # no 180 px cap
    assert stretch_of(bar.frame.layout(), bar.step_label) == 1
    bar.set_current("MX4T9PK2JR7D", "等待")
    bar.show()
    # the step label reaches the end of the text column (it gets the spare width, not a spacer)
    assert bar.step_label.geometry().right() >= bar.line2.geometry().right() - 1
    assert bar.bar_size_physical()[0] >= mb.BAR_W
    bar.set_compact(True)
    assert bar.width() == mb.COMPACT_W
    bar.set_compact(False)
    assert bar.width() == mb.BAR_W


# ----------------------------------------------------------------------------- U18


def test_picker_instruction_pill_is_opaque_over_the_guides(qapp: Any) -> None:
    from autopress.ui import overlays
    from autopress.ui.overlays_geom import ScreenGeom
    from autopress.ui.overlays_widgets import PickerOverlay

    picker = overlays.ScreenPicker()
    picker.kind = "region"
    picker.instruction = "第 5 步：框出結果訊息出現的範圍"
    picker.target_rect = (100, 20, 600, 400)  # dashed outline's top edge inside the pill band
    ov = PickerOverlay(picker, ScreenGeom((0, 0, 800, 600), 1.0), np.full((600, 800, 4), 255, np.uint8))
    ov.cursor_local = QPointF(400, 300)  # the vertical crosshair line crosses the centred pill
    img = QImage(800, 600, QImage.Format.Format_ARGB32)
    img.fill(0)
    ov.render(img)
    pill = (28, 32, 39)
    assert img.pixelColor(400, 28).getRgb()[:3] == pill  # on the crosshair line, inside the pill
    assert img.pixelColor(400, 30).getRgb()[:3] == pill
    assert img.pixelColor(330, 28).getRgb()[:3] == pill  # next to it
    assert img.pixelColor(400, 200).getRgb()[:3] != pill  # the guide is still drawn outside the pill
    ov.deleteLater()


# ----------------------------------------------------------------------------- U19


BOUNDS = QRectF(0, 0, 1280, 800)
INNER = BOUNDS.adjusted(2, 2, -2, -2)


def test_point_mark_title_goes_to_the_other_side_near_the_right_edge() -> None:
    from autopress.ui.overlays_widgets import place_point_mark

    c = QPointF(1250, 760)  # e.g. a close button in the corner of a maximised window
    badge, box = place_point_mark(c, 220, 24, BOUNDS)
    ring = QRectF(c.x() - 17, c.y() - 17, 34, 34)
    assert INNER.contains(badge) and INNER.contains(box)
    assert not box.intersects(badge) and not box.intersects(ring)
    assert box.right() <= badge.left() < c.x()  # badge on the ring's left, title left of it
    badge, box = place_point_mark(QPointF(640, 300), 220, 24, BOUNDS)  # the usual place
    assert badge.left() > 640 and box.left() >= badge.right() and badge.bottom() < 300
    badge, box = place_point_mark(QPointF(640, 10), 220, 24, BOUNDS)  # top edge: below the ring
    assert INNER.contains(badge) and INNER.contains(box) and badge.top() > 10 and not box.intersects(badge)
    badge, box = place_point_mark(QPointF(640, 300), 0, 0, BOUNDS)  # no title
    assert box is None and INNER.contains(badge)
    c = QPointF(640, 300)  # a title too long for either side: stacked above the badge, off the ring
    badge, box = place_point_mark(c, 700, 24, BOUNDS)
    ring = QRectF(c.x() - 17, c.y() - 17, 34, 34)
    assert INNER.contains(box) and not box.intersects(badge) and not box.intersects(ring) and box.bottom() <= badge.top()


def test_region_mark_badge_and_title_stay_on_screen() -> None:
    from autopress.ui.overlays_widgets import place_rect_mark

    badge, box = place_rect_mark(QRectF(400, 380, 600, 120), 160, 24, BOUNDS)
    assert badge.bottom() <= 380 and box.left() >= badge.right()  # above the corner, title right
    badge, box = place_rect_mark(QRectF(100, 5, 600, 120), 160, 24, BOUNDS)  # no room above
    assert INNER.contains(badge) and INNER.contains(box) and not box.intersects(badge)
    badge, box = place_rect_mark(QRectF(1200, 300, 70, 50), 220, 24, BOUNDS)  # at the right edge
    assert INNER.contains(badge) and INNER.contains(box) and not box.intersects(badge)


def test_marks_overlay_titles_carry_no_number_and_paint_at_the_edges(qapp: Any) -> None:
    from autopress.ui.overlays_geom import ScreenGeom
    from autopress.ui.overlays_widgets import MarksOverlay

    marks = [PreviewMark(1, "a", PreviewKind.POINT, (640, 300, 1, 1), "點一下序號輸入框", True),
             PreviewMark(4, "b", PreviewKind.REGION, (300, 3, 760, 140), "辨識結果", True),
             PreviewMark(5, "c", PreviewKind.POINT, (1250, 760, 1, 1), "被遮住的位置", False)]
    ov = MarksOverlay(ScreenGeom((0, 0, 1280, 800), 1.0), marks)
    assert [MarksOverlay.title_of(m) for m in marks] == ["點一下序號輸入框", "辨識結果", "被遮住的位置（不在目標上）"]
    img = QImage(1280, 800, QImage.Format.Format_ARGB32)
    img.fill(0)
    ov.render(img)  # paints without errors
    ov.deleteLater()


# ----------------------------------------------------------------------------- U22


def test_the_empty_live_log_says_what_will_appear(qtbot: Any) -> None:
    from autopress.ui.run_widgets import LogView

    view = LogView()
    qtbot.addWidget(view)
    view.resize(420, 200)
    assert view.placeholder_visible()
    assert view.placeholder_text() == "按「開始兌換」或「測試一筆」後，每一筆序號的處理過程和結果會顯示在這裡。"
    img = view.grab().toImage()
    background = img.pixelColor(img.width() - 6, img.height() - 6)
    assert any(img.pixelColor(x, y) != background for x in range(9, 200) for y in range(6, 24))  # painted
    view.add_entry(LogEntry(message="第 1 / 4 筆：MX4T9PK2JR7D"))
    assert not view.placeholder_visible()
    i18n.set_language("en")
    assert view.placeholder_text().startswith("After you press Start or Test one")


# ----------------------------------------------------------------------------- U23


def test_a_blocking_preflight_error_is_explained_next_to_start(page: RunPage) -> None:
    page.ctx.session.preflight_report = PreflightReport(issues=[
        PreflightIssue(IssueLevel.ERROR, "target_not_found", "找不到目標視窗", "", "pick_window"),
        PreflightIssue(IssueLevel.WARNING, "untested_profile", "還沒有測試過", "", "test_one")])
    page.recheck()
    want = "有 1 個問題必須先處理（標示 ✕ 的項目）；按「開始兌換」會再檢查一次。"
    assert page.hint.text() == want and page.start_btn.toolTip() == want
    assert page.start_btn.isEnabled()  # the sheet it opens checks again and blocks (SPEC 2.4)
    i18n.set_language("en")
    page.ctx.session.preflight_report.issues.append(PreflightIssue(IssueLevel.ERROR, "ocr_failed", "OCR failed"))
    page.recheck()
    assert page.hint.text() == "2 problems must be fixed first (marked ✕); Start checks again."
    page.ctx.session.preflight_report = None
    page.recheck()
    assert page.hint.text() == "" and page.start_btn.toolTip() == ""


# ----------------------------------------------------------------------------- U32


def _three_issues() -> list[PreflightIssue]:
    return [PreflightIssue(IssueLevel.ERROR, "target_not_found", "找不到目標視窗", "", "pick_window"),
            PreflightIssue(IssueLevel.WARNING, "untested_profile", "還沒有測試過"),
            PreflightIssue(IssueLevel.INFO, "estimate", "預估約 30 秒")]


def test_issue_rows_have_level_icons_and_even_heights(qtbot: Any) -> None:
    issues = run_sheet.IssueList(lambda _a: None)
    qtbot.addWidget(issues)
    issues.set_issues(_three_issues())
    assert len(issues.marks) == 3
    for mark in issues.marks:
        assert mark.pixmap() is not None and not mark.pixmap().isNull() and not mark.text()
    assert len({m.accessibleName() for m in issues.marks}) == 3 and all(m.accessibleName() for m in issues.marks)
    issues.resize(700, 300)
    issues.show()
    heights = [row.height() for row in issues.rows]
    assert len(set(heights)) == 1 and heights[0] >= theme.CONTROL_H  # with and without a button


def test_preflight_sheet_is_as_tall_as_its_content(demo_ctx: Any, qtbot: Any) -> None:
    plan = demo_ctx.session.build_plan(demo_ctx.active_profile(), demo_ctx.settings)
    sheet = run_sheet.PreflightSheet(demo_ctx, PreflightReport(issues=_three_issues()), plan)
    qtbot.addWidget(sheet)
    assert sheet.minimumHeight() < 380 and sheet.height() < 380  # no fixed 380 px with a blank band
    lay = sheet.layout()
    assert lay.stretch(lay.indexOf(sheet.issue_scroll)) == 0
    sheet.show()
    qtbot.waitUntil(sheet.isVisible, timeout=2000)
    qtbot.wait(50)  # let the layout requests run
    viewport = sheet.issue_scroll.viewport()
    assert viewport.height() >= sheet.issue_list.heightForWidth(viewport.width())  # the whole list is visible
    assert sheet.issue_scroll.verticalScrollBar().maximum() == 0  # three issues: no scroll bar
    sheet.close()
    empty = run_sheet.PreflightSheet(demo_ctx, PreflightReport(), plan)
    qtbot.addWidget(empty)
    assert empty.issue_scroll.isHidden() and empty.height() < sheet.height()


# ----------------------------------------------------------------------------- U33


def test_the_summary_does_not_repeat_the_stop_reason(qtbot: Any) -> None:
    from autopress.ui.run_widgets import SummaryCard

    card = SummaryCard()
    qtbot.addWidget(card)
    card.show_summary(RunSummary(profile_name="示範", total=4, done=4, stop_reason=StopReason.COMPLETED,
                                 message=messages.completed(4)), {CodeStatus.SUCCESS: 4})
    text = card.title.text() + "\n" + card.detail.text()
    assert text.count("完成") == 1 and card.detail.text() == "「示範」已處理 4 / 4 筆"
    card.show_summary(RunSummary(profile_name="示範", total=4, done=1, stop_reason=StopReason.USER,
                                 message=messages.stopped_by_user()), {CodeStatus.SUCCESS: 1})
    assert card.detail.text() == "「示範」已處理 1 / 4 筆"
    card.show_summary(RunSummary(profile_name="示範", total=4, done=3, stop_reason=StopReason.FAILURES,
                                 message=messages.failures_stop(3)), {CodeStatus.FAILED: 3})
    assert card.detail.text().endswith(messages.failures_stop(3))  # advice is kept
    i18n.set_language("en")
    card.show_summary(RunSummary(profile_name="Demo", total=4, done=4, stop_reason=StopReason.COMPLETED,
                                 message=messages.completed(4)), {CodeStatus.SUCCESS: 4})
    assert card.detail.text() == "'Demo': 4 of 4 codes processed"
