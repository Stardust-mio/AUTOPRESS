# OWNED BY G3
"""Key names <-> virtual-key codes. The accepted vocabulary is models.KEY_NAMES and parsing
of combo text is models.parse_combo_names (single source of truth); this module maps names
to VKs and builds RegisterHotKey arguments. Pure Python (no Win32 calls)."""

from __future__ import annotations

from ..models import KEY_NAMES, format_combo, parse_combo_names, validate_hotkey

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

EXTENDED_VKS: frozenset[int] = frozenset({
    0xA5, 0xA3, 0x2D, 0x2E, 0x24, 0x23, 0x21, 0x22, 0x25, 0x26, 0x27, 0x28, 0x6F, 0x90, 0x2C,
})
"""Keys that need KEYEVENTF_EXTENDEDKEY (RAlt, RCtrl, Insert, Delete, Home, End, PgUp, PgDn,
arrows, Divide, NumLock, PrintScreen) - MapVirtualKeyEx does not report them (win32_input.md 3)."""

_NAME_TO_VK: dict[str, int] = {
    "Ctrl": 0x11, "Shift": 0x10, "Alt": 0x12, "Win": 0x5B,
    "Enter": 0x0D, "Esc": 0x1B, "Tab": 0x09, "Space": 0x20, "Backspace": 0x08, "Delete": 0x2E,
    "Insert": 0x2D, "Home": 0x24, "End": 0x23, "PageUp": 0x21, "PageDown": 0x22,
    "Up": 0x26, "Down": 0x28, "Left": 0x25, "Right": 0x27,
    **{chr(c): c for c in range(ord("A"), ord("Z") + 1)},
    **{str(d): 0x30 + d for d in range(10)},
    **{f"F{i}": 0x6F + i for i in range(1, 25)},  # F1 = 0x70 ... F24 = 0x87
}
_MOD_BITS: dict[str, int] = {"Ctrl": MOD_CONTROL, "Shift": MOD_SHIFT, "Alt": MOD_ALT, "Win": MOD_WIN}

# Qt key codes (Qt.Key) -> canonical names; letters / digits / F-keys are computed below.
_QT_NAMED: dict[int, str] = {
    0x01000000: "Esc", 0x01000001: "Tab", 0x01000002: "Tab",  # Key_Backtab = Shift+Tab
    0x01000003: "Backspace", 0x01000004: "Enter", 0x01000005: "Enter",  # Return, keypad Enter
    0x01000006: "Insert", 0x01000007: "Delete", 0x01000010: "Home", 0x01000011: "End",
    0x01000012: "Left", 0x01000013: "Up", 0x01000014: "Right", 0x01000015: "Down",
    0x01000016: "PageUp", 0x01000017: "PageDown", 0x20: "Space",
}
_QT_MODIFIER_KEYS: frozenset[int] = frozenset({
    0x01000020, 0x01000021, 0x01000022, 0x01000023,  # Shift, Control, Meta, Alt
    0x01001103, 0x01000024, 0x01000025, 0x01000026,  # AltGr, CapsLock, NumLock, ScrollLock
    0x01000053, 0x01000054, 0x01000055,  # Super_L, Super_R, Menu
})
_QT_KEY_F1 = 0x01000030
# Shift + digit reports the shifted symbol on the US / zh-TW layout ("!" for Shift+1).
_QT_SHIFTED_DIGITS: dict[int, str] = {0x21: "1", 0x40: "2", 0x23: "3", 0x24: "4", 0x25: "5", 0x5E: "6",
                                      0x26: "7", 0x2A: "8", 0x28: "9", 0x29: "0"}
_QT_SHIFT, _QT_CTRL, _QT_ALT, _QT_META = 0x02000000, 0x04000000, 0x08000000, 0x10000000


def vk_for_name(name: str) -> int:
    """VK code of a canonical models.KEY_NAMES name ("Ctrl" -> VK_CONTROL 0x11 ... "F9" -> 0x78).
    ValueError for other names."""
    vk = _NAME_TO_VK.get(name) if name in KEY_NAMES else None
    if vk is None:
        raise ValueError(f"unknown key name {name!r}")
    return vk


def parse_combo(text: str) -> list[int]:
    """"Ctrl+A" -> [0x11, 0x41] (modifiers first). ValueError for invalid text."""
    return [vk_for_name(n) for n in parse_combo_names(text)]


def parse_hotkey(text: str) -> tuple[int, int]:
    """(MOD_* | MOD_NOREPEAT, vk) for RegisterHotKey. ValueError if models.validate_hotkey
    rejects the combo (the message is the localized reason)."""
    reason = validate_hotkey(text)
    if reason is not None:
        raise ValueError(reason)
    names = parse_combo_names(text)
    mods = MOD_NOREPEAT
    for n in names[:-1]:
        mods |= _MOD_BITS[n]
    return mods, vk_for_name(names[-1])


def _qt_key_name(key: int, shift: bool) -> str | None:
    if key in _QT_NAMED:
        return _QT_NAMED[key]
    if ord("A") <= key <= ord("Z") or ord("0") <= key <= ord("9"):
        return chr(key)
    if ord("a") <= key <= ord("z"):
        return chr(key).upper()
    if _QT_KEY_F1 <= key < _QT_KEY_F1 + 24:
        return f"F{key - _QT_KEY_F1 + 1}"
    if shift and key in _QT_SHIFTED_DIGITS:
        return _QT_SHIFTED_DIGITS[key]
    return None


def combo_from_qt(key: int, modifiers: int) -> str | None:
    """Canonical combo text for a Qt key event (``int(event.key())``,
    ``int(event.modifiers().value)``), e.g. "Ctrl+Shift+F9". None for modifier-only presses
    and keys outside models.KEY_NAMES. Used by the hotkey fields of the Settings page."""
    key = int(getattr(key, "value", key))
    mods = int(getattr(modifiers, "value", modifiers))
    if key in _QT_MODIFIER_KEYS:
        return None
    name = _qt_key_name(key, bool(mods & _QT_SHIFT))
    if name is None:
        return None
    names = [n for n, bit in (("Ctrl", _QT_CTRL), ("Shift", _QT_SHIFT), ("Alt", _QT_ALT), ("Win", _QT_META))
             if mods & bit]
    try:
        return format_combo(parse_combo_names("+".join([*names, name])))
    except ValueError:
        return None
