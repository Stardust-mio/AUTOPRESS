# OWNED BY G3
"""win32.input with SendInput MOCKED (no input reaches Windows): InputBlocked on short counts,
keys / buttons released when a hold's sleep raises, clipboard and IME restored in finally,
guard order and messages, failsafe corners, wrap-safe ticks, event encoding (SPEC 2.7, 8.2); also
the desktop-state restore that tests/conftest.py puts around every realinput test."""

from __future__ import annotations

import time
from typing import Any

import pytest

from autopress import i18n
from autopress.models import ClearMethod, MouseButton, TypingMode
from autopress.win32 import _events as ev
from autopress.win32 import api
from autopress.win32 import input as inp
from tests.win32_helpers import RecordingGuard, SendRecorder, decode

VK_A, VK_B, VK_V = 0x41, 0x42, 0x56


class Boom(Exception):
    """Stands in for StopRequested / UserActivity raised by RunControl.sleep."""


def boom(_seconds: float) -> None:
    raise Boom


@pytest.fixture(autouse=True)
def rec(monkeypatch: pytest.MonkeyPatch) -> SendRecorder:
    """EVERY test here: SendInput replaced by a recorder, module state reset (nothing injected)."""
    r = SendRecorder()
    monkeypatch.setattr(api, "SendInput", r)
    monkeypatch.setattr(ev, "_last_tick", None)
    monkeypatch.setattr(ev, "_baseline", None)
    monkeypatch.setattr(ev, "_last_key_or_button", None)
    monkeypatch.setattr(api, "tick_count", lambda: 1000)
    inp._held_keys.clear()
    inp._held_buttons.clear()
    inp._monitor_cache[:] = [0.0, []]
    yield r
    inp._held_keys.clear()
    inp._held_buttons.clear()
    inp._monitor_cache[:] = [0.0, []]


def keys_of(batch: list[tuple]) -> list[tuple[int, bool]]:
    return [(e[1], bool(e[3] & api.KEYEVENTF_KEYUP)) for e in batch if e[0] == "key"]


# ----------------------------------------------------------------------------- InputBlocked


def test_short_sendinput_count_raises_input_blocked(rec: SendRecorder) -> None:
    rec.script = [0]
    with pytest.raises(inp.InputBlocked) as info:
        inp.press_keys([api.VK_RETURN], RecordingGuard())
    exc = info.value
    assert (exc.sent, exc.requested) == (0, 2)
    assert str(exc).startswith("Windows 擋下了模擬輸入")
    assert isinstance(exc, inp.InjectionAborted) and isinstance(exc, RuntimeError)
    assert inp.held_by_us() == []
    i18n.set_language("en")
    assert str(inp.InputBlocked()).startswith("Windows blocked the simulated input")


