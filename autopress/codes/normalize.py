# OWNED BY G1
"""Text and code normalisation, look-alike flagging and segment splitting (pure Python).

Reference: docs/research/ocr.md section 7, docs/research/scripts/ocr/ocr_common.py
(CodeSpec.normalize, CONFUSABLE, DASHES), docs/research/ux.md section 3.

Rules (SPEC 5.4, decisions PX-18, PX-19, T10):
* ``normalize_text`` runs on every import: NFKC (applied per character cluster, so every output
  character can be traced back to its source characters), invisible format characters (zero
  width, BOM, soft hyphen, bidi marks) and control characters removed, dash look-alikes -> "-",
  every line break -> LF. "_" and "~" become "-" only for OCR text.
* ``normalize_code`` fits ONE candidate to a CodeFormat. A valid character is never changed; a
  character outside the charset may be repaired through ``CONFUSABLE`` (or a plain case change)
  and its index is returned, so the caller flags it (REVIEW until the user confirms it).
* Look-alikes are only highlighted (``lookalike_indices``); they never cause REVIEW on their own.

The underscore helpers (``spec_for``, ``fit``, ``normalize_spans``) are shared with
codes.extract; other groups use the public functions only.
"""

from __future__ import annotations

import functools
import logging
import re
import unicodedata
from array import array
from collections.abc import Sequence
from dataclasses import dataclass

from ..models import SEPARATOR_CHARS, CodeFormat, SplitMode

log = logging.getLogger(__name__)

DASHES: str = "‐‑‒–—―−－ー一"
"""Dash look-alikes mapped to "-" by normalize_text for EVERY source (ocr_common.DASHES)."""

OCR_DASHES: str = "_~"
"""Mapped to "-" only for OCR sources (OCR misreads "-" as "_" or "~"). In pasted / file text
"_" is a real separator kept as written and "~" is not code text (SPEC 5.4, decision PX-19)."""

LOOKALIKE_GROUPS: tuple[str, ...] = ("0ODQ", "1Il|", "2Z", "5S", "6G", "8B", "UV", "VY")
"""Visually confusable characters (ux.md section 3). Highlighted, never fixed silently, and NOT
a reason for REVIEW on their own (nearly every code contains one - decision PX-18).
Each group is read as a star around its SECOND character (the shape the others are mistaken
for): 0/O, D/O, Q/O; 1/I, l/I, |/I; 2/Z; 5/S ... So Nintendo, which excludes O, I and Z, has no
look-alike 0, 1 or 2 (D and Q only resemble O)."""

CONFUSABLE: dict[str, str] = {
    "O": "0O", "0": "O0", "o": "O0", "Q": "O0", "D": "0O", "口": "O0",
    "I": "1I", "1": "I1", "l": "I1", "i": "I1", "|": "I1", "!": "I1", "丨": "I1", "工": "I1",
    "S": "5S", "5": "S5", "s": "S5", "$": "S5", "§": "S5",
    "B": "8B", "8": "B8", "Z": "2Z", "2": "Z2", "z": "Z2",
    "G": "6G", "6": "G6", "g": "9G", "q": "9Q", "U": "VU", "V": "UV", "u": "UV", "v": "VU",
}
"""Repair candidates for a character OUTSIDE the format's charset (ocr_common.CONFUSABLE): the
first member the charset allows replaces it. Characters inside the charset are never looked up."""

OCR_CODE_SYMBOLS: str = "|!$§口丨工"
"""Symbols OCR produces for code glyphs (ocr_common.RELAXED). They belong to candidate runs of
OCR text only (pasted "!" ends a sentence) and are repaired through CONFUSABLE (flagged)."""

_LINE_BREAKS = frozenset("\r\n\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029")
_ASCII_DIRTY = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")
_OCR_ASCII = str.maketrans({c: "-" for c in OCR_DASHES})


# =============================================================================== text


def _clean_char(ch: str, dashes: str) -> str:
    """One NFKC output character -> its normalised form ("" = dropped)."""
    if ch in dashes:
        return "-"
    if ch in _LINE_BREAKS:
        return "\n"
    cat = unicodedata.category(ch)
    if cat in ("Cf", "Cs") or (cat == "Cc" and ch != "\t"):
        return ""
    return ch


