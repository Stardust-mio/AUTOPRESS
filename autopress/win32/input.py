# OWNED BY G3 - replace this stub
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
  RunControl.sleep, which is interruptible); default time.sleep.
* Mouse coordinates are PHYSICAL pixels, sent as ABSOLUTE|VIRTUALDESK with the pixel-centre
  formula ``((x - vx) * 65536 + 32768) // vw``.
* dwExtraInfo of every injected event = EXTRA_TAG ("APRS").
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Sequence

from ..models import ClearMethod, MouseButton, Point, TypingMode

__stub__ = True

EXTRA_TAG = 0x41505253

Sleep = Callable[[float], None]


class InjectionAborted(RuntimeError):
    """Base class: an injection was refused for safety. ``str(exc)`` is localized."""


class ForegroundLost(InjectionAborted):
    """The target is not the foreground window."""


class PointNotOnTarget(InjectionAborted):
    """The click point's root window (WindowFromPoint + GA_ROOT) is not the target. The message
    names the covering window: AutoPress's own mini bar -> 「AutoPress 的迷你控制列擋住了點擊
    位置…」, another window -> its title (SPEC 7.1)."""


class UserActivity(InjectionAborted):
    """Physical input happened after our last injection (GetLastInputInfo)."""


class FailsafeTriggered(InjectionAborted):
    """The mouse cursor is in a failsafe corner (models.failsafe_corners of the monitors)."""


class InputBlocked(InjectionAborted):
    """SendInput inserted fewer events than requested: Windows refused the input (UAC prompt,
    locked screen, secure desktop, input desktop switched). Localized message (SPEC 7.1)."""


class ClipboardBusy(OSError):
    """OpenClipboard kept failing (another program holds the clipboard)."""


class UnmappableChar(ValueError):
    """VK mode: a character has no key on the target's keyboard layout."""


class InjectGuard:
    """Checks that must pass before every injection. ``hwnd`` may be reassigned by the runner
    when the target window is found again."""

    def __init__(self, hwnd: int, *, pid: int = 0, allow_same_process: bool = False,
                 check_user_input: bool = True, slack_ms: int = 200,
                 failsafe: bool = True, failsafe_margin_px: int = 3,
                 cancel: Callable[[], None] | None = None) -> None:
        raise NotImplementedError

    def check(self, what: str, point: Point | None = None) -> None:
        """In this order: ``cancel()`` (lets the runner's StopRequested propagate); failsafe
        corner -> FailsafeTriggered; user input since our last injection -> UserActivity;
        foreground window is not ``hwnd`` (or, with allow_same_process, not a window of
        ``pid``) -> ForegroundLost; for clicks, the root window at ``point`` is not the
        target (with allow_same_process: not a window of ``pid``) -> PointNotOnTarget naming the
        covering window. ``what`` is a short label used in the messages."""
        raise NotImplementedError


def bring_to_foreground(hwnd: int, attempts: int = 3, verify_s: float = 0.25, sleep: Sleep = time.sleep) -> tuple[bool, str]:
    """Activate ``hwnd``: SW_RESTORE if minimized, then plain SetForegroundWindow, then a
    zero-distance mouse move + SetForegroundWindow, then AttachThreadInput; each verified with
    GetForegroundWindow for ``verify_s``. Returns (ok, method or failure reason)."""
    raise NotImplementedError


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
    raise NotImplementedError


def press_keys(vks: Sequence[int], guard: InjectGuard, *, hold_ms: int = 0, sleep: Sleep = time.sleep) -> None:
    """Press a combination (modifiers first) and release in reverse order; atomic when hold_ms == 0."""
    raise NotImplementedError


def press_combo(combo: str, guard: InjectGuard, *, repeat: int = 1, interval_ms: int = 50,
                hold_ms: int = 0, sleep: Sleep = time.sleep) -> None:
    """press_keys(keys.parse_combo(combo)) ``repeat`` times, ``interval_ms`` apart."""
    raise NotImplementedError


def clear_field(guard: InjectGuard, method: ClearMethod = ClearMethod.CTRL_A, *, backspaces: int = 40,
                sleep: Sleep = time.sleep) -> None:
    """CTRL_A: Ctrl+A, Backspace. END_SHIFT_HOME: End, Shift+Home, Delete. BACKSPACE: End, then
    ``backspaces`` x Backspace."""
    raise NotImplementedError


def click(x: int, y: int, guard: InjectGuard, *, button: MouseButton = MouseButton.LEFT, double: bool = False,
          settle_ms: int = 30, hold_ms: int = 30, restore_cursor: bool = False, sleep: Sleep = time.sleep) -> None:
    """Move to the physical point, wait ``settle_ms``, press, hold ``hold_ms``, release.
    ``double`` = two such clicks (an atomic 4-event double click is ignored by Qt)."""
    raise NotImplementedError


def release_all_modifiers(pressed_by_us: Iterable[int] = ()) -> list[int]:
    """Key-up for every Shift/Ctrl that is down, for Alt/Win only if in ``pressed_by_us`` (a
    lone Alt/Win up opens menus), and for every key and mouse button this module pressed and has
    not released yet (tracked internally). Returns the VKs released (mouse buttons as
    VK_LBUTTON / VK_RBUTTON / VK_MBUTTON). Call in ``finally``, on abort and at app exit."""
    raise NotImplementedError


def last_injection_tick() -> int:
    """GetTickCount() value of our most recent SendInput (0 if none)."""
    raise NotImplementedError


def reset_user_input_baseline() -> None:
    """Treat input up to now as ours (call at run start and after every resume, so the
    hotkey/click that resumed the run does not pause it again)."""
    raise NotImplementedError


def user_active_since_last_injection(slack_ms: int = 200) -> bool:
    """GetLastInputInfo().dwTime newer than max(last injection, baseline) + slack_ms (wrap-safe
    32-bit comparison). Our own SendInput updates GetLastInputInfo with 0 ms lag (measured),
    hence the comparison."""
    raise NotImplementedError


def failsafe_triggered(margin_px: int = 3) -> bool:
    """models.in_failsafe_corner(GetCursorPos(), [m.rect for m in win32.dpi.monitors()],
    margin_px): the cursor is within ``margin_px`` of an OUTER top-left corner of the desktop.
    On a PC whose second monitor is left of the primary, that is the left monitor's top-left,
    not (0, 0) (T04 / PX-12; monitors cached, refreshed on WM_DISPLAYCHANGE or every 2 s)."""
    raise NotImplementedError


def ime_state(hwnd: int) -> dict[str, int] | None:
    """{"open": 0|1, "conversion": mode} of the window's default IME (WM_IME_CONTROL), or None."""
    raise NotImplementedError


def ime_set_open(hwnd: int, is_open: bool) -> bool:
    """IMC_SETOPENSTATUS through ImmGetDefaultIMEWnd (works cross-process, measured)."""
    raise NotImplementedError
