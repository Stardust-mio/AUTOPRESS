# OWNED BY G6
"""Paste / file import dialog: text area (pre-filled), code-format combo (auto-detected with
codes.presets.detect_format, user can override), live candidate list (checkbox, code, badges
重複 / 已兌換過 / 不像序號 / 已修正字元, raw text next to the code when normalisation changed it),
summary 「將加入 {a} 筆，略過 {d} 筆重複、{h} 筆已兌換過」 (parts with a count of 0 left out), 加入 / 取消.
Word-like tokens (codes.extract ``likely`` False, e.g. "Redemption" in "Redemption code: …") are
listed unticked with the 不像序號 badge on purpose, so a code that is a word can still be ticked.
The live extraction is
debounced (300 ms after the last edit, T35); the initial text is extracted at once. Without an
active profile the codes are added unassigned (game "")."""

from __future__ import annotations

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QPlainTextEdit, QStackedWidget, QVBoxLayout, QWidget

from ..codes import extract
from ..context import AppContext
from ..i18n import tr
from ..models import CodeCandidate, CodeFormat, CodeSource
from . import theme, widgets
from .codes_candidates import PASTE_COLUMNS, ImportDialogBase
from .codes_common import NO_CODES_FOUND

DEBOUNCE_MS = 300


class PasteDialog(ImportDialogBase):
    def __init__(self, ctx: AppContext, text: str = "", source: CodeSource = CodeSource.PASTE,
                 detail: str = "", parent: QWidget | None = None, format_choice: str | None = None) -> None:
        """``format_choice``: a key of codes_common.format_choices (default: the profile's rule)."""
        super().__init__(ctx, source, detail, parent, format_choice, PASTE_COLUMNS)
        if source is CodeSource.FILE and detail:
            self.setWindowTitle(tr("從檔案匯入：{name}", "Import from file: {name}").format(name=detail))
        else:
            self.setWindowTitle(tr("貼上序號", "Paste codes"))
        self._editor = QPlainTextEdit()
        self._editor.setPlaceholderText(tr("把含有序號的文字貼在這裡，例如直播聊天室或公告的內容…",
                                           "Paste text that contains codes here, e.g. a stream chat or an announcement…"))
        self._editor.setAccessibleName(tr("序號文字", "Text with codes"))
        self._editor.setTabChangesFocus(True)
        self._editor.setPlainText(text)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._timer.timeout.connect(self._extract)
        self._editor.textChanged.connect(self._timer.start)
        self._empty = widgets.label("", "muted")
        self._empty.setWordWrap(True)
        self._stack = QStackedWidget()
        self._stack.addWidget(self._view)
        holder = QWidget()
        hl = QVBoxLayout(holder)
        hl.setContentsMargins(theme.SP[3], theme.SP[4], theme.SP[3], theme.SP[4])
        hl.addWidget(self._empty)
        hl.addStretch(1)
        self._stack.addWidget(holder)
        self._build()
        self._extract()
        self._editor.setFocus()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SP[5], theme.SP[4], theme.SP[5], theme.SP[4])
        root.setSpacing(theme.SP[3])
        root.addWidget(widgets.label(self.windowTitle(), "title"))
        hint = widgets.label(tr("AutoPress 會從文字中找出序號並去除重複；可以直接修改左邊的文字，右邊會跟著更新。",
                                "AutoPress finds the codes in the text and removes duplicates; edit the text on "
                                "the left and the list on the right follows."), "muted")
        hint.setWordWrap(True)
        root.addWidget(hint)
        body = QHBoxLayout()
        body.setSpacing(theme.SP[4])
        left = QVBoxLayout()
        left.setSpacing(theme.SP[2])
        left.addWidget(widgets.label(tr("文字", "Text"), "secondary"))
        left.addWidget(self._editor, 1)
        right = QVBoxLayout()
        right.setSpacing(theme.SP[2])
        right.addLayout(self._format_row())
        right.addWidget(self._target_label)
        right.addWidget(self._stack, 1)
        body.addLayout(left, 5)
        body.addLayout(right, 6)
        root.addLayout(body, 1)
        root.addLayout(self._footer())
        self.setMinimumSize(720, 460)
        parent = self.parentWidget()
        avail = parent.window().size() if parent is not None else None
        w = min(940, avail.width() - 40) if avail is not None and avail.width() > 760 else 940
        h = min(600, avail.height() - 40) if avail is not None and avail.height() > 500 else 600
        self.resize(max(720, w), max(460, h))

    # -- extraction ---------------------------------------------------------------------------
    def text(self) -> str:
        return self._editor.toPlainText()

    def extraction_pending(self) -> bool:
        """True while an edit waits for the debounced extraction."""
        return self._timer.isActive()

    def _on_format_changed(self) -> None:
        self._extract()

    def _extract(self) -> None:
        self._timer.stop()
        text = self._editor.toPlainText()
        fmt = self._resolve_format(text)
        cands = extract.extract_from_text(text, fmt) if text.strip() else []
        self._set_candidates(cands)
        if cands:
            self._stack.setCurrentIndex(0)
        else:
            self._empty.setText(str(NO_CODES_FOUND) if text.strip() else
                                tr("把含有序號的文字貼在左邊，這裡會列出找到的序號。",
                                   "Paste text with codes on the left; the codes found are listed here."))
            self._stack.setCurrentIndex(1)

    def candidates(self) -> list[CodeCandidate]:
        """The checked candidates (valid after exec() returned Accepted)."""
        if self._timer.isActive():
            self._extract()
        return super().candidates()

    def code_format(self) -> CodeFormat:
        return super().code_format()

    def accept(self) -> None:
        if self._timer.isActive():  # pressed 加入 within 300 ms of typing: use the final text
            self._extract()
            if self.summary_counts()[0] == 0:
                return
        QDialog.accept(self)
