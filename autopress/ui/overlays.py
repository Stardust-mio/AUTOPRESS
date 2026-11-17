# OWNED BY G7 - replace this stub
"""Full-screen overlays (win32_windows.md section 5).

Picker: grab every monitor (capture.Grabber.grab_all) after hiding ``hide_windows`` (+ 200 ms),
then one frameless, always-on-top Tool overlay per QScreen (setGeometry(screen.geometry()))
painting its monitor's frozen shot as a QImage with setDevicePixelRatio(screen dpr) at (0, 0)
-> 1:1 physical pixels. Mouse -> physical with win32.dpi.local_to_physical(screen,
event.position()). Crosshair, 4x magnifier, live x/y, instruction text, the target's client
rect outlined (``target_hwnd``). Esc cancels. Window mode hides the overlays before
win32.windows.window_at(). Overlays take keyboard focus only while picking.
Preview: transparent, click-through (WindowTransparentForInput), topmost, never activated;
numbered markers for PreviewMarks (red when not ok). Countdown: big 3-2-1 centred on the
target's monitor, click-through, never activated.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QWidget

from ..models import Point, PreviewMark, Rect

__stub__ = True


@dataclass
class PickResult:
    kind: str = "point"  # "point" | "region" | "window"
    point: Point | None = None  # physical
    rect: Rect | None = None  # physical (region mode)
    hwnd: int = 0  # root window (window mode)
    image: np.ndarray | None = None  # BGRA crop of the frozen screenshot (region mode)


class ScreenPicker(QObject):
    finished = pyqtSignal(object)  # PickResult, or None when cancelled

    def __init__(self, parent: QObject | None = None) -> None:
        raise NotImplementedError

    def start(self, kind: str, *, instruction: str = "", target_hwnd: int = 0,
              hide_windows: Sequence[QWidget] = ()) -> None:
        """Begin picking; ``finished`` fires once. Hidden windows are shown again afterwards."""
        raise NotImplementedError

    def cancel(self) -> None:
        raise NotImplementedError


def pick(kind: str, *, instruction: str = "", target_hwnd: int = 0,
         hide_windows: Sequence[QWidget] = ()) -> PickResult | None:
    """Blocking convenience wrapper (local QEventLoop, GUI thread). None when cancelled."""
    raise NotImplementedError


class PreviewOverlay(QObject):
    def __init__(self, parent: QObject | None = None) -> None:
        raise NotImplementedError

    def show_marks(self, marks: Sequence[PreviewMark], duration_ms: int = 6000) -> None:
        raise NotImplementedError

    def hide(self) -> None:
        raise NotImplementedError


class CountdownOverlay(QObject):
    done = pyqtSignal()
    cancelled = pyqtSignal()

    def __init__(self, parent: QObject | None = None) -> None:
        raise NotImplementedError

    def start(self, seconds: int, monitor_rect: Rect | None = None, hint: str = "") -> None:
        """``seconds`` == 0 emits ``done`` on the next event-loop turn. ``hint`` is shown under
        the digits - RunFlow passes 「F9 停止 · 滑鼠移到 ↖ 這個角落＝緊急停止」 with the arrow
        drawn towards the real failsafe corner (models.failsafe_corners)."""
        raise NotImplementedError

    def cancel(self) -> None:
        raise NotImplementedError
