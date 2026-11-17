"""G2: ocr.textfind - exact / contains / regex (no alternative splitting) / nth / alternatives.
Pure Python, no OCR engine."""

from __future__ import annotations

import pytest

from autopress.models import OcrLine, OcrResult, TextMatch
from autopress.ocr.textfind import find_all, find_text, text_present


def line(text: str, x: float, y: float, w: float, h: float = 20.0, score: float = 0.99) -> OcrLine:
    return OcrLine(text=text, quad=[(x, y), (x + w, y), (x + w, y + h), (x, y + h)], score=score)


def dialog_lines() -> list[OcrLine]:
    return [
        line("請輸入兌換碼", 120, 160, 120),   # label; contains 兌換 but is not the button
        line("兌換", 273, 380, 34, 21),       # button (box from ocr.md 3.2)
        line("取消", 493, 380, 34, 21),
        line("Redeem", 600, 380, 60, 21),
    ]


def test_exact_matches_whole_line_only() -> None:
    hit = find_text(dialog_lines(), "兌換")
    assert hit is not None and hit.text == "兌換" and hit.exact
    assert hit.line_index == 1
    assert (hit.x, hit.y) == pytest.approx((290.0, 390.5))
    assert find_text([line("兌換碼", 0, 0, 60)], "兌換") is None  # substring is not enough


def test_exact_normalises_width_case_and_spaces() -> None:
    lines = [line("ＲＥＤＥＥＭ ＮＯＷ", 10, 10, 200)]
    assert find_text(lines, "redeem now") is not None
    assert find_text(lines, "RedeemNow") is not None
    assert find_text(lines, "redeem") is None


def test_contains_sub_box_counts_cjk_double() -> None:
    # "請輸入兌換碼" -> 6 wide chars, 兌換 = chars 3..5 -> proportional span [0.5, 0.833]
    lab = line("請輸入兌換碼", 100, 50, 120, 20)
    hit = find_text([lab], "兌換", TextMatch.CONTAINS)
    assert hit is not None and not hit.exact
    assert hit.x == pytest.approx(100 + 120 * (0.5 + 5 / 6) / 2)
    assert hit.y == pytest.approx(60.0)
    mixed = line("Code兌換", 0, 0, 80, 10)  # weights 1,1,1,1,2,2 -> 兌換 = [4/8, 8/8]
    h2 = find_text([mixed], "兌換", TextMatch.CONTAINS)
    assert h2 is not None and h2.x == pytest.approx(80 * 0.75)


def test_contains_prefers_exact_then_score() -> None:
    lines = [line("請輸入兌換碼", 0, 0, 120, score=0.999), line("兌換", 0, 100, 40, score=0.90)]
    hit = find_text(lines, "兌換", TextMatch.CONTAINS)
    assert hit is not None and hit.text == "兌換" and hit.exact
    lines2 = [line("兌換碼 A", 0, 0, 120, score=0.80), line("兌換碼 B", 0, 100, 120, score=0.95)]
    hit2 = find_text(lines2, "兌換", TextMatch.CONTAINS)
    assert hit2 is not None and hit2.text == "兌換碼 B"


def test_regex_is_one_pattern_never_split() -> None:
    lines = [line("OK", 0, 0, 40), line("OK123", 0, 50, 80), line("確定", 0, 100, 40)]
    hits = find_all(lines, r"^(確定|OK)$", TextMatch.REGEX)
    assert [h.text for h in hits] == ["OK", "確定"]
    assert all(h.exact for h in hits)
    # split at "|" this would be "^(確定" and "OK)$": two broken patterns
    assert find_text(lines, r"^(確定|OK)$", TextMatch.REGEX) is not None
    # an escaped bar stays a literal bar inside the regex
    assert find_text([line("A|B", 0, 0, 30)], r"A\|B", TextMatch.REGEX) is not None


def test_regex_sub_box_and_case_insensitive() -> None:
    ln = line("Code: ab12", 0, 0, 100)
    hit = find_text([ln], r"AB\d+", TextMatch.REGEX)
    assert hit is not None and not hit.exact
    assert hit.x == pytest.approx(100 * (6 + 10) / 2 / 10)


def test_regex_zero_length_and_invalid_find_nothing() -> None:
    lines = dialog_lines()
    assert find_all(lines, "兌換|", TextMatch.REGEX)[0].text == "請輸入兌換碼"  # only real matches
    assert len(find_all(lines, "兌換|", TextMatch.REGEX)) == 2
    assert find_all(lines, "x*", TextMatch.REGEX) == []
    assert find_all(lines, "(", TextMatch.REGEX) == []
    assert find_all(lines, "  ", TextMatch.REGEX) == []


def test_alternatives() -> None:
    lines = [line("Redeem", 0, 0, 60), line("Cancel", 100, 0, 60)]
    hit = find_text(lines, "兌換|Redeem")
    assert hit is not None and hit.text == "Redeem"
    assert find_text(lines, " | ") is None
    assert find_text(lines, "") is None
    assert find_text([line("a|b", 0, 0, 30)], r"a\|b") is not None  # escaped bar = literal


def test_nth_in_reading_order() -> None:
    lines = [
        line("確定", 300, 200, 40),   # row 2, right
        line("確定", 100, 50, 40),    # row 1
        line("確定", 50, 203, 40),    # row 2, left (slightly lower, same row)
    ]
    hits = find_all(lines, "確定")
    assert [h.line_index for h in hits] == [1, 2, 0]
    assert find_text(lines, "確定", nth=1).line_index == 1
    assert find_text(lines, "確定", nth=2).line_index == 2
    assert find_text(lines, "確定", nth=3).line_index == 0
    assert find_text(lines, "確定", nth=4) is None
    assert find_text(lines, "確定").line_index == 1  # best: equal hits -> first in reading order


def test_several_hits_in_one_line_count_for_nth() -> None:
    merged = line("確定 確定", 0, 0, 100)  # two buttons OCR merged into one line
    hits = find_all([merged], "確定", TextMatch.CONTAINS)
    assert len(hits) == 2 and hits[0].x < hits[1].x
    assert find_text([merged], "確定", TextMatch.CONTAINS, nth=2).x == pytest.approx(hits[1].x)


def test_min_score_ignores_weak_lines() -> None:
    lines = [line("兌換", 0, 0, 40, score=0.3)]
    assert find_text(lines, "兌換") is None
    assert find_text(lines, "兌換", min_score=0.2) is not None


def test_text_present_defaults_to_contains() -> None:
    lines = [line("序號已被使用", 0, 0, 120)]
    assert text_present(lines, "已被使用")
    assert not text_present(lines, "已被使用", TextMatch.EXACT)
    assert text_present(lines, "兌換成功|已被使用")
    assert not text_present([], "x")


def test_accepts_ocr_result_and_bad_quads() -> None:
    res = OcrResult(lines=[OcrLine(text="兌換", quad=[], score=0.9)])
    hit = find_text(res, "兌換")  # type: ignore[arg-type]
    assert hit is not None and (hit.x, hit.y) == (0.0, 0.0)


def test_slanted_quad_interpolates_both_edges() -> None:
    ln = OcrLine(text="AB", quad=[(0, 0), (100, 10), (100, 30), (0, 20)], score=0.9)
    hit = find_text([ln], "B", TextMatch.CONTAINS)
    assert hit is not None
    assert hit.x == pytest.approx(75.0) and hit.y == pytest.approx(17.5)
