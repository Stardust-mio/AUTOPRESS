# OWNED BY G4
"""RunSession: the GUI-thread facade over one runner worker thread (SPEC section 2).

The worker (``Runner``, a QObject moved to a QThread; defined in runner.worker) executes the plan
and emits signals; RunSession receives them on the GUI thread, updates the CodeQueue and
HistoryStore (the only writer during a run), then re-emits its own signals for the UI. Control
requests go through a runner.control.RunControl (thread-safe), never through signals.

Bookkeeping rules: a ``code_finished`` for an id that is no longer in the queue is logged and
ignored (the queue is not touched; the attempt is still written to the history); on
``finished`` any plan item still RUNNING becomes REVIEW (「執行中斷，請確認是否已兌換」);
every persisted message uses tr() with both languages. The runner thread calls
win32.power.keep_awake(True) at start and keep_awake(False) in its finally (PX-31).
"""

from __future__ import annotations

import copy
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QCoreApplication, QObject, QThread, pyqtSignal, pyqtSlot

from ..models import (
    CodeStatus,
    KeywordConfig,
    PauseReason,
    PlanItem,
    PlanMode,
    PreflightReport,
    Profile,
    Rect,
    ResultClass,
    RunPlan,
    RunSelection,
    RunState,
    RunSummary,
    Settings,
    StopReason,
)
from . import messages as msg
from .control import RunControl
from .preflight import run_preflight
from .worker import CodeDone, Runner, SharedState

if TYPE_CHECKING:
    from ..codes.history import HistoryStore
    from ..codes.queue import CodeQueue
    from ..ocr.service import OcrService
    from .backend import Backend

__all__ = ["RunSession", "Runner"]

log = logging.getLogger(__name__)

RELABEL_WINDOW_S = 1.5  # F8 within 1.5 s of an automatic USER_INPUT pause counts as "pause" (PX-11)

_RESULT_FOR_STATUS: dict[CodeStatus, ResultClass] = {
    CodeStatus.SUCCESS: ResultClass.SUCCESS, CodeStatus.USED: ResultClass.USED,
    CodeStatus.INVALID: ResultClass.INVALID, CodeStatus.EXPIRED: ResultClass.EXPIRED,
}


@dataclass
class _PlanNotes:
    """What build_plan learned that preflight reports (keyed by run id)."""

    unassigned: int = 0
    cap_left: int = -1  # attempts left today (-1 = no daily cap)
    capped: bool = False  # the cap removed codes from the plan


