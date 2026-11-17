# OWNED BY G7
"""「測試此步驟」 on the Profiles page (SPEC 6.4.2, 2.7 rule 4; private helper of
ui.profiles_page).

Dry runs (default) call RunSession.test_step(dry_run=True) at once: geometry and OCR, no input.
A real test asks the first time 「會真的對目標視窗輸入」, warns when the step submits the sample
code (index >= Profile.first_submit_index()), registers the stop hotkey for the test, shows
the countdown on the target's monitor and only then calls test_step(dry_run=False); 停止測試
and the stop hotkey call session.stop(). The main window is minimised while a step that clicks,
types or reads the screen runs, so AutoPress itself never covers the target."""

from __future__ import annotations

import logging
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QWidget

from ..context import AppContext
from ..i18n import tr
from ..models import Profile, StepTestResult, StepType, TypeCodeParams, clone
from . import widgets as w
from .overlays import CountdownOverlay
from .run_actions import call, countdown_hint, find_target, main_window, monitor_rect_for, window_not_found_text

log = logging.getLogger(__name__)

_CONFIRMED = "g7.real_step_test_confirmed"


def submits_text(code: str) -> str:
    """SPEC 7.1 'real step test submits'."""
    return tr(f"這一步會送出測試序號「{code}」；有些服務會把它算成一次錯誤嘗試。",
              f"This step submits the test code \"{code}\"; some services count it as a failed attempt.")


