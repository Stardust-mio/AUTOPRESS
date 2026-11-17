# OWNED BY G2
"""OcrService: the ONE OCR worker thread that owns the engine (ocr.md section 5).

* start() spawns the worker - a DAEMON ``threading.Thread`` (never a QThread: destroying a
  running QThread at exit aborts the process, and one inference can outlast shutdown's timeout)
  - which builds the engine (with ``engine_factory`` when given - tests inject fakes) and warms
  it up when settings.warmup_on_start. State: NOT_STARTED -> LOADING -> READY | FAILED
  (DISABLED when settings.enabled is False). ``state_changed`` is emitted on the GUI thread.
* Jobs run one at a time from a priority queue (lower number first; the runner uses 0, UI
  imports use 1). BGRA input is converted to BGR. With ``opts.code_charset`` the worker
  re-reads Latin-looking lines with OcrEngine.reread_line and fills OcrLine.char_confs.
* Cancellation only stops waiting; a running inference finishes and its result is dropped.
  One inference takes 0.2-1.5 s (full-HD regions up to ~1.4 s; a live 4K desktop up to 4.5 s,
  ocr.md 3.4).
* The service object lives for the whole app (``ctx.ocr`` is never replaced; RunSession keeps
  it): settings changes and 「重新啟動引擎」 call ``restart(settings)``.

Behaviour details (G2):
* DISABLED is the state from construction when ``settings.enabled`` is False; start() then does
  nothing. submit() / wait_ready() on a NOT_STARTED service start it (lazy start).
* Errors: ``error`` is the short localized reason (FAILED only); a job of a FAILED service fails
  with ``OcrUnavailable`` whose ``str()`` is the full 7.1 sentence 「文字辨識引擎無法啟動：…」 and
  whose ``reason`` equals ``error``. DISABLED jobs fail with OcrUnavailable 「文字辨識已在設定中關閉…」.
  OcrTimeout carries the 7.1 OCR-timeout text.
* restart(): pending jobs move to the new worker (they just wait for the new engine); the
  old worker finishes its current job normally and exits. shutdown(): pending and running
  jobs fail with OcrCancelled; later submits fail with OcrCancelled until start()/restart().
* ``opts=None`` means ``OcrOptions(det_side=settings.det_side)``. ``origin`` (keyword
  addition on submit / recognize / request) is copied into ``OcrResult.origin``.
* The image must not be modified until its job is done (it is not copied on submit).
* Request callbacks and ``state_changed`` are delivered through a queued private signal, so
  they run on the thread of the service object (the GUI thread) at the next event-loop turn,
  never synchronously inside request(). An exception raised by a callback goes to
  ``sys.excepthook`` (the app's crash handler), never into Qt.
"""

from __future__ import annotations

import enum
import heapq
import itertools
import logging
import sys
import threading
import time
from collections.abc import Callable
from concurrent.futures import CancelledError, Future, InvalidStateError
from concurrent.futures import wait as futures_wait
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from PyQt6.QtCore import QCoreApplication, QObject, Qt, pyqtSignal

from ..i18n import tr
from ..models import OcrOptions, OcrResult, OcrSettings, Point, clone
from . import imageio
from .engine import CODE_LINE, OcrEngine, OcrUnavailable, short_error, unavailable

log = logging.getLogger(__name__)

SLICE_S = 0.05  # longest blocking wait between cancel checks


class OcrState(enum.StrEnum):
    NOT_STARTED = "not_started"
    LOADING = "loading"
    READY = "ready"
    FAILED = "failed"
    DISABLED = "disabled"

    def label(self) -> str:
        """Short status text (status bar / settings page)."""
        return {OcrState.NOT_STARTED: tr("未啟動", "Not started"), OcrState.LOADING: tr("載入中", "Loading"),
                OcrState.READY: tr("就緒", "Ready"), OcrState.FAILED: tr("無法使用", "Unavailable"),
                OcrState.DISABLED: tr("已關閉", "Off")}[self]


class OcrCancelled(Exception):
    """recognize() was cancelled by its ``cancel`` callback."""


