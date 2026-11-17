"""G1 normalisation: text rules, code fitting and repair, separators, flags, look-alikes and
segment splitting (SPEC 5.4, 5.3 type_code, 8.2 row G1)."""

from __future__ import annotations

import pytest

from autopress.codes import normalize as N
from autopress.codes.presets import get_format
from autopress.models import CodeFormat, SplitMode

GENERIC = get_format("generic")
STEAM = get_format("steam")
XBOX = get_format("xbox")
NINTENDO = get_format("nintendo")


# ----------------------------------------------------------------------------- normalize_text


def test_full_width_becomes_ascii() -> None:
    assert N.normalize_text("ＡＢＣＤ－１２３４　ｘｙｚ") == "ABCD-1234 xyz"


@pytest.mark.parametrize("dash", list(N.DASHES))
def test_every_dash_variant_becomes_hyphen(dash: str) -> None:
    assert N.normalize_text(f"AB{dash}CD") == "AB-CD"


def test_nfkc_forms_of_dashes_are_mapped_too() -> None:
    # U+2011 -> U+2010, U+FE63 -> "-", half-width U+FF70 -> U+30FC (all end as "-")
    assert N.normalize_text("AB‑CD﹣EFｰGH") == "AB-CD-EF-GH"


def test_zero_width_bom_and_invisible_format_characters_removed() -> None:
    assert N.normalize_text("\ufeffAB\u200bCD\u200c12\u200d34\u2060\u00ad\u200eX") == "ABCD1234X"


def test_ocr_dashes_only_for_ocr_sources() -> None:
    assert N.normalize_text("AB_CD~EF") == "AB_CD~EF"
    assert N.normalize_text("AB_CD~EF", ocr=True) == "AB-CD-EF"
    assert N.normalize_text("ＡＢ～ＣＤ＿ＥＦ") == "AB~CD_EF"  # full-width forms: NFKC first
    assert N.normalize_text("ＡＢ～ＣＤ＿ＥＦ", ocr=True) == "AB-CD-EF"


def test_line_breaks_and_control_characters() -> None:
    assert N.normalize_text("A\r\nB\rC\nD\u2028E\x0bF") == "A\nB\nC\nD\nE\nF"
    assert N.normalize_text("A\x00B\x07C\tD\x7f") == "ABC\tD"
    assert N.normalize_text("") == ""


def test_spans_map_every_output_character_to_its_source() -> None:
    src = "兌換碼：ＡＢ－１２\r\nok"
    norm, starts, ends = N.normalize_spans(src)
    assert norm == "兌換碼:AB-12\nok"
    i = norm.index("AB")
    assert src[starts[i]:ends[i + 4]] == "ＡＢ－１２"
    j = norm.index("\n")
    assert src[starts[j]:ends[j]] == "\n"  # CRLF counts as one line break (the LF)
    norm2, starts2, ends2 = N.normalize_spans("AB\u200bCD")
    assert norm2 == "ABCD" and [starts2[k] for k in range(4)] == [0, 1, 3, 4]
    plain, s3, e3 = N.normalize_spans("A_B~C", ocr=True)  # ASCII fast path
    assert plain == "A-B-C" and list(s3) == [0, 1, 2, 3, 4] and list(e3) == [1, 2, 3, 4, 5]


# ----------------------------------------------------------------------------- normalize_code


def test_generic_keeps_case_and_lower_case_letters() -> None:
    assert N.normalize_code("abCD12ef", GENERIC) == ("abCD12ef", [])
    assert N.normalize_code("ComeNightorDay", get_format("hoyoverse")) == ("ComeNightorDay", [])


def test_case_insensitive_formats_upper_case_without_flagging() -> None:
    assert N.normalize_code("abcde fghij klmno", STEAM) == ("ABCDE-FGHIJ-KLMNO", [])
    assert N.normalize_code("abcdefghjkmnpqrs", NINTENDO) == ("ABCDEFGHJKMNPQRS", [])


def test_spaces_are_dropped_and_length_counts_charset_characters() -> None:
    assert N.normalize_code("AB CD 12", GENERIC) == ("ABCD12", [])
    assert N.normalize_code("AB-CD", GENERIC) == (None, [])  # 4 charset characters < 6
    assert N.normalize_code("A" * 24, GENERIC)[0] == "A" * 24
    assert N.normalize_code("A" * 25, GENERIC) == (None, [])


def test_repair_only_outside_the_charset() -> None:
    # every look-alike is valid in the generic charset: nothing is touched
    assert N.normalize_code("O0Il1S5Z2B8", GENERIC) == ("O0Il1S5Z2B8", [])
    # Nintendo excludes I, O and Z: they are repaired (and reported)
    assert N.normalize_code("ABCDEFGHJKLMNOPQ", NINTENDO) == ("ABCDEFGHJKLMN0PQ", [13])
    assert N.normalize_code("IZCDEFGHJKLMNPQR", NINTENDO) == ("12CDEFGHJKLMNPQR", [0, 1])
    # lower-case o is upper-cased first (case-insensitive), then repaired O -> 0
    assert N.normalize_code("abcdefghjklmnopq", NINTENDO) == ("ABCDEFGHJKLMN0PQ", [13])


