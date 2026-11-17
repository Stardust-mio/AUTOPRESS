# OWNED BY G1
"""Find codes in pasted text, files and OCR results (ocr_common.extract_codes, ocr.md section 7).

Text is cut into lines and every line into runs of code-like characters (ASCII letters and
digits, separators, spaces and tabs; OCR text also allows normalize.OCR_CODE_SYMBOLS). A run is
split at spaces into tokens and scanned left to right:
* a token that fits the format on its own is a candidate by itself (so a line listing several
  codes gives several candidates, never their concatenation);
* otherwise consecutive tokens that do not fit alone are joined ("ABCD 1234", "XXXXX XXXXX
  XXXXX" for Steam) - only tokens that are not word-like (``is_likely_code``) - and the longest
  join that fits wins. The join stops growing once it holds more than fmt.max_len (or
  sum(fmt.groups)) code characters, so the work is linear in the text length (T35).
* ``likely`` (pre-checked in previews): ``is_likely_code`` of the token; a join of several tokens
  is only "likely" for formats with a fixed length (groups or min_len == max_len), because joined
  words ("FREE GIFT CODE") are frequent in announcements.
Candidates are de-duplicated by models.code_key (first occurrence kept; it becomes ``likely``
when any occurrence was).
"""

from __future__ import annotations

import functools
import re
import string
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from ..i18n import tr
from ..models import SEPARATOR_CHARS, CodeCandidate, CodeFormat, OcrResult
from .normalize import (
    OCR_CODE_SYMBOLS,
    FormatSpec,
    fit,
    flag_indices,
    lookalike_indices,
    normalize_spans,
    normalize_text,
    repair_char,
    spec_for,
)

_LINE_SPLIT = re.compile(r"\r\n|[\n\r\x0b\x0c\x1c-\x1e\x85\u2028\u2029]")
_TOKEN = re.compile(r"[^ \t]+")
_DATE = re.compile(r"\d{4}[-_]\d{1,2}[-_]\d{1,2}|\d{1,2}[-_]\d{1,2}[-_]\d{4}")
_DIGIT = re.compile(r"[0-9]")
_LETTERS = re.compile(r"[A-Za-z]+")
_KEY_DELETE = str.maketrans("", "", SEPARATOR_CHARS + " \t\n")  # = models.code_key for normalised codes
_MAX_JOIN_TOKENS = 64


@functools.lru_cache(maxsize=32)
def _run_pattern(seps: str, ocr: bool) -> re.Pattern[str]:
    chars = string.ascii_letters + string.digits + seps + (OCR_CODE_SYMBOLS if ocr else "")
    return re.compile("[" + re.escape(chars) + " \t]+")


def _likely(token: str, case_sensitive: bool) -> bool:
    """The ``likely`` rule on normalised text (see is_likely_code)."""
    t = "".join(token.split())
    if _DATE.fullmatch(t):
        return False
    if _DIGIT.search(t):
        return True
    letters = "".join(_LETTERS.findall(t))
    if not letters:
        return False  # only symbols, e.g. "||||||" read by OCR
    if not case_sensitive:
        return letters.isupper()
    if letters.islower():
        return False
    return not (letters[0].isupper() and (len(letters) == 1 or letters[1:].islower()))


@dataclass
class _Line:
    source: str  # the line as written (OCR: the row text)
    norm: str
    starts: Sequence[int]
    ends: Sequence[int]


@dataclass
class _Hit:
    start: int  # in the normalised line
    end: int
    code: str
    repaired: list[int]
    src: list[int]  # per code character: index in the normalised line, -1 = inserted separator
    likely: bool


def _split_lines(text: str) -> Iterator[str]:
    pos = 0
    for m in _LINE_SPLIT.finditer(text):
        yield text[pos:m.start()]
        pos = m.end()
    yield text[pos:]


def _prepare(text: str) -> list[_Line]:
    out: list[_Line] = []
    for line in _split_lines(text):
        if line.strip():
            norm, starts, ends = normalize_spans(line)
            out.append(_Line(line, norm, starts, ends))
    return out


def _chars_ok(token: str, spec: FormatSpec) -> bool:
    if spec.clean_re.fullmatch(token.upper() if not spec.case_sensitive else token):
        return True
    for ch in token:
        if ch in spec.input_seps:
            continue
        c = chr(ord(ch) - 32) if not spec.case_sensitive and "a" <= ch <= "z" else ch
        if c not in spec.allowed and repair_char(c, spec.allowed) is None:
            return False
    return True


