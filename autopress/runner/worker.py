# OWNED BY G4
"""Runner: the worker object that executes one RunPlan in the runner QThread (SPEC 2.4 - 2.7).

It never touches widgets or stores: everything goes out through its signals (queued to
runner.engine.RunSession on the GUI thread) and comes in through RunControl, SharedState and the
plan (a deep copy). ``Runner.run()`` may also be called directly (unit tests): it then runs in
the calling thread and its signals are delivered directly.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from enum import Enum
from typing import Any

from PyQt6.QtCore import QCoreApplication, QObject, pyqtSignal, pyqtSlot

from ..i18n import tr
from ..logsetup import mask_code
from ..models import (
    FORBIDDEN_TARGET_EXES,
    Attention,
    AttemptRecord,
    CodeStatus,
    KeywordConfig,
    LogEntry,
    LogLevel,
    OcrCheckParams,
    PauseReason,
    PlanItem,
    PlanMode,
    RateLimitAction,
    ResultClass,
    RunPlan,
    RunState,
    RunSummary,
    StepTestResult,
    StepType,
    StopReason,
    UnknownAction,
    WindowInfo,
    now_iso,
    status_for_result,
)
from ..win32.input import FailsafeTriggered, ForegroundLost, InjectionAborted, InputBlocked, PointNotOnTarget, UserActivity
from . import messages as msg
from .control import RunControl, StopRequested
from .preflight import per_code_seconds
from .shared import CodeDone, SharedState
from .steps import (
    CaptureBlank,
    StepContext,
    StepError,
    StepOutcome,
    TargetGone,
    TitleChanged,
    baseline_texts,
    bring_target_to_front,
    execute_step,
)
from .waits import WaitsMixin

__all__ = ["CodeDone", "Runner", "SharedState"]

log = logging.getLogger(__name__)

OCR_READY_TIMEOUT_S = 120.0
FOCUS_TIMEOUT_S = 3.0


class _Next(Enum):
    NEXT = 1  # go on with the next code (after the interval)
    RETRY = 2  # same code again (after a pause; at least interval_min since the last submit)
    RETRY_NOW = 3  # same code again at once (after a rate-limit cool-down)


class Runner(QObject, WaitsMixin):
    """Worker object living in the runner QThread (G4-internal; the UI never touches it)."""

    state_changed = pyqtSignal(str, str)
    progress = pyqtSignal(int, int, float)
    code_started = pyqtSignal(str, int)
    step_started = pyqtSignal(str, int, str)
    code_done = pyqtSignal(str, object)  # code_id, CodeDone
    log = pyqtSignal(object)  # LogEntry
    cooldown = pyqtSignal(float)
    waiting = pyqtSignal(float)
    attention = pyqtSignal(object)
    run_finished = pyqtSignal(object)  # RunSummary
    test_finished = pyqtSignal(object)  # StepTestResult

    def __init__(self, plan: RunPlan, control: object, backend_factory: Callable[[], Any],
                 shared: SharedState | None = None) -> None:
        super().__init__()
        assert isinstance(control, RunControl)
        self.plan = plan
        self.control: RunControl = control
        self._factory = backend_factory
        self._shared = shared if shared is not None else SharedState()
        self.backend: Any = None
        self.profile = plan.profile
        self.settings = plan.settings
        self._dry = plan.mode is PlanMode.TEST_STEP and plan.dry_run
        self._target: WindowInfo | None = None
        self._had_target = False
        self._used_plan_hwnd = False
        self._rebind_candidates: list[WindowInfo] = []  # matches found after the run's window was closed
        self._rebind_confirmed: int | None = None  # set when the user resumed after a re-bind pause
        self._last_bound: WindowInfo | None = None  # the window the run used last
        self._guard: Any = None
        self._start_size: tuple[int, int] | None = None
        self._submit_index = plan.profile.first_submit_index()
        self._last_submit_t: float | None = None
        self._resumed = False
        self._paused_total = 0.0
        self._t0 = time.monotonic()
        self._done = 0
        self._counts: dict[CodeStatus, int] = {}
        self._fail_streak = 0
        self._invalid_streak = 0
        self._cooldowns_used = 0
        self._evidence_n = 0
        self._stop_note = ""
        self._codes: set[str] = {it.code for it in plan.items if it.code}
        self.started_at = ""

    # =========================================================================== entry point
    @pyqtSlot()
    def run(self) -> None:
        try:
            self._run()
        finally:
            thread = self.thread()
            app = QCoreApplication.instance()
            if thread is not None and app is not None and thread is not app.thread():
                thread.quit()

    def _run(self) -> None:
        test = self.plan.mode is PlanMode.TEST_STEP
        self.started_at = now_iso()
        self._t0 = time.monotonic()
        summary: RunSummary | None = None
        result: StepTestResult | None = None
        try:
            self.backend = self._factory()
        except Exception as exc:  # noqa: BLE001 - reported to the UI, never raised into Qt
            log.exception("runner backend could not be created")
            text = msg.unexpected_error(f"{type(exc).__name__}: {exc}")
            if test:
                self.test_finished.emit(StepTestResult(ok=False, step_index=self.plan.step_index, message=text))
            else:
                self._log(LogLevel.ERROR, text)
                self.run_finished.emit(self._summary(StopReason.ERROR, text))
            return
        try:
            self.control.set_tick(self._tick)
            if not self._dry:
                self._safe(self.backend.keep_awake, True)
                self._safe(self.backend.reset_input_baseline)
            if test:
                result = self._run_test_step()
            else:
                summary = self._run_plan()
        except Exception as exc:  # noqa: BLE001 - last safety net; the run must always finish
            log.exception("runner failed")
            text = msg.unexpected_error(f"{type(exc).__name__}: {exc}")
            if test:
                result = StepTestResult(ok=False, step_index=self.plan.step_index, message=text)
            else:
                summary = self._summary(StopReason.ERROR, text)
        finally:
            self.control.set_tick(None)
            self._safe(self.backend.release_all)
            if not self._dry:
                self._safe(self.backend.keep_awake, False)
            self._safe(self.backend.close)
        if test:
            self.test_finished.emit(result)
        else:
            self.run_finished.emit(summary)

    @staticmethod
    def _safe(fn: Callable[..., Any], *args: Any) -> Any:
        try:
            return fn(*args)
        except Exception:  # noqa: BLE001 - cleanup must not raise
            log.warning("runner cleanup call %s failed", getattr(fn, "__name__", fn), exc_info=True)
            return None

    # =========================================================================== the plan
    def _run_plan(self) -> RunSummary:
        items = self.plan.items
        n = len(items)
        self._emit_state(RunState.RUNNING, "")
        unknown = sum(1 for s in self.profile.steps if s.enabled and s.type is StepType.UNKNOWN)
        if unknown:
            self._log(LogLevel.WARNING, msg.unknown_steps_skipped(unknown))
        self._emit_progress()
        try:
            if n and self.profile.uses_ocr():
                self._wait_ocr_ready()
            i = 0
            while i < n:
                nxt = self._process_item(i, items[i])
                if nxt is _Next.NEXT:
                    i += 1
                    if i < n:
                        self._interval_wait()
                elif nxt is _Next.RETRY:
                    self._interval_wait()
            return self._summary(StopReason.COMPLETED, msg.completed(n))
        except StopRequested as exc:
            return self._summary(exc.reason, self._stop_message(exc.reason))
        except FailsafeTriggered:
            return self._summary(StopReason.FAILSAFE, msg.failsafe_stop())

    def _wait_ocr_ready(self) -> None:
        state, err = self.backend.ocr_status()
        if state == "ready":
            return
        self._log(LogLevel.INFO, msg.pf_ocr_loading())
        deadline = time.monotonic() + OCR_READY_TIMEOUT_S
        while True:
            if self.backend.ocr_ready(0.5, lambda: self.control.stop_requested):
                return
            self.control.checkpoint()
            state, err = self.backend.ocr_status()
            if state in ("failed", "disabled") or time.monotonic() > deadline:
                self._stop(StopReason.ERROR, msg.ocr_not_ready(err or state))

    # =========================================================================== one code
    def _process_item(self, i: int, item: PlanItem) -> _Next:
        self._ensure_target()
        ctx = self._context(item.code, i, item.code_id)
        code_id = item.code_id
        t_start, started_at = time.monotonic(), now_iso()
        self.code_started.emit(code_id, i)
        self._log(LogLevel.INFO, msg.code_started(i + 1, len(self.plan.items), item.code), code_id)
        possibly = False
        result_out: StepOutcome | None = None
        result_step = -1
        try:
            for idx, step in enumerate(self.profile.steps):
                if not step.enabled or step.type is StepType.UNKNOWN:
                    continue
                ctx.step_index = idx
                self.step_started.emit(code_id, idx, step.display_title())
                if idx == self._submit_index:
                    self._take_baselines(ctx, code_id)
                if step.type.sends_input and not self._dry:
                    self._check_title()
                before = ctx.guard_passed()
                try:
                    out = execute_step(step, ctx)
                finally:
                    if ctx.guard_passed() > before and idx >= self._submit_index >= 0:
                        possibly = True
                        self._last_submit_t = time.monotonic()
                        self._resumed = False
                if out.result is not None:
                    result_out, result_step = out, idx
        except (UserActivity, ForegroundLost, PointNotOnTarget, InputBlocked, CaptureBlank, TargetGone,
                TitleChanged) as exc:
            return self._interrupted(item, possibly, started_at, t_start, ctx.step_index, exc)
        except FailsafeTriggered:
            self._finish_interrupted(item, possibly, started_at, t_start)
            self._stop(StopReason.FAILSAFE)
        except StopRequested:
            self._finish_interrupted(item, possibly, started_at, t_start)
            raise
        except StepError as exc:
            return self._finish_result(item, result_out, result_step, possibly, started_at, t_start,
                                       error=str(exc), error_step=ctx.step_index)
        except OSError as exc:
            if not self._target_alive():
                return self._interrupted(item, possibly, started_at, t_start, ctx.step_index, TargetGone())
            return self._unexpected(item, possibly, started_at, t_start, ctx.step_index, exc)
        except Exception as exc:  # noqa: BLE001 - SPEC 2.5: anything else pauses with ERROR
            return self._unexpected(item, possibly, started_at, t_start, ctx.step_index, exc)
        return self._finish_result(item, result_out, result_step, possibly, started_at, t_start)

    def _take_baselines(self, ctx: StepContext, code_id: str) -> None:
        """Before the submitting step: read the region of every ocr_check with only_new_text."""
        for idx, step in enumerate(self.profile.steps):
            p = step.params
            if not (step.enabled and isinstance(p, OcrCheckParams) and p.only_new_text and p.region is not None
                    and idx > self._submit_index):
                continue
            try:
                _img, res = ctx.read(ctx.region(p.region), p.upscale or 1)
            except StepError as exc:
                self._log(LogLevel.WARNING, tr(f"無法讀取送出前的結果區：{exc}", f"Could not read the result area before "
                                                                    f"submitting: {exc}"), code_id, idx)
                continue
            ctx.baselines[idx] = baseline_texts(res.lines)

    def _record(self, item: PlanItem, status: CodeStatus, result: ResultClass | None, message: str, keyword: str,
                started_at: str, t_start: float, evidence: str) -> AttemptRecord:
        p = self.profile
        return AttemptRecord(run_id=self.plan.run_id, code_id=item.code_id, code=item.code, game=p.game,
                             game_key=p.game_key(), profile_id=p.id, profile_name=p.name, status=status, result=result,
                             message=message, matched_keyword=keyword, started_at=started_at, finished_at=now_iso(),
                             duration_ms=int((time.monotonic() - t_start) * 1000), evidence_path=evidence)

    def _finish_interrupted(self, item: PlanItem, possibly: bool, started_at: str, t_start: float) -> None:
        """Guard trip / stop / error in the middle of a code: PENDING (retried, not written to the
        history) or, once it was possibly submitted, REVIEW."""
        if possibly:
            status, message, persist = CodeStatus.REVIEW, msg.interrupted_after_submit(), True
        else:
            status, message, persist = CodeStatus.PENDING, "", False
        rec = self._record(item, status, None, message, "", started_at, t_start, "")
        self.code_done.emit(item.code_id, CodeDone(rec, status, message, persist))
        if possibly:
            self._count(status)
            self._log(LogLevel.WARNING, msg.code_result(item.code, status.label(), message), item.code_id)

    def _interrupted(self, item: PlanItem, possibly: bool, started_at: str, t_start: float, step_index: int,
                     exc: BaseException) -> _Next:
        reason, text = self._pause_reason(exc)
        if isinstance(exc, TargetGone):
            self._had_target = self._had_target or self._target is not None
            self._target = None
        self._finish_interrupted(item, possibly, started_at, t_start)
        self._hard_pause(reason, text, code_id=item.code_id, step_index=step_index)
        return _Next.NEXT if possibly else _Next.RETRY

    def _unexpected(self, item: PlanItem, possibly: bool, started_at: str, t_start: float, step_index: int,
                    exc: BaseException) -> _Next:
        log.error("unexpected error in the runner (step %s)", step_index, exc_info=exc)
        self._finish_interrupted(item, possibly, started_at, t_start)
        self._hard_pause(PauseReason.ERROR, msg.unexpected_error(f"{type(exc).__name__}: {exc}"),
                         code_id=item.code_id, step_index=step_index)
        return _Next.NEXT if possibly else _Next.RETRY

    @staticmethod
    def _pause_reason(exc: BaseException) -> tuple[PauseReason, str]:
        if isinstance(exc, UserActivity):
            return PauseReason.USER_INPUT, str(exc) or msg.user_input()
        if isinstance(exc, ForegroundLost):
            return PauseReason.FOCUS_LOST, str(exc) or msg.focus_lost()
        if isinstance(exc, PointNotOnTarget):
            return PauseReason.POINT_BLOCKED, str(exc) or msg.point_covered("?")
        if isinstance(exc, InputBlocked):
            return PauseReason.ERROR, str(exc) or msg.input_blocked()
        if isinstance(exc, CaptureBlank):
            return PauseReason.CAPTURE_BLANK, msg.capture_blank()
        if isinstance(exc, TitleChanged):
            return PauseReason.TITLE_CHANGED, msg.title_changed()
        return PauseReason.TARGET_LOST, msg.target_closed()

    def _finish_result(self, item: PlanItem, result_out: StepOutcome | None, result_step: int, possibly: bool,
                       started_at: str, t_start: float, error: str | None = None, error_step: int = -1) -> _Next:
        code_id = item.code_id
        evidence = result_out.evidence_path if result_out else ""
        if error is None or result_out is not None:
            result = result_out.result if result_out else None
            status = status_for_result(result)
            message = result_out.message if result_out else ""
            keyword = result_out.matched_keyword if result_out else ""
            if error is not None:  # PX-07: the result read by ocr_check is kept
                self._log(LogLevel.WARNING, error, code_id, error_step)
        else:
            result, keyword = None, ""
            if possibly:
                status, message = CodeStatus.REVIEW, msg.failed_after_submit(error)
            else:
                status, message = CodeStatus.FAILED, error
            self._log(LogLevel.ERROR, error, code_id, error_step)
        rec = self._record(item, status, result, message, keyword, started_at, t_start, evidence)
        pol = self.profile.policy

        if status is CodeStatus.COOLDOWN:  # rate-limited
            if pol.on_rate_limit is RateLimitAction.COOLDOWN and self._cooldowns_used < pol.max_cooldowns:
                note = msg.rate_limit_cooldown(pol.cooldown_s)
                self.code_done.emit(code_id, CodeDone(rec, CodeStatus.COOLDOWN, note, True))
                self._log(LogLevel.WARNING, note, code_id)
                self._cooldowns_used += 1
                self._cooldown_wait(float(pol.cooldown_s))
                return _Next.RETRY_NOW
            note = msg.rate_limit_stop()
            self.code_done.emit(code_id, CodeDone(rec, CodeStatus.PENDING, note, True))
            self._log(LogLevel.ERROR, note, code_id)
            self._stop(StopReason.RATE_LIMITED, note)

        self.code_done.emit(code_id, CodeDone(rec, status, message, True))
        self._count(status)
        level = (LogLevel.SUCCESS if status in (CodeStatus.SUCCESS, CodeStatus.SUBMITTED)
                 else LogLevel.WARNING if status in (CodeStatus.REVIEW, CodeStatus.USED, CodeStatus.EXPIRED)
                 else LogLevel.ERROR if status in (CodeStatus.FAILED, CodeStatus.INVALID) else LogLevel.INFO)
        self._log(level, msg.code_result(item.code, status.label(), message), code_id)

        # Policy order (gate G-11): rate limit (above), then the unknown-result decision, then the
        # counters - which use the status the user chose in that decision (resolve_attention).
        counted = status
        if result is ResultClass.UNKNOWN and result_out is not None:
            shown = " ".join((result_out.ocr_text or "").split())[:200] or message
            att = Attention(kind=PauseReason.UNKNOWN_RESULT, message=msg.unknown_result(shown), code_id=code_id,
                            step_index=result_step, ocr_text=result_out.ocr_text, evidence_path=evidence)
            if pol.on_unknown is UnknownAction.PAUSE:
                self._shared.take_resolved(code_id)  # forget a stale choice
                self._hard_pause(att.kind, att.message, code_id=code_id, step_index=result_step,
                                 ocr_text=att.ocr_text, evidence_path=evidence)
                counted = self._shared.take_resolved(code_id) or status
            elif pol.on_unknown is UnknownAction.STOP:
                self._stop(StopReason.ERROR, msg.unknown_stop(shown), attention=att)

        if counted in (CodeStatus.FAILED, CodeStatus.REVIEW):
            self._fail_streak += 1
            self._invalid_streak = 0
        elif counted is CodeStatus.INVALID:
            self._invalid_streak += 1
            self._fail_streak = 0
        else:
            self._fail_streak = self._invalid_streak = 0
        if pol.stop_after_failures > 0 and self._fail_streak >= pol.stop_after_failures:
            self._stop(StopReason.FAILURES, msg.failures_stop(self._fail_streak))

        if pol.pause_after_invalid > 0 and self._invalid_streak >= pol.pause_after_invalid:
            n = self._invalid_streak
            self._hard_pause(PauseReason.INVALID_STREAK, msg.invalid_streak(n), code_id=code_id)
            self._invalid_streak = 0  # resume resets the streak
        return _Next.NEXT

    def _count(self, status: CodeStatus) -> None:
        self._counts[status] = self._counts.get(status, 0) + 1
        self._done += 1
        self._emit_progress()

    # =========================================================================== target checks
    def _ensure_target(self) -> None:
        """Before every code (SPEC 2.5): soft pause, target alive / re-found, title still
        matching, brought to front, client size unchanged. Pauses on every problem and checks
        again after the resume."""
        while True:
            try:
                self._honour_soft_pause()
                self.control.checkpoint()
                info = self._locate_target()
                if info is None:
                    cands, self._rebind_candidates = self._rebind_candidates, []
                    if cands:  # gate G-03: never switch to another window without the user's OK
                        text = (msg.target_rebind(cands[0].title) if len(cands) == 1
                                else msg.target_rebind_many(len(cands)))
                    else:
                        text = (msg.target_closed() if self._had_target
                                else msg.target_not_found(self.profile.target.describe()))
                    self._hard_pause(PauseReason.TARGET_LOST, text)
                    if cands:
                        self._rebind_confirmed = cands[0].hwnd if len(cands) == 1 else 0
                    continue
                if not self.profile.target.matches(info.exe_path, info.title, info.class_name):
                    self._hard_pause(PauseReason.TITLE_CHANGED, msg.title_changed())
                    continue
                if not bring_target_to_front(self.backend, self.control, info,
                                             allow_same_process=self.profile.target.allow_same_process,
                                             timeout_s=FOCUS_TIMEOUT_S,
                                             settle_s=self.settings.delays.after_focus_ms / 1000.0):
                    self._hard_pause(PauseReason.FOCUS_LOST, msg.focus_failed())
                    continue
                client = self.backend.client_rect(info.hwnd)
                size = (int(client[2]), int(client[3]))
                if self._start_size is None:
                    self._start_size = size
                elif size != self._start_size:
                    a, b = f"{self._start_size[0]}×{self._start_size[1]}", f"{size[0]}×{size[1]}"
                    self._start_size = None  # the resume accepts the new size as start size
                    self._hard_pause(PauseReason.SIZE_CHANGED, msg.size_changed(a, b))
                    continue
            except UserActivity as exc:
                self._hard_pause(PauseReason.USER_INPUT, str(exc) or msg.user_input())
                continue
            except OSError:
                if self._target is not None and not self._target_alive():
                    self._had_target, self._target = True, None
                self._hard_pause(PauseReason.TARGET_LOST, msg.target_closed())
                continue
            if self._guard is None or self._target is None or info.hwnd != self._target.hwnd:
                self._guard = self.backend.make_guard(info, self.settings, self.profile.target.allow_same_process,
                                                      self.control.checkpoint)
            self._target = info
            self._had_target = True
            self._rebind_confirmed = None
            self._last_bound = info
            return

    def _usable(self, info: WindowInfo) -> bool:
        """Gate G-03: the RESOLVED window must not belong to a shell / terminal / system UI
        program (FORBIDDEN_TARGET_EXES) or to AutoPress itself, whatever the profile's exe says."""
        if info.exe_name.casefold() in FORBIDDEN_TARGET_EXES:
            return False
        try:
            return not (info.pid and info.pid == self.backend.own_pid())
        except Exception:  # noqa: BLE001 - an unreadable pid is not "own"
            return True

    def _locate_target(self) -> WindowInfo | None:
        """The window to use for the next code: the run's own window while it lives; at the start
        the plan's ``target_hwnd`` (the window the preflight showed), else the first usable match.
        Once the run HAD a window and it is gone, another match is used only after the user
        confirmed it (TARGET_LOST pause naming the candidate, gate G-03): until then this returns
        None and leaves the candidates in ``_rebind_candidates``."""
        if self._target is not None:
            if self.backend.is_alive(self._target):
                return self.backend.window_info(self._target.hwnd) or self._target
            self._target = None
        if not self._used_plan_hwnd and self.plan.target_hwnd:
            self._used_plan_hwnd = True
            info = self.backend.window_info(self.plan.target_hwnd)
            if info is not None and self._usable(info):
                return info
        found = [w for w in self.backend.find_targets(self.profile.target) if self._usable(w)]
        if not found:
            return None
        if not self._had_target:
            return found[0]  # first binding (the preflight warned about target_multiple)
        last = self._last_bound
        for w in found:
            if last is not None and w.hwnd == last.hwnd and w.pid == last.pid:
                return w  # the same window again (it only looked gone): no confirmation needed
        confirmed = self._rebind_confirmed
        if confirmed is not None:
            if len(found) == 1 and confirmed in (0, found[0].hwnd):
                return found[0]
            for w in found:
                if confirmed and w.hwnd == confirmed:
                    return w
        self._rebind_candidates = found
        return None

    def _check_title(self) -> None:
        """Gate G-04: before every step that sends input, the target's CURRENT title must still
        match the profile's title rule (a browser keeps its HWND when the active tab changes)."""
        t = self._target
        if t is None:
            return
        try:
            info = self.backend.window_info(t.hwnd)
        except Exception:  # noqa: BLE001 - a failing probe is reported by the step itself
            return
        if info is not None and not self.profile.target.matches(info.exe_path, info.title, info.class_name):
            raise TitleChanged()

    def _target_alive(self) -> bool:
        try:
            return self._target is not None and bool(self.backend.is_alive(self._target))
        except Exception:  # noqa: BLE001
            return False

    def _context(self, code: str, index: int, code_id: str = "") -> StepContext:
        ctx = StepContext(backend=self.backend, control=self.control, profile=self.profile, settings=self.settings,
                          target=self._target or WindowInfo(), guard=self._guard, code=code, index=index,
                          run_id=self.plan.run_id, dry_run=self._dry, keywords=self._keywords,
                          masked_rects=self._shared.masked_rects, evidence_seq=self._next_evidence)
        ctx._log = lambda level, text: self._log(level, text, code_id, ctx.step_index)  # noqa: SLF001
        return ctx

    def _keywords(self) -> KeywordConfig:
        kw = self._shared.keywords()
        return kw if kw is not None else self.profile.keywords

    def _next_evidence(self) -> int:
        self._evidence_n += 1
        return self._evidence_n

    # =========================================================================== step test
    def _run_test_step(self) -> StepTestResult:
        t0 = time.monotonic()
        idx = self.plan.step_index
        self._emit_state(RunState.RUNNING, "")
        res = StepTestResult(ok=False, step_index=idx)
        try:
            if not 0 <= idx < len(self.profile.steps):
                res.message = tr("沒有這一步", "No such step")
                return res
            step = self.profile.steps[idx]
            if step.type is StepType.UNKNOWN:
                res.message = msg.unknown_step()
                return res
            info = self._locate_target()
            if info is None:
                res.message = msg.target_not_found(self.profile.target.describe())
                return res
            if not bring_target_to_front(self.backend, self.control, info,
                                         allow_same_process=self.profile.target.allow_same_process,
                                         timeout_s=FOCUS_TIMEOUT_S,
                                         settle_s=self.settings.delays.after_focus_ms / 1000.0):
                res.message = msg.focus_failed()
                return res
            self._target = info
            if not self._dry:
                self._guard = self.backend.make_guard(info, self.settings, self.profile.target.allow_same_process,
                                                      self.control.checkpoint)
            ctx = self._context(self.plan.sample_code, 0)
            ctx.step_index = idx
            out = execute_step(step, ctx)
            res = StepTestResult(ok=out.ok, step_index=idx, message=out.message or msg.step_done(), point=out.point,
                                 rect=out.rect, ocr_text=out.ocr_text, result=out.result)
        except StopRequested:
            res.message = msg.test_stopped()
        except FailsafeTriggered:
            res.message = msg.failsafe_stop()
        except InjectionAborted as exc:
            res.message = str(exc) or msg.input_blocked()
        except CaptureBlank:
            res.message = msg.capture_blank()
        except TargetGone:
            res.message = msg.target_closed()
        except StepError as exc:
            res.message = str(exc)
        except Exception as exc:  # noqa: BLE001 - reported in the result
            log.exception("step test failed")
            res.message = msg.unexpected_error(f"{type(exc).__name__}: {exc}")
        finally:
            res.duration_ms = int((time.monotonic() - t0) * 1000)
        return res

    # =========================================================================== signals
    def _emit_state(self, state: RunState, reason: str) -> None:
        self.state_changed.emit(state.value, reason)

    def _emit_progress(self) -> None:
        total = len(self.plan.items)
        self.progress.emit(self._done, total, float(self._eta()))

    def _eta(self) -> float:
        remaining = len(self.plan.items) - self._done
        if remaining <= 0:
            return 0.0
        active = time.monotonic() - self._t0 - self._paused_total
        if self._done > 0 and active > 0:
            return active / self._done * remaining
        return per_code_seconds(self.profile) * remaining

    def _log(self, level: LogLevel, text: str, code_id: str = "", step_index: int = -1) -> None:
        self.log.emit(LogEntry(level=level, message=text, code_id=code_id, step_index=step_index))
        masked = text
        for code in self._codes:
            if code in masked:
                masked = masked.replace(code, mask_code(code))
        log.log(logging.WARNING if level in (LogLevel.WARNING, LogLevel.ERROR) else logging.INFO, "%s", masked)

    def _summary(self, reason: StopReason, message: str) -> RunSummary:
        p = self.profile
        return RunSummary(run_id=self.plan.run_id, profile_id=p.id, profile_name=p.name, mode=self.plan.mode,
                          started_at=self.started_at or now_iso(), finished_at=now_iso(), total=len(self.plan.items),
                          done=self._done, counts=dict(self._counts), stop_reason=reason, message=message)
