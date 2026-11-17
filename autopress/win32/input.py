# OWNED BY G3
"""Input injection with SendInput (win32_input.md sections 0-12; port wa_win32.py).

Safety invariants (SPEC section 2.7):
* InjectGuard.check() runs before EVERY keystroke, character and click.
* One atomic SendInput per character / combo (key down+up in the same call) unless a hold
  time is requested. EVERY key and mouse button we press is released in ``finally`` before an
  exception propagates - the ``sleep`` of a hold may raise StopRequested / FailsafeTriggered /
  UserActivity (a button left down after a failsafe would drag across the desktop; PX-10).
  The module tracks what it holds; release_all_modifiers() also releases those.
* Interrupted typing restores the clipboard snapshot (CLIPBOARD mode) and the target's IME
  state (VK mode) in ``finally`` as well (T28).
* SendInput returning fewer events than sent (UAC prompt, locked screen, secure desktop)
  raises InputBlocked (T33).
* Tick comparisons are wrap-safe: GetTickCount / GetLastInputInfo wrap after 49.7 days, so
  "a newer than b" is ``((a - b) & 0xFFFFFFFF) < 0x80000000``.
* Every wait goes through the ``sleep`` callable passed in (the runner passes
  RunControl.sleep, which is interruptible); default time.sleep. The only exceptions are the
  short bounded settles inside ``finally`` (>= 50 ms after Ctrl+V before the clipboard comes
  back, 150 ms before the target's IME is reopened), which must not be interrupted.
* Mouse coordinates are PHYSICAL pixels, sent as ABSOLUTE|VIRTUALDESK with the pixel-centre
  formula ``((x - vx) * 65536 + 32768) // vw``.
* dwExtraInfo of every injected event = EXTRA_TAG ("APRS").

Exceptions derived from InjectionAborted, ClipboardBusy and UnmappableChar carry the SPEC 7.1
text as ``str(exc)`` (constructed without a message they use that text too) plus attributes for
logs (``what``, the covering window of PointNotOnTarget, the SendInput counts of InputBlocked).
press_combo() also refuses the system shortcuts of models.combo_risk (ERROR) as a last line of
defence for shared profiles (SPEC 2.7.7): ValueError with the localized reason.

Private helpers live in ``_errors`` (messages, exception classes) and ``_events`` (INPUT
construction, SendInput, held keys, ticks); their public names are re-exported here.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as W
import logging
import os
import time
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from ..models import ClearMethod, IssueLevel, MouseButton, Point, TypingMode, combo_risk, in_failsafe_corner
from . import api, clipboard
from ._errors import (
    ClipboardBusy,
    FailsafeTriggered,
    ForegroundLost,
    InjectionAborted,
    InputBlocked,
    PointNotOnTarget,
    UnmappableChar,
    UserActivity,
    _msg_covered,
    _msg_covered_generic,
    _msg_covered_minibar,
    _msg_offscreen,
)
from ._events import (
    _BUTTONS,
    EXTRA_TAG,
    Sleep,
    _held_buttons,
    _held_keys,
    _kbd,
    _lock,
    _mouse,
    _note_injection,
    _press_held,
    _send,
    _target_layout,
    _to_absolute,
    _utf16_units,
    _vk_event,
    held_by_us,
    injected_presses,
    last_injection_tick,
    reset_user_input_baseline,
    user_active_since_last_injection,
)
from .keys import parse_combo

__all__ = [
    "EXTRA_TAG", "ClipboardBusy", "FailsafeTriggered", "ForegroundLost", "InjectGuard", "InjectionAborted",
    "InputBlocked", "PointNotOnTarget", "Sleep", "UnmappableChar", "UserActivity", "bring_to_foreground",
    "clear_field", "click", "failsafe_triggered", "held_by_us", "ime_set_open", "ime_state", "injected_presses",
    "last_injection_tick", "press_combo", "press_keys", "release_all_modifiers", "reset_user_input_baseline",
    "type_text", "user_active_since_last_injection",
]

log = logging.getLogger(__name__)

IME_SETTLE_S = 0.05  # after closing the target's IME, before the first key (interruptible)
IME_RESTORE_DELAY_S = 0.15  # before reopening it: let the target process the queued keys first
PASTE_MIN_DELAY_S = 0.05  # Ctrl+V -> clipboard restore never sooner (0 ms pasted the old content)
DOUBLE_CLICK_MIN_HOLD_MS = 20  # an atomic 4-event double click is ignored by Qt; 20 ms holds worked
MONITOR_CACHE_S = 2.0

_monitor_cache: list[Any] = [0.0, []]  # [monotonic time, monitor rects]
_INJECT_VK = {api.VK_SHIFT: api.VK_LSHIFT, api.VK_CONTROL: api.VK_LCONTROL, api.VK_MENU: api.VK_LMENU}
"""Generic modifiers are injected as the left-hand keys (the measured path, win32_input.md)."""
_GENERIC_SIDES = {api.VK_SHIFT: (api.VK_LSHIFT, api.VK_RSHIFT), api.VK_CONTROL: (api.VK_LCONTROL, api.VK_RCONTROL),
                  api.VK_MENU: (api.VK_LMENU, api.VK_RMENU)}
_MODIFIER_VKS = (api.VK_LSHIFT, api.VK_RSHIFT, api.VK_LCONTROL, api.VK_RCONTROL, api.VK_LMENU, api.VK_RMENU,
                 api.VK_LWIN, api.VK_RWIN)
_ALT_WIN = frozenset({api.VK_LMENU, api.VK_RMENU, api.VK_LWIN, api.VK_RWIN})
_caps_cache: dict[tuple[int, int], bool] = {}


# ================================================================================ failsafe


def _monitor_rects() -> list[tuple[int, int, int, int]]:
    now = time.monotonic()
    with _lock:
        stamp, rects = _monitor_cache
        if rects and now - stamp < MONITOR_CACHE_S:
            return list(rects)
    rects = [m.rect for m in api.enum_monitors()]
    with _lock:
        _monitor_cache[0], _monitor_cache[1] = now, rects
    return list(rects)


def failsafe_triggered(margin_px: int = 3) -> bool:
    """models.in_failsafe_corner(GetCursorPos(), [m.rect for m in win32.dpi.monitors()],
    margin_px): the cursor is within ``margin_px`` of an OUTER top-left corner of the desktop.
    On a PC whose second monitor is left of the primary, that is the left monitor's top-left,
    not (0, 0) (T04 / PX-12; monitors cached, refreshed every 2 s). False when the cursor
    position cannot be read (locked session)."""
    pos = api.cursor_pos()
    if pos is None:
        return False
    return in_failsafe_corner(pos[0], pos[1], _monitor_rects(), margin_px)


# ================================================================================ guard


class InjectGuard:
    """Checks that must pass before every injection. ``hwnd`` may be reassigned by the runner
    when the target window is found again (assigning it forgets an explicit ``pid``; the pid is
    then read from the new window)."""

    def __init__(self, hwnd: int, *, pid: int = 0, allow_same_process: bool = False,
                 check_user_input: bool = True, slack_ms: int = 200,
                 failsafe: bool = True, failsafe_margin_px: int = 3,
                 cancel: Callable[[], None] | None = None) -> None:
        self._hwnd = int(hwnd or 0)
        self._pid = int(pid or 0)
        self.allow_same_process = bool(allow_same_process)
        self.check_user_input = bool(check_user_input)
        self.slack_ms = int(slack_ms)
        self.failsafe = bool(failsafe)
        self.failsafe_margin_px = int(failsafe_margin_px)
        self.cancel = cancel

    @property
    def hwnd(self) -> int:
        return self._hwnd

    @hwnd.setter
    def hwnd(self, value: int) -> None:
        self._hwnd = int(value or 0)
        self._pid = 0

    @property
    def pid(self) -> int:
        return self._pid or api.window_pid(self._hwnd)

    @pid.setter
    def pid(self, value: int) -> None:
        self._pid = int(value or 0)

    def __repr__(self) -> str:
        return (f"InjectGuard(hwnd={self._hwnd:#x}, pid={self._pid}, same_process={self.allow_same_process}, "
                f"user_input={self.check_user_input}, failsafe={self.failsafe})")

    def _is_target(self, h: int) -> bool:
        if not h:
            return False
        if h == self._hwnd:
            return True
        if self.allow_same_process:
            pid = self.pid
            return bool(pid) and api.window_pid(h) == pid
        return False

    def check(self, what: str, point: Point | None = None) -> None:
        """In this order: ``cancel()`` (lets the runner's StopRequested propagate); failsafe
        corner -> FailsafeTriggered; user input since our last injection -> UserActivity;
        foreground window is not ``hwnd`` (or, with allow_same_process, not a window of
        ``pid``) -> ForegroundLost; for clicks, the root window at ``point`` is not the
        target (with allow_same_process: not a window of ``pid``) -> PointNotOnTarget naming the
        covering window. ``what`` is a short label used in the messages."""
        if self.cancel is not None:
            self.cancel()
        if self.failsafe and failsafe_triggered(self.failsafe_margin_px):
            raise FailsafeTriggered(what=what, cursor=api.cursor_pos())
        if self.check_user_input and user_active_since_last_injection(self.slack_ms):
            raise UserActivity(what=what)
        fg = api.hwnd_int(api.GetForegroundWindow())
        if not self._is_target(fg):
            log.debug("guard %s: foreground %#x is not the target %#x", what, fg, self._hwnd)
            raise ForegroundLost(what=what, foreground_hwnd=fg)
        if point is not None:
            x, y = int(point[0]), int(point[1])
            hit = api.hwnd_int(api.WindowFromPoint(W.POINT(x, y)))
            root = (api.hwnd_int(api.GetAncestor(hit, api.GA_ROOT)) if hit else 0) or hit
            if not self._is_target(root):
                raise _covered(what, (x, y), root)


def _covered(what: str, point: Point, root: int) -> PointNotOnTarget:
    """PointNotOnTarget naming the covering root window (SPEC 7.1)."""
    if not root:
        return PointNotOnTarget(_msg_offscreen(), what=what, point=point)
    own = api.window_pid(root) == os.getpid()
    minibar = own and bool(api.exstyle(root) & api.WS_EX_TOOLWINDOW)
    if own:
        title = "AutoPress"
        message = _msg_covered_minibar() if minibar else _msg_covered(title)
    else:
        title = api.window_text(root)
        if not title:
            path, _err = api.exe_path(api.window_pid(root))
            title = path.replace("\\", "/").rsplit("/", 1)[-1] if path else api.class_name(root)
        message = _msg_covered(title) if title else _msg_covered_generic()
    log.debug("guard %s: point %s covered by %#x %r (own=%s)", what, point, root, title, own)
    return PointNotOnTarget(message, what=what, point=point, covering_hwnd=root, covering_title=title,
                            covering_is_own=own, covering_is_minibar=minibar)


# ================================================================================ foreground


def _foreground() -> int:
    return api.hwnd_int(api.GetForegroundWindow())


def _wait_foreground(hwnd: int, timeout_s: float, sleep: Sleep) -> bool:
    deadline = time.monotonic() + max(0.0, timeout_s)
    while True:
        if _foreground() == hwnd:
            return True
        if time.monotonic() >= deadline:
            return False
        sleep(0.01)


def _fg_plain(hwnd: int) -> None:
    api.SetForegroundWindow(hwnd)


def _fg_input(hwnd: int) -> None:
    """A zero-distance relative mouse move (no key, no click, no cursor movement) makes us the
    last input provider, which the foreground lock accepts; then SetForegroundWindow."""
    _send([_mouse(0, 0, api.MOUSEEVENTF_MOVE)], "focus")
    api.SetForegroundWindow(hwnd)


def _fg_attach(hwnd: int) -> None:
    """AttachThreadInput(our thread -> foreground thread), BringWindowToTop, SetForegroundWindow."""
    fg = _foreground()
    me = int(api.GetCurrentThreadId())
    ftid = api.window_tid(fg) if fg else 0
    attached = bool(ftid and ftid != me and api.AttachThreadInput(me, ftid, True))
    try:
        api.BringWindowToTop(hwnd)
        api.SetForegroundWindow(hwnd)
    finally:
        if attached:
            api.AttachThreadInput(me, ftid, False)


def _settle_client(hwnd: int, max_s: float, sleep: Sleep) -> None:
    """After restoring a minimized window: wait until two client_rect reads 100 ms apart agree
    (exclusive-fullscreen games switch the display mode), at most ``max_s`` (SPEC 2.5)."""
    if max_s <= 0:
        return
    from .windows import client_rect

    deadline = time.monotonic() + max_s
    previous = client_rect(hwnd)
    while time.monotonic() < deadline:
        sleep(0.1)
        current = client_rect(hwnd)
        if current == previous:
            return
        previous = current


def bring_to_foreground(hwnd: int, attempts: int = 3, verify_s: float = 0.25, sleep: Sleep = time.sleep,
                        restore_settle_s: float = 5.0) -> tuple[bool, str]:
    """Activate ``hwnd``: SW_RESTORE if minimized, then plain SetForegroundWindow, then a
    zero-distance mouse move + SetForegroundWindow, then AttachThreadInput; each verified with
    GetForegroundWindow for ``verify_s``. Returns (ok, method or failure reason). A window that
    was minimized is given up to ``restore_settle_s`` for its client rect to stop changing.
    Raises InputBlocked when even the zero-distance move is refused (locked screen, UAC)."""
    hwnd = int(hwnd or 0)
    if not hwnd or not api.IsWindow(hwnd):
        return False, "window not found"
    if _foreground() == hwnd and not api.IsIconic(hwnd):
        return True, "already"
    restored = False
    if api.IsIconic(hwnd):
        api.ShowWindow(hwnd, api.SW_RESTORE)
        restored = True
        if _wait_foreground(hwnd, verify_s, sleep):
            _settle_client(hwnd, restore_settle_s, sleep)
            return True, "restore"
    for _round in range(max(1, int(attempts))):
        for name, method in (("plain", _fg_plain), ("input", _fg_input), ("attach", _fg_attach)):
            method(hwnd)
            if _wait_foreground(hwnd, verify_s, sleep):
                if restored:
                    _settle_client(hwnd, restore_settle_s, sleep)
                return True, name
    return False, "SetForegroundWindow was refused"


# ================================================================================ IME


def _ime_send(hwnd: int, command: int, value: int = 0) -> int | None:
    ime = api.hwnd_int(api.ImmGetDefaultIMEWnd(int(hwnd or 0))) if hwnd else 0
    if not ime:
        return None
    res = api.ULONG_PTR(0)
    ok = api.SendMessageTimeoutW(ime, api.WM_IME_CONTROL, command, value, api.SMTO_ABORTIFHUNG, 500,
                                 ctypes.byref(res))
    return int(res.value) if ok else None


def ime_state(hwnd: int) -> dict[str, int] | None:
    """{"open": 0|1, "conversion": mode} of the window's default IME (WM_IME_CONTROL), or None."""
    opened = _ime_send(hwnd, api.IMC_GETOPENSTATUS)
    if opened is None:
        return None
    conversion = _ime_send(hwnd, api.IMC_GETCONVERSIONMODE)
    return {"open": 1 if opened else 0, "conversion": int(conversion or 0)}


def ime_set_open(hwnd: int, is_open: bool) -> bool:
    """IMC_SETOPENSTATUS through ImmGetDefaultIMEWnd (works cross-process, measured)."""
    return _ime_send(hwnd, api.IMC_SETOPENSTATUS, 1 if is_open else 0) is not None


def _ime_restore(hwnd: int, saved: dict[str, int]) -> None:
    """Reopen the IME; put the conversion mode back if reopening did not (documented API, not
    measured: the research saw open/conversion 1/1 -> 0/0 -> 1/1)."""
    if not ime_set_open(hwnd, True):
        log.warning("could not reopen the IME of %#x", hwnd)
        return
    now = ime_state(hwnd)
    if now is not None and now["conversion"] != saved["conversion"]:
        _ime_send(hwnd, api.IMC_SETCONVERSIONMODE, saved["conversion"])


# ================================================================================ typing


def _caps_lock_on() -> bool:
    return bool(api.GetKeyState(api.VK_CAPITAL) & 1)


def _caps_affects(vk: int, layout: Any) -> bool:
    """True if CapsLock changes the character of this key (letters on US / zh-TW layouts)."""
    key = (vk, int(layout or 0))
    if key not in _caps_cache:
        state = (ctypes.c_ubyte * 256)()
        buf = ctypes.create_unicode_buffer(8)
        sc = int(api.MapVirtualKeyExW(vk, api.MAPVK_VK_TO_VSC, layout))
        n1 = api.ToUnicodeEx(vk, sc, ctypes.byref(state), buf, 8, 0x4, layout)  # 0x4: keep kernel state
        plain = buf.value[:max(n1, 0)]
        state[api.VK_CAPITAL] = 0x01
        n2 = api.ToUnicodeEx(vk, sc, ctypes.byref(state), buf, 8, 0x4, layout)
        _caps_cache[key] = plain != buf.value[:max(n2, 0)]
    return _caps_cache[key]


def _vk_plan(ch: str, layout: Any, caps: bool) -> list[int]:
    """VKs to press for one character in VK mode (Shift first when needed; CapsLock inverts Shift
    for letters). UnmappableChar for characters without a key (or needing Ctrl / AltGr)."""
    if len(_utf16_units(ch)) != 1:
        raise UnmappableChar(ch)
    r = int(api.VkKeyScanExW(ch, layout))
    if r == -1 or (r & 0xFF) == 0xFF:
        raise UnmappableChar(ch)
    vk, shift_state = r & 0xFF, (r >> 8) & 0xFF
    if shift_state & 0x06:  # needs Ctrl / Alt (AltGr): never injected
        raise UnmappableChar(ch)
    need_shift = bool(shift_state & 0x01)
    if caps and _caps_affects(vk, layout):
        need_shift = not need_shift
    return ([api.VK_LSHIFT] if need_shift else []) + [vk]


def _type_unicode(text: str, guard: InjectGuard, key_delay_ms: int, hold_ms: int, sleep: Sleep) -> None:
    chars = list(text)
    for i, ch in enumerate(chars):
        units = _utf16_units(ch)
        guard.check(f"char[{i}]")
        if hold_ms > 0:
            downs = [_kbd(0, u, api.KEYEVENTF_UNICODE) for u in units]
            ups = [_kbd(0, u, api.KEYEVENTF_UNICODE | api.KEYEVENTF_KEYUP) for u in units]
            _press_held(downs, ups, (), hold_ms, sleep, "char")
        else:  # down+up per UTF-16 unit, the whole character in ONE SendInput call
            _send([e for u in units for e in (_kbd(0, u, api.KEYEVENTF_UNICODE),
                                              _kbd(0, u, api.KEYEVENTF_UNICODE | api.KEYEVENTF_KEYUP))], "char")
        if key_delay_ms > 0 and i < len(chars) - 1:
            sleep(key_delay_ms / 1000.0)


def _type_vk(text: str, guard: InjectGuard, key_delay_ms: int, hold_ms: int, close_ime: bool,
             sleep: Sleep) -> None:
    layout = _target_layout(guard.hwnd)
    caps = _caps_lock_on()
    plans = [_vk_plan(ch, layout, caps) for ch in text]  # UnmappableChar before anything is typed
    hwnd = guard.hwnd
    saved: dict[str, int] | None = None
    try:
        if close_ime:
            guard.check("ime")  # never touch the IME of a window that is not the foreground target
            state = ime_state(hwnd)
            if state is not None and state["open"] and ime_set_open(hwnd, False):
                saved = state
                sleep(IME_SETTLE_S)
        for i, vks in enumerate(plans):
            guard.check(f"char[{i}]")
            downs = [_vk_event(v, False, layout) for v in vks]
            ups = [_vk_event(v, True, layout) for v in reversed(vks)]
            if hold_ms > 0:
                _press_held(downs, ups, vks, hold_ms, sleep, "char")
            else:
                _send(downs + ups, "char")
            if key_delay_ms > 0 and i < len(plans) - 1:
                sleep(key_delay_ms / 1000.0)
    finally:
        if saved is not None:
            time.sleep(IME_RESTORE_DELAY_S)  # bounded and NOT interruptible: the IME must come back
            _ime_restore(hwnd, saved)


def _type_clipboard(text: str, guard: InjectGuard, hold_ms: int, restore_ms: int, sleep: Sleep) -> None:
    guard.check("paste")
    snap = clipboard.snapshot()
    pasted_at: float | None = None
    try:
        clipboard.set_text(text, private=True)
        pasted_at = time.monotonic()
        press_keys((api.VK_CONTROL, ord("V")), guard, hold_ms=hold_ms, sleep=sleep)
        sleep(max(PASTE_MIN_DELAY_S * 1000, restore_ms) / 1000.0)
    finally:
        if pasted_at is not None:
            remaining = PASTE_MIN_DELAY_S - (time.monotonic() - pasted_at)
            if remaining > 0:
                time.sleep(remaining)  # restoring right after Ctrl+V pastes the OLD clipboard
        try:
            clipboard.restore(snap)
        except OSError as exc:
            log.warning("clipboard not restored: %s", exc)


def type_text(text: str, guard: InjectGuard, mode: TypingMode = TypingMode.UNICODE, *,
              key_delay_ms: int = 15, hold_ms: int = 0, close_ime: bool = True,
              restore_clipboard_ms: int = 300, sleep: Sleep = time.sleep) -> None:
    """Type ``text`` into the focused control of the guarded window.
    UNICODE: KEYEVENTF_UNICODE per UTF-16 unit, one atomic SendInput per character.
    CLIPBOARD: snapshot the clipboard (all formats), set text (privacy formats), Ctrl+V, wait
    ``restore_clipboard_ms`` (>= 50; 0 ms pastes the old content), restore the snapshot.
    VK: VkKeyScanExW + scan codes with Shift and CapsLock compensation; when ``close_ime`` the
    target's IME is closed (ime_set_open False) for the duration and restored afterwards;
    ``hold_ms`` > 0 splits down/up (needed >= 20 ms for polling games).
    Clipboard snapshot, IME state and held keys are restored / released in ``finally``, also
    when a guard check or the ``sleep`` raises.
    Raises InjectionAborted subclasses (incl. InputBlocked), ClipboardBusy, UnmappableChar."""
    if not text:
        return
    mode = TypingMode(mode)
    key_delay_ms, hold_ms = max(0, int(key_delay_ms)), max(0, int(hold_ms))
    if mode is TypingMode.CLIPBOARD:
        _type_clipboard(text, guard, hold_ms, int(restore_clipboard_ms), sleep)
    elif mode is TypingMode.VK:
        _type_vk(text, guard, key_delay_ms, hold_ms, close_ime, sleep)
    else:
        _type_unicode(text, guard, key_delay_ms, hold_ms, sleep)


# ================================================================================ keys and mouse


def press_keys(vks: Sequence[int], guard: InjectGuard, *, hold_ms: int = 0, sleep: Sleep = time.sleep) -> None:
    """Press a combination (modifiers first) and release in reverse order; atomic when hold_ms == 0.
    Generic Shift / Ctrl / Alt are injected as the left-hand keys."""
    keys = [_INJECT_VK.get(int(v), int(v)) for v in vks]
    if not keys:
        return
    layout = _target_layout(guard.hwnd)
    guard.check("keys")
    downs = [_vk_event(v, False, layout) for v in keys]
    ups = [_vk_event(v, True, layout) for v in reversed(keys)]
    if hold_ms > 0:
        _press_held(downs, ups, keys, int(hold_ms), sleep, "keys")
    else:
        _send(downs + ups, "keys")


def press_combo(combo: str, guard: InjectGuard, *, repeat: int = 1, interval_ms: int = 50,
                hold_ms: int = 0, sleep: Sleep = time.sleep) -> None:
    """press_keys(keys.parse_combo(combo)) ``repeat`` times, ``interval_ms`` apart. System
    shortcuts (models.combo_risk ERROR: Win combos, Alt+Tab, Alt+F4, Ctrl+Alt+Delete ...) raise
    ValueError (localized reason) before anything is sent; so does unparsable text."""
    level, reason = combo_risk(combo)
    if level is IssueLevel.ERROR:
        raise ValueError(reason)
    vks = parse_combo(combo)
    n = max(1, int(repeat))
    for i in range(n):
        press_keys(vks, guard, hold_ms=hold_ms, sleep=sleep)
        if i < n - 1 and interval_ms > 0:
            sleep(interval_ms / 1000.0)


def clear_field(guard: InjectGuard, method: ClearMethod = ClearMethod.CTRL_A, *, backspaces: int = 40,
                sleep: Sleep = time.sleep) -> None:
    """CTRL_A: Ctrl+A, Backspace. END_SHIFT_HOME: End, Shift+Home, Delete. BACKSPACE: End, then
    ``backspaces`` x Backspace."""
    method = ClearMethod(method)
    if method is ClearMethod.END_SHIFT_HOME:
        press_keys((api.VK_END,), guard, sleep=sleep)
        press_keys((api.VK_SHIFT, api.VK_HOME), guard, sleep=sleep)
        press_keys((api.VK_DELETE,), guard, sleep=sleep)
    elif method is ClearMethod.BACKSPACE:
        press_keys((api.VK_END,), guard, sleep=sleep)
        for _ in range(max(0, int(backspaces))):
            press_keys((api.VK_BACK,), guard, sleep=sleep)
    else:
        press_keys((api.VK_CONTROL, ord("A")), guard, sleep=sleep)
        press_keys((api.VK_BACK,), guard, sleep=sleep)


def click(x: int, y: int, guard: InjectGuard, *, button: MouseButton = MouseButton.LEFT, double: bool = False,
          settle_ms: int = 30, hold_ms: int = 30, restore_cursor: bool = False, sleep: Sleep = time.sleep) -> None:
    """Move to the physical point, wait ``settle_ms``, press, hold ``hold_ms``, release.
    ``double`` = two such clicks (an atomic 4-event double click is ignored by Qt), each held at
    least 20 ms. Every press and release repeats the absolute move, so the button acts on the
    point even if something moved the cursor during the settle or the hold."""
    button = MouseButton(button)
    down_flag, up_flag, _vk = _BUTTONS[button]
    old = api.cursor_pos() if restore_cursor else None
    nx, ny = _to_absolute(x, y)
    move = api.MOUSEEVENTF_MOVE | api.MOUSEEVENTF_ABSOLUTE | api.MOUSEEVENTF_VIRTUALDESK
    hold = max(int(hold_ms), DOUBLE_CLICK_MIN_HOLD_MS) if double else int(hold_ms)
    try:
        if settle_ms > 0:  # (without a settle the move goes out with the press, after its check)
            guard.check("click", (x, y))
            _send([_mouse(nx, ny, move)], "move")
            sleep(settle_ms / 1000.0)
        for _i in range(2 if double else 1):
            guard.check("click", (x, y))
            if hold > 0:
                _press_held([_mouse(nx, ny, move), _mouse(0, 0, down_flag)], [_mouse(nx, ny, move),
                            _mouse(0, 0, up_flag)], (), hold, sleep, "click", button)
            else:
                _send([_mouse(nx, ny, move), _mouse(0, 0, down_flag), _mouse(0, 0, up_flag)], "click")
    finally:
        if old is not None:
            api.SetCursorPos(old[0], old[1])
            _note_injection()  # our own cursor move must not count as the user's input


def release_all_modifiers(pressed_by_us: Iterable[int] = ()) -> list[int]:
    """Key-up for every Shift/Ctrl that is down, for Alt/Win only if in ``pressed_by_us`` (a
    lone Alt/Win up opens menus), and for every key and mouse button this module pressed and has
    not released yet (tracked internally). Returns the VKs released (mouse buttons as
    VK_LBUTTON / VK_RBUTTON / VK_MBUTTON). Call in ``finally``, on abort and at app exit.
    Never raises: when Windows refuses the key-ups (locked screen) it logs and returns []."""
    ours: set[int] = set()
    for v in pressed_by_us:
        ours.update(_GENERIC_SIDES.get(int(v), (int(v),)))
    with _lock:
        keys = list(_held_keys)
        buttons = list(_held_buttons)
    ours.update(keys)
    events: list[api.INPUT] = []
    released: list[int] = []
    for b in buttons:
        events.append(_mouse(0, 0, _BUTTONS[b][1]))
        released.append(_BUTTONS[b][2])
    for vk in reversed(keys):
        events.append(_vk_event(vk, True))
        released.append(vk)
    for vk in _MODIFIER_VKS:
        if vk in released or not (api.GetAsyncKeyState(vk) & 0x8000):
            continue
        if vk in _ALT_WIN and vk not in ours:
            continue
        events.append(_vk_event(vk, True))
        released.append(vk)
    if not events:
        return []
    try:
        _send(events, "release_all")
    except InputBlocked:
        log.warning("release_all_modifiers: Windows refused the key-ups (%s)", released)
        return []
    with _lock:
        for vk in keys:
            _held_keys.pop(vk, None)
        for b in buttons:
            _held_buttons.pop(b, None)
    return released
