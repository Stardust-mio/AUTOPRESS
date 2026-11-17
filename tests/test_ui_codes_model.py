# OWNED BY G6
"""CodesTableModel / CodesFilterProxy / delegates (SPEC 6.4.1, 8.2 G6): model <-> queue events,
filters / search / game filter, check state and plan locking, look-alike vs flagged painting."""

from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtCore import QItemSelectionModel, QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter

from autopress.models import CodeCandidate, CodeSource, CodeStatus, QueueEventKind
from autopress.ui import theme
from autopress.ui.codes_model import (
    COL_CHECK,
    COL_CODE,
    COL_CONF,
    COL_INDEX,
    FILTERS,
    ROLE_LOCKED,
    CodesFilterProxy,
    CodesTableModel,
    filter_accepts,
)
from autopress.ui.codes_paint import code_char_styles, confidence_tone, paint_code
from tests.fakes import FakeCodeQueue, skip_if_stub


def _real_queue(tmp: Path) -> object:
    skip_if_stub("autopress.codes.queue")
    from autopress.codes.queue import CodeQueue

    q = CodeQueue(tmp / "queue.json")
    q.load()
    return q


@pytest.fixture(params=["fake", "real"])
def queue(request: pytest.FixtureRequest, tmp_path: Path) -> object:
    return FakeCodeQueue() if request.param == "fake" else _real_queue(tmp_path)


def _add(queue: object, codes: list[str], game_key: str = "game:a", game: str = "A", **kw: object) -> list[str]:
    cands = [CodeCandidate(code=c, raw=c, **kw) for c in codes]  # type: ignore[arg-type]
    return queue.add_candidates(cands, CodeSource.PASTE, game_key=game_key, game=game).added  # type: ignore[attr-defined]


def _codes(model: CodesTableModel) -> list[str]:
    return [model.item_at(r).code for r in range(model.rowCount())]  # type: ignore[union-attr]


def test_model_follows_queue_events(qapp: object, queue: object) -> None:
    model = CodesTableModel(queue)
    seen: list[tuple] = []
    model.rowsInserted.connect(lambda _p, a, b: seen.append(("ins", a, b)))
    model.rowsRemoved.connect(lambda _p, a, b: seen.append(("rem", a, b)))
    model.layoutChanged.connect(lambda *_a: seen.append(("layout",)))
    model.modelReset.connect(lambda: seen.append(("reset",)))
    ids = _add(queue, [f"CODE{i:04d}AB" for i in range(5)])
    assert model.rowCount() == 5 and ("ins", 0, 4) in seen and ("reset",) not in seen
    assert model.data(model.index(2, COL_INDEX)) == "3"
    seen.clear()
    queue.move([ids[3]], -2)  # type: ignore[attr-defined]
    assert _codes(model) == ["CODE0000AB", "CODE0003AB", "CODE0001AB", "CODE0002AB", "CODE0004AB"]
    assert seen == [("layout",)]
    seen.clear()
    queue.remove([ids[0], ids[4]])  # type: ignore[attr-defined]
    assert _codes(model) == ["CODE0003AB", "CODE0001AB", "CODE0002AB"]
    assert all(s[0] == "rem" for s in seen) and len(seen) == 2
    changed: list[tuple[int, int]] = []
    model.dataChanged.connect(lambda a, b, *_r: changed.append((a.row(), b.row())))
    queue.set_status(ids[1], CodeStatus.REVIEW, "x")  # type: ignore[attr-defined]
    assert changed == [(1, 1)]
    assert model.item_at(1).status is CodeStatus.REVIEW  # type: ignore[union-attr]


def test_model_batch_coalesces_and_reset_reloads(qapp: object, queue: object) -> None:
    model = CodesTableModel(queue)
    ids = _add(queue, [f"BATCH{i:03d}XY" for i in range(4)])
    changes: list[int] = []
    model.itemsChanged.connect(lambda: changes.append(1))
    with model.batch():
        for cid in ids:
            queue.set_status(cid, CodeStatus.SKIPPED)  # type: ignore[attr-defined]
        assert changes == []  # deferred
    assert changes == [1]
    assert all(model.item_at(r).status is CodeStatus.SKIPPED for r in range(4))  # type: ignore[union-attr]
    resets: list[int] = []
    model.modelReset.connect(lambda: resets.append(1))
    model._on_queue_event(type("E", (), {"kind": QueueEventKind.RESET, "ids": []})())  # type: ignore[arg-type]
    assert resets == [1] and model.rowCount() == 4


