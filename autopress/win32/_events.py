# OWNED BY G3
"""Private helpers of win32.input: INPUT construction, the SendInput wrapper, what this process
holds down, and the injection / user-input ticks (win32_input.md 10). Never imported outside
autopress.win32; the public names are re-exported by win32.input.

Every injected event carries dwExtraInfo = EXTRA_TAG. ``_send`` raises InputBlocked when SendInput
inserts fewer events than requested; keys / buttons a partially inserted batch left down are
recorded, so release_all_modifiers() can let them go. ``_send`` also notes when it last inserted an
ordinary key or a mouse-button event (not a KEYEVENTF_UNICODE character, not a bare move): UNICODE
typing waits after those for targets with an IME (input.TEXT_AFTER_KEYS_SETTLE_S). State is shared
by all threads (lock).
"""

from __future__ import annotations

import ctypes
import logging
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from ..models import MouseButton
from . import api
from ._errors import InputBlocked
from .keys import EXTENDED_VKS

log = logging.getLogger(__name__)

EXTRA_TAG = 0x41505253

Sleep = Callable[[float], None]

_lock = threading.RLock()
_last_tick: int | None = None  # GetTickCount() of our last SendInput
_baseline: int | None = None  # reset_user_input_baseline()
_held_keys: dict[int, None] = {}  # VKs we pressed and have not released (insertion order)
_held_buttons: dict[MouseButton, None] = {}
_presses = 0  # key-down / button-down events inserted so far (moves and releases not counted)
_last_key_or_button: float | None = None  # time.monotonic() of the last inserted ordinary key / mouse-button event
_BUTTONS: dict[MouseButton, tuple[int, int, int]] = {  # down flag, up flag, VK
    MouseButton.LEFT: (api.MOUSEEVENTF_LEFTDOWN, api.MOUSEEVENTF_LEFTUP, api.VK_LBUTTON),
    MouseButton.RIGHT: (api.MOUSEEVENTF_RIGHTDOWN, api.MOUSEEVENTF_RIGHTUP, api.VK_RBUTTON),
    MouseButton.MIDDLE: (api.MOUSEEVENTF_MIDDLEDOWN, api.MOUSEEVENTF_MIDDLEUP, api.VK_MBUTTON),
}


# ================================================================================ ticks


def _note_injection() -> None:
    global _last_tick
    with _lock:
        _last_tick = api.tick_count()


def last_injection_tick() -> int:
    """GetTickCount() value of our most recent SendInput (0 if none)."""
    with _lock:
        return _last_tick or 0


def reset_user_input_baseline() -> None:
    """Treat input up to now as ours (call at run start and after every resume, so the
    hotkey/click that resumed the run does not pause it again)."""
    global _baseline
    with _lock:
        _baseline = api.tick_count()


def user_active_since_last_injection(slack_ms: int = 200) -> bool:
    """GetLastInputInfo().dwTime newer than max(last injection, baseline) + slack_ms (wrap-safe
    32-bit comparison). Our own SendInput updates GetLastInputInfo with 0 ms lag (measured),
    hence the comparison. False while neither an injection nor a baseline exists yet, and when
    GetLastInputInfo fails."""
    last_input = api.last_input_tick()
    if last_input is None:
        return False
    with _lock:
        refs = [t for t in (_last_tick, _baseline) if t is not None]
    if not refs:
        return False
    ref = refs[0]
    for t in refs[1:]:
        if api.tick_newer(t, ref):
            ref = t
    return api.tick_newer(last_input, (ref + max(0, int(slack_ms))) & 0xFFFFFFFF)


def injected_presses() -> int:
    """Number of key-down and mouse-button-down events this process has injected so far
    (mouse moves and releases are not counted). The difference across a step tells exactly
    whether the step pressed anything - unlike counting passed guard checks, a few of which
    (the clipboard / IME pre-checks) are not followed by an injection."""
    with _lock:
        return _presses


def _count_presses(events: Sequence[api.INPUT]) -> int:
    n = 0
    for ev in events:
        if ev.type == api.INPUT_KEYBOARD:
            n += not ev.ki.dwFlags & api.KEYEVENTF_KEYUP
        elif ev.type == api.INPUT_MOUSE:
            n += any(ev.mi.dwFlags & down for down, _up, _vk in _BUTTONS.values())
    return n


def held_by_us() -> list[int]:
    """VKs (mouse buttons as VK_LBUTTON / VK_RBUTTON / VK_MBUTTON) this module pressed and has
    not released yet - normally empty; diagnostics and tests."""
    with _lock:
        return [_BUTTONS[b][2] for b in _held_buttons] + list(_held_keys)


def _is_key_or_button(ev: api.INPUT) -> bool:
    """An ordinary key event (not KEYEVENTF_UNICODE) or a mouse event with a button flag."""
    if ev.type == api.INPUT_KEYBOARD:
        return not ev.ki.dwFlags & api.KEYEVENTF_UNICODE
    if ev.type == api.INPUT_MOUSE:
        return any(ev.mi.dwFlags & (down | up) for down, up, _vk in _BUTTONS.values())
    return False


def seconds_since_key_or_button() -> float | None:
    """Seconds since this process last inserted an ordinary key or mouse-button event (None if never)."""
    with _lock:
        last = _last_key_or_button
    return None if last is None else max(0.0, time.monotonic() - last)


# ================================================================================ events