class OcrTimeout(TimeoutError):
    """recognize() did not get a result within ``timeout_s``."""


def timeout_message() -> str:
    """The 7.1 OCR-timeout text."""
    return tr("文字辨識逾時。請縮小搜尋範圍，或在設定中重新啟動文字辨識引擎。",
              "Text recognition timed out. Use a smaller search region or restart the OCR engine in Settings.")


def disabled_error() -> OcrUnavailable:
    reason = tr("文字辨識已在設定中關閉", "text recognition is turned off in Settings")
    return OcrUnavailable(tr("文字辨識已在設定中關閉，請到「設定 > 文字辨識」開啟後再試。",
                             "Text recognition is turned off. Turn it on in Settings > Text recognition and try again."),
                          reason)


def _cancelled() -> OcrCancelled:
    return OcrCancelled(tr("文字辨識已取消", "Text recognition was cancelled"))


def _settle(fut: Future[Any], result: Any = None, exc: BaseException | None = None) -> None:
    """Finish ``fut`` unless it is already finished or cancelled (races are expected)."""
    try:
        if exc is not None:
            fut.set_exception(exc)
        else:
            fut.set_result(result)
    except InvalidStateError:
        pass


@dataclass(order=True)
class _Job:
    priority: int
    seq: int
    image: np.ndarray = field(compare=False)
    opts: OcrOptions = field(compare=False)
    origin: Point = field(compare=False)
    future: Future[OcrResult] = field(compare=False)


def _process(engine: Any, job: _Job) -> OcrResult:
    """Run one job on the worker thread."""
    t0 = time.perf_counter()
    img = imageio.to_bgr(job.image)
    h, w = img.shape[:2]
    opts = job.opts
    lines = [] if h == 0 or w == 0 else list(engine.recognize(img, upscale=opts.upscale, det_side=opts.det_side))
    if opts.min_score > 0:
        lines = [ln for ln in lines if ln.score >= opts.min_score]
    if opts.code_charset and lines:
        for ln in lines:
            if not CODE_LINE.search(ln.text):
                continue
            try:
                if opts.upscale > 1:
                    text, confs = engine.reread_line(img, ln.quad, opts.code_charset, upscale=opts.upscale)
                else:
                    text, confs = engine.reread_line(img, ln.quad, opts.code_charset)
            except Exception as exc:  # noqa: BLE001 - keep the plain reading of this line
                log.warning("constrained re-read failed: %s", short_error(exc))
                continue
            if text:
                ln.text = text
                ln.char_confs = [float(c) for c in confs]
    elapsed = (time.perf_counter() - t0) * 1000.0
    log.debug("OCR %dx%d upscale %d det_side %d: %d lines in %.0f ms", w, h, opts.upscale, opts.det_side,
              len(lines), elapsed)
    return OcrResult(lines=lines, width=w, height=h, elapsed_ms=elapsed, origin=(int(job.origin[0]), int(job.origin[1])))


