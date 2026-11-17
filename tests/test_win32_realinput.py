# OWNED BY G3
"""REALINPUT tests of the win32 layer (SPEC 8.2 G3) - skipped unless AUTOPRESS_REALINPUT=1.

They inject real keyboard / mouse input, but only into AutoPress's own test windows
(tests/win32_target_app.py processes and windows of this test process), always through an
InjectGuard (foreground check on). After every test, tests/conftest.py releases every key still
held (release_all_modifiers()) and restores the user's clipboard, CapsLock state and cursor
position. Run them alone, with nobody touching the PC (touching it trips the user-input guard and
fails the test):

    AUTOPRESS_REALINPUT=1 .venv/Scripts/python.exe -m pytest -q -m realinput tests/test_win32_realinput.py -rw

The exclude_from_capture measurement (SPEC 11.10) is reported as a warning (``-rw`` lists it).
Run on 2026-11-17 by a fresh verifier: all 26 tests then in this module passed, twice in a row.
"""

from __future__ import annotations

import time
import warnings
from collections.abc import Iterator
from pathlib import Path

import pytest

from autopress.models import ClearMethod, MouseButton, TypingMode
from autopress.win32 import api, clipboard, windows
from autopress.win32 import input as inp
from autopress.win32.hotkeys import GlobalHotkeys
from tests.win32_harness import TargetApp, center
from tests.win32_harness import caps_lock_on as caps_on
from tests.win32_helpers import HWND_TOPMOST, SW_MINIMIZE, SWP_NOACTIVATE, SetWindowPos, ShowWindow

pytestmark = pytest.mark.realinput

VK_A, VK_Q, VK_F24 = 0x41, 0x51, 0x87
MODIFIERS = (api.VK_SHIFT, api.VK_CONTROL, api.VK_LSHIFT, api.VK_RSHIFT, api.VK_LCONTROL, api.VK_RCONTROL)


class Boom(Exception):
    """Stands in for StopRequested raised by RunControl.sleep."""


def boom(_seconds: float) -> None:
    raise Boom


def key_down(vk: int) -> bool:
    return bool(api.GetAsyncKeyState(vk) & 0x8000)


def button_released(vk: int, timeout_s: float = 0.5) -> bool:
    """True once GetAsyncKeyState shows the mouse button ``vk`` up (within ``timeout_s``). SendInput
    returns before Windows has processed injected MOUSE events, so right after a button-up was
    inserted the button can still read "down" for a few ms (2026-11-17, two runs of 40: 17 and 6 first
    reads "down", every one "up" within 2 ms; keyboard keys read "up" at once). A stuck button never
    reads up."""
    deadline = time.monotonic() + timeout_s
    while key_down(vk):
        if time.monotonic() > deadline:
            return False
        time.sleep(0.001)
    return True


# tests/conftest.py (_realinput_user_state) creates the QApplication first (per-monitor-v2: physical
# coordinates) and, after every test, releases held keys and restores CapsLock, clipboard and cursor.


def focus(t: TargetApp) -> inp.InjectGuard:
    """Bring the target to the front and return a guard for it (user-input baseline reset)."""
    ok, how = inp.bring_to_foreground(t.hwnd)
    assert ok, f"could not activate the test target: {how}"
    time.sleep(0.2)  # after activation (win32_input.md 9)
    t.refresh()
    inp.reset_user_input_baseline()
    return inp.InjectGuard(t.hwnd, pid=t.pid)


def focus_edit(t: TargetApp, guard: inp.InjectGuard) -> None:
    inp.click(*center(t.info["edit_rect"]), guard)
    time.sleep(0.12)  # after click, before typing


def launch(tmp_path: Path, env: dict[str, str], name: str, *extra: str, title: str | None = None) -> TargetApp:
    return TargetApp(tmp_path, env, name, title=title, extra=list(extra))


