"""The per-code algorithm (SPEC 2.5 - 2.7) with a fake backend: the Runner runs synchronously
(or in a Python thread) with direct signal delivery (G4)."""

from __future__ import annotations

import time
from typing import Any

import pytest

from autopress.models import (
    CodeStatus,
    CoordMode,
    KeywordConfig,
    KeyParams,
    LogLevel,
    PauseReason,
    PlanMode,
    RateLimitAction,
    ResultClass,
    RunPlan,
    RunState,
    StepType,
    StopReason,
    TargetMatch,
    TimeoutAction,
    TitleMatch,
    UnknownAction,
    UnknownParams,
    Step,
    make_step,
    record_point,
    record_region,
)
from autopress.runner import messages as msg
from autopress.win32.input import FailsafeTriggered, ForegroundLost, InputBlocked, PointNotOnTarget, UserActivity
from tests.runner_helpers import (
    FakeWorld,
    SyncRun,
    fast_runner,
    fast_settings,
    make_plan,
    make_profile,
    runner_standins,
    wait_until,
)

pytestmark = pytest.mark.usefixtures("runner_standins", "fast_runner")
_ = (runner_standins, fast_runner)

VALID = {"AAAA-1111", "BBBB-2222", "CCCC-3333"}


def world_with(**kw: Any) -> FakeWorld:
    kw.setdefault("valid", set(VALID))
    return FakeWorld(**kw)


def add_key_step(profile: Any, keys: str = "Esc") -> None:
    s = make_step(StepType.KEY)
    assert isinstance(s.params, KeyParams)
    s.params.keys, s.params.after_ms = keys, 0
    profile.steps.append(s)


# ----------------------------------------------------------------------------- happy path


def test_full_run_statuses_history_progress_and_cleanup() -> None:
    world = world_with(used={"CCCC-3333"})
    plan = make_plan(make_profile(world), ["AAAA-1111", "XXXX-0000", "EXP-9999", "CCCC-3333", "BBBB-2222"])
    r = SyncRun(plan, world).run()
    s = r.summary
    assert s.stop_reason is StopReason.COMPLETED and s.done == 5 and s.total == 5
    assert [d.queue_status for d in r.done()] == [CodeStatus.SUCCESS, CodeStatus.INVALID, CodeStatus.EXPIRED,
                                                  CodeStatus.USED, CodeStatus.SUCCESS]
    assert all(d.persist for d in r.done())
    rec = r.done()[0].record
    assert rec.result is ResultClass.SUCCESS and rec.matched_keyword == "兌換成功" and rec.run_id == plan.run_id
    assert rec.game_key == plan.profile.game_key() and rec.evidence_path and rec.duration_ms >= 0
    assert s.counts == {CodeStatus.SUCCESS: 2, CodeStatus.INVALID: 1, CodeStatus.EXPIRED: 1, CodeStatus.USED: 1}
    prog = r.of("progress")
    assert prog[0] == (0, 5, 0.0) and prog[-1] == (5, 5, 0.0)  # no waits in this profile: estimate 0
    assert [a[0] for a in r.of("code_started")] == ["id0", "id1", "id2", "id3", "id4"]
    b = r.backend
    assert b.keep_awake_calls == [True, False] and b.released == 1 and b.closed
    assert world.submitted == ["AAAA-1111", "XXXX-0000", "EXP-9999", "CCCC-3333", "BBBB-2222"]
    assert r.states()[0] == ("running", "")


def test_no_result_check_gives_submitted() -> None:
    world = world_with()
    r = SyncRun(make_plan(make_profile(world, result_check=False), ["AAAA-1111"]), world).run()
    assert r.done()[0].queue_status is CodeStatus.SUBMITTED and r.done()[0].record.result is None


def test_step_started_titles_and_unknown_steps_skipped() -> None:
    world = world_with()
    prof = make_profile(world)
    prof.steps.insert(2, Step(type=StepType.UNKNOWN, params=UnknownParams(type_name="click_image")))
    r = SyncRun(make_plan(prof, ["AAAA-1111"]), world).run()
    assert r.done()[0].queue_status is CodeStatus.SUCCESS
    titles = [(a[1], a[2]) for a in r.of("step_started")]
    assert titles[0] == (0, "點一下序號輸入框") and 2 not in [i for i, _t in titles]
    assert msg.unknown_steps_skipped(1) in r.logs()


# ----------------------------------------------------------------------------- possibly submitted


