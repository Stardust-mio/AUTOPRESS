# OWNED BY G5
"""Reusable themed widgets (ux.md section 6 component table; prototype.py shows the look).

Pages (G5/G6/G7) build their UI from these helpers so the look stays consistent. Styling is
QSS-driven through dynamic properties: buttons ``variant`` = primary | secondary | ghost |
danger; labels ``role`` = display | title | body | secondary | muted | caption | mono | error
(more roles in theme.py). Custom-painted widgets read the theme colours at paint time.

Compatibility with the plain-Qt stand-ins of tests/ui_fallback.py (other groups coded against
them): ``Banner.text()``, ``StatusChip.status`` / ``.text``, ``ProgressRing.done`` / ``.total``
/ ``.tone`` and ``Spinner.running`` exist here too. ``confirm`` / ``message`` live in
widgets_dialogs.py; on the headless ``offscreen`` platform (tests) nobody can answer a modal
dialog, so ``confirm`` returns True and ``message`` returns at once, exactly like the stand-ins.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QFontMetrics, QKeyEvent, QPainter, QPaintEvent, QPen, QResizeEvent
from PyQt6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import icons, theme
from .widgets_status import ProgressRing, Spinner, StatusChip, paint_status_chip, status_chip_width

__all__ = [
    "Banner", "Card", "ChevronCombo", "Divider", "ElidedLabel", "EmptyState", "Keycap", "ProgressRing",
    "SearchField", "SegmentedControl", "Spinner", "StatusChip", "Switch", "combo", "confirm", "form_row",
    "icon_button", "icon_label", "label", "message", "paint_status_chip", "push_button", "section_header",
    "keep_quoted", "SeparatedLabel", "status_chip_width", "tool_button",
]

_ICON_TOKEN = {"primary": "on_accent", "danger": "error_text", "ghost": "text_secondary", "secondary": "text_secondary"}


def _repolish(w: QWidget) -> None:
    style = w.style()
    if style is not None:
        style.unpolish(w)
        style.polish(w)
    w.update()


WORD_JOINER = "\u2060"
_QUOTED = re.compile("「([^「」\n]{2,12})」")


def keep_quoted(text: str) -> str:
    """``text`` with every short 「quoted term」 (a button, step or field name) kept on one line:
    invisible word joiners (U+2060) between its characters, so a narrow word-wrapped label breaks
    before or after 「模擬鍵入」, never inside it. Terms over 12 characters stay breakable (they
    might not fit a narrow line at all)."""
    return _QUOTED.sub(lambda m: "「" + WORD_JOINER.join(m.group(1)) + "」", text)


def label(text: str = "", role: str = "body") -> QLabel:
    lb = QLabel(text)
    lb.setProperty("role", role)
    if role in ("display", "title", "caption", "keycap"):
        lb.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
    return lb


def push_button(text: str, variant: str = "secondary", icon_name: str | None = None) -> QPushButton:
    """Height CONTROL_H, radius 8; primary = accent_fill + bold."""
    b = QPushButton(text)
    b.setProperty("variant", variant)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setFixedHeight(theme.CONTROL_H)
    if icon_name:
        icons.bind(b, icon_name, _ICON_TOKEN.get(variant, "text_secondary"), 16)
    return b


def icon_button(icon_name: str, tooltip: str, variant: str = "ghost") -> QToolButton:
    """32x32 icon-only button; tooltip and accessibleName = ``tooltip``."""
    b = QToolButton()
    b.setProperty("variant", variant)
    b.setToolTip(tooltip)
    b.setAccessibleName(tooltip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setProperty("iconOnly", True)
    b.setFixedSize(theme.CONTROL_H, theme.CONTROL_H)
    b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
    icons.bind(b, icon_name, _ICON_TOKEN.get(variant, "text_secondary"), 16)
    return b


def tool_button(icon_name: str, text: str, variant: str = "secondary") -> QToolButton:
    """Text + icon tool button in the prototype style (toolbars, bulk bars). Extra helper."""
    b = QToolButton()
    b.setProperty("variant", variant)
    b.setText(text)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setFixedHeight(theme.CONTROL_H)
    b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    icons.bind(b, icon_name, _ICON_TOKEN.get(variant, "text_secondary"), 16)
    return b


def icon_label(icon_name: str, color_token: str = "text_secondary", size: int = 16) -> QLabel:
    """A fixed-size label showing a themed icon. Extra helper."""
    lb = QLabel()
    lb.setFixedSize(size, size)
    icons.bind(lb, icon_name, color_token, size)
    return lb


def section_header(title: str, subtitle: str = "", actions: Sequence[QWidget] = ()) -> QWidget:
    """Page header: display title (+ muted subtitle) on the left, ``actions`` on the right."""
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(theme.SP[2])
    col = QVBoxLayout()
    col.setSpacing(2)
    t = label(title, "display")
    t.setObjectName("SectionTitle")
    col.addWidget(t)
    if subtitle:
        s = label(subtitle, "muted")
        s.setObjectName("SectionSubtitle")
        col.addWidget(s)
    lay.addLayout(col)
    lay.addStretch(1)
    for a in actions:
        lay.addWidget(a, 0, Qt.AlignmentFlag.AlignVCenter)
    return box


def form_row(label_text: str, field: QWidget, hint: str = "") -> QWidget:
    """Label above/left of ``field`` with an optional muted hint line below."""
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(theme.SP[1] + 2)
    lb = label(label_text, "secondary")
    lb.setBuddy(field)
    lay.addWidget(lb)
    lay.addWidget(field)
    if hint:
        h = label(hint, "muted")
        h.setWordWrap(True)
        lay.addWidget(h)
    return box


class Switch(QAbstractButton):
    """34x20 pill toggle (checkable; use ``toggled(bool)``); keyboard: Space toggles."""

    def __init__(self, checked: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:
        return QSize(40, theme.CONTROL_H)  # 34x20 pill inside a 32 px tall click target (SPEC 6.5)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, _event: QPaintEvent | None) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF((self.width() - 34) / 2 + 0.5, (self.height() - 20) / 2 + 0.5, 33, 19)
        on = self.isChecked()
        enabled = self.isEnabled()
        if self.hasFocus():
            p.setPen(QPen(theme.color("accent"), 1.6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(-1.5, -1.5, 1.5, 1.5), 11, 11)
        p.setPen(Qt.PenStyle.NoPen if on else QPen(theme.color("border_strong"), 1))
        fill = "accent_fill" if on else "surface_inset"
        if not enabled:
            fill = "border_strong" if on else "surface_inset"
        p.setBrush(theme.color(fill))
        p.drawRoundedRect(r, 9.5, 9.5)
        p.setPen(Qt.PenStyle.NoPen)
        knob = "#FFFFFF" if on else "text_muted"
        if not enabled:
            knob = "text_disabled"
        p.setBrush(theme.color(knob))
        d = 14
        x = r.right() - d - 3 if on else r.left() + 3
        p.drawEllipse(QRectF(x, r.top() + 2.5, d, d))
        p.end()


class SegmentedControl(QWidget):
    currentChanged = pyqtSignal(int)

    def __init__(self, items: Sequence[str] = (), checked: int = 0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._frame = QFrame(self)
        self._frame.setProperty("frameRole", "segmented")
        outer.addWidget(self._frame)
        self._lay = QHBoxLayout(self._frame)
        self._lay.setContentsMargins(3, 3, 3, 3)
        self._lay.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._group.idClicked.connect(self._clicked)
        self._index = -1
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setItems(items)
        self.setCurrentIndex(checked)

    def _clicked(self, index: int) -> None:
        if index != self._index:
            self._index = index
            self.currentChanged.emit(index)

    def buttons(self) -> list[QPushButton]:
        """The segment buttons (extra, for tests and accessibility names)."""
        return [b for b in self._group.buttons() if isinstance(b, QPushButton)]

    def currentIndex(self) -> int:
        return self._index

    def setCurrentIndex(self, index: int) -> None:
        b = self._group.button(index)
        if b is None:
            return
        if not b.isChecked():
            b.setChecked(True)
        if index != self._index:
            self._index = index
            self.currentChanged.emit(index)

    def setItems(self, items: Sequence[str]) -> None:
        """Replace the segment texts. With the same count only the texts change (selection and
        focus kept, no signal) - e.g. counts in the labels ("全部 24")."""
        items = list(items)
        existing = sorted(self._group.buttons(), key=self._group.id)
        if len(existing) == len(items) and existing:
            for b, text in zip(existing, items):
                b.setText(text)
            return
        for b in existing:
            self._group.removeButton(b)
            self._lay.removeWidget(b)
            b.deleteLater()
        for i, text in enumerate(items):
            b = QPushButton(text, self._frame)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setAutoDefault(False)
            self._group.addButton(b, i)
            self._lay.addWidget(b)
        old = self._index
        self._index = -1
        if items:
            target = old if 0 <= old < len(items) else 0
            btn = self._group.button(target)
            if btn is not None:
                btn.setChecked(True)
                self._index = target
                if target != old:
                    self.currentChanged.emit(target)

    def keyPressEvent(self, event: QKeyEvent | None) -> None:
        if event is not None and event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            n = len(self._group.buttons())
            if n:
                step = -1 if event.key() == Qt.Key.Key_Left else 1
                new = (max(self._index, 0) + step) % n
                self.setCurrentIndex(new)
                b = self._group.button(new)
                if b is not None:
                    b.setFocus()
                return
        super().keyPressEvent(event)


class SearchField(QLineEdit):
    """Height 32 with a painted search icon and a clear button."""

    def __init__(self, placeholder: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setAccessibleName(placeholder)
        self.setClearButtonEnabled(True)
        self.setTextMargins(22, 0, 0, 0)
        self.setFixedHeight(theme.CONTROL_H)

    def paintEvent(self, event: QPaintEvent | None) -> None:
        super().paintEvent(event)
        p = QPainter(self)
        p.drawPixmap(QPointF(10, (self.height() - 16) / 2), icons.icon_pixmap("search", "text_muted", 16))
        p.end()


class ChevronCombo(QComboBox):
    """QComboBox with a painted chevron (QSS ``combobox-popup: 0`` keeps the popup below).
    The chevron is the theme's QSS ``::down-arrow`` image, shared by every QComboBox. The size
    hint gets 8 px extra: with the QSS box model the longest item otherwise fits to the pixel and
    the label drawing (1 px inset per side) cuts its last letter (measured at 150 %)."""

    _EXTRA_W = 8

    def sizeHint(self) -> QSize:
        sh = super().sizeHint()
        return QSize(sh.width() + self._EXTRA_W, sh.height())

    def minimumSizeHint(self) -> QSize:
        sh = super().minimumSizeHint()
        return QSize(sh.width() + self._EXTRA_W, sh.height())


def combo(items: Sequence[str] = (), width: int | None = None) -> ChevronCombo:
    c = ChevronCombo()
    c.addItems([str(i) for i in items])
    c.setFixedHeight(theme.CONTROL_H)
    if width:
        c.setFixedWidth(int(width))
    return c


class Card(QFrame):
    """surface fill, 1 px border, radius 12, CARD_MARGINS; ``self.layout()`` is a QVBoxLayout
    (or QHBoxLayout when not vertical)."""

    def __init__(self, vertical: bool = True, margins: tuple[int, int, int, int] | None = None,
                 spacing: int = 8, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("frameRole", "card")
        lay = QVBoxLayout(self) if vertical else QHBoxLayout(self)
        lay.setContentsMargins(*(margins or theme.CARD_MARGINS))
        lay.setSpacing(spacing)


_BANNER_ICON = {"warning": "alert", "error": "alert", "success": "check", "info": "info", "accent": "info",
                "neutral": "info", "violet": "info", "orange": "alert"}


class Banner(QFrame):
    """Soft tone fill + 1 px tone border, icon, text, optional ghost action and close button."""

    actionClicked = pyqtSignal()
    closed = pyqtSignal()

    def __init__(self, tone: str = "warning", text: str = "", action_text: str = "",
                 closable: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("frameRole", "banner")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(theme.SP[3] + 2, theme.SP[2], theme.SP[2], theme.SP[2])
        lay.setSpacing(theme.SP[2] + 2)
        self._icon = QLabel(self)
        self._icon.setFixedSize(18, 18)
        lay.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignVCenter)
        self._label = QLabel(text, self)
        self._label.setWordWrap(True)
        self._label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self._label, 1)
        self._action = QPushButton(action_text, self)
        self._action.setProperty("variant", "ghost")
        self._action.setCursor(Qt.CursorShape.PointingHandCursor)
        self._action.setFixedHeight(theme.CONTROL_H)
        self._action.clicked.connect(self.actionClicked.emit)
        self._action.setVisible(bool(action_text))
        lay.addWidget(self._action, 0, Qt.AlignmentFlag.AlignVCenter)
        self._close = QToolButton(self)
        self._close.setProperty("variant", "icon")
        self._close.setFixedSize(theme.CONTROL_H, theme.CONTROL_H)
        self._close.setCursor(Qt.CursorShape.PointingHandCursor)
        from ..i18n import tr

        self._close.setToolTip(tr("關閉", "Close"))
        self._close.setAccessibleName(tr("關閉", "Close"))
        icons.bind(self._close, "x", "text_muted", 16)
        self._close.clicked.connect(self._on_close)
        self._close.setVisible(closable)
        lay.addWidget(self._close, 0, Qt.AlignmentFlag.AlignVCenter)
        self._tone = ""
        self.setTone(tone)

    def _on_close(self) -> None:
        self.hide()
        self.closed.emit()

    def text(self) -> str:
        return self._label.text()

    def setText(self, text: str) -> None:
        self._label.setText(text)

    def tone(self) -> str:
        return self._tone

    def setTone(self, tone: str) -> None:
        tone = tone if tone in theme.TONES else "warning"
        self._tone = tone
        self.setProperty("tone", tone)
        self._label.setProperty("role", f"tone_{tone}")
        self._action.setProperty("tone", tone)
        icons.bind(self._icon, _BANNER_ICON.get(tone, "info"), tone, 18)
        for w in (self, self._label, self._action):
            _repolish(w)

    def setActionText(self, text: str) -> None:
        """Extra: change or hide ("") the action button."""
        self._action.setText(text)
        self._action.setVisible(bool(text))

    def action_button(self) -> QPushButton:
        """Extra: the ghost action button (tests, focus order)."""
        return self._action


class _EmptyArt(QWidget):
    """Large illustration for empty states: dashed drop zone with an icon."""

    def __init__(self, icon_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icon = icon_name
        self.setFixedSize(120, 96)

    def paintEvent(self, _event: QPaintEvent | None) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(theme.color("border_strong"), 1.5, Qt.PenStyle.DashLine))
        p.setBrush(theme.color("surface_inset"))
        p.drawRoundedRect(r, 16, 16)
        p.drawPixmap(QPointF(r.center().x() - 20, r.center().y() - 20), icons.icon_pixmap(self._icon, "accent", 40, 1.6))
        p.end()


class EmptyState(QWidget):
    """Dashed art with an icon, title, hint, action buttons and an optional keycap tip
    (e.g. tip_keys=["Ctrl", "V"], tip_text="貼上序號")."""

    def __init__(self, icon_name: str, title: str, hint: str = "", actions: Sequence[QAbstractButton] = (),
                 tip_keys: Sequence[str] = (), tip_text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        # 16 px above and below: the stretches centre the content when there is room; tall margins only
        # raised the minimum height (a scroll bar in the empty code list at 150 % in the smallest window)
        lay.setContentsMargins(theme.SP[6], theme.SP[4], theme.SP[6], theme.SP[4])
        lay.setSpacing(theme.SP[3])
        lay.addStretch(1)
        lay.addWidget(_EmptyArt(icon_name, self), 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addSpacing(theme.SP[2])
        self.title_label = label(title, "title")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self.title_label, 0, Qt.AlignmentFlag.AlignHCenter)
        self.hint_label = label(hint, "secondary")
        self.hint_label.setWordWrap(True)
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.hint_label.setMaximumWidth(560)
        self.hint_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.hint_label.setVisible(bool(hint))
        # no alignment flag on a wrapped label (the layout would size it for one line): centre it
        # between stretches instead, so its height follows the wrapped text
        hint_row = QHBoxLayout()
        hint_row.addStretch(1)
        hint_row.addWidget(self.hint_label, 10)
        hint_row.addStretch(1)
        lay.addLayout(hint_row)
        if actions:
            lay.addSpacing(theme.SP[2])
            row = QHBoxLayout()
            row.setSpacing(theme.SP[2])
            row.addStretch(1)
            for a in actions:
                row.addWidget(a)
            row.addStretch(1)
            lay.addLayout(row)
        if tip_keys or tip_text:
            lay.addSpacing(theme.SP[1])
            tip = QHBoxLayout()
            tip.setSpacing(theme.SP[1])
            tip.addStretch(1)
            for n, key in enumerate(tip_keys):
                if n:
                    tip.addWidget(label("+", "muted"), 0, Qt.AlignmentFlag.AlignVCenter)
                tip.addWidget(Keycap(key), 0, Qt.AlignmentFlag.AlignVCenter)
            if tip_text:
                tip.addWidget(label(tip_text, "muted"), 0, Qt.AlignmentFlag.AlignVCenter)
            tip.addStretch(1)
            lay.addLayout(tip)
        lay.addStretch(2)


class Keycap(QLabel):
    """Height 20, radius 4, 2 px bottom border, small bold text (e.g. "F8")."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setProperty("role", "keycap")
        self.setFixedHeight(theme.KEYCAP_H)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    # no setMinimumWidth: an explicit minimum overrides the size hint and lets a crowded layout
    # squeeze the key text (measured in the English status bar at 1100 px)
    def sizeHint(self) -> QSize:
        return QSize(max(theme.KEYCAP_H, super().sizeHint().width()), theme.KEYCAP_H)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()


