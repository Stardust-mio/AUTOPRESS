# OWNED BY G1 - replace this stub
"""Attempt history: append-only history.jsonl (one AttemptRecord per line, "schema_version"
on every line), in-memory index by (game_key, code_key). Pure Python, GUI thread only.
Corrupt lines are skipped (logged). remove()/clear() rewrite the file atomically.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable
from pathlib import Path

from ..models import AttemptRecord, CodeStatus

__stub__ = True


class HistoryStore:
    def __init__(self, path: Path | None = None) -> None:
        """``path`` None -> paths.history_path(). Nothing is read until load()."""
        raise NotImplementedError

    def load(self) -> None:
        raise NotImplementedError

    def append(self, record: AttemptRecord) -> None:
        """Append one line (flush) and notify subscribers."""
        raise NotImplementedError

    def update(self, record_id: str, **changes: object) -> AttemptRecord:
        """Change fields of one record IN PLACE (same id, same position, so ``latest`` keeps its
        meaning) and rewrite the file atomically; notifies subscribers. KeyError if absent.
        Used by RunSession.resolve_attention (status / result / message of an unknown result)."""
        raise NotImplementedError

    def records(self) -> list[AttemptRecord]:
        """All records, oldest first (a new list)."""
        raise NotImplementedError

    def latest(self, game_key: str, code: str) -> AttemptRecord | None:
        """Most recent record for this game and code (compared by models.code_key)."""
        raise NotImplementedError

    def is_done(self, game_key: str, code: str, statuses: Collection[CodeStatus]) -> bool:
        """True if latest(game_key, code).status is in ``statuses``."""
        raise NotImplementedError

    def query(self, text: str = "", statuses: Collection[CodeStatus] | None = None,
              game_key: str | None = None) -> list[AttemptRecord]:
        """Newest first; ``text`` matches code, message, game or profile name (case-insensitive)."""
        raise NotImplementedError

    def games(self) -> list[tuple[str, str]]:
        """Distinct (game_key, game display name) pairs, newest game first."""
        raise NotImplementedError

    def remove(self, record_ids: Iterable[str]) -> int:
        raise NotImplementedError

    def clear(self) -> int:
        raise NotImplementedError

    def prune_evidence(self, keep_days: int) -> int:
        """Delete evidence PNGs older than ``keep_days`` (0 = keep all) and blank the paths of
        records that pointed to them. Returns the number of files deleted."""
        raise NotImplementedError

    def subscribe(self, callback: Callable[[], None]) -> Callable[[], None]:
        raise NotImplementedError
