# OWNED BY G5
"""Toasts: overlay r10 cards in the main window's top-right corner, icon + text + optional
action, auto-hide after 4 s, stacked (max 3). While the main window is hidden (run mode)
toasts are dropped (the run log and the mini bar carry the information), so nothing a user must
act on during a run may be a toast only (hotkey failures are a dialog before the countdown).

``ToastManager.shown`` keeps every request as (kind, text), displayed or not (the
tests/ui_fallback.py stand-in offered the same list); ``toasts()`` returns the visible cards.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer
from PyQt6.QtGui import QEnterEvent
from PyQt6.QtWidgets import QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QPushButton, QToolButton, QWidget

from ..context import AppSignals
from ..i18n import tr
from . import icons, theme

log = logging.getLogger(__name__)

MAX_TOASTS = 3
TOAST_W = 360
MARGIN = 16
GAP = 8
_KIND = {"info": ("info", "info"), "success": ("check", "success"), "warning": ("alert", "warning"),
         "error": ("alert", "error")}


class Toast(QFrame):
    """One toast card (frameRole "toast"); closes itself after ``timeout_ms`` (paused while the
    mouse is over it)."""

    def __init__(self, manager: ToastManager, text: str, kind: str, action_text: str,
                 action: Callable[[], None] | None, timeout_ms: int, parent: QWidget) -> None:
        super().__init__(parent)
        self.manager = manager
        self.kind = kind if kind in _KIND else "info"
        self.action_text = action_text
        self._action = action
        self.setProperty("frameRole", "toast")
        self.setFixedWidth(TOAST_W)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(theme.SP[3], theme.SP[1] + 2, theme.SP[1] + 2, theme.SP[1] + 2)
        lay.setSpacing(theme.SP[2] + 2)
        name, tone = _KIND[self.kind]
        ic = QLabel(self)
        ic.setFixedSize(18, 18)
        icons.bind(ic, name, tone, 18)
        lay.addWidget(ic, 0, Qt.AlignmentFlag.AlignVCenter)
        self.label = QLabel(text, self)
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.label, 1)
        self.action_button: QPushButton | None = None
        if action_text:
            b = QPushButton(action_text, self)
            b.setProperty("variant", "ghost")
            b.setProperty("tone", "accent")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFixedHeight(theme.CONTROL_H)
            b.clicked.connect(self._on_action)
            lay.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
            self.action_button = b
        close = QToolButton(self)
        close.setProperty("variant", "icon")
        close.setFixedSize(theme.CONTROL_H, theme.CONTROL_H)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setToolTip(tr("關閉", "Close"))
        close.setAccessibleName(tr("關閉", "Close"))
        icons.bind(close, "x", "text_muted", 14)
        close.clicked.connect(self.dismiss)
        lay.addWidget(close, 0, Qt.AlignmentFlag.AlignVCenter)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 8)
        shadow.setColor(theme.color("shadow"))
        self.setGraphicsEffect(shadow)
        self.setAccessibleName(text)
        self._timeout = max(500, int(timeout_ms))
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        self._closed = False

    def text(self) -> str:
        return self.label.text()

    def start(self) -> None:
        self._timer.start(self._timeout)

    def _on_action(self) -> None:
        action = self._action
        self.dismiss()
        if action is not None:
            try:
                action()
            except Exception:  # noqa: BLE001 - a toast action must never crash the app
                log.exception("toast action failed")

    def dismiss(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._timer.stop()
        self.hide()
        self.manager._removed(self)
        self.deleteLater()

    def enterEvent(self, event: QEnterEvent | None) -> None:
        self._timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent | None) -> None:
        if not self._closed:
            self._timer.start(1500)
        super().leaveEvent(event)


class ToastManager(QObject):
    def __init__(self, host: QWidget) -> None:
        super().__init__(host)
        self.host = host
        self.shown: list[tuple[str, str]] = []  # every request (kind, text)
        self._toasts: list[Toast] = []  # newest first
        host.installEventFilter(self)

    def attach_signals(self, signals: AppSignals) -> None:
        """Show every ``signals.toast(kind, text)``."""
        signals.toast.connect(lambda kind, text: self.show_toast(text, kind))

    def toasts(self) -> list[Toast]:
        """The visible toasts, newest first."""
        return list(self._toasts)

    def _can_show(self) -> bool:
        win = self.host.window()
        return win is not None and win.isVisible() and not win.isMinimized()

    def show_toast(self, text: str, kind: str = "info", action_text: str = "",
                   action: Callable[[], None] | None = None, timeout_ms: int = 4000) -> None:
        self.shown.append((kind, text))
        if not self._can_show():
            log.info("toast dropped (main window hidden): [%s] %s", kind, text)
            return
        toast = Toast(self, text, kind, action_text, action, timeout_ms, self.host)
        self._toasts.insert(0, toast)
        while len(self._toasts) > MAX_TOASTS:
            self._toasts[-1].dismiss()
        toast.adjustSize()
        toast.show()
        toast.raise_()
        toast.start()
        self._layout()

    def clear(self) -> None:
        """Remove every visible toast (e.g. when the window goes into run mode)."""
        for t in list(self._toasts):
            t.dismiss()

    def _removed(self, toast: Toast) -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
            self._layout()

    def _layout(self) -> None:
        y = MARGIN
        right = self.host.width() - MARGIN
        for t in self._toasts:
            h = t.heightForWidth(TOAST_W)  # word-wrapped text: height for the fixed width
            if h > 0:
                t.resize(TOAST_W, h)
            else:
                t.adjustSize()
            t.move(max(MARGIN, right - t.width()), y)
            t.raise_()
            y += t.height() + GAP

    def eventFilter(self, obj: QObject | None, event: QEvent | None) -> bool:
        if obj is self.host and event is not None:
            if event.type() == QEvent.Type.Resize:
                self._layout()
            elif event.type() == QEvent.Type.Hide:
                self.clear()
        return False
