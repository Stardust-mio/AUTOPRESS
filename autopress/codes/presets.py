# OWNED BY G1
"""Built-in code formats (extraction presets) - docs/research/ux.md section 3.

| id              | charset       | case     | length          | groups        |
|-----------------|---------------|----------|-----------------|---------------|
| generic         | A-Za-z0-9     | preserve | 6-24            | -             |
| hoyoverse       | A-Za-z0-9     | preserve | 6-16            | -             |
| wuthering_waves | A-Za-z0-9     | preserve | 6-20            | -             |
| blue_archive    | A-Za-z0-9     | preserve | 6-20            | -             |
| steam           | A-Z0-9        | upper    | 15              | [5, 5, 5]     |
| xbox            | A-Z0-9        | upper    | 25              | [5,5,5,5,5]   |
| nintendo        | A-HJ-NP-Y0-9  | upper    | 16-16           | -             |
| custom          | (as generic; the user edits it in the profile)                  |

"generic" keeps the case as written (= models.CodeFormat() defaults): AutoPress never changes
the case of a code unless the format says the platform is case-insensitive (steam, xbox,
nintendo upper-case; decision PX-19). Lengths count charset characters, not separators.

detect_format ranks the presets (custom excluded) by the number of candidates that look like
real codes of that format: ``likely``, nothing repaired, and - for the upper-casing presets - no
lower-case letter in the source (so auto-detection never changes a code's case or characters
silently). Ties go to the more specific format (fixed groups > fixed length > free length),
then to the earlier id in BUILTIN_FORMAT_IDS (so generic wins among the free-length presets).
"""

from __future__ import annotations

import string
from dataclasses import replace

from ..i18n import tr
from ..models import CodeFormat, expand_charset

BUILTIN_FORMAT_IDS: tuple[str, ...] = (
    "generic", "hoyoverse", "wuthering_waves", "blue_archive", "steam", "xbox", "nintendo", "custom",
)

_FORMATS: dict[str, CodeFormat] = {
    "generic": CodeFormat(id="generic"),
    "hoyoverse": CodeFormat(id="hoyoverse", charset="A-Za-z0-9", case_sensitive=True, min_len=6, max_len=16),
    "wuthering_waves": CodeFormat(id="wuthering_waves", charset="A-Za-z0-9", case_sensitive=True,
                                  min_len=6, max_len=20),
    "blue_archive": CodeFormat(id="blue_archive", charset="A-Za-z0-9", case_sensitive=True, min_len=6, max_len=20),
    "steam": CodeFormat(id="steam", charset="A-Z0-9", case_sensitive=False, min_len=15, max_len=15,
                        groups=[5, 5, 5], separator="-"),
    "xbox": CodeFormat(id="xbox", charset="A-Z0-9", case_sensitive=False, min_len=25, max_len=25,
                       groups=[5, 5, 5, 5, 5], separator="-"),
    "nintendo": CodeFormat(id="nintendo", charset="A-HJ-NP-Y0-9", case_sensitive=False, min_len=16, max_len=16),
    "custom": CodeFormat(id="custom"),
}

_LABELS: dict[str, tuple[str, str]] = {  # (zh-TW, en) pairs, resolved at call time
    "generic": ("通用", "Generic"),
    "hoyoverse": ("HoYoverse（原神／星鐵／絕區零）", "HoYoverse (Genshin / Star Rail / ZZZ)"),
    "wuthering_waves": ("鳴潮", "Wuthering Waves"),
    "blue_archive": ("蔚藍檔案", "Blue Archive"),
    "steam": ("Steam", "Steam"),
    "xbox": ("Xbox／Microsoft", "Xbox / Microsoft"),
    "nintendo": ("Nintendo eShop", "Nintendo eShop"),
    "custom": ("自訂", "Custom"),
}


def _copy(fmt: CodeFormat) -> CodeFormat:
    return replace(fmt, groups=list(fmt.groups))


def list_formats() -> list[CodeFormat]:
    """Copies of all built-in formats in BUILTIN_FORMAT_IDS order."""
    return [_copy(_FORMATS[fid]) for fid in BUILTIN_FORMAT_IDS]


def get_format(format_id: str) -> CodeFormat:
    """A copy of the built-in format; unknown ids -> a copy of "generic"."""
    return _copy(_FORMATS.get(format_id, _FORMATS["generic"]))


def format_label(format_id: str) -> str:
    """Localized name, e.g. "通用" / "Generic", "HoYoverse（原神／星鐵／絕區零）".
    Unknown ids (e.g. a preset of a newer version) are labelled like "custom"."""
    zh, en = _LABELS.get(format_id, _LABELS["custom"])
    return tr(zh, en)


