"""G1 queue: semantics, events and persistence of CodeQueue (SPEC 5.1, 5.7, 5.9, 8.2 row G1).
Files live in the test's AUTOPRESS_HOME (isolated_home) or tmp_path only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from autopress import i18n, paths, storage
from autopress.codes import queue as queue_mod
from autopress.codes.history import HistoryStore
from autopress.codes.presets import get_format
from autopress.codes.queue import CodeQueue
from autopress.models import (
    AttemptRecord,
    CodeCandidate,
    CodeSource,
    CodeStatus,
    QueueEvent,
    QueueEventKind,
    RunSelection,
)

GAME_A = "game:原神"
GAME_B = "game:星穹鐵道"
RECOVERY_ZH = "上次執行中斷，請確認是否已兌換"
RECOVERY_EN = "The last run was interrupted; check whether this code was redeemed"


@pytest.fixture
def qpath(isolated_home: Path) -> Path:
    return isolated_home / "queue.json"


@pytest.fixture
def q(qpath: Path) -> CodeQueue:
    queue = CodeQueue(qpath)
    queue.load()
    return queue


@pytest.fixture
def events(q: CodeQueue) -> list[QueueEvent]:
    got: list[QueueEvent] = []
    q.subscribe(got.append)
    return got


def cand(code: str, **kw: object) -> CodeCandidate:
    return CodeCandidate(code=code, raw=kw.pop("raw", code), **kw)  # type: ignore[arg-type]


def add(q: CodeQueue, *codes: str, game_key: str = GAME_A, game: str = "原神", **kw: object) -> list[str]:
    return q.add_candidates([cand(c) for c in codes], CodeSource.PASTE, game_key=game_key, game=game, **kw).added


def codes_of(q: CodeQueue) -> list[str]:
    return [i.code for i in q.items()]


# ----------------------------------------------------------------------------- adding


def test_add_candidates_statuses_fields_and_event(q: CodeQueue, events: list[QueueEvent]) -> None:
    res = q.add_candidates([
        cand("ABCD-1234"),
        cand("Q8ZL0W3NBX5C", flagged=[4], lookalikes=[0, 1, 4], char_confs=[0.9] * 12),
        cand("ZZZ888", lookalikes=[3, 4, 5]),
    ], CodeSource.IMAGE, source_detail="shot.png", game_key=GAME_A, game="原神")
    assert len(res.added) == 3 and (res.duplicates, res.skipped_history, res.invalid) == (0, 0, 0)
    a, b, c = (q.get(i) for i in res.added)
    assert a.status is CodeStatus.PENDING and a.game_key == GAME_A and a.game == "原神"
    assert a.source is CodeSource.IMAGE and a.source_detail == "shot.png" and a.checked and a.attempts == 0
    assert b.status is CodeStatus.REVIEW and b.flagged == [4] and b.lookalikes == [0, 1, 4]
    assert b.char_confs == [0.9] * 12 and b.confidence == pytest.approx(0.9)
    assert c.status is CodeStatus.PENDING and c.lookalikes == [3, 4, 5]  # look-alikes never cause REVIEW
    assert events == [QueueEvent(QueueEventKind.ADDED, res.added)]


def test_candidate_data_is_sanitised(q: CodeQueue) -> None:
    res = q.add_candidates([cand("  ABCD1234\x07 ", flagged=[1, 99, -1], lookalikes=[50], char_confs=[0.5, 0.5]),
                            cand("   ")], CodeSource.PASTE)
    item = q.get(res.added[0])
    assert item.code == "ABCD1234" and item.flagged == [1] and item.lookalikes == [] and item.char_confs == []
    assert res.invalid == 1


def test_duplicates_are_per_game(q: CodeQueue) -> None:
    add(q, "ABCD-1234")
    res = q.add_candidates([cand("ABCD1234"), cand("abcd1234"), cand("ABCD 1234"), cand("EFGH5678"),
                            cand("EFGH-5678")], CodeSource.PASTE, game_key=GAME_A)
    assert res.duplicates == 3  # separators and spaces ignored; the second EFGH is a duplicate of the first
    assert codes_of(q) == ["ABCD-1234", "abcd1234", "EFGH5678"]  # case kept: abcd1234 is another code
    other = q.add_candidates([cand("ABCD-1234")], CodeSource.PASTE, game_key=GAME_B, game="星穹鐵道")
    assert len(other.added) == 1 and other.duplicates == 0  # same code for another game is allowed
    unassigned = q.add_candidates([cand("ABCD-1234")], CodeSource.PASTE)
    assert len(unassigned.added) == 1 and q.get(unassigned.added[0]).game == ""


def test_history_skip_only_for_a_game_and_listed_statuses(q: CodeQueue, isolated_home: Path) -> None:
    hist = HistoryStore(isolated_home / "history.jsonl")
    hist.load()
    hist.append(AttemptRecord(code="ABCD-1234", game_key=GAME_A, status=CodeStatus.SUCCESS))
    hist.append(AttemptRecord(code="EFGH5678", game_key=GAME_A, status=CodeStatus.SUCCESS))
    hist.append(AttemptRecord(code="EFGH5678", game_key=GAME_A, status=CodeStatus.INVALID))  # latest wins
    hist.append(AttemptRecord(code="SUBM1TTED", game_key=GAME_A, status=CodeStatus.SUBMITTED))
    skip = (CodeStatus.SUCCESS, CodeStatus.USED)
    res = q.add_candidates([cand("ABCD1234"), cand("EFGH5678"), cand("SUBM1TTED")], CodeSource.PASTE,
                           history=hist, game_key=GAME_A, skip_statuses=skip)
    assert res.skipped_history == 1 and codes_of(q) == ["EFGH5678", "SUBM1TTED"]
    res_b = q.add_candidates([cand("ABCD1234")], CodeSource.PASTE, history=hist, game_key=GAME_B, skip_statuses=skip)
    assert len(res_b.added) == 1  # history of another game does not count
    res_none = q.add_candidates([cand("ABCD1234")], CodeSource.PASTE, history=hist, game_key="", skip_statuses=skip)
    assert len(res_none.added) == 1  # unassigned imports never skip
    res_off = q.add_candidates([cand("ABCD-1234")], CodeSource.PASTE, history=hist, game_key=GAME_A)
    assert len(res_off.added) == 1  # skip_statuses () = switch off
    hist.append(AttemptRecord(code="STR1NG-CODE", game_key=GAME_A, status=CodeStatus.USED))
    res_str = q.add_candidates([cand("STR1NGCODE")], CodeSource.PASTE, history=hist, game_key=GAME_A,
                               skip_statuses=["used", "bogus"])
    assert res_str.skipped_history == 1 and not res_str.added  # status values as strings work too


def test_add_codes_with_and_without_format(q: CodeQueue) -> None:
    res = q.add_codes(["abcde fghij klmno", "too-short", "ABCDE-FGHIJ-KLMNO"], fmt=get_format("steam"),
                      game_key=GAME_A, game="原神")
    assert codes_of(q) == ["ABCDE-FGHIJ-KLMNO"] and res.invalid == 1 and res.duplicates == 1
    assert q.get(res.added[0]).source is CodeSource.MANUAL and q.get(res.added[0]).raw == "abcde fghij klmno"
    rep = q.add_codes(["ABCDEFGHJKLMNOPQ"], CodeSource.FILE, fmt=get_format("nintendo"))
    item = q.get(rep.added[0])
    assert item.code == "ABCDEFGHJKLMN0PQ" and item.flagged == [13] and item.status is CodeStatus.REVIEW
    raw = q.add_codes([" kept as given ", ""], source_detail="list.txt")
    assert [q.get(i).code for i in raw.added] == ["kept as given"] and raw.invalid == 1
    assert q.add_codes("SINGLE123").added  # a single string is one code


# ----------------------------------------------------------------------------- persistence


def test_reload_keeps_order_and_fields(q: CodeQueue, qpath: Path) -> None:
    ids = q.add_candidates([cand("ABCD-1234"), cand("Q8ZL0W3NBX5C", flagged=[4], lookalikes=[4],
                                                    char_confs=[0.8] * 12)],
                           CodeSource.SNIP, source_detail="區域", game_key=GAME_A, game="原神").added
    add(q, "ZZZ888", game_key="", game="")
    q.update(ids[0], status=CodeStatus.USED, message="此兌換碼已被使用", attempts=2)
    q.set_checked([ids[1]], False)
    q.move([ids[1]], -1)
    again = CodeQueue(qpath)
    again.load()
    assert [(i.id, i.code, i.status, i.message, i.checked, i.game_key, i.game, i.flagged, i.lookalikes,
             i.char_confs, i.confidence, i.source, i.source_detail, i.attempts, i.added_at)
            for i in again.items()] == [
        (i.id, i.code, i.status, i.message, i.checked, i.game_key, i.game, i.flagged, i.lookalikes,
         i.char_confs, i.confidence, i.source, i.source_detail, i.attempts, i.added_at) for i in q.items()]
    data = json.loads(qpath.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1 and len(data["items"]) == 3 and data["items"][0]["code"] == "Q8ZL0W3NBX5C"


def test_missing_file_gives_empty_queue_and_reset(qpath: Path) -> None:
    q = CodeQueue(qpath)
    got: list[QueueEvent] = []
    q.subscribe(got.append)
    q.load()
    assert len(q) == 0 and got == [QueueEvent(QueueEventKind.RESET, [])]
    assert not qpath.exists()  # loading never writes


def test_broken_file_is_quarantined(qpath: Path) -> None:
    qpath.write_text("{not json", encoding="utf-8")
    q = CodeQueue(qpath)
    q.load()
    assert len(q) == 0
    assert list(qpath.parent.glob("queue.json.broken-*"))  # storage.read_json renamed it (data folder)
    add(q, "ABCD1234")
    assert json.loads(qpath.read_text(encoding="utf-8"))["items"][0]["code"] == "ABCD1234"


def test_wrong_shape_is_kept_aside_before_the_first_write(qpath: Path) -> None:
    qpath.write_text('["ABCD-1234", "EFGH-5678"]', encoding="utf-8")
    q = CodeQueue(qpath)
    q.load()
    assert len(q) == 0 and not list(qpath.parent.glob("queue.json.broken-*"))
    add(q, "ZZZ888")
    (aside,) = qpath.parent.glob("queue.json.broken-*")
    assert json.loads(aside.read_text(encoding="utf-8")) == ["ABCD-1234", "EFGH-5678"]


def test_bad_entries_are_dropped_or_repaired(qpath: Path) -> None:
    qpath.write_text(json.dumps({"schema_version": 1, "items": [
        "junk", {"code": ""}, {"id": "dup", "code": "ABCD1234", "flagged": [2, 40], "char_confs": [0.5]},
        {"id": "dup", "code": "EFGH5678", "status": "no-such-status"}, {"code": "ZZZ888", "attempts": -5},
    ]}), encoding="utf-8")
    q = CodeQueue(qpath)
    q.load()
    a, b, c = q.items()
    assert [a.code, b.code, c.code] == ["ABCD1234", "EFGH5678", "ZZZ888"]
    assert a.id == "dup" and b.id != "dup" and len({a.id, b.id, c.id}) == 3
    assert a.flagged == [2] and a.char_confs == [] and b.status is CodeStatus.PENDING and c.attempts == 0


def test_newer_schema_loads_and_saves_current_version(qpath: Path) -> None:
    qpath.write_text(json.dumps({"schema_version": 99, "future": True,
                                 "items": [{"code": "ABCD1234", "new_field": 1}]}), encoding="utf-8")
    q = CodeQueue(qpath)
    q.load()
    assert codes_of(q) == ["ABCD1234"]
    q.save()
    assert json.loads(qpath.read_text(encoding="utf-8"))["schema_version"] == 1


def test_autosave_off_writes_only_on_save(qpath: Path) -> None:
    q = CodeQueue(qpath, autosave=False)
    q.load()
    add(q, "ABCD1234")
    assert not qpath.exists()
    q.save()
    assert qpath.exists()


def test_writes_go_through_write_bytes_atomic(q: CodeQueue, qpath: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Path] = []
    real = storage.write_bytes_atomic

    def spy(path: Path, data: bytes) -> None:
        calls.append(Path(path))
        real(path, data)

    monkeypatch.setattr(storage, "write_bytes_atomic", spy)
    monkeypatch.setattr("tempfile.mkstemp", lambda *a, **k: pytest.fail("mkstemp must not be used"))
    add(q, "ABCD1234")
    assert calls == [qpath]


def test_autosave_failure_is_logged_not_raised(q: CodeQueue, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(path: Path, data: object) -> None:
        raise storage.StorageError("disk full")

    monkeypatch.setattr(storage, "write_json", boom)
    got: list[QueueEvent] = []
    q.subscribe(got.append)
    ids = add(q, "ABCD1234")
    assert ids and q.last_error == "disk full" and got[-1].kind is QueueEventKind.ADDED
    with pytest.raises(storage.StorageError):
        q.save()


def test_default_path_is_the_data_folder(isolated_home: Path) -> None:
    q = CodeQueue()
    q.load()
    add(q, "ABCD1234")
    assert q.path == paths.queue_path() == isolated_home / "queue.json"
    assert (isolated_home / "queue.json").exists()


# ----------------------------------------------------------------------------- changing


def test_update_semantics(q: CodeQueue, events: list[QueueEvent], monkeypatch: pytest.MonkeyPatch) -> None:
    (cid,) = q.add_candidates([cand("Q8ZL0W3NBX5C", flagged=[4], lookalikes=[0, 4], char_confs=[0.7] * 12)],
                              CodeSource.IMAGE, game_key=GAME_A).added
    monkeypatch.setattr(queue_mod, "now_iso", lambda: "2030-01-01T00:00:00+08:00")
    item = q.update(cid, message="note", checked=False)
    assert item.status is CodeStatus.REVIEW and item.flagged == [4] and item.updated_at.startswith("2030")
    item = q.update(cid, code=" Q8ZLOW3NBX5C ")
    assert item.code == "Q8ZLOW3NBX5C" and item.flagged == [] and item.status is CodeStatus.PENDING
    assert item.lookalikes == [] and item.char_confs == []  # they pointed at the old characters
    item = q.update(cid, code="Q8ZL0W3NBX5C", lookalikes=[4])
    assert item.lookalikes == [4]
    assert q.update(cid, status="used").status is CodeStatus.USED  # enum values as strings
    assert [e.kind for e in events[-4:]] == [QueueEventKind.UPDATED] * 4 and events[-1].ids == [cid]
    with pytest.raises(KeyError):
        q.update("missing", message="x")
    with pytest.raises(AttributeError):
        q.update(cid, no_such_field=1)
    with pytest.raises(ValueError):
        q.update(cid, id="other")


def test_editing_a_final_code_keeps_its_status(q: CodeQueue) -> None:
    (cid,) = add(q, "ABCD1234")
    q.set_status(cid, CodeStatus.INVALID, "兌換碼無效")
    assert q.update(cid, code="ABCD1235").status is CodeStatus.INVALID


def test_set_status(q: CodeQueue) -> None:
    (cid,) = add(q, "ABCD1234")
    q.update(cid, message="old")
    assert q.set_status(cid, CodeStatus.SUCCESS).message == "old"
    item = q.set_status(cid, CodeStatus.FAILED, "找不到「兌換」按鈕")
    assert (item.status, item.message) == (CodeStatus.FAILED, "找不到「兌換」按鈕")


def test_remove_and_clear(q: CodeQueue, events: list[QueueEvent]) -> None:
    a, b, c, d = add(q, "AAAA1111", "BBBB2222", "CCCC3333", "DDDD4444")
    assert q.remove([b, "missing"]) == 1 and events[-1] == QueueEvent(QueueEventKind.REMOVED, [b])
    assert q.remove(["missing"]) == 0 and events[-1].ids == [b]  # no event when nothing was removed
    assert q.remove(a) == 1  # a single id string
    q.set_status(c, CodeStatus.SUCCESS)
    assert q.clear([CodeStatus.SUCCESS, CodeStatus.USED]) == 1 and codes_of(q) == ["DDDD4444"]
    assert q.clear() == 1 and len(q) == 0
    assert q.clear() == 0


def test_move_keeps_relative_order_and_stops_at_the_ends(q: CodeQueue, events: list[QueueEvent]) -> None:
    a, b, c, d, e = add(q, "AAAA1111", "BBBB2222", "CCCC3333", "DDDD4444", "EEEE5555")
    q.move([c, d], -1)
    assert codes_of(q) == ["AAAA1111", "CCCC3333", "DDDD4444", "BBBB2222", "EEEE5555"]
    assert events[-1] == QueueEvent(QueueEventKind.MOVED, [c, d])
    q.move([d, c], -10)
    assert codes_of(q)[:2] == ["CCCC3333", "DDDD4444"]
    q.move([a, e], 2)
    assert codes_of(q) == ["CCCC3333", "DDDD4444", "BBBB2222", "AAAA1111", "EEEE5555"]
    n = len(events)
    q.move([c], -1)  # already at the top
    q.move([], 3)
    assert len(events) == n


def test_move_to(q: CodeQueue) -> None:
    a, b, c, d = add(q, "AAAA1111", "BBBB2222", "CCCC3333", "DDDD4444")
    q.move_to([d, c], 0)
    assert codes_of(q) == ["CCCC3333", "DDDD4444", "AAAA1111", "BBBB2222"]
    q.move_to([c], 99)
    assert codes_of(q)[-1] == "CCCC3333"
    q.move_to([a], 1)
    assert codes_of(q) == ["DDDD4444", "AAAA1111", "BBBB2222", "CCCC3333"]


def test_checked_and_runnable(q: CodeQueue) -> None:
    a, b, c = add(q, "AAAA1111", "BBBB2222", "CCCC3333")
    (d,) = add(q, "DDDD4444", game_key=GAME_B, game="星穹鐵道")
    (e,) = add(q, "EEEE5555", game_key="", game="")
    q.set_status(b, CodeStatus.COOLDOWN)
    q.set_status(c, CodeStatus.SUCCESS)
    q.set_checked([a], False)

    def ids(items: list) -> list[str]:
        return [i.id for i in items]

    assert ids(q.runnable()) == [a, b, d, e]
    assert ids(q.runnable(RunSelection.CHECKED)) == [b, d, e]
    assert ids(q.runnable(RunSelection.UNFINISHED, game_key=GAME_A)) == [a, b]
    assert ids(q.runnable("checked", game_key=GAME_A)) == [b]
    assert ids(q.runnable(game_key=GAME_B)) == [d]  # unassigned codes never match a profile's game


def test_set_checked_events(q: CodeQueue, events: list[QueueEvent]) -> None:
    a, b = add(q, "AAAA1111", "BBBB2222")
    q.set_checked([a, b, "missing"], False)
    assert events[-1] == QueueEvent(QueueEventKind.UPDATED, [a, b])
    n = len(events)
    q.set_checked([a], False)  # unchanged: no event
    assert len(events) == n and not q.get(a).checked


def test_retry_failed_touches_failed_only(q: CodeQueue, events: list[QueueEvent]) -> None:
    a, b, c = add(q, "AAAA1111", "BBBB2222", "CCCC3333")
    q.set_status(a, CodeStatus.FAILED, "找不到文字")
    q.set_status(b, CodeStatus.REVIEW, "送出後結果區沒有變化")
    q.set_status(c, CodeStatus.INVALID, "無效")
    assert q.retry_failed() == 1
    assert [(i.status, i.message) for i in q.items()] == [
        (CodeStatus.PENDING, ""), (CodeStatus.REVIEW, "送出後結果區沒有變化"), (CodeStatus.INVALID, "無效")]
    assert events[-1] == QueueEvent(QueueEventKind.UPDATED, [a])
    assert q.retry_failed() == 0


def test_reset_confirms_and_resets_final_statuses(q: CodeQueue) -> None:
    (a,) = q.add_candidates([cand("Q8ZL0W3NBX5C", flagged=[4])], CodeSource.IMAGE, game_key=GAME_A).added
    b, c = add(q, "BBBB2222", "CCCC3333")
    q.set_status(b, CodeStatus.INVALID, "無效")
    q.set_status(c, CodeStatus.RUNNING)
    assert q.get(a).status is CodeStatus.REVIEW
    assert q.reset([a, b, c, "missing"]) == 2
    assert [(i.status, i.flagged, i.message) for i in q.items()] == [
        (CodeStatus.PENDING, [], ""), (CodeStatus.PENDING, [], ""), (CodeStatus.RUNNING, [], "")]


def test_assign_game(q: CodeQueue, events: list[QueueEvent]) -> None:
    (keep,) = add(q, "ABCD1234")
    u1, u2, u3 = add(q, "abcd-1234", "ABCD-1234", "ZZZ888", game_key="", game="")
    moved = q.assign_game([u1, u2, u3], GAME_A)
    assert moved == 2  # u2 duplicates the code already queued for GAME_A and is removed
    assert q.get(u2) is None and q.get(u1).game_key == GAME_A and q.get(u1).game == "原神"  # name reused
    assert [e.kind for e in events[-2:]] == [QueueEventKind.UPDATED, QueueEventKind.REMOVED]
    assert events[-2].ids == [u1, u3] and events[-1].ids == [u2]
    assert q.assign_game([keep, u1], GAME_A, "原神 Genshin") == 0  # same game: only the display name
    assert q.get(keep).game == "原神 Genshin"
    assert q.assign_game([u3], GAME_B, "星穹鐵道") == 1 and q.get(u3).game_key == GAME_B
    assert q.assign_game(["missing"], GAME_B) == 0


def test_games_in_queue_order(q: CodeQueue) -> None:
    add(q, "AAAA1111", game_key="", game="")
    add(q, "BBBB2222", game_key=GAME_B, game="")
    add(q, "CCCC3333", game_key=GAME_A, game="原神")
    add(q, "DDDD4444", game_key=GAME_B, game="星穹鐵道")
    assert q.games() == [("", ""), (GAME_B, "星穹鐵道"), (GAME_A, "原神")]


@pytest.mark.parametrize(("lang", "note"), [("zh-TW", RECOVERY_ZH), ("en", RECOVERY_EN)])
def test_recover_after_crash_with_bilingual_message(qpath: Path, lang: str, note: str) -> None:
    q = CodeQueue(qpath)
    q.load()
    a, b, c = add(q, "AAAA1111", "BBBB2222", "CCCC3333")
    q.set_status(a, CodeStatus.RUNNING)
    q.set_status(b, CodeStatus.COOLDOWN, "偵測到「操作過於頻繁」，300 秒後重試這筆序號。")
    q.set_status(c, CodeStatus.SUCCESS, "兌換成功")
    i18n.set_language(lang)
    restarted = CodeQueue(qpath)
    restarted.load()
    got: list[QueueEvent] = []
    restarted.subscribe(got.append)
    assert restarted.recover_after_crash() == 2
    assert [(i.status, i.message) for i in restarted.items()] == [
        (CodeStatus.REVIEW, note), (CodeStatus.PENDING, ""), (CodeStatus.SUCCESS, "兌換成功")]
    assert got == [QueueEvent(QueueEventKind.UPDATED, [a, b])]
    again = CodeQueue(qpath)
    again.load()
    assert again.get(a).status is CodeStatus.REVIEW and again.recover_after_crash() == 0


def test_counts_and_lookups(q: CodeQueue) -> None:
    a, b = add(q, "ABCD-1234", "EFGH5678")
    (c,) = add(q, "ABCD1234", game_key=GAME_B, game="星穹鐵道")
    q.set_status(b, CodeStatus.USED)
    counts = q.counts()
    assert set(counts) == set(CodeStatus) and counts[CodeStatus.PENDING] == 2 and counts[CodeStatus.USED] == 1
    assert sum(counts.values()) == len(q) == 3
    assert q.index_of(b) == 1 and q.index_of("missing") == -1
    assert q.find_code("abcd1234") is None and q.find_code("ABCD 1234").id == a
    assert q.find_code("ABCD1234", GAME_B).id == c and q.find_code("EFGH-5678", GAME_B) is None
    items = q.items()
    items.clear()
    assert len(q) == 3  # items() returns a new list


def test_subscribers_see_the_saved_file_and_errors_are_contained(q: CodeQueue, qpath: Path) -> None:
    seen: list[list[str]] = []

    def reader(ev: QueueEvent) -> None:
        seen.append([i["code"] for i in json.loads(qpath.read_text(encoding="utf-8"))["items"]])

    def broken(ev: QueueEvent) -> None:
        raise RuntimeError("view bug")

    q.subscribe(broken)
    unsubscribe = q.subscribe(reader)
    add(q, "ABCD1234")
    assert seen == [["ABCD1234"]]  # saved before subscribers are notified; a broken view is contained
    unsubscribe()
    unsubscribe()  # harmless twice
    add(q, "EFGH5678")
    assert seen == [["ABCD1234"]]


def test_annotate_preview_candidates(q: CodeQueue, isolated_home: Path) -> None:
    (a,) = add(q, "ABCD-1234")
    hist = HistoryStore(isolated_home / "history.jsonl")
    hist.load()
    hist.append(AttemptRecord(code="ZZZ888", game_key=GAME_A, status=CodeStatus.SUCCESS))
    out = q.annotate([cand("ABCD1234"), cand("ZZZ888"), cand("NEW12345")], history=hist, game_key=GAME_A)
    assert [(c.duplicate_of, c.history_status) for c in out] == [(a, None), ("", CodeStatus.SUCCESS), ("", None)]
    assert q.annotate([cand("ABCD1234")], game_key=GAME_B)[0].duplicate_of == ""


def test_demo_context_runs_on_the_real_stores(demo_ctx: object) -> None:
    from tests.fakes import DEMO_ROWS

    ctx: object = demo_ctx
    queue, history = ctx.queue, ctx.history  # type: ignore[attr-defined]
    assert isinstance(queue, CodeQueue) and isinstance(history, HistoryStore)
    assert [i.status for i in queue.items()] == [row[4] for row in DEMO_ROWS]
    done = [row for row in DEMO_ROWS if row[4] not in (CodeStatus.PENDING, CodeStatus.REVIEW)]
    assert len(history.records()) == len(done)
    reloaded = CodeQueue(queue.path)
    reloaded.load()
    assert len(reloaded) == len(DEMO_ROWS)