@pytest.fixture
def target(tmp_path: Path, clean_env: dict[str, str]) -> Iterator[TargetApp]:
    t = launch(tmp_path, clean_env, "target", "--ime", "off")
    yield t
    t.close()


@pytest.fixture
def target_ime(tmp_path: Path, clean_env: dict[str, str]) -> Iterator[TargetApp]:
    t = launch(tmp_path, clean_env, "target_ime", "--ime", "on")
    yield t
    t.close()


@pytest.fixture
def decoy(tmp_path: Path, clean_env: dict[str, str]) -> Iterator[TargetApp]:
    t = launch(tmp_path, clean_env, "decoy", "--ime", "off", "--pos", "860,560")
    yield t
    t.close()


# ----------------------------------------------------------------------------- typing


@pytest.mark.parametrize(("mode", "text"), [
    (TypingMode.UNICODE, "AbC-123_xyz"), (TypingMode.UNICODE, "測試ABC"),
    (TypingMode.CLIPBOARD, "AbC-123_xyz"), (TypingMode.CLIPBOARD, "測試ABC"),
    (TypingMode.VK, "AbC-123_xyz"), (TypingMode.VK, "a1B2c3D4e5F6g7H8"),
])
def test_typing_modes_type_exactly(target: TargetApp, mode: TypingMode, text: str) -> None:
    guard = focus(target)
    focus_edit(target, guard)
    inp.clear_field(guard)
    inp.type_text(text, guard, mode, key_delay_ms=5)
    assert target.wait_text(text) == text
    assert inp.held_by_us() == []


def test_vk_typing_with_capslock_on(target: TargetApp) -> None:
    guard = focus(target)
    focus_edit(target, guard)
    if not caps_on():
        inp.press_keys([api.VK_CAPITAL], guard)
        time.sleep(0.15)
    assert caps_on()
    inp.clear_field(guard)
    inp.type_text("AbC-123_xyz", guard, TypingMode.VK, key_delay_ms=5)
    assert target.wait_text("AbC-123_xyz") == "AbC-123_xyz"


def test_vk_typing_closes_and_restores_the_target_ime(target_ime: TargetApp) -> None:
    guard = focus(target_ime)
    focus_edit(target_ime, guard)
    before = inp.ime_state(target_ime.hwnd)
    if before is None:
        pytest.skip("the target window has no IME on this PC")
    inp.press_keys([api.VK_ESCAPE], guard)  # cancel a composition left over
    inp.clear_field(guard)
    inp.type_text("ab1cd2", guard, TypingMode.VK, key_delay_ms=5)
    assert target_ime.wait_text("ab1cd2") == "ab1cd2"
    assert inp.ime_state(target_ime.hwnd) == before


def test_our_own_input_never_trips_the_user_input_guard(target: TargetApp) -> None:
    guard = focus(target)
    focus_edit(target, guard)
    inp.clear_field(guard)
    text = "ABCDEFGHIJ0123456789abcdefghij"
    inp.type_text(text, guard, key_delay_ms=20)  # ~0.6 s, GetLastInputInfo checked before every char
    assert target.wait_text(text) == text
    assert not inp.user_active_since_last_injection()


@pytest.mark.parametrize("method", list(ClearMethod))
def test_clear_recipes_empty_the_field(target: TargetApp, method: ClearMethod) -> None:
    guard = focus(target)
    focus_edit(target, guard)
    inp.clear_field(guard)
    inp.type_text("ABCD-1234", guard, key_delay_ms=0)
    assert target.wait_text("ABCD-1234") == "ABCD-1234"
    inp.press_keys([api.VK_HOME], guard)
    for _ in range(3):
        inp.press_keys([api.VK_RIGHT], guard)  # caret inside the text
    inp.clear_field(guard, method, backspaces=25)
    assert target.wait_text("") == ""


