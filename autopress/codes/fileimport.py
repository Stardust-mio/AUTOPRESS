# OWNED BY G1 - replace this stub
"""Read code lists from files (the text is then passed to extract.extract_from_text)."""

from __future__ import annotations

from pathlib import Path

__stub__ = True

SUPPORTED_EXTENSIONS: tuple[str, ...] = (".txt", ".csv", ".tsv", ".json", ".log")


class CodeFileError(Exception):
    """The file cannot be used; ``str(exc)`` is a localized message for the user."""


def read_code_file(path: Path, max_bytes: int = 5_000_000) -> str:
    """Text of a code file.

    Encoding: BOM-detected UTF-8 / UTF-16, else UTF-8, else cp950 (Big5), else UTF-8 with
    replacement. .csv/.tsv: every cell, one per line. .json: a list of strings, or of objects
    with a "code" key, or {"codes": [...]}. Other extensions are read as text.
    Raises CodeFileError for missing/unreadable files, files over ``max_bytes`` and JSON
    without codes."""
    raise NotImplementedError


def file_dialog_filter() -> str:
    """QFileDialog filter, e.g. "序號清單 (*.txt *.csv *.tsv *.json *.log);;所有檔案 (*)"."""
    raise NotImplementedError
