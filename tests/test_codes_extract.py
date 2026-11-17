"""G1 extraction: text windows, likely heuristic, de-duplication, OCR mapping, validation and the
linear-time guarantee (SPEC 5.4, decision T35, 8.2 row G1)."""

from __future__ import annotations

import random
import time

import pytest

from autopress import i18n
from autopress.codes import extract as E
from autopress.codes.presets import get_format
from autopress.models import CodeFormat, OcrLine, OcrResult

GENERIC = get_format("generic")
STEAM = get_format("steam")
NINTENDO = get_format("nintendo")


def codes(text: str, fmt: CodeFormat = GENERIC) -> list[str]:
    return [c.code for c in E.extract_from_text(text, fmt)]


# ----------------------------------------------------------------------------- text windows


def test_code_after_a_label_and_spaced_code() -> None:
    assert codes("兌換碼：ABCD-1234") == ["ABCD-1234"]
    cands = E.extract_from_text("ABCD 1234", GENERIC)
    assert [(c.code, c.raw) for c in cands] == [("ABCD1234", "ABCD 1234")]


def test_codes_listed_on_one_line_are_never_concatenated() -> None:
    assert codes("ABCD1234 EFGH5678 ZZZ888") == ["ABCD1234", "EFGH5678", "ZZZ888"]
    assert codes("ABCD1234\nEFGH5678\r\nZZZ888") == ["ABCD1234", "EFGH5678", "ZZZ888"]


def test_sentence_gives_the_code_and_unlikely_words_only() -> None:
    cands = E.extract_from_text("Use code GENSHINGIFT now to get 60 Primogems!", GENERIC)
    assert [(c.code, c.likely) for c in cands] == [("GENSHINGIFT", True), ("Primogems", False)]


def test_joined_words_are_not_pre_checked() -> None:
    cands = {c.code: c.likely for c in E.extract_from_text("FREE GIFT CODE: ABCD1234", GENERIC)}
    assert cands == {"FREEGIFTCODE": False, "ABCD1234": True}


def test_space_grouped_code_joins_for_free_and_fixed_length() -> None:
    cands = E.extract_from_text("ABCD EFGH IJKL MNOP", GENERIC)
    assert [(c.code, c.likely) for c in cands] == [("ABCDEFGHIJKLMNOP", False)]  # free length: user confirms
    steam = E.extract_from_text("Codes ABCDE FGHIJ KLMNO", STEAM)
    assert [(c.code, c.raw, c.likely) for c in steam] == [("ABCDE-FGHIJ-KLMNO", "ABCDE FGHIJ KLMNO", True)]


def test_word_like_tokens_never_join_a_code() -> None:
    assert codes("Codes ABCDE FGHIJ KLMNO", STEAM) == ["ABCDE-FGHIJ-KLMNO"]  # not CODES-ABCDE-FGHIJ
    assert "Usecode" not in codes("Use code GENSHINGIFT")


def test_full_width_source_keeps_raw_text() -> None:
    cands = E.extract_from_text("禮包碼：ＺＺＺ８８８。", GENERIC)
    assert [(c.code, c.raw) for c in cands] == [("ZZZ888", "ＺＺＺ８８８")]


def test_separators_in_text_sources() -> None:
    assert codes("ABCD_1234") == ["ABCD_1234"]  # "_" is a real separator in pasted text
    assert codes("ABCD~1234") == []  # "~" ends the run: two 4-character pieces
    assert codes("ab-CD__ef--12") == ["ab-CD_ef-12"]


def test_punctuation_ends_runs_in_text_but_ocr_symbols_are_repaired() -> None:
    assert codes("Use ABCD1234!") == ["ABCD1234"]
    assert codes("ABCD|234") == []  # text: "|" is not code text
    result = OcrResult(lines=[OcrLine(text="ABCD|234", quad=[(0, 0), (90, 0), (90, 20), (0, 20)], score=0.99)])
    cand = E.extract_from_ocr(result, GENERIC)[0]
    assert cand.code == "ABCDI234" and cand.repaired == [4] and 4 in cand.flagged


def test_dedupe_by_code_key_first_occurrence_kept() -> None:
    cands = E.extract_from_text("ABCD-1234\nABCD1234\nabcd1234", GENERIC)
    assert [(c.code, c.raw) for c in cands] == [("ABCD-1234", "ABCD-1234"), ("abcd1234", "abcd1234")]


def test_dedupe_marks_likely_when_any_occurrence_was() -> None:
    cands = E.extract_from_text("abcde-fghij-klmno\nABCDE-FGHIJ-KLMNO", STEAM)
    assert len(cands) == 1 and cands[0].raw == "abcde-fghij-klmno" and cands[0].likely


