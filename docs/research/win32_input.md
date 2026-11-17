# R2a: Win32 input injection, focus and global hotkeys (ctypes only)

Measured 2026-11-17 on Windows 10 LTSC 2021 (19044), Python 3.12.10, PyQt6 6.12.1 / Qt 6.12.0, two 1920x1080
monitors at 100 % (virtual desktop origin **-1920,0**, 3840x1080), keyboard layout 0x04040404 (zh-TW, Microsoft
Bopomofo IME, the only layout), NumLock on, ForegroundLockTimeout 200000 ms. Medium integrity, not elevated.
Every number below comes from a run of the named script; raw data is in `scripts/win32/wa_results/wa_result_*.json`.
DPI mapping, window enumeration, elevation detection and capture are R2b (`win32_windows.md`), not repeated here.

## 0. Recommendations
1. **Default typing mode: KEYEVENTF_UNICODE, one atomic SendInput per character.** 100 % exact in every Qt test,
   with or without the zh-TW IME (ASCII codes), CapsLock-independent. Offer **clipboard paste** as mode 2 (fastest,
   IME-proof, also CJK) and **VK + scan code** as "game mode" (the only mode raw-input / polling games can see).
2. **zh-TW users: the Bopomofo IME breaks VK typing** (0/60 exact in Chinese mode). Before VK typing, close the
   target's IME cross-process with `WM_IME_CONTROL/IMC_SETOPENSTATUS 0` (60/60 afterwards), restore it after.
3. Foreground: `bring_to_foreground()` = restore-if-minimized, then SetForegroundWindow, then zero-move input +
   SetForegroundWindow, then AttachThreadInput; verify each step with GetForegroundWindow (in-process 10/10).
4. Guard **every** keystroke/click: GetForegroundWindow() == game HWND, and for clicks WindowFromPoint() root ==
   game HWND; abort the code on mismatch. Abort/pause when GetLastInputInfo shows input newer than our own.
5. Never split a key's down/up across SendInput calls unless a hold time is needed; release modifiers in
   `finally` (killed injector left Shift down 8/10 with split calls, 0/10 atomic).
6. Global hotkeys: RegisterHotKey on the main window HWND + `QWidget.nativeEvent`, with MOD_NOREPEAT.
   No WH_KEYBOARD_LL hook is needed. Handle error 1409 ("hotkey already used") in the UI.
7. Warn before running when the game's integrity level is higher (R2b `input_permission()`): UIPI drops our
   input silently (SendInput still returns the full count, measured).

## 1. Test bench and how to rerun
`wa_target_app.py` (separate PyQt6 process, unique title): QLineEdit + "Submit" + status label; logs every
text change, submit (with the field content), key / IME / focus / mouse / activation event, optional raw input
(`--rawinput`) and 60 Hz GetAsyncKeyState polling (`--poll`) as JSON lines (`--log`); writes HWND, pid and the
**physical** rects of client area, line edit and Submit button to `--info` at startup and after move/resize.
`--ime off` calls `ImmDisableIME(-1)` (no IME), `--ime on` keeps the user's IME. Drivers are separate processes
(`wa_harness.Target` launches the target and tails its log); the ctypes layer is `wa_win32.py`.
All drivers check the foreground before every keystroke/click and send keys/clicks only to their own windows (the
foreground trick and `wa_drv_misc.py` send zero-distance mouse moves only), pause 2 s after every 14 s of input and
abort if the user touched mouse/keyboard meanwhile, release modifiers in `finally`, and restore CapsLock,
clipboard (all formats) and cursor.
Run from the repository root with the project venv (the harness starts the target with it):

