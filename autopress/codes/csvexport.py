# OWNED BY G1
"""CSV export for Excel: UTF-8 with BOM, CRLF rows, localized header row, written atomically
with storage.write_bytes_atomic. Formula injection (OWASP): every cell that starts with "=", "+",
"-", "@", a tab or a carriage return gets a leading apostrophe (messages come from OCR of
arbitrary pages). Times are written as "yyyy-mm-dd HH:MM:SS" local time (Excel reads that as a
date; the stored ISO text is kept when it cannot be parsed)."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path

from .. import storage
from ..i18n import tr
from ..models import AttemptRecord, CodeItem

_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value: object) -> str:
    """Text of one cell with the formula-injection guard applied."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_FORMULA_START) else text


def _time_text(stamp: str) -> str:
    if not stamp:
        return ""
    try:
        dt = datetime.fromisoformat(stamp)
    except ValueError:
        return stamp
    return (dt.astimezone() if dt.tzinfo else dt).strftime("%Y-%m-%d %H:%M:%S")


def _write(path: Path, header: Sequence[str], rows: Iterable[Sequence[object]]) -> None:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow([safe_cell(h) for h in header])
    for row in rows:
        writer.writerow([safe_cell(v) for v in row])
    storage.write_bytes_atomic(Path(path), ("\ufeff" + buf.getvalue()).encode("utf-8", errors="replace"))


def export_codes_csv(path: Path, items: Sequence[CodeItem]) -> None:
    """Columns: #, 序號/Code, 狀態/Status (label), 訊息/Message, 來源/Source (label),
    辨識信心/Confidence (0-100 or empty), 加入時間/Added. Raises storage.StorageError."""
    header = ["#", tr("序號", "Code"), tr("狀態", "Status"), tr("訊息", "Message"), tr("來源", "Source"),
              tr("辨識信心", "Confidence"), tr("加入時間", "Added")]
    rows = ([n, item.code, item.status.label(), item.message, item.source.label(),
             "" if item.confidence is None else round(item.confidence * 100), _time_text(item.added_at)]
            for n, item in enumerate(items, 1))
    _write(path, header, rows)


def export_history_csv(path: Path, records: Sequence[AttemptRecord]) -> None:
    """Columns: 時間/Time (finished_at), 序號/Code, 遊戲/Game, 設定檔/Profile, 結果/Status (label),
    訊息/Message, 耗時(ms)/Duration (ms). Raises storage.StorageError. A record without
    finished_at shows its started_at."""
    header = [tr("時間", "Time"), tr("序號", "Code"), tr("遊戲", "Game"), tr("設定檔", "Profile"),
              tr("結果", "Status"), tr("訊息", "Message"), tr("耗時(ms)", "Duration (ms)")]
    rows = ([_time_text(r.finished_at or r.started_at), r.code, r.game, r.profile_name, r.status.label(),
             r.message, r.duration_ms] for r in records)
    _write(path, header, rows)