def _kbd(vk: int, scan: int, flags: int) -> api.INPUT:
    i = api.INPUT(type=api.INPUT_KEYBOARD)
    i.ki = api.KEYBDINPUT(vk, scan, flags, 0, EXTRA_TAG)
    return i


def _mouse(dx: int, dy: int, flags: int) -> api.INPUT:
    i = api.INPUT(type=api.INPUT_MOUSE)
    i.mi = api.MOUSEINPUT(dx, dy, 0, flags, 0, EXTRA_TAG)
    return i


def _vk_event(vk: int, up: bool, layout: Any = None) -> api.INPUT:
    """One KEYBDINPUT with the matching scan code and the E0 flag where needed."""
    sc = int(api.MapVirtualKeyExW(vk, api.MAPVK_VK_TO_VSC_EX, layout))
    ext = vk in EXTENDED_VKS or (sc & 0xFF00) in (0xE000, 0xE100)
    flags = (api.KEYEVENTF_EXTENDEDKEY if ext else 0) | (api.KEYEVENTF_KEYUP if up else 0)
    return _kbd(vk, sc & 0xFF, flags)


def _utf16_units(ch: str) -> list[int]:
    b = ch.encode("utf-16-le", "surrogatepass")
    return [b[i] | (b[i + 1] << 8) for i in range(0, len(b), 2)]


def _to_absolute(x: int, y: int) -> tuple[int, int]:
    """Physical pixel -> 0..65535 over the VIRTUAL desktop (negative origins work), pixel centre."""
    vx, vy, vw, vh = api.virtual_screen()
    if vw <= 0 or vh <= 0:
        vx, vy = 0, 0
        vw = max(1, int(api.GetSystemMetrics(api.SM_CXSCREEN)))
        vh = max(1, int(api.GetSystemMetrics(api.SM_CYSCREEN)))
    nx = ((int(x) - vx) * 65536 + 32768) // vw
    ny = ((int(y) - vy) * 65536 + 32768) // vh
    return max(0, min(65535, nx)), max(0, min(65535, ny))


def _target_layout(hwnd: int) -> Any:
    """HKL of the thread owning ``hwnd`` - the keyboard layout the target will use."""
    tid = api.window_tid(int(hwnd or 0))
    return api.GetKeyboardLayout(tid) if tid else api.GetKeyboardLayout(0)


# ================================================================================ sending


def _track_leftovers(prefix: Sequence[api.INPUT]) -> None:
    """After a short SendInput count: keys / buttons pressed by the inserted prefix and not released
    by it are now held by us (release_all_modifiers() will let them go)."""
    keys: dict[int, None] = {}
    buttons: dict[MouseButton, None] = {}
    for ev in prefix:
        if ev.type == api.INPUT_KEYBOARD:
            if ev.ki.dwFlags & api.KEYEVENTF_UNICODE:
                continue
            if ev.ki.dwFlags & api.KEYEVENTF_KEYUP:
                keys.pop(int(ev.ki.wVk), None)
            else:
                keys[int(ev.ki.wVk)] = None
        elif ev.type == api.INPUT_MOUSE:
            for b, (down, up, _vk) in _BUTTONS.items():
                if ev.mi.dwFlags & down:
                    buttons[b] = None
                if ev.mi.dwFlags & up:
                    buttons.pop(b, None)
    with _lock:
        _held_keys.update(keys)
        _held_buttons.update(buttons)


def _send(events: Sequence[api.INPUT], what: str = "") -> None:
    """One SendInput call. Fewer inserted events than requested -> InputBlocked."""
    n = len(events)
    if n == 0:
        return
    global _presses, _last_key_or_button
    arr = (api.INPUT * n)(*events)
    sent = int(api.SendInput(n, arr, ctypes.sizeof(api.INPUT)))
    err = ctypes.get_last_error() if sent != n else 0
    _note_injection()
    inserted = list(events)[:max(0, sent)]
    pressed = _count_presses(inserted)
    if pressed:
        with _lock:
            _presses += pressed
    if any(_is_key_or_button(ev) for ev in inserted):
        with _lock:
            _last_key_or_button = time.monotonic()
    if sent != n:
        _track_leftovers(inserted)
        log.warning("SendInput inserted %d of %d events (%s, error %s)", sent, n, what, err)
        raise InputBlocked(what=what, sent=sent, requested=n, error=err)


def _release(ups: Sequence[api.INPUT], keys: Iterable[int] = (), button: MouseButton | None = None, *,
             raise_errors: bool) -> None:
    """Send prepared key-up / button-up events (in ``finally``). On success the keys / button are no
    longer held; a failure is raised only when no other exception is propagating."""
    keys = list(keys)
    try:
        _send(ups, "release")
    except InputBlocked:
        if raise_errors:
            raise
        log.warning("could not release %s / %s while unwinding", keys, button)
        return
    with _lock:
        for vk in keys:
            _held_keys.pop(vk, None)
        if button is not None:
            _held_buttons.pop(button, None)


def _press_held(downs: Sequence[api.INPUT], ups: Sequence[api.INPUT], keys: Sequence[int], hold_ms: int,
                sleep: Sleep, what: str, button: MouseButton | None = None) -> None:
    """Down events, hold (``sleep`` may raise), up events in ``finally``."""
    with _lock:
        for vk in keys:
            _held_keys[vk] = None
        if button is not None:
            _held_buttons[button] = None
    ok = False
    try:
        _send(downs, what)
        sleep(hold_ms / 1000.0)
        ok = True
    finally:
        _release(ups, keys, button, raise_errors=ok)
