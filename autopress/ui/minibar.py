# OWNED BY G7 - replace this stub
"""Mini run bar (mock-up docs/research/ux/minibar_dark.png): r14 overlay with shadow, grip,
ProgressRing, current code (mono), last result chips, 暫停 / 繼續 / 停止 buttons with keycaps,
expand. Frameless | Tool | WindowStaysOnTopHint | WindowDoesNotAcceptFocus,
WA_ShowWithoutActivating: it never takes the foreground from the target. Draggable (Qt mouse
events, not the native move loop); position saved in Settings.minibar_pos.

Never in the way of the run (T01 / PX-03): RunFlow places it with place_away_from(every
PreviewMark rect, target client rect); after show / move / hide RunFlow publishes its physical
frame rect with ctx.session.set_masked_rects (the runner blanks it in every capture) and calls
win32.windows.exclude_from_capture on it (best effort). If a click point still ends up under
it, the guard pauses with 「AutoPress 的迷你控制列擋住了點擊位置」 and the user drags it away.
The pause / resume button is disabled for 0.7 s after every state change (no flip under the
user's hand, PX-11). Tooltip and paused state show the failsafe hint (F9 / corner). Dialogs
opened from the bar use it as parent."""

from __future__ import annotations

from collections.abc import Sequence

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget

from ..context import AppContext
from ..models import CodeStatus, Rect

__stub__ = True


class MiniBar(QWidget):
    pauseClicked = pyqtSignal()
    stopClicked = pyqtSignal()
    expandClicked = pyqtSignal()

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        raise NotImplementedError

    def set_progress(self, done: int, total: int, eta_s: float) -> None:
        raise NotImplementedError

    def set_current(self, code: str, step_title: str = "") -> None:
        raise NotImplementedError

    def set_state(self, state: str, reason: str = "") -> None:
        raise NotImplementedError

    def add_result(self, status: CodeStatus) -> None:
        raise NotImplementedError

    def place_away_from(self, avoid: Sequence[Rect] = (), target: Rect | None = None) -> None:
        """Choose the bar position (physical rects): the saved Settings.minibar_pos when it
        intersects no ``avoid`` rect; else, in this order, a monitor that does not contain the
        ``target`` client rect, a corner of the target's monitor outside ``target``, a corner
        inside ``target`` that intersects no ``avoid`` rect (points inflated by 24 px), and
        finally the corner with the smallest overlap in compact one-line form."""
        raise NotImplementedError
