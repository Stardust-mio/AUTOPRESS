"""Smoke tests for tests/fakes.py and tests/ui_fallback.py (OWNED BY A1)."""

from __future__ import annotations

from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QImage, QPainter

from autopress import models as m
from tests import fakes


def test_fake_queue_semantics(make_items: object) -> None:
    q = fakes.FakeCodeQueue()
    events: list[m.QueueEvent] = []
    unsub = q.subscribe(events.append)
    res = q.add_candidates([m.CodeCandidate(code="AAAA-1111"), m.CodeCandidate(code="aaaa1111x"),
                            m.CodeCandidate(code="AAAA1111"), m.CodeCandidate(code="BBBB2222", flagged=[1])],
                           m.CodeSource.PASTE)
    assert len(res.added) == 3 and res.duplicates == 1
    a, x, b = (q.get(i) for i in res.added)
    assert b.status is m.CodeStatus.REVIEW
    q.update(b.id, code="BBBB2223")
    assert q.get(b.id).status is m.CodeStatus.PENDING and q.get(b.id).flagged == []
    q.move([b.id], -2)
    assert [i.id for i in q.items()] == [b.id, a.id, x.id]
    q.set_checked([a.id], False)
    assert [i.id for i in q.runnable(m.RunSelection.CHECKED)] == [b.id, x.id]
    q.set_status(x.id, m.CodeStatus.FAILED)
    assert q.retry_failed() == 1 and q.counts()[m.CodeStatus.PENDING] == 3
    q.set_status(a.id, m.CodeStatus.RUNNING)
    assert q.recover_after_crash() == 1 and q.get(a.id).status is m.CodeStatus.REVIEW
    assert q.clear({m.CodeStatus.REVIEW}) == 1 and len(q) == 2
    unsub()
    n = len(events)
    q.remove([x.id])
    assert len(events) == n


def test_fake_queue_games_and_reset() -> None:
    """PX-02: codes belong to a game; duplicates per game; runs take only the profile's game."""
    q = fakes.FakeCodeQueue()
    g1 = q.add_candidates([m.CodeCandidate(code="SAME1234"), m.CodeCandidate(code="ONLY5678")], m.CodeSource.PASTE,
                          game_key="game:a", game="A")
    g2 = q.add_candidates([m.CodeCandidate(code="SAME-1234")], m.CodeSource.PASTE, game_key="game:b", game="B")
    loose = q.add_candidates([m.CodeCandidate(code="LOOSE999")], m.CodeSource.PASTE)
    assert len(g1.added) == 2 and len(g2.added) == 1 and g2.duplicates == 0
    assert [i.code for i in q.runnable(game_key="game:a")] == ["SAME1234", "ONLY5678"]
    assert q.games() == [("game:a", "A"), ("game:b", "B"), ("", "")]
    assert q.assign_game(loose.added, "game:a", "A") == 1 and q.get(loose.added[0]).game_key == "game:a"
    assert q.assign_game(g2.added, "game:a", "A") == 0 and q.get(g2.added[0]) is None  # duplicate in game A
    q.set_status(g1.added[0], m.CodeStatus.INVALID, "兌換碼無效")
    q.set_status(g1.added[1], m.CodeStatus.REVIEW)
    assert q.retry_failed() == 0  # T37: REVIEW is not retried blindly
    assert q.reset(g1.added) == 2 and {q.get(i).status for i in g1.added} == {m.CodeStatus.PENDING}


def test_fake_history_and_session(demo_ctx: object, qtbot: object) -> None:
    ctx = demo_ctx
    prof = ctx.active_profile()
    plan = ctx.session.build_plan(prof, ctx.settings)
    assert plan.items and all(ctx.queue.get(i.code_id).status.is_runnable for i in plan.items)
    assert ctx.session.preflight(plan).ok
    with qtbot.waitSignal(ctx.session.state_changed):
        ctx.session.start(plan)
    rec = ctx.session.simulate_code(plan.items[0].code_id, m.CodeStatus.SUCCESS, "兌換成功")
    assert ctx.queue.get(rec.code_id).status is m.CodeStatus.SUCCESS
    assert ctx.history.records()[-1].code == rec.code
    with qtbot.waitSignal(ctx.session.finished):
        ctx.session.stop()
    with qtbot.waitSignal(ctx.session.test_finished):
        ctx.session.test_step(prof, 1, ctx.settings)
    with qtbot.waitSignal(ctx.ocr.state_changed):
        ctx.ocr.start()
    got: list[m.OcrResult] = []
    ctx.ocr.request(None, None, got.append)
    qtbot.waitUntil(lambda: bool(got))
    assert ctx.hotkeys.register("stop", "F9").ok and ctx.hotkeys.registered() == {"stop": "F9"}


def test_icon_names_cover_model_icons() -> None:
    from autopress.ui import icons

    needed = {s.icon for s in m.StepType} | {s.icon for s in m.CodeSource}
    assert needed <= set(icons.ICON_NAMES)
    assert len(set(icons.ICON_NAMES)) == len(icons.ICON_NAMES)


def test_stub_detection() -> None:
    assert not fakes.is_stub("autopress.models")
    if fakes.is_stub("autopress.codes.queue"):
        import pytest

        with pytest.raises(pytest.skip.Exception):
            fakes.skip_if_stub("autopress.codes.queue")


def test_ui_foundation_usable(qapp: object) -> None:
    """Real G5 widgets or the fallbacks: either way the documented API works."""
    from autopress.ui import icons, theme, widgets

    theme.apply_theme(qapp, "dark")
    assert theme.current_theme() == "dark" and theme.color("accent").isValid()
    assert not icons.icon("codes").isNull() or getattr(icons, "__fallback__", False)
    sw = widgets.Switch(True)
    assert sw.isChecked()
    seg = widgets.SegmentedControl(["全部", "待兌換"], 1)
    assert seg.currentIndex() == 1
    chip = widgets.StatusChip(m.CodeStatus.USED)
    assert chip.width() > 0
    img = QImage(200, 40, QImage.Format.Format_ARGB32)
    p = QPainter(img)
    width = widgets.paint_status_chip(p, QRectF(0, 0, 200, 40), m.CodeStatus.SUCCESS)
    p.end()
    assert width > 0
    widgets.Banner("warning", "2 筆需要確認", "逐筆確認")
    widgets.EmptyState("codes", "還沒有序號", "貼上序號、開啟檔案或框選螢幕", tip_keys=["Ctrl", "V"])
    ring = widgets.ProgressRing()
    ring.setProgress(3, 12)
