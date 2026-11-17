"""Small pure text helpers shared by codes (G1), OCR (G2) and the runner (G4).

OWNED BY A1 (foundation). Pure Python, no Qt, no numpy.

* ``nfkc``           - Unicode NFKC (full-width -> half-width, compatibility forms).
* ``norm_match``     - NFKC + casefold + no whitespace: strict "same label" comparison
                       (used by OCR text finding, ocr.md section 4 ``find_text_center``).
* ``squash``         - ``norm_match`` + no punctuation: keyword matching for result messages
                       (bench_u3.py ``squash``; 100 % class accuracy on the U3 set).
* ``fuzzy_contains`` - substring match allowing ``max_edits`` edits for non-CJK needles of at
                       least ``min_len`` (6) characters (stricter than bench_u3.py ``fuzzy_in``).
* ``split_alternatives`` - "兌換|Redeem" -> ["兌換", "Redeem"] ("\\|" is a literal bar).
* ``clean_text``     - drop lone surrogates and control characters (QLineEdit can produce lone
                       surrogates, which break UTF-8 JSON writing; see pyqt-windows.md).
"""

from __future__ import annotations

import unicodedata

__all__ = [
    "clean_text",
    "fuzzy_contains",
    "has_wide",
    "levenshtein",
    "nfkc",
    "norm_match",
    "semi_global_distance",
    "split_alternatives",
    "squash",
]

_ZERO_WIDTH = {"​", "‌", "‍", "⁠", "﻿"}


def nfkc(text: str) -> str:
    """NFKC-normalised ``text`` with zero-width characters and the BOM removed."""
    return "".join(c for c in unicodedata.normalize("NFKC", text) if c not in _ZERO_WIDTH)


def norm_match(text: str) -> str:
    """NFKC, casefold, all whitespace removed. Two labels are "the same text" when equal."""
    return "".join(c for c in nfkc(text) if not c.isspace()).casefold()


def squash(text: str) -> str:
    """``norm_match`` plus removal of punctuation (Unicode category P*)."""
    return "".join(c for c in norm_match(text) if not unicodedata.category(c).startswith("P"))


def levenshtein(a: str, b: str) -> int:
    """Classic edit distance (insert / delete / substitute, cost 1 each)."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j - 1] + (ca != cb), prev[j] + 1, cur[j - 1] + 1))
        prev = cur
    return prev[-1]


def semi_global_distance(needle: str, hay: str) -> int:
    """Smallest edit distance between ``needle`` and any substring of ``hay``."""
    if not needle:
        return 0
    if not hay:
        return len(needle)
    prev = [0] * (len(hay) + 1)  # leading text of hay is free
    for i, cn in enumerate(needle, 1):
        cur = [i]
        for j, ch in enumerate(hay, 1):
            cur.append(min(prev[j - 1] + (cn != ch), prev[j] + 1, cur[j - 1] + 1))
        prev = cur
    return min(prev)  # trailing text of hay is free


def has_wide(text: str) -> bool:
    """True if ``text`` contains East-Asian wide/full-width characters (CJK, kana, Hangul)."""
    return any(unicodedata.east_asian_width(c) in "WF" for c in text)


def fuzzy_contains(needle: str, hay: str, max_edits: int = 1, min_len: int = 6, allow_wide: bool = False) -> bool:
    """True if ``needle`` occurs in ``hay``. Up to ``max_edits`` edits are tolerated (OCR
    noise) only when ``len(needle) >= min_len`` and - unless ``allow_wide`` - the needle has no
    wide (CJK) characters: one edit in a 4-character CJK keyword is a different word
    ("已被使用" vs "已達使用上限"). Callers normalise both sides first (normally :func:`squash`).
    An empty needle never matches."""
    if not needle:
        return False
    if needle in hay:
        return True
    if max_edits <= 0 or len(needle) < min_len or not hay:
        return False
    if not allow_wide and has_wide(needle):
        return False
    return semi_global_distance(needle, hay) <= max_edits


def split_alternatives(text: str) -> list[str]:
    """Split a user pattern on unescaped ``|``; ``\\|`` stands for a literal bar.
    Parts are stripped and empty parts dropped: ``"兌換 | Redeem|"`` -> ``["兌換", "Redeem"]``."""
    parts: list[str] = []
    cur: list[str] = []
    i = 0
    while i < len(text):
        c = text[i]
        if c == "\\" and i + 1 < len(text) and text[i + 1] == "|":
            cur.append("|")
            i += 2
            continue
        if c == "|":
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    parts.append("".join(cur))
    return [p.strip() for p in parts if p.strip()]


def clean_text(text: str) -> str:
    """Remove lone UTF-16 surrogates and C0/C1 control characters except tab and newline."""
    out = []
    for c in text:
        o = ord(c)
        if 0xD800 <= o <= 0xDFFF:
            continue
        if (o < 0x20 and c not in "\t\n") or 0x7F <= o <= 0x9F:
            continue
        out.append(c)
    return "".join(out)
