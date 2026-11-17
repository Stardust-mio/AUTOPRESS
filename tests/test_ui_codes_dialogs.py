# OWNED BY G6
"""PasteDialog (debounced extraction + summary, badges) and OcrReviewDialog with the
FakeOcrService (loading, error, no codes, results, 確認無誤 / edits clear the flags) - SPEC 6.4.1,
8.2 G6."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from PyQt6.QtCore import Qt

from autopress.models import (
    AttemptRecord,
    CodeSource,
    CodeStatus,
    OcrLine,
    OcrOptions,
    OcrResult,
)
from autopress.ui.ocr_review import OcrReviewDialog
from autopress.ui.paste_dialog import DEBOUNCE_MS, PasteDialog
from tests.fakes import FakeOcrService, skip_if_stub

G1 = ("autopress.codes.queue", "autopress.codes.history", "autopress.codes.extract", "autopress.codes.presets",
      "autopress.codes.normalize")


@pytest.fixture
def ctx(demo_ctx: Any) -> Any:
    skip_if_stub(*G1)
    return demo_ctx


def _codes(dlg: Any) -> list[str]:
    return [e.cand.code for e in dlg.entries()]


# ============================================================================= paste dialog


def test_paste_dialog_debounced_extraction_and_summary(ctx: Any, qtbot: Any) -> None:
    key = ctx.active_profile().game_key()
    ctx.history.append(AttemptRecord(code="DONE1234AB", game_key=key, game="示範遊戲", status=CodeStatus.USED))
    dlg = PasteDialog(ctx, "", format_choice="generic")
    qtbot.addWidget(dlg)
    assert dlg.entries() == []
    assert not dlg._add_btn.isEnabled()
    dlg._editor.setPlainText("兌換碼：AB12-CD34-EF56\nAP7K2QX9MZ4T\nDONE1234AB\nGH78JK90LM12")
    assert dlg.extraction_pending()  # debounced: nothing extracted yet
    assert dlg.entries() == []
    qtbot.waitUntil(lambda: not dlg.extraction_pending(), timeout=DEBOUNCE_MS + 1500)
    assert _codes(dlg) == ["AB12-CD34-EF56", "AP7K2QX9MZ4T", "DONE1234AB", "GH78JK90LM12"]
    assert dlg.summary_counts() == (2, 1, 1, 0)
    assert dlg._summary.text() == "將加入 2 筆，略過 1 筆重複、1 筆已兌換過"
    assert dlg._add_btn.text() == "加入 2 筆" and dlg._add_btn.isEnabled()
    badges = {e.cand.code: [t for t, _tone in e.badges()] for e in dlg.entries()}
    assert badges["AP7K2QX9MZ4T"] == ["重複"]  # queued AND redeemed (demo history): skipped as duplicate
    assert badges["GH78JK90LM12"] == []
    assert badges["DONE1234AB"] == ["已兌換過"]
    # duplicates / history skips stay in candidates() so the queue counts them
    assert {c.code for c in dlg.candidates()} == set(_codes(dlg))
    dup = next(c for c in dlg.candidates() if c.code == "AP7K2QX9MZ4T")
    assert dup.duplicate_of == ctx.queue.find_code("AP7K2QX9MZ4T", key).id
    res = ctx.queue.add_candidates(dlg.candidates(), CodeSource.PASTE, history=ctx.history, game_key=key,
                                   game="示範遊戲", skip_statuses=[CodeStatus.SUCCESS, CodeStatus.USED])
    assert (len(res.added), res.duplicates, res.skipped_history) == (2, 1, 1)


def test_paste_dialog_unlikely_words_unchecked_and_raw_text(ctx: Any, qtbot: Any) -> None:
    dlg = PasteDialog(ctx, "Redemption code: XY12ZW34QP\nＱＲ５６－ＳＴ７８ＵＶ", format_choice="generic")
    qtbot.addWidget(dlg)
    entries = {e.cand.code: e for e in dlg.entries()}
    assert entries["Redemption"].checked is False
    assert "不像序號" in [t for t, _ in entries["Redemption"].badges()]
    assert entries["XY12ZW34QP"].checked is True
    fw = entries["QR56-ST78UV"]
    assert fw.cand.raw == "ＱＲ５６－ＳＴ７８ＵＶ"
    row = dlg.entries().index(fw)
    tip = dlg._model.data(dlg._model.index(row, dlg._model.col("code")), Qt.ItemDataRole.ToolTipRole)
    assert "原文：ＱＲ５６－ＳＴ７８ＵＶ" in tip
    assert {c.code for c in dlg.candidates()} == {"XY12ZW34QP", "QR56-ST78UV"}
    # ticking the unlikely one adds it too
    dlg._model.setData(dlg._model.index(dlg.entries().index(entries["Redemption"]), 0), Qt.CheckState.Checked,
                       Qt.ItemDataRole.CheckStateRole)
    assert dlg.summary_counts()[0] == 3


def test_paste_dialog_format_change_reextracts(ctx: Any, qtbot: Any) -> None:
    dlg = PasteDialog(ctx, "ABCDE-FGHIJ-KLMNP\nXY12ZW34QP", format_choice="generic")
    qtbot.addWidget(dlg)
    assert set(_codes(dlg)) == {"ABCDE-FGHIJ-KLMNP", "XY12ZW34QP"}
    dlg._format_combo.setCurrentIndex(dlg._format_keys.index("steam"))
    assert _codes(dlg) == ["ABCDE-FGHIJ-KLMNP"]
    assert dlg.code_format().id == "steam"
    dlg._format_combo.setCurrentIndex(dlg._format_keys.index("auto"))
    assert dlg._detected and dlg._detected_label.text().startswith("偵測為：")


def test_paste_dialog_no_codes_message_and_accept_flushes(ctx: Any, qtbot: Any) -> None:
    dlg = PasteDialog(ctx, "只有中文，沒有序號", format_choice="generic")
    qtbot.addWidget(dlg)
    assert dlg._stack.currentIndex() == 1
    assert dlg._empty.text() == "沒有找到符合格式的序號，請換一種序號格式或手動輸入。"
    dlg._editor.setPlainText("FAST1234ZZ")  # 加入 right after typing: the pending extraction runs first
    dlg.accept()
    assert dlg.result() == 1
    assert [c.code for c in dlg.candidates()] == ["FAST1234ZZ"]


# ============================================================================= OCR review


def _ocr_result() -> OcrResult:
    low = [0.99] * 12
    low[4] = 0.6
    return OcrResult(lines=[
        OcrLine(text="K8ZL0W3NBX5H", quad=[(10, 10), (220, 10), (220, 40), (10, 40)], score=0.9, char_confs=low),
        OcrLine(text="MX4T9PK2JR7Z", quad=[(10, 60), (220, 60), (220, 90), (10, 90)], score=0.99, char_confs=[0.99] * 12),
        OcrLine(text="兌換碼", quad=[(10, 100), (80, 100), (80, 130), (10, 130)], score=0.95),
    ], width=240, height=150)


def _image() -> np.ndarray:
    img = np.full((150, 240, 3), 30, np.uint8)
    img[10:40, 10:220] = 200
    return img


def test_ocr_review_loading_then_results(ctx: Any, qtbot: Any) -> None:
    ctx.ocr.result = _ocr_result()
    dlg = OcrReviewDialog(ctx, _image(), CodeSource.IMAGE, "card.png", format_choice="generic")
    qtbot.addWidget(dlg)
    assert dlg.state() == "loading"  # the fake delivers on the next event-loop turn
    assert not dlg._add_btn.isEnabled()
    image, opts = ctx.ocr.requests[-1]
    assert isinstance(opts, OcrOptions) and opts.det_side == ctx.settings.ocr.det_side == 960
    from autopress.codes import presets

    fmt = presets.get_format("generic")
    assert opts.code_charset == fmt.allowed_chars() + fmt.separator
    assert image.shape == (150, 240, 3)
    qtbot.waitUntil(lambda: dlg.state() == "results", timeout=2000)
    entries = {e.cand.code: e for e in dlg.entries()}
    assert set(entries) == {"K8ZL0W3NBX5H", "MX4T9PK2JR7Z"}
    assert entries["K8ZL0W3NBX5H"].cand.flagged == [4] and entries["K8ZL0W3NBX5H"].needs_review
    assert entries["K8ZL0W3NBX5H"].crop is not None and not entries["K8ZL0W3NBX5H"].crop.isNull()
    assert dlg._summary.text() == "將加入 2 筆（1 筆需要確認）"  # skip parts with 0 are left out
    assert dlg._all_reviewed_btn.isVisibleTo(dlg)
    assert dlg._add_btn.isEnabled()


def test_ocr_review_reviewed_and_edited_clear_flags(ctx: Any, qtbot: Any) -> None:
    ctx.ocr.result = _ocr_result()
    dlg = OcrReviewDialog(ctx, _image(), CodeSource.SNIP, format_choice="generic")
    qtbot.addWidget(dlg)
    qtbot.waitUntil(lambda: dlg.state() == "results", timeout=2000)
    model = dlg._model
    row = next(n for n, e in enumerate(dlg.entries()) if e.cand.code == "K8ZL0W3NBX5H")
    rcol = model.col("reviewed")
    assert model.data(model.index(row, rcol), Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Unchecked
    assert model.data(model.index(1 - row, rcol), Qt.ItemDataRole.CheckStateRole) is None  # not flagged
    # not reviewed: stays flagged -> REVIEW in the queue
    flagged = {c.code: c.flagged for c in dlg.candidates()}
    assert flagged["K8ZL0W3NBX5H"] == [4]
    assert model.setData(model.index(row, rcol), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    flagged = {c.code: c.flagged for c in dlg.candidates()}
    assert flagged["K8ZL0W3NBX5H"] == [] and dlg.summary_counts()[3] == 0
    model.setData(model.index(row, rcol), Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
    assert model.set_all_reviewed() == 1
    assert all(not c.flagged for c in dlg.candidates())
    # an edit clears the flags too and is validated
    model.setData(model.index(row, rcol), Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
    ccol = model.col("code")
    assert not model.setData(model.index(row, ccol), "abc", Qt.ItemDataRole.EditRole)
    assert dlg._edit_error.text()
    assert not model.setData(model.index(row, ccol), "MX4T9PK2JR7Z", Qt.ItemDataRole.EditRole)  # duplicate
    assert model.setData(model.index(row, ccol), "K8ZLOW3NBX5H", Qt.ItemDataRole.EditRole)
    e = dlg.entries()[row]
    assert e.edited and e.flagged == [] and e.cand.code == "K8ZLOW3NBX5H"
    assert "已修改" in [t for t, _ in e.badges()]
    res = ctx.queue.add_candidates(dlg.candidates(), CodeSource.SNIP, game_key=ctx.active_profile().game_key())
    assert {ctx.queue.get(i).status for i in res.added} == {CodeStatus.PENDING}


def test_ocr_review_error_state_and_retry(ctx: Any, qtbot: Any) -> None:
    ctx.ocr = FakeOcrService(state="failed", error="找不到模型檔")
    dlg = OcrReviewDialog(ctx, _image())
    qtbot.addWidget(dlg)
    qtbot.waitUntil(lambda: dlg.state() == "error", timeout=2000)
    assert dlg.error_text().startswith("文字辨識引擎無法啟動：找不到模型檔")
    assert "防毒軟體" in dlg.error_text()
    assert not dlg._add_btn.isEnabled()
    n = len(ctx.ocr.requests)
    ctx.ocr._state = type(ctx.ocr.state)("ready")
    ctx.ocr.result = _ocr_result()
    dlg._error_banner.actionClicked.emit()  # 重試
    assert len(ctx.ocr.requests) == n + 1
    qtbot.waitUntil(lambda: dlg.state() == "results", timeout=2000)


def test_ocr_review_no_codes_state(ctx: Any, qtbot: Any) -> None:
    ctx.ocr.result = OcrResult(lines=[OcrLine(text="今天沒有序號", quad=[(5, 5), (90, 5), (90, 30), (5, 30)], score=0.9)],
                               width=100, height=40)
    dlg = OcrReviewDialog(ctx, _image(), format_choice="generic")
    qtbot.addWidget(dlg)
    qtbot.waitUntil(lambda: dlg.state() == "empty", timeout=2000)
    assert dlg._ocr_text.toPlainText() == "今天沒有序號"
    assert not dlg._add_btn.isEnabled()
    dlg.accept()
    assert dlg.result() == 0  # nothing to add: accept is ignored


def test_ocr_review_cancel_drops_pending_request(ctx: Any, qtbot: Any) -> None:
    ctx.ocr.result = _ocr_result()
    dlg = OcrReviewDialog(ctx, _image())
    qtbot.addWidget(dlg)
    job = dlg._job
    dlg.reject()
    assert job in ctx.ocr._cancelled
    qtbot.wait(20)
    assert dlg.state() == "loading"  # the cancelled result never arrived


def test_ocr_review_bgra_input_and_page_flow(ctx: Any, qtbot: Any) -> None:
    from autopress.ui.codes_page import CodesPage

    ctx.ocr.result = _ocr_result()
    page = CodesPage(ctx)
    qtbot.addWidget(page)
    bgra = np.dstack([_image(), np.full((150, 240), 255, np.uint8)])
    page.import_image(bgra, CodeSource.CLIPBOARD)
    dlg = page.current_dialog()
    assert isinstance(dlg, OcrReviewDialog)
    qtbot.waitUntil(lambda: dlg.state() == "results", timeout=2000)
    dlg.accept()
    key = ctx.active_profile().game_key()
    review = ctx.queue.find_code("K8ZL0W3NBX5H", key)
    assert review is not None and review.status is CodeStatus.REVIEW and review.source is CodeSource.CLIPBOARD
    assert ctx.queue.find_code("MX4T9PK2JR7Z", key).status is CodeStatus.PENDING
