# OWNED BY G3
"""GlobalHotkeys on hidden native windows (no input is injected): register / 1409 / unregister,
attach on invalid handles, delivery of a posted WM_HOTKEY through the app-wide native filter
(the offscreen platform uses QEventDispatcherWin32 too), re-attach (SPEC 8.2, T12)."""

from __future__ import annotations

import gc

import pytest

from autopress.models import validate_hotkey
from autopress.win32 import hotkeys
from autopress.win32.hotkeys import ERROR_HOTKEY_ALREADY_REGISTERED, GlobalHotkeys
from autopress.win32.keys import parse_hotkey
from tests.win32_helpers import WM_HOTKEY, PostMessageW, RegisterHotKey, UnregisterHotKey, hidden_window

# unusual combos (F20-F24 are not on keyboards) so nothing real is ever shadowed
COMBO_A, COMBO_B, COMBO_C = "Ctrl+Shift+F24", "Ctrl+Shift+F23", "Ctrl+Shift+F22"


def raw_register(hwnd: int, hk_id: int, combo: str) -> bool:
    mods, vk = parse_hotkey(combo)
    return bool(RegisterHotKey(hwnd, hk_id, mods, vk))


def combo_is_free(combo: str) -> bool:
    """True when nobody holds the combo (registers and immediately unregisters it)."""
    with hidden_window("AutoPress G3 probe") as probe:
        if raw_register(probe, 0x77, combo):
            UnregisterHotKey(probe, 0x77)
            return True
        return False


@pytest.fixture
def hk(qapp: object) -> GlobalHotkeys:
    obj = GlobalHotkeys()
    yield obj
    obj.unregister_all()


def test_not_attached_and_invalid_handles_never_raise(hk: GlobalHotkeys) -> None:
    res = hk.register("stop", COMBO_A)
    assert res.ok is False and res.error == 0 and res.message
    hk.attach(0x7FFFFFF0)  # not a window (like winId() on the offscreen platform)
    res = hk.register("stop", COMBO_A)
    assert res.ok is False and res.error != 0 and "Ctrl+Shift+F24" in res.message
    assert hk.registered() == {}
    hk.attach("not a handle")  # type: ignore[arg-type]
    hk.attach(None)  # type: ignore[arg-type]
    assert hk.hwnd() == 0 and hk.registered() == {}


def test_invalid_combos_report_the_validation_reason(hk: GlobalHotkeys) -> None:
    with hidden_window() as hwnd:
        hk.attach(hwnd)
        for combo in ("Win+F8", "F12", "Shift+A", "nonsense"):
            res = hk.register("stop", combo)
            assert res.ok is False and res.error == 0
            assert res.message == validate_hotkey(combo)
        assert hk.registered() == {}


def test_register_and_unregister(hk: GlobalHotkeys) -> None:
    with hidden_window() as hwnd:
        hk.attach(hwnd)
        res = hk.register("stop", "ctrl + shift + f24")
        assert res.ok and res.error == 0 and res.message == ""
        assert hk.registered() == {"stop": COMBO_A}
        assert not combo_is_free(COMBO_A)  # really registered system-wide
        assert hk.register("stop", COMBO_A).ok  # same combo again: no-op
        hk.unregister("stop")
        assert hk.registered() == {} and combo_is_free(COMBO_A)
        hk.unregister("stop")  # unknown action: no error


def test_1409_when_another_program_holds_the_combo(hk: GlobalHotkeys) -> None:
    with hidden_window() as mine, hidden_window("AutoPress G3 other") as other:
        assert raw_register(other, 0x55, COMBO_B)
        try:
            hk.attach(mine)
            res = hk.register("pause_resume", COMBO_B)
            assert res.ok is False and res.error == ERROR_HOTKEY_ALREADY_REGISTERED == 1409
            assert res.message.startswith(f"快捷鍵 {COMBO_B} 已被其他程式使用")
            assert hk.registered() == {}
        finally:
            UnregisterHotKey(other, 0x55)
        assert hk.register("pause_resume", COMBO_B).ok


def test_one_combo_cannot_serve_two_actions(hk: GlobalHotkeys) -> None:
    with hidden_window() as hwnd:
        hk.attach(hwnd)
        assert hk.register("pause_resume", COMBO_C).ok
        res = hk.register("stop", COMBO_C)
        assert res.ok is False and res.error == 1409 and "其他動作" in res.message
        assert hk.registered() == {"pause_resume": COMBO_C}


def test_replacing_a_combo_and_keeping_it_when_the_new_one_fails(hk: GlobalHotkeys) -> None:
    with hidden_window() as hwnd, hidden_window("AutoPress G3 other") as other:
        hk.attach(hwnd)
        assert hk.register("stop", COMBO_A).ok
        assert hk.register("stop", COMBO_C).ok
        assert hk.registered() == {"stop": COMBO_C} and combo_is_free(COMBO_A)
        assert raw_register(other, 0x56, COMBO_B)
        try:
            res = hk.register("stop", COMBO_B)
            assert res.ok is False and res.error == 1409
            assert hk.registered() == {"stop": COMBO_C} and not combo_is_free(COMBO_C)
        finally:
            UnregisterHotKey(other, 0x56)