def normalize_spans(text: str, ocr: bool = False) -> tuple[str, Sequence[int], Sequence[int]]:
    """normalize_text plus, for every output character k, the source span
    ``text[starts[k]:ends[k]]`` it came from (CRLF counts as one line break)."""
    if text.isascii() and not _ASCII_DIRTY.search(text):  # nothing to change: identity spans
        return (text.translate(_OCR_ASCII) if ocr else text), range(len(text)), range(1, len(text) + 1)
    dashes = DASHES + OCR_DASHES if ocr else DASHES
    out: list[str] = []
    starts = array("l")
    ends = array("l")
    combining = unicodedata.combining
    nfkc = unicodedata.normalize
    n = len(text)
    i = 0
    while i < n:
        c = text[i]
        j = i + 1
        if c == "\r" and j < n and text[j] == "\n":
            i = j  # CRLF -> one LF (emitted for the "\n")
            continue
        if c < "\x80" and (j >= n or text[j] < "\u0300" or not combining(text[j])):
            m = ("-" if c in dashes else c) if " " <= c < "\x7f" else _clean_char(c, dashes)
            if m:
                out.append(m)
                starts.append(i)
                ends.append(j)
            i = j
            continue
        while j < n and combining(text[j]):
            j += 1
        for ch in nfkc("NFKC", text[i:j]):
            m = _clean_char(ch, dashes)
            if m:
                out.append(m)
                starts.append(i)
                ends.append(j)
        i = j
    return "".join(out), starts, ends


def normalize_text(text: str, ocr: bool = False) -> str:
    """Normalise imported text: NFKC (full-width -> ASCII), zero-width characters and BOM
    removed, every DASHES character (plus OCR_DASHES when ``ocr``) -> "-", CRLF / CR -> LF.
    Applied to every import. Also drops the other invisible format characters (soft hyphen,
    bidi marks) and control characters except tab and LF."""
    return normalize_spans(text or "", ocr)[0]


# =============================================================================== code fitting


@dataclass(frozen=True)
class FormatSpec:
    """Pre-computed view of a CodeFormat (cached by its field values)."""

    allowed: frozenset[str]
    case_sensitive: bool
    min_len: int
    max_len: int
    groups: tuple[int, ...]
    separator: str  # inserted between groups
    input_seps: str  # characters read as separators in the source text
    regex: re.Pattern[str] | None
    valid: bool
    clean_re: re.Pattern[str]  # fullmatch: only allowed characters and separators (no repair needed)
    sep_run_re: re.Pattern[str]
    sep_delete: dict[int, None]

    @property
    def limit(self) -> int:
        """Largest possible count of code characters."""
        return sum(self.groups) if self.groups else self.max_len

    def length_ok(self, n: int) -> bool:
        if self.groups:
            return n == sum(self.groups)
        return self.min_len <= n <= self.max_len


@functools.lru_cache(maxsize=128)
def _build_spec(charset: str, case_sensitive: bool, min_len: int, max_len: int, groups: tuple[int, ...],
                separator: str, regex: str) -> FormatSpec:
    allowed = CodeFormat(charset=charset, case_sensitive=case_sensitive).allowed_chars()
    seps = SEPARATOR_CHARS
    if len(separator) == 1 and not separator.isalnum() and not separator.isspace() and separator not in seps:
        seps += separator
    pattern: re.Pattern[str] | None = None
    if regex:
        try:
            pattern = re.compile(regex, 0 if case_sensitive else re.IGNORECASE)
        except re.error:
            log.debug("invalid code regex %r ignored", regex)
    valid = bool(allowed) and all(g > 0 for g in groups) and (bool(groups) or 0 < min_len <= max_len)
    sep_class = "[" + re.escape(seps) + "]"
    clean = re.compile("[" + re.escape(allowed + seps) + "]*") if allowed else re.compile(r"(?!)")
    return FormatSpec(frozenset(allowed), case_sensitive, min_len, max_len, groups, separator, seps, pattern, valid,
                      clean, re.compile(sep_class + "+"), str.maketrans("", "", seps))


