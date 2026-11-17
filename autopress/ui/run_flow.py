# OWNED BY G7 - replace this stub
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

from collections.abc import Sequence

from PyQt6.QtCore import QObject, pyqtSignal

from ..context import AppContext
from ..models import PlanMode, Profile, RunSelection

__stub__ = True


class RunFlow(QObject):
    started = pyqtSignal()
    ended = pyqtSignal(object)  # RunSummary, or None when cancelled before the start

    def __init__(self, ctx: AppContext, parent: QObject | None = None) -> None:
        raise NotImplementedError

    def begin(self, profile: Profile, selection: RunSelection = RunSelection.UNFINISHED, *,
              code_ids: Sequence[str] | None = None, mode: PlanMode = PlanMode.NORMAL,
              target_hwnd: int = 0) -> bool:
        """Run the sequence; False if it was cancelled or blocked before session.start."""
        raise NotImplementedError

    def is_running(self) -> bool:
        raise NotImplementedError

    def resume(self) -> None:
        """Continue a paused run: hide the main window again (run mode), show the resume
        countdown (Settings.resume_countdown_s; F9 during it stops the run), then
        session.resume(). Physical input during the countdown is ignored because the runner
        resets its input baseline when it resumes (T14)."""
        raise NotImplementedError
