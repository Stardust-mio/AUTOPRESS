# OWNED BY ORCH (UI polish, repair round 1 after the screenshot verification, SPEC 3.2)
"""Repair round 1 of the UI polish (offscreen). Each test fails on the code before the repair:

* the run page's selection segment is greyed during a run (a QSS rule for disabled segments)
* the picker's 「目標視窗」 badge sits outside the target window and is opaque; the magnifier shows
  a crosshair and a dark pixel outline on a white page
* the countdown card is opaque; its arrow ends at the ring around the corner; the 「緊急停止」 box
  stays off the arrow
* the decision card frames its evidence crop and draws it at its natural size (no path tooltip)
* the running card keeps the info line on the chips row (no empty band under the chips)
* the pre-flight card's empty note line takes no space; the setup counts include the running code
* 測試一筆 is offered by the pre-flight only with a code; a normal run never marks the profile as
  tested (repair round 2: only 測試一筆 does); the setup hint and the pre-flight item use one sentence
  for 'no codes'
* the mini bar names the running state as the Run page does; the log placeholder uses the muted
  text colour; quoted terms do not split across lines; the wizard dialogs share one head
* history: game / profile columns fit their entries, thumbnails show where the content starts
* the import card explains the {code} placeholder
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QPixmap
from PyQt6.QtWidgets import QApplication

from autopress import i18n
from autopress.models import (
    Attention,
    CodeStatus,
    PauseReason,
    PlanMode,
    RunState,
    StepType,
    StopReason,
    make_step,
)
from autopress.runner import messages
from autopress.ui import theme, widgets
from tests.data.ui_run.g7_helpers import attach_main_window


@pytest.fixture
def themed(qapp: QApplication) -> Iterator[QApplication]:
    """Tests that switch themes leave the shared application in the dark theme."""
    yield qapp
    theme.apply_theme(qapp, "dark")


def _grab(widget: Any) -> QImage:
    QApplication.processEvents()
    return widget.grab().toImage().convertToFormat(QImage.Format.Format_RGB32)


def _brightest(img: QImage, rect: Any) -> int:
    return max(max(img.pixelColor(x, y).getRgb()[:3])
               for x in range(int(rect.left()), int(rect.right()) + 1)
               for y in range(int(rect.top()), int(rect.bottom()) + 1))


# ============================================================================ U9: selection segment


@pytest.mark.parametrize("name", ["dark", "light"])
def test_disabled_selection_segment_is_greyed(qtbot: Any, themed: QApplication, name: str) -> None:
    """Before: the segmented rule overrode the generic QPushButton:disabled colour, so the segment
    looked enabled during a run while every other setup control was greyed."""
    theme.apply_theme(themed, name)
    seg = widgets.SegmentedControl(["全部未完成", "只跑勾選的"])
    qtbot.addWidget(seg)
    seg.show()
    seg.resize(seg.sizeHint())

    def inks(button: Any) -> list[int]:
        from PyQt6.QtCore import QPoint

        img = _grab(seg)  # the whole control: the buttons themselves have no background
        o = button.mapTo(seg, QPoint(0, 0))
        return [sum(img.pixelColor(o.x() + x, o.y() + y).getRgb()[:3]) for x in range(4, button.width() - 4)
                for y in range(4, button.height() - 4)]

    buttons = seg.buttons()
    assert len(buttons) == 2
    enabled = [inks(b) for b in buttons]
    seg.setEnabled(False)
    disabled = [inks(b) for b in buttons]
    ink = theme.color("text_disabled")
    target = ink.red() + ink.green() + ink.blue()
    for on, off in zip(enabled, disabled):
        assert on != off  # the label is drawn in another colour
        if name == "dark":  # no text pixel brighter than the disabled text colour
            assert max(off) <= max(target + 30, min(off) + 30) and max(on) > max(off)
        else:  # no text pixel darker than it
            assert min(off) >= target - 30 and min(on) < min(off)


def test_run_page_selection_segment_is_disabled_during_a_run(demo_ctx: Any, qtbot: Any) -> None:
    from autopress.ui.run_page import RunPage

    attach_main_window(demo_ctx)
    page = RunPage(demo_ctx)
    qtbot.addWidget(page)
    s = demo_ctx.session
    s.start(s.build_plan(demo_ctx.active_profile(), demo_ctx.settings))
    assert not page.selection.isEnabled()
    qss = theme.build_qss(theme.DARK)
    assert 'QFrame[frameRole="segmented"] QPushButton:disabled' in qss
    s.stop()


# ============================================================================ picker and countdown


def _render(widget: Any, w: int, h: int) -> QImage:
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(0)
    widget.render(img)
    return img.convertToFormat(QImage.Format.Format_RGB32)


def test_target_badge_sits_outside_the_target_window(qapp: QApplication) -> None:  # fonts need the app
    from autopress.ui.overlays_widgets import _font, target_badge_anchor

    bounds, font = QRectF(0, 0, 1280, 800), _font(12, bold=True)
    full_width = QRectF(0, 0, 1280, 720)  # a maximised browser above the taskbar: below its bottom edge
    a = target_badge_anchor(full_width, bounds, font)
    assert a.y() >= full_width.bottom() and a.x() == full_width.left()
    window = QRectF(200, 150, 600, 400)  # a window with room above: just above its top edge
    a = target_badge_anchor(window, bounds, font)
    assert a.y() < window.top() and a.x() == window.left()
    screen = QRectF(0, 0, 1280, 800)  # a fullscreen game: inside, top-left
    a = target_badge_anchor(screen, bounds, font)
    assert screen.contains(a)


def test_picker_badge_is_opaque_and_the_magnifier_is_visible_on_white(qapp: QApplication) -> None:
    from autopress.ui import overlays
    from autopress.ui.overlays_geom import ScreenGeom
    from autopress.ui.overlays_widgets import MAG_BOX, PickerOverlay

    picker = overlays.ScreenPicker()
    picker.kind = "region"
    picker.target_rect = (0, 0, 800, 520)
    shot = np.full((600, 800, 4), 255, np.uint8)  # a white page
    ov = PickerOverlay(picker, ScreenGeom((0, 0, 800, 600), 1.0), shot)
    ov.drag_start, ov.cursor_local = QPointF(100, 100), QPointF(300, 200)
    img = _render(ov, 800, 600)
    accent = theme.color("accent")
    # the badge below the outline (no room above it) is the plain accent colour: opaque
    assert img.pixelColor(4, 526).getRgb()[:3] == accent.getRgb()[:3] or \
        img.pixelColor(6, 528).getRgb()[:3] == accent.getRgb()[:3]
    # the magnifier box right-below the cursor: dark outline around the picked pixel, accent crosshair
    box = QRectF(300 + 24, 200 + 24, MAG_BOX, MAG_BOX)
    inner = [img.pixelColor(x, y) for x in range(int(box.left()) + 3, int(box.right()) - 3)
             for y in range(int(box.top()) + 3, int(box.bottom()) - 3)]
    assert min(c.red() + c.green() + c.blue() for c in inner) < 200  # the dark pixel outline
    assert any(c.blue() > c.red() + 60 for c in inner)  # the crosshair inside the magnifier
    ov.deleteLater()


def test_countdown_card_is_opaque_and_the_arrow_reaches_the_corner(qapp: QApplication) -> None:
    from autopress.ui.overlays_geom import ScreenGeom
    from autopress.ui.overlays_widgets import CORNER_RING_R, PILL_FILL, CountdownWidget, _font, corner_label_anchor

    cw = CountdownWidget(ScreenGeom((0, 0, 1280, 800), 1.0), "F9 停止", (0, 0))
    cw.set_value(3)
    img = QImage(1280, 800, QImage.Format.Format_ARGB32)
    img.fill(QColor("#FFFFFF"))  # a white page behind the overlay
    cw.render(img)
    panel = QRectF(0, 0, 360, 240)
    panel.moveCenter(QPointF(640, 400))
    assert img.pixelColor(int(panel.left()) + 30, int(panel.top()) + 30).getRgb()[:3] == PILL_FILL.getRgb()[:3]
    warn = theme.color("warning")

    def warm(x: int, y: int) -> bool:
        c = img.pixelColor(x, y)
        return abs(c.red() - warn.red()) < 40 and abs(c.green() - warn.green()) < 40 and abs(c.blue() - warn.blue()) < 40

    # the arrow's head is just outside the ring (the head tip 8 px off the ring along the diagonal)
    d = 640 / (640 ** 2 + 400 ** 2) ** 0.5, 400 / (640 ** 2 + 400 ** 2) ** 0.5
    tip = CORNER_RING_R + 8 + 4
    assert warm(round(d[0] * tip), round(d[1] * tip))
    mid = 300  # nothing of the arrow left mid-screen
    assert not warm(round(d[0] * mid), round(d[1] * mid))
    # the label box does not cover the arrow
    font = _font(12, bold=True)
    a = corner_label_anchor(QPointF(0, 0), QPointF(*d), "緊急停止", font)
    from PyQt6.QtGui import QFontMetricsF

    fm = QFontMetricsF(font)
    box = QRectF(a.x(), a.y(), fm.horizontalAdvance("緊急停止") + 14, fm.height() + 8)
    for t in range(int(CORNER_RING_R + 8), 140, 2):
        p = QPointF(d[0] * t, d[1] * t)
        assert not box.adjusted(-3, -3, 3, 3).contains(p), t
    cw.deleteLater()


# ============================================================================ decision card evidence


def test_decision_card_frames_the_crop_at_its_natural_size(qtbot: Any, tmp_path: Path, themed: QApplication) -> None:
    from autopress.ui.run_widgets import AttentionPanel

    theme.apply_theme(themed, "light")
    crop = QPixmap(380, 70)
    crop.fill(QColor("#FFFFFF"))  # a white crop on the white light card
    (tmp_path / "evidence").mkdir()
    crop.save(str(tmp_path / "evidence" / "a.png"))
    panel = AttentionPanel(lambda: tmp_path)
    qtbot.addWidget(panel)
    panel.resize(900, 520)
    panel.show_attention(Attention(kind=PauseReason.UNKNOWN_RESULT, code_id="x", ocr_text="t",
                                   evidence_path="evidence/a.png"), "AAAA-1111")
    ev = panel.evidence
    assert ev.isVisibleTo(panel) and ev.toolTip() == ""  # no local path in a tooltip
    r = ev.image_rect()
    dpr = ev.devicePixelRatioF() or 1.0
    assert abs(r.width() - 380 / dpr) < 0.5 and abs(r.height() - 70 / dpr) < 0.5  # one image px per screen px
    img = _grab(ev)
    frame = theme.color("border_strong").name()
    assert img.pixelColor(0, int(r.center().y())).name() == frame  # left edge of the frame
    assert img.pixelColor(int(r.center().x()), 0).name() == frame  # top edge
    big = QPixmap(2400, 600)
    big.fill(QColor("#FFFFFF"))
    ev.setPixmap(big)
    assert ev.image_rect(900).height() <= ev.MAX_H - 2 and ev.image_rect(900).width() <= 900 - 2  # shrunk to fit


# ============================================================================ running card / pre-flight card


def test_info_line_shares_the_chips_row(demo_ctx: Any, qtbot: Any) -> None:
    from autopress.ui.run_widgets import RunningCard

    card = RunningCard("F8", "F9")
    qtbot.addWidget(card)
    card.resize(980, 200)
    card.show()
    card.counts.set_counts({CodeStatus.SUCCESS: 1})
    QApplication.processEvents()
    h0 = card.sizeHint().height()
    card.info.setText("下一筆 6 秒後")
    QApplication.processEvents()
    assert card.sizeHint().height() == h0  # no extra line, no jump
    chip = card.counts.chips[CodeStatus.SUCCESS]
    chip_mid = chip.mapTo(card, chip.rect().center()).y()
    info_mid = card.info.mapTo(card, card.info.rect().center()).y()
    assert abs(chip_mid - info_mid) <= 3  # the same row


def _real_preflight(ctx: Any) -> None:
    """The fake session answers with the real pre-flight check against a fake desktop (never the
    real windows: the demo target is not found there)."""
    from autopress.runner.preflight import run_preflight
    from tests.runner_helpers import FakeBackend, FakeWorld

    ctx.session.preflight_provider = lambda plan: run_preflight(plan.profile, ctx.settings, code_count=len(plan.items),
                                                                ocr_state="ready", backend=FakeBackend(FakeWorld()))


def test_preflight_note_line_takes_no_space_while_empty(demo_ctx: Any, qtbot: Any) -> None:
    from autopress.ui.run_page import RunPage

    attach_main_window(demo_ctx)
    _real_preflight(demo_ctx)
    page = RunPage(demo_ctx)
    qtbot.addWidget(page)
    page.recheck()
    assert page._report is not None and page._report.issues  # items, so no 「一切就緒。」
    assert page.preflight_empty.text() == "" and page.preflight_empty.isHidden()
    demo_ctx.session.preflight_provider = None  # the fake's empty report: 「一切就緒。」
    page.recheck()
    assert page.preflight_empty.text() == "一切就緒。" and not page.preflight_empty.isHidden()


def test_setup_counts_include_the_running_code(demo_ctx: Any, qtbot: Any) -> None:
    from autopress.ui.run_page import RunPage

    attach_main_window(demo_ctx)
    page = RunPage(demo_ctx)
    qtbot.addWidget(page)
    profile = demo_ctx.active_profile()
    before = page._counts_for(profile)
    s = demo_ctx.session
    plan = s.build_plan(profile, demo_ctx.settings)
    s.start(plan)
    s.begin_code(plan.items[0].code_id, 0)  # RUNNING: neither pending nor done
    assert page._counts_for(profile) == before  # the running code still counts as unfinished
    s.stop()


# ============================================================================ untested profile


def test_untested_warning_offers_test_one_only_with_a_code() -> None:
    from autopress.runner.preflight import run_preflight
    from tests.runner_helpers import FakeBackend, FakeWorld, fast_settings, make_profile

    world = FakeWorld()
    profile = make_profile(world)
    profile.last_test_ok_at = ""
    with_codes = run_preflight(profile, fast_settings(), code_count=2, ocr_state="ready", backend=FakeBackend(world))
    none = run_preflight(profile, fast_settings(), code_count=0, ocr_state="ready", backend=FakeBackend(world))
    issue = {i.key: i for i in with_codes.issues}["untested_profile"]
    assert issue.action == "test_one"
    issue = {i.key: i for i in none.issues}["untested_profile"]
    assert issue.action == ""  # the page's own 測試一筆 is disabled without codes
    no_codes = {i.key: i for i in none.issues}["no_codes"]
    assert no_codes.message == messages.pf_no_codes(profile.game or profile.name)


@pytest.mark.parametrize(("tested", "status", "stored"), [
    ("", CodeStatus.SUCCESS, False), ("", CodeStatus.USED, False), ("", CodeStatus.REVIEW, False),
    ("2026-11-01T10:00:00+08:00", CodeStatus.SUCCESS, False)])
def test_a_normal_run_never_marks_the_profile_tested(
        demo_ctx: Any, qtbot: Any, monkeypatch: pytest.MonkeyPatch, tested: str, status: CodeStatus,
        stored: bool) -> None:
    """Repair round 2: storing last_test_ok_at after a normal run went beyond the listed issues; only
    測試一筆 marks a profile as tested (as before the UI polish)."""
    from autopress.ui import run_flow as rf
    from autopress.ui import run_sheet
    from tests.data.ui_run.g7_helpers import patch_dialogs

    attach_main_window(demo_ctx)
    demo_ctx.settings.countdown_s = demo_ctx.settings.resume_countdown_s = 0
    monkeypatch.setattr(run_sheet, "show_preflight_sheet", lambda ctx, report, plan, parent: "start")
    patch_dialogs(monkeypatch)
    profile = demo_ctx.active_profile()
    profile.last_test_ok_at = tested
    demo_ctx.profiles.save(profile, touch=False)
    flow = rf.RunFlow(demo_ctx)
    assert flow.begin(demo_ctx.profiles.get(profile.id)) is True
    assert flow._mode is PlanMode.NORMAL
    demo_ctx.session.simulate_code(demo_ctx.session.plan.items[0].code_id, status, "x")
    demo_ctx.session.stop(StopReason.COMPLETED)
    after = demo_ctx.profiles.get(profile.id).last_test_ok_at
    assert (after != tested) is stored


def test_setup_hint_and_preflight_item_say_no_codes_alike(demo_ctx: Any, qtbot: Any) -> None:
    from autopress.ui.run_page import RunPage

    attach_main_window(demo_ctx)
    _real_preflight(demo_ctx)
    for item in demo_ctx.queue.items():
        demo_ctx.queue.update(item.id, status=CodeStatus.SUCCESS)
    page = RunPage(demo_ctx)
    qtbot.addWidget(page)
    page.recheck()
    profile = demo_ctx.active_profile()
    want = messages.pf_no_codes(profile.game or profile.name)
    assert page.hint.text() == want
    assert want in [i.message for i in page._report.issues]


# ============================================================================ words and wrapping


def test_minibar_names_the_running_state_like_the_run_page(demo_ctx: Any, qtbot: Any) -> None:
    from autopress.ui.minibar import MiniBar

    bar = MiniBar(demo_ctx)
    qtbot.addWidget(bar)
    for st in (RunState.RUNNING, RunState.PAUSED, RunState.COOLDOWN, RunState.STOPPING):
        bar.set_state(st.value)
        assert bar.state_label.text() == st.label()
    assert RunState.RUNNING.label() == "執行中"


@pytest.mark.parametrize("name", ["dark", "light"])
def test_log_placeholder_uses_the_muted_text_colour(qtbot: Any, themed: QApplication, name: str) -> None:
    from autopress.ui.run_widgets import LogView

    theme.apply_theme(themed, name)
    view = LogView()
    qtbot.addWidget(view)
    view.resize(600, 160)
    view.show()
    img = _grab(view.viewport())
    muted = theme.color("text_muted")
    target = muted.red() + muted.green() + muted.blue()
    sums = [img.pixelColor(x, y).red() + img.pixelColor(x, y).green() + img.pixelColor(x, y).blue()
            for x in range(4, 300) for y in range(4, 30)]
    darkest, brightest = min(sums), max(sums)
    if name == "light":  # some glyph pixels reach the muted colour (before: text at half opacity)
        assert darkest <= target + 30
    else:
        assert brightest >= target - 30


def test_keep_quoted_joins_short_quoted_terms_only() -> None:
    wj = widgets.WORD_JOINER
    assert widgets.keep_quoted("請用「模擬鍵入」或「貼上」。") == f"請用「模{wj}擬{wj}鍵{wj}入」或「貼{wj}上」。"
    long = "「" + "字" * 13 + "」"
    assert widgets.keep_quoted(long) == long  # too long for one narrow line: left breakable
    assert widgets.keep_quoted("no quotes") == "no quotes"


def test_wizard_dialogs_share_one_head(qtbot: Any) -> None:
    from autopress.models import Profile
    from autopress.ui import profiles_wizard as pw

    p = Profile(name="p")
    p.steps = [make_step(StepType.CLICK_POINT)]
    p.steps[0].label = "點一下序號輸入框"
    item = pw.position_items(p, False)[0]
    dialogs = [pw._PositionDialog(1, 4, item, False, None, progress=(1, 4)),
               pw._CloseDialog("ok", None, progress=(3, 4)),
               pw._TestDialog(p, "MX4T9PK2JR7D", None, progress=(4, 4))]
    heads = []
    for dlg in dialogs:
        qtbot.addWidget(dlg)
        dlg.adjustSize()
        dlg.resize(dlg.width(), dlg.height() + 40)  # spare height (a wrapped label measured taller, U39)
        dlg.show()
        QApplication.processEvents()
        heads.append((dlg.caption.geometry().top(), dlg.caption.height(), dlg.heading.geometry().top()))
        assert dlg.caption.height() == dlg.caption.sizeHint().height()
    assert len(set(heads)) == 1, heads  # spare height goes above the buttons, never into the caption
    assert dialogs[0].heading.text() == "點一下序號輸入框"
    assert dialogs[1].heading.text() == "選擇結果視窗的關閉方式"
    assert "第一筆待兌換的序號「MX4T9PK2JR7D」" in dialogs[2].findChildren(type(dialogs[2].heading))[2].text()


# ============================================================================ history


def test_thumbnail_shows_where_the_content_starts(qapp: QApplication) -> None:
    from PyQt6.QtGui import QPainter

    from autopress.ui.history_page import THUMB_H, THUMB_W, thumb_source

    crop = QPixmap(760, 140)
    crop.fill(QColor("#FFFFFF"))
    p = QPainter(crop)
    p.fillRect(400, 20, 22, 22, QColor("#169A5A"))  # the message starts in the middle (a centred popup)
    p.end()
    part = thumb_source(crop)
    assert part.width() == round(140 * THUMB_W / THUMB_H) and part.height() == 140
    img = part.toImage()
    assert img.pixelColor(8 + 5, 30).name() == "#169a5a"  # 8 px of margin, then the content
    small = QPixmap(100, 60)
    assert thumb_source(small).size() == small.size()  # not wider than 2:1: untouched


def test_history_game_and_profile_columns_fit_their_entries(demo_ctx: Any, qtbot: Any) -> None:
    from autopress.ui.history_page import COL_GAME, COL_MESSAGE, COL_PROFILE, WIDTHS, HistoryPage

    page = HistoryPage(demo_ctx)
    qtbot.addWidget(page)
    page.resize(1060, 764)
    page.show()
    page.refresh()
    t = page._table
    page._fit_columns()
    qtbot.waitUntil(lambda: sum(t.columnWidth(c) for c in range(7)) == t.viewport().width())
    game, prof = t.columnWidth(COL_GAME), t.columnWidth(COL_PROFILE)
    assert game < WIDTHS[COL_GAME] and prof < WIDTHS[COL_PROFILE]  # before: always 140 each
    others = sum(t.columnWidth(c) for c in range(7) if c != COL_MESSAGE)
    assert t.columnWidth(COL_MESSAGE) == t.viewport().width() - others  # the message column gets the rest
    from PyQt6.QtGui import QFontMetrics

    fm = QFontMetrics(theme.font(theme.FS_BODY))
    header = t.horizontalHeader()
    for col in (COL_GAME, COL_PROFILE):  # as wide as the longest entry (or the header), so every entry fits
        texts = [str(page._model.data(page._model.index(row, col)) or "") for row in range(page._model.rowCount())]
        need = max([header.sectionSizeHint(col), 72] + [fm.horizontalAdvance(x) + 24 + 4 for x in texts])
        assert t.columnWidth(col) == min(need, WIDTHS[col]), (col, t.columnWidth(col), need)
        assert all(fm.horizontalAdvance(x) + 24 <= t.columnWidth(col) for x in texts)


# ============================================================================ import card


def test_import_line_explains_the_code_placeholder() -> None:
    from autopress.models import Profile

    p = Profile(name="p")
    t = make_step(StepType.TYPE_TEXT)
    t.params.text = "/redeem {code}"
    p.steps = [t]
    (line, risky), = p.action_lines()
    assert "「/redeem {code}」" in line and "（{code} 會換成每一筆序號）" in line and not risky
    i18n.set_language("en")
    (line, _r), = p.action_lines()
    assert "({code} becomes each code)" in line