def spec_for(fmt: CodeFormat) -> FormatSpec:
    try:
        groups = tuple(int(g) for g in fmt.groups)
    except (TypeError, ValueError):
        groups = (0,)
    return _build_spec(str(fmt.charset or ""), bool(fmt.case_sensitive), int(fmt.min_len), int(fmt.max_len),
                       groups, str(fmt.separator or ""), str(fmt.regex or ""))


def repair_char(c: str, allowed: frozenset[str] | set[str]) -> str | None:
    """Replacement for a character outside ``allowed`` (CONFUSABLE, then a case change)."""
    for cand in CONFUSABLE.get(c, ""):
        if cand in allowed:
            return cand
    if c.isascii() and c.isalpha():
        for cand in (c.upper(), c.lower()):
            if cand != c and cand in allowed:
                return cand
    return None


def _fit_clean(window: str, spec: FormatSpec) -> tuple[str, list[int], list[int]] | None | bool:
    """Fast path of fit() without source indices for ASCII windows that need no repair.
    False = not applicable (a character may need a repair; use the full path)."""
    if not window.isascii():
        return False
    t = window.replace(" ", "").replace("\t", "")
    if not spec.case_sensitive:
        t = t.upper()
    if spec.clean_re.fullmatch(t) is None:
        return False
    core = t.translate(spec.sep_delete)
    if not spec.length_ok(len(core)):
        return None
    if spec.groups:
        parts, pos = [], 0
        for g in spec.groups:
            parts.append(core[pos:pos + g])
            pos += g
        code = spec.separator.join(parts)
    else:
        code = spec.sep_run_re.sub(lambda m: m.group()[0], t.strip(spec.input_seps))
    if spec.regex is not None and not (spec.regex.fullmatch(code) or spec.regex.fullmatch(core)):
        return None
    return code, [], []


