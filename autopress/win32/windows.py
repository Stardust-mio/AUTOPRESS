# OWNED BY G3 - replace this stub
"""Top-level window utilities (win32_windows.md section 2; port wb_win32.py).

All rects are PHYSICAL screen pixels (x, y, w, h). Handles are recycled: a target is alive
only if IsWindow holds AND pid, exe and class are unchanged. Minimized windows report
-32000 rects; use restored_rect(). In a dev run, a Python program's exe is the BASE
python.exe (the venv python.exe is a launcher stub).
"""

from __future__ import annotations

from ..models import Rect, TargetMatch, WindowInfo

__stub__ = True


def list_windows(alt_tab_only: bool = True) -> list[WindowInfo]:
    """Visible, titled, non-cloaked top-level windows in z-order (topmost first); with
    ``alt_tab_only`` WS_EX_TOOLWINDOW windows without WS_EX_APPWINDOW are skipped.
    AutoPress's own windows are excluded."""
    raise NotImplementedError


def window_info(hwnd: int) -> WindowInfo | None:
    """Fresh info for one window, None if it no longer exists."""
    raise NotImplementedError


def window_at(x: int, y: int, skip_own: bool = False) -> int | None:
    """Root window under a physical point (WindowFromPoint + GetAncestor GA_ROOT). Hide
    AutoPress overlays first: input-transparent windows are skipped, others are not. With
    ``skip_own`` the topmost visible top-level window at the point that does NOT belong to
    AutoPress is returned (z-order walk) - preview and preflight use it, because AutoPress's main
    window usually covers the target while the user is setting up (T30)."""
    raise NotImplementedError


def exclude_from_capture(hwnd: int, exclude: bool = True) -> bool:
    """SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE = 0x11) (Windows 10 2004+), or
    WDA_NONE when ``exclude`` is False. True when the call succeeded. Whether mss (BitBlt +
    CAPTUREBLT) then omits the window is UNVERIFIED (the 2026-11-17 probe ran on a locked
    session): G3 measures it with an own window (realinput) and reports. The runner masks
    AutoPress's windows in every capture regardless (ocr.imageio.mask_rects)."""
    raise NotImplementedError


def client_rect(hwnd: int) -> Rect:
    """Client area in screen coordinates (GetClientRect + ClientToScreen). OSError if gone."""
    raise NotImplementedError


def window_rect(hwnd: int) -> Rect:
    raise NotImplementedError


def frame_bounds(hwnd: int) -> Rect | None:
    """DWMWA_EXTENDED_FRAME_BOUNDS (visible frame), None if unavailable."""
    raise NotImplementedError


def restored_rect(hwnd: int) -> Rect:
    """GetWindowPlacement().rcNormalPosition (workspace coordinates) for minimized windows."""
    raise NotImplementedError


def is_window(hwnd: int) -> bool:
    raise NotImplementedError


def is_alive(info: WindowInfo) -> bool:
    """IsWindow(info.hwnd) and the window still has the same pid, exe and class."""
    raise NotImplementedError


def is_minimized(hwnd: int) -> bool:
    raise NotImplementedError


def foreground_window() -> int:
    """GetForegroundWindow() (0 if none)."""
    raise NotImplementedError


def window_pid(hwnd: int) -> int:
    raise NotImplementedError


def is_own_window(hwnd: int) -> bool:
    """The window belongs to the AutoPress process."""
    raise NotImplementedError


def find_windows(match: TargetMatch) -> list[WindowInfo]:
    """list_windows() filtered with ``match.matches(exe_path, title, class_name)``, z-order kept."""
    raise NotImplementedError


def find_window(match: TargetMatch) -> WindowInfo | None:
    """First (topmost) match, or None."""
    raise NotImplementedError


def window_dpi(hwnd: int) -> int:
    """GetDpiForWindow (96 if unavailable)."""
    raise NotImplementedError
