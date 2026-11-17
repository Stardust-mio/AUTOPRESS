# OWNED BY G3 - replace this stub
"""Keep the display and the system awake during a run (decision PX-31).

A 5-minute rate-limit cool-down equals common display-off / lock timeouts; a locked session has
no foreground window and captures black, so the run would pause or produce REVIEW items.
SetThreadExecutionState is PER THREAD: the runner thread calls keep_awake(True) when the run
starts and keep_awake(False) in its ``finally`` (the state also ends when the thread exits).
Standard API, not measured in the research.
"""

from __future__ import annotations

__stub__ = True


def keep_awake(active: bool) -> bool:
    """active: SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED);
    inactive: SetThreadExecutionState(ES_CONTINUOUS). True when the call succeeded."""
    raise NotImplementedError
