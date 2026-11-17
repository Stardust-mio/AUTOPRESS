# OWNED BY G4 - replace this stub
"""Execution of one step (internal to the runner; the UI uses RunSession.test_step)."""

from __future__ import annotations

from dataclasses import dataclass

from ..models import Point, Rect, ResultClass, Step

__stub__ = True


class StepError(Exception):
    """A step could not do its job (text not found, OCR failed or timed out, capture failed,
    unmappable character, typed text mismatch...). ``str(exc)`` is localized (SPEC 7.1).
    Outcome (SPEC 2.5, PX-07): a result already read by ocr_check is KEPT (the error is logged
    as a warning); otherwise REVIEW when the attempt was possibly submitted; FAILED only for
    errors before submitting. Guard errors (InjectionAborted) pause instead."""


@dataclass
class StepOutcome:
    ok: bool = True
    message: str = ""  # localized
    result: ResultClass | None = None  # set by ocr_check
    matched_keyword: str = ""
    ocr_text: str = ""
    point: Point | None = None
    rect: Rect | None = None
    evidence_path: str = ""
    sent_input: bool = False  # the step injected input (used for "possibly submitted")


def render_template(text: str, code: str, index: int) -> str:
    """Fill {code}, {index} (1-based), {date} (YYYY-MM-DD) and {time} (HH:MM:SS); unknown
    placeholders and stray braces are left as they are."""
    raise NotImplementedError


def execute_step(step: Step, ctx: object) -> StepOutcome:
    """Run ``step`` with the runner's step context (G4-internal type). Raises StepError,
    win32.input.InjectionAborted subclasses and control.StopRequested. Rules from SPEC 5.3:
    click_text not found -> fallback_point, else on_not_found (FAIL = StepError, CONTINUE = log
    and go on); click_text offsets x window_dpi / 96; ocr_check with only_new_text classifies
    only lines absent from the baseline read taken before profile.first_submit_index()."""
    raise NotImplementedError
