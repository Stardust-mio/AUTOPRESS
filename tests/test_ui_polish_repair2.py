# OWNED BY ORCH (UI polish, repair round 2 after the second screenshot verification, SPEC 3.2)
"""Repair round 2 of the UI polish (offscreen). Each test fails on the code before the repair:

* built-in template step names fit the step list (no 「拉出結果訊息出現的…」), also the wizard's close steps
* the gallery: the meta line wraps only between its parts (no line starts or ends with 「·」), the
  descriptions changed for widows
* one disabled look for primary, secondary and danger buttons
* the capture's paste text has no unticked 「不像序號」 row
* a preset format shows its allowed characters in words only; 「自訂」 shows the editable rule
* the Codes header says 「待處理 n」, the number of the sidebar pill
* the mini bar: wider in English; chips that leave no room for the wait / pause text show only counts
* the capture: the sheet's warning is a resized browser (not 'never tested'); evidence crops at 150 %
* the wizard: an untitled step's position gets an instruction that says what to pick
"""

from __future__ import annotations

import argparse
import shutil
from collections.abc import Iterator
from typing import Any

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication, QWidget

from autopress import i18n
from autopress.models import CodeStatus, PauseReason, Profile, RunState, StepType, make_step
from autopress.storage import load_templates
from autopress.ui import theme, widgets
from tools import guide_capture as gc


@pytest.fixture
def themed(qapp: QApplication) -> Iterator[QApplication]:
    """Tests that switch themes leave the shared application in the dark theme."""
    yield qapp
    theme.apply_theme(qapp, "dark")


def _opts(scale: float = 1.0) -> argparse.Namespace:
    return argparse.Namespace(theme="dark", scale=scale, lang="zh-TW", geometry=False)


# ============================================================================ step names


def _width_units(text: str) -> float:
    """Full-width characters count 1, the others 1/2 (a CJK character is 13 px, a Latin one 6-7 px)."""
    import unicodedata

    return sum(1.0 if unicodedata.east_asian_width(c) in ("W", "F") else 0.5 for c in text)


def test_template_step_names_fit_the_step_list() -> None:
    """The step list's name label is 144 px at the default window (real fonts: a CJK character 13 px,
    「N. 」 14 px; measured with the windows platform: every name fits at 100 / 125 / 150 %). Offscreen
    has no real fonts, so this pins the sizes that were measured to fit: 9 full-width characters and
    21 Latin characters."""
    from autopress.ui import profiles_wizard as pw

    names = [(s.label, s.label_en) for t in load_templates() for s in t.steps]
    p = Profile(name="p")
    p.steps = [make_step(StepType.OCR_CHECK)]
    for choice in (pw.CLOSE_OK, pw.CLOSE_ESC):
        pw.apply_close_choice(p, choice)
        close = p.steps[-1]
        names.append((close.label, close.label_en))
    assert len(names) == 3 * 6 + 2
    for zh, en in names:
        assert _width_units(zh) <= 9 and len(en) <= 21, (zh, en)
    assert ("框出結果訊息的範圍", "Drag over the result") in names
    assert not any("拉出結果訊息出現的範圍" in zh for zh, _en in names)


def test_game_dialog_description_names_its_type_code_step() -> None:
    t = next(t for t in load_templates() if t.template.key == "game_dialog")
    step = next(s for s in t.steps if s.type is StepType.TYPE_CODE)
    assert f"「{step.label}」步驟" in t.template.description_zh  # the description's 「輸入序號」 is the step's name


# ============================================================================ gallery


