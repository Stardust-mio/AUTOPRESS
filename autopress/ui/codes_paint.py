# OWNED BY G6
"""Painting helpers shared by the G6 tables and dialogs (private to G6): the mono code with
flagged / look-alike marks, badges, the confidence bar, check boxes and column widths. Colours are
read from the theme at paint time, so a theme switch only needs a repaint."""

from __future__ import annotations

from collections.abc import Iterable

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QFontMetricsF, QPainter, QPen

from ..models import CodeStatus
from . import theme, widgets

CELL_PAD = 12  # horizontal padding of a table cell (codes_model.CellDelegate)


def code_char_styles(code: str, flagged: Iterable[int], lookalikes: Iterable[int]) -> list[str]:
    """Per character: "flagged" (must be checked; REVIEW gate), "lookalike" (highlight only) or ""."""
    fl, lk = set(flagged or ()), set(lookalikes or ())
    return ["flagged" if i in fl else "lookalike" if i in lk else "" for i in range(len(code))]


def paint_code(painter: QPainter, rect: QRectF, code: str, flagged: Iterable[int] = (),
               lookalikes: Iterable[int] = (), text_token: str = "text") -> list[tuple[int, str]]:
    """Paint ``code`` in the mono font, left-aligned and vertically centred in ``rect``: flagged
    characters get a warning_soft cell and a solid warning underline, look-alikes a dotted muted
    underline only. Elides with "…" when the code does not fit. Returns the decorations painted
    as (index, style) - used by tests."""
    f = theme.font(theme.FS_MONO, mono=True)
    painter.save()
    painter.setFont(f)
    fm = QFontMetricsF(f)
    cy = rect.center().y()
    base_y = cy + (fm.ascent() - fm.descent()) / 2
    x = rect.left()
    limit = rect.right() + 0.5
    if fm.horizontalAdvance(code) > rect.width() + 0.5:
        limit -= fm.horizontalAdvance("…")  # leave room for the ellipsis
    marks: list[tuple[int, str]] = []
    styles = code_char_styles(code, flagged, lookalikes)
    for i, ch in enumerate(code):
        adv = fm.horizontalAdvance(ch)
        if x + adv > limit:
            painter.setPen(theme.color("text_muted"))
            painter.drawText(QPointF(x, base_y), "…")
            break
        style = styles[i]
        if style == "flagged":
            cell = QRectF(x - 1, cy - 11, adv + 2, 22)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.color("warning_soft"))
            painter.drawRoundedRect(cell, 3, 3)
            painter.setPen(QPen(theme.color("warning"), 1.6))
            painter.drawLine(QPointF(cell.left() + 1.5, cell.bottom() - 2), QPointF(cell.right() - 1.5, cell.bottom() - 2))
            painter.setPen(theme.color("warning_text"))
            marks.append((i, style))
        elif style == "lookalike":
            pen = QPen(theme.color("text_muted"), 1.3, Qt.PenStyle.DotLine)
            painter.setPen(pen)
            y = cy + 9
            painter.drawLine(QPointF(x + 1, y), QPointF(x + adv - 1, y))
            painter.setPen(theme.color(text_token))
            marks.append((i, style))
        else:
            painter.setPen(theme.color(text_token))
        painter.drawText(QPointF(x, base_y), ch)
        x += adv
    painter.restore()
    return marks


def code_width(code: str) -> float:
    """Width of ``code`` in the mono code font."""
    return QFontMetricsF(theme.font(theme.FS_MONO, mono=True)).horizontalAdvance(code)


def badge_width(text: str) -> float:
    return QFontMetricsF(theme.font(theme.FS_CAPTION, bold=True)).horizontalAdvance(text) + 14


def paint_badge(painter: QPainter, x: float, cy: float, text: str, tone: str) -> float:
    """Small pill (h 20, soft tone fill, bold caption text) starting at ``x``; returns its width."""
    base, soft, fg = theme.tone_colors(tone)
    w = badge_width(text)
    r = QRectF(x, cy - 10, w, 20)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(soft)
    painter.drawRoundedRect(r, 10, 10)
    painter.setPen(fg)
    painter.setFont(theme.font(theme.FS_CAPTION, bold=True))
    painter.drawText(r, Qt.AlignmentFlag.AlignCenter, text)
    painter.restore()
    return w


def confidence_tone(conf: float) -> str:
    """success >= 0.95 > warning >= 0.8 > error."""
    return "success" if conf >= 0.95 else ("warning" if conf >= 0.8 else "error")


def paint_confidence(painter: QPainter, rect: QRectF, conf: float | None) -> None:
    """4 px rounded bar (48 px) + percentage; "—" when ``conf`` is None (text sources)."""
    painter.save()
    painter.setFont(theme.font(theme.FS_SMALL, tnum=True))
    if conf is None:
        painter.setPen(theme.color("text_disabled"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "—")
        painter.restore()
        return
    conf = max(0.0, min(1.0, float(conf)))
    tone = confidence_tone(conf)
    base, _soft, fg = theme.tone_colors(tone)
    track = QRectF(rect.left(), rect.center().y() - 2, 48, 4)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(theme.color("border_strong"))
    painter.drawRoundedRect(track, 2, 2)
    painter.setBrush(base)
    painter.drawRoundedRect(QRectF(track.left(), track.top(), max(4.0, 48 * conf), 4), 2, 2)
    painter.setPen(fg if tone != "success" else theme.color("text_secondary"))
    painter.drawText(rect.adjusted(58, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                     f"{round(conf * 100)}%")
    painter.restore()


def paint_check(painter: QPainter, rect: QRectF, checked: bool, enabled: bool = True) -> QRectF:
    """16 px rounded check box at the left of ``rect`` (vertically centred); returns the box."""
    box = QRectF(rect.left(), rect.center().y() - 8, 16, 16)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if checked:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.color("accent_fill" if enabled else "text_disabled"))
    else:
        painter.setPen(QPen(theme.color("border_strong" if enabled else "border"), 1.2))
        painter.setBrush(theme.color("surface_raised"))
    painter.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
    if checked:
        pen = QPen(theme.color("on_accent"), 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolyline([QPointF(box.left() + 4, box.top() + 8.5), QPointF(box.left() + 7, box.top() + 11.5),
                              QPointF(box.left() + 12, box.top() + 5)])
    painter.restore()
    return box


def code_column_width(codes: Iterable[str]) -> int:
    """Code column width for the longest code (mono font): between 150 and 280 px."""
    longest = max(codes, key=len, default="")
    return int(max(150, min(280, code_width(longest) + 2 * CELL_PAD + 12)))


def status_column_width() -> int:
    """Width that fits the widest status chip in the current language."""
    return max(widgets.status_chip_width(s) for s in CodeStatus) + 24