class RunSession(QObject):
    state_changed = pyqtSignal(str, str)  # RunState value, reason (PauseReason/StopReason value or "")
    progress = pyqtSignal(int, int, float)  # done, total, eta seconds (-1 = unknown)
    code_started = pyqtSignal(str, int)  # code_id, index in plan (0-based)
    step_started = pyqtSignal(str, int, str)  # code_id, step index (0-based), step display title
    code_finished = pyqtSignal(str, object)  # code_id, AttemptRecord (queue + history already updated)
    log = pyqtSignal(object)  # LogEntry
    cooldown = pyqtSignal(float)  # rate-limit cool-down: seconds left, about once per second
    waiting = pyqtSignal(float)  # interval before the next code: seconds left, about once per second
    attention = pyqtSignal(object)  # Attention - the run is paused (or stopped) when emitted
    finished = pyqtSignal(object)  # RunSummary
    test_finished = pyqtSignal(object)  # StepTestResult

    def __init__(self, queue: CodeQueue, history: HistoryStore, ocr: OcrService, *,
                 backend_factory: Callable[[], Backend] | None = None, parent: QObject | None = None) -> None:
        """``backend_factory`` None -> RealBackend(ocr), created inside the worker thread."""
        super().__init__(parent)
        self._queue = queue
        self._history = history
        self._ocr = ocr
        self._factory = backend_factory
        self._state = RunState.IDLE
        self._plan: RunPlan | None = None
        self._control: RunControl | None = None
        self._shared = SharedState()
        self._threads: list[tuple[QThread, Runner]] = []
        self._notes: dict[str, _PlanNotes] = {}
        self._last_run_id = ""
        self._pause_reason = ""
        self._user_pause_t = float("-inf")
        self._input_pause_t = float("-inf")

    # ================================================================== state
    @property
    def state(self) -> RunState:
        return self._state

    @property
    def plan(self) -> RunPlan | None:
        """The plan being run (None when idle)."""
        return self._plan

    def is_active(self) -> bool:
        """A run or step test is in progress (state not IDLE / FINISHED)."""
        return self._state not in (RunState.IDLE, RunState.FINISHED)

    def _set_state(self, state: RunState, reason: str = "") -> None:
        self._state = state
        if state is RunState.PAUSED:
            self._pause_reason = reason
        self.state_changed.emit(state.value, reason)

    # ================================================================== planning
    def build_plan(self, profile: Profile, settings: Settings, selection: RunSelection = RunSelection.UNFINISHED, *,
                   code_ids: Sequence[str] | None = None, target_hwnd: int = 0,
                   mode: PlanMode = PlanMode.NORMAL) -> RunPlan:
        """Plan over queue.runnable(selection, game_key=profile.game_key()) - only codes of the
        profile's game; unassigned codes are reported by preflight (``unassigned_codes``) -
        restricted to ``code_ids`` when given, queue order kept, with a deep copy of ``profile``
        and ``settings``. Side effects (SPEC 5.7): runnable items whose code the history already
        shows as done (settings.history_skip_statuses, profile.game_key()) become SKIPPED when
        settings.skip_history_on_import; with settings.daily_cap > 0 the items are truncated to
        the attempts left today (preflight reports it). TEST_ONE plans keep only the first item."""
        selection = RunSelection(selection)
        mode = PlanMode(mode)
        game_key = profile.game_key()
        items = list(self._queue.runnable(selection, game_key=game_key))
        if code_ids is not None:
            wanted = set(code_ids)
            items = [i for i in items if i.id in wanted]
        if settings.skip_history_on_import and settings.history_skip_statuses:
            kept = []
            for item in items:
                if self._history.is_done(game_key, item.code, settings.history_skip_statuses):
                    self._queue.set_status(item.id, CodeStatus.SKIPPED, msg.history_skip())
                else:
                    kept.append(item)
            items = kept
        notes = _PlanNotes(unassigned=len(self._queue.runnable(selection, game_key="")))
        if settings.daily_cap > 0:
            notes.cap_left = max(0, settings.daily_cap - self._attempts_today())
            if len(items) > notes.cap_left:
                items = items[:notes.cap_left]
                notes.capped = True
        if mode is PlanMode.TEST_ONE:
            items = items[:1]
        plan = RunPlan(profile=copy.deepcopy(profile), items=[PlanItem(code_id=i.id, code=i.code) for i in items],
                       target_hwnd=int(target_hwnd or 0), mode=mode, settings=copy.deepcopy(settings))
        self._notes[plan.run_id] = notes
        return plan

    def _attempts_today(self) -> int:
        today = date.today().isoformat()
        n = 0
        for rec in self._history.records():
            if rec.run_id == "manual":
                continue
            if (rec.started_at or rec.finished_at or "")[:10] == today:
                n += 1
        return n

    def _ocr_status(self) -> tuple[str, str]:
        state = getattr(self._ocr, "state", "")
        return str(getattr(state, "value", state) or ""), str(getattr(self._ocr, "error", "") or "")

    def preflight(self, plan: RunPlan) -> PreflightReport:
        """runner.preflight.run_preflight for the plan (GUI thread, < 100 ms, no input). Sets
        ``plan.target_hwnd`` when the target is found."""
        notes = self._notes.get(plan.run_id, _PlanNotes())
        state, error = self._ocr_status()
        backend = self._factory() if self._factory is not None else None
        try:
            report = run_preflight(plan.profile, plan.settings, code_count=len(plan.items), ocr_state=state,
                                   target_hwnd=plan.target_hwnd, backend=backend, unassigned_count=notes.unassigned,
                                   ocr_error=error, daily_cap_left=notes.cap_left, daily_cap_shortened=notes.capped)
        finally:
            if backend is not None:
                try:
                    backend.close()
                except Exception:  # noqa: BLE001
                    log.debug("preflight backend close failed", exc_info=True)
        if plan.mode is PlanMode.TEST_ONE:  # testing one code IS the recommended test
            report.issues = [i for i in report.issues if i.key != "untested_profile"]
        if report.target is not None:
            plan.target_hwnd = report.target.hwnd
        return report

    # ================================================================== starting
    def start(self, plan: RunPlan) -> None:
        """Start the worker thread. RuntimeError if a run is active. The caller has already
        shown the countdown and registered the hotkeys."""
        if self.is_active():
            raise RuntimeError("a run or step test is already active")
        self._start_worker(plan)

    def test_step(self, profile: Profile, step_index: int, settings: Settings, *,
                  sample_code: str = "TEST-1234", dry_run: bool = True, target_hwnd: int = 0) -> None:
        """Run one step against the target in the worker (focus first). ``dry_run`` (the default,
        SPEC 2.7.4 / gate G-09: a caller that forgets the argument never injects input) locates /
        reads but sends no input. Result via ``test_finished``. RuntimeError if active. A real
        (not dry) test is stoppable with stop() at every checkpoint like a run; the caller shows
        the countdown and registers the stop hotkey first (SPEC 6.4.2)."""
        if self.is_active():
            raise RuntimeError("a run or step test is already active")
        plan = RunPlan(profile=copy.deepcopy(profile), items=[], target_hwnd=int(target_hwnd or 0),
                       mode=PlanMode.TEST_STEP, step_index=int(step_index), dry_run=bool(dry_run),
                       sample_code=sample_code, settings=copy.deepcopy(settings))
        self._start_worker(plan)

    def _backend_factory(self) -> Callable[[], Backend]:
        if self._factory is not None:
            return self._factory
        ocr = self._ocr

        def make() -> Backend:
            from .backend import RealBackend

            return RealBackend(ocr)

        return make

    def _start_worker(self, plan: RunPlan) -> None:
        self._reap_threads(wait=True)
        self._plan = plan
        self._last_run_id = plan.run_id
        self._shared.set_keywords(None)
        self._pause_reason = ""
        self._user_pause_t = self._input_pause_t = float("-inf")
        if plan.profile.uses_ocr() and self._ocr_status()[0] == "not_started":
            try:
                self._ocr.start()
            except Exception:  # noqa: BLE001 - the runner reports an engine that never gets ready
                log.warning("could not start the OCR service", exc_info=True)
        control = RunControl()
        self._control = control
        self._set_state(RunState.STARTING, "")
        runner = Runner(copy.deepcopy(plan), control, self._backend_factory(), self._shared)
        thread = QThread()
        thread.setObjectName("AutoPressRunner")
        runner.moveToThread(thread)
        runner.state_changed.connect(self._on_state)
        runner.progress.connect(self._on_progress)
        runner.code_started.connect(self._on_code_started)
        runner.step_started.connect(self._on_step_started)
        runner.code_done.connect(self._on_code_done)
        runner.log.connect(self._on_log)
        runner.cooldown.connect(self._on_cooldown)
        runner.waiting.connect(self._on_waiting)
        runner.attention.connect(self._on_attention)
        runner.run_finished.connect(self._on_finished)
        runner.test_finished.connect(self._on_test_finished)
        thread.started.connect(runner.run)
        thread.finished.connect(self._on_thread_finished)
        self._threads.append((thread, runner))
        thread.start()

    def _reap_threads(self, wait: bool) -> None:
        alive: list[tuple[QThread, Runner]] = []
        for thread, runner in self._threads:
            if thread.isRunning() and wait:
                thread.wait(2000)
            if thread.isRunning():
                alive.append((thread, runner))
        self._threads = alive

    # ================================================================== control (any time, GUI thread)
    def pause(self) -> None:
        """Soft pause (after the current code; at once while waiting). Idempotent: no-op while
        PAUSING / PAUSED, except that a USER_INPUT pause younger than 1.5 s is relabelled USER
        (the F8 press itself tripped the input guard; PX-11) and ``state_changed`` re-emitted."""
        now = time.monotonic()
        if self._state in (RunState.PAUSING, RunState.PAUSED):
            if (self._state is RunState.PAUSED and self._pause_reason == PauseReason.USER_INPUT.value
                    and now - self._input_pause_t <= RELABEL_WINDOW_S):
                self._set_state(RunState.PAUSED, PauseReason.USER.value)
            return
        if self._control is None or self._state not in (RunState.STARTING, RunState.RUNNING, RunState.COOLDOWN):
            return
        self._user_pause_t = now
        self._control.request_pause()
        self._set_state(RunState.PAUSING, PauseReason.USER.value)

    def resume(self) -> None:
        """Resume NOW (reset the input baseline in the runner, re-focus, continue). The UI calls
        RunFlow.resume(), which hides the main window and shows the resume countdown first."""
        if self._control is None or self._state not in (RunState.PAUSED, RunState.PAUSING):
            return
        self._user_pause_t = self._input_pause_t = float("-inf")  # the relabel window ends with the pause
        self._control.request_resume()
        self._set_state(RunState.RUNNING, "")

    def toggle_pause(self) -> None:
        """Immediate pause / resume without countdown or debounce (scripts and tests). The F8
        hotkey goes through RunFlow (debounce + resume countdown, SPEC 2.6)."""
        if self._state in (RunState.PAUSED, RunState.PAUSING):
            self.resume()
        else:
            self.pause()

    def stop(self, reason: StopReason = StopReason.USER) -> None:
        if self._control is None or not self.is_active():
            return
        reason = StopReason(reason)
        self._control.request_stop(reason)
        if self._state is not RunState.STOPPING:
            self._set_state(RunState.STOPPING, reason.value)

    def resolve_attention(self, code_id: str, status: CodeStatus, message: str = "") -> None:
        """The user classified an unknown result (Run page): update the queue item and, with
        HistoryStore.update, the latest history record of this run for that code (same record
        id); then the paused run may be resumed."""
        status = CodeStatus(status)
        if self.is_active():
            self._shared.set_resolved(code_id, status)  # the runner's failure counters use it (gate G-11)
        if self._queue.get(code_id) is not None:
            changes: dict[str, Any] = {"status": status}
            if message:
                changes["message"] = message
            self._queue.update(code_id, **changes)
        else:
            log.warning("resolve_attention for a code that is no longer queued")
        run_id = self._plan.run_id if self._plan is not None else self._last_run_id
        for rec in reversed(self._history.records()):
            if rec.code_id == code_id and (not run_id or rec.run_id == run_id):
                rec_changes: dict[str, Any] = {"status": status}
                if status in _RESULT_FOR_STATUS:
                    rec_changes["result"] = _RESULT_FOR_STATUS[status]
                if message:
                    rec_changes["message"] = message
                self._history.update(rec.id, **rec_changes)
                break

    def set_masked_rects(self, rects: Sequence[Rect]) -> None:
        """Physical screen rects of AutoPress's own windows that are visible during the run (the
        mini bar). Thread-safe; the runner blanks them in every capture before OCR, blank checks
        and evidence (ocr.imageio.mask_rects), so OCR never reads AutoPress's own text (T01 /
        PX-03). RunFlow calls it whenever the bar is shown, moved or hidden ([] when hidden)."""
        self._shared.set_masked_rects(list(rects or ()))

    def masked_rects(self) -> list[Rect]:
        """The rects last given to set_masked_rects (G4 addition, for tests and diagnostics)."""
        return self._shared.masked_rects()

    def update_keywords(self, keywords: KeywordConfig) -> None:
        """Use new keyword groups for the remaining codes of the running plan (thread-safe)."""
        self._shared.set_keywords(keywords)

    def shutdown(self, timeout_s: float = 3.0) -> None:
        """Stop any run and join the worker (app exit), then deliver the runner's queued final
        signals synchronously (``QCoreApplication.sendPostedEvents(self)``) so the last
        ``code_finished`` / ``finished`` bookkeeping reaches the queue and history BEFORE
        ui.app saves the queue (T29)."""
        if self._control is not None:
            self._control.request_stop(StopReason.USER)
        deadline = time.monotonic() + max(0.0, timeout_s)
        for thread, _runner in list(self._threads):
            left_ms = max(0, int((deadline - time.monotonic()) * 1000))
            if thread.isRunning():
                thread.wait(left_ms)
        QCoreApplication.sendPostedEvents(self, 0)
        if self._plan is not None and self.is_active():
            # the final signals never came (worker still busy): never leave RUNNING items behind
            plan = self._plan
            self._mark_running_as_review(plan)
            self._plan = None
            self._control = None
            self._set_state(RunState.FINISHED, StopReason.USER.value)
        self._reap_threads(wait=False)

    # ================================================================== runner signals (GUI thread)
    @pyqtSlot(str, str)
    def _on_state(self, state_value: str, reason: str) -> None:
        if self._state in (RunState.IDLE, RunState.FINISHED):
            return  # stale signal of a finished run
        st = RunState(state_value)
        if self._state is RunState.STOPPING and st is not RunState.STOPPING:
            return  # only the final signal ends a stop
        if (self._state is RunState.PAUSING and st in (RunState.RUNNING, RunState.COOLDOWN)
                and self._control is not None and self._control.pause_requested):
            return  # the runner has not reached the pause yet
        now = time.monotonic()
        if st is RunState.PAUSED and reason == PauseReason.USER_INPUT.value:
            if now - self._user_pause_t <= RELABEL_WINDOW_S:
                reason = PauseReason.USER.value  # the F8 press itself tripped the input guard
            else:
                self._input_pause_t = now
        self._set_state(st, reason)

    @pyqtSlot(int, int, float)
    def _on_progress(self, done: int, total: int, eta: float) -> None:
        self.progress.emit(done, total, eta)

    @pyqtSlot(str, int)
    def _on_code_started(self, code_id: str, index: int) -> None:
        item = self._queue.get(code_id)
        if item is None:
            log.warning("code_started for a code that is no longer queued (index %d)", index)
        else:
            self._queue.update(code_id, status=CodeStatus.RUNNING, attempts=item.attempts + 1)
        self.code_started.emit(code_id, index)

    @pyqtSlot(str, int, str)
    def _on_step_started(self, code_id: str, step_index: int, title: str) -> None:
        self.step_started.emit(code_id, step_index, title)

    @pyqtSlot(str, object)
    def _on_code_done(self, code_id: str, payload: object) -> None:
        done = payload if isinstance(payload, CodeDone) else None
        if done is None:
            log.error("unexpected code_done payload %r", type(payload))
            return
        if done.persist:
            try:
                self._history.append(done.record)
            except Exception:  # noqa: BLE001 - a full disk must not kill the run bookkeeping
                log.exception("could not write the history record")
        if self._queue.get(code_id) is None:
            log.warning("code_finished for a code that is no longer queued - ignored")
        else:
            try:
                self._queue.update(code_id, status=done.queue_status, message=done.queue_message)
            except (KeyError, OSError):
                log.exception("could not update the queue item")
        self.code_finished.emit(code_id, done.record)

    @pyqtSlot(object)
    def _on_log(self, entry: object) -> None:
        self.log.emit(entry)

    @pyqtSlot(float)
    def _on_cooldown(self, seconds: float) -> None:
        self.cooldown.emit(seconds)

    @pyqtSlot(float)
    def _on_waiting(self, seconds: float) -> None:
        self.waiting.emit(seconds)

    @pyqtSlot(object)
    def _on_attention(self, attention: object) -> None:
        self.attention.emit(attention)

    def _mark_running_as_review(self, plan: RunPlan) -> None:
        """Run end: RUNNING items become REVIEW (SPEC 2.2); an item still COOLDOWN (the run was
        stopped during its rate-limit cool-down) becomes PENDING with its message kept (gate G-06)."""
        for it in plan.items:
            item = self._queue.get(it.code_id)
            if item is None:
                continue
            if item.status is CodeStatus.RUNNING:
                self._queue.update(it.code_id, status=CodeStatus.REVIEW, message=msg.run_interrupted())
            elif item.status is CodeStatus.COOLDOWN:
                self._queue.update(it.code_id, status=CodeStatus.PENDING)

    @pyqtSlot(object)
    def _on_finished(self, summary: object) -> None:
        plan = self._plan
        if plan is not None:
            self._mark_running_as_review(plan)
        self._plan = None
        self._control = None
        reason = summary.stop_reason.value if isinstance(summary, RunSummary) else StopReason.ERROR.value
        self._set_state(RunState.FINISHED, reason)
        self.finished.emit(summary)

    @pyqtSlot(object)
    def _on_test_finished(self, result: object) -> None:
        self._plan = None
        self._control = None
        self._set_state(RunState.IDLE, "")
        self.test_finished.emit(result)

    @pyqtSlot()
    def _on_thread_finished(self) -> None:
        self._reap_threads(wait=False)
