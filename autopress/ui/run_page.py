# OWNED BY G7
"""Run page (SPEC section 6.4.3): active profile, target window (change / refresh), selection
(全部未完成 / 只跑勾選的), preflight issue list with action buttons (restart_admin, pick_window,
preview, open_profile, wait_ocr, assign_codes, test_one, realign), 開始兌換 / 測試一筆 /
預覽點位; while running: ProgressRing, n / N, ETA, current code and step, state chip,
暫停／繼續 (F8) and 停止 (F9) with keycaps, live log, result counts; attention panel (shown when
RunFlow restores the main window for a paused run): reason, OCR text, evidence, 標記為…,
加入關鍵字…, 開啟紀錄檔 (errors), 繼續 (RunFlow.resume: countdown) / 停止; finished summary with
匯出結果 and 重試失敗項目."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PyQt6.QtWidgets import QComboBox, QDialog, QFileDialog, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from .. import paths
from ..context import AppContext
from ..i18n import format_count, tr
from ..models import (
    Attention,
    CodeStatus,
    LogEntry,
    LogLevel,
    PlanMode,
    Profile,
    RunSelection,
    RunState,
    RunSummary,
    StepTestResult,
    status_for_result,
)
from . import widgets as w
from .profiles_editor import card
from .run_actions import (
    active_flow,
    apply_target,
    call,
    find_target,
    first_runnable,
    perform_action,
    show_preview,
)
from .run_sheet import IssueList
from .run_widgets import AttentionPanel, KeywordDialog, LogView, RunningCard, SummaryCard

log = logging.getLogger(__name__)


def ask_csv_path(parent: QWidget | None, default_name: str) -> str:
    path, _f = QFileDialog.getSaveFileName(parent, tr("匯出結果", "Export results"), default_name, "CSV (*.csv)")
    if path and not path.lower().endswith(".csv"):
        path += ".csv"
    return path


class RunPage(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self._flow: Any = None
        self._report: Any = None
        self._summary: RunSummary | None = None
        self._run_counts: dict[CodeStatus, int] = {}
        self._run_id = ""
        self._state = RunState.IDLE.value
        self._recheck_timer = QTimer(self)
        self._recheck_timer.setSingleShot(True)
        self._recheck_timer.setInterval(400)
        self._recheck_timer.timeout.connect(self.recheck)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(16)
        lay.addWidget(w.section_header(tr("執行", "Run"), tr("檢查設定、開始兌換，並即時查看每一筆的結果。",
                                                           "Check the setup, start redeeming and follow every code live.")))
        hk = ctx.settings.hotkeys
        self.running = RunningCard(hk.pause_resume, hk.stop)
        self.running.pauseClicked.connect(self._toggle_pause)
        self.running.stopClicked.connect(self._stop)
        self.running.hide()
        lay.addWidget(self.running)
        self.paused_banner = w.Banner("warning", "", tr("繼續", "Resume"), False)
        self.paused_banner.actionClicked.connect(self._resume)
        self.paused_banner.hide()
        lay.addWidget(self.paused_banner)
        self.attention = AttentionPanel(lambda: paths.data_dir(create=False))
        self.attention.markClicked.connect(self._mark)
        self.attention.addKeywordClicked.connect(self._add_keyword)
        self.attention.openLogClicked.connect(self._open_log)
        self.attention.resumeClicked.connect(self._resume)
        self.attention.stopClicked.connect(self._stop)
        self.attention.hide()
        lay.addWidget(self.attention)
        self.summary = SummaryCard()
        self.summary.exportClicked.connect(self.export_results)
        self.summary.retryClicked.connect(self._retry_failed)
        self.summary.hide()
        lay.addWidget(self.summary)
        lay.addWidget(self._build_setup())
        self.preflight_card, pl = card(tr("開始前檢查", "Pre-flight check"))
        self.issues = IssueList(self._on_action)
        pl.addWidget(self.issues)
        self.preflight_empty = w.label("", "muted")
        self.preflight_empty.setWordWrap(True)
        pl.addWidget(self.preflight_empty)
        lay.addWidget(self.preflight_card)
        log_card, ll = card(tr("即時紀錄", "Live log"))
        self.log_view = LogView()
        ll.addWidget(self.log_view)
        lay.addWidget(log_card)
        lay.addStretch(1)

        s = ctx.session
        s.state_changed.connect(self._on_state)
        s.progress.connect(self._on_progress)
        s.code_started.connect(self._on_code_started)
        s.step_started.connect(self._on_step_started)
        s.code_finished.connect(self._on_code_finished)
        s.log.connect(self._on_log)
        s.cooldown.connect(self._on_cooldown)
        s.waiting.connect(self._on_waiting)
        s.attention.connect(self._on_attention)
        s.finished.connect(self._on_finished)
        s.test_finished.connect(self._on_test_finished)
        ctx.signals.active_profile_changed.connect(lambda _id: self._profile_changed())
        ctx.signals.profiles_changed.connect(self._profile_changed)
        try:
            ctx.ocr.state_changed.connect(lambda _s: self.schedule_recheck())
        except Exception:  # pragma: no cover - fake without the signal
            pass
        try:
            self._unsubscribe = ctx.queue.subscribe(lambda _e: self.schedule_recheck())
        except Exception as exc:  # G1 stub
            log.debug("queue.subscribe unavailable: %s", exc)
        QShortcut(QKeySequence("F5"), self, activated=self.refresh_target)
        self._profile_changed()
        self._recheck_timer.stop()
        self.recheck()

    # ================================================================ building
    def _build_setup(self) -> QWidget:
        c, lay = card(tr("這次要跑什麼", "What to run"))
        row = QHBoxLayout()
        row.addWidget(w.label(tr("設定檔", "Profile"), "secondary"))
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(260)
        self.profile_combo.currentIndexChanged.connect(self._combo_changed)
        row.addWidget(self.profile_combo)
        self.edit_btn = w.push_button(tr("編輯", "Edit"), "ghost", "edit")
        self.edit_btn.clicked.connect(lambda: self.profile() and perform_action(self.ctx, "open_profile", self.profile()))
        row.addWidget(self.edit_btn)
        row.addStretch(1)
        lay.addLayout(row)
        trow = QHBoxLayout()
        trow.addWidget(w.label(tr("目標視窗", "Target window"), "secondary"))
        self.target_label = w.label("", "body")
        trow.addWidget(self.target_label, 1)
        self.change_target_btn = w.push_button(tr("變更", "Change"), "secondary", "window")
        self.change_target_btn.clicked.connect(self.change_target)
        trow.addWidget(self.change_target_btn)
        self.refresh_btn = w.icon_button("refresh", tr("重新整理（F5）", "Refresh (F5)"))
        self.refresh_btn.clicked.connect(self.refresh_target)
        trow.addWidget(self.refresh_btn)
        lay.addLayout(trow)
        srow = QHBoxLayout()
        srow.addWidget(w.label(tr("要跑的序號", "Codes to run"), "secondary"))
        self.selection = w.SegmentedControl([RunSelection.UNFINISHED.label(), RunSelection.CHECKED.label()],
                                            0 if self.ctx.settings.run_selection is RunSelection.UNFINISHED else 1)
        self.selection.currentChanged.connect(self._selection_changed)
        srow.addWidget(self.selection)
        self.count_label = w.label("", "muted")
        srow.addWidget(self.count_label)
        srow.addStretch(1)
        lay.addLayout(srow)
        brow = QHBoxLayout()
        self.hint = w.label("", "muted")
        self.hint.setWordWrap(True)
        brow.addWidget(self.hint, 1)
        self.preview_btn = w.push_button(tr("預覽點位", "Preview positions"), "secondary", "eye")
        self.preview_btn.clicked.connect(self.preview)
        brow.addWidget(self.preview_btn)
        self.recheck_btn = w.push_button(tr("重新檢查", "Check again"), "ghost", "refresh")
        self.recheck_btn.clicked.connect(self.recheck)
        brow.addWidget(self.recheck_btn)
        self.test_btn = w.push_button(tr("測試一筆", "Test one"), "secondary", "flask")
        self.test_btn.clicked.connect(self.test_one)
        brow.addWidget(self.test_btn)
        self.start_btn = w.push_button(tr("開始兌換", "Start"), "primary", "play")
        self.start_btn.clicked.connect(self.start_run)
        brow.addWidget(self.start_btn)
        lay.addLayout(brow)
        self.setup_card = c
        return c

    # ================================================================ state
    def profile(self) -> Profile | None:
        return self.ctx.active_profile()

    def selection_value(self) -> RunSelection:
        return RunSelection.CHECKED if self.selection.currentIndex() == 1 else RunSelection.UNFINISHED

    def run_flow(self) -> Any:
        if self._flow is None:
            from .run_flow import RunFlow

            self._flow = RunFlow(self.ctx, self)
            self._flow.ended.connect(lambda _s: self.schedule_recheck())
        return self._flow

    def _controller(self) -> Any:
        return active_flow(self.ctx) or self._flow

    def _profile_changed(self) -> None:
        profiles = call(self.ctx.profiles.list, default=[]) or []
        active = self.ctx.settings.active_profile_id
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItem(tr("（未選擇）", "(none)"), "")
        for p in profiles:
            self.profile_combo.addItem(f"{p.name} · {p.game}" if p.game else p.name, p.id)
        self.profile_combo.setCurrentIndex(max(0, self.profile_combo.findData(active)))
        self.profile_combo.blockSignals(False)
        self.refresh_target()

    def _combo_changed(self) -> None:
        pid = self.profile_combo.currentData() or ""
        self.ctx.set_active_profile(pid)

    def _selection_changed(self, _i: int) -> None:
        sel = self.selection_value()
        if self.ctx.settings.run_selection is not sel:
            self.ctx.settings.run_selection = sel
            self.ctx.save_settings()
        self.schedule_recheck()

    def refresh_target(self) -> None:
        p = self.profile()
        if p is None:
            self.target_label.setText(tr("—", "-"))
        elif p.target.is_empty():
            self.target_label.setText(tr("尚未選擇目標視窗", "No target window yet"))
        else:
            info = find_target(p)
            self.target_label.setText(tr(f"{info.title}（已找到）", f"{info.title} (found)") if info is not None
                                      else tr(f"找不到目標視窗：{p.target.describe()}", f"Target window not found: {p.target.describe()}"))
        self.schedule_recheck()

    def schedule_recheck(self) -> None:
        self._recheck_timer.start()

    def _counts_for(self, p: Profile) -> tuple[int, int]:
        unfinished = call(self.ctx.queue.runnable, RunSelection.UNFINISHED, p.game_key(), default=[]) or []
        checked = call(self.ctx.queue.runnable, RunSelection.CHECKED, p.game_key(), default=[]) or []
        return len(unfinished), len(checked)

    def recheck(self) -> None:
        """Run build_plan + preflight for the active profile (only while no run is active)."""
        p = self.profile()
        active = bool(call(self.ctx.session.is_active, default=False))
        for b in (self.start_btn, self.test_btn, self.preview_btn, self.change_target_btn, self.edit_btn):
            b.setEnabled(p is not None and not active)
        if p is None:
            self.hint.setText(tr("先建立或選擇設定檔，才能開始兌換。", "Create or choose a profile to start redeeming."))
            self.count_label.setText("")
            self.issues.set_issues([])
            self.preflight_empty.setText(tr("選擇設定檔後會在這裡顯示檢查結果。", "The check appears here once a profile is chosen."))
            return
        n_all, n_checked = self._counts_for(p)
        self.count_label.setText(tr(f"未完成 {n_all} 筆 · 勾選 {n_checked} 筆", f"{n_all} unfinished · {n_checked} checked"))
        count = n_checked if self.selection_value() is RunSelection.CHECKED else n_all
        self.start_btn.setEnabled(not active and count > 0)
        self.test_btn.setEnabled(not active and n_all > 0)
        self.hint.setText("" if count else tr(f"沒有「{p.game or p.name}」可以執行的序號。請先到「序號」頁加入序號。",
                                              f"No runnable codes for '{p.game or p.name}'. Add codes on the Codes page."))
        if active:
            return
        try:
            plan = self.ctx.session.build_plan(p, self.ctx.settings, self.selection_value())
            self._report = self.ctx.session.preflight(plan)
        except NotImplementedError:
            self._report = None
            self.issues.set_issues([])
            self.preflight_empty.setText(tr("開始前檢查尚未實作。", "The pre-flight check is not implemented yet."))
            return
        except Exception as exc:
            log.warning("preflight failed: %s", exc)
            self._report = None
            self.issues.set_issues([])
            self.preflight_empty.setText(tr(f"檢查失敗：{exc}", f"The check failed: {exc}"))
            return
        self.issues.set_issues(self._report.issues, p)
        self.preflight_empty.setText("" if self._report.issues else tr("一切就緒。", "Everything is ready."))

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.schedule_recheck()

    # ================================================================ actions
    def _on_action(self, action: str) -> None:
        p = self.profile()
        if p is None:
            return
        if action == "test_one":
            self.test_one()
            return
        if perform_action(self.ctx, action, p, self.window(), self.run_flow()):
            self.refresh_target()

    def start_run(self) -> bool:
        p = self.profile()
        if p is None:
            return False
        try:
            return bool(self.run_flow().begin(p, self.selection_value()))
        except NotImplementedError:
            self.ctx.notify(tr("尚未實作", "Not implemented yet"), "warning")
            return False

    def test_one(self) -> bool:
        p = self.profile()
        if p is None:
            return False
        cid = first_runnable(self.ctx, p)
        if cid is None:
            self.ctx.notify(tr("沒有可以測試的序號。", "There is no code to test."), "info")
            return False
        return bool(self.run_flow().begin(p, self.selection_value(), code_ids=[cid], mode=PlanMode.TEST_ONE))

    def preview(self) -> None:
        p = self.profile()
        if p is not None:
            show_preview(self.ctx, p, parent=self.window())

    def change_target(self) -> None:
        p = self.profile()
        if p is None:
            return
        from .window_picker import pick_target_window

        info = pick_target_window(self.ctx, p.target, self.window(), suggested_exe=p.suggested_exe)
        if info is not None:
            apply_target(self.ctx, p.id, info)
            self.refresh_target()

    def _toggle_pause(self) -> None:
        flow = self._controller()
        if flow is not None and getattr(flow, "is_running", lambda: False)():
            flow.toggle()
        elif self._state == RunState.PAUSED.value:
            call(self.ctx.session.resume)
        else:
            call(self.ctx.session.pause)

    def _resume(self) -> None:
        flow = self._controller() or self.run_flow()
        flow.resume()

    def _stop(self) -> None:
        flow = self._controller()
        if flow is not None and getattr(flow, "is_running", lambda: False)():
            flow.stop()
        else:
            call(self.ctx.session.stop)

    def _mark(self, status: CodeStatus) -> None:
        att = self.attention.attention
        if att is None or not att.code_id:
            return
        call(self.ctx.session.resolve_attention, att.code_id, CodeStatus(status), att.ocr_text)
        self.attention.mark_resolved(CodeStatus(status))

    def _add_keyword(self) -> None:
        att = self.attention.attention
        plan = getattr(self.ctx.session, "plan", None)
        pid = plan.profile.id if plan is not None else self.ctx.settings.active_profile_id
        stored = self.ctx.profiles.get(pid) if pid else None
        if att is None or stored is None:
            return
        dlg = KeywordDialog(att.ocr_text, self.window())
        try:
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            cls, keyword = dlg.result_class(), dlg.keyword()
        finally:
            dlg.deleteLater()
        self.add_keyword_to_profile(stored, cls, keyword)
        if att.code_id:
            self._mark(status_for_result(cls))

    def add_keyword_to_profile(self, profile: Profile, cls: Any, keyword: str) -> None:
        """Append a keyword to the stored profile, save it and give it to the running session."""
        from .keywords_editor import KeywordsEditor

        editor = KeywordsEditor()
        editor.set_config(profile.keywords)
        editor.add_keyword(cls, keyword)
        profile.keywords = editor.config()
        editor.deleteLater()
        self.ctx.profiles.save(profile)
        self.ctx.signals.profiles_changed.emit()
        call(self.ctx.session.update_keywords, profile.keywords)
        self.ctx.notify(tr(f"已把「{keyword}」加入「{cls.label()}」", f"Added '{keyword}' to '{cls.label()}'"), "success")

    def _open_log(self) -> None:
        try:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.logs_dir())))
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("opening the log folder failed: %s", exc)

    def _retry_failed(self) -> None:
        n = call(self.ctx.queue.retry_failed, default=0) or 0
        self.ctx.notify(tr(f"已把 {n} 筆失敗的序號改回待兌換", f"{n} failed codes are pending again"), "success")
        self.summary.retry_btn.setEnabled(False)
        self.schedule_recheck()

    def export_results(self) -> None:
        run_id = self._summary.run_id if self._summary is not None else self._run_id
        records = [r for r in (call(self.ctx.history.records, default=[]) or []) if not run_id or r.run_id == run_id]
        if not records:
            self.ctx.notify(tr("這次執行沒有可以匯出的結果。", "This run has no results to export."), "info")
            return
        path = ask_csv_path(self.window(), "autopress-results.csv")
        if not path:
            return
        try:
            from ..codes import csvexport

            csvexport.export_history_csv(Path(path), records)
        except NotImplementedError:
            self.ctx.notify(tr("匯出 CSV 尚未實作", "CSV export is not implemented yet"), "warning")
            return
        except OSError as exc:
            self.ctx.notify(str(exc), "error")
            return
        self.ctx.notify(tr(f"已匯出 {format_count(len(records))}結果", f"Exported {len(records)} results"), "success")

    # ================================================================ session signals
    def _on_state(self, state: str, reason: str) -> None:
        plan = getattr(self.ctx.session, "plan", None)
        if plan is not None and getattr(plan, "mode", None) is PlanMode.TEST_STEP:
            return  # a step test of the Profiles page, not a run
        self._state = state
        active = state not in (RunState.IDLE.value, RunState.FINISHED.value)
        self.running.setVisible(active)
        self.preflight_card.setVisible(not active)
        self.running.set_state(state)
        if active:
            self.summary.hide()
        paused = state == RunState.PAUSED.value
        if paused:
            from .minibar import pause_text

            self.paused_banner.setText(pause_text(reason) if reason else RunState.PAUSED.label())
        self.paused_banner.setVisible(paused and self.attention.isHidden())
        if not paused:
            self.attention.hide()
        if state == RunState.RUNNING.value and not self._run_id:
            plan = getattr(self.ctx.session, "plan", None)
            self._run_id = plan.run_id if plan is not None else ""
        if not active:
            self.schedule_recheck()
        for b in (self.start_btn, self.test_btn, self.preview_btn, self.change_target_btn, self.edit_btn):
            b.setEnabled(not active and self.profile() is not None)

    def _on_progress(self, done: int, total: int, eta: float) -> None:
        self.running.set_progress(done, total, eta)

    def _on_code_started(self, code_id: str, _index: int) -> None:
        item = call(self.ctx.queue.get, code_id)
        self.running.code.setText(item.code if item is not None else "")
        self.running.step.setText("")
        self.running.info.setText("")

    def _on_step_started(self, _code_id: str, index: int, title: str) -> None:
        self.running.step.setText(tr(f"第 {index + 1} 步：{title}", f"Step {index + 1}: {title}"))

    def _on_code_finished(self, _code_id: str, record: Any) -> None:
        status = getattr(record, "status", None)
        if isinstance(status, CodeStatus) and status not in (CodeStatus.PENDING, CodeStatus.COOLDOWN):
            # retried attempts (interrupted before submitting, rate-limited) are not results
            self._run_counts[status] = self._run_counts.get(status, 0) + 1
            self.running.counts.set_counts(self._run_counts)

    def _on_log(self, entry: Any) -> None:
        if isinstance(entry, LogEntry):
            self.log_view.add_entry(entry)

    def _on_cooldown(self, seconds: float) -> None:
        s = max(0, round(seconds))
        self.running.info.setText(tr(f"偵測到「操作過於頻繁」，{s} 秒後重試這筆序號。", f"Rate limit detected; retrying this code in {s} s.")
                                  if s else "")

    def _on_waiting(self, seconds: float) -> None:
        s = max(0, round(seconds))
        self.running.info.setText(tr(f"下一筆 {s} 秒後", f"Next code in {s} s") if s else "")

    def _on_attention(self, att: Any) -> None:
        if isinstance(att, Attention):
            self.attention.show_attention(att)
            self.paused_banner.hide()

    def _on_finished(self, summary: Any) -> None:
        self._state = RunState.FINISHED.value
        self.running.hide()
        self.paused_banner.hide()
        self.attention.hide()
        if isinstance(summary, RunSummary):
            self._summary = summary
            counts = {st: n for st, n in summary.counts.items() if n} if summary.counts else dict(self._run_counts)
            self.summary.show_summary(summary, counts)
        self._run_counts = {}
        self._run_id = ""
        self.schedule_recheck()

    def _on_test_finished(self, result: Any) -> None:
        if isinstance(result, StepTestResult):
            level = LogLevel.SUCCESS if result.ok else LogLevel.WARNING
            self.log_view.add_entry(LogEntry(level=level, message=tr(f"步驟測試：{result.message}", f"Step test: {result.message}"),
                                             step_index=result.step_index))


__all__ = ["RunPage", "ask_csv_path"]

