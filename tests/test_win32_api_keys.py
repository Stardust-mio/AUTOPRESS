# OWNED BY G3
"""ctypes layer (structure sizes, prototypes) and key-name mapping (SPEC 8.2 G3)."""

from __future__ import annotations

import ast
import ctypes
from pathlib import Path

import pytest

from autopress.models import KEY_NAMES, normalize_combo, validate_hotkey
from autopress.win32 import api, keys

WIN32_DIR = Path(__file__).resolve().parent.parent / "autopress" / "win32"


# ----------------------------------------------------------------------------- structures


@pytest.mark.parametrize("name", sorted(api.EXPECTED_SIZES))
def test_structure_sizes(name: str) -> None:
    assert ctypes.sizeof(getattr(api, name)) == api.EXPECTED_SIZES[name]


def test_input_is_40_bytes_with_pointer_sized_extra_info() -> None:
    assert ctypes.sizeof(api.INPUT) == 40
    assert ctypes.sizeof(api.ULONG_PTR) == ctypes.sizeof(ctypes.c_void_p) == 8
    assert api.KEYBDINPUT.dwExtraInfo.size == 8 and api.MOUSEINPUT.dwExtraInfo.size == 8


# ----------------------------------------------------------------------------- prototypes


def test_every_prototype_has_argtypes_and_restype() -> None:
    assert len(api.PROTOTYPES) >= 70
    names = [n for n, *_ in api.PROTOTYPES]
    assert len(names) == len(set(names)), "a prototype is declared twice"
    for name, fn, restype, argtypes in api.PROTOTYPES:
        assert fn.argtypes is not None, name
        assert list(fn.argtypes) == argtypes, name
        assert fn.restype is restype, name


def test_pointer_returning_functions_are_not_truncated() -> None:
    """GlobalLock without restype truncated 0x1f500fb9770 -> 0xfb9770 (win32_input.md 10)."""
    for fn in (api.GlobalAlloc, api.GlobalLock, api.GlobalFree, api.GetClipboardData, api.SetClipboardData,
               api.GetForegroundWindow, api.WindowFromPoint, api.GetKeyboardLayout, api.OpenProcess):
        assert fn.restype in (ctypes.c_void_p, ctypes.c_size_t) or ctypes.sizeof(fn.restype) == 8, fn.__name__


def test_window_from_point_takes_point_by_value() -> None:
    assert api.WindowFromPoint.argtypes == [ctypes.wintypes.POINT]
    assert api.MonitorFromPoint.argtypes[0] is ctypes.wintypes.POINT


