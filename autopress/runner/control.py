# OWNED BY G4 - replace this stub
"""Thread-safe run control shared by the GUI thread (requests) and the runner thread (checks).

Every blocking wait in the runner goes through RunControl.sleep (slices <= ``slice_s``), so
stop requests and safety checks are honoured within ~50 ms even during long waits.
"""

from __future__ import annotations

from collections.abc import Callable

from ..models import StopReason

__stub__ = True


class StopRequested(Exception):
    """Raised in the runner thread by checkpoint()/sleep() after request_stop()."""

    def __init__(self, reason: StopReason = StopReason.USER) -> None:
        super().__init__(reason.value)
        self.reason = reason


class RunControl:
    def __init__(self, tick: Callable[[], None] | None = None, slice_s: float = 0.05) -> None:
        """``tick`` runs in every sleep slice (runner thread) and may raise - the runner uses it
        for the failsafe corner and physical-input checks during waits."""
        raise NotImplementedError

    def request_pause(self) -> None:
        """Any thread. Soft pause: honoured at the next code boundary (or at once while waiting
        between codes)."""
        raise NotImplementedError

    def request_resume(self) -> None:
        raise NotImplementedError

    def request_stop(self, reason: StopReason = StopReason.USER) -> None:
        """Any thread. The first reason wins; also releases wait_while_paused()."""
        raise NotImplementedError

    @property
    def pause_requested(self) -> bool:
        raise NotImplementedError

    @property
    def stop_requested(self) -> bool:
        raise NotImplementedError

    @property
    def stop_reason(self) -> StopReason | None:
        raise NotImplementedError

    def checkpoint(self) -> None:
        """Raise StopRequested if a stop was requested."""
        raise NotImplementedError

    def sleep(self, seconds: float) -> None:
        """Interruptible sleep: checkpoint() and tick() every slice. Raises StopRequested."""
        raise NotImplementedError

    def wait_while_paused(self) -> None:
        """Block while a pause is requested; returns on resume, raises StopRequested on stop."""
        raise NotImplementedError
