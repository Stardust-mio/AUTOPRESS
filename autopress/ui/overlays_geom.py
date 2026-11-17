# OWNED BY G7
"""Pure screen / overlay geometry (win32_windows.md sections 1 and 5; private helper of G7).

Qt keeps every QScreen's ORIGIN in native (physical) pixels and scales only inside the screen,
so a point on a screen maps as ``phys = origin + qRound(local * dpr)`` and back as
``local = (phys - origin) / dpr``. Never go through global logical coordinates for more than
one screen (mixed DPI makes "islands"). Everything here is plain arithmetic on
:class:`ScreenGeom` values, so tests can use fake screens (any origin, any dpr).

The live helpers at the bottom (``screen_geoms``, ``monitor_rects``, ``work_rects``) read
QGuiApplication / win32.dpi and fall back to Qt when the win32 layer is unavailable.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass

from ..models import Point, Rect, intersect_rect

log = logging.getLogger(__name__)

__all__ = [
    "ScreenGeom",
    "clamp_point",
    "drag_rect",
    "inflate",
    "local_to_physical",
    "logical_to_physical",
    "magnifier_source",
    "monitor_rects",
    "nearest_corner",
    "overlap_area",
    "physical_rect_to_local",
    "physical_to_local",
    "physical_to_logical",
    "qround",
    "rect_center",
    "screen_for_physical_point",
    "screen_for_physical_rect",
    "screen_geoms",
    "work_rects",
]


def qround(v: float) -> int:
    """Qt's qRound: round half up for non-negative values (Python's round() rounds half to
    even, which is off by one pixel at x.5). Negative values round half away from zero."""
    return int(math.floor(v + 0.5)) if v >= 0 else -int(math.floor(-v + 0.5))


@dataclass(frozen=True)
class ScreenGeom:
    """One screen: Qt logical geometry (x, y = native origin) + device pixel ratio, and the
    work area (logical; = geometry when unknown)."""

    logical: tuple[float, float, float, float]  # x, y, w, h as QScreen.geometry()
    dpr: float = 1.0
    available: tuple[float, float, float, float] | None = None  # QScreen.availableGeometry()
    name: str = ""

    @property
    def origin(self) -> Point:
        return int(self.logical[0]), int(self.logical[1])

    @property
    def physical(self) -> Rect:
        """Physical monitor rect: native origin + qRound(size * dpr)."""
        ox, oy = self.origin
        return ox, oy, qround(self.logical[2] * self.dpr), qround(self.logical[3] * self.dpr)

    @property
    def physical_work(self) -> Rect:
        if self.available is None:
            return self.physical
        ax, ay, aw, ah = self.available
        x0, y0 = logical_to_physical(self, ax, ay)
        x1, y1 = logical_to_physical(self, ax + aw, ay + ah)
        return x0, y0, max(1, x1 - x0), max(1, y1 - y0)


def local_to_physical(geom: ScreenGeom, lx: float, ly: float) -> Point:
    """Point relative to the screen's top-left (a full-screen overlay's event.position())
    -> physical screen point."""
    ox, oy = geom.origin
    return ox + qround(lx * geom.dpr), oy + qround(ly * geom.dpr)


def physical_to_local(geom: ScreenGeom, px: float, py: float) -> tuple[float, float]:
    """Physical point -> local overlay coordinates (may be outside the screen)."""
    ox, oy = geom.origin
    return (px - ox) / geom.dpr, (py - oy) / geom.dpr


def physical_rect_to_local(geom: ScreenGeom, rect: Rect) -> tuple[float, float, float, float]:
    """Physical rect -> local (x, y, w, h) in overlay coordinates (for outlines)."""
    x, y = physical_to_local(geom, rect[0], rect[1])
    return x, y, rect[2] / geom.dpr, rect[3] / geom.dpr


def logical_to_physical(geom: ScreenGeom, gx: float, gy: float) -> Point:
    """GLOBAL logical point on this screen -> physical: origin + qRound((p - origin) * dpr)."""
    ox, oy = geom.origin
    return ox + qround((gx - ox) * geom.dpr), oy + qround((gy - oy) * geom.dpr)


def physical_to_logical(geom: ScreenGeom, px: float, py: float) -> tuple[float, float]:
    """Physical point -> GLOBAL logical point on this screen (for QWidget.move)."""
    ox, oy = geom.origin
    return ox + (px - ox) / geom.dpr, oy + (py - oy) / geom.dpr


def rect_center(rect: Rect) -> Point:
    return rect[0] + rect[2] // 2, rect[1] + rect[3] // 2


def screen_for_physical_point(geoms: Sequence[ScreenGeom], px: int, py: int) -> ScreenGeom | None:
    for g in geoms:
        x, y, w, h = g.physical
        if x <= px < x + w and y <= py < y + h:
            return g
    return None


def screen_for_physical_rect(geoms: Sequence[ScreenGeom], rect: Rect | None) -> ScreenGeom | None:
    """Screen with the largest overlap with ``rect``; else the one nearest to its centre;
    None only when ``geoms`` is empty. ``rect`` None -> the first screen (primary)."""
    if not geoms:
        return None
    if rect is None:
        return geoms[0]
    best, best_area = None, 0
    for g in geoms:
        area = overlap_area(g.physical, rect)
        if area > best_area:
            best, best_area = g, area
    if best is not None:
        return best
    cx, cy = rect_center(rect)

    def dist(g: ScreenGeom) -> float:
        x, y, w, h = g.physical
        dx = max(x - cx, 0, cx - (x + w - 1))
        dy = max(y - cy, 0, cy - (y + h - 1))
        return math.hypot(dx, dy)

    return min(geoms, key=dist)


def drag_rect(p0: Point, p1: Point) -> Rect:
    """Normalised rect between two physical corner points (exclusive end)."""
    x0, x1 = sorted((int(p0[0]), int(p1[0])))
    y0, y1 = sorted((int(p0[1]), int(p1[1])))
    return x0, y0, x1 - x0, y1 - y0


def clamp_point(lx: float, ly: float, width: float, height: float) -> tuple[float, float]:
    """Clamp a local point into [0, width) x [0, height) (drags outside the overlay)."""
    eps = 1e-6
    return min(max(lx, 0.0), max(0.0, width - eps)), min(max(ly, 0.0), max(0.0, height - eps))


def inflate(rect: Rect, d: int) -> Rect:
    return rect[0] - d, rect[1] - d, rect[2] + 2 * d, rect[3] + 2 * d


def overlap_area(a: Rect, b: Rect) -> int:
    r = intersect_rect(a, b)
    return r[2] * r[3] if r else 0


def magnifier_source(ix: int, iy: int, img_w: int, img_h: int, size: int) -> Rect:
    """Source rect (image pixels) of a ``size`` x ``size`` magnifier centred on pixel (ix, iy),
    shifted (never shrunk) to stay inside the image; smaller images give the whole image."""
    size = max(1, int(size))
    w, h = min(size, max(1, img_w)), min(size, max(1, img_h))
    x = min(max(0, ix - w // 2), max(0, img_w - w))
    y = min(max(0, iy - h // 2), max(0, img_h - h))
    return x, y, w, h


def nearest_corner(corners: Sequence[Point], rect: Rect) -> Point | None:
    """The corner closest to ``rect`` (0 distance when inside); None for no corners."""
    if not corners:
        return None
    x, y, w, h = rect

    def dist(c: Point) -> float:
        dx = max(x - c[0], 0, c[0] - (x + w - 1))
        dy = max(y - c[1], 0, c[1] - (y + h - 1))
        return math.hypot(dx, dy)

    return min(corners, key=dist)


# ----------------------------------------------------------------------------- live helpers


def screen_geoms() -> list[ScreenGeom]:
    """ScreenGeom of every QScreen, primary first. [] before QApplication exists."""
    from PyQt6.QtGui import QGuiApplication

    if QGuiApplication.instance() is None:
        return []
    primary = QGuiApplication.primaryScreen()
    out: list[ScreenGeom] = []
    for s in QGuiApplication.screens():
        g, a = s.geometry(), s.availableGeometry()
        geom = ScreenGeom((g.x(), g.y(), g.width(), g.height()), float(s.devicePixelRatio()),
                          (a.x(), a.y(), a.width(), a.height()), s.name())
        if s is primary:
            out.insert(0, geom)
        else:
            out.append(geom)
    return out


def _win32_monitors() -> list[object]:
    try:
        from ..win32 import dpi

        return list(dpi.monitors())
    except Exception as exc:  # stub (NotImplementedError), ctypes failure, offscreen
        log.debug("win32.dpi.monitors unavailable: %s", exc)
        return []


def monitor_rects() -> list[Rect]:
    """Physical monitor rects (win32.dpi.monitors(); Qt screens as fallback)."""
    mons = _win32_monitors()
    rects = [tuple(m.rect) for m in mons if getattr(m, "rect", (0, 0, 0, 0))[2] > 0]
    return rects or [g.physical for g in screen_geoms()]  # type: ignore[return-value]


def work_rects() -> list[tuple[Rect, Rect]]:
    """(monitor rect, work rect) pairs in physical pixels, primary first."""
    mons = _win32_monitors()
    out = [(tuple(m.rect), tuple(m.work)) for m in mons if getattr(m, "rect", (0, 0, 0, 0))[2] > 0]
    if out:
        return out  # type: ignore[return-value]
    return [(g.physical, g.physical_work) for g in screen_geoms()]
