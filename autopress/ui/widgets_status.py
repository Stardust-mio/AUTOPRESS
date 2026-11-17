# OWNED BY G5
"""Private part of ui.widgets: status chips, the progress ring and the spinner (custom painted,
colours read at paint time). ``widgets`` re-exports every name, so pages import them from
``autopress.ui.widgets`` as documented."""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QFontMetrics, QPainter, QPaintEvent, QPen
from PyQt6.QtWidgets import QWidget

from ..models import CodeStatus
from . import theme

__all__ = ["ProgressRing", "Spinner", "StatusChip", "paint_status_chip", "status_chip_width"]


def status_chip_width(status: CodeStatus, text: str | None = None) -> int:
    return QFontMetrics(theme.font(theme.FS_SMALL, bold=True)).horizontalAdvance(text or status.label()) + 30


def paint_status_chip(painter: QPainter, rect: QRectF, status: CodeStatus, text: str | None = None) -> float:
    """Paint a chip (h22 pill, soft fill, dot/ring/dash glyph from status.glyph, bold 12 px
    text = ``text`` or status.label()) at the left of ``rect``, vertically centred, for item
    delegates. Restores the painter state. Returns the painted width."""
    text = text or status.label()
    base, soft, fg = theme.tone_colors(status.tone)
    width = status_chip_width(status, text)
    r = QRectF(QRectF(rect).left(), QRectF(rect).center().y() - theme.CHIP_H / 2, width, theme.CHIP_H)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(soft)
    painter.drawRoundedRect(r, theme.CHIP_H / 2, theme.CHIP_H / 2)
    cx, cy = r.left() + 12, r.center().y()
    glyph = status.glyph
    if glyph == "dot":
        painter.setBrush(base)
        painter.drawEllipse(QPointF(cx, cy), 3.2, 3.2)
    elif glyph == "ring":
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(base, 1.4))
        painter.drawEllipse(QPointF(cx, cy), 3.0, 3.0)
    else:
        painter.setPen(QPen(base, 1.6, cap=Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(cx - 3, cy), QPointF(cx + 3, cy))
    painter.setFont(theme.font(theme.FS_SMALL, bold=True))
    painter.setPen(fg)
    painter.drawText(r.adjusted(20, 0, -8, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
    painter.restore()
    return float(width)


class StatusChip(QWidget):
    def __init__(self, status: CodeStatus = CodeStatus.PENDING, text: str | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.status: CodeStatus = status
        self.text: str | None = text
        self.setStatus(status, text)

    def setStatus(self, status: CodeStatus, text: str | None = None) -> None:
        self.status, self.text = status, text
        self.setFixedSize(status_chip_width(status, text), theme.CHIP_H + 2)
        self.setAccessibleName(text or status.label())
        self.update()

    def paintEvent(self, _event: QPaintEvent | None) -> None:
        p = QPainter(self)
        paint_status_chip(p, QRectF(self.rect()), self.status, self.text)
        p.end()


class ProgressRing(QWidget):
    """Ring of ``size`` px, 4 px round-cap stroke; centre text "done/total"."""

    def __init__(self, size: int = 40, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.done, self.total, self.tone = 0, 0, "accent"

    def setProgress(self, done: int, total: int) -> None:
        self.done, self.total = max(0, int(done)), max(0, int(total))
        self.setAccessibleName(f"{self.done}/{self.total}")
        self.update()

    def setTone(self, tone: str) -> None:
        self.tone = tone
        self.update()

    def paintEvent(self, _event: QPaintEvent | None) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        p.setPen(QPen(theme.color("border_strong"), 4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(r)
        if self.total > 0 and self.done > 0:
            frac = min(1.0, self.done / self.total)
            p.setPen(QPen(theme.tone_colors(self.tone)[0], 4, cap=Qt.PenCapStyle.RoundCap))
            p.drawArc(r, 90 * 16, -round(360 * 16 * frac))
        size = theme.FS_CAPTION if self.width() >= 36 else 9
        p.setFont(theme.font(size, bold=True, num=True, tnum=True))
        p.setPen(theme.color("text"))
        p.drawText(QRectF(self.rect()), Qt.AlignmentFlag.AlignCenter, f"{self.done}/{self.total}")
        p.end()


class Spinner(QWidget):
    """Busy indicator for loading states (OCR running...)."""

    def __init__(self, size: int = 20, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.running = False
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)

    def _tick(self) -> None:
        self._angle = (self._angle + 24) % 360
        self.update()

    def start(self) -> None:
        self.running = True
        self._timer.start()
        self.update()

    def stop(self) -> None:
        self.running = False
        self._timer.stop()
        self.update()

    def paintEvent(self, _event: QPaintEvent | None) -> None:
        if not self.running:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = max(2.0, self.width() / 9)
        r = QRectF(self.rect()).adjusted(w, w, -w, -w)
        p.setPen(QPen(theme.color("border_strong"), w))
        p.drawEllipse(r)
        p.setPen(QPen(theme.color("accent"), w, cap=Qt.PenCapStyle.RoundCap))
        p.drawArc(r, -self._angle * 16, 100 * 16)
        p.end()
