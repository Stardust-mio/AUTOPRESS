# OWNED BY G6
"""History page (SPEC section 6.4.4): table of attempts (時間, 序號, 遊戲, 設定檔, 結果 chip,
訊息, 證據 thumbnail -> image viewer), search, status and game filters, 重新加入佇列 (as items of
the record's game_key / game), 移除所選, 清除全部 (confirm), 匯出 CSV; empty state.

重新加入佇列: a code that is still queued for that game is reset to 待兌換 when it has a final
status (already pending or running codes are left alone); other codes are added as MANUAL items
of the record's game. Evidence paths are relative to the data folder (SPEC 5.8)."""

from __future__ import annotations

import logging
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from PyQt6.QtCore import (
    QAbstractTableModel,
    QEvent,
    QItemSelectionModel,
    QModelIndex,
    QRectF,
    QSize,
    QSizeF,
    Qt,
    QTimer,
    QUrl,
)
from PyQt6.QtGui import (
    QDesktopServices,
    QFontMetrics,
    QGuiApplication,
    QImage,
    QKeySequence,
    QPainter,
    QPaintEvent,
    QPixmap,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from .. import paths
from ..codes import csvexport
from ..context import AppContext
from ..i18n import T, tr
from ..models import AttemptRecord, CodeCandidate, CodeSource, CodeStatus, code_key
from ..storage import StorageError
from . import theme, widgets
from .codes_common import fit_wrapped_label, subscribe_weak
from .codes_model import ROLE_ITEM, ROLE_STATUS, CellDelegate, StatusDelegate
from .codes_paint import CELL_PAD, code_column_width, paint_code, status_column_width

log = logging.getLogger(__name__)

COL_TIME, COL_CODE, COL_GAME, COL_PROFILE, COL_RESULT, COL_MESSAGE, COL_EVIDENCE = range(7)
TITLES: tuple[T, ...] = (T("時間", "Time"), T("序號", "Code"), T("遊戲", "Game"), T("設定檔", "Profile"),
                         T("結果", "Result"), T("訊息", "Message"), T("證據", "Evidence"))
WIDTHS: tuple[int, ...] = (148, 0, 140, 140, 0, -1, 84)
"""Fixed widths (game / profile shrink on narrow windows); 0 = computed, -1 = stretch."""
STATUS_CHOICES: tuple[CodeStatus, ...] = (
    CodeStatus.SUCCESS, CodeStatus.SUBMITTED, CodeStatus.USED, CodeStatus.INVALID, CodeStatus.EXPIRED,
    CodeStatus.COOLDOWN, CodeStatus.FAILED, CodeStatus.REVIEW, CodeStatus.SKIPPED)
THUMB_W, THUMB_H = 60, 30
_KEEP = object()  # set_filters: leave this filter as it is


def thumb_source(pm: QPixmap) -> QPixmap:
    """The part of an evidence crop the 60 x 30 thumbnail shows: a crop wider than 2:1 is cut to a
    2:1 window starting just left of its content (the first column that differs from the corner
    colour), where a result message begins - squeezed whole into the cell, a 760 x 140 crop was a
    blank white strip 11 px tall."""
    w, h = pm.width(), pm.height()
    want = round(h * THUMB_W / THUMB_H)
    if w <= want or h <= 0:
        return pm
    try:
        import numpy as np

        img = pm.toImage().convertToFormat(QImage.Format.Format_RGB32)
        ptr = img.constBits()
        ptr.setsize(img.sizeInBytes())
        a = np.frombuffer(ptr, np.uint8).reshape(img.height(), img.bytesPerLine())[:, : w * 4].reshape(h, w, 4)
        diff = np.abs(a[:, :, :3].astype(np.int16) - a[0, 0, :3].astype(np.int16)).max(axis=2)
        cols = np.flatnonzero((diff > 40).any(axis=0))
        left = max(0, int(cols[0]) - 8) if cols.size else 0
    except Exception:  # noqa: BLE001 - a thumbnail must never fail: then the crop's left end
        left = 0
    left = min(left, w - want)
    return pm.copy(left, 0, want, h)


def format_time(iso: str) -> str:
    """ISO timestamp -> local "yyyy-mm-dd hh:mm" (the text itself when it cannot be parsed)."""
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return iso or ""


def evidence_file(evidence_path: str) -> Path | None:
    """The evidence PNG of a record (relative to the data folder), or None when missing."""
    if not evidence_path:
        return None
    p = Path(evidence_path)
    if not p.is_absolute():
        p = paths.data_dir(create=False) / p
    return p if p.is_file() else None


class HistoryTableModel(QAbstractTableModel):
    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._records: list[AttemptRecord] = []
        self._thumbs: dict[str, QPixmap | None] = {}

    def set_records(self, records: list[AttemptRecord]) -> None:
        self.beginResetModel()
        self._records = list(records)
        if len(self._thumbs) > 500:
            self._thumbs.clear()
        self.endResetModel()

    def records(self) -> list[AttemptRecord]:
        return list(self._records)

    def record_at(self, row: int) -> AttemptRecord | None:
        return self._records[row] if 0 <= row < len(self._records) else None

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._records)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(TITLES)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(TITLES):
            if role == Qt.ItemDataRole.DisplayRole:
                return str(TITLES[section])
            if role == Qt.ItemDataRole.TextAlignmentRole:
                return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return None

    def thumbnail(self, rec: AttemptRecord) -> QPixmap | None:
        if not rec.evidence_path:
            return None
        if rec.evidence_path not in self._thumbs:
            f = evidence_file(rec.evidence_path)
            pm = QPixmap(str(f)) if f is not None else QPixmap()
            self._thumbs[rec.evidence_path] = (
                None if pm.isNull() else thumb_source(pm).scaled(
                    THUMB_W * 2, THUMB_H * 2, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        return self._thumbs[rec.evidence_path]

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        rec = self.record_at(index.row()) if index.isValid() else None
        if rec is None:
            return None
        col = index.column()
        if role == ROLE_ITEM:
            return rec
        if role == ROLE_STATUS:
            return rec.status
        if role == Qt.ItemDataRole.DisplayRole:
            return {COL_TIME: format_time(rec.finished_at or rec.started_at), COL_CODE: rec.code,
                    COL_GAME: rec.game or ("" if rec.game_key else tr("未指定", "None")),
                    COL_PROFILE: rec.profile_name or (tr("手動標記", "Marked manually") if rec.run_id == "manual" else ""),
                    COL_RESULT: rec.status.label(), COL_MESSAGE: rec.message,
                    COL_EVIDENCE: "" if rec.evidence_path else "—"}.get(col)
        if role == Qt.ItemDataRole.DecorationRole and col == COL_EVIDENCE:
            return self.thumbnail(rec)
        if role == Qt.ItemDataRole.ToolTipRole:
            if col == COL_MESSAGE and rec.message:
                return rec.message
            if col == COL_EVIDENCE:
                return tr("點一下放大證據圖片", "Click to view the evidence image") if self.thumbnail(rec) else \
                    tr("沒有證據圖片", "No evidence image")
            if col == COL_RESULT and rec.matched_keyword:
                return tr("符合關鍵字：{k}", "Matched keyword: {k}").format(k=rec.matched_keyword)
            if col == COL_TIME:
                return rec.finished_at
        return None


class HistoryCodeDelegate(CellDelegate):
    def paint_content(self, painter: QPainter, rect: QRectF, index: QModelIndex) -> None:
        paint_code(painter, rect, str(index.data(Qt.ItemDataRole.DisplayRole) or ""))


class EvidenceDelegate(CellDelegate):
    pad = 8

    def paint_content(self, painter: QPainter, rect: QRectF, index: QModelIndex) -> None:
        pm = index.data(Qt.ItemDataRole.DecorationRole)
        if not isinstance(pm, QPixmap) or pm.isNull():
            painter.setFont(theme.font(theme.FS_BODY))
            painter.setPen(theme.color("text_disabled"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "—")
            return
        w, h = pm.width(), pm.height()
        scale = min(THUMB_W / max(1, w), THUMB_H / max(1, h))
        target = QRectF(rect.left(), rect.center().y() - h * scale / 2, w * scale, h * scale)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(target, pm, QRectF(0, 0, w, h))
        painter.setPen(theme.color("border_strong"))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(target.adjusted(-0.5, -0.5, 0.5, 0.5), 3, 3)


class EvidenceImage(QWidget):
    """An evidence crop at its natural size inside a 1 px frame, at the top left. The crop holds screen
    pixels, so each image pixel is drawn on one screen pixel: as large as it was on screen and sharp at any
    Windows scaling. The frame keeps a white crop visible on the light dialog. Colours are read at paint time."""

    FRAME = 1

    def __init__(self, pixmap: QPixmap, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixmap = pixmap
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        self.setAccessibleName(tr("證據圖片", "Evidence image"))

    def pixmap(self) -> QPixmap:
        return self._pixmap

    def image_size(self) -> QSizeF:
        """The crop's size in device-independent pixels on this widget's screen."""
        dpr = self.devicePixelRatioF() or 1.0
        return QSizeF(self._pixmap.width() / dpr, self._pixmap.height() / dpr)

    def sizeHint(self) -> QSize:
        if self._pixmap.isNull():
            return QSize(0, 0)
        s = self.image_size()
        return QSize(math.ceil(s.width()) + 2 * self.FRAME, math.ceil(s.height()) + 2 * self.FRAME)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()  # the scroll area scrolls instead of squeezing the image

    def event(self, event: QEvent | None) -> bool:
        if event is not None and event.type() == QEvent.Type.DevicePixelRatioChange:
            self.updateGeometry()  # another screen scaling: another natural size
        return super().event(event)

    def paintEvent(self, _event: QPaintEvent | None) -> None:
        if self._pixmap.isNull():
            return
        s, f = self.image_size(), self.FRAME
        p = QPainter(self)
        p.fillRect(QRectF(0, 0, s.width() + 2 * f, s.height() + 2 * f), theme.color("border_strong"))
        # no SmoothPixmapTransform: the target is the crop's own size in device pixels, a 1:1 copy
        p.drawPixmap(QRectF(f, f, s.width(), s.height()), self._pixmap, QRectF(self._pixmap.rect()))
        p.end()


class EvidenceDialog(QDialog):
    """The evidence crop of one attempt at its natural size, framed (scrolls when larger), with the
    attempt's time."""

    MAX_VIEW = QSize(960, 560)
    """Largest image area before the dialog scrolls."""

    def __init__(self, record: AttemptRecord, path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("證據：{code}", "Evidence: {code}").format(code=record.code))
        self._path = path
        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.SP[5], theme.SP[4], theme.SP[5], theme.SP[4])
        lay.setSpacing(theme.SP[3])
        head = QHBoxLayout()
        head.addWidget(widgets.label(record.code, "mono"))
        head.addWidget(widgets.StatusChip(record.status))
        head.addStretch(1)
        when = format_time(record.finished_at or record.started_at)  # the same time as the table row
        self.time_label = widgets.label(when, "muted") if when else None
        if self.time_label is not None:
            head.addWidget(self.time_label)
        lay.addLayout(head)
        self.image = EvidenceImage(QPixmap(str(path)))
        self._scroll = scroll = QScrollArea()
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(self.image)
        scroll.setWidgetResizable(True)
        lay.addWidget(scroll, 1)
        self._fit_view()
        if record.message:
            msg = widgets.label(record.message, "secondary")
            msg.setWordWrap(True)
            lay.addWidget(msg)
        row = QHBoxLayout()
        folder = widgets.push_button(tr("開啟資料夾", "Open folder"), "secondary", "folder")
        folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._path.parent))))
        row.addWidget(folder)
        row.addStretch(1)
        close = widgets.push_button(tr("關閉", "Close"), "primary")
        close.setDefault(True)
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)

    def _fit_view(self) -> None:
        """The image area shows the whole crop up to MAX_VIEW, measured with the scaling of the
        screen the dialog is on (again when it is shown or moved to another screen)."""
        hint, cap = self.image.sizeHint(), self.MAX_VIEW
        bar = 12  # a scroll bar (10 px + margins in the app style) when the other side is capped
        self._scroll.setMinimumSize(min(hint.width(), cap.width()) + (bar if hint.height() > cap.height() else 0),
                                    min(hint.height(), cap.height()) + (bar if hint.width() > cap.width() else 0))

    def showEvent(self, event: Any) -> None:  # noqa: N802
        self._fit_view()
        super().showEvent(event)

    def event(self, event: QEvent | None) -> bool:
        if event is not None and event.type() == QEvent.Type.DevicePixelRatioChange:
            self._fit_view()
        return super().event(event)


