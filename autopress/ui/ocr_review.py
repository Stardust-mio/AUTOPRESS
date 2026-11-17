# OWNED BY G6
"""OCR review dialog (ux.md flow F2): the image (zoomable) with detected line boxes on the
left; candidates on the right (checkbox, editable mono code with ``flagged`` characters
highlighted and ``lookalikes`` dotted-underlined, confidence, crop of the source line next to
the text, badges, a 「已核對」 tick per flagged candidate and 「全部已核對」); code-format combo
(re-extract on change), 重新辨識; states: loading (Spinner "辨識中…"), error (engine
unavailable, with the reason), no codes found. OCR runs through ctx.ocr.request with
OcrOptions(code_charset=fmt.allowed_chars() + fmt.separator, det_side=ctx.settings.ocr.det_side)
for every image size (det 1920 lost small text, T13). Candidates ticked 「已核對」 are returned
with ``flagged`` cleared, so they enter the queue as PENDING (PX-18); so are edited ones.

With 自動偵測 the OCR read uses the generic charset and the format is detected from the OCR
text; changing the format re-extracts from the same OCR result, 重新辨識 reads the image again
with the chosen format's charset."""

from __future__ import annotations

import logging

import numpy as np
from PyQt6.QtCore import QModelIndex, QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap, QPolygonF, QWheelEvent
from PyQt6.QtWidgets import (
    QDialog,
    QGraphicsPixmapItem,
    QGraphicsPolygonItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QHeaderView,
    QPlainTextEdit,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..codes import extract, normalize
from ..context import AppContext
from ..i18n import tr
from ..models import CodeCandidate, CodeFormat, CodeSource, OcrLine, OcrOptions, OcrResult, code_key
from ..ocr import imageio
from ..textutil import clean_text
from . import theme, widgets
from .codes_candidates import OCR_COLUMNS, CandidateEntry, ImportDialogBase
from .codes_common import NO_CODES_FOUND
from .codes_paint import code_column_width

log = logging.getLogger(__name__)

STATES = ("loading", "error", "empty", "results")


class ImageView(QGraphicsView):
    """The image with the OCR line boxes; wheel zooms, drag pans, double-click fits."""

    boxClicked = pyqtSignal(int)  # OcrResult.lines index

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self._pixmap = QGraphicsPixmapItem()
        self._pixmap.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self.scene().addItem(self._pixmap)
        self._boxes: dict[int, QGraphicsPolygonItem] = {}
        self._kinds: dict[int, str] = {}
        self._current = -1
        self._fit = True
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(theme.color("surface_inset"))
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setMinimumSize(240, 200)
        self.setAccessibleName(tr("辨識的圖片", "Recognised image"))

    def set_image(self, pixmap: QPixmap) -> None:
        self._pixmap.setPixmap(pixmap)
        self.scene().setSceneRect(QRectF(pixmap.rect()))
        self.fit()

    def set_lines(self, lines: list[OcrLine], kinds: dict[int, str]) -> None:
        """Boxes for every line; ``kinds``: line index -> "code" | "flagged" (others muted)."""
        for item in self._boxes.values():
            self.scene().removeItem(item)
        self._boxes, self._kinds, self._current = {}, dict(kinds), -1
        for i, ln in enumerate(lines):
            if not ln.quad:
                continue
            item = QGraphicsPolygonItem(QPolygonF([QPointF(x, y) for x, y in ln.quad]))
            item.setData(0, i)
            item.setToolTip(ln.text)
            self.scene().addItem(item)
            self._boxes[i] = item
            self._style(i)

    def highlight(self, line_index: int) -> None:
        old, self._current = self._current, line_index
        for i in (old, line_index):
            if i in self._boxes:
                self._style(i)
        if line_index in self._boxes:
            self.ensureVisible(self._boxes[line_index], 24, 24)

    def _style(self, i: int) -> None:
        kind = self._kinds.get(i, "")
        token = {"flagged": "warning", "code": "accent"}.get(kind, "text_muted")
        pen = QPen(theme.color(token), 3.0 if i == self._current else (2.0 if kind else 1.0))
        pen.setCosmetic(True)
        if not kind:
            pen.setStyle(Qt.PenStyle.DashLine)
        item = self._boxes[i]
        item.setPen(pen)
        fill = QColor(theme.color(token))
        fill.setAlpha(60 if i == self._current else 0)
        item.setBrush(QBrush(fill))
        item.setZValue(2 if i == self._current else 1)

    def fit(self) -> None:
        self._fit = True
        if not self._pixmap.pixmap().isNull():
            self.fitInView(self._pixmap, Qt.AspectRatioMode.KeepAspectRatio)

    def zoom(self, factor: float) -> None:
        current = self.transform().m11()
        factor = max(0.05 / current, min(16.0 / current, factor))
        self._fit = False
        self.scale(factor, factor)

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        if delta:
            self.zoom(1.15 ** (delta / 120))
        event.accept()

    def mouseDoubleClickEvent(self, event: object) -> None:
        self.fit()

    def mousePressEvent(self, event: object) -> None:
        item = self.itemAt(event.position().toPoint())  # type: ignore[attr-defined]
        if isinstance(item, QGraphicsPolygonItem) and item.data(0) is not None:
            self.boxClicked.emit(int(item.data(0)))
        super().mousePressEvent(event)  # type: ignore[arg-type]

    def resizeEvent(self, event: object) -> None:
        super().resizeEvent(event)  # type: ignore[arg-type]
        if self._fit:
            self.fit()


class OcrReviewDialog(ImportDialogBase):
    def __init__(self, ctx: AppContext, image: np.ndarray, source: CodeSource = CodeSource.IMAGE,
                 detail: str = "", parent: QWidget | None = None, format_choice: str | None = None) -> None:
        """``image``: BGR or BGRA (mss captures); ``format_choice``: a codes_common.format_choices key."""
        super().__init__(ctx, source, detail, parent, format_choice, OCR_COLUMNS)
        title = {CodeSource.CLIPBOARD: tr("剪貼簿圖片辨識", "Clipboard image"),
                 CodeSource.SNIP: tr("框選畫面辨識", "Screen region")}.get(source, tr("圖片辨識", "Image recognition"))
        self.setWindowTitle(tr("{title}：{detail}", "{title}: {detail}").format(title=title, detail=detail)
                            if detail else title)
        self._image = np.ascontiguousarray(image)
        self._result: OcrResult | None = None
        self._job: int | None = None
        self._state = "loading"
        self._error = ""
        self._model.editable = True
        self._model.on_edit = self._apply_edit
        code_delegate = self._view.itemDelegateForColumn(self._model.col("code"))
        code_delegate.validator = lambda _index, text: self._validate(text)  # type: ignore[attr-defined]
        code_delegate.edit_rejected.connect(self._show_edit_error)  # type: ignore[attr-defined]
        self._view.selectionModel().currentRowChanged.connect(self._on_current_row)
        self._build()
        ocr_signal = getattr(ctx.ocr, "state_changed", None)
        if ocr_signal is not None:
            ocr_signal.connect(self._on_ocr_state)
        self._start_ocr()

    # -- layout -------------------------------------------------------------------------------
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SP[5], theme.SP[4], theme.SP[5], theme.SP[4])
        root.setSpacing(theme.SP[3])
        root.addWidget(widgets.label(self.windowTitle(), "title"))
        bar = QHBoxLayout()
        bar.setSpacing(theme.SP[2])
        bar.addLayout(self._format_row(), 1)
        self._retry_btn = widgets.push_button(tr("重新辨識", "Read again"), "secondary", "refresh")
        self._retry_btn.setToolTip(tr("用目前選的序號格式重新辨識圖片", "Read the image again with the chosen code format"))
        self._retry_btn.clicked.connect(self._start_ocr)
        self._fit_btn = widgets.icon_button("expand", tr("符合視窗大小", "Fit to window"))
        self._fit_btn.clicked.connect(lambda: self._image_view.fit())
        bar.addWidget(self._retry_btn)
        bar.addWidget(self._fit_btn)
        root.addLayout(bar)

        self._image_view = ImageView()
        self._image_view.boxClicked.connect(self._select_line)
        qimg = imageio.to_qimage(self._image)
        self._image_view.set_image(QPixmap.fromImage(qimg))

        self._stack = QStackedWidget()
        self._stack.addWidget(self._loading_panel())
        self._stack.addWidget(self._error_panel())
        self._stack.addWidget(self._empty_panel())
        self._stack.addWidget(self._results_panel())

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(theme.SP[3], 0, 0, 0)
        rl.setSpacing(theme.SP[2])
        rl.addWidget(self._target_label)
        rl.addWidget(self._stack, 1)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self._image_view)
        split.addWidget(right)
        split.setStretchFactor(0, 5)
        split.setStretchFactor(1, 6)
        split.setChildrenCollapsible(False)
        root.addWidget(split, 1)
        root.addLayout(self._footer())
        self.setMinimumSize(820, 500)
        parent = self.parentWidget()
        avail = parent.window().size() if parent is not None else None
        w = min(1120, avail.width() - 40) if avail is not None and avail.width() > 860 else 1120
        h = min(680, avail.height() - 40) if avail is not None and avail.height() > 540 else 680
        self.resize(max(820, w), max(500, h))
        split.setSizes([int(self.width() * 0.38), int(self.width() * 0.62)])

    def _loading_panel(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        self._spinner = widgets.Spinner(20)
        row.addWidget(self._spinner)
        self._loading_label = widgets.label(tr("辨識中…", "Recognising…"), "secondary")
        row.addWidget(self._loading_label)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(2)
        return w

    def _error_panel(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, theme.SP[2], 0, 0)
        self._error_banner = widgets.Banner("error", "", tr("重試", "Retry"), False)
        self._error_banner.actionClicked.connect(self._start_ocr)
        lay.addWidget(self._error_banner)
        lay.addStretch(1)
        return w

    def _empty_panel(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, theme.SP[2], 0, 0)
        lay.setSpacing(theme.SP[2])
        msg = widgets.label(str(NO_CODES_FOUND), "body")
        msg.setWordWrap(True)
        lay.addWidget(msg)
        self._ocr_text_label = widgets.label(tr("辨識到的文字：", "Text found:"), "secondary")
        lay.addWidget(self._ocr_text_label)
        self._ocr_text = QPlainTextEdit()
        self._ocr_text.setReadOnly(True)
        self._ocr_text.setAccessibleName(tr("辨識到的文字", "Text found"))
        lay.addWidget(self._ocr_text, 1)
        return w

    def _results_panel(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.SP[2])
        row = QHBoxLayout()
        self._review_hint = widgets.label(
            tr("黃色字元的辨識信心偏低：請對照左邊的原圖，正確就勾選「已核對」，不對就雙擊序號修改。",
               "Yellow characters were read with low confidence: compare them with the image, tick "
               "Checked when correct, or double-click the code to fix it."), "secondary")
        self._review_hint.setWordWrap(True)
        row.addWidget(self._review_hint, 1)
        self._all_reviewed_btn = widgets.push_button(tr("全部已核對", "All checked"), "ghost", "check")
        self._all_reviewed_btn.clicked.connect(self._model.set_all_reviewed)
        row.addWidget(self._all_reviewed_btn)
        lay.addLayout(row)
        lay.addWidget(self._view, 1)
        self._edit_error = widgets.label("", "error")
        self._edit_error.setWordWrap(True)
        self._edit_error.hide()
        lay.addWidget(self._edit_error)
        return w

    # -- state --------------------------------------------------------------------------------
    def state(self) -> str:
        """"loading" | "error" | "empty" | "results"."""
        return self._state

    def error_text(self) -> str:
        return self._error

    def ocr_result(self) -> OcrResult | None:
        return self._result

    def _set_state(self, state: str) -> None:
        self._state = state
        self._stack.setCurrentIndex(STATES.index(state))
        if state == "loading":
            self._spinner.start()
        else:
            self._spinner.stop()
        self._retry_btn.setEnabled(state != "loading")
        if state != "results":
            self._add_btn.setEnabled(False)
        else:
            self._update_summary()

    def _on_ocr_state(self, value: str) -> None:
        if self._state == "loading":
            self._loading_label.setText(tr("文字辨識引擎載入中…", "Loading the OCR engine…") if value == "loading"
                                        else tr("辨識中…", "Recognising…"))

    # -- OCR ----------------------------------------------------------------------------------
    def _start_ocr(self) -> None:
        self._cancel_job()
        fmt = self._resolve_format("")
        opts = OcrOptions(code_charset=fmt.allowed_chars() + fmt.separator, det_side=self.ctx.settings.ocr.det_side)
        state = getattr(getattr(self.ctx.ocr, "state", None), "value", "")
        self._loading_label.setText(tr("文字辨識引擎載入中…", "Loading the OCR engine…") if state == "loading"
                                    else tr("辨識中…", "Recognising…"))
        self._set_state("loading")
        self._summary.setText("")
        try:
            self._job = self.ctx.ocr.request(self._image, opts, self._on_ocr_done, self._on_ocr_error, priority=1)
        except Exception as exc:  # noqa: BLE001 - shown as the error state, never raised into Qt
            log.warning("OCR request failed: %s", exc)
            self._on_ocr_error(exc)

    def _cancel_job(self) -> None:
        if self._job is not None:
            try:
                self.ctx.ocr.cancel_request(self._job)
            except Exception:  # noqa: BLE001
                log.debug("cancel_request failed", exc_info=True)
            self._job = None

    def _on_ocr_done(self, result: OcrResult) -> None:
        self._job = None
        self._result = result
        self._extract()

    def _on_ocr_error(self, exc: Exception) -> None:
        self._job = None
        # OcrUnavailable carries the full 7.1 sentence in str() and the short reason in .reason (G2):
        # wrap only the short reason, never the sentence again
        reason = getattr(exc, "reason", "") or str(exc) or getattr(self.ctx.ocr, "error", "") or type(exc).__name__
        self._error = tr("文字辨識引擎無法啟動：{reason}。請重新下載完整的壓縮檔並解壓縮，或檢查防毒軟體是否隔離了檔案。",
                         "The OCR engine could not start: {reason}. Download and unzip the full package again, "
                         "or check whether antivirus quarantined files.").format(reason=reason.rstrip("。."))
        self._error_banner.setText(self._error)
        self._set_state("error")

    def _on_format_changed(self) -> None:
        if self._result is not None and self._state in ("empty", "results"):
            self._extract()

    def _extract(self) -> None:
        result = self._result
        if result is None:
            return
        text = result.text()
        fmt = self._resolve_format(text)
        cands = extract.extract_from_ocr(result, fmt, review_threshold=self.ctx.settings.ocr.review_threshold)
        self._set_candidates(cands)
        for e in self._model.entries:
            e.crop = self._crop(result, e.cand.line_index)
        kinds: dict[int, str] = {}
        for e in self._model.entries:
            if e.cand.line_index >= 0:
                kinds[e.cand.line_index] = "flagged" if e.cand.flagged else kinds.get(e.cand.line_index, "code")
        self._image_view.set_lines(result.lines, kinds)
        col = self._model.col("code")  # the code keeps its width; the badges column takes the rest
        self._view.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
        self._view.setColumnWidth(col, code_column_width(e.cand.code for e in self._model.entries))
        flagged = any(e.cand.flagged for e in self._model.entries)
        self._review_hint.setVisible(flagged)
        self._all_reviewed_btn.setVisible(flagged)
        if cands:
            self._set_state("results")
            self._view.selectRow(0)
        else:
            self._ocr_text.setPlainText(text)
            self._ocr_text_label.setVisible(bool(text.strip()))
            self._ocr_text.setVisible(bool(text.strip()))
            self._set_state("empty")

    def _crop(self, result: OcrResult, line_index: int) -> QPixmap | None:
        if not 0 <= line_index < len(result.lines):
            return None
        x, y, w, h = result.lines[line_index].bounds()
        if w <= 0 or h <= 0:
            return None
        part = imageio.crop(self._image, (x - 3, y - 3, w + 6, h + 6))
        if part.size == 0:
            return None
        pm = QPixmap.fromImage(imageio.to_qimage(part))
        return pm.scaledToHeight(min(64, max(16, pm.height())), Qt.TransformationMode.SmoothTransformation)

    # -- interaction --------------------------------------------------------------------------
    def _on_current_row(self, current: QModelIndex, _previous: QModelIndex) -> None:
        e = self._model.entry(current.row())
        self._image_view.highlight(e.cand.line_index if e is not None else -1)

    def _select_line(self, line_index: int) -> None:
        for row, e in enumerate(self._model.entries):
            if e.cand.line_index == line_index:
                self._view.selectRow(row)
                self._view.scrollTo(self._model.index(row, 0))
                return

    def _validate(self, text: str) -> tuple[str | None, str]:
        code, reason = extract.validate_code(clean_text(text).strip(), self._format)
        if code is None:
            return None, reason
        current = self._model.entry(self._view.currentIndex().row())
        for e in self._model.entries:
            if e is not current and code_key(e.cand.code) == code_key(code):
                return None, tr("這個序號已在清單中", "This code is already in the list")
        return code, ""

    def _apply_edit(self, entry: CandidateEntry, text: str) -> bool:
        code, reason = self._validate(text)
        if code is None:
            self._show_edit_error(reason)
            return False
        entry.cand.code = code
        entry.cand.repaired = []
        entry.cand.lookalikes = normalize.lookalike_indices(code, self._format)
        entry.edited = True
        entry.checked = True
        dup = self.ctx.queue.find_code(code, self._target.game_key)
        rec = self.ctx.history.latest(self._target.game_key, code) if self._target.game_key else None
        entry.duplicate = dup is not None
        entry.cand.duplicate_of = dup.id if dup is not None else ""
        entry.history_status = rec.status if rec is not None else None
        entry.cand.history_status = entry.history_status
        entry.history_skip = rec is not None and rec.status in self._target.skip_statuses
        self._edit_error.hide()
        return True

    def _show_edit_error(self, reason: str) -> None:
        self._edit_error.setText(reason)
        self._edit_error.setVisible(bool(reason))

    def _update_summary(self) -> None:
        super()._update_summary()
        if self._state != "results":
            self._add_btn.setEnabled(False)

    def candidates(self) -> list[CodeCandidate]:
        """The checked (possibly edited) candidates, valid after exec() returned Accepted."""
        return super().candidates()

    def code_format(self) -> CodeFormat:
        return super().code_format()

    def done(self, result: int) -> None:
        self._cancel_job()
        super().done(result)

    def accept(self) -> None:
        if self._state == "results" and self.summary_counts()[0] > 0:
            QDialog.accept(self)