def fit(window: str, spec: FormatSpec, repair: bool = True,
        want_src: bool = True) -> tuple[str, list[int], list[int]] | None:
    """Fit already normalised text to ``spec``: (code, repaired indices in code, source index in
    ``window`` for every code character, -1 for inserted group separators) or None.
    With ``want_src`` False the source indices may be left empty (faster)."""
    if not spec.valid:
        return None
    if not want_src:
        quick = _fit_clean(window, spec)
        if quick is not False:
            return quick  # type: ignore[return-value]
    allowed = spec.allowed
    seps = spec.input_seps
    upper = not spec.case_sensitive
    core: list[str] = []
    src: list[int] = []
    rep: set[int] = set()
    kept: dict[int, tuple[str, int]] = {}  # core index -> (separator, source index) written before it
    pending: tuple[str, int] | None = None
    for idx, ch in enumerate(window):
        if ch in seps:
            if core and pending is None:
                pending = (ch, idx)  # a run of separators collapses to its first character
            continue
        if ch.isspace():
            continue
        c = chr(ord(ch) - 32) if upper and "a" <= ch <= "z" else ch
        if c not in allowed:
            if not repair:
                return None
            r = repair_char(c, allowed)
            if r is None:
                return None
            c = r
            rep.add(len(core))
        if pending is not None:
            kept[len(core)] = pending
            pending = None
        core.append(c)
        src.append(idx)
    n = len(core)
    if not spec.length_ok(n):
        return None
    out: list[str] = []
    out_src: list[int] = []
    where: list[int] = []  # core index -> index in out
    if spec.groups:
        k = 0
        for gi, g in enumerate(spec.groups):
            if gi:
                for sc in spec.separator:
                    out.append(sc)
                    out_src.append(-1)
            for _ in range(g):
                where.append(len(out))
                out.append(core[k])
                out_src.append(src[k])
                k += 1
    else:
        for k in range(n):
            if k in kept:
                out.append(kept[k][0])
                out_src.append(kept[k][1])
            where.append(len(out))
            out.append(core[k])
            out_src.append(src[k])
    code = "".join(out)
    if spec.regex is not None and not (spec.regex.fullmatch(code) or spec.regex.fullmatch("".join(core))):
        return None
    return code, sorted(where[k] for k in rep), out_src


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
    Full-match fmt.regex when set (the code as normalised, or the code without separators;
    case-insensitive for case-insensitive formats; an invalid regex is ignored - validation
    reports it). A single-character fmt.separator that is not alphanumeric is also read as a
    separator in the source text.
    Returns (code, indices_of_repaired_characters_in_code) or (None, []) if it does not fit."""
    res = fit(normalize_text(raw or ""), spec_for(fmt), want_src=False)
    if res is None:
        return None, []
    return res[0], res[1]


# =============================================================================== flags


@functools.lru_cache(maxsize=64)
def _lookalike_set(ok: frozenset[str]) -> frozenset[str]:
    out: set[str] = set()
    for group in LOOKALIKE_GROUPS:
        if len(group) < 2:
            continue
        hub = group[1]
        for c in group:
            partners = [p for p in group if p != hub] if c == hub else [hub]
            if any(p in ok for p in partners):
                out.add(c)
    return frozenset(out)


def lookalike_indices(code: str, fmt: CodeFormat) -> list[int]:
    """Indices of characters that have a LOOKALIKE_GROUPS partner which fmt also allows
    (e.g. both 0 and O allowed -> every 0 and O; Nintendo excludes O -> 0 is not). These end up
    in CodeCandidate / CodeItem ``lookalikes`` (highlight only)."""
    looks = _lookalike_set(spec_for(fmt).allowed)
    return [i for i, c in enumerate(code or "") if c in looks]


def _separator_set(fmt: CodeFormat) -> set[str]:
    seps = set(SEPARATOR_CHARS)
    seps.update(fmt.separator or "")
    return seps


def flag_indices(code: str, char_confs: Sequence[float] | None, fmt: CodeFormat,
                 threshold: float = 0.95, repaired: Sequence[int] = ()) -> list[int]:
    """Characters that must be checked before the code may run (``flagged`` -> REVIEW):
    {i: conf[i] < threshold} U repaired. Sorted and unique. ``char_confs`` None -> confidence is
    not considered (text sources: only repaired characters). Separators are never flagged.
    Indices outside ``code`` are ignored."""
    code = code or ""
    seps = _separator_set(fmt)
    out: set[int] = set()
    if char_confs is not None:
        for i, (c, conf) in enumerate(zip(code, char_confs)):
            try:
                low = float(conf) < threshold
            except (TypeError, ValueError):
                low = True
            if low and c not in seps and not c.isspace():
                out.add(i)
    for i in repaired:
        if isinstance(i, int) and 0 <= i < len(code) and code[i] not in seps and not code[i].isspace():
            out.add(i)
    return sorted(out)


# =============================================================================== segments


def strip_separators(code: str, separators: str = "-_") -> str:
    """``code`` without any character from ``separators`` (and without whitespace)."""
    return "".join(c for c in code or "" if c not in separators and not c.isspace())


def split_code(code: str, mode: SplitMode, separators: str = "-_", group_sizes: Sequence[int] = ()) -> list[str]:
    """Segments for multi-field entry (type_code split).

    NONE -> [code]. SEPARATOR -> split at any character of ``separators``, empty parts dropped
    (works for groupless formats too, because their codes keep the source separators; segments
    may have different lengths, e.g. 4-6-2). FIXED -> separators removed first, then consecutive
    chunks of ``group_sizes``; characters beyond sum(group_sizes) form one extra last segment.
    ValueError for FIXED without sizes (or with a size below 1)."""
    code = code or ""
    mode = SplitMode(mode)
    if mode is SplitMode.NONE:
        return [code]
    if mode is SplitMode.SEPARATOR:
        parts: list[str] = []
        cur: list[str] = []
        for c in code:
            if c in separators:
                if cur:
                    parts.append("".join(cur))
                    cur = []
            else:
                cur.append(c)
        if cur:
            parts.append("".join(cur))
        return parts
    sizes = [int(s) for s in group_sizes]
    if not sizes:
        raise ValueError("FIXED split needs group sizes")
    if any(s < 1 for s in sizes):
        raise ValueError(f"group sizes must be positive: {sizes}")
    flat = strip_separators(code, separators)
    out: list[str] = []
    pos = 0
    for size in sizes:
        if pos >= len(flat):
            break
        out.append(flat[pos:pos + size])
        pos += size
    if pos < len(flat):
        out.append(flat[pos:])
    return out
