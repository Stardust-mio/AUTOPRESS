"""G1 CSV export: UTF-8 BOM, CRLF, localized headers, formula-injection guard, atomic writes
(SPEC 9, decisions T07 / T36, 8.2 row G1). Files: tmp_path only."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from autopress import i18n, storage
from autopress.codes import csvexport as C
from autopress.models import AttemptRecord, CodeItem, CodeSource, CodeStatus

ITEMS = [
    CodeItem(code="ABCD-1234", source=CodeSource.PASTE, status=CodeStatus.SUCCESS, message="兌換成功",
             added_at="2026-11-17T15:04:05+08:00"),
    CodeItem(code="Q8ZL0W3NBX5C", source=CodeSource.IMAGE, status=CodeStatus.REVIEW, confidence=0.714,
             message="=HYPERLINK(\"http://x\")", added_at="2026-11-17T15:05:00+08:00"),
    CodeItem(code="ZZZ888", source=CodeSource.SNIP, status=CodeStatus.INVALID, confidence=1.0,
             message="-5 points\nsecond line", added_at="not a time"),
]
RECORDS = [
    AttemptRecord(code="ABCD-1234", game="原神", profile_name="網頁兌換", status=CodeStatus.SUCCESS,
                  message="@SUM(A1)", started_at="2026-11-17T15:00:00+08:00",
                  finished_at="2026-11-17T15:00:04+08:00", duration_ms=4200),
    AttemptRecord(code="ZZZ888", game="原神", profile_name="網頁兌換", status=CodeStatus.USED,
                  message="+cmd|' /C calc'!A0", started_at="2026-11-17T15:01:00+08:00", duration_ms=0),
]


def read(path: Path) -> tuple[bytes, list[list[str]]]:
    raw = path.read_bytes()
    return raw, list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))


def test_codes_csv_bom_crlf_header_and_rows(tmp_path: Path) -> None:
    path = tmp_path / "codes.csv"
    C.export_codes_csv(path, ITEMS)
    raw, rows = read(path)
    assert raw.startswith(b"\xef\xbb\xbf")
    assert raw.count(b"\r\n") == 4 and raw.endswith(b"\r\n")  # header + 3 rows (the quoted LF stays LF)
    assert rows[0] == ["#", "序號", "狀態", "訊息", "來源", "辨識信心", "加入時間"]
    assert rows[1] == ["1", "ABCD-1234", "成功", "兌換成功", "貼上", "", "2026-11-17 15:04:05"]
    assert rows[2][:2] == ["2", "Q8ZL0W3NBX5C"] and rows[2][2] == "需確認" and rows[2][5] == "71"
    assert rows[3][5] == "100" and rows[3][6] == "not a time" and rows[3][4] == "截圖"


def test_formula_injection_prefix(tmp_path: Path) -> None:
    path = tmp_path / "codes.csv"
    C.export_codes_csv(path, ITEMS)
    _raw, rows = read(path)
    assert rows[2][3] == "'=HYPERLINK(\"http://x\")"
    assert rows[3][3] == "'-5 points\nsecond line"
    assert rows[1][3] == "兌換成功"  # harmless text unchanged
    for start in ("=", "+", "-", "@", "\t", "\r"):
        assert C.safe_cell(start + "x") == "'" + start + "x"
    assert C.safe_cell("x=1") == "x=1" and C.safe_cell(None) == "" and C.safe_cell(42) == "42"


def test_history_csv(tmp_path: Path) -> None:
    path = tmp_path / "history.csv"
    C.export_history_csv(path, RECORDS)
    raw, rows = read(path)
    assert raw.startswith(b"\xef\xbb\xbf") and raw.endswith(b"\r\n")
    assert rows[0] == ["時間", "序號", "遊戲", "設定檔", "結果", "訊息", "耗時(ms)"]
    assert rows[1] == ["2026-11-17 15:00:04", "ABCD-1234", "原神", "網頁兌換", "成功", "'@SUM(A1)", "4200"]
    assert rows[2][0] == "2026-11-17 15:01:00"  # no finished_at: started_at
    assert rows[2][4] == "已使用" and rows[2][5].startswith("'+cmd")


def test_headers_follow_the_language(tmp_path: Path) -> None:
    i18n.set_language("en")
    C.export_codes_csv(tmp_path / "c.csv", ITEMS[:1])
    C.export_history_csv(tmp_path / "h.csv", RECORDS[:1])
    assert read(tmp_path / "c.csv")[1][0] == ["#", "Code", "Status", "Message", "Source", "Confidence", "Added"]
    assert read(tmp_path / "c.csv")[1][1][2:5] == ["Redeemed", "兌換成功", "Paste"]  # labels localized
    assert read(tmp_path / "h.csv")[1][0] == ["Time", "Code", "Game", "Profile", "Status", "Message", "Duration (ms)"]


def test_empty_export_has_the_header_only(tmp_path: Path) -> None:
    C.export_codes_csv(tmp_path / "e.csv", [])
    raw, rows = read(tmp_path / "e.csv")
    assert len(rows) == 1 and raw.count(b"\r\n") == 1


def test_writes_go_through_write_bytes_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[Path, bytes]] = []
    monkeypatch.setattr(storage, "write_bytes_atomic", lambda p, d: calls.append((Path(p), d)))
    monkeypatch.setattr("tempfile.mkstemp", lambda *a, **k: pytest.fail("mkstemp must not be used"))
    C.export_codes_csv(tmp_path / "a.csv", ITEMS)
    C.export_history_csv(tmp_path / "b.csv", RECORDS)
    assert [p.name for p, _d in calls] == ["a.csv", "b.csv"]
    assert all(d.startswith(b"\xef\xbb\xbf") for _p, d in calls)
    assert not (tmp_path / "a.csv").exists()  # nothing written behind the helper's back


def test_unwritable_target_raises_storage_error(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    with pytest.raises(storage.StorageError):
        C.export_codes_csv(blocker / "codes.csv", ITEMS)  # parent is a file


def test_chinese_path(tmp_path: Path) -> None:
    path = tmp_path / "匯出 資料夾" / "序號 結果.csv"
    C.export_history_csv(path, RECORDS)
    assert read(path)[1][1][1] == "ABCD-1234"
