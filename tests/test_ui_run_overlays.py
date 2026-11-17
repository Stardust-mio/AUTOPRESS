# OWNED BY G7
"""Overlay math (fake screens), the screen picker controller, countdown and preview overlays,
and the mini bar (placement, 0.7 s button lock, results, dragging)."""

from __future__ import annotations

import numpy as np
import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QWidget

from autopress.models import CodeStatus, PreviewKind, PreviewMark, RunState
from autopress.ui import overlays
from autopress.ui.minibar_place import POINT_PAD, choose_position
from autopress.ui.overlays_geom import (
    ScreenGeom,
    drag_rect,
    local_to_physical,
    logical_to_physical,
    magnifier_source,
    physical_rect_to_local,
    physical_to_local,
    physical_to_logical,
    qround,
    screen_for_physical_point,
    screen_for_physical_rect,
)

# The research PC: secondary monitor LEFT of the primary (win32_windows.md section 1).
SECONDARY_125 = ScreenGeom((-1920, 0, 1536, 864), 1.25)
SECONDARY_150 = ScreenGeom((-1920, 0, 1280, 720), 1.5)
SECONDARY_175 = ScreenGeom((-1920, 0, 1097, 617), 1.75)
PRIMARY_150 = ScreenGeom((0, 0, 1280, 720), 1.5)


# ----------------------------------------------------------------------------- pure math


def test_qround_rounds_half_up_like_qt() -> None:
    assert [qround(v) for v in (0.5, 1.5, 2.5, 83.75, 100.5, 117.25)] == [1, 2, 3, 84, 101, 117]
    assert round(2.5) == 2  # Python's banker's rounding would be off by one pixel


@pytest.mark.parametrize(("geom", "expected"), [
    (SECONDARY_125, (-1794, 84)),  # measured in win32_windows.md (1.25 secondary)
    (SECONDARY_150, (-1768, 101)),  # measured (1.5 secondary)
    (SECONDARY_175, (-1743, 117)),  # measured (1.75 secondary)
])
def test_local_to_physical_matches_the_measured_table(geom: ScreenGeom, expected: tuple[int, int]) -> None:
    # global logical (-1819, 67) on the secondary screen = local (101, 67)
    assert local_to_physical(geom, 101, 67) == expected
    assert logical_to_physical(geom, -1819, 67) == expected


def test_physical_and_local_round_trip_on_fake_screens() -> None:
    for geom in (SECONDARY_125, SECONDARY_150, PRIMARY_150):
        ox, oy = geom.origin
        for px, py in ((ox, oy), (ox + 333, oy + 211), (ox + 1919, oy + 1079)):
            lx, ly = physical_to_local(geom, px, py)
            assert local_to_physical(geom, lx, ly) == (px, py)
            gx, gy = physical_to_logical(geom, px, py)
            assert logical_to_physical(geom, gx, gy) == (px, py)
    assert PRIMARY_150.physical == (0, 0, 1920, 1080)
    assert SECONDARY_125.physical == (-1920, 0, 1920, 1080)
    x, y, w, h = physical_rect_to_local(PRIMARY_150, (150, 75, 300, 150))
    assert (x, y, w, h) == (100.0, 50.0, 200.0, 100.0)


def test_screen_lookup_by_physical_point_and_rect() -> None:
    geoms = [PRIMARY_150, SECONDARY_125]
    assert screen_for_physical_point(geoms, -5, 10) is SECONDARY_125
    assert screen_for_physical_point(geoms, 5, 10) is PRIMARY_150
    assert screen_for_physical_point(geoms, 5000, 10) is None
    assert screen_for_physical_rect(geoms, (-300, 100, 400, 200)) is SECONDARY_125  # 300 px on the left
    assert screen_for_physical_rect(geoms, (5000, 0, 10, 10)) is PRIMARY_150  # nearest
    assert screen_for_physical_rect(geoms, None) is PRIMARY_150


def test_drag_rect_and_magnifier_source() -> None:
    assert drag_rect((50, 40), (10, 100)) == (10, 40, 40, 60)
    assert magnifier_source(5, 5, 1920, 1080, 32) == (0, 0, 32, 32)  # shifted, not shrunk
    assert magnifier_source(1919, 1079, 1920, 1080, 32) == (1888, 1048, 32, 32)
    assert magnifier_source(500, 400, 1920, 1080, 32) == (484, 384, 32, 32)
    assert magnifier_source(3, 3, 10, 8, 32) == (0, 0, 10, 8)


