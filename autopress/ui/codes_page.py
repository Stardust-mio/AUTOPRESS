# OWNED BY G6 - replace this stub
"""Codes page (SPEC section 6.4.1; mock-up docs/research/ux/codes_dark.png): import toolbar
(貼上文字 Ctrl+V, 開啟檔案 Ctrl+O, 圖片辨識 + drag-and-drop, 剪貼簿圖片, 框選螢幕), active
profile + code format, game filter (active profile's game + unassigned; 「所有遊戲」), search,
status filter, the queue table, banners (no profile; unassigned codes; review), bulk actions,
empty state; switch 略過已兌換過的序號 (Settings.skip_history_on_import); bulk 移除 / 標記為已兌換
(SUCCESS + a history record) / 略過 / 確認無誤 and 重設為待兌換 (queue.reset) / 指定給目前遊戲
(queue.assign_game); buttons 試跑 1 筆 and 開始兌換 run through a page-owned ui.run_flow.RunFlow
that is created LAZILY on first click - while G7's RunFlow (or overlays.pick) still raises
NotImplementedError the click shows a 「尚未實作」 toast, so CodesPage(ctx) always builds (T11).
Disabled buttons say why (tooltip + inline hint). During a run the items of the active plan are
read-only (edit / remove / move disabled, 「執行中，請先停止」)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PyQt6.QtWidgets import QWidget

from ..context import AppContext
from ..models import CodeSource

__stub__ = True


class CodesPage(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        raise NotImplementedError

    def import_text(self, text: str, source: CodeSource = CodeSource.PASTE, detail: str = "") -> None:
        """Open the PasteDialog pre-filled with ``text`` (extraction preview, then add)."""
        raise NotImplementedError

    def import_file(self, path: Path) -> None:
        """codes.fileimport.read_code_file, then import_text(..., CodeSource.FILE, file name).
        Errors -> toast with the localized CodeFileError message."""
        raise NotImplementedError

    def import_image(self, image: np.ndarray, source: CodeSource = CodeSource.IMAGE, detail: str = "") -> None:
        """Open the OcrReviewDialog for a BGR/BGRA image, then add the accepted candidates."""
        raise NotImplementedError