def format_shape(fmt: CodeFormat) -> str:
    """Shape hint for any format: groups -> "XXXXX-XXXXX-XXXXX"; a fixed length -> X's plus the
    count; a length range -> eight X's plus the range (localized)."""
    if fmt.groups and all(g > 0 for g in fmt.groups):
        return fmt.separator.join("X" * g for g in fmt.groups)
    if fmt.min_len == fmt.max_len:
        xs = "X" * min(fmt.min_len, 32)
        return tr(f"{xs}（{fmt.min_len} 碼）", f"{xs} ({fmt.min_len} characters)")
    xs = "X" * 8
    return tr(f"{xs}（{fmt.min_len}–{fmt.max_len} 碼）", f"{xs} ({fmt.min_len}-{fmt.max_len} characters)")


def format_example(format_id: str) -> str:
    """Shape hint for the UI, e.g. "XXXXX-XXXXX-XXXXX" (never a real code)."""
    return format_shape(get_format(format_id))


_UPPER, _LOWER, _DIGITS = set(string.ascii_uppercase), set(string.ascii_lowercase), set(string.digits)
NB_HYPHEN = "\u2011"  # non-breaking hyphen: a raw charset like A-F0-9 never wraps as "A-" / "F0-9"


def _raw_charset(charset: str) -> str:
    return (charset or "").replace("-", NB_HYPHEN)


def charset_label(charset: str, case_sensitive: bool = True) -> str:
    """Plain words for a code character set (gamers never see "A-Za-z0-9"):
    letters + digits -> "英文字母與數字" / "letters and digits"; A-Z0-9, or letters that are
    upper-cased because the format is not case-sensitive -> "大寫英文與數字" / "capital letters and
    digits"; up to four capital letters left out are named (Nintendo: "大寫英文與數字，不含 I、O、Z"
    / "capital letters and digits except I, O and Z"); digits only -> "數字" / "digits". Any other
    set is shown as written, with non-breaking hyphens."""
    try:
        chars = set(expand_charset(charset))
    except ValueError:
        return _raw_charset(charset)
    if not case_sensitive:
        chars = {c.upper() for c in chars}
    digits = chars & _DIGITS
    letters = chars - _DIGITS
    if digits and digits != _DIGITS:
        return _raw_charset(charset)
    missing: list[str] = []
    if letters == _UPPER | _LOWER:
        zh, en = "英文字母", "letters"
    elif letters == _LOWER:
        zh, en = "小寫英文", "lowercase letters"
    elif letters and letters <= _UPPER and len(_UPPER - letters) <= 4:
        zh, en = "大寫英文", "capital letters"
        missing = sorted(_UPPER - letters)
    elif not letters:
        return tr("數字", "digits")
    else:
        return _raw_charset(charset)
    if digits:
        zh, en = zh + "與數字", en + " and digits"
    if missing:
        en_list = missing[0] if len(missing) == 1 else ", ".join(missing[:-1]) + " and " + missing[-1]
        zh, en = zh + "，不含 " + "、".join(missing), en + " except " + en_list
    return tr(zh, en)


def length_label(fmt: CodeFormat) -> str:
    """"6–16 碼" / "6–16 characters" ("15 碼" for a fixed length); separators are not counted.
    The number and its unit never wrap apart (no-break space, word joiner after the en dash - in
    both languages: an ASCII hyphen could still wrap as "6-" / "16 characters")."""
    if fmt.min_len == fmt.max_len:
        return tr(f"{fmt.min_len}\u00a0碼", f"{fmt.min_len}\u00a0characters")
    return tr(f"{fmt.min_len}–\u2060{fmt.max_len}\u00a0碼", f"{fmt.min_len}–\u2060{fmt.max_len}\u00a0characters")


def _specificity(fmt: CodeFormat) -> int:
    if fmt.groups:
        return 2
    return 1 if fmt.min_len == fmt.max_len else 0


def detect_format(text: str) -> str:
    """Id of the built-in format that extracts the most likely candidates from ``text``
    (ties: the more specific format - fixed groups/length beat free length). "generic" when
    nothing matches. "custom" is never returned. Counting rules: module docstring."""
    from .extract import extract_many  # local import: extract does not depend on presets

    if not text or not text.strip():
        return "generic"
    ids = [fid for fid in BUILTIN_FORMAT_IDS if fid != "custom"]
    results = extract_many(text, [_FORMATS[fid] for fid in ids])
    best_id, best_key = "generic", (0, 0, 0)
    for fid, cands in zip(ids, results):
        fmt = _FORMATS[fid]
        order = BUILTIN_FORMAT_IDS.index(fid)
        score = 0
        for cand in cands:
            if not cand.likely or cand.repaired:
                continue
            if not fmt.case_sensitive and any(c.islower() for c in cand.raw):
                continue
            score += 1
        key = (score, _specificity(fmt), -order)
        if score and key > best_key:
            best_id, best_key = fid, key
    return best_id
