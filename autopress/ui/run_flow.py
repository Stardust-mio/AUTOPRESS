# OWNED BY G7
"""The "開始兌換" sequence (SPEC section 2.4): build plan -> preflight sheet (errors block;
warnings need a click) -> confirm when more than Settings.confirm_run_over codes -> register
hotkeys (ctx.hotkeys: "pause_resume" -> this flow's pause / resume handling, "stop" -> cancel
the countdown or session.stop); a failed registration shows a warning DIALOG (繼續 / 取消) and
forces the mini bar on -> countdown overlay (hint: F9 and the failsafe corner) ->
MainWindow.set_run_mode(True) (minimised instead of hidden when the mini bar is disabled) +
MiniBar (placed with place_away_from, masked via session.set_masked_rects) -> session.start.

During the run (SPEC 2.6): F8 pauses (session.pause, idempotent); F8 or 繼續 while PAUSED calls
resume() - except within 1.5 s after an automatic pause, when F8 counts as "pause". An
Attention whose reason ``opens_main_window`` restores the main window on the Run page (the run
is already paused); 展開 on the bar requests a soft pause and restores the main window when
PAUSED. On finish: unregister hotkeys, hide the mini bar, set_masked_rects([]),
set_run_mode(False), summary toast, navigate to "run"; a TEST_ONE run whose code reached a
result (any final status except FAILED / REVIEW) stores ``profile.last_test_ok_at``.
Any page may own a RunFlow (Codes page and Run page do); an instance reacts only to the runs it
started. All its dialogs are parented to the main window or the mini bar."""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from typing import Any

from PyQt6.QtCore import QEventLoop, QObject, QTimer, pyqtSignal

from ..context import AppContext
from ..i18n import format_count, tr
from ..models import (
    Attention,
    CodeStatus,
    PauseReason,
    PlanMode,
    PreflightReport,
    Profile,
    Rect,
    RunPlan,
    RunSelection,
    RunState,
    RunSummary,
    StopReason,
    now_iso,
)
from . import run_sheet
from . import widgets as w
from .overlays import CountdownOverlay
from .run_actions import (
    active_flow,
    call,
    countdown_hint,
    dialog_parent,
    main_window,
    monitor_rect_for,
    perform_action,
    set_active_flow,
)

log = logging.getLogger(__name__)

_now = time.monotonic  # tests monkeypatch this
F8_AFTER_AUTO_PAUSE_S = 1.5  # SPEC 2.6 (UNVERIFIED constant, 11.14)
_NOT_A_RESULT = (CodeStatus.FAILED, CodeStatus.REVIEW, CodeStatus.PENDING, CodeStatus.RUNNING)


def summary_text(summary: RunSummary, counts: dict[CodeStatus, int], policy_failures: int) -> tuple[str, str]:
    """(toast text, kind) for a finished run (SPEC 7.1)."""
    parts = [f"{st.label()} {n}" for st, n in counts.items() if n]
    tail = tr("：", ": ") + tr("、", ", ").join(parts) if parts else ""
    reason = summary.stop_reason
    if reason is StopReason.RATE_LIMITED:
        return tr("偵測到「操作過於頻繁」，已停止。請稍後再試。", "Rate limit detected; stopped. Try again later."), "warning"
    if reason is StopReason.FAILURES:
        n = policy_failures
        return tr(f"連續 {n} 筆失敗，已停止。請檢查設定檔與目標視窗。",
                  f"{n} failures in a row; stopped. Check the profile and the target window."), "error"
    if reason is StopReason.FAILSAFE:
        return tr("滑鼠移到螢幕左上角，已緊急停止。", "Mouse moved to the top-left corner: emergency stop."), "warning"
    if reason is StopReason.COMPLETED:
        return tr("全部完成", "All done") + tail, "success"
    if reason is StopReason.USER:
        return tr("已停止", "Stopped") + tail, "info"
    text = reason.label()
    if summary.message:
        text += tr("：", ": ") + summary.message
    return text, "error"