class _Worker:
    """One generation of the OCR worker: its own job heap, stop flag, engine and daemon thread."""

    def __init__(self, service: OcrService, settings: OcrSettings, factory: Callable[[], Any] | None) -> None:
        self.service = service
        self.settings = settings
        self.factory = factory
        self.cond = threading.Condition()
        self.heap: list[_Job] = []
        self.stopped = False
        self.running: _Job | None = None
        self.thread = threading.Thread(target=self._run, name="AutoPress-OCR", daemon=True)

    def put(self, job: _Job) -> bool:
        with self.cond:
            if self.stopped:
                return False
            heapq.heappush(self.heap, job)
            self.cond.notify()
            return True

    def adopt(self, jobs: list[_Job]) -> None:
        with self.cond:
            self.heap.extend(jobs)
            heapq.heapify(self.heap)
            self.cond.notify()

    def retire(self) -> list[_Job]:
        """Stop taking jobs; return the pending ones (the running job finishes normally)."""
        with self.cond:
            self.stopped = True
            jobs, self.heap = self.heap, []
            self.cond.notify_all()
            return jobs

    def stop(self, make_exc: Callable[[], BaseException]) -> None:
        """Stop and fail the pending AND the running job (its inference result is dropped)."""
        for job in self.retire():
            _settle(job.future, exc=make_exc())
        with self.cond:
            running = self.running
        if running is not None:
            _settle(running.future, exc=make_exc())

    def _run(self) -> None:
        t0 = time.perf_counter()
        try:
            if self.factory is not None:
                engine = self.factory()
            else:
                engine = OcrEngine(threads=self.settings.threads, det_side=self.settings.det_side)
            if self.settings.warmup_on_start:
                warm = getattr(engine, "warmup", None)
                if callable(warm):
                    warm()
        except Exception as exc:  # noqa: BLE001 - every start failure -> FAILED with a reason
            if isinstance(exc, OcrUnavailable):
                err = exc
                log.error("OCR engine unavailable: %s", exc.reason)
            else:
                err = unavailable(short_error(exc))
                log.error("OCR engine failed to start", exc_info=True)
            self.service._worker_failed(self, err)
            for job in self.retire():
                _settle(job.future, exc=OcrUnavailable(str(err), err.reason))
            return
        log.info("OCR engine ready after %.2f s", time.perf_counter() - t0)
        if not self.service._worker_ready(self):
            return  # retired while loading (restart / shutdown)
        while True:
            with self.cond:
                while not self.heap and not self.stopped:
                    self.cond.wait()
                if self.stopped:
                    break
                job = heapq.heappop(self.heap)
                if not job.future.set_running_or_notify_cancel():
                    continue  # cancelled while queued
                self.running = job
            try:
                result = _process(engine, job)
            except Exception as exc:  # noqa: BLE001 - the job's future carries the error
                log.warning("OCR job failed: %s", short_error(exc), exc_info=True)
                _settle(job.future, exc=exc)
            else:
                _settle(job.future, result=result)
            finally:
                with self.cond:
                    self.running = None