def test_guard_trip_before_submit_is_pending_and_retried() -> None:
    world = world_with()
    world.trips.append(["click", 1, ForegroundLost("前景不見了")])  # 2nd click = the submit button
    r = SyncRun(make_plan(make_profile(world), ["AAAA-1111"]), world).run()
    first, second = r.done()
    assert first.queue_status is CodeStatus.PENDING and not first.persist
    assert second.queue_status is CodeStatus.SUCCESS
    assert r.pauses() == [PauseReason.FOCUS_LOST.value]
    assert r.attentions()[0].kind is PauseReason.FOCUS_LOST and r.attentions()[0].message == "前景不見了"
    assert world.submitted == ["AAAA-1111"]  # submitted once, by the retry


def test_guard_trip_after_submit_is_review_and_not_retried() -> None:
    world = world_with()
    prof = make_profile(world)
    add_key_step(prof)  # after ocr_check
    world.trips.append(["key", 0, UserActivity("使用者動了滑鼠")])
    r = SyncRun(make_plan(prof, ["AAAA-1111", "BBBB-2222"]), world).run()
    first = r.done()[0]
    assert first.queue_status is CodeStatus.REVIEW and first.persist
    assert first.queue_message == msg.interrupted_after_submit()
    assert r.pauses()[0] == PauseReason.USER_INPUT.value
    assert world.submitted == ["AAAA-1111", "BBBB-2222"]  # REVIEW is not retried


def test_typing_is_before_submit_index() -> None:
    world = world_with()
    world.trips.append(["type", 3, PointNotOnTarget("點擊位置被「記事本」遮住，已暫停。")])
    r = SyncRun(make_plan(make_profile(world), ["AAAA-1111"]), world).run()
    assert r.done()[0].queue_status is CodeStatus.PENDING
    assert r.pauses() == [PauseReason.POINT_BLOCKED.value] and "記事本" in r.attentions()[0].message


def test_input_blocked_pauses_with_error_attention() -> None:
    world = world_with()
    world.trips.append(["click", 0, InputBlocked(msg.input_blocked())])
    r = SyncRun(make_plan(make_profile(world), ["AAAA-1111"]), world).run()
    att = r.attentions()[0]
    assert att.kind is PauseReason.ERROR and att.message == msg.input_blocked()
    assert r.done()[0].queue_status is CodeStatus.PENDING and r.done()[-1].queue_status is CodeStatus.SUCCESS


# ----------------------------------------------------------------------------- step errors


def test_step_error_before_submit_is_failed() -> None:
    world = world_with()
    prof = make_profile(world, submit="click_text")
    world_no_button = world
    world_no_button.statics.clear()
    prof.steps[2].params.text = "確認送出"  # not on the page: the submit step fails before any input
    prof.steps[2].params.timeout_ms = 0
    r = SyncRun(make_plan(prof, ["AAAA-1111"]), world).run()
    d = r.done()[0]
    assert d.queue_status is CodeStatus.FAILED and d.queue_message == msg.text_not_found("確認送出")
    assert d.persist and not world.submitted


def test_step_error_after_submit_without_result_is_review() -> None:
    world = world_with()
    prof = make_profile(world, result_check=False)
    d = make_step(StepType.CLICK_TEXT)
    d.params.text, d.params.timeout_ms, d.params.on_not_found = "確定", 0, TimeoutAction.FAIL
    prof.steps.append(d)
    r = SyncRun(make_plan(prof, ["AAAA-1111"]), world).run()
    out = r.done()[0]
    assert out.queue_status is CodeStatus.REVIEW
    assert out.queue_message == msg.failed_after_submit(msg.text_not_found("確定"))


def test_step_error_after_a_result_keeps_the_result() -> None:
    world = world_with()
    prof = make_profile(world)
    d = make_step(StepType.CLICK_TEXT)
    d.params.text, d.params.timeout_ms = "確定", 0
    prof.steps.append(d)
    r = SyncRun(make_plan(prof, ["AAAA-1111"]), world).run()
    out = r.done()[0]
    assert out.queue_status is CodeStatus.SUCCESS and out.record.result is ResultClass.SUCCESS
    warnings = [a[0] for a in r.of("log") if a[0].level is LogLevel.WARNING]
    assert any(e.message == msg.text_not_found("確定") for e in warnings)


# ----------------------------------------------------------------------------- pauses