| Command (`.venv/Scripts/python.exe docs/research/scripts/win32/...`) | Test | Time |
|---|---|---|
| `wa_drv_typing.py --plan main` / `--plan ime` / `--plan cliprestore` | 1, IME, clipboard timing | 4 / 2 / 1 min |
| `wa_drv_keys.py` | 2 special keys, clear recipes, Enter latency | 30 s |
| `wa_drv_mouse.py` | 3 normalization, clicks, double-click | 60 s |
| `wa_drv_foreground.py` and `... --methods inproc_plain,inproc_restore,inproc_attach,inproc_plain,inproc_routine --tag _noinject` | 4 | 1 min each |
| `wa_drv_hotkey.py` (uses `wa_hotkey_app.py`) | 5 | 20 s |
| `wa_drv_stuck.py` (uses `wa_stuck_child.py`) | 6 | 25 s |
| `wa_drv_uipi.py` (uses `wa_uipi_child.py`) | 7 | 5 s |
| `wa_drv_polling.py` | 8 polling / raw-input readers | 25 s |
| `wa_drv_misc.py` (no keys/clicks; opens 3 targets briefly), `wa_check_doc.py` (executes section 10) | pitfalls, doc check | 15 s each |

## 2. Typing modes (test 1) - `wa_drv_typing.py`, 20 runs per cell, field cleared between runs
IME detached (`--ime off`). "cps" = characters / (first SendInput -> target's final textChanged), median.

| Mode | ABCD-1234-EFGH | AbC-123_xyz | a1B2c3D4e5F6g7H8 | 測試ABC | cps @0 / 5 / 15 ms delay |
|---|---|---|---|---|---|
| unicode (KEYEVENTF_UNICODE per UTF-16 unit) | 60/60 | 60/60 | 60/60 | 60/60 | 1134-1376 / 175-205 / 66-77 |
| vk (VkKeyScanExW + MapVirtualKeyExW, Shift) | 60/60 | 60/60 | 60/60 | n/a | 770-1045 / 177-180 / 66-68 |
| vk, CapsLock ON (Shift inverted for letters) | 60/60 | 60/60 | 60/60 | n/a | 916-1167 / 177-181 / 66-68 |
| unicode, CapsLock ON (0 ms) | 20/20 | 20/20 | 20/20 | - | 1104-1326 |
| clipboard (Ctrl+V, restore after 100 ms) | 20/20 | 20/20 | 20/20 | 20/20 | whole code in 1.9-2.2 ms |
| clipboard, CapsLock ON | 20/20 | - | - | - | 2.2 ms |

(60/60 = 20 runs at each of 0, 5, 15 ms.) Qt needed no inter-key delay at all. CapsLock: `GetKeyState(VK_CAPITAL)&1`
read in the background driver tracked the toggle correctly; letters are the only CapsLock-affected keys on this
layout (ToUnicodeEx check over printable ASCII, `wa_drv_misc.py`). The driver turned CapsLock on with an injected
VK_CAPITAL press and restored it.

**zh-TW Bopomofo IME in Chinese mode** (`--plan ime`, target default state open=1, conv=1, 5 ms delay, 20 runs):

| Mode | ASCII strings | 測試ABC | What happened (target log) |
|---|---|---|---|
| unicode | 60/60 | 0/20 | ASCII arrives as IME commits; CJK stays in the composition (preedit "測試ABC") |
| vk | **0/60** | n/a | lower-case letters/digits become Bopomofo (`b`->ㄖ, `1`->ㄅ); result e.g. "AC_" |
| clipboard | 60/60 | 20/20 | IME not involved |
| vk after `ime_set_open(hwnd, False)` | 60/60 | n/a | IME state 1/1 -> 0/0 -> restored to 1/1 |

`ime_query()` / `ime_set_open()` send WM_IME_CONTROL (IMC_GETOPENSTATUS 5, IMC_GETCONVERSIONMODE 1,
IMC_SETOPENSTATUS 6) to `ImmGetDefaultIMEWnd(target)`; works cross-process with this TSF IME. Qt's
`WA_InputMethodEnabled=False` did **not** detach it (state stayed open/Chinese, `wa_drv_misc.py` ime_detach).

**Clipboard** (`--plan cliprestore`, `wa_drv_misc.py`): restoring the previous clipboard 0 ms after Ctrl+V pasted the
OLD content 20/20 times; 2, 10, 30, 100 ms all 20/20 (the paste showed up ~2 ms after `paste_text()` began). A holder
that opened the clipboard with a real HWND made OpenClipboard fail with **ERROR_ACCESS_DENIED (5)** for its whole 0.4
s; the 10 ms retry loop succeeded on attempt 39. A holder that opened with NULL did **not** block other openers.
OpenClipboard(NULL)+EmptyClipboard+SetClipboardData succeeded here although the docs say it fails; pass the Qt main
window HWND anyway. Snapshot/restore of every HGLOBAL format round-tripped the user's image clipboard (PNG, CF_DIBV5,
HTML Format, CF_DIB) byte-exact. The three privacy formats [M4] are set on every write.