@pytest.mark.parametrize("width", [120, 160, 200, 260, 320, 420, 900])
def test_separated_label_breaks_only_between_parts(qapp: QApplication, width: int) -> None:
    parts = ["6 個步驟", "HoYoverse（原神／星鐵／絕區零）", "英文字母與數字", "6–16 碼"]
    lb = widgets.SeparatedLabel(parts)
    lines = lb.lines_for(width)
    assert widgets.SeparatedLabel.SEP.join(lines) == widgets.SeparatedLabel.SEP.join(parts)  # parts kept, in order
    for line in lines:
        assert not line.strip().startswith("·") and not line.strip().endswith("·"), lines
        assert line.split(widgets.SeparatedLabel.SEP)[0] in parts  # a line starts with a whole part
    fm = lb.fontMetrics()
    if len(lines) == 2:  # balanced: moving the break either way makes the longer line no shorter
        longer = max(fm.horizontalAdvance(line) for line in lines)
        for k in range(1, len(parts)):
            a = fm.horizontalAdvance(widgets.SeparatedLabel.SEP.join(parts[:k]))
            b = fm.horizontalAdvance(widgets.SeparatedLabel.SEP.join(parts[k:]))
            if a <= width and b <= width:
                assert longer <= max(a, b)


def test_separated_label_reflows_on_resize(qtbot: Any) -> None:
    host = QWidget()
    qtbot.addWidget(host)
    parts = ["一二三四", "五六七八", "九十"]
    lb = widgets.SeparatedLabel(parts, parent=host)
    host.resize(800, 200)
    host.show()  # resize events reach shown widgets only
    lb.ensurePolished()  # the role font decides the widths
    fm = lb.fontMetrics()
    lb.resize(fm.horizontalAdvance(widgets.SeparatedLabel.SEP.join(parts)) + 4, 40)
    QApplication.processEvents()
    assert "\n" not in lb.text()
    lb.resize(lb.fontMetrics().horizontalAdvance("一二三四") + 2, 80)
    QApplication.processEvents()
    assert lb.text().count("\n") >= 1 and "·\n" not in lb.text() and "\n·" not in lb.text()
    assert lb.heightForWidth(lb.width()) >= 2 * lb.fontMetrics().lineSpacing() - 1


def test_gallery_meta_line_is_a_separated_label(qtbot: Any) -> None:
    from autopress.ui.profiles_dialogs import TemplateGallery, format_parts

    templates = load_templates()
    gallery = TemplateGallery(templates)
    qtbot.addWidget(gallery)
    metas = gallery.findChildren(widgets.SeparatedLabel)
    assert len(metas) == len(templates)
    hoyo = next(t for t in templates if t.template.key == "hoyoverse_web")
    assert ["6 個步驟", *format_parts(hoyo.code_format)] in [m.parts() for m in metas]


# ============================================================================ disabled buttons


@pytest.mark.parametrize("name", ["dark", "light"])
def test_disabled_buttons_share_one_look(qtbot: Any, themed: QApplication, name: str) -> None:
    theme.apply_theme(themed, name)
    host = QWidget()
    qtbot.addWidget(host)
    buttons = [widgets.push_button(text, variant) for text, variant in
               (("測試一筆", "secondary"), ("開始兌換", "primary"), ("停止", "danger"))]
    for n, b in enumerate(buttons):
        b.setParent(host)
        b.setGeometry(10, 10 + n * 50, 120, 32)
        b.setEnabled(False)
    host.resize(160, 170)
    host.show()
    QApplication.processEvents()
    img = host.grab().toImage().convertToFormat(QImage.Format.Format_RGB32)
    fills = {img.pixelColor(b.x() + 6, b.y() + 16).name() for b in buttons}  # left of the text, inside the border
    edges = {img.pixelColor(b.x() + 60, b.y()).name() for b in buttons}
    assert fills == {theme.color("surface_raised").name()}, fills
    assert edges == {theme.color("border").name()}, edges


# ============================================================================ paste text of the capture


def test_capture_paste_text_has_no_unlikely_row(qapp: QApplication) -> None:
    world = gc.DemoWorld()
    undo = gc.install_demo_environment(world)
    st = None
    try:
        st = gc.Stage(_opts(), world)
        dlg = gc.s_paste(st).widget
        entries = dlg._model.entries  # noqa: SLF001 - the dialog's candidate rows
        assert [e.cand.code for e in entries] == ["AB12-CD34-EF56", "AP7K2QX9MZ4T", "XY12ZW34QP", "QR56-ST78UV"]
        assert all(e.cand.likely for e in entries)  # no unticked 「不像序號」 row (U34)
        dlg.deleteLater()
    finally:
        undo()
        if st is not None:
            shutil.rmtree(st.home, ignore_errors=True)


