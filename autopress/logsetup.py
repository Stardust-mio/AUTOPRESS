"""Logging setup and crash reporting.

OWNED BY A1 (foundation). Library code uses ``logging.getLogger(__name__)`` and never prints.

* ``setup_logging()`` (called once by ui.app.main) writes ``<data>/logs/autopress.log``
  (UTF-8, rotating 1 MB x 3) and, when a console exists, also to stderr. A windowed
  PyInstaller exe has ``sys.stderr is None``; that case is handled.
* ``install_excepthook()`` logs uncaught exceptions of the main thread and of Python threads
  (``threading.excepthook``) and calls an optional UI callback with a short message.
* ``mask_code()`` - codes belong to the user: log them masked (``ABC***YZ``).
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
import threading
import traceback
from collections.abc import Callable
from pathlib import Path

from . import paths

__all__ = ["LOG_FILE_NAME", "install_excepthook", "mask_code", "setup_logging"]

LOG_FILE_NAME = "autopress.log"
_FORMAT = "%(asctime)s %(levelname)-7s %(threadName)s %(name)s: %(message)s"
_configured_handlers: list[logging.Handler] = []


def setup_logging(level: int = logging.INFO, console: bool | None = None, log_dir: Path | None = None) -> Path:
    """Configure the root logger (idempotent: earlier AutoPress handlers are replaced).
    ``console=None`` means "when sys.stderr exists". Returns the log file path."""
    root = logging.getLogger()
    for h in _configured_handlers:
        root.removeHandler(h)
        h.close()
    _configured_handlers.clear()
    directory = Path(log_dir) if log_dir is not None else paths.logs_dir()
    directory.mkdir(parents=True, exist_ok=True)
    log_file = directory / LOG_FILE_NAME
    fh = logging.handlers.RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(fh)
    _configured_handlers.append(fh)
    if console is None:
        console = sys.stderr is not None
    if console and sys.stderr is not None:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        root.addHandler(sh)
        _configured_handlers.append(sh)
    root.setLevel(level)
    for noisy in ("PIL", "rapidocr", "RapidOCR", "onnxruntime", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return log_file


def install_excepthook(on_error: Callable[[str], None] | None = None) -> None:
    """Log uncaught exceptions (main thread and ``threading``); call ``on_error(summary)``.
    The callback must be thread-safe (e.g. emit a Qt signal); its own errors are swallowed."""
    log = logging.getLogger("autopress.crash")

    def report(exc_type: type[BaseException], exc: BaseException, tb: object) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            return
        text = "".join(traceback.format_exception(exc_type, exc, tb))  # type: ignore[arg-type]
        log.critical("uncaught exception\n%s", text)
        if on_error is not None:
            try:
                on_error(f"{exc_type.__name__}: {exc}")
            except Exception:  # noqa: BLE001 - never raise from the hook
                log.exception("on_error callback failed")

    sys.excepthook = report

    def thread_hook(args: threading.ExceptHookArgs) -> None:
        if args.exc_type is not None and args.exc_value is not None:
            report(args.exc_type, args.exc_value, args.exc_traceback)

    threading.excepthook = thread_hook


def mask_code(code: str) -> str:
    """``"ABCD-1234-EFGH"`` -> ``"ABC***GH"``; codes of 6 characters or less -> ``"***"``."""
    c = code or ""
    if len(c) <= 6:
        return "***"
    return f"{c[:3]}***{c[-2:]}"
