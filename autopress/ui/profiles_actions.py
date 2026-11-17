# OWNED BY G7
"""Actions of the Profiles page (private helper of ui.profiles_page, mixed into ProfilesPage):
new from template / blank, import (PX-01 flow), export with an optional title keyword,
duplicate, delete, 設為使用中, the setup checklist, 預覽點位, 測試此步驟 and drag-and-drop of
*.autopress.json files. The methods use the page's widgets and state (``self._profile`` ...)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QWidget

from .. import storage
from ..context import AppContext
from ..i18n import tr
from ..models import PROFILE_FILE_SUFFIX, IssueLevel, Profile, StepType, make_step
from . import profiles_dialogs as dialogs
from . import widgets as w
from .profiles_steptest import describe_result

log = logging.getLogger(__name__)


def ask_open_path(parent: QWidget | None) -> str:
    path, _f = QFileDialog.getOpenFileName(parent, tr("匯入設定檔", "Import profile"), "",
                                           tr(f"AutoPress 設定檔 (*{PROFILE_FILE_SUFFIX});;JSON (*.json)",
                                              f"AutoPress profile (*{PROFILE_FILE_SUFFIX});;JSON (*.json)"))
    return path


def ask_save_path(parent: QWidget | None, default_name: str) -> str:
    path, _f = QFileDialog.getSaveFileName(parent, tr("匯出設定檔", "Export profile"), default_name,
                                           tr(f"AutoPress 設定檔 (*{PROFILE_FILE_SUFFIX})",
                                              f"AutoPress profile (*{PROFILE_FILE_SUFFIX})"))
    if path and not path.endswith(PROFILE_FILE_SUFFIX):
        path = path[: -len(".json")] + PROFILE_FILE_SUFFIX if path.endswith(".json") else path + PROFILE_FILE_SUFFIX
    return path


def blank_profile(ctx: AppContext) -> Profile:
    """「從空白開始」: the usual skeleton (focus, click the box, type, Enter, read the result)."""
    p = Profile(name=tr("新的設定檔", "New profile"))
    focus = make_step(StepType.FOCUS_WINDOW, ctx.settings.delays)
    click = make_step(StepType.CLICK_POINT, ctx.settings.delays)
    click.label, click.label_en = "點一下序號輸入框", "Click the code box"
    typ = make_step(StepType.TYPE_CODE, ctx.settings.delays)
    typ.params.mode = ctx.settings.default_typing_mode  # type: ignore[union-attr]
    enter = make_step(StepType.KEY, ctx.settings.delays)
    check = make_step(StepType.OCR_CHECK, ctx.settings.delays)
    check.label, check.label_en = "框出結果訊息出現的範圍", "Mark where the result message appears"
    p.steps = [focus, click, typ, enter, check]
    return p


class ProfileActions:
    """Mixin for ProfilesPage (plain Python class: no QObject base)."""

    # -- helpers --------------------------------------------------------------------------
    def _emit_profiles_changed(self: Any) -> None:
        """profiles_changed without reloading this page (it already shows the change)."""
        self._saving = True
        try:
            self.ctx.signals.profiles_changed.emit()
        finally:
            self._saving = False

    # -- list actions ---------------------------------------------------------------------
    def set_active(self: Any) -> None:
        if self._profile is not None:
            self.ctx.set_active_profile(self._profile.id)
            self.refresh_list()

    def new_from_template(self: Any, template_key: str | None = None) -> None:
        """Create a profile from a built-in template (gallery dialog when ``template_key`` is None)."""
        if not self._maybe_leave():
            return
        try:
            templates = storage.load_templates()
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("loading templates failed: %s", exc)
            templates = []
        if template_key is None:
            ok, tpl = dialogs.choose_template(templates, self.window())
            if not ok:
                return
        else:
            tpl = next((t for t in templates if t.template is not None and t.template.key == template_key), None)
            if tpl is None:
                self.ctx.notify(tr(f"找不到範本「{template_key}」", f"Template '{template_key}' not found"), "error")
                return
        self._create_from(tpl)

    def _create_from(self: Any, tpl: object) -> None:
        if self._profile is not None and not self._maybe_leave():
            return
        p = storage.profile_from_template(tpl) if isinstance(tpl, Profile) else blank_profile(self.ctx)
        try:
            self.ctx.profiles.save(p)
        except storage.StorageError as exc:
            self.ctx.notify(str(exc), "error")
            return
        if not self.ctx.settings.active_profile_id or not self.ctx.profiles.exists(self.ctx.settings.active_profile_id):
            self.ctx.set_active_profile(p.id)
        self._emit_profiles_changed()
        self._load(p.id)
        self.start_wizard(p.id)

    def _import_clicked(self: Any) -> None:
        path = ask_open_path(self.window())
        if path:
            self.import_profile_file(Path(path))

    def import_profile_file(self: Any, path: Path) -> None:
        """ProfileStore.read_file (nothing saved or renamed; target already cleared) -> the import
        card (action_lines verbatim, 「我看得懂這些動作」) -> ProfileStore.import_profile -> the setup
        wizard opens on 「選擇目標視窗」 (also used by drag-and-drop of *.autopress.json)."""
        if not self._maybe_leave():
            return
        try:
            p = self.ctx.profiles.read_file(Path(path))
        except storage.StorageError as exc:
            self.ctx.notify(str(exc), "error")
            return
        if not dialogs.confirm_import(p, Path(path).name, self.window()):
            return
        try:
            saved = self.ctx.profiles.import_profile(p)
        except storage.StorageError as exc:
            self.ctx.notify(str(exc), "error")
            return
        self._emit_profiles_changed()
        self.ctx.notify(tr(f"已匯入「{saved.name}」，接著請選擇目標視窗", f"Imported '{saved.name}'; now choose the target window"),
                        "success")
        self._load(saved.id)
        self.start_wizard(saved.id, realign=bool(saved.reference_sizes()))

    def export_profile(self: Any) -> None:
        p = self._profile
        if p is None:
            return
        keyword = dialogs.ask_export_keyword(p, self.window())
        if keyword is None:
            return
        safe = "".join(c for c in (p.name or "profile") if c not in '\\/:*?"<>|').strip() or "profile"
        path = ask_save_path(self.window(), safe + PROFILE_FILE_SUFFIX)
        if not path:
            return
        try:
            self.ctx.profiles.export_file(p, Path(path), keyword)
        except storage.StorageError as exc:
            self.ctx.notify(str(exc), "error")
            return
        self.ctx.notify(tr(f"已匯出到 {path}", f"Exported to {path}"), "success")

    def duplicate_profile(self: Any) -> None:
        if self._profile is None or not self._maybe_leave():
            return
        copy = self.ctx.profiles.duplicate(self._profile.id)
        self._emit_profiles_changed()
        self._load(copy.id)

    def delete_profile(self: Any) -> None:
        p = self._profile
        if p is None:
            return
        if not w.confirm(self.window(), tr("刪除設定檔", "Delete profile"),
                         tr(f"確定要刪除「{p.name}」嗎？佇列中的序號和紀錄不會被刪除。",
                            f"Delete '{p.name}'? Queued codes and history are kept."),
                         tr("刪除", "Delete"), tr("取消", "Cancel"), danger=True):
            return
        self.ctx.profiles.delete(p.id)
        self._profile, self._saved = None, None
        if self.ctx.settings.active_profile_id == p.id:
            self.ctx.set_active_profile("")
        self._emit_profiles_changed()
        self.refresh_list()
        if self._profiles:
            self._load(self._profiles[0].id)
        else:
            self._show_gallery()

    # -- setup checklist ------------------------------------------------------------------
    def _refresh_checklist(self: Any) -> None:
        while self.checklist_rows.count():
            item = self.checklist_rows.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        p = self._profile
        if p is None:
            self.checklist.hide()
            return
        issues = [i for i in p.validate() if i.level in (IssueLevel.ERROR, IssueLevel.WARNING)]
        issues.sort(key=lambda i: 0 if i.level is IssueLevel.ERROR else 1)
        for issue in issues[:8]:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            mark = "✕ " if issue.level is IssueLevel.ERROR else "! "
            lb = w.label(mark + issue.message, "error" if issue.level is IssueLevel.ERROR else "secondary")
            lb.setWordWrap(True)
            h.addWidget(lb, 1)
            btn = self._checklist_button(issue)
            if btn is not None:
                h.addWidget(btn)
            self.checklist_rows.addWidget(row)
        if len(issues) > 8:
            self.checklist_rows.addWidget(w.label(tr(f"還有 {len(issues) - 8} 項", f"{len(issues) - 8} more"), "muted"))
        self.checklist.setVisible(bool(issues))

    def _checklist_button(self: Any, issue: Any) -> QWidget | None:
        if issue.path.startswith("target"):
            b = w.push_button(tr("設定", "Set up"), "secondary")
            b.clicked.connect(self._pick_target)
            return b
        if issue.step_index >= 0:
            field = issue.path.rsplit(".", 1)[-1]
            if field in ("point", "region"):
                b = w.push_button(tr("設定", "Set up"), "secondary")
                b.clicked.connect(lambda _c=False, i=issue.step_index, f=field: self.pick_step_field(i, f))
                return b
            b = w.push_button(tr("前往", "Go"), "ghost")
            b.clicked.connect(lambda _c=False, i=issue.step_index: self.step_list.set_current(i))
            return b
        return None

    def pick_step_field(self: Any, index: int, field: str) -> None:
        """設定 in the checklist: select the step and pick its position."""
        if self._profile is None or not 0 <= index < len(self._profile.steps):
            return
        self.step_list.set_current(index)
        step = self._profile.steps[index]
        from .step_pick import hide_list, pick_point, pick_region

        hide = hide_list(self, getattr(self.ctx, "main_window", None))
        if field == "point":
            value, err = pick_point(self._profile, step.display_title(), hide=hide)
        else:
            value, err = pick_region(self._profile, step.display_title(), hide=hide)
        if err:
            w.message(self.window(), tr("設定位置", "Pick position"), err, "warning")
        if value is not None:
            setattr(step.params, field, value)
            self.replace_step(index, step)

    # -- preview / step test --------------------------------------------------------------
    def preview(self: Any) -> None:
        if self._profile is not None:
            from .run_actions import show_preview

            show_preview(self.ctx, self._profile, parent=self.window())

    def test_step(self: Any, real: bool | None = None) -> bool:
        """測試此步驟 for the selected step (dry run unless 「真的執行」 is ticked)."""
        if self._profile is None:
            return False
        idx = self.step_list.current_index()
        if idx < 0:
            return False
        real = self.real_check.isChecked() if real is None else real
        return self._steptest.start(self._profile, idx, dry_run=not real)

    def _on_test_started(self: Any, real: bool) -> None:
        self.test_btn.setEnabled(False)
        self.stop_test_btn.setVisible(real)
        self.test_result.setText(tr("測試中…", "Testing…"))

    def _on_test_finished(self: Any, result: Any) -> None:
        self.test_btn.setEnabled(True)
        self.stop_test_btn.hide()
        text, _tone = describe_result(result)
        self.test_result.setText(text)

    # -- drag and drop --------------------------------------------------------------------
    def dragEnterEvent(self: Any, event: Any) -> None:  # noqa: N802
        urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
        if any(u.toLocalFile().endswith((PROFILE_FILE_SUFFIX, ".json")) for u in urls):
            event.acceptProposedAction()

    def dropEvent(self: Any, event: Any) -> None:  # noqa: N802
        for u in event.mimeData().urls():
            path = u.toLocalFile()
            if path.endswith((PROFILE_FILE_SUFFIX, ".json")):
                event.acceptProposedAction()
                self.import_profile_file(Path(path))
                return


__all__ = ["ProfileActions", "ask_open_path", "ask_save_path", "blank_profile"]
