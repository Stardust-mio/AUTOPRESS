# OWNED BY G1 - replace this stub
"""Text and code normalisation, look-alike flagging and segment splitting (pure Python).

Reference: docs/research/ocr.md section 7, docs/research/scripts/ocr/ocr_common.py
(CodeSpec.normalize, CONFUSABLE, DASHES), docs/research/ux.md section 3.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..models import CodeFormat, SplitMode

__stub__ = True

DASHES: str = "‐‑‒–—―−－ー一"
"""Dash look-alikes mapped to "-" by normalize_text for EVERY source (ocr_common.DASHES)."""

OCR_DASHES: str = "_~"
"""Mapped to "-" only for OCR sources (OCR misreads "-" as "_" or "~"). In pasted / file text
"_" is a real separator kept as written and "~" is not code text (SPEC 5.4, decision PX-19)."""

LOOKALIKE_GROUPS: tuple[str, ...] = ("0ODQ", "1Il|", "2Z", "5S", "6G", "8B", "UV", "VY")
"""Visually confusable characters (ux.md section 3). Highlighted, never fixed silently, and NOT
a reason for REVIEW on their own (nearly every code contains one - decision PX-18)."""


def normalize_text(text: str, ocr: bool = False) -> str:
    """Normalise imported text: NFKC (full-width -> ASCII), zero-width characters and BOM
    removed, every DASHES character (plus OCR_DASHES when ``ocr``) -> "-", CRLF / CR -> LF.
    Applied to every import."""
    raise NotImplementedError


def normalize_code(raw: str, fmt: CodeFormat) -> tuple[str | None, list[int]]:
    """Fit one candidate string to ``fmt``.

    Steps: normalize_text; drop spaces; upper-case unless fmt.case_sensitive; repair ONLY
    characters outside fmt.allowed_chars() and outside models.SEPARATOR_CHARS through their
    confusable group (o -> O/0, l i | ! -> I/1, $ § -> S/5, z -> Z/2 ..., else a case change);
    valid characters are never touched; check min_len/max_len (or sum(fmt.groups)) counting
    charset characters only. Separators: with fmt.groups every separator is removed and
    fmt.separator re-inserted between the groups; WITHOUT groups the source separators ("-",
    "_") are kept where they stand (runs collapsed to one, none at the start or end), so
    "ABCD-1234-EF" stays as written and type_code's SEPARATOR split can use them (T10).
    Full-match fmt.regex when set.
    Returns (code, indices_of_repaired_characters_in_code) or (None, []) if it does not fit."""
    raise NotImplementedError


def lookalike_indices(code: str, fmt: CodeFormat) -> list[int]:
    """Indices of characters that have a LOOKALIKE_GROUPS partner which fmt also allows
    (e.g. both 0 and O allowed -> every 0 and O; Nintendo excludes O -> 0 is not). These end up
    in CodeCandidate / CodeItem ``lookalikes`` (highlight only)."""
    raise NotImplementedError


def flag_indices(code: str, char_confs: Sequence[float] | None, fmt: CodeFormat,
                 threshold: float = 0.95, repaired: Sequence[int] = ()) -> list[int]:
    """Characters that must be checked before the code may run (``flagged`` -> REVIEW):
    {i: conf[i] < threshold} U repaired. Sorted and unique. ``char_confs`` None -> confidence is
    not considered (text sources: only repaired characters). Separators are never flagged."""
    raise NotImplementedError


def strip_separators(code: str, separators: str = "-_") -> str:
    """``code`` without any character from ``separators`` (and without whitespace)."""
    raise NotImplementedError


def split_code(code: str, mode: SplitMode, separators: str = "-_", group_sizes: Sequence[int] = ()) -> list[str]:
    """Segments for multi-field entry (type_code split).

    NONE -> [code]. SEPARATOR -> split at any character of ``separators``, empty parts dropped
    (works for groupless formats too, because their codes keep the source separators; segments
    may have different lengths, e.g. 4-6-2). FIXED -> separators removed first, then consecutive
    chunks of ``group_sizes``; characters beyond sum(group_sizes) form one extra last segment.
    ValueError for FIXED without sizes."""
    raise NotImplementedError
