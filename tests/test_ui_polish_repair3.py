# OWNED BY ORCH (UI polish, repair round 3 after the third screenshot verification, SPEC 3.2)
"""Repair round 3 of the UI polish (offscreen). Each test fails on the code before the repair:

* the step list's red "required setting missing" dot leads the summary line: a row with the dot
  gives its name as much room as a row without (it cut 「5. 框出結果訊息的範圍」 in fresh templates)
* 「待處理 n」 in the Codes header is the sum of the 待兌換 and 需確認 segments also while a code is
  兌換中, and the sidebar's 序號 pill and its tooltip count the same codes
* 以系統管理員身分重新啟動 asks Save / Discard / Cancel for unsaved profile edits BEFORE the elevated
  instance starts (it waits only 10 s for this one to quit); 取消 starts nothing, 不儲存 takes effect
  only with the restart
* the in-game template's English description names its 「輸入序號」 step by its English name
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from PyQt6.QtWidgets import QApplication, QWidget

from autopress.models import CodeStatus, IssueLevel, StepType
from autopress.storage import load_templates
from autopress.ui import main_window as mw_mod
from autopress.ui import profiles_dialogs
from autopress.ui.profiles_page import ProfilesPage
from autopress.ui.step_editor import StepListWidget
from tests.data.ui_run.g7_helpers import attach_main_window, patch_dialogs

THIS = "tests.test_ui_polish_repair3"


# ============================================================================ step list dot


def test_missing_setting_dot_does_not_narrow_the_step_name(demo_ctx: Any, qtbot: Any) -> None:
    tpl = next(t for t in load_templates() if t.template.key == "web_generic")
    errors = {i.step_index for i in tpl.validate() if i.level is IssueLevel.ERROR and i.step_index >= 0}
    assert {1, 4} <= errors  # a fresh template profile: the click position and the result region
    lst = StepListWidget(demo_ctx)
    qtbot.addWidget(lst)
    lst.resize(300, 420)
    lst.set_steps(tpl.steps)
    lst.set_error_rows(errors)
    lst.show()
    QApplication.processEvents()
    rows = [lst.list.itemWidget(lst.list.item(i)) for i in range(len(tpl.steps))]
    names = {i: row.title.width() for i, row in enumerate(rows)}
    assert min(names.values()) > 100 and len(set(names.values())) == 1, names  # the dot costs no name width
    for i, row in enumerate(rows):
        assert row.issue.isHidden() == (i not in errors)
        if i in errors:  # 「● 尚未設定位置」: on the summary line, in front of the summary, centred on it
            dot, summary, title = row.issue.geometry(), row.summary.geometry(), row.title.geometry()
            assert dot.center().y() > title.bottom() and dot.right() < summary.left(), (dot, summary, title)
            assert abs(dot.center().y() - summary.center().y()) <= 1
            assert row.summary.text() in ("尚未設定位置", "尚未設定結果範圍")
            assert row.issue.toolTip() == "這一步還有必填項目沒設定"


# ============================================================================ 待處理


class StandInPage(QWidget):
    """Replaces the pages these tests do not look at."""

    def __init__(self, ctx: object) -> None:
        super().__init__()
        self.ctx = ctx


@pytest.fixture
def shell(demo_ctx: Any, qtbot: Any, monkeypatch: pytest.MonkeyPatch) -> mw_mod.MainWindow:
    pages = dict(mw_mod.PAGE_CLASSES)
    for pid in ("profiles", "run", "history"):
        pages[pid] = (THIS, "StandInPage")
    monkeypatch.setattr(mw_mod, "PAGE_CLASSES", pages)
    monkeypatch.setattr(mw_mod, "_request_quit", lambda: None)
    w = mw_mod.MainWindow(demo_ctx)
    qtbot.addWidget(w)
    return w


def test_todo_count_adds_up_with_the_segments_while_a_code_runs(shell: mw_mod.MainWindow, demo_ctx: Any,
                                                                  qtbot: Any) -> None:
    from autopress.ui.codes_model import FILTER_STATUSES, FILTERS, TODO_STATUSES

    assert set(TODO_STATUSES) == FILTER_STATUSES["pending"] | FILTER_STATUSES["review"]
    page = shell.page("codes")
    assert page is not None
    pending = [it for it in demo_ctx.queue.items() if it.status is CodeStatus.PENDING]
    demo_ctx.queue.update(pending[0].id, status=CodeStatus.RUNNING)  # as the engine does when a code starts
    page.refresh()
    segments = {k: int(label.rsplit(" ", 1)[1]) for k, label in zip(FILTERS, page._segment_labels)}
    header = page._subtitle.text()
    todo = int(re.search(r"待處理 (\d+)", header).group(1))  # type: ignore[union-attr]
    assert todo == segments["pending"] + segments["review"], (header, page._segment_labels)
    assert segments["all"] == sum(n for k, n in segments.items() if k != "all")  # the segments still add up
    counts = demo_ctx.queue.counts()
    codes = shell.sidebar.buttons["codes"]
    qtbot.waitUntil(lambda: "兌換中 1" in codes.toolTip())  # the pill's refresh is coalesced
    assert codes.badge() == str(todo)  # the pill: the same codes as the header
    tip = codes.toolTip()
    assert tip.startswith(f"待處理的序號 {todo} 筆：")
    assert all((f"{s.label()} {counts[s]}" in tip) == bool(counts[s]) for s in TODO_STATUSES)
    assert "已完成" not in tip and "成功" not in tip


# ============================================================================ restart as administrator


@pytest.fixture
def page(demo_ctx: Any, qtbot: Any, monkeypatch: pytest.MonkeyPatch) -> ProfilesPage:
    mw = attach_main_window(demo_ctx)
    monkeypatch.setattr(ProfilesPage, "start_wizard", lambda self, pid, realign=False: None)
    p = ProfilesPage(demo_ctx)
    qtbot.addWidget(p)
    mw.pages["profiles"] = p
    return p


@pytest.fixture
def restart(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Records the order of: the Save / Discard / Cancel question (``answer`` is what the user
    clicks), the start of the elevated instance (``ok`` = it started) and QApplication.quit."""
    from autopress.win32 import elevation

    rec: dict[str, Any] = {"events": [], "answer": "cancel", "ok": True, "parents": []}

    def ask(parent: Any, name: str) -> str:
        rec["events"].append(f"ask:{rec['answer']}")
        rec["parents"].append(parent)
        return rec["answer"]

    def start(argv: Any = None) -> bool:
        rec["events"].append("restart")
        return rec["ok"]

    monkeypatch.setattr(profiles_dialogs, "ask_save_changes", ask)
    monkeypatch.setattr(elevation, "restart_as_admin", start)
    monkeypatch.setattr(QApplication, "quit", staticmethod(lambda: rec["events"].append("quit")))
    rec["dialogs"] = patch_dialogs(monkeypatch, default=True)  # 重新啟動 at the confirmation
    return rec