def test_vanished_window_pauses_target_lost_and_retries() -> None:
    world = world_with()
    world.hooks["char"] = lambda w: (setattr(w, "alive", False), w.hooks.pop("char"))

    def revive(run: SyncRun, reason: str) -> None:
        run.world.alive = True
        run.control.request_resume()

    r = SyncRun(make_plan(make_profile(world), ["AAAA-1111"]), world, on_pause=revive).run()
    assert r.pauses() == [PauseReason.TARGET_LOST.value]
    assert r.attentions()[0].message == msg.target_closed()
    assert [d.queue_status for d in r.done()] == [CodeStatus.PENDING, CodeStatus.SUCCESS]


def test_tab_change_inside_a_code_pauses_before_the_next_input_step() -> None:
    """Gate G-04: a browser keeps its HWND when the active tab changes; the title is checked
    again right before every step that sends input, so nothing is typed into the other tab."""
    world = world_with()
    world.hooks["click"] = lambda w: (setattr(w, "title", "論壇 - 其他分頁"), w.hooks.pop("click"))

    def back(run: SyncRun, reason: str) -> None:
        run.world.title = "測試遊戲 - 兌換"
        run.control.request_resume()

    r = SyncRun(make_plan(make_profile(world), ["AAAA-1111"]), world, on_pause=back).run()
    assert r.pauses() == [PauseReason.TITLE_CHANGED.value]
    assert r.attentions()[0].message == msg.title_changed()
    assert [d.queue_status for d in r.done()] == [CodeStatus.PENDING, CodeStatus.SUCCESS]
    assert world.typed_text() == "AAAA-1111"  # typed once, after the user switched back


def test_another_matching_window_is_used_only_after_confirmation() -> None:
    """Gate G-03: when the run's window is gone, a different matching window (e.g. another browser
    window whose tab title also contains the keyword) is never used silently."""
    world = world_with()
    world.hooks["char"] = lambda w: (setattr(w, "alive", False), w.hooks.pop("char"))
    seen: list[str] = []

    def new_window(run: SyncRun, reason: str) -> None:
        seen.append(reason)
        if len(seen) == 1:  # the window was closed; another one with a matching title opens
            run.world.hwnd, run.world.pid, run.world.alive = 7777, 8888, True
            run.world.foreground = 7777
        run.control.request_resume()

    r = SyncRun(make_plan(make_profile(world), ["AAAA-1111"]), world, on_pause=new_window).run()
    assert r.pauses() == [PauseReason.TARGET_LOST.value] * 2
    assert r.attentions()[1].message == msg.target_rebind(world.title)
    assert [d.queue_status for d in r.done()] == [CodeStatus.PENDING, CodeStatus.SUCCESS]


def test_window_of_a_forbidden_program_is_never_used() -> None:
    world = world_with(exe_path="C:/Windows/explorer.exe")
    prof = make_profile(world)
    prof.target = TargetMatch(exe="", title=world.title, title_mode=TitleMatch.EXACT)
    r = SyncRun(make_plan(prof, ["AAAA-1111"]), world, on_pause="stop").run()
    assert r.pauses() == [PauseReason.TARGET_LOST.value]
    assert not world.actions and r.summary.stop_reason is StopReason.USER


def test_target_missing_before_a_code_pauses_target_lost() -> None:
    world = world_with(alive=False)

    def revive(run: SyncRun, reason: str) -> None:
        run.world.alive = True
        run.control.request_resume()

    r = SyncRun(make_plan(make_profile(world), ["AAAA-1111"]), world, on_pause=revive).run()
    assert r.pauses() == [PauseReason.TARGET_LOST.value]
    assert "找不到目標視窗" in r.attentions()[0].message
    assert r.done()[0].queue_status is CodeStatus.SUCCESS


def test_unexpected_exception_pauses_with_error() -> None:
    world = world_with()

    def boom(w: FakeWorld) -> None:
        w.hooks.pop("click")
        raise ZeroDivisionError("boom")

    world.hooks["click"] = boom
    r = SyncRun(make_plan(make_profile(world), ["AAAA-1111"]), world).run()
    att = r.attentions()[0]
    assert att.kind is PauseReason.ERROR and att.message == msg.unexpected_error("ZeroDivisionError: boom")
    assert [d.queue_status for d in r.done()] == [CodeStatus.PENDING, CodeStatus.SUCCESS]


def test_title_change_pauses_before_the_next_code() -> None:
    world = world_with()

    def change(w: FakeWorld) -> None:
        if len(w.submitted) == 1:
            w.title = "新分頁 - Google"

    world.hooks["submit"] = change

    def restore(run: SyncRun, reason: str) -> None:
        run.world.title = "測試遊戲 - 兌換"
        run.control.request_resume()

    r = SyncRun(make_plan(make_profile(world), ["AAAA-1111", "XXXX-0000"]), world, on_pause=restore).run()
    assert r.pauses() == [PauseReason.TITLE_CHANGED.value]
    assert r.attentions()[0].message == msg.title_changed()
    assert [d.queue_status for d in r.done()] == [CodeStatus.SUCCESS, CodeStatus.INVALID]


