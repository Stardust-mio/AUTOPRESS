"""RunSession (G4): plan building, bookkeeping on the GUI thread, pause / resume / stop through the
worker QThread, the USER_INPUT relabel, resolve_attention, step tests and shutdown."""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest
from PyQt6.QtCore import QCoreApplication

from autopress.models import (
    AttemptRecord,
    CodeStatus,
    KeywordConfig,
    PauseReason,
    PlanItem,
    PlanMode,
    ResultClass,
    RunPlan,
    RunSelection,
    RunState,
    RunSummary,
    StopReason,
    UnknownAction,
    now_iso,
)
from autopress.runner import messages as msg
from autopress.runner.engine import RunSession
from autopress.win32.input import UserActivity
from tests.fakes import FakeCodeQueue, FakeHistoryStore, FakeOcrService
from tests.runner_helpers import FakeBackend, FakeWorld, fast_runner, fast_settings, make_profile, runner_standins, wait_until

pytestmark = pytest.mark.usefixtures("runner_standins", "fast_runner")
_ = (runner_standins, fast_runner)


class Env:
    def __init__(self, world: FakeWorld | None = None, ocr_state: str = "ready") -> None:
        self.world = world or FakeWorld(valid={"AAAA-1111", "BBBB-2222", "CCCC-3333"})
        self.queue = FakeCodeQueue()
        self.history = FakeHistoryStore()
        self.ocr = FakeOcrService(state=ocr_state)
        self.backends: list[FakeBackend] = []

        def factory() -> FakeBackend:
            b = FakeBackend(self.world)
            self.backends.append(b)
            return b

        self.session = RunSession(self.queue, self.history, self.ocr, backend_factory=factory)
        self.profile = make_profile(self.world)
        self.settings = fast_settings()
        self.events: list[tuple[str, tuple[Any, ...]]] = []
        for name in ("state_changed", "progress", "code_started", "step_started", "code_finished", "log", "cooldown",
                     "waiting", "attention", "finished", "test_finished"):
            getattr(self.session, name).connect(lambda *a, n=name: self.events.append((n, a)))

    def add(self, *codes: str, game_key: str | None = None) -> list[str]:
        gk = self.profile.game_key() if game_key is None else game_key
        res = self.queue.add_codes(list(codes), game_key=gk, game=self.profile.game if gk else "")
        return res.added

    def of(self, name: str) -> list[tuple[Any, ...]]:
        return [a for n, a in self.events if n == name]

    def states(self) -> list[tuple[str, str]]:
        return [(a[0], a[1]) for a in self.of("state_changed")]

    def status(self, code_id: str) -> CodeStatus:
        item = self.queue.get(code_id)
        assert item is not None
        return item.status


@pytest.fixture
def env(qapp: Any) -> Env:
    e = Env()
    yield e
    e.session.shutdown(2.0)


def run(qtbot: Any, env: Env, plan: RunPlan, timeout: int = 10000) -> RunSummary:
    with qtbot.waitSignal(env.session.finished, timeout=timeout) as blocker:
        env.session.start(plan)
    return blocker.args[0]


# ----------------------------------------------------------------------------- build_plan / preflight


def test_build_plan_filters_game_skips_history_and_copies(env: Env) -> None:
    a, b, c = env.add("AAAA-1111", "BBBB-2222", "CCCC-3333")
    other = env.add("DDDD-4444", game_key="game:別的遊戲")
    unassigned = env.add("EEEE-5555", game_key="")
    env.history.append(AttemptRecord(run_id="old", code="BBBB-2222", game_key=env.profile.game_key(),
                                     status=CodeStatus.USED, started_at=now_iso()))
    plan = env.session.build_plan(env.profile, env.settings)
    assert [i.code_id for i in plan.items] == [a, c]
    assert env.status(b) is CodeStatus.SKIPPED and env.queue.get(b).message == msg.history_skip()
    assert env.status(other[0]) is CodeStatus.PENDING and env.status(unassigned[0]) is CodeStatus.PENDING
    assert plan.profile is not env.profile and plan.profile.id == env.profile.id
    assert plan.settings is not env.settings
    report = env.session.preflight(plan)
    keys = {i.key for i in report.issues}
    assert "unassigned_codes" in keys and report.target is not None and plan.target_hwnd == env.world.hwnd


