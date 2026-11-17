# OWNED BY G7
"""Painting widgets of the full-screen overlays (private helper of ui.overlays).

One frameless, always-on-top Tool window per QScreen, ``setGeometry(screen.geometry())``;
everything is drawn in the screen's local logical coordinates and converted with
ui.overlays_geom (``phys = origin + qRound(local * dpr)``), never through global logical
coordinates (win32_windows.md section 5).

* PickerOverlay  - interactive: frozen screenshot, crosshair, 4x magnifier (crosshair and a
  two-tone pixel outline, visible on white pages too), live physical x/y, instruction (an opaque
  pill drawn over the guides), target client rect outline with an opaque badge outside it when
  there is room, rubber band (region) or window outline (window).
* MarksOverlay   - click-through: PreviewMarks with a number badge and the step title beside it
  (red when not ok); near a screen edge badge and title move to the other side of the mark
  (place_point_mark / place_rect_mark), so a title never covers its own badge.
* CountdownWidget - click-through: big 3-2-1 digit and hint line on an opaque card, an arrow
  that ends at the ring around the failsafe corner (towards it when the corner is on another screen).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import TYPE_CHECKING

import numpy as np
from PyQt6.QtCore import QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen, QPolygonF
from PyQt6.QtWidgets import QWidget

from ..i18n import tr
from ..models import Point, PreviewKind, PreviewMark, Rect
from . import theme
from .overlays_geom import ScreenGeom, physical_rect_to_local, physical_to_local

if TYPE_CHECKING:
    from .overlays import ScreenPicker

MAG_BOX = 128  # magnifier size (logical px)
MAG_ZOOM = 4
PILL_FILL = QColor(28, 32, 39)  # instruction pill: opaque, so no guide line runs through its text
BADGE = 22.0  # number badge of a preview mark (logical px)
LABEL_GAP = 4.0  # between a badge and its title
RING_R = 15.0  # ring of a point mark
CORNER_RING_R = 22.0  # ring around the failsafe corner (countdown)
CORNER_ARROW_MAX = 110.0  # longest countdown arrow towards a corner on the same screen


def _color(token: str, fallback: str) -> QColor:
    try:
        c = theme.color(token)
        if c.isValid():
            return c
    except Exception:  # theme stub before G5 / fallback
        pass
    return QColor(fallback)


def _font(px: int, bold: bool = False, mono: bool = False) -> QFont:
    try:
        return theme.font(px, bold=bold, mono=mono)
    except Exception:
        f = QFont()
        f.setPixelSize(px)
        f.setBold(bold)
        return f


def bgra_to_qimage(arr: np.ndarray) -> QImage:
    """BGRA / BGR / gray uint8 array -> deep-copied QImage Format_RGB32 (B, G, R, X bytes)."""
    a = np.asarray(arr, dtype=np.uint8)
    if a.ndim == 2:
        a = np.dstack([a, a, a, np.full(a.shape, 255, np.uint8)])
    elif a.shape[2] == 3:
        a = np.dstack([a, np.full(a.shape[:2], 255, np.uint8)])
    a = np.ascontiguousarray(a)
    h, w = a.shape[:2]
    return QImage(a.tobytes(), w, h, w * 4, QImage.Format.Format_RGB32).copy()


def qimage_to_bgra(img: QImage) -> np.ndarray:
    """Any QImage -> (h, w, 4) uint8 BGRA copy (bytesPerLine padding removed)."""
    img = img.convertToFormat(QImage.Format.Format_ARGB32)
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    if w <= 0 or h <= 0:
        return np.zeros((0, 0, 4), np.uint8)
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    return np.frombuffer(ptr, np.uint8).reshape(h, bpl)[:, : w * 4].reshape(h, w, 4).copy()


class OverlayBase(QWidget):
    """Frameless always-on-top Tool window covering one screen."""

    def __init__(self, geom: ScreenGeom, interactive: bool) -> None:
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint
        if not interactive:
            flags |= Qt.WindowType.WindowTransparentForInput | Qt.WindowType.WindowDoesNotAcceptFocus
        super().__init__(None, flags)
        self.geom = geom
        if not interactive:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        x, y, w, h = geom.logical
        self.setGeometry(QRect(int(x), int(y), max(1, math.ceil(w)), max(1, math.ceil(h))))

    def local_rect(self, rect: Rect) -> QRectF:
        x, y, w, h = physical_rect_to_local(self.geom, rect)
        return QRectF(x, y, w, h)

    def local_point(self, p: Point) -> QPointF:
        x, y = physical_to_local(self.geom, p[0] + 0.5, p[1] + 0.5)
        return QPointF(x, y)


def _label_box(p: QPainter, anchor: QPointF, text: str, fg: QColor, bg: QColor, font: QFont,
               bounds: QRectF) -> QRectF:
    """Draw ``text`` in a rounded box with its top-left at ``anchor`` (kept inside ``bounds``)."""
    p.setFont(font)
    fm = p.fontMetrics()
    w, h = fm.horizontalAdvance(text) + 14, fm.height() + 8
    x = min(max(bounds.left() + 2, anchor.x()), bounds.right() - w - 2)
    y = min(max(bounds.top() + 2, anchor.y()), bounds.bottom() - h - 2)
    box = QRectF(x, y, w, h)
    _draw_box(p, box, text, fg, bg)
    return box


def target_badge_anchor(target: QRectF, bounds: QRectF, font: QFont) -> QPointF:
    """Top-left of the picker's 「目標視窗」 badge (a _label_box of ``font``): just above the target
    window's outline, else just below it, so it labels the outline without covering the window's
    content; inside the top-left corner only when the window fills the screen."""
    fm = QFontMetricsF(font)
    h = fm.height() + 8
    if target.top() - h - 2 >= bounds.top() + 2:
        return QPointF(target.left(), target.top() - h - 2)
    if target.bottom() + 2 + h <= bounds.bottom() - 2:
        return QPointF(target.left(), target.bottom() + 2)
    return QPointF(target.left() + 6, target.top() + 6)


def corner_label_anchor(corner: QPointF, inward: QPointF, text: str, font: QFont) -> QPointF:
    """Top-left of the countdown's 「緊急停止」 box (a _label_box of ``text`` / ``font``) next to the
    ring around a screen ``corner``. ``inward`` is the unit direction from the corner to where the
    arrow comes from: the box goes along the screen edge the arrow runs farther from, just past
    the arrow, so it never covers the arrow head and stays close to the ring."""
    fm = QFontMetricsF(font)
    w, h = fm.horizontalAdvance(text) + 14, fm.height() + 8
    ax, ay = abs(inward.x()), abs(inward.y())
    sx, sy = (1 if inward.x() >= 0 else -1), (1 if inward.y() >= 0 else -1)
    clear = 2.5 + 6  # half the arrow's width plus a gap
    if ax >= ay:  # the arrow runs closer to the horizontal edge: the box goes along the vertical edge
        off = max(CORNER_RING_R + 6, (4 + w) * ay / max(ax, 1e-6) + clear / max(ax, 1e-6))
        x = corner.x() + 4 if sx > 0 else corner.x() - 4 - w
        y = corner.y() + off if sy > 0 else corner.y() - off - h
    else:
        off = max(CORNER_RING_R + 6, (4 + h) * ax / max(ay, 1e-6) + clear / max(ay, 1e-6))
        y = corner.y() + 4 if sy > 0 else corner.y() - 4 - h
        x = corner.x() + off if sx > 0 else corner.x() - off - w
    return QPointF(x, y)


def _draw_box(p: QPainter, box: QRectF, text: str, fg: QColor, bg: QColor) -> None:
    """Rounded label box with centred ``text`` (the painter's font)."""
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(bg)
    p.drawRoundedRect(box, 6, 6)
    p.setPen(fg)
    p.drawText(box, int(Qt.AlignmentFlag.AlignCenter), text)


def _beside(badge: QRectF, w: float, h: float, side: int) -> QRectF:
    """A ``w`` x ``h`` box vertically centred on ``badge``, right of it (side 1) or left (-1)."""
    x = badge.right() + LABEL_GAP if side > 0 else badge.left() - LABEL_GAP - w
    return QRectF(x, badge.center().y() - h / 2, w, h)


def _fits(inner: QRectF, badge: QRectF, box: QRectF | None) -> bool:
    return inner.contains(badge) and (box is None or inner.contains(box))


def _first_fit(candidates: Sequence[QRectF], w: float, h: float, bounds: QRectF,
               sides: Sequence[int] = (1, -1)) -> tuple[QRectF, QRectF | None]:
    """First (badge, title box) of the candidate badges (title right, then left of each) that
    lies inside ``bounds`` (2 px margin); else the first badge clamped on screen with the title
    clamped right or left of it, on the side with more room."""
    inner = bounds.adjusted(2, 2, -2, -2)
    for badge in candidates:
        for side in sides:
            box = _beside(badge, w, h, side) if w > 0 else None
            if _fits(inner, badge, box):
                return badge, box
    b = QRectF(candidates[0])
    b.moveLeft(min(max(inner.left(), b.left()), inner.right() - b.width()))
    b.moveTop(min(max(inner.top(), b.top()), inner.bottom() - b.height()))
    if w <= 0:
        return b, None
    side = 1 if inner.right() - b.right() >= b.left() - inner.left() else -1
    box = _beside(b, w, h, side)
    box.moveLeft(min(max(inner.left(), box.left()), inner.right() - w))
    box.moveTop(min(max(inner.top(), box.top()), inner.bottom() - h))
    return b, box


def place_point_mark(c: QPointF, w: float, h: float, bounds: QRectF) -> tuple[QRectF, QRectF | None]:
    """(badge, title box) of a point mark at ``c`` (local px) whose title box is ``w`` x ``h``
    (w 0 = no title): the badge sits on the ring's upper right with the title to its right; near
    the right edge both go to the ring's upper left (title left of the badge), near the top
    edge below the ring. The title never covers its badge or the ring."""
    right = c.x() + RING_R - 5  # badge overlaps the ring's edge a little, like a counter badge
    left = c.x() - RING_R + 5 - BADGE
    above, below = c.y() - RING_R - 15, c.y() + RING_R - 7
    candidates = [QRectF(right, above, BADGE, BADGE), QRectF(left, above, BADGE, BADGE),
                  QRectF(right, below, BADGE, BADGE), QRectF(left, below, BADGE, BADGE)]
    inner = bounds.adjusted(2, 2, -2, -2)
    for i, badge in enumerate(candidates):
        side = 1 if i % 2 == 0 else -1  # the title goes away from the ring
        box = _beside(badge, w, h, side) if w > 0 else None
        if _fits(inner, badge, box):
            return badge, box
    # a title too long for either side: stack it above a badge above the ring (below one below
    # the ring), clamped horizontally - still clear of the ring and the badge
    for i, badge in enumerate(candidates):
        if not inner.contains(badge):
            continue
        y = badge.top() - LABEL_GAP - h if i < 2 else badge.bottom() + LABEL_GAP
        box = QRectF(min(max(inner.left(), badge.left()), inner.right() - w), y, w, h) if w > 0 else None
        if _fits(inner, badge, box):
            return badge, box
    return _first_fit(candidates, w, h, bounds)  # degenerate (screen smaller than the title)


def place_rect_mark(r: QRectF, w: float, h: float, bounds: QRectF) -> tuple[QRectF, QRectF | None]:
    """(badge, title box) of a region mark ``r`` (local px): the badge just above the region's
    top-left corner with the title to its right (left when the right side has no room); inside
    the corner when there is no room above the region."""
    inner = bounds.adjusted(2, 2, -2, -2)
    x = min(max(inner.left(), r.left() - 1), inner.right() - BADGE)
    candidates = [QRectF(x, r.top() - BADGE - 2, BADGE, BADGE),
                  QRectF(min(max(inner.left(), r.left() + 4), inner.right() - BADGE), r.top() + 4, BADGE, BADGE)]
    return _first_fit(candidates, w, h, bounds)


class PickerOverlay(OverlayBase):
    """Interactive picker surface for one screen; forwards input to its ScreenPicker."""

    def __init__(self, picker: ScreenPicker, geom: ScreenGeom, shot: np.ndarray | None) -> None:
        super().__init__(geom, interactive=True)
        self.picker = picker
        self.shot = shot  # BGRA, physical pixels of this monitor (may be None)
        self.qimage: QImage | None = None
        if shot is not None and shot.size:
            self.qimage = bgra_to_qimage(shot)
            if geom.logical[2] > 0:
                self.qimage.setDevicePixelRatio(shot.shape[1] / geom.logical[2])
        self.cursor_local: QPointF | None = None
        self.drag_start: QPointF | None = None
        self.hover_rect: Rect | None = None
        self.hover_text = ""
        self.hint = ""
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(tr("選取位置", "Pick a position"))

    # -- input -> picker ------------------------------------------------------------------
    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.picker.on_move(self, event.position())

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.RightButton:
            self.picker.cancel()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.picker.on_press(self, event.position())

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.picker.on_release(self, event.position())

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.picker.cancel()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.picker.on_enter(self)
        else:
            super().keyPressEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self.drag_start is None:
            self.cursor_local = None
            self.update()
        super().leaveEvent(event)

    # -- painting -------------------------------------------------------------------------
    def image_pixel(self, local: QPointF) -> tuple[int, int]:
        """Frozen-shot pixel under a local point (shots may differ slightly from the monitor size)."""
        if self.shot is None or not self.shot.size or self.geom.logical[2] <= 0:
            return 0, 0
        scale_x = self.shot.shape[1] / self.geom.logical[2]
        scale_y = self.shot.shape[0] / max(1e-9, self.geom.logical[3])
        ix = min(max(0, int(local.x() * scale_x)), self.shot.shape[1] - 1)
        iy = min(max(0, int(local.y() * scale_y)), self.shot.shape[0] - 1)
        return ix, iy

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        bounds = QRectF(self.rect())
        if self.qimage is not None:
            p.drawImage(QPointF(0, 0), self.qimage)
        else:
            p.fillRect(bounds, QColor(16, 18, 22))
        kind = self.picker.kind
        sel = self._selection()
        dim = QColor(0, 0, 0, 96 if kind != "region" else 120)
        if sel is None:
            p.fillRect(bounds, dim)
        else:  # dim everything but the selection
            path = QPainterPath()
            path.addRect(bounds)
            inner = QPainterPath()
            inner.addRect(sel)
            p.fillPath(path.subtracted(inner), dim)
        accent = _color("accent", "#6B93FF")
        target = self.picker.target_rect
        if target is not None:
            tr_ = self.local_rect(target)
            p.setPen(QPen(accent, 2, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(tr_)
            # opaque, and outside the window when there is room: it never covers (or shows through
            # to) the window's own text, e.g. a browser tab title in the window's top-left corner
            _label_box(p, target_badge_anchor(tr_, bounds, _font(12, bold=True)), tr("目標視窗", "Target window"),
                       QColor("#FFFFFF"), QColor(accent.red(), accent.green(), accent.blue()),
                       _font(12, bold=True), bounds)
        if kind == "window" and self.hover_rect is not None:
            hr = self.local_rect(self.hover_rect)
            p.setPen(QPen(accent, 3))
            p.setBrush(QColor(accent.red(), accent.green(), accent.blue(), 40))
            p.drawRect(hr)
            if self.hover_text:
                _label_box(p, QPointF(hr.left() + 4, hr.top() + 4), self.hover_text, QColor("#FFFFFF"),
                           QColor(20, 22, 28, 230), _font(12, bold=True), bounds)
        if sel is not None:
            p.setPen(QPen(accent, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(sel)
        cur = self.cursor_local
        if cur is not None:
            p.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 200), 1))
            p.drawLine(QPointF(0, cur.y()), QPointF(bounds.width(), cur.y()))
            p.drawLine(QPointF(cur.x(), 0), QPointF(cur.x(), bounds.height()))
            self._paint_magnifier(p, cur, bounds)
        self._paint_instruction(p, bounds)
        p.end()

    def _selection(self) -> QRectF | None:
        if self.picker.kind != "region" or self.drag_start is None or self.cursor_local is None:
            return None
        return QRectF(self.drag_start, self.cursor_local).normalized()

    def _paint_magnifier(self, p: QPainter, cur: QPointF, bounds: QRectF) -> None:
        if self.shot is None or not self.shot.size or self.qimage is None:
            return
        from .overlays_geom import magnifier_source

        ix, iy = self.image_pixel(cur)
        src_size = max(3, MAG_BOX // MAG_ZOOM)
        sx, sy, sw, sh = magnifier_source(ix, iy, self.shot.shape[1], self.shot.shape[0], src_size)
        crop = self.qimage.copy(QRect(sx, sy, sw, sh))
        crop.setDevicePixelRatio(1.0)
        box = QRectF(cur.x() + 24, cur.y() + 24, MAG_BOX, MAG_BOX)
        if box.right() > bounds.right() - 4:
            box.moveLeft(cur.x() - 24 - MAG_BOX)
        if box.bottom() > bounds.bottom() - 40:
            box.moveTop(cur.y() - 24 - MAG_BOX)
        p.save()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        p.drawImage(box, crop)
        cell_w, cell_h = box.width() / max(1, sw), box.height() / max(1, sh)
        cx = box.left() + (ix - sx) * cell_w
        cy = box.top() + (iy - sy) * cell_h
        cell = QRectF(cx, cy, cell_w, cell_h)
        accent = _color("accent", "#6B93FF")
        # the crosshair continues inside the magnifier up to the picked pixel, and that pixel has a
        # dark and a white outline: both stay visible on a white page and on a dark game
        p.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 200), 1))
        mx, my = cell.center().x(), cell.center().y()
        for a, b in ((QPointF(box.left(), my), QPointF(cell.left() - 2, my)),
                     (QPointF(cell.right() + 2, my), QPointF(box.right(), my)),
                     (QPointF(mx, box.top()), QPointF(mx, cell.top() - 2)),
                     (QPointF(mx, cell.bottom() + 2), QPointF(mx, box.bottom()))):
            p.drawLine(a, b)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(20, 22, 28), 1))
        p.drawRect(cell.adjusted(-1, -1, 1, 1))
        p.setPen(QPen(QColor(255, 255, 255), 1))
        p.drawRect(cell)
        p.setPen(QPen(accent, 2))
        p.drawRect(box)
        phys = self.picker.physical_at(self, cur)
        text = f"{phys[0]}, {phys[1]}"
        if self.picker.kind == "region" and self.drag_start is not None:
            a = self.picker.physical_at(self, self.drag_start)
            text = f"{abs(phys[0] - a[0])} × {abs(phys[1] - a[1])}"
        _label_box(p, QPointF(box.left(), box.bottom() + 4), text, QColor("#FFFFFF"), QColor(20, 22, 28, 230),
                   _font(12, bold=True, mono=True), bounds)
        p.restore()

    def _paint_instruction(self, p: QPainter, bounds: QRectF) -> None:
        title = self.picker.instruction or {
            "point": tr("點一下要點擊的位置", "Click the position"),
            "region": tr("按住滑鼠拖曳，框出範圍", "Drag to mark the region"),
            "window": tr("點一下要選的視窗", "Click the window"),
        }.get(self.picker.kind, "")
        sub = self.hint or {
            "point": tr("Esc 取消 · Enter 選目前位置", "Esc cancels · Enter picks the current position"),
            "region": tr("Esc 取消 · 右鍵取消", "Esc or right-click cancels"),
            "window": tr("Esc 取消", "Esc cancels"),
        }.get(self.picker.kind, "")
        f1, f2 = _font(15, bold=True), _font(12)
        p.setFont(f1)
        w1 = p.fontMetrics().horizontalAdvance(title)
        p.setFont(f2)
        w2 = p.fontMetrics().horizontalAdvance(sub)
        w = min(bounds.width() - 32, max(w1, w2) + 40)
        box = QRectF((bounds.width() - w) / 2, 24, w, 62)
        cur = self.cursor_local
        if cur is not None and box.adjusted(-20, -20, 20, 20).contains(cur):
            box.moveTop(bounds.height() - box.height() - 40)
        p.setPen(QPen(_color("border_strong", "#333A46"), 1))
        p.setBrush(PILL_FILL)  # opaque: the crosshair and the target outline stop at its edge
        p.drawRoundedRect(box, 12, 12)
        p.setPen(QColor("#E7E9EE"))
        p.setFont(f1)
        p.drawText(box.adjusted(16, 8, -16, -30), int(Qt.AlignmentFlag.AlignCenter), title)
        p.setPen(QColor("#A9B1BE"))
        p.setFont(f2)
        p.drawText(box.adjusted(16, 34, -16, -6), int(Qt.AlignmentFlag.AlignCenter), sub)


