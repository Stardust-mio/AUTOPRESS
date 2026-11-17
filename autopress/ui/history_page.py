# OWNED BY G6 - replace this stub
"""History page (SPEC section 6.4.4): table of attempts (時間, 序號, 遊戲, 設定檔, 結果 chip,
訊息, 證據 thumbnail -> image viewer), search, status and game filters, 重新加入佇列 (as items of
the record's game_key / game), 移除所選, 清除全部 (confirm), 匯出 CSV; empty state."""

from __future__ import annotations

from PyQt6.QtWidgets import QWidget

from ..context import AppContext

__stub__ = True


class HistoryPage(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        raise NotImplementedError
