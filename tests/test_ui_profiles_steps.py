# OWNED BY G7
"""Step editor round-trips for every step type (anchor, label per language, on_not_found,
only_new_text, split sizes, key combos), the step list, the keyword editor and the window
picker list (fake windows; forbidden programs disabled)."""

from __future__ import annotations

from typing import Any

import pytest
from PyQt6.QtCore import Qt

from autopress import i18n
from autopress.models import (
    Anchor,
    ClickPointParams,
    ClickTextParams,
    KeywordConfig,
    OcrCheckParams,
    ResultClass,
    SplitMode,
    Step,
    StepType,
    TargetMatch,
    TimeoutAction,
    TitleMatch,
    TypeCodeParams,
    UnknownParams,
    make_step,
    record_point,
    record_region,
    to_dict,
)
from autopress.ui.keywords_editor import KeywordsEditor, parse_keywords
from autopress.ui.step_editor import StepEditor, StepListWidget
from autopress.ui.step_forms import parse_sizes
from tests.data.ui_run.g7_helpers import window

CLIENT = (100, 50, 1280, 720)


@pytest.fixture
def editor(demo_ctx: Any, qtbot: Any) -> StepEditor:
    ed = StepEditor(demo_ctx)
    qtbot.addWidget(ed)
    return ed


def emitted(editor: StepEditor) -> list[Step]:
    out: list[Step] = []
    editor.stepChanged.connect(out.append)
    return out


@pytest.mark.parametrize("step_type", [t for t in StepType if t is not StepType.UNKNOWN])
def test_every_step_type_round_trips_unchanged(editor: StepEditor, demo_ctx: Any, step_type: StepType) -> None:
    profile = demo_ctx.active_profile()
    step = make_step(step_type)
    step.label, step.label_en = "中文標題", "English title"
    editor.set_step(step, profile, 3)
    assert editor.form is not None and editor.field("title") is not None
    assert to_dict(editor.step()) == to_dict(step)  # loading the form changes nothing
    assert editor.header.text().startswith("第 4 步")


def test_title_edits_label_in_zh_and_label_en_in_en(editor: StepEditor, demo_ctx: Any) -> None:
    profile = demo_ctx.active_profile()
    step = make_step(StepType.CLICK_POINT)
    out = emitted(editor)
    editor.set_step(step, profile, 0)
    editor.field("title").setText("點一下序號輸入框")
    assert out[-1].label == "點一下序號輸入框" and out[-1].label_en == ""
    i18n.set_language("en")
    editor.set_step(out[-1], profile, 0)
    assert editor.field("title").placeholderText() == "點一下序號輸入框"
    editor.field("title").setText("Click the code box")
    assert out[-1].label == "點一下序號輸入框" and out[-1].label_en == "Click the code box"


def test_click_point_anchor_and_clear(editor: StepEditor, demo_ctx: Any) -> None:
    step = make_step(StepType.CLICK_POINT)
    step.params.point = record_point(CLIENT, 1300, 700)
    out = emitted(editor)
    editor.set_step(step, demo_ctx.active_profile(), 1)
    field = editor.field("point")
    assert "(1200, 650)" in field.value_label.text()
    field.anchor.setCurrentIndex(field.anchor.findData(Anchor.BR.value))
    assert isinstance(out[-1].params, ClickPointParams) and out[-1].params.point.anchor is Anchor.BR
    assert out[-1].params.point.dx == 1200  # only the anchor changed
    field.clear_btn.click()
    assert out[-1].params.point is None
    assert "尚未設定點擊位置" in editor.issues.text()


