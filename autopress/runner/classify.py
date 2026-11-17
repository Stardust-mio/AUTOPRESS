# OWNED BY G4
"""Classify a result message by keyword groups (ux.md section 4, bench_u3.py classify)."""

from __future__ import annotations

from ..models import KeywordConfig, ResultClass


def classify_text(text: str, keywords: KeywordConfig) -> tuple[ResultClass, str]:
    """(class, matched keyword) for OCR text: ``return keywords.classify(text)``. The rule lives
    in models.KeywordConfig.classify (A1, tested on the U3 and critique sentences): squash both
    sides; fuzzy (1 edit) only for non-CJK keywords of FUZZY_MIN_LEN (9)+ characters; SUCCESS
    together with another class or a NEGATION_MARKERS entry -> UNKNOWN; else the first class in
    ``keywords.order`` with a hit. No hit (or empty text) -> (UNKNOWN, "")."""
    return keywords.classify(text or "")