# ----------------------------------------------------------------------------- picker


@pytest.fixture
def picker(qapp: object) -> overlays.ScreenPicker:
    p = overlays.ScreenPicker()
    p._active = True  # as after start(); the tests build the overlays themselves
    yield p
    p.cancel()


def _shot(geom: ScreenGeom) -> np.ndarray:
    _x, _y, w, h = geom.physical
    img = np.zeros((h, w, 4), np.uint8)
    img[..., 1] = 120
    return img


def test_picker_point_on_a_fake_125_percent_screen_left_of_the_primary(picker: overlays.ScreenPicker) -> None:
    got: list[object] = []
    picker.finished.connect(got.append)
    ovs = picker.build_overlays([(PRIMARY_150, _shot(PRIMARY_150)), (SECONDARY_125, _shot(SECONDARY_125))])
    picker.on_move(ovs[1], QPointF(101, 67))
    picker.on_release(ovs[1], QPointF(101, 67))
    assert got and isinstance(got[0], overlays.PickResult)
    assert got[0].kind == "point" and got[0].point == (-1794, 84)
    assert picker.overlays == [] and not picker.is_active()


def test_picker_region_crops_the_frozen_shot_in_physical_pixels(picker: overlays.ScreenPicker) -> None:
    picker.kind = "region"
    got: list[object] = []
    picker.finished.connect(got.append)
    shot = _shot(PRIMARY_150)
    shot[150:300, 300:600, 2] = 255  # a red block at physical (300, 150) 300x150
    (ov,) = picker.build_overlays([(PRIMARY_150, shot)])
    picker.on_press(ov, QPointF(200, 100))  # physical (300, 150)
    picker.on_move(ov, QPointF(400, 200))
    picker.on_release(ov, QPointF(400, 200))  # physical (600, 300)
    res = got[0]
    assert res.kind == "region" and res.rect == (300, 150, 300, 150)
    assert res.image.shape == (150, 300, 4) and int(res.image[..., 2].min()) == 255


def test_picker_ignores_a_tiny_drag_and_drags_outside_are_clamped(picker: overlays.ScreenPicker) -> None:
    picker.kind = "region"
    got: list[object] = []
    picker.finished.connect(got.append)
    (ov,) = picker.build_overlays([(PRIMARY_150, _shot(PRIMARY_150))])
    picker.on_press(ov, QPointF(10, 10))
    picker.on_release(ov, QPointF(11, 11))
    assert got == [] and picker.is_active() and ov.hint  # asks to drag a real rectangle
    picker.on_press(ov, QPointF(1200, 700))
    picker.on_release(ov, QPointF(5000, 5000))  # dragged off the overlay: clamped to the screen
    x, y, w, h = got[0].rect
    assert (x, y) == (1800, 1050) and x + w <= 1920 and y + h <= 1080