def _scan(norm: str, spec: FormatSpec, ocr: bool, want_src: bool) -> Iterator[_Hit]:
    """Candidate windows of one normalised line, left to right."""
    fixed = bool(spec.groups) or spec.min_len == spec.max_len
    limit = spec.limit
    seps = spec.input_seps
    cs = spec.case_sensitive
    for run in _run_pattern(seps, ocr).finditer(norm):
        base = run.start()
        toks = [(base + m.start(), base + m.end()) for m in _TOKEN.finditer(run.group())]
        texts = [norm[s:e] for s, e in toks]
        counts = [len(t) - sum(map(t.count, seps)) for t in texts]
        alone = [fit(t, spec, want_src=want_src) if 0 < n <= limit else None for t, n in zip(texts, counts)]
        n_tok = len(toks)
        join_ok: list[bool | None] = [None] * n_tok

        def joinable(k: int) -> bool:
            ok = join_ok[k]
            if ok is None:
                ok = join_ok[k] = (0 < counts[k] < limit and alone[k] is None and _chars_ok(texts[k], spec)
                                   and _likely(texts[k], cs))
            return ok

        i = 0
        while i < n_tok:
            single = alone[i]
            if single is not None:
                code, rep, src = single
                yield _Hit(toks[i][0], toks[i][1], code, rep, [toks[i][0] + s if s >= 0 else -1 for s in src],
                           _likely(texts[i], cs))
                i += 1
                continue
            if not joinable(i):
                i += 1
                continue
            best: tuple[int, tuple[str, list[int], list[int]]] | None = None
            total = counts[i]
            k = i + 1
            while k < n_tok and k - i < _MAX_JOIN_TOKENS:
                if counts[k] and not joinable(k):
                    break
                total += counts[k]
                if total > limit:
                    break
                if counts[k] and spec.length_ok(total):
                    res = fit(norm[toks[i][0]:toks[k][1]], spec, want_src=want_src)
                    if res is not None:
                        best = (k, res)
                k += 1
            if best is None:
                i += 1
                continue
            k, (code, rep, src) = best
            start = toks[i][0]
            yield _Hit(start, toks[k][1], code, rep, [start + s if s >= 0 else -1 for s in src],
                       fixed and _likely(norm[start:toks[k][1]], cs))
            i = k + 1


