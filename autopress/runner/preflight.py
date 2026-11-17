# OWNED BY G4 - replace this stub
"""Checks before a run (SPEC section 7.2 lists every issue key, level, message and action)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..models import PreflightReport, Profile, Settings

__stub__ = True

if TYPE_CHECKING:
    from .backend import Backend


def run_preflight(profile: Profile, settings: Settings, *, code_count: int, ocr_state: str,
                  target_hwnd: int = 0, backend: Backend | None = None,
                  unassigned_count: int = 0) -> PreflightReport:
    """Validate the profile (errors, first three warnings), check the target rules (forbidden
    exe, browser title keyword), find the target (``target_hwnd`` first when still alive),
    check elevation/UIPI, client size and DPI vs recorded ones, OCR availability, blank capture
    (only when the target is not minimized; AutoPress's own windows are ignored, never sampled),
    codes (``unassigned_count`` = queued codes without a game), tested state, interval, and add
    the ``estimate`` line. Every key of SPEC 7.2. Sends no input. ``backend`` None -> a
    RealBackend without OCR."""
    raise NotImplementedError
