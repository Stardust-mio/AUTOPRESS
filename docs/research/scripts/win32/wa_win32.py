"""wa_win32.py - ctypes-only Win32 input layer (research prototype for the AutoPress "input" module).

Everything here is plain ctypes (no pywin32 / pyautogui / pynput / keyboard).
All argtypes / restype are declared explicitly; the INPUT layout is asserted (40 bytes on x64).
Imported by the wa_drv_*.py driver scripts in this folder.
"""
import ctypes
import ctypes.wintypes as W
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
imm32 = ctypes.WinDLL("imm32", use_last_error=True)

ULONG_PTR = ctypes.c_size_t      # pointer-sized unsigned (8 bytes on x64)
LRESULT = W.LPARAM                # pointer-sized signed
HGLOBAL = ctypes.c_void_p
IS64 = ctypes.sizeof(ctypes.c_void_p) == 8

# ---------------------------------------------------------------- structures
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", W.LONG), ("dy", W.LONG), ("mouseData", W.DWORD),
                ("dwFlags", W.DWORD), ("time", W.DWORD), ("dwExtraInfo", ULONG_PTR)]

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", W.WORD), ("wScan", W.WORD), ("dwFlags", W.DWORD),
                ("time", W.DWORD), ("dwExtraInfo", ULONG_PTR)]

class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", W.DWORD), ("wParamL", W.WORD), ("wParamH", W.WORD)]

class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", W.DWORD), ("u", _INPUTUNION)]

assert ctypes.sizeof(MOUSEINPUT) == (32 if IS64 else 24)
assert ctypes.sizeof(KEYBDINPUT) == (24 if IS64 else 16)
assert ctypes.sizeof(INPUT) == (40 if IS64 else 28), ctypes.sizeof(INPUT)

class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", W.UINT), ("dwTime", W.DWORD)]

class GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", W.DWORD), ("flags", W.DWORD), ("hwndActive", W.HWND),
                ("hwndFocus", W.HWND), ("hwndCapture", W.HWND), ("hwndMenuOwner", W.HWND),
                ("hwndMoveSize", W.HWND), ("hwndCaret", W.HWND), ("rcCaret", W.RECT)]

# ---------------------------------------------------------------- constants
INPUT_MOUSE, INPUT_KEYBOARD, INPUT_HARDWARE = 0, 1, 2
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE, KEYEVENTF_SCANCODE = 0x1, 0x2, 0x4, 0x8
MOUSEEVENTF_MOVE, MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0001, 0x0002, 0x0004
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
MOUSEEVENTF_WHEEL, MOUSEEVENTF_VIRTUALDESK, MOUSEEVENTF_ABSOLUTE = 0x0800, 0x4000, 0x8000
VK_BACK, VK_TAB, VK_RETURN, VK_SHIFT, VK_CONTROL, VK_MENU = 0x08, 0x09, 0x0D, 0x10, 0x11, 0x12
VK_CAPITAL, VK_ESCAPE, VK_SPACE, VK_END, VK_HOME = 0x14, 0x1B, 0x20, 0x23, 0x24
VK_LEFT, VK_UP, VK_RIGHT, VK_DOWN, VK_INSERT, VK_DELETE = 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E
VK_LWIN, VK_RWIN, VK_NUMLOCK, VK_F9 = 0x5B, 0x5C, 0x90, 0x78
VK_LSHIFT, VK_RSHIFT, VK_LCONTROL, VK_RCONTROL, VK_LMENU, VK_RMENU = 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5
MAPVK_VK_TO_VSC, MAPVK_VK_TO_VSC_EX = 0, 4
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 76, 77, 78, 79
SW_MINIMIZE, SW_RESTORE, SW_SHOW = 6, 9, 5
GA_ROOT = 2
WM_CLOSE, WM_HOTKEY, WM_IME_CONTROL = 0x0010, 0x0312, 0x0283
IMC_GETCONVERSIONMODE, IMC_SETCONVERSIONMODE, IMC_GETOPENSTATUS, IMC_SETOPENSTATUS = 1, 2, 5, 6
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
CF_UNICODETEXT, GMEM_MOVEABLE = 13, 0x0002
ERROR_ACCESS_DENIED, ERROR_HOTKEY_ALREADY_REGISTERED = 5, 1409
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
EXTRA_TAG = 0x41505253            # "APRS" in dwExtraInfo: lets a hook/target recognise our own input

