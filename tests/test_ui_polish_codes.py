# OWNED BY ORCH (UI polish of the screenshot review, SPEC 3.2; written by the G6 fix group)
"""UI polish of the Codes page and its import dialogs (the README / user-guide screenshots), one
group per review item: U1 the check column vs. the row selection, U16 one verb (確認) in the OCR
review, U17 the Run page's 測試一筆 label, U27 the no-profile reason said once and the same import
labels in the empty state, U28 a visible run-lock reason without 正在…中, U34 no zero counts in
the import summary. Offscreen only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import QLabel

from autopress import i18n
from autopress.models import CodeSource, OcrLine, OcrResult, RunSelection
from autopress.ui import theme
from autopress.ui.codes_candidates import summary_text
from autopress.ui.codes_common import NO_PROFILE
from autopress.ui.codes_model import COL_CHECK, COL_CODE
from autopress.ui.codes_page import CodesPage
from autopress.ui.codes_paint import CELL_PAD
from autopress.ui.ocr_review import OcrReviewDialog
from autopress.ui.paste_dialog import PasteDialog
from tests.fakes import demo_context, skip_if_stub

G1 = ("autopress.codes.queue", "autopress.codes.history", "autopress.codes.extract", "autopress.codes.presets",
      "autopress.codes.normalize")
UNTICK_NOTE = "目前會兌換全部未完成的序號，取消勾選不會略過它；只想跑勾選的序號，請在「執行」頁選「只跑勾選的」。"
RUN_LOCK = "執行中：這次執行的序號暫時不能修改"
SELECT_HINT = "點選序號即可批次操作"


def _page(qtbot: Any, ctx: Any) -> CodesPage:
    page = CodesPage(ctx)
    qtbot.addWidget(page)
    page.resize(1060, 760)
    page.refresh()
    return page


@pytest.fixture
def page(qtbot: Any, demo_ctx: Any) -> CodesPage:
    skip_if_stub(*G1)
    return _page(qtbot, demo_ctx)


@pytest.fixture
def toasts(demo_ctx: Any) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    demo_ctx.signals.toast.connect(lambda kind, text: out.append((kind, text)))
    return out


def _item(ctx: Any, code: str) -> Any:
    return next(i for i in ctx.queue.items() if i.code == code)


def _check_index(page: CodesPage, code: str) -> Any:
    return page._proxy.index(page._proxy.row_of(_item(page.ctx, code).id), COL_CHECK)


def _visible_label_texts(page: CodesPage) -> list[str]:
    return [lb.text() for lb in page.findChildren(QLabel) if lb.isVisibleTo(page)]


# ============================================================================= U1 ticks vs. selection


def test_u1_check_column_has_a_title_and_a_header_tooltip(page: CodesPage) -> None:
    model = page._model
    h = Qt.Orientation.Horizontal
    assert model.headerData(COL_CHECK, h, Qt.ItemDataRole.DisplayRole) == "執行"
    tip = model.headerData(COL_CHECK, h, Qt.ItemDataRole.ToolTipRole)
    assert "「只跑勾選的」" in tip and "「全部未完成」" in tip and "批次動作" in tip  # the Run page's names
    assert model.headerData(COL_CODE, h, Qt.ItemDataRole.ToolTipRole) is None
    # room for the bold 12 px title (2 CJK characters) plus the 12 px section padding on each side
    assert page._table.columnWidth(COL_CHECK) >= 2 * theme.FS_SMALL + 2 * 12
    i18n.set_language("en")
    assert model.headerData(COL_CHECK, h, Qt.ItemDataRole.DisplayRole) == "Run"
    tip = model.headerData(COL_CHECK, h, Qt.ItemDataRole.ToolTipRole)
    assert "Checked only" in tip and "All unfinished" in tip and "highlighted" in tip


def test_u1_bulk_bar_says_how_to_select_instead_of_zero(page: CodesPage) -> None:
    ctx = page.ctx
    assert all(it.checked for it in ctx.queue.items())  # imported codes start ticked
    assert page.selected_items() == []
    assert page._sel_label.text() == SELECT_HINT and "0" not in page._sel_label.text()
    assert not page._btn_remove.isEnabled()
    page.select_ids([_item(ctx, "ZK6WD2TQ9HNA").id, _item(ctx, "BZ2M5KQ8XH3P").id])
    assert page._sel_label.text() == "已選取 2 筆"
    assert page._btn_remove.isEnabled()
    page._table.clearSelection()
    assert page._sel_label.text() == SELECT_HINT
    i18n.set_language("en")
    page._update_bulk_bar()
    assert page._sel_label.text() == "Select codes for bulk actions"
    # the label elides instead of making the page wider than the 1100 px minimum window
    assert page._sel_label.minimumSizeHint().width() < page._sel_label.sizeHint().width()


def test_u1_untick_with_all_unfinished_explains_once(page: CodesPage, toasts: list) -> None:
    ctx = page.ctx
    assert RunSelection(ctx.settings.run_selection) is RunSelection.UNFINISHED  # the default
    page.on_check_toggled(_check_index(page, "ZK6WD2TQ9HNA"), True)  # ticking says nothing
    assert toasts == []
    page.on_check_toggled(_check_index(page, "ZK6WD2TQ9HNA"), False)
    assert _item(ctx, "ZK6WD2TQ9HNA").checked is False
    assert toasts == [("info", UNTICK_NOTE)]
    page.on_check_toggled(_check_index(page, "BZ2M5KQ8XH3P"), False)  # once per page
    page.set_checked_visible(False)
    assert toasts == [("info", UNTICK_NOTE)]
    assert not any(it.checked for it in ctx.queue.items())


def test_u1_untick_note_also_for_space_and_not_with_checked_only(qtbot: Any, demo_ctx: Any, toasts: list) -> None:
    skip_if_stub(*G1)
    page = _page(qtbot, demo_ctx)
    page.select_ids([_item(demo_ctx, "MX4T9PK2JR7D").id])
    page.toggle_checked_selected()  # Space on a ticked row
    assert _item(demo_ctx, "MX4T9PK2JR7D").checked is False
    assert toasts == [("info", UNTICK_NOTE)]
    toasts.clear()
    demo_ctx.settings.run_selection = RunSelection.CHECKED  # the ticks matter now: nothing to explain
    other = _page(qtbot, demo_ctx)
    other.on_check_toggled(_check_index(other, "ZK6WD2TQ9HNA"), False)
    other.set_checked_visible(False)
    assert _item(demo_ctx, "ZK6WD2TQ9HNA").checked is False
    assert toasts == []
    i18n.set_language("en")
    demo_ctx.settings.run_selection = RunSelection.UNFINISHED
    third = _page(qtbot, demo_ctx)
    third.set_checked_visible(True)
    third.on_check_toggled(_check_index(third, "ZK6WD2TQ9HNA"), False)
    assert toasts == [("info", "All unfinished codes run, so unchecking does not skip a code; to run only the "
                               "checked codes, choose Checked only on the Run page.")]


# ============================================================================= U16 one verb in the OCR review


def _ocr_result() -> OcrResult:
    low = [0.99] * 12
    low[4] = 0.6
    sure = [0.99] * 12
    return OcrResult(lines=[
        OcrLine(text="K8ZL0W3NBX5H", quad=[(10, 10), (220, 10), (220, 40), (10, 40)], score=0.9, char_confs=low),
        OcrLine(text="MX4T9PK2JR7Z", quad=[(10, 60), (220, 60), (220, 90), (10, 90)], score=0.99, char_confs=sure),
    ], width=240, height=150)


def _image() -> np.ndarray:
    img = np.full((150, 240, 3), 30, np.uint8)
    img[10:40, 10:220] = 200
    return img


def _ocr_dialog(ctx: Any, qtbot: Any) -> OcrReviewDialog:
    ctx.ocr.result = _ocr_result()
    dlg = OcrReviewDialog(ctx, _image(), CodeSource.IMAGE, "card.png", format_choice="generic")
    qtbot.addWidget(dlg)
    qtbot.waitUntil(lambda: dlg.state() == "results", timeout=2000)
    return dlg


def _review_texts(dlg: OcrReviewDialog, row: int) -> list[str]:
    model = dlg._model
    ix = model.index(row, model.col("reviewed"))
    return [dlg._review_hint.text(), dlg._all_reviewed_btn.text(), dlg._all_reviewed_btn.toolTip(),
            str(model.headerData(model.col("reviewed"), Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)),
            str(model.data(ix, Qt.ItemDataRole.DisplayRole)), str(model.data(ix, Qt.ItemDataRole.ToolTipRole)),
            dlg._summary.text()]


def test_u16_ocr_review_tick_hint_and_button_use_the_same_words(demo_ctx: Any, qtbot: Any) -> None:
    skip_if_stub(*G1)
    dlg = _ocr_dialog(demo_ctx, qtbot)
    model = dlg._model
    row = next(n for n, e in enumerate(dlg.entries()) if e.cand.flagged)
    ix = model.index(row, model.col("reviewed"))
    assert model.data(ix, Qt.ItemDataRole.DisplayRole) == "確認無誤"  # not 需核對 before the tick
    assert model.setData(ix, Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    assert model.data(ix, Qt.ItemDataRole.DisplayRole) == "確認無誤"  # the tick and colour show the state
    assert "勾選「確認無誤」" in dlg._review_hint.text()
    assert dlg._all_reviewed_btn.text() == "全部確認無誤"
    assert model.headerData(model.col("reviewed"), Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == "確認"
    unflagged = next(n for n, e in enumerate(dlg.entries()) if not e.cand.flagged)
    assert model.data(model.index(unflagged, model.col("reviewed")), Qt.ItemDataRole.DisplayRole) is None
    for text in _review_texts(dlg, row):
        assert "核對" not in text and "黃色" not in text and "橘色" not in text, text  # one verb, no colour names
    page = _page(qtbot, demo_ctx)
    assert "核對" not in page._btn_confirm.toolTip() and page._btn_confirm.text() == "確認無誤"


def test_u16_ocr_review_english_wording(demo_ctx: Any, qtbot: Any) -> None:
    skip_if_stub(*G1)
    i18n.set_language("en")
    dlg = _ocr_dialog(demo_ctx, qtbot)
    model = dlg._model
    row = next(n for n, e in enumerate(dlg.entries()) if e.cand.flagged)
    rcol = model.col("reviewed")
    assert model.data(model.index(row, rcol), Qt.ItemDataRole.DisplayRole) == "Looks right"
    assert 'tick "Looks right"' in dlg._review_hint.text()
    assert dlg._all_reviewed_btn.text() == "All look right"
    assert model.headerData(rcol, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == "Review"
    for text in _review_texts(dlg, row):
        assert "yellow" not in text.lower() and "orange" not in text.lower() and "Checked" not in text, text
    # the wider English label fits its column (box 16 px + gap 6 px + cell padding)
    label = QFontMetrics(theme.font(theme.FS_SMALL, bold=True)).horizontalAdvance("Looks right")
    assert dlg._view.columnWidth(rcol) >= label + 16 + 6 + 2 * CELL_PAD


# ============================================================================= U17 test-one label


def test_u17_test_one_has_the_run_page_label(demo_ctx: Any, qtbot: Any) -> None:
    skip_if_stub(*G1)
    from autopress.runner import messages
    from autopress.ui import run_actions
    from autopress.ui.run_page import RunPage
    from tests.data.ui_run.g7_helpers import attach_main_window

    attach_main_window(demo_ctx)
    demo_ctx.settings.countdown_s = 0
    for lang, want in (("zh-TW", "測試一筆"), ("en", "Test one")):
        i18n.set_language(lang)
        codes = CodesPage(demo_ctx)
        qtbot.addWidget(codes)
        run = RunPage(demo_ctx)
        qtbot.addWidget(run)
        assert codes._test_btn.text() == run.test_btn.text() == run_actions.action_label("test_one") == want
        assert want in messages.pf_untested()  # the preflight message names a button on both pages


# ============================================================================= U27 no-profile state


def test_u27_no_profile_reason_once_and_same_import_labels(qtbot: Any, isolated_home: Path) -> None:
    skip_if_stub(*G1)
    ctx = demo_context(isolated_home, with_data=False)
    page = _page(qtbot, ctx)
    assert page.banner_texts()["no_profile"] == str(NO_PROFILE)
    assert page._start_btn.toolTip() == page._test_btn.toolTip() == str(NO_PROFILE)  # tooltips still say why
    assert not page._run_hint.isVisibleTo(page)
    assert _visible_label_texts(page).count(str(NO_PROFILE)) == 1
    assert page._stack.currentIndex() == 1  # the empty state
    for key in ("paste", "file", "snip"):
        assert page._empty_actions[key].text() == page._import_buttons[key].text()
        assert page._empty_actions[key].isVisibleTo(page)
    assert page._empty_actions["snip"].text() == "框選螢幕"


# ============================================================================= U28 run lock


def test_u28_run_lock_reason_is_shown_and_not_redundant(page: CodesPage) -> None:
    ctx = page.ctx
    session = ctx.session
    plan = session.build_plan(ctx.active_profile(), ctx.settings)
    session.start(plan)
    assert page._model.locked_ids() == {i.code_id for i in plan.items}  # their check boxes turn grey
    assert page._run_hint.isVisibleTo(page) and page._run_hint.text() == RUN_LOCK
    assert page._start_btn.toolTip() == page._test_btn.toolTip() == RUN_LOCK
    assert not any("正在" in t and "中" in t for t in _visible_label_texts(page))
    i18n.set_language("en")
    page._update_run_buttons()
    assert page._run_hint.text() == "A run is in progress: its codes are read-only"
    i18n.set_language("zh-TW")
    session.stop()
    assert not page._run_hint.isVisibleTo(page) and page._start_btn.isEnabled()
    assert page._model.locked_ids() == frozenset()


# ============================================================================= U34 import summary


@pytest.mark.parametrize(("counts", "zh", "en"), [
    ((3, 1, 0), "將加入 3 筆，略過 1 筆重複", "3 will be added; skipping 1 duplicate(s)"),
    ((2, 0, 0, 1), "將加入 2 筆（1 筆需要確認）", "2 will be added (1 need review)"),
    ((2, 1, 1), "將加入 2 筆，略過 1 筆重複、1 筆已兌換過",
     "2 will be added; skipping 1 duplicate(s) and 1 already redeemed"),
    ((2, 0, 1), "將加入 2 筆，略過 1 筆已兌換過", "2 will be added; skipping 1 already redeemed"),
    ((0, 2, 0), "將加入 0 筆，略過 2 筆重複", "0 will be added; skipping 2 duplicate(s)"),
    ((4, 0, 0), "將加入 4 筆", "4 will be added"),
    ((1, 1, 0, 1), "將加入 1 筆，略過 1 筆重複（1 筆需要確認）", "1 will be added; skipping 1 duplicate(s) (1 need review)"),
])
def test_u34_summary_leaves_out_zero_counts(counts: tuple[int, ...], zh: str, en: str) -> None:
    assert summary_text(*counts) == zh
    i18n.set_language("en")
    assert summary_text(*counts) == en


def test_u34_paste_dialog_footer_has_no_zero_count(demo_ctx: Any, qtbot: Any) -> None:
    skip_if_stub(*G1)
    text = "今天的直播兌換碼：\nAB12-CD34-EF56\nAP7K2QX9MZ4T（重複）\nRedemption code: XY12ZW34QP\nＱＲ５６－ＳＴ７８ＵＶ\n"
    dlg = PasteDialog(demo_ctx, text, format_choice="generic")
    qtbot.addWidget(dlg)
    assert dlg.summary_counts() == (3, 1, 0, 0)
    assert dlg._summary.text() == "將加入 3 筆，略過 1 筆重複"
    # a word-like token stays listed but unticked (some real codes are words)
    word = next(e for e in dlg.entries() if e.cand.code == "Redemption")
    assert word.checked is False and "不像序號" in [t for t, _tone in word.badges()]
    assert next(e for e in dlg.entries() if e.cand.code == "AP7K2QX9MZ4T").duplicate
