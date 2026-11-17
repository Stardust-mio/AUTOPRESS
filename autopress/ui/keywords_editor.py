# OWNED BY G7 - replace this stub
"""Result keyword editor: one row per ResultClass in KeywordConfig.order (label, chips or a
comma-separated field, move up/down to change the order), fuzzy switch, "還原預設" (models.
default_keyword_groups), overlap warnings (KeywordConfig.overlaps)."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget

from ..models import KeywordConfig, ResultClass

__stub__ = True


class KeywordsEditor(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        raise NotImplementedError

    def set_config(self, config: KeywordConfig) -> None:
        raise NotImplementedError

    def config(self) -> KeywordConfig:
        raise NotImplementedError

    def add_keyword(self, result: ResultClass, keyword: str) -> None:
        """Used by the Run page's "加入關鍵字…" action."""
        raise NotImplementedError
