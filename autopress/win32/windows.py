# OWNED BY G3
"""Top-level window utilities (win32_windows.md section 2; port wb_win32.py).

All rects are PHYSICAL screen pixels (x, y, w, h). Handles are recycled: a target is alive
only if IsWindow holds AND pid, exe and class are unchanged. Minimized windows report
-32000 rects; use restored_rect(). In a dev run, a Python program's exe is the BASE
python.exe (the venv python.exe is a launcher stub).
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as W
import logging
import os

from ..models import Rect, TargetMatch, WindowInfo, point_in_rect
from . import api

log = logging.getLogger(__name__)


def _gone(hwnd: int) -> OSError:
    return OSError(api.ERROR_INVALID_WINDOW_HANDLE, f"window {hwnd:#x} does not exist")


def _is_alt_tab(ex: int) -> bool:
    return not (ex & api.WS_EX_TOOLWINDOW) or bool(ex & api.WS_EX_APPWINDOW)


def _input_transparent(ex: int) -> bool:
    """Click-through overlays (Qt WindowTransparentForInput = WS_EX_TRANSPARENT | WS_EX_LAYERED):
    WindowFromPoint skips them (win32_windows.md 2)."""
    return bool(ex & api.WS_EX_TRANSPARENT) and bool(ex & api.WS_EX_LAYERED)


def _make_info(hwnd: int, *, title: str | None = None, pid: int | None = None,
               exe_cache: dict[int, str] | None = None) -> WindowInfo:
    pid = api.window_pid(hwnd) if pid is None else pid
    if exe_cache is not None and pid in exe_cache:
        exe = exe_cache[pid]
    else:
        path, _err = api.exe_path(pid)
        exe = path or ""
        if exe_cache is not None:
            exe_cache[pid] = exe
    try:
        client = client_rect(hwnd)
    except OSError:
        client = (0, 0, 0, 0)
    try:
        rect = window_rect(hwnd)
    except OSError:
        rect = (0, 0, 0, 0)
    return WindowInfo(hwnd=int(hwnd), title=api.window_text(hwnd) if title is None else title,
                      class_name=api.class_name(hwnd), pid=pid, exe_path=exe, rect=rect, client=client,
                      minimized=bool(api.IsIconic(hwnd)), visible=bool(api.IsWindowVisible(hwnd)))


def list_windows(alt_tab_only: bool = True) -> list[WindowInfo]:
    """Visible, titled, non-cloaked top-level windows in z-order (topmost first); with
    ``alt_tab_only`` WS_EX_TOOLWINDOW windows without WS_EX_APPWINDOW are skipped.
    AutoPress's own windows are excluded."""
    own = os.getpid()
    cache: dict[int, str] = {}
    out: list[WindowInfo] = []
    for h in api.enum_windows():
        if not api.IsWindowVisible(h) or api.is_cloaked(h):
            continue
        if alt_tab_only and not _is_alt_tab(api.exstyle(h)):
            continue
        pid = api.window_pid(h)
        if pid == own:
            continue
        title = api.window_text(h)
        if not title:
            continue
        out.append(_make_info(h, title=title, pid=pid, exe_cache=cache))
    return out


def window_info(hwnd: int) -> WindowInfo | None:
    """Fresh info for one window, None if it no longer exists."""
    hwnd = int(hwnd or 0)
    if not hwnd or not api.IsWindow(hwnd):
        return None
    return _make_info(hwnd)


def window_at(x: int, y: int, skip_own: bool = False) -> int | None:
    """Root window under a physical point (WindowFromPoint + GetAncestor GA_ROOT). Hide
    AutoPress overlays first: input-transparent windows are skipped, others are not. With
    ``skip_own`` the topmost visible top-level window at the point that does NOT belong to
    AutoPress is returned (z-order walk) - preview and preflight use it, because AutoPress's main
    window usually covers the target while the user is setting up (T30).

    With ``skip_own``: when WindowFromPoint already lands on a foreign window that window is the
    answer (exact hit-testing); only when an AutoPress window is on top does the z-order walk
    continue below it, testing window rects (visible, not minimized, not cloaked, not
    input-transparent, not AutoPress's)."""
    hit = api.hwnd_int(api.WindowFromPoint(W.POINT(int(x), int(y))))
    root = api.hwnd_int(api.GetAncestor(hit, api.GA_ROOT)) if hit else 0
    root = root or hit
    if not skip_own:
        return root or None
    own = os.getpid()
    if root and api.window_pid(root) != own:
        return root
    for h in api.enum_windows():
        if api.window_pid(h) == own:
            continue
        if not api.IsWindowVisible(h) or api.IsIconic(h) or api.is_cloaked(h):
            continue
        if _input_transparent(api.exstyle(h)):
            continue
        try:
            r = window_rect(h)
        except OSError:
            continue
        if point_in_rect(r, int(x), int(y)):
            return h
    return None


def exclude_from_capture(hwnd: int, exclude: bool = True) -> bool:
    """SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE = 0x11) (Windows 10 2004+), or
    WDA_NONE when ``exclude`` is False. True when the call succeeded. Whether mss (BitBlt +
    CAPTUREBLT) then omits the window is UNVERIFIED (the 2026-11-17 probe ran on a locked
    session): G3 measures it with an own window (realinput) and reports. The runner masks
    AutoPress's windows in every capture regardless (ocr.imageio.mask_rects). Only windows of
    this process can be changed."""
    if api.SetWindowDisplayAffinity is None or not hwnd:
        return False
    affinity = api.WDA_EXCLUDEFROMCAPTURE if exclude else api.WDA_NONE
    ok = bool(api.SetWindowDisplayAffinity(int(hwnd), affinity))
    if not ok:
        log.info("SetWindowDisplayAffinity(%#x, %#x) failed: error %s", int(hwnd), affinity, ctypes.get_last_error())
    return ok


