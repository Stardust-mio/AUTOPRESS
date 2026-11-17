"""Tests for autopress.textutil and autopress.i18n (OWNED BY A1)."""

from __future__ import annotations

import math

import pytest

from autopress import i18n
from autopress import textutil as tu


def test_normalisation() -> None:
    assert tu.nfkc("ＡＢ１２－ｃｄ​") == "AB12-cd"
    assert tu.norm_match(" Ｒｅｄｅｅｍ  Now ") == "redeemnow"
    assert tu.squash("Too many requests. Please try again later!") == "toomanyrequestspleasetryagainlater"
    assert tu.squash("操作過於頻繁，請稍後再試。") == "操作過於頻繁請稍後再試"


def test_levenshtein_and_semi_global() -> None:
    assert tu.levenshtein("kitten", "sitting") == 3
    assert tu.levenshtein("", "abc") == 3
    assert tu.semi_global_distance("expired", "code has expird now") == 1
    assert tu.semi_global_distance("abc", "") == 3


@pytest.mark.parametrize(("needle", "hay", "ok"), [
    ("expired", "codeexpired", True),
    ("successfully", "redeemedsuccesfully", True),  # one edit, long Latin keyword
    ("invalid", "invalld", True),
    ("used", "usod", False),  # too short for fuzzy
    ("已被使用", "已達使用上限", False),  # CJK: exact only
    ("已被使用", "序號已被使用", True),
    ("", "anything", False),
])
def test_fuzzy_contains(needle: str, hay: str, ok: bool) -> None:
    assert tu.fuzzy_contains(needle, hay) is ok


def test_fuzzy_contains_options() -> None:
    assert tu.fuzzy_contains("已被使用", "已達使用", allow_wide=True, min_len=4)
    assert not tu.fuzzy_contains("expired", "expird", max_edits=0)


def test_split_alternatives() -> None:
    assert tu.split_alternatives("兌換 | Redeem|") == ["兌換", "Redeem"]
    assert tu.split_alternatives(r"a\|b|c") == ["a|b", "c"]
    assert tu.split_alternatives("  ") == []


def test_clean_text() -> None:
    assert tu.clean_text("a\ud800b\x00c\r\n\td\x85") == "abc\n\td"


def test_has_wide() -> None:
    assert tu.has_wide("兌換") and tu.has_wide("이미")
    assert not tu.has_wide("ｶ")  # half-width katakana KA is narrow
    assert not tu.has_wide("Redeem")


# ----------------------------------------------------------------------------- i18n


def test_tr_and_language_switch() -> None:
    assert i18n.set_language("zh-TW") == "zh-TW"
    assert i18n.tr("成功", "Done") == "成功" and i18n.is_zh()
    assert i18n.set_language("en") == "en"
    assert i18n.tr("成功", "Done") == "Done" and not i18n.is_zh()
    assert str(i18n.T("成功", "Done")) == "Done" and i18n.T("成功", "Done").text == "Done"


@pytest.mark.parametrize(("value", "expected"), [
    ("zh", "zh-TW"), ("zh_TW", "zh-TW"), ("zh-Hant", "zh-TW"), ("zh-CN", "zh-TW"), ("en-US", "en"),
    ("EN", "en"), ("", "auto"), (None, "auto"), ("system", "auto"), ("fr", "auto"),
])
def test_normalize_language(value: str | None, expected: str) -> None:
    assert i18n.normalize_language(value) == expected


def test_auto_language_is_supported() -> None:
    assert i18n.system_language() in i18n.SUPPORTED
    assert i18n.set_language("auto") in i18n.SUPPORTED


def test_format_helpers() -> None:
    i18n.set_language("zh-TW")
    assert i18n.format_duration(75) == "1 分 15 秒"
    assert i18n.format_duration(3700) == "1 小時 1 分"
    assert i18n.format_duration(None) == "—" and i18n.format_duration(math.inf) == "—"
    assert i18n.format_count(3) == "3 筆"
    i18n.set_language("en")
    assert i18n.format_duration(9.6) == "10 s"
    assert i18n.format_count(1) == "1 code" and i18n.format_count(2) == "2 codes"
