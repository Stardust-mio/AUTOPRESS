# OWNED BY G2 - replace this stub
"""Locate a label in OCR lines (recipe find_text_center, ocr.md section 3.2). Pure Python.

``query`` may hold alternatives separated by "|" (textutil.split_alternatives) - EXCEPT in REGEX
mode, where the whole query is one pattern (a regex has its own "|", e.g. ``^(OK|確定)$``; T27).
Matching:
EXACT    textutil.norm_match(line.text) == norm_match(alternative)  (safest: 0 wrong clicks)
CONTAINS norm_match(alternative) is a substring of norm_match(line.text): the point is the
         centre of the proportional sub-box (CJK characters count double)
REGEX    re.search(query, line.text, re.IGNORECASE): sub-box of the match span
Lines with score < min_score are ignored. Best hit = (exact match first, then higher score).
"""

from __future__ import annotations

from collections.abc import Sequence

from ..models import OcrLine, TextHit, TextMatch

__stub__ = True


def find_text(lines: Sequence[OcrLine], query: str, match: TextMatch = TextMatch.EXACT,
              nth: int = 0, min_score: float = 0.5) -> TextHit | None:
    """The best hit (``nth`` = 0) or the ``nth`` hit (1-based) in reading order; None if none."""
    raise NotImplementedError


def find_all(lines: Sequence[OcrLine], query: str, match: TextMatch = TextMatch.EXACT,
             min_score: float = 0.5) -> list[TextHit]:
    """All hits in reading order (rows top to bottom, then left to right)."""
    raise NotImplementedError


def text_present(lines: Sequence[OcrLine], query: str, match: TextMatch = TextMatch.CONTAINS,
                 min_score: float = 0.5) -> bool:
    raise NotImplementedError