def test_text_sources_flag_repaired_characters_only() -> None:
    (cand,) = E.extract_from_text("eShop: ABCDEFGHJKLMNOPQ", NINTENDO)
    assert cand.code == "ABCDEFGHJKLMN0PQ"
    assert cand.repaired == [13] and cand.flagged == [13]
    assert cand.char_confs is None and cand.confidence is None and cand.line_index == -1


def test_lookalikes_are_reported_but_not_flagged() -> None:
    (cand,) = E.extract_from_text("Q8ZL0W3NBX5C", GENERIC)
    assert cand.flagged == [] and cand.repaired == []
    assert cand.lookalikes == [0, 1, 2, 4, 8, 10]  # Q 8 Z 0 B 5 (L, W, N, X, C, 3 have no partner)


def test_dates_and_symbol_runs_are_unlikely() -> None:
    cands = {c.code: c.likely for c in E.extract_from_text("活動期間 2026-11-17 ~ 2026-12-01 兌換碼 ABCD1234", GENERIC)}
    assert cands == {"2026-11-17": False, "2026-12-01": False, "ABCD1234": True}


@pytest.mark.parametrize(("token", "fmt", "likely"), [
    ("GENSHINGIFT", GENERIC, True),
    ("ComeNightorDay", GENERIC, True),  # mixed case livestream code
    ("Primogems", GENERIC, False),  # only Capitalised
    ("primogems", GENERIC, False),  # all lower-case
    ("primo9ems", GENERIC, True),  # a digit
    ("abcde", STEAM, False),  # case-insensitive format, lower-case letters
    ("ABCDE", STEAM, True),
    ("abc12", STEAM, True),
    ("Ａｂｃｄｅｆ", GENERIC, False),  # full-width counts after NFKC
    ("2026-11-17", GENERIC, False),
    ("17_11_2026", GENERIC, False),
    ("20261117", GENERIC, True),
    ("||||||", GENERIC, False),
])
def test_likely_heuristic(token: str, fmt: CodeFormat, likely: bool) -> None:
    assert E.is_likely_code(token, fmt) is likely


def test_invalid_format_extracts_nothing() -> None:
    assert E.extract_from_text("ABCD1234", CodeFormat(charset="z-a")) == []
    assert E.extract_from_text("", GENERIC) == []


def test_extraction_stays_linear() -> None:
    rng = random.Random(7)
    words = ["the", "redeem", "Primogems", "活動", "兌換碼", "before", "deadline", "2026-12-01", "x60", "GIFT",
             "CODE", "Use", "now", "Genshin", "Impact", "and", "for", "ZZZ888", "livestream", "AB", "A1"]
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ0123456789"
    tokens = ["".join(rng.choice(alphabet) for _ in range(12)) if i % 25 == 0 else rng.choice(words)
              for i in range(1000)]
    paragraph = " ".join(tokens)
    for fmt in (GENERIC, STEAM, NINTENDO):
        best = min(_timed(paragraph, fmt) for _ in range(3))
        assert best < 0.2, f"{fmt.id}: {best * 1000:.0f} ms for 1000 words"
    assert len(E.extract_from_text(paragraph, GENERIC)) >= 40
    # pathological input: thousands of short code-like tokens that never form a code
    shorts = " ".join(["AB"] * 4000)
    assert min(_timed(shorts, STEAM) for _ in range(2)) < 0.6
    # many separator-only tokens between two letters
    assert _timed("A " + " ".join(["-"] * 4000) + " B", GENERIC) < 0.6


def _timed(text: str, fmt: CodeFormat) -> float:
    t0 = time.perf_counter()
    E.extract_from_text(text, fmt)
    return time.perf_counter() - t0


def test_extract_many_matches_single_extraction() -> None:
    text = "ABCDE-FGHIJ-KLMNO GENSHINGIFT ＺＺＺ８８８ abcd efgh"
    many = E.extract_many(text, [GENERIC, STEAM])
    assert [c.code for c in many[0]] == codes(text, GENERIC)
    assert [c.code for c in many[1]] == codes(text, STEAM)


# ----------------------------------------------------------------------------- OCR


def _line(text: str, y: float, x: float = 0.0, score: float = 0.99, confs: list[float] | None = None) -> OcrLine:
    w = 12.0 * max(1, len(text))
    return OcrLine(text=text, quad=[(x, y), (x + w, y), (x + w, y + 20), (x, y + 20)], score=score, char_confs=confs)


