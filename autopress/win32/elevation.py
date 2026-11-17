# OWNED BY G3
"""Integrity levels and UIPI (win32_windows.md section 3, win32_input.md section 8).

UIPI drops injected input into higher-integrity windows SILENTLY (SendInput still returns
the full count). Compare token integrity levels before every run. OpenProcess failing with
ERROR_ACCESS_DENIED means a system/protected process: treat as UNKNOWN (probably elevated).
AutoPress stays asInvoker; restart_as_admin() is the user's explicit choice.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as W
import enum
import logging
import os
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from . import api

log = logging.getLogger(__name__)

WAIT_LOCK_ARG = "--wait-lock"


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


def _read_token(tok: int, pid: int) -> TokenInfo:
    val, ret = W.DWORD(0), W.DWORD(0)
    fields: dict[str, int] = {}
    for key, cls in (("elevated", api.TokenElevation), ("elevation_type", api.TokenElevationType),
                     ("uiaccess", api.TokenUIAccess)):
        if api.GetTokenInformation(tok, cls, ctypes.byref(val), ctypes.sizeof(val), ctypes.byref(ret)):
            fields[key] = int(val.value)
    rid: int | None = None
    buf = ctypes.create_string_buffer(256)
    if api.GetTokenInformation(tok, api.TokenIntegrityLevel, buf, len(buf), ctypes.byref(ret)):
        sid = api.SID_AND_ATTRIBUTES.from_buffer(buf).Sid
        count = api.GetSidSubAuthorityCount(sid)
        if count:
            n = int(count.contents.value)
            if n > 0:
                rid = int(api.GetSidSubAuthority(sid, n - 1).contents.value)
    return TokenInfo(pid=pid, integrity_rid=rid,
                     elevated=bool(fields["elevated"]) if "elevated" in fields else None,
                     elevation_type=fields.get("elevation_type"),
                     uiaccess=bool(fields["uiaccess"]) if "uiaccess" in fields else None,
                     error=0)


def token_info(pid: int | None = None) -> TokenInfo:
    """Token of ``pid`` (None = this process). Never raises: ``error`` holds the GetLastError of
    the failing call (5 = access denied: system / protected process)."""
    own = pid is None or pid == os.getpid()
    the_pid = os.getpid() if pid is None else int(pid)
    if own:
        hproc = api.GetCurrentProcess()  # pseudo handle, never closed
    else:
        hproc = api.OpenProcess(api.PROCESS_QUERY_LIMITED_INFORMATION, False, the_pid)
        if not hproc:
            return TokenInfo(pid=the_pid, error=ctypes.get_last_error() or 5)
    tok = W.HANDLE()
    try:
        if not api.OpenProcessToken(hproc, api.TOKEN_QUERY, ctypes.byref(tok)):
            return TokenInfo(pid=the_pid, error=ctypes.get_last_error() or 5)
        return _read_token(tok, the_pid)
    finally:
        if tok:
            api.CloseHandle(tok)
        if not own:
            api.CloseHandle(hproc)


def is_elevated() -> bool:
    """This process runs elevated (high integrity)."""
    info = token_info()
    return bool(info.elevated) or (info.integrity_rid or 0) >= 0x3000


def can_elevate() -> bool:
    """This user can elevate with a consent prompt (elevation_type 3)."""
    return token_info().elevation_type == 3


def input_permission(hwnd: int) -> InputPermission:
    """OK when the target's integrity level is not above ours (UIPI lets the input through),
    BLOCKED_ELEVATED when it is (input would be dropped silently), UNKNOWN when the target's
    token cannot be read (system / protected / anti-cheat process, or the window is gone)."""
    pid = api.window_pid(int(hwnd or 0))
    if not pid:
        return InputPermission.UNKNOWN
    if pid == os.getpid():
        return InputPermission.OK
    mine = token_info()
    theirs = token_info(pid)
    if theirs.integrity_rid is None or mine.integrity_rid is None:
        log.info("input_permission: token of pid %s not readable (error %s)", pid, theirs.error)
        return InputPermission.UNKNOWN
    if theirs.integrity_rid > mine.integrity_rid:
        return InputPermission.BLOCKED_ELEVATED
    return InputPermission.OK


def restart_command(argv: Sequence[str] | None = None) -> tuple[str, str, str]:
    """(executable, parameter string, working folder) that restart_as_admin() hands to
    ShellExecuteW: the frozen exe, or this Python interpreter + the project's main.py; then
    ``argv`` (default: the current arguments) plus ``--wait-lock`` once."""
    args = [str(a) for a in (sys.argv[1:] if argv is None else argv)]
    if WAIT_LOCK_ARG not in args:
        args.append(WAIT_LOCK_ARG)
    if getattr(sys, "frozen", False):
        exe = sys.executable
        cwd = str(Path(sys.executable).resolve().parent)
    else:
        root = Path(__file__).resolve().parent.parent.parent
        main_py = root / "main.py"
        exe = sys.executable
        args = ([str(main_py)] if main_py.is_file() else ["-m", "autopress"]) + args
        cwd = str(root)
    return exe, subprocess.list2cmdline(args), cwd


def restart_as_admin(argv: Sequence[str] | None = None) -> bool:
    """ShellExecuteW(verb="runas") on this executable (sys.executable + script when not
    frozen) with ``argv`` plus ``--wait-lock``, so the new instance waits up to 10 s for the
    single-instance lock while this one shuts down (T32). True if the elevated process was
    started - the caller then quits the app. An elevated AutoPress cannot receive drag-and-drop
    from Explorer (UIPI): the restart prompt and Help say so (T40). Shows the UAC prompt;
    False when the user declines it or the call fails."""
    exe, params, cwd = restart_command(argv)
    result = api.ShellExecuteW(None, "runas", exe, params, cwd, api.SW_SHOWNORMAL)
    code = int(result or 0)
    if code <= 32:
        log.warning("restart_as_admin: ShellExecuteW returned %s (error %s)", code, ctypes.get_last_error())
        return False
    log.info("restart_as_admin: elevated instance started (%s %s)", exe, params)
    return True
