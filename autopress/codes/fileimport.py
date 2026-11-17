# OWNED BY G1
"""Read code lists from files (the text is then passed to extract.extract_from_text).

* Encoding: UTF-8 / UTF-16 / UTF-32 with a BOM; UTF-16 without a BOM when about half of the
  bytes are NUL (Windows tools write such files); else strict UTF-8, else cp950 (Big5), else
  UTF-8 with replacement characters. Line breaks become LF; control characters are dropped.
* .csv / .tsv: every cell on its own line. When the first non-empty row has a code column header
  (code, codes, key, serial, coupon, gift code, 序號, 兌換碼, コード ...), only that column is
  read, so re-importing an AutoPress CSV export does not offer its timestamps, statuses and
  messages as codes. A file the csv module cannot parse is read as plain text.
* .json: a list of strings (numbers are accepted), or of objects with a "code" key, or
  {"codes": [...]} (also {"items": [...]}, the queue.json layout).
* Every other extension (.txt, .log, unknown) is read as text.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ..i18n import tr
from ..textutil import clean_text, squash

log = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS: tuple[str, ...] = (".txt", ".csv", ".tsv", ".json", ".log")

_CODE_HEADERS = frozenset(squash(h) for h in (
    "code", "codes", "key", "keys", "serial", "serials", "serial code", "coupon", "coupons", "coupon code",
    "gift code", "redeem code", "redemption code", "promo code", "cd key", "cdkey", "product key",
    "序號", "序号", "兌換碼", "兑换码", "禮包碼", "礼包码", "禮物碼", "虛寶碼", "激活碼", "激活码",
    "コード", "シリアル", "シリアルコード", "クーポン", "ギフトコード",
))


class CodeFileError(Exception):
    """The file cannot be used; ``str(exc)`` is a localized message for the user."""


def _size_text(n: int) -> str:
    return f"{n / 1_000_000:.1f} MB" if n >= 100_000 else f"{max(1, round(n / 1000))} KB"


def _utf16_guess(data: bytes) -> str | None:
    """UTF-16 without BOM: NUL bytes in about every second position (ASCII-heavy text)."""
    if len(data) < 4 or len(data) % 2:
        return None
    half = len(data) // 2
    even, odd = data[0::2].count(0), data[1::2].count(0)
    if odd >= 0.4 * half and even <= 0.05 * half:
        return "utf-16-le"
    if even >= 0.4 * half and odd <= 0.05 * half:
        return "utf-16-be"
    return None


def decode_bytes(data: bytes) -> str:
    """Text of a code file's bytes (encoding rules: module docstring), LF line breaks, no
    control characters except tab."""
    text: str | None = None
    if data.startswith(b"\xef\xbb\xbf"):
        text = data[3:].decode("utf-8", errors="replace")
    elif data.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        text = data.decode("utf-32", errors="replace")
    elif data.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = data.decode("utf-16", errors="replace")
    else:
        guess = _utf16_guess(data)
        candidates = ([guess] if guess else []) + ["utf-8", "cp950"]
        for enc in candidates:
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            text = data.decode("utf-8", errors="replace")
    return clean_text(text.replace("\r\n", "\n").replace("\r", "\n"))


def _cells_text(text: str, delimiter: str) -> str:
    try:
        rows = [[cell.strip() for cell in row] for row in csv.reader(io.StringIO(text), delimiter=delimiter)]
    except csv.Error as exc:
        log.warning("CSV parse failed (%s); reading the file as plain text", exc)
        return text
    first = next((n for n, row in enumerate(rows) if any(row)), None)
    if first is not None:
        col = next((n for n, cell in enumerate(rows[first]) if cell and squash(cell) in _CODE_HEADERS), None)
        if col is not None:
            return "\n".join(row[col] for row in rows[first + 1:] if len(row) > col and row[col])
    return "\n".join(cell for row in rows for cell in row if cell)


def _key(obj: dict[str, Any], name: str) -> Any:
    if name in obj:
        return obj[name]
    for k, v in obj.items():
        if isinstance(k, str) and k.strip().lower() == name:
            return v
    return None


def _as_code(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return None


def _from_items(items: Iterable[Any], out: list[str]) -> None:
    for item in items:
        code = _as_code(_key(item, "code")) if isinstance(item, dict) else _as_code(item)
        if code:
            out.append(code)


def _json_text(text: str, name: str) -> str:
    try:
        data = json.loads(text)
    except (ValueError, RecursionError) as exc:
        raise CodeFileError(tr(f"無法解析 JSON 檔案：{name}", f"The JSON file could not be read: {name}")) from exc
    codes: list[str] = []
    if isinstance(data, list):
        _from_items(data, codes)
    elif isinstance(data, dict):
        for name_key in ("codes", "items"):
            lst = _key(data, name_key)
            if isinstance(lst, list):
                _from_items(lst, codes)
                break
        else:
            single = _as_code(_key(data, "code"))
            if single:
                codes.append(single)
    if not codes:
        raise CodeFileError(tr(f"JSON 檔案裡沒有序號：{name}", f"No codes in the JSON file: {name}"))
    return "\n".join(codes)


def read_code_file(path: Path, max_bytes: int = 5_000_000) -> str:
    """Text of a code file.

    Encoding: BOM-detected UTF-8 / UTF-16, else UTF-8, else cp950 (Big5), else UTF-8 with
    replacement. .csv/.tsv: every cell, one per line. .json: a list of strings, or of objects
    with a "code" key, or {"codes": [...]}. Other extensions are read as text.
    Raises CodeFileError for missing/unreadable files, files over ``max_bytes`` and JSON
    without codes. Details (code column of CSV files, UTF-16 without BOM): module docstring."""
    p = Path(path)
    name = p.name or str(p)
    try:
        if p.is_dir():
            raise CodeFileError(tr(f"這是資料夾，不是檔案：{name}", f"This is a folder, not a file: {name}"))
        if not p.is_file():
            raise CodeFileError(tr(f"找不到檔案：{name}", f"File not found: {name}"))
        size = p.stat().st_size
        if size > max_bytes:
            raise CodeFileError(tr(f"檔案太大：{name}（{_size_text(size)}，上限 {_size_text(max_bytes)}）",
                                   f"The file is too large: {name} ({_size_text(size)}, limit {_size_text(max_bytes)})"))
        with p.open("rb") as fh:
            data = fh.read(max_bytes + 1)
    except CodeFileError:
        raise
    except OSError as exc:
        reason = exc.strerror or str(exc)
        raise CodeFileError(tr(f"無法讀取檔案：{name}（{reason}）", f"Cannot read the file: {name} ({reason})")) from exc
    if len(data) > max_bytes:
        raise CodeFileError(tr(f"檔案太大：{name}（上限 {_size_text(max_bytes)}）",
                               f"The file is too large: {name} (limit {_size_text(max_bytes)})"))
    text = decode_bytes(data)
    ext = p.suffix.lower()
    if ext in (".csv", ".tsv"):
        return _cells_text(text, "\t" if ext == ".tsv" else ",")
    if ext == ".json":
        return _json_text(text, name)
    return text


def file_dialog_filter() -> str:
    """QFileDialog filter, e.g. "序號清單 (*.txt *.csv *.tsv *.json *.log);;所有檔案 (*)"."""
    patterns = " ".join(f"*{ext}" for ext in SUPPORTED_EXTENSIONS)
    return tr(f"序號清單 ({patterns});;所有檔案 (*)", f"Code lists ({patterns});;All files (*)")