def test_unicode_text_after_clear_field_keeps_its_first_characters_with_an_ime(target_ime: TargetApp) -> None:
    """Regression (2026-11-17): in a Qt window with an IME, KEYEVENTF_UNICODE characters typed right
    after clear_field's Ctrl+A + Backspace overtook those keys and the clear deleted the first
    characters of the code (30/30 without a gap). type_text now waits TEXT_AFTER_KEYS_SETTLE_S after
    our last key: checked here on a real IME window (the ``target`` fixture has no IME window after
    ImmDisableIME, so it never waits). The field is never empty before a clear, so text that a late
    clear would delete cannot pass for the code first."""
    guard = focus(target_ime)
    if not inp._has_ime_window(target_ime.hwnd):
        pytest.skip("the target window has no IME window on this PC")
    focus_edit(target_ime, guard)
    inp.type_text("OLD-0000", guard, key_delay_ms=15)
    assert target_ime.wait_text("OLD-0000") == "OLD-0000"
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        time.sleep(seconds)

    for code in ("AB12-CD34", "EF56-GH78", "JK90-LM12", "NP34-QR56", "ST78-UV90"):
        slept.clear()
        inp.clear_field(guard)
        inp.type_text(code, guard, key_delay_ms=15, sleep=sleep)
        # the settle came first (this window has an IME window), then a key delay after each character but the last
        assert len(slept) == len(code) and 0 < slept[0] <= inp.TEXT_AFTER_KEYS_SETTLE_S, slept
        assert target_ime.wait_text(code) == code
    assert inp.held_by_us() == []


# ----------------------------------------------------------------------------- mouse


def test_clicks_submit_and_double_click(target: TargetApp) -> None:
    guard = focus(target)
    m = target.mark()
    inp.click(*center(target.info["submit_rect"]), guard)
    assert target.wait(lambda evs: [e for e in evs if e["ev"] == "submit" and e["src"] == "click"], m)
    time.sleep(0.6)  # > GetDoubleClickTime: the next click must not pair with this one
    m = target.mark()
    inp.click(*center(target.info["edit_rect"]), guard, double=True)
    assert target.wait(lambda evs: [e for e in evs if e["ev"] == "mouse" and e["kind"] == "dblclick"
                                    and e["w"] == "edit"], m)
    assert not key_down(api.VK_LBUTTON)


def test_right_and_middle_buttons_and_cursor_restore(target: TargetApp) -> None:
    guard = focus(target)
    start = api.cursor_pos()
    point = tuple(target.info["blank_point"])
    for button, qt_button in ((MouseButton.RIGHT, 2), (MouseButton.MIDDLE, 4)):
        m = target.mark()
        inp.click(point[0], point[1], guard, button=button, restore_cursor=True)
        assert target.wait(lambda evs, b=qt_button: [e for e in evs if e["ev"] == "mouse" and e["kind"] == "press"
                                                      and e["btn"] == b], m), button
        assert api.cursor_pos() == start
        time.sleep(0.6)


# ----------------------------------------------------------------------------- foreground and guard trips


def test_foreground_routine_incl_a_minimized_target(target: TargetApp, decoy: TargetApp) -> None:
    ok, how = inp.bring_to_foreground(decoy.hwnd)
    assert ok and windows.foreground_window() == decoy.hwnd, how
    ok, how = inp.bring_to_foreground(target.hwnd)
    assert ok and windows.foreground_window() == target.hwnd, how
    ShowWindow(target.hwnd, SW_MINIMIZE)
    deadline = time.monotonic() + 3
    while not windows.is_minimized(target.hwnd) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert windows.is_minimized(target.hwnd)
    ok, how = inp.bring_to_foreground(target.hwnd)
    assert ok, how
    assert not windows.is_minimized(target.hwnd) and windows.foreground_window() == target.hwnd