def test_repair_by_case_change_for_case_sensitive_single_case_charset() -> None:
    fmt = CodeFormat(id="custom", charset="A-Z0-9", case_sensitive=True, min_len=6, max_len=12)
    assert N.normalize_code("abc123", fmt) == ("ABC123", [0, 1, 2])


def test_symbols_are_repaired_through_confusable_groups() -> None:
    assert N.normalize_code("AB|D$123", GENERIC) == ("ABIDS123", [2, 4])  # first allowed group member
    assert N.normalize_code("AB~CD123", GENERIC) == (None, [])  # "~" is not code text


def test_unrepairable_character_rejects_the_candidate() -> None:
    assert N.normalize_code("ABCD#1234", GENERIC) == (None, [])
    assert N.normalize_code("兌換ABCD1234", GENERIC) == (None, [])


def test_groupless_formats_keep_source_separators() -> None:
    assert N.normalize_code("ABCD-1234-EF", GENERIC) == ("ABCD-1234-EF", [])
    assert N.normalize_code("ABCD_1234_EF", GENERIC) == ("ABCD_1234_EF", [])
    assert N.normalize_code("-AB--CD__EF-", GENERIC) == ("AB-CD_EF", [])  # runs collapsed, ends dropped
    assert N.normalize_code("AB-_CD12", GENERIC) == ("AB-CD12", [])
    assert N.normalize_code("ＡＢＣＤ－１２３４", GENERIC) == ("ABCD-1234", [])


def test_grouped_formats_regroup_with_their_separator() -> None:
    assert N.normalize_code("ABCDEFGHIJKLMNO", STEAM) == ("ABCDE-FGHIJ-KLMNO", [])
    assert N.normalize_code("ABCDE_FGHIJ-KLMNO", STEAM) == ("ABCDE-FGHIJ-KLMNO", [])
    assert N.normalize_code("ABC-DEFGH-IJKLMNO", STEAM) == ("ABCDE-FGHIJ-KLMNO", [])
    assert N.normalize_code("AAAAABBBBBCCCCCDDDDDEEEEE", XBOX) == ("AAAAA-BBBBB-CCCCC-DDDDD-EEEEE", [])
    assert N.normalize_code("ABCDE-FGHIJ-KLMN", STEAM) == (None, [])
    custom = CodeFormat(id="custom", charset="A-Z0-9", case_sensitive=False, groups=[4, 6, 2], separator=".")
    assert N.normalize_code("abcd.efghij.kl", custom) == ("ABCD.EFGHIJ.KL", [])  # "." read as separator
    assert N.normalize_code("ABCDEFGHIJKL", custom) == ("ABCD.EFGHIJ.KL", [])


def test_repaired_indices_point_into_the_regrouped_code() -> None:
    fmt = CodeFormat(id="custom", charset="A-HJ-NP-Y0-9", case_sensitive=False, groups=[4, 4])
    code, repaired = N.normalize_code("ABCDOFGH", fmt)
    assert code == "ABCD-0FGH" and repaired == [5]


def test_regex_full_match() -> None:
    fmt = CodeFormat(id="custom", charset="A-Za-z0-9", case_sensitive=True, min_len=8, max_len=8,
                     regex=r"[A-Z]{4}\d{4}")
    assert N.normalize_code("ABCD1234", fmt) == ("ABCD1234", [])
    assert N.normalize_code("ABCD-1234", fmt) == ("ABCD-1234", [])  # matched without separators
    assert N.normalize_code("1234ABCD", fmt) == (None, [])
    loose = CodeFormat(id="custom", charset="A-Z0-9", case_sensitive=False, regex=r"[a-z]{3}\d{3}")
    assert N.normalize_code("abc123", loose) == ("ABC123", [])  # case-insensitive format
    broken = CodeFormat(id="custom", regex="(")
    assert N.normalize_code("ABC123", broken) == ("ABC123", [])  # invalid regex ignored


def test_invalid_formats_fit_nothing() -> None:
    assert N.normalize_code("ABC123", CodeFormat(charset="z-a")) == (None, [])
    assert N.normalize_code("ABC123", CodeFormat(groups=[3, 0])) == (None, [])
    assert N.normalize_code("ABC123", CodeFormat(min_len=9, max_len=3)) == (None, [])