def _hotkey_id(hk: GlobalHotkeys, action: str) -> int:
    return hk._active[action][1]


def test_posted_wm_hotkey_triggers_once(hk: GlobalHotkeys, qtbot: object) -> None:
    seen: list[str] = []
    hk.triggered.connect(seen.append)
    with hidden_window() as hwnd:
        hk.attach(hwnd)
        assert hk.register("pause_resume", COMBO_A).ok and hk.register("stop", COMBO_C).ok
        mods, vk = parse_hotkey(COMBO_A)
        with qtbot.waitSignal(hk.triggered, timeout=3000) as blocker:  # type: ignore[attr-defined]
            assert PostMessageW(hwnd, WM_HOTKEY, _hotkey_id(hk, "pause_resume"), (vk << 16) | (mods & 0xFFFF))
        assert blocker.args == ["pause_resume"]
        with qtbot.waitSignal(hk.triggered, timeout=3000) as blocker:  # type: ignore[attr-defined]
            PostMessageW(hwnd, WM_HOTKEY, _hotkey_id(hk, "stop"), 0)
        assert blocker.args == ["stop"]
        PostMessageW(hwnd, WM_HOTKEY, 0xBEEF, 0)  # not ours: ignored
        qtbot.wait(200)  # type: ignore[attr-defined]
        assert seen == ["pause_resume", "stop"]  # each message seen exactly once


def test_signal_is_emitted_from_the_event_loop_not_inside_the_filter(hk: GlobalHotkeys) -> None:
    with hidden_window() as hwnd:
        hk.attach(hwnd)
        assert hk.register("stop", COMBO_A).ok
        seen: list[str] = []
        hk.triggered.connect(seen.append)
        hk._on_hotkey(_hotkey_id(hk, "stop"))  # what the native filter calls
        assert seen == []  # queued: delivered by the event loop
        from PyQt6.QtCore import QCoreApplication

        QCoreApplication.processEvents()
        assert seen == ["stop"]


def test_reattach_moves_every_hotkey(hk: GlobalHotkeys, qtbot: object) -> None:
    with hidden_window() as first, hidden_window("AutoPress G3 second") as second:
        hk.attach(first)
        assert hk.register("stop", COMBO_A).ok and hk.register("pause_resume", COMBO_C).ok
        old_id = _hotkey_id(hk, "stop")
        hk.attach(second)
        assert hk.hwnd() == second
        assert hk.registered() == {"stop": COMBO_A, "pause_resume": COMBO_C}
        assert not combo_is_free(COMBO_A)
        seen: list[str] = []
        hk.triggered.connect(seen.append)
        PostMessageW(first, WM_HOTKEY, old_id, 0)  # the old window no longer routes to us
        with qtbot.waitSignal(hk.triggered, timeout=3000):  # type: ignore[attr-defined]
            PostMessageW(second, WM_HOTKEY, _hotkey_id(hk, "stop"), 0)
        qtbot.wait(100)  # type: ignore[attr-defined]
        assert seen == ["stop"]
        hk.unregister_all()
        assert hk.registered() == {} and combo_is_free(COMBO_A) and combo_is_free(COMBO_C)


def test_a_dropped_object_receives_nothing(qapp: object, qtbot: object) -> None:
    with hidden_window() as hwnd:
        obj = GlobalHotkeys()
        obj.attach(hwnd)
        assert obj.register("stop", COMBO_B).ok
        hk_id = _hotkey_id(obj, "stop")
        obj.unregister_all()
        assert obj.register("stop", COMBO_B).ok
        hk_id = _hotkey_id(obj, "stop")
        del obj
        gc.collect()
        PostMessageW(hwnd, WM_HOTKEY, hk_id, 0)
        qtbot.wait(100)  # type: ignore[attr-defined]  - no crash, nothing to deliver to
    # the window is destroyed with the hidden_window context: Windows frees its hotkeys
    assert combo_is_free(COMBO_B)


def test_one_native_filter_per_process(qapp: object) -> None:
    with hidden_window() as hwnd:
        a, b = GlobalHotkeys(), GlobalHotkeys()
        a.attach(hwnd)
        b.attach(hwnd)
        assert hotkeys._filter is not None
        first = hotkeys._filter
        assert a.register("stop", COMBO_A).ok and b.register("stop", COMBO_C).ok
        assert _hotkey_id(a, "stop") != _hotkey_id(b, "stop")  # ids never collide on one window
        assert hotkeys._filter is first
        a.unregister_all()
        b.unregister_all()
