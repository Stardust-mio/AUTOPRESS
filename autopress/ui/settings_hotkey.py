# OWNED BY G5
"""Hotkey capture field of the settings page (SPEC 6.4.5): press the new combination.

The field shows the current combo; when focused, the next key press (with Ctrl / Alt / Shift)
becomes the candidate, normalised with ``models.normalize_combo`` and checked with
``models.validate_hotkey`` (no Win, no F12, non-F keys need Ctrl or Alt). Esc cancels, Tab /
Shift+Tab move the focus as usual. A valid combo emits ``comboChanged(combo)``; the page then
tests it against other programs (temporary GlobalHotkeys.register + unregister).
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFocusEvent, QKeyEvent
from PyQt6.QtWidgets import QLineEdit, QWidget

from ..i18n import tr
from ..models import normalize_combo, validate_hotkey
from . import theme

_NAMED = {
    Qt.Key.Key_Return: "Enter", Qt.Key.Key_Enter: "Enter", Qt.Key.Key_Escape: "Esc", Qt.Key.Key_Tab: "Tab",
    Qt.Key.Key_Space: "Space", Qt.Key.Key_Backspace: "Backspace", Qt.Key.Key_Delete: "Delete",
    Qt.Key.Key_Insert: "Insert", Qt.Key.Key_Home: "Home", Qt.Key.Key_End: "End", Qt.Key.Key_PageUp: "PageUp",
    Qt.Key.Key_PageDown: "PageDown", Qt.Key.Key_Up: "Up", Qt.Key.Key_Down: "Down", Qt.Key.Key_Left: "Left",
    Qt.Key.Key_Right: "Right",
}
_MODIFIER_KEYS = {Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta, Qt.Key.Key_AltGr,
                  Qt.Key.Key_CapsLock, Qt.Key.Key_unknown}


def key_name(key: int) -> str | None:
    """models.KEY_NAMES spelling of a Qt key (letters, digits, F1-F24, named keys) or None."""
    try:
        k = Qt.Key(key)
    except ValueError:
        return None
    if k in _NAMED:
        return _NAMED[k]
    v = int(k)
    if int(Qt.Key.Key_A) <= v <= int(Qt.Key.Key_Z):
        return chr(v)
    if int(Qt.Key.Key_0) <= v <= int(Qt.Key.Key_9):
        return chr(v)
    if int(Qt.Key.Key_F1) <= v <= int(Qt.Key.Key_F24):
        return f"F{v - int(Qt.Key.Key_F1) + 1}"
    return None


def combo_from_event(key: int, modifiers: Qt.KeyboardModifier) -> str | None:
    """"Ctrl+Shift+K" style combo for a key press, or None (modifier only / unsupported key)."""
    if key in _MODIFIER_KEYS:
        return None
    name = key_name(key)
    if name is None:
        return None
    parts = []
    if modifiers & Qt.KeyboardModifier.ControlModifier:
        parts.append("Ctrl")
    if modifiers & Qt.KeyboardModifier.ShiftModifier:
        parts.append("Shift")
    if modifiers & Qt.KeyboardModifier.AltModifier:
        parts.append("Alt")
    if modifiers & Qt.KeyboardModifier.MetaModifier:
        parts.append("Win")
    parts.append(name)
    try:
        return normalize_combo("+".join(parts))
    except ValueError:
        return None


class HotkeyEdit(QLineEdit):
    """Read-only line edit that captures one key combination.

    ``comboChanged(str)`` - a valid new combo; ``rejected(str)`` - a localized reason why the
    pressed combination cannot be used (shown by the page)."""

    comboChanged = pyqtSignal(str)
    rejected = pyqtSignal(str)

    def __init__(self, combo: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._combo = combo
        self.setReadOnly(True)
        self.setText(combo)
        self.setFixedHeight(theme.CONTROL_H)
        self.setFixedWidth(160)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.setToolTip(tr("點一下，再按下新的組合鍵（Esc 取消）", "Click, then press the new key combination (Esc cancels)"))

    def combo(self) -> str:
        return self._combo

    def setCombo(self, combo: str) -> None:
        self._combo = combo
        if not self.hasFocus():
            self.setText(combo)
        else:
            self.setPlaceholderText(combo)

    def focusInEvent(self, event: QFocusEvent | None) -> None:
        super().focusInEvent(event)
        self.setPlaceholderText(tr("按下新的組合鍵…", "Press the new keys…"))
        self.setText("")

    def focusOutEvent(self, event: QFocusEvent | None) -> None:
        super().focusOutEvent(event)
        self.setText(self._combo)

    def keyPressEvent(self, event: QKeyEvent | None) -> None:
        if event is None:
            return
        key = event.key()
        mods = event.modifiers()
        plain = not (mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier))
        if key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab) and plain:
            super().keyPressEvent(event)  # keyboard navigation
            return
        if key == Qt.Key.Key_Escape and plain:
            self.clearFocus()
            return
        if key in _MODIFIER_KEYS:
            held = [n for flag, n in ((Qt.KeyboardModifier.ControlModifier, "Ctrl"),
                                      (Qt.KeyboardModifier.ShiftModifier, "Shift"),
                                      (Qt.KeyboardModifier.AltModifier, "Alt")) if mods & flag]
            self.setText("+".join(held) + "+…" if held else "")
            return
        combo = combo_from_event(key, mods)
        if combo is None:
            self.setText("")
            self.rejected.emit(tr("不支援這個按鍵，請改用 F1–F24 或 Ctrl／Alt 組合鍵。",
                                  "This key is not supported; use F1-F24 or a Ctrl / Alt combination."))
            return
        reason = validate_hotkey(combo)
        if reason:
            self.setText("")
            self.rejected.emit(reason)
            return
        self.setText(combo)
        if combo != self._combo:
            self.comboChanged.emit(combo)
        self.clearFocus()