## 3. Special keys and clear field (test 2) - `wa_drv_keys.py`
All checks passed: Home/End/Left/Right/Delete with KEYEVENTF_EXTENDEDKEY moved/deleted as expected ("ABCD-1234" ->
"XABCD-12YZ"), Backspace, Ctrl+A+Backspace -> "", Enter -> submit (src enter), Tab / Shift+Tab move focus
edit<->Submit, Esc reaches the field, Up/Down arrive with scan 0xE048/0xE050. Extended flag matters for scan-code
readers: VK_LEFT **without** the flag reached Qt as scan 0x4B + KeypadModifier and raw input without RI_KEY_E0; with
it Qt saw 0xE04B and raw input flags 2/3 (RI_KEY_E0). Scan-code-only injection (KEYEVENTF_SCANCODE) of 0x4B without
the flag typed **"4"** (NumLock on); with the flag it moved the caret. `MapVirtualKeyExW(VK_LEFT, MAPVK_VK_TO_VSC_EX)`
returned 0x4B (no E0; same for Delete/Home) but 0xE01D/0xE038/0xE035 for RCtrl/RAlt/Divide, so keep an explicit
extended-key table (`EXTENDED_VKS`). wVk-only input (wScan=0) gave raw-input MakeCode 0. Clear recipes, caret at a
random position, 4-20 chars, 20 runs each: Ctrl+A,Backspace 20/20; End,Shift+Home,Delete 20/20; End + 25x Backspace
20/20. Enter -> submit latency: median 1.2 ms, max 1.7 ms (20).

## 4. Mouse (test 3) - `wa_drv_mouse.py`
Normalization over the virtual desktop, 159 points incl. corners and both sides of x=0 (cursor read back):
`nx = ((x - vx) * 65536 + 32768) // vw` (pixel centre) **159/159 exact**; the classic `(x - vx) * 65535 / (vw - 1)`
157/159 (two 1-px misses at x=-1874, -1901). Without MOUSEEVENTF_VIRTUALDESK, 0..65535 maps to the primary monitor
only ((65535,65535) -> (1919,1079)). Cursor restored after the scan.
Clicks on Submit at random points 3 px inside, 20 each: SendInput move+down+up in one call 20/20, SetCursorPos +
SendInput down/up 20/20, SendInput with 30 ms settle + 30 ms hold 20/20; position error 0 px in all (Qt-reported
local press position vs requested physical point). Edge test: 1 px inside each corner submitted 4/4, 1 px outside
each edge did not 4/4. Double-click on the line edit: four events in ONE SendInput call -> **0/20** Qt
double-clicks; with a 20 ms hold per click (down, 20 ms, up, twice) 20/20. Two SINGLE clicks on one spot 100 ms
apart: Qt reported the second as a double-click 5/5 (>GetDoubleClickTime 500 ms apart: 0/5); QPushButton still
clicked 10/10, a game may not.
`restore_cursor=True` put the cursor back exactly. Click -> focus-in latency median 3.1 ms, max 6.1 ms (10).

## 5. Foreground (test 4) - `wa_drv_foreground.py`
Each trial: a helper process first makes a decoy window (ours) foreground, then one method is tried on the
target, verified with GetForegroundWindow within 300 ms. "fresh" = a new process per attempt; "in-process" = the
long-running driver, which is what AutoPress is.