def test_ocr_char_confidences_flags_and_line_index() -> None:
    confs = [0.99] * 4 + [0.6] + [0.99] * 4 + [0.2] + [0.99] * 4
    result = OcrResult(lines=[
        _line("兌換碼", 0),
        _line("AB0D-1234_EFGH", 40, confs=confs),
    ])
    (cand,) = E.extract_from_ocr(result, GENERIC)
    assert cand.code == "AB0D-1234-EFGH"  # "_" is a misread dash for OCR
    assert cand.raw == "AB0D-1234_EFGH"
    assert cand.line_index == 1
    assert len(cand.char_confs) == len(cand.code)
    assert cand.char_confs[4] == 1.0 and cand.char_confs[9] == 1.0  # separators never lower confidence
    assert cand.flagged == []  # the low values sat on separators
    assert cand.confidence == pytest.approx(0.99)
    assert 2 in cand.lookalikes and 3 in cand.lookalikes  # 0 and D


def test_ocr_low_confidence_and_repaired_characters_are_flagged() -> None:
    confs = [0.99, 0.99, 0.50, 0.99, 0.99, 0.99, 0.99, 0.99]
    result = OcrResult(lines=[_line("AB8D$123", 0, confs=confs)])
    (cand,) = E.extract_from_ocr(result, GENERIC, review_threshold=0.95)
    assert cand.code == "AB8DS123"
    assert cand.repaired == [4] and cand.flagged == [2, 4]
    (lenient,) = E.extract_from_ocr(result, GENERIC, review_threshold=0.4)
    assert lenient.flagged == [4]  # repaired characters are flagged whatever the threshold


def test_ocr_line_score_used_without_char_confidences() -> None:
    result = OcrResult(lines=[_line("ZZZ888", 0, score=0.8), _line("ABCDEFGH", 40, score=0.97,
                                                                    confs=[0.9, 0.9])])  # wrong length: ignored
    cands = E.extract_from_ocr(result, GENERIC)
    assert [(c.code, c.char_confs, c.flagged) for c in cands] == [
        ("ZZZ888", [0.8] * 6, [0, 1, 2, 3, 4, 5]), ("ABCDEFGH", [0.97] * 8, [])]


def test_ocr_code_split_over_two_boxes_of_one_row() -> None:
    result = OcrResult(lines=[_line("ABCDE-FGHIJ", 0, x=0), _line("KLMNO", 0, x=200, score=0.9)])
    (cand,) = E.extract_from_ocr(result, STEAM)
    assert cand.code == "ABCDE-FGHIJ-KLMNO"
    assert cand.line_index == 0  # the line holding most of the characters
    assert cand.flagged == [12, 13, 14, 15, 16]  # the second box scored 0.9


def test_ocr_rows_are_read_in_order_and_deduplicated() -> None:
    result = OcrResult(lines=[_line("XYZ789XYZ", 80), _line("ABC123ABC", 0), _line("abc123abc", 40),
                              _line("ABC-123-ABC", 120)])
    assert [c.code for c in E.extract_from_ocr(result, CodeFormat())] == ["ABC123ABC", "abc123abc", "XYZ789XYZ"]


def test_ocr_empty_result() -> None:
    assert E.extract_from_ocr(OcrResult(), GENERIC) == []


# ----------------------------------------------------------------------------- validate_code


def test_validate_accepts_and_normalises() -> None:
    assert E.validate_code(" abcde fghij klmno ", STEAM) == ("ABCDE-FGHIJ-KLMNO", "")
    assert E.validate_code("ＡＢＣＤ－１２３４", GENERIC) == ("ABCD-1234", "")


def test_validate_reasons() -> None:
    assert E.validate_code("", GENERIC) == (None, "請輸入序號")
    assert E.validate_code("ABCDE-FGHIJ-KLMN", STEAM) == (None, "長度須為 15 碼")
    assert E.validate_code("ABCDEFGHJKLMNPQ", NINTENDO) == (None, "長度須為 16 碼")
    assert E.validate_code("ABC", GENERIC) == (None, "長度須為 6–24 碼")
    assert E.validate_code("ABCDEFGHJKLMNOPQ", NINTENDO) == (None, "「O」不是允許的字元，是不是「0」？")
    assert E.validate_code("ABCD#1234", GENERIC) == (None, "含有不允許的字元「#」")
    regex = CodeFormat(id="custom", regex=r"[A-Z]{4}\d{4}")
    assert E.validate_code("1234ABCD", regex) == (None, "不符合設定檔的序號格式")
    assert E.validate_code("ABC123", CodeFormat(charset="z-a"))[0] is None


def test_validate_reasons_in_english() -> None:
    i18n.set_language("en")
    assert E.validate_code("ABCDE", STEAM) == (None, "Must be 15 characters")
    assert E.validate_code("ABC", GENERIC) == (None, "Must be 6-24 characters")
    assert E.validate_code("", GENERIC) == (None, "Enter a code")
