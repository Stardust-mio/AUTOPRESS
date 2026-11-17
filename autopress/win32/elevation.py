# OWNED BY G3 - replace this stub
"""Integrity levels and UIPI (win32_windows.md section 3, win32_input.md section 8).

UIPI drops injected input into higher-integrity windows SILENTLY (SendInput still returns
the full count). Compare token integrity levels before every run. OpenProcess failing with
ERROR_ACCESS_DENIED means a system/protected process: treat as UNKNOWN (probably elevated).
AutoPress stays asInvoker; restart_as_admin() is the user's explicit choice.
"""

from __future__ import annotations

import enum
from collections.abc import Sequence
from dataclasses import dataclass

__stub__ = True


class InputPermission(enum.StrEnum):
    OK = "ok"
    BLOCKED_ELEVATED = "blocked_elevated"  # target integrity above ours: input will be dropped
    UNKNOWN = "unknown"  # token not readable (system / protected / anti-cheat process)


@dataclass(frozen=True)
class TokenInfo:
    pid: int = 0
    integrity_rid: int | None = None  # 0x2000 medium, 0x3000 high, 0x4000 system
    elevated: bool | None = None
    elevation_type: int | None = None  # 1 default, 2 full, 3 limited (admin with UAC split token)
    uiaccess: bool | None = None
    error: int = 0  # GetLastError of the failing call, 0 if readable


def token_info(pid: int | None = None) -> TokenInfo:
    """Token of ``pid`` (None = this process)."""
    raise NotImplementedError


def is_elevated() -> bool:
    """This process runs elevated (high integrity)."""
    raise NotImplementedError


def can_elevate() -> bool:
    """This user can elevate with a consent prompt (elevation_type 3)."""
    raise NotImplementedError


def input_permission(hwnd: int) -> InputPermission:
    raise NotImplementedError


def restart_as_admin(argv: Sequence[str] | None = None) -> bool:
    """ShellExecuteW(verb="runas") on this executable (sys.executable + script when not
    frozen) with ``argv`` plus ``--wait-lock``, so the new instance waits up to 10 s for the
    single-instance lock while this one shuts down (T32). True if the elevated process was
    started - the caller then quits the app. An elevated AutoPress cannot receive drag-and-drop
    from Explorer (UIPI): the restart prompt and Help say so (T40)."""
    raise NotImplementedError
