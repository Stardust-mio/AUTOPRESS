"""Integration of the UI polish (orchestrator): the "needed outside my files" items the seven fix
groups handed over, each with a test that fails on the code before it. Offscreen only.

* a decision on an unknown result is counted as the user's choice everywhere: the run summary
  (worker counters), RunSession re-emits code_finished with the updated record, and the live
  chips of the Run page and the mini bar keep one result per code (repair round 1: also when the run
  is stopped right after the mark, and for a 冷卻中 choice; a hand-marked 測試一筆 is not a pass)
* the Codes page's profile combo is locked during a run, like the Run page's setup card
* the Profiles editor never scrolls sideways, also in English at the smallest window (keywords
  editor fuzzy line wraps, the format combo shrinks, the header buttons sit 8 px apart)
* the status bar looks the target window up again when a page is shown (U6 remainder)
* the wizard's position dialog says the step type once and keeps 「Esc 可取消。」 on its own line
* texts that quote the 「以系統管理員身分重新啟動」 button quote its real label; no 試跑 left
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from autopress import i18n
from autopress.models import Attention, CodeStatus, PauseReason, StopReason
from autopress.runner import messages
from autopress.runner.engine import RunSession
from tests.fakes import FakeCodeQueue, FakeHistoryStore, FakeOcrService, skip_if_stub
from tests.runner_helpers import (
    FakeBackend,
    FakeWorld,
    SyncRun,
    fast_runner,
    fast_settings,
    make_plan,
    make_profile,
    runner_standins,
)

_ = (runner_standins, fast_runner)
LOCK_TIP = "執行中無法切換設定檔"


def _unknown_world() -> FakeWorld:
    """Every submit shows a message that matches no keyword: an unknown result (需確認)."""
    world = FakeWorld(valid={"AAAA-1111", "BBBB-2222", "CCCC-3333"})
    world.hooks["submit"] = lambda w: setattr(w, "pending", (time.monotonic(), "獎勵已入帳", "x"))
    return world


# ============================================================================ decisions are counted


@pytest.mark.usefixtures("runner_standins", "fast_runner")
def test_the_summary_counts_the_result_picked_in_a_decision() -> None:
    """Before: the worker counted 需確認 at code_done and never moved it, so the summary and the
    finish toast said 需確認 3 while the history said 成功 3."""
    world = _unknown_world()
    prof = make_profile(world)

    def resolve(run: SyncRun, reason: str) -> None:
        if reason == PauseReason.UNKNOWN_RESULT.value:
            run.shared.set_resolved(run.of("code_started")[-1][0], CodeStatus.SUCCESS)
        run.control.request_resume()

    r = SyncRun(make_plan(prof, ["AAAA-1111", "BBBB-2222", "CCCC-3333"]), world, on_pause=resolve).run()
    assert r.summary.stop_reason is StopReason.COMPLETED
    assert r.summary.counts == {CodeStatus.SUCCESS: 3}
    assert r.summary.done == 3


@pytest.mark.usefixtures("runner_standins", "fast_runner")
def test_an_unresolved_decision_stays_counted_as_needs_review() -> None:
    world = _unknown_world()
    prof = make_profile(world)
    prof.policy.stop_after_failures = 0
    r = SyncRun(make_plan(prof, ["AAAA-1111", "BBBB-2222"]), world).run()  # resumed without a choice
    assert r.summary.counts == {CodeStatus.REVIEW: 2}


@pytest.mark.usefixtures("runner_standins", "fast_runner")
def test_resolve_attention_during_a_run_emits_code_finished_with_the_new_result(qtbot: Any) -> None:
    world = _unknown_world()
    queue, history = FakeCodeQueue(), FakeHistoryStore()
    session = RunSession(queue, history, FakeOcrService(state="ready"), backend_factory=lambda: FakeBackend(world))
    profile = make_profile(world)
    (code_id,) = queue.add_codes(["AAAA-1111"], game_key=profile.game_key(), game=profile.game).added
    finished: list[tuple[str, CodeStatus]] = []
    session.code_finished.connect(lambda cid, rec: finished.append((cid, rec.status)))
    try:
        with qtbot.waitSignal(session.attention, timeout=10000):
            session.start(session.build_plan(profile, fast_settings()))
        assert finished == [(code_id, CodeStatus.REVIEW)]
        session.resolve_attention(code_id, CodeStatus.SUCCESS, "人工確認")
        assert finished == [(code_id, CodeStatus.REVIEW), (code_id, CodeStatus.SUCCESS)]
        assert history.records()[-1].status is CodeStatus.SUCCESS and len(history.records()) == 1
        with qtbot.waitSignal(session.finished, timeout=10000) as blocker:
            session.resume()
        assert blocker.args[0].counts == {CodeStatus.SUCCESS: 1}
        # after the run: the record changes, nothing is emitted (no live counts to correct)
        session.resolve_attention(code_id, CodeStatus.USED)
        assert len(finished) == 2 and history.records()[-1].status is CodeStatus.USED
    finally:
        session.shutdown(2.0)


def _decision(session: Any, code_id: str) -> None:
    """One code needs review and the run pauses on its decision (FakeRunSession helpers)."""
    session.begin_code(code_id, 0)
    session.finish_code(code_id, CodeStatus.REVIEW, "獎勵已入帳")
    session.pause_for(Attention(kind=PauseReason.UNKNOWN_RESULT, code_id=code_id, ocr_text="獎勵已入帳",
                                message=messages.unknown_result("獎勵已入帳")))


def test_run_page_chips_follow_the_result_picked_in_a_decision(demo_ctx: Any, qtbot: Any) -> None:
    from autopress.ui.run_page import RunPage
    from tests.data.ui_run.g7_helpers import attach_main_window

    attach_main_window(demo_ctx)
    page = RunPage(demo_ctx)
    qtbot.addWidget(page)
    s = demo_ctx.session
    plan = s.build_plan(demo_ctx.active_profile(), demo_ctx.settings)
    s.start(plan)
    first, second = plan.items[0].code_id, plan.items[1].code_id
    s.simulate_code(first, CodeStatus.SUCCESS, "兌換成功")
    _decision(s, second)
    assert page.running.counts.counts == {CodeStatus.SUCCESS: 1, CodeStatus.REVIEW: 1}
    page._mark(CodeStatus.USED)  # 標記為 已使用
    assert page.running.counts.counts == {CodeStatus.SUCCESS: 1, CodeStatus.USED: 1}  # still one per code
    assert demo_ctx.queue.get(second).status is CodeStatus.USED
    assert page.running.step.text() == "結果：已使用"


def test_minibar_chips_follow_the_result_picked_in_a_decision(demo_ctx: Any, qtbot: Any,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    from autopress.ui import run_flow as rf
    from autopress.ui import run_sheet
    from tests.data.ui_run.g7_helpers import attach_main_window, patch_dialogs

    attach_main_window(demo_ctx)
    demo_ctx.settings.countdown_s = demo_ctx.settings.resume_countdown_s = 0
    monkeypatch.setattr(run_sheet, "show_preflight_sheet", lambda ctx, report, plan, parent: "start")
    patch_dialogs(monkeypatch)
    flow = rf.RunFlow(demo_ctx)
    assert flow.begin(demo_ctx.active_profile()) is True
    s = demo_ctx.session
    items = s.plan.items
    s.simulate_code(items[0].code_id, CodeStatus.SUCCESS, "兌換成功")
    _decision(s, items[1].code_id)
    assert flow.minibar.counts == {CodeStatus.SUCCESS: 1, CodeStatus.REVIEW: 1}
    s.resolve_attention(items[1].code_id, CodeStatus.SUCCESS, "人工確認")
    assert flow.minibar.counts == {CodeStatus.SUCCESS: 2}
    assert not flow.minibar.chips[CodeStatus.REVIEW].isVisibleTo(flow.minibar)
    assert flow.minibar.chips[CodeStatus.SUCCESS].text == f"{CodeStatus.SUCCESS.label()} 2"
    s.stop()


@pytest.mark.usefixtures("runner_standins", "fast_runner")
def test_a_result_marked_and_then_stopped_is_counted_as_the_choice(qtbot: Any) -> None:
    """Repair round 1 (F1): Stop during the decision raises StopRequested inside the pause, so the
    count move after it never ran - the live chips said 成功 and the summary / toast 需確認."""
    world = _unknown_world()
    queue, history = FakeCodeQueue(), FakeHistoryStore()
    session = RunSession(queue, history, FakeOcrService(state="ready"), backend_factory=lambda: FakeBackend(world))
    profile = make_profile(world)
    (code_id,) = queue.add_codes(["AAAA-1111"], game_key=profile.game_key(), game=profile.game).added
    try:
        with qtbot.waitSignal(session.attention, timeout=10000):
            session.start(session.build_plan(profile, fast_settings()))
        session.resolve_attention(code_id, CodeStatus.SUCCESS, "人工確認")
        with qtbot.waitSignal(session.finished, timeout=10000) as blocker:
            session.stop()
        assert blocker.args[0].stop_reason is StopReason.USER
        assert blocker.args[0].counts == {CodeStatus.SUCCESS: 1}
        assert history.records()[-1].status is CodeStatus.SUCCESS and queue.get(code_id).status is CodeStatus.SUCCESS
    finally:
        session.shutdown(2.0)


@pytest.mark.usefixtures("runner_standins", "fast_runner")
def test_a_decision_for_a_rate_limit_keyword_is_counted_as_cooldown() -> None:
    world = _unknown_world()
    prof = make_profile(world)

    def resolve(run: SyncRun, reason: str) -> None:
        if reason == PauseReason.UNKNOWN_RESULT.value:
            run.shared.set_resolved(run.of("code_started")[-1][0], CodeStatus.COOLDOWN)
        run.control.request_resume()

    r = SyncRun(make_plan(prof, ["AAAA-1111"]), world, on_pause=resolve).run()
    assert r.summary.counts == {CodeStatus.COOLDOWN: 1}


def test_a_cooldown_decision_is_one_result_on_the_run_page_and_the_minibar(demo_ctx: Any, qtbot: Any,
                                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    """Repair round 1 (F3): 加入關鍵字 with 操作過於頻繁 marks the code 冷卻中. The Run page kept
    需確認, the mini bar dropped the code (chips 2 against ring 3), the summary said 冷卻中."""
    from autopress.ui import run_flow as rf
    from autopress.ui import run_sheet
    from autopress.ui.run_page import RunPage
    from tests.data.ui_run.g7_helpers import attach_main_window, patch_dialogs

    attach_main_window(demo_ctx)
    demo_ctx.settings.countdown_s = demo_ctx.settings.resume_countdown_s = 0
    monkeypatch.setattr(run_sheet, "show_preflight_sheet", lambda ctx, report, plan, parent: "start")
    patch_dialogs(monkeypatch)
    page = RunPage(demo_ctx)
    qtbot.addWidget(page)
    flow = rf.RunFlow(demo_ctx)
    assert flow.begin(demo_ctx.active_profile()) is True
    s = demo_ctx.session
    items = s.plan.items
    s.simulate_code(items[0].code_id, CodeStatus.SUCCESS, "兌換成功")
    _decision(s, items[1].code_id)
    page._mark(CodeStatus.COOLDOWN)  # what _add_keyword does for a RATE_LIMITED keyword
    want = {CodeStatus.SUCCESS: 1, CodeStatus.COOLDOWN: 1}
    assert page.running.counts.counts == want and flow.minibar.counts == want
    s.simulate_code(items[2].code_id, CodeStatus.SUCCESS, "兌換成功")  # the next code keeps it
    want = {CodeStatus.SUCCESS: 2, CodeStatus.COOLDOWN: 1}
    assert page.running.counts.counts == want and flow.minibar.counts == want
    s.stop()


def test_a_retried_attempt_is_still_not_a_result(demo_ctx: Any, qtbot: Any) -> None:
    """Control for the change above: a COOLDOWN / PENDING attempt of a code WITHOUT a result yet
    (rate-limited, interrupted before submitting) is retried and adds no chip."""
    from autopress.ui.run_page import RunPage
    from tests.data.ui_run.g7_helpers import attach_main_window

    attach_main_window(demo_ctx)
    page = RunPage(demo_ctx)
    qtbot.addWidget(page)
    s = demo_ctx.session
    plan = s.build_plan(demo_ctx.active_profile(), demo_ctx.settings)
    s.start(plan)
    cid = plan.items[0].code_id
    s.begin_code(cid, 0)
    s.finish_code(cid, CodeStatus.COOLDOWN, "操作過於頻繁")
    assert page.running.counts.counts == {}
    s.finish_code(cid, CodeStatus.SUCCESS, "兌換成功")
    assert page.running.counts.counts == {CodeStatus.SUCCESS: 1}
    s.stop()


def test_test_one_marked_by_hand_is_not_a_passed_test(demo_ctx: Any, qtbot: Any,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    """Repair round 1 (F2): the re-emitted code_finished carried the hand-picked 成功, so a 測試一筆
    whose result could NOT be read cleared the pre-flight 'never passed a test' warning."""
    from autopress.models import PlanMode
    from autopress.ui import run_flow as rf
    from autopress.ui import run_sheet
    from tests.data.ui_run.g7_helpers import attach_main_window, patch_dialogs

    attach_main_window(demo_ctx)
    demo_ctx.settings.countdown_s = demo_ctx.settings.resume_countdown_s = 0
    monkeypatch.setattr(run_sheet, "show_preflight_sheet", lambda ctx, report, plan, parent: "start")
    patch_dialogs(monkeypatch)
    profile = demo_ctx.active_profile()
    profile.last_test_ok_at = ""
    demo_ctx.profiles.save(profile, touch=False)
    ids = [item.id for item in demo_ctx.queue.runnable(game_key=profile.game_key())][:3]
    assert len(ids) == 3
    for cid, marked in zip(ids, (CodeStatus.SUCCESS, CodeStatus.USED)):
        flow = rf.RunFlow(demo_ctx)
        assert flow.begin(demo_ctx.profiles.get(profile.id), mode=PlanMode.TEST_ONE, code_ids=[cid]) is True
        _decision(demo_ctx.session, cid)
        demo_ctx.session.resolve_attention(cid, marked, "人工確認")
        assert flow.minibar.counts == {marked: 1}  # the chips follow the choice
        demo_ctx.session.stop(StopReason.COMPLETED)
        assert demo_ctx.profiles.get(profile.id).last_test_ok_at == ""
    # control: a result the runner read itself still counts
    flow = rf.RunFlow(demo_ctx)
    assert flow.begin(demo_ctx.profiles.get(profile.id), mode=PlanMode.TEST_ONE, code_ids=[ids[2]]) is True
    demo_ctx.session.simulate_code(ids[2], CodeStatus.SUCCESS, "兌換成功")
    demo_ctx.session.stop(StopReason.COMPLETED)
    assert demo_ctx.profiles.get(profile.id).last_test_ok_at != ""


def test_minibar_set_counts_replaces_every_chip(demo_ctx: Any, qtbot: Any) -> None:
    from autopress.ui.minibar import MiniBar

    bar = MiniBar(demo_ctx)
    qtbot.addWidget(bar)
    bar.add_result(CodeStatus.SUCCESS)
    bar.add_result(CodeStatus.REVIEW)
    bar.set_counts({CodeStatus.SUCCESS: 2, CodeStatus.REVIEW: 0})
    assert bar.counts == {CodeStatus.SUCCESS: 2}
    assert bar.chips[CodeStatus.SUCCESS].isVisibleTo(bar) and not bar.chips[CodeStatus.REVIEW].isVisibleTo(bar)


# ============================================================================ Codes page combo lock


def test_codes_page_profile_combo_is_locked_during_a_run(demo_ctx: Any, qtbot: Any) -> None:
    skip_if_stub("autopress.codes.queue", "autopress.codes.history")
    from autopress.ui.codes_page import CodesPage

    page = CodesPage(demo_ctx)
    qtbot.addWidget(page)
    combo = page._profile_combo
    assert combo.isEnabled() and combo.toolTip() == ""
    s = demo_ctx.session
    s.start(s.build_plan(demo_ctx.active_profile(), demo_ctx.settings))
    assert not combo.isEnabled() and combo.toolTip() == LOCK_TIP
    demo_ctx.signals.profiles_changed.emit()  # a reload during the run keeps the lock
    assert not combo.isEnabled() and combo.toolTip() == LOCK_TIP
    s.pause()
    assert not combo.isEnabled()
    s.stop()
    assert combo.isEnabled() and combo.toolTip() == ""
    i18n.set_language("en")
    s.start(s.build_plan(demo_ctx.active_profile(), demo_ctx.settings))
    assert combo.toolTip() == "You cannot switch profiles during a run"
    s.stop()


# ============================================================================ Profiles editor width


@pytest.mark.parametrize("size", [(1060, 740), (880, 640)])  # default window, smallest window (1100 x 700)
def test_profiles_editor_never_scrolls_sideways(demo_ctx: Any, qtbot: Any, size: tuple[int, int]) -> None:
    """The whole editor (header row, every card incl. the keywords editor) fits the viewport, so
    the horizontal bar ("as needed", repair round 1) never shows. Offscreen fonts are not the real ones, so pixel widths are
    checked in zh-TW only; English was measured with the real fonts on the windows platform
    (hidden widgets, 100 / 125 / 150 %, 0 px overflow) and is pinned here by the three changes that
    made it fit: the keywords editor's fuzzy line wraps, the format combo may shrink, the header
    buttons sit 8 px apart (before: 633 px keywords card, 498 px format card, 533 px header row
    against a 536 px viewport in English)."""
    from PyQt6.QtWidgets import QComboBox

    from autopress.ui import theme
    from autopress.ui.profiles_page import ProfilesPage

    page = ProfilesPage(demo_ctx)
    qtbot.addWidget(page)
    page.resize(*size)
    page.show()
    QApplication.processEvents()
    sa = page.editor_page
    assert sa.horizontalScrollBarPolicy() is Qt.ScrollBarPolicy.ScrollBarAsNeeded  # overflow scrolls, never clips
    assert sa.widget().minimumSizeHint().width() <= sa.viewport().width()
    assert not sa.horizontalScrollBar().isVisible()
    assert page.keywords.fuzzy_label.wordWrap()
    preset = page.format_card.preset
    assert preset.sizeAdjustPolicy() is QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
    longest = max((preset.itemText(i) for i in range(preset.count())), key=preset.fontMetrics().horizontalAdvance)
    assert preset.minimumSizeHint().width() < preset.fontMetrics().horizontalAdvance(longest)  # may shrink
    head = sa.widget().layout().itemAt(0).layout()
    assert head.indexOf(page.save_btn) >= 0 and head.spacing() == theme.SP[2]


# ============================================================================ status bar target (U6 remainder)


def test_status_bar_target_is_looked_up_again_when_a_page_is_shown(demo_ctx: Any, qtbot: Any,
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    """The Run page looks the window up when it is shown; the status bar now does too, so the two
    never disagree for up to 2 s (its poll interval) after the redeem page was closed."""
    from autopress.models import WindowInfo
    from autopress.ui import main_window as mw_mod
    from autopress.win32 import windows

    monkeypatch.setattr(mw_mod, "_request_quit", lambda: None)
    found: dict[str, Any] = {"info": WindowInfo(hwnd=5, title="示範遊戲 兌換頁 - Google Chrome",
                                                exe_path="C:/Program Files/Google/Chrome/Application/chrome.exe")}
    monkeypatch.setattr(windows, "find_window", lambda match: found["info"])
    win = mw_mod.MainWindow(demo_ctx)
    qtbot.addWidget(win)
    win.show()
    win._refresh_target()
    assert win.status_text("target") == "已找到目標視窗：示範遊戲 兌換頁 - Google Chrome"
    found["info"] = None  # the redeem page was closed
    win.navigate("run")
    assert win.status_text("target") == "找不到目標視窗"  # at once, not at the next poll


# ============================================================================ wizard position dialog


def test_wizard_position_dialog_says_the_step_type_once_and_keeps_esc_on_its_line(qtbot: Any) -> None:
    """A step without its own title shows its type as the heading, so the step line does not repeat
    it (before: 「點擊位置」 / 「設定檔的第 2 步：點擊位置」); 「Esc 可取消。」 has a line of its own (before it
    wrapped as a lone 「消。」 at the dialog's width)."""
    from PyQt6.QtWidgets import QLabel

    from autopress.ui import profiles_wizard as pw

    untitled = pw._PositionDialog(1, 4, pw.PositionItem(1, "point", "point", "點擊位置", False, "點擊位置"), False, None,
                                  progress=(1, 4))
    qtbot.addWidget(untitled)
    assert untitled.heading.text() == "點擊位置" and untitled.step_line.text() == "設定檔的第 2 步"
    titled = pw._PositionDialog(1, 4, pw.PositionItem(1, "point", "point", "點一下序號輸入框", False, "點擊位置"), False,
                                None)
    qtbot.addWidget(titled)
    assert titled.step_line.text() == "設定檔的第 2 步：點擊位置"
    for dlg, last in ((untitled, "Esc 可取消。"),
                      (pw._PositionDialog(1, 1, pw.PositionItem(4, "region", "region", "框出結果範圍", False), True, None),
                       "Esc 可取消。")):
        qtbot.addWidget(dlg)
        how = next(lb.text() for lb in dlg.findChildren(QLabel) if "暫時定格" in lb.text())
        assert how.splitlines()[-1] == last and len(how.splitlines()) == 2


# ============================================================================ texts


def test_elevated_texts_quote_the_restart_button() -> None:
    from autopress.ui import help_content, run_actions, window_picker

    button = run_actions.action_label("restart_admin")
    assert button == "以系統管理員身分重新啟動"
    for text in (messages.pf_target_elevated(), window_picker.elevated_text()):
        assert f"「{button}」" in text and "重新啟動 AutoPress」" not in text
    help_texts = [str(t) for sec in help_content.SECTIONS for t in _texts(sec)]
    assert any(f"「{button}」" in t for t in help_texts)
    assert not any("重新啟動 AutoPress」" in t for t in help_texts)
    i18n.set_language("en")
    button = run_actions.action_label("restart_admin")
    assert f'"{button}"' in messages.pf_target_elevated() and f'"{button}"' in window_picker.elevated_text()


def _texts(node: Any) -> list[Any]:
    """Every i18n.T / str inside a help_content section (nested tuples, lists and dicts)."""
    out: list[Any] = []
    if isinstance(node, dict):
        for v in node.values():
            out += _texts(v)
    elif isinstance(node, (list, tuple)):
        for v in node:
            out += _texts(v)
    elif node is not None and not isinstance(node, (int, float, bool)):
        out.append(node)
    return out


def test_no_dry_run_wording_left_in_messages() -> None:
    assert messages.wait_skipped() == "測試時不等待"  # the step tests are called 測試 everywhere else