def test_every_proto_call_in_api_is_registered() -> None:
    """Each ``_proto(...)`` in api.py ended in PROTOTYPES (or MISSING for optional ones)."""
    tree = ast.parse((WIN32_DIR / "api.py").read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_proto"]
    assert len(calls) == len(api.PROTOTYPES) + len(api.MISSING)


def test_no_module_bypasses_the_declared_prototypes() -> None:
    """Only api.py loads DLLs; the other modules never touch raw DLL attributes or windll."""
    for path in sorted(WIN32_DIR.glob("*.py")):
        if path.name == "api.py":
            continue
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                assert node.attr not in ("windll", "WinDLL", "oledll", "cdll"), f"{path.name}: {node.attr}"
                if isinstance(node.value, ast.Attribute) and node.value.attr in (
                        "user32", "kernel32", "advapi32", "dwmapi", "imm32", "shell32", "shcore"):
                    pytest.fail(f"{path.name}:{node.lineno} calls api.{node.value.attr}.{node.attr} directly")


def test_importing_the_package_changes_nothing() -> None:
    """Import-time side effects are forbidden: no DPI calls (awareness stays whatever it was)."""
    import importlib
    import subprocess
    import sys

    code = ("import ctypes, ctypes.wintypes as W\n"
            "u = ctypes.WinDLL('user32'); u.GetThreadDpiAwarenessContext.restype = W.HANDLE\n"
            "u.AreDpiAwarenessContextsEqual.argtypes = [W.HANDLE, W.HANDLE]\n"
            "before = u.AreDpiAwarenessContextsEqual(u.GetThreadDpiAwarenessContext(), W.HANDLE(-1))\n"
            "import autopress.win32.api, autopress.win32.input, autopress.win32.windows, autopress.win32.dpi\n"
            "import autopress.win32.hotkeys, autopress.win32.clipboard, autopress.win32.elevation\n"
            "import autopress.win32.power, autopress.win32.keys\n"
            "after = u.AreDpiAwarenessContextsEqual(u.GetThreadDpiAwarenessContext(), W.HANDLE(-1))\n"
            "print(before, after)\n")
    root = Path(__file__).resolve().parent.parent
    out = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    before, after = out.stdout.split()
    assert before == after == "1", out.stdout  # a fresh python.exe is DPI-unaware and stays so
    importlib.import_module("autopress.win32")


# ----------------------------------------------------------------------------- keys


def test_every_key_name_has_a_vk() -> None:
    vks = {name: keys.vk_for_name(name) for name in KEY_NAMES}
    assert len(set(vks.values())) == len(KEY_NAMES)
    assert vks["Ctrl"] == 0x11 and vks["Shift"] == 0x10 and vks["Alt"] == 0x12 and vks["Win"] == 0x5B
    assert vks["F1"] == 0x70 and vks["F9"] == 0x78 and vks["F24"] == 0x87
    assert vks["A"] == 0x41 and vks["z".upper()] == 0x5A and vks["0"] == 0x30 and vks["9"] == 0x39
    assert vks["Enter"] == 0x0D and vks["Esc"] == 0x1B and vks["Delete"] == 0x2E and vks["PageDown"] == 0x22


@pytest.mark.parametrize("bad", ["ctrl", "a", "F25", "Return", "", "Ctrl+A"])
def test_vk_for_name_rejects_non_canonical_names(bad: str) -> None:
    with pytest.raises(ValueError):
        keys.vk_for_name(bad)


def test_parse_combo_orders_modifiers_first() -> None:
    assert keys.parse_combo("ctrl+a") == [0x11, 0x41]
    assert keys.parse_combo("Shift + Ctrl + Home") == [0x11, 0x10, 0x24]
    assert keys.parse_combo("Enter") == [0x0D]
    for bad in ("Ctrl", "A+B", "Ctrl+Ctrl+A", "Hyper+A", ""):
        with pytest.raises(ValueError):
            keys.parse_combo(bad)


def test_parse_hotkey_sets_norepeat_and_modifiers() -> None:
    assert keys.parse_hotkey("F8") == (keys.MOD_NOREPEAT, 0x77)
    assert keys.parse_hotkey("Ctrl+Shift+F9") == (keys.MOD_NOREPEAT | keys.MOD_CONTROL | keys.MOD_SHIFT, 0x78)
    assert keys.parse_hotkey("alt+p") == (keys.MOD_NOREPEAT | keys.MOD_ALT, 0x50)


@pytest.mark.parametrize("bad", ["Win+F8", "F12", "A", "Shift+A", "nonsense"])
def test_parse_hotkey_uses_validate_hotkey(bad: str) -> None:
    reason = validate_hotkey(bad)
    assert reason
    with pytest.raises(ValueError) as info:
        keys.parse_hotkey(bad)
    assert str(info.value) == reason


def test_combo_from_qt() -> None:
    from PyQt6.QtCore import Qt

    k, m = Qt.Key, Qt.KeyboardModifier

    def combo(key: Qt.Key, *mods: Qt.KeyboardModifier) -> str | None:
        value = 0
        for mod in mods:
            value |= mod.value
        return keys.combo_from_qt(int(key.value), value)

    assert combo(k.Key_F9) == "F9"
    assert combo(k.Key_F9, m.ShiftModifier, m.ControlModifier) == "Ctrl+Shift+F9"
    assert combo(k.Key_A, m.ControlModifier) == "Ctrl+A"
    assert combo(k.Key_Exclam, m.ShiftModifier, m.AltModifier) == "Shift+Alt+1"  # Shift+1 reports "!"
    assert combo(k.Key_Backtab, m.ShiftModifier) == "Shift+Tab"
    assert combo(k.Key_Return) == "Enter" and combo(k.Key_Enter, m.KeypadModifier) == "Enter"
    assert combo(k.Key_P, m.MetaModifier) == "Win+P"
    assert combo(k.Key_F24) == "F24"
    assert combo(k.Key_Control, m.ControlModifier) is None  # modifier-only press
    assert combo(k.Key_Shift, m.ShiftModifier) is None
    assert combo(k.Key_Print) is None and combo(k.Key_Semicolon) is None and combo(k.Key_F25) is None
    # works with the enum objects too
    assert keys.combo_from_qt(k.Key_F8, m.AltModifier) == "Alt+F8"


def test_combo_from_qt_output_is_canonical_for_validation() -> None:
    from PyQt6.QtCore import Qt

    text = keys.combo_from_qt(int(Qt.Key.Key_F8.value), int(Qt.KeyboardModifier.ControlModifier.value))
    assert text == normalize_combo(text) == "Ctrl+F8"
    assert validate_hotkey(text) is None


def test_extended_vks_cover_navigation_keys() -> None:
    for vk in (0x2D, 0x2E, 0x24, 0x23, 0x21, 0x22, 0x25, 0x26, 0x27, 0x28, 0xA3, 0xA5):
        assert vk in keys.EXTENDED_VKS
    assert 0x41 not in keys.EXTENDED_VKS and 0x0D not in keys.EXTENDED_VKS
