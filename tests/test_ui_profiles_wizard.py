# OWNED BY G7
"""Setup wizard / 重新對準 (SPEC 6.4.2): target window (browser title keyword), every
missing_setup() position, the result-close choice, preview, 測試一筆 with a paste box for one
real code, cancel keeps progress, realign re-picks recorded positions."""

from __future__ import annotations

from typing import Any

import pytest

from autopress.models import (
    ClickTextParams,
    KeyParams,
    PlanMode,
    StepType,
    TargetMatch,
    TimeoutAction,
    TitleMatch,
    make_step,
    record_point,
    record_region,
)
from autopress.ui import profiles_wizard as pw
from autopress.ui.profiles_page import ProfilesPage, blank_profile
from tests.data.ui_run.g7_helpers import attach_main_window, patch_dialogs, window

CLIENT = (100, 50, 1280, 720)


class Script:
    """Scripted answers for the wizard's UI methods."""

    def __init__(self, positions: list[str], close: str | None = "esc", test: Any = None) -> None:
        self.positions = list(positions)
        self.close = close
        self.test = test
        self.asked: list[str] = []
        self.picked: list[str] = []
        self.started: list[list[str]] = []
        self.previewed = 0

    def install(self, monkeypatch: pytest.MonkeyPatch, info: Any) -> None:
        s = self
        monkeypatch.setattr(pw.SetupWizard, "choose_window", lambda self: info)
        monkeypatch.setattr(pw.SetupWizard, "ask_title_keyword", lambda self, kw: kw.split(" - ")[0])

        def ask_position(self: Any, n: int, total: int, item: pw.PositionItem) -> str:
            s.asked.append(f"{item.step_index}.{item.field}")
            return s.positions.pop(0) if s.positions else "cancel"

        def pick_position(self: Any, item: pw.PositionItem) -> tuple[Any, str]:
            s.picked.append(f"{item.step_index}.{item.field}")
            if item.kind == "point":
                return record_point(CLIENT, 740, 410), ""
            return record_region(CLIENT, 300, 200, 700, 300), ""

        monkeypatch.setattr(pw.SetupWizard, "ask_position", ask_position)
        monkeypatch.setattr(pw.SetupWizard, "pick_position", pick_position)
        monkeypatch.setattr(pw.SetupWizard, "ask_close_choice", lambda self, current: s.close)
        monkeypatch.setattr(pw.SetupWizard, "preview", lambda self: setattr(s, "previewed", s.previewed + 1))
        monkeypatch.setattr(pw.SetupWizard, "ask_test", lambda self: s.test)
        monkeypatch.setattr(pw.SetupWizard, "start_test", lambda self, ids: s.started.append(list(ids)) or True)


@pytest.fixture
def page(demo_ctx: Any, qtbot: Any) -> ProfilesPage:
    attach_main_window(demo_ctx)
    p = ProfilesPage(demo_ctx)
    qtbot.addWidget(p)
    return p


def _new_blank(page: ProfilesPage, game: str = "新遊戲") -> str:
    prof = blank_profile(page.ctx)
    prof.game = game
    page.ctx.profiles.save(prof)
    page.refresh_list()
    page.open_profile(prof.id)
    return prof.id