def test_point_picking_records_client_relative_with_the_dpi(editor: StepEditor, demo_ctx: Any,
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    from autopress.ui import overlays

    from tests.data.ui_run.g7_helpers import patch_target

    info = window(55, "chrome.exe", "兌換 - Google Chrome", client=CLIENT)
    patch_target(monkeypatch, info, dpi=120)
    seen: dict[str, Any] = {}

    def fake_pick(kind: str, **kw: Any) -> overlays.PickResult:
        seen.update(kw, kind=kind)
        return overlays.PickResult(kind=kind, point=(740, 410))

    monkeypatch.setattr(overlays, "pick", fake_pick)
    out = emitted(editor)
    step = make_step(StepType.CLICK_POINT)
    step.label = "點一下序號輸入框"
    editor.set_step(step, demo_ctx.active_profile(), 1)
    editor.field("point").anchor.setCurrentIndex(0)
    editor.field("point").pick_btn.click()
    p = out[-1].params.point
    assert (p.dx, p.dy, p.ref_w, p.ref_h, p.ref_dpi) == (640, 360, 1280, 720, 120)
    assert seen["kind"] == "point" and seen["target_hwnd"] == 55 and seen["instruction"] == "點一下序號輸入框"


def test_picking_outside_the_client_area_is_refused(editor: StepEditor, demo_ctx: Any,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    from autopress.ui import overlays

    from tests.data.ui_run.g7_helpers import patch_target

    patch_target(monkeypatch, window(55, "chrome.exe", "兌換", client=CLIENT))
    monkeypatch.setattr(overlays, "pick", lambda kind, **kw: overlays.PickResult(kind=kind, point=(5, 5)))
    out = emitted(editor)
    editor.set_step(make_step(StepType.CLICK_POINT), demo_ctx.active_profile(), 1)
    editor.field("point").pick_btn.click()
    assert out == [] and "不在目標視窗" in editor.field("point").error.text()


def test_region_picking_is_clipped_to_the_client_area(editor: StepEditor, demo_ctx: Any,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    from autopress.ui import overlays

    from tests.data.ui_run.g7_helpers import patch_target

    patch_target(monkeypatch, window(55, "game.exe", "Game", client=CLIENT))
    monkeypatch.setattr(overlays, "pick", lambda kind, **kw: overlays.PickResult(kind=kind, rect=(50, 600, 400, 300)))
    out = emitted(editor)
    editor.set_step(make_step(StepType.OCR_CHECK), demo_ctx.active_profile(), 4)
    editor.field("region").pick_btn.click()
    r = out[-1].params.region
    assert (r.dx, r.dy, r.w, r.h) == (0, 550, 350, 170)


def test_click_text_on_not_found_and_text(editor: StepEditor, demo_ctx: Any) -> None:
    step = make_step(StepType.CLICK_TEXT)
    out = emitted(editor)
    editor.set_step(step, demo_ctx.active_profile(), 3)
    editor.field("text").setText("確定|OK")
    combo = editor.field("on_not_found")
    combo.setCurrentIndex(combo.findData(TimeoutAction.CONTINUE.value))
    p = out[-1].params
    assert isinstance(p, ClickTextParams) and p.text == "確定|OK" and p.on_not_found is TimeoutAction.CONTINUE
    assert editor.field("nth") is not None and editor.form.adv_box.isHidden()  # advanced fields collapsed
    editor.form.adv_btn.setChecked(True)
    assert not editor.form.adv_box.isHidden()


def test_ocr_check_only_new_text_switch(editor: StepEditor, demo_ctx: Any) -> None:
    step = make_step(StepType.OCR_CHECK)
    step.params.region = record_region(CLIENT, 300, 200, 700, 300)
    out = emitted(editor)
    editor.set_step(step, demo_ctx.active_profile(), 4)
    sw = editor.field("only_new_text")
    assert sw.isChecked()
    sw.setChecked(False)
    assert isinstance(out[-1].params, OcrCheckParams) and out[-1].params.only_new_text is False


def test_type_code_split_fields_follow_the_mode(editor: StepEditor, demo_ctx: Any) -> None:
    out = emitted(editor)
    editor.set_step(make_step(StepType.TYPE_CODE), demo_ctx.active_profile(), 2)
    form = editor.form
    assert form._rows["group_sizes"][0].isHidden() and form._rows["between"][0].isHidden()
    combo = editor.field("split")
    combo.setCurrentIndex(combo.findData(SplitMode.FIXED.value))
    assert not form._rows["group_sizes"][0].isHidden() and not form._rows["between"][0].isHidden()
    form.fields["group_sizes_edit"].setText("4,6,2")
    assert isinstance(out[-1].params, TypeCodeParams) and out[-1].params.group_sizes == [4, 6, 2]
    assert out[-1].params.split is SplitMode.FIXED
    form.fields["group_sizes_edit"].setText("4,x")  # invalid: kept, error shown
    assert out[-1].params.group_sizes == [4, 6, 2]


def test_key_combo_is_normalised_and_system_shortcuts_flagged(editor: StepEditor, demo_ctx: Any) -> None:
    out = emitted(editor)
    editor.set_step(make_step(StepType.KEY), demo_ctx.active_profile(), 5)
    edit = editor.form.fields["keys_edit"]
    edit.setText("ctrl + a")
    assert out[-1].params.keys == "Ctrl+A"
    edit.setText("Win+R")
    assert "系統快捷鍵" in editor.issues.text()


def test_spin_boxes_apply_on_enter_only(editor: StepEditor, demo_ctx: Any) -> None:
    out = emitted(editor)
    editor.set_step(make_step(StepType.WAIT), demo_ctx.active_profile(), 0)
    sb = editor.field("ms")
    assert not sb.keyboardTracking()
    sb.setValue(2500)
    assert out[-1].params.ms == 2500


def test_unknown_step_is_kept_verbatim(editor: StepEditor, demo_ctx: Any) -> None:
    step = Step(type=StepType.UNKNOWN, params=UnknownParams(type_name="click_image", raw={"threshold": 0.9}))
    editor.set_step(step, demo_ctx.active_profile(), 2)
    assert editor.field("unknown") is not None
    assert to_dict(editor.step()) == to_dict(step)


def test_parse_sizes() -> None:
    assert parse_sizes("5,5,5") == [5, 5, 5] and parse_sizes("4-6-2") == [4, 6, 2]
    assert parse_sizes("") == [] and parse_sizes("5,0") is None and parse_sizes("a") is None


# ----------------------------------------------------------------------------- step list


def test_step_list_add_duplicate_move_enable_delete(demo_ctx: Any, qtbot: Any) -> None:
    lst = StepListWidget(demo_ctx)
    qtbot.addWidget(lst)
    changes: list[int] = []
    lst.stepsChanged.connect(lambda: changes.append(1))
    steps = [make_step(t) for t in (StepType.FOCUS_WINDOW, StepType.CLICK_POINT, StepType.TYPE_CODE)]
    lst.set_steps(steps)
    assert lst.current_index() == 0 and [s.id for s in lst.steps()] == [s.id for s in steps]
    lst.set_current(1)
    at = lst.add_step(StepType.WAIT)
    assert at == 2 and lst.steps()[2].type is StepType.WAIT
    lst.duplicate_step(0)
    assert lst.steps()[1].type is StepType.FOCUS_WINDOW and lst.steps()[1].id != lst.steps()[0].id
    lst.move_step(1, 1)
    assert [s.type for s in lst.steps()][:3] == [StepType.FOCUS_WINDOW, StepType.CLICK_POINT, StepType.FOCUS_WINDOW]
    lst.set_enabled(0, False)
    assert lst.steps()[0].enabled is False
    lst.delete_step(0)
    assert len(lst.steps()) == 4 and len(changes) == 5
    assert not lst.up_btn.isEnabled() or lst.current_index() > 0


def test_step_list_drag_reorder_syncs_the_steps(demo_ctx: Any, qtbot: Any) -> None:
    from PyQt6.QtCore import QModelIndex

    lst = StepListWidget(demo_ctx)
    qtbot.addWidget(lst)
    steps = [make_step(t) for t in (StepType.FOCUS_WINDOW, StepType.CLICK_POINT, StepType.TYPE_CODE)]
    lst.set_steps(steps)
    model = lst.list.model()
    if not model.moveRows(QModelIndex(), 0, 1, QModelIndex(), 3):  # what an internal drag does
        pytest.skip("QListWidget model cannot move rows here")
    assert [s.id for s in lst.steps()] == [steps[1].id, steps[2].id, steps[0].id]
    assert all(lst.list.itemWidget(lst.list.item(i)) is not None for i in range(3))


def test_step_rows_show_numbers_titles_and_error_dots(demo_ctx: Any, qtbot: Any) -> None:
    lst = StepListWidget(demo_ctx)
    qtbot.addWidget(lst)
    click = make_step(StepType.CLICK_POINT)
    click.label = "點一下序號輸入框"
    lst.set_steps([make_step(StepType.FOCUS_WINDOW), click])
    lst.set_error_rows({1})
    row = lst.list.itemWidget(lst.list.item(1))
    assert row.title.text() == "2. 點一下序號輸入框" and row.summary.text() == "尚未設定位置"
    assert not row.issue.isHidden()


# ----------------------------------------------------------------------------- keywords


def test_keyword_editor_round_trip_order_and_add(qtbot: Any) -> None:
    ed = KeywordsEditor()
    qtbot.addWidget(ed)
    cfg = KeywordConfig(groups={ResultClass.SUCCESS: ["兌換成功"], ResultClass.USED: ["已使用", "already used"]},
                        order=[ResultClass.USED, ResultClass.SUCCESS], fuzzy=False)
    cfg._after_load()
    ed.set_config(cfg)
    out = ed.config()
    assert out.order[:2] == [ResultClass.USED, ResultClass.SUCCESS] and out.fuzzy is False
    assert out.groups[ResultClass.USED] == ["已使用", "already used"]
    changes: list[int] = []
    ed.changed.connect(lambda: changes.append(1))
    ed.add_keyword(ResultClass.SUCCESS, "領取成功")
    ed.add_keyword(ResultClass.SUCCESS, "領取 成功")  # same squash: not added twice
    ed.add_keyword(ResultClass.UNKNOWN, "x")  # ignored
    assert ed.config().groups[ResultClass.SUCCESS] == ["兌換成功", "領取成功"] and changes
    ed.move_class(ResultClass.SUCCESS, -1)
    assert ed.config().order[0] is ResultClass.SUCCESS


def test_keyword_editor_overlap_warning_and_defaults(qtbot: Any) -> None:
    ed = KeywordsEditor()
    qtbot.addWidget(ed)
    ed.field(ResultClass.INVALID).setText("無效, 已使用")
    ed.field(ResultClass.USED).setText("已使用")
    assert not ed.warning.isHidden() and "已使用" in ed.warning.text()
    ed.restore_defaults()
    assert ed.warning.isHidden()
    assert ed.config().groups == KeywordConfig().groups


def test_parse_keywords_accepts_chinese_separators() -> None:
    assert parse_keywords("兌換成功，領取成功、已發送; done\n too many ") == ["兌換成功", "領取成功", "已發送", "done", "too many"]


# ----------------------------------------------------------------------------- window picker


@pytest.fixture
def fake_windows(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    from autopress.win32 import elevation, windows

    wins = [window(1, "explorer.exe", "檔案總管"), window(2, "chrome.exe", "原神兌換 - Google Chrome"),
            window(3, "game.exe", "My Game"), window(4, "notepad.exe", "記事本"),
            window(5, "launcher.exe", "Launcher", minimized=True)]
    monkeypatch.setattr(windows, "list_windows", lambda alt_tab_only=True: list(wins))
    perms = {3: "blocked_elevated", 4: "unknown"}
    monkeypatch.setattr(elevation, "input_permission", lambda hwnd: perms.get(hwnd, "ok"))
    return wins


def test_window_picker_lists_badges_and_disables_forbidden(demo_ctx: Any, qtbot: Any, fake_windows: list) -> None:
    from autopress.ui.window_picker import WindowPickerDialog

    dlg = WindowPickerDialog(demo_ctx, None, None, suggested_exe="game.exe")
    qtbot.addWidget(dlg)
    items = [dlg.tree.topLevelItem(i) for i in range(dlg.tree.topLevelItemCount())]
    assert [it.text(1) for it in items][0] == "game.exe"  # the suggested exe first
    by_exe = {it.text(1): it for it in items}
    assert not (by_exe["explorer.exe"].flags() & Qt.ItemFlag.ItemIsEnabled)
    assert "系統程式，不能當目標" in by_exe["explorer.exe"].text(2)
    assert "系統管理員" in by_exe["game.exe"].text(2) and "建議" in by_exe["game.exe"].text(2)
    assert "未知權限" in by_exe["notepad.exe"].text(2)
    assert "已最小化" in by_exe["launcher.exe"].text(2)
    assert not dlg.select_hwnd(1)  # forbidden: cannot be selected
    assert dlg.select_hwnd(2) and dlg.ok_btn.isEnabled()
    assert dlg.selected().exe_name == "chrome.exe"
    dlg.search.setText("記事")
    assert dlg.tree.topLevelItemCount() == 1


def test_window_picker_preselects_the_current_target(demo_ctx: Any, qtbot: Any, fake_windows: list) -> None:
    from autopress.ui.window_picker import WindowPickerDialog

    current = TargetMatch(exe="chrome.exe", title="原神兌換", title_mode=TitleMatch.CONTAINS)
    dlg = WindowPickerDialog(demo_ctx, current)
    qtbot.addWidget(dlg)
    assert dlg.selected() is not None and dlg.selected().hwnd == 2


def test_window_picker_survives_a_failing_window_list(demo_ctx: Any, qtbot: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from autopress.ui.window_picker import WindowPickerDialog
    from autopress.win32 import windows

    def boom(alt_tab_only: bool = True) -> list:
        raise OSError("denied")

    monkeypatch.setattr(windows, "list_windows", boom)
    dlg = WindowPickerDialog(demo_ctx)
    qtbot.addWidget(dlg)
    assert dlg.tree.topLevelItemCount() == 0 and "無法讀取視窗清單" in dlg.empty.text()
    assert not dlg.ok_btn.isEnabled()
