# OWNED BY G7
"""The preflight sheet shown by RunFlow before a run (SPEC 2.4 step 2; private G7 helper):
errors block (with action buttons), warnings need a click (「我已了解這些提醒」), info lines -
including the ``estimate`` - are shown. Also the reusable issue list of the Run page and the
hotkey-failure text (SPEC 7.1).

Issue rows: a level icon whose shape differs per level (✕ / triangle / i, so the level is never
shown by colour alone - SPEC 6.5), the message, a muted hint and an optional action button; every
row is at least a button tall, so rows with and without a button are spaced evenly. The sheet
is as tall as its content (the list scrolls beyond 60 % of the screen height)."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from ..context import AppContext
from ..i18n import tr
from ..models import IssueLevel, PlanMode, PreflightIssue, PreflightReport, Profile, RunPlan
from . import icons, theme
from . import widgets as w
from .run_actions import action_label

_ORDER = {IssueLevel.ERROR: 0, IssueLevel.WARNING: 1, IssueLevel.INFO: 2}
# level -> (icon name, colour token): distinct shapes, not only distinct colours
_MARK_ICON = {IssueLevel.ERROR: ("x", "error"), IssueLevel.WARNING: ("alert", "warning"), IssueLevel.INFO: ("info", "info")}
SHEET_MAX_LIST = 0.6  # the issue list grows with its content up to this share of the screen height


def issue_mark(level: IssueLevel) -> str:
    """Text glyph for text-only contexts (the issue rows use issue_icon); never colour alone."""
    return {IssueLevel.ERROR: "✕", IssueLevel.WARNING: "!", IssueLevel.INFO: "i"}.get(level, "·")


def issue_level_name(level: IssueLevel) -> str:
    """Accessible name of a row's level icon."""
    return {IssueLevel.ERROR: tr("錯誤", "Error"), IssueLevel.WARNING: tr("提醒", "Warning"),
            IssueLevel.INFO: tr("資訊", "Information")}.get(level, "")


def issue_icon(level: IssueLevel) -> QLabel:
    """18 px label with the level's icon (follows theme switches through icons.bind)."""
    mark = QLabel()
    mark.setFixedSize(18, 18)
    mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
    name, token = _MARK_ICON.get(level, ("info", "info"))
    icons.bind(mark, name, token, 16)
    mark.setAccessibleName(issue_level_name(level))
    return mark


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
    """Rows of preflight issues: level icon + message + muted hint + optional action button."""

    def __init__(self, on_action: Callable[[str], None] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.on_action = on_action
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(4)  # rows are button-tall: even gaps whether a row has a button or not
        self.buttons: dict[str, QWidget] = {}
        self.rows: list[QWidget] = []
        self.marks: list[QLabel] = []

    def set_issues(self, issues: Sequence[PreflightIssue], profile: Profile | None = None) -> None:
        while self.lay.count():
            item = self.lay.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.buttons = {}
        self.rows, self.marks = [], []
        for issue in sorted_issues(issues):
            row = QWidget()
            row.setMinimumHeight(theme.CONTROL_H)
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(10)
            role = {IssueLevel.ERROR: "error", IssueLevel.WARNING: "body"}.get(issue.level, "secondary")
            mark = issue_icon(issue.level)
            h.addWidget(mark, 0, Qt.AlignmentFlag.AlignVCenter)
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
                h.addWidget(btn, 0, Qt.AlignmentFlag.AlignVCenter)
                self.buttons[issue.action] = btn
            self.lay.addWidget(row)
            self.rows.append(row)
            self.marks.append(mark)
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
        self.setMinimumWidth(600)  # the height follows the content (_fit_to_content)
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
        self.issue_scroll = scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self.issue_list)
        scroll.setVisible(bool(report.issues))
        lay.addWidget(scroll)  # no stretch: no blank band between the list and the checkbox
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
        self._fit_to_content()

    def _fit_to_content(self) -> None:
        """Make the sheet as tall as its content: the issue list without a scroll bar (up to
        SHEET_MAX_LIST of the screen height, then it scrolls) and no empty band above the
        checkbox / buttons. QScrollArea does not pass on the height-for-width of its word-wrapped
        rows, so the list height is measured at the width the list gets."""
        screen = self.screen() or QGuiApplication.primaryScreen()
        avail = screen.availableGeometry().height() if screen is not None else 800
        cap = max(160, int(avail * SHEET_MAX_LIST))
        self.issue_scroll.setMaximumHeight(cap)
        self.adjustSize()
        lay = self.layout()
        if lay is not None:
            lay.activate()
        # the scroll area's own width: its viewport is only resized once the sheet is shown
        width = self.issue_scroll.contentsRect().width()
        need = self.issue_list.heightForWidth(width) if self.issue_list.hasHeightForWidth() else -1
        if need < 0:
            need = self.issue_list.sizeHint().height()
        # fixed: the scroll area's size hint assumes a narrower width (more wrapped lines); the
        # sheet never gets narrower than now (minimum width), so the content height holds
        self.issue_scroll.setFixedHeight(min(need, cap))
        self.adjustSize()

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


__all__ = ["IssueList", "PreflightSheet", "hotkey_failure_text", "issue_icon", "issue_level_name", "issue_mark",
           "show_preflight_sheet", "sorted_issues"]