class RunFlow(QObject):
    started = pyqtSignal()
    ended = pyqtSignal(object)  # RunSummary, or None when cancelled before the start

    def __init__(self, ctx: AppContext, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.minibar: Any = None
        self.countdown = CountdownOverlay(self)
        self.resume_countdown = CountdownOverlay(self)
        self.resume_countdown.done.connect(self._resume_now)
        self._active = False  # a run started by this flow is in progress
        self._starting = False  # inside begin()
        self._counting = False  # start countdown running
        self._plan: RunPlan | None = None
        self._report: PreflightReport | None = None
        self._mode = PlanMode.NORMAL
        self._registered = False
        self._bar_forced = False
        self._auto_pause_at = -1e9
        self._expand_pending = False
        self._main_hidden = False
        self._results: dict[str, CodeStatus] = {}
        self._codes: dict[str, str] = {}
        s = ctx.session
        s.state_changed.connect(self._on_state)
        s.progress.connect(self._on_progress)
        s.code_started.connect(self._on_code_started)
        s.step_started.connect(self._on_step_started)
        s.code_finished.connect(self._on_code_finished)
        s.waiting.connect(self._on_waiting)
        s.cooldown.connect(self._on_cooldown)
        s.attention.connect(self._on_attention)
        s.finished.connect(self._on_finished)
        ctx.hotkeys.triggered.connect(self._on_hotkey)

    # ================================================================ public
    def is_running(self) -> bool:
        return self._active

    def begin(self, profile: Profile, selection: RunSelection = RunSelection.UNFINISHED, *,
              code_ids: Sequence[str] | None = None, mode: PlanMode = PlanMode.NORMAL,
              target_hwnd: int = 0) -> bool:
        """Run the sequence; False if it was cancelled or blocked before session.start."""
        other = active_flow(self.ctx)
        if self._starting or self._active or (other is not None and other is not self) or \
                call(self.ctx.session.is_active, default=False):
            self.ctx.notify(tr("已有執行中的工作，請先停止。", "Something is already running; stop it first."), "warning")
            return False
        self._starting = True
        set_active_flow(self.ctx, self)
        try:
            ok = self._begin(profile, RunSelection(selection), list(code_ids) if code_ids is not None else None,
                             PlanMode(mode), int(target_hwnd or 0))
        except Exception:
            log.exception("starting the run failed")
            ok = False
            self.ctx.notify(tr("無法開始執行，詳情已記錄在紀錄檔。", "The run could not start; details are in the log."), "error")
        finally:
            self._starting = False
        if not ok:
            self._release_hotkeys()
            if not self._active:
                set_active_flow(self.ctx, None)
            self.ended.emit(None)
        return ok

    def resume(self) -> None:
        """Continue a paused run: hide the main window again (run mode), show the resume
        countdown (Settings.resume_countdown_s; F9 during it stops the run), then
        session.resume(). Physical input during the countdown is ignored because the runner
        resets its input baseline when it resumes (T14)."""
        other = active_flow(self.ctx)
        if other is not None and other is not self and hasattr(other, "resume"):
            other.resume()
            return
        state = self._state()
        if not self._active:
            if state is RunState.PAUSED:  # orphaned pause (no flow owns it): resume directly
                call(self.ctx.session.resume)
            return
        if state is not RunState.PAUSED or self.resume_countdown.is_running():
            return
        self._enter_run_mode()
        self.resume_countdown.start(self.ctx.settings.resume_countdown_s, self._target_monitor(),
                                    countdown_hint(self.ctx))

    def pause(self) -> None:
        """暫停 (button): soft pause, idempotent."""
        if self._active:
            call(self.ctx.session.pause)

    def toggle(self) -> None:
        """The pause / resume button of the Run page and the mini bar."""
        if self._state() is RunState.PAUSED:
            self.resume()
        else:
            self.pause()

    def stop(self) -> None:
        if self._counting:
            self.countdown.cancel()
        elif self.resume_countdown.is_running():
            self.resume_countdown.cancel()
            call(self.ctx.session.stop)
        elif self._active:
            call(self.ctx.session.stop)

    def expand(self) -> None:
        """展開 on the mini bar: soft pause first, the main window comes back when PAUSED."""
        if not self._active:
            return
        if self._state() is RunState.PAUSED:
            self._restore_main()
        else:
            self._expand_pending = True
            call(self.ctx.session.pause)

    # ================================================================ begin
    def _begin(self, profile: Profile, selection: RunSelection, code_ids: list[str] | None, mode: PlanMode,
               target_hwnd: int) -> bool:
        ctx = self.ctx
        while True:
            plan = ctx.session.build_plan(profile, ctx.settings, selection, code_ids=code_ids,
                                          target_hwnd=target_hwnd, mode=mode)
            report = ctx.session.preflight(plan)
            answer = run_sheet.show_preflight_sheet(ctx, report, plan, dialog_parent(ctx))
            if answer == "start":
                break
            if not answer or not answer.startswith("action:"):
                return False
            action = answer.split(":", 1)[1]
            if action == "test_one":
                ids = [plan.items[0].code_id] if plan.items else None
                QTimer.singleShot(0, lambda p=profile, i=ids: self.begin(p, mode=PlanMode.TEST_ONE, code_ids=i))
                return False
            if action in ("open_profile", "realign", "restart_admin"):
                QTimer.singleShot(0, lambda a=action, p=profile: perform_action(ctx, a, p, dialog_parent(ctx), self))
                return False
            perform_action(ctx, action, profile, dialog_parent(ctx), self)
            stored = ctx.profiles.get(profile.id)  # the action may have changed the target
            if stored is not None:
                profile = stored
        if not report.ok:
            return False
        if not plan.items:
            w.message(dialog_parent(ctx), tr("開始兌換", "Start"),
                      tr("沒有可以執行的序號。", "There are no codes to run."), "info")
            return False
        n = len(plan.items)
        limit = ctx.settings.confirm_run_over
        if mode is PlanMode.NORMAL and limit > 0 and n > limit:
            if not w.confirm(dialog_parent(ctx), tr("開始兌換", "Start"),
                             tr(f"這次會輸入 {format_count(n)}序號，確定要開始嗎？", f"This run enters {format_count(n)}. Start?"),
                             tr("開始", "Start"), tr("取消", "Cancel")):
                return False
        if not self._register_hotkeys():
            return False
        self._plan, self._report, self._mode = plan, report, mode
        self._results, self._codes = {}, {item.code_id: item.code for item in plan.items}
        if not self._run_countdown(ctx.settings.countdown_s):
            return False
        self._active = True
        self._auto_pause_at = -1e9
        self._expand_pending = False
        self._enter_run_mode(first=True)
        try:
            ctx.session.start(plan)
        except (RuntimeError, NotImplementedError) as exc:
            log.warning("session.start refused: %s", exc)
            self._teardown()
            self._active = False
            ctx.notify(tr("無法開始執行，可能已有其他工作在執行。", "The run could not start; something else may be running."), "error")
            return False
        self.started.emit()
        return True

    def _register_hotkeys(self) -> bool:
        hk = self.ctx.settings.hotkeys
        failed: list[tuple[str, Any]] = []
        for action, combo in (("pause_resume", hk.pause_resume), ("stop", hk.stop)):
            res = self.ctx.hotkeys.register(action, combo)
            if not getattr(res, "ok", False):
                failed.append((combo, res))
        self._registered = True
        self._bar_forced = False
        if not failed:
            return True
        text = "\n".join(run_sheet.hotkey_failure_text(combo, getattr(res, "error", 0), getattr(res, "message", ""))
                         for combo, res in failed)
        if not w.confirm(dialog_parent(self.ctx), tr("快捷鍵無法使用", "Hotkeys unavailable"), text,
                         tr("繼續", "Continue"), tr("取消", "Cancel")):
            self._release_hotkeys()
            return False
        self._bar_forced = True
        return True

    def _release_hotkeys(self) -> None:
        if self._registered:
            call(self.ctx.hotkeys.unregister, "pause_resume")
            call(self.ctx.hotkeys.unregister, "stop")
        self._registered = False

    def _run_countdown(self, seconds: int) -> bool:
        loop = QEventLoop()
        box: dict[str, bool] = {}

        def done() -> None:
            box["ok"] = True
            loop.quit()

        def cancelled() -> None:
            box["ok"] = False
            loop.quit()

        self.countdown.done.connect(done)
        self.countdown.cancelled.connect(cancelled)
        self._counting = True
        try:
            self.countdown.start(seconds, self._target_monitor(), countdown_hint(self.ctx))
            if "ok" not in box:
                loop.exec()
        finally:
            self._counting = False
            self.countdown.done.disconnect(done)
            self.countdown.cancelled.disconnect(cancelled)
        return box.get("ok", False)

    # ================================================================ run mode / mini bar
    def _use_bar(self) -> bool:
        return bool(self.ctx.settings.minibar_enabled or self._bar_forced)

    def _target_rect(self) -> Rect | None:
        rep = self._report
        if rep is not None and rep.target is not None and rep.target.client[2] > 0:
            return tuple(rep.target.client)  # type: ignore[return-value]
        hwnd = self._plan.target_hwnd if self._plan is not None else 0
        if hwnd:
            from ..win32 import windows

            rect = call(windows.client_rect, hwnd)
            if rect:
                return tuple(rect)  # type: ignore[return-value]
        return None

    def _target_monitor(self) -> Rect | None:
        return monitor_rect_for(self._target_rect())

    def _enter_run_mode(self, first: bool = False) -> None:
        mw = main_window(self.ctx)
        use_bar = self._use_bar()
        if mw is not None and hasattr(mw, "set_run_mode"):
            call(mw.set_run_mode, True, minimize=not use_bar)
        self._main_hidden = True
        if use_bar:
            self._show_bar(first)

    def _show_bar(self, first: bool) -> None:
        from .minibar import MiniBar

        if self.minibar is None:
            self.minibar = MiniBar(self.ctx)
            self.minibar.pauseClicked.connect(self.toggle)
            self.minibar.stopClicked.connect(self.stop)
            self.minibar.expandClicked.connect(self.expand)
            self.minibar.moved.connect(self._publish_mask)
        bar = self.minibar
        if first:
            bar.reset()
            bar.set_state(RunState.STARTING.value)
            bar.set_progress(0, len(self._plan.items) if self._plan else 0, -1.0)
        avoid: list[Rect] = []
        if self._plan is not None and self._plan.target_hwnd:
            from ..runner import preview

            marks = call(preview.preview_profile, self._plan.profile, self._plan.target_hwnd, default=[]) or []
            avoid = [tuple(m.rect) for m in marks]  # type: ignore[misc]
        bar.place_away_from(avoid, self._target_rect())
        bar.show()
        from ..win32 import windows

        call(windows.exclude_from_capture, int(bar.winId()), True)
        self._publish_mask()

    def _publish_mask(self) -> None:
        bar = self.minibar
        rects = [bar.frame_rect_physical()] if bar is not None and bar.isVisible() else []
        call(self.ctx.session.set_masked_rects, rects)

    def _hide_bar(self) -> None:
        if self.minibar is not None:
            self.minibar.hide()
        call(self.ctx.session.set_masked_rects, [])

    def _restore_main(self) -> None:
        self._hide_bar()
        mw = main_window(self.ctx)
        if mw is not None and hasattr(mw, "set_run_mode"):
            call(mw.set_run_mode, False)
        self._main_hidden = False
        self.ctx.navigate("run")

    def _teardown(self) -> None:
        self._release_hotkeys()
        if self.resume_countdown.is_running():
            self.resume_countdown.cancel()
        self._hide_bar()
        mw = main_window(self.ctx)
        if mw is not None and hasattr(mw, "set_run_mode"):
            call(mw.set_run_mode, False)
        self._main_hidden = False
        set_active_flow(self.ctx, None)

    # ================================================================ session signals
    def _state(self) -> RunState:
        try:
            return RunState(self.ctx.session.state)
        except Exception:
            return RunState.IDLE

    def _on_state(self, state: str, reason: str) -> None:
        if not self._active:
            return
        if self.minibar is not None:
            self.minibar.set_state(state, reason)
        if state == RunState.PAUSED.value:
            if reason and reason != PauseReason.USER.value:
                self._auto_pause_at = _now()
            if self._expand_pending:
                self._expand_pending = False
                self._restore_main()

    def _on_progress(self, done: int, total: int, eta: float) -> None:
        if self._active and self.minibar is not None:
            self.minibar.set_progress(done, total, eta)

    def _code_text(self, code_id: str) -> str:
        item = call(self.ctx.queue.get, code_id)
        return item.code if item is not None else self._codes.get(code_id, "")

    def _on_code_started(self, code_id: str, _index: int) -> None:
        if self._active and self.minibar is not None:
            self.minibar.set_current(self._code_text(code_id))
            self.minibar.set_waiting(0)

    def _on_step_started(self, code_id: str, _index: int, title: str) -> None:
        if self._active and self.minibar is not None:
            self.minibar.set_current(self._code_text(code_id), title)

    def _on_code_finished(self, code_id: str, record: Any) -> None:
        if not self._active:
            return
        status = getattr(record, "status", None)
        if isinstance(status, CodeStatus):
            self._results[code_id] = status
            # PENDING (interrupted before submitting) and COOLDOWN (rate-limited) attempts are
            # retried: they are not results (integration; G4 emits code_finished for every attempt)
            if self.minibar is not None and status not in (CodeStatus.PENDING, CodeStatus.COOLDOWN):
                self.minibar.add_result(status)

    def _on_waiting(self, seconds: float) -> None:
        if self._active and self.minibar is not None:
            self.minibar.set_waiting(seconds)

    def _on_cooldown(self, seconds: float) -> None:
        if self._active and self.minibar is not None:
            self.minibar.set_cooldown(seconds)

    def _on_attention(self, att: Any) -> None:
        if not self._active or not isinstance(att, Attention):
            return
        if PauseReason(att.kind).opens_main_window:
            self._restore_main()

    def _on_finished(self, summary: Any) -> None:
        if not self._active:
            return
        self._active = False
        self._teardown()
        if isinstance(summary, RunSummary):
            counts = {st: n for st, n in summary.counts.items() if n} if summary.counts else {}
            if not counts:
                for st in self._results.values():
                    counts[st] = counts.get(st, 0) + 1
            failures = self._plan.profile.policy.stop_after_failures if self._plan is not None else 0
            text, kind = summary_text(summary, counts, failures)
            self.ctx.notify(text, kind)
        if self._mode is PlanMode.TEST_ONE and self._plan is not None:
            if any(st not in _NOT_A_RESULT for st in self._results.values()):
                self._store_test_ok(self._plan.profile.id)
        self.ctx.navigate("run")
        self.ended.emit(summary)

    def _store_test_ok(self, profile_id: str) -> None:
        stored = self.ctx.profiles.get(profile_id)
        if stored is None:
            return
        stored.last_test_ok_at = now_iso()
        try:
            self.ctx.profiles.save(stored, touch=False)
        except OSError as exc:
            log.warning("saving last_test_ok_at failed: %s", exc)
            return
        self.ctx.signals.profiles_changed.emit()

    # ================================================================ hotkeys / buttons
    def _on_hotkey(self, action: str) -> None:
        if action == "stop":
            if self._counting or self._active:
                self.stop()
            return
        if action != "pause_resume" or not self._active or self._counting or self.resume_countdown.is_running():
            return
        state = self._state()
        if state is RunState.PAUSED:
            if _now() - self._auto_pause_at < F8_AFTER_AUTO_PAUSE_S:
                call(self.ctx.session.pause)  # the key press itself tripped the input guard: stays paused
            else:
                self.resume()
        elif state in (RunState.RUNNING, RunState.COOLDOWN, RunState.STARTING, RunState.PAUSING):
            call(self.ctx.session.pause)

    def _resume_now(self) -> None:
        if self._active and self._state() is RunState.PAUSED:
            call(self.ctx.session.resume)
