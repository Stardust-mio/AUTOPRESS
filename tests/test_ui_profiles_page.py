# OWNED BY G7
"""Profiles page (SPEC 6.4.2): CRUD, dirty prompt (Save / Discard / Cancel), newer-version
warning, template creation, game combo + near-duplicate warning + moving queued codes on a
rename, import flow (read_file -> action_lines card -> checkbox -> import_profile; target
always empty), export title keyword, setup checklist, real step test countdown + stop."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from autopress.models import (
    KeyParams,
    Profile,
    StepType,
    TargetMatch,
    TemplateInfo,
    TitleMatch,
    make_step,
    to_dict,
)
from autopress.ui import profiles_actions, profiles_dialogs
from autopress.ui.profiles_editor import similar_game
from autopress.ui.profiles_page import ProfilesPage
from tests.data.ui_run.g7_helpers import attach_main_window, patch_dialogs, patch_target, window


@pytest.fixture
def page(demo_ctx: Any, qtbot: Any, monkeypatch: pytest.MonkeyPatch) -> ProfilesPage:
    attach_main_window(demo_ctx)
    monkeypatch.setattr(ProfilesPage, "start_wizard", lambda self, pid, realign=False: self.wizard_calls.append((pid, realign)))
    ProfilesPage.wizard_calls = []
    p = ProfilesPage(demo_ctx)
    p.wizard_calls = []
    qtbot.addWidget(p)
    return p


def test_opens_the_active_profile(page: ProfilesPage) -> None:
    ctx = page.ctx
    assert page.working_profile().id == ctx.settings.active_profile_id
    assert page.title.text() == "示範：網頁兌換" and not page.is_dirty()
    assert page.stack.currentWidget() is page.editor_page
    assert len(page.step_list.steps()) == 6 and page.step_editor.index() == 0


def test_edit_save_and_dirty_marker(page: ProfilesPage) -> None:
    page.basics.name.setText("我的兌換")
    assert page.is_dirty() and not page.dirty_label.isHidden()
    assert page.save_profile()
    assert page.ctx.profiles.get(page.working_profile().id).name == "我的兌換"
    assert not page.is_dirty() and page.dirty_label.isHidden()


@pytest.mark.parametrize(("answer", "switched", "saved_name"), [
    ("cancel", False, "示範：網頁兌換"), ("discard", True, "示範：網頁兌換"), ("save", True, "改過的名字")])
def test_dirty_prompt_on_leaving(page: ProfilesPage, monkeypatch: pytest.MonkeyPatch, answer: str, switched: bool,
                                 saved_name: str) -> None:
    ctx = page.ctx
    first = page.working_profile().id
    other = Profile(name="另一個", game="別的遊戲")
    ctx.profiles.save(other)
    page.refresh_list()
    asked: list[str] = []
    monkeypatch.setattr(profiles_dialogs, "ask_save_changes", lambda parent, name: asked.append(name) or answer)
    page.basics.name.setText("改過的名字")
    page.open_profile(other.id)
    assert asked == ["改過的名字"]
    assert (page.working_profile().id == other.id) is switched
    assert ctx.profiles.get(first).name == saved_name
    if not switched:
        assert page.is_dirty() and page.working_profile().name == "改過的名字"


def test_newer_version_warning_before_saving(page: ProfilesPage, monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = page.ctx
    data = to_dict(Profile(name="新版本的設定檔"))
    data["schema_version"] = 99
    data["future_field"] = {"x": 1}
    pid = data["id"]
    ctx.profiles.path_for(pid).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    page.refresh_list()
    page.open_profile(pid)
    assert page.newer_banner.isVisibleTo(page) and "較新版本" in page.newer_banner.text()
    dialogs = patch_dialogs(monkeypatch, answers=[False])
    page.basics.name.setText("改名")
    assert page.save_profile() is False
    assert "較新版本" in dialogs.confirms[0][1]
    assert json.loads(ctx.profiles.path_for(pid).read_text(encoding="utf-8"))["schema_version"] == 99
    dialogs.answers = [True]
    assert page.save_profile() is True
    assert json.loads(ctx.profiles.path_for(pid).read_text(encoding="utf-8"))["schema_version"] == 1


def test_duplicate_and_delete(page: ProfilesPage, monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = page.ctx
    original = page.working_profile().id
    page.duplicate_profile()
    copy = page.working_profile()
    assert copy.id != original and copy.name == "示範：網頁兌換（副本）"
    assert len(page.profile_ids()) == 2
    patch_dialogs(monkeypatch, answers=[True])
    page.open_profile(original)
    page.delete_profile()
    assert not ctx.profiles.exists(original) and ctx.settings.active_profile_id == ""
    assert page.working_profile().id == copy.id


def test_gallery_when_there_are_no_profiles(demo_ctx: Any, qtbot: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from autopress import storage

    for p in demo_ctx.profiles.list():
        demo_ctx.profiles.delete(p.id)
    demo_ctx.settings.active_profile_id = ""
    tpl = Profile(name="web", template=TemplateInfo(key="web_generic", title_zh="網頁兌換（通用）", title_en="Web redeem"))
    tpl.steps = [make_step(StepType.TYPE_CODE)]
    monkeypatch.setattr(storage, "load_templates", lambda directory=None: [tpl])
    calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(ProfilesPage, "start_wizard", lambda self, pid, realign=False: calls.append((pid, realign)))
    page = ProfilesPage(demo_ctx)
    qtbot.addWidget(page)
    assert page.stack.currentWidget() is page.gallery_page and page.working_profile() is None
    page.gallery.buttons[0].click()  # 「使用這個範本」
    p = page.working_profile()
    assert p is not None and p.name == "網頁兌換（通用）" and p.template is None
    assert demo_ctx.settings.active_profile_id == p.id  # the first profile becomes active
    assert calls == [(p.id, False)]


def test_new_from_template_by_key_and_blank(page: ProfilesPage, monkeypatch: pytest.MonkeyPatch) -> None:
    from autopress import storage

    tpl = Profile(name="game", template=TemplateInfo(key="game_dialog", title_zh="遊戲內兌換視窗（通用）"))
    monkeypatch.setattr(storage, "load_templates", lambda directory=None: [tpl])
    page.new_from_template("game_dialog")
    assert page.working_profile().name == "遊戲內兌換視窗（通用）"
    assert page.wizard_calls[-1] == (page.working_profile().id, False)
    monkeypatch.setattr(profiles_dialogs, "choose_template", lambda templates, parent: (True, None))
    page.new_from_template()
    blank = page.working_profile()
    assert blank.name == "新的設定檔" and [s.type for s in blank.steps] == [
        StepType.FOCUS_WINDOW, StepType.CLICK_POINT, StepType.TYPE_CODE, StepType.KEY, StepType.OCR_CHECK]
    toasts: list[tuple[str, str]] = []
    page.ctx.signals.toast.connect(lambda kind, text: toasts.append((kind, text)))
    page.new_from_template("nope")
    assert toasts and toasts[-1][0] == "error"


def test_real_templates_load_into_the_gallery(page: ProfilesPage) -> None:
    from autopress import storage

    templates = storage.load_templates()
    gallery = profiles_dialogs.TemplateGallery(templates)
    assert len(gallery.buttons) == len(templates) + 1  # + 從空白開始


# ----------------------------------------------------------------------------- game


def test_similar_game_rule() -> None:
    known = ["Genshin Impact", "原神", "崩壞：星穹鐵道"]
    assert similar_game("Genshin Impact", known) is None  # exact
    assert similar_game("genshin  impact", known) == "Genshin Impact"  # same squash
    assert similar_game("Genshin Impakt", known) == "Genshin Impact"  # Levenshtein 1
    assert similar_game("原神 ", known) is None  # the same name with a stray space
    assert similar_game("原袖", known) == "原神"  # 1 edit on a short name
    assert similar_game("鳴潮", known) is None
    assert similar_game("", known) is None


def test_game_combo_lists_known_names_and_warns(page: ProfilesPage) -> None:
    ctx = page.ctx
    ctx.profiles.save(Profile(name="other", game="Genshin Impact"))
    page.basics.load(page.working_profile())
    names = [page.basics.game.itemText(i) for i in range(page.basics.game.count())]
    assert "Genshin Impact" in names  # from the other profile
    assert "示範遊戲" in names  # from the queue and the history of this game
    page.basics.game.setEditText("Genshin Impakt")
    assert page.basics.game_warning.isVisibleTo(page) and "Genshin Impact" in page.basics.game_warning.text()
    page.basics.game.setEditText("Genshin Impact")
    assert page.basics.game_warning.isHidden()


def test_renaming_the_game_offers_to_move_the_queued_codes(page: ProfilesPage, monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = page.ctx
    old_key = page.working_profile().game_key()
    before = [i.id for i in ctx.queue.items() if i.game_key == old_key]
    assert before
    dialogs = patch_dialogs(monkeypatch, answers=[True])
    page.basics.game.setEditText("新遊戲")
    assert page.save_profile()
    assert any("移到「新遊戲」" in text or "新遊戲" in text for _t, text in dialogs.confirms)
    new_key = page.working_profile().game_key()
    assert new_key == "game:新遊戲"
    assert all(ctx.queue.get(i).game_key == new_key for i in before if ctx.queue.get(i) is not None)


# ----------------------------------------------------------------------------- import / export


def _shared_file(tmp: Path) -> Path:
    p = Profile(name="分享的設定檔", game="原神", author="某人",
                target=TargetMatch(exe="explorer.exe", title="作者的帳號名稱", title_mode=TitleMatch.CONTAINS,
                                   allow_same_process=True))
    key = make_step(StepType.KEY)
    assert isinstance(key.params, KeyParams)
    key.params.keys = "Ctrl+L"  # risky: address bar
    text = make_step(StepType.TYPE_TEXT)
    text.params.text = "hello"  # risky: no {code}
    p.steps = [make_step(StepType.FOCUS_WINDOW), make_step(StepType.TYPE_CODE), key, text]
    p.last_test_ok_at = "2026-11-01T10:00:00+08:00"
    path = tmp / "分享.autopress.json"
    path.write_text(json.dumps(to_dict(p), ensure_ascii=False), encoding="utf-8")
    return path


def test_import_card_lists_actions_verbatim_and_needs_the_checkbox(page: ProfilesPage, tmp_path: Path, qtbot: Any) -> None:
    prof = page.ctx.profiles.read_file(_shared_file(tmp_path))
    dlg = profiles_dialogs.ImportCardDialog(prof, "分享.autopress.json")
    qtbot.addWidget(dlg)
    assert dlg.action_labels == prof.action_lines()
    risky = [text for text, r in dlg.action_labels if r]
    assert any("Ctrl+L" in t for t in risky) and any("hello" in t for t in risky)
    assert not dlg.import_btn.isEnabled()
    dlg.accept()
    assert dlg.result() == 0  # refused without the checkbox
    dlg.check.setChecked(True)
    assert dlg.import_btn.isEnabled()
    assert dlg.banner.text() == profiles_dialogs.import_warning_text()


def test_import_flow_never_keeps_the_authors_target(page: ProfilesPage, tmp_path: Path,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = page.ctx
    src = _shared_file(tmp_path)
    original = src.read_bytes()
    shown: list[Any] = []

    def fake_confirm(profile: Profile, name: str, parent: Any) -> bool:
        dlg = profiles_dialogs.ImportCardDialog(profile, name, parent)
        shown.append([t for t, _r in dlg.action_labels])
        dlg.check.setChecked(True)
        ok = dlg.import_btn.isEnabled()
        dlg.deleteLater()
        return ok

    monkeypatch.setattr(profiles_dialogs, "confirm_import", fake_confirm)
    page.import_profile_file(src)
    imported = page.working_profile()
    assert shown and imported.name == "分享的設定檔"
    assert imported.target.is_empty() and imported.target.allow_same_process is False
    assert imported.suggested_exe == ""  # explorer.exe is forbidden: not even suggested
    assert imported.last_test_ok_at == "" and ctx.profiles.exists(imported.id)
    assert page.wizard_calls == [(imported.id, False)]  # opens on the target picker
    assert src.read_bytes() == original  # the user's file is untouched


def test_import_cancel_saves_nothing_and_bad_files_toast(page: ProfilesPage, tmp_path: Path,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = page.ctx
    n = len(ctx.profiles.list())
    monkeypatch.setattr(profiles_dialogs, "confirm_import", lambda *a: False)
    page.import_profile_file(_shared_file(tmp_path))
    assert len(ctx.profiles.list()) == n and page.wizard_calls == []
    bad = tmp_path / "bad.autopress.json"
    bad.write_text("{not json", encoding="utf-8")
    toasts: list[tuple[str, str]] = []
    ctx.signals.toast.connect(lambda kind, text: toasts.append((kind, text)))
    page.import_profile_file(bad)
    assert toasts[-1] == ("error", "這不是 AutoPress 設定檔") and bad.exists()


@pytest.mark.parametrize("keyword", ["兌換", ""])
def test_export_writes_only_the_chosen_title_keyword(page: ProfilesPage, tmp_path: Path,
                                                     monkeypatch: pytest.MonkeyPatch, keyword: str) -> None:
    out = tmp_path / "out.autopress.json"
    page.working_profile().target.allow_same_process = True
    monkeypatch.setattr(profiles_dialogs, "ask_export_keyword", lambda profile, parent: keyword)
    monkeypatch.setattr(profiles_actions, "ask_save_path", lambda parent, name: str(out))
    page.export_profile()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["target"]["title"] == keyword and data["target"]["allow_same_process"] is False
    assert data["target"]["exe"] == "chrome.exe"


def test_export_cancelled_writes_nothing(page: ProfilesPage, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(profiles_dialogs, "ask_export_keyword", lambda profile, parent: None)
    monkeypatch.setattr(profiles_actions, "ask_save_path", lambda parent, name: pytest.fail("no file dialog"))
    page.export_profile()


# ----------------------------------------------------------------------------- checklist / target


def test_checklist_lists_missing_positions_with_set_up_buttons(page: ProfilesPage, monkeypatch: pytest.MonkeyPatch) -> None:
    from autopress.ui import overlays

    p = page.working_profile()
    p.steps[1].params.point = None
    page.replace_step(1, p.steps[1])
    assert page.checklist.isVisibleTo(page)
    from PyQt6.QtWidgets import QLabel

    texts = []
    for i in range(page.checklist_rows.count()):
        row = page.checklist_rows.itemAt(i).widget()
        texts.append(" ".join(lb.text() for lb in row.findChildren(QLabel)))
    assert any("第 2 步" in t and "點擊位置" in t for t in texts)
    patch_target(monkeypatch, window(9, "chrome.exe", "兌換 - Google Chrome", client=(100, 50, 1280, 720)))
    monkeypatch.setattr(overlays, "pick", lambda kind, **kw: overlays.PickResult(kind=kind, point=(740, 410)))
    page.pick_step_field(1, "point")
    assert page.working_profile().steps[1].params.point.dx == 640
    assert page.is_dirty()


def test_choose_window_sets_a_browser_title_keyword(page: ProfilesPage, monkeypatch: pytest.MonkeyPatch) -> None:
    from autopress.ui import window_picker

    monkeypatch.setattr(window_picker, "pick_target_window",
                        lambda *a, **k: window(3, "msedge.exe", "原神 兌換頁 - 個人 - Microsoft​ Edge"))
    page._pick_target()
    t = page.working_profile().target
    assert t.exe == "msedge.exe" and t.title.startswith("原神 兌換頁") and "Edge" not in t.title
    assert page.is_dirty()


# ----------------------------------------------------------------------------- step test


def test_dry_step_test_runs_test_step_without_input(page: ProfilesPage, monkeypatch: pytest.MonkeyPatch, qtbot: Any) -> None:
    patch_target(monkeypatch, window(9, "chrome.exe", "兌換 - Google Chrome"))
    page.step_list.set_current(3)  # click_text
    assert page.test_step(real=False)
    qtbot.waitUntil(lambda: "(fake) OK" in page.test_result.text(), timeout=2000)
    calls = [a for n, a in page.ctx.session.calls if n == "test_step"]
    assert calls[-1][1] == 3 and calls[-1][3] is True  # dry run
    assert page.ctx.hotkeys.registered() == {}


def test_real_step_test_countdown_then_stop(page: ProfilesPage, monkeypatch: pytest.MonkeyPatch, qtbot: Any) -> None:
    ctx = page.ctx
    ctx.settings.countdown_s = 3
    patch_target(monkeypatch, window(9, "chrome.exe", "兌換 - Google Chrome"))
    dialogs = patch_dialogs(monkeypatch, answers=[True, True])
    page.step_list.set_current(3)  # click_text 兌換: at the submit index
    assert page.ctx.active_profile().first_submit_index() == 3
    assert page.test_step(real=True)
    assert "會真的對目標視窗輸入" in dialogs.confirms[0][1]
    assert "這一步會送出測試序號「TEST-1234」" in dialogs.confirms[1][1]
    assert ctx.hotkeys.registered() == {"stop": "F9"} and page.stop_test_btn.isVisibleTo(page)
    assert page._steptest.countdown.is_running()
    ctx.hotkeys.triggered.emit("stop")  # F9 during the countdown
    assert not page._steptest.is_active() and ctx.hotkeys.registered() == {}
    assert not [a for n, a in ctx.session.calls if n == "test_step"]
    assert page.test_result.text() == "測試已取消。"


def test_real_step_test_after_the_countdown_and_stop_button(page: ProfilesPage, monkeypatch: pytest.MonkeyPatch,
                                                           qtbot: Any) -> None:
    ctx = page.ctx
    ctx.settings.countdown_s = 0
    patch_target(monkeypatch, window(9, "chrome.exe", "兌換 - Google Chrome"))
    patch_dialogs(monkeypatch, answers=[True])  # first real test only: the step does not submit
    page.step_list.set_current(1)  # click_point before the submit index
    finished: list[object] = []
    page._steptest.finished.connect(finished.append)
    assert page.test_step(real=True)
    qtbot.waitUntil(lambda: bool(finished), timeout=2000)
    calls = [a for n, a in ctx.session.calls if n == "test_step"]
    assert calls[-1][1] == 1 and calls[-1][3] is False  # real
    assert ctx.hotkeys.registered() == {}
    # the confirmation is asked only the first time
    dialogs = patch_dialogs(monkeypatch, default=False)
    assert page.test_step(real=True)
    assert dialogs.confirms == []
    page._steptest.stop()  # 停止測試 during the test -> session.stop
    qtbot.waitUntil(lambda: len(finished) == 2, timeout=2000)


def test_real_step_test_refused_when_not_confirmed(page: ProfilesPage, monkeypatch: pytest.MonkeyPatch) -> None:
    patch_target(monkeypatch, window(9, "chrome.exe", "兌換 - Google Chrome"))
    patch_dialogs(monkeypatch, answers=[False])
    page.step_list.set_current(1)
    assert page.test_step(real=True) is False
    assert page.ctx.hotkeys.registered() == {}


def test_step_test_without_a_target_explains(page: ProfilesPage, monkeypatch: pytest.MonkeyPatch) -> None:
    patch_target(monkeypatch, None)
    dialogs = patch_dialogs(monkeypatch)
    assert page.test_step(real=False) is False
    assert dialogs.messages and "找不到目標視窗" in dialogs.messages[0][1]


def test_drag_and_drop_accepts_profile_files(page: ProfilesPage, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from PyQt6.QtCore import QMimeData, QPointF, Qt, QUrl
    from PyQt6.QtGui import QDropEvent

    seen: list[Path] = []
    monkeypatch.setattr(ProfilesPage, "import_profile_file", lambda self, path: seen.append(Path(path)))
    src = _shared_file(tmp_path)
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(src))])
    ev = QDropEvent(QPointF(10, 10), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier)
    page.dropEvent(ev)
    assert seen == [src]


def test_target_card_shows_the_elevation_badge(page: ProfilesPage, monkeypatch: pytest.MonkeyPatch) -> None:
    from autopress.win32 import elevation

    patch_target(monkeypatch, window(9, "chrome.exe", "兌換 - Google Chrome"))
    monkeypatch.setattr(elevation, "input_permission", lambda hwnd: "blocked_elevated")
    page._refresh_target_status()
    assert page.target_card.status.text() == "已找到：兌換 - Google Chrome · 系統管理員"
    assert "系統管理員權限" in page.target_card.status.toolTip()


def test_import_card_lists_loosened_run_rules(qtbot: Any) -> None:
    """Gate G-02 (integration): the import card shows the run rules that differ from the
    defaults, with switched-off safety stops highlighted."""
    from autopress.models import Profile, StepType, make_step
    from autopress.ui.profiles_dialogs import ImportCardDialog

    prof = Profile(name="shared", suggested_exe="game.exe")
    prof.steps = [make_step(StepType.TYPE_CODE)]
    prof.policy.stop_after_failures = 0
    dlg = ImportCardDialog(prof, "share.autopress.json")
    qtbot.addWidget(dlg)
    assert dlg.policy_labels == prof.policy_lines() and len(dlg.policy_labels) == 1
    assert dlg.policy_labels[0][1]  # risky: the run never stops after failures
