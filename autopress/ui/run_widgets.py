# OWNED BY G7
"""Parts of the Run page (private helper of ui.run_page): the live log, the running card, the
attention panel and the finished summary card.

One count everywhere: the progress ring, the running card's heading, the ring tooltips (Run page
and mini bar) and the summary say how many codes were processed (``processed_text``); the
position of the code being worked on (「第 i / N 筆」) comes from RunSession.code_started and is
shown next to that code."""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import QEvent, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPaintEvent, QPalette, QPixmap
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..i18n import format_duration, tr
from ..models import (
    Attention,
    CodeStatus,
    LogEntry,
    LogLevel,
    PauseReason,
    ResultClass,
    RunState,
    RunSummary,
    StopReason,
)
from . import theme
from . import widgets as w

log = logging.getLogger(__name__)

MAX_LOG = 2000
MARK_STATUSES = (CodeStatus.SUCCESS, CodeStatus.USED, CodeStatus.INVALID, CodeStatus.EXPIRED, CodeStatus.FAILED)
COUNT_ORDER = (CodeStatus.SUCCESS, CodeStatus.SUBMITTED, CodeStatus.USED, CodeStatus.INVALID, CodeStatus.EXPIRED,
               CodeStatus.COOLDOWN, CodeStatus.FAILED, CodeStatus.REVIEW, CodeStatus.SKIPPED, CodeStatus.PENDING)
# stop reasons whose runner message only repeats the summary title (「全部完成，共 4 筆。」 under
# 「執行結束：全部完成」); the other messages carry advice or the error text
_REASON_IN_TITLE = (StopReason.COMPLETED, StopReason.USER, StopReason.FAILSAFE)


def level_glyph(level: LogLevel) -> str:
    return {LogLevel.INFO: "·", LogLevel.SUCCESS: "✓", LogLevel.WARNING: "!", LogLevel.ERROR: "✕"}.get(level, "·")


def processed_text(done: int, total: int) -> str:
    """「已處理 2 / 4 筆」: the number the progress ring shows, in the same words wherever it
    appears (running card heading, ring tooltips, summary)."""
    return tr("已處理 {done} / {total} 筆", "{done} of {total} processed").format(done=int(done), total=int(total))


def position_text(index: int, total: int) -> str:
    """「第 3 / 4 筆」 for the 0-based plan ``index`` of the code being processed."""
    if total > 0:
        return tr("第 {i} / {n} 筆", "Code {i} of {n}").format(i=index + 1, n=total)
    return tr("第 {i} 筆", "Code {i}").format(i=index + 1)


def result_text(status: CodeStatus) -> str:
    """「結果：成功」: replaces the step line once a code has its result (no step is running)."""
    return tr("結果：{label}", "Result: {label}").format(label=status.label())


def _tone_color(tone: str) -> QColor:
    try:
        return theme.tone_colors(tone)[2]
    except Exception:
        return QColor()


def _tone_token(token: str) -> QColor:
    """A theme colour token at paint time (an invalid QColor when the theme cannot answer)."""
    try:
        return QColor(theme.color(token))
    except Exception:
        return QColor()


