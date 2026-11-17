"""Plain-Qt stand-ins for G5's UI foundation while it is still a stub (OWNED BY A1).

``install()`` patches ``autopress.ui.theme``, ``icons``, ``widgets`` and ``toast`` ONLY when the
module still carries ``__stub__ = True``. Once G5 replaces a module this does nothing for it.
The stand-ins keep the public API of the stubs (names, signatures, signals) but look plain;
they exist so G6/G7 can build and test pages before G5 lands. Patched modules get
``__fallback__ = True``. Import pages AFTER install() (conftest and tools/snap_widget.py do).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PyQt6.QtCore import QObject, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPalette, QPen, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from autopress.models import CodeStatus

_installed: list[str] = []


def install() -> list[str]:
    """Patch every G5 module that is still a stub. Returns the names patched (idempotent)."""
    from autopress.ui import icons, theme, toast, widgets

    for name, mod, fn in (("theme", theme, _patch_theme), ("icons", icons, _patch_icons),
                          ("widgets", widgets, _patch_widgets), ("toast", toast, _patch_toast)):
        if getattr(mod, "__stub__", False) and not getattr(mod, "__fallback__", False):
            fn(mod)
            mod.__fallback__ = True
            _installed.append(name)
    return list(_installed)


# ============================================================================= theme


def _patch_theme(theme: object) -> None:
    state = {"name": "dark"}

    def resolve_theme(name: object) -> str:
        return "light" if str(name) == "light" else "dark"

    def tokens() -> dict[str, str]:
        return theme.THEMES[state["name"]]

    def color(token: str) -> QColor:
        value = tokens().get(token, token)
        text = value.lstrip("#")
        if len(text) not in (6, 8):
            return QColor(value)
        r, g, b = int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)
        a = int(text[6:8], 16) if len(text) == 8 else 255
        return QColor(r, g, b, a)

    def css(token: str) -> str:
        c = color(token)
        return c.name() if c.alpha() == 255 else f"rgba({c.red()}, {c.green()}, {c.blue()}, {c.alpha()})"

    def tone_colors(tone: str) -> tuple[QColor, QColor, QColor]:
        if tone == "accent":
            return color("accent"), color("accent_soft"), color("accent_text")
        return color(tone), color(f"{tone}_soft"), color(f"{tone}_text")

    def font(px: int = theme.FS_BODY, *, bold: bool = False, mono: bool = False, tnum: bool = False) -> QFont:
        f = QFont()
        f.setFamilies(list(theme.FONT_MONO if mono else theme.FONT_UI))
        f.setPixelSize(px)
        if bold:
            f.setWeight(QFont.Weight.Bold)
        return f

    def build_palette(t: dict[str, str]) -> QPalette:
        pal = QPalette()
        pal.setColor(QPalette.ColorRole.Window, QColor(t["bg_app"]))
        pal.setColor(QPalette.ColorRole.WindowText, QColor(t["text"]))
        pal.setColor(QPalette.ColorRole.Base, QColor(t["surface_raised"]))
        pal.setColor(QPalette.ColorRole.Text, QColor(t["text"]))
        pal.setColor(QPalette.ColorRole.Button, QColor(t["surface_raised"]))
        pal.setColor(QPalette.ColorRole.ButtonText, QColor(t["text"]))
        return pal

    def build_qss(t: dict[str, str]) -> str:
        return ""

    def apply_theme(app: QApplication, name: object) -> str:
        state["name"] = resolve_theme(name)
        app.setPalette(build_palette(tokens()))
        return state["name"]

    def current_theme() -> str:
        return state["name"]

    for fn in (resolve_theme, tokens, color, css, tone_colors, font, build_palette, build_qss,
               apply_theme, current_theme):
        setattr(theme, fn.__name__, fn)


# ============================================================================= icons


def _patch_icons(icons: object) -> None:
    def icon_pixmap(name: str, color: str, size: int = 18, stroke: float = 1.8) -> QPixmap:
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        return pm

    def icon(name: str, color_token: str = "text_secondary", size: int = 16) -> QIcon:
        return QIcon(icon_pixmap(name, color_token, size))

    def app_icon() -> QIcon:
        return QIcon()

    icons.icon_pixmap, icons.icon, icons.app_icon = icon_pixmap, icon, app_icon
    if not hasattr(icons, "ICONS"):
        icons.ICONS = {name: "" for name in icons.ICON_NAMES}


# ============================================================================= widgets


def _patch_widgets(w: object) -> None:
    from autopress.ui import theme

    def label(text: str = "", role: str = "body") -> QLabel:
        lb = QLabel(text)
        lb.setProperty("role", role)
        return lb

    def push_button(text: str, variant: str = "secondary", icon_name: str | None = None) -> QPushButton:
        b = QPushButton(text)
        b.setProperty("variant", variant)
        return b

    def icon_button(icon_name: str, tooltip: str, variant: str = "ghost") -> QToolButton:
        b = QToolButton()
        b.setToolTip(tooltip)
        b.setAccessibleName(tooltip)
        b.setText(icon_name[:1].upper())
        b.setFixedSize(32, 32)
        b.setProperty("variant", variant)
        return b

    def section_header(title: str, subtitle: str = "", actions: Sequence[QWidget] = ()) -> QWidget:
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        col = QVBoxLayout()
        col.addWidget(label(title, "display"))
        if subtitle:
            col.addWidget(label(subtitle, "muted"))
        lay.addLayout(col)
        lay.addStretch(1)
        for a in actions:
            lay.addWidget(a)
        return box

    def form_row(label_text: str, field: QWidget, hint: str = "") -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(label(label_text, "secondary"))
        lay.addWidget(field)
        if hint:
            lay.addWidget(label(hint, "muted"))
        return box

    class Switch(QCheckBox):
        def __init__(self, checked: bool = False, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self.setChecked(checked)

    class SegmentedControl(QWidget):
        currentChanged = pyqtSignal(int)

        def __init__(self, items: Sequence[str] = (), checked: int = 0, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self._lay = QHBoxLayout(self)
            self._lay.setContentsMargins(0, 0, 0, 0)
            self._group = QButtonGroup(self)
            self._group.setExclusive(True)
            self._group.idClicked.connect(self.currentChanged.emit)
            self.setItems(items)
            self.setCurrentIndex(checked)

        def setItems(self, items: Sequence[str]) -> None:
            for b in self._group.buttons():
                self._group.removeButton(b)
                b.deleteLater()
            for i, text in enumerate(items):
                b = QPushButton(text)
                b.setCheckable(True)
                self._group.addButton(b, i)
                self._lay.addWidget(b)

        def currentIndex(self) -> int:
            return self._group.checkedId()

        def setCurrentIndex(self, index: int) -> None:
            b = self._group.button(index)
            if b is not None and not b.isChecked():
                b.setChecked(True)
                self.currentChanged.emit(index)

    class SearchField(QLineEdit):
        def __init__(self, placeholder: str = "", parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self.setPlaceholderText(placeholder)
            self.setClearButtonEnabled(True)

    class ChevronCombo(QComboBox):
        pass

    def combo(items: Sequence[str] = (), width: int | None = None) -> ChevronCombo:
        c = ChevronCombo()
        c.addItems(list(items))
        if width:
            c.setFixedWidth(width)
        return c

    class Card(QFrame):
        def __init__(self, vertical: bool = True, margins: tuple[int, int, int, int] | None = None,
                     spacing: int = 8, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            lay = QVBoxLayout(self) if vertical else QHBoxLayout(self)
            lay.setContentsMargins(*(margins or theme.CARD_MARGINS))
            lay.setSpacing(spacing)
            self.setFrameShape(QFrame.Shape.StyledPanel)

    class Banner(QFrame):
        actionClicked = pyqtSignal()
        closed = pyqtSignal()

        def __init__(self, tone: str = "warning", text: str = "", action_text: str = "",
                     closable: bool = True, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            lay = QHBoxLayout(self)
            self._label = QLabel(text)
            self._label.setWordWrap(True)
            lay.addWidget(self._label, 1)
            self._tone = tone
            if action_text:
                b = QPushButton(action_text)
                b.clicked.connect(self.actionClicked.emit)
                lay.addWidget(b)
            if closable:
                c = QToolButton()
                c.setText("×")
                c.setAccessibleName("close")
                c.clicked.connect(self._close)
                lay.addWidget(c)

        def _close(self) -> None:
            self.hide()
            self.closed.emit()

        def setText(self, text: str) -> None:
            self._label.setText(text)

        def text(self) -> str:
            return self._label.text()

        def setTone(self, tone: str) -> None:
            self._tone = tone

    class EmptyState(QWidget):
        def __init__(self, icon_name: str, title: str, hint: str = "", actions: Sequence[object] = (),
                     tip_keys: Sequence[str] = (), tip_text: str = "", parent: QWidget | None = None) -> None:
            super().__init__(parent)
            lay = QVBoxLayout(self)
            lay.addWidget(label(title, "title"))
            if hint:
                lay.addWidget(label(hint, "muted"))
            row = QHBoxLayout()
            for a in actions:
                row.addWidget(a)
            lay.addLayout(row)
            if tip_keys or tip_text:
                lay.addWidget(label("+".join(tip_keys) + (" " + tip_text if tip_text else ""), "caption"))

    class Keycap(QLabel):
        def __init__(self, text: str, parent: QWidget | None = None) -> None:
            super().__init__(text, parent)
            self.setProperty("role", "keycap")

    def status_chip_width(status: CodeStatus, text: str | None = None) -> int:
        return QFontMetrics(theme.font(theme.FS_SMALL, bold=True)).horizontalAdvance(text or status.label()) + 30

    def paint_status_chip(painter: QPainter, rect: QRectF, status: CodeStatus, text: str | None = None) -> float:
        base, soft, fg = theme.tone_colors(status.tone)
        width = status_chip_width(status, text)
        r = QRectF(rect.left(), rect.center().y() - 11, width, 22)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(soft)
        painter.drawRoundedRect(r, 11, 11)
        painter.setPen(QPen(fg))
        painter.setFont(theme.font(theme.FS_SMALL, bold=True))
        painter.drawText(r.adjusted(20, 0, -8, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         text or status.label())
        painter.setBrush(base)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(r.left() + 9, r.center().y() - 3, 6, 6))
        painter.restore()
        return float(width)

    class StatusChip(QWidget):
        def __init__(self, status: CodeStatus = CodeStatus.PENDING, text: str | None = None,
                     parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self.setStatus(status, text)

        def setStatus(self, status: CodeStatus, text: str | None = None) -> None:
            self.status, self.text = status, text
            self.setFixedSize(status_chip_width(status, text), 24)
            self.update()

        def paintEvent(self, _event: object) -> None:
            p = QPainter(self)
            paint_status_chip(p, QRectF(self.rect()), self.status, self.text)
            p.end()

    class ProgressRing(QWidget):
        def __init__(self, size: int = 40, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self.setFixedSize(size, size)
            self.done, self.total, self.tone = 0, 0, "accent"

        def setProgress(self, done: int, total: int) -> None:
            self.done, self.total = done, total
            self.update()

        def setTone(self, tone: str) -> None:
            self.tone = tone
            self.update()

        def paintEvent(self, _event: object) -> None:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            r = QRectF(self.rect()).adjusted(3, 3, -3, -3)
            p.setPen(QPen(theme.color("border_strong"), 4))
            p.drawEllipse(r)
            if self.total:
                p.setPen(QPen(theme.tone_colors(self.tone)[0], 4))
                p.drawArc(r, 90 * 16, -int(360 * 16 * self.done / self.total))
            p.end()

    class Spinner(QWidget):
        def __init__(self, size: int = 20, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self.setFixedSize(size, size)
            self.running = False

        def start(self) -> None:
            self.running = True

        def stop(self) -> None:
            self.running = False

    class Divider(QFrame):
        def __init__(self, vertical: bool = False, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self.setFrameShape(QFrame.Shape.VLine if vertical else QFrame.Shape.HLine)

    class ElidedLabel(QLabel):
        pass

    def confirm(parent: QWidget | None, title: str, text: str, ok_text: str | None = None,
                cancel_text: str | None = None, danger: bool = False) -> bool:
        return True  # tests monkeypatch widgets.confirm to answer "no"

    def message(parent: QWidget | None, title: str, text: str, kind: str = "info") -> None:
        return None

    for name, obj in {
        "label": label, "push_button": push_button, "icon_button": icon_button, "section_header": section_header,
        "form_row": form_row, "Switch": Switch, "SegmentedControl": SegmentedControl, "SearchField": SearchField,
        "ChevronCombo": ChevronCombo, "combo": combo, "Card": Card, "Banner": Banner, "EmptyState": EmptyState,
        "Keycap": Keycap, "status_chip_width": status_chip_width, "paint_status_chip": paint_status_chip,
        "StatusChip": StatusChip, "ProgressRing": ProgressRing, "Spinner": Spinner, "Divider": Divider,
        "ElidedLabel": ElidedLabel, "confirm": confirm, "message": message,
    }.items():
        setattr(w, name, obj)


# ============================================================================= toast


def _patch_toast(toast: object) -> None:
    class ToastManager(QObject):
        def __init__(self, host: QWidget) -> None:
            super().__init__(host)
            self.host = host
            self.shown: list[tuple[str, str]] = []  # (kind, text) - tests inspect this

        def attach_signals(self, signals: object) -> None:
            signals.toast.connect(lambda kind, text: self.show_toast(text, kind))

        def show_toast(self, text: str, kind: str = "info", action_text: str = "",
                       action: Callable[[], None] | None = None, timeout_ms: int = 4000) -> None:
            self.shown.append((kind, text))

    toast.ToastManager = ToastManager


__all__ = ["install"]