def _text_candidates(lines: Sequence[_Line], fmt: CodeFormat) -> list[CodeCandidate]:
    spec = spec_for(fmt)
    out: list[CodeCandidate] = []
    if not spec.valid:
        return out
    keys: dict[str, CodeCandidate] = {}
    for line in lines:
        for hit in _scan(line.norm, spec, ocr=False, want_src=False):
            key = hit.code.translate(_KEY_DELETE)
            seen = keys.get(key)
            if seen is not None:
                seen.likely = seen.likely or hit.likely
                continue
            cand = CodeCandidate(code=hit.code, raw=line.source[line.starts[hit.start]:line.ends[hit.end - 1]],
                                 char_confs=None, flagged=list(hit.repaired),
                                 lookalikes=lookalike_indices(hit.code, fmt), repaired=list(hit.repaired),
                                 line_index=-1, likely=hit.likely)
            keys[key] = cand
            out.append(cand)
    return out


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
    lower-case or only Capitalised). ``raw`` is the source text of the window as written
    (before NFKC). Window selection: module docstring."""
    if not text:
        return []
    return _text_candidates(_prepare(text), fmt)


def extract_many(text: str, formats: Sequence[CodeFormat]) -> list[list[CodeCandidate]]:
    """extract_from_text for several formats, normalising the text only once (detect_format)."""
    lines = _prepare(text) if text else []
    return [_text_candidates(lines, fmt) for fmt in formats]


def extract_from_ocr(result: OcrResult, fmt: CodeFormat, review_threshold: float = 0.95) -> list[CodeCandidate]:
    """Like extract_from_text over ``result.rows()`` (normalize_text with ``ocr=True``), plus
    OCR data: ``line_index`` of the source line, ``char_confs`` mapped from OcrLine.char_confs
    (or the line score when absent), ``flagged`` = normalize.flag_indices(...,
    threshold=review_threshold, repaired=...) (low confidence or repaired -> REVIEW),
    ``lookalikes`` = normalize.lookalike_indices (highlight only), ``repaired``.
    A code spread over two OCR lines of one row gets the line holding most of its characters.
    Separator positions get confidence 1.0 (they are never flagged and never lower
    ``confidence``); OcrLine.char_confs whose length differs from the line text are ignored."""
    spec = spec_for(fmt)
    out: list[CodeCandidate] = []
    if not spec.valid:
        return out
    keys: dict[str, CodeCandidate] = {}
    for row in result.rows():
        pieces: list[str] = []
        src_line: list[int] = []
        src_conf: list[float] = []
        for li in row.line_indices:
            if not 0 <= li < len(result.lines):
                continue
            line = result.lines[li]
            if pieces:
                pieces.append(" ")
                src_line.append(-1)
                src_conf.append(1.0)
            confs = line.char_confs if line.char_confs is not None and len(line.char_confs) == len(line.text) else None
            for k, ch in enumerate(line.text):
                pieces.append(ch)
                src_line.append(li)
                src_conf.append(float(confs[k]) if confs is not None else float(line.score))
        row_text = "".join(pieces)
        if not row_text.strip():
            continue
        norm, starts, ends = normalize_spans(row_text, ocr=True)
        for hit in _scan(norm, spec, ocr=True, want_src=True):
            key = hit.code.translate(_KEY_DELETE)
            seen = keys.get(key)
            if seen is not None:
                seen.likely = seen.likely or hit.likely
                continue
            confs_out: list[float] = []
            votes: dict[int, int] = {}
            for ch, pos in zip(hit.code, hit.src):
                if pos < 0 or ch in spec.input_seps or ch in spec.separator:
                    confs_out.append(1.0)
                    continue
                a, b = starts[pos], ends[pos]
                confs_out.append(min(src_conf[a:b]))
                if src_line[a] >= 0:
                    votes[src_line[a]] = votes.get(src_line[a], 0) + 1
            cand = CodeCandidate(
                code=hit.code, raw=row_text[starts[hit.start]:ends[hit.end - 1]], char_confs=confs_out,
                flagged=flag_indices(hit.code, confs_out, fmt, threshold=review_threshold, repaired=hit.repaired),
                lookalikes=lookalike_indices(hit.code, fmt), repaired=list(hit.repaired),
                line_index=max(votes, key=lambda li: (votes[li], -li)) if votes else -1, likely=hit.likely)
            keys[key] = cand
            out.append(cand)
    return out


def _length_reason(spec: FormatSpec) -> str:
    if spec.groups:
        n = sum(spec.groups)
        return tr(f"長度須為 {n} 碼", f"Must be {n} characters")
    if spec.min_len == spec.max_len:
        return tr(f"長度須為 {spec.min_len} 碼", f"Must be {spec.min_len} characters")
    return tr(f"長度須為 {spec.min_len}–{spec.max_len} 碼", f"Must be {spec.min_len}-{spec.max_len} characters")


def validate_code(text: str, fmt: CodeFormat) -> tuple[str | None, str]:
    """For editable cells: (normalised code, "") when ``text`` fits ``fmt``, else
    (None, localized reason such as "長度須為 16 碼" / "Must be 16 characters").
    Stricter than extraction: a character outside the charset is never repaired here - the
    reason names it (and its likely intended character), so the user fixes it."""
    spec = spec_for(fmt)
    norm = normalize_text(text or "")
    if not norm.strip():
        return None, tr("請輸入序號", "Enter a code")
    if not spec.allowed:
        return None, tr("序號字元集格式錯誤", "Invalid code character set")
    if not spec.valid:
        return None, tr("序號格式設定有誤", "The code format settings are invalid")
    res = fit(norm, spec, repair=False)
    if res is not None:
        return res[0], ""
    count = 0
    for ch in norm:
        if ch in spec.input_seps or ch.isspace():
            continue
        c = chr(ord(ch) - 32) if not spec.case_sensitive and "a" <= ch <= "z" else ch
        if c not in spec.allowed:
            hint = repair_char(c, spec.allowed)
            if hint:
                return None, tr(f"「{ch}」不是允許的字元，是不是「{hint}」？",
                                f'"{ch}" is not allowed here - did you mean "{hint}"?')
            return None, tr(f"含有不允許的字元「{ch}」", f'Contains a character that is not allowed: "{ch}"')
        count += 1
    if not spec.length_ok(count):
        return None, _length_reason(spec)
    return None, tr("不符合設定檔的序號格式", "Does not match the profile's code pattern")


def is_likely_code(token: str, fmt: CodeFormat) -> bool:
    """The ``likely`` heuristic of extract_from_text for one source token. Also False for a
    date written with separators (2026-11-17, 17-11-2026) and for a token made of symbols only."""
    return _likely(normalize_text(token or ""), bool(fmt.case_sensitive))
