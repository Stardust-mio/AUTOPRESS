# OWNED BY G2
"""Locate a label in OCR lines (recipe find_text_center, ocr.md section 3.2). Pure Python.

``query`` may hold alternatives separated by "|" (textutil.split_alternatives) - EXCEPT in REGEX
mode, where the whole query is one pattern (a regex has its own "|", e.g. ``^(OK|確定)$``; T27).
Matching:
EXACT    textutil.norm_match(line.text) == norm_match(alternative)  (safest: 0 wrong clicks)
CONTAINS norm_match(alternative) is a substring of norm_match(line.text): the point is the
         centre of the proportional sub-box (CJK characters count double)
REGEX    re.search(query, line.text, re.IGNORECASE): sub-box of the match span
Lines with score < min_score are ignored. Best hit = (exact match first, then higher score).

Details:
* Click point of a hit = centre of the sub-box of the matched span, interpolated along the top
  and bottom edges of the line quad (for a whole-line match: the centre of the quad).
* One line can hold several hits (every non-overlapping occurrence of every alternative), so
  ``nth`` also counts two buttons that OCR merged into one line.
* REGEX: zero-length matches are ignored (``兌換|`` would otherwise match every line); an
  invalid pattern finds nothing (models validation reports it as an ERROR).
* Reading order = rows top to bottom (``OcrResult.rows()``: lines sharing half their height
  form a row), then left to right, then by position inside the line.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from ..models import OcrLine, OcrResult, TextHit, TextMatch
from ..textutil import norm_match, split_alternatives

log = logging.getLogger(__name__)


@dataclass
class _Span:
    start: int
    end: int
    text: str  # the string the span indexes (normalised text, or the raw text for REGEX)
    exact: bool


def _weights(s: str) -> list[float]:
    return [2.0 if unicodedata.east_asian_width(c) in "WF" else 1.0 for c in s]


def _sub_box_centre(line: OcrLine, span: _Span) -> tuple[float, float]:
    """Centre of the part of the line quad that holds ``span`` (proportional, wide chars x2)."""
    quad = line.quad
    if len(quad) != 4:
        return line.center()
    w = _weights(span.text)
    total = sum(w)
    if total <= 0 or span.end <= span.start:
        a, b = 0.0, 1.0
    else:
        a, b = sum(w[: span.start]) / total, sum(w[: span.end]) / total
    m = (a + b) / 2.0
    (tlx, tly), (trx, try_), (brx, bry), (blx, bly) = quad
    x = (tlx + (trx - tlx) * m + blx + (brx - blx) * m) / 2.0
    y = (tly + (try_ - tly) * m + bly + (bry - bly) * m) / 2.0
    return float(x), float(y)


def _plain_spans(text: str, alternatives: Sequence[str], match: TextMatch) -> list[_Span]:
    n = norm_match(text)
    spans: list[_Span] = []
    for alt in alternatives:
        t = norm_match(alt)
        if not t or not n:
            continue
        if match is TextMatch.EXACT:
            if n == t:
                spans.append(_Span(0, len(n), n, True))
            continue
        i = n.find(t)
        while i >= 0:
            spans.append(_Span(i, i + len(t), n, n == t))
            i = n.find(t, i + len(t))
    return spans


def _regex_spans(text: str, pattern: re.Pattern[str]) -> list[_Span]:
    whole = norm_match(text)
    spans = []
    for m in pattern.finditer(text):
        if m.end() <= m.start():
            continue  # zero-length match: never a hit
        spans.append(_Span(m.start(), m.end(), text, bool(whole) and norm_match(m.group(0)) == whole))
    return spans


def _dedupe(spans: list[_Span]) -> list[_Span]:
    """Non-overlapping spans in position order (earlier start first, then longer)."""
    spans.sort(key=lambda s: (s.start, -(s.end - s.start)))
    out: list[_Span] = []
    for s in spans:
        if out and s.start < out[-1].end:
            continue
        out.append(s)
    return out


def _reading_order(lines: Sequence[OcrLine]) -> list[int]:
    return [i for row in OcrResult(lines=list(lines)).rows() for i in row.line_indices]


def _lines_of(lines: Sequence[OcrLine] | OcrResult) -> list[OcrLine]:
    return list(lines.lines) if isinstance(lines, OcrResult) else list(lines)


def find_all(lines: Sequence[OcrLine], query: str, match: TextMatch = TextMatch.EXACT,
             min_score: float = 0.5) -> list[TextHit]:
    """All hits in reading order (rows top to bottom, then left to right)."""
    items = _lines_of(lines)
    match = TextMatch(match)
    query = query or ""
    pattern: re.Pattern[str] | None = None
    alternatives: list[str] = []
    if match is TextMatch.REGEX:
        if not query.strip():
            return []
        try:
            pattern = re.compile(query, re.IGNORECASE)
        except re.error as exc:
            log.warning("invalid text pattern %r: %s", query, exc)
            return []
    else:
        alternatives = split_alternatives(query)
        if not alternatives:
            return []
    hits: list[TextHit] = []
    for i in _reading_order(items):
        line = items[i]
        if line.score < min_score or not line.text:
            continue
        spans = _regex_spans(line.text, pattern) if pattern is not None else \
            _plain_spans(line.text, alternatives, match)
        for span in _dedupe(spans):
            x, y = _sub_box_centre(line, span)
            hits.append(TextHit(x=x, y=y, line_index=i, text=line.text, score=float(line.score), exact=span.exact))
    return hits


def find_text(lines: Sequence[OcrLine], query: str, match: TextMatch = TextMatch.EXACT,
              nth: int = 0, min_score: float = 0.5) -> TextHit | None:
    """The best hit (``nth`` = 0) or the ``nth`` hit (1-based) in reading order; None if none."""
    hits = find_all(lines, query, match, min_score)
    if not hits:
        return None
    if nth and nth > 0:
        return hits[nth - 1] if nth <= len(hits) else None
    best = hits[0]
    for h in hits[1:]:  # strict ">" keeps the first (reading order) of equal hits
        if (h.exact, h.score) > (best.exact, best.score):
            best = h
    return best


def text_present(lines: Sequence[OcrLine], query: str, match: TextMatch = TextMatch.CONTAINS,
                 min_score: float = 0.5) -> bool:
    """True when ``query`` (alternatives, or one regex) is found in at least one line."""
    return bool(find_all(lines, query, match, min_score))