def test_size_change_pauses_and_resume_accepts_the_new_size() -> None:
    world = world_with()
    world.hooks["submit"] = lambda w: setattr(w, "client", (100, 50, 1024, 600)) if len(w.submitted) == 1 else None
    prof = make_profile(world)
    prof.coord_mode = CoordMode.OFFSET  # the fake page does not scale with the window
    r = SyncRun(make_plan(prof, ["AAAA-1111", "XXXX-0000", "EXP-1234"]), world).run()
    assert r.pauses() == [PauseReason.SIZE_CHANGED.value]
    assert r.attentions()[0].message == msg.size_changed("1280×720", "1024×600")
    assert r.summary.done == 3


def test_blank_capture_pauses_capture_blank() -> None:
    world = world_with(blank=True)

    def unblank(run: SyncRun, reason: str) -> None:
        run.world.blank = False
        run.control.request_resume()

    r = SyncRun(make_plan(make_profile(world), ["AAAA-1111"]), world, on_pause=unblank).run()
    assert r.pauses() == [PauseReason.CAPTURE_BLANK.value]
    assert r.attentions()[0].message == msg.capture_blank()
    assert r.done()[-1].queue_status is CodeStatus.SUCCESS


def test_focus_failure_pauses_focus_lost() -> None:
    world = world_with(foreground=999, focus_ok=False)

    def allow(run: SyncRun, reason: str) -> None:
        run.world.focus_ok = True
        run.control.request_resume()

    r = SyncRun(make_plan(make_profile(world), ["AAAA-1111"]), world, on_pause=allow).run()
    assert r.pauses() == [PauseReason.FOCUS_LOST.value]
    assert r.attentions()[0].message == msg.focus_failed()
    assert r.done()[0].queue_status is CodeStatus.SUCCESS


def test_resume_resets_input_baseline() -> None:
    world = world_with()
    world.trips.append(["click", 0, ForegroundLost("x")])
    r = SyncRun(make_plan(make_profile(world), ["AAAA-1111"]), world).run()
    assert r.backend.baseline_resets >= 2  # run start + resume


def test_soft_pause_finishes_the_current_code_first() -> None:
    world = world_with()
    holder: dict[str, SyncRun] = {}
    world.hooks["submit"] = lambda w: holder["r"].control.request_pause() if len(w.submitted) == 1 else None
    r = SyncRun(make_plan(make_profile(world), ["AAAA-1111", "XXXX-0000"]), world)
    holder["r"] = r
    r.run()
    names = [(n, a[0] if n == "state_changed" else "") for n, a in r.events if n in ("code_done", "state_changed")]
    i_done = names.index(("code_done", ""))
    i_pause = names.index(("state_changed", "paused"))
    assert i_done < i_pause  # the first code got its result before the pause
    assert r.pauses() == [PauseReason.USER.value] and not r.attentions()
    assert [d.queue_status for d in r.done()] == [CodeStatus.SUCCESS, CodeStatus.INVALID]


def test_stop_while_paused_ends_the_run() -> None:
    world = world_with()
    world.trips.append(["click", 1, ForegroundLost("x")])
    r = SyncRun(make_plan(make_profile(world), ["AAAA-1111", "BBBB-2222"]), world, on_pause="stop").run()
    assert r.summary.stop_reason is StopReason.USER
    assert [d.queue_status for d in r.done()] == [CodeStatus.PENDING]
    assert world.submitted == []


# ----------------------------------------------------------------------------- policy


def test_rate_limit_cooldown_then_retry_same_code() -> None:
    world = world_with(rate_limit=1)
    prof = make_profile(world)
    prof.policy.cooldown_s = 0.3
    prof.policy.max_cooldowns = 1
    world.hooks["submit"] = lambda w: None
    r = SyncRun(make_plan(prof, ["AAAA-1111", "BBBB-2222"]), world)
    # the second submit is rate-limited; reset the page's window during the cool-down
    r.runner.cooldown.connect(lambda s: setattr(world, "_submit_times", []))
    r.run()
    statuses = [(d.record.code, d.queue_status) for d in r.done()]
    assert statuses == [("AAAA-1111", CodeStatus.SUCCESS), ("BBBB-2222", CodeStatus.COOLDOWN),
                        ("BBBB-2222", CodeStatus.SUCCESS)]
    assert r.done()[1].queue_message == msg.rate_limit_cooldown(0.3) and r.done()[1].persist
    assert ("cooldown", "") in r.states()
    cds = [a[0] for a in r.of("cooldown")]
    assert cds[0] > 0 and cds[-1] == 0.0
    assert r.summary.stop_reason is StopReason.COMPLETED