class LogView(QListWidget):
    """Live log: time, level glyph, message; auto-scrolls while the view is at the bottom. While
    it is empty a muted line says what will appear here."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName(tr("即時紀錄", "Live log"))
        self.setAccessibleDescription(self.placeholder_text())
        self.setUniformItemSizes(True)
        self.setWordWrap(False)
        self.setMinimumHeight(160)

    @staticmethod
    def placeholder_text() -> str:
        return tr("按「開始兌換」或「測試一筆」後，每一筆序號的處理過程和結果會顯示在這裡。",
                  "After you press Start or Test one, the progress and result of every code appear here.")

    def placeholder_visible(self) -> bool:
        return self.count() == 0

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override; paints the viewport)
        super().paintEvent(event)
        if not self.placeholder_visible():
            return
        p = QPainter(self.viewport())
        try:
            # the theme's muted text colour: under the style sheet the palette's placeholder role is the
            # text colour at half opacity (about 3.4:1 on the light card)
            muted = _tone_token("text_muted")
            p.setPen(muted if muted.isValid() else self.palette().color(QPalette.ColorRole.PlaceholderText))
            p.setFont(self.font())
            # roughly where the first row's text would start (item padding 6 px + frame)
            rect = self.viewport().rect().adjusted(9, 6, -9, -6)
            p.drawText(rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop) | int(Qt.TextFlag.TextWordWrap),
                       self.placeholder_text())
        finally:
            p.end()

    def add_entry(self, entry: LogEntry) -> None:
        at_bottom = self.verticalScrollBar().value() >= self.verticalScrollBar().maximum() - 4
        t = entry.time[11:19] if len(entry.time) >= 19 else entry.time
        item = QListWidgetItem(f"{t}  {level_glyph(entry.level)}  {entry.message}")
        item.setToolTip(entry.message)
        tone = {LogLevel.SUCCESS: "success", LogLevel.WARNING: "warning", LogLevel.ERROR: "error"}.get(entry.level)
        if tone:
            c = _tone_color(tone)
            if c.isValid():
                item.setForeground(c)
        self.addItem(item)
        while self.count() > MAX_LOG:
            self.takeItem(0)
        if at_bottom:
            self.scrollToBottom()

    def lines(self) -> list[str]:
        return [self.item(i).text() for i in range(self.count())]


class CountsRow(QWidget):
    """Status chips with counts ("成功 5")."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(6)
        self.counts: dict[CodeStatus, int] = {}
        self.chips: dict[CodeStatus, QWidget] = {}
        for st in COUNT_ORDER:
            chip = w.StatusChip(st, f"{st.label()} 0")
            chip.hide()
            self.lay.addWidget(chip)
            self.chips[st] = chip
        self.lay.addStretch(1)

    def set_counts(self, counts: dict[CodeStatus, int]) -> None:
        self.counts = {st: int(n) for st, n in counts.items() if n}
        for st, chip in self.chips.items():
            n = self.counts.get(st, 0)
            chip.setStatus(st, f"{st.label()} {n}")
            chip.setVisible(n > 0)

    def add(self, status: CodeStatus) -> None:
        c = dict(self.counts)
        c[status] = c.get(status, 0) + 1
        self.set_counts(c)


