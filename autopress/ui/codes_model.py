# OWNED BY G6
"""Qt model, filter proxy and delegates for the code queue table (SPEC 6.4.1).

Columns (COLUMNS): check (titled 執行, header tooltip ``check_column_tip``), #, 序號 (mono;
``flagged`` characters highlighted with warning_soft and underlined, ``lookalikes`` with a dotted
underline only), 來源 (icon + label), 辨識信心 (bar only for OCR sources), 狀態 (status chip via
widgets.paint_status_chip), 訊息 (elided), ⋯ (row menu). Rows 42 px, no grid. The model observes
CodeQueue.subscribe and maps QueueEvents to fine-grained model signals: after every event it
diffs the queue's id list against its own (missing ids -> rowsRemoved, a new order ->
layoutChanged with the persistent indexes moved, new ids -> rowsInserted, then dataChanged), so
it stays correct whatever ids an event names.

Painting helpers shared with the import dialogs and the History page: ``paint_code``,
``paint_badge``, ``paint_confidence``, ``paint_check`` and ``CellDelegate`` (draws the QSS item
background first, then the custom content - prototype lesson in ux.md section 6).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from PyQt6.QtCore import (
    QAbstractTableModel,
    QEvent,
    QModelIndex,
    QPersistentModelIndex,
    QPointF,
    QRectF,
    QSize,
    QSortFilterProxyModel,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QIcon, QPainter
from PyQt6.QtWidgets import QApplication, QLineEdit, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QToolTip, QWidget

from ..i18n import T, tr
from ..models import CodeItem, CodeStatus, QueueEvent, QueueEventKind, RunSelection, code_key
from ..textutil import clean_text
from . import icons, theme, widgets
from .codes_common import subscribe_weak
from .codes_paint import CELL_PAD, paint_check, paint_code, paint_confidence

log = logging.getLogger(__name__)

COL_CHECK, COL_INDEX, COL_CODE, COL_SOURCE, COL_CONF, COL_STATUS, COL_MESSAGE, COL_MORE = range(8)
COLUMNS: tuple[str, ...] = ("check", "index", "code", "source", "confidence", "status", "message", "more")

ROLE_ITEM = Qt.ItemDataRole.UserRole + 1  # the CodeItem of the row
ROLE_FLAGGED = Qt.ItemDataRole.UserRole + 2  # list[int]
ROLE_STATUS = Qt.ItemDataRole.UserRole + 3  # CodeStatus
ROLE_LOOKALIKES = Qt.ItemDataRole.UserRole + 4  # list[int]
ROLE_GAME = Qt.ItemDataRole.UserRole + 5  # game_key str
ROLE_CONFIDENCE = Qt.ItemDataRole.UserRole + 6  # float | None (OCR sources only)
ROLE_SOURCE = Qt.ItemDataRole.UserRole + 7  # CodeSource
ROLE_LOCKED = Qt.ItemDataRole.UserRole + 8  # bool: the row belongs to the active run plan (read-only)

FILTERS: tuple[str, ...] = ("all", "pending", "review", "done", "failed", "skipped")
"""Status filter keys (segments 全部 / 待兌換 / 需確認 / 已完成 / 失敗 / 已略過): all; pending (PENDING,
COOLDOWN, RUNNING); review (REVIEW); done (SUCCESS, SUBMITTED, USED); failed (FAILED, INVALID, EXPIRED);
skipped (SKIPPED)."""

FILTER_STATUSES: dict[str, frozenset[CodeStatus]] = {
    "pending": frozenset({CodeStatus.PENDING, CodeStatus.COOLDOWN, CodeStatus.RUNNING}),
    "review": frozenset({CodeStatus.REVIEW}),
    "done": frozenset({CodeStatus.SUCCESS, CodeStatus.SUBMITTED, CodeStatus.USED}),
    "failed": frozenset({CodeStatus.FAILED, CodeStatus.INVALID, CodeStatus.EXPIRED}),
    "skipped": frozenset({CodeStatus.SKIPPED}),
}
FILTER_LABELS: dict[str, T] = {
    "all": T("全部", "All"), "pending": T("待兌換", "Pending"), "review": T("需確認", "Review"),
    "done": T("已完成", "Done"), "failed": T("失敗", "Failed"), "skipped": T("已略過", "Skipped"),
}
COLUMN_TITLES: tuple[T, ...] = (T("執行", "Run"), T("#", "#"), T("序號", "Code"), T("來源", "Source"),
                                T("辨識信心", "Confidence"), T("狀態", "Status"), T("訊息", "Message"), T("", ""))
"""The check column is titled 執行 / Run: its ticks say which codes 「只跑勾選的」 redeems, so they
are never mistaken for the row selection that the bulk actions use."""
COLUMN_WIDTHS: tuple[int, ...] = (56, 44, 220, 112, 116, 0, -1, 44)
"""Fixed widths; 0 = computed from the widest status chip, -1 = stretch. The page fits the code
column to the longest code (``code_column_width``). 56 = the bold 12 px header title plus the
12 px section padding on each side."""


def check_column_tip() -> str:
    """Tooltip of the 執行 column header: what a tick does in each run setting (the setting's
    names come from RunSelection, as on the Run page) and that bulk actions use the selection."""
    return tr("勾選＝在「執行」頁選「{checked}」時要兌換的序號（選「{all}」時勾選不影響）。\n"
              "批次動作只作用在點選反白的序號。",
              "Checked = redeemed when the Run page is set to {checked} (no effect with {all}).\n"
              "Bulk actions work on the highlighted codes.").format(
        checked=RunSelection.CHECKED.label(), all=RunSelection.UNFINISHED.label())


MUTED_STATUSES = frozenset({CodeStatus.USED, CodeStatus.INVALID, CodeStatus.EXPIRED, CodeStatus.SKIPPED})


def filter_accepts(key: str, status: CodeStatus) -> bool:
    """Whether a status passes the status filter ``key`` (one of FILTERS)."""
    return key == "all" or status in FILTER_STATUSES.get(key, frozenset())


def search_accepts(item: CodeItem, text: str) -> bool:
    """Case-insensitive match in code, message or source text; separators in the code are ignored."""
    t = text.strip().casefold()
    if not t:
        return True
    if t in f"{item.code}\n{item.message}\n{item.raw}".casefold():
        return True
    bare = code_key(t)
    return bool(bare) and bare in code_key(item.code).casefold()


# ============================================================================= model


class CodesTableModel(QAbstractTableModel):
    """Rows = queue items in queue order. Writes go back to the queue (check state, code edits
    through ``code_editor``); rows in ``locked`` ids (the active run plan) are read-only."""

    itemsChanged = pyqtSignal()  # after every applied queue change (structure or data)

    def __init__(self, queue: object, parent: object | None = None) -> None:
        """``queue`` is a codes.queue.CodeQueue (or a test fake with the same API)."""
        super().__init__(parent)  # type: ignore[arg-type]
        self._queue: Any = queue
        self._items: list[CodeItem] = []
        self._rows: dict[str, int] = {}
        self._locked: frozenset[str] = frozenset()
        self._defer = 0
        self._pending: set[QueueEventKind] = set()
        self.code_editor: Callable[[CodeItem, str], bool] | None = None
        """Applies an edited code (the page validates, checks duplicates and updates the queue);
        None -> ``queue.update(id, code=text)``."""
        self._items = list(self._queue.items())
        self._reindex()
        self._unsubscribe = subscribe_weak(self._queue.subscribe, self._on_queue_event)
        self.destroyed.connect(self._unsubscribe)

    # -- access -------------------------------------------------------------------------------
    def item_at(self, row: int) -> CodeItem | None:
        return self._items[row] if 0 <= row < len(self._items) else None

    def row_of(self, code_id: str) -> int:
        return self._rows.get(code_id, -1)

    def items(self) -> list[CodeItem]:
        return list(self._items)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._items)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(COLUMNS)

    # -- locking (active run plan) ------------------------------------------------------------
    def set_locked(self, code_ids: Iterable[str]) -> None:
        ids = frozenset(code_ids)
        if ids == self._locked:
            return
        self._locked = ids
        self._emit_all_changed()

    def is_locked(self, code_id: str) -> bool:
        return code_id in self._locked

    def locked_ids(self) -> frozenset[str]:
        return self._locked

    def can_edit(self, item: CodeItem) -> bool:
        return item.id not in self._locked and item.status is not CodeStatus.RUNNING

    # -- Qt API ---------------------------------------------------------------------------------
    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if orientation != Qt.Orientation.Horizontal or not 0 <= section < len(COLUMNS):
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return str(COLUMN_TITLES[section])
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ToolTipRole and section == COL_CHECK:
            return check_column_tip()
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        item = self.item_at(index.row()) if index.isValid() else None
        if item is None:
            return Qt.ItemFlag.NoItemFlags
        f = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == COL_CHECK and item.id not in self._locked:
            f |= Qt.ItemFlag.ItemIsUserCheckable
        if index.column() == COL_CODE and self.can_edit(item):
            f |= Qt.ItemFlag.ItemIsEditable
        return f

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        item = self.item_at(index.row()) if index.isValid() else None
        if item is None:
            return None
        col = index.column()
        if role == ROLE_ITEM:
            return item
        if role == ROLE_STATUS:
            return item.status
        if role == ROLE_FLAGGED:
            return list(item.flagged)
        if role == ROLE_LOOKALIKES:
            return list(item.lookalikes)
        if role == ROLE_GAME:
            return item.game_key
        if role == ROLE_CONFIDENCE:
            return item.confidence if item.source.is_ocr else None
        if role == ROLE_SOURCE:
            return item.source
        if role == ROLE_LOCKED:
            return item.id in self._locked
        if role == Qt.ItemDataRole.DisplayRole:
            return self._display(item, index.row(), col)
        if role == Qt.ItemDataRole.EditRole and col == COL_CODE:
            return item.code
        if role == Qt.ItemDataRole.CheckStateRole and col == COL_CHECK:
            return Qt.CheckState.Checked if item.checked else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip(item, col)
        return None

    def _display(self, item: CodeItem, row: int, col: int) -> str | None:
        if col == COL_INDEX:
            return str(row + 1)
        if col == COL_CODE:
            return item.code
        if col == COL_SOURCE:
            return item.source.label()
        if col == COL_CONF:
            conf = item.confidence if item.source.is_ocr else None
            return "—" if conf is None else f"{round(conf * 100)}%"
        if col == COL_STATUS:
            return item.status.label()
        if col == COL_MESSAGE:
            return item.message
        return None

    def _tooltip(self, item: CodeItem, col: int) -> str | None:
        if item.id in self._locked and col in (COL_CHECK, COL_CODE, COL_MORE):
            return tr("執行中，請先停止", "Running - stop the run first")
        if col == COL_CODE:
            lines = []
            if item.raw and item.raw.strip() != item.code:
                lines.append(tr("原文：{raw}", "Source text: {raw}").format(raw=item.raw.strip()))
            if item.flagged:
                pos = "、".join(str(i + 1) for i in item.flagged)
                lines.append(tr("第 {pos} 個字元需要確認", "Check character(s) {pos}").format(pos=pos))
            if item.game:
                lines.append(tr("遊戲：{game}", "Game: {game}").format(game=item.game))
            elif not item.game_key:
                lines.append(tr("尚未指定遊戲", "No game assigned yet"))
            lines.append(tr("雙擊或按 F2 修改", "Double-click or press F2 to edit"))
            return "\n".join(lines)
        if col == COL_SOURCE:
            return item.source_detail or item.source.label()
        if col == COL_MESSAGE:
            return item.message or None
        if col == COL_CHECK:
            return check_column_tip()
        if col == COL_MORE:
            return tr("更多動作", "More actions")
        return None

    def setData(self, index: QModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:
        item = self.item_at(index.row()) if index.isValid() else None
        if item is None or item.id in self._locked:
            return False
        col = index.column()
        if col == COL_CHECK and role == Qt.ItemDataRole.CheckStateRole:
            checked = value in (Qt.CheckState.Checked, Qt.CheckState.Checked.value, True)
            self._queue.set_checked([item.id], checked)
            return True
        if col == COL_CODE and role == Qt.ItemDataRole.EditRole:
            text = clean_text(str(value)).strip()
            if not text or text == item.code or not self.can_edit(item):
                return False
            if self.code_editor is not None:
                return bool(self.code_editor(item, text))
            self._queue.update(item.id, code=text)
            return True
        return False

    # -- queue observation ------------------------------------------------------------------
    @contextmanager
    def batch(self) -> Iterator[None]:
        """Coalesce the queue events of several calls into one model update."""
        self._defer += 1
        try:
            yield
        finally:
            self._defer -= 1
            if self._defer == 0 and self._pending:
                kinds, self._pending = self._pending, set()
                if QueueEventKind.RESET in kinds:
                    self._full_reset()
                else:
                    self._sync(None)

    def _on_queue_event(self, event: QueueEvent) -> None:
        if self._defer:
            self._pending.add(event.kind)
            return
        if event.kind is QueueEventKind.RESET:
            self._full_reset()
        else:
            self._sync(event)

    def refresh(self) -> None:
        """Re-read the queue (normally automatic)."""
        self._sync(None)

    def _reindex(self) -> None:
        self._rows = {it.id: n for n, it in enumerate(self._items)}

    def _full_reset(self) -> None:
        self.beginResetModel()
        self._items = list(self._queue.items())
        self._reindex()
        self.endResetModel()
        self.itemsChanged.emit()

    def _emit_all_changed(self) -> None:
        if self._items:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self._items) - 1, len(COLUMNS) - 1))

    def _sync(self, event: QueueEvent | None) -> None:
        new_items = list(self._queue.items())
        new_ids = [it.id for it in new_items]
        old_ids = [it.id for it in self._items]
        if new_ids == old_ids:
            self._items = new_items
            if event is not None and event.kind is QueueEventKind.UPDATED and event.ids:
                rows = sorted(self._rows[i] for i in set(event.ids) if i in self._rows)
                for start, end in _blocks(rows):
                    self.dataChanged.emit(self.index(start, 0), self.index(end, len(COLUMNS) - 1))
            else:
                self._emit_all_changed()
            self.itemsChanged.emit()
            return
        by_id = {it.id: it for it in new_items}
        new_set = set(new_ids)
        # 1. removals, bottom-up in contiguous blocks
        gone = [n for n, i in enumerate(old_ids) if i not in new_set]
        for start, end in reversed(list(_blocks(gone))):
            self.beginRemoveRows(QModelIndex(), start, end)
            del self._items[start:end + 1]
            self.endRemoveRows()
        # 2. reorder the remaining rows
        kept_ids = [it.id for it in self._items]
        kept = set(kept_ids)
        order = [i for i in new_ids if i in kept]
        if order != kept_ids:
            self.layoutAboutToBeChanged.emit()
            pos = {cid: n for n, cid in enumerate(order)}
            old = self.persistentIndexList()
            new = [self.index(pos[kept_ids[ix.row()]], ix.column()) if 0 <= ix.row() < len(kept_ids) else QModelIndex()
                   for ix in old]
            self._items = [by_id[i] for i in order]
            self.changePersistentIndexList(old, new)
            self.layoutChanged.emit()
        # 3. insertions in ascending target position
        added = [n for n, i in enumerate(new_ids) if i not in kept]
        for start, end in _blocks(added):
            self.beginInsertRows(QModelIndex(), start, end)
            self._items[start:start] = [by_id[new_ids[n]] for n in range(start, end + 1)]
            self.endInsertRows()
        # 4. fresh objects everywhere (data changes may come with the structural change)
        self._items = new_items
        self._reindex()
        self._emit_all_changed()
        self.itemsChanged.emit()


def _blocks(rows: Sequence[int]) -> Iterator[tuple[int, int]]:
    """Contiguous (start, end) runs of sorted row numbers."""
    start = prev = None
    for r in rows:
        if start is None:
            start = prev = r
        elif r == prev + 1:
            prev = r
        else:
            yield start, prev  # type: ignore[misc]
            start = prev = r
    if start is not None:
        yield start, prev  # type: ignore[misc]


# ============================================================================= proxy


class CodesFilterProxy(QSortFilterProxyModel):
    """Status filter (FILTERS), search text and game filter; keeps the queue order (no sorting)."""

    def __init__(self, parent: object | None = None) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self._filter = "all"
        self._search = ""
        self._game: str | None = None
        self.setDynamicSortFilter(True)

    def set_filter(self, key: str) -> None:
        """One of FILTERS."""
        if key not in FILTERS:
            raise ValueError(f"unknown filter {key!r}")
        if key != self._filter:
            self._change(lambda: setattr(self, "_filter", key))

    def set_search(self, text: str) -> None:
        text = text or ""
        if text != self._search:
            self._change(lambda: setattr(self, "_search", text))

    def set_game(self, game_key: str | None) -> None:
        """Show items of ``game_key`` plus unassigned ("") items; None = all games."""
        if game_key != self._game:
            self._change(lambda: setattr(self, "_game", game_key))

    def filter_key(self) -> str:
        return self._filter

    def search_text(self) -> str:
        return self._search

    def game(self) -> str | None:
        return self._game

    def game_accepts(self, game_key: str) -> bool:
        return self._game is None or game_key in ("", self._game)

    def item_at(self, row: int) -> CodeItem | None:
        """The item at a PROXY row."""
        src = self.sourceModel()
        if src is None or not 0 <= row < self.rowCount():
            return None
        return src.data(self.mapToSource(self.index(row, 0)), ROLE_ITEM)

    def row_of(self, code_id: str) -> int:
        """PROXY row of an item, -1 when absent or filtered out."""
        src = self.sourceModel()
        row = src.row_of(code_id) if isinstance(src, CodesTableModel) else -1
        if row < 0:
            return -1
        return self.mapFromSource(src.index(row, 0)).row()

    def _change(self, apply: Callable[[], None]) -> None:
        self.beginFilterChange()
        apply()
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        src = self.sourceModel()
        item = src.data(src.index(source_row, 0, source_parent), ROLE_ITEM) if src is not None else None
        if item is None:
            return False
        return (self.game_accepts(item.game_key) and filter_accepts(self._filter, item.status)
                and search_accepts(item, self._search))


# ============================================================================= delegates


class CellDelegate(QStyledItemDelegate):
    """Lets the style draw the QSS item background (dividers, opaque selection), then paints the
    content: by default elided secondary text."""

    pad = CELL_PAD

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        opt.icon = QIcon()
        opt.features &= ~QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        opt.state &= ~QStyle.StateFlag.State_HasFocus
        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.paint_content(painter, QRectF(option.rect).adjusted(self.pad, 0, -self.pad, 0), index)
        painter.restore()

    def paint_content(self, painter: QPainter, rect: QRectF, index: QModelIndex) -> None:
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        painter.setFont(theme.font(theme.FS_BODY))
        painter.setPen(theme.color("text_secondary"))
        elided = painter.fontMetrics().elidedText(str(text), Qt.TextElideMode.ElideRight, int(rect.width()))
        painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided)

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        base = super().sizeHint(option, index)
        return QSize(base.width(), theme.ROW_H)


class CheckDelegate(CellDelegate):
    """Painted check box; a click anywhere in the cell toggles CheckStateRole (``on_toggle`` lets
    the page apply it to every selected row)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.on_toggle: Callable[[QModelIndex, bool], None] | None = None

    def paint_content(self, painter: QPainter, rect: QRectF, index: QModelIndex) -> None:
        state = index.data(Qt.ItemDataRole.CheckStateRole)
        if state is None:  # not applicable (e.g. a duplicate in the import preview)
            painter.setFont(theme.font(theme.FS_BODY))
            painter.setPen(theme.color("text_disabled"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "—")
            return
        checked = state in (Qt.CheckState.Checked, Qt.CheckState.Checked.value)
        enabled = bool(index.flags() & Qt.ItemFlag.ItemIsUserCheckable)
        paint_check(painter, rect, checked, enabled)

    def editorEvent(self, event: QEvent, model: Any, option: QStyleOptionViewItem, index: QModelIndex) -> bool:
        if not index.flags() & Qt.ItemFlag.ItemIsUserCheckable:
            return False
        et = event.type()
        if et in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick):
            return event.button() == Qt.MouseButton.LeftButton  # type: ignore[attr-defined]
        if et == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:  # type: ignore[attr-defined]
            state = index.data(Qt.ItemDataRole.CheckStateRole)
            new = state not in (Qt.CheckState.Checked, Qt.CheckState.Checked.value)
            if self.on_toggle is not None:
                self.on_toggle(index, new)
            else:
                model.setData(index, Qt.CheckState.Checked if new else Qt.CheckState.Unchecked,
                              Qt.ItemDataRole.CheckStateRole)
            return True
        return False


