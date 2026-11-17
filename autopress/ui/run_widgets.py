# OWNED BY G7
"""Parts of the Run page (private helper of ui.run_page): the live log, the running card, the
attention panel and the finished summary card."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
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
)
from . import theme
from . import widgets as w

log = logging.getLogger(__name__)

MAX_LOG = 2000
MARK_STATUSES = (CodeStatus.SUCCESS, CodeStatus.USED, CodeStatus.INVALID, CodeStatus.EXPIRED, CodeStatus.FAILED)
COUNT_ORDER = (CodeStatus.SUCCESS, CodeStatus.SUBMITTED, CodeStatus.USED, CodeStatus.INVALID, CodeStatus.EXPIRED,
               CodeStatus.COOLDOWN, CodeStatus.FAILED, CodeStatus.REVIEW, CodeStatus.SKIPPED, CodeStatus.PENDING)


def level_glyph(level: LogLevel) -> str:
    return {LogLevel.INFO: "·", LogLevel.SUCCESS: "✓", LogLevel.WARNING: "!", LogLevel.ERROR: "✕"}.get(level, "·")


def _tone_color(tone: str) -> QColor:
    try:
        return theme.tone_colors(tone)[2]
    except Exception:
        return QColor()


class LogView(QListWidget):
    """Live log: time, level glyph, message; auto-scrolls while the view is at the bottom."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName(tr("即時紀錄", "Live log"))
        self.setUniformItemSizes(True)
        self.setWordWrap(False)
        self.setMinimumHeight(160)

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
    """Progress while a run is active: ring, n / N, ETA, current code and step, state, buttons."""

    pauseClicked = pyqtSignal()
    stopClicked = pyqtSignal()

    def __init__(self, pause_key: str, stop_key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
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
        self.counts = CountsRow()
        lay.addWidget(self.counts)
        self.info = w.label("", "muted")
        lay.addWidget(self.info)

    def set_progress(self, done: int, total: int, eta: float) -> None:
        self.ring.setProgress(done, total)
        i = min(done + 1, total) if total else 0
        self.position.setText(tr(f"第 {i} / {total} 筆", f"Code {i} of {total}"))
        self.eta.setText(tr(f"預估剩餘 {format_duration(eta if eta >= 0 else None)}",
                            f"About {format_duration(eta if eta >= 0 else None)} left"))

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


class AttentionPanel(QWidget):
    """Shown when a paused run needs a decision (SPEC 6.4.3)."""

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
        self.message = w.label("", "body")
        self.message.setWordWrap(True)
        lay.addWidget(self.message)
        self.ocr_caption = w.label(tr("讀到的文字", "Text that was read"), "caption")
        lay.addWidget(self.ocr_caption)
        self.ocr_text = w.label("", "mono")
        self.ocr_text.setWordWrap(True)
        self.ocr_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.ocr_text)
        self.evidence = QLabel()
        self.evidence.setMaximumHeight(160)
        self.evidence.setAlignment(Qt.AlignmentFlag.AlignLeft)
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

    def show_attention(self, att: Attention) -> None:
        self.attention = att
        kind = PauseReason(att.kind)
        self.title.setText(kind.label())
        unknown = kind is PauseReason.UNKNOWN_RESULT
        text = att.message
        if unknown and att.ocr_text and not text:
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
            self.evidence.setPixmap(pm.scaledToHeight(min(160, pm.height()), Qt.TransformationMode.SmoothTransformation))
            self.evidence.setToolTip(str(path))
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
        lines = [tr(f"「{summary.profile_name}」完成 {summary.done} / {summary.total} 筆",
                    f"'{summary.profile_name}': {summary.done} of {summary.total} codes done")]
        if summary.message:
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


__all__ = ["AttentionPanel", "CountsRow", "KeywordDialog", "LogView", "RunningCard", "SummaryCard", "level_glyph"]
