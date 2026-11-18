# OWNED BY G7
"""Run page (SPEC 6.4.3): reacts to every RunSession signal, preflight list with action
buttons, attention actions (標記為…, 加入關鍵字…, 開啟紀錄檔, 繼續 / 停止), summary card."""

from __future__ import annotations

from typing import Any

import pytest

from autopress.models import (
    AttemptRecord,
    Attention,
    CodeStatus,
    IssueLevel,
    LogEntry,
    LogLevel,
    PauseReason,
    PreflightIssue,
    PreflightReport,
    ResultClass,
    RunSelection,
    RunState,
    RunSummary,
    StepTestResult,
    StopReason,
)
from autopress.ui import run_sheet
from autopress.ui.run_page import RunPage
from tests.data.ui_run.g7_helpers import attach_main_window


@pytest.fixture
def page(demo_ctx: Any, qtbot: Any) -> RunPage:
    attach_main_window(demo_ctx)
    demo_ctx.settings.countdown_s = 0
    demo_ctx.settings.resume_countdown_s = 0
    p = RunPage(demo_ctx)
    qtbot.addWidget(p)
    return p


def shown(widget: Any, page: RunPage) -> bool:
    return widget.isVisibleTo(page)


def test_idle_page_shows_the_profile_counts_and_the_preflight(page: RunPage) -> None:
    ctx = page.ctx
    assert page.profile_combo.currentData() == ctx.settings.active_profile_id
    assert page.count_label.text() == "未完成 4 筆 · 勾選 4 筆"
    assert page.start_btn.isEnabled() and page.test_btn.isEnabled()
    assert ("preflight", ) == tuple(n for n, _a in ctx.session.calls if n == "preflight")[:1]
    assert page.preflight_empty.text() == "一切就緒。"
    assert not shown(page.running, page) and not shown(page.summary, page)


def test_no_profile_disables_the_buttons_and_says_why(page: RunPage) -> None:
    page.ctx.set_active_profile("")
    page.recheck()
    assert not page.start_btn.isEnabled()
    assert page.hint.text() == "先建立或選擇設定檔，才能開始兌換。"