class RunningCard(QWidget):
    """Progress while a run is active: ring and heading with the same count (「已處理 n / N 筆」),
    ETA, the code being processed with its position (「第 i / N 筆」) and step - or its result
    once it has one - state, buttons."""

    pauseClicked = pyqtSignal()
    stopClicked = pyqtSignal()

    def __init__(self, pause_key: str, stop_key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.total = 0
        self.current_index = -1  # 0-based plan index of the code being processed (-1: none yet)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        c = w.Card(True, None, 10)
        outer.addWidget(c)
        lay = c.layout()
        top = QHBoxLayout()
        top.setSpacing(16)
        self.ring = w.ProgressRing(64)
        top.addWidget(self.ring)
        col = QVBoxLayout()
        col.setSpacing(2)
        row1 = QHBoxLayout()
        self.position = w.label("", "title")
        row1.addWidget(self.position)
        self.state = w.label("", "caption")
        row1.addWidget(self.state)
        row1.addStretch(1)
        col.addLayout(row1)
        self.eta = w.label("", "secondary")
        col.addWidget(self.eta)
        row2 = QHBoxLayout()
        self.index = w.label("", "secondary")
        row2.addWidget(self.index)
        self.code = w.label("", "mono")
        try:
            self.code.setFont(theme.font(theme.FS_MONO, mono=True))
        except Exception:
            pass
        row2.addWidget(self.code)
        self.step = w.label("", "muted")
        row2.addWidget(self.step, 1)
        col.addLayout(row2)
        top.addLayout(col, 1)
        self.pause_btn = w.push_button(tr("暫停", "Pause"), "secondary", "pause")
        self.pause_btn.clicked.connect(self.pauseClicked.emit)
        top.addWidget(self.pause_btn)
        self.pause_key = w.Keycap(pause_key)
        top.addWidget(self.pause_key)
        self.stop_btn = w.push_button(tr("停止", "Stop"), "danger", "stop")
        self.stop_btn.clicked.connect(self.stopClicked.emit)
        top.addWidget(self.stop_btn)
        self.stop_key = w.Keycap(stop_key)
        top.addWidget(self.stop_key)
        lay.addLayout(top)
        # the chips and the info line (「下一筆 6 秒後」, the cool-down) share one row: an empty info line
        # of its own left a band of padding at the bottom of the card, and hiding it made the card jump
        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        self.counts = CountsRow()
        bottom.addWidget(self.counts, 1)
        self.info = w.label("", "muted")
        bottom.addWidget(self.info, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(bottom)

    def set_progress(self, done: int, total: int, eta: float) -> None:
        self.total = max(0, int(total))
        self.ring.setProgress(done, total)
        text = processed_text(done, total)  # the ring's number, in words
        self.position.setText(text)
        self.ring.setToolTip(text)
        self.eta.setText(tr(f"預估剩餘 {format_duration(eta if eta >= 0 else None)}",
                            f"About {format_duration(eta if eta >= 0 else None)} left"))
        self._show_position()

    def set_current(self, index: int, code: str, total: int | None = None) -> None:
        """The code being processed: its 0-based plan ``index`` (RunSession.code_started) and
        text; ``total`` = plan size when known (else the last progress total)."""
        if total is not None and total > 0:
            self.total = int(total)
        self.current_index = int(index)
        self.code.setText(code)
        self._show_position()

    def _show_position(self) -> None:
        self.index.setText(position_text(self.current_index, self.total) if self.current_index >= 0 else "")

    def reset(self) -> None:
        """A new run: nothing of the previous run's code, step, result chips or info line."""
        self.current_index = -1
        for lb in (self.index, self.code, self.step, self.info):
            lb.setText("")
        self.counts.set_counts({})

    def set_controls_visible(self, visible: bool) -> None:
        """Pause / stop and their keycaps; hidden while the decision card (which has its own
        繼續 / 停止) is shown. F8 / F9 keep working."""
        for widget in (self.pause_btn, self.pause_key, self.stop_btn, self.stop_key):
            widget.setVisible(visible)

    def set_state(self, state: str) -> None:
        try:
            st = RunState(state)
            self.state.setText(st.label())
        except ValueError:
            st = None
            self.state.setText(state)
        paused = st is RunState.PAUSED
        self.pause_btn.setText(tr("繼續", "Resume") if paused else tr("暫停", "Pause"))
        from .minibar import bind_icon

        bind_icon(self.pause_btn, "play" if paused else "pause", "text_secondary")


class EvidenceView(QWidget):
    """The evidence crop on the decision card, like the history's evidence viewer: inside a 1 px
    frame (a white crop on the white light card would look like part of AutoPress's own UI) and
    at its natural size - one image pixel per screen pixel, as large as it was on screen and sharp
    at any Windows scaling - shrunk only to fit MAX_H and the card's width."""

    MAX_H = 160  # logical px
    FRAME = 1

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixmap = QPixmap()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(tr("證據圖片", "Evidence image"))

    def setPixmap(self, pixmap: QPixmap) -> None:  # noqa: N802 (QLabel-like)
        self._pixmap = QPixmap(pixmap)
        self.updateGeometry()
        self.update()

    def pixmap(self) -> QPixmap:
        return self._pixmap

    def clear(self) -> None:
        self.setPixmap(QPixmap())

    def image_rect(self, width: float | None = None) -> QRectF:
        """Where the crop is drawn (inside the frame) for a widget ``width`` logical px wide."""
        if self._pixmap.isNull():
            return QRectF()
        dpr = self.devicePixelRatioF() or 1.0
        nw, nh = self._pixmap.width() / dpr, self._pixmap.height() / dpr
        avail_w = (self.width() if width is None else width) - 2 * self.FRAME
        s = min(1.0, (self.MAX_H - 2 * self.FRAME) / max(1.0, nh), max(1.0, avail_w) / max(1.0, nw))
        return QRectF(self.FRAME, self.FRAME, nw * s, nh * s)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return not self._pixmap.isNull()

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return math.ceil(self.image_rect(width).height()) + 2 * self.FRAME if not self._pixmap.isNull() else 0

    def sizeHint(self) -> QSize:  # noqa: N802
        if self._pixmap.isNull():
            return QSize(0, 0)
        r = self.image_rect(1e6)
        return QSize(math.ceil(r.width()) + 2 * self.FRAME, math.ceil(r.height()) + 2 * self.FRAME)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, 0)

    def event(self, event: QEvent | None) -> bool:
        if event is not None and event.type() == QEvent.Type.DevicePixelRatioChange:
            self.updateGeometry()  # another screen scaling: another natural size
        return super().event(event)

    def paintEvent(self, _event: QPaintEvent | None) -> None:  # noqa: N802
        r = self.image_rect()
        if r.isEmpty():
            return
        p = QPainter(self)
        f = self.FRAME
        p.fillRect(r.adjusted(-f, -f, f, f), _tone_token("border_strong"))
        natural = abs(r.width() * (self.devicePixelRatioF() or 1.0) - self._pixmap.width()) < 0.5
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, not natural)  # a 1:1 copy needs no filter
        p.drawPixmap(r, self._pixmap, QRectF(self._pixmap.rect()))
        p.end()


