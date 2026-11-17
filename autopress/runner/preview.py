# OWNED BY G4 - replace this stub
"""Resolve a profile's points and regions against the live target window (dry-run overlay)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..models import PreviewMark, Profile

__stub__ = True

if TYPE_CHECKING:
    from .backend import Backend


def preview_profile(profile: Profile, hwnd: int, *, backend: Backend | None = None) -> list[PreviewMark]:
    """One PreviewMark per recorded geometry of every enabled step, in step order: click_point
    point, click_text search region + fallback point, type_code verify region, wait_text
    region, ocr_check region. Physical rects via models.resolve_point/resolve_region with
    ``profile.coord_mode`` and the window's DPI. ``ok`` is False when a point is outside the
    client area or covered by another window - AutoPress's own windows do not count
    (win32.windows.window_at(..., skip_own=True)): they are hidden during runs. Sends no input.
    Empty list if the window is gone. RunFlow also passes these rects to MiniBar.place_away_from."""
    raise NotImplementedError