# ============================================================================ allowed characters


def test_preset_shows_allowed_characters_in_words_only(demo_ctx: Any, qtbot: Any) -> None:
    from autopress.ui.profiles_page import ProfilesPage

    page = ProfilesPage(demo_ctx)
    qtbot.addWidget(page)
    fc = page.format_card
    assert fc.preset.currentData() != "custom"
    assert fc.charset_words.text() == "英文字母與數字" and not fc.charset_words.isHidden()
    assert fc.charset.isHidden() and fc.charset_hint.isHidden()  # no "A-Za-z0-9" for a preset (U30)
    fc.preset.setCurrentIndex(fc.preset.findData("custom"))
    assert not fc.charset.isHidden() and fc.charset.text() == "A-Za-z0-9" and fc.charset_words.isHidden()
    assert fc.charset_hint.text() == "英文字母與數字" and not fc.charset_hint.isHidden()
    fc.preset.setCurrentIndex(fc.preset.findData("generic"))
    assert fc.charset.isHidden() and not fc.charset_words.isHidden()
    fc.max_len.setValue(20)  # changing a preset makes it 自訂: the rule appears
    assert fc.preset.currentData() == "custom" and not fc.charset.isHidden()


# ============================================================================ Codes header


def test_codes_header_names_what_the_pill_counts(demo_ctx: Any, qtbot: Any) -> None:
    from autopress.ui.codes_page import CodesPage

    page = CodesPage(demo_ctx)
    qtbot.addWidget(page)
    page.refresh()
    counts = demo_ctx.queue.counts()
    todo = sum(int(counts.get(s, 0) or 0) for s in (CodeStatus.PENDING, CodeStatus.COOLDOWN, CodeStatus.REVIEW))
    assert todo > 0
    assert f" · 待處理 {todo}" in page._subtitle.text()  # the sidebar pill's number, in words (U43)
    i18n.set_language("en")
    page.refresh()
    assert f" · {todo} to do" in page._subtitle.text()


# ============================================================================ mini bar


def test_minibar_is_wider_in_english(demo_ctx: Any, qtbot: Any) -> None:
    from autopress.ui import minibar as mb

    assert mb.bar_width() == mb.BAR_W == 660
    i18n.set_language("en")
    bar = mb.MiniBar(demo_ctx)
    qtbot.addWidget(bar)
    assert mb.bar_width() == mb.BAR_W_EN > mb.BAR_W and bar.width() == mb.BAR_W_EN


def test_minibar_chips_give_way_to_the_wait_and_pause_text(demo_ctx: Any, qtbot: Any) -> None:
    from autopress.ui import minibar as mb

    bar = mb.MiniBar(demo_ctx)
    qtbot.addWidget(bar)
    bar.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    bar.show()
    bar.set_state(RunState.RUNNING.value)
    bar.add_result(CodeStatus.SUCCESS)
    QApplication.processEvents()
    assert not bar.compact_chips and bar.chips[CodeStatus.SUCCESS].text == "成功 1"  # room: words
    for st in (CodeStatus.USED, CodeStatus.INVALID, CodeStatus.EXPIRED, CodeStatus.REVIEW, CodeStatus.FAILED):
        bar.add_result(st)
    QApplication.processEvents()
    assert bar.compact_chips  # six chips with words leave no room for 「下一筆 6 秒後」
    chip = bar.chips[CodeStatus.USED]
    assert chip.text == "1" and chip.toolTip() == "已使用 1" and chip.accessibleName() == "已使用 1"
    bar.set_waiting(6)
    assert bar.compact_chips and bar.info_text() == "· 下一筆 6 秒後"
    bar.set_waiting(0)
    assert bar.compact_chips  # decided by the chips, not by each wait between codes
    bar.set_counts({CodeStatus.SUCCESS: 2})
    assert not bar.compact_chips and bar.chips[CodeStatus.SUCCESS].text == "成功 2"
    assert bar.chips[CodeStatus.SUCCESS].toolTip() == ""
    bar.set_state(RunState.PAUSED.value, PauseReason.POINT_BLOCKED.value)
    words = sum(widgets.status_chip_width(st, f"{st.label()} {n}") for st, n in bar.counts.items())
    reason = bar.info_label.fontMetrics().horizontalAdvance(bar.info_label.text())
    assert bar.compact_chips is (words + bar.line2.layout().spacing() > bar.line2.width() - reason)
    bar.reset()
    assert not bar.compact_chips and all(c.isHidden() for c in bar.chips.values())