class OcrService(QObject):
    state_changed = pyqtSignal(str)  # OcrState value; emitted on the GUI thread
    _post = pyqtSignal(object)  # private: run a callable on the service's (GUI) thread

    def __init__(self, settings: OcrSettings | None = None,
                 engine_factory: Callable[[], OcrEngine] | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        app = QCoreApplication.instance()
        if parent is None and app is not None and not app.thread().isCurrentThread():
            self.moveToThread(app.thread())  # callbacks belong on the GUI thread
        self._lock = threading.Lock()
        self._changed = threading.Condition(self._lock)
        self._settings = clone(settings) if settings is not None else OcrSettings()
        self._factory = engine_factory
        self._state = OcrState.NOT_STARTED if self._settings.enabled else OcrState.DISABLED
        self._error: OcrUnavailable | None = None
        self._worker: _Worker | None = None
        self._shut_down = False
        self._seq = itertools.count()
        self._ids = itertools.count(1)
        self._requests: dict[int, Future[OcrResult]] = {}
        self._warned_gui_block = False
        self._post.connect(self._run_posted, Qt.ConnectionType.QueuedConnection)

    # ------------------------------------------------------------------ state

    @property
    def state(self) -> OcrState:
        return self._state

    @property
    def error(self) -> str:
        """Localized reason when state is FAILED, else ""."""
        with self._lock:
            return self._error.reason if self._state is OcrState.FAILED and self._error is not None else ""

    @property
    def error_message(self) -> str:
        """The full 7.1 sentence for a FAILED engine (what its jobs raise), else ""."""
        with self._lock:
            return str(self._error) if self._state is OcrState.FAILED and self._error is not None else ""

    @property
    def settings(self) -> OcrSettings:
        """A copy of the settings in use."""
        with self._lock:
            return clone(self._settings)

    def _set_state_locked(self, state: OcrState, error: OcrUnavailable | None = None) -> None:
        if state is self._state and error is self._error:
            return
        self._state, self._error = state, error
        self._changed.notify_all()
        value = state.value
        self._call_soon(lambda: self.state_changed.emit(value))

    def _call_soon(self, fn: Callable[[], None]) -> None:
        try:
            self._post.emit(fn)
        except RuntimeError:  # the QObject is already gone (app exit)
            pass

    def _run_posted(self, fn: Callable[[], None]) -> None:
        try:
            fn()
        except RuntimeError as exc:
            if "has been deleted" in str(exc):  # the requesting widget closed before the result came
                log.debug("OCR callback target already deleted: %s", exc)
            else:
                sys.excepthook(*sys.exc_info())
        except Exception:  # noqa: BLE001 - never let an exception reach Qt's event loop
            sys.excepthook(*sys.exc_info())

    def _worker_ready(self, worker: _Worker) -> bool:
        with self._lock:
            if worker is not self._worker:
                return False
            self._set_state_locked(OcrState.READY)
            return True

    def _worker_failed(self, worker: _Worker, err: OcrUnavailable) -> None:
        with self._lock:
            if worker is not self._worker:
                return
            self._worker = None
            self._set_state_locked(OcrState.FAILED, err)

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> None:
        """Start the worker (non-blocking, idempotent)."""
        with self._lock:
            self._shut_down = False
            if not self._settings.enabled:
                self._set_state_locked(OcrState.DISABLED)
                return
            if self._worker is not None or self._state is OcrState.FAILED:
                return
            worker = self._new_worker_locked()
        worker.thread.start()

    def _new_worker_locked(self) -> _Worker:
        worker = _Worker(self, clone(self._settings), self._factory)
        self._worker = worker
        self._set_state_locked(OcrState.LOADING)
        return worker

    def shutdown(self, timeout_s: float = 2.0) -> None:
        """Stop the worker; pending jobs fail with OcrCancelled. Waits up to ``timeout_s`` for a
        running inference, then abandons it (daemon thread; its result is dropped). Safe to call
        twice. Test: shutdown during a slow fake inference neither hangs nor crashes."""
        with self._lock:
            worker, self._worker = self._worker, None
            self._shut_down = True
            if self._state is not OcrState.DISABLED:
                self._set_state_locked(OcrState.NOT_STARTED)
        if worker is None:
            return
        worker.stop(_cancelled)
        if timeout_s and timeout_s > 0:
            worker.thread.join(timeout_s)
            if worker.thread.is_alive():
                log.warning("OCR worker still busy after %.1f s; abandoned (daemon thread)", timeout_s)

    def restart(self, settings: OcrSettings | None = None) -> None:
        """Same object, new worker: shutdown(), take ``settings`` (None = keep the current ones),
        then start() - state DISABLED when settings.enabled is False. Non-blocking (GUI thread).
        Pending jobs are handed to the new worker instead of failing."""
        worker: _Worker | None = None
        failed: list[_Job] = []
        with self._lock:
            if settings is not None:
                self._settings = clone(settings)
            old, self._worker = self._worker, None
            self._shut_down = False
            pending = old.retire() if old is not None else []
            if not self._settings.enabled:
                self._set_state_locked(OcrState.DISABLED)
                failed = pending
            else:
                self._state = OcrState.NOT_STARTED  # the transition below always emits LOADING
                worker = self._new_worker_locked()
                worker.adopt(pending)
        for job in failed:
            _settle(job.future, exc=disabled_error())
        if worker is not None:
            worker.thread.start()

    def wait_ready(self, timeout_s: float = 30.0, cancel: Callable[[], bool] | None = None) -> bool:
        """Block (worker threads only) until READY; False on FAILED/DISABLED/timeout/cancel."""
        if self._state is OcrState.NOT_STARTED and not self._shut_down:
            self.start()
        deadline = time.monotonic() + max(0.0, float(timeout_s))
        while True:
            state = self._state
            if state is OcrState.READY:
                return True
            if state in (OcrState.FAILED, OcrState.DISABLED, OcrState.NOT_STARTED):
                return False
            if cancel is not None and cancel():
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            with self._changed:
                if self._state is OcrState.LOADING:
                    self._changed.wait(min(SLICE_S, remaining))

    # ------------------------------------------------------------------ jobs

    def submit(self, image: np.ndarray, opts: OcrOptions | None = None, priority: int = 1, *,
               origin: Point = (0, 0)) -> Future[OcrResult]:
        """Queue a job from any thread. The future fails with engine.OcrUnavailable when the
        engine is FAILED/DISABLED."""
        if not isinstance(image, np.ndarray) or image.ndim not in (2, 3):
            raise TypeError(f"OCR needs an HxW or HxWxC numpy image, got {type(image).__name__}")
        if self._state is OcrState.NOT_STARTED and not self._shut_down:
            self.start()
        fut: Future[OcrResult] = Future()
        with self._lock:
            state = self._state
            if state is OcrState.FAILED:
                err = self._error or unavailable("?")
                fut.set_exception(OcrUnavailable(str(err), err.reason))
                return fut
            if state is OcrState.DISABLED:
                fut.set_exception(disabled_error())
                return fut
            worker = self._worker
            if worker is not None:
                job_opts = clone(opts) if opts is not None else OcrOptions(det_side=self._settings.det_side)
                job = _Job(int(priority), next(self._seq), image, job_opts,
                           (int(origin[0]), int(origin[1])), fut)
                if worker.put(job):
                    return fut
        fut.set_exception(_cancelled())  # shut down (not started again)
        return fut

    def recognize(self, image: np.ndarray, opts: OcrOptions | None = None, *, timeout_s: float = 30.0,
                  cancel: Callable[[], bool] | None = None, priority: int = 0,
                  origin: Point = (0, 0)) -> OcrResult:
        """Blocking OCR for the runner thread: submit, then wait in <= 50 ms slices calling
        ``cancel()``. Raises OcrCancelled, OcrTimeout, engine.OcrUnavailable. Never call it on
        the GUI thread."""
        app = QCoreApplication.instance()
        if app is not None and app.thread().isCurrentThread() and not self._warned_gui_block:
            self._warned_gui_block = True
            log.warning("OcrService.recognize() called on the GUI thread; use request() there")
        fut = self.submit(image, opts, priority, origin=origin)
        deadline = time.monotonic() + max(0.0, float(timeout_s))
        while not fut.done():
            if cancel is not None and cancel():
                fut.cancel()
                raise _cancelled()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                fut.cancel()
                raise OcrTimeout(timeout_message())
            futures_wait([fut], timeout=min(SLICE_S, remaining))
        try:
            return fut.result()
        except CancelledError as exc:
            raise _cancelled() from exc

    def request(self, image: np.ndarray, opts: OcrOptions | None, on_done: Callable[[OcrResult], None],
                on_error: Callable[[Exception], None] | None = None, priority: int = 1, *,
                origin: Point = (0, 0)) -> int:
        """Asynchronous OCR for the UI: callbacks are invoked on the GUI thread. Returns a job id."""
        job_id = next(self._ids)
        fut = self.submit(image, opts, priority, origin=origin)
        with self._lock:
            self._requests[job_id] = fut

        def done(f: Future[OcrResult]) -> None:
            self._call_soon(lambda: self._deliver(job_id, f, on_done, on_error))

        fut.add_done_callback(done)
        return job_id

    def _deliver(self, job_id: int, fut: Future[OcrResult], on_done: Callable[[OcrResult], None],
                 on_error: Callable[[Exception], None] | None) -> None:
        with self._lock:
            live = self._requests.pop(job_id, None) is not None
        if not live or fut.cancelled():
            return
        exc = fut.exception()
        if exc is None:
            on_done(fut.result())
        elif on_error is not None:
            on_error(exc)  # type: ignore[arg-type]
        else:
            log.warning("OCR request %d failed: %s", job_id, short_error(exc))

    def cancel_request(self, job_id: int) -> None:
        """Drop a pending request; its callbacks will not be called."""
        with self._lock:
            fut = self._requests.pop(job_id, None)
        if fut is not None:
            fut.cancel()