def test_build_plan_selection_code_ids_and_test_one(env: Env) -> None:
    a, b, c = env.add("AAAA-1111", "BBBB-2222", "CCCC-3333")
    env.queue.set_checked([b], False)
    plan = env.session.build_plan(env.profile, env.settings, RunSelection.CHECKED)
    assert [i.code_id for i in plan.items] == [a, c]
    plan = env.session.build_plan(env.profile, env.settings, code_ids=[c, b])
    assert [i.code_id for i in plan.items] == [b, c]  # queue order kept
    plan = env.session.build_plan(env.profile, env.settings, mode=PlanMode.TEST_ONE)
    assert [i.code_id for i in plan.items] == [a] and plan.mode is PlanMode.TEST_ONE
    env.settings.skip_history_on_import = False
    env.history.append(AttemptRecord(run_id="old", code="AAAA-1111", game_key=env.profile.game_key(),
                                     status=CodeStatus.SUCCESS, started_at=now_iso()))
    assert len(env.session.build_plan(env.profile, env.settings).items) == 3


def test_build_plan_daily_cap(env: Env) -> None:
    env.add("AAAA-1111", "BBBB-2222", "CCCC-3333")
    for n in range(2):
        env.history.append(AttemptRecord(run_id="r", code=f"OLD{n}", game_key="game:x", status=CodeStatus.INVALID,
                                         started_at=now_iso()))
    env.history.append(AttemptRecord(run_id="manual", code="M1", game_key="game:x", status=CodeStatus.SUCCESS,
                                     started_at=now_iso()))  # manual marks are not attempts
    env.history.append(AttemptRecord(run_id="r", code="Y1", game_key="game:x", status=CodeStatus.INVALID,
                                     started_at="2020-01-01T10:00:00+08:00"))  # not today
    env.settings.daily_cap = 3
    plan = env.session.build_plan(env.profile, env.settings)
    assert len(plan.items) == 1
    issues = {i.key: i for i in env.session.preflight(plan).issues}
    assert issues["daily_cap"].level.value == "info" and issues["daily_cap"].message == msg.pf_daily_cap_shortened(1)
    env.settings.daily_cap = 2
    plan = env.session.build_plan(env.profile, env.settings)
    issues = {i.key: i for i in env.session.preflight(plan).issues}
    assert not plan.items and issues["daily_cap"].level.value == "error" and "no_codes" not in issues


def test_preflight_test_one_drops_untested_warning(env: Env) -> None:
    env.add("AAAA-1111")
    keys = {i.key for i in env.session.preflight(env.session.build_plan(env.profile, env.settings)).issues}
    assert "untested_profile" in keys
    plan = env.session.build_plan(env.profile, env.settings, mode=PlanMode.TEST_ONE)
    assert "untested_profile" not in {i.key for i in env.session.preflight(plan).issues}


# ----------------------------------------------------------------------------- runs and bookkeeping


def test_run_updates_queue_history_and_emits_signals(qtbot: Any, env: Env) -> None:
    a, b, c = env.add("AAAA-1111", "XXXX-0000", "EXP-1234")
    plan = env.session.build_plan(env.profile, env.settings)
    summary = run(qtbot, env, plan)
    assert summary.stop_reason is StopReason.COMPLETED and summary.done == 3
    assert [env.status(i) for i in (a, b, c)] == [CodeStatus.SUCCESS, CodeStatus.INVALID, CodeStatus.EXPIRED]
    assert all(env.queue.get(i).attempts == 1 for i in (a, b, c))
    assert env.queue.get(b).message == "兌換碼無效"
    recs = env.history.records()
    assert [r.code_id for r in recs] == [a, b, c] and all(r.run_id == plan.run_id for r in recs)
    assert [x[0] for x in env.of("code_finished")] == [a, b, c]
    assert env.states()[0] == ("starting", "") and env.states()[-1] == ("finished", "completed")
    assert env.session.state is RunState.FINISHED and not env.session.is_active() and env.session.plan is None
    assert env.of("progress")[-1][:2] == (3, 3)
    assert env.backends[-1].keep_awake_calls == [True, False]
    with pytest.raises(AssertionError):
        assert env.session.is_active()


