# OWNED BY G7
"""RunFlow (SPEC 2.4 / 2.6) with tests/fakes.py FakeRunSession and FakeHotkeys: preflight
block, confirm, countdown 0, hotkeys registered / unregistered, hotkey failure dialog, run mode,
masked rects, F8 debounce, resume countdown, F9 cancels the countdown, attention restores the
main window, expand = soft pause, last_test_ok_at after TEST_ONE; the preflight sheet itself."""

from __future__ import annotations

from typing import Any

import pytest
from PyQt6.QtCore import QTimer

from autopress.models import (
    Attention,
    CodeStatus,
    IssueLevel,
    PauseReason,
    PlanMode,
    PreflightIssue,
    PreflightReport,
    RunPlan,
    RunState,
    StopReason,
)
from autopress.ui import run_flow as rf
from autopress.ui import run_sheet
from tests.data.ui_run.g7_helpers import attach_main_window, patch_dialogs


@pytest.fixture
def ctx(demo_ctx: Any) -> Any:
    attach_main_window(demo_ctx)
    demo_ctx.settings.countdown_s = 0
    demo_ctx.settings.resume_countdown_s = 0
    return demo_ctx


@pytest.fixture
def sheets(monkeypatch: pytest.MonkeyPatch) -> list[tuple[PreflightReport, RunPlan]]:
    seen: list[tuple[PreflightReport, RunPlan]] = []

    def fake_sheet(ctx: Any, report: PreflightReport, plan: RunPlan, parent: Any) -> str:
        seen.append((report, plan))
        return "start"

    monkeypatch.setattr(run_sheet, "show_preflight_sheet", fake_sheet)
    return seen


def calls(ctx: Any, name: str) -> list[tuple[Any, ...]]:
    return [args for n, args in ctx.session.calls if n == name]