class MarksOverlay(OverlayBase):
    """Click-through preview of PreviewMarks on one screen: the badge carries the step number,
    the box beside it the step title (PreviewMark.label, no number)."""

    def __init__(self, geom: ScreenGeom, marks: Sequence[PreviewMark]) -> None:
        super().__init__(geom, interactive=False)
        self.marks = list(marks)

    @staticmethod
    def title_of(m: PreviewMark) -> str:
        text = (m.label or "").strip()
        if not m.ok:
            text += tr("（不在目標上）", " (not on the target)")
        return text.strip()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds = QRectF(self.rect())
        ok_c, bad_c = _color("accent", "#6B93FF"), _color("error", "#F87171")
        font = _font(12, bold=True)
        p.setFont(font)
        fm = p.fontMetrics()
        for m in self.marks:
            col = ok_c if m.ok else bad_c
            num = str(m.step_index + 1)
            text = self.title_of(m)
            w, h = (fm.horizontalAdvance(text) + 14.0, fm.height() + 8.0) if text else (0.0, 0.0)
            if m.kind in (PreviewKind.POINT, PreviewKind.FALLBACK_POINT) or (m.rect[2] <= 1 and m.rect[3] <= 1):
                c = self.local_point((m.rect[0], m.rect[1]))
                style = Qt.PenStyle.DashLine if m.kind is PreviewKind.FALLBACK_POINT else Qt.PenStyle.SolidLine
                p.setPen(QPen(QColor(255, 255, 255), 4))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(c, RING_R, RING_R)
                p.setPen(QPen(col, 3, style))
                p.drawEllipse(c, RING_R, RING_R)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(col)
                p.drawEllipse(c, 3, 3)
                badge, box = place_point_mark(c, w, h, bounds)
            else:
                r = self.local_rect(m.rect)
                style = Qt.PenStyle.DashLine if m.kind is PreviewKind.SEARCH_REGION else Qt.PenStyle.SolidLine
                p.setPen(QPen(col, 2, style))
                p.setBrush(QColor(col.red(), col.green(), col.blue(), 28))
                p.drawRect(r)
                badge, box = place_rect_mark(r, w, h, bounds)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawEllipse(badge)
            p.setPen(QColor("#FFFFFF"))
            p.setFont(font)
            p.drawText(badge, int(Qt.AlignmentFlag.AlignCenter), num)
            if box is not None:
                _draw_box(p, box, text, QColor("#FFFFFF"), QColor(20, 22, 28, 220))
        p.end()