def test_fit_fast_path_agrees_with_full_path() -> None:
    samples = ["ABCD-1234-EF", "abcde fghij klmno", "AB|D$123", "-AB--CD__EF-", "ABCDE_FGHIJ-KLMNO", "x" * 30,
               "ab-CD__ef--12", "ABCDEFGHJKLMNOPQ"]
    checked = 0
    for fmt in (GENERIC, STEAM, NINTENDO, XBOX):
        spec = N.spec_for(fmt)
        for s in samples:
            full = N.fit(s, spec)
            fast = N.fit(s, spec, want_src=False)
            full_view = None if full is None else (full[0], full[1])
            fast_view = None if fast is None else (fast[0], fast[1])
            assert full_view == fast_view, (fmt.id, s)
            checked += full is not None
    assert checked >= 6


def test_fit_reports_source_indices() -> None:
    fmt = CodeFormat(id="custom", charset="A-Z0-9", case_sensitive=False, groups=[4, 4])
    res = N.fit("ab-cd e|gh", N.spec_for(fmt))
    assert res is not None
    code, repaired, src = res
    assert code == "ABCD-EIGH" and repaired == [6]
    assert src == [0, 1, 3, 4, -1, 6, 7, 8, 9]  # -1 = inserted group separator


# ----------------------------------------------------------------------------- flags and look-alikes


def test_flags_are_low_confidence_or_repaired_and_never_separators() -> None:
    confs = [0.99, 0.50, 0.10, 0.97, 0.94]
    assert N.flag_indices("AB-CD", confs, GENERIC) == [1, 4]
    assert N.flag_indices("AB-CD", confs, GENERIC, repaired=[3]) == [1, 3, 4]
    assert N.flag_indices("AB-CD", confs, GENERIC, threshold=0.9) == [1]
    assert N.flag_indices("AB-CD", None, GENERIC, repaired=[0, 2, 9]) == [0]  # text source: repaired only
    assert N.flag_indices("AB-CD", None, GENERIC) == []


def test_lookalikes_follow_the_format() -> None:
    assert N.lookalike_indices("O0I1AX", STEAM) == [0, 1, 2, 3]
    assert N.lookalike_indices("Il1", GENERIC) == [0, 1, 2]
    assert N.lookalike_indices("S5Z2B8G6UVY", STEAM) == list(range(11))
    assert N.lookalike_indices("ACEFHKMNPRTWX347", STEAM) == []


def test_nintendo_has_no_lookalike_0_1_2() -> None:
    # Nintendo excludes O, I and Z: 0, 1, 2 cannot be misread as an allowed letter (D and Q only
    # resemble O); B/8, S/5, G/6, U/V/Y stay ambiguous
    assert N.lookalike_indices("012DQ", NINTENDO) == []
    assert N.lookalike_indices("B8S5G6UVY", NINTENDO) == list(range(9))


def test_lookalikes_and_flags_are_separate() -> None:
    code, repaired = N.normalize_code("Q8ZL0W3NBX5C", GENERIC)
    assert repaired == [] and N.flag_indices(code, None, GENERIC, repaired=repaired) == []
    assert len(N.lookalike_indices(code, GENERIC)) >= 5


# ----------------------------------------------------------------------------- segments


def test_strip_separators() -> None:
    assert N.strip_separators("AB-CD_EF 12") == "ABCDEF12"
    assert N.strip_separators("AB.CD-EF", ".") == "ABCD-EF"


def test_split_none_keeps_the_code() -> None:
    assert N.split_code("ABCD-EFGH", SplitMode.NONE) == ["ABCD-EFGH"]
    assert N.split_code("ABCD-EFGH", "none") == ["ABCD-EFGH"]


def test_split_separator_with_unequal_segments() -> None:
    code, _ = N.normalize_code("ABCD-EFGHIJ-KL", GENERIC)  # groupless: separators kept (4-6-2)
    assert N.split_code(code, SplitMode.SEPARATOR) == ["ABCD", "EFGHIJ", "KL"]
    assert N.split_code("AB_CD--EF", SplitMode.SEPARATOR) == ["AB", "CD", "EF"]
    assert N.split_code("ABCDEF", SplitMode.SEPARATOR) == ["ABCDEF"]
    assert N.split_code("AB.CD", SplitMode.SEPARATOR, separators=".") == ["AB", "CD"]


def test_split_fixed_sizes() -> None:
    assert N.split_code("ABCDEFGHIJKL", SplitMode.FIXED, group_sizes=[4, 6, 2]) == ["ABCD", "EFGHIJ", "KL"]
    assert N.split_code("ABCD-EFGHIJ-KL", SplitMode.FIXED, group_sizes=[4, 6, 2]) == ["ABCD", "EFGHIJ", "KL"]
    assert N.split_code("ABCDEFGHIJKLMN", SplitMode.FIXED, group_sizes=[4, 6, 2]) == ["ABCD", "EFGHIJ", "KL", "MN"]
    assert N.split_code("ABCDEFG", SplitMode.FIXED, group_sizes=[5, 5, 5]) == ["ABCDE", "FG"]
    with pytest.raises(ValueError):
        N.split_code("ABCDEF", SplitMode.FIXED)
    with pytest.raises(ValueError):
        N.split_code("ABCDEF", SplitMode.FIXED, group_sizes=[3, 0])