def test_full_sequence_registers_hotkeys_hides_the_window_and_publishes_the_mask(ctx: Any, sheets: list, qtbot: Any,
                                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    dialogs = patch_dialogs(monkeypatch)
    flow = rf.RunFlow(ctx)
    started: list[int] = []
    ended: list[object] = []
    flow.started.connect(lambda: started.append(1))
    flow.ended.connect(ended.append)
    profile = ctx.active_profile()
    assert flow.begin(profile) is True
    assert sheets and len(sheets[0][1].items) == 4  # the runnable demo codes of this game
    assert dialogs.confirms == []  # 4 codes < confirm_run_over (30)
    assert ctx.hotkeys.registered() == {"pause_resume": "F8", "stop": "F9"}
    assert ctx.main_window.run_mode_calls == [(True, False)]
    assert flow.minibar is not None and flow.minibar.isVisible()
    assert ctx.session.masked_rects == [flow.minibar.frame_rect_physical()]
    assert calls(ctx, "start") and flow.is_running() and started == [1]
    assert rf.active_flow(ctx) is flow
    # the bar follows the session
    ctx.session.progress.emit(1, 4, 20.0)
    code_id = sheets[0][1].items[0].code_id
    ctx.session.simulate_code(code_id, CodeStatus.SUCCESS, "兌換成功")
    assert flow.minibar.counts == {CodeStatus.SUCCESS: 1}
    ctx.session.waiting.emit(6.0)
    assert "6 秒" in flow.minibar.info_text()
    # moving the bar republishes the mask
    n = len(calls(ctx, "set_masked_rects"))
    flow.minibar.moved.emit()
    assert len(calls(ctx, "set_masked_rects")) == n + 1
    # finish
    ctx.session.stop()
    assert ctx.hotkeys.registered() == {}
    assert not flow.minibar.isVisible() and ctx.session.masked_rects == []
    assert ctx.main_window.run_mode_calls[-1] == (False, False)
    assert ctx.main_window.navigated[-1] == "run"
    assert ended and ended[0].stop_reason is StopReason.USER and not flow.is_running()
    assert rf.active_flow(ctx) is None


def test_preflight_errors_block_the_run(ctx: Any, sheets: list) -> None:
    ctx.session.preflight_report = PreflightReport(issues=[PreflightIssue(IssueLevel.ERROR, "target_not_found", "找不到")])
    flow = rf.RunFlow(ctx)
    ended: list[object] = []
    flow.ended.connect(ended.append)
    assert flow.begin(ctx.active_profile()) is False
    assert not calls(ctx, "start") and ctx.hotkeys.registered() == {} and ended == [None]
    assert rf.active_flow(ctx) is None


def test_cancelled_sheet_and_a_sheet_action_rechecks(ctx: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter(["action:assign_codes", "cancel"])
    monkeypatch.setattr(run_sheet, "show_preflight_sheet", lambda *a: next(answers))
    patch_dialogs(monkeypatch)
    flow = rf.RunFlow(ctx)
    assert flow.begin(ctx.active_profile()) is False
    assert len(calls(ctx, "preflight")) == 2  # the action re-ran the check
    assert not calls(ctx, "start")


def test_confirm_over_the_threshold(ctx: Any, sheets: list, monkeypatch: pytest.MonkeyPatch) -> None:
    ctx.settings.confirm_run_over = 2
    dialogs = patch_dialogs(monkeypatch, answers=[False])
    flow = rf.RunFlow(ctx)
    assert flow.begin(ctx.active_profile()) is False
    assert len(dialogs.confirms) == 1 and "4 筆" in dialogs.confirms[0][1]
    assert not calls(ctx, "start") and ctx.hotkeys.registered() == {}


def test_hotkey_failure_opens_a_dialog_and_forces_the_bar(ctx: Any, sheets: list, monkeypatch: pytest.MonkeyPatch) -> None:
    ctx.settings.minibar_enabled = False
    ctx.hotkeys.fail_combos = {"F8"}
    dialogs = patch_dialogs(monkeypatch, answers=[True])
    flow = rf.RunFlow(ctx)
    assert flow.begin(ctx.active_profile()) is True
    assert "快捷鍵 F8 已被其他程式使用" in dialogs.confirms[0][1]
    assert ctx.main_window.run_mode_calls == [(True, False)]  # hidden: the bar is forced on
    assert flow.minibar.isVisible()
    ctx.session.stop()


def test_hotkey_failure_cancel_stops_before_the_countdown(ctx: Any, sheets: list, monkeypatch: pytest.MonkeyPatch) -> None:
    ctx.hotkeys.fail_combos = {"F9"}
    patch_dialogs(monkeypatch, answers=[False])
    flow = rf.RunFlow(ctx)
    assert flow.begin(ctx.active_profile()) is False
    assert ctx.hotkeys.registered() == {} and not calls(ctx, "start")


def test_without_the_mini_bar_the_main_window_is_minimised(ctx: Any, sheets: list) -> None:
    ctx.settings.minibar_enabled = False
    flow = rf.RunFlow(ctx)
    assert flow.begin(ctx.active_profile())
    assert ctx.main_window.run_mode_calls == [(True, True)]
    assert flow.minibar is None and ctx.session.masked_rects == []
    ctx.session.stop()


def test_f9_cancels_the_start_countdown(ctx: Any, sheets: list, qtbot: Any) -> None:
    ctx.settings.countdown_s = 3
    flow = rf.RunFlow(ctx)
    QTimer.singleShot(150, lambda: ctx.hotkeys.triggered.emit("stop"))
    assert flow.begin(ctx.active_profile()) is False
    assert not calls(ctx, "start") and ctx.hotkeys.registered() == {}
    assert ctx.main_window.run_mode_calls == []


def test_countdown_runs_before_the_start(ctx: Any, sheets: list, qtbot: Any) -> None:
    ctx.settings.countdown_s = 1
    flow = rf.RunFlow(ctx)
    seen: list[bool] = []
    QTimer.singleShot(300, lambda: seen.append(flow.countdown.is_running() and not calls(ctx, "start")))
    assert flow.begin(ctx.active_profile()) is True
    assert seen == [True]
    ctx.session.stop()


def test_f8_pauses_and_debounces_after_an_automatic_pause(ctx: Any, sheets: list, qtbot: Any,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [1000.0]
    monkeypatch.setattr(rf, "_now", lambda: clock[0])
    flow = rf.RunFlow(ctx)
    assert flow.begin(ctx.active_profile())
    ctx.hotkeys.triggered.emit("pause_resume")  # running -> pause
    assert calls(ctx, "pause") and ctx.session.state is RunState.PAUSED
    ctx.session._set_state(RunState.RUNNING)
    ctx.session._set_state(RunState.PAUSED, PauseReason.USER_INPUT.value)  # the guard tripped
    clock[0] += 0.5
    n_pause = len(calls(ctx, "pause"))
    ctx.hotkeys.triggered.emit("pause_resume")  # within 1.5 s: counts as pause, never resumes
    assert len(calls(ctx, "pause")) == n_pause + 1 and not calls(ctx, "resume")
    assert ctx.session.state is RunState.PAUSED
    clock[0] += 5.0
    ctx.hotkeys.triggered.emit("pause_resume")  # later: resume through the countdown
    qtbot.waitUntil(lambda: ctx.session.state is RunState.RUNNING, timeout=2000)
    assert calls(ctx, "resume")
    ctx.session.stop()


def test_resume_shows_the_countdown_and_f9_during_it_stops(ctx: Any, sheets: list, qtbot: Any) -> None:
    ctx.settings.resume_countdown_s = 2
    flow = rf.RunFlow(ctx)
    assert flow.begin(ctx.active_profile())
    ctx.session.pause()
    ctx.main_window.run_mode_calls.clear()
    flow.resume()
    assert flow.resume_countdown.is_running()
    assert ctx.main_window.run_mode_calls == [(True, False)]  # hidden again
    assert not calls(ctx, "resume")
    ctx.hotkeys.triggered.emit("stop")
    assert not flow.resume_countdown.is_running()
    assert calls(ctx, "stop") and not flow.is_running() and not calls(ctx, "resume")


def test_resume_countdown_then_session_resume(ctx: Any, sheets: list, qtbot: Any) -> None:
    ctx.settings.resume_countdown_s = 1
    flow = rf.RunFlow(ctx)
    assert flow.begin(ctx.active_profile())
    ctx.session.pause()
    other = rf.RunFlow(ctx)  # e.g. the Run page's flow: resume() is delegated to the owner
    other.resume()
    assert flow.resume_countdown.is_running()
    qtbot.waitUntil(lambda: ctx.session.state is RunState.RUNNING, timeout=3000)
    ctx.session.stop()


def test_attention_restores_the_main_window_only_for_decisions(ctx: Any, sheets: list) -> None:
    flow = rf.RunFlow(ctx)
    assert flow.begin(ctx.active_profile())
    ctx.session.pause()
    ctx.session.attention.emit(Attention(kind=PauseReason.USER_INPUT, message="偵測到滑鼠"))
    assert ctx.main_window.run_mode_calls == [(True, False)] and flow.minibar.isVisible()
    ctx.session.attention.emit(Attention(kind=PauseReason.UNKNOWN_RESULT, message="無法判讀", ocr_text="???"))
    assert ctx.main_window.run_mode_calls[-1] == (False, False)
    assert ctx.main_window.navigated[-1] == "run"
    assert not flow.minibar.isVisible() and ctx.session.masked_rects == []
    ctx.session.stop()


def test_expand_requests_a_soft_pause_then_restores(ctx: Any, sheets: list) -> None:
    flow = rf.RunFlow(ctx)
    assert flow.begin(ctx.active_profile())
    flow.minibar.expandClicked.emit()
    assert calls(ctx, "pause")  # FakeRunSession pauses at once -> PAUSED -> main window back
    assert ctx.main_window.run_mode_calls[-1] == (False, False)
    ctx.session.stop()


def test_the_bar_buttons_pause_resume_and_stop(ctx: Any, sheets: list, qtbot: Any) -> None:
    flow = rf.RunFlow(ctx)
    assert flow.begin(ctx.active_profile())
    flow.minibar.pauseClicked.emit()
    assert ctx.session.state is RunState.PAUSED
    flow.minibar.pauseClicked.emit()
    qtbot.waitUntil(lambda: ctx.session.state is RunState.RUNNING, timeout=2000)
    flow.minibar.stopClicked.emit()
    assert not flow.is_running()


@pytest.mark.parametrize(("status", "stored"), [(CodeStatus.SUCCESS, True), (CodeStatus.USED, True),
                                                 (CodeStatus.FAILED, False), (CodeStatus.REVIEW, False)])
def test_test_one_stores_last_test_ok_at(ctx: Any, sheets: list, status: CodeStatus, stored: bool) -> None:
    profile = ctx.active_profile()
    assert profile.last_test_ok_at == ""
    cid = ctx.queue.runnable(game_key=profile.game_key())[0].id
    flow = rf.RunFlow(ctx)
    assert flow.begin(profile, mode=PlanMode.TEST_ONE, code_ids=[cid])
    assert sheets[0][1].mode is PlanMode.TEST_ONE
    ctx.session.simulate_code(cid, status, "x")
    ctx.session.stop(StopReason.COMPLETED)
    assert bool(ctx.profiles.get(profile.id).last_test_ok_at) is stored


def test_only_one_flow_runs_at_a_time(ctx: Any, sheets: list, monkeypatch: pytest.MonkeyPatch) -> None:
    flow = rf.RunFlow(ctx)
    assert flow.begin(ctx.active_profile())
    toasts: list[tuple[str, str]] = []
    ctx.signals.toast.connect(lambda kind, text: toasts.append((kind, text)))
    other = rf.RunFlow(ctx)
    assert other.begin(ctx.active_profile()) is False
    assert toasts and toasts[0][0] == "warning"
    other.ctx.hotkeys.triggered.emit("stop")  # the other flow ignores it; the owner stops
    assert not flow.is_running()


def test_finish_toast_texts() -> None:
    from autopress.models import RunSummary

    text, kind = rf.summary_text(RunSummary(stop_reason=StopReason.FAILURES), {}, 3)
    assert text == "連續 3 筆失敗，已停止。請檢查設定檔與目標視窗。" and kind == "error"
    text, _k = rf.summary_text(RunSummary(stop_reason=StopReason.RATE_LIMITED), {}, 3)
    assert text.startswith("偵測到「操作過於頻繁」")
    text, kind = rf.summary_text(RunSummary(stop_reason=StopReason.COMPLETED), {CodeStatus.SUCCESS: 2}, 3)
    assert kind == "success" and "成功 2" in text
    text, _k = rf.summary_text(RunSummary(stop_reason=StopReason.FAILSAFE), {}, 3)
    assert "緊急停止" in text


# ----------------------------------------------------------------------------- the sheet


def _plan(ctx: Any) -> RunPlan:
    return ctx.session.build_plan(ctx.active_profile(), ctx.settings)


def test_sheet_with_errors_has_no_start_button(ctx: Any, qtbot: Any) -> None:
    report = PreflightReport(issues=[
        PreflightIssue(IssueLevel.INFO, "estimate", "共 4 筆，每筆間隔 6–8 秒，預估約 30 秒。"),
        PreflightIssue(IssueLevel.ERROR, "target_not_found", "找不到目標視窗", "請先開啟", "pick_window"),
    ])
    sheet = run_sheet.PreflightSheet(ctx, report, _plan(ctx))
    qtbot.addWidget(sheet)
    assert sheet.start_btn is None and "pick_window" in sheet.issue_list.buttons
    sheet.issue_list.buttons["pick_window"].click()
    assert sheet.answer == "action:pick_window"


def test_sheet_warnings_need_a_click(ctx: Any, qtbot: Any) -> None:
    report = PreflightReport(issues=[PreflightIssue(IssueLevel.WARNING, "untested_profile", "還沒有測試過", "", "test_one"),
                                     PreflightIssue(IssueLevel.INFO, "estimate", "預估約 30 秒")])
    sheet = run_sheet.PreflightSheet(ctx, report, _plan(ctx))
    qtbot.addWidget(sheet)
    assert sheet.start_btn is not None and not sheet.start_btn.isEnabled()
    assert sheet.start_btn.text() == "仍要開始"
    sheet.ack.setChecked(True)
    assert sheet.start_btn.isEnabled()
    sheet.start_btn.click()
    assert sheet.answer == "start"


def test_sheet_without_problems_starts_directly(ctx: Any, qtbot: Any) -> None:
    sheet = run_sheet.PreflightSheet(ctx, PreflightReport(), _plan(ctx))
    qtbot.addWidget(sheet)
    assert sheet.ack is None and sheet.start_btn.isEnabled() and sheet.start_btn.text() == "開始兌換"
    assert run_sheet.hotkey_failure_text("F8").startswith("快捷鍵 F8 已被其他程式使用")
