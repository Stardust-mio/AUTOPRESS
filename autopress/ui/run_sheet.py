# OWNED BY G7
"""The preflight sheet shown by RunFlow before a run (SPEC 2.4 step 2; private G7 helper):
errors block (with action buttons), warnings need a click (「我已了解這些提醒」), info lines -
including the ``estimate`` - are shown. Also the reusable issue list of the Run page and the
hotkey-failure text (SPEC 7.1)."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PyQt6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from ..context import AppContext
from ..i18n import tr
from ..models import IssueLevel, PlanMode, PreflightIssue, PreflightReport, Profile, RunPlan
from . import widgets as w
from .run_actions import action_label

_ORDER = {IssueLevel.ERROR: 0, IssueLevel.WARNING: 1, IssueLevel.INFO: 2}


def issue_mark(level: IssueLevel) -> str:
    """Text glyph so the level is never shown by colour alone (SPEC 6.5)."""
    return {IssueLevel.ERROR: "✕", IssueLevel.WARNING: "!", IssueLevel.INFO: "i"}.get(level, "·")


def sorted_issues(issues: Sequence[PreflightIssue]) -> list[PreflightIssue]:
    return sorted(issues, key=lambda i: _ORDER.get(i.level, 3))


def hotkey_failure_text(combo: str, error: int = 1409, message: str = "") -> str:
    """SPEC 7.1 'hotkey in use (1409)' (generic wording for other failures)."""
    if error == 1409:
        return tr(f"快捷鍵 {combo} 已被其他程式使用，請在設定中更換；這次執行請用迷你控制列的按鈕或左上角緊急停止。",
                  f"Hotkey {combo} is used by another program; change it in Settings. For this run use the mini bar "
                  "buttons or the top-left emergency stop.")
    extra = f"（{message}）" if message else ""
    return tr(f"無法註冊快捷鍵 {combo}{extra}；這次執行請用迷你控制列的按鈕或左上角緊急停止。",
              f"Hotkey {combo} could not be registered{(' (' + message + ')') if message else ''}; for this run use "
              "the mini bar buttons or the top-left emergency stop.")


class IssueList(QWidget):
    """Rows of preflight issues: glyph + message + muted hint + optional action button."""

    def __init__(self, on_action: Callable[[str], None] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.on_action = on_action
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(8)
        self.buttons: dict[str, QWidget] = {}

    def set_issues(self, issues: Sequence[PreflightIssue], profile: Profile | None = None) -> None:
        while self.lay.count():
            item = self.lay.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.buttons = {}
        for issue in sorted_issues(issues):
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(10)
            role = {IssueLevel.ERROR: "error", IssueLevel.WARNING: "body"}.get(issue.level, "secondary")
            mark_role = {IssueLevel.ERROR: "error", IssueLevel.WARNING: "warning"}.get(issue.level, "info")
            mark = w.label(issue_mark(issue.level), mark_role)
            mark.setFixedWidth(16)
            h.addWidget(mark)
            col = QVBoxLayout()
            col.setSpacing(0)
            msg = w.label(issue.message, role)
            msg.setWordWrap(True)
            col.addWidget(msg)
            if issue.hint:
                hint = w.label(issue.hint, "muted")
                hint.setWordWrap(True)
                col.addWidget(hint)
            h.addLayout(col, 1)
            if issue.action and self.on_action is not None:
                btn = w.push_button(action_label(issue.action, profile), "secondary")
                btn.clicked.connect(lambda _c=False, a=issue.action: self.on_action(a))
                h.addWidget(btn)
                self.buttons[issue.action] = btn
            self.lay.addWidget(row)
        self.lay.addStretch(1)


class PreflightSheet(QDialog):
    """Result: ``answer`` = "start" | "cancel" | "action:<name>"."""

    def __init__(self, ctx: AppContext, report: PreflightReport, plan: RunPlan, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.report = report
        self.answer = "cancel"
        test = plan.mode is PlanMode.TEST_ONE
        self.setWindowTitle(tr("測試一筆：開始前檢查", "Test one: pre-flight check") if test
                            else tr("開始前檢查", "Pre-flight check"))
        self.setMinimumSize(600, 380)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)
        n = len(plan.items)
        head = tr(f"「{plan.profile.name}」· {n} 筆序號", f"'{plan.profile.name}' · {n} codes")
        lay.addWidget(w.label(head, "title"))
        target = report.target
        if target is not None:
            lay.addWidget(w.label(tr(f"目標視窗：{target.title}", f"Target window: {target.title}"), "secondary"))
        errors = [i for i in report.issues if i.level is IssueLevel.ERROR]
        warnings = [i for i in report.issues if i.level is IssueLevel.WARNING]
        self.issue_list = IssueList(self._action)
        self.issue_list.set_issues(report.issues, plan.profile)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(self.issue_list)
        lay.addWidget(scroll, 1)
        if not report.issues:
            lay.addWidget(w.label(tr("一切就緒。", "Everything is ready."), "secondary"))
        self.ack: QCheckBox | None = None
        if errors:
            note = w.label(tr(f"有 {len(errors)} 個問題必須先處理，才能開始。", f"{len(errors)} problems must be fixed first."), "error")
            note.setWordWrap(True)
            lay.addWidget(note)
        elif warnings:
            self.ack = QCheckBox(tr("我已了解上面的提醒", "I have read the warnings above"))
            self.ack.toggled.connect(self._update)
            lay.addWidget(self.ack)
        row = QHBoxLayout()
        row.addStretch(1)
        self.cancel_btn = w.push_button(tr("關閉", "Close") if errors else tr("取消", "Cancel"), "secondary")
        self.cancel_btn.clicked.connect(self.reject)
        row.addWidget(self.cancel_btn)
        self.start_btn = None
        if not errors:
            text = tr("開始測試", "Start test") if test else tr("開始兌換", "Start")
            if warnings:
                text = tr("仍要開始", "Start anyway")
            self.start_btn = w.push_button(text, "primary", "play")
            self.start_btn.clicked.connect(self._start)
            row.addWidget(self.start_btn)
        lay.addLayout(row)
        self._update()

    def _update(self) -> None:
        if self.start_btn is not None:
            ok = self.ack is None or self.ack.isChecked()
            self.start_btn.setEnabled(ok)
            self.start_btn.setDefault(ok)

    def _start(self) -> None:
        if self.start_btn is not None and self.start_btn.isEnabled():
            self.answer = "start"
            self.accept()

    def _action(self, action: str) -> None:
        self.answer = f"action:{action}"
        self.accept()


def show_preflight_sheet(ctx: AppContext, report: PreflightReport, plan: RunPlan, parent: QWidget | None) -> str:
    """Modal sheet; "start" | "cancel" | "action:<name>". Tests monkeypatch this function."""
    dlg = PreflightSheet(ctx, report, plan, parent)
    try:
        dlg.exec()
        return dlg.answer
    finally:
        dlg.deleteLater()


__all__ = ["IssueList", "PreflightSheet", "hotkey_failure_text", "issue_mark", "show_preflight_sheet", "sorted_issues"]
