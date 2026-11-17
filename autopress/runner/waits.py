# OWNED BY G4
"""Pauses, waits and stops of the Runner (SPEC 2.3, 2.5, 2.6) as a mixin of runner.worker.Runner
(G4-internal). Every wait goes through RunControl.sleep; a paused run blocks in
RunControl.wait_while_paused (no input checks)."""

from __future__ import annotations

import random
import time
from typing import Any

from ..models import Attention, LogLevel, PauseReason, RunState, StopReason
from ..win32.input import FailsafeTriggered, UserActivity
from . import messages as msg
from .control import StopRequested

MIN_INTERVAL_S = 1.0  # SPEC 2.7.5: never faster than 1 s between codes (also when a profile was built in code)


class WaitsMixin:
    """Needs from the host: settings, profile, plan, backend, control, attention / waiting /
    cooldown signals, _log, _emit_state, _safe, _dry, _paused_total, _resumed, _last_submit_t,
    _stop_note, _fail_streak."""

    settings: Any
    profile: Any
    plan: Any
    backend: Any
    control: Any
    attention: Any
    waiting: Any
    cooldown: Any
    _dry: bool
    _paused_total: float
    _resumed: bool
    _last_submit_t: float | None
    _stop_note: str
    _fail_streak: int

    def _tick(self) -> None:
        """Every RunControl.sleep slice (runner thread): the failsafe corner only.

        Physical input is NOT checked here (integration, gate G-07): it is checked by the input
        guard right before every injection (win32.input.InjectGuard.check). So input during a
        wait (an ocr_check poll after submitting, a wait step, the interval) never aborts a
        result read - it trips at the next keystroke / click, before anything is sent - and F8
        during a wait is the documented soft pause (SPEC 2.3, 2.6)."""
        if self._dry:
            return
        s = self.settings
        if s.failsafe_enabled and self.backend.failsafe_hit(s.failsafe_margin_px):
            raise FailsafeTriggered(msg.failsafe_stop())

    def _hard_pause(self, reason: PauseReason, text: str, *, code_id: str = "", step_index: int = -1,
                    ocr_text: str = "", evidence_path: str = "") -> None:
        """PAUSED with ``reason`` + Attention; blocks until resume (StopRequested on stop)."""
        self.control.request_pause()
        self._log(LogLevel.WARNING, text, code_id, step_index)
        self._emit_state(RunState.PAUSED, reason.value)
        self.attention.emit(Attention(kind=reason, message=text, code_id=code_id, step_index=step_index,
                                      ocr_text=ocr_text, evidence_path=evidence_path))
        self._wait_paused()

    def _wait_paused(self) -> None:
        t0 = time.monotonic()
        try:
            self.control.wait_while_paused()
        finally:
            self._paused_total += time.monotonic() - t0
        self._resumed = True
        self._safe(self.backend.reset_input_baseline)  # the click / key that resumed is not "user input"
        self._log(LogLevel.INFO, msg.resumed())
        self._emit_state(RunState.RUNNING, "")

    def _honour_soft_pause(self) -> None:
        while self.control.pause_requested:
            self._log(LogLevel.INFO, msg.paused_by_user())
            self._emit_state(RunState.PAUSED, PauseReason.USER.value)
            self._wait_paused()
            self._wait_min_since_submit()

    def _interval_min(self) -> float:
        pol = self.profile.policy
        return max(MIN_INTERVAL_S, min(pol.interval_min_s, pol.interval_max_s))

    def _wait_min_since_submit(self) -> None:
        if self._last_submit_t is None:
            return
        left = self._interval_min() - (time.monotonic() - self._last_submit_t)
        if left > 0:
            self._timed_wait(left, self.waiting, break_on_pause=True)

    def _interval_wait(self) -> None:
        """Between codes: uniform(interval_min_s, interval_max_s); after a resume only what is
        left of interval_min_s since the last submit. A soft pause ends the wait at once. The
        wait runs after the previous item is final, so nothing raised here changes that item
        (gate G-06): a stop ends the run, the failsafe aborts it."""
        pol = self.profile.policy
        while True:
            try:
                if self._resumed:
                    if self._last_submit_t is None:
                        return
                    left = self._interval_min() - (time.monotonic() - self._last_submit_t)
                else:
                    lo = self._interval_min()
                    left = random.uniform(lo, max(lo, max(MIN_INTERVAL_S, pol.interval_max_s)))
                if left > 0:
                    self._timed_wait(left, self.waiting, break_on_pause=True)
                return
            except UserActivity as exc:  # only from a custom tick; the default tick never raises it
                self._hard_pause(PauseReason.USER_INPUT, str(exc) or msg.user_input())

    def _timed_wait(self, total: float, signal: Any, break_on_pause: bool) -> None:
        """Wait ``total`` seconds in 50 ms slices, emitting ``signal(seconds_left)`` about once a
        second and ``signal(0.0)`` at the end."""
        end = time.monotonic() + total
        next_emit = 0.0
        try:
            while True:
                now = time.monotonic()
                left = end - now
                if left <= 0 or (break_on_pause and self.control.pause_requested):
                    return
                if now >= next_emit:
                    signal.emit(float(left))
                    next_emit = now + 1.0
                self.control.sleep(min(0.05, left))
        finally:
            signal.emit(0.0)

    def _cooldown_wait(self, seconds: float) -> None:
        """Rate-limit cool-down (state COOLDOWN). Paused time does not count."""
        self._emit_state(RunState.COOLDOWN, "")
        end = time.monotonic() + seconds
        while True:
            left = end - time.monotonic()
            if left <= 0:
                break
            t_pause = time.monotonic()
            try:
                if self.control.pause_requested:
                    self._emit_state(RunState.PAUSED, PauseReason.USER.value)
                    self._wait_paused()
                else:
                    self._timed_wait(left, self.cooldown, break_on_pause=True)
                    continue
            except UserActivity as exc:
                self._hard_pause(PauseReason.USER_INPUT, str(exc) or msg.user_input())
            end += time.monotonic() - t_pause
            self._emit_state(RunState.COOLDOWN, "")
        self._emit_state(RunState.RUNNING, "")

    def _stop(self, reason: StopReason, note: str = "", attention: Attention | None = None) -> None:
        """End the run with ``reason`` (raises StopRequested)."""
        self._stop_note = note
        self.control.request_stop(reason)
        self._emit_state(RunState.STOPPING, reason.value)
        if attention is not None:
            self.attention.emit(attention)
        raise StopRequested(reason)

    def _stop_message(self, reason: StopReason) -> str:
        if self._stop_note:
            return self._stop_note
        return {
            StopReason.USER: msg.stopped_by_user(),
            StopReason.FAILSAFE: msg.failsafe_stop(),
            StopReason.RATE_LIMITED: msg.rate_limit_stop(),
            StopReason.FAILURES: msg.failures_stop(self._fail_streak),
            StopReason.COMPLETED: msg.completed(len(self.plan.items)),
        }.get(reason, reason.label())