class AttentionPanel(QWidget):
    """Shown when a paused run needs a decision (SPEC 6.4.3): reason, the code it is about,
    what to do, the text that was read, evidence, 標記為…, 加入關鍵字…, 繼續 / 停止."""

    markClicked = pyqtSignal(object)  # CodeStatus
    addKeywordClicked = pyqtSignal()
    openLogClicked = pyqtSignal()
    resumeClicked = pyqtSignal()
    stopClicked = pyqtSignal()

    def __init__(self, data_dir: Callable[[], Path] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.data_dir = data_dir
        self.attention: Attention | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.banner = w.Banner("warning", "", "", False)
        outer.addWidget(self.banner)
        c = w.Card(True, None, 10)
        outer.addWidget(c)
        lay = c.layout()
        self.title = w.label("", "title")
        lay.addWidget(self.title)
        self.code_row = QWidget()
        cr = QHBoxLayout(self.code_row)
        cr.setContentsMargins(0, 0, 0, 0)
        cr.setSpacing(8)
        cr.addWidget(w.label(tr("序號", "Code"), "secondary"))
        self.code = w.label("", "mono")
        try:
            self.code.setFont(theme.font(theme.FS_MONO, mono=True))
        except Exception:
            pass
        self.code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        cr.addWidget(self.code)
        cr.addStretch(1)
        self.code_row.hide()
        lay.addWidget(self.code_row)
        self.message = w.label("", "body")
        self.message.setWordWrap(True)
        lay.addWidget(self.message)
        self.ocr_caption = w.label(tr("讀到的文字", "Text that was read"), "caption")
        lay.addWidget(self.ocr_caption)
        self.ocr_text = w.label("", "mono")
        self.ocr_text.setWordWrap(True)
        self.ocr_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.ocr_text)
        self.evidence = EvidenceView()
        lay.addWidget(self.evidence)
        self.mark_row = QWidget()
        mr = QHBoxLayout(self.mark_row)
        mr.setContentsMargins(0, 0, 0, 0)
        mr.addWidget(w.label(tr("標記為", "Mark as"), "secondary"))
        self.mark_buttons: dict[CodeStatus, QWidget] = {}
        for st in MARK_STATUSES:
            b = w.push_button(st.label(), "secondary")
            b.clicked.connect(lambda _c=False, s=st: self.markClicked.emit(s))
            mr.addWidget(b)
            self.mark_buttons[st] = b
        mr.addStretch(1)
        self.keyword_btn = w.push_button(tr("加入關鍵字…", "Add keyword…"), "ghost", "plus")
        self.keyword_btn.clicked.connect(self.addKeywordClicked.emit)
        mr.addWidget(self.keyword_btn)
        lay.addWidget(self.mark_row)
        self.resolved = w.label("", "secondary")
        self.resolved.hide()
        lay.addWidget(self.resolved)
        row = QHBoxLayout()
        self.log_btn = w.push_button(tr("開啟紀錄檔", "Open log"), "ghost", "folder")
        self.log_btn.clicked.connect(self.openLogClicked.emit)
        row.addWidget(self.log_btn)
        row.addStretch(1)
        self.stop_btn = w.push_button(tr("停止", "Stop"), "danger", "stop")
        self.stop_btn.clicked.connect(self.stopClicked.emit)
        row.addWidget(self.stop_btn)
        self.resume_btn = w.push_button(tr("繼續", "Resume"), "primary", "play")
        self.resume_btn.clicked.connect(self.resumeClicked.emit)
        row.addWidget(self.resume_btn)
        lay.addLayout(row)

    def show_attention(self, att: Attention, code: str = "") -> None:
        """``code`` = the text of the code ``att.code_id`` refers to ("" hides the code line)."""
        self.attention = att
        kind = PauseReason(att.kind)
        self.title.setText(kind.label())
        self.code.setText(code)
        self.code_row.setVisible(bool(code))
        unknown = kind is PauseReason.UNKNOWN_RESULT
        decide = unknown and bool(att.code_id)  # the 標記為 buttons are shown
        text = att.message
        if decide and att.ocr_text:
            # the runner's message quotes the text that is shown right below: say what to do instead
            text = tr("請選擇這筆序號的結果，或把讀到的文字加入關鍵字。",
                      "Choose the result for this code, or add the text that was read as a keyword.")
        elif decide and not text:
            text = tr("請選擇這筆序號的結果。", "Choose the result for this code.")
        elif unknown and att.ocr_text and not text:
            text = tr(f"無法判讀結果：「{att.ocr_text}」。請選擇結果，或把文字加入關鍵字。",
                      f"Could not recognise the result: \"{att.ocr_text}\". Pick the result or add the text as a keyword.")
        self.message.setText(text)
        self.banner.setText(tr("執行已暫停，需要你決定怎麼處理。", "The run is paused and needs your decision."))
        self.ocr_text.setText(att.ocr_text)
        self.ocr_caption.setVisible(bool(att.ocr_text))
        self.ocr_text.setVisible(bool(att.ocr_text))
        self.mark_row.setVisible(unknown and bool(att.code_id))
        for b in self.mark_buttons.values():
            b.setEnabled(True)
        self.keyword_btn.setEnabled(bool(att.ocr_text))
        self.resolved.hide()
        self.log_btn.setVisible(kind is PauseReason.ERROR)
        self._load_evidence(att.evidence_path)
        self.show()

    def _load_evidence(self, rel: str) -> None:
        self.evidence.clear()
        self.evidence.hide()
        if not rel or self.data_dir is None:
            return
        try:
            path = Path(rel) if Path(rel).is_absolute() else self.data_dir() / rel
        except Exception:  # pragma: no cover - defensive
            return
        pm = QPixmap(str(path))
        if not pm.isNull():
            # no tooltip with the file's path: it names the Windows account folder (screen recordings)
            self.evidence.setPixmap(pm)
            self.evidence.show()

    def mark_resolved(self, status: CodeStatus) -> None:
        for b in self.mark_buttons.values():
            b.setEnabled(False)
        self.resolved.setText(tr(f"已標記為「{status.label()}」。按「繼續」接著做下一筆。",
                                 f"Marked as '{status.label()}'. Press Resume to continue."))
        self.resolved.show()


