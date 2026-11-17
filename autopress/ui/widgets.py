# OWNED BY G5 - replace this stub
"""Reusable themed widgets (ux.md section 6 component table; prototype.py shows the look).

Pages (G5/G6/G7) build their UI from these helpers so the look stays consistent. Styling is
QSS-driven through dynamic properties: buttons ``variant`` = primary | secondary | ghost |
danger; labels ``role`` = display | title | body | secondary | muted | caption | mono | error.
Before G5 replaces this stub, tests/ui_fallback.py provides plain-Qt stand-ins.
"""

from __future__ import annotations

from collections.abc import Sequence

from PyQt6.QtCore import QRectF, pyqtSignal
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import QAbstractButton, QComboBox, QFrame, QLabel, QLineEdit, QPushButton, QToolButton, QWidget

from ..models import CodeStatus

__stub__ = True


def label(text: str = "", role: str = "body") -> QLabel:
    raise NotImplementedError


def push_button(text: str, variant: str = "secondary", icon_name: str | None = None) -> QPushButton:
    """Height CONTROL_H, radius 8; primary = accent_fill + bold."""
    raise NotImplementedError


def icon_button(icon_name: str, tooltip: str, variant: str = "ghost") -> QToolButton:
    """32x32 icon-only button; tooltip and accessibleName = ``tooltip``."""
    raise NotImplementedError


def section_header(title: str, subtitle: str = "", actions: Sequence[QWidget] = ()) -> QWidget:
    """Page header: display title (+ muted subtitle) on the left, ``actions`` on the right."""
    raise NotImplementedError


def form_row(label_text: str, field: QWidget, hint: str = "") -> QWidget:
    """Label above/left of ``field`` with an optional muted hint line below."""
    raise NotImplementedError


class Switch(QAbstractButton):
    """34x20 pill toggle (checkable; use ``toggled(bool)``); keyboard: Space toggles."""

    def __init__(self, checked: bool = False, parent: QWidget | None = None) -> None:
        raise NotImplementedError


class SegmentedControl(QWidget):
    currentChanged = pyqtSignal(int)

    def __init__(self, items: Sequence[str] = (), checked: int = 0, parent: QWidget | None = None) -> None:
        raise NotImplementedError

    def currentIndex(self) -> int:
        raise NotImplementedError

    def setCurrentIndex(self, index: int) -> None:
        raise NotImplementedError

    def setItems(self, items: Sequence[str]) -> None:
        raise NotImplementedError


class SearchField(QLineEdit):
    """Height 32 with a painted search icon and a clear button."""

    def __init__(self, placeholder: str = "", parent: QWidget | None = None) -> None:
        raise NotImplementedError


class ChevronCombo(QComboBox):
    """QComboBox with a painted chevron (QSS ``combobox-popup: 0`` keeps the popup below)."""


def combo(items: Sequence[str] = (), width: int | None = None) -> ChevronCombo:
    raise NotImplementedError


class Card(QFrame):
    """surface fill, 1 px border, radius 12, CARD_MARGINS; ``self.layout()`` is a QVBoxLayout
    (or QHBoxLayout when not vertical)."""

    def __init__(self, vertical: bool = True, margins: tuple[int, int, int, int] | None = None,
                 spacing: int = 8, parent: QWidget | None = None) -> None:
        raise NotImplementedError


class Banner(QFrame):
    """Soft tone fill + 1 px tone border, icon, text, optional ghost action and close button."""

    actionClicked = pyqtSignal()
    closed = pyqtSignal()

    def __init__(self, tone: str = "warning", text: str = "", action_text: str = "",
                 closable: bool = True, parent: QWidget | None = None) -> None:
        raise NotImplementedError

    def setText(self, text: str) -> None:
        raise NotImplementedError

    def setTone(self, tone: str) -> None:
        raise NotImplementedError


class EmptyState(QWidget):
    """Dashed art with an icon, title, hint, action buttons and an optional keycap tip
    (e.g. tip_keys=["Ctrl", "V"], tip_text="貼上序號")."""

    def __init__(self, icon_name: str, title: str, hint: str = "", actions: Sequence[QAbstractButton] = (),
                 tip_keys: Sequence[str] = (), tip_text: str = "", parent: QWidget | None = None) -> None:
        raise NotImplementedError


class Keycap(QLabel):
    """Height 20, radius 4, 2 px bottom border, small bold text (e.g. "F8")."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        raise NotImplementedError


def status_chip_width(status: CodeStatus, text: str | None = None) -> int:
    raise NotImplementedError


def paint_status_chip(painter: QPainter, rect: QRectF, status: CodeStatus, text: str | None = None) -> float:
    """Paint a chip (h22 pill, soft fill, dot/ring/dash glyph from status.glyph, bold 12 px
    text = ``text`` or status.label()) at the left of ``rect``, vertically centred, for item
    delegates. Restores the painter state. Returns the painted width."""
    raise NotImplementedError


class StatusChip(QWidget):
    def __init__(self, status: CodeStatus = CodeStatus.PENDING, text: str | None = None,
                 parent: QWidget | None = None) -> None:
        raise NotImplementedError

    def setStatus(self, status: CodeStatus, text: str | None = None) -> None:
        raise NotImplementedError


class ProgressRing(QWidget):
    """Ring of ``size`` px, 4 px round-cap stroke; centre text "done/total"."""

    def __init__(self, size: int = 40, parent: QWidget | None = None) -> None:
        raise NotImplementedError

    def setProgress(self, done: int, total: int) -> None:
        raise NotImplementedError

    def setTone(self, tone: str) -> None:
        raise NotImplementedError


class Spinner(QWidget):
    """Busy indicator for loading states (OCR running...)."""

    def __init__(self, size: int = 20, parent: QWidget | None = None) -> None:
        raise NotImplementedError

    def start(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError


class Divider(QFrame):
    def __init__(self, vertical: bool = False, parent: QWidget | None = None) -> None:
        raise NotImplementedError


class ElidedLabel(QLabel):
    """Single-line label that elides with "…" instead of widening its parent."""


def confirm(parent: QWidget | None, title: str, text: str, ok_text: str | None = None,
            cancel_text: str | None = None, danger: bool = False) -> bool:
    """Themed modal question; True when confirmed. Default button = cancel when ``danger``.
    Always pass a parent (the main window, or the mini bar during runs); None only before the
    main window exists (first-run dialogs)."""
    raise NotImplementedError


def message(parent: QWidget | None, title: str, text: str, kind: str = "info") -> None:
    """Themed modal message (kind: info | success | warning | error); parent rule as confirm."""
    raise NotImplementedError