class CountdownWidget(OverlayBase):
    """Click-through 3-2-1 on one screen, with the hint and an arrow to the failsafe corner."""

    def __init__(self, geom: ScreenGeom, hint: str, corner: Point | None) -> None:
        super().__init__(geom, interactive=False)
        self.hint = hint
        self.corner = corner
        self.value = 0

    def set_value(self, value: int) -> None:
        self.value = value
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds = QRectF(self.rect())
        panel = QRectF(0, 0, 360, 240)
        panel.moveCenter(bounds.center())
        p.setPen(QPen(_color("border_strong", "#333A46"), 1))
        p.setBrush(PILL_FILL)  # opaque: no text of the window behind shows through the digit or the hint
        p.drawRoundedRect(panel, 18, 18)
        p.setPen(QColor("#FFFFFF"))
        p.setFont(_font(110, bold=True))
        p.drawText(panel.adjusted(0, 6, 0, -70), int(Qt.AlignmentFlag.AlignCenter), str(self.value))
        p.setFont(_font(14, bold=True))
        p.setPen(QColor("#E7E9EE"))
        p.drawText(panel.adjusted(18, 166, -18, -10),
                   int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop) | int(Qt.TextFlag.TextWordWrap),
                   self.hint)
        if self.corner is not None:
            self._paint_corner_arrow(p, panel, bounds)
        p.end()

    def _paint_corner_arrow(self, p: QPainter, panel: QRectF, bounds: QRectF) -> None:
        cx, cy = physical_to_local(self.geom, self.corner[0], self.corner[1])
        target = QPointF(cx, cy)
        start = panel.center()
        dx, dy = target.x() - start.x(), target.y() - start.y()
        dist = math.hypot(dx, dy)
        if dist < 1:
            return
        ux, uy = dx / dist, dy / dist
        t_edge = min(abs((panel.width() / 2) / ux) if ux else 1e9, abs((panel.height() / 2) / uy) if uy else 1e9)
        if bounds.contains(target):
            # the corner is on this screen: the arrow ends at the ring around it, so it points AT the
            # corner (an arrow that stopped mid-screen seemed to point at whatever was there)
            room = dist - t_edge - 10 - (CORNER_RING_R + 8)
            length = min(CORNER_ARROW_MAX, max(20.0, room))
            b = QPointF(target.x() - ux * (CORNER_RING_R + 8), target.y() - uy * (CORNER_RING_R + 8))
            a = QPointF(b.x() - ux * length, b.y() - uy * length)
        else:  # on another screen: leave the panel towards it with an arrow of at most 90 px
            a = QPointF(start.x() + ux * (t_edge + 10), start.y() + uy * (t_edge + 10))
            length = min(90.0, max(30.0, dist - t_edge - 20))
            b = QPointF(a.x() + ux * length, a.y() + uy * length)
        col = _color("warning", "#F5B544")
        p.setPen(QPen(col, 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(a, b)
        head = QPolygonF([b, QPointF(b.x() - ux * 18 - uy * 10, b.y() - uy * 18 + ux * 10),
                          QPointF(b.x() - ux * 18 + uy * 10, b.y() - uy * 18 - ux * 10)])
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawPolygon(head)
        if bounds.contains(target):
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(col, 4))
            p.drawEllipse(target, CORNER_RING_R, CORNER_RING_R)
            text, font = tr("緊急停止", "Emergency stop"), _font(12, bold=True)
            _label_box(p, corner_label_anchor(target, QPointF(-ux, -uy), text, font), text,
                       QColor("#14181F"), col, font, bounds)