# Keys that need KEYEVENTF_EXTENDEDKEY (E0-prefixed scan codes) when injected.
EXTENDED_VKS = {VK_RMENU, VK_RCONTROL, VK_INSERT, VK_DELETE, VK_HOME, VK_END, 0x21, 0x22,
                VK_LEFT, VK_UP, VK_RIGHT, VK_DOWN, VK_NUMLOCK, 0x2C, 0x6F, VK_LWIN, VK_RWIN, 0x5D, 0x03}

# ---------------------------------------------------------------- prototypes
def _proto(dll, name, restype, *argtypes):
    f = getattr(dll, name)
    f.restype = restype
    f.argtypes = list(argtypes)
    return f

SendInput = _proto(user32, "SendInput", W.UINT, W.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
GetForegroundWindow = _proto(user32, "GetForegroundWindow", W.HWND)
SetForegroundWindow = _proto(user32, "SetForegroundWindow", W.BOOL, W.HWND)
BringWindowToTop = _proto(user32, "BringWindowToTop", W.BOOL, W.HWND)
ShowWindow = _proto(user32, "ShowWindow", W.BOOL, W.HWND, ctypes.c_int)
IsIconic = _proto(user32, "IsIconic", W.BOOL, W.HWND)
IsWindow = _proto(user32, "IsWindow", W.BOOL, W.HWND)
GetWindowThreadProcessId = _proto(user32, "GetWindowThreadProcessId", W.DWORD, W.HWND, ctypes.POINTER(W.DWORD))
AttachThreadInput = _proto(user32, "AttachThreadInput", W.BOOL, W.DWORD, W.DWORD, W.BOOL)
GetCurrentThreadId = _proto(kernel32, "GetCurrentThreadId", W.DWORD)
GetWindowRect = _proto(user32, "GetWindowRect", W.BOOL, W.HWND, ctypes.POINTER(W.RECT))
WindowFromPoint = _proto(user32, "WindowFromPoint", W.HWND, W.POINT)
GetAncestor = _proto(user32, "GetAncestor", W.HWND, W.HWND, W.UINT)
GetCursorPos = _proto(user32, "GetCursorPos", W.BOOL, ctypes.POINTER(W.POINT))
SetCursorPos = _proto(user32, "SetCursorPos", W.BOOL, ctypes.c_int, ctypes.c_int)
GetSystemMetrics = _proto(user32, "GetSystemMetrics", ctypes.c_int, ctypes.c_int)
MapVirtualKeyExW = _proto(user32, "MapVirtualKeyExW", W.UINT, W.UINT, W.UINT, W.HKL)
VkKeyScanExW = _proto(user32, "VkKeyScanExW", W.SHORT, W.WCHAR, W.HKL)
GetKeyboardLayout = _proto(user32, "GetKeyboardLayout", W.HKL, W.DWORD)
GetKeyState = _proto(user32, "GetKeyState", W.SHORT, ctypes.c_int)
GetAsyncKeyState = _proto(user32, "GetAsyncKeyState", W.SHORT, ctypes.c_int)
ToUnicodeEx = _proto(user32, "ToUnicodeEx", ctypes.c_int, W.UINT, W.UINT, ctypes.POINTER(ctypes.c_ubyte * 256),
                     W.LPWSTR, ctypes.c_int, W.UINT, W.HKL)
OpenClipboard = _proto(user32, "OpenClipboard", W.BOOL, W.HWND)
CloseClipboard = _proto(user32, "CloseClipboard", W.BOOL)
EmptyClipboard = _proto(user32, "EmptyClipboard", W.BOOL)
GetClipboardData = _proto(user32, "GetClipboardData", W.HANDLE, W.UINT)
SetClipboardData = _proto(user32, "SetClipboardData", W.HANDLE, W.UINT, W.HANDLE)
IsClipboardFormatAvailable = _proto(user32, "IsClipboardFormatAvailable", W.BOOL, W.UINT)
RegisterClipboardFormatW = _proto(user32, "RegisterClipboardFormatW", W.UINT, W.LPCWSTR)
GetOpenClipboardWindow = _proto(user32, "GetOpenClipboardWindow", W.HWND)
GetClipboardSequenceNumber = _proto(user32, "GetClipboardSequenceNumber", W.DWORD)
CountClipboardFormats = _proto(user32, "CountClipboardFormats", ctypes.c_int)
GlobalAlloc = _proto(kernel32, "GlobalAlloc", HGLOBAL, W.UINT, ctypes.c_size_t)
GlobalLock = _proto(kernel32, "GlobalLock", ctypes.c_void_p, HGLOBAL)
GlobalUnlock = _proto(kernel32, "GlobalUnlock", W.BOOL, HGLOBAL)
GlobalFree = _proto(kernel32, "GlobalFree", HGLOBAL, HGLOBAL)
GlobalSize = _proto(kernel32, "GlobalSize", ctypes.c_size_t, HGLOBAL)
GetLastInputInfo = _proto(user32, "GetLastInputInfo", W.BOOL, ctypes.POINTER(LASTINPUTINFO))
GetTickCount = _proto(kernel32, "GetTickCount", W.DWORD)
RegisterHotKey = _proto(user32, "RegisterHotKey", W.BOOL, W.HWND, ctypes.c_int, W.UINT, W.UINT)
UnregisterHotKey = _proto(user32, "UnregisterHotKey", W.BOOL, W.HWND, ctypes.c_int)
PostMessageW = _proto(user32, "PostMessageW", W.BOOL, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
SendMessageTimeoutW = _proto(user32, "SendMessageTimeoutW", LRESULT, W.HWND, W.UINT, W.WPARAM, W.LPARAM,
                             W.UINT, W.UINT, ctypes.POINTER(ULONG_PTR))
ImmGetDefaultIMEWnd = _proto(imm32, "ImmGetDefaultIMEWnd", W.HWND, W.HWND)
GetGUIThreadInfo = _proto(user32, "GetGUIThreadInfo", W.BOOL, W.DWORD, ctypes.POINTER(GUITHREADINFO))
SetProcessDpiAwarenessContext = _proto(user32, "SetProcessDpiAwarenessContext", W.BOOL, ctypes.c_void_p)


def set_dpi_aware():
    """Per-monitor-v2 DPI awareness: every coordinate below is a physical pixel."""
    return bool(SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2))


def hwnd_int(h):
    return int(h or 0)

# ---------------------------------------------------------------- guards
class ForegroundLost(RuntimeError):
    pass


class Guard:
    """Call check() immediately before every keystroke / click; raises ForegroundLost otherwise."""

    def __init__(self, hwnd):
        self.hwnd = int(hwnd)
        self.skips = []

    def check(self, what="key", point=None):
        fg = hwnd_int(GetForegroundWindow())
        ok = fg == self.hwnd
        if ok and point is not None:
            under = WindowFromPoint(W.POINT(int(point[0]), int(point[1])))
            ok = hwnd_int(GetAncestor(under, GA_ROOT)) == self.hwnd
        if not ok:
            self.skips.append({"what": what, "fg": fg, "point": point, "t": time.time()})
            raise ForegroundLost(f"{what}: foreground={fg:#x} expected={self.hwnd:#x}")


class NoGuard:
    def check(self, what="key", point=None):
        return None

# ---------------------------------------------------------------- raw send
_last_send_tick = [0]


def send(inputs):
    """SendInput a list of INPUT; returns events inserted. Raises OSError when 0 were inserted."""
    n = len(inputs)
    arr = (INPUT * n)(*inputs)
    sent = SendInput(n, arr, ctypes.sizeof(INPUT))
    _last_send_tick[0] = GetTickCount()
    if sent != n:
        err = ctypes.get_last_error()
        raise OSError(err, f"SendInput inserted {sent}/{n} events (GetLastError={err})")
    return sent


def last_send_tick():
    return _last_send_tick[0]


def kbd(vk=0, scan=0, flags=0):
    i = INPUT(type=INPUT_KEYBOARD)
    i.ki = KEYBDINPUT(vk, scan, flags, 0, EXTRA_TAG)
    return i


def mouse(dx=0, dy=0, flags=0, data=0):
    i = INPUT(type=INPUT_MOUSE)
    i.mi = MOUSEINPUT(dx, dy, data & 0xFFFFFFFF, flags, 0, EXTRA_TAG)
    return i


def target_layout(hwnd=None):
    """HKL of the thread owning hwnd (default: foreground window) - the layout the target will use."""
    h = hwnd or GetForegroundWindow()
    tid = GetWindowThreadProcessId(h, None) if h else 0
    return GetKeyboardLayout(tid)


def vk_key(vk, up=False, layout=None, extended=None, with_scan=True):
    """One KEYBDINPUT for a virtual key with matching scan code (+E0 extended flag where needed)."""
    sc_ex = MapVirtualKeyExW(vk, MAPVK_VK_TO_VSC_EX, layout) if with_scan else 0
    ext = extended if extended is not None else (vk in EXTENDED_VKS or (sc_ex & 0xFF00) in (0xE000, 0xE100))
    flags = (KEYEVENTF_EXTENDEDKEY if ext else 0) | (KEYEVENTF_KEYUP if up else 0)
    return kbd(vk, sc_ex & 0xFF, flags)


def combo_inputs(vks, layout=None):
    """Press vks in order, release in reverse order - one atomic batch."""
    return [vk_key(v, False, layout) for v in vks] + [vk_key(v, True, layout) for v in reversed(vks)]


def press(vks, guard, layout=None, what="combo"):
    if isinstance(vks, int):
        vks = [vks]
    guard.check(what)
    return send(combo_inputs(vks, layout))

# ---------------------------------------------------------------- typing modes
def unicode_char_inputs(ch):
    """KEYEVENTF_UNICODE: one down+up per UTF-16 code unit (VK_PACKET on the target side)."""
    data = ch.encode("utf-16-le")
    out = []
    for i in range(0, len(data), 2):
        unit = data[i] | (data[i + 1] << 8)
        out.append(kbd(0, unit, KEYEVENTF_UNICODE))
        out.append(kbd(0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
    return out


def caps_lock_on():
    return bool(GetKeyState(VK_CAPITAL) & 1)


_caps_cache = {}


def caps_affects(vk, layout):
    """True if CapsLock changes the character this key produces (letters on US/zh-TW layouts)."""
    key = (vk, layout)
    if key not in _caps_cache:
        st = (ctypes.c_ubyte * 256)()
        buf = ctypes.create_unicode_buffer(8)
        sc = MapVirtualKeyExW(vk, MAPVK_VK_TO_VSC, layout)
        n1 = ToUnicodeEx(vk, sc, ctypes.byref(st), buf, 8, 0x4, layout)   # 0x4: keep kernel key state
        a = buf.value[:max(n1, 0)]
        st[VK_CAPITAL] = 0x01
        n2 = ToUnicodeEx(vk, sc, ctypes.byref(st), buf, 8, 0x4, layout)
        b = buf.value[:max(n2, 0)]
        _caps_cache[key] = a != b
    return _caps_cache[key]


class UnmappableChar(ValueError):
    pass


def vk_char_inputs(ch, layout=None, caps=None, hold_split=False):
    """VK + scan-code typing via VkKeyScanExW; Shift added when needed, inverted for CapsLock letters.
    Returns a list of INPUT for one character (atomic unless hold_split)."""
    r = VkKeyScanExW(ch, layout)
    if r == -1:
        raise UnmappableChar(ch)
    vk, shift_state = r & 0xFF, (r >> 8) & 0xFF
    if shift_state & 0x06:      # needs Ctrl/Alt (AltGr) - never injected by this module
        raise UnmappableChar(ch)
    need_shift = bool(shift_state & 1)
    if caps is None:
        caps = caps_lock_on()
    if caps and caps_affects(vk, layout):
        need_shift = not need_shift
    seq = []
    if need_shift:
        seq.append(vk_key(VK_LSHIFT, False, layout))
    seq += [vk_key(vk, False, layout), vk_key(vk, True, layout)]
    if need_shift:
        seq.append(vk_key(VK_LSHIFT, True, layout))
    return seq


def type_text(text, guard, mode="unicode", delay_ms=0, layout=None, caps=None, hold_ms=0):
    """Type text char-by-char. mode: 'unicode' | 'vk'. Each character is ONE atomic SendInput batch
    (so a crash can never leave Shift down) unless hold_ms > 0 (down/up split for frame-polling games)."""
    if layout is None:
        layout = target_layout(guard.hwnd if hasattr(guard, "hwnd") else None)
    t0 = time.perf_counter()
    for i, ch in enumerate(text):
        seq = unicode_char_inputs(ch) if mode == "unicode" else vk_char_inputs(ch, layout, caps)
        guard.check(f"char[{i}]")
        if hold_ms > 0:
            downs = [x for x in seq if not (x.ki.dwFlags & KEYEVENTF_KEYUP)]
            ups = [x for x in seq if x.ki.dwFlags & KEYEVENTF_KEYUP]
            try:
                send(downs)
                time.sleep(hold_ms / 1000)
            finally:
                send(ups)
        else:
            send(seq)
        if delay_ms and i < len(text) - 1:
            time.sleep(delay_ms / 1000)
    return time.perf_counter() - t0

# ---------------------------------------------------------------- clipboard
class ClipboardBusy(OSError):
    pass


def open_clipboard(hwnd=None, retries=50, delay_s=0.01):
    """OpenClipboard with retries (another process may hold it). Returns attempts used."""
    err = 0
    for attempt in range(1, retries + 1):
        if OpenClipboard(hwnd):
            return attempt
        err = ctypes.get_last_error()
        time.sleep(delay_s)
    raise ClipboardBusy(err, f"OpenClipboard failed {retries}x, holder hwnd={hwnd_int(GetOpenClipboardWindow()):#x}")


def get_clipboard_text(hwnd=None):
    open_clipboard(hwnd)
    try:
        if not IsClipboardFormatAvailable(CF_UNICODETEXT):
            return None
        h = GetClipboardData(CF_UNICODETEXT)
        if not h:
            return None
        p = GlobalLock(h)
        if not p:
            return None
        try:
            return ctypes.wstring_at(p)
        finally:
            GlobalUnlock(h)
    finally:
        CloseClipboard()


def _hglobal_from_bytes(data):
    h = GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not h:
        raise ctypes.WinError(ctypes.get_last_error())
    p = GlobalLock(h)
    if not p:
        GlobalFree(h)
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        ctypes.memmove(p, data, len(data))
    finally:
        GlobalUnlock(h)
    return h


_PRIVACY_FORMATS = None


def _privacy_formats():
    global _PRIVACY_FORMATS
    if _PRIVACY_FORMATS is None:
        _PRIVACY_FORMATS = [RegisterClipboardFormatW(n) for n in
                            ("ExcludeClipboardContentFromMonitorProcessing",
                             "CanIncludeInClipboardHistory", "CanUploadToCloudClipboard")]
    return _PRIVACY_FORMATS


def set_clipboard_text(text, hwnd=None, private=True):
    """CF_UNICODETEXT via GlobalAlloc(GMEM_MOVEABLE). private=True also keeps it out of
    Win+V clipboard history and cloud sync. Returns OpenClipboard attempts used."""
    data = text.encode("utf-16-le") + b"\x00\x00"
    attempts = open_clipboard(hwnd)
    try:
        if not EmptyClipboard():
            raise ctypes.WinError(ctypes.get_last_error())
        h = _hglobal_from_bytes(data)
        if not SetClipboardData(CF_UNICODETEXT, h):
            err = ctypes.get_last_error()
            GlobalFree(h)                     # only free on failure; on success the system owns it
            raise ctypes.WinError(err)
        if private:
            excl, hist, cloud = _privacy_formats()
            for fmt, payload in ((excl, b"\x00\x00\x00\x00"), (hist, b"\x00\x00\x00\x00"),
                                 (cloud, b"\x00\x00\x00\x00")):
                hh = _hglobal_from_bytes(payload)
                if not SetClipboardData(fmt, hh):
                    GlobalFree(hh)
    finally:
        CloseClipboard()
    return attempts


EnumClipboardFormats = _proto(user32, "EnumClipboardFormats", W.UINT, W.UINT)
GetClipboardFormatNameW = _proto(user32, "GetClipboardFormatNameW", ctypes.c_int, W.UINT, W.LPWSTR, ctypes.c_int)
# GDI-handle / owner-display / private formats cannot be copied as HGLOBAL bytes.
_NON_HGLOBAL = {2, 3, 9, 14, 0x80, 0x82, 0x83, 0x8E}


def clipboard_snapshot(hwnd=None):
    """Copy every HGLOBAL clipboard format (text, HTML, PNG, DIB, ...) -> list[(fmt, name, bytes)].
    CF_BITMAP etc. are skipped (the system re-synthesizes them from CF_DIB)."""
    snap = []
    open_clipboard(hwnd)
    try:
        f = 0
        while True:
            f = EnumClipboardFormats(f)
            if not f:
                break
            if f in _NON_HGLOBAL or 0x200 <= f <= 0x3FF:
                continue
            h = GetClipboardData(f)
            if not h:
                continue
            size = GlobalSize(h)
            p = GlobalLock(h)
            if not p:
                continue
            try:
                data = ctypes.string_at(p, size)
            finally:
                GlobalUnlock(h)
            nb = ctypes.create_unicode_buffer(128)
            GetClipboardFormatNameW(f, nb, 128)
            snap.append((f, nb.value, data))
    finally:
        CloseClipboard()
    return snap


def clipboard_restore(snap, hwnd=None):
    open_clipboard(hwnd)
    try:
        EmptyClipboard()
        for f, _name, data in snap:
            h = _hglobal_from_bytes(data)
            if not SetClipboardData(f, h):
                GlobalFree(h)
    finally:
        CloseClipboard()


def paste_text(text, guard, restore=True, restore_delay_ms=150, hwnd=None, layout=None):
    """Clipboard mode: set text, Ctrl+V (atomic batch), wait, restore previous clipboard TEXT."""
    prev = get_clipboard_text(hwnd) if restore else None
    set_clipboard_text(text, hwnd)
    try:
        guard.check("ctrl+v")
        send(combo_inputs([VK_LCONTROL, ord("V")], layout))
        time.sleep(restore_delay_ms / 1000)
    finally:
        if restore and prev is not None:
            set_clipboard_text(prev, hwnd)
    return prev

# ---------------------------------------------------------------- field helpers
def clear_field(guard, method="ctrl_a", layout=None, n_backspace=40):
    """ctrl_a: Ctrl+A then Backspace | end_shift_home: End, Shift+Home, Delete | backspace: End + N x Backspace."""
    if method == "ctrl_a":
        press([VK_LCONTROL, ord("A")], guard, layout, "ctrl+a")
        press(VK_BACK, guard, layout, "backspace")
    elif method == "end_shift_home":
        press(VK_END, guard, layout, "end")
        press([VK_LSHIFT, VK_HOME], guard, layout, "shift+home")
        press(VK_DELETE, guard, layout, "delete")
    else:
        press(VK_END, guard, layout, "end")
        for i in range(n_backspace):
            press(VK_BACK, guard, layout, f"backspace{i}")

# ---------------------------------------------------------------- mouse
def virtual_screen():
    return (GetSystemMetrics(SM_XVIRTUALSCREEN), GetSystemMetrics(SM_YVIRTUALSCREEN),
            GetSystemMetrics(SM_CXVIRTUALSCREEN), GetSystemMetrics(SM_CYVIRTUALSCREEN))


def to_absolute(x, y, formula="center"):
    """Physical pixel -> 0..65535 normalized coords over the VIRTUAL desktop (handles negative origins).
    'center' targets the middle of the pixel: ((x - vx) * 65536 + 32768) // vw  (clamped)."""
    vx, vy, vw, vh = virtual_screen()
    if formula == "center":
        nx = ((x - vx) * 65536 + 32768) // vw
        ny = ((y - vy) * 65536 + 32768) // vh
    else:  # classic "(x - vx) * 65535 / (vw - 1)"
        nx = round((x - vx) * 65535 / (vw - 1))
        ny = round((y - vy) * 65535 / (vh - 1))
    return max(0, min(65535, nx)), max(0, min(65535, ny))


def cursor_pos():
    p = W.POINT()
    GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def move_abs(x, y, formula="center"):
    nx, ny = to_absolute(x, y, formula)
    return send([mouse(nx, ny, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK)])


def click(x, y, guard, method="sendinput", button="left", double=False, settle_ms=0, hold_ms=0,
          restore_cursor=False):
    """method 'sendinput': absolute+virtualdesk move in SendInput; 'setcursorpos': SetCursorPos then
    SendInput button down/up. settle_ms: pause after the move (hover); hold_ms: pause between down/up."""
    down, up = ((MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP) if button == "left"
                else (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP))
    old = cursor_pos() if restore_cursor else None
    try:
        guard.check("click", (x, y))
        if method == "setcursorpos":
            SetCursorPos(int(x), int(y))
            moves = []
        else:
            nx, ny = to_absolute(x, y)
            moves = [mouse(nx, ny, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK)]
        clicks = 2 if double else 1
        if settle_ms == 0 and hold_ms == 0:
            seq = moves + [mouse(0, 0, down), mouse(0, 0, up)] * clicks
            send(seq)
        else:
            if moves:
                send(moves)
            time.sleep(settle_ms / 1000)
            for _ in range(clicks):
                guard.check("click", (x, y))
                send([mouse(0, 0, down)])
                try:
                    time.sleep(hold_ms / 1000)
                finally:
                    send([mouse(0, 0, up)])
    finally:
        if old:
            SetCursorPos(*old)

# ---------------------------------------------------------------- foreground
def window_tid(hwnd):
    return GetWindowThreadProcessId(hwnd, None)


def wait_foreground(hwnd, timeout_s=0.3, step_s=0.01):
    end = time.perf_counter() + timeout_s
    while True:
        if hwnd_int(GetForegroundWindow()) == int(hwnd):
            return True
        if time.perf_counter() >= end:
            return False
        time.sleep(step_s)


def fg_plain(hwnd):
    return bool(SetForegroundWindow(hwnd))


def fg_input_trick(hwnd):
    """Inject a harmless zero-distance relative mouse move (no button, no key), then SetForegroundWindow.
    The caller becomes the last input provider, which the foreground lock accepts."""
    send([mouse(0, 0, MOUSEEVENTF_MOVE)])
    return bool(SetForegroundWindow(hwnd))


def fg_attach_trick(hwnd):
    """AttachThreadInput(our thread -> current foreground thread), BringWindowToTop, SetForegroundWindow."""
    fg = GetForegroundWindow()
    me = GetCurrentThreadId()
    ftid = window_tid(fg) if fg else 0
    attached = bool(ftid and ftid != me and AttachThreadInput(me, ftid, True))
    try:
        BringWindowToTop(hwnd)
        return bool(SetForegroundWindow(hwnd))
    finally:
        if attached:
            AttachThreadInput(me, ftid, False)


def bring_to_foreground(hwnd, attempts=3, verify_s=0.25):
    """Recommended routine: restore if minimized -> plain -> input trick -> attach trick, verify each
    with GetForegroundWindow, retry. Returns (ok, method, tries)."""
    tries = 0
    if hwnd_int(GetForegroundWindow()) == int(hwnd):
        return True, "already", 0
    if IsIconic(hwnd):
        ShowWindow(hwnd, SW_RESTORE)
        if wait_foreground(hwnd, verify_s):
            return True, "restore", 0
    for _ in range(attempts):
        for name, fn in (("plain", fg_plain), ("input", fg_input_trick), ("attach", fg_attach_trick)):
            tries += 1
            fn(hwnd)
            if wait_foreground(hwnd, verify_s):
                return True, name, tries
    return False, None, tries

# ---------------------------------------------------------------- safety
MODIFIERS = [VK_LSHIFT, VK_RSHIFT, VK_LCONTROL, VK_RCONTROL, VK_LMENU, VK_RMENU, VK_LWIN, VK_RWIN]


def key_down(vk):
    return bool(GetAsyncKeyState(vk) & 0x8000)


def release_all_modifiers(pressed_by_us=(), allow_alt_win=False):
    """Abort recipe: key-up every modifier that is down. Alt/Win are only released when we pressed them
    (or allow_alt_win) because a lone Win-up/Alt-up after a user's own press opens Start / menus."""
    ups = []
    for vk in MODIFIERS:
        if not key_down(vk):
            continue
        if vk in (VK_LMENU, VK_RMENU, VK_LWIN, VK_RWIN) and not (allow_alt_win or vk in pressed_by_us):
            continue
        ups.append(vk_key(vk, up=True))
    if ups:
        send(ups)
    return [i.ki.wVk for i in ups]


def idle_ms():
    li = LASTINPUTINFO(cbSize=ctypes.sizeof(LASTINPUTINFO))
    GetLastInputInfo(ctypes.byref(li))
    return (GetTickCount() - li.dwTime) & 0xFFFFFFFF


def last_input_tick():
    li = LASTINPUTINFO(cbSize=ctypes.sizeof(LASTINPUTINFO))
    GetLastInputInfo(ctypes.byref(li))
    return li.dwTime


def user_active_since_our_input(slack_ms=100):
    """True if keyboard/mouse input arrived after our last SendInput (+slack) - i.e. the user moved."""
    ours = last_send_tick()
    return ours != 0 and ((last_input_tick() - ours) & 0xFFFFFFFF) < 0x7FFFFFFF and \
        ((last_input_tick() - ours) & 0xFFFFFFFF) > slack_ms

# ---------------------------------------------------------------- IME (cross-process query)
def ime_query(hwnd):
    """Open status / conversion mode of the target window's IME via its default IME window."""
    ime = ImmGetDefaultIMEWnd(hwnd)
    if not ime:
        return None
    res = ULONG_PTR()
    out = {}
    for name, cmd in (("open", IMC_GETOPENSTATUS), ("conv", IMC_GETCONVERSIONMODE)):
        ok = SendMessageTimeoutW(ime, WM_IME_CONTROL, cmd, 0, 0x2, 500, ctypes.byref(res))
        out[name] = res.value if ok else None
    return out


def ime_set_open(hwnd, is_open):
    ime = ImmGetDefaultIMEWnd(hwnd)
    if not ime:
        return False
    res = ULONG_PTR()
    return bool(SendMessageTimeoutW(ime, WM_IME_CONTROL, IMC_SETOPENSTATUS, 1 if is_open else 0, 0x2, 500,
                                    ctypes.byref(res)))
