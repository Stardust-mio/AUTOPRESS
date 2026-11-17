"""Application context passed to every page / dialog: shared services and app-wide signals.

OWNED BY A1 (foundation). ui.app (G5) builds exactly one ``AppContext`` at startup; pages
receive it as their first constructor argument (``CodesPage(ctx)``) and keep a reference.
Everything here is used from the GUI thread only.

Tests and screenshots build a context from fakes: ``tests/fakes.py: demo_context()``.

The services are created once and NEVER replaced (RunSession keeps references to them): new OCR
settings go through ``ctx.ocr.restart(settings.ocr)``, never a new OcrService.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QObject, pyqtSignal

from . import storage
from .models import Profile, Settings

if TYPE_CHECKING:  # imported for type checkers only; avoids import cycles and Qt-free stubs
    from PyQt6.QtWidgets import QWidget

    from .codes.history import HistoryStore
    from .codes.queue import CodeQueue
    from .ocr.service import OcrService
    from .runner.engine import RunSession
    from .storage import ProfileStore
    from .win32.hotkeys import GlobalHotkeys

__all__ = ["PAGE_IDS", "AppContext", "AppSignals"]

log = logging.getLogger(__name__)

PAGE_IDS: tuple[str, ...] = ("codes", "profiles", "run", "history", "settings", "help")
"""Navigation ids of the main-window pages (ui.main_window)."""


class AppSignals(QObject):
    """App-wide notifications (all emitted and received on the GUI thread)."""

    settings_changed = pyqtSignal(object)  # Settings - after AppContext.save_settings()
    profiles_changed = pyqtSignal()  # a profile was created, saved, renamed or deleted
    active_profile_changed = pyqtSignal(str)  # profile id ("" = none)
    navigate = pyqtSignal(str)  # page id from PAGE_IDS; MainWindow switches pages
    theme_changed = pyqtSignal(str)  # resolved theme "dark" | "light" (after apply)
    toast = pyqtSignal(str, str)  # (kind: info|success|warning|error, text) -> ToastManager


@dataclass
class AppContext:
    settings: Settings
    profiles: ProfileStore
    queue: CodeQueue
    history: HistoryStore
    ocr: OcrService
    session: RunSession
    hotkeys: GlobalHotkeys
    signals: AppSignals = field(default_factory=AppSignals)
    main_window: QWidget | None = None  # set by ui.app after MainWindow is created
    extras: dict[str, Any] = field(default_factory=dict)  # free slot for integration glue

    # -- settings ------------------------------------------------------------------------
    def save_settings(self) -> None:
        """Persist ``self.settings`` and emit ``signals.settings_changed``."""
        try:
            storage.save_settings(self.settings)
        except storage.StorageError as exc:
            log.error("saving settings failed: %s", exc)
            self.notify(str(exc), "error")
        self.signals.settings_changed.emit(self.settings)

    # -- active profile --------------------------------------------------------------------
    def active_profile(self) -> Profile | None:
        """The profile used by the Codes page (format, history key) and the Run page."""
        pid = self.settings.active_profile_id
        return self.profiles.get(pid) if pid else None

    def set_active_profile(self, profile_id: str) -> None:
        if profile_id == self.settings.active_profile_id:
            return
        self.settings.active_profile_id = profile_id
        self.save_settings()
        self.signals.active_profile_changed.emit(profile_id)

    # -- feedback --------------------------------------------------------------------------
    def notify(self, text: str, kind: str = "info") -> None:
        """Show a toast (kind: info | success | warning | error)."""
        self.signals.toast.emit(kind, text)

    def navigate(self, page_id: str) -> None:
        self.signals.navigate.emit(page_id)