def display_affinity(hwnd: int) -> int | None:
    """GetWindowDisplayAffinity (None when unavailable or failing) - for tests and diagnostics."""
    if api.GetWindowDisplayAffinity is None or not hwnd:
        return None
    val = W.DWORD(0)
    if not api.GetWindowDisplayAffinity(int(hwnd), ctypes.byref(val)):
        return None
    return int(val.value)


def client_rect(hwnd: int) -> Rect:
    """Client area in screen coordinates (GetClientRect + ClientToScreen). OSError if gone."""
    hwnd = int(hwnd or 0)
    if not hwnd or not api.IsWindow(hwnd):
        raise _gone(hwnd)
    r = W.RECT()
    if not api.GetClientRect(hwnd, ctypes.byref(r)):
        raise ctypes.WinError(ctypes.get_last_error())
    pt = W.POINT(0, 0)
    if not api.ClientToScreen(hwnd, ctypes.byref(pt)):
        raise ctypes.WinError(ctypes.get_last_error())
    return int(pt.x), int(pt.y), int(r.right - r.left), int(r.bottom - r.top)


def window_rect(hwnd: int) -> Rect:
    """GetWindowRect (includes the invisible resize borders). OSError if gone."""
    hwnd = int(hwnd or 0)
    if not hwnd or not api.IsWindow(hwnd):
        raise _gone(hwnd)
    r = W.RECT()
    if not api.GetWindowRect(hwnd, ctypes.byref(r)):
        raise ctypes.WinError(ctypes.get_last_error())
    return api.rect_tuple(r)


def frame_bounds(hwnd: int) -> Rect | None:
    """DWMWA_EXTENDED_FRAME_BOUNDS (visible frame), None if unavailable."""
    if not hwnd:
        return None
    r = W.RECT()
    hr = api.DwmGetWindowAttribute(int(hwnd), api.DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r), ctypes.sizeof(r))
    return api.rect_tuple(r) if hr == 0 else None


def restored_rect(hwnd: int) -> Rect:
    """GetWindowPlacement().rcNormalPosition (workspace coordinates) for minimized windows.
    OSError if gone."""
    hwnd = int(hwnd or 0)
    if not hwnd or not api.IsWindow(hwnd):
        raise _gone(hwnd)
    wp = api.WINDOWPLACEMENT()
    wp.length = ctypes.sizeof(api.WINDOWPLACEMENT)
    if not api.GetWindowPlacement(hwnd, ctypes.byref(wp)):
        raise ctypes.WinError(ctypes.get_last_error())
    return api.rect_tuple(wp.rcNormalPosition)


def is_window(hwnd: int) -> bool:
    return bool(hwnd) and bool(api.IsWindow(int(hwnd)))


def is_alive(info: WindowInfo) -> bool:
    """IsWindow(info.hwnd) and the window still has the same pid, exe and class."""
    if not is_window(info.hwnd):
        return False
    pid = api.window_pid(info.hwnd)
    if pid != info.pid or api.class_name(info.hwnd) != info.class_name:
        return False
    if info.exe_path:
        path, _err = api.exe_path(pid)
        if path is not None and path.casefold() != info.exe_path.casefold():
            return False
    return True


def is_minimized(hwnd: int) -> bool:
    return bool(hwnd) and bool(api.IsIconic(int(hwnd)))


def foreground_window() -> int:
    """GetForegroundWindow() (0 if none)."""
    return api.hwnd_int(api.GetForegroundWindow())


def window_pid(hwnd: int) -> int:
    return api.window_pid(int(hwnd or 0))


def is_own_window(hwnd: int) -> bool:
    """The window belongs to the AutoPress process."""
    return bool(hwnd) and api.window_pid(int(hwnd)) == os.getpid()


def find_windows(match: TargetMatch) -> list[WindowInfo]:
    """list_windows() filtered with ``match.matches(exe_path, title, class_name)``, z-order kept.
    Alt-Tab windows come first; tool windows (which list_windows() hides by default) follow, so
    a target picked with the crosshair can always be found again. Never AutoPress's own windows."""
    hits = [info for info in list_windows(alt_tab_only=False)
            if not is_own_window(info.hwnd) and match.matches(info.exe_path, info.title, info.class_name)]
    alt = [_is_alt_tab(api.exstyle(info.hwnd)) for info in hits]
    return [i for i, a in zip(hits, alt, strict=True) if a] + [i for i, a in zip(hits, alt, strict=True) if not a]


def find_window(match: TargetMatch) -> WindowInfo | None:
    """First (topmost) match, or None."""
    found = find_windows(match)
    return found[0] if found else None


def window_dpi(hwnd: int) -> int:
    """GetDpiForWindow (96 if unavailable)."""
    if not hwnd or api.GetDpiForWindow is None:
        return 96
    dpi = int(api.GetDpiForWindow(int(hwnd)))
    return dpi if dpi > 0 else 96
