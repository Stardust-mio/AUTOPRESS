# OWNED BY G4
"""Resolve a profile's points and regions against the live target window (dry-run overlay)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..models import (
    ClientPoint,
    ClientRegion,
    PreviewKind,
    PreviewMark,
    Profile,
    Rect,
    StepType,
    intersect_rect,
    point_in_rect,
    resolve_point,
    resolve_region,
)

if TYPE_CHECKING:
    from .backend import Backend

log = logging.getLogger(__name__)

# (params attribute, kind) per step type, in the order the marks are produced
_GEOMETRY: dict[StepType, tuple[tuple[str, PreviewKind], ...]] = {
    StepType.CLICK_POINT: (("point", PreviewKind.POINT),),
    StepType.CLICK_TEXT: (("region", PreviewKind.SEARCH_REGION), ("fallback_point", PreviewKind.FALLBACK_POINT)),
    StepType.TYPE_CODE: (("verify_region", PreviewKind.REGION),),
    StepType.WAIT_TEXT: (("region", PreviewKind.SEARCH_REGION),),
    StepType.OCR_CHECK: (("region", PreviewKind.REGION),),
}


def _point_ok(backend: Backend, profile: Profile, hwnd: int, pid: int, client: Rect, x: int, y: int) -> bool:
    if not point_in_rect(client, x, y):
        return False
    try:
        root = backend.window_at(x, y, skip_own=True)  # AutoPress's own windows do not count (T30)
    except Exception:  # noqa: BLE001 - cannot tell: do not mark it red
        return True
    if not root or root == hwnd:
        return True
    if profile.target.allow_same_process:
        try:
            return backend.window_pid(root) == pid
        except Exception:  # noqa: BLE001
            return False
    return False


def preview_profile(profile: Profile, hwnd: int, *, backend: Backend | None = None) -> list[PreviewMark]:
    """One PreviewMark per recorded geometry of every enabled step, in step order: click_point
    point, click_text search region + fallback point, type_code verify region, wait_text
    region, ocr_check region. ``label`` is the step's display title without its number (the
    overlay's badge shows step_index + 1). Physical rects via models.resolve_point/resolve_region with
    ``profile.coord_mode`` and the window's DPI. ``ok`` is False when a point is outside the
    client area or covered by another window - AutoPress's own windows do not count
    (win32.windows.window_at(..., skip_own=True)): they are hidden during runs. Regions are ok
    when they lie inside the client area. Sends no input. Empty list if the window is gone.
    RunFlow also passes these rects to MiniBar.place_away_from."""
    own_backend = backend is None
    if backend is None:
        from .backend import RealBackend

        backend = RealBackend(None)
    try:
        info = backend.window_info(hwnd) if hwnd else None
        if info is None:
            return []
        try:
            client = backend.client_rect(hwnd)
        except OSError:
            return []
        if client[2] <= 0 or client[3] <= 0:
            return []
        try:
            dpi = int(backend.window_dpi(hwnd)) or 96
        except Exception:  # noqa: BLE001
            dpi = 96
        marks: list[PreviewMark] = []
        for i, step in enumerate(profile.steps):
            if not step.enabled or step.type is StepType.UNKNOWN:
                continue
            label = step.display_title()  # the badge carries the number
            for attr, kind in _GEOMETRY.get(step.type, ()):
                value = getattr(step.params, attr, None)
                if isinstance(value, ClientPoint):
                    x, y = resolve_point(client, value, profile.coord_mode, dpi=dpi)
                    ok = _point_ok(backend, profile, hwnd, info.pid, client, x, y)
                    marks.append(PreviewMark(step_index=i, step_id=step.id, kind=kind, rect=(x, y, 1, 1),
                                             label=label, ok=ok))
                elif isinstance(value, ClientRegion):
                    rect = resolve_region(client, value, profile.coord_mode, dpi=dpi)
                    ok = intersect_rect(rect, client) == rect
                    marks.append(PreviewMark(step_index=i, step_id=step.id, kind=kind, rect=rect, label=label, ok=ok))
        return marks
    finally:
        if own_backend:
            try:
                backend.close()
            except Exception:  # noqa: BLE001
                pass
