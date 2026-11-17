# OWNED BY G6
"""Codes page (SPEC 6.4.1, 8.2 G6): builds while RunFlow is a stub (lazy creation), banners,
確認無誤 / 重設為待兌換 / 指定給, read-only plan rows, inline edit validation, imports through the
dialogs, drag-and-drop of text and image files, CSV export, shortcuts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PyQt6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QGuiApplication, QImage
from PyQt6.QtWidgets import QApplication

from autopress.models import (
    AttemptRecord,
    CodeCandidate,
    CodeSource,
    CodeStatus,
    PlanMode,
    RunSelection,
)
from autopress.ui import widgets
from autopress.ui.codes_model import COL_CODE, FILTERS, CodeEditor
from autopress.ui.codes_page import CodesPage
from autopress.ui.ocr_review import OcrReviewDialog
from autopress.ui.paste_dialog import PasteDialog
from tests.fakes import demo_context, skip_if_stub

G1 = ("autopress.codes.queue", "autopress.codes.history", "autopress.codes.extract", "autopress.codes.presets",
      "autopress.codes.normalize")


@pytest.fixture
def toasts(demo_ctx: Any) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    demo_ctx.signals.toast.connect(lambda kind, text: out.append((kind, text)))
    return out


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


def _item(ctx: Any, code: str) -> Any:
    return next(i for i in ctx.queue.items() if i.code == code)


def _select(page: CodesPage, *codes: str) -> None:
    page.select_ids([_item(page.ctx, c).id for c in codes])


class _FakeFlow:
    instances: list[_FakeFlow] = []

    def __init__(self, ctx: Any, parent: Any = None) -> None:
        self.calls: list[tuple[Any, ...]] = []
        _FakeFlow.instances.append(self)

    def begin(self, profile: Any, selection: RunSelection = RunSelection.UNFINISHED, *, code_ids: Any = None,
              mode: PlanMode = PlanMode.NORMAL, target_hwnd: int = 0) -> bool:
        self.calls.append((profile.id, selection, list(code_ids or []), mode))
        return True


# ============================================================================= building / run buttons


def test_builds_while_runflow_is_a_stub(page: CodesPage, toasts: list, monkeypatch: pytest.MonkeyPatch) -> None:
    from autopress.ui import run_flow

    class Stub:
        def __init__(self, *a: Any, **k: Any) -> None:
            raise NotImplementedError

    monkeypatch.setattr(run_flow, "RunFlow", Stub)
    assert page._run_flow is None  # nothing created at construction (T11)
    assert page._start_btn.isEnabled()
    assert page.start_run() is False
    assert ("warning", "尚未實作") in toasts
    assert page._run_flow is None


def test_runflow_created_lazily_once(page: CodesPage, monkeypatch: pytest.MonkeyPatch) -> None:
    from autopress.ui import run_flow

    _FakeFlow.instances = []
    monkeypatch.setattr(run_flow, "RunFlow", _FakeFlow)
    assert _FakeFlow.instances == []
    _select(page, "ZK6WD2TQ9HNA")
    assert page.start_run(test_one=True)
    assert page.start_run(test_one=False)
    assert len(_FakeFlow.instances) == 1
    flow = _FakeFlow.instances[0]
    pid = page.ctx.active_profile().id
    assert flow.calls[0] == (pid, RunSelection.UNFINISHED, [_item(page.ctx, "ZK6WD2TQ9HNA").id], PlanMode.TEST_ONE)
    assert flow.calls[1] == (pid, RunSelection.UNFINISHED, [], PlanMode.NORMAL)


def test_test_one_takes_first_runnable_without_selection(page: CodesPage, monkeypatch: pytest.MonkeyPatch) -> None:
    from autopress.ui import run_flow

    _FakeFlow.instances = []
    monkeypatch.setattr(run_flow, "RunFlow", _FakeFlow)
    _select(page, "AP7K2QX9MZ4T")  # SUCCESS: not runnable -> first runnable code of the game
    page.start_run(test_one=True)
    first = page.ctx.queue.runnable(RunSelection.UNFINISHED, page.ctx.active_profile().game_key())[0]
    assert _FakeFlow.instances[0].calls[0][2] == [first.id]


def test_no_profile_banner_and_disabled_buttons_say_why(qtbot: Any, isolated_home: Path) -> None:
    ctx = demo_context(isolated_home, with_data=False)
    page = _page(qtbot, ctx)
    assert "no_profile" in page.banner_texts()
    assert page.banner_texts()["no_profile"] == "先建立或選擇設定檔，才能開始兌換。"
    for btn in (page._start_btn, page._test_btn):
        assert not btn.isEnabled()
        assert btn.toolTip() == "先建立或選擇設定檔，才能開始兌換。"
    # the no-profile banner is the inline explanation: the hint under the buttons does not repeat it
    assert page._run_hint.text() == "" and not page._run_hint.isVisibleTo(page)
    assert page._stack.currentIndex() == 1  # empty state
    assert page.format_choice() == "auto"
    navigated: list[str] = []
    ctx.signals.navigate.connect(navigated.append)
    page._no_profile_banner.actionClicked.emit()
    assert navigated == ["profiles"]


def test_disabled_without_runnable_codes(page: CodesPage) -> None:
    ctx = page.ctx
    key = ctx.active_profile().game_key()
    with page._model.batch():
        for it in ctx.queue.runnable(RunSelection.UNFINISHED, key):
            ctx.queue.set_status(it.id, CodeStatus.SKIPPED)
    page.refresh()
    assert not page._start_btn.isEnabled() and not page._test_btn.isEnabled()
    assert "沒有「示範遊戲」可兌換的序號" in page._start_btn.toolTip()
    assert page._run_hint.text() == page._start_btn.toolTip()


def test_buttons_disabled_during_run(page: CodesPage) -> None:
    session = page.ctx.session
    plan = session.build_plan(page.ctx.active_profile(), page.ctx.settings)
    session.start(plan)
    assert not page._start_btn.isEnabled()
    assert page._start_btn.toolTip() == "執行中：這次執行的序號暫時不能修改"
    session.stop()
    assert page._start_btn.isEnabled()


# ============================================================================= banners and actions


def test_unassigned_banner_assigns_to_active_game(page: CodesPage, toasts: list) -> None:
    ctx = page.ctx
    ctx.queue.add_candidates([CodeCandidate(code="UNSET111AA"), CodeCandidate(code="UNSET222BB")], CodeSource.PASTE)
    page.refresh()
    assert page.banner_texts()["unassigned"] == "2 筆序號尚未指定遊戲，這次不會執行。"
    page._unassigned_banner.actionClicked.emit()
    key = ctx.active_profile().game_key()
    assert all(i.game_key == key and i.game == "示範遊戲" for i in ctx.queue.items())
    page.refresh()
    assert "unassigned" not in page.banner_texts()
    assert any("指定給「示範遊戲」" in t for _k, t in toasts)


def test_review_banner_and_next_review(page: CodesPage) -> None:
    assert page.banner_texts()["review"] == "2 筆序號需要確認（辨識信心偏低或字元已修正）"
    page._segments.setCurrentIndex(FILTERS.index("done"))  # the REVIEW rows are hidden by the filter
    assert page.next_review()
    assert page._proxy.filter_key() == "all"
    assert [i.code for i in page.selected_items()] == ["Q8ZL0W3NBX5C"]
    page.next_review()
    assert [i.code for i in page.selected_items()] == ["TRV6Y2NCBL1X"]
    page.next_review()  # wraps around
    assert [i.code for i in page.selected_items()] == ["Q8ZL0W3NBX5C"]
    page._review_banner.closed.emit()
    page.refresh()
    assert "review" not in page.banner_texts()  # dismissed until the count grows


def test_confirm_ok_and_reset_pending(page: CodesPage) -> None:
    ctx = page.ctx
    _select(page, "Q8ZL0W3NBX5C", "TRV6Y2NCBL1X", "AP7K2QX9MZ4T")
    assert page._btn_confirm.isEnabled()
    assert page.confirm_ok() == 2
    for code in ("Q8ZL0W3NBX5C", "TRV6Y2NCBL1X"):
        it = _item(ctx, code)
        assert it.status is CodeStatus.PENDING and it.flagged == [] and it.message == ""
    assert _item(ctx, "AP7K2QX9MZ4T").status is CodeStatus.SUCCESS  # confirm touches REVIEW only
    _select(page, "JW8R3TD5QN2K", "EK5P9WM3ZT7V")  # INVALID, EXPIRED
    assert page.reset_pending() == 2
    assert _item(ctx, "JW8R3TD5QN2K").status is CodeStatus.PENDING
    assert _item(ctx, "EK5P9WM3ZT7V").status is CodeStatus.PENDING


def test_skip_unskip_keeps_review_gate(page: CodesPage) -> None:
    ctx = page.ctx
    _select(page, "Q8ZL0W3NBX5C", "ZK6WD2TQ9HNA")  # REVIEW (flagged) + PENDING
    assert page.toggle_skip() == 2
    assert {_item(ctx, c).status for c in ("Q8ZL0W3NBX5C", "ZK6WD2TQ9HNA")} == {CodeStatus.SKIPPED}
    page._update_bulk_bar()
    assert page._btn_skip.text() == "取消略過"
    assert page.toggle_skip() == 2
    assert _item(ctx, "Q8ZL0W3NBX5C").status is CodeStatus.REVIEW  # flagged -> back to REVIEW
    assert _item(ctx, "ZK6WD2TQ9HNA").status is CodeStatus.PENDING


def test_mark_redeemed_writes_manual_history(page: CodesPage) -> None:
    ctx = page.ctx
    before = len(ctx.history.records())
    _select(page, "ZK6WD2TQ9HNA")
    assert page.mark_redeemed() == 1
    it = _item(ctx, "ZK6WD2TQ9HNA")
    assert it.status is CodeStatus.SUCCESS and it.message == "手動標記"
    recs = ctx.history.records()
    assert len(recs) == before + 1
    rec = recs[-1]
    assert rec.run_id == "manual" and rec.code == "ZK6WD2TQ9HNA" and rec.game_key == it.game_key
    assert ctx.history.is_done(it.game_key, "ZK6WD2TQ9HNA", [CodeStatus.SUCCESS])


def test_assign_selected_to_current_game(page: CodesPage) -> None:
    ctx = page.ctx
    res = ctx.queue.add_candidates([CodeCandidate(code="OTHERG1234")], CodeSource.PASTE, game_key="game:other",
                                   game="別的遊戲")
    page._set_game(None)  # 所有遊戲
    page.select_ids(res.added)
    assert page.assign_to_current() == 1
    it = ctx.queue.get(res.added[0])
    assert it.game_key == ctx.active_profile().game_key() and it.game == "示範遊戲"


def test_remove_move_and_clear_done(page: CodesPage, monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = page.ctx
    n0 = len(ctx.queue)
    _select(page, "BZ2M5KQ8XH3P")
    page.move_selected_top()
    assert ctx.queue.items()[0].code == "BZ2M5KQ8XH3P"
    assert [i.code for i in page.selected_items()] == ["BZ2M5KQ8XH3P"]  # selection followed the row
    page.move_selected(1)
    assert ctx.queue.items()[1].code == "BZ2M5KQ8XH3P"
    monkeypatch.setattr(widgets, "confirm", lambda *a, **k: False)
    _select(page, "BZ2M5KQ8XH3P", "ZK6WD2TQ9HNA")
    assert page.remove_selected() == 0 and len(ctx.queue) == n0  # declined
    monkeypatch.setattr(widgets, "confirm", lambda *a, **k: True)
    assert page.remove_selected() == 2 and len(ctx.queue) == n0 - 2
    done = {"AP7K2QX9MZ4T", "HV3N8RT2KD6W", "GS4H8NM2VC6R"}  # SUCCESS, USED, SUBMITTED
    assert page.clear_done() == 3
    assert not done & {i.code for i in ctx.queue.items()}


def test_plan_rows_read_only_during_run(page: CodesPage, toasts: list) -> None:
    ctx = page.ctx
    session = ctx.session
    plan = session.build_plan(ctx.active_profile(), ctx.settings)
    plan_ids = {p.code_id for p in plan.items}
    assert plan_ids
    session.start(plan)
    pid = next(iter(plan_ids))
    row = page._proxy.row_of(pid)
    assert not page._proxy.flags(page._proxy.index(row, COL_CODE)) & Qt.ItemFlag.ItemIsEditable
    page.select_ids([pid])
    assert not page._btn_remove.isEnabled()
    assert page.remove_selected() == 0
    assert ctx.queue.get(pid) is not None
    assert any(t == "執行中，請先停止" for _k, t in toasts)
    other = _item(ctx, "AP7K2QX9MZ4T")  # not in the plan: still editable
    assert page._proxy.flags(page._proxy.index(page._proxy.row_of(other.id), COL_CODE)) & Qt.ItemFlag.ItemIsEditable
    session.stop()
    assert page._proxy.flags(page._proxy.index(page._proxy.row_of(pid), COL_CODE)) & Qt.ItemFlag.ItemIsEditable


# ============================================================================= inline editing


def test_inline_edit_validation(page: CodesPage, toasts: list) -> None:
    ctx = page.ctx
    item = _item(ctx, "Q8ZL0W3NBX5C")
    assert item.status is CodeStatus.REVIEW and item.flagged == [4]
    ix = page._proxy.index(page._proxy.row_of(item.id), COL_CODE)
    page._table.setCurrentIndex(ix)
    page._table.edit(ix)
    editor = page._table.findChild(CodeEditor)
    assert editor is not None
    editor.setText("abc")
    assert editor.property("invalid") is True and "6" in editor.reason
    page._code_delegate.setModelData(editor, page._proxy, ix)
    assert _item(ctx, "Q8ZL0W3NBX5C").flagged == [4]  # rejected
    assert toasts[-1][0] == "warning"
    editor.setText("AP7K2QX9MZ4T")  # duplicate of row 1 in the same game
    assert "已在清單中" in editor.reason
    editor.setText("Q8ZLOW3NBX5C")
    assert editor.property("invalid") is False
    page._code_delegate.setModelData(editor, page._proxy, ix)
    edited = ctx.queue.get(item.id)
    assert edited.code == "Q8ZLOW3NBX5C"
    assert edited.flagged == [] and edited.status is CodeStatus.PENDING and edited.confidence is None
    assert 4 in edited.lookalikes  # O has the look-alike 0 in the generic charset


def test_edit_of_final_status_resets_to_pending(page: CodesPage) -> None:
    ctx = page.ctx
    item = _item(ctx, "JW8R3TD5QN2K")  # INVALID
    assert page._apply_code_edit(item, "JW8R3TD5QN2X")
    edited = ctx.queue.get(item.id)
    assert edited.status is CodeStatus.PENDING and edited.message == ""


# ============================================================================= imports


def test_import_text_adds_to_active_game(page: CodesPage, toasts: list) -> None:
    ctx = page.ctx
    page.import_text("兌換碼：AB12-CD34-EF56\nAP7K2QX9MZ4T\nGH78JK90LM12")
    dlg = page.current_dialog()
    assert isinstance(dlg, PasteDialog)
    assert dlg.summary_counts()[:2] == (2, 1)  # AP7K2QX9MZ4T is already queued
    dlg.accept()
    assert page.current_dialog() is None
    key = ctx.active_profile().game_key()
    added = [i for i in ctx.queue.items() if i.code in ("AB12-CD34-EF56", "GH78JK90LM12")]
    assert len(added) == 2 and all(i.game_key == key and i.source is CodeSource.PASTE for i in added)
    assert toasts[-1] == ("success", "已加入 2 筆序號（略過 1 筆重複）")
    assert "已去除 1 筆重複" in page._subtitle.text()
    assert {i.code for i in page.selected_items()} == {"AB12-CD34-EF56", "GH78JK90LM12"}


def test_import_without_profile_is_unassigned(qtbot: Any, isolated_home: Path) -> None:
    skip_if_stub(*G1)
    ctx = demo_context(isolated_home, with_data=False)
    page = _page(qtbot, ctx)
    page.import_text("ZZ99XX88YY77")
    page.current_dialog().accept()
    (item,) = ctx.queue.items()
    assert item.game_key == "" and item.game == ""
    assert "unassigned" not in page.banner_texts()  # no profile: the no-profile banner explains it


def test_history_skip_follows_the_switch(page: CodesPage) -> None:
    ctx = page.ctx
    key = ctx.active_profile().game_key()
    ctx.history.append(AttemptRecord(code="DONE1234AB", game_key=key, game="示範遊戲", status=CodeStatus.SUCCESS))
    page.import_text("DONE1234AB")
    dlg = page.current_dialog()
    assert dlg.summary_counts()[:3] == (0, 0, 1)
    dlg.reject()
    page._skip_switch.setChecked(False)
    assert ctx.settings.skip_history_on_import is False
    page.import_text("DONE1234AB")
    dlg = page.current_dialog()
    assert dlg.summary_counts()[:3] == (1, 0, 0)
    dlg.accept()
    assert ctx.queue.find_code("DONE1234AB", key) is not None


def test_import_file_error_toast(page: CodesPage, toasts: list, tmp_path: Path) -> None:
    page.import_file(tmp_path / "missing.txt")
    assert toasts and toasts[-1][0] == "error"
    assert page.current_dialog() is None


def _drop(page: CodesPage, mime: QMimeData) -> bool:
    enter = QDragEnterEvent(QPoint(20, 20), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton,
                            Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(page, enter)
    if not enter.isAccepted():
        return False
    drop = QDropEvent(QPointF(20, 20), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton,
                      Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(page, drop)
    return drop.isAccepted()


def test_drag_drop_text_and_image_files(page: CodesPage, qtbot: Any, tmp_path: Path) -> None:
    skip_if_stub("autopress.codes.fileimport", "autopress.ocr.imageio")
    txt = tmp_path / "序號清單.txt"
    txt.write_text("DROP1111AA\nDROP2222BB\n", encoding="utf-8")
    png = tmp_path / "截圖.png"
    img = QImage(120, 40, QImage.Format.Format_RGB32)
    img.fill(Qt.GlobalColor.white)
    assert img.save(str(png))
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(txt)), QUrl.fromLocalFile(str(png))])
    assert _drop(page, mime)
    dlg = page.current_dialog()
    assert isinstance(dlg, PasteDialog) and dlg._source is CodeSource.FILE and dlg._detail == "序號清單.txt"
    assert [e.cand.code for e in dlg.entries()] == ["DROP1111AA", "DROP2222BB"]
    dlg.accept()
    qtbot.waitUntil(lambda: isinstance(page.current_dialog(), OcrReviewDialog), timeout=2000)
    ocr = page.current_dialog()
    assert ocr._source is CodeSource.IMAGE and ocr._detail == "截圖.png"
    assert ocr._image.shape[:2] == (40, 120)
    ocr.reject()
    assert {i.source_detail for i in page.ctx.queue.items() if i.code.startswith("DROP")} == {"序號清單.txt"}


def test_drag_drop_plain_text_and_rejects_other(page: CodesPage) -> None:
    mime = QMimeData()
    mime.setText("TEXT1111ZZ")
    assert _drop(page, mime)
    assert isinstance(page.current_dialog(), PasteDialog)
    page.current_dialog().reject()
    assert not _drop(page, QMimeData())


def test_ctrl_v_opens_paste_dialog_with_clipboard_text(page: CodesPage, qtbot: Any) -> None:
    QGuiApplication.clipboard().setText("CLIP1234XYZ")
    page.show()
    page.activateWindow()
    page._table.setFocus()
    qtbot.waitUntil(lambda: QApplication.focusWidget() is not None, timeout=2000)
    qtbot.keyClick(QApplication.focusWidget(), Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    dlg = page.current_dialog()
    assert isinstance(dlg, PasteDialog)
    assert dlg.text() == "CLIP1234XYZ"
    dlg.reject()


def test_csv_export_of_visible_rows(page: CodesPage, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    skip_if_stub("autopress.codes.csvexport")
    from PyQt6.QtWidgets import QFileDialog

    out = tmp_path / "匯出.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(out), "CSV"))
    page._segments.setCurrentIndex(FILTERS.index("review"))
    assert page.export_csv()
    data = out.read_bytes()
    assert data.startswith(b"\xef\xbb\xbf")
    text = data.decode("utf-8-sig")
    assert "Q8ZL0W3NBX5C" in text and "TRV6Y2NCBL1X" in text and "AP7K2QX9MZ4T" not in text
    assert text.splitlines()[0].startswith("#")


def test_game_filter_default_and_all_games(page: CodesPage) -> None:
    ctx = page.ctx
    ctx.queue.add_candidates([CodeCandidate(code="OTHERG5678")], CodeSource.PASTE, game_key="game:other", game="別的遊戲")
    page.refresh()
    labels = [page._game_combo.itemText(i) for i in range(page._game_combo.count())]
    assert labels[:2] == ["示範遊戲（含未指定）", "所有遊戲"] and "別的遊戲（含未指定）" in labels
    assert ctx.queue.find_code("OTHERG5678").id not in {i.id for i in page.visible_items()}
    page._game_combo.setCurrentIndex(1)
    page._on_game_activated(1)
    assert ctx.queue.find_code("OTHERG5678").id in {i.id for i in page.visible_items()}
    assert page._segment_labels[0] == f"全部 {len(ctx.queue)}"


def test_import_card_keeps_format_combo_reachable(page: CodesPage, qtbot: Any) -> None:
    page.show()
    page.resize(1060, 760)
    qtbot.wait(20)
    wide_row = page.format_box_row()
    page.resize(700, 700)
    qtbot.waitUntil(lambda: page.format_box_row() == 2, timeout=2000)
    # (the minimum width itself is measured with real fonts on the windows platform, not offscreen)
    page.resize(1600, 760)
    qtbot.waitUntil(lambda: page.format_box_row() == 1, timeout=2000)
    assert wide_row in (1, 2)