class HistoryPage(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.setObjectName("HistoryPage")
        self._statuses: list[CodeStatus | None] = [None, *STATUS_CHOICES]
        self._game_keys: list[str | None] = [None]
        self._last_games: list[tuple[str, str]] | None = None
        self._model = HistoryTableModel(self)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(0)
        self._refresh_timer.timeout.connect(self.refresh)
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.setInterval(0)
        self._fit_timer.timeout.connect(self._fit_columns)
        self._build_ui()
        self._unsubscribe = subscribe_weak(ctx.history.subscribe, self._on_history_changed)
        self.destroyed.connect(self._unsubscribe)
        ctx.signals.theme_changed.connect(self._on_theme_changed)
        self.refresh()

    # -- layout ---------------------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(*theme.PAGE_MARGINS)
        root.setSpacing(theme.SP[4])
        head = QHBoxLayout()
        head.setSpacing(theme.SP[2])
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(widgets.label(tr("紀錄", "History"), "display"))
        self._subtitle = widgets.label("", "muted")
        titles.addWidget(self._subtitle)
        head.addLayout(titles)
        head.addStretch(1)
        self._export_btn = widgets.push_button(tr("匯出 CSV", "Export CSV"), "secondary", "export")
        self._export_btn.setToolTip(tr("匯出目前列出的紀錄（UTF-8，Excel 可直接開啟）",
                                       "Export the records shown (UTF-8, opens in Excel)"))
        self._export_btn.clicked.connect(self.export_csv)
        self._clear_btn = widgets.push_button(tr("清除全部", "Clear all"), "danger", "trash")
        self._clear_btn.clicked.connect(self.clear_all)
        head.addWidget(self._export_btn)
        head.addWidget(self._clear_btn)
        root.addLayout(head)

        card = widgets.Card(vertical=True, margins=(theme.SP[4], theme.SP[3], theme.SP[4], theme.SP[2]),
                            spacing=theme.SP[2])
        lay = card.layout()
        top = QHBoxLayout()
        top.setSpacing(theme.SP[3])
        self._search = widgets.SearchField(tr("搜尋序號、訊息、遊戲或設定檔", "Search codes, messages, games or profiles"))
        self._search.setMinimumWidth(180)
        self._search.setMaximumWidth(320)
        self._search.textChanged.connect(self._refresh_timer.start)
        top.addWidget(self._search, 1)
        top.addStretch(1)
        top.addWidget(widgets.label(tr("結果", "Result"), "secondary"))
        self._status_combo = widgets.combo([tr("所有結果", "All results")] + [s.label() for s in STATUS_CHOICES])
        self._status_combo.setAccessibleName(tr("結果篩選", "Result filter"))
        self._status_combo.currentIndexChanged.connect(self._refresh_timer.start)
        top.addWidget(self._status_combo)
        top.addWidget(widgets.label(tr("遊戲", "Game"), "secondary"))
        self._game_combo = widgets.combo([tr("所有遊戲", "All games")])
        self._game_combo.setMinimumWidth(140)
        self._game_combo.setAccessibleName(tr("遊戲篩選", "Game filter"))
        self._game_combo.currentIndexChanged.connect(self._refresh_timer.start)
        top.addWidget(self._game_combo)
        lay.addLayout(top)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_table())
        go = widgets.push_button(tr("前往序號頁", "Go to Codes"), "primary", "codes")
        go.clicked.connect(lambda: self.ctx.navigate("codes"))
        hint = tr("開始兌換後，每一筆的結果都會記在這裡；之後匯入同一款遊戲的序號時，已兌換過的會自動略過。",
                  "Every attempt is recorded here once you start redeeming; codes already redeemed for a game are "
                  "skipped on later imports.")
        empty = widgets.EmptyState("history", tr("還沒有兌換紀錄", "No history yet"), hint, actions=[go])
        for lb in empty.findChildren(QLabel):
            if lb.text() == hint and lb.wordWrap():
                fit_wrapped_label(lb, 560)
        self._stack.addWidget(empty)
        no_match = QWidget()
        nl = QVBoxLayout(no_match)
        nl.addStretch(1)
        self._no_match = widgets.label(tr("沒有符合篩選條件的紀錄", "No records match the filters"), "secondary")
        self._no_match.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nl.addWidget(self._no_match)
        nl.addStretch(2)
        self._stack.addWidget(no_match)
        lay.addWidget(self._stack, 1)

        bar = QHBoxLayout()
        bar.setSpacing(theme.SP[1])
        self._sel_label = widgets.label("", "secondary")
        bar.addWidget(self._sel_label)
        bar.addSpacing(theme.SP[2])
        self._requeue_btn = widgets.push_button(tr("重新加入佇列", "Queue again"), "ghost", "refresh")
        self._requeue_btn.setToolTip(tr("把選取的序號加回序號頁（同一款遊戲），狀態改為待兌換",
                                        "Put the selected codes back on the Codes page (same game) as pending"))
        self._requeue_btn.clicked.connect(self.requeue_selected)
        self._remove_btn = widgets.push_button(tr("移除所選", "Remove selected"), "ghost", "trash")
        self._remove_btn.clicked.connect(self.remove_selected)
        bar.addWidget(self._requeue_btn)
        bar.addWidget(self._remove_btn)
        bar.addStretch(1)
        lay.addLayout(bar)
        self._bar_widgets = [self._sel_label, self._requeue_btn, self._remove_btn]
        root.addWidget(card, 1)

    def _build_table(self) -> QTableView:
        t = QTableView()
        t.setObjectName("HistoryTable")
        t.setAccessibleName(tr("兌換紀錄", "Redemption history"))
        t.setModel(self._model)
        t.setShowGrid(False)
        t.setWordWrap(False)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        t.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        t.customContextMenuRequested.connect(self._on_context_menu)
        t.clicked.connect(self._on_clicked)
        t.verticalHeader().setVisible(False)
        t.verticalHeader().setDefaultSectionSize(theme.ROW_H)
        header = t.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setHighlightSections(False)
        header.setFixedHeight(36)
        self._delegates = {COL_CODE: HistoryCodeDelegate(t), COL_RESULT: StatusDelegate(t),
                           COL_EVIDENCE: EvidenceDelegate(t)}
        for col in range(len(TITLES)):
            t.setItemDelegateForColumn(col, self._delegates.get(col) or CellDelegate(t))
            w = WIDTHS[col]
            if w < 0:
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
            else:
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
                t.setColumnWidth(col, w or (status_column_width() if col == COL_RESULT else 180))
        t.selectionModel().selectionChanged.connect(self._update_bar)
        sc = QShortcut(QKeySequence(QKeySequence.StandardKey.Delete), t)
        sc.setContext(Qt.ShortcutContext.WidgetShortcut)
        sc.activated.connect(self.remove_selected)
        cp = QShortcut(QKeySequence(QKeySequence.StandardKey.Copy), t)
        cp.setContext(Qt.ShortcutContext.WidgetShortcut)
        cp.activated.connect(self.copy_selected)
        self._table = t
        return t

    # -- data -----------------------------------------------------------------------------------
    def _on_history_changed(self, *_args: object) -> None:
        self._refresh_timer.start()

    def _on_theme_changed(self, _name: str) -> None:
        self._table.viewport().update()

    def status_filter(self) -> CodeStatus | None:
        i = self._status_combo.currentIndex()
        return self._statuses[i] if 0 <= i < len(self._statuses) else None

    def game_filter(self) -> str | None:
        i = self._game_combo.currentIndex()
        return self._game_keys[i] if 0 <= i < len(self._game_keys) else None

    def set_filters(self, text: str | None = None, status: Any = _KEEP, game_key: Any = _KEEP) -> None:
        """Programmatic filters (tests, links from other pages); omitted arguments stay as they are.
        ``status`` / ``game_key`` None = all."""
        if text is not None:
            self._search.setText(text)
        if status is not _KEEP:
            self._status_combo.setCurrentIndex(self._statuses.index(status) if status in self._statuses else 0)
        if game_key is not _KEEP:
            self._reload_games()
            self._game_combo.setCurrentIndex(self._game_keys.index(game_key) if game_key in self._game_keys else 0)
        self.refresh()

    def _reload_games(self) -> None:
        games = self.ctx.history.games()
        if games == self._last_games:
            return
        self._last_games = list(games)
        current = self.game_filter()
        keys: list[str | None] = [None]
        labels = [tr("所有遊戲", "All games")]
        for key, name in games:
            keys.append(key)
            labels.append(name or (tr("未指定遊戲", "No game") if not key else tr("（未命名遊戲）", "(unnamed game)")))
        self._game_combo.blockSignals(True)
        self._game_combo.clear()
        self._game_combo.addItems(labels)
        self._game_combo.setCurrentIndex(keys.index(current) if current in keys else 0)
        self._game_combo.blockSignals(False)
        self._game_keys = keys

    def refresh(self) -> None:
        self._refresh_timer.stop()
        self._reload_games()
        status = self.status_filter()
        selected = {r.id for r in self.selected_records()}
        records = self.ctx.history.query(self._search.text(), [status] if status is not None else None,
                                         self.game_filter())
        self._model.set_records(records)
        if selected:
            sel = self._table.selectionModel()
            for row, rec in enumerate(records):
                if rec.id in selected:
                    sel.select(self._model.index(row, 0),
                               QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        width = code_column_width(r.code for r in records)
        if width != self._table.columnWidth(COL_CODE):
            self._table.setColumnWidth(COL_CODE, width)
        self._fit_columns()  # the game / profile columns follow their entries
        all_records = self.ctx.history.records()
        total = len(all_records)
        ok = sum(1 for r in all_records if r.status is CodeStatus.SUCCESS)
        self._subtitle.setText(tr("共 {n} 筆紀錄 · 成功 {s} 筆", "{n} records · {s} redeemed").format(n=total, s=ok)
                               if total else tr("尚無紀錄", "No records yet"))
        self._stack.setCurrentIndex(0 if records else (1 if not total else 2))
        for w in self._bar_widgets:
            w.setVisible(bool(total))
        self._export_btn.setEnabled(bool(records))
        self._clear_btn.setEnabled(bool(total))
        self._update_bar()

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self._fit_timer.start()

    def _fit_columns(self) -> None:
        """Game and profile columns are as wide as their longest entry (at most WIDTHS), and give up
        width on narrow windows, so the message column gets the rest (fewer cut-off messages) and the
        evidence column stays visible (the table never scrolls sideways)."""
        vw = self._table.viewport().width()
        fixed = sum(self._table.columnWidth(c) for c in (COL_TIME, COL_CODE, COL_RESULT, COL_EVIDENCE))
        each = int(max(72, min(WIDTHS[COL_GAME], (vw - fixed - 120) / 2)))
        header = self._table.horizontalHeader()
        fm = QFontMetrics(theme.font(theme.FS_BODY))  # what CellDelegate paints
        for col in (COL_GAME, COL_PROFILE):
            texts = (str(self._model.data(self._model.index(row, col)) or "") for row in range(self._model.rowCount()))
            need = max([header.sectionSizeHint(col)] + [fm.horizontalAdvance(t) + 2 * CELL_PAD + 4 for t in texts])
            width = max(72, min(each, need))
            if self._table.columnWidth(col) != width:
                self._table.setColumnWidth(col, width)

    def records_shown(self) -> list[AttemptRecord]:
        return self._model.records()

    def selected_records(self) -> list[AttemptRecord]:
        rows = sorted({ix.row() for ix in self._table.selectionModel().selectedRows()})
        return [r for row in rows if (r := self._model.record_at(row)) is not None]

    def _update_bar(self, *_args: object) -> None:
        n = len(self.selected_records())
        self._sel_label.setText(tr("已選取 {n} 筆", "{n} selected").format(n=n))
        self._requeue_btn.setEnabled(n > 0)
        self._remove_btn.setEnabled(n > 0)

    # -- actions --------------------------------------------------------------------------------
    def requeue_selected(self) -> int:
        """重新加入佇列 as codes of each record's game. Returns the number added or reset.
        Items of an active run's plan are never touched (G-16); a code the history marks as done is
        queued, but the user is told that 開始兌換 still skips it while the history skip is on (G-19)."""
        seen: set[tuple[str, str]] = set()
        groups: dict[tuple[str, str], list[CodeCandidate]] = {}
        reset_ids: list[str] = []
        already = locked = done = 0
        queue, session = self.ctx.queue, self.ctx.session
        plan = session.plan if session.is_active() else None
        plan_ids = {i.code_id for i in plan.items} if plan is not None else set()
        settings = self.ctx.settings
        skip = set(settings.history_skip_statuses) if settings.skip_history_on_import else set()
        for rec in self.selected_records():
            key = (rec.game_key, code_key(rec.code))
            if not rec.code or key in seen:
                continue
            seen.add(key)
            item = queue.find_code(rec.code, rec.game_key)
            if item is not None and item.id in plan_ids:
                locked += 1
                continue
            latest = self.ctx.history.latest(rec.game_key, rec.code) if rec.game_key else None
            if latest is not None and latest.status in skip:
                done += 1
            if item is not None:
                if item.status.is_runnable or item.status is CodeStatus.RUNNING:
                    already += 1
                else:
                    reset_ids.append(item.id)
                continue
            groups.setdefault((rec.game_key, rec.game), []).append(CodeCandidate(code=rec.code, raw=rec.code))
        added = queue.reset(reset_ids) if reset_ids else 0
        for (game_key, game), cands in groups.items():
            res = queue.add_candidates(cands, CodeSource.MANUAL, source_detail=tr("紀錄", "History"),
                                       game_key=game_key, game=game)
            added += len(res.added)
            already += res.duplicates
        if added or already or locked:
            text = tr("已重新加入 {n} 筆序號", "Queued {n} code(s) again").format(n=added)
            if already:
                text += tr("（{d} 筆已在佇列中）", " ({d} already queued)").format(d=already)
            if locked:
                text += tr("；{n} 筆執行中，請先停止", "; {n} are in the running plan - stop the run first").format(n=locked)
            if done and added:
                text += tr("。紀錄顯示其中 {n} 筆已兌換過：開始兌換時仍會略過，除非關閉「略過已兌換過的序號」或移除那筆紀錄。",
                           ". The history says {n} of them were redeemed: runs still skip them unless you turn off "
                           "'Skip codes already redeemed' or remove the record.").format(n=done)
            self.ctx.notify(text, "success" if added and not (locked or done) else ("warning" if locked or done else "info"))
        return added

    def remove_selected(self) -> int:
        recs = self.selected_records()
        if not recs:
            return 0
        if not widgets.confirm(self, tr("移除紀錄", "Remove records"),
                               tr("要移除 {n} 筆紀錄嗎？之後匯入時，這些序號不會再被當成「已兌換過」。",
                                  "Remove {n} records? Later imports will no longer treat these codes as redeemed.")
                               .format(n=len(recs)), tr("移除", "Remove"), danger=True):
            return 0
        n = self.ctx.history.remove([r.id for r in recs])
        self.ctx.notify(tr("已移除 {n} 筆紀錄", "Removed {n} record(s)").format(n=n), "info")
        return n

    def clear_all(self) -> int:
        total = len(self.ctx.history.records())
        if not total or not widgets.confirm(
                self, tr("清除全部紀錄", "Clear all history"),
                tr("要清除全部 {n} 筆紀錄嗎？此動作無法復原，之後匯入時不會再自動略過已兌換過的序號。",
                   "Clear all {n} records? This cannot be undone, and later imports will no longer skip "
                   "codes that were redeemed.").format(n=total), tr("全部清除", "Clear all"), danger=True):
            return 0
        n = self.ctx.history.clear()
        self.ctx.notify(tr("已清除 {n} 筆紀錄", "Cleared {n} record(s)").format(n=n), "info")
        return n

    def export_csv(self) -> bool:
        records = self.records_shown()
        if not records:
            return False
        name = f"autopress-history-{datetime.now():%Y%m%d-%H%M}.csv"
        path, _ = QFileDialog.getSaveFileName(self, tr("匯出 CSV", "Export CSV"), str(Path.home() / name),
                                              tr("CSV 檔 (*.csv)", "CSV files (*.csv)"))
        if not path:
            return False
        try:
            csvexport.export_history_csv(Path(path), records)
        except (StorageError, OSError) as exc:
            self.ctx.notify(str(exc), "error")
            return False
        self.ctx.notify(tr("已匯出 {n} 筆到 {name}", "Exported {n} record(s) to {name}").format(
            n=len(records), name=Path(path).name), "success")
        return True

    def copy_selected(self) -> int:
        recs = self.selected_records()
        if recs:
            QGuiApplication.clipboard().setText("\n".join(r.code for r in recs))
        return len(recs)

    def open_evidence(self, record: AttemptRecord) -> QDialog | None:
        f = evidence_file(record.evidence_path)
        if f is None:
            self.ctx.notify(tr("找不到證據圖片（可能已超過保留天數而被刪除）",
                               "The evidence image is gone (older than the keep period?)"), "info")
            return None
        dlg = EvidenceDialog(record, f, self)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dlg.open()
        return dlg

    def _on_clicked(self, index: QModelIndex) -> None:
        if index.column() == COL_EVIDENCE:
            rec = self._model.record_at(index.row())
            if rec is not None and rec.evidence_path:
                self.open_evidence(rec)

    def _on_context_menu(self, pos: object) -> None:
        index = self._table.indexAt(pos)  # type: ignore[arg-type]
        rec = self._model.record_at(index.row()) if index.isValid() else None
        if rec is None:
            return
        if index.row() not in {ix.row() for ix in self._table.selectionModel().selectedRows()}:
            self._table.selectRow(index.row())
        menu = QMenu(self)
        menu.addAction(tr("重新加入佇列", "Queue again")).triggered.connect(lambda _c=False: self.requeue_selected())
        menu.addAction(tr("複製序號", "Copy code")).triggered.connect(lambda _c=False: self.copy_selected())
        ev = menu.addAction(tr("檢視證據", "View evidence"))
        ev.setEnabled(evidence_file(rec.evidence_path) is not None)
        ev.triggered.connect(lambda _c=False: self.open_evidence(rec))
        menu.addSeparator()
        menu.addAction(tr("移除", "Remove")).triggered.connect(lambda _c=False: self.remove_selected())
        menu.popup(self._table.viewport().mapToGlobal(pos))  # type: ignore[arg-type]