def test_preflight_issues_with_action_buttons(page: RunPage, monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = page.ctx
    unassigned = ctx.queue.add_codes(["FREEC0DE1234"])  # no game yet
    assert unassigned.added
    ctx.session.preflight_report = PreflightReport(issues=[
        PreflightIssue(IssueLevel.INFO, "unassigned_codes", "1 筆序號尚未指定遊戲，這次不會執行。", "", "assign_codes"),
        PreflightIssue(IssueLevel.WARNING, "untested_profile", "還沒有成功測試過", "", "test_one"),
    ])
    page.recheck()
    assert set(page.issues.buttons) == {"assign_codes", "test_one"}
    assert page.issues.buttons["assign_codes"].text() == "指定給「示範遊戲」"
    page.issues.buttons["assign_codes"].click()
    item = ctx.queue.get(unassigned.added[0])
    assert item.game_key == ctx.active_profile().game_key()


def test_page_reacts_to_every_session_signal(page: RunPage, qtbot: Any) -> None:
    ctx = page.ctx
    s = ctx.session
    item = ctx.queue.runnable(game_key=ctx.active_profile().game_key())[0]
    s.state_changed.emit(RunState.RUNNING.value, "")
    assert shown(page.running, page) and page.running.state.text() == "執行中"
    assert not page.start_btn.isEnabled()
    s.progress.emit(2, 5, 30.0)
    # heading = the ring's count; the position belongs to the code being processed (code_started)
    assert page.running.position.text() == "已處理 2 / 5 筆" and "30 秒" in page.running.eta.text()
    s.code_started.emit(item.id, 2)
    assert page.running.code.text() == item.code and page.running.index.text() == "第 3 / 5 筆"
    s.step_started.emit(item.id, 1, "點一下序號輸入框")
    assert page.running.step.text() == "第 2 步：點一下序號輸入框"
    s.code_finished.emit(item.id, AttemptRecord(code_id=item.id, status=CodeStatus.SUCCESS))
    assert page.running.counts.counts == {CodeStatus.SUCCESS: 1}
    assert page.running.step.text() == "結果：成功"
    s.log.emit(LogEntry(level=LogLevel.WARNING, message="沒有出現「確定」，略過這一步"))
    assert page.log_view.lines()[-1].endswith("!  沒有出現「確定」，略過這一步")
    s.cooldown.emit(12.0)
    assert page.running.info.text() == "偵測到「操作過於頻繁」，12 秒後重試這筆序號。"
    s.waiting.emit(5.0)
    assert page.running.info.text() == "下一筆 5 秒後"
    s.state_changed.emit(RunState.PAUSED.value, PauseReason.FOCUS_LOST.value)
    assert shown(page.paused_banner, page) and "目標視窗失去焦點" in page.paused_banner.text()
    assert page.running.pause_btn.text() == "繼續"
    s.attention.emit(Attention(kind=PauseReason.UNKNOWN_RESULT, message="無法判讀結果：「???」",
                               code_id=item.id, ocr_text="???"))
    assert shown(page.attention, page) and not shown(page.paused_banner, page)
    assert page.attention.ocr_text.text() == "???" and shown(page.attention.mark_row, page)
    s.test_finished.emit(StepTestResult(ok=True, step_index=0, message="找到文字"))
    assert "步驟測試：找到文字" in page.log_view.lines()[-1]
    s.finished.emit(RunSummary(run_id="r1", profile_name="示範", total=5, done=1,
                               counts={CodeStatus.SUCCESS: 1}, stop_reason=StopReason.USER))
    assert shown(page.summary, page) and not shown(page.running, page) and not shown(page.attention, page)
    assert page.summary.title.text() == "執行結束：使用者停止"
    qtbot.waitUntil(page.start_btn.isEnabled, timeout=2000)


def test_attention_mark_and_add_keyword(page: RunPage, monkeypatch: pytest.MonkeyPatch) -> None:
    from autopress.ui import run_widgets

    ctx = page.ctx
    item = ctx.queue.runnable(game_key=ctx.active_profile().game_key())[0]
    att = Attention(kind=PauseReason.UNKNOWN_RESULT, code_id=item.id, ocr_text="序號已達領取上限\n請稍候")
    ctx.session.attention.emit(att)
    page.attention.mark_buttons[CodeStatus.USED].click()
    assert ("resolve_attention", (item.id, CodeStatus.USED, att.ocr_text)) in ctx.session.calls
    assert not page.attention.mark_buttons[CodeStatus.INVALID].isEnabled()
    assert "已使用" in page.attention.resolved.text()

    ctx.session.attention.emit(att)  # a new decision: buttons enabled again
    assert page.attention.mark_buttons[CodeStatus.INVALID].isEnabled()

    def fake_exec(dlg: Any) -> int:
        assert dlg.edit.text() == "序號已達領取上限"  # first line of the OCR text
        dlg.kind.setCurrentIndex(dlg.kind.findData(ResultClass.INELIGIBLE.value))
        dlg.edit.setText("領取上限")
        return 1

    monkeypatch.setattr(run_widgets.KeywordDialog, "exec", fake_exec)
    page.attention.keyword_btn.click()
    stored = ctx.profiles.get(ctx.active_profile().id)
    assert "領取上限" in stored.keywords.groups[ResultClass.INELIGIBLE]
    assert any(n == "update_keywords" for n, _a in ctx.session.calls)
    assert ("resolve_attention", (item.id, CodeStatus.FAILED, att.ocr_text)) in ctx.session.calls


def test_attention_error_offers_the_log_and_resume_uses_the_flow(page: RunPage, monkeypatch: pytest.MonkeyPatch,
                                                                 qtbot: Any) -> None:
    from autopress.ui import run_page as rp

    opened: list[str] = []
    monkeypatch.setattr(rp.QDesktopServices, "openUrl", lambda url: opened.append(url.toLocalFile()) or True)
    monkeypatch.setattr(run_sheet, "show_preflight_sheet", lambda *a: "start")
    ctx = page.ctx
    assert page.start_run()
    ctx.session.pause()
    ctx.session.attention.emit(Attention(kind=PauseReason.ERROR, message="發生未預期的錯誤"))
    assert shown(page.attention.log_btn, page) and not shown(page.attention.mark_row, page)
    page.attention.log_btn.click()
    assert opened and opened[0].replace("\\", "/").endswith("logs")
    page.attention.resume_btn.click()
    qtbot.waitUntil(lambda: ctx.session.state is RunState.RUNNING, timeout=2000)
    page.running.stop_btn.click()
    assert not page.run_flow().is_running()


def test_run_started_on_another_page_is_resumed_and_stopped_through_its_owner(
        page: RunPage, monkeypatch: pytest.MonkeyPatch, qtbot: Any) -> None:
    """Gate G-05 (integration): the Codes page's own RunFlow started the run; the Run page's
    繼續 / 停止 act on that owner (ctx.extras active-flow registry), never a second flow."""
    from autopress.ui import run_flow as rf

    monkeypatch.setattr(run_sheet, "show_preflight_sheet", lambda *a: "start")
    ctx = page.ctx
    owner = rf.RunFlow(ctx)  # what CodesPage._ensure_run_flow creates
    assert owner.begin(ctx.active_profile()) and rf.active_flow(ctx) is owner
    ctx.session.pause()
    ctx.session.attention.emit(Attention(kind=PauseReason.UNKNOWN_RESULT, message="無法判讀", ocr_text="???"))
    assert shown(page.attention, page)
    page.attention.resume_btn.click()
    qtbot.waitUntil(lambda: ctx.session.state is RunState.RUNNING, timeout=2000)
    assert owner.is_running() and page._flow is None  # the page did not create a flow of its own
    page.running.stop_btn.click()
    assert not owner.is_running() and rf.active_flow(ctx) is None


def test_pause_and_stop_buttons_go_through_the_flow(page: RunPage, monkeypatch: pytest.MonkeyPatch, qtbot: Any) -> None:
    monkeypatch.setattr(run_sheet, "show_preflight_sheet", lambda *a: "start")
    ctx = page.ctx
    assert page.start_run()
    page.running.pause_btn.click()
    assert ctx.session.state is RunState.PAUSED
    page.running.pause_btn.click()  # resume: countdown 0 then session.resume
    qtbot.waitUntil(lambda: ctx.session.state is RunState.RUNNING, timeout=2000)
    page.running.stop_btn.click()
    assert ctx.session.state is RunState.FINISHED and shown(page.summary, page)


def test_test_one_uses_the_first_runnable_code(page: RunPage, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run_sheet, "show_preflight_sheet", lambda *a: "start")
    ctx = page.ctx
    first = ctx.queue.runnable(game_key=ctx.active_profile().game_key())[0]
    assert page.test_one()
    build = [a for n, a in ctx.session.calls if n == "build_plan"][-1]
    assert build[2] == (first.id,) and build[3].value == "test_one"
    ctx.session.stop()


def test_test_one_ignores_only_checked_when_the_first_code_is_unticked(page: RunPage,
                                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    """「測試一筆」 on the Run page tests the first pending code even under 「只跑勾選的」 with that
    code unticked (like the Codes page): the page's selection made the plan empty and the sheet
    blocked with "no codes" although the codes exist."""
    plans: list[Any] = []

    def sheet(_ctx: Any, _report: Any, plan: Any, _parent: Any) -> str:
        plans.append(plan)
        return "start"

    monkeypatch.setattr(run_sheet, "show_preflight_sheet", sheet)
    ctx = page.ctx
    first = ctx.queue.runnable(game_key=ctx.active_profile().game_key())[0]
    ctx.queue.set_checked([first.id], False)
    page.selection.setCurrentIndex(1)
    assert page.selection_value() is RunSelection.CHECKED
    assert page.test_one()
    build = [a for n, a in ctx.session.calls if n == "build_plan"][-1]
    assert build[1] is RunSelection.UNFINISHED
    assert build[2] == (first.id,) and build[3].value == "test_one"
    assert [i.code_id for i in plans[-1].items] == [first.id]
    ctx.session.stop()


def test_summary_export_and_retry(page: RunPage, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    from autopress.ui import run_page as rp

    ctx = page.ctx
    ctx.history.append(AttemptRecord(run_id="r9", code="AAAA1111", status=CodeStatus.SUCCESS, finished_at="2026-11-17T10:00:00+08:00"))
    ctx.history.append(AttemptRecord(run_id="other", code="BBBB2222", status=CodeStatus.INVALID))
    failed = ctx.queue.runnable(game_key=ctx.active_profile().game_key())[0]
    ctx.queue.set_status(failed.id, CodeStatus.FAILED, "x")
    ctx.session.finished.emit(RunSummary(run_id="r9", total=2, done=2, counts={CodeStatus.FAILED: 1, CodeStatus.SUCCESS: 1}))
    assert page.summary.retry_btn.isEnabled()
    out = tmp_path / "結果.csv"
    monkeypatch.setattr(rp, "ask_csv_path", lambda parent, name: str(out))
    page.summary.export_btn.click()
    text = out.read_bytes().decode("utf-8-sig")
    assert "AAAA1111" in text and "BBBB2222" not in text
    page.summary.retry_btn.click()
    assert ctx.queue.get(failed.id).status is CodeStatus.PENDING


def test_change_target_saves_the_profile(page: RunPage, monkeypatch: pytest.MonkeyPatch) -> None:
    from autopress.ui import window_picker

    from tests.data.ui_run.g7_helpers import window

    info = window(77, "chrome.exe", "原神兌換 - Google Chrome")
    monkeypatch.setattr(window_picker, "pick_target_window", lambda *a, **k: info)
    page.change_target()
    stored = page.ctx.profiles.get(page.ctx.settings.active_profile_id)
    assert stored.target.exe == "chrome.exe" and stored.target.title == "原神兌換"
    assert not stored.target.allow_same_process