class StepTestController(QObject):
    started = pyqtSignal(bool)  # True = real test (countdown running), False = dry run
    finished = pyqtSignal(object)  # StepTestResult, or None when cancelled / stopped

    def __init__(self, ctx: AppContext, parent_widget: QWidget | None = None) -> None:
        super().__init__(parent_widget)
        self.ctx = ctx
        self.parent_widget = parent_widget
        self.countdown = CountdownOverlay(self)
        self.countdown.done.connect(self._countdown_done)
        self.countdown.cancelled.connect(self._countdown_cancelled)
        self._active = False
        self._real = False
        self._testing = False  # test_step was called
        self._hotkey = False
        self._minimized = False
        self._pending: tuple[Profile, int, str, int] | None = None
        ctx.session.test_finished.connect(self._on_test_finished)
        ctx.session.finished.connect(self._on_session_finished)
        ctx.hotkeys.triggered.connect(self._on_hotkey)

    def is_active(self) -> bool:
        return self._active

    def is_real(self) -> bool:
        return self._active and self._real

    # -- start ----------------------------------------------------------------------------
    def start(self, profile: Profile, index: int, *, dry_run: bool = True, sample_code: str = "TEST-1234") -> bool:
        parent = self.parent_widget
        if self._active or call(self.ctx.session.is_active, default=False):
            self.ctx.notify(tr("已有執行中的工作，請先停止。", "Something is already running; stop it first."), "warning")
            return False
        if not 0 <= index < len(profile.steps):
            return False
        step = profile.steps[index]
        info = find_target(profile)
        if info is None:
            w.message(parent, tr("測試此步驟", "Test this step"), window_not_found_text(profile), "warning")
            return False
        if not dry_run:
            if not self.ctx.extras.get(_CONFIRMED):
                if not w.confirm(parent, tr("真的執行這一步", "Run this step for real"),
                                 tr("會真的對目標視窗輸入：這一步的點擊或按鍵會送到目標視窗。要繼續嗎？",
                                    "This sends real input: the step's clicks or keys go to the target window. Continue?"),
                                 tr("繼續", "Continue"), tr("取消", "Cancel")):
                    return False
                self.ctx.extras[_CONFIRMED] = True
            fsi = profile.first_submit_index()
            if step.type.sends_input and 0 <= fsi <= index:
                if not w.confirm(parent, tr("測試此步驟", "Test this step"), submits_text(sample_code),
                                 tr("仍要測試", "Test anyway"), tr("取消", "Cancel")):
                    return False
        self._active, self._real, self._testing = True, not dry_run, False
        self._pending = (clone(profile), index, sample_code, info.hwnd)
        uses_screen = (step.type.sends_input or step.type.uses_ocr
                       or (step.type is StepType.TYPE_CODE and isinstance(step.params, TypeCodeParams)
                           and step.params.verify_region is not None))
        if dry_run:
            self._minimize(uses_screen)
            self.started.emit(False)
            self._run_test(dry_run=True)
            return True
        res = self.ctx.hotkeys.register("stop", self.ctx.settings.hotkeys.stop)
        self._hotkey = bool(getattr(res, "ok", False))
        if not self._hotkey:
            combo = self.ctx.settings.hotkeys.stop
            if not w.confirm(parent, tr("快捷鍵無法使用", "Hotkey unavailable"),
                             tr(f"快捷鍵 {combo} 已被其他程式使用，請在設定中更換；這次測試請用「停止測試」或左上角緊急停止。",
                                f"Hotkey {combo} is used by another program; change it in Settings. For this test use "
                                "'Stop test' or the top-left emergency stop."),
                             tr("繼續", "Continue"), tr("取消", "Cancel")):
                self._cleanup()
                return False
        self._minimize(uses_screen)
        self.started.emit(True)
        self.countdown.start(self.ctx.settings.countdown_s, monitor_rect_for(info.client), countdown_hint(self.ctx))
        return True

    def stop(self) -> None:
        """停止測試: cancel the countdown, or stop the running test (session.stop)."""
        if self.countdown.is_running():
            self.countdown.cancel()
        elif self._active and self._testing:
            call(self.ctx.session.stop)

    # -- internals ------------------------------------------------------------------------
    def _minimize(self, uses_screen: bool) -> None:
        mw = main_window(self.ctx)
        if uses_screen and mw is not None and mw.isVisible() and not mw.isMinimized():
            mw.showMinimized()
            self._minimized = True

    def _run_test(self, dry_run: bool) -> None:
        if self._pending is None:
            return
        profile, index, code, hwnd = self._pending
        try:
            self._testing = True
            self.ctx.session.test_step(profile, index, self.ctx.settings, sample_code=code,
                                       dry_run=dry_run, target_hwnd=hwnd)
        except NotImplementedError:
            self._cleanup()
            self.ctx.notify(tr("測試此步驟尚未實作", "Step tests are not implemented yet"), "warning")
            self.finished.emit(None)
        except RuntimeError as exc:
            log.info("test_step refused: %s", exc)
            self._cleanup()
            self.ctx.notify(tr("已有執行中的工作，請先停止。", "Something is already running; stop it first."), "warning")
            self.finished.emit(None)

    def _countdown_done(self) -> None:
        if self._active:
            self._run_test(dry_run=False)

    def _countdown_cancelled(self) -> None:
        if self._active and not self._testing:
            self._cleanup()
            self.finished.emit(None)

    def _on_hotkey(self, action: str) -> None:
        if action == "stop" and self._active and self._real:
            self.stop()

    def _on_test_finished(self, result: Any) -> None:
        if not self._active or not self._testing:
            return
        self._cleanup()
        self.finished.emit(result if isinstance(result, StepTestResult) else None)

    def _on_session_finished(self, _summary: Any) -> None:
        if self._active and self._testing:
            self._cleanup()
            self.finished.emit(None)

    def _cleanup(self) -> None:
        if self._hotkey:
            call(self.ctx.hotkeys.unregister, "stop")
        self._hotkey = False
        self._active = self._real = self._testing = False
        self._pending = None
        mw = main_window(self.ctx)
        if self._minimized and mw is not None:
            mw.showNormal()
            mw.raise_()
            mw.activateWindow()
        self._minimized = False


def describe_result(result: StepTestResult | None) -> tuple[str, str]:
    """(text, tone) for the result line under the step editor."""
    if result is None:
        return tr("測試已取消。", "The test was cancelled."), "neutral"
    parts = [result.message or (tr("完成", "Done") if result.ok else tr("失敗", "Failed"))]
    if result.point is not None:
        parts.append(tr(f"位置 {result.point[0]}, {result.point[1]}", f"position {result.point[0]}, {result.point[1]}"))
    if result.ocr_text:
        parts.append(tr(f"讀到「{result.ocr_text[:80]}」", f"read '{result.ocr_text[:80]}'"))
    if result.result is not None:
        parts.append(tr(f"判定：{result.result.label()}", f"result: {result.result.label()}"))
    return " · ".join(parts), "success" if result.ok else "error"
