# OWNED BY G7
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

import logging
from collections.abc import Sequence

from PyQt6.QtCore import QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..context import AppContext
from ..i18n import format_duration, tr
from ..models import CodeStatus, PauseReason, Rect, RunState
from . import theme
from . import widgets as w
from .minibar_place import choose_position
from .overlays_geom import (
    logical_to_physical,
    physical_to_logical,
    qround,
    screen_for_physical_point,
    screen_geoms,
    work_rects,
)

log = logging.getLogger(__name__)

BUTTON_LOCK_MS = 700  # pause / resume disabled after every state change (PX-11)
SHADOW = (16, 10, 16, 22)  # transparent margins around the bar for the drop shadow (l, t, r, b)
CHIP_ORDER = (CodeStatus.SUCCESS, CodeStatus.SUBMITTED, CodeStatus.USED, CodeStatus.INVALID, CodeStatus.EXPIRED,
              CodeStatus.COOLDOWN, CodeStatus.FAILED, CodeStatus.REVIEW, CodeStatus.SKIPPED)


def pause_text(reason: str) -> str:
    """SPEC 7.1 texts for the pauses that stay on the bar; the PauseReason label otherwise."""
    texts = {
        PauseReason.FOCUS_LOST.value: tr("目標視窗失去焦點，已暫停。切回目標視窗後按「繼續」(F8)。",
                                         "The target window lost focus; paused. Switch back and press Resume (F8)."),
        PauseReason.USER_INPUT.value: tr("偵測到滑鼠或鍵盤操作，已暫停以免輸入到錯誤的地方。按「繼續」(F8) 接著做。",
                                         "Mouse or keyboard input detected; paused so nothing goes to the wrong place. "
                                         "Press Resume (F8)."),
        PauseReason.POINT_BLOCKED.value: tr("點擊位置被其他視窗遮住，已暫停。請移開該視窗後按「繼續」。",
                                            "The click position is covered by another window; paused. Move it away and "
                                            "press Resume."),
    }
    if reason in texts:
        return texts[reason]
    try:
        return PauseReason(reason).label()
    except ValueError:
        return reason


def bind_icon(widget: QWidget, name: str, token: str, size: int = 16) -> None:
    """Theme-following icon (icons.bind when G5 provides it, else a one-off QIcon)."""
    try:
        from . import icons

        binder = getattr(icons, "bind", None)
        if binder is not None:
            binder(widget, name, token, size)
        elif hasattr(widget, "setIcon"):
            widget.setIcon(icons.icon(name, token, size))
    except Exception as exc:  # pragma: no cover - icons unavailable
        log.debug("icon %s unavailable: %s", name, exc)


