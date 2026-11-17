"""Test fakes with the same public API as the real services, plus ``demo_context()``.
OWNED BY A1. Groups may use these in their tests; do not edit - copy into your own test file
if you need different behaviour.

* FakeCodeQueue / FakeHistoryStore - in-memory versions of codes.queue.CodeQueue and
  codes.history.HistoryStore (same method names and semantics, no files).
* FakeOcrService - returns a configurable OcrResult (``.result``) or fails (``state="failed"``).
* FakeRunSession - all RunSession signals; records calls in ``.calls``; ``simulate_code()``
  plays one code through the queue/history bookkeeping for UI tests and screenshots;
  ``begin_code()`` / ``finish_code()`` / ``finish_run()`` stage a run in the engine's signal order
  (tools/guide_capture.py); ``preflight_provider`` (a callable) builds live preflight reports.
* FakeHotkeys - records registrations.
* demo_context(home) - AppContext with demo data: the REAL CodeQueue/HistoryStore when G1 has
  implemented them (module without ``__stub__``), otherwise the fakes; always fake OCR,
  session and hotkeys (deterministic, no threads, no input). The demo data is one state the
  real app can show at rest (no RUNNING / COOLDOWN codes; every history record has times);
  its texts follow the UI language (tr), so English screenshots get English demo data.
* is_stub(module) / skip_if_stub(*modules) - for tests that need ANOTHER group's real code:
  ``skip_if_stub("autopress.codes.queue")`` skips the test while that module is still a stub.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Collection, Iterable, Sequence
from concurrent.futures import Future
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from autopress.context import AppContext, AppSignals
from autopress.i18n import tr
from autopress.models import (
    AddResult,
    Attention,
    AttemptRecord,
    ClickPointParams,
    ClickTextParams,
    CodeCandidate,
    CodeFormat,
    CodeItem,
    CodeSource,
    CodeStatus,
    KeywordConfig,
    OcrCheckParams,
    OcrOptions,
    OcrResult,
    OcrSettings,
    PlanItem,
    PlanMode,
    PreflightReport,
    Profile,
    QueueEvent,
    QueueEventKind,
    Rect,
    ResultClass,
    RunPlan,
    RunSelection,
    RunState,
    RunSummary,
    Settings,
    StepTestResult,
    StepType,
    StopReason,
    TargetMatch,
    TitleMatch,
    code_key,
    make_step,
    new_id,
    now_iso,
    record_point,
    record_region,
)
from autopress.storage import ProfileStore

# ============================================================================= stub detection


def is_stub(module: str) -> bool:
    """True while ``module`` (dotted name) still carries ``__stub__ = True``."""
    return bool(getattr(importlib.import_module(module), "__stub__", False))


def skip_if_stub(*modules: str) -> None:
    """Skip the calling test while any of ``modules`` is still an unimplemented stub."""
    import pytest

    pending = [m for m in modules if is_stub(m)]
    if pending:
        pytest.skip("waiting for the real implementation of " + ", ".join(pending))


# ============================================================================= queue / history


class FakeCodeQueue:
    """In-memory CodeQueue (no file). ``path``/``autosave`` are accepted and ignored."""

    def __init__(self, path: Path | None = None, *, autosave: bool = True) -> None:
        self._items: list[CodeItem] = []
        self._subs: list[Callable[[QueueEvent], None]] = []

    def _emit(self, kind: QueueEventKind, ids: Sequence[str] = ()) -> None:
        ev = QueueEvent(kind, list(ids))
        for cb in list(self._subs):
            cb(ev)

    def load(self) -> None:
        self._emit(QueueEventKind.RESET)

    def save(self) -> None:
        pass

    def items(self) -> list[CodeItem]:
        return list(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def get(self, code_id: str) -> CodeItem | None:
        return next((i for i in self._items if i.id == code_id), None)

    def index_of(self, code_id: str) -> int:
        return next((n for n, i in enumerate(self._items) if i.id == code_id), -1)

    def find_code(self, code: str, game_key: str | None = None) -> CodeItem | None:
        key = code_key(code)
        return next((i for i in self._items
                     if code_key(i.code) == key and (game_key is None or i.game_key == game_key)), None)

    def add_candidates(self, candidates: Sequence[CodeCandidate], source: CodeSource, *, source_detail: str = "",
                       history: Any = None, game_key: str = "", skip_statuses: Collection[CodeStatus] = (),
                       game: str = "") -> AddResult:
        res = AddResult()
        for c in candidates:
            if self.find_code(c.code, game_key) is not None:
                res.duplicates += 1
                continue
            if history is not None and game_key and skip_statuses and history.is_done(game_key, c.code, skip_statuses):
                res.skipped_history += 1
                continue
            item = CodeItem(code=c.code, raw=c.raw, game_key=game_key, game=game, source=source,
                            source_detail=source_detail, confidence=c.confidence, char_confs=list(c.char_confs or []),
                            flagged=list(c.flagged), lookalikes=list(c.lookalikes),
                            status=CodeStatus.REVIEW if c.flagged else CodeStatus.PENDING)
            self._items.append(item)
            res.added.append(item.id)
        if res.added:
            self._emit(QueueEventKind.ADDED, res.added)
        return res

    def add_codes(self, codes: Sequence[str], source: CodeSource = CodeSource.MANUAL, *,
                  fmt: CodeFormat | None = None, **kwargs: Any) -> AddResult:
        cands = [CodeCandidate(code=c.strip(), raw=c) for c in codes if c.strip()]
        res = self.add_candidates(cands, source, **kwargs)
        res.invalid += sum(1 for c in codes if not c.strip())
        return res

    def update(self, code_id: str, **changes: Any) -> CodeItem:
        item = self.get(code_id)
        if item is None:
            raise KeyError(code_id)
        for k, v in changes.items():
            if not hasattr(item, k):
                raise AttributeError(k)
            setattr(item, k, v)
        if "code" in changes:
            item.flagged = []
            if item.status is CodeStatus.REVIEW:
                item.status = CodeStatus.PENDING
        item.updated_at = now_iso()
        self._emit(QueueEventKind.UPDATED, [code_id])
        return item

    def set_status(self, code_id: str, status: CodeStatus, message: str | None = None) -> CodeItem:
        changes: dict[str, Any] = {"status": status}
        if message is not None:
            changes["message"] = message
        return self.update(code_id, **changes)

    def remove(self, code_ids: Iterable[str]) -> int:
        ids = set(code_ids)
        before = len(self._items)
        self._items = [i for i in self._items if i.id not in ids]
        n = before - len(self._items)
        if n:
            self._emit(QueueEventKind.REMOVED, list(ids))
        return n

    def clear(self, statuses: Collection[CodeStatus] | None = None) -> int:
        ids = [i.id for i in self._items if statuses is None or i.status in statuses]
        return self.remove(ids)

    def move(self, code_ids: Sequence[str], delta: int) -> None:
        ids = set(code_ids)
        order = list(self._items)
        rng = range(len(order)) if delta < 0 else range(len(order) - 1, -1, -1)
        for _ in range(abs(delta)):
            for n in rng:
                m = n + (1 if delta > 0 else -1)
                if order[n].id in ids and 0 <= m < len(order) and order[m].id not in ids:
                    order[n], order[m] = order[m], order[n]
        self._items = order
        self._emit(QueueEventKind.MOVED, list(code_ids))

    def move_to(self, code_ids: Sequence[str], index: int) -> None:
        ids = list(code_ids)
        moving = [i for i in self._items if i.id in ids]
        rest = [i for i in self._items if i.id not in ids]
        index = max(0, min(index, len(rest)))
        self._items = rest[:index] + moving + rest[index:]
        self._emit(QueueEventKind.MOVED, ids)

    def set_checked(self, code_ids: Iterable[str], checked: bool) -> None:
        ids = list(code_ids)
        for i in self._items:
            if i.id in ids:
                i.checked = checked
        self._emit(QueueEventKind.UPDATED, ids)

    def runnable(self, selection: RunSelection = RunSelection.UNFINISHED,
                 game_key: str | None = None) -> list[CodeItem]:
        return [i for i in self._items if i.status.is_runnable and (selection is RunSelection.UNFINISHED or i.checked)
                and (game_key is None or i.game_key == game_key)]

    def retry_failed(self) -> int:
        ids = [i.id for i in self._items if i.status is CodeStatus.FAILED]
        for i in ids:
            self.set_status(i, CodeStatus.PENDING, "")
        return len(ids)

    def reset(self, code_ids: Iterable[str]) -> int:
        ids = [i.id for i in self._items if i.id in set(code_ids) and i.status is not CodeStatus.RUNNING]
        for i in ids:
            self.update(i, status=CodeStatus.PENDING, flagged=[], message="")
        return len(ids)

    def assign_game(self, code_ids: Iterable[str], game_key: str, game: str = "") -> int:
        moved, dupes = 0, []
        for cid in list(code_ids):
            item = self.get(cid)
            if item is None or item.game_key == game_key:
                continue
            other = self.find_code(item.code, game_key)
            if other is not None and other.id != cid:
                dupes.append(cid)
                continue
            self.update(cid, game_key=game_key, game=game)
            moved += 1
        self.remove(dupes)
        return moved

    def games(self) -> list[tuple[str, str]]:
        seen: dict[str, str] = {}
        for i in self._items:
            seen.setdefault(i.game_key, i.game)
        return list(seen.items())

    def recover_after_crash(self) -> int:
        n = 0
        for i in self._items:
            if i.status is CodeStatus.RUNNING:
                i.status, n = CodeStatus.REVIEW, n + 1
                i.message = tr("上次執行中斷，請確認是否已兌換", "The last run was interrupted; check whether this code was redeemed")
            elif i.status is CodeStatus.COOLDOWN:
                i.status, n = CodeStatus.PENDING, n + 1
        if n:
            self._emit(QueueEventKind.RESET)
        return n

    def counts(self) -> dict[CodeStatus, int]:
        out = {s: 0 for s in CodeStatus}
        for i in self._items:
            out[i.status] += 1
        return out

    def subscribe(self, callback: Callable[[QueueEvent], None]) -> Callable[[], None]:
        self._subs.append(callback)
        return lambda: self._subs.remove(callback) if callback in self._subs else None


class FakeHistoryStore:
    def __init__(self, path: Path | None = None) -> None:
        self._records: list[AttemptRecord] = []
        self._subs: list[Callable[[], None]] = []

    def _emit(self) -> None:
        for cb in list(self._subs):
            cb()

    def load(self) -> None:
        self._emit()

    def append(self, record: AttemptRecord) -> None:
        self._records.append(record)
        self._emit()

    def update(self, record_id: str, **changes: object) -> AttemptRecord:
        rec = next((r for r in self._records if r.id == record_id), None)
        if rec is None:
            raise KeyError(record_id)
        for k, v in changes.items():
            if not hasattr(rec, k):
                raise AttributeError(k)
            setattr(rec, k, v)
        self._emit()
        return rec

    def records(self) -> list[AttemptRecord]:
        return list(self._records)

    def latest(self, game_key: str, code: str) -> AttemptRecord | None:
        key = code_key(code)
        for r in reversed(self._records):
            if r.game_key == game_key and code_key(r.code) == key:
                return r
        return None

    def is_done(self, game_key: str, code: str, statuses: Collection[CodeStatus]) -> bool:
        r = self.latest(game_key, code)
        return r is not None and r.status in statuses

    def query(self, text: str = "", statuses: Collection[CodeStatus] | None = None,
              game_key: str | None = None) -> list[AttemptRecord]:
        t = text.casefold()
        out = [r for r in reversed(self._records)
               if (not t or t in f"{r.code} {r.message} {r.game} {r.profile_name}".casefold())
               and (statuses is None or r.status in statuses) and (game_key is None or r.game_key == game_key)]
        return out

    def games(self) -> list[tuple[str, str]]:
        seen: dict[str, str] = {}
        for r in reversed(self._records):
            seen.setdefault(r.game_key, r.game)
        return list(seen.items())

    def remove(self, record_ids: Iterable[str]) -> int:
        ids = set(record_ids)
        before = len(self._records)
        self._records = [r for r in self._records if r.id not in ids]
        self._emit()
        return before - len(self._records)

    def clear(self) -> int:
        n = len(self._records)
        self._records = []
        self._emit()
        return n

    def prune_evidence(self, keep_days: int) -> int:
        return 0

    def subscribe(self, callback: Callable[[], None]) -> Callable[[], None]:
        self._subs.append(callback)
        return lambda: self._subs.remove(callback) if callback in self._subs else None


# ============================================================================= OCR


class FakeOcrService(QObject):
    state_changed = pyqtSignal(str)

    def __init__(self, result: OcrResult | None = None, state: str = "ready", error: str = "") -> None:
        super().__init__()
        from autopress.ocr.service import OcrState

        self.result = result or OcrResult()
        self._state = OcrState(state)
        self._error = error
        self.requests: list[tuple[Any, OcrOptions | None]] = []
        self._next_id = 0
        self._cancelled: set[int] = set()

    @property
    def state(self) -> Any:
        return self._state

    @property
    def error(self) -> str:
        return self._error

    def _fail(self) -> Exception | None:
        from autopress.ocr.engine import OcrUnavailable

        if self._state.value in ("failed", "disabled"):
            return OcrUnavailable(self._error or "OCR unavailable (fake)")
        return None

    def start(self) -> None:
        self.state_changed.emit(self._state.value)

    def shutdown(self, timeout_s: float = 2.0) -> None:
        pass

    def restart(self, settings: OcrSettings | None = None) -> None:
        from autopress.ocr.service import OcrState

        if settings is not None:
            self._state = OcrState.READY if settings.enabled else OcrState.DISABLED
        self.state_changed.emit(self._state.value)

    def wait_ready(self, timeout_s: float = 30.0, cancel: Callable[[], bool] | None = None) -> bool:
        return self._state.value == "ready"

    def submit(self, image: Any, opts: OcrOptions | None = None, priority: int = 1) -> Future[OcrResult]:
        self.requests.append((image, opts))
        fut: Future[OcrResult] = Future()
        err = self._fail()
        if err:
            fut.set_exception(err)
        else:
            fut.set_result(self.result)
        return fut

    def recognize(self, image: Any, opts: OcrOptions | None = None, *, timeout_s: float = 30.0,
                  cancel: Callable[[], bool] | None = None, priority: int = 0) -> OcrResult:
        return self.submit(image, opts, priority).result()

    def request(self, image: Any, opts: OcrOptions | None, on_done: Callable[[OcrResult], None],
                on_error: Callable[[Exception], None] | None = None, priority: int = 1) -> int:
        self.requests.append((image, opts))
        self._next_id += 1
        job = self._next_id
        err = self._fail()

        def deliver() -> None:
            if job in self._cancelled:
                return
            if err is not None:
                if on_error is not None:
                    on_error(err)
            else:
                on_done(self.result)

        QTimer.singleShot(0, deliver)
        return job

    def cancel_request(self, job_id: int) -> None:
        self._cancelled.add(job_id)


# ============================================================================= session / hotkeys


class FakeRunSession(QObject):
    state_changed = pyqtSignal(str, str)
    progress = pyqtSignal(int, int, float)
    code_started = pyqtSignal(str, int)
    step_started = pyqtSignal(str, int, str)
    code_finished = pyqtSignal(str, object)
    log = pyqtSignal(object)
    cooldown = pyqtSignal(float)
    waiting = pyqtSignal(float)
    attention = pyqtSignal(object)
    finished = pyqtSignal(object)
    test_finished = pyqtSignal(object)

    def __init__(self, queue: Any, history: Any, ocr: Any = None, *, backend_factory: Any = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.queue, self.history, self.ocr = queue, history, ocr
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self._state = RunState.IDLE
        self._plan: RunPlan | None = None
        self.preflight_report: PreflightReport | None = None  # tests may preset one
        # or a callable (plan) -> PreflightReport, used when no report is preset (live reports)
        self.preflight_provider: Callable[[RunPlan], PreflightReport] | None = None
        self.masked_rects: list[Rect] = []

    @property
    def state(self) -> RunState:
        return self._state

    @property
    def plan(self) -> RunPlan | None:
        return self._plan

    def is_active(self) -> bool:
        return self._state not in (RunState.IDLE, RunState.FINISHED)

    def _set_state(self, state: RunState, reason: str = "") -> None:
        self._state = state
        self.state_changed.emit(state.value, reason)

    def build_plan(self, profile: Profile, settings: Settings, selection: RunSelection = RunSelection.UNFINISHED, *,
                   code_ids: Sequence[str] | None = None, target_hwnd: int = 0,
                   mode: PlanMode = PlanMode.NORMAL) -> RunPlan:
        self.calls.append(("build_plan", (profile.id, selection, tuple(code_ids or ()), mode)))
        items = [PlanItem(i.id, i.code) for i in self.queue.runnable(selection, game_key=profile.game_key())
                 if code_ids is None or i.id in code_ids]
        return RunPlan(profile=profile.clone(new_identity=False), items=items, target_hwnd=target_hwnd,
                       mode=mode, settings=settings)

    def preflight(self, plan: RunPlan) -> PreflightReport:
        self.calls.append(("preflight", (plan.run_id,)))
        if self.preflight_report is None and self.preflight_provider is not None:
            return self.preflight_provider(plan)
        return self.preflight_report or PreflightReport(code_count=len(plan.items), ocr_needed=plan.profile.uses_ocr())

    def start(self, plan: RunPlan) -> None:
        if self.is_active():
            raise RuntimeError("a run is active")
        self.calls.append(("start", (plan.run_id,)))
        self._plan = plan
        self._set_state(RunState.RUNNING)
        self.progress.emit(0, len(plan.items), -1.0)

    def pause(self) -> None:
        """Idempotent like RunSession.pause (the fake pauses at once)."""
        self.calls.append(("pause", ()))
        if self._state in (RunState.RUNNING, RunState.COOLDOWN):
            self._set_state(RunState.PAUSED, "user")

    def resume(self) -> None:
        self.calls.append(("resume", ()))
        if self._state is RunState.PAUSED:
            self._set_state(RunState.RUNNING)

    def toggle_pause(self) -> None:
        if self._state is RunState.PAUSED:
            self.resume()
        else:
            self.pause()

    def stop(self, reason: StopReason = StopReason.USER) -> None:
        self.calls.append(("stop", (reason,)))
        if not self.is_active():
            return
        plan = self._plan
        self._set_state(RunState.FINISHED, reason.value)
        summary = RunSummary(run_id=plan.run_id if plan else "", profile_id=plan.profile.id if plan else "",
                             profile_name=plan.profile.name if plan else "", total=len(plan.items) if plan else 0,
                             stop_reason=reason, started_at=now_iso(), finished_at=now_iso())
        self._plan = None
        self.finished.emit(summary)

    def resolve_attention(self, code_id: str, status: CodeStatus, message: str = "") -> None:
        """Queue item + the latest history record of this run for the code (HistoryStore.update);
        during a run code_finished is emitted again with the updated record, like RunSession."""
        self.calls.append(("resolve_attention", (code_id, status, message)))
        self.queue.set_status(code_id, status, message)
        run_id = self._plan.run_id if self._plan else None
        for rec in reversed(self.history.records()):
            if rec.code_id == code_id and (run_id is None or rec.run_id == run_id):
                updated = self.history.update(rec.id, status=status, message=message or rec.message)
                if self.is_active():
                    self.code_finished.emit(code_id, updated)
                break

    def update_keywords(self, keywords: KeywordConfig) -> None:
        self.calls.append(("update_keywords", (keywords,)))

    def set_masked_rects(self, rects: Sequence[Rect]) -> None:
        self.calls.append(("set_masked_rects", (tuple(rects),)))
        self.masked_rects = list(rects)

    def test_step(self, profile: Profile, step_index: int, settings: Settings, *, sample_code: str = "TEST-1234",
                  dry_run: bool = True, target_hwnd: int = 0) -> None:
        self.calls.append(("test_step", (profile.id, step_index, sample_code, dry_run)))
        res = StepTestResult(ok=True, step_index=step_index, message="(fake) OK")
        QTimer.singleShot(0, lambda: self.test_finished.emit(res))

    def shutdown(self, timeout_s: float = 3.0) -> None:
        self.calls.append(("shutdown", ()))

    # -- helpers for tests and screenshots ------------------------------------------------
    def simulate_code(self, code_id: str, status: CodeStatus, message: str = "", index: int = 0,
                      **record: Any) -> AttemptRecord:
        """Emit code_started/code_finished for ``code_id`` and apply the bookkeeping.
        ``record``: optional AttemptRecord fields (started_at, finished_at, result, ...)."""
        self.code_started.emit(code_id, index)
        return self.finish_code(code_id, status, message, **record)

    def begin_code(self, code_id: str, index: int) -> None:
        """Like the engine when a code starts: the queue item becomes RUNNING (one more
        attempt), then code_started. Finish it with ``finish_code()``."""
        item = self.queue.get(code_id)
        if item is not None:
            self.queue.update(code_id, status=CodeStatus.RUNNING, attempts=item.attempts + 1)
        self.code_started.emit(code_id, index)

    def finish_code(self, code_id: str, status: CodeStatus, message: str = "", **record: Any) -> AttemptRecord:
        """The bookkeeping of one finished attempt (queue item, history record of this run's
        profile), then code_finished. ``record``: optional AttemptRecord fields; started_at /
        finished_at default to now."""
        item = self.queue.get(code_id)
        plan = self._plan
        fields: dict[str, Any] = {
            "code_id": code_id, "code": item.code if item else "", "status": status, "message": message,
            "started_at": now_iso(), "finished_at": now_iso(), "run_id": plan.run_id if plan else ""}
        if plan is not None:
            p = plan.profile
            fields.update(game=p.game, game_key=p.game_key(), profile_id=p.id, profile_name=p.name)
        fields.update(record)
        rec = AttemptRecord(**fields)
        if item is not None:
            attempts = item.attempts if item.status is CodeStatus.RUNNING else item.attempts + 1
            self.queue.update(code_id, status=status, message=message, attempts=attempts)
        self.history.append(rec)
        self.code_finished.emit(code_id, rec)
        return rec

    def pause_for(self, attention: Attention) -> None:
        """A decision pause like the worker's: state PAUSED (reason = the attention kind), then
        the attention signal."""
        self._set_state(RunState.PAUSED, attention.kind.value)
        self.attention.emit(attention)

    def finish_run(self, stop_reason: StopReason = StopReason.COMPLETED, message: str = "", *,
                   counts: dict[CodeStatus, int] | None = None, started_at: str = "",
                   finished_at: str = "") -> RunSummary:
        """End the active run like the engine: RUNNING items become REVIEW, COOLDOWN items
        PENDING, state FINISHED (reason = the stop reason), then ``finished(summary)``."""
        plan = self._plan
        items = plan.items if plan else []
        for it in items:
            item = self.queue.get(it.code_id)
            if item is not None and item.status is CodeStatus.RUNNING:
                self.queue.update(it.code_id, status=CodeStatus.REVIEW)
            elif item is not None and item.status is CodeStatus.COOLDOWN:
                self.queue.update(it.code_id, status=CodeStatus.PENDING)
        counts = dict(counts or {})
        summary = RunSummary(run_id=plan.run_id if plan else "", profile_id=plan.profile.id if plan else "",
                             profile_name=plan.profile.name if plan else "", mode=plan.mode if plan else PlanMode.NORMAL,
                             started_at=started_at or now_iso(), finished_at=finished_at or now_iso(),
                             total=len(items), done=sum(counts.values()), counts=counts, stop_reason=stop_reason,
                             message=message)
        self._plan = None
        self._set_state(RunState.FINISHED, stop_reason.value)
        self.finished.emit(summary)
        return summary


class FakeHotkeys(QObject):
    triggered = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.hwnd = 0
        self._registered: dict[str, str] = {}
        self.fail_combos: set[str] = set()  # combos that report error 1409

    def attach(self, hwnd: int) -> None:
        self.hwnd = hwnd

    def register(self, action: str, combo: str) -> Any:
        from autopress.win32.hotkeys import HotkeyResult

        if combo in self.fail_combos:
            return HotkeyResult(False, 1409, "此快捷鍵已被其他程式使用")
        self._registered[action] = combo
        return HotkeyResult(True)

    def unregister(self, action: str) -> None:
        self._registered.pop(action, None)

    def unregister_all(self) -> None:
        self._registered.clear()

    def registered(self) -> dict[str, str]:
        return dict(self._registered)


# ============================================================================= demo data

# invented strings - NOT real codes: (code, source, confidence, flagged, status, message)
# A state the real app can show at rest: no RUNNING / COOLDOWN items (a run's end turns them into
# REVIEW / PENDING), and the queue never stores a message for look-alike characters (the code
# column highlights them). Messages of finished codes are the demo game's result texts.
DEMO_ROWS: list[tuple[str, CodeSource, float | None, list[int], CodeStatus, str]] = [
    ("AP7K2QX9MZ4T", CodeSource.PASTE, None, [], CodeStatus.SUCCESS, "兌換成功，獎勵已寄至信箱"),
    ("HV3N8RT2KD6W", CodeSource.PASTE, None, [], CodeStatus.USED, "此序號已被使用"),
    ("Q8ZL0W3NBX5C", CodeSource.IMAGE, 0.71, [4], CodeStatus.REVIEW, ""),
    ("MX4T9PK2JR7D", CodeSource.IMAGE, 0.97, [], CodeStatus.PENDING, ""),
    ("ZK6WD2TQ9HNA", CodeSource.FILE, None, [], CodeStatus.PENDING, ""),
    ("TRV6Y2NCBL1X", CodeSource.SNIP, 0.64, [8, 10], CodeStatus.REVIEW, ""),
    ("BZ2M5KQ8XH3P", CodeSource.CLIPBOARD, 0.93, [], CodeStatus.PENDING, ""),
    ("JW8R3TD5QN2K", CodeSource.PASTE, None, [], CodeStatus.INVALID, "序號無效"),
    ("EK5P9WM3ZT7V", CodeSource.PASTE, None, [], CodeStatus.EXPIRED, "序號已過期"),
    ("LN7C2XR9PB4Q", CodeSource.SNIP, 0.88, [], CodeStatus.PENDING, ""),
    ("GS4H8NM2VC6R", CodeSource.SNIP, 0.91, [], CodeStatus.SUBMITTED, ""),
    ("WQ9D3KF7TX2M", CodeSource.FILE, None, [], CodeStatus.FAILED, "角色等級未達 10 級，無法兌換"),
]

# English versions of the demo texts (tr() picks one; tests run in zh-TW)
DEMO_TEXT_EN: dict[str, str] = {
    "示範：網頁兌換": "Demo: web redeem",
    "示範遊戲": "Demo Game",
    "兌換": "Redeem",
    "兌換成功，獎勵已寄至信箱": "Redeemed - rewards sent to your mailbox",
    "此序號已被使用": "This code has already been used",
    "序號無效": "Invalid code",
    "序號已過期": "This code has expired",
    "角色等級未達 10 級，無法兌換": "Reach level 10 to redeem this code",
}

# the result class behind each final demo status (FAILED = not eligible; SUBMITTED = no check)
DEMO_RESULTS: dict[CodeStatus, ResultClass | None] = {
    CodeStatus.SUCCESS: ResultClass.SUCCESS, CodeStatus.USED: ResultClass.USED,
    CodeStatus.INVALID: ResultClass.INVALID, CodeStatus.EXPIRED: ResultClass.EXPIRED,
    CodeStatus.FAILED: ResultClass.INELIGIBLE, CodeStatus.SUBMITTED: None,
}

# history: (code, seconds before ``now``, duration ms), oldest first - the newest record is the success
DEMO_HISTORY: list[tuple[str, int, int]] = [
    ("WQ9D3KF7TX2M", 1581, 6100), ("GS4H8NM2VC6R", 1307, 3900), ("EK5P9WM3ZT7V", 893, 4600),
    ("JW8R3TD5QN2K", 548, 4300), ("HV3N8RT2KD6W", 236, 4800), ("AP7K2QX9MZ4T", 0, 5200),
]


def demo_text(zh: str) -> str:
    """A demo text in the current UI language (DEMO_TEXT_EN; zh-TW otherwise)."""
    return tr(zh, DEMO_TEXT_EN.get(zh, zh))


def demo_profile() -> Profile:
    """A web-redeem style profile with every position recorded (client 1280x720)."""
    client = (100, 50, 1280, 720)
    p = Profile(name=demo_text("示範：網頁兌換"), game=demo_text("示範遊戲"),
                target=TargetMatch(exe="chrome.exe", title=demo_text("兌換"), title_mode=TitleMatch.CONTAINS))
    steps = [make_step(t) for t in (StepType.FOCUS_WINDOW, StepType.CLICK_POINT, StepType.TYPE_CODE,
                                    StepType.CLICK_TEXT, StepType.OCR_CHECK, StepType.KEY)]
    assert isinstance(steps[1].params, ClickPointParams)
    steps[1].params.point = record_point(client, 640, 300)
    assert isinstance(steps[3].params, ClickTextParams)
    steps[3].params.text = "兌換|Redeem"
    steps[3].params.region = record_region(client, 400, 380, 600, 120)
    assert isinstance(steps[4].params, OcrCheckParams)
    steps[4].params.region = record_region(client, 300, 200, 760, 140)
    p.steps = steps
    return p


def demo_context(home: Path | None = None, *, with_data: bool = True, now: datetime | None = None) -> AppContext:
    """AppContext for page tests and screenshots (see module docstring). ``now``: the time of
    the newest history record (default: the current time); the others are minutes earlier."""
    import tempfile

    from autopress.codes import history as history_mod
    from autopress.codes import queue as queue_mod

    home = Path(home) if home is not None else Path(tempfile.mkdtemp(prefix="autopress-demo-"))
    queue: Any = (FakeCodeQueue() if getattr(queue_mod, "__stub__", False)
                  else queue_mod.CodeQueue(home / "queue.json"))
    history: Any = (FakeHistoryStore() if getattr(history_mod, "__stub__", False)
                    else history_mod.HistoryStore(home / "history.jsonl"))
    if not isinstance(queue, FakeCodeQueue):
        queue.load()
    if not isinstance(history, FakeHistoryStore):
        history.load()
    ocr = FakeOcrService()
    session = FakeRunSession(queue, history, ocr)
    ctx = AppContext(settings=Settings(first_run_done=True), profiles=ProfileStore(home / "profiles"),
                     queue=queue, history=history, ocr=ocr, session=session, hotkeys=FakeHotkeys(),
                     signals=AppSignals())
    if with_data:
        prof = demo_profile()
        ctx.profiles.save(prof)
        ctx.settings.active_profile_id = prof.id
        done: dict[str, tuple[str, CodeStatus, str]] = {}  # code -> (queue id, status, message)
        for code, source, conf, flagged, status, message in DEMO_ROWS:
            looks = [n for n, ch in enumerate(code) if ch in "0ODQ1I2Z5S6G8BUVY"] if source.is_ocr else []
            cand = CodeCandidate(code=code, raw=code, flagged=list(flagged), lookalikes=looks,
                                 char_confs=[conf] * len(code) if conf is not None else None)
            res = queue.add_candidates([cand], source, source_detail="demo.png" if source.is_ocr else "",
                                       game_key=prof.game_key(), game=prof.game)
            text = demo_text(message) if message else ""
            for cid in res.added:
                queue.update(cid, status=status, message=text)
                if status not in (CodeStatus.PENDING, CodeStatus.REVIEW):
                    done[code] = (cid, status, text)
        base = now if now is not None else datetime.now()
        base = base.astimezone()  # naive = local time
        order = [c for c, _ago, _ms in DEMO_HISTORY if c in done]
        order += [c for c in done if c not in order]  # rows without a planned time: newest
        timing = {c: (ago, ms) for c, ago, ms in DEMO_HISTORY}
        for code in order:
            cid, status, text = done[code]
            ago, ms = timing.get(code, (0, 4200))
            finished = base - timedelta(seconds=ago)
            started = finished - timedelta(milliseconds=ms)
            history.append(AttemptRecord(run_id="demo", code_id=cid, code=code, game=prof.game,
                                         game_key=prof.game_key(), profile_id=prof.id, profile_name=prof.name,
                                         status=status, result=DEMO_RESULTS.get(status), message=text,
                                         started_at=started.isoformat(timespec="seconds"),
                                         finished_at=finished.isoformat(timespec="seconds"), duration_ms=ms))
    return ctx


__all__ = [
    "DEMO_HISTORY",
    "DEMO_RESULTS",
    "DEMO_ROWS",
    "DEMO_TEXT_EN",
    "FakeCodeQueue",
    "FakeHistoryStore",
    "FakeHotkeys",
    "FakeOcrService",
    "FakeRunSession",
    "demo_context",
    "demo_profile",
    "demo_text",
    "is_stub",
    "new_id",
    "skip_if_stub",
]