class SummaryCard(QWidget):
    exportClicked = pyqtSignal()
    retryClicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        c = w.Card(True, None, 10)
        outer.addWidget(c)
        lay = c.layout()
        self.title = w.label("", "title")
        lay.addWidget(self.title)
        self.detail = w.label("", "secondary")
        self.detail.setWordWrap(True)
        lay.addWidget(self.detail)
        self.counts = CountsRow()
        lay.addWidget(self.counts)
        row = QHBoxLayout()
        row.addStretch(1)
        self.retry_btn = w.push_button(tr("重試失敗項目", "Retry failed"), "secondary", "refresh")
        self.retry_btn.clicked.connect(self.retryClicked.emit)
        row.addWidget(self.retry_btn)
        self.export_btn = w.push_button(tr("匯出結果", "Export results"), "secondary", "export")
        self.export_btn.clicked.connect(self.exportClicked.emit)
        row.addWidget(self.export_btn)
        lay.addLayout(row)
        self.summary: RunSummary | None = None

    def show_summary(self, summary: RunSummary, counts: dict[CodeStatus, int]) -> None:
        self.summary = summary
        self.title.setText(tr("執行結束：", "Run finished: ") + summary.stop_reason.label())
        lines = [tr("「{name}」已處理 {done} / {total} 筆", "'{name}': {done} of {total} codes processed").format(
            name=summary.profile_name, done=summary.done, total=summary.total)]
        if summary.message and summary.stop_reason not in _REASON_IN_TITLE:
            lines.append(summary.message)
        self.detail.setText("\n".join(lines))
        self.counts.set_counts(counts)
        self.retry_btn.setEnabled(counts.get(CodeStatus.FAILED, 0) > 0)
        self.show()