def test_rate_limit_again_after_cooldown_stops() -> None:
    world = world_with(rate_limit=1, persist=False)
    prof = make_profile(world, only_new_text=False)  # the same rate-limit text twice in a row
    prof.policy.cooldown_s = 0.1
    prof.policy.max_cooldowns = 1
    r = SyncRun(make_plan(prof, ["AAAA-1111", "BBBB-2222", "CCCC-3333"]), world).run()
    assert r.summary.stop_reason is StopReason.RATE_LIMITED
    assert r.summary.message == msg.rate_limit_stop()
    last = r.done()[-1]
    assert last.queue_status is CodeStatus.PENDING and last.record.status is CodeStatus.COOLDOWN and last.persist
    assert "CCCC-3333" not in world.submitted


def test_rate_limit_stop_policy() -> None:
    world = world_with(rate_limit=1)
    prof = make_profile(world)
    prof.policy.on_rate_limit = RateLimitAction.STOP
    r = SyncRun(make_plan(prof, ["AAAA-1111", "BBBB-2222"]), world).run()
    assert r.summary.stop_reason is StopReason.RATE_LIMITED and ("cooldown", "") not in r.states()


def test_failure_counter_stops_the_run() -> None:
    world = world_with()
    prof = make_profile(world, submit="click_text")
    prof.steps[2].params.text, prof.steps[2].params.timeout_ms = "確認送出", 0
    prof.policy.stop_after_failures = 2
    r = SyncRun(make_plan(prof, ["AAAA-1111", "BBBB-2222", "CCCC-3333"]), world).run()
    assert r.summary.stop_reason is StopReason.FAILURES and r.summary.message == msg.failures_stop(2)
    assert [d.queue_status for d in r.done()] == [CodeStatus.FAILED, CodeStatus.FAILED]
    assert ("stopping", "failures") in r.states()


def test_success_resets_the_failure_counter() -> None:
    world = world_with()
    prof = make_profile(world, result_check=True, only_new_text=False)
    prof.policy.stop_after_failures = 2
    prof.policy.on_unknown = UnknownAction.CONTINUE
    world.persist = False
    codes = ["XXXX-0001", "AAAA-1111", "XXXX-0002"]
    world.hooks["submit"] = lambda w: setattr(w, "pending", None) if w.submitted[-1].startswith("XXXX") else None
    r = SyncRun(make_plan(prof, codes), world).run()  # unknown, success, unknown -> never 2 in a row
    assert r.summary.stop_reason is StopReason.COMPLETED
    assert [d.queue_status for d in r.done()] == [CodeStatus.REVIEW, CodeStatus.SUCCESS, CodeStatus.REVIEW]


def test_invalid_streak_pauses_and_resume_resets() -> None:
    world = world_with(persist=False)
    prof = make_profile(world, only_new_text=False)
    prof.policy.pause_after_invalid = 2
    r = SyncRun(make_plan(prof, ["X1XX-0001", "X2XX-0002", "X3XX-0003", "X4XX-0004", "X5XX-0005"]), world).run()
    assert r.pauses() == [PauseReason.INVALID_STREAK.value, PauseReason.INVALID_STREAK.value]
    assert r.attentions()[0].message == msg.invalid_streak(2)
    assert r.summary.done == 5


@pytest.mark.parametrize("policy", [UnknownAction.PAUSE, UnknownAction.CONTINUE, UnknownAction.STOP])
def test_unknown_result_policy(policy: UnknownAction) -> None:
    world = world_with(persist=False)
    world.hooks["submit"] = lambda w: setattr(w, "pending", (time.monotonic(), "請先登入帳號", "invalid"))
    prof = make_profile(world)
    prof.policy.on_unknown = policy
    prof.policy.stop_after_failures = 0
    r = SyncRun(make_plan(prof, ["AAAA-1111", "BBBB-2222"]), world).run()
    first = r.done()[0]
    assert first.queue_status is CodeStatus.REVIEW and first.record.result is ResultClass.UNKNOWN
    assert first.queue_message == "請先登入帳號"
    if policy is UnknownAction.PAUSE:
        att = r.attentions()[0]
        assert att.kind is PauseReason.UNKNOWN_RESULT and att.ocr_text == "請先登入帳號"
        assert att.message == msg.unknown_result("請先登入帳號") and att.evidence_path and att.step_index == 3
        assert r.pauses()[0] == PauseReason.UNKNOWN_RESULT.value and r.summary.done == 2
    elif policy is UnknownAction.CONTINUE:
        assert not r.attentions() and not r.pauses() and r.summary.done == 2
    else:
        assert r.attentions()[0].kind is PauseReason.UNKNOWN_RESULT
        assert r.summary.stop_reason is StopReason.ERROR and r.summary.done == 1


