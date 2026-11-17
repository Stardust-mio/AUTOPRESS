# OWNED BY G6 - replace this stub
"""Qt model, filter proxy and delegates for the code queue table.

Columns (COLUMNS): check, #, 序號 (mono; ``flagged`` characters highlighted with warning_soft
and underlined, ``lookalikes`` with a dotted underline only), 來源 (icon + label), 辨識信心
(bar only for OCR sources), 狀態 (status chip via widgets.paint_status_chip), 訊息 (elided),
⋯ (row menu). Rows 42 px, no grid. The model observes CodeQueue.subscribe and maps QueueEvents
to fine-grained model signals.
"""

from __future__ import annotations

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PyQt6.QtWidgets import QStyledItemDelegate

from ..models import CodeItem

__stub__ = True

COL_CHECK, COL_INDEX, COL_CODE, COL_SOURCE, COL_CONF, COL_STATUS, COL_MESSAGE, COL_MORE = range(8)
COLUMNS: tuple[str, ...] = ("check", "index", "code", "source", "confidence", "status", "message", "more")

ROLE_ITEM = Qt.ItemDataRole.UserRole + 1  # the CodeItem of the row
ROLE_FLAGGED = Qt.ItemDataRole.UserRole + 2  # list[int]
ROLE_STATUS = Qt.ItemDataRole.UserRole + 3  # CodeStatus
ROLE_LOOKALIKES = Qt.ItemDataRole.UserRole + 4  # list[int]
ROLE_GAME = Qt.ItemDataRole.UserRole + 5  # game_key str

FILTERS: tuple[str, ...] = ("all", "pending", "review", "done", "failed", "skipped")
"""Status filter keys (segments 全部 / 待兌換 / 需確認 / 已完成 / 失敗 / 已略過): all; pending (PENDING,
COOLDOWN, RUNNING); review (REVIEW); done (SUCCESS, SUBMITTED, USED); failed (FAILED, INVALID, EXPIRED);
skipped (SKIPPED)."""


class CodesTableModel(QAbstractTableModel):
    def __init__(self, queue: object, parent: object | None = None) -> None:
        """``queue`` is a codes.queue.CodeQueue (or a test fake with the same API)."""
        raise NotImplementedError

    def item_at(self, row: int) -> CodeItem | None:
        raise NotImplementedError

    def row_of(self, code_id: str) -> int:
        raise NotImplementedError

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        raise NotImplementedError

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        raise NotImplementedError


class CodesFilterProxy(QSortFilterProxyModel):
    def set_filter(self, key: str) -> None:
        """One of FILTERS."""
        raise NotImplementedError

    def set_search(self, text: str) -> None:
        raise NotImplementedError

    def set_game(self, game_key: str | None) -> None:
        """Show items of ``game_key`` plus unassigned ("") items; None = all games."""
        raise NotImplementedError


class CodeDelegate(QStyledItemDelegate):
    """Mono code text with flagged characters highlighted; inline editor with live validation."""


class ConfidenceDelegate(QStyledItemDelegate):
    """4 px rounded bar + percentage (success >= 0.95 > warning >= 0.8 > error)."""


class StatusDelegate(QStyledItemDelegate):
    """widgets.paint_status_chip for the row status."""