# ============================================================================ capture staging


def test_capture_sheet_warns_about_a_resized_window(qapp: QApplication) -> None:
    from PyQt6.QtWidgets import QLabel

    world = gc.DemoWorld()
    undo = gc.install_demo_environment(world)
    st = None
    try:
        st = gc.Stage(_opts(), world)
        sheet = gc.s_sheet(st).widget
        text = " ".join(lb.text() for lb in sheet.findChildren(QLabel))
        assert "視窗大小與錄製時不同（1280×720 → 1180×660）" in text
        assert "還沒有成功測試過" not in text  # the demo profile is tested on every screen
        sheet.deleteLater()
    finally:
        undo()
        if st is not None:
            shutil.rmtree(st.home, ignore_errors=True)


def test_capture_evidence_crops_follow_the_scale(qapp: QApplication) -> None:
    from PIL import Image

    world = gc.DemoWorld()
    st = gc.Stage(_opts(1.5), world)
    try:
        st.attach_evidence()
        rec = next(r for r in st.ctx.history.records() if r.evidence_path)
        w, h = st.page.layout.result_region[2:]
        assert Image.open(st.home / rec.evidence_path).size == (round(w * 1.5), round(h * 1.5))  # 1140 x 210
    finally:
        shutil.rmtree(st.home, ignore_errors=True)


# ============================================================================ wizard


def test_untitled_steps_get_an_instruction_that_says_what_to_pick(qtbot: Any) -> None:
    from autopress.ui import profiles_wizard as pw

    p = Profile(name="p")
    p.steps = [make_step(StepType.FOCUS_WINDOW), make_step(StepType.CLICK_POINT), make_step(StepType.TYPE_CODE),
               make_step(StepType.OCR_CHECK)]
    items = pw.position_items(p, False)
    assert [i.instruction for i in items] == ["點選第 2 步要點擊的位置", "框出結果訊息的範圍"]
    dlg = pw._PositionDialog(1, 2, items[0], False, None, progress=(1, 4))  # noqa: SLF001
    qtbot.addWidget(dlg)
    assert dlg.heading.text() == "點選第 2 步要點擊的位置" and dlg.step_line.text() == "設定檔的第 2 步：點擊位置"
    p.steps[1].label = "點一下序號輸入框"  # a step with its own title keeps it
    assert pw.position_items(p, False)[0].instruction == "點一下序號輸入框"
    ct = make_step(StepType.CLICK_TEXT)
    ct.params.region = ct.params.fallback_point = None  # type: ignore[union-attr]
    p.steps.append(ct)
    i18n.set_language("en")
    texts = {(i.step_index, i.field): i.instruction for i in pw.position_items(p, True)}
    assert texts[(3, "region")] == "Drag over the result message area"
    i18n.set_language("zh-TW")
    assert pw.untitled_instruction(5, ct.params, "region") == "框出第 5 步找文字的範圍"
    assert pw.untitled_instruction(5, ct.params, "fallback_point") == "點選第 5 步找不到文字時改點的位置"
    assert pw.untitled_instruction(3, make_step(StepType.TYPE_CODE).params, "verify_region") == "框出第 3 步要核對的輸入框"
