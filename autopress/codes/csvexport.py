# OWNED BY G1 - replace this stub
"""CSV export for Excel: UTF-8 with BOM, CRLF rows, localized header row, written atomically
with storage.write_bytes_atomic. Formula injection (OWASP): every cell that starts with "=", "+",
"-", "@", a tab or a carriage return gets a leading apostrophe (messages come from OCR of
arbitrary pages)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from ..models import AttemptRecord, CodeItem

__stub__ = True


def export_codes_csv(path: Path, items: Sequence[CodeItem]) -> None:
    """Columns: #, 序號/Code, 狀態/Status (label), 訊息/Message, 來源/Source (label),
    辨識信心/Confidence (0-100 or empty), 加入時間/Added. Raises storage.StorageError."""
    raise NotImplementedError


def export_history_csv(path: Path, records: Sequence[AttemptRecord]) -> None:
    """Columns: 時間/Time (finished_at), 序號/Code, 遊戲/Game, 設定檔/Profile, 結果/Status (label),
    訊息/Message, 耗時(ms)/Duration (ms). Raises storage.StorageError."""
    raise NotImplementedError