def test_update_keywords_applies_to_remaining_codes() -> None:
    world = world_with(persist=False)
    world.hooks["submit"] = lambda w: setattr(w, "pending", (time.monotonic(), "獎勵已入帳", "x"))
    prof = make_profile(world, only_new_text=False)  # both codes show the same text
    prof.policy.on_unknown = UnknownAction.CONTINUE
    holder: dict[str, SyncRun] = {}

    def add_keyword(rr: Any, *_a: Any) -> None:
        kw = KeywordConfig()
        kw.groups[ResultClass.SUCCESS].append("已入帳")
        holder["r"].shared.set_keywords(kw)

    r = SyncRun(make_plan(prof, ["AAAA-1111", "BBBB-2222"]), world)
    holder["r"] = r
    r.runner.code_done.connect(add_keyword)
    r.run()
    assert [d.queue_status for d in r.done()] == [CodeStatus.REVIEW, CodeStatus.SUCCESS]


def test_shared_masked_rects_reach_the_run() -> None:
    world = world_with()
    prof = make_profile(world)
    prof.policy.on_unknown = UnknownAction.CONTINUE
    r = SyncRun(make_plan(prof, ["AAAA-1111"]), world)
    r.shared.set_masked_rects([world.result_rect])
    r.run()
    assert r.done()[0].queue_status is CodeStatus.REVIEW  # the bar covered the message


# ----------------------------------------------------------------------------- waits, timing, abort


def test_waiting_signal_between_codes_not_after_the_last() -> None:
    world = world_with()
    prof = make_profile(world)
    prof.policy.interval_min_s = prof.policy.interval_max_s = 0.3
    r = SyncRun(make_plan(prof, ["AAAA-1111", "BBBB-2222"]), world).run()
    names = [n for n, _a in r.events if n in ("waiting", "code_started", "run_finished")]
    first_wait = names.index("waiting")
    assert names.index("code_started") < first_wait < len(names) - 1 - names[::-1].index("code_started")
    waits = [a[0] for a in r.of("waiting")]
    assert 0.2 < waits[0] <= 0.3 and waits[-1] == 0.0
    assert names[-1] == "run_finished" and names[-2] != "waiting"


def test_minimum_interval_is_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    import autopress.runner.waits as waits

    monkeypatch.setattr(waits, "MIN_INTERVAL_S", 0.4)
    world = world_with()
    prof = make_profile(world)  # interval 0 in the profile
    t0 = time.monotonic()
    SyncRun(make_plan(prof, ["AAAA-1111", "BBBB-2222"]), world).run()
    assert time.monotonic() - t0 >= 0.39


def test_stop_and_pause_react_within_100ms_while_waiting() -> None:
    world = world_with()
    prof = make_profile(world)
    prof.policy.interval_min_s = prof.policy.interval_max_s = 30.0
    r = SyncRun(make_plan(prof, ["AAAA-1111", "BBBB-2222"]), world, on_pause=None)
    th = r.start_thread()
    assert wait_until(lambda: len(r.of("waiting")) > 0)
    t0 = time.monotonic()
    r.control.request_pause()
    assert wait_until(lambda: ("paused", "user") in r.states(), 1.0)
    assert time.monotonic() - t0 < 0.1
    r.control.request_resume()
    assert wait_until(lambda: r.states()[-1] == ("running", ""), 1.0)
    time.sleep(0.05)
    t1 = time.monotonic()
    r.control.request_stop()
    th.join(2)
    assert not th.is_alive() and time.monotonic() - t1 < 0.15
    assert r.summary.stop_reason is StopReason.USER and r.summary.done == 1