def test_interrupted_before_submit_is_not_in_history(qtbot: Any, env: Env) -> None:
    (a,) = env.add("AAAA-1111")
    from autopress.win32.input import ForegroundLost

    env.world.trips.append(["click", 1, ForegroundLost("x")])
    env.session.state_changed.connect(lambda s, r: env.session.resume() if s == "paused" else None)
    summary = run(qtbot, env, env.session.build_plan(env.profile, env.settings))
    assert summary.done == 1 and env.status(a) is CodeStatus.SUCCESS
    assert len(env.history.records()) == 1  # the PENDING attempt was not written
    assert env.queue.get(a).attempts == 2
    assert [x[1].status for x in env.of("code_finished")] == [CodeStatus.PENDING, CodeStatus.SUCCESS]


def test_code_finished_for_a_removed_code_is_ignored(qtbot: Any, env: Env) -> None:
    a, b = env.add("AAAA-1111", "XXXX-0000")
    env.session.code_started.connect(lambda cid, i: env.queue.remove([cid]) if cid == a else None)
    summary = run(qtbot, env, env.session.build_plan(env.profile, env.settings))
    assert summary.done == 2 and env.queue.get(a) is None and env.status(b) is CodeStatus.INVALID
    assert [r.code_id for r in env.history.records()] == [a, b]


def test_running_leftovers_become_review(env: Env) -> None:
    (a,) = env.add("AAAA-1111")
    env.queue.set_status(a, CodeStatus.RUNNING)
    env.session._plan = RunPlan(items=[PlanItem(code_id=a, code="AAAA-1111")])  # noqa: SLF001
    env.session._state = RunState.RUNNING  # noqa: SLF001
    env.session._on_finished(RunSummary(stop_reason=StopReason.ERROR))  # noqa: SLF001
    item = env.queue.get(a)
    assert item.status is CodeStatus.REVIEW and item.message == msg.run_interrupted()
    assert env.session.state is RunState.FINISHED


def test_resolve_attention_updates_queue_and_history_in_place(qtbot: Any, env: Env) -> None:
    (a,) = env.add("AAAA-1111")
    env.world.hooks["submit"] = lambda w: setattr(w, "pending", (time.monotonic(), "請先登入", "x"))
    env.profile.policy.on_unknown = UnknownAction.CONTINUE
    run(qtbot, env, env.session.build_plan(env.profile, env.settings))
    assert env.status(a) is CodeStatus.REVIEW
    rec_before = env.history.records()[0]
    assert rec_before.result is ResultClass.UNKNOWN
    env.session.resolve_attention(a, CodeStatus.SUCCESS, "人工確認")
    rec = env.history.records()[0]
    assert len(env.history.records()) == 1 and rec.id == rec_before.id
    assert rec.status is CodeStatus.SUCCESS and rec.result is ResultClass.SUCCESS and rec.message == "人工確認"
    assert env.status(a) is CodeStatus.SUCCESS and env.queue.get(a).message == "人工確認"
    env.session.resolve_attention(a, CodeStatus.FAILED)
    assert env.history.records()[0].message == "人工確認" and env.history.records()[0].status is CodeStatus.FAILED


def test_cooldown_and_waiting_signals_reach_the_ui(qtbot: Any, env: Env) -> None:
    env.add("AAAA-1111", "XXXX-0000")
    env.profile.policy.interval_min_s = env.profile.policy.interval_max_s = 0.3
    run(qtbot, env, env.session.build_plan(env.profile, env.settings))
    waits = [x[0] for x in env.of("waiting")]
    assert waits and waits[-1] == 0.0
    assert any(x[0].message.startswith("第 1 / 2 筆") for x in env.of("log"))


def test_stop_during_cooldown_leaves_the_item_pending(qtbot: Any, env: Env) -> None:
    """Gate G-06: the cool-down runs after the attempt is final; a stop there ends the run and
    the item, still COOLDOWN in the queue, becomes PENDING with its message kept."""
    from autopress.models import RateLimitAction

    a, b = env.add("AAAA-1111", "BBBB-2222")
    env.world.rate_limit = 1  # the second submit within 10 s is rate-limited
    pol = env.profile.policy
    pol.interval_min_s = pol.interval_max_s = 0.0
    pol.on_rate_limit, pol.cooldown_s, pol.max_cooldowns = RateLimitAction.COOLDOWN, 30, 3
    env.session.start(env.session.build_plan(env.profile, env.settings))
    qtbot.waitUntil(lambda: bool(env.of("cooldown")), timeout=5000)
    assert env.status(b) is CodeStatus.COOLDOWN
    note = env.queue.get(b).message
    with qtbot.waitSignal(env.session.finished, timeout=5000):
        env.session.stop()
    assert env.status(a) is CodeStatus.SUCCESS
    assert env.status(b) is CodeStatus.PENDING and env.queue.get(b).message == note and note


