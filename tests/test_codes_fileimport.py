"""G1 file import: encodings, CSV / TSV cells, JSON layouts, errors (SPEC 5.4, 8.2 row G1).
Every file is written into the test's tmp_path."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from autopress import i18n
from autopress.codes import fileimport as F
from autopress.codes.csvexport import export_codes_csv
from autopress.codes.extract import extract_from_text
from autopress.codes.presets import get_format
from autopress.models import CodeItem, CodeSource, CodeStatus

TEXT = "兌換碼：ABCD-1234\n禮包碼 ZZZ888\n"


def write(tmp_path: Path, name: str, data: bytes) -> Path:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


@pytest.mark.parametrize(("label", "data"), [
    ("utf8", TEXT.encode("utf-8")),
    ("utf8-bom", b"\xef\xbb\xbf" + TEXT.encode("utf-8")),
    ("utf16-le-bom", TEXT.encode("utf-16")),
    ("utf16-be-bom", b"\xfe\xff" + TEXT.encode("utf-16-be")),
    ("utf32-bom", TEXT.encode("utf-32")),
    ("cp950", TEXT.encode("cp950")),
    ("crlf", TEXT.replace("\n", "\r\n").encode("utf-8")),
])
def test_encodings(tmp_path: Path, label: str, data: bytes) -> None:
    text = F.read_code_file(write(tmp_path, f"{label}.txt", data))
    assert text == TEXT
    assert [c.code for c in extract_from_text(text, get_format("generic"))] == ["ABCD-1234", "ZZZ888"]


def test_utf16_without_bom(tmp_path: Path) -> None:
    ascii_text = "codes:\nABCD-1234\nEFGH-5678\n"
    assert F.read_code_file(write(tmp_path, "le.txt", ascii_text.encode("utf-16-le"))) == ascii_text
    assert F.read_code_file(write(tmp_path, "be.txt", ascii_text.encode("utf-16-be"))) == ascii_text


def test_undecodable_bytes_do_not_raise(tmp_path: Path) -> None:
    text = F.read_code_file(write(tmp_path, "bad.txt", b"ABCD-1234 \xff\xfe\xfa\x80\x80 ZZZ888"))
    assert "ABCD-1234" in text and "ZZZ888" in text


def test_control_characters_dropped(tmp_path: Path) -> None:
    # (never name a test file "nul.*": Windows maps it to the NUL device)
    assert F.read_code_file(write(tmp_path, "controls.log", b"ABCD\x001234\x07\tX")) == "ABCD1234\tX"


def test_csv_every_cell_on_its_own_line(tmp_path: Path) -> None:
    data = 'ABCD-1234,ZZZ888\n"EFGH,5678","multi\nline",\n,QWER7890\n'.encode()
    assert F.read_code_file(write(tmp_path, "list.csv", data)).split("\n") == [
        "ABCD-1234", "ZZZ888", "EFGH,5678", "multi", "line", "QWER7890"]  # the quoted cell keeps its LF


def test_tsv_cells(tmp_path: Path) -> None:
    data = "ABCD-1234\tused\nZZZ888\t\n".encode()
    assert F.read_code_file(write(tmp_path, "list.tsv", data)) == "ABCD-1234\nused\nZZZ888"


@pytest.mark.parametrize("header", ["序號", "Code", "兌換碼", "Gift Code", "コード", " KEY "])
def test_csv_with_a_code_column_header_reads_that_column_only(tmp_path: Path, header: str) -> None:
    data = f"#,{header},Status\n1,ABCD-1234,2026-11-17T15:04:05+08:00\n2,ZZZ888,Redeemed\n".encode()
    assert F.read_code_file(write(tmp_path, "h.csv", data)) == "ABCD-1234\nZZZ888"


def test_own_csv_export_reimports_codes_only(tmp_path: Path) -> None:
    items = [CodeItem(code="ABCD-1234", source=CodeSource.PASTE, status=CodeStatus.SUCCESS, message="Redeemed OK"),
             CodeItem(code="ZZZ888", source=CodeSource.IMAGE, confidence=0.93, message="=cmd")]
    for lang in ("zh-TW", "en"):
        i18n.set_language(lang)
        path = tmp_path / f"export-{lang}.csv"
        export_codes_csv(path, items)
        text = F.read_code_file(path)
        assert text == "ABCD-1234\nZZZ888", lang


def test_unparsable_csv_falls_back_to_text(tmp_path: Path) -> None:
    huge_cell = '"' + "A" * 200_000  # unterminated quote beyond the csv field limit
    text = F.read_code_file(write(tmp_path, "broken.csv", (huge_cell + "\nZZZ888\n").encode()))
    assert "ZZZ888" in text


@pytest.mark.parametrize(("payload", "expected"), [
    (["ABCD-1234", "ZZZ888", "", None, True], "ABCD-1234\nZZZ888"),
    ([12345678, "ZZZ888"], "12345678\nZZZ888"),
    ([{"code": "ABCD-1234", "note": "x"}, {"Code": "ZZZ888"}, {"other": "IGNORED1"}], "ABCD-1234\nZZZ888"),
    ({"codes": ["ABCD-1234", {"code": "ZZZ888"}]}, "ABCD-1234\nZZZ888"),
    ({"schema_version": 1, "items": [{"code": "ABCD-1234", "status": "pending"}]}, "ABCD-1234"),
    ({"code": "ABCD-1234"}, "ABCD-1234"),
])
def test_json_layouts(tmp_path: Path, payload: object, expected: str) -> None:
    path = write(tmp_path, "codes.json", json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    assert F.read_code_file(path) == expected


@pytest.mark.parametrize("payload", [[], {"codes": []}, {"name": "x"}, [1.5, False, None], "just text"])
def test_json_without_codes_raises(tmp_path: Path, payload: object) -> None:
    with pytest.raises(F.CodeFileError, match="JSON"):
        F.read_code_file(write(tmp_path, "empty.json", json.dumps(payload).encode()))


def test_invalid_json_raises(tmp_path: Path) -> None:
    with pytest.raises(F.CodeFileError, match="無法解析 JSON 檔案：bad.json"):
        F.read_code_file(write(tmp_path, "bad.json", b"[\"ABCD-1234\", "))


def test_missing_file_and_folder(tmp_path: Path) -> None:
    with pytest.raises(F.CodeFileError, match="找不到檔案：nope.txt"):
        F.read_code_file(tmp_path / "nope.txt")
    with pytest.raises(F.CodeFileError, match="資料夾"):
        F.read_code_file(tmp_path)
    i18n.set_language("en")
    with pytest.raises(F.CodeFileError, match="File not found: nope.txt"):
        F.read_code_file(tmp_path / "nope.txt")


def test_too_large_file(tmp_path: Path) -> None:
    path = write(tmp_path, "big.txt", b"A" * 2048)
    with pytest.raises(F.CodeFileError, match="檔案太大"):
        F.read_code_file(path, max_bytes=1000)
    assert F.read_code_file(path, max_bytes=2048) == "A" * 2048


def test_other_extensions_read_as_text_and_chinese_paths(tmp_path: Path) -> None:
    path = write(tmp_path, "序號 清單/直播 兌換碼.log", "直播碼 ABCD-1234".encode("cp950"))
    assert F.read_code_file(path) == "直播碼 ABCD-1234"
    assert F.read_code_file(write(tmp_path, "x.unknown", b"ZZZ888")) == "ZZZ888"
    assert F.read_code_file(write(tmp_path, "empty.txt", b"")) == ""
    assert F.read_code_file(str(path)) == "直播碼 ABCD-1234"  # str paths work too


def test_file_dialog_filter() -> None:
    zh = F.file_dialog_filter()
    assert zh.startswith("序號清單 (") and zh.endswith(";;所有檔案 (*)")
    assert all(f"*{ext}" in zh for ext in F.SUPPORTED_EXTENSIONS)
    i18n.set_language("en")
    assert F.file_dialog_filter() == "Code lists (*.txt *.csv *.tsv *.json *.log);;All files (*)"
