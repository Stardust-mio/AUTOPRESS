# OWNED BY G2 - replace this stub
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
"""

from __future__ import annotations

import enum
from collections.abc import Callable
from concurrent.futures import Future

import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal

from ..models import OcrOptions, OcrResult, OcrSettings
from .engine import OcrEngine

__stub__ = True


class OcrState(enum.StrEnum):
    NOT_STARTED = "not_started"
    LOADING = "loading"
    READY = "ready"
    FAILED = "failed"
    DISABLED = "disabled"


class OcrCancelled(Exception):
    """recognize() was cancelled by its ``cancel`` callback."""


class OcrTimeout(TimeoutError):
    """recognize() did not get a result within ``timeout_s``."""


class OcrService(QObject):
    state_changed = pyqtSignal(str)  # OcrState value; emitted on the GUI thread

    def __init__(self, settings: OcrSettings | None = None,
                 engine_factory: Callable[[], OcrEngine] | None = None, parent: QObject | None = None) -> None:
        raise NotImplementedError

    @property
    def state(self) -> OcrState:
        raise NotImplementedError

    @property
    def error(self) -> str:
        """Localized reason when state is FAILED, else ""."""
        raise NotImplementedError

    def start(self) -> None:
        """Start the worker (non-blocking, idempotent)."""
        raise NotImplementedError

    def shutdown(self, timeout_s: float = 2.0) -> None:
        """Stop the worker; pending jobs fail with OcrCancelled. Waits up to ``timeout_s`` for a
        running inference, then abandons it (daemon thread; its result is dropped). Safe to call
        twice. Test: shutdown during a slow fake inference neither hangs nor crashes."""
        raise NotImplementedError

    def restart(self, settings: OcrSettings | None = None) -> None:
        """Same object, new worker: shutdown(), take ``settings`` (None = keep the current ones),
        then start() - state DISABLED when settings.enabled is False. Non-blocking (GUI thread)."""
        raise NotImplementedError

    def wait_ready(self, timeout_s: float = 30.0, cancel: Callable[[], bool] | None = None) -> bool:
        """Block (worker threads only) until READY; False on FAILED/DISABLED/timeout/cancel."""
        raise NotImplementedError

    def submit(self, image: np.ndarray, opts: OcrOptions | None = None, priority: int = 1) -> Future[OcrResult]:
        """Queue a job from any thread. The future fails with engine.OcrUnavailable when the
        engine is FAILED/DISABLED."""
        raise NotImplementedError

    def recognize(self, image: np.ndarray, opts: OcrOptions | None = None, *, timeout_s: float = 30.0,
                  cancel: Callable[[], bool] | None = None, priority: int = 0) -> OcrResult:
        """Blocking OCR for the runner thread: submit, then wait in <= 50 ms slices calling
        ``cancel()``. Raises OcrCancelled, OcrTimeout, engine.OcrUnavailable. Never call it on
        the GUI thread."""
        raise NotImplementedError

    def request(self, image: np.ndarray, opts: OcrOptions | None, on_done: Callable[[OcrResult], None],
                on_error: Callable[[Exception], None] | None = None, priority: int = 1) -> int:
        """Asynchronous OCR for the UI: callbacks are invoked on the GUI thread. Returns a job id."""
        raise NotImplementedError

    def cancel_request(self, job_id: int) -> None:
        """Drop a pending request; its callbacks will not be called."""
        raise NotImplementedError
