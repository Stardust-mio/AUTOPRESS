"""G1 history: append-only JSON lines, latest / is_done, query, in-place update, remove / clear,
corrupt lines, evidence pruning (SPEC 5.1, 5.8, 8.2 row G1). Files: the test's AUTOPRESS_HOME."""

from __future__ import annotations

import json
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from autopress import storage
from autopress.codes import history as history_mod
from autopress.codes.history import HistoryStore
from autopress.models import AttemptRecord, CodeStatus, ResultClass

GAME_A = "game:原神"
GAME_B = "game:星穹鐵道"


@pytest.fixture
def hpath(isolated_home: Path) -> Path:
    return isolated_home / "history.jsonl"


@pytest.fixture
def h(hpath: Path) -> HistoryStore:
    store = HistoryStore(hpath)
    store.load()
    return store


def rec(code: str, status: CodeStatus = CodeStatus.SUCCESS, game_key: str = GAME_A, **kw: object) -> AttemptRecord:
    kw.setdefault("game", "原神" if game_key == GAME_A else "星穹鐵道")
    return AttemptRecord(code=code, status=status, game_key=game_key, **kw)  # type: ignore[arg-type]


def lines(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def test_append_persists_one_line_per_record(h: HistoryStore, hpath: Path) -> None:
    notified: list[int] = []
    h.subscribe(lambda: notified.append(len(h.records())))
    h.append(rec("ABCD-1234", message="兌換成功", result=ResultClass.SUCCESS, duration_ms=4200))
    h.append(rec("ZZZ888", CodeStatus.INVALID, profile_name="網頁兌換"))
    rows = lines(hpath)
    assert [r["code"] for r in rows] == ["ABCD-1234", "ZZZ888"]
    assert all(r["schema_version"] == 1 for r in rows)
    assert rows[0]["status"] == "success" and rows[0]["result"] == "success" and rows[0]["message"] == "兌換成功"
    assert notified == [1, 2]
    again = HistoryStore(hpath)
    again.load()
    assert [(r.id, r.code, r.status, r.duration_ms) for r in again.records()] == [
        (r.id, r.code, r.status, r.duration_ms) for r in h.records()]


def test_append_renews_empty_or_used_ids(h: HistoryStore) -> None:
    first = rec("ABCD1234", id="same")
    second = rec("EFGH5678", id="same")
    h.append(first)
    h.append(second)
    h.append(rec("ZZZ888", id=""))
    ids = [r.id for r in h.records()]
    assert ids[0] == "same" and len(set(ids)) == 3 and all(ids)


def test_latest_and_is_done_by_code_key_and_game(h: HistoryStore) -> None:
    h.append(rec("ABCD-1234", CodeStatus.INVALID))
    h.append(rec("ABCD1234", CodeStatus.SUCCESS))
    h.append(rec("ABCD 1234", CodeStatus.USED, game_key=GAME_B))
    assert h.latest(GAME_A, "abcd1234") is None  # case is part of the code
    assert h.latest(GAME_A, "ABCD_1234").status is CodeStatus.SUCCESS
    assert h.latest(GAME_B, "ABCD-1234").status is CodeStatus.USED
    assert h.is_done(GAME_A, "ABCD1234", {CodeStatus.SUCCESS, CodeStatus.USED})
    assert not h.is_done(GAME_A, "ABCD1234", [CodeStatus.USED])
    assert h.is_done(GAME_A, "ABCD1234", ["success"])
    assert not h.is_done(GAME_A, "NOPE1234", [CodeStatus.SUCCESS])
    assert h.latest("", "ABCD1234") is None


def test_query_text_status_game_newest_first(h: HistoryStore) -> None:
    h.append(rec("ABCD-1234", CodeStatus.SUCCESS, message="Code redeemed", profile_name="網頁兌換"))
    h.append(rec("ZZZ888", CodeStatus.INVALID, message="兌換碼無效"))
    h.append(rec("QWER7890", CodeStatus.USED, game_key=GAME_B, profile_name="Star Rail web"))
    codes = lambda rs: [r.code for r in rs]  # noqa: E731
    assert codes(h.query()) == ["QWER7890", "ZZZ888", "ABCD-1234"]
    assert codes(h.query("abcd1234")) == ["ABCD-1234"]  # case-insensitive, separators ignored
    assert codes(h.query("redeemed")) == ["ABCD-1234"]
    assert codes(h.query("無效")) == ["ZZZ888"]
    assert codes(h.query("星穹")) == ["QWER7890"]  # game display name
    assert codes(h.query("star rail")) == ["QWER7890"]  # profile name
    assert codes(h.query(statuses=[CodeStatus.SUCCESS, CodeStatus.USED])) == ["QWER7890", "ABCD-1234"]
    assert codes(h.query(game_key=GAME_A)) == ["ZZZ888", "ABCD-1234"]
    assert codes(h.query("zzz", statuses=["invalid"], game_key=GAME_A)) == ["ZZZ888"]
    assert h.query(statuses=[]) == []


def test_update_keeps_id_and_position(h: HistoryStore, hpath: Path) -> None:
    h.append(rec("ABCD1234", CodeStatus.REVIEW, result=ResultClass.UNKNOWN, message="無法判讀"))
    h.append(rec("EFGH5678", CodeStatus.SUCCESS))
    target = h.records()[0]
    notified: list[bool] = []
    h.subscribe(lambda: notified.append(True))
    updated = h.update(target.id, status=CodeStatus.USED, result="used", message="此兌換碼已被使用")
    assert updated is h.records()[0] and updated.id == target.id
    assert (updated.status, updated.result) == (CodeStatus.USED, ResultClass.USED)
    assert h.latest(GAME_A, "ABCD1234") is updated and notified == [True]
    rows = lines(hpath)
    assert [r["id"] for r in rows] == [target.id, h.records()[1].id] and rows[0]["status"] == "used"
    again = HistoryStore(hpath)
    again.load()
    assert again.records()[0].message == "此兌換碼已被使用"
    with pytest.raises(KeyError):
        h.update("missing", status=CodeStatus.USED)
    with pytest.raises(AttributeError):
        h.update(target.id, nope=1)
    with pytest.raises(ValueError):
        h.update(target.id, id="x")


def test_update_of_code_reindexes(h: HistoryStore) -> None:
    h.append(rec("ABCD1234"))
    h.update(h.records()[0].id, code="WXYZ9876")
    assert h.latest(GAME_A, "ABCD1234") is None and h.latest(GAME_A, "WXYZ9876") is not None


def test_remove_and_clear_rewrite_atomically(h: HistoryStore, hpath: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for code in ("AAAA1111", "BBBB2222", "CCCC3333"):
        h.append(rec(code))
    calls: list[Path] = []
    real = storage.write_bytes_atomic
    monkeypatch.setattr(storage, "write_bytes_atomic", lambda p, d: (calls.append(Path(p)), real(p, d)))
    monkeypatch.setattr("tempfile.mkstemp", lambda *a, **k: pytest.fail("mkstemp must not be used"))
    first = h.records()[0].id
    assert h.remove([first, "missing"]) == 1
    assert [r["code"] for r in lines(hpath)] == ["BBBB2222", "CCCC3333"]
    assert h.remove(["missing"]) == 0
    assert h.clear() == 2 and h.records() == [] and hpath.read_bytes() == b""
    assert calls == [hpath, hpath]
    assert h.latest(GAME_A, "BBBB2222") is None


def test_corrupt_lines_are_skipped_and_appends_survive_a_cut_line(hpath: Path) -> None:
    good = json.dumps({"schema_version": 1, "id": "a1", "code": "ABCD1234", "status": "success",
                       "game_key": GAME_A}, ensure_ascii=False)
    hpath.write_bytes(b"\xef\xbb\xbf" + good.encode() + b"\r\n" + b"{broken json\n" + b"[1, 2]\n"
                      + b'{"code": "\xff\xfe bad utf8"}\n' + b"\n"
                      + json.dumps({"id": "a1", "code": "DUP-ID", "status": "used", "extra": 1}).encode()
                      + b"\n" + b'{"id": "cut", "code": "EFG')  # last line cut off by a crash
    store = HistoryStore(hpath)
    store.load()
    assert [r.code for r in store.records()] == ["ABCD1234", "DUP-ID"]
    assert store.skipped_lines == 4
    assert store.records()[0].id == "a1" and store.records()[1].id != "a1"
    store.append(rec("ZZZ888"))
    again = HistoryStore(hpath)
    again.load()
    assert [r.code for r in again.records()] == ["ABCD1234", "DUP-ID", "ZZZ888"]


def test_append_failure_is_logged_not_raised(h: HistoryStore, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(self: HistoryStore, line: str) -> None:
        raise PermissionError("locked")

    monkeypatch.setattr(HistoryStore, "_append_line", boom)
    h.append(rec("ABCD1234"))
    assert len(h.records()) == 1 and "locked" in h.last_error


def test_games_newest_first(h: HistoryStore) -> None:
    h.append(rec("AAAA1111", game_key=GAME_A))
    h.append(rec("BBBB2222", game_key=GAME_B))
    h.append(rec("CCCC3333", game_key="", game=""))
    h.append(rec("DDDD4444", game_key=GAME_A, game="原神（台服）"))
    assert h.games() == [(GAME_A, "原神（台服）"), ("", ""), (GAME_B, "星穹鐵道")]


def test_attempts_on_counts_today_without_manual_marks(h: HistoryStore) -> None:
    now = datetime.now().astimezone()
    yesterday = (now - timedelta(days=1)).isoformat(timespec="seconds")
    h.append(rec("AAAA1111", started_at=now.isoformat(timespec="seconds")))
    h.append(rec("BBBB2222", started_at="", finished_at=now.isoformat(timespec="seconds")))
    h.append(rec("CCCC3333", started_at=yesterday))
    h.append(rec("DDDD4444", run_id="manual", started_at=now.isoformat(timespec="seconds")))
    assert h.attempts_on() == 2
    assert h.attempts_on(date.today() - timedelta(days=1)) == 1


def test_default_path_is_the_data_folder(isolated_home: Path) -> None:
    store = HistoryStore()
    store.load()
    store.append(rec("ABCD1234"))
    assert store.path == isolated_home / "history.jsonl" and store.path.exists()


# ----------------------------------------------------------------------------- evidence


def _evidence(home: Path, day: date, name: str) -> str:
    folder = home / "evidence" / day.isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(b"\x89PNG fake")
    return f"evidence/{day.isoformat()}/{name}"


def test_prune_evidence_by_folder_date_and_mtime(h: HistoryStore, isolated_home: Path, hpath: Path) -> None:
    today = date.today()
    old = _evidence(isolated_home, today - timedelta(days=31), "run1_1.png")
    edge = _evidence(isolated_home, today - timedelta(days=30), "run2_1.png")
    new = _evidence(isolated_home, today, "run3_1.png")
    loose_dir = isolated_home / "evidence" / "misc"
    loose_dir.mkdir()
    (loose_dir / "stale.png").write_bytes(b"x")
    (loose_dir / "fresh.png").write_bytes(b"x")
    stale_ts = time.time() - 40 * 86400
    os.utime(loose_dir / "stale.png", (stale_ts, stale_ts))
    (isolated_home / "evidence" / "notes.txt").write_text("keep", encoding="utf-8")
    h.append(rec("AAAA1111", evidence_path=old))
    h.append(rec("BBBB2222", evidence_path=edge))
    h.append(rec("CCCC3333", evidence_path=new))
    h.append(rec("DDDD4444", evidence_path="evidence/2020-01-01/gone.png"))  # file already missing
    assert h.prune_evidence(0) == 0  # 0 = keep everything
    notified: list[bool] = []
    h.subscribe(lambda: notified.append(True))
    assert h.prune_evidence(30) == 2  # the 31-day-old folder file and the stale loose file
    assert not (isolated_home / old).exists() and (isolated_home / edge).exists() and (isolated_home / new).exists()
    assert not (isolated_home / old).parent.exists()  # empty date folder removed
    assert (loose_dir / "fresh.png").exists() and (isolated_home / "evidence" / "notes.txt").exists()
    assert [r.evidence_path for r in h.records()] == ["", edge, new, ""]
    assert notified == [True]
    assert [r["evidence_path"] for r in lines(hpath)] == ["", edge, new, ""]
    assert h.prune_evidence(30) == 0


def test_remove_deletes_unshared_evidence_inside_the_evidence_folder(h: HistoryStore, isolated_home: Path,
                                                                      tmp_path: Path) -> None:
    today = date.today()
    mine = _evidence(isolated_home, today, "run1_1.png")
    shared = _evidence(isolated_home, today, "run1_2.png")
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"x")
    h.append(rec("AAAA1111", evidence_path=mine))
    h.append(rec("BBBB2222", evidence_path=shared))
    h.append(rec("BBBB2222", evidence_path=shared))
    h.append(rec("CCCC3333", evidence_path=str(outside)))
    h.append(rec("DDDD4444", evidence_path="../outside.png"))
    a, b1, _b2, c, d = (r.id for r in h.records())
    h.remove([a, b1, c, d])
    assert not (isolated_home / mine).exists()
    assert (isolated_home / shared).exists()  # still used by the remaining record
    assert outside.exists()  # never outside <data folder>/evidence
    h.clear()
    assert not (isolated_home / shared).exists() and not (isolated_home / "evidence" / today.isoformat()).exists()


def test_module_has_no_stub_marker() -> None:
    assert not hasattr(history_mod, "__stub__")