class IndexDelegate(CellDelegate):
    def paint_content(self, painter: QPainter, rect: QRectF, index: QModelIndex) -> None:
        painter.setFont(theme.font(theme.FS_SMALL, tnum=True))
        painter.setPen(theme.color("text_muted"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         str(index.data(Qt.ItemDataRole.DisplayRole) or ""))


class CodeEditor(QLineEdit):
    """Inline code editor with live validation: an ``invalid`` property, an error border and the
    localized reason as tooltip while the text does not fit the code format."""

    def __init__(self, parent: QWidget | None, validate: Callable[[str], tuple[str | None, str]] | None) -> None:
        super().__init__(parent)
        self._validate = validate
        self.reason = ""
        self.setFont(theme.font(theme.FS_MONO, mono=True))
        self.textChanged.connect(self._check)

    def _check(self, text: str) -> None:
        reason = ""
        if self._validate is not None and clean_text(text).strip():
            code, reason = self._validate(clean_text(text).strip())
            if code is not None:
                reason = ""
        changed = reason != self.reason
        self.reason = reason
        self.setProperty("invalid", bool(reason))
        self.setToolTip(reason)
        self.setStyleSheet(f"QLineEdit {{ border: 1px solid {theme.css('error')}; border-radius: 6px; }}"
                           if reason else "")
        if changed and self.isVisible():
            if reason:
                QToolTip.showText(self.mapToGlobal(self.rect().bottomLeft()), reason, self)
            else:
                QToolTip.hideText()

    def is_valid(self) -> bool:
        return not self.reason


class CodeDelegate(CellDelegate):
    """Mono code text with flagged characters highlighted; inline editor with live validation."""

    edit_rejected = pyqtSignal(str)  # localized reason

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.validator: Callable[[QModelIndex, str], tuple[str | None, str]] | None = None
        """(index, text) -> (normalised code or None, localized reason)."""

    def paint_content(self, painter: QPainter, rect: QRectF, index: QModelIndex) -> None:
        status = index.data(ROLE_STATUS)
        token = "text_muted" if status in MUTED_STATUSES else "text"
        paint_code(painter, rect, str(index.data(Qt.ItemDataRole.DisplayRole) or ""),
                   index.data(ROLE_FLAGGED) or (), index.data(ROLE_LOOKALIKES) or (), token)

    def createEditor(self, parent: QWidget, option: QStyleOptionViewItem, index: QModelIndex) -> QWidget:
        validate = None
        if self.validator is not None:
            validator = self.validator
            pindex = QPersistentModelIndex(index)

            def validate(text: str) -> tuple[str | None, str]:
                return validator(QModelIndex(pindex), text)

        return CodeEditor(parent, validate)

    def setEditorData(self, editor: QWidget, index: QModelIndex) -> None:
        if isinstance(editor, QLineEdit):
            editor.setText(str(index.data(Qt.ItemDataRole.EditRole) or ""))
            editor.selectAll()

    def setModelData(self, editor: QWidget, model: Any, index: QModelIndex) -> None:
        if not isinstance(editor, CodeEditor):
            return
        text = clean_text(editor.text()).strip()
        if text == str(index.data(Qt.ItemDataRole.EditRole) or ""):
            return
        if self.validator is not None:
            code, reason = self.validator(index, text)
            if code is None:
                self.edit_rejected.emit(reason)
                return
            text = code
        model.setData(index, text, Qt.ItemDataRole.EditRole)

    def updateEditorGeometry(self, editor: QWidget, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        r = option.rect.adjusted(4, 5, -4, -5)
        editor.setGeometry(r)

    def eventFilter(self, obj: Any, event: QEvent) -> bool:
        if (isinstance(obj, CodeEditor) and event.type() == QEvent.Type.KeyPress
                and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)  # type: ignore[attr-defined]
                and not obj.is_valid()):
            QToolTip.showText(obj.mapToGlobal(obj.rect().bottomLeft()), obj.reason, obj)
            return True  # keep the editor open until the code is valid (Esc cancels)
        return super().eventFilter(obj, event)


class SourceDelegate(CellDelegate):
    def paint_content(self, painter: QPainter, rect: QRectF, index: QModelIndex) -> None:
        source = index.data(ROLE_SOURCE)
        if source is not None:
            pm = icons.icon_pixmap(source.icon, "text_muted", 16)
            painter.drawPixmap(QPointF(rect.left(), rect.center().y() - 8), pm)
        painter.setFont(theme.font(theme.FS_BODY))
        painter.setPen(theme.color("text_secondary"))
        r = rect.adjusted(24, 0, 0, 0)
        text = painter.fontMetrics().elidedText(str(index.data(Qt.ItemDataRole.DisplayRole) or ""),
                                                Qt.TextElideMode.ElideRight, int(r.width()))
        painter.drawText(r, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)


class ConfidenceDelegate(CellDelegate):
    """4 px rounded bar + percentage (success >= 0.95 > warning >= 0.8 > error)."""

    def paint_content(self, painter: QPainter, rect: QRectF, index: QModelIndex) -> None:
        paint_confidence(painter, rect, index.data(ROLE_CONFIDENCE))


class StatusDelegate(CellDelegate):
    """widgets.paint_status_chip for the row status."""

    def paint_content(self, painter: QPainter, rect: QRectF, index: QModelIndex) -> None:
        status = index.data(ROLE_STATUS)
        if isinstance(status, CodeStatus):
            widgets.paint_status_chip(painter, rect, status)


class MoreDelegate(CellDelegate):
    """The "⋯" row-menu button (the page opens the menu on click)."""

    pad = 0

    def paint_content(self, painter: QPainter, rect: QRectF, index: QModelIndex) -> None:
        pm = icons.icon_pixmap("more", "text_muted", 18)
        painter.drawPixmap(QPointF(rect.center().x() - 9, rect.center().y() - 9), pm)
