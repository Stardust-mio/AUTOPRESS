# OWNED BY G7
"""Profiles page (SPEC section 6.4.2): profile list (new from template, import, export,
duplicate, delete) + editor (name, game - an editable combo of known game names with a
near-duplicate warning -, target window, code format, coordinate mode, setup checklist banner,
step list, step editor, run policy, keywords) with explicit 儲存, dirty marker and a Save /
Discard / Cancel prompt (and a warning before saving a profile from a newer version); template
gallery when there are no profiles (the empty list says 「還沒有設定檔」 and points to it); the four form
cards share one label column; buttons 預覽點位 (PreviewOverlay), 測試此步驟
(RunSession.test_step: dry run by default; a real test shows the countdown, registers the stop
hotkey, offers 停止測試 and warns when the step submits the sample code), 設為使用中.

Import (PX-01 / PX-17): ProfileStore.read_file (nothing saved, nothing renamed) -> a warning
card listing Profile.action_lines() verbatim (risky lines highlighted), the suggested exe, the
code format and 「只匯入你信任的人分享的設定檔」 -> the 匯入 button is enabled only after the
checkbox 「我看得懂這些動作」 -> ProfileStore.import_profile -> the setup wizard opens on 「選擇
目標視窗」 (an imported profile never has a target). Export asks for an optional title keyword
(ProfileStore.export_file(..., title_keyword)). Renaming the game offers to move the queued
codes of the old game (CodeQueue.assign_game).
"""

from __future__ import annotations

import logging
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import storage
from ..context import AppContext
from ..i18n import tr
from ..models import (
    PROFILE_SCHEMA_VERSION,
    IssueLevel,
    Profile,
    Step,
    TargetMatch,
    profile_from_dict,
    to_dict,
)
from . import profiles_dialogs as dialogs
from . import theme
from . import widgets as w
from .keywords_editor import KeywordsEditor
from .profiles_editor import BasicsCard, FormatCard, PolicyCard, TargetCard, align_form_labels, card
from .profiles_actions import ProfileActions, ask_open_path, ask_save_path, blank_profile
from .profiles_steptest import StepTestController
from .step_editor import StepEditor, StepListWidget

log = logging.getLogger(__name__)

STEP_LIST_W = 300  # step list width while the page has room
STEP_LIST_MIN_W = 240  # ... and in the smallest window


def _snapshot(p: Profile | None) -> dict[str, Any] | None:
    if p is None:
        return None
    d = to_dict(p)
    d.pop("updated_at", None)
    return d


class _ProfileRow(QWidget):
    def __init__(self, profile: Profile, active: bool) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(0)
        top = QHBoxLayout()
        top.addWidget(w.label(profile.name or tr("（未命名）", "(untitled)"), "body"), 1)
        self.badge = None
        if active:
            self.badge = w.label(tr("● 使用中", "● Active"), "success")  # green: in use (grey read as inactive, U35)
            top.addWidget(self.badge)
        lay.addLayout(top)
        sub = profile.game or tr("未指定遊戲", "No game")
        if profile.missing_setup() or profile.target.is_empty():
            sub += tr(" · 尚未設定完成", " · setup incomplete")
        lay.addWidget(w.label(sub, "muted"))


