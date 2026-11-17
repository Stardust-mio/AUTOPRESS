# OWNED BY G3 - replace this stub
"""Monitors and logical <-> physical mapping (win32_windows.md sections 1, 5).

Importing this module is side-effect free; CALL its functions only after QApplication exists
(QApplication makes the process per-monitor-v2 aware). Qt keeps each screen's ORIGIN in native
pixels and scales only within the screen:
    phys = origin + qRound((logical - origin) * dpr)      (qRound = round half up)
Match QScreen <-> monitor by native origin, never by name. Never go through global logical
coordinates for widgets: use widget_to_physical (ClientToScreen of the top-level HWND +
qRound(local * dpr)). QCursor.pos() is up to dpr/2 off: use cursor_physical().
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QScreen
from PyQt6.QtWidgets import QWidget

from ..models import Monitor, Point, Rect

__stub__ = True


def process_awareness() -> str:
    """"unaware" | "system" | "pmv1" | "pmv2" (compared with AreDpiAwarenessContextsEqual)."""
    raise NotImplementedError


def ensure_per_monitor_v2() -> str:
    """For Qt-less helper processes only: SetProcessDpiAwarenessContext(-4) if still unaware.
    Returns process_awareness() afterwards. Never call it before QApplication in the app."""
    raise NotImplementedError


def monitors() -> list[Monitor]:
    """EnumDisplayMonitors + GetMonitorInfoW + GetDpiForMonitor, primary first."""
    raise NotImplementedError


def primary_monitor() -> Monitor:
    raise NotImplementedError


def monitor_at(x: int, y: int) -> Monitor:
    """Monitor containing the physical point (nearest when outside all)."""
    raise NotImplementedError


def virtual_screen() -> Rect:
    """SM_XVIRTUALSCREEN .. SM_CYVIRTUALSCREEN (may start at negative x)."""
    raise NotImplementedError


def monitor_for_screen(screen: QScreen) -> Monitor | None:
    """The monitor whose physical origin equals ``screen.geometry().topLeft()``."""
    raise NotImplementedError


def screen_for_monitor(monitor: Monitor) -> QScreen | None:
    raise NotImplementedError


def screen_to_physical(screen: QScreen, p: QPointF) -> Point:
    """Global logical point on ``screen`` -> physical: origin + qRound((p - origin) * dpr)."""
    raise NotImplementedError


def physical_to_screen(screen: QScreen, x: int, y: int) -> QPointF:
    """Inverse of screen_to_physical: origin + (phys - origin) / dpr."""
    raise NotImplementedError


def local_to_physical(screen: QScreen, local: QPointF) -> Point:
    """Point relative to the screen's top-left (e.g. a full-screen overlay's event.position())
    -> physical: monitor origin + qRound(local * dpr)."""
    raise NotImplementedError


def widget_to_physical(widget: QWidget, local: QPointF) -> Point:
    """ClientToScreen(top-level HWND) + qRound(widget.mapTo(top, local) * dpr)."""
    raise NotImplementedError


def cursor_physical() -> Point:
    """GetCursorPos()."""
    raise NotImplementedError