def test_typing_into_a_background_target_is_refused(target: TargetApp, decoy: TargetApp) -> None:
    guard = focus(target)
    ok, how = inp.bring_to_foreground(decoy.hwnd)
    assert ok, how
    inp.reset_user_input_baseline()
    mt, md = target.mark(), decoy.mark()
    with pytest.raises(inp.ForegroundLost) as info:
        inp.type_text("SHOULD-NOT-APPEAR", guard)
    assert info.value.foreground_hwnd == decoy.hwnd
    time.sleep(0.3)
    assert target.since(mt, "text") == [] and decoy.since(md, "text") == []


def test_point_covered_by_another_program_is_named(target: TargetApp, tmp_path: Path,
                                                   clean_env: dict[str, str]) -> None:
    focus(target)
    sx, sy, sw, sh = target.info["submit_rect"]
    cover = launch(tmp_path, clean_env, "cover", "--ime", "off", "--topmost",
                   "--rect", f"{sx - 20},{sy - 20},{sw + 260},{sh + 160}", title="AutoPress G3 Cover")
    try:
        time.sleep(0.4)
        guard = focus(target)  # the target is active again; the topmost cover stays above it
        m, mc = target.mark(), cover.mark()
        with pytest.raises(inp.PointNotOnTarget) as info:
            inp.click(*center(target.info["submit_rect"]), guard)
        exc = info.value
        assert exc.covering_hwnd == cover.hwnd and not exc.covering_is_own
        assert "AutoPress G3 Cover" in str(exc) and exc.covering_title == "AutoPress G3 Cover"
        time.sleep(0.3)
        assert target.since(m, "submit") == [] and cover.since(mc, "mouse") == []
    finally:
        cover.close()


def test_own_tool_window_over_the_point_gets_the_mini_bar_message(target: TargetApp, qtbot: object) -> None:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QWidget

    guard = focus(target)
    flags = (Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
             | Qt.WindowType.WindowDoesNotAcceptFocus)
    bar = QWidget(None, flags)
    bar.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    bar.setWindowTitle("AutoPress mini bar stand-in")
    bar.show()
    try:
        sx, sy, sw, sh = target.info["submit_rect"]
        SetWindowPos(int(bar.winId()), HWND_TOPMOST, sx - 10, sy - 10, sw + 20, sh + 20, SWP_NOACTIVATE)
        qtbot.wait(300)  # type: ignore[attr-defined]
        assert windows.foreground_window() == target.hwnd
        m = target.mark()
        with pytest.raises(inp.PointNotOnTarget) as info:
            inp.click(*center(target.info["submit_rect"]), guard)
        assert info.value.covering_is_own and info.value.covering_is_minibar
        assert str(info.value).startswith("AutoPress 的迷你控制列擋住了點擊位置")
        assert target.since(m, "submit") == []
    finally:
        bar.close()


def test_same_process_windows_need_allow_same_process(tmp_path: Path, clean_env: dict[str, str]) -> None:
    t = launch(tmp_path, clean_env, "two", "--ime", "off", "--second-window")
    try:
        second = int(t.info["second_hwnd"])
        point = center(t.info["second_button_rect"])
        strict = inp.InjectGuard(t.hwnd, pid=t.pid)
        same = inp.InjectGuard(t.hwnd, pid=t.pid, allow_same_process=True)
        ok, how = inp.bring_to_foreground(second)
        assert ok, how
        time.sleep(0.2)
        inp.reset_user_input_baseline()
        with pytest.raises(inp.ForegroundLost):
            inp.click(*point, strict)
        m = t.mark()
        inp.click(*point, same)  # the foreground window and the click root belong to the target process
        assert t.wait(lambda evs: [e for e in evs if e["ev"] == "second_click"], m)
        ok, how = inp.bring_to_foreground(t.hwnd)
        assert ok, how
        inp.reset_user_input_baseline()
        with pytest.raises(inp.PointNotOnTarget):
            strict.check("click", point)  # the second window is another root window
        same.check("click", point)
    finally:
        t.close()


# ----------------------------------------------------------------------------- release in finally


