# OWNED BY G1 - replace this stub
"""Find codes in pasted text, files and OCR results (ocr_common.extract_codes, ocr.md section 7)."""

from __future__ import annotations

from ..models import CodeCandidate, CodeFormat, OcrResult

__stub__ = True


def extract_from_text(text: str, fmt: CodeFormat) -> list[CodeCandidate]:
    """Candidates in reading order, de-duplicated by models.code_key (first occurrence kept).

    normalize_text, then runs of code-like characters (letters, digits, models.SEPARATOR_CHARS,
    spaces); windows of consecutive space-separated tokens are tried with normalize_code (so
    "ABCD 1234" and "兌換碼：ABCD-1234" both work). A window stops growing as soon as its
    charset-character count exceeds fmt.max_len (or sum(fmt.groups)): linear work, a pasted
    1000-word paragraph must take < 200 ms (T35). Text sources carry no confidence;
    ``flagged`` = ``repaired`` (a character outside the charset was changed - shown, and REVIEW
    until confirmed); ``lookalikes`` = normalize.lookalike_indices (highlight only).
    ``likely`` is False for word-like tokens: no digit and (case-insensitive format and the
    source token has lower-case letters, or case-sensitive format and the token is all
    lower-case or only Capitalised)."""
    raise NotImplementedError


def extract_from_ocr(result: OcrResult, fmt: CodeFormat, review_threshold: float = 0.95) -> list[CodeCandidate]:
    """Like extract_from_text over ``result.rows()`` (normalize_text with ``ocr=True``), plus
    OCR data: ``line_index`` of the source line, ``char_confs`` mapped from OcrLine.char_confs
    (or the line score when absent), ``flagged`` = normalize.flag_indices(...,
    threshold=review_threshold, repaired=...) (low confidence or repaired -> REVIEW),
    ``lookalikes`` = normalize.lookalike_indices (highlight only), ``repaired``."""
    raise NotImplementedError


def validate_code(text: str, fmt: CodeFormat) -> tuple[str | None, str]:
    """For editable cells: (normalised code, "") when ``text`` fits ``fmt``, else
    (None, localized reason such as "長度須為 16 碼" / "Must be 16 characters")."""
    raise NotImplementedError


def is_likely_code(token: str, fmt: CodeFormat) -> bool:
    """The ``likely`` heuristic of extract_from_text for one source token."""
    raise NotImplementedError