def test_failsafe_in_a_wait_aborts_and_releases() -> None:
    world = world_with()
    prof = make_profile(world)
    prof.policy.interval_min_s = prof.policy.interval_max_s = 30.0
    r = SyncRun(make_plan(prof, ["AAAA-1111", "BBBB-2222"]), world)
    th = r.start_thread()
    assert wait_until(lambda: len(r.of("waiting")) > 0)
    t0 = time.monotonic()
    world.failsafe = True
    th.join(2)
    assert time.monotonic() - t0 < 0.15
    assert r.summary.stop_reason is StopReason.FAILSAFE and r.summary.message == msg.failsafe_stop()
    assert r.backend.released == 1


def test_failsafe_during_a_step_stops_with_item_pending() -> None:
    world = world_with()
    world.trips.append(["type", 0, FailsafeTriggered("corner")])
    r = SyncRun(make_plan(make_profile(world), ["AAAA-1111", "BBBB-2222"]), world).run()
    assert r.summary.stop_reason is StopReason.FAILSAFE
    assert [d.queue_status for d in r.done()] == [CodeStatus.PENDING] and not r.done()[0].persist


def test_user_input_during_interval_trips_at_the_next_injection() -> None:
    """Gate G-07: input during a wait never pauses by itself (the per-slice tick checks only the
    failsafe); the guard trips at the next code's first click, before anything is sent, and that
    code is retried after the resume."""
    world = world_with()
    prof = make_profile(world)
    prof.policy.interval_min_s = prof.policy.interval_max_s = 0.5
    r = SyncRun(make_plan(prof, ["AAAA-1111", "XXXX-0000"]), world)
    r.runner.waiting.connect(lambda s: setattr(world, "user_active", True) if s > 0.3 else None)
    r.run()
    assert r.pauses() == [PauseReason.USER_INPUT.value]
    assert r.attentions()[0].message == msg.user_input()
    assert [d.queue_status for d in r.done()] == [CodeStatus.SUCCESS, CodeStatus.PENDING, CodeStatus.INVALID]
    assert not r.done()[1].persist  # interrupted before submitting: not written to the history


def test_user_input_after_submit_keeps_the_result_read() -> None:
    """Gate G-07: moving the mouse while ocr_check waits for the result does not turn the code
    into REVIEW; the result is read, and the trip happens at the next code's first injection."""
    world = world_with()
    prof = make_profile(world)
    oc_index = next(i for i, st in enumerate(prof.steps) if st.type is StepType.OCR_CHECK)
    prof.steps[oc_index].params.initial_delay_ms = 120
    r = SyncRun(make_plan(prof, ["AAAA-1111", "XXXX-0000"]), world)
    r.runner.step_started.connect(lambda _cid, idx, _t: setattr(world, "user_active", True) if idx == oc_index else None)
    r.run()
    statuses = [d.queue_status for d in r.done()]
    assert statuses[0] is CodeStatus.SUCCESS and r.done()[0].persist
    assert CodeStatus.REVIEW not in statuses
    assert PauseReason.USER_INPUT.value in r.pauses()
    assert statuses[-1] is CodeStatus.INVALID


def _unknown_world() -> Any:
    world = world_with()
    world.hooks["submit"] = lambda w: setattr(w, "pending", (time.monotonic(), "獎勵已入帳", "x"))
    return world


def test_unknown_results_resolved_by_the_user_use_the_chosen_status_for_the_counters() -> None:
    """Gate G-11: the failure counter uses the status chosen in the attention (resolve_attention),
    so unknown results the user confirms as successes never stop the run with FAILURES."""
    world = _unknown_world()
    prof = make_profile(world)
    prof.policy.stop_after_failures = 2

    def resolve(run: SyncRun, reason: str) -> None:
        if reason == PauseReason.UNKNOWN_RESULT.value:
            run.shared.set_resolved(run.of("code_started")[-1][0], CodeStatus.SUCCESS)
        run.control.request_resume()

    r = SyncRun(make_plan(prof, ["AAAA-1111", "BBBB-2222", "CCCC-3333"]), world, on_pause=resolve).run()
    assert r.summary.stop_reason is StopReason.COMPLETED
    assert r.pauses() == [PauseReason.UNKNOWN_RESULT.value] * 3


def test_unknown_results_left_unresolved_still_stop_after_the_failure_limit() -> None:
    world = _unknown_world()
    prof = make_profile(world)
    prof.policy.stop_after_failures = 2
    r = SyncRun(make_plan(prof, ["AAAA-1111", "BBBB-2222", "CCCC-3333"]), world).run()
    assert r.summary.stop_reason is StopReason.FAILURES
    assert r.pauses() == [PauseReason.UNKNOWN_RESULT.value] * 2  # the decision comes before the stop


