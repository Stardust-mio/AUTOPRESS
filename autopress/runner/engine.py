# OWNED BY G4 - replace this stub
"""RunSession: the GUI-thread facade over one runner worker thread (SPEC section 2).

The worker (``Runner``, a QObject moved to a QThread) executes the plan and emits signals;
RunSession receives them on the GUI thread, updates the CodeQueue and HistoryStore (the only
writer during a run), then re-emits its own signals for the UI. Control requests go through
a runner.control.RunControl (thread-safe), never through signals.

Bookkeeping rules: a ``code_finished`` for an id that is no longer in the queue is logged and
ignored; on ``finished`` any plan item still RUNNING becomes REVIEW (「執行中斷，請確認是否已兌換」);
every persisted message uses tr() with both languages. The runner thread calls
win32.power.keep_awake(True) at start and keep_awake(False) in its finally (PX-31).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, pyqtSignal

from ..models import (
    CodeStatus,
    KeywordConfig,
    PlanMode,
    PreflightReport,
    Profile,
    Rect,
    RunPlan,
    RunSelection,
    RunState,
    Settings,
    StopReason,
)

__stub__ = True

if TYPE_CHECKING:
    from ..codes.history import HistoryStore
    from ..codes.queue import CodeQueue
    from ..ocr.service import OcrService
    from .backend import Backend


class Runner(QObject):
    """Worker object living in the runner QThread (G4-internal; the UI never touches it)."""

    def __init__(self, plan: RunPlan, control: object, backend_factory: Callable[[], Backend]) -> None:
        raise NotImplementedError


class RunSession(QObject):
    state_changed = pyqtSignal(str, str)  # RunState value, reason (PauseReason/StopReason value or "")
    progress = pyqtSignal(int, int, float)  # done, total, eta seconds (-1 = unknown)
    code_started = pyqtSignal(str, int)  # code_id, index in plan (0-based)
    step_started = pyqtSignal(str, int, str)  # code_id, step index (0-based), step display title
    code_finished = pyqtSignal(str, object)  # code_id, AttemptRecord (queue + history already updated)
    log = pyqtSignal(object)  # LogEntry
    cooldown = pyqtSignal(float)  # rate-limit cool-down: seconds left, about once per second
    waiting = pyqtSignal(float)  # interval before the next code: seconds left, about once per second
    attention = pyqtSignal(object)  # Attention - the run is paused (or stopped) when emitted
    finished = pyqtSignal(object)  # RunSummary
    test_finished = pyqtSignal(object)  # StepTestResult

    def __init__(self, queue: CodeQueue, history: HistoryStore, ocr: OcrService, *,
                 backend_factory: Callable[[], Backend] | None = None, parent: QObject | None = None) -> None:
        """``backend_factory`` None -> RealBackend(ocr), created inside the worker thread."""
        raise NotImplementedError

    @property
    def state(self) -> RunState:
        raise NotImplementedError

    @property
    def plan(self) -> RunPlan | None:
        """The plan being run (None when idle)."""
        raise NotImplementedError

    def is_active(self) -> bool:
        """A run or step test is in progress (state not IDLE / FINISHED)."""
        raise NotImplementedError

    def build_plan(self, profile: Profile, settings: Settings, selection: RunSelection = RunSelection.UNFINISHED, *,
                   code_ids: Sequence[str] | None = None, target_hwnd: int = 0,
                   mode: PlanMode = PlanMode.NORMAL) -> RunPlan:
        """Plan over queue.runnable(selection, game_key=profile.game_key()) - only codes of the
        profile's game; unassigned codes are reported by preflight (``unassigned_codes``) -
        restricted to ``code_ids`` when given, queue order kept, with a deep copy of ``profile``
        and ``settings``. Side effects (SPEC 5.7): runnable items whose code the history already
        shows as done (settings.history_skip_statuses, profile.game_key()) become SKIPPED when
        settings.skip_history_on_import; with settings.daily_cap > 0 the items are truncated to
        the attempts left today (preflight reports it). TEST_ONE plans keep only the first item."""
        raise NotImplementedError

    def preflight(self, plan: RunPlan) -> PreflightReport:
        """runner.preflight.run_preflight for the plan (GUI thread, < 100 ms, no input). Sets
        ``plan.target_hwnd`` when the target is found."""
        raise NotImplementedError

    def start(self, plan: RunPlan) -> None:
        """Start the worker thread. RuntimeError if a run is active. The caller has already
        shown the countdown and registered the hotkeys."""
        raise NotImplementedError

    def pause(self) -> None:
        """Soft pause (after the current code; at once while waiting). Idempotent: no-op while
        PAUSING / PAUSED, except that a USER_INPUT pause younger than 1.5 s is relabelled USER
        (the F8 press itself tripped the input guard; PX-11) and ``state_changed`` re-emitted."""
        raise NotImplementedError

    def resume(self) -> None:
        """Resume NOW (reset the input baseline in the runner, re-focus, continue). The UI calls
        RunFlow.resume(), which hides the main window and shows the resume countdown first."""
        raise NotImplementedError

    def toggle_pause(self) -> None:
        """Immediate pause / resume without countdown or debounce (scripts and tests). The F8
        hotkey goes through RunFlow (debounce + resume countdown, SPEC 2.6)."""
        raise NotImplementedError

    def stop(self, reason: StopReason = StopReason.USER) -> None:
        raise NotImplementedError

    def resolve_attention(self, code_id: str, status: CodeStatus, message: str = "") -> None:
        """The user classified an unknown result (Run page): update the queue item and, with
        HistoryStore.update, the latest history record of this run for that code (same record
        id); then the paused run may be resumed."""
        raise NotImplementedError

    def set_masked_rects(self, rects: Sequence[Rect]) -> None:
        """Physical screen rects of AutoPress's own windows that are visible during the run (the
        mini bar). Thread-safe; the runner blanks them in every capture before OCR, blank checks
        and evidence (ocr.imageio.mask_rects), so OCR never reads AutoPress's own text (T01 /
        PX-03). RunFlow calls it whenever the bar is shown, moved or hidden ([] when hidden)."""
        raise NotImplementedError

    def update_keywords(self, keywords: KeywordConfig) -> None:
        """Use new keyword groups for the remaining codes of the running plan (thread-safe)."""
        raise NotImplementedError

    def test_step(self, profile: Profile, step_index: int, settings: Settings, *,
                  sample_code: str = "TEST-1234", dry_run: bool = False, target_hwnd: int = 0) -> None:
        """Run one step against the target in the worker (focus first). ``dry_run`` locates /
        reads but sends no input. Result via ``test_finished``. RuntimeError if active. A real
        (not dry) test is stoppable with stop() at every checkpoint like a run; the caller shows
        the countdown and registers the stop hotkey first (SPEC 6.4.2)."""
        raise NotImplementedError

    def shutdown(self, timeout_s: float = 3.0) -> None:
        """Stop any run and join the worker (app exit), then deliver the runner's queued final
        signals synchronously (``QCoreApplication.sendPostedEvents(self)``) so the last
        ``code_finished`` / ``finished`` bookkeeping reaches the queue and history BEFORE
        ui.app saves the queue (T29)."""
        raise NotImplementedError
