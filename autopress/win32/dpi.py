# OWNED BY G3
"""Monitors and logical <-> physical mapping (win32_windows.md sections 1, 5).

Importing this module is side-effect free; CALL its functions only after QApplication exists
(QApplication makes the process per-monitor-v2 aware). Qt keeps each screen's ORIGIN in native
pixels and scales only within the screen:
    phys = origin + qRound((logical - origin) * dpr)
Match QScreen <-> monitor by native origin, never by name. Never go through global logical
coordinates for widgets: use widget_to_physical (ClientToScreen of the top-level HWND +
qRound(local * dpr)). QCursor.pos() is up to dpr/2 off: use cursor_physical().

qRound is Qt 6's: half away from zero (QPointF(-1.5, 2.5).toPoint() == (-2, 3), measured with
Qt 6.12), which equals "half up" for the non-negative in-screen offsets the formulas use. The
mapping functions only need ``geometry().topLeft()`` and ``devicePixelRatio()`` of the screen, so
tests can pass stand-in objects.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as W
import logging
import math

from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QScreen
from PyQt6.QtWidgets import QWidget

from ..models import Monitor, Point, Rect
from . import api

log = logging.getLogger(__name__)

_last_cursor: list[Point] = [(0, 0)]


def qround(value: float) -> int:
    """Qt 6 qRound: round half away from zero."""
    return int(math.floor(value + 0.5)) if value >= 0 else -int(math.floor(-value + 0.5))


def _monitor(rec: api.MonitorRecord) -> Monitor:
    return Monitor(device=rec.device, rect=rec.rect, work=rec.work, dpi=rec.dpi, primary=rec.primary)


def process_awareness() -> str:
    """"unaware" | "system" | "pmv1" | "pmv2" (compared with AreDpiAwarenessContextsEqual)."""
    ctx = None
    if api.GetDpiAwarenessContextForProcess is not None:
        ctx = api.GetDpiAwarenessContextForProcess(api.GetCurrentProcess())
    elif api.GetThreadDpiAwarenessContext is not None:
        ctx = api.GetThreadDpiAwarenessContext()
    for name, ref in (("pmv2", api.CTX_PMV2), ("pmv1", api.CTX_PMV1), ("system", api.CTX_SYSTEM)):
        if api.contexts_equal(ctx, ref):
            return name
    return "unaware"  # also UNAWARE_GDISCALED


def ensure_per_monitor_v2() -> str:
    """For Qt-less helper processes only: SetProcessDpiAwarenessContext(-4) if still unaware.
    Returns process_awareness() afterwards. Never call it before QApplication in the app."""
    if process_awareness() == "unaware" and api.SetProcessDpiAwarenessContext is not None:
        if not api.SetProcessDpiAwarenessContext(api.CTX_PMV2):
            log.info("SetProcessDpiAwarenessContext(PMv2) failed: error %s", ctypes.get_last_error())
    return process_awareness()


def monitors() -> list[Monitor]:
    """EnumDisplayMonitors + GetMonitorInfoW + GetDpiForMonitor, primary first."""
    recs = api.enum_monitors()
    recs.sort(key=lambda r: not r.primary)  # stable: enumeration order otherwise
    out = [_monitor(r) for r in recs]
    if not out:  # never empty (headless / failure): the primary screen from the system metrics
        w, h = int(api.GetSystemMetrics(api.SM_CXSCREEN)), int(api.GetSystemMetrics(api.SM_CYSCREEN))
        out = [Monitor(device="", rect=(0, 0, w, h), work=(0, 0, w, h), dpi=96, primary=True)]
    return out


def primary_monitor() -> Monitor:
    mons = monitors()
    return next((m for m in mons if m.primary), mons[0])


def monitor_at(x: int, y: int) -> Monitor:
    """Monitor containing the physical point (nearest when outside all)."""
    hmon = api.hwnd_int(api.MonitorFromPoint(W.POINT(int(x), int(y)), api.MONITOR_DEFAULTTONEAREST))
    rec = api.monitor_record(hmon) if hmon else None
    if rec is not None:
        return _monitor(rec)
    return primary_monitor()


def virtual_screen() -> Rect:
    """SM_XVIRTUALSCREEN .. SM_CYVIRTUALSCREEN (may start at negative x)."""
    return api.virtual_screen()


def _origin(screen: QScreen) -> tuple[int, int]:
    tl = screen.geometry().topLeft()
    return int(tl.x()), int(tl.y())


def monitor_for_screen(screen: QScreen) -> Monitor | None:
    """The monitor whose physical origin equals ``screen.geometry().topLeft()``."""
    if screen is None:
        return None
    origin = _origin(screen)
    return next((m for m in monitors() if (m.rect[0], m.rect[1]) == origin), None)


def screen_for_monitor(monitor: Monitor) -> QScreen | None:
    from PyQt6.QtGui import QGuiApplication

    if QGuiApplication.instance() is None:
        return None
    target = (monitor.rect[0], monitor.rect[1])
    return next((s for s in QGuiApplication.screens() if _origin(s) == target), None)


def screen_to_physical(screen: QScreen, p: QPointF) -> Point:
    """Global logical point on ``screen`` -> physical: origin + qRound((p - origin) * dpr)."""
    ox, oy = _origin(screen)
    dpr = float(screen.devicePixelRatio())
    return ox + qround((p.x() - ox) * dpr), oy + qround((p.y() - oy) * dpr)


def physical_to_screen(screen: QScreen, x: int, y: int) -> QPointF:
    """Inverse of screen_to_physical: origin + (phys - origin) / dpr."""
    ox, oy = _origin(screen)
    dpr = float(screen.devicePixelRatio()) or 1.0
    return QPointF(ox + (x - ox) / dpr, oy + (y - oy) / dpr)


def local_to_physical(screen: QScreen, local: QPointF) -> Point:
    """Point relative to the screen's top-left (e.g. a full-screen overlay's event.position())
    -> physical: monitor origin + qRound(local * dpr)."""
    ox, oy = _origin(screen)
    dpr = float(screen.devicePixelRatio())
    return ox + qround(local.x() * dpr), oy + qround(local.y() * dpr)


def _client_origin(hwnd: int) -> Point | None:
    if not hwnd or not api.IsWindow(hwnd):
        return None
    pt = W.POINT(0, 0)
    if not api.ClientToScreen(hwnd, ctypes.byref(pt)):
        return None
    return int(pt.x), int(pt.y)


def widget_to_physical(widget: QWidget, local: QPointF) -> Point:
    """ClientToScreen(top-level HWND) + qRound(widget.mapTo(top, local) * dpr). Without a real
    native window (offscreen platform, not yet shown) it falls back to Qt's global mapping and
    screen_to_physical (up to 1 px off at fractional scaling)."""
    top = widget.window()
    rel = widget.mapTo(top, QPointF(local)) if widget is not top else QPointF(local)
    dpr = float(top.devicePixelRatioF())
    origin = _client_origin(int(top.winId())) if top.windowHandle() is not None else None
    if origin is not None:
        return origin[0] + qround(rel.x() * dpr), origin[1] + qround(rel.y() * dpr)
    screen = top.screen()
    glob = widget.mapToGlobal(QPointF(local))
    if screen is None:
        return qround(glob.x() * dpr), qround(glob.y() * dpr)
    return screen_to_physical(screen, glob)


def cursor_physical() -> Point:
    """GetCursorPos(). When the call fails (locked session) the last position read is returned."""
    pos = api.cursor_pos()
    if pos is None:
        return _last_cursor[0]
    _last_cursor[0] = pos
    return pos