def test_masked_rects_and_keywords_are_shared(qtbot: Any, env: Env) -> None:
    (a,) = env.add("AAAA-1111")
    env.profile.policy.on_unknown = UnknownAction.CONTINUE
    env.session.set_masked_rects([env.world.result_rect, (0, 0, 0, 5)])
    assert env.session.masked_rects() == [env.world.result_rect]
    run(qtbot, env, env.session.build_plan(env.profile, env.settings))
    assert env.status(a) is CodeStatus.REVIEW  # the "mini bar" covered the message
    env.session.set_masked_rects([])
    env.world.used.clear()
    (b,) = env.add("BBBB-2222")
    env.world.hooks["submit"] = lambda w: setattr(w, "pending", (time.monotonic(), "獎勵已入帳", "x"))
    kw = KeywordConfig()
    kw.groups[ResultClass.SUCCESS].append("已入帳")
    env.session.code_started.connect(lambda cid, i: env.session.update_keywords(kw))
    run(qtbot, env, env.session.build_plan(env.profile, env.settings))
    assert env.status(b) is CodeStatus.SUCCESS


def test_start_while_active_raises_and_ocr_is_started(qtbot: Any, qapp: Any) -> None:
    e = Env(ocr_state="not_started")
    started = []
    e.ocr.start = lambda: started.append(1)  # type: ignore[method-assign]
    e.add("AAAA-1111", "XXXX-0000")
    e.profile.policy.interval_min_s = e.profile.policy.interval_max_s = 5.0
    plan = e.session.build_plan(e.profile, e.settings)
    e.session.start(plan)
    try:
        assert started == [1] and e.session.is_active() and e.session.plan is plan
        with pytest.raises(RuntimeError):
            e.session.start(plan)
        with pytest.raises(RuntimeError):
            e.session.test_step(e.profile, 0, e.settings)
    finally:
        with qtbot.waitSignal(e.session.finished, timeout=5000):
            e.session.stop()
    assert e.states()[-1] == ("finished", "user")


# ----------------------------------------------------------------------------- pause / resume / stop


def long_interval_plan(env: Env, n: int = 2) -> RunPlan:
    codes = ["AAAA-1111", "XXXX-0000", "EXP-1234"][:n]
    env.add(*codes)
    env.profile.policy.interval_min_s = env.profile.policy.interval_max_s = 30.0
    return env.session.build_plan(env.profile, env.settings)


def test_pause_is_idempotent_and_resume_continues(qtbot: Any, env: Env) -> None:
    plan = long_interval_plan(env)
    env.session.start(plan)
    qtbot.waitUntil(lambda: bool(env.of("waiting")), timeout=5000)
    env.session.pause()
    assert env.session.state is RunState.PAUSING
    qtbot.waitUntil(lambda: env.session.state is RunState.PAUSED, timeout=1000)
    n_states = len(env.states())
    env.session.pause()
    env.session.pause()
    assert len(env.states()) == n_states and env.states()[-1] == ("paused", "user")
    env.profile.policy.interval_min_s = 0  # (the running plan is a copy: no effect)
    with qtbot.waitSignal(env.session.finished, timeout=5000):
        env.session.stop()
    assert env.states()[-2:] == [("stopping", "user"), ("finished", "user")]


def test_user_input_pause_relabelled_when_f8_follows(qtbot: Any, env: Env) -> None:
    plan = long_interval_plan(env)
    # the F8 key press itself is physical input: the guard trips at the next injection (G-07)
    env.world.trips.append([None, 0, UserActivity(msg.user_input())])
    env.session.start(plan)
    qtbot.waitUntil(lambda: env.session.state is RunState.PAUSED, timeout=5000)
    assert env.states()[-1] == ("paused", "user_input")
    env.session.pause()  # F8 arrives right after
    assert env.states()[-1] == ("paused", "user")
    n = len(env.states())
    env.session.pause()
    assert len(env.states()) == n
    with qtbot.waitSignal(env.session.finished, timeout=5000):
        env.session.stop()


