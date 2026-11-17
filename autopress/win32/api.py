# OWNED BY G3
"""Private ctypes declarations for the win32 package (structures, constants, prototypes).

Ported from docs/research/scripts/win32/wa_win32.py (input, clipboard, foreground, IME) and
wb_win32.py (windows, monitors, DPI, tokens). Rules: WinDLL(..., use_last_error=True);
EVERY foreign function gets explicit argtypes AND restype (64-bit handles, GlobalLock
truncation); ULONG_PTR = c_size_t (sizeof(INPUT) must be 40); keep references to ctypes
callbacks; pass POINT by value to WindowFromPoint. Only modules of autopress.win32 import this.

Every prototype is created through ``_proto`` and recorded in ``PROTOTYPES`` (tests check that
each one carries argtypes and restype). Our own WinDLL instances keep these declarations apart
from other libraries that use ``ctypes.windll`` with different prototypes. Prototypes that a
Windows version may lack (DPI-context functions, GetDpiForWindow, display affinity) are None
when missing and every caller handles that. Importing this module changes no process state.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as W
import logging
from typing import Any, NamedTuple

log = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
imm32 = ctypes.WinDLL("imm32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
try:
    shcore: Any = ctypes.WinDLL("shcore", use_last_error=True)
except OSError:  # pragma: no cover - Windows 8.1+ always has shcore
    shcore = None

ULONG_PTR = ctypes.c_size_t  # pointer-sized; c_ulong would make INPUT 28 bytes -> SendInput error 87
LONG_PTR = ctypes.c_ssize_t
LRESULT = W.LPARAM  # pointer-sized signed
HGLOBAL = ctypes.c_void_p
HRESULT = ctypes.c_long  # raw HRESULT (ctypes.HRESULT would raise by itself)
DPI_AWARENESS_CONTEXT = W.HANDLE  # pointer-sized pseudo handle: compare with AreDpiAwarenessContextsEqual
WNDENUMPROC = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
MONITORENUMPROC = ctypes.WINFUNCTYPE(W.BOOL, W.HMONITOR, W.HDC, ctypes.POINTER(W.RECT), W.LPARAM)


# ================================================================================ structures


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", W.LONG), ("dy", W.LONG), ("mouseData", W.DWORD), ("dwFlags", W.DWORD),
                ("time", W.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", W.WORD), ("wScan", W.WORD), ("dwFlags", W.DWORD), ("time", W.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", W.DWORD), ("wParamL", W.WORD), ("wParamH", W.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", W.DWORD), ("u", _INPUTUNION)]


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", W.UINT), ("dwTime", W.DWORD)]


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", W.DWORD), ("rcMonitor", W.RECT), ("rcWork", W.RECT), ("dwFlags", W.DWORD),
                ("szDevice", W.WCHAR * 32)]


class WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [("length", W.UINT), ("flags", W.UINT), ("showCmd", W.UINT), ("ptMinPosition", W.POINT),
                ("ptMaxPosition", W.POINT), ("rcNormalPosition", W.RECT)]


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", W.DWORD)]


# measured on x64 (win32_input.md 10): MOUSEINPUT 32, KEYBDINPUT 24, HARDWAREINPUT 8, INPUT 40
EXPECTED_SIZES: dict[str, int] = {"INPUT": 40, "MOUSEINPUT": 32, "KEYBDINPUT": 24, "HARDWAREINPUT": 8,
                                  "LASTINPUTINFO": 8, "MONITORINFOEXW": 104, "WINDOWPLACEMENT": 44,
                                  "SID_AND_ATTRIBUTES": 16}

# ================================================================================ constants

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE, KEYEVENTF_SCANCODE = 0x1, 0x2, 0x4, 0x8
MOUSEEVENTF_MOVE, MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0001, 0x0002, 0x0004
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP = 0x0020, 0x0040
MOUSEEVENTF_VIRTUALDESK, MOUSEEVENTF_ABSOLUTE = 0x4000, 0x8000

VK_LBUTTON, VK_RBUTTON, VK_MBUTTON = 0x01, 0x02, 0x04
VK_BACK, VK_TAB, VK_RETURN, VK_SHIFT, VK_CONTROL, VK_MENU = 0x08, 0x09, 0x0D, 0x10, 0x11, 0x12
VK_CAPITAL, VK_ESCAPE, VK_SPACE, VK_END, VK_HOME = 0x14, 0x1B, 0x20, 0x23, 0x24
VK_LEFT, VK_UP, VK_RIGHT, VK_DOWN, VK_INSERT, VK_DELETE = 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E
VK_LWIN, VK_RWIN = 0x5B, 0x5C
VK_LSHIFT, VK_RSHIFT, VK_LCONTROL, VK_RCONTROL, VK_LMENU, VK_RMENU = 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5
MAPVK_VK_TO_VSC, MAPVK_VK_TO_VSC_EX = 0, 4

SM_CXSCREEN, SM_CYSCREEN = 0, 1
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 76, 77, 78, 79
SW_SHOWNORMAL, SW_RESTORE = 1, 9
GA_ROOT = 2
GW_HWNDNEXT = 2
GWL_EXSTYLE = -20
WS_EX_TOPMOST, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW = 0x8, 0x20, 0x80
WS_EX_APPWINDOW, WS_EX_LAYERED, WS_EX_NOACTIVATE = 0x40000, 0x80000, 0x08000000
WM_NULL, WM_HOTKEY, WM_IME_CONTROL = 0x0000, 0x0312, 0x0283
IMC_GETCONVERSIONMODE, IMC_SETCONVERSIONMODE, IMC_GETOPENSTATUS, IMC_SETOPENSTATUS = 1, 2, 5, 6
SMTO_ABORTIFHUNG = 0x0002
CF_UNICODETEXT, GMEM_MOVEABLE = 13, 0x0002
ERROR_ACCESS_DENIED, ERROR_INVALID_WINDOW_HANDLE, ERROR_HOTKEY_ALREADY_REGISTERED = 5, 1400, 1409
DWMWA_EXTENDED_FRAME_BOUNDS, DWMWA_CLOAKED = 9, 14
MONITOR_DEFAULTTONEAREST = 2
MONITORINFOF_PRIMARY = 1
MDT_EFFECTIVE_DPI = 0
WDA_NONE, WDA_EXCLUDEFROMCAPTURE = 0x0, 0x11
PROCESS_QUERY_LIMITED_INFORMATION, TOKEN_QUERY = 0x1000, 0x0008
TokenElevationType, TokenElevation, TokenIntegrityLevel, TokenUIAccess = 18, 20, 25, 26
ES_SYSTEM_REQUIRED, ES_DISPLAY_REQUIRED, ES_CONTINUOUS = 0x00000001, 0x00000002, 0x80000000

CTX_UNAWARE, CTX_SYSTEM, CTX_PMV1, CTX_PMV2, CTX_GDISCALED = (DPI_AWARENESS_CONTEXT(v) for v in (-1, -2, -3, -4, -5))

# ================================================================================ prototypes

PROTOTYPES: list[tuple[str, Any, Any, list[Any]]] = []
"""(name, function, restype, argtypes) of every foreign function declared here."""
MISSING: list[str] = []
"""Optional functions this Windows version does not export."""


def _proto(dll: Any, name: str, restype: Any, *argtypes: Any, optional: bool = False) -> Any:
    try:
        fn = getattr(dll, name)
    except AttributeError:
        if not optional:
            raise
        MISSING.append(name)
        return None
    fn.restype = restype
    fn.argtypes = list(argtypes)
    PROTOTYPES.append((name, fn, restype, list(argtypes)))
    return fn


P = ctypes.POINTER
SendInput = _proto(user32, "SendInput", W.UINT, W.UINT, P(INPUT), ctypes.c_int)
GetForegroundWindow = _proto(user32, "GetForegroundWindow", W.HWND)
SetForegroundWindow = _proto(user32, "SetForegroundWindow", W.BOOL, W.HWND)
BringWindowToTop = _proto(user32, "BringWindowToTop", W.BOOL, W.HWND)
ShowWindow = _proto(user32, "ShowWindow", W.BOOL, W.HWND, ctypes.c_int)
IsIconic = _proto(user32, "IsIconic", W.BOOL, W.HWND)
IsWindow = _proto(user32, "IsWindow", W.BOOL, W.HWND)
IsWindowVisible = _proto(user32, "IsWindowVisible", W.BOOL, W.HWND)
GetWindowThreadProcessId = _proto(user32, "GetWindowThreadProcessId", W.DWORD, W.HWND, P(W.DWORD))
AttachThreadInput = _proto(user32, "AttachThreadInput", W.BOOL, W.DWORD, W.DWORD, W.BOOL)
GetWindowRect = _proto(user32, "GetWindowRect", W.BOOL, W.HWND, P(W.RECT))
GetClientRect = _proto(user32, "GetClientRect", W.BOOL, W.HWND, P(W.RECT))
ClientToScreen = _proto(user32, "ClientToScreen", W.BOOL, W.HWND, P(W.POINT))
WindowFromPoint = _proto(user32, "WindowFromPoint", W.HWND, W.POINT)  # POINT by value
GetAncestor = _proto(user32, "GetAncestor", W.HWND, W.HWND, W.UINT)
GetWindow = _proto(user32, "GetWindow", W.HWND, W.HWND, W.UINT)
GetCursorPos = _proto(user32, "GetCursorPos", W.BOOL, P(W.POINT))
SetCursorPos = _proto(user32, "SetCursorPos", W.BOOL, ctypes.c_int, ctypes.c_int)
GetSystemMetrics = _proto(user32, "GetSystemMetrics", ctypes.c_int, ctypes.c_int)
MapVirtualKeyExW = _proto(user32, "MapVirtualKeyExW", W.UINT, W.UINT, W.UINT, W.HKL)
VkKeyScanExW = _proto(user32, "VkKeyScanExW", W.SHORT, W.WCHAR, W.HKL)
GetKeyboardLayout = _proto(user32, "GetKeyboardLayout", W.HKL, W.DWORD)
GetKeyState = _proto(user32, "GetKeyState", W.SHORT, ctypes.c_int)
GetAsyncKeyState = _proto(user32, "GetAsyncKeyState", W.SHORT, ctypes.c_int)
ToUnicodeEx = _proto(user32, "ToUnicodeEx", ctypes.c_int, W.UINT, W.UINT, P(ctypes.c_ubyte * 256), W.LPWSTR,
                     ctypes.c_int, W.UINT, W.HKL)
OpenClipboard = _proto(user32, "OpenClipboard", W.BOOL, W.HWND)
CloseClipboard = _proto(user32, "CloseClipboard", W.BOOL)
EmptyClipboard = _proto(user32, "EmptyClipboard", W.BOOL)
GetClipboardData = _proto(user32, "GetClipboardData", W.HANDLE, W.UINT)
SetClipboardData = _proto(user32, "SetClipboardData", W.HANDLE, W.UINT, W.HANDLE)
IsClipboardFormatAvailable = _proto(user32, "IsClipboardFormatAvailable", W.BOOL, W.UINT)
RegisterClipboardFormatW = _proto(user32, "RegisterClipboardFormatW", W.UINT, W.LPCWSTR)
GetOpenClipboardWindow = _proto(user32, "GetOpenClipboardWindow", W.HWND)
EnumClipboardFormats = _proto(user32, "EnumClipboardFormats", W.UINT, W.UINT)
GetClipboardFormatNameW = _proto(user32, "GetClipboardFormatNameW", ctypes.c_int, W.UINT, W.LPWSTR, ctypes.c_int)
GetClipboardSequenceNumber = _proto(user32, "GetClipboardSequenceNumber", W.DWORD)
GetLastInputInfo = _proto(user32, "GetLastInputInfo", W.BOOL, P(LASTINPUTINFO))
RegisterHotKey = _proto(user32, "RegisterHotKey", W.BOOL, W.HWND, ctypes.c_int, W.UINT, W.UINT)
UnregisterHotKey = _proto(user32, "UnregisterHotKey", W.BOOL, W.HWND, ctypes.c_int)
PostMessageW = _proto(user32, "PostMessageW", W.BOOL, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
SendMessageTimeoutW = _proto(user32, "SendMessageTimeoutW", LRESULT, W.HWND, W.UINT, W.WPARAM, W.LPARAM,
                             W.UINT, W.UINT, P(ULONG_PTR))
EnumWindows = _proto(user32, "EnumWindows", W.BOOL, WNDENUMPROC, W.LPARAM)
GetWindowTextW = _proto(user32, "GetWindowTextW", ctypes.c_int, W.HWND, W.LPWSTR, ctypes.c_int)
GetClassNameW = _proto(user32, "GetClassNameW", ctypes.c_int, W.HWND, W.LPWSTR, ctypes.c_int)
GetWindowLongPtrW = _proto(user32, "GetWindowLongPtrW", LONG_PTR, W.HWND, ctypes.c_int)
GetWindowPlacement = _proto(user32, "GetWindowPlacement", W.BOOL, W.HWND, P(WINDOWPLACEMENT))
EnumDisplayMonitors = _proto(user32, "EnumDisplayMonitors", W.BOOL, W.HDC, P(W.RECT), MONITORENUMPROC, W.LPARAM)
GetMonitorInfoW = _proto(user32, "GetMonitorInfoW", W.BOOL, W.HMONITOR, P(MONITORINFOEXW))
MonitorFromPoint = _proto(user32, "MonitorFromPoint", W.HMONITOR, W.POINT, W.DWORD)  # POINT by value
SetWindowDisplayAffinity = _proto(user32, "SetWindowDisplayAffinity", W.BOOL, W.HWND, W.DWORD, optional=True)
GetWindowDisplayAffinity = _proto(user32, "GetWindowDisplayAffinity", W.BOOL, W.HWND, P(W.DWORD), optional=True)
GetDpiForWindow = _proto(user32, "GetDpiForWindow", W.UINT, W.HWND, optional=True)
GetThreadDpiAwarenessContext = _proto(user32, "GetThreadDpiAwarenessContext", DPI_AWARENESS_CONTEXT, optional=True)
AreDpiAwarenessContextsEqual = _proto(user32, "AreDpiAwarenessContextsEqual", W.BOOL, DPI_AWARENESS_CONTEXT,
                                      DPI_AWARENESS_CONTEXT, optional=True)
GetDpiAwarenessContextForProcess = _proto(user32, "GetDpiAwarenessContextForProcess", DPI_AWARENESS_CONTEXT,
                                          W.HANDLE, optional=True)  # Windows 10 1803+
SetProcessDpiAwarenessContext = _proto(user32, "SetProcessDpiAwarenessContext", W.BOOL, DPI_AWARENESS_CONTEXT,
                                       optional=True)

GetCurrentThreadId = _proto(kernel32, "GetCurrentThreadId", W.DWORD)
GetCurrentProcess = _proto(kernel32, "GetCurrentProcess", W.HANDLE)
GlobalAlloc = _proto(kernel32, "GlobalAlloc", HGLOBAL, W.UINT, ctypes.c_size_t)
GlobalLock = _proto(kernel32, "GlobalLock", ctypes.c_void_p, HGLOBAL)
GlobalUnlock = _proto(kernel32, "GlobalUnlock", W.BOOL, HGLOBAL)
GlobalFree = _proto(kernel32, "GlobalFree", HGLOBAL, HGLOBAL)
GlobalSize = _proto(kernel32, "GlobalSize", ctypes.c_size_t, HGLOBAL)
GetTickCount = _proto(kernel32, "GetTickCount", W.DWORD)
OpenProcess = _proto(kernel32, "OpenProcess", W.HANDLE, W.DWORD, W.BOOL, W.DWORD)
CloseHandle = _proto(kernel32, "CloseHandle", W.BOOL, W.HANDLE)
QueryFullProcessImageNameW = _proto(kernel32, "QueryFullProcessImageNameW", W.BOOL, W.HANDLE, W.DWORD, W.LPWSTR,
                                    P(W.DWORD))
SetThreadExecutionState = _proto(kernel32, "SetThreadExecutionState", W.DWORD, W.DWORD)

OpenProcessToken = _proto(advapi32, "OpenProcessToken", W.BOOL, W.HANDLE, W.DWORD, P(W.HANDLE))
GetTokenInformation = _proto(advapi32, "GetTokenInformation", W.BOOL, W.HANDLE, ctypes.c_int, ctypes.c_void_p,
                             W.DWORD, P(W.DWORD))
GetSidSubAuthorityCount = _proto(advapi32, "GetSidSubAuthorityCount", P(ctypes.c_ubyte), ctypes.c_void_p)
GetSidSubAuthority = _proto(advapi32, "GetSidSubAuthority", P(W.DWORD), ctypes.c_void_p, W.DWORD)

DwmGetWindowAttribute = _proto(dwmapi, "DwmGetWindowAttribute", HRESULT, W.HWND, W.DWORD, ctypes.c_void_p, W.DWORD)
ImmGetDefaultIMEWnd = _proto(imm32, "ImmGetDefaultIMEWnd", W.HWND, W.HWND)
ShellExecuteW = _proto(shell32, "ShellExecuteW", ctypes.c_void_p, W.HWND, W.LPCWSTR, W.LPCWSTR, W.LPCWSTR,
                       W.LPCWSTR, ctypes.c_int)
GetDpiForMonitor = (_proto(shcore, "GetDpiForMonitor", HRESULT, W.HMONITOR, ctypes.c_int, P(W.UINT), P(W.UINT),
                           optional=True) if shcore is not None else None)

# ================================================================================ helpers


def hwnd_int(h: Any) -> int:
    """HWND/handle return values (int or None) -> int."""
    return int(h or 0)


def rect_tuple(r: W.RECT) -> tuple[int, int, int, int]:
    """RECT -> (x, y, w, h)."""
    return (int(r.left), int(r.top), int(r.right - r.left), int(r.bottom - r.top))


def window_text(hwnd: int) -> str:
    """Title (GetWindowTextW with a fixed buffer: no WM_GETTEXTLENGTH round trip)."""
    if not hwnd:
        return ""
    buf = ctypes.create_unicode_buffer(512)
    GetWindowTextW(hwnd, buf, len(buf))
    return buf.value


def class_name(hwnd: int) -> str:
    if not hwnd:
        return ""
    buf = ctypes.create_unicode_buffer(256)
    GetClassNameW(hwnd, buf, len(buf))
    return buf.value


def window_pid(hwnd: int) -> int:
    if not hwnd:
        return 0
    pid = W.DWORD(0)
    GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def window_tid(hwnd: int) -> int:
    return int(GetWindowThreadProcessId(hwnd, None)) if hwnd else 0


def exstyle(hwnd: int) -> int:
    return int(GetWindowLongPtrW(hwnd, GWL_EXSTYLE)) & 0xFFFFFFFF if hwnd else 0


def exe_path(pid: int) -> tuple[str | None, int]:
    """(full image path or None, GetLastError of the failing call)."""
    if not pid:
        return None, 87
    h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None, ctypes.get_last_error()
    try:
        size = W.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value, 0
        return None, ctypes.get_last_error()
    finally:
        CloseHandle(h)


def is_cloaked(hwnd: int) -> bool:
    """DWMWA_CLOAKED (suspended UWP windows, other virtual desktops)."""
    val = W.DWORD(0)
    hr = DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(val), ctypes.sizeof(val))
    return hr == 0 and val.value != 0


def enum_windows() -> list[int]:
    """Top-level windows in z-order (topmost first)."""
    out: list[int] = []

    def cb(h: Any, _lp: Any) -> bool:
        out.append(hwnd_int(h))
        return True

    proc = WNDENUMPROC(cb)  # keep the callback referenced while EnumWindows runs
    EnumWindows(proc, 0)
    return out


def cursor_pos() -> tuple[int, int] | None:
    """GetCursorPos, None when it fails (e.g. the input desktop is not ours: locked session)."""
    p = W.POINT()
    if not GetCursorPos(ctypes.byref(p)):
        return None
    return int(p.x), int(p.y)


def tick_count() -> int:
    return int(GetTickCount()) & 0xFFFFFFFF


def last_input_tick() -> int | None:
    """GetLastInputInfo().dwTime, None when the call fails."""
    li = LASTINPUTINFO(cbSize=ctypes.sizeof(LASTINPUTINFO))
    if not GetLastInputInfo(ctypes.byref(li)):
        return None
    return int(li.dwTime) & 0xFFFFFFFF


def tick_newer(a: int, b: int) -> bool:
    """Wrap-safe 32-bit tick comparison: ``a`` is strictly newer than ``b`` (GetTickCount wraps after
    49.7 days): ``((a - b) & 0xFFFFFFFF) < 0x80000000`` and a != b."""
    d = (int(a) - int(b)) & 0xFFFFFFFF
    return d != 0 and d < 0x80000000


class MonitorRecord(NamedTuple):
    hmonitor: int
    device: str
    rect: tuple[int, int, int, int]
    work: tuple[int, int, int, int]
    primary: bool
    dpi: int


def monitor_record(hmon: int) -> MonitorRecord | None:
    info = MONITORINFOEXW()
    info.cbSize = ctypes.sizeof(MONITORINFOEXW)
    if not hmon or not GetMonitorInfoW(hmon, ctypes.byref(info)):
        return None
    dpi = 96
    if GetDpiForMonitor is not None:
        dx, dy = W.UINT(0), W.UINT(0)
        if GetDpiForMonitor(hmon, MDT_EFFECTIVE_DPI, ctypes.byref(dx), ctypes.byref(dy)) == 0 and dx.value:
            dpi = int(dx.value)
    return MonitorRecord(int(hmon), info.szDevice, rect_tuple(info.rcMonitor), rect_tuple(info.rcWork),
                         bool(info.dwFlags & MONITORINFOF_PRIMARY), dpi)


def enum_monitors() -> list[MonitorRecord]:
    """EnumDisplayMonitors + GetMonitorInfoW + GetDpiForMonitor (enumeration order)."""
    handles: list[int] = []

    def cb(hmon: Any, _hdc: Any, _rect: Any, _lp: Any) -> bool:
        handles.append(hwnd_int(hmon))
        return True

    proc = MONITORENUMPROC(cb)  # keep the callback referenced while EnumDisplayMonitors runs
    EnumDisplayMonitors(None, None, proc, 0)
    out = []
    for h in handles:
        rec = monitor_record(h)
        if rec is not None:
            out.append(rec)
    return out


def virtual_screen() -> tuple[int, int, int, int]:
    return (int(GetSystemMetrics(SM_XVIRTUALSCREEN)), int(GetSystemMetrics(SM_YVIRTUALSCREEN)),
            int(GetSystemMetrics(SM_CXVIRTUALSCREEN)), int(GetSystemMetrics(SM_CYVIRTUALSCREEN)))


def contexts_equal(a: Any, b: Any) -> bool:
    if AreDpiAwarenessContextsEqual is None or not a:
        return False
    return bool(AreDpiAwarenessContextsEqual(a, b))
