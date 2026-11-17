# OWNED BY G3 - replace this stub
"""Key names <-> virtual-key codes. The accepted vocabulary is models.KEY_NAMES and parsing
of combo text is models.parse_combo_names (single source of truth); this module maps names
to VKs and builds RegisterHotKey arguments."""

from __future__ import annotations

__stub__ = True

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


def vk_for_name(name: str) -> int:
    """VK code of a canonical models.KEY_NAMES name ("Ctrl" -> VK_CONTROL 0x11 ... "F9" -> 0x78).
    ValueError for other names."""
    raise NotImplementedError


def parse_combo(text: str) -> list[int]:
    """"Ctrl+A" -> [0x11, 0x41] (modifiers first). ValueError for invalid text."""
    raise NotImplementedError


def parse_hotkey(text: str) -> tuple[int, int]:
    """(MOD_* | MOD_NOREPEAT, vk) for RegisterHotKey. ValueError if models.validate_hotkey
    rejects the combo."""
    raise NotImplementedError


def combo_from_qt(key: int, modifiers: int) -> str | None:
    """Canonical combo text for a Qt key event (``int(event.key())``,
    ``int(event.modifiers().value)``), e.g. "Ctrl+Shift+F9". None for modifier-only presses
    and keys outside models.KEY_NAMES. Used by the hotkey fields of the Settings page."""
    raise NotImplementedError