def test_restart_asks_about_unsaved_edits_before_the_elevated_instance_starts(page: ProfilesPage,
                                                                               restart: dict[str, Any]) -> None:
    from autopress.ui import run_actions

    ctx = page.ctx
    pid = page.working_profile().id
    stored_name = ctx.profiles.get(pid).name
    page.basics.name.setText("改過但還沒存")
    assert page.is_dirty()
    picker = QWidget()  # the window picker that holds the button

    # 取消: nothing starts, the edits stay unsaved
    assert run_actions.restart_as_admin_flow(picker, ctx) is False
    assert restart["events"] == ["ask:cancel"] and restart["parents"] == [picker]
    assert page.is_dirty() and page.basics.name.text() == "改過但還沒存"

    # 不儲存 while the consent prompt is declined: nothing is lost, the edits are still unsaved
    restart["events"].clear()
    restart["answer"], restart["ok"] = "discard", False
    assert run_actions.restart_as_admin_flow(picker, ctx) is False
    assert restart["events"] == ["ask:discard", "restart"] and restart["dialogs"].messages
    assert page.is_dirty() and page.basics.name.text() == "改過但還沒存"

    # 不儲存: the question comes first, the edits are dropped only once the restart started, so
    # closing (MainWindow.closeEvent -> maybe_leave) does not ask again while the new instance waits
    restart["events"].clear()
    restart["ok"] = True
    assert run_actions.restart_as_admin_flow(picker, ctx) is True
    assert restart["events"] == ["ask:discard", "restart", "quit"]
    assert not page.is_dirty() and page.basics.name.text() == stored_name
    assert ctx.profiles.get(pid).name == stored_name
    assert page.maybe_leave() is True and restart["events"] == ["ask:discard", "restart", "quit"]


def test_restart_saves_the_edits_first_when_asked(page: ProfilesPage, restart: dict[str, Any],
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    from autopress.ui import run_actions
    from autopress.win32 import elevation

    ctx = page.ctx
    pid = page.working_profile().id
    page.basics.name.setText("改過也要存")
    restart["answer"] = "save"
    seen: list[str] = []
    monkeypatch.setattr(elevation, "restart_as_admin",
                        lambda argv=None: seen.append(ctx.profiles.get(pid).name) or restart["events"].append("restart") or True)
    assert run_actions.restart_as_admin_flow(None, ctx) is True
    assert restart["events"] == ["ask:save", "restart", "quit"]
    assert seen == ["改過也要存"]  # saved before the elevated instance (which loads the profiles) started
    assert not page.is_dirty()

    # no unsaved edits: no question at all
    restart["events"].clear()
    assert run_actions.restart_as_admin_flow(None, ctx) is True
    assert restart["events"] == ["restart", "quit"]


def test_restart_stays_when_the_save_fails(page: ProfilesPage, restart: dict[str, Any],
                                           monkeypatch: pytest.MonkeyPatch) -> None:
    from autopress.ui import run_actions

    page.basics.name.setText("存不進去")
    restart["answer"] = "save"
    monkeypatch.setattr(ProfilesPage, "save_profile", lambda self, confirm_newer=True: False)
    assert run_actions.restart_as_admin_flow(None, page.ctx) is False
    assert restart["events"] == ["ask:save"] and page.is_dirty()


# ============================================================================ template text


def test_game_dialog_english_description_names_its_type_code_step() -> None:
    t = next(t for t in load_templates() if t.template.key == "game_dialog")
    step = next(s for s in t.steps if s.type is StepType.TYPE_CODE)
    assert f'"{step.label_en}" step' in t.template.description_en
    assert f"「{step.label}」步驟" in t.template.description_zh