| Method | fresh process | in-process (run 1) | in-process (`_noinject`) |
|---|---|---|---|
| SetForegroundWindow only | 10/10 | **1/10** (only the first) | 11/20 (the first, and each one right after an AttachThreadInput success) |
| zero-distance mouse move (SendInput) + SetForegroundWindow | 10/10 | 10/10 | - |
| AttachThreadInput(fg thread) + BringWindowToTop + SetForegroundWindow | 10/10 | 10/10 | 10/10 |
| minimized target: ShowWindow(SW_RESTORE) only | 10/10 | 10/10 | 10/10 |
| `bring_to_foreground()` routine | 10/10 (plain) | - | 10/10 (always via the input step) |

Fresh processes always succeeded with plain SetForegroundWindow, so testing activation from a newly started
helper is misleading. The docs list the rules ("The calling process received the last input event", lock timeout
etc. [M2]); the zero-move trick presumably counts as that rule (mechanism undocumented) and injects no key,
click or cursor movement. A received WM_HOTKEY also grants the right: the hotkey receiver's SetForegroundWindow
failed after a posted control message and
succeeded right after the hotkey (`wa_drv_hotkey.py` step 7). Routine recommended (`wa_win32.bring_to_foreground`):
if IsIconic -> SW_RESTORE; then plain; then input trick; then attach trick; verify each for 250 ms; 3 rounds;
else ask the user to click the game window.

## 6. Global hotkeys (test 5) - `wa_drv_hotkey.py`, Ctrl+Shift+F9 injected while wa_target_app is foreground
* `QWidget.nativeEvent(self, eventType, message)`: eventType == b"windows_generic_MSG"; `message` is a sip.voidptr
  to MSG -> `ctypes.wintypes.MSG.from_address(int(message))`; return `(True, 0)` when handled, `(False, 0)` otherwise
  (`(bool, sip.voidptr(0))` also accepted, no errors in either form). 5/5 received, lParam = mods 6 | vk 0x78 << 16.
* The foreground app never saw F9 (down or up); Ctrl/Shift down/up still reached it.
* MOD_NOREPEAT: 6 auto-repeat key-downs -> 1 WM_HOTKEY. Without it -> 6.
* Second RegisterHotKey of the same combo (other process, or same process other id): fails, GetLastError **1409**
  (ERROR_HOTKEY_ALREADY_REGISTERED). UnregisterHotKey in closeEvent returned TRUE; a new process could then register.
* QAbstractNativeEventFilter (app-wide): a window-bound WM_HOTKEY was seen **twice** (both b"windows_generic_MSG")
  when returning False, once when returning `(True, 0)`. Thread hotkey (RegisterHotKey(NULL)) seen once, MSG.hwnd 0.
* Docs [M3]: F12 is reserved for the debugger; MOD_WIN shortcuts are reserved for the OS.
No WH_KEYBOARD_LL hook is needed: RegisterHotKey fired for injected input while another process was foreground
(real key presses are its documented path [M3]).