class Divider(QFrame):
    def __init__(self, vertical: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "vdivider" if vertical else "divider")
        if vertical:
            self.setFixedWidth(1)
            self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        else:
            self.setFixedHeight(1)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


class ElidedLabel(QLabel):
    """Single-line label that elides with "…" instead of widening its parent."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        # Preferred: as wide as the text when there is room, down to minimumSizeHint when not
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.setWordWrap(False)
        self._auto_tip = ""

    def minimumSizeHint(self) -> QSize:
        return QSize(16, super().minimumSizeHint().height())

    def paintEvent(self, event: QPaintEvent | None) -> None:
        text = self.text()
        if not text or self.pixmap() is not None and not self.pixmap().isNull():
            super().paintEvent(event)
            return
        p = QPainter(self)
        rect = self.contentsRect()
        fm = QFontMetrics(self.font())
        first = text.split("\n")[0]
        elided = fm.elidedText(first, Qt.TextElideMode.ElideRight, rect.width())
        p.setPen(self.palette().color(self.foregroundRole()))
        p.drawText(rect, int(self.alignment() | Qt.AlignmentFlag.AlignVCenter), elided)
        p.end()
        own_tip = self.toolTip() and self.toolTip() != self._auto_tip
        if not own_tip:  # show the full text as a tooltip only while it is cut
            want = text if elided != first else ""
            if want != self._auto_tip:
                self._auto_tip = want
                self.setToolTip(want)

    def resizeEvent(self, event: QResizeEvent | None) -> None:
        super().resizeEvent(event)
        self.update()


class SeparatedLabel(QLabel):
    """Short parts joined by 「 · 」 (the gallery's meta line) that wrap only BETWEEN parts: the
    dot at a line break is dropped, so no line starts or ends with it, and when two lines are
    needed the break that balances them is used (UI review U31). A part wider than the label
    still wraps inside itself."""

    SEP = "\u00a0·\u00a0"  # no-break spaces: the label never breaks at a dot by itself

    def __init__(self, parts: Sequence[str] = (), role: str = "caption", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", role)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.setWordWrap(True)
        self._parts: list[str] = []
        self._flow_w = -1
        self.set_parts(parts)

    def parts(self) -> list[str]:
        return list(self._parts)

    def set_parts(self, parts: Sequence[str]) -> None:
        self._parts = [str(p) for p in parts if str(p)]
        self._flow_w = -1
        self.setText(self.SEP.join(self._parts))  # one line until the label knows its width
        if self._inner_width() > 0:
            self._reflow(self._inner_width())

    def _inner_width(self) -> int:
        return self.contentsRect().width() - 2 * self.margin()

    def lines_for(self, width: int) -> list[str]:
        """The parts flowed into lines of at most ``width`` px."""
        parts = self._parts
        if len(parts) <= 1 or width <= 0:
            return [self.SEP.join(parts)] if parts else []
        self.ensurePolished()
        fm = QFontMetrics(self.font())

        def wide(group: Sequence[str]) -> int:
            return fm.horizontalAdvance(self.SEP.join(group))

        lines: list[list[str]] = [[]]
        for p in parts:
            if lines[-1] and wide([*lines[-1], p]) > width:
                lines.append([])
            lines[-1].append(p)
        if len(lines) == 2:  # the break whose longer line is the shortest (still within the width)
            k = min(range(1, len(parts)), key=lambda i: max(wide(parts[:i]), wide(parts[i:])))
            if max(wide(parts[:k]), wide(parts[k:])) <= width:
                lines = [parts[:k], parts[k:]]
        return [self.SEP.join(line) for line in lines]

    def _reflow(self, width: int) -> None:
        if width == self._flow_w:
            return
        self._flow_w = width
        text = "\n".join(self.lines_for(width))
        if text != self.text():
            self.setText(text)

    def heightForWidth(self, width: int) -> int:
        m = self.contentsMargins()
        inner = width - m.left() - m.right() - 2 * self.margin()
        if inner <= 0:
            return super().heightForWidth(width)
        text = "\n".join(self.lines_for(inner))
        flags = int(self.alignment()) | int(Qt.TextFlag.TextWordWrap)
        rect = QFontMetrics(self.font()).boundingRect(0, 0, inner, 2000, flags, text)
        return rect.height() + m.top() + m.bottom() + 2 * self.margin()

    def resizeEvent(self, event: QResizeEvent | None) -> None:
        super().resizeEvent(event)
        self._reflow(self._inner_width())


def confirm(parent: QWidget | None, title: str, text: str, ok_text: str | None = None,
            cancel_text: str | None = None, danger: bool = False) -> bool:
    """Themed modal question; True when confirmed. Default button = cancel when ``danger``.
    Always pass a parent (the main window, or the mini bar during runs); None only before the
    main window exists (first-run dialogs)."""
    from .widgets_dialogs import confirm as _confirm

    return _confirm(parent, title, text, ok_text, cancel_text, danger)


def message(parent: QWidget | None, title: str, text: str, kind: str = "info") -> None:
    """Themed modal message (kind: info | success | warning | error); parent rule as confirm."""
    from .widgets_dialogs import message as _message

    _message(parent, title, text, kind)
