"""Two-language UI text: ``tr("中文", "English")`` (zh-TW is the primary language).

OWNED BY A1 (foundation). Pure Python (ctypes only for the Windows UI language).

Rules for every group (SPEC section 6.1):
* Every user-visible string goes through ``tr(zh, en)`` with the Traditional Chinese text
  FIRST. Placeholders use ``str.format`` names: ``tr("共 {n} 筆", "{n} codes").format(n=3)``.
* Never call ``tr`` at import time (module-level constants, default arguments, class bodies):
  the language is chosen after the settings are loaded. Keep ``(zh, en)`` pairs or ``T``
  objects and resolve them when the text is shown.
* The language is fixed for the life of the process: ``set_language`` is called once at
  startup; the Settings page tells the user a change takes effect after a restart.
"""

from __future__ import annotations

import locale
import logging
import math
from typing import NamedTuple

__all__ = [
    "EN",
    "SUPPORTED",
    "ZH_TW",
    "T",
    "format_count",
    "format_duration",
    "get_language",
    "is_zh",
    "normalize_language",
    "set_language",
    "system_language",
    "tr",
]

log = logging.getLogger(__name__)

ZH_TW = "zh-TW"
EN = "en"
SUPPORTED: tuple[str, ...] = (ZH_TW, EN)

_current: str | None = None  # resolved language; None = not chosen yet (system default)


def _windows_ui_locale() -> str | None:
    """Windows display-language locale name such as "zh_TW" or "en_US" (None if unknown)."""
    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        fn = kernel32.GetUserDefaultUILanguage
        fn.argtypes = []
        fn.restype = ctypes.c_ushort
        langid = int(fn())
    except (OSError, AttributeError):
        return None
    return locale.windows_locale.get(langid)


def system_language() -> str:
    """``"zh-TW"`` when the Windows UI language (or, failing that, the process locale) is any
    Chinese variant, else ``"en"``. Simplified-Chinese systems also get zh-TW (closest)."""
    name = _windows_ui_locale()
    if not name:
        try:
            name = locale.getlocale()[0] or ""
        except (ValueError, TypeError):
            name = ""
    name = (name or "").lower()
    return ZH_TW if name.startswith("zh") or name.startswith("chinese") else EN


def normalize_language(value: str | None) -> str:
    """Map user/locale spellings to ``"auto"``, ``"zh-TW"`` or ``"en"``.
    ``"zh"``, ``"zh_TW"``, ``"zh-Hant"``, ``"zh-CN"`` -> ``"zh-TW"``; ``"en-US"`` -> ``"en"``;
    empty, ``None``, ``"auto"``, ``"system"`` and anything unknown -> ``"auto"``."""
    v = (value or "").strip().replace("_", "-").lower()
    if not v or v in ("auto", "system", "default"):
        return "auto"
    if v.startswith("zh"):
        return ZH_TW
    if v.startswith("en"):
        return EN
    return "auto"


def set_language(lang: str | None) -> str:
    """Choose the UI language (``"auto"``, ``"zh-TW"``, ``"en"`` or a locale spelling).
    Returns the resolved language (``"zh-TW"`` or ``"en"``)."""
    global _current
    norm = normalize_language(lang)
    _current = system_language() if norm == "auto" else norm
    log.debug("language set to %s (requested %r)", _current, lang)
    return _current


def get_language() -> str:
    """The resolved UI language; the system language until ``set_language`` is called."""
    global _current
    if _current is None:
        _current = system_language()
    return _current


def is_zh() -> bool:
    return get_language() == ZH_TW


def tr(zh: str, en: str) -> str:
    """Return ``zh`` or ``en`` for the current language."""
    return zh if get_language() == ZH_TW else en


class T(NamedTuple):
    """A lazily translated pair, safe to keep in module-level tables: ``str(T("成功", "Done"))``."""

    zh: str
    en: str

    def __str__(self) -> str:
        return tr(self.zh, self.en)

    @property
    def text(self) -> str:
        return tr(self.zh, self.en)


def format_duration(seconds: float | None) -> str:
    """Human duration: 75 -> "1 分 15 秒" / "1 min 15 s"; 3700 -> "1 小時 1 分" / "1 h 1 min".
    ``None``, negative or non-finite values -> "—"."""
    if seconds is None or not math.isfinite(seconds) or seconds < 0:
        return "—"
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return tr(f"{h} 小時 {m} 分", f"{h} h {m} min")
    if m:
        return tr(f"{m} 分 {sec} 秒", f"{m} min {sec} s")
    return tr(f"{sec} 秒", f"{sec} s")


def format_count(n: int, zh_unit: str = "筆", en_singular: str = "code", en_plural: str | None = None) -> str:
    """``format_count(3)`` -> "3 筆" / "3 codes"; ``format_count(1)`` -> "1 筆" / "1 code"."""
    if is_zh():
        return f"{n} {zh_unit}"
    word = en_singular if n == 1 else (en_plural or en_singular + "s")
    return f"{n} {word}"
