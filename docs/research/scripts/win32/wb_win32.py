"""wb_win32 - ctypes-only Win32 bindings for the AutoPress R2b research (64-bit safe).

Every foreign function used here has argtypes AND restype declared (a missing
declaration truncates 64-bit handles/pointers to 32-bit ints).
Importing this module has no side effects: it does NOT change DPI awareness,
focus, the foreground window or anything else. All helpers are read-only.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import re
from dataclasses import dataclass, field

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
shcore = ctypes.WinDLL("shcore", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)

HRESULT = ctypes.c_long            # raw HRESULT (ctypes.HRESULT would raise automatically)
LONG_PTR = ctypes.c_ssize_t
DPI_AWARENESS_CONTEXT = wt.HANDLE  # pointer-sized pseudo handle
WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
MONITORENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HMONITOR, wt.HDC, ctypes.POINTER(wt.RECT), wt.LPARAM)


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT),
                ("dwFlags", wt.DWORD), ("szDevice", wt.WCHAR * 32)]


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wt.DWORD)]


def _f(dll, name, restype, *argtypes):
    fn = getattr(dll, name)
    fn.restype = restype
    fn.argtypes = list(argtypes)
    return fn


# ---- DPI -------------------------------------------------------------------------------
GetThreadDpiAwarenessContext = _f(user32, "GetThreadDpiAwarenessContext", DPI_AWARENESS_CONTEXT)
GetAwarenessFromDpiAwarenessContext = _f(user32, "GetAwarenessFromDpiAwarenessContext", ctypes.c_int, DPI_AWARENESS_CONTEXT)
AreDpiAwarenessContextsEqual = _f(user32, "AreDpiAwarenessContextsEqual", wt.BOOL, DPI_AWARENESS_CONTEXT, DPI_AWARENESS_CONTEXT)
GetWindowDpiAwarenessContext = _f(user32, "GetWindowDpiAwarenessContext", DPI_AWARENESS_CONTEXT, wt.HWND)
GetDpiAwarenessContextForProcess = _f(user32, "GetDpiAwarenessContextForProcess", DPI_AWARENESS_CONTEXT, wt.HANDLE)  # Win10 1803+
GetDpiForWindow = _f(user32, "GetDpiForWindow", wt.UINT, wt.HWND)
GetDpiForSystem = _f(user32, "GetDpiForSystem", wt.UINT)
GetProcessDpiAwareness = _f(shcore, "GetProcessDpiAwareness", HRESULT, wt.HANDLE, ctypes.POINTER(ctypes.c_int))
GetDpiForMonitor = _f(shcore, "GetDpiForMonitor", HRESULT, wt.HMONITOR, ctypes.c_int, ctypes.POINTER(wt.UINT), ctypes.POINTER(wt.UINT))
GetScaleFactorForMonitor = _f(shcore, "GetScaleFactorForMonitor", HRESULT, wt.HMONITOR, ctypes.POINTER(ctypes.c_int))

CTX_UNAWARE, CTX_SYSTEM, CTX_PMV1, CTX_PMV2, CTX_GDISCALED = (DPI_AWARENESS_CONTEXT(v) for v in (-1, -2, -3, -4, -5))
MDT_EFFECTIVE_DPI = 0

# ---- monitors / windows ----------------------------------------------------------------
EnumDisplayMonitors = _f(user32, "EnumDisplayMonitors", wt.BOOL, wt.HDC, ctypes.POINTER(wt.RECT), MONITORENUMPROC, wt.LPARAM)
GetMonitorInfoW = _f(user32, "GetMonitorInfoW", wt.BOOL, wt.HMONITOR, ctypes.POINTER(MONITORINFOEXW))
MonitorFromWindow = _f(user32, "MonitorFromWindow", wt.HMONITOR, wt.HWND, wt.DWORD)
MonitorFromPoint = _f(user32, "MonitorFromPoint", wt.HMONITOR, wt.POINT, wt.DWORD)   # POINT by value
GetSystemMetrics = _f(user32, "GetSystemMetrics", ctypes.c_int, ctypes.c_int)
EnumWindows = _f(user32, "EnumWindows", wt.BOOL, WNDENUMPROC, wt.LPARAM)
IsWindow = _f(user32, "IsWindow", wt.BOOL, wt.HWND)
IsWindowVisible = _f(user32, "IsWindowVisible", wt.BOOL, wt.HWND)
IsIconic = _f(user32, "IsIconic", wt.BOOL, wt.HWND)
IsZoomed = _f(user32, "IsZoomed", wt.BOOL, wt.HWND)
GetWindowTextLengthW = _f(user32, "GetWindowTextLengthW", ctypes.c_int, wt.HWND)
GetWindowTextW = _f(user32, "GetWindowTextW", ctypes.c_int, wt.HWND, wt.LPWSTR, ctypes.c_int)
GetClassNameW = _f(user32, "GetClassNameW", ctypes.c_int, wt.HWND, wt.LPWSTR, ctypes.c_int)
GetWindowThreadProcessId = _f(user32, "GetWindowThreadProcessId", wt.DWORD, wt.HWND, ctypes.POINTER(wt.DWORD))
GetWindowLongPtrW = _f(user32, "GetWindowLongPtrW", LONG_PTR, wt.HWND, ctypes.c_int)
GetWindow = _f(user32, "GetWindow", wt.HWND, wt.HWND, wt.UINT)
GetAncestor = _f(user32, "GetAncestor", wt.HWND, wt.HWND, wt.UINT)
WindowFromPoint = _f(user32, "WindowFromPoint", wt.HWND, wt.POINT)                  # POINT by value
GetClientRect = _f(user32, "GetClientRect", wt.BOOL, wt.HWND, ctypes.POINTER(wt.RECT))
ClientToScreen = _f(user32, "ClientToScreen", wt.BOOL, wt.HWND, ctypes.POINTER(wt.POINT))
GetWindowRect = _f(user32, "GetWindowRect", wt.BOOL, wt.HWND, ctypes.POINTER(wt.RECT))
GetForegroundWindow = _f(user32, "GetForegroundWindow", wt.HWND)                    # read-only check
GetCursorPos = _f(user32, "GetCursorPos", wt.BOOL, ctypes.POINTER(wt.POINT))        # read-only
DwmGetWindowAttribute = _f(dwmapi, "DwmGetWindowAttribute", HRESULT, wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD)

GA_ROOT, GW_OWNER = 2, 4
GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_EX_TOOLWINDOW, WS_EX_APPWINDOW, WS_EX_NOACTIVATE = 0x80, 0x40000, 0x08000000
DWMWA_EXTENDED_FRAME_BOUNDS, DWMWA_CLOAKED = 9, 14
MONITOR_DEFAULTTONULL, MONITOR_DEFAULTTONEAREST = 0, 2

# ---- processes / tokens ----------------------------------------------------------------
OpenProcess = _f(kernel32, "OpenProcess", wt.HANDLE, wt.DWORD, wt.BOOL, wt.DWORD)
CloseHandle = _f(kernel32, "CloseHandle", wt.BOOL, wt.HANDLE)
GetCurrentProcess = _f(kernel32, "GetCurrentProcess", wt.HANDLE)
QueryFullProcessImageNameW = _f(kernel32, "QueryFullProcessImageNameW", wt.BOOL, wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD))
OpenProcessToken = _f(advapi32, "OpenProcessToken", wt.BOOL, wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE))
GetTokenInformation = _f(advapi32, "GetTokenInformation", wt.BOOL, wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD))
GetSidSubAuthorityCount = _f(advapi32, "GetSidSubAuthorityCount", ctypes.POINTER(ctypes.c_ubyte), ctypes.c_void_p)
GetSidSubAuthority = _f(advapi32, "GetSidSubAuthority", ctypes.POINTER(wt.DWORD), ctypes.c_void_p, wt.DWORD)

PROCESS_QUERY_LIMITED_INFORMATION, TOKEN_QUERY = 0x1000, 0x0008
TokenElevationType, TokenElevation, TokenIntegrityLevel, TokenUIAccess = 18, 20, 25, 26
IL_NAMES = {0x0000: "untrusted", 0x1000: "low", 0x2000: "medium", 0x2100: "medium+", 0x3000: "high", 0x4000: "system"}


# ---- helpers ---------------------------------------------------------------------------
def hr_hex(hr: int) -> str:
    return f"0x{hr & 0xFFFFFFFF:08X}"


def awareness_name(ctx) -> str:
    """Name of a DPI_AWARENESS_CONTEXT (compare with AreDpiAwarenessContextsEqual, never by value)."""
    for name, ref in (("PER_MONITOR_AWARE_V2", CTX_PMV2), ("PER_MONITOR_AWARE", CTX_PMV1), ("SYSTEM_AWARE", CTX_SYSTEM),
                      ("UNAWARE_GDISCALED", CTX_GDISCALED), ("UNAWARE", CTX_UNAWARE)):
        if AreDpiAwarenessContextsEqual(ctx, ref):
            return name
    return f"OTHER(awareness={GetAwarenessFromDpiAwarenessContext(ctx)})"


def thread_awareness() -> str:
    return awareness_name(GetThreadDpiAwarenessContext())


def process_awareness() -> str:
    return awareness_name(GetDpiAwarenessContextForProcess(GetCurrentProcess()))


def rect_tuple(r: wt.RECT) -> tuple[int, int, int, int]:
    """(left, top, width, height)"""
    return (r.left, r.top, r.right - r.left, r.bottom - r.top)


def monitors() -> list[dict]:
    """Physical monitor rects + effective DPI (meaningful only in a per-monitor-aware process)."""
    out: list[dict] = []

    def cb(hmon, _hdc, _prc, _lp):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        GetMonitorInfoW(hmon, ctypes.byref(info))
        dx, dy, sf = wt.UINT(), wt.UINT(), ctypes.c_int()
        hr = GetDpiForMonitor(hmon, MDT_EFFECTIVE_DPI, ctypes.byref(dx), ctypes.byref(dy))
        GetScaleFactorForMonitor(hmon, ctypes.byref(sf))
        out.append({"hmonitor": hmon, "device": info.szDevice, "primary": bool(info.dwFlags & 1),
                    "rect": rect_tuple(info.rcMonitor), "work": rect_tuple(info.rcWork),
                    "dpi": (dx.value, dy.value), "dpi_hr": hr_hex(hr), "scale_pct": sf.value})
        return True

    proc = MONITORENUMPROC(cb)  # keep a reference while EnumDisplayMonitors runs
    EnumDisplayMonitors(None, None, proc, 0)
    return out


def window_text(hwnd) -> str:
    n = GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def class_name(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    GetClassNameW(hwnd, buf, 256)
    return buf.value


def window_pid(hwnd) -> int:
    pid = wt.DWORD()
    GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def exe_path(pid: int) -> tuple[str | None, int]:
    """(full image path or None, GetLastError)."""
    h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None, ctypes.get_last_error()
    try:
        size = wt.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value, 0
        return None, ctypes.get_last_error()
    finally:
        CloseHandle(h)


def is_cloaked(hwnd) -> bool:
    val = wt.DWORD()
    hr = DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(val), ctypes.sizeof(val))
    return hr == 0 and val.value != 0


def window_rect(hwnd) -> tuple[int, int, int, int]:
    r = wt.RECT()
    GetWindowRect(hwnd, ctypes.byref(r))
    return rect_tuple(r)


def frame_bounds(hwnd) -> tuple[int, int, int, int] | None:
    """Visible frame without the invisible resize borders (always physical pixels)."""
    r = wt.RECT()
    hr = DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r), ctypes.sizeof(r))
    return rect_tuple(r) if hr == 0 else None


def client_rect_screen(hwnd) -> tuple[int, int, int, int]:
    """Client area in screen coordinates: (left, top, width, height)."""
    r = wt.RECT()
    GetClientRect(hwnd, ctypes.byref(r))
    pt = wt.POINT(0, 0)
    ClientToScreen(hwnd, ctypes.byref(pt))
    return (pt.x, pt.y, r.right, r.bottom)


@dataclass
class WindowInfo:
    hwnd: int
    title: str
    cls: str
    pid: int
    exe: str | None
    exe_err: int
    iconic: bool
    rect: tuple[int, int, int, int]
    extra: dict = field(default_factory=dict)


def list_top_windows(include_untitled: bool = False, include_tool: bool = False) -> list[WindowInfo]:
    """Visible, non-cloaked, non-tool, titled top-level windows (Alt-Tab-like filter)."""
    hwnds: list[int] = []
    proc = WNDENUMPROC(lambda h, _lp: hwnds.append(h) or True)
    EnumWindows(proc, 0)
    out = []
    for h in hwnds:
        if not IsWindowVisible(h) or is_cloaked(h):
            continue
        ex = GetWindowLongPtrW(h, GWL_EXSTYLE)
        if ex & WS_EX_TOOLWINDOW and not ex & WS_EX_APPWINDOW and not include_tool:
            continue
        title = window_text(h)
        if not title and not include_untitled:
            continue
        pid = window_pid(h)
        exe, err = exe_path(pid)
        out.append(WindowInfo(h, title, class_name(h), pid, exe, err, bool(IsIconic(h)), window_rect(h)))
    return out


def find_window(exe_name: str | None, title_regex: str | None) -> int | None:
    """Re-find a window later by (exe basename, title regex); returns the first match."""
    rx = re.compile(title_regex) if title_regex else None
    for w in list_top_windows():
        if exe_name and (not w.exe or os.path.basename(w.exe).lower() != exe_name.lower()):
            continue
        if rx and not rx.search(w.title):
            continue
        return w.hwnd
    return None


def window_from_point_root(x: int, y: int) -> tuple[int | None, int | None]:
    """(deepest hwnd under the physical point, its GA_ROOT top-level)."""
    h = WindowFromPoint(wt.POINT(x, y))
    return h, (GetAncestor(h, GA_ROOT) if h else None)


def token_info(pid: int | None = None) -> dict:
    """Elevation/integrity of a process (None = ourselves). error = GetLastError of the failing step."""
    if pid is None:
        hproc, own = GetCurrentProcess(), False
    else:
        hproc, own = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid), True
        if not hproc:
            return {"ok": False, "step": "OpenProcess", "error": ctypes.get_last_error()}
    tok = wt.HANDLE()
    try:
        if not OpenProcessToken(hproc, TOKEN_QUERY, ctypes.byref(tok)):
            return {"ok": False, "step": "OpenProcessToken", "error": ctypes.get_last_error()}
        res: dict = {"ok": True}
        val, ret = wt.DWORD(), wt.DWORD()
        for key, cls in (("elevated", TokenElevation), ("elevation_type", TokenElevationType), ("uiaccess", TokenUIAccess)):
            if GetTokenInformation(tok, cls, ctypes.byref(val), ctypes.sizeof(val), ctypes.byref(ret)):
                res[key] = val.value
        buf = ctypes.create_string_buffer(256)
        if GetTokenInformation(tok, TokenIntegrityLevel, buf, len(buf), ctypes.byref(ret)):
            sid = SID_AND_ATTRIBUTES.from_buffer(buf).Sid
            n = GetSidSubAuthorityCount(sid).contents.value
            rid = GetSidSubAuthority(sid, n - 1).contents.value
            res["integrity_rid"] = rid
            res["integrity"] = IL_NAMES.get(rid, hex(rid))
        return res
    finally:
        if tok:
            CloseHandle(tok)
        if own:
            CloseHandle(hproc)
