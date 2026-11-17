# OWNED BY G5
"""Private part of ui.settings_page: the settings card (icon + title, rows with a title, a muted
hint and the control on the right, dividers between rows) and the spin-box factory."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QSpinBox, QVBoxLayout, QWidget

from . import theme
from .widgets import Card, Divider, icon_label, label

__all__ = ["Section", "spin_box"]


def spin_box(lo: int, hi: int, suffix: str = "", special: str = "", step: int = 1) -> QSpinBox:
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setKeyboardTracking(False)
    s.setAccelerated(True)
    s.setFixedWidth(130)
    if suffix:
        s.setSuffix(suffix)
    if special:
        s.setSpecialValueText(special)
    return s


class Section(Card):
    """A settings card: icon + title header, then rows separated by dividers."""

    def __init__(self, icon_name: str, title: str, parent: QWidget | None = None) -> None:
        super().__init__(True, (theme.SP[4], theme.SP[3], theme.SP[4], theme.SP[2]), 0, parent)
        head = QHBoxLayout()
        head.setSpacing(theme.SP[2])
        head.addWidget(icon_label(icon_name, "accent_text", 18), 0, Qt.AlignmentFlag.AlignVCenter)
        self.title = label(title, "title")
        head.addWidget(self.title, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addStretch(1)
        self.layout().addLayout(head)
        self.layout().addSpacing(theme.SP[2])
        self._rows = 0

    def add_row(self, title: str, field: QWidget | None, hint: str = "") -> tuple[QWidget, QLabel]:
        """Title + muted hint on the left, the control on the right. Returns (row, hint label)."""
        if self._rows:
            self.layout().addWidget(Divider(parent=self))
        self._rows += 1
        row = QWidget(self)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, theme.SP[2] + 2, 0, theme.SP[2] + 2)
        lay.setSpacing(theme.SP[4])
        col = QVBoxLayout()
        col.setSpacing(2)
        t = label(title, "body")
        t.setWordWrap(True)
        col.addWidget(t)
        h = label(hint, "muted")
        h.setWordWrap(True)
        h.setVisible(bool(hint))
        col.addWidget(h)
        lay.addLayout(col, 1)
        if field is not None:
            lay.addWidget(field, 0, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
            if isinstance(field, QWidget) and not field.accessibleName():
                field.setAccessibleName(title)
            t.setBuddy(field)
        self.layout().addWidget(row)
        return row, h

    def add_widget(self, w: QWidget) -> None:
        if self._rows:
            self.layout().addWidget(Divider(parent=self))
        self._rows += 1
        self.layout().addWidget(w)