def test_partial_batch_tracks_the_keys_left_down(rec: SendRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    rec.script = [1]  # only "LShift down" of [LShift down, A down, A up, LShift up] was inserted
    with pytest.raises(inp.InputBlocked):
        inp.press_keys([api.VK_SHIFT, VK_A], RecordingGuard())
    assert inp.held_by_us() == [api.VK_LSHIFT]
    monkeypatch.setattr(api, "GetAsyncKeyState", lambda vk: 0)
    assert inp.release_all_modifiers() == [api.VK_LSHIFT]
    assert keys_of(rec.batches[-1]) == [(api.VK_LSHIFT, True)]
    assert inp.held_by_us() == []


def test_unicode_short_count_raises_too(rec: SendRecorder) -> None:
    rec.script = [None, 1]
    with pytest.raises(inp.InputBlocked):
        inp.type_text("AB", RecordingGuard(), TypingMode.UNICODE, key_delay_ms=0)
    assert len(rec.batches) == 2


# ----------------------------------------------------------------------------- holds release in finally


def test_key_hold_releases_when_sleep_raises(rec: SendRecorder) -> None:
    with pytest.raises(Boom):
        inp.press_keys([api.VK_CONTROL, VK_A], RecordingGuard(), hold_ms=30, sleep=boom)
    assert keys_of(rec.batches[0]) == [(api.VK_LCONTROL, False), (VK_A, False)]
    assert keys_of(rec.batches[1]) == [(VK_A, True), (api.VK_LCONTROL, True)]
    assert inp.held_by_us() == []


def test_failed_release_keeps_tracking_and_the_original_exception(rec: SendRecorder,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    rec.script = [None, 0]  # downs inserted, key-ups refused (screen locked meanwhile)
    with pytest.raises(Boom):
        inp.press_keys([api.VK_SHIFT, VK_A], RecordingGuard(), hold_ms=30, sleep=boom)
    assert sorted(inp.held_by_us()) == sorted([api.VK_LSHIFT, VK_A])
    monkeypatch.setattr(api, "GetAsyncKeyState", lambda vk: 0)
    assert sorted(inp.release_all_modifiers()) == sorted([api.VK_LSHIFT, VK_A])
    assert inp.held_by_us() == []


def test_hold_release_failure_raises_input_blocked_when_nothing_else_failed(rec: SendRecorder) -> None:
    rec.script = [None, 0]
    with pytest.raises(inp.InputBlocked):
        inp.press_keys([VK_A], RecordingGuard(), hold_ms=5, sleep=lambda s: None)
    assert inp.held_by_us() == [VK_A]


def test_click_hold_releases_the_button_when_sleep_raises(rec: SendRecorder) -> None:
    with pytest.raises(Boom):
        inp.click(100, 200, RecordingGuard(), settle_ms=0, hold_ms=30, sleep=boom)
    last = rec.batches[-1]
    assert any(e[0] == "mouse" and e[3] & api.MOUSEEVENTF_LEFTUP for e in last)
    assert inp.held_by_us() == []


def test_vk_hold_releases_shift_when_sleep_raises(rec: SendRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inp, "_caps_lock_on", lambda: False)
    with pytest.raises(Boom):
        inp.type_text("B", RecordingGuard(), TypingMode.VK, hold_ms=30, close_ime=False, sleep=boom)
    assert keys_of(rec.batches[0]) == [(api.VK_LSHIFT, False), (VK_B, False)]
    assert keys_of(rec.batches[1]) == [(VK_B, True), (api.VK_LSHIFT, True)]
    assert inp.held_by_us() == []


def test_unicode_hold_sends_the_up_events_when_sleep_raises(rec: SendRecorder) -> None:
    with pytest.raises(Boom):
        inp.type_text("x", RecordingGuard(), TypingMode.UNICODE, hold_ms=30, sleep=boom)
    assert [e[3] for e in rec.batches[0]] == [api.KEYEVENTF_UNICODE]
    assert [e[3] for e in rec.batches[1]] == [api.KEYEVENTF_UNICODE | api.KEYEVENTF_KEYUP]


# ----------------------------------------------------------------------------- typing modes


def test_unicode_typing_one_atomic_call_per_character(rec: SendRecorder) -> None:
    guard = RecordingGuard()
    slept: list[float] = []
    inp.type_text("aB-測\U0001f600", guard, TypingMode.UNICODE, key_delay_ms=7, sleep=slept.append)
    assert len(rec.batches) == 5
    assert [len(b) for b in rec.batches] == [2, 2, 2, 2, 4]  # the emoji = 2 UTF-16 units
    assert rec.batches[0] == [("key", 0, ord("a"), api.KEYEVENTF_UNICODE),
                              ("key", 0, ord("a"), api.KEYEVENTF_UNICODE | api.KEYEVENTF_KEYUP)]
    assert [e[2] for e in rec.batches[4]] == [0xD83D, 0xD83D, 0xDE00, 0xDE00]
    assert [c[0] for c in guard.calls] == [f"char[{i}]" for i in range(5)]
    assert slept == [0.007] * 4


def test_guard_runs_before_every_character(rec: SendRecorder) -> None:
    guard = RecordingGuard(raise_at=2, exc=inp.ForegroundLost())
    with pytest.raises(inp.ForegroundLost):
        inp.type_text("ABCD", guard, TypingMode.UNICODE, key_delay_ms=0)
    assert len(rec.batches) == 2  # two characters typed, the third refused before sending


# ----------------------------------------------------------------------------- UNICODE text after keys (IME)


class QtImeField:
    """SendInput stand-in modelling the measured Qt window with an IME (2026-11-17): the IME commit of a
    KEYEVENTF_UNICODE character is applied when it is sent, ordinary keys reach the field ``lag``
    seconds later. ``text()`` replays Ctrl+A, Backspace and characters in arrival order."""

    def __init__(self, clock: list[float], lag: float = 0.05) -> None:
        self.clock, self.lag = clock, lag
        self.arrivals: list[tuple[float, int, tuple]] = []

    def __call__(self, n: int, arr: Any, size: int) -> int:
        for i in range(n):
            e = decode(arr[i])
            delay = 0.0 if e[0] == "key" and e[3] & api.KEYEVENTF_UNICODE else self.lag
            self.arrivals.append((self.clock[0] + delay, len(self.arrivals), e))
        return n

    def text(self, start: str) -> str:
        text, selected, ctrl = start, False, False
        for _t, _n, (kind, vk, scan, flags) in sorted(self.arrivals):
            down = kind == "key" and not flags & api.KEYEVENTF_KEYUP
            if kind != "key":
                continue
            if flags & api.KEYEVENTF_UNICODE:
                if down:
                    text, selected = ("" if selected else text) + chr(scan), False
            elif vk == api.VK_LCONTROL:
                ctrl = down
            elif vk == VK_A and down and ctrl:
                selected = True
            elif vk == api.VK_BACK and down:
                text, selected = ("" if selected else text[:-1]), False
        return text


def test_unicode_text_after_the_clear_keeps_its_first_characters_on_a_qt_ime_target(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression (e2e 2026-11-17): typed 'A-1111' for AAAA-1111 - the clear's Ctrl+A + Backspace
    arrived after the first characters and deleted them."""
    clock = [100.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(api, "ImmGetDefaultIMEWnd", lambda h: 0x777 if int(h or 0) == 0x1234 else 0)

    def sleep(seconds: float) -> None:
        clock[0] += seconds

    results = []
    for settle in (0.0, inp.TEXT_AFTER_KEYS_SETTLE_S):
        monkeypatch.setattr(inp, "TEXT_AFTER_KEYS_SETTLE_S", settle)
        field = QtImeField(clock)
        monkeypatch.setattr(api, "SendInput", field)
        guard = RecordingGuard(hwnd=0x1234)
        inp.clear_field(guard, sleep=sleep)
        inp.type_text("AAAA-1111", guard, TypingMode.UNICODE, key_delay_ms=15, sleep=sleep)
        clock[0] += 1.0
        results.append(field.text("OLD-CODE"))
    assert results[0] != "AAAA-1111"  # the model reproduces the bug without the wait
    assert results[1] == "AAAA-1111"


def test_unicode_text_waits_only_after_a_recent_key_or_click_on_an_ime_target(
        rec: SendRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [100.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(api, "ImmGetDefaultIMEWnd", lambda h: 0x777 if int(h or 0) == 0x1234 else 0)
    guard, no_ime = RecordingGuard(hwnd=0x1234), RecordingGuard(hwnd=0x999)
    slept: list[float] = []
    inp.type_text("ab", guard, TypingMode.UNICODE, key_delay_ms=0, sleep=slept.append)  # nothing sent before
    inp.type_text("cd", guard, TypingMode.UNICODE, key_delay_ms=0, sleep=slept.append)  # characters do not count
    assert slept == []
    inp.press_keys([api.VK_BACK], guard)
    clock[0] += 0.05
    n = len(rec.batches)
    inp.type_text("ef", guard, TypingMode.UNICODE, key_delay_ms=0, sleep=slept.append)
    assert slept == [pytest.approx(inp.TEXT_AFTER_KEYS_SETTLE_S - 0.05)]
    assert len(rec.batches) == n + 2  # the wait happened, then both characters
    slept.clear()
    inp.click(10, 10, guard, settle_ms=0, hold_ms=0)  # a click counts as well
    inp.type_text("gh", no_ime, TypingMode.UNICODE, key_delay_ms=0, sleep=slept.append)  # no IME: no wait
    assert slept == []
    inp.type_text("ij", guard, TypingMode.UNICODE, key_delay_ms=0, sleep=slept.append)
    assert slept == [pytest.approx(inp.TEXT_AFTER_KEYS_SETTLE_S)]
    slept.clear()
    clock[0] += inp.TEXT_AFTER_KEYS_SETTLE_S
    inp.type_text("kl", guard, TypingMode.UNICODE, key_delay_ms=0, sleep=slept.append)  # already long enough
    assert slept == []


def test_only_ordinary_keys_and_mouse_buttons_count_as_keys_before_text(rec: SendRecorder) -> None:
    assert ev._is_key_or_button(ev._vk_event(api.VK_BACK, False))
    assert ev._is_key_or_button(ev._vk_event(api.VK_LCONTROL, True))
    assert ev._is_key_or_button(ev._mouse(0, 0, api.MOUSEEVENTF_LEFTUP))
    assert not ev._is_key_or_button(ev._kbd(0, ord("a"), api.KEYEVENTF_UNICODE))
    assert not ev._is_key_or_button(ev._mouse(0, 0, api.MOUSEEVENTF_MOVE))  # bring_to_foreground's zero move
    assert ev.seconds_since_key_or_button() is None
    inp.type_text("x", RecordingGuard(), TypingMode.UNICODE, key_delay_ms=0)
    assert ev.seconds_since_key_or_button() is None
    inp.press_keys([api.VK_RETURN], RecordingGuard())
    assert ev.seconds_since_key_or_button() is not None


def test_vk_typing_uses_shift_only_for_upper_case(rec: SendRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inp, "_caps_lock_on", lambda: False)
    inp.type_text("aB", RecordingGuard(), TypingMode.VK, key_delay_ms=0, close_ime=False)
    assert keys_of(rec.batches[0]) == [(VK_A, False), (VK_A, True)]
    assert keys_of(rec.batches[1]) == [(api.VK_LSHIFT, False), (VK_B, False), (VK_B, True), (api.VK_LSHIFT, True)]
    assert all(e[2] for e in rec.events)  # scan codes are filled in (raw-input readers need them)


def test_vk_typing_compensates_capslock(rec: SendRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inp, "_caps_lock_on", lambda: True)
    inp.type_text("aB", RecordingGuard(), TypingMode.VK, key_delay_ms=0, close_ime=False)
    assert keys_of(rec.batches[0]) == [(api.VK_LSHIFT, False), (VK_A, False), (VK_A, True), (api.VK_LSHIFT, True)]
    assert keys_of(rec.batches[1]) == [(VK_B, False), (VK_B, True)]


def test_unmappable_character_fails_before_any_input(rec: SendRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(inp, "_ime_send", lambda *a: calls.append(a) or 1)
    guard = RecordingGuard()
    with pytest.raises(inp.UnmappableChar) as info:
        inp.type_text("AB測", guard, TypingMode.VK)
    assert info.value.ch == "測" and "測" in str(info.value)
    assert rec.batches == [] and guard.calls == [] and calls == []
    with pytest.raises(inp.UnmappableChar):
        inp.type_text("\U0001f600", guard, TypingMode.VK)


class FakeIme:
    """_ime_send stand-in keeping an open / conversion state; reopening resets the conversion."""

    def __init__(self, opened: int = 1, conversion: int = 9) -> None:
        self.opened, self.conversion = opened, conversion
        self.log: list[tuple[int, int]] = []

    def __call__(self, hwnd: int, command: int, value: int = 0) -> int | None:
        self.log.append((command, value))
        if command == api.IMC_GETOPENSTATUS:
            return self.opened
        if command == api.IMC_GETCONVERSIONMODE:
            return self.conversion
        if command == api.IMC_SETOPENSTATUS:
            self.opened = value
            self.conversion = 0  # the measured IME went 1/1 -> 0/0 when closed; reopening may not restore
            return 0
        if command == api.IMC_SETCONVERSIONMODE:
            self.conversion = value
            return 0
        return None


@pytest.mark.parametrize("fail", [False, True])
def test_vk_mode_closes_the_ime_and_restores_it(rec: SendRecorder, monkeypatch: pytest.MonkeyPatch, fail: bool) -> None:
    ime = FakeIme()
    monkeypatch.setattr(inp, "_ime_send", ime)
    monkeypatch.setattr(inp, "_caps_lock_on", lambda: False)
    monkeypatch.setattr(inp, "IME_RESTORE_DELAY_S", 0.0)
    # checks: "ime", char[0], char[1] (raises after one character was typed), char[2]
    guard = RecordingGuard(raise_at=2, exc=inp.UserActivity()) if fail else RecordingGuard()
    if fail:
        with pytest.raises(inp.UserActivity):
            inp.type_text("abc", guard, TypingMode.VK, key_delay_ms=0, sleep=lambda s: None)
        assert len(rec.batches) == 1
    else:
        inp.type_text("abc", guard, TypingMode.VK, key_delay_ms=0, sleep=lambda s: None)
        assert len(rec.batches) == 3
    assert guard.calls[0][0] == "ime"
    assert (api.IMC_SETOPENSTATUS, 0) in ime.log
    assert ime.log.index((api.IMC_SETOPENSTATUS, 0)) < ime.log.index((api.IMC_SETOPENSTATUS, 1))
    assert (ime.opened, ime.conversion) == (1, 9)  # open state and conversion mode restored


def test_vk_mode_never_touches_the_ime_of_a_background_window(rec: SendRecorder,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    ime = FakeIme()
    monkeypatch.setattr(inp, "_ime_send", ime)
    with pytest.raises(inp.ForegroundLost):
        inp.type_text("abc", RecordingGuard(raise_at=0, exc=inp.ForegroundLost()), TypingMode.VK)
    assert ime.log == [] and rec.batches == []


def test_vk_mode_restores_the_ime_when_the_settle_sleep_raises(rec: SendRecorder,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    ime = FakeIme()
    monkeypatch.setattr(inp, "_ime_send", ime)
    monkeypatch.setattr(inp, "IME_RESTORE_DELAY_S", 0.0)
    with pytest.raises(Boom):
        inp.type_text("abc", RecordingGuard(), TypingMode.VK, sleep=boom)
    assert rec.batches == [] and ime.opened == 1


def test_vk_mode_leaves_a_closed_or_unwanted_ime_alone(rec: SendRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    ime = FakeIme(opened=0)
    monkeypatch.setattr(inp, "_ime_send", ime)
    inp.type_text("ab", RecordingGuard(), TypingMode.VK, key_delay_ms=0)
    assert all(cmd != api.IMC_SETOPENSTATUS for cmd, _v in ime.log)
    ime2 = FakeIme()
    monkeypatch.setattr(inp, "_ime_send", ime2)
    inp.type_text("ab", RecordingGuard(), TypingMode.VK, key_delay_ms=0, close_ime=False)
    assert ime2.log == []


class FakeClipboard:
    def __init__(self, restore_error: Exception | None = None) -> None:
        self.events: list[tuple[str, Any, float]] = []
        self.snap = object()
        self.restore_error = restore_error

    def snapshot(self, hwnd: int = 0) -> object:
        self.events.append(("snapshot", None, time.monotonic()))
        return self.snap

    def set_text(self, text: str, hwnd: int = 0, private: bool = True) -> None:
        self.events.append(("set_text", (text, private), time.monotonic()))

    def restore(self, snap: object, hwnd: int = 0) -> None:
        self.events.append(("restore", snap, time.monotonic()))
        if self.restore_error is not None:
            raise self.restore_error


@pytest.fixture
def fake_clip(monkeypatch: pytest.MonkeyPatch) -> FakeClipboard:
    from autopress.win32 import clipboard

    fake = FakeClipboard()
    for name in ("snapshot", "set_text", "restore"):
        monkeypatch.setattr(clipboard, name, getattr(fake, name))
    return fake


def test_clipboard_mode_pastes_and_restores(rec: SendRecorder, fake_clip: FakeClipboard) -> None:
    slept: list[float] = []
    inp.type_text("AB-12", RecordingGuard(), TypingMode.CLIPBOARD, restore_clipboard_ms=300, sleep=slept.append)
    assert [e[0] for e in fake_clip.events] == ["snapshot", "set_text", "restore"]
    assert fake_clip.events[1][1] == ("AB-12", True)
    assert fake_clip.events[2][1] is fake_clip.snap
    assert keys_of(rec.batches[0]) == [(api.VK_LCONTROL, False), (VK_V, False), (VK_V, True), (api.VK_LCONTROL, True)]
    assert slept == [0.3]


def test_clipboard_restore_delay_never_below_50_ms(rec: SendRecorder, fake_clip: FakeClipboard) -> None:
    slept: list[float] = []
    inp.type_text("X", RecordingGuard(), TypingMode.CLIPBOARD, restore_clipboard_ms=0, sleep=slept.append)
    assert slept == [0.05]


def test_clipboard_restored_when_stopped_during_the_restore_delay(rec: SendRecorder,
                                                                  fake_clip: FakeClipboard) -> None:
    with pytest.raises(Boom):
        inp.type_text("AB-12", RecordingGuard(), TypingMode.CLIPBOARD, sleep=boom)
    names = [e[0] for e in fake_clip.events]
    assert names == ["snapshot", "set_text", "restore"]
    pasted_at = fake_clip.events[1][2]
    restored_at = fake_clip.events[2][2]
    assert restored_at - pasted_at >= 0.045  # never right after Ctrl+V (that pasted the OLD content)


def test_clipboard_untouched_when_the_guard_refuses(rec: SendRecorder, fake_clip: FakeClipboard) -> None:
    with pytest.raises(inp.ForegroundLost):
        inp.type_text("X", RecordingGuard(raise_at=0, exc=inp.ForegroundLost()), TypingMode.CLIPBOARD)
    assert fake_clip.events == [] and rec.batches == []


def test_clipboard_restore_failure_does_not_mask_the_stop(rec: SendRecorder, monkeypatch: pytest.MonkeyPatch,
                                                          fake_clip: FakeClipboard) -> None:
    fake_clip.restore_error = inp.ClipboardBusy()
    with pytest.raises(Boom):
        inp.type_text("X", RecordingGuard(), TypingMode.CLIPBOARD, sleep=boom)
    # and without a stop the paste still counts as done (restore failure is only logged)
    inp.type_text("X", RecordingGuard(), TypingMode.CLIPBOARD, sleep=lambda s: None)


def test_empty_text_types_nothing(rec: SendRecorder, fake_clip: FakeClipboard) -> None:
    for mode in TypingMode:
        inp.type_text("", RecordingGuard(), mode)
    assert rec.batches == [] and fake_clip.events == []


# ----------------------------------------------------------------------------- guard


class Env:
    """Patched Win32 view for InjectGuard: foreground, hit-testing, pids, titles, styles."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, fg: int, root: int = 0, pids: dict[int, int] | None = None,
                 titles: dict[int, str] | None = None, styles: dict[int, int] | None = None) -> None:
        self.fg, self.root = fg, root
        self.pids = pids or {}
        monkeypatch.setattr(api, "GetForegroundWindow", lambda: self.fg)
        monkeypatch.setattr(api, "WindowFromPoint", lambda pt: self.root)
        monkeypatch.setattr(api, "GetAncestor", lambda h, flag: h)
        monkeypatch.setattr(api, "window_pid", lambda h: self.pids.get(int(h or 0), 0))
        monkeypatch.setattr(api, "window_text", lambda h: (titles or {}).get(h, ""))
        monkeypatch.setattr(api, "exstyle", lambda h: (styles or {}).get(h, 0))
        monkeypatch.setattr(api, "exe_path", lambda pid: ("C:/Games/game.exe", 0) if pid else (None, 87))
        monkeypatch.setattr(api, "class_name", lambda h: "SomeClass")
        monkeypatch.setattr(inp, "failsafe_triggered", lambda margin_px=3: False)
        monkeypatch.setattr(inp, "user_active_since_last_injection", lambda slack_ms=200: False)


TARGET, OTHER, SIBLING, OWN = 0x1000, 0x2000, 0x3000, 0x4000


def test_guard_passes_for_the_foreground_target(monkeypatch: pytest.MonkeyPatch) -> None:
    Env(monkeypatch, fg=TARGET, root=TARGET)
    guard = inp.InjectGuard(TARGET)
    guard.check("key")
    guard.check("click", (10, 20))


def test_guard_order_cancel_failsafe_input_foreground_point(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    Env(monkeypatch, fg=OTHER, root=OTHER, pids={OTHER: 1})
    order: list[str] = []

    def cancel() -> None:
        order.append("cancel")
        raise Boom

    with pytest.raises(Boom):
        inp.InjectGuard(TARGET, cancel=cancel).check("key")
    monkeypatch.setattr(inp, "failsafe_triggered", lambda margin_px=3: True)
    with pytest.raises(inp.FailsafeTriggered):
        inp.InjectGuard(TARGET, cancel=lambda: order.append("ok")).check("key")
    monkeypatch.setattr(inp, "user_active_since_last_injection", lambda slack_ms=200: True)
    with pytest.raises(inp.UserActivity):
        inp.InjectGuard(TARGET, failsafe=False).check("key")
    with pytest.raises(inp.ForegroundLost) as info:
        inp.InjectGuard(TARGET, failsafe=False, check_user_input=False).check("key")
    assert info.value.foreground_hwnd == OTHER and info.value.what == "key"
    assert str(info.value).startswith("目標視窗失去焦點")
    env = Env(monkeypatch, fg=TARGET, root=OTHER, pids={OTHER: os.getpid() + 1}, titles={OTHER: "Notepad"})
    with pytest.raises(inp.PointNotOnTarget) as pinfo:
        inp.InjectGuard(TARGET).check("click", (5, 6))
    assert pinfo.value.covering_hwnd == OTHER and pinfo.value.point == (5, 6)
    assert "「Notepad」" in str(pinfo.value) and not pinfo.value.covering_is_own
    env.root = TARGET
    inp.InjectGuard(TARGET).check("click", (5, 6))
    assert order == ["cancel", "ok"]


def test_guard_allow_same_process(monkeypatch: pytest.MonkeyPatch) -> None:
    Env(monkeypatch, fg=SIBLING, root=SIBLING, pids={TARGET: 77, SIBLING: 77, OTHER: 78})
    with pytest.raises(inp.ForegroundLost):
        inp.InjectGuard(TARGET).check("key")
    guard = inp.InjectGuard(TARGET, allow_same_process=True)
    guard.check("key")
    guard.check("click", (1, 1))  # a root window of the target process is accepted for clicks
    inp.InjectGuard(TARGET, pid=77, allow_same_process=True).check("click", (1, 1))
    wrong_pid = inp.InjectGuard(TARGET, pid=78, allow_same_process=True)
    with pytest.raises(inp.ForegroundLost):
        wrong_pid.check("key")
    wrong_pid.hwnd = TARGET  # reassigning the window forgets the explicit pid
    assert wrong_pid.pid == 77
    wrong_pid.check("key")


def test_point_messages_name_the_covering_window(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    me = os.getpid()
    Env(monkeypatch, fg=TARGET, root=OWN, pids={TARGET: 5, OWN: me}, styles={OWN: api.WS_EX_TOOLWINDOW | api.WS_EX_TOPMOST})
    guard = inp.InjectGuard(TARGET)
    with pytest.raises(inp.PointNotOnTarget) as info:
        guard.check("click", (1, 2))
    assert info.value.covering_is_own and info.value.covering_is_minibar
    assert str(info.value).startswith("AutoPress 的迷你控制列擋住了點擊位置")
    Env(monkeypatch, fg=TARGET, root=OWN, pids={TARGET: 5, OWN: me})  # own, but not a tool window
    with pytest.raises(inp.PointNotOnTarget) as info:
        guard.check("click", (1, 2))
    assert "「AutoPress」" in str(info.value) and not info.value.covering_is_minibar
    env = Env(monkeypatch, fg=TARGET, root=OTHER, pids={TARGET: 5, OTHER: 6})  # untitled -> exe name
    with pytest.raises(inp.PointNotOnTarget) as info:
        guard.check("click", (1, 2))
    assert "「game.exe」" in str(info.value)
    env.root = 0  # nothing under the point (off-screen)
    with pytest.raises(inp.PointNotOnTarget) as info:
        guard.check("click", (-99999, 5))
    assert info.value.covering_hwnd == 0 and "螢幕外" in str(info.value)
    i18n.set_language("en")
    env.root = OTHER
    with pytest.raises(inp.PointNotOnTarget) as info:
        guard.check("click", (1, 2))
    assert str(info.value).startswith('The click position is covered by "game.exe"')


def test_exception_defaults_are_localized() -> None:
    assert str(inp.ForegroundLost()).startswith("目標視窗失去焦點")
    assert str(inp.UserActivity()).startswith("偵測到滑鼠或鍵盤操作")
    assert str(inp.FailsafeTriggered()) == "滑鼠移到螢幕左上角，已緊急停止。"
    assert "剪貼簿被其他程式佔用" in str(inp.ClipboardBusy()) and isinstance(inp.ClipboardBusy(), OSError)
    assert "「é」" in str(inp.UnmappableChar("é")) and isinstance(inp.UnmappableChar("é"), ValueError)
    assert str(inp.ForegroundLost("custom")) == "custom"
    i18n.set_language("en")
    assert str(inp.FailsafeTriggered()) == "Mouse moved to the top-left corner: emergency stop."
    assert str(inp.UnmappableChar("é")).startswith('Game mode cannot type "é"')


# ----------------------------------------------------------------------------- failsafe


def mon(rect: tuple[int, int, int, int], primary: bool = False) -> api.MonitorRecord:
    return api.MonitorRecord(1, "\\\\.\\DISPLAY", rect, rect, primary, 96)


def test_failsafe_uses_the_outer_corner_of_a_left_secondary_monitor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "enum_monitors", lambda: [mon((0, 0, 1920, 1080), True), mon((-1920, 0, 1920, 1080))])
    pos = [(-1920, 0)]
    monkeypatch.setattr(api, "cursor_pos", lambda: pos[0])
    assert inp.failsafe_triggered() is True
    for p, expected in (((-1917, 3), True), ((-1916, 0), False), ((0, 0), False), ((2, 1), False),
                        ((-1920, 4), False)):
        pos[0] = p
        assert inp.failsafe_triggered(3) is expected, p
    pos[0] = (-1910, 9)
    assert inp.failsafe_triggered(10) is True


def test_failsafe_single_monitor_and_unreadable_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "enum_monitors", lambda: [mon((0, 0, 2560, 1440), True)])
    monkeypatch.setattr(api, "cursor_pos", lambda: (1, 2))
    assert inp.failsafe_triggered() is True
    monkeypatch.setattr(api, "cursor_pos", lambda: None)  # locked session: never a false trip
    assert inp.failsafe_triggered() is False


def test_failsafe_monitor_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def mons() -> list[api.MonitorRecord]:
        calls.append(1)
        return [mon((0, 0, 100, 100), True)]

    monkeypatch.setattr(api, "enum_monitors", mons)
    monkeypatch.setattr(api, "cursor_pos", lambda: (50, 50))
    for _ in range(5):
        inp.failsafe_triggered()
    assert len(calls) == 1
    inp._monitor_cache[0] -= inp.MONITOR_CACHE_S + 0.1
    inp.failsafe_triggered()
    assert len(calls) == 2


# ----------------------------------------------------------------------------- ticks / user input


def test_tick_comparison_is_wrap_safe() -> None:
    assert api.tick_newer(5, 0xFFFFFFF0) is True  # 21 ms after the 49.7-day wrap
    assert api.tick_newer(0xFFFFFFF0, 5) is False
    assert api.tick_newer(1234, 1234) is False
    assert api.tick_newer(0x7FFFFFFF, 0) is True and api.tick_newer(0x80000000, 0) is False


def test_user_activity_across_the_wrap(monkeypatch: pytest.MonkeyPatch) -> None:
    last_input = [0]
    monkeypatch.setattr(api, "last_input_tick", lambda: last_input[0])
    monkeypatch.setattr(ev, "_last_tick", 0xFFFFFF00)  # injected 256 ms before the wrap
    last_input[0] = 0x00000100  # input 512 ms later, after the wrap
    assert inp.user_active_since_last_injection(200) is True
    last_input[0] = 0xFFFFFF50  # 80 ms after our injection: inside the slack
    assert inp.user_active_since_last_injection(200) is False
    last_input[0] = 0xFFFFFF00  # our own SendInput (0 ms lag, measured)
    assert inp.user_active_since_last_injection(0) is False


def test_baseline_and_missing_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    last_input = [5000]
    monkeypatch.setattr(api, "last_input_tick", lambda: last_input[0])
    assert inp.user_active_since_last_injection() is False  # nothing to compare with yet
    monkeypatch.setattr(api, "tick_count", lambda: 6000)
    inp.reset_user_input_baseline()
    assert inp.user_active_since_last_injection() is False  # the click that resumed is "ours"
    last_input[0] = 6500
    assert inp.user_active_since_last_injection(200) is True
    monkeypatch.setattr(api, "tick_count", lambda: 6600)
    inp.press_keys([api.VK_RETURN], RecordingGuard())  # a newer injection replaces the reference
    assert inp.last_injection_tick() == 6600
    assert inp.user_active_since_last_injection(200) is False
    monkeypatch.setattr(api, "last_input_tick", lambda: None)
    assert inp.user_active_since_last_injection() is False


# ----------------------------------------------------------------------------- mouse


MOVE_ABS = api.MOUSEEVENTF_MOVE | api.MOUSEEVENTF_ABSOLUTE | api.MOUSEEVENTF_VIRTUALDESK


def test_click_absolute_virtual_desktop_coordinates(rec: SendRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "virtual_screen", lambda: (-1920, 0, 3840, 1080))
    guard = RecordingGuard()
    slept: list[float] = []
    inp.click(-1874, 500, guard, settle_ms=30, hold_ms=30, sleep=slept.append)
    nx = ((-1874 + 1920) * 65536 + 32768) // 3840  # pixel-centre formula, 159/159 exact (measured)
    ny = (500 * 65536 + 32768) // 1080
    assert rec.batches[0] == [("mouse", nx, ny, MOVE_ABS)]
    assert rec.batches[1] == [("mouse", nx, ny, MOVE_ABS), ("mouse", 0, 0, api.MOUSEEVENTF_LEFTDOWN)]
    assert rec.batches[2] == [("mouse", nx, ny, MOVE_ABS), ("mouse", 0, 0, api.MOUSEEVENTF_LEFTUP)]
    assert slept == [0.03, 0.03]
    assert guard.calls == [("click", (-1874, 500)), ("click", (-1874, 500))]


def test_click_without_waits_is_one_atomic_call(rec: SendRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "virtual_screen", lambda: (0, 0, 1920, 1080))
    guard = RecordingGuard()
    inp.click(10, 10, guard, button=MouseButton.RIGHT, settle_ms=0, hold_ms=0)
    assert len(rec.batches) == 1
    assert [e[3] for e in rec.batches[0]] == [MOVE_ABS, api.MOUSEEVENTF_RIGHTDOWN, api.MOUSEEVENTF_RIGHTUP]
    assert len(guard.calls) == 1  # every passed check is followed by an injection


def test_injected_presses_counts_key_and_button_downs_only(rec: SendRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "virtual_screen", lambda: (0, 0, 1920, 1080))
    start = inp.injected_presses()
    inp.press_keys([api.VK_SHIFT, VK_A], RecordingGuard())  # 2 key downs
    inp.click(5, 5, RecordingGuard(), settle_ms=30, hold_ms=0, sleep=lambda s: None)  # moves don't count: 1
    inp.type_text("ab", RecordingGuard(), key_delay_ms=0)  # 2 unicode key downs
    assert inp.injected_presses() - start == 5
    rec.script = [1]  # only "LShift down" inserted
    with pytest.raises(inp.InputBlocked):
        inp.press_keys([api.VK_SHIFT, VK_A], RecordingGuard())
    assert inp.injected_presses() - start == 6
    rec.script = [1]  # a lone move inserted, the press refused
    with pytest.raises(inp.InputBlocked):
        inp.click(5, 5, RecordingGuard(), settle_ms=0, hold_ms=0)
    assert inp.injected_presses() - start == 6


def test_double_click_is_two_held_clicks(rec: SendRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "virtual_screen", lambda: (0, 0, 1920, 1080))
    slept: list[float] = []
    inp.click(10, 10, RecordingGuard(), double=True, button=MouseButton.MIDDLE, settle_ms=0, hold_ms=0,
              sleep=slept.append)
    downs = [e for e in rec.events if e[0] == "mouse" and e[3] & api.MOUSEEVENTF_MIDDLEDOWN]
    ups = [e for e in rec.events if e[0] == "mouse" and e[3] & api.MOUSEEVENTF_MIDDLEUP]
    assert len(downs) == len(ups) == 2 and len(rec.batches) == 4
    assert slept == [0.02, 0.02]  # never an atomic 4-event double click (Qt ignores it)


def test_click_restores_the_cursor_as_our_own_input(rec: SendRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "virtual_screen", lambda: (0, 0, 1920, 1080))
    monkeypatch.setattr(api, "cursor_pos", lambda: (7, 8))
    moved: list[tuple[int, int]] = []
    monkeypatch.setattr(api, "SetCursorPos", lambda x, y: moved.append((x, y)) or 1)
    ticks = iter([100, 150])
    monkeypatch.setattr(api, "tick_count", lambda: next(ticks))
    inp.click(500, 500, RecordingGuard(), settle_ms=0, hold_ms=0, restore_cursor=True)
    assert moved == [(7, 8)]
    assert inp.last_injection_tick() == 150  # the SetCursorPos counts as ours, not as the user's


# ----------------------------------------------------------------------------- keys


def test_press_combo_refuses_system_shortcuts(rec: SendRecorder) -> None:
    for combo in ("Alt+F4", "Win+R", "Ctrl+Alt+Delete", "Alt+Tab", "Ctrl+Shift+Esc"):
        with pytest.raises(ValueError):
            inp.press_combo(combo, RecordingGuard())
    with pytest.raises(ValueError):
        inp.press_combo("Hyper+Q", RecordingGuard())
    assert rec.batches == []


def test_press_combo_repeat_and_interval(rec: SendRecorder) -> None:
    slept: list[float] = []
    guard = RecordingGuard()
    inp.press_combo("ctrl+a", guard, repeat=3, interval_ms=40, sleep=slept.append)
    assert len(rec.batches) == 3 and slept == [0.04, 0.04]
    assert keys_of(rec.batches[0]) == [(api.VK_LCONTROL, False), (VK_A, False), (VK_A, True), (api.VK_LCONTROL, True)]
    assert len(guard.calls) == 3


def test_extended_flag_for_navigation_keys(rec: SendRecorder) -> None:
    inp.press_keys([api.VK_LEFT], RecordingGuard())
    inp.press_keys([api.VK_RETURN], RecordingGuard())
    assert all(e[3] & api.KEYEVENTF_EXTENDEDKEY for e in rec.batches[0])
    assert not any(e[3] & api.KEYEVENTF_EXTENDEDKEY for e in rec.batches[1])


@pytest.mark.parametrize(("method", "expected"), [
    (ClearMethod.CTRL_A, [[api.VK_LCONTROL, VK_A], [api.VK_BACK]]),
    (ClearMethod.END_SHIFT_HOME, [[api.VK_END], [api.VK_LSHIFT, api.VK_HOME], [api.VK_DELETE]]),
    (ClearMethod.BACKSPACE, [[api.VK_END]] + [[api.VK_BACK]] * 3),
])
def test_clear_field_recipes(rec: SendRecorder, method: ClearMethod, expected: list[list[int]]) -> None:
    guard = RecordingGuard()
    inp.clear_field(guard, method, backspaces=3)
    assert [[vk for vk, up in keys_of(b) if not up] for b in rec.batches] == expected
    assert len(guard.calls) == len(expected)  # one guard check per key combo


def test_release_all_modifiers_alt_and_win_only_when_ours(rec: SendRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    down = {api.VK_LSHIFT, api.VK_RCONTROL, api.VK_LMENU, api.VK_LWIN}
    monkeypatch.setattr(api, "GetAsyncKeyState", lambda vk: -32768 if vk in down else 0)
    assert inp.release_all_modifiers() == [api.VK_LSHIFT, api.VK_RCONTROL]
    assert inp.release_all_modifiers([api.VK_MENU]) == [api.VK_LSHIFT, api.VK_RCONTROL, api.VK_LMENU]
    assert inp.release_all_modifiers([0x5B]) == [api.VK_LSHIFT, api.VK_RCONTROL, api.VK_LWIN]
    monkeypatch.setattr(api, "GetAsyncKeyState", lambda vk: 0)
    assert inp.release_all_modifiers() == []


def test_release_all_modifiers_releases_held_buttons_and_never_raises(rec: SendRecorder,
                                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "GetAsyncKeyState", lambda vk: 0)
    inp._held_buttons[MouseButton.LEFT] = None
    inp._held_keys[api.VK_LMENU] = None  # an Alt WE pressed is released even without pressed_by_us
    rec.script = [0]
    assert inp.release_all_modifiers() == []  # refused (locked screen): logged, still tracked
    assert sorted(inp.held_by_us()) == sorted([api.VK_LBUTTON, api.VK_LMENU])
    assert inp.release_all_modifiers() == [api.VK_LBUTTON, api.VK_LMENU]
    assert rec.batches[-1][0] == ("mouse", 0, 0, api.MOUSEEVENTF_LEFTUP)
    assert inp.held_by_us() == []


# ----------------------------------------------------------------------------- foreground


class Fg:
    """Patched foreground state: SetForegroundWindow only succeeds after the chosen trick."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, iconic: bool = False, grant_on: str = "input") -> None:
        self.fg = OTHER
        self.iconic = iconic
        self.log: list[str] = []
        self.grant_on = grant_on
        monkeypatch.setattr(api, "IsWindow", lambda h: h == TARGET)
        monkeypatch.setattr(api, "IsIconic", lambda h: self.iconic)
        monkeypatch.setattr(api, "GetForegroundWindow", lambda: self.fg)
        monkeypatch.setattr(api, "ShowWindow", self.show)
        monkeypatch.setattr(api, "SetForegroundWindow", self.set_fg)
        monkeypatch.setattr(api, "BringWindowToTop", lambda h: self.log.append("top") or 1)
        monkeypatch.setattr(api, "AttachThreadInput", lambda a, b, c: self.log.append(f"attach{int(c)}") or 1)
        monkeypatch.setattr(api, "window_tid", lambda h: 99)
        monkeypatch.setattr(api, "GetCurrentThreadId", lambda: 1)

    def show(self, h: int, cmd: int) -> int:
        self.log.append(f"show{cmd}")
        self.iconic = False
        if self.grant_on == "restore":
            self.fg = h
        return 1

    def set_fg(self, h: int) -> int:
        last = self.log[-1] if self.log else ""
        self.log.append("setfg")
        if self.grant_on == "plain" or (self.grant_on == "input" and last == "move") \
                or (self.grant_on == "attach" and last == "top"):
            self.fg = h
        return 1


def test_bring_to_foreground_falls_back_to_the_input_trick(rec: SendRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    fg = Fg(monkeypatch, grant_on="input")
    real_send = inp._send

    def send(events: Any, what: str = "") -> None:
        fg.log.append("move")
        real_send(events, what)

    monkeypatch.setattr(inp, "_send", send)
    ok, method = inp.bring_to_foreground(TARGET, verify_s=0.02, sleep=lambda s: None)
    assert (ok, method) == (True, "input")
    assert rec.batches == [[("mouse", 0, 0, api.MOUSEEVENTF_MOVE)]]  # zero-distance move, no click


def test_bring_to_foreground_attach_trick_detaches(rec: SendRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    fg = Fg(monkeypatch, grant_on="attach")
    ok, method = inp.bring_to_foreground(TARGET, verify_s=0.02, sleep=lambda s: None)
    assert (ok, method) == (True, "attach")
    assert fg.log.count("attach1") == fg.log.count("attach0") == 1


def test_bring_to_foreground_restores_minimized_and_waits_for_a_stable_client(
        rec: SendRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    from autopress.win32 import windows

    fg = Fg(monkeypatch, iconic=True, grant_on="restore")
    rects = iter([(0, 0, 800, 600), (0, 0, 1920, 1080), (0, 0, 1920, 1080)])
    monkeypatch.setattr(windows, "client_rect", lambda h: next(rects))
    slept: list[float] = []
    ok, method = inp.bring_to_foreground(TARGET, verify_s=0.02, sleep=slept.append)
    assert (ok, method) == (True, "restore")
    assert fg.log[0] == f"show{api.SW_RESTORE}"
    assert slept.count(0.1) == 2  # the client rect changed once, then two equal reads 100 ms apart


def test_bring_to_foreground_already_failed_and_gone(rec: SendRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    fg = Fg(monkeypatch, grant_on="never")
    ok, reason = inp.bring_to_foreground(TARGET, attempts=2, verify_s=0.0, sleep=lambda s: None)
    assert ok is False and reason
    assert fg.log.count("setfg") == 6  # 2 rounds x (plain, input, attach)
    fg.fg = TARGET
    assert inp.bring_to_foreground(TARGET) == (True, "already")
    assert inp.bring_to_foreground(0x9999)[0] is False


def test_a_minimized_foreground_window_is_still_restored(rec: SendRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    from autopress.win32 import windows

    fg = Fg(monkeypatch, iconic=True, grant_on="restore")
    fg.fg = TARGET  # minimized but still reported as the foreground window
    monkeypatch.setattr(windows, "client_rect", lambda h: (0, 0, 800, 600))
    ok, method = inp.bring_to_foreground(TARGET, verify_s=0.02, sleep=lambda s: None)
    assert (ok, method) == (True, "restore") and fg.log[0] == f"show{api.SW_RESTORE}"


def test_bring_to_foreground_propagates_input_blocked(rec: SendRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    Fg(monkeypatch, grant_on="never")
    rec.script = [0]
    with pytest.raises(inp.InputBlocked):
        inp.bring_to_foreground(TARGET, verify_s=0.0, sleep=lambda s: None)


# ----------------------------------------------------------------------------- realinput harness (desktop state)


class Desktop:
    """Fakes for tests/win32_harness.desktop_state_restored(): clipboard, CapsLock, cursor and
    release_all_modifiers (SendInput is the ``rec`` recorder): nothing reaches the real desktop."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from autopress.win32 import clipboard

        self.seq, self.caps, self.cursor = 7, 0, (10, 20)
        self.snap: object = object()
        self.restored: list[object] = []
        self.moved: list[tuple[int, int]] = []
        self.released = 0
        self.busy_restore = False
        monkeypatch.setattr(clipboard, "snapshot", self.snapshot)
        monkeypatch.setattr(clipboard, "restore", self.restore)
        monkeypatch.setattr(api, "GetClipboardSequenceNumber", lambda: self.seq)
        monkeypatch.setattr(api, "GetKeyState", lambda vk: self.caps if vk == api.VK_CAPITAL else 0)
        monkeypatch.setattr(api, "cursor_pos", lambda: self.cursor)
        monkeypatch.setattr(api, "SetCursorPos", lambda x, y: self.moved.append((x, y)))
        monkeypatch.setattr(inp, "release_all_modifiers", self.release)
        monkeypatch.setattr(time, "sleep", lambda s: None)

    def snapshot(self) -> object:
        if self.snap is None:
            raise inp.ClipboardBusy()
        return self.snap

    def restore(self, snap: object) -> None:
        if self.busy_restore:
            raise inp.ClipboardBusy()
        self.restored.append(snap)

    def release(self) -> list[int]:
        self.released += 1
        return []


def test_desktop_state_restored_puts_back_only_what_changed(rec: SendRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    """tests/conftest.py wraps every realinput test in it (those run only with AUTOPRESS_REALINPUT=1)."""
    from tests.win32_harness import desktop_state_restored

    d = Desktop(monkeypatch)
    with desktop_state_restored():
        pass  # nothing changed: nothing is written back, held keys are still released
    assert (d.restored, d.moved, rec.batches, d.released) == ([], [], [], 1)
    with pytest.raises(Boom), desktop_state_restored():  # the restore also runs when the body raises
        d.seq, d.caps, d.cursor = 8, 1, (300, 400)
        raise Boom
    assert d.restored == [d.snap] and d.moved == [(10, 20)] and d.released == 2
    assert keys_of(rec.batches[0]) == [(api.VK_CAPITAL, False), (api.VK_CAPITAL, True)]


def test_desktop_state_restored_warns_instead_of_failing(rec: SendRecorder, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.win32_harness import desktop_state_restored

    d = Desktop(monkeypatch)
    d.busy_restore, d.cursor = True, None  # clipboard held by another program; locked session
    rec.script = [0]  # the CapsLock toggle is refused
    with pytest.warns(UserWarning) as record, desktop_state_restored():
        d.seq, d.caps = 8, 1
    assert sorted(str(w.message).split(":")[1].strip() for w in record) == ["CapsLock not restored",
                                                                             "clipboard not restored"]
    assert d.moved == [] and d.released == 1
    d.snap, d.busy_restore = None, False  # no snapshot (clipboard busy at the start): never written back
    with desktop_state_restored():
        d.seq = 9
    assert d.restored == []
