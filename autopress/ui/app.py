# OWNED BY G5 - replace this stub
"""Application entry: process setup, QApplication, context wiring, shutdown (SPEC section 2.6)."""

from __future__ import annotations

from collections.abc import Sequence

from PyQt6.QtWidgets import QApplication

from ..context import AppContext
from ..models import Settings

__stub__ = True


def main(argv: Sequence[str] | None = None) -> int:
    """Start AutoPress; returns the exit code (SPEC 2.8). ``--selftest <report.json>`` is
    dispatched FIRST - before create_application - to autopress.selftest.run(report) (G8; it
    creates or reuses the QApplication itself). ``--wait-lock`` (from restart_as_admin) waits
    up to 10 s for the single-instance lock (``QLockFile.tryLock(10000)``)."""
    raise NotImplementedError


def create_application(argv: Sequence[str]) -> QApplication:
    """QApplication (BEFORE any capture / mss use; OPENBLAS_NUM_THREADS=1 is already set by
    main.py / __main__.py before anything imports numpy), app/org name = APP_ID, Fusion style,
    default font, Qt's qtbase_zh_TW translator when the language is zh-TW, and
    ``setQuitOnLastWindowClosed(False)``: during runs the main window is hidden and only Tool
    windows remain, so closing any dialog would otherwise quit the app mid-run (measured, T02).
    The app quits explicitly from MainWindow.closeEvent (and the tray-less exit paths)."""
    raise NotImplementedError


def build_context(app: QApplication, settings: Settings | None = None) -> AppContext:
    """Create stores and services (ProfileStore, CodeQueue.load + recover_after_crash,
    HistoryStore.load + prune_evidence, OcrService, RunSession, GlobalHotkeys) and return the
    AppContext. Does not start OCR or show windows. Services are never replaced later."""
    raise NotImplementedError