def test_picker_window_mode_hides_overlays_before_window_at(picker: overlays.ScreenPicker,
                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    from autopress.win32 import windows

    picker.kind = "window"
    seen: list[bool] = []

    def fake_window_at(x: int, y: int, skip_own: bool = False) -> int:
        assert skip_own  # AutoPress's own windows are never picked as the target
        seen.append(all(not ov.isVisible() for ov in picker.overlays))
        return 4242 if (x, y) == (150, 75) else 0

    monkeypatch.setattr(windows, "window_at", fake_window_at)
    got: list[object] = []
    picker.finished.connect(got.append)
    (ov,) = picker.build_overlays([(PRIMARY_150, None)])
    picker.on_release(ov, QPointF(100, 50))
    assert got[0].kind == "window" and got[0].hwnd == 4242 and seen == [True]


def test_picker_start_hides_windows_and_escape_cancels(qtbot: object) -> None:
    host = QWidget()
    host.show()
    p = overlays.ScreenPicker()
    got: list[object] = []
    p.finished.connect(got.append)
    p.start("point", instruction="測試", hide_windows=[host])
    assert not host.isVisible()
    qtbot.waitUntil(lambda: bool(p.overlays), timeout=3000)
    QTest.keyClick(p.overlays[0], Qt.Key.Key_Escape)
    assert got == [None] and host.isVisible() and not p.overlays


def test_pick_wrapper_returns_the_clicked_physical_point(qtbot: object) -> None:
    from PyQt6.QtCore import QTimer

    def click() -> None:
        ov = next(iter(w for w in overlays.QApplication.topLevelWidgets()
                       if isinstance(w, overlays.PickerOverlay) and w.isVisible()), None)
        if ov is None:
            QTimer.singleShot(50, click)
            return
        QTest.mouseClick(ov, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(120, 80))

    QTimer.singleShot(100, click)
    res = overlays.pick("point", instruction="點一下")
    # offscreen: one 800x800 screen at dpr 1 -> physical == local
    assert res is not None and res.point == (120, 80)


def test_picker_rejects_unknown_kinds_and_double_start(qapp: object) -> None:
    p = overlays.ScreenPicker()
    with pytest.raises(ValueError):
        p.start("circle")
    p.start("point")
    with pytest.raises(RuntimeError):
        p.start("point")
    p.cancel()


# ----------------------------------------------------------------------------- countdown / preview


def test_countdown_zero_emits_done_on_the_next_turn(qtbot: object) -> None:
    c = overlays.CountdownOverlay()
    done: list[int] = []
    c.done.connect(lambda: done.append(1))
    c.start(0)
    assert done == [] and c.is_running()
    qtbot.waitUntil(lambda: done == [1], timeout=1000)
    assert not c.is_running() and c.widget is None


def test_countdown_cancel_and_restart(qtbot: object) -> None:
    c = overlays.CountdownOverlay()
    events: list[str] = []
    c.done.connect(lambda: events.append("done"))
    c.cancelled.connect(lambda: events.append("cancelled"))
    c.start(3, None, "F9 停止")
    assert c.widget is not None and c.widget.value == 3 and c.widget.hint == "F9 停止"
    c.cancel()
    assert events == ["cancelled"] and c.widget is None
    c.cancel()  # no second signal
    c.start(0)
    c.start(1)  # the pending 0-second completion of the first start must not fire
    qtbot.wait(100)
    assert events == ["cancelled"]
    qtbot.waitUntil(lambda: events == ["cancelled", "done"], timeout=2500)


def test_preview_overlay_shows_marks_and_hides_itself(qtbot: object) -> None:
    ov = overlays.PreviewOverlay()
    marks = [PreviewMark(0, "a", PreviewKind.POINT, (100, 100, 1, 1), "1 點擊位置", True),
             PreviewMark(2, "b", PreviewKind.REGION, (200, 200, 300, 100), "3 結果範圍", False),
             PreviewMark(3, "c", PreviewKind.POINT, (90000, 90000, 1, 1), "off screen", False)]
    ov.show_marks(marks, duration_ms=150)
    assert ov.is_visible() and len(ov.overlays) == 1
    assert [m.step_id for m in ov.overlays[0].marks] == ["a", "b"]
    assert ov.overlays[0].testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    ov.overlays[0].grab()  # paints without errors
    qtbot.waitUntil(lambda: not ov.is_visible(), timeout=2000)


# ----------------------------------------------------------------------------- mini bar placement


ONE = [((0, 0, 1920, 1080), (0, 0, 1920, 1040))]
TWO = [((0, 0, 1920, 1080), (0, 0, 1920, 1040)), ((-1920, 0, 1920, 1080), (-1920, 0, 1920, 1040))]
BAR, COMPACT = (600, 90), (470, 60)


def _hits(pos: tuple[int, int], size: tuple[int, int], rect: tuple[int, int, int, int]) -> bool:
    from autopress.models import intersect_rect

    return intersect_rect((pos[0], pos[1], size[0], size[1]), rect) is not None


def test_place_prefers_another_monitor_when_the_target_is_on_the_primary() -> None:
    target = (0, 0, 1920, 1040)
    pos, compact = choose_position(BAR, COMPACT, TWO, [(960, 500, 1, 1)], target)
    assert not compact and pos[0] < 0  # on the left monitor


def test_place_uses_a_corner_outside_the_target_on_one_monitor() -> None:
    target = (0, 0, 1200, 800)
    avoid = [(640, 300, 1, 1), (400, 380, 600, 120)]
    pos, compact = choose_position(BAR, COMPACT, ONE, avoid, target)
    assert not compact and not _hits(pos, BAR, target)


def test_place_inside_a_fullscreen_target_avoids_every_point_and_region() -> None:
    target = (0, 0, 1920, 1080)
    br_point = (1920 - 16 - 300, 1040 - 16 - 45, 1, 1)  # in the middle of the bottom-right candidate
    avoid = [br_point, (1300, 16, 600, 120)]  # top-right region
    pos, compact = choose_position(BAR, COMPACT, ONE, avoid, target)
    assert not compact
    x, y, w, h = br_point
    assert not _hits(pos, BAR, (x - POINT_PAD, y - POINT_PAD, w + 2 * POINT_PAD, h + 2 * POINT_PAD))
    assert not _hits(pos, BAR, avoid[1])


def test_place_falls_back_to_the_compact_form_with_the_smallest_overlap() -> None:
    target = (0, 0, 1920, 1080)
    avoid = [(0, 0, 1920, 1040)]  # one huge OCR region: nothing is free
    pos, compact = choose_position(BAR, COMPACT, ONE, avoid, target)
    assert compact


def test_place_keeps_the_saved_position_unless_it_covers_a_point() -> None:
    target = (0, 0, 1920, 1080)
    pos, _c = choose_position(BAR, COMPACT, ONE, [(100, 100, 1, 1)], target, saved=(1000, 600))
    assert pos == (1000, 600)
    pos2, _c = choose_position(BAR, COMPACT, ONE, [(1100, 620, 1, 1)], target, saved=(1000, 600))
    assert pos2 != (1000, 600)


# ----------------------------------------------------------------------------- mini bar widget


@pytest.fixture
def bar(demo_ctx: object, qtbot: object) -> object:
    from autopress.ui.minibar import MiniBar

    b = MiniBar(demo_ctx)
    qtbot.addWidget(b)
    return b


def test_minibar_never_activates(bar: object) -> None:
    flags = bar.windowFlags()
    assert flags & Qt.WindowType.WindowDoesNotAcceptFocus and flags & Qt.WindowType.WindowStaysOnTopHint
    assert flags & Qt.WindowType.Tool and bar.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert "F9" in bar.toolTip()  # failsafe hint


def test_minibar_pause_button_is_locked_for_0_7_s_after_a_state_change(bar: object, qtbot: object) -> None:
    import time

    bar.set_state(RunState.RUNNING.value)
    t0 = time.monotonic()
    assert not bar.pause_btn.isEnabled()
    qtbot.waitUntil(bar.pause_btn.isEnabled, timeout=2000)
    assert time.monotonic() - t0 >= 0.6
    bar.set_state(RunState.PAUSED.value, "focus_lost")
    assert not bar.pause_btn.isEnabled()
    assert "目標視窗失去焦點" in bar.info_text()
    assert "繼續" in bar.pause_btn.toolTip()
    qtbot.waitUntil(bar.pause_btn.isEnabled, timeout=2000)


def test_minibar_results_waiting_and_cooldown(bar: object) -> None:
    bar.set_progress(7, 15, 120.0)
    bar.set_current("MX4T9PK2JR7D", "點一下序號輸入框")
    bar.add_result(CodeStatus.SUCCESS)
    bar.add_result(CodeStatus.SUCCESS)
    bar.add_result(CodeStatus.USED)
    assert bar.counts == {CodeStatus.SUCCESS: 2, CodeStatus.USED: 1}
    assert not bar.chips[CodeStatus.SUCCESS].isHidden() and bar.chips[CodeStatus.INVALID].isHidden()
    bar.set_waiting(6.2)
    assert bar.info_text() == "· 下一筆 6 秒後"
    bar.set_cooldown(299.6)
    assert "300 秒後重試" in bar.info_text()
    assert bar.code_label.text() == "MX4T9PK2JR7D"


def test_minibar_place_away_from_uses_the_live_monitors(bar: object, monkeypatch: pytest.MonkeyPatch) -> None:
    import autopress.ui.minibar as mb

    monkeypatch.setattr(mb, "work_rects", lambda: ONE)
    monkeypatch.setattr(mb, "screen_geoms", lambda: [ScreenGeom((0, 0, 1920, 1080), 1.0)])
    target = (0, 0, 1200, 800)
    bar.place_away_from([(640, 300, 1, 1)], target)
    assert not _hits(bar.placed_at, bar.bar_size_physical(), target)
    assert (bar.x(), bar.y()) == bar.placed_at


def test_minibar_drag_saves_the_position_and_emits_moved(bar: object, qtbot: object) -> None:
    bar.move(100, 100)
    bar.show()
    moved: list[int] = []
    bar.moved.connect(lambda: moved.append(1))
    QTest.mousePress(bar, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(30, 30))
    QTest.mouseMove(bar, QPoint(80, 70))
    QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(80, 70))
    assert moved == [1]
    assert bar.ctx.settings.minibar_pos == [bar.x(), bar.y()] and (bar.x(), bar.y()) != (100, 100)