## 7. Stuck-key safety (test 6) - `wa_drv_stuck.py`
Shift/Ctrl (left, right, mixed) pressed without key-up, then `release_all_modifiers()`: GetAsyncKeyState showed
all 11 modifier VKs up afterwards, 5/5 combos. Injector killed with TerminateProcess at a random moment, 10 kills
each: separate SendInput calls for Shift down / A / Shift up -> **Shift stuck 8/10**; one atomic call per character
-> 0/10; the recipe released every stuck key. The recipe key-ups only modifiers that are down and skips Alt/Win
unless we pressed them (a lone Win/Alt up after the user's own press opens Start / menus); Alt/Win paths were not
exercised (never injected).

## 8. UIPI (test 7) - `wa_drv_uipi.py`
Docs [M1]: "This function fails when it is blocked by UIPI. Note that neither GetLastError nor the return value will
indicate the failure was caused by UIPI blocking." and "Applications are permitted to inject input only into
applications that are at an equal or lesser integrity level." Elevating needs a UAC prompt, so the same rule was
measured one level down: a **low-integrity** child (`wa_uipi_child.py` via CreateProcessAsUserW, duplicated token
labelled S-1-16-4096) typing into the medium-IL target: SendInput returned 8/8, GetLastError 0, target received
**nothing**; PostMessage WM_CHAR failed with error 5. Medium-IL control: target got "PUIPI". Proposal: before a run
call R2b's `input_permission(game_hwnd)`; "blocked_elevated" -> block with "遊戲以系統管理員身分執行，AutoPress 也必須以系統管理員身分執行才能輸入"
+ a "Restart as administrator" button (ShellExecuteW "runas"); "unknown" -> warn, run one code, and require the
post-submit OCR check to see the typed text before continuing.

## 9. Timing and game-like readers (test 8) - `wa_drv_polling.py` + the latencies above
Typing "abcdefghij" 5x per row into a target that also polls GetAsyncKeyState every 16 ms and logs raw input:

| Mode, key hold | Text field | 60 Hz polling saw key down | Raw input key-downs |
|---|---|---|---|
| vk, hold 0 (atomic) | 5/5 | 0/50 (low "pressed" bit 47/50, unreliable) | 50/50 |
| vk, hold 10 / 20 / 40 ms | 5/5 | 45/50 (partial) / 50/50 / 50/50 | 50/50 |
| unicode (VK_PACKET) | 5/5 | 0/50 | **0/50** |

Injected raw input has hDevice = 0 (games can tell it is synthetic). Recommended defaults (Qt needed far less):

| Step | Qt measured | Default | Notes |
|---|---|---|---|
| between characters | 0 ms was 100 % | 15 ms (~66 cps, 0.25 s per 16-char code) | 30-50 ms if a game drops keys |
| key hold (down->up) | 0 ms | 0 (text-field mode); 30 ms (game mode) | 60 Hz polling needed >= 20 ms |
| after activation | verified immediately | 200 ms after GetForegroundWindow matches | full-screen games 500 ms+ |
| after click, before typing | focus-in 3.1 ms (max 6.1) | 120 ms | caret/animations in games |
| mouse move -> down -> up | atomic worked | 30 ms settle, 30 ms hold | hover-driven game UIs |
| Ctrl+V -> restore clipboard | >= 2 ms | 300 ms | 0 ms pasted the old content |
| after Enter/Submit | submit event 1.2 ms (max 1.7) | 800 ms, then OCR-poll result up to 5 s | stop on rate-limit text |
| between codes | - | >= 1.5 s | never faster than the user could |

## 10. Verified ctypes snippets (condensed from `wa_win32.py`; this block is executed as-is by `wa_check_doc.py`)
```python
user32 = ctypes.WinDLL("user32", use_last_error=True); kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
ULONG_PTR = ctypes.c_size_t                     # pointer-sized; c_ulong here makes INPUT 28 bytes -> error 87
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", W.LONG), ("dy", W.LONG), ("mouseData", W.DWORD), ("dwFlags", W.DWORD),
                ("time", W.DWORD), ("dwExtraInfo", ULONG_PTR)]
class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", W.WORD), ("wScan", W.WORD), ("dwFlags", W.DWORD), ("time", W.DWORD), ("dwExtraInfo", ULONG_PTR)]
class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", W.DWORD), ("wParamL", W.WORD), ("wParamH", W.WORD)]
class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]
class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", W.DWORD), ("u", _INPUTUNION)]
assert ctypes.sizeof(INPUT) == 40               # measured: MOUSEINPUT 32, KEYBDINPUT 24, HARDWAREINPUT 8
SendInput = user32.SendInput; SendInput.argtypes = [W.UINT, ctypes.POINTER(INPUT), ctypes.c_int]; SendInput.restype = W.UINT
for f, res, args in ((kernel32.GlobalAlloc, ctypes.c_void_p, [W.UINT, ctypes.c_size_t]),
                     (kernel32.GlobalLock, ctypes.c_void_p, [ctypes.c_void_p]), (kernel32.GlobalUnlock, W.BOOL, [ctypes.c_void_p]),
                     (kernel32.GlobalFree, ctypes.c_void_p, [ctypes.c_void_p]), (user32.OpenClipboard, W.BOOL, [W.HWND]),
                     (user32.EmptyClipboard, W.BOOL, []), (user32.CloseClipboard, W.BOOL, []),
                     (user32.SetClipboardData, W.HANDLE, [W.UINT, W.HANDLE]), (user32.GetClipboardData, W.HANDLE, [W.UINT]),
                     (user32.GetForegroundWindow, W.HWND, []), (user32.SetForegroundWindow, W.BOOL, [W.HWND]),
                     (user32.AttachThreadInput, W.BOOL, [W.DWORD, W.DWORD, W.BOOL]),
                     (user32.MapVirtualKeyExW, W.UINT, [W.UINT, W.UINT, W.HKL]), (user32.VkKeyScanExW, W.SHORT, [W.WCHAR, W.HKL]),
                     (user32.GetAsyncKeyState, W.SHORT, [ctypes.c_int]), (user32.WindowFromPoint, W.HWND, [W.POINT])):
    f.restype, f.argtypes = res, args           # default restype c_int truncated GlobalLock 0x1f500fb9770 -> 0xfb9770

def kbd(vk=0, scan=0, flags=0):
    i = INPUT(type=1); i.ki = KEYBDINPUT(vk, scan, flags, 0, EXTRA_TAG); return i
def vk_key(vk, up=False, layout=None):          # scan code + E0 flag; table needed (MapVirtualKeyEx says 0x4B for VK_LEFT)
    sc = user32.MapVirtualKeyExW(vk, 4, layout)  # MAPVK_VK_TO_VSC_EX
    ext = vk in EXTENDED_VKS or (sc & 0xFF00) in (0xE000, 0xE100)
    return kbd(vk, sc & 0xFF, (0x1 if ext else 0) | (0x2 if up else 0))
def unicode_char_inputs(ch):                    # down+up per UTF-16 unit, send each char in ONE SendInput call
    b = ch.encode("utf-16-le"); units = [b[i] | b[i + 1] << 8 for i in range(0, len(b), 2)]
    return [x for u in units for x in (kbd(0, u, 0x4), kbd(0, u, 0x4 | 0x2))]
def set_clipboard_text(text, hwnd):             # GMEM_MOVEABLE; free only on failure; retry OpenClipboard
    data = text.encode("utf-16-le") + b"\0\0"; h = kernel32.GlobalAlloc(0x2, len(data))
    p = kernel32.GlobalLock(h); ctypes.memmove(p, data, len(data)); kernel32.GlobalUnlock(h)
    open_clipboard(hwnd)                        # 50 x OpenClipboard, sleep 10 ms on ERROR_ACCESS_DENIED
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(13, h): kernel32.GlobalFree(h); raise ctypes.WinError(ctypes.get_last_error())
        # + "ExcludeClipboardContentFromMonitorProcessing", "CanIncludeInClipboardHistory"=0, "CanUploadToCloudClipboard"=0
    finally:
        user32.CloseClipboard()
def to_absolute(x, y):                          # physical px -> 0..65535 over the virtual desktop (negative origin OK)
    vx, vy, vw, vh = (user32.GetSystemMetrics(i) for i in (76, 77, 78, 79))
    return ((x - vx) * 65536 + 32768) // vw, ((y - vy) * 65536 + 32768) // vh   # flags MOVE|ABSOLUTE|VIRTUALDESK
```

## 11. Recommended `autopress/platform/input.py` API
```python
class ForegroundLost(RuntimeError): ...
class UserActivity(RuntimeError): ...
class ClipboardBusy(OSError): ...
class InjectGuard:      # check() before EVERY key/click: foreground == hwnd, point root == hwnd, no newer user input
    def __init__(self, hwnd: int, abort_on_user_input: bool = True, slack_ms: int = 200): ...
    def check(self, what: str, point: tuple[int, int] | None = None) -> None: ...
def bring_to_foreground(hwnd: int, attempts: int = 3, verify_s: float = 0.25) -> tuple[bool, str | None]: ...
def type_text(text: str, guard: InjectGuard, mode: Literal["unicode", "clipboard", "vk"] = "unicode",
              key_delay_ms: int = 15, hold_ms: int = 0, close_ime: bool = True, restore_delay_ms: int = 300) -> None: ...
def press_keys(vks: Sequence[int], guard: InjectGuard) -> None: ...      # atomic combo: Ctrl+A, Enter, Esc, Tab ...
def clear_field(guard: InjectGuard, method: Literal["ctrl_a", "end_shift_home", "backspace"] = "ctrl_a") -> None: ...
def click(x: int, y: int, guard: InjectGuard, button: str = "left", double: bool = False, settle_ms: int = 30,
          hold_ms: int = 30, restore_cursor: bool = False) -> None: ...  # physical px, SendInput ABSOLUTE|VIRTUALDESK
def release_all_modifiers(pressed_by_us: Iterable[int] = ()) -> list[int]: ...   # in finally / on abort hotkey
def ime_state(hwnd: int) -> dict | None: ...
def ime_set_open(hwnd: int, is_open: bool) -> bool: ...
def clipboard_snapshot() -> list[tuple[int, str, bytes]]: ...
def clipboard_restore(snap: list[tuple[int, str, bytes]]) -> None: ...
def user_active_since_last_injection(slack_ms: int = 200) -> bool: ...  # GetLastInputInfo vs our last SendInput
class GlobalHotkeys(QObject): ...  # RegisterHotKey(main HWND) + nativeEvent; signal triggered(id); register() -> (ok, err)
```

## 12. Pitfalls (measured unless cited)
1. Bopomofo IME (zh-TW default) eats VK typing; KEYEVENTF_UNICODE CJK text stays uncommitted under it.
2. KEYEVENTF_UNICODE is invisible to raw input and key-state polling; wScan=0 gives raw MakeCode 0.
3. MAPVK_VK_TO_VSC_EX does not mark arrows/Home/Delete as extended; without KEYEVENTF_EXTENDEDKEY scan-code
   readers see the numpad key, and scan-code-only arrows type digits when NumLock is on.
4. Wrong cbSize -> SendInput returns 0, error 87 (28/32/36/44 tried). Missing restype truncates 64-bit pointers.
5. Fresh helper processes may set the foreground freely; the long-running app may not (1/10). Test in-process.
6. Restoring the clipboard right after Ctrl+V pastes the old content; restore after a delay and snapshot all formats
   (text-only restore would have destroyed the user's copied image).
7. Atomic double-clicks are ignored by Qt; consecutive single clicks at one spot within 500 ms become double-clicks.
8. GetLastInputInfo is updated by our own SendInput (0 ms lag) - compare with our last injection tick.
9. An app-wide native event filter sees window hotkeys twice unless it returns True.
10. UIPI blocks silently (SendInput returns the full count); PostMessage at least fails with error 5.

## Open issues
* No real game, full-screen exclusive window or anti-cheat was tested; hold/delay defaults for games are estimates.
* Elevated-target blocking was shown low->medium IL, not medium->high (no UAC prompt allowed).
* MOD_NOREPEAT/hotkey behaviour with a real (not injected) keyboard was not tested.
* The "user moved, pause" check (GetLastInputInfo newer than our last SendInput) never fired: no real user input
  happened during the runs; only its premise (our SendInput updates GetLastInputInfo with 0 ms lag) was measured.

## Sources
[M1] https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput
[M2] https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setforegroundwindow
[M3] https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-registerhotkey
[M4] https://learn.microsoft.com/en-us/windows/win32/dataxchg/clipboard-formats (Cloud Clipboard and Clipboard History Formats)