def test_keys_and_buttons_are_released_when_the_hold_sleep_raises(target: TargetApp) -> None:
    guard = focus(target)
    focus_edit(target, guard)
    with pytest.raises(Boom):
        inp.press_keys([api.VK_SHIFT, VK_A], guard, hold_ms=200, sleep=boom)
    assert not any(key_down(vk) for vk in (*MODIFIERS, VK_A))
    with pytest.raises(Boom):
        inp.type_text("Q", guard, TypingMode.VK, hold_ms=200, close_ime=False, sleep=boom)
    assert not any(key_down(vk) for vk in (*MODIFIERS, VK_Q))
    time.sleep(0.6)
    with pytest.raises(Boom):
        inp.click(*target.info["blank_point"], guard, settle_ms=0, hold_ms=200, sleep=boom)
    assert inp.held_by_us() == []  # the button-up was inserted before Boom propagated
    assert button_released(api.VK_LBUTTON)


def test_clipboard_restored_after_a_stop_during_the_restore_delay(target: TargetApp) -> None:
    guard = focus(target)
    focus_edit(target, guard)
    inp.clear_field(guard)
    clipboard.set_text("AutoPress G3 sentinel")

    def stop_in_restore_wait(seconds: float) -> None:
        if seconds >= 0.2:
            raise Boom

    with pytest.raises(Boom):
        inp.type_text("PASTE-1234", guard, TypingMode.CLIPBOARD, restore_clipboard_ms=500,
                      sleep=stop_in_restore_wait)
    assert target.wait_text("PASTE-1234") == "PASTE-1234"  # the code, never the old clipboard
    assert clipboard.get_text() == "AutoPress G3 sentinel"


def test_ime_restored_after_a_stop_while_typing(target_ime: TargetApp) -> None:
    guard = focus(target_ime)
    focus_edit(target_ime, guard)
    before = inp.ime_state(target_ime.hwnd)
    if before is None or not before["open"]:
        pytest.skip("no open IME in the target on this PC")
    calls: list[float] = []

    def stop_on_third_wait(seconds: float) -> None:  # IME settle, key delay, key delay -> stop
        calls.append(seconds)
        if len(calls) == 3:
            raise Boom

    with pytest.raises(Boom):
        inp.type_text("abcdef", guard, TypingMode.VK, key_delay_ms=30, sleep=stop_on_third_wait)
    assert inp.ime_state(target_ime.hwnd) == before


def test_release_all_modifiers_lets_stuck_modifiers_go(target: TargetApp) -> None:
    guard = focus(target)
    guard.check("stuck")
    # pressed without key-up and NOT tracked - what a killed injector leaves behind (8/10, research)
    inp._send([inp._vk_event(api.VK_LSHIFT, False), inp._vk_event(api.VK_RCONTROL, False)], "stuck")
    time.sleep(0.05)
    assert key_down(api.VK_LSHIFT) and key_down(api.VK_RCONTROL)
    released = inp.release_all_modifiers()
    assert api.VK_LSHIFT in released and api.VK_RCONTROL in released
    time.sleep(0.05)
    assert not any(key_down(vk) for vk in MODIFIERS)


# ----------------------------------------------------------------------------- clipboard, hotkeys, capture


def test_clipboard_snapshot_restore_roundtrip() -> None:
    fmt = int(api.RegisterClipboardFormatW("AutoPress.G3.Test"))
    payload = bytes(range(256)) * 4
    clipboard._open(0)
    try:
        api.EmptyClipboard()
        assert clipboard._set(api.CF_UNICODETEXT, "G3 測試 clip".encode("utf-16-le") + b"\x00\x00")
        assert clipboard._set(fmt, payload)
    finally:
        api.CloseClipboard()
    snap = clipboard.snapshot()
    saved = {f: d for f, _name, d in snap.formats}
    assert saved[fmt][:len(payload)] == payload
    clipboard.set_text("something else")
    assert clipboard.get_text() == "something else"
    clipboard.restore(snap)
    again = {f: d for f, _name, d in clipboard.snapshot().formats}
    for f, data in saved.items():
        assert again.get(f, b"")[:len(data)] == data, f  # GlobalSize may round the size up
    assert clipboard.get_text() == "G3 測試 clip"