class MiniBar(QWidget):
    pauseClicked = pyqtSignal()
    stopClicked = pyqtSignal()
    expandClicked = pyqtSignal()
    moved = pyqtSignal()  # after a drag (RunFlow republishes the masked rect)

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint
                 | Qt.WindowType.WindowDoesNotAcceptFocus)
        super().__init__(parent, flags)
        self.ctx = ctx
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowTitle("AutoPress")
        self.state = RunState.IDLE.value
        self.reason = ""
        self.counts: dict[CodeStatus, int] = {}
        self.compact = False
        self._done = self._total = 0
        self._eta = -1.0
        self._info = ""
        self._drag_from: QPoint | None = None
        self._drag_origin: QPoint | None = None
        self._lock = QTimer(self)
        self._lock.setSingleShot(True)
        self._lock.timeout.connect(self._unlock)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(*SHADOW)
        self.frame = QFrame()
        self.frame.setObjectName("MiniBar")  # G5 QSS: overlay fill, strong border, r14, raised icon buttons
        self.frame.setProperty("frameRole", "minibar")
        shadow = QGraphicsDropShadowEffect(self.frame)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 8)
        try:
            shadow.setColor(theme.color("shadow"))
        except Exception:
            shadow.setColor(QColor(0, 0, 0, 176))
        self.frame.setGraphicsEffect(shadow)
        outer.addWidget(self.frame)
        b = QHBoxLayout(self.frame)
        b.setContentsMargins(8, 8, 12, 8)
        b.setSpacing(12)
        self.grip = QLabel()
        self.grip.setFixedSize(18, 18)
        try:
            from . import icons

            self.grip.setPixmap(icons.icon_pixmap("drag", "text_disabled", 16))
        except Exception:
            self.grip.setText("⋮")
        self.grip.setToolTip(tr("拖曳移動", "Drag to move"))
        b.addWidget(self.grip, 0, Qt.AlignmentFlag.AlignVCenter)
        self.ring = w.ProgressRing(40)
        b.addWidget(self.ring, 0, Qt.AlignmentFlag.AlignVCenter)
        text = QVBoxLayout()
        text.setSpacing(1)
        line1 = QHBoxLayout()
        line1.setSpacing(8)
        self.state_label = w.label(tr("準備中", "Starting"), "body")
        f = self.state_label.font()
        f.setBold(True)
        self.state_label.setFont(f)
        line1.addWidget(self.state_label)
        self.code_label = w.label("", "mono")
        try:
            self.code_label.setFont(theme.font(theme.FS_MONO, mono=True))
        except Exception:
            pass
        line1.addWidget(self.code_label)
        self.step_label = w.ElidedLabel("")
        self.step_label.setProperty("role", "muted")
        self.step_label.setMaximumWidth(180)
        line1.addWidget(self.step_label)
        line1.addStretch(1)
        text.addLayout(line1)
        self.line2 = QWidget()
        l2 = QHBoxLayout(self.line2)
        l2.setContentsMargins(0, 0, 0, 0)
        l2.setSpacing(6)
        self.chips: dict[CodeStatus, QWidget] = {}
        for st in CHIP_ORDER:
            chip = w.StatusChip(st, f"{st.label()} 0")
            chip.hide()
            l2.addWidget(chip)
            self.chips[st] = chip
        self.info_label = w.label("", "muted")
        l2.addWidget(self.info_label)
        l2.addStretch(1)
        text.addWidget(self.line2)
        b.addLayout(text, 1)
        hk = ctx.settings.hotkeys
        self.pause_btn = w.icon_button("pause", tr(f"暫停（{hk.pause_resume}）", f"Pause ({hk.pause_resume})"), "icon")
        bind_icon(self.pause_btn, "pause", "text")
        self.pause_btn.clicked.connect(self.pauseClicked.emit)
        b.addWidget(self.pause_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self.pause_key = w.Keycap(hk.pause_resume)
        b.addWidget(self.pause_key, 0, Qt.AlignmentFlag.AlignVCenter)
        self.stop_btn = w.icon_button("stop", tr(f"停止（{hk.stop}）", f"Stop ({hk.stop})"), "icon")
        bind_icon(self.stop_btn, "stop", "error")
        self.stop_btn.clicked.connect(self.stopClicked.emit)
        b.addWidget(self.stop_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self.stop_key = w.Keycap(hk.stop)
        b.addWidget(self.stop_key, 0, Qt.AlignmentFlag.AlignVCenter)
        self.expand_btn = w.icon_button("expand", tr("展開主視窗（會先暫停）", "Open the main window (pauses first)"), "icon")
        self.expand_btn.clicked.connect(self.expandClicked.emit)
        b.addWidget(self.expand_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self.setToolTip(self.failsafe_hint())
        self.setFixedWidth(600)
        self._refresh()

    # -- API ------------------------------------------------------------------------------
    def failsafe_hint(self) -> str:
        stop = self.ctx.settings.hotkeys.stop
        if self.ctx.settings.failsafe_enabled:
            return tr(f"{stop} 停止 · 滑鼠移到螢幕最左上角＝緊急停止", f"{stop} stops · mouse to the top-left corner = emergency stop")
        return tr(f"{stop} 停止", f"{stop} stops")

    def set_progress(self, done: int, total: int, eta_s: float) -> None:
        self._done, self._total, self._eta = int(done), int(total), float(eta_s)
        self.ring.setProgress(self._done, self._total)
        self.ring.setToolTip(tr(f"第 {min(done + 1, total)} / {total} 筆 · 預估剩餘 {format_duration(eta_s if eta_s >= 0 else None)}",
                                f"Code {min(done + 1, total)} of {total} · about {format_duration(eta_s if eta_s >= 0 else None)} left"))

    def set_current(self, code: str, step_title: str = "") -> None:
        self.code_label.setText(code)
        self.step_label.setText(f"· {step_title}" if step_title else "")
        self.step_label.setToolTip(step_title)

    def set_state(self, state: str, reason: str = "") -> None:
        self.state, self.reason = str(state), str(reason or "")
        self._info = ""
        self.pause_btn.setEnabled(False)  # never flip under the user's hand
        self._lock.start(BUTTON_LOCK_MS)
        self._refresh()

    def add_result(self, status: CodeStatus) -> None:
        st = CodeStatus(status)
        self.counts[st] = self.counts.get(st, 0) + 1
        chip = self.chips.get(st)
        if chip is not None:
            chip.setStatus(st, f"{st.label()} {self.counts[st]}")
            chip.show()

    def reset(self) -> None:
        self.counts.clear()
        for chip in self.chips.values():
            chip.hide()
        self.set_current("")
        self._info = ""
        self.set_progress(0, 0, -1.0)

    def set_waiting(self, seconds_left: float) -> None:
        self._info = tr(f"· 下一筆 {max(0, round(seconds_left))} 秒後", f"· next code in {max(0, round(seconds_left))} s") \
            if seconds_left > 0 else ""
        self._refresh()

    def set_cooldown(self, seconds_left: float) -> None:
        s = max(0, round(seconds_left))
        self._info = tr(f"· 偵測到「操作過於頻繁」，{s} 秒後重試", f"· rate limit: retrying in {s} s") if s > 0 else ""
        self._refresh()

    def set_compact(self, compact: bool) -> None:
        self.compact = bool(compact)
        self.line2.setVisible(not self.compact)
        self.step_label.setVisible(not self.compact)
        self.setFixedWidth(470 if self.compact else 600)
        self.adjustSize()

    def info_text(self) -> str:
        return self.info_label.text()

    # -- placement ------------------------------------------------------------------------
    def bar_size_physical(self, compact: bool = False) -> tuple[int, int]:
        hint = self.sizeHint()
        width = 470 if compact else max(self.width(), 600)
        height = hint.height() - (24 if compact else 0)
        dpr = max([g.dpr for g in screen_geoms()] or [1.0])
        return qround(width * dpr), qround(max(40, height) * dpr)

    def frame_rect_physical(self) -> Rect:
        """The window's physical screen rect (for RunSession.set_masked_rects)."""
        try:
            from ..win32 import windows

            if self.isVisible():
                rect = tuple(windows.window_rect(int(self.winId())))
                if rect[2] > 0 and rect[3] > 0:
                    return rect  # type: ignore[return-value]
        except Exception as exc:
            log.debug("window_rect of the mini bar unavailable: %s", exc)
        geo = self.frameGeometry()
        geoms = screen_geoms()
        screen = next((g for g in geoms if g.logical[0] <= geo.x() < g.logical[0] + g.logical[2]
                       and g.logical[1] <= geo.y() < g.logical[1] + g.logical[3]), geoms[0] if geoms else None)
        if screen is None:
            return geo.x(), geo.y(), geo.width(), geo.height()
        x0, y0 = logical_to_physical(screen, geo.x(), geo.y())
        x1, y1 = logical_to_physical(screen, geo.x() + geo.width(), geo.y() + geo.height())
        return x0, y0, x1 - x0, y1 - y0

    def _saved_physical(self) -> tuple[int, int] | None:
        pos = list(self.ctx.settings.minibar_pos or [])
        if len(pos) != 2:
            return None
        for g in screen_geoms():
            x, y, ww, hh = g.logical
            if x <= pos[0] < x + ww and y <= pos[1] < y + hh:
                return logical_to_physical(g, pos[0], pos[1])
        return None

    def place_away_from(self, avoid: Sequence[Rect] = (), target: Rect | None = None) -> None:
        """Choose the bar position (physical rects): the saved Settings.minibar_pos when it
        intersects no ``avoid`` rect; else, in this order, a monitor that does not contain the
        ``target`` client rect, a corner of the target's monitor outside ``target``, a corner
        inside ``target`` that intersects no ``avoid`` rect (points inflated by 24 px), and
        finally the corner with the smallest overlap in compact one-line form."""
        self.set_compact(False)
        self.adjustSize()
        (px, py), compact = choose_position(self.bar_size_physical(False), self.bar_size_physical(True),
                                            work_rects(), avoid, target, self._saved_physical())
        if compact:
            self.set_compact(True)
        geoms = screen_geoms()
        screen = screen_for_physical_point(geoms, px, py) or (geoms[0] if geoms else None)
        if screen is None:
            self.move(px, py)
        else:
            lx, ly = physical_to_logical(screen, px, py)
            self.move(int(round(lx)), int(round(ly)))
        self.placed_at = (px, py)

    # -- internals ------------------------------------------------------------------------
    def _unlock(self) -> None:
        self.pause_btn.setEnabled(self.state in (RunState.RUNNING.value, RunState.PAUSED.value,
                                                 RunState.COOLDOWN.value, RunState.PAUSING.value))

    def _refresh(self) -> None:
        st = self.state
        paused = st == RunState.PAUSED.value
        labels = {
            RunState.IDLE.value: tr("待命", "Idle"), RunState.STARTING.value: tr("準備中", "Starting"),
            RunState.RUNNING.value: tr("正在兌換", "Redeeming"), RunState.PAUSING.value: tr("即將暫停", "Pausing"),
            RunState.PAUSED.value: tr("已暫停", "Paused"), RunState.COOLDOWN.value: tr("冷卻中", "Cooling down"),
            RunState.STOPPING.value: tr("正在停止", "Stopping"), RunState.FINISHED.value: tr("已結束", "Finished"),
        }
        self.state_label.setText(labels.get(st, st))
        hk = self.ctx.settings.hotkeys
        if paused:
            self.pause_btn.setToolTip(tr(f"繼續（{hk.pause_resume}）", f"Resume ({hk.pause_resume})"))
            self.pause_btn.setAccessibleName(tr("繼續", "Resume"))
            bind_icon(self.pause_btn, "play", "text")
        else:
            self.pause_btn.setToolTip(tr(f"暫停（{hk.pause_resume}）", f"Pause ({hk.pause_resume})"))
            self.pause_btn.setAccessibleName(tr("暫停", "Pause"))
            bind_icon(self.pause_btn, "pause", "text")
        info = self._info
        if paused and self.reason:
            try:
                label = PauseReason(self.reason).label()
            except ValueError:
                label = self.reason
            info = f"· {label}"
            self.info_label.setToolTip(pause_text(self.reason) + "\n" + self.failsafe_hint())
        else:
            self.info_label.setToolTip(self.failsafe_hint())
        self.info_label.setText(info)

    # -- dragging (Qt mouse events; the bar never activates) --------------------------------
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_from = event.globalPosition().toPoint()
            self._drag_origin = self.pos()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_from is not None and self._drag_origin is not None:
            delta = event.globalPosition().toPoint() - self._drag_from
            self.move(self._drag_origin + delta)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._drag_from is not None and event.button() == Qt.MouseButton.LeftButton:
            moved = self._drag_origin is not None and self.pos() != self._drag_origin
            self._drag_from = self._drag_origin = None
            if moved:
                self.ctx.settings.minibar_pos = [self.x(), self.y()]
                try:
                    self.ctx.save_settings()
                except Exception as exc:  # pragma: no cover - defensive
                    log.debug("saving the bar position failed: %s", exc)
                self.moved.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)
