# OWNED BY G6 - replace this stub
"""Paste / file import dialog: text area (pre-filled), code-format combo (auto-detected with
codes.presets.detect_format, user can override), live candidate list (checkbox, code, badges
重複 / 已兌換過 / 不像序號 / 已修正字元, raw text next to the code when normalisation changed it),
summary "將加入 N 筆，略過 M 筆", 加入 / 取消. The live extraction is debounced (300 ms after
the last edit, T35); without an active profile the codes are added unassigned (game "")."""

from __future__ import annotations

from PyQt6.QtWidgets import QDialog, QWidget

from ..context import AppContext
from ..models import CodeCandidate, CodeFormat, CodeSource

__stub__ = True


class PasteDialog(QDialog):
    def __init__(self, ctx: AppContext, text: str = "", source: CodeSource = CodeSource.PASTE,
                 detail: str = "", parent: QWidget | None = None) -> None:
        raise NotImplementedError

    def candidates(self) -> list[CodeCandidate]:
        """The checked candidates (valid after exec() returned Accepted)."""
        raise NotImplementedError

    def code_format(self) -> CodeFormat:
        raise NotImplementedError