def test_hotkey_delivered_while_the_host_window_is_hidden(qtbot: object) -> None:
    """SPEC 11.2: the main window is HIDDEN during runs and owns the hotkeys."""
    from PyQt6.QtWidgets import QWidget

    host = QWidget()
    host.setWindowTitle("AutoPress G3 hidden hotkey host")
    host.show()
    qtbot.wait(200)  # type: ignore[attr-defined]
    host.hide()
    sink = QWidget()
    sink.setWindowTitle("AutoPress G3 key sink")
    sink.setGeometry(420, 420, 320, 120)
    sink.show()
    qtbot.wait(300)  # type: ignore[attr-defined]
    hk = GlobalHotkeys()
    try:
        host_hwnd = int(host.winId())
        hk.attach(host_hwnd)
        assert not api.IsWindowVisible(host_hwnd)
        res = hk.register("stop", "Ctrl+Shift+F24")
        if not res.ok:
            pytest.skip(f"Ctrl+Shift+F24 is not available: {res.message}")
        ok, how = inp.bring_to_foreground(int(sink.winId()))
        assert ok, how
        inp.reset_user_input_baseline()
        guard = inp.InjectGuard(int(sink.winId()))  # the injected Ctrl / Shift go to our own sink
        with qtbot.waitSignal(hk.triggered, timeout=3000) as blocker:  # type: ignore[attr-defined]
            inp.press_keys([api.VK_CONTROL, api.VK_SHIFT, VK_F24], guard)
        assert blocker.args == ["stop"]
    finally:
        hk.unregister_all()
        sink.close()
        host.close()


def test_exclude_from_capture_measured_with_mss(qtbot: object) -> None:
    """SPEC 11.10 measurement: does mss (BitBlt + CAPTUREBLT) omit a WDA_EXCLUDEFROMCAPTURE window?
    Reported as a warning; only the call itself and the measurement's sanity are asserted."""
    import mss
    import numpy as np
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QColor, QPalette
    from PyQt6.QtWidgets import QWidget

    flags = (Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
             | Qt.WindowType.WindowDoesNotAcceptFocus)
    w = QWidget(None, flags)
    w.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    pal = w.palette()
    pal.setColor(QPalette.ColorRole.Window, QColor(255, 0, 255))
    w.setPalette(pal)
    w.setAutoFillBackground(True)
    w.setGeometry(140, 140, 260, 160)
    w.show()
    qtbot.wait(400)  # type: ignore[attr-defined]
    hwnd = int(w.winId())
    x, y, cw, ch = windows.client_rect(hwnd)

    def magenta_share() -> float:
        with mss.MSS() as sct:
            shot = sct.grab({"left": x, "top": y, "width": cw, "height": ch})
        a = np.asarray(shot)[:, :, :3].astype(int)  # BGRA -> BGR
        mask = (a[..., 0] > 247) & (a[..., 1] < 8) & (a[..., 2] > 247)
        return float(mask.mean())

    try:
        before = magenta_share()
        ok = windows.exclude_from_capture(hwnd, True)
        qtbot.wait(400)  # type: ignore[attr-defined]
        excluded = magenta_share()
        windows.exclude_from_capture(hwnd, False)
        qtbot.wait(400)  # type: ignore[attr-defined]
        cleared = magenta_share()
    finally:
        w.close()
    warnings.warn(f"G3 exclude_from_capture with mss: call ok={ok}; magenta share before={before:.2f}, "
                  f"excluded={excluded:.2f}, cleared={cleared:.2f} (excluded near 0 = mss omits the window)",
                  UserWarning, stacklevel=1)
    assert before > 0.9, "the capture did not see the test window (locked screen?)"
    assert ok