def test_pause_first_then_user_input_trip_is_labelled_user(qtbot: Any, env: Env) -> None:
    plan = long_interval_plan(env)
    clicked, paused = threading.Event(), threading.Event()

    def on_click(world: FakeWorld) -> None:  # runner thread, right after the first click
        world.hooks.pop("click", None)
        clicked.set()
        paused.wait(5.0)
        world.trips.append([None, 0, UserActivity(msg.user_input())])  # F8 tripped the guard

    env.world.hooks["click"] = on_click
    env.session.start(plan)
    qtbot.waitUntil(clicked.is_set, timeout=5000)
    env.session.pause()  # F8 while the code is being typed
    paused.set()
    qtbot.waitUntil(lambda: env.session.state is RunState.PAUSED, timeout=2000)
    assert env.states()[-1] == ("paused", "user")
    with qtbot.waitSignal(env.session.finished, timeout=5000):
        env.session.stop()


def test_old_user_input_pause_is_not_relabelled(qtbot: Any, env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    import autopress.runner.engine as engine

    monkeypatch.setattr(engine, "RELABEL_WINDOW_S", 0.05)
    plan = long_interval_plan(env)
    env.world.trips.append([None, 0, UserActivity(msg.user_input())])
    env.session.start(plan)
    qtbot.waitUntil(lambda: env.session.state is RunState.PAUSED, timeout=5000)
    qtbot.wait(100)
    env.session.pause()
    assert env.states()[-1] == ("paused", "user_input")
    with qtbot.waitSignal(env.session.finished, timeout=5000):
        env.session.stop()


def test_toggle_pause_and_resume(qtbot: Any, env: Env) -> None:
    env.add("AAAA-1111", "XXXX-0000")
    env.profile.policy.interval_min_s, env.profile.policy.interval_max_s = 0.3, 30.0
    plan = env.session.build_plan(env.profile, env.settings)
    env.session.start(plan)
    qtbot.waitUntil(lambda: bool(env.of("waiting")), timeout=5000)
    env.session.toggle_pause()
    qtbot.waitUntil(lambda: env.session.state is RunState.PAUSED, timeout=1000)
    env.session.toggle_pause()
    assert env.session.state is RunState.RUNNING
    # after a resume only interval_min_s since the last submit is waited (SPEC 2.5), not the rest of 30 s
    qtbot.waitUntil(lambda: len(env.of("code_started")) == 2, timeout=3000)
    # (not waitSignal: the short second code may finish before a waitSignal block would start)
    qtbot.waitUntil(lambda: env.session.state is RunState.FINISHED, timeout=5000)


def test_stop_reaches_finished_quickly(qtbot: Any, env: Env) -> None:
    plan = long_interval_plan(env)
    env.session.start(plan)
    qtbot.waitUntil(lambda: bool(env.of("waiting")), timeout=5000)
    t0 = time.monotonic()
    with qtbot.waitSignal(env.session.finished, timeout=3000) as blocker:
        env.session.stop()
    assert time.monotonic() - t0 < 0.5
    assert blocker.args[0].stop_reason is StopReason.USER and blocker.args[0].done == 1
    env.session.stop()  # idle: no-op
    env.session.pause()
    env.session.resume()


def test_shutdown_delivers_the_final_signals(qapp: Any) -> None:
    e = Env()
    a, b = e.add("AAAA-1111", "XXXX-0000")
    e.profile.policy.interval_min_s = e.profile.policy.interval_max_s = 30.0
    e.session.start(e.session.build_plan(e.profile, e.settings))
    assert wait_until(lambda: len(e.world.submitted) == 1 and bool(e.world.evidence), 5)
    time.sleep(0.2)  # the worker is in the interval wait; nothing has been delivered yet
    assert e.status(a) is CodeStatus.PENDING
    e.session.shutdown(3.0)  # no event loop spin in between
    assert e.status(a) is CodeStatus.SUCCESS and e.status(b) is CodeStatus.PENDING
    assert [r.code_id for r in e.history.records()] == [a]
    assert e.session.state is RunState.FINISHED and e.of("finished")


def test_shutdown_when_idle_is_harmless(qapp: Any) -> None:
    e = Env()
    e.session.shutdown()
    QCoreApplication.processEvents()
    assert e.session.state is RunState.IDLE


# ----------------------------------------------------------------------------- step tests


def test_test_step_dry_and_real(qtbot: Any, env: Env) -> None:
    env.world.foreground = 77
    with qtbot.waitSignal(env.session.test_finished, timeout=5000) as blocker:
        env.session.test_step(env.profile, 0, env.settings, dry_run=True)
    res = blocker.args[0]
    assert res.ok and res.point == env.world.center(env.world.box_rects()[0]) and not env.world.actions
    assert env.session.state is RunState.IDLE and not env.session.is_active() and not env.of("finished")
    assert env.history.records() == [] and len(env.queue) == 0
    env.world.focused = 0
    with qtbot.waitSignal(env.session.test_finished, timeout=5000) as blocker:
        env.session.test_step(env.profile, 1, env.settings, sample_code="SAMPLE-0001", dry_run=False)
    assert blocker.args[0].ok and env.world.boxes == ["SAMPLE-0001"]


def test_test_step_stop(qtbot: Any, env: Env) -> None:
    from autopress.models import StepType, make_step

    w = make_step(StepType.WAIT)
    w.params.ms = 20000
    env.profile.steps.append(w)
    env.session.test_step(env.profile, len(env.profile.steps) - 1, env.settings, dry_run=False)
    qtbot.waitUntil(lambda: env.session.state is RunState.RUNNING, timeout=3000)
    with qtbot.waitSignal(env.session.test_finished, timeout=3000) as blocker:
        env.session.stop()
    assert not blocker.args[0].ok and blocker.args[0].message == msg.test_stopped()


def test_attention_signal_for_unknown_result(qtbot: Any, env: Env) -> None:
    (a,) = env.add("AAAA-1111")
    env.world.hooks["submit"] = lambda w: setattr(w, "pending", (time.monotonic(), "伺服器維護中", "x"))
    env.session.attention.connect(lambda att: env.session.resume())
    run(qtbot, env, env.session.build_plan(env.profile, env.settings))
    att = env.of("attention")[0][0]
    assert att.kind is PauseReason.UNKNOWN_RESULT and att.code_id == a and att.ocr_text == "伺服器維護中"
    assert ("paused", "unknown_result") in env.states()


def test_bookkeeping_with_the_real_g1_stores(qtbot: Any, qapp: Any, tmp_path: Any) -> None:
    """Same bookkeeping against codes.queue.CodeQueue / codes.history.HistoryStore (files in tmp)."""
    from tests.fakes import skip_if_stub

    skip_if_stub("autopress.codes.queue", "autopress.codes.history")
    from autopress.codes.history import HistoryStore
    from autopress.codes.queue import CodeQueue

    world = FakeWorld(valid={"AAAA-1111"})
    queue, history = CodeQueue(tmp_path / "queue.json"), HistoryStore(tmp_path / "history.jsonl")
    queue.load()
    history.load()
    session = RunSession(queue, history, FakeOcrService(), backend_factory=lambda: FakeBackend(world))
    profile = make_profile(world)
    profile.policy.on_unknown = UnknownAction.CONTINUE
    ids = queue.add_codes(["AAAA-1111", "XXXX-0000", "EXP-1234"], game_key=profile.game_key(), game=profile.game).added
    plan = session.build_plan(profile, fast_settings())
    try:
        with qtbot.waitSignal(session.finished, timeout=10000):
            session.start(plan)
    finally:
        session.shutdown(2.0)
    assert [queue.get(i).status for i in ids] == [CodeStatus.SUCCESS, CodeStatus.INVALID, CodeStatus.EXPIRED]
    assert all(queue.get(i).attempts == 1 for i in ids)
    reloaded = HistoryStore(tmp_path / "history.jsonl")
    reloaded.load()
    assert [r.code for r in reloaded.records()] == ["AAAA-1111", "XXXX-0000", "EXP-1234"]
    first = reloaded.records()[1]
    session.resolve_attention(ids[1], CodeStatus.SUCCESS, "人工確認")
    reloaded2 = HistoryStore(tmp_path / "history.jsonl")
    reloaded2.load()
    rec = reloaded2.records()[1]
    assert rec.id == first.id and rec.status is CodeStatus.SUCCESS and len(reloaded2.records()) == 3
    queue2 = CodeQueue(tmp_path / "queue.json")
    queue2.load()
    assert queue2.get(ids[1]).status is CodeStatus.SUCCESS and queue2.get(ids[1]).message == "人工確認"
    # history skip on the next plan: the redeemed code becomes SKIPPED with the bilingual note
    queue.reset([ids[0]])
    session.build_plan(profile, fast_settings())
    assert queue.get(ids[0]).status is CodeStatus.SKIPPED and queue.get(ids[0]).message == msg.history_skip()
