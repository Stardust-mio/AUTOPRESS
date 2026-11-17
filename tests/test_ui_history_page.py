# OWNED BY G6
"""History page (SPEC 6.4.4, 8.2 G6): filters, 重新加入佇列 with the record's game, remove /
clear (confirm), CSV export, evidence thumbnail + viewer, empty state, live updates."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPixmap

from autopress.models import AttemptRecord, CodeCandidate, CodeSource, CodeStatus
from autopress.ui import widgets
from autopress.ui.history_page import COL_EVIDENCE, EvidenceDialog, HistoryPage, format_time
from tests.fakes import demo_context, skip_if_stub

G1 = ("autopress.codes.queue", "autopress.codes.history", "autopress.codes.csvexport")


def _records() -> list[AttemptRecord]:
    return [
        AttemptRecord(code="AAAA1111ZZ", game="原神", game_key="game:原神", profile_name="網頁兌換", status=CodeStatus.SUCCESS,
                      message="兌換成功", finished_at="2026-11-17T10:00:00+08:00"),
        AttemptRecord(code="BBBB2222ZZ", game="原神", game_key="game:原神", profile_name="網頁兌換", status=CodeStatus.INVALID,
                      message="兌換碼無效", finished_at="2026-11-17T10:01:00+08:00"),
        AttemptRecord(code="CCCC3333ZZ", game="鳴潮", game_key="game:鳴潮", profile_name="遊戲內", status=CodeStatus.FAILED,
                      message="找不到「兌換」按鈕", finished_at="2026-11-17T10:02:00+08:00"),
        AttemptRecord(code="DDDD4444ZZ", game="鳴潮", game_key="game:鳴潮", profile_name="遊戲內", status=CodeStatus.USED,
                      message="已被使用", finished_at="2026-11-17T10:03:00+08:00"),
    ]


@pytest.fixture
def ctx(qapp: object, isolated_home: Path) -> Any:
    skip_if_stub(*G1)
    c = demo_context(isolated_home, with_data=False)
    for r in _records():
        c.history.append(r)
    return c


@pytest.fixture
def page(qtbot: Any, ctx: Any) -> HistoryPage:
    p = HistoryPage(ctx)
    qtbot.addWidget(p)
    p.resize(1060, 760)
    return p


def _shown(page: HistoryPage) -> list[str]:
    return [r.code for r in page.records_shown()]


def _select(page: HistoryPage, *codes: str) -> None:
    page._table.clearSelection()
    for row, rec in enumerate(page.records_shown()):
        if rec.code in codes:
            page._table.selectionModel().select(page._model.index(row, 0), page._table.selectionModel().SelectionFlag.Select
                                                | page._table.selectionModel().SelectionFlag.Rows)


def test_lists_newest_first_with_filters(page: HistoryPage) -> None:
    assert _shown(page) == ["DDDD4444ZZ", "CCCC3333ZZ", "BBBB2222ZZ", "AAAA1111ZZ"]
    assert page._subtitle.text() == "共 4 筆紀錄 · 成功 1 筆"
    page.set_filters(text="無效")
    assert _shown(page) == ["BBBB2222ZZ"]
    page.set_filters(text="", status=CodeStatus.USED)
    assert _shown(page) == ["DDDD4444ZZ"]
    page.set_filters(status=None, game_key="game:原神")
    assert _shown(page) == ["BBBB2222ZZ", "AAAA1111ZZ"]
    labels = [page._game_combo.itemText(i) for i in range(page._game_combo.count())]
    assert labels[0] == "所有遊戲" and {"原神", "鳴潮"} <= set(labels)
    page.set_filters(text="zzzz-not-there", game_key=None)
    assert _shown(page) == [] and page._stack.currentIndex() == 2
    assert format_time("2026-11-17T10:00:00+08:00").startswith("2026-11-17")


def test_requeue_uses_the_records_game(page: HistoryPage, ctx: Any) -> None:
    # CCCC3333ZZ is still queued for 鳴潮 as FAILED -> reset; the others are added
    res = ctx.queue.add_candidates([CodeCandidate(code="CCCC3333ZZ")], CodeSource.PASTE, game_key="game:鳴潮", game="鳴潮")
    ctx.queue.set_status(res.added[0], CodeStatus.FAILED, "x")
    _select(page, "AAAA1111ZZ", "CCCC3333ZZ")
    assert page.requeue_selected() == 2
    a = ctx.queue.find_code("AAAA1111ZZ", "game:原神")
    assert a is not None and a.game == "原神" and a.status is CodeStatus.PENDING and a.source is CodeSource.MANUAL
    c = ctx.queue.get(res.added[0])
    assert c.status is CodeStatus.PENDING and c.game_key == "game:鳴潮"
    assert ctx.queue.find_code("AAAA1111ZZ", "game:鳴潮") is None
    _select(page, "AAAA1111ZZ")
    assert page.requeue_selected() == 0  # already pending: left alone


def test_remove_and_clear_need_confirmation(page: HistoryPage, ctx: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _select(page, "BBBB2222ZZ")
    monkeypatch.setattr(widgets, "confirm", lambda *a, **k: False)
    assert page.remove_selected() == 0 and len(ctx.history.records()) == 4
    assert page.clear_all() == 0
    monkeypatch.setattr(widgets, "confirm", lambda *a, **k: True)
    assert page.remove_selected() == 1
    page.refresh()
    assert "BBBB2222ZZ" not in _shown(page)
    assert page.clear_all() == 3
    page.refresh()
    assert page._stack.currentIndex() == 1  # empty state
    assert not page._clear_btn.isEnabled()


def test_updates_when_history_changes(page: HistoryPage, ctx: Any, qtbot: Any) -> None:
    ctx.history.append(AttemptRecord(code="EEEE5555ZZ", game="原神", game_key="game:原神", status=CodeStatus.SUCCESS,
                                     finished_at="2026-11-17T11:00:00+08:00"))
    qtbot.waitUntil(lambda: _shown(page)[:1] == ["EEEE5555ZZ"], timeout=2000)
    assert page._subtitle.text() == "共 5 筆紀錄 · 成功 2 筆"


def test_export_csv_of_shown_records(page: HistoryPage, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from PyQt6.QtWidgets import QFileDialog

    out = tmp_path / "紀錄.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(out), "CSV"))
    page.set_filters(game_key="game:鳴潮")
    assert page.export_csv()
    text = out.read_bytes().decode("utf-8-sig")
    assert "CCCC3333ZZ" in text and "DDDD4444ZZ" in text and "AAAA1111ZZ" not in text


def test_evidence_thumbnail_and_viewer(page: HistoryPage, ctx: Any, isolated_home: Path) -> None:
    rel = Path("evidence") / "2026-11-17" / "run1_1.png"
    f = isolated_home / rel
    f.parent.mkdir(parents=True)
    img = QImage(200, 60, QImage.Format.Format_RGB32)
    img.fill(Qt.GlobalColor.darkCyan)
    assert img.save(str(f))
    ctx.history.append(AttemptRecord(code="EVID1234ZZ", game="原神", game_key="game:原神", status=CodeStatus.SUCCESS,
                                     message="兌換成功", evidence_path=rel.as_posix(),
                                     finished_at="2026-11-17T12:00:00+08:00"))
    page.refresh()
    row = _shown(page).index("EVID1234ZZ")
    thumb = page._model.data(page._model.index(row, COL_EVIDENCE), Qt.ItemDataRole.DecorationRole)
    assert isinstance(thumb, QPixmap) and not thumb.isNull()
    dlg = page.open_evidence(page.records_shown()[row])
    assert isinstance(dlg, EvidenceDialog)
    dlg.reject()
    other = _shown(page).index("AAAA1111ZZ")
    assert page._model.data(page._model.index(other, COL_EVIDENCE), Qt.ItemDataRole.DecorationRole) is None
    assert page.open_evidence(page.records_shown()[other]) is None


def test_empty_state_links_to_codes(qtbot: Any, isolated_home: Path) -> None:
    skip_if_stub(*G1)
    ctx = demo_context(isolated_home, with_data=False)
    page = HistoryPage(ctx)
    qtbot.addWidget(page)
    assert page._stack.currentIndex() == 1
    assert page._subtitle.text() == "尚無紀錄"
    assert not page._export_btn.isEnabled()


def test_requeue_leaves_running_plan_alone_and_explains_history_skip(page: HistoryPage, ctx: Any) -> None:
    from autopress.models import Profile

    toasts: list[tuple[str, str]] = []
    ctx.signals.toast.connect(lambda kind, text: toasts.append((kind, text)))
    res = ctx.queue.add_candidates([CodeCandidate(code="BBBB2222ZZ")], CodeSource.PASTE, game_key="game:原神", game="原神")
    profile = Profile(name="網頁兌換", game="原神")
    assert profile.game_key() == "game:原神"
    ctx.session.start(ctx.session.build_plan(profile, ctx.settings))
    assert [i.code_id for i in ctx.session.plan.items] == res.added
    _select(page, "AAAA1111ZZ", "BBBB2222ZZ")
    assert page.requeue_selected() == 1  # only AAAA1111ZZ: BBBB2222ZZ is in the running plan
    assert ctx.queue.get(res.added[0]).status is CodeStatus.PENDING
    kind, text = toasts[-1]
    assert kind == "warning" and "執行中" in text and "已兌換過" in text
    ctx.session.stop()