def test_selection_follows_moved_rows(qapp: object, queue: object) -> None:
    model = CodesTableModel(queue)
    proxy = CodesFilterProxy()
    proxy.setSourceModel(model)
    sel = QItemSelectionModel(proxy)
    ids = _add(queue, [f"MOVE{i:04d}ZZ" for i in range(4)])
    sel.select(proxy.index(3, 0), QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    queue.move_to([ids[3]], 0)  # type: ignore[attr-defined]
    rows = {ix.row() for ix in sel.selectedRows()}
    assert rows == {0}
    assert proxy.item_at(0).id == ids[3]  # type: ignore[union-attr]


def test_filters_search_and_game(qapp: object, queue: object) -> None:
    model = CodesTableModel(queue)
    proxy = CodesFilterProxy()
    proxy.setSourceModel(model)
    a = _add(queue, ["AAAA-1111-ZZ", "AAAA2222ZZ", "AAAA3333ZZ"], "game:a", "A")
    b = _add(queue, ["BBBB1111ZZ"], "game:b", "B")
    u = _add(queue, ["UUUU1111ZZ"], "", "")
    queue.set_status(a[1], CodeStatus.SUCCESS, "兌換成功")  # type: ignore[attr-defined]
    queue.set_status(a[2], CodeStatus.INVALID, "兌換碼無效")  # type: ignore[attr-defined]
    queue.set_status(b[0], CodeStatus.COOLDOWN)  # type: ignore[attr-defined]
    assert proxy.rowCount() == 5
    proxy.set_game("game:a")  # active game + unassigned
    assert {proxy.item_at(r).id for r in range(proxy.rowCount())} == {*a, *u}  # type: ignore[union-attr]
    proxy.set_filter("done")
    assert [proxy.item_at(r).id for r in range(proxy.rowCount())] == [a[1]]  # type: ignore[union-attr]
    proxy.set_filter("failed")
    assert [proxy.item_at(r).id for r in range(proxy.rowCount())] == [a[2]]  # type: ignore[union-attr]
    proxy.set_game(None)
    proxy.set_filter("pending")
    assert {proxy.item_at(r).id for r in range(proxy.rowCount())} == {a[0], b[0], u[0]}  # type: ignore[union-attr]
    proxy.set_filter("all")
    proxy.set_search("aaaa1111")  # separators ignored, case-insensitive
    assert [proxy.item_at(r).id for r in range(proxy.rowCount())] == [a[0]]  # type: ignore[union-attr]
    proxy.set_search("無效")  # messages are searched too
    assert [proxy.item_at(r).id for r in range(proxy.rowCount())] == [a[2]]  # type: ignore[union-attr]
    assert proxy.row_of(a[2]) == 0 and proxy.row_of(a[0]) == -1
    with pytest.raises(ValueError):
        proxy.set_filter("nope")
    # dynamic filtering: a status change moves the row out of the filtered view
    proxy.set_search("")
    proxy.set_filter("pending")
    queue.set_status(a[0], CodeStatus.SKIPPED)  # type: ignore[attr-defined]
    assert a[0] not in {proxy.item_at(r).id for r in range(proxy.rowCount())}  # type: ignore[union-attr]


def test_filter_keys_cover_every_status() -> None:
    for status in CodeStatus:
        keys = [k for k in FILTERS if k != "all" and filter_accepts(k, status)]
        assert len(keys) == 1, (status, keys)
        assert filter_accepts("all", status)


def test_check_state_and_locked_rows(qapp: object, queue: object) -> None:
    model = CodesTableModel(queue)
    ids = _add(queue, ["LOCK1111AA", "LOCK2222AA"])
    ix = model.index(0, COL_CHECK)
    assert model.data(ix, Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
    assert model.setData(ix, Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
    assert queue.get(ids[0]).checked is False  # type: ignore[attr-defined]
    assert model.flags(model.index(0, COL_CODE)) & Qt.ItemFlag.ItemIsEditable
    model.set_locked([ids[1]])
    assert model.data(model.index(1, COL_CODE), ROLE_LOCKED) is True
    assert not model.flags(model.index(1, COL_CODE)) & Qt.ItemFlag.ItemIsEditable
    assert not model.flags(model.index(1, COL_CHECK)) & Qt.ItemFlag.ItemIsUserCheckable
    assert not model.setData(model.index(1, COL_CHECK), Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
    assert queue.get(ids[1]).checked is True  # type: ignore[attr-defined]
    assert "執行中" in model.data(model.index(1, COL_CODE), Qt.ItemDataRole.ToolTipRole)
    # code edits go through code_editor
    calls: list[tuple[str, str]] = []
    model.code_editor = lambda item, text: calls.append((item.id, text)) or True
    assert model.setData(model.index(0, COL_CODE), "  NEWCODE99  ", Qt.ItemDataRole.EditRole)
    assert calls == [(ids[0], "NEWCODE99")]
    assert not model.setData(model.index(1, COL_CODE), "OTHER12345", Qt.ItemDataRole.EditRole)  # locked


def test_confidence_only_for_ocr_sources(qapp: object) -> None:
    q = FakeCodeQueue()
    q.add_candidates([CodeCandidate(code="OCRCODE123", char_confs=[0.91] * 10)], CodeSource.SNIP, game_key="g")
    q.add_candidates([CodeCandidate(code="TXTCODE123", char_confs=[0.5] * 10)], CodeSource.PASTE, game_key="g")
    model = CodesTableModel(q)
    assert model.data(model.index(0, COL_CONF)) == "91%"
    assert model.data(model.index(1, COL_CONF)) == "—"
    assert confidence_tone(0.95) == "success" and confidence_tone(0.9) == "warning" and confidence_tone(0.79) == "error"


def test_model_unsubscribes_when_deleted(qapp: object) -> None:
    q = FakeCodeQueue()
    model = CodesTableModel(q)
    assert len(q._subs) == 1
    model.deleteLater()
    from PyQt6.QtCore import QCoreApplication, QEvent

    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    assert q._subs == []
    q.add_candidates([CodeCandidate(code="AFTERDEL12")], CodeSource.PASTE)  # no crash


def test_char_styles_flagged_beats_lookalike() -> None:
    assert code_char_styles("Q8ZL0W", [4], [1, 2, 4]) == ["", "lookalike", "lookalike", "", "flagged", ""]


def _render(code: str, flagged: list[int], lookalikes: list[int]) -> tuple[QImage, list[tuple[int, str]]]:
    img = QImage(400, 40, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    marks = paint_code(p, QRectF(0, 0, 400, 40), code, flagged, lookalikes)
    p.end()
    return img, marks


def _has_color(img: QImage, color: QColor, tolerance: int = 6) -> bool:
    target = color.rgba()
    for y in range(img.height()):
        for x in range(img.width()):
            px = img.pixel(x, y)
            if all(abs(((px >> s) & 0xFF) - ((target >> s) & 0xFF)) <= tolerance for s in (0, 8, 16, 24)):
                return True
    return False


def test_flagged_painted_with_fill_lookalike_only_dotted(qapp: object) -> None:
    img_flag, marks_flag = _render("Q8ZL0W3NBX5C", [4], [])
    img_look, marks_look = _render("Q8ZL0W3NBX5C", [], [4])
    assert marks_flag == [(4, "flagged")]
    assert marks_look == [(4, "lookalike")]
    soft = theme.color("warning_soft")
    # the warning_soft cell exists only for flagged characters (same paint path as the probe)
    probe = QImage(1, 1, QImage.Format.Format_ARGB32_Premultiplied)
    probe.fill(Qt.GlobalColor.transparent)
    pp = QPainter(probe)
    pp.fillRect(0, 0, 1, 1, soft)
    pp.end()
    soft_px = QColor.fromRgba(probe.pixel(0, 0))
    assert _has_color(img_flag, soft_px)
    assert not _has_color(img_look, soft_px)
