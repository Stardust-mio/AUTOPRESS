# OWNED BY G7
"""Where the mini bar goes (pure function; private helper of ui.minibar).

All rects are PHYSICAL screen pixels (x, y, w, h). The bar must never sit on a click point or
an OCR region of the running profile (T01 / PX-03): the runner masks it in every capture, but a
bar on a click point would still swallow the click (the guard then pauses).
Order (MiniBar.place_away_from docstring):
1. the saved position when it lies on a work area and intersects no avoid rect;
2. a monitor that does not contain the target client rect;
3. a corner of the target's monitor outside the target;
4. a candidate inside the target that intersects no avoid rect (points inflated by 24 px);
5. the candidate with the smallest overlap, in the compact one-line form.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..models import Point, Rect, intersect_rect
from .overlays_geom import inflate, overlap_area

__all__ = ["MARGIN", "POINT_PAD", "candidates", "choose_position"]

MARGIN = 16  # distance from the work-area edges
POINT_PAD = 24  # click points are inflated by this much before testing overlaps


def _avoid_rects(avoid: Sequence[Rect]) -> list[Rect]:
    out = []
    for r in avoid:
        if r[2] <= 1 and r[3] <= 1:
            out.append(inflate(r, POINT_PAD))
        else:
            out.append(tuple(r))  # type: ignore[arg-type]
    return out


def candidates(area: Rect, size: tuple[int, int], margin: int = MARGIN) -> list[Point]:
    """Top-left points of the bar at the corners and edge centres of ``area`` (preference
    order: bottom-right, top-right, bottom-left, top-left, bottom-centre, top-centre)."""
    x, y, w, h = area
    bw, bh = size
    left, right = x + margin, x + w - bw - margin
    top, bottom = y + margin, y + h - bh - margin
    cx = x + (w - bw) // 2
    out: list[Point] = []
    for p in ((right, bottom), (right, top), (left, bottom), (left, top), (cx, bottom), (cx, top)):
        if p not in out:
            out.append(p)
    return out


def _rect(p: Point, size: tuple[int, int]) -> Rect:
    return p[0], p[1], size[0], size[1]


def _inside(inner: Rect, outer: Rect) -> bool:
    return (outer[0] <= inner[0] and outer[1] <= inner[1]
            and inner[0] + inner[2] <= outer[0] + outer[2] and inner[1] + inner[3] <= outer[1] + outer[3])


def _hits(r: Rect, rects: Sequence[Rect]) -> bool:
    return any(intersect_rect(r, a) is not None for a in rects)


def choose_position(size: tuple[int, int], compact_size: tuple[int, int],
                    monitors: Sequence[tuple[Rect, Rect]], avoid: Sequence[Rect] = (),
                    target: Rect | None = None, saved: Point | None = None,
                    margin: int = MARGIN) -> tuple[Point, bool]:
    """(physical top-left, compact) for a bar of ``size`` (``compact_size`` for step 5).
    ``monitors`` = (monitor rect, work rect) pairs, primary first."""
    avoid_r = _avoid_rects(avoid)
    works = [w for _m, w in monitors] or [(0, 0, 1920, 1080)]
    # 1. the saved position
    if saved is not None:
        r = _rect(saved, size)
        if any(_inside(r, w) for w in works) and not _hits(r, avoid_r):
            return (int(saved[0]), int(saved[1])), False
    if target is None or target[2] <= 0 or target[3] <= 0:
        for p in candidates(works[0], size, margin):
            if not _hits(_rect(p, size), avoid_r):
                return p, False
        return candidates(works[0], size, margin)[0], False
    # 2. a monitor that does not contain the target
    for mon, work in monitors:
        if intersect_rect(mon, target) is None:
            for p in candidates(work, size, margin):
                if not _hits(_rect(p, size), avoid_r):
                    return p, False
    # the target's monitor = largest overlap
    tmon = max(monitors, key=lambda m: overlap_area(m[0], target)) if monitors else ((0, 0, 1920, 1080),) * 2
    twork = tmon[1]
    # 3. a corner of the target's monitor outside the target
    for p in candidates(twork, size, margin):
        r = _rect(p, size)
        if intersect_rect(r, target) is None and not _hits(r, avoid_r):
            return p, False
    # 4. inside the target, but away from every click point / region
    inner = intersect_rect(target, twork) or twork
    cands = candidates(inner, size, margin) + [p for p in candidates(twork, size, margin)]
    for p in cands:
        r = _rect(p, size)
        if _inside(r, twork) and not _hits(r, avoid_r):
            return p, False
    # 5. compact form, smallest overlap
    ccands = candidates(inner, compact_size, margin) + candidates(twork, compact_size, margin)
    best = min(ccands, key=lambda p: (sum(overlap_area(_rect(p, compact_size), a) for a in avoid_r),
                                       ccands.index(p)))
    return best, True