def test_full_wizard_on_a_blank_profile(page: ProfilesPage, monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = page.ctx
    pid = _new_blank(page)
    script = Script(["pick", "pick"], close="esc", test=("paste", "NEWC0DE12345"))
    script.install(monkeypatch, window(31, "chrome.exe", "兌換中心 - Google Chrome"))
    wiz = pw.SetupWizard(page, pid)
    assert wiz.run() is True
    stored = ctx.profiles.get(pid)
    assert stored.target.exe == "chrome.exe" and stored.target.title == "兌換中心"
    assert stored.target.title_mode is TitleMatch.CONTAINS
    assert script.asked == ["1.point", "4.region"] and stored.missing_setup() == []
    assert stored.steps[1].params.point.dx == 640 and stored.steps[4].params.region.w == 700
    # 「按 Esc」 was inserted right after the ocr_check
    assert stored.steps[5].type is StepType.KEY and isinstance(stored.steps[5].params, KeyParams)
    assert stored.steps[5].params.keys == "Esc"
    assert script.previewed == 1
    # the pasted code was queued for the profile's game and tested
    item = ctx.queue.find_code("NEWC0DE12345", stored.game_key())
    assert item is not None and item.game == "新遊戲"
    assert script.started == [[item.id]]
    assert not page.is_dirty()  # every step was saved


def test_cancel_keeps_what_was_set_up(page: ProfilesPage, monkeypatch: pytest.MonkeyPatch) -> None:
    pid = _new_blank(page)
    script = Script(["pick", "cancel"])
    script.install(monkeypatch, window(31, "game.exe", "My Game"))
    assert pw.SetupWizard(page, pid).run() is False
    stored = page.ctx.profiles.get(pid)
    assert stored.target.exe == "game.exe" and stored.steps[1].params.point is not None
    assert stored.missing_setup() == [(4, "region")]  # the checklist remains
    assert script.started == []


def test_cancel_at_the_target_stops_at_once(page: ProfilesPage, monkeypatch: pytest.MonkeyPatch) -> None:
    pid = _new_blank(page)
    script = Script(["pick"])
    script.install(monkeypatch, None)
    assert pw.SetupWizard(page, pid).run() is False
    assert script.asked == [] and page.ctx.profiles.get(pid).target.is_empty()


def test_skip_and_a_picker_error_asks_again(page: ProfilesPage, monkeypatch: pytest.MonkeyPatch) -> None:
    pid = _new_blank(page)
    script = Script(["skip", "pick", "pick"], close="none", test=None)
    script.install(monkeypatch, window(31, "game.exe", "My Game"))
    errors = iter([(None, "這個範圍不在目標視窗的內容區內"), (record_region(CLIENT, 300, 200, 700, 300), "")])
    monkeypatch.setattr(pw.SetupWizard, "pick_position", lambda self, item: next(errors))
    dialogs = patch_dialogs(monkeypatch)
    assert pw.SetupWizard(page, pid).run() is True
    assert script.asked == ["1.point", "4.region", "4.region"]
    assert dialogs.messages and "不在目標視窗" in dialogs.messages[0][1]
    stored = page.ctx.profiles.get(pid)
    assert stored.steps[1].params.point is None and stored.steps[4].params.region is not None
    assert pw.find_close_step(stored) == (-1, pw.CLOSE_NONE)


@pytest.mark.parametrize("choice", [pw.CLOSE_OK, pw.CLOSE_ESC, pw.CLOSE_NONE])
def test_close_choice_replaces_inserts_or_removes_one_step(choice: str, demo_ctx: Any) -> None:
    prof = blank_profile(demo_ctx)
    esc = make_step(StepType.KEY)
    esc.params.keys = "Esc"
    prof.steps.append(esc)
    pw.apply_close_choice(prof, choice)
    idx, current = pw.find_close_step(prof)
    assert current == choice
    if choice == pw.CLOSE_OK:
        p = prof.steps[idx].params
        assert isinstance(p, ClickTextParams) and p.text == "確定|OK" and p.on_not_found is TimeoutAction.CONTINUE
        assert len(prof.steps) == 6
    elif choice == pw.CLOSE_NONE:
        assert len(prof.steps) == 5
    pw.apply_close_choice(prof, choice)  # idempotent
    assert pw.find_close_step(prof)[1] == choice


def test_realign_repicks_every_recorded_position(page: ProfilesPage, monkeypatch: pytest.MonkeyPatch) -> None:
    from autopress.win32 import windows

    ctx = page.ctx
    prof = ctx.active_profile()
    items = pw.position_items(prof, realign=True)
    assert [(i.step_index, i.field) for i in items] == [(1, "point"), (3, "region"), (4, "region")]
    assert pw.position_items(prof, realign=False) == []  # nothing missing
    info = window(31, "chrome.exe", "兌換 - Google Chrome")
    monkeypatch.setattr(windows, "find_window", lambda match: info)  # target found: no picker
    script = Script(["pick", "skip", "pick"], close="ok", test=None)
    script.install(monkeypatch, None)
    old = ctx.profiles.get(prof.id)
    assert pw.SetupWizard(page, prof.id, realign=True).run() is True
    stored = ctx.profiles.get(prof.id)
    assert script.picked == ["1.point", "4.region"]
    assert stored.steps[3].params.region == old.steps[3].params.region  # kept
    assert stored.steps[1].params.point.dx == 640
    assert stored.target.exe == "chrome.exe"


def test_wizard_asks_for_the_target_again_when_realigning_a_lost_window(page: ProfilesPage,
                                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    from autopress.win32 import windows

    monkeypatch.setattr(windows, "find_window", lambda match: None)
    script = Script(["skip", "skip", "skip"], close=None)
    script.install(monkeypatch, window(40, "chrome.exe", "新的兌換頁 - Google Chrome"))
    prof = page.ctx.active_profile()
    assert pw.SetupWizard(page, prof.id, realign=True).run() is False  # close choice cancelled
    assert page.ctx.profiles.get(prof.id).target.title == "新的兌換頁"


def test_test_one_with_a_queued_code_uses_the_run_flow(page: ProfilesPage, monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = page.ctx
    prof = ctx.active_profile()
    first = ctx.queue.runnable(game_key=prof.game_key())[0]
    wiz = pw.SetupWizard(page, prof.id)
    monkeypatch.setattr(pw.SetupWizard, "ask_test", lambda self: ("queue", first.id))
    begun: list[tuple[Any, ...]] = []
    flow = page.run_flow()
    monkeypatch.setattr(flow, "begin", lambda p, *a, **k: begun.append((p.id, k.get("mode"), k.get("code_ids"))) or True)
    assert wiz._step_test() is True
    assert begun == [(prof.id, PlanMode.TEST_ONE, [first.id])]


def test_paste_box_rejects_a_code_that_cannot_run(page: ProfilesPage, monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = page.ctx
    prof = ctx.active_profile()
    done = next(i for i in ctx.queue.items() if i.status.value == "success")
    dialogs = patch_dialogs(monkeypatch)
    wiz = pw.SetupWizard(page, prof.id)
    assert wiz._queue_code(done.code) is None
    assert dialogs.messages and "無法加入佇列" in dialogs.messages[0][1]


def test_start_wizard_from_the_page_and_the_dialogs_build(page: ProfilesPage, monkeypatch: pytest.MonkeyPatch,
                                                         qtbot: Any) -> None:
    runs: list[tuple[str, bool]] = []
    monkeypatch.setattr(pw.SetupWizard, "run", lambda self: runs.append((self.profile_id, self.realign)) or True)
    pid = page.working_profile().id
    page.start_wizard(pid, realign=True)
    assert runs == [(pid, True)]
    item = pw.PositionItem(1, "point", "point", "點一下序號輸入框", False)
    for dlg in (pw._PositionDialog(1, 2, item, False, page), pw._CloseDialog(pw.CLOSE_ESC, page),
                pw._KeywordDialog("兌換", page), pw._TestDialog(page.working_profile(), "", page)):
        qtbot.addWidget(dlg)
    close = pw._CloseDialog(pw.CLOSE_ESC, page)
    qtbot.addWidget(close)
    assert close.choice() == pw.CLOSE_ESC
    kw = pw._KeywordDialog("兌換", page)
    qtbot.addWidget(kw)
    kw.edit.setText("  ")
    assert not kw.ok_btn.isEnabled()  # a browser keyword can be shortened, not emptied
    test = pw._TestDialog(page.working_profile(), "", page)
    qtbot.addWidget(test)
    assert not test.ok_btn.isEnabled()
    test.edit.setText("ABCD-1234")
    assert test.ok_btn.isEnabled() and test.code() == "ABCD-1234"
    assert isinstance(page.working_profile().target, TargetMatch)