class ProfilesPage(ProfileActions, QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self._profile: Profile | None = None
        self._saved: dict[str, Any] | None = None
        self._loading = False
        self._saving = False
        self._wizard_running = False
        self._flow: Any = None
        self._steptest = StepTestController(ctx, self)
        self._steptest.started.connect(self._on_test_started)
        self._steptest.finished.connect(self._on_test_finished)
        self.setAcceptDrops(True)

        root = QHBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)
        root.addWidget(self._build_left())
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self.gallery_page = QScrollArea()
        self.gallery_page.setWidgetResizable(True)
        self.gallery_page.setFrameShape(QScrollArea.Shape.NoFrame)
        self.stack.addWidget(self.gallery_page)
        self.editor_page = QScrollArea()
        self.editor_page.setWidgetResizable(True)
        self.editor_page.setFrameShape(QScrollArea.Shape.NoFrame)
        # No sideways scrolling (U4): every card of this page fits the page width down to the smallest
        # window (1100 x 700) - long texts wrap or elide, a narrow step form puts fields under their
        # labels, the keywords editor's fuzzy line wraps, combos shrink. Measured with real fonts at
        # 100 / 125 / 150 % in zh-TW and English: 0 px overflow, so the bar never shows. It stays "as
        # needed" (not off): a case nobody measured (another font, a longer label) scrolls instead of
        # cutting off the right edge; the blank corner rule keeps the fitting case unchanged.
        self.editor_page.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.editor_page.setWidget(self._build_editor())
        self.stack.addWidget(self.editor_page)

        QShortcut(QKeySequence("Ctrl+S"), self, activated=lambda: self.save_profile())
        ctx.signals.profiles_changed.connect(self._on_profiles_changed)
        ctx.signals.active_profile_changed.connect(lambda _id: self.refresh_list())
        self.refresh_list()
        first = ctx.settings.active_profile_id if ctx.profiles.exists(ctx.settings.active_profile_id) else ""
        if not first and self._profiles:
            first = self._profiles[0].id
        if first:
            self._load(first)
        else:
            self._show_gallery()

    # ================================================================ building
    def _build_left(self) -> QWidget:
        left = QWidget()
        left.setFixedWidth(270)
        lay = QVBoxLayout(left)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lay.addWidget(w.label(tr("設定檔", "Profiles"), "display"))
        sub = w.label(tr("每個設定檔是一套兌換流程：對哪個視窗、依序點哪裡、輸入、怎麼判讀結果。",
                         "A profile is one redeem procedure: which window, where to click, what to type, how to read the result."),
                      "muted")
        sub.setWordWrap(True)
        lay.addWidget(sub)
        row = QHBoxLayout()
        self.new_btn = w.push_button(tr("從範本新增", "New from template"), "primary", "plus")
        self.new_btn.clicked.connect(lambda: self.new_from_template())
        row.addWidget(self.new_btn, 1)
        self.import_btn = w.push_button(tr("匯入", "Import"), "secondary", "import")
        self.import_btn.clicked.connect(self._import_clicked)
        row.addWidget(self.import_btn)
        lay.addLayout(row)
        self.list = QListWidget()
        self.list.setAccessibleName(tr("設定檔清單", "Profile list"))
        self.list.currentRowChanged.connect(self._on_list_row)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(lambda pos: self._list_menu(self.list.mapToGlobal(pos)))
        self.list_empty = self._build_list_empty()
        lay.addWidget(self.list, 1)
        bottom = QHBoxLayout()
        self.active_btn = w.push_button(tr("設為使用中", "Set as active"), "secondary", "check")
        self.active_btn.clicked.connect(self.set_active)
        bottom.addWidget(self.active_btn, 1)
        self.export_btn = w.icon_button("export", tr("匯出", "Export"))
        self.export_btn.clicked.connect(self.export_profile)
        self.dup_btn = w.icon_button("copy", tr("複製", "Duplicate"))
        self.dup_btn.clicked.connect(self.duplicate_profile)
        self.del_btn = w.icon_button("trash", tr("刪除", "Delete"))
        self.del_btn.clicked.connect(self.delete_profile)
        for b in (self.export_btn, self.dup_btn, self.del_btn):
            bottom.addWidget(b)
        lay.addLayout(bottom)
        self._profiles: list[Profile] = []
        return left

    def _build_list_empty(self) -> QWidget:
        """Empty state drawn inside the (empty) profile list, on its own background (U21): what
        to do first - the template gallery on the right, or 匯入."""
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        v.addWidget(w.icon_label("profiles", "text_muted", 28), 0, Qt.AlignmentFlag.AlignHCenter)
        title = w.label(tr("還沒有設定檔", "No profiles yet"), "strong")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        v.addWidget(title)
        self.list_empty_hint = w.label(tr("從右邊選一個範本開始，或按「匯入」載入別人分享的設定檔。",
                                          "Pick a template on the right, or click Import to load a profile someone shared."),
                                       "muted")
        self.list_empty_hint.setWordWrap(True)
        self.list_empty_hint.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        v.addWidget(self.list_empty_hint)
        holder = QVBoxLayout(self.list.viewport())  # the list keeps its own panel look around the text
        holder.setContentsMargins(20, 40, 20, 20)
        holder.addWidget(box)
        holder.addStretch(1)
        box.hide()
        return box

    def _build_editor(self) -> QWidget:
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(16)
        head = QHBoxLayout()
        head.setSpacing(theme.SP[2])  # like the Codes page header; 16 px gaps made the English row too wide
        col = QVBoxLayout()
        self.title = w.ElidedLabel("")  # a long profile name elides instead of pushing 儲存 off the page
        self.title.setProperty("role", "display")
        col.addWidget(self.title)
        self.dirty_label = w.label(tr("● 有未儲存的變更", "● Unsaved changes"), "caption")
        self.dirty_label.hide()
        col.addWidget(self.dirty_label)
        head.addLayout(col, 1)
        self.preview_btn = w.push_button(tr("預覽點位", "Preview positions"), "secondary", "eye")
        self.preview_btn.clicked.connect(self.preview)
        self.wizard_btn = w.push_button(tr("設定精靈", "Setup wizard"), "secondary", "flask")
        self.wizard_btn.clicked.connect(lambda: self._profile and self.start_wizard(self._profile.id))
        self.realign_btn = w.push_button(tr("重新對準", "Re-align"), "secondary", "crosshair")
        self.realign_btn.setToolTip(tr("把每個位置重新點選一次（視窗大小或縮放改變、匯入之後）",
                                       "Pick every position again (window size or scaling changed, after an import)"))
        self.realign_btn.clicked.connect(lambda: self._profile and self.start_wizard(self._profile.id, realign=True))
        self.save_btn = w.push_button(tr("儲存", "Save"), "primary", "save")
        self.save_btn.setToolTip(tr("儲存（Ctrl+S）", "Save (Ctrl+S)"))
        self.save_btn.clicked.connect(lambda: self.save_profile())
        for b in (self.preview_btn, self.wizard_btn, self.realign_btn, self.save_btn):
            head.addWidget(b)
        lay.addLayout(head)
        self.newer_banner = w.Banner("warning", "", "", False)
        self.newer_banner.hide()
        lay.addWidget(self.newer_banner)
        self.checklist, self.checklist_lay = card(tr("設定檢查", "Setup checklist"))
        self.checklist_rows = QVBoxLayout()
        self.checklist_lay.addLayout(self.checklist_rows)
        lay.addWidget(self.checklist)
        self.basics = BasicsCard(self.ctx, self._changed)
        lay.addWidget(self.basics)
        self.target_card = TargetCard(self.ctx, self._changed, self._pick_target)
        lay.addWidget(self.target_card)
        self.format_card = FormatCard(self._changed)
        lay.addWidget(self.format_card)
        steps_card, steps_lay = card(tr("步驟", "Steps"),
                                     tr("每筆序號都會依序執行這些步驟。左邊選步驟，右邊改設定。",
                                        "Every code runs these steps in order. Select a step on the left, edit it on the right."))
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        self.step_list = StepListWidget(self.ctx)
        # 300 px at the default window size (setSizes below), down to 240 px in a small window so
        # the step form keeps room beside it (U4: the form had to scroll sideways)
        self.step_list.setMinimumWidth(STEP_LIST_MIN_W)
        self.step_list.setMinimumHeight(420)
        self.step_list.currentChanged.connect(self._on_step_selected)
        self.step_list.stepsChanged.connect(self._on_steps_changed)
        split.addWidget(self.step_list)
        right = QWidget()
        rlay = QVBoxLayout(right)
        rlay.setContentsMargins(12, 0, 0, 0)
        self.step_editor = StepEditor(self.ctx)
        self.step_editor.stepChanged.connect(self._on_step_edited)
        rlay.addWidget(self.step_editor, 1)
        self.test_btn = w.push_button(tr("測試此步驟", "Test this step"), "secondary", "flask")
        self.test_btn.setToolTip(tr("預設只定位與辨識、不送出任何輸入", "By default it only locates and reads; no input is sent"))
        self.test_btn.clicked.connect(lambda: self.test_step())
        self.real_check = QCheckBox(tr("真的執行（會送出輸入）", "Run for real (sends input)"))
        self.real_check.setFixedHeight(theme.CONTROL_H)  # centred on the buttons beside it
        self.stop_test_btn = w.push_button(tr("停止測試", "Stop test"), "danger", "stop")
        self.stop_test_btn.clicked.connect(self._steptest.stop)
        self.stop_test_btn.hide()
        btns = QWidget()
        bl = QHBoxLayout(btns)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(self.test_btn)
        bl.addWidget(self.stop_test_btn)
        # [測試此步驟] [☐ 真的執行] on one line; the check box moves under the button when narrow
        self.test_row = QFormLayout()
        self.test_row.setContentsMargins(0, 0, 0, 0)
        self.test_row.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.test_row.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        self.test_row.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.test_row.setHorizontalSpacing(12)
        self.test_row.setVerticalSpacing(4)
        self.test_row.addRow(btns, self.real_check)
        rlay.addLayout(self.test_row)
        self.test_result = w.label("", "muted")
        self.test_result.setWordWrap(True)
        rlay.addWidget(self.test_result)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        split.setSizes([STEP_LIST_W, 10_000])  # the list keeps 300 px when there is room
        self.steps_split = split
        steps_lay.addWidget(split)
        self.steps_card = steps_card
        lay.addWidget(steps_card)
        self.policy_card = PolicyCard(self._changed)
        lay.addWidget(self.policy_card)
        kw_card, kw_lay = card(tr("結果關鍵字", "Result keywords"))
        self.keywords = KeywordsEditor()
        self.keywords.changed.connect(self._on_keywords)
        kw_lay.addWidget(self.keywords)
        lay.addWidget(kw_card)
        lay.addStretch(1)
        # one label column for the four form cards: their fields start at the same x (U35)
        self.label_width = align_form_labels([c.form for c in (self.basics, self.target_card, self.format_card,
                                                              self.policy_card)])
        return body

    # ================================================================ list
    def refresh_list(self) -> None:
        try:
            self._profiles = self.ctx.profiles.list()
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("listing profiles failed: %s", exc)
            self._profiles = []
        current = self._profile.id if self._profile else ""
        self.list.blockSignals(True)
        self.list.clear()
        for p in self._profiles:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, p.id)
            row = _ProfileRow(p, p.id == self.ctx.settings.active_profile_id)
            item.setSizeHint(row.sizeHint().expandedTo(row.minimumSizeHint()))
            self.list.addItem(item)
            self.list.setItemWidget(item, row)
            if p.id == current:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        self.list_empty.setVisible(not self._profiles)
        has = self._profile is not None
        for b in (self.active_btn, self.export_btn, self.dup_btn, self.del_btn):
            b.setEnabled(has)
        self.active_btn.setEnabled(has and self._profile.id != self.ctx.settings.active_profile_id)

    def profile_ids(self) -> list[str]:
        return [p.id for p in self._profiles]

    def _on_list_row(self, row: int) -> None:
        if not 0 <= row < len(self._profiles):
            return
        pid = self._profiles[row].id
        if self._profile is not None and pid == self._profile.id:
            return
        if not self._maybe_leave():
            self.refresh_list()  # put the selection back
            return
        self._load(pid)

    def _list_menu(self, pos: Any) -> None:
        if self._profile is None:
            return
        menu = QMenu(self)
        menu.addAction(tr("設為使用中", "Set as active"), self.set_active)
        menu.addAction(tr("匯出…", "Export…"), self.export_profile)
        menu.addAction(tr("複製", "Duplicate"), self.duplicate_profile)
        menu.addSeparator()
        menu.addAction(tr("刪除", "Delete"), self.delete_profile)
        menu.exec(pos)

    # ================================================================ load / dirty / save
    def working_profile(self) -> Profile | None:
        return self._profile

    def is_dirty(self) -> bool:
        return self._profile is not None and _snapshot(self._profile) != self._saved

    def open_profile(self, profile_id: str) -> None:
        if self._profile is not None and self._profile.id == profile_id:
            self.stack.setCurrentWidget(self.editor_page)
            return
        if not self._maybe_leave():
            return
        self._load(profile_id)

    def _load(self, profile_id: str, keep_step: int = 0) -> None:
        p = self.ctx.profiles.get(profile_id)
        if p is None:
            self.ctx.notify(tr("找不到這個設定檔", "Profile not found"), "error")
            return
        self._loading = True
        try:
            self._profile = p
            self._saved = _snapshot(p)
            self.basics.load(p)
            self.target_card.load(p)
            self.format_card.load(p)
            self.policy_card.load(p)
            self.keywords.set_config(p.keywords)
            self.step_list.set_steps(p.steps)
            self.step_list.set_current(min(keep_step, len(p.steps) - 1))
            idx = self.step_list.current_index()
            self.step_editor.set_step(p.steps[idx] if idx >= 0 else None, p, idx)
        finally:
            self._loading = False
        newer = p.schema_version > PROFILE_SCHEMA_VERSION
        self.newer_banner.setText(dialogs.newer_profile_text())
        self.newer_banner.setVisible(newer)
        self.test_result.setText("")
        self.stack.setCurrentWidget(self.editor_page)
        self.refresh_list()
        self._changed(mark=False)
        self._refresh_target_status()

    def _changed(self, mark: bool = True) -> None:
        if self._loading or self._profile is None:
            return
        p = self._profile
        self.title.setText(p.name or tr("（未命名）", "(untitled)"))
        self.dirty_label.setVisible(self.is_dirty())
        self._refresh_checklist()
        errors = {i.step_index for i in p.validate() if i.level is IssueLevel.ERROR and i.step_index >= 0}
        self.step_list.set_error_rows(errors)
        self.preview_btn.setEnabled(not p.target.is_empty())

    def save_profile(self, confirm_newer: bool = True) -> bool:
        p = self._profile
        if p is None:
            return False
        if confirm_newer and p.schema_version > PROFILE_SCHEMA_VERSION:
            if not w.confirm(self.window(), tr("儲存設定檔", "Save profile"), dialogs.newer_profile_text(),
                             tr("仍要儲存", "Save anyway"), tr("取消", "Cancel")):
                return False
        pol = p.policy
        if pol.interval_min_s > pol.interval_max_s:
            pol.interval_min_s, pol.interval_max_s = pol.interval_max_s, pol.interval_min_s
        if not p.name.strip():
            p.name = tr("未命名設定檔", "Untitled profile")
        old = profile_from_dict(self._saved) if self._saved else None
        try:
            self._saving = True
            self.ctx.profiles.save(p)
        except storage.StorageError as exc:
            self.ctx.notify(str(exc), "error")
            return False
        finally:
            self._saving = False
        self._saved = _snapshot(p)
        if old is not None and old.game_key() != p.game_key():
            self._offer_move_codes(old, p)
        self._saving = True
        try:
            self.ctx.signals.profiles_changed.emit()
        finally:
            self._saving = False
        self.refresh_list()
        self.policy_card.load(p)
        self._changed(mark=False)
        return True

    def _offer_move_codes(self, old: Profile, new: Profile) -> None:
        ids = [i.id for i in self.ctx.queue.items() if i.game_key == old.game_key()]
        if not ids:
            return
        old_name = old.game or tr("（未指定遊戲）", "(no game)")
        new_name = new.game or new.name
        if w.confirm(self.window(), tr("遊戲名稱已變更", "Game renamed"),
                     tr(f"佇列中還有 {len(ids)} 筆「{old_name}」的序號，要改成屬於「{new_name}」嗎？",
                        f"{len(ids)} queued codes belong to '{old_name}'. Move them to '{new_name}'?"),
                     tr("移過去", "Move them"), tr("不用", "No")):
            from .run_actions import call

            n = call(self.ctx.queue.assign_game, ids, new.game_key(), new.game, default=0) or 0
            self.ctx.notify(tr(f"已移動 {n} 筆序號", f"Moved {n} codes"), "success")

    def discard_changes(self) -> None:
        if self._profile is not None:
            self._load(self._profile.id, self.step_list.current_index())

    def maybe_leave(self) -> bool:
        """Public form of the Save / Discard / Cancel question (MainWindow.closeEvent asks it
        before quitting; integration). False = the user cancelled."""
        return self._maybe_leave()

    def _maybe_leave(self) -> bool:
        """Save / Discard / Cancel when the current profile has unsaved changes."""
        if not self.is_dirty():
            return True
        answer = dialogs.ask_save_changes(self.window(), self._profile.name if self._profile else "")
        if answer == "save":
            return self.save_profile()
        if answer == "discard":
            self._saved = _snapshot(self._profile)
            return True
        return False

    def _on_profiles_changed(self) -> None:
        if self._saving:
            return
        self.refresh_list()
        p = self._profile
        if p is None:
            if not self._profiles:
                self._show_gallery()
            return
        stored = self.ctx.profiles.get(p.id)
        if stored is None:
            self._profile, self._saved = None, None
            if self._profiles:
                self._load(self._profiles[0].id)
            else:
                self._show_gallery()
            return
        if not self.is_dirty():
            self._load(p.id, self.step_list.current_index())
            return
        snap = profile_from_dict(self._saved) if self._saved else None  # merge outside changes
        if snap is not None and to_dict(snap.target) != to_dict(stored.target):
            p.target = stored.target
            self.target_card.load(p)
        p.last_test_ok_at = stored.last_test_ok_at
        if snap is not None:
            snap.target, snap.last_test_ok_at = stored.target, stored.last_test_ok_at
            self._saved = _snapshot(snap)
        self._changed()

    def hideEvent(self, event) -> None:  # noqa: N802
        # only when another page is shown (not while the window is minimised or hidden for a run)
        if self.is_dirty() and not self._wizard_running and not event.spontaneous() and self.window().isVisible():
            self.ctx.notify(tr(f"設定檔「{self._profile.name}」有未儲存的變更", f"Profile '{self._profile.name}' has unsaved changes"),
                            "warning")
        super().hideEvent(event)

    def _show_gallery(self) -> None:
        templates = []
        try:
            templates = storage.load_templates()
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("loading templates failed: %s", exc)
        gallery = dialogs.TemplateGallery(templates)
        gallery.chosen.connect(self._create_from)
        self.gallery = gallery
        self.gallery_page.setWidget(gallery)
        self.stack.setCurrentWidget(self.gallery_page)
        self._profile, self._saved = None, None
        self.refresh_list()

    # ================================================================ editing hooks
    def _on_step_selected(self, index: int) -> None:
        if self._loading or self._profile is None:
            return
        steps = self._profile.steps
        self.step_editor.set_step(steps[index] if 0 <= index < len(steps) else None, self._profile, index)
        self.test_result.setText("")

    def _on_steps_changed(self) -> None:
        if self._profile is None:
            return
        self._profile.steps = self.step_list.steps()
        self._on_step_selected(self.step_list.current_index())
        self._changed()

    def _on_step_edited(self, step: Step) -> None:
        if self._profile is None:
            return
        idx = self.step_editor.index()
        if 0 <= idx < len(self._profile.steps):
            self._profile.steps[idx] = step
            self.step_list.update_step(idx, step)
            self._changed()

    def _on_keywords(self) -> None:
        if self._profile is not None and not self._loading:
            self._profile.keywords = self.keywords.config()
            self._changed()

    def replace_step(self, index: int, step: Step) -> None:
        """Set one step from outside the editor (wizard) and refresh the views."""
        if self._profile is None or not 0 <= index < len(self._profile.steps):
            return
        self._profile.steps[index] = step
        self.step_list.set_steps(self._profile.steps)
        self.step_list.set_current(index)
        self._changed()

    def set_target(self, target: TargetMatch) -> None:
        if self._profile is None:
            return
        self._profile.target = target
        self.target_card.load(self._profile)
        self._refresh_target_status()
        self._changed()

    def _refresh_target_status(self) -> None:
        from .run_actions import find_target

        if self._profile is not None:
            self.target_card.refresh_text(find_target(self._profile))

    def _pick_target(self) -> None:
        if self._profile is None:
            return
        from .run_actions import target_from_window
        from .window_picker import pick_target_window

        info = pick_target_window(self.ctx, self._profile.target, self.window(), suggested_exe=self._profile.suggested_exe)
        if info is not None:
            self.set_target(target_from_window(info))

    # ================================================================ actions
    def run_flow(self) -> Any:
        if self._flow is None:
            from .run_flow import RunFlow

            self._flow = RunFlow(self.ctx, self)
        return self._flow

    def start_wizard(self, profile_id: str, realign: bool = False) -> None:
        """The setup wizard (SPEC 6.4.2): target window, every missing_setup() position, the
        result-close choice, 預覽點位, 測試一筆 (with a paste box for one real code). ``realign``
        = 「重新對準」: re-pick every recorded position (preflight actions size_changed /
        dpi_changed, after an import)."""
        if self._wizard_running:
            return
        if self._profile is None or self._profile.id != profile_id:
            self.open_profile(profile_id)
        if self._profile is None or self._profile.id != profile_id:
            return
        from .profiles_wizard import SetupWizard

        self._wizard_running = True
        try:
            SetupWizard(self, profile_id, realign).run()
        finally:
            self._wizard_running = False
        self._changed()


__all__ = ["ProfilesPage", "ask_open_path", "ask_save_path", "blank_profile"]  # helpers re-exported from profiles_actions