def test_eta_uses_measured_average() -> None:
    world = world_with()
    prof = make_profile(world)
    prof.policy.interval_min_s = prof.policy.interval_max_s = 0.2
    r = SyncRun(make_plan(prof, ["AAAA-1111", "BBBB-2222", "CCCC-3333"]), world).run()
    prog = r.of("progress")
    assert prog[1][0] == 1 and 0 < prog[1][2] < 5  # 2 codes left at ~0.2-0.3 s each
    assert prog[-1][2] == 0.0


# ----------------------------------------------------------------------------- step tests


def test_step_test_dry_run_sends_nothing() -> None:
    world = world_with(foreground=999)
    prof = make_profile(world)
    plan = RunPlan(profile=prof, mode=PlanMode.TEST_STEP, step_index=0, dry_run=True, settings=fast_settings())
    r = SyncRun(plan, world).run()
    res = r.test_result
    assert res.ok and res.point == world.center(world.box_rects()[0]) and res.step_index == 0
    assert not [a for a in world.actions if a[0] in ("click", "char")]
    assert r.backend.keep_awake_calls == [] and not r.of("run_finished")


def test_step_test_real_types_the_sample_code() -> None:
    world = world_with()
    world.focused = 0
    prof = make_profile(world)
    plan = RunPlan(profile=prof, mode=PlanMode.TEST_STEP, step_index=1, sample_code="TEST-1234",
                   settings=fast_settings())
    res = SyncRun(plan, world).run().test_result
    assert res.ok and world.boxes == ["TEST-1234"] and res.duration_ms >= 0


def test_step_test_ocr_check_and_errors() -> None:
    world = world_with(result_text="兌換碼已過期")
    prof = make_profile(world)
    plan = RunPlan(profile=prof, mode=PlanMode.TEST_STEP, step_index=3, dry_run=True, settings=fast_settings())
    res = SyncRun(plan, world).run().test_result
    assert res.result is ResultClass.EXPIRED and res.rect is not None and "兌換碼已過期" in res.ocr_text
    world2 = world_with(alive=False)
    res2 = SyncRun(RunPlan(profile=prof, mode=PlanMode.TEST_STEP, step_index=0, settings=fast_settings()),
                   world2).run().test_result
    assert not res2.ok and "找不到目標視窗" in res2.message


def test_step_test_stop() -> None:
    world = world_with()
    prof = make_profile(world)
    w = make_step(StepType.WAIT)
    w.params.ms = 10000
    prof.steps.append(w)
    plan = RunPlan(profile=prof, mode=PlanMode.TEST_STEP, step_index=len(prof.steps) - 1, settings=fast_settings())
    r = SyncRun(plan, world)
    th = r.start_thread()
    time.sleep(0.2)
    r.control.request_stop()
    th.join(2)
    assert not r.test_result.ok and r.test_result.message == msg.test_stopped()


def test_record_point_helpers_used_by_profiles() -> None:
    """Sanity: the fake page geometry round-trips through record_point / record_region."""
    world = FakeWorld()
    p = record_point(world.client, 300, 300)
    r = record_region(world.client, 200, 200, 100, 50)
    assert (p.dx, p.dy) == (200, 250) and (r.dx, r.dy, r.w, r.h) == (100, 150, 100, 50)
    assert RunState.PAUSED.value == "paused"


def test_consecutive_identical_messages_give_unknown_with_only_new_text() -> None:
    """SPEC 5.3 / 11.12: the previous code's message is in the baseline, so an identical new
    message is not "new" -> UNKNOWN 「送出後結果區沒有變化」 (a popup or only_new_text off avoids it)."""
    world = world_with()
    prof = make_profile(world)
    prof.policy.on_unknown = UnknownAction.CONTINUE
    r = SyncRun(make_plan(prof, ["AAAA-1111", "BBBB-2222"]), world).run()
    first, second = r.done()
    assert first.queue_status is CodeStatus.SUCCESS
    assert second.queue_status is CodeStatus.REVIEW and second.queue_message == msg.no_change_after_submit()
    world2 = world_with(popup_on="always")
    prof2 = make_profile(world2, dismiss_popup=True)
    r2 = SyncRun(make_plan(prof2, ["AAAA-1111", "BBBB-2222"]), world2).run()
    assert [d.queue_status for d in r2.done()] == [CodeStatus.SUCCESS, CodeStatus.SUCCESS]
    assert [a for a in world2.actions if a[0] == "popup_closed"] == [("popup_closed",)] * 2
