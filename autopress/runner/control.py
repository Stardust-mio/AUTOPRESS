# OWNED BY G4
"""Thread-safe run control shared by the GUI thread (requests) and the runner thread (checks).

Every blocking wait in the runner goes through RunControl.sleep (slices <= ``slice_s``), so
stop requests and safety checks are honoured within ~50 ms even during long waits. A stop
request also wakes a sleeping slice at once (condition variable), so the reaction time in waits
is well below one slice.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from ..models import StopReason


class StopRequested(Exception):
    """Raised in the runner thread by checkpoint()/sleep() after request_stop()."""

    def __init__(self, reason: StopReason = StopReason.USER) -> None:
        super().__init__(reason.value)
        self.reason = reason


class RunControl:
    def __init__(self, tick: Callable[[], None] | None = None, slice_s: float = 0.05) -> None:
        """``tick`` runs in every sleep slice (runner thread) and may raise - the runner uses it
        for the failsafe corner and physical-input checks during waits."""
        self._cond = threading.Condition(threading.Lock())
        self._pause = False
        self._stop_reason: StopReason | None = None
        self._tick = tick
        self._slice = min(0.05, max(0.001, float(slice_s)))

    # ------------------------------------------------------------------ requests (any thread)
    def request_pause(self) -> None:
        """Any thread. Soft pause: honoured at the next code boundary (or at once while waiting
        between codes)."""
        with self._cond:
            self._pause = True
            self._cond.notify_all()

    def request_resume(self) -> None:
        with self._cond:
            self._pause = False
            self._cond.notify_all()

    def request_stop(self, reason: StopReason = StopReason.USER) -> None:
        """Any thread. The first reason wins; also releases wait_while_paused()."""
        with self._cond:
            if self._stop_reason is None:
                self._stop_reason = StopReason(reason)
            self._cond.notify_all()

    def set_tick(self, tick: Callable[[], None] | None) -> None:
        """Replace the per-slice check (the runner installs it once its backend exists)."""
        self._tick = tick

    # ------------------------------------------------------------------ state
    @property
    def pause_requested(self) -> bool:
        return self._pause

    @property
    def stop_requested(self) -> bool:
        return self._stop_reason is not None

    @property
    def stop_reason(self) -> StopReason | None:
        return self._stop_reason

    # ------------------------------------------------------------------ runner thread
    def checkpoint(self) -> None:
        """Raise StopRequested if a stop was requested."""
        reason = self._stop_reason
        if reason is not None:
            raise StopRequested(reason)

    def sleep(self, seconds: float) -> None:
        """Interruptible sleep: checkpoint() and tick() every slice. Raises StopRequested."""
        deadline = time.monotonic() + max(0.0, float(seconds))
        while True:
            self.checkpoint()
            tick = self._tick
            if tick is not None:
                tick()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            with self._cond:
                if self._stop_reason is None:
                    self._cond.wait(min(self._slice, remaining))

    def wait_while_paused(self) -> None:
        """Block while a pause is requested; returns on resume, raises StopRequested on stop.
        Runs no input checks (a paused run never trips the guard)."""
        with self._cond:
            while self._pause and self._stop_reason is None:
                self._cond.wait(0.25)
        self.checkpoint()
