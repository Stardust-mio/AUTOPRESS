"""G1 presets: the table of built-in formats, labels, shape hints and detect_format (SPEC 5.4,
autopress/codes/presets.py docstring, 8.2 row G1)."""

from __future__ import annotations

import pytest

from autopress import i18n
from autopress.codes import presets as P
from autopress.codes.extract import extract_from_text
from autopress.codes.normalize import normalize_code
from autopress.models import CodeFormat

TABLE = [
    # id, charset, case_sensitive, min, max, groups
    ("generic", "A-Za-z0-9", True, 6, 24, []),
    ("hoyoverse", "A-Za-z0-9", True, 6, 16, []),
    ("wuthering_waves", "A-Za-z0-9", True, 6, 20, []),
    ("blue_archive", "A-Za-z0-9", True, 6, 20, []),
    ("steam", "A-Z0-9", False, 15, 15, [5, 5, 5]),
    ("xbox", "A-Z0-9", False, 25, 25, [5, 5, 5, 5, 5]),
    ("nintendo", "A-HJ-NP-Y0-9", False, 16, 16, []),
    ("custom", "A-Za-z0-9", True, 6, 24, []),
]


@pytest.mark.parametrize(("fid", "charset", "case_sensitive", "lo", "hi", "groups"), TABLE)
def test_preset_table(fid: str, charset: str, case_sensitive: bool, lo: int, hi: int, groups: list[int]) -> None:
    fmt = P.get_format(fid)
    assert (fmt.id, fmt.charset, fmt.case_sensitive, fmt.min_len, fmt.max_len, fmt.groups) == (
        fid, charset, case_sensitive, lo, hi, groups)
    assert fmt.separator == "-" and fmt.regex == ""
    assert not fmt.validate()


def test_list_formats_order_and_copies() -> None:
    formats = P.list_formats()
    assert [f.id for f in formats] == list(P.BUILTIN_FORMAT_IDS)
    formats[4].groups.append(99)
    formats[0].min_len = 1
    assert P.get_format("steam").groups == [5, 5, 5]
    assert P.get_format("generic").min_len == 6


def test_generic_equals_model_defaults_and_unknown_ids_fall_back() -> None:
    generic = P.get_format("generic")
    assert generic == CodeFormat()
    assert P.get_format("no-such-preset") == generic
    custom = P.get_format("custom")
    assert custom.id == "custom" and (custom.charset, custom.min_len, custom.max_len) == ("A-Za-z0-9", 6, 24)


@pytest.mark.parametrize("fid", ["generic", "hoyoverse", "wuthering_waves", "blue_archive", "custom"])
def test_free_length_presets_keep_lower_case_letters(fid: str) -> None:
    assert normalize_code("abCD12efGH", P.get_format(fid)) == ("abCD12efGH", [])


@pytest.mark.parametrize(("fid", "raw", "code"), [
    ("steam", "abcde-fghij-k1mno", "ABCDE-FGHIJ-K1MNO"),
    ("xbox", "aaaaa bbbbb ccccc ddddd eeeee", "AAAAA-BBBBB-CCCCC-DDDDD-EEEEE"),
    ("nintendo", "abcd efgh jkmn pqrs", "ABCDEFGHJKMNPQRS"),
])
def test_case_insensitive_presets_upper_case(fid: str, raw: str, code: str) -> None:
    assert normalize_code(raw, P.get_format(fid)) == (code, [])


@pytest.mark.parametrize(("fid", "ok_len", "too_long"), [
    ("generic", 24, 25), ("hoyoverse", 16, 17), ("wuthering_waves", 20, 21), ("blue_archive", 20, 21)])
