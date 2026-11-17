# OWNED BY G7
"""Full-screen overlays (win32_windows.md section 5).

Picker: grab every monitor (capture.Grabber.grab_all) after hiding ``hide_windows`` (+ 200 ms),
then one frameless, always-on-top Tool overlay per QScreen (setGeometry(screen.geometry()))
painting its monitor's frozen shot as a QImage with setDevicePixelRatio(screen dpr) at (0, 0)
-> 1:1 physical pixels. Mouse -> physical with ``origin + qRound(event.position() * dpr)``
(ui.overlays_geom.local_to_physical, the same formula as win32.dpi.local_to_physical).
Crosshair, 4x magnifier, live x/y, instruction text, the target's client rect outlined
(``target_hwnd``). Esc (or a right click) cancels. Window mode hides the overlays before
win32.windows.window_at(). Overlays take keyboard focus only while picking. When the capture
layer is unavailable the frozen shot comes from QScreen.grabWindow(0) (same physical pixels).
Preview: transparent, click-through (WindowTransparentForInput), topmost, never activated;
numbered markers for PreviewMarks (red when not ok). Countdown: big 3-2-1 centred on the
target's monitor, click-through, never activated, with an arrow to the failsafe corner
(models.failsafe_corners).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from PyQt6.QtCore import QEventLoop, QObject, QPointF, QTimer, pyqtSignal
from PyQt6.QtGui import QCursor, QGuiApplication
from PyQt6.QtWidgets import QApplication, QWidget

from ..models import Point, PreviewMark, Rect, failsafe_corners, intersect_rect
from .overlays_geom import (
    ScreenGeom,
    clamp_point,
    drag_rect,
    local_to_physical,
    monitor_rects,
    nearest_corner,
    screen_for_physical_rect,
    screen_geoms,
)
from .overlays_widgets import CountdownWidget, MarksOverlay, PickerOverlay, qimage_to_bgra

log = logging.getLogger(__name__)

PICK_KINDS = ("point", "region", "window")
MIN_REGION_PX = 4  # smaller drags are treated as accidental clicks


@dataclass
class PickResult:
    kind: str = "point"  # "point" | "region" | "window"
    point: Point | None = None  # physical
    rect: Rect | None = None  # physical (region mode)
    hwnd: int = 0  # root window (window mode)
    image: np.ndarray | None = None  # BGRA crop of the frozen screenshot (region mode)


def _live_screens() -> list[tuple[object, ScreenGeom]]:
    """(QScreen, ScreenGeom) pairs, primary first."""
    if QGuiApplication.instance() is None:
        return []
    geoms = screen_geoms()
    screens = list(QGuiApplication.screens())
    primary = QGuiApplication.primaryScreen()
    screens.sort(key=lambda s: 0 if s is primary else 1)
    return list(zip(screens, geoms, strict=False))


def _grab_shots(screens: Sequence[tuple[object, ScreenGeom]]) -> list[np.ndarray | None]:
    """Frozen BGRA shot per screen: capture.Grabber.grab_all() matched by monitor origin, else
    QScreen.grabWindow(0) (physical pixels with the screen's dpr on Windows)."""
    shots: list[np.ndarray | None] = [None] * len(screens)
    try:
        from ..capture import Grabber

        grabber = Grabber()
        try:
            pairs = grabber.grab_all()
        finally:
            grabber.close()
        for mon, img in pairs:
            for i, (_s, geom) in enumerate(screens):
                if shots[i] is None and tuple(mon.rect[:2]) == geom.origin:
                    shots[i] = img
    except Exception as exc:  # stub, CaptureError, ...: fall back to Qt
        log.debug("capture.Grabber unavailable for the picker: %s", exc)
    for i, (screen, _geom) in enumerate(screens):
        if shots[i] is None and screen is not None:
            try:
                pm = screen.grabWindow(0)
                if not pm.isNull():
                    shots[i] = qimage_to_bgra(pm.toImage())
            except Exception as exc:  # pragma: no cover - platform specific
                log.debug("grabWindow failed: %s", exc)
    return shots


class ScreenPicker(QObject):
    finished = pyqtSignal(object)  # PickResult, or None when cancelled

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.kind = "point"
        self.instruction = ""
        self.target_hwnd = 0
        self.target_rect: Rect | None = None
        self.overlays: list[PickerOverlay] = []
        self._hidden: list[QWidget] = []
        self._windows: list[object] = []  # WindowInfo list for the window-mode hover outline
        self._active = False
        self._token = 0

    # -- public ---------------------------------------------------------------------------
    def is_active(self) -> bool:
        return self._active

    def start(self, kind: str, *, instruction: str = "", target_hwnd: int = 0,
              hide_windows: Sequence[QWidget] = ()) -> None:
        """Begin picking; ``finished`` fires once. Hidden windows are shown again afterwards."""
        if kind not in PICK_KINDS:
            raise ValueError(f"unknown pick kind {kind!r}")
        if self._active:
            raise RuntimeError("the picker is already active")
        self._active = True
        self._token += 1
        self.kind, self.instruction, self.target_hwnd = kind, instruction, int(target_hwnd or 0)
        self._hidden = []
        for w in hide_windows:
            if w is not None and w.isVisible():
                w.hide()
                self._hidden.append(w)
        token = self._token
        QTimer.singleShot(200 if self._hidden else 30, lambda: self._begin(token))

    def cancel(self) -> None:
        if self._active:
            self._finish(None)

    # -- setup ----------------------------------------------------------------------------
    def _begin(self, token: int) -> None:
        if not self._active or token != self._token:
            return
        screens = _live_screens()
        self.target_rect = self._client_rect(self.target_hwnd)
        if self.kind == "window":
            self._windows = self._list_windows()
        shots = _grab_shots(screens)
        self.build_overlays([(geom, shot) for (_s, geom), shot in zip(screens, shots, strict=False)])

    def build_overlays(self, items: Sequence[tuple[ScreenGeom, np.ndarray | None]]) -> list[PickerOverlay]:
        """Create and show one overlay per (screen geometry, frozen shot) (tests use fake screens)."""
        self.overlays = [PickerOverlay(self, geom, shot) for geom, shot in items]
        cursor = QCursor.pos()
        focus = None
        for ov in self.overlays:
            ov.show()
            ov.raise_()
            if ov.geometry().contains(cursor):
                focus = ov
        focus = focus or (self.overlays[0] if self.overlays else None)
        if focus is not None:
            focus.activateWindow()
            focus.setFocus()
            local = QPointF(cursor - focus.geometry().topLeft())
            focus.cursor_local = local if focus.rect().contains(local.toPoint()) else None
        if not self.overlays:  # no screen at all: nothing to pick on
            QTimer.singleShot(0, self.cancel)
        return self.overlays

    @staticmethod
    def _client_rect(hwnd: int) -> Rect | None:
        if not hwnd:
            return None
        try:
            from ..win32 import windows

            return tuple(windows.client_rect(hwnd))  # type: ignore[return-value]
        except Exception as exc:
            log.debug("client_rect(%s) unavailable: %s", hwnd, exc)
            return None

    @staticmethod
    def _list_windows() -> list[object]:
        try:
            from ..win32 import windows

            return list(windows.list_windows())
        except Exception as exc:
            log.debug("list_windows unavailable: %s", exc)
            return []

    # -- input from the overlays ----------------------------------------------------------
    def physical_at(self, ov: PickerOverlay, local: QPointF) -> Point:
        lx, ly = clamp_point(local.x(), local.y(), ov.geom.logical[2], ov.geom.logical[3])
        return local_to_physical(ov.geom, lx, ly)

    def _clamped(self, ov: PickerOverlay, local: QPointF) -> QPointF:
        lx, ly = clamp_point(local.x(), local.y(), ov.geom.logical[2], ov.geom.logical[3])
        return QPointF(lx, ly)

    def on_move(self, ov: PickerOverlay, local: QPointF) -> None:
        for other in self.overlays:
            if other is not ov and other.cursor_local is not None and other.drag_start is None:
                other.cursor_local = None
                other.update()
        ov.cursor_local = self._clamped(ov, local)
        if self.kind == "window":
            ov.hover_rect, ov.hover_text = self._window_under(self.physical_at(ov, local))
        ov.update()

    def on_press(self, ov: PickerOverlay, local: QPointF) -> None:
        ov.cursor_local = self._clamped(ov, local)
        if self.kind == "region":
            ov.drag_start = ov.cursor_local
            ov.hint = ""
        ov.update()

    def on_release(self, ov: PickerOverlay, local: QPointF) -> None:
        if not self._active:
            return
        p = self.physical_at(ov, local)
        if self.kind == "point":
            self._finish(PickResult(kind="point", point=p))
        elif self.kind == "window":
            self._finish_window(p)
        elif ov.drag_start is not None:
            a = self.physical_at(ov, ov.drag_start)
            rect = drag_rect(a, p)
            ov.drag_start = None
            if rect[2] < MIN_REGION_PX or rect[3] < MIN_REGION_PX:
                from ..i18n import tr

                ov.hint = tr("請按住滑鼠拖曳，框出一個範圍（Esc 取消）", "Hold the mouse button and drag a rectangle (Esc cancels)")
                ov.update()
                return
            self._finish(PickResult(kind="region", rect=rect, image=self._crop(ov, rect)))

    def on_enter(self, ov: PickerOverlay) -> None:
        if self.kind in ("point", "window") and ov.cursor_local is not None:
            self.on_release(ov, ov.cursor_local)

    @staticmethod
    def _crop(ov: PickerOverlay, rect: Rect) -> np.ndarray | None:
        if ov.shot is None or not ov.shot.size:
            return None
        ox, oy = ov.geom.origin
        mon_w = max(1, ov.geom.physical[2])
        scale = ov.shot.shape[1] / mon_w
        x0, y0 = int((rect[0] - ox) * scale), int((rect[1] - oy) * scale)
        x1, y1 = int((rect[0] + rect[2] - ox) * scale), int((rect[1] + rect[3] - oy) * scale)
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(ov.shot.shape[1], x1), min(ov.shot.shape[0], y1)
        if x1 <= x0 or y1 <= y0:
            return None
        return ov.shot[y0:y1, x0:x1].copy()

    def _window_under(self, p: Point) -> tuple[Rect | None, str]:
        for info in self._windows:
            rect = getattr(info, "rect", None)
            if rect and rect[2] > 0 and intersect_rect(rect, (p[0], p[1], 1, 1)) and not getattr(info, "minimized", False):
                title = getattr(info, "title", "") or ""
                exe = getattr(info, "exe_name", "") or ""
                return rect, f"{title} · {exe}" if exe else title
        return None, ""

    def _finish_window(self, p: Point) -> None:
        for ov in self.overlays:  # never hit our own overlays
            ov.hide()
        QApplication.processEvents()
        hwnd = 0
        try:
            from ..win32 import windows

            hwnd = int(windows.window_at(p[0], p[1], skip_own=True) or 0)  # never AutoPress itself
        except Exception as exc:
            log.debug("window_at unavailable: %s", exc)
            for info in self._windows:
                rect = getattr(info, "rect", None)
                if rect and intersect_rect(rect, (p[0], p[1], 1, 1)):
                    hwnd = int(getattr(info, "hwnd", 0))
                    break
        self._finish(PickResult(kind="window", point=p, hwnd=hwnd))

    def _finish(self, result: PickResult | None) -> None:
        if not self._active:
            return
        self._active = False
        self._token += 1
        for ov in self.overlays:
            ov.hide()
            ov.close()
            ov.deleteLater()
        self.overlays = []
        hidden, self._hidden = self._hidden, []
        for w in hidden:
            try:
                w.show()
                w.raise_()
            except RuntimeError:  # deleted meanwhile
                pass
        self.finished.emit(result)


def pick(kind: str, *, instruction: str = "", target_hwnd: int = 0,
         hide_windows: Sequence[QWidget] = ()) -> PickResult | None:
    """Blocking convenience wrapper (local QEventLoop, GUI thread). None when cancelled."""
    picker = ScreenPicker()
    loop = QEventLoop()
    box: dict[str, PickResult | None] = {}

    def done(result: object) -> None:
        box["result"] = result  # type: ignore[assignment]
        loop.quit()

    picker.finished.connect(done)
    picker.start(kind, instruction=instruction, target_hwnd=target_hwnd, hide_windows=hide_windows)
    if "result" not in box:
        loop.exec()
    picker.deleteLater()
    return box.get("result")


class PreviewOverlay(QObject):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.marks: list[PreviewMark] = []
        self.overlays: list[MarksOverlay] = []
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def is_visible(self) -> bool:
        return bool(self.overlays)

    def show_marks(self, marks: Sequence[PreviewMark], duration_ms: int = 6000) -> None:
        """Show the marks on every screen they touch for ``duration_ms`` (<= 0: until hide())."""
        self.hide()
        self.marks = list(marks)
        for _screen, geom in _live_screens():
            mine = [m for m in self.marks if intersect_rect(geom.physical, (m.rect[0], m.rect[1],
                                                                            max(1, m.rect[2]), max(1, m.rect[3])))]
            if mine:
                ov = MarksOverlay(geom, mine)
                ov.show()
                self.overlays.append(ov)
        if duration_ms > 0:
            self._timer.start(int(duration_ms))

    def hide(self) -> None:
        self._timer.stop()
        for ov in self.overlays:
            ov.hide()
            ov.close()
            ov.deleteLater()
        self.overlays = []


class CountdownOverlay(QObject):
    done = pyqtSignal()
    cancelled = pyqtSignal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._remaining = 0
        self._running = False
        self._token = 0
        self.widget: CountdownWidget | None = None

    def is_running(self) -> bool:
        return self._running

    def remaining(self) -> int:
        return self._remaining

    def start(self, seconds: int, monitor_rect: Rect | None = None, hint: str = "") -> None:
        """``seconds`` == 0 emits ``done`` on the next event-loop turn. ``hint`` is shown under
        the digits - RunFlow passes 「F9 停止 · 滑鼠移到 ↖ 這個角落＝緊急停止」 with the arrow
        drawn towards the real failsafe corner (models.failsafe_corners)."""
        self._close_widget()
        self._timer.stop()
        self._token += 1
        self._running = True
        self._remaining = max(0, int(seconds))
        if self._remaining == 0:
            token = self._token
            QTimer.singleShot(0, lambda: self._complete(token))
            return
        geoms = [g for _s, g in _live_screens()]
        geom = screen_for_physical_rect(geoms, monitor_rect)
        if geom is not None:
            corner = nearest_corner(failsafe_corners(monitor_rects()), geom.physical)
            self.widget = CountdownWidget(geom, hint, corner)
            self.widget.set_value(self._remaining)
            self.widget.show()
        self._timer.start()

    def _tick(self) -> None:
        self._remaining -= 1
        if self._remaining <= 0:
            self._complete(self._token)
        elif self.widget is not None:
            self.widget.set_value(self._remaining)

    def _complete(self, token: int) -> None:
        if not self._running or token != self._token:
            return
        self._running = False
        self._timer.stop()
        self._close_widget()
        self.done.emit()

    def cancel(self) -> None:
        if not self._running:
            return
        self._running = False
        self._token += 1
        self._timer.stop()
        self._close_widget()
        self.cancelled.emit()

    def _close_widget(self) -> None:
        if self.widget is not None:
            self.widget.hide()
            self.widget.close()
            self.widget.deleteLater()
            self.widget = None
