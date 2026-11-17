# OWNED BY G5 - replace this stub
"""Toasts: overlay r10 cards in the main window's top-right corner, icon + text + optional
action, auto-hide after 4 s, stacked (max 3). While the main window is hidden (run mode)
toasts are dropped (the run log and the mini bar carry the information), so nothing a user must
act on during a run may be a toast only (hotkey failures are a dialog before the countdown)."""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QWidget

from ..context import AppSignals

__stub__ = True


class ToastManager(QObject):
    def __init__(self, host: QWidget) -> None:
        raise NotImplementedError

    def attach_signals(self, signals: AppSignals) -> None:
        """Show every ``signals.toast(kind, text)``."""
        raise NotImplementedError

    def show_toast(self, text: str, kind: str = "info", action_text: str = "",
                   action: Callable[[], None] | None = None, timeout_ms: int = 4000) -> None:
        raise NotImplementedError