class KeywordDialog(QDialog):
    """「加入關鍵字…」: which result class the text means, and the keyword itself."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("加入關鍵字", "Add keyword"))
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(8)
        info = w.label(tr("以後讀到含有這段文字的結果時，會自動判定為你選的結果。關鍵字越短越容易誤判，"
                          "請只留下最能代表結果的幾個字。",
                          "Results containing this text are classified automatically from now on. Keep only the "
                          "few characters that identify the result; very short keywords match too much."), "muted")
        info.setWordWrap(True)
        lay.addWidget(info)
        self.kind = QComboBox()
        for cls in (ResultClass.SUCCESS, ResultClass.USED, ResultClass.INVALID, ResultClass.EXPIRED,
                    ResultClass.RATE_LIMITED, ResultClass.INELIGIBLE):
            self.kind.addItem(cls.label(), cls.value)
        lay.addWidget(w.form_row(tr("這段文字代表", "This text means"), self.kind))
        first = next((ln.strip() for ln in (text or "").splitlines() if ln.strip()), "")
        self.edit = QLineEdit(first[:40])
        self.edit.textChanged.connect(self._update)
        lay.addWidget(w.form_row(tr("關鍵字", "Keyword"), self.edit))
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = w.push_button(tr("取消", "Cancel"), "secondary")
        cancel.clicked.connect(self.reject)
        self.ok_btn = w.push_button(tr("加入", "Add"), "primary")
        self.ok_btn.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(self.ok_btn)
        lay.addLayout(row)
        self._update()

    def _update(self) -> None:
        self.ok_btn.setEnabled(bool(self.edit.text().strip()))

    def result_class(self) -> ResultClass:
        return ResultClass(self.kind.currentData())

    def keyword(self) -> str:
        from ..textutil import clean_text

        return clean_text(self.edit.text()).strip()


__all__ = ["AttentionPanel", "CountsRow", "EvidenceView", "KeywordDialog", "LogView", "RunningCard", "SummaryCard",
           "level_glyph", "position_text", "processed_text", "result_text"]