def test_length_ranges(fid: str, ok_len: int, too_long: int) -> None:
    fmt = P.get_format(fid)
    assert normalize_code("A1" * (ok_len // 2), fmt)[0] is not None
    assert normalize_code("Z" * too_long, fmt)[0] is None
    assert normalize_code("ABCDE", fmt)[0] is None  # minimum 6
    assert normalize_code("ABCDEF", fmt)[0] == "ABCDEF"


def test_labels_are_localized() -> None:
    assert P.format_label("generic") == "通用"
    assert P.format_label("hoyoverse") == "HoYoverse（原神／星鐵／絕區零）"
    assert P.format_label("unknown-id") == "自訂"
    i18n.set_language("en")
    assert P.format_label("generic") == "Generic"
    assert P.format_label("custom") == "Custom"
    assert all(P.format_label(fid) for fid in P.BUILTIN_FORMAT_IDS)


def test_examples_are_shapes_not_codes() -> None:
    assert P.format_example("steam") == "XXXXX-XXXXX-XXXXX"
    assert P.format_example("xbox") == "XXXXX-XXXXX-XXXXX-XXXXX-XXXXX"
    assert P.format_example("nintendo").startswith("X" * 16) and "16" in P.format_example("nintendo")
    assert P.format_example("generic").startswith("XXXXXXXX") and "6–24" in P.format_example("generic")
    i18n.set_language("en")
    assert "6-24" in P.format_example("generic")
    for fid in P.BUILTIN_FORMAT_IDS:
        shape = P.format_example(fid).split(" (")[0]
        assert set(shape) <= {"X", "-"}, (fid, shape)  # a shape, never a code-like example


# ----------------------------------------------------------------------------- detect_format


@pytest.mark.parametrize(("text", "expected"), [
    ("Steam key: ABCDE-FGHIJ-KLMNO", "steam"),
    ("ABCDE FGHIJ KLMNO\nPQRST-UVWXY-Z1234", "steam"),
    ("Xbox: AAAAA-BBBBB-CCCCC-DDDDD-EEEEE", "xbox"),
    ("eShop ABCDEFGHJKLMNPQR", "nintendo"),
    ("兌換碼：GENSHINGIFT、ZZZ888、ComeNightorDay", "generic"),
    ("ABCD1234EFGH", "generic"),
    ("", "generic"),
    ("no codes in this sentence at all", "generic"),
])
def test_detect_format(text: str, expected: str) -> None:
    assert P.detect_format(text) == expected


def test_detect_never_changes_case_or_characters_silently() -> None:
    # a mixed-case 16-character code also fits Nintendo after upper-casing: generic must win
    assert P.detect_format("Ab12Cd34Ef56Gh78") == "generic"
    # a 16-character code with an O would be repaired by Nintendo (O -> 0): generic must win
    assert P.detect_format("ABO2CD34EF56GH78") == "generic"
    # lower-case Steam keys: generic keeps them as written (Steam itself ignores case)
    assert P.detect_format("abcde-fghij-klmno") == "generic"


def test_detect_prefers_the_format_with_more_codes() -> None:
    text = "ABCDE-FGHIJ-KLMNO\nGENSHINGIFT\nZZZ888\nHOYO2026GIFT"
    assert P.detect_format(text) == "generic"  # generic extracts 4, steam 1
    # two Steam keys + one other code: generic extracts all three, steam only two
    assert P.detect_format("ABCDE-FGHIJ-KLMNO\nPQRST-UVWXY-Z1234\nZZZ888") == "generic"
    # equal counts: the more specific format wins the tie
    assert P.detect_format("ABCDE-FGHIJ-KLMNO\nPQRST-UVWXY-Z1234") == "steam"
    assert "custom" not in {P.detect_format(t) for t, _ in [("ABCDEF", 0), ("ABCDE-FGHIJ-KLMNO", 0)]}


def test_detect_counts_only_likely_candidates() -> None:
    # words are candidates of the generic format too, but not "likely": nothing is detected
    assert P.detect_format("Congratulations everyone, redemption") == "generic"
    assert P.detect_format("ABCDEFGHJKLMNPQR and Congratulations") == "nintendo"
