# OWNED BY G1 - replace this stub
"""The code queue: ordered CodeItems, persisted to queue.json, observable (pure Python).

Single writer: the GUI thread (pages and runner.engine.RunSession). Every mutating call
saves the file (when autosave) and then notifies subscribers synchronously.
File: {"schema_version": 1, "items": [CodeItem dicts]} via storage.write_json / read_json.

Every item belongs to ONE game (``CodeItem.game_key`` = Profile.game_key() of the active profile
at import, "" = not assigned yet): duplicates are detected per game, runs only take the codes of
the profile's game, and unassigned codes never run until assigned (SPEC 5.7, decision PX-02).
Persisted messages written here use tr() with both languages (e.g. the crash-recovery note).
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..models import (
    AddResult,
    CodeCandidate,
    CodeFormat,
    CodeItem,
    CodeSource,
    CodeStatus,
    QueueEvent,
    RunSelection,
)

__stub__ = True

if TYPE_CHECKING:
    from .history import HistoryStore


class CodeQueue:
    def __init__(self, path: Path | None = None, *, autosave: bool = True) -> None:
        """``path`` None -> paths.queue_path(). Nothing is read until load()."""
        raise NotImplementedError

    def load(self) -> None:
        """Read the file (missing/broken -> empty queue); notify RESET."""
        raise NotImplementedError

    def save(self) -> None:
        raise NotImplementedError

    def items(self) -> list[CodeItem]:
        """The items in queue order (a new list; do not mutate the items - use update())."""
        raise NotImplementedError

    def __len__(self) -> int:
        raise NotImplementedError

    def get(self, code_id: str) -> CodeItem | None:
        raise NotImplementedError

    def index_of(self, code_id: str) -> int:
        """Position of the item, -1 if absent."""
        raise NotImplementedError

    def find_code(self, code: str, game_key: str | None = None) -> CodeItem | None:
        """Item whose models.code_key equals code_key(code) - of game ``game_key`` when given
        (None = any game)."""
        raise NotImplementedError

    def add_candidates(self, candidates: Sequence[CodeCandidate], source: CodeSource, *,
                       source_detail: str = "", history: HistoryStore | None = None,
                       game_key: str = "", skip_statuses: Collection[CodeStatus] = (),
                       game: str = "") -> AddResult:
        """Append candidates as items of game ``game_key`` / ``game`` (copied into the items;
        "" = unassigned): PENDING, or REVIEW when ``flagged`` is non-empty (``lookalikes`` are
        copied, they do not cause REVIEW). Duplicates = same code_key AND same game_key
        (counted in ``duplicates``; the same code may be queued for two games). With
        ``history`` and a non-empty ``game_key``, codes whose latest history status for that
        game is in ``skip_statuses`` are not added (``skipped_history``). Notifies ADDED."""
        raise NotImplementedError

    def add_codes(self, codes: Sequence[str], source: CodeSource = CodeSource.MANUAL, *,
                  fmt: CodeFormat | None = None, **kwargs: Any) -> AddResult:
        """Convenience: normalise ``codes`` with ``fmt`` (invalid ones counted in ``invalid``;
        fmt None = take them as given) and call add_candidates with the same kwargs."""
        raise NotImplementedError

    def update(self, code_id: str, **changes: Any) -> CodeItem:
        """Set CodeItem fields (``updated_at`` refreshed). KeyError if absent. Editing ``code``
        clears ``flagged`` and turns REVIEW into PENDING. Notifies UPDATED."""
        raise NotImplementedError

    def set_status(self, code_id: str, status: CodeStatus, message: str | None = None) -> CodeItem:
        raise NotImplementedError

    def remove(self, code_ids: Iterable[str]) -> int:
        raise NotImplementedError

    def clear(self, statuses: Collection[CodeStatus] | None = None) -> int:
        """Remove all items, or only those with a status in ``statuses``. Returns the count."""
        raise NotImplementedError

    def move(self, code_ids: Sequence[str], delta: int) -> None:
        """Move the items up (delta < 0) or down, keeping their relative order. Notifies MOVED."""
        raise NotImplementedError

    def move_to(self, code_ids: Sequence[str], index: int) -> None:
        raise NotImplementedError

    def set_checked(self, code_ids: Iterable[str], checked: bool) -> None:
        raise NotImplementedError

    def runnable(self, selection: RunSelection = RunSelection.UNFINISHED,
                 game_key: str | None = None) -> list[CodeItem]:
        """Items a run would process, in order: status.is_runnable (and ``checked`` for CHECKED),
        restricted to items whose game_key equals ``game_key`` when given (runs pass
        profile.game_key(); unassigned items never match a profile)."""
        raise NotImplementedError

    def retry_failed(self) -> int:
        """FAILED items -> PENDING (message cleared). REVIEW items are NOT touched: they may have
        been redeemed already and need the user's decision (``reset``). Returns the count."""
        raise NotImplementedError

    def reset(self, code_ids: Iterable[str]) -> int:
        """Selected items -> PENDING with ``flagged`` and ``message`` cleared (RUNNING items are
        skipped). Backs 「確認無誤」 (REVIEW -> PENDING) and 「重設為待兌換」 (any final status,
        e.g. INVALID caused by a typing problem). Notifies UPDATED. Returns the count."""
        raise NotImplementedError

    def assign_game(self, code_ids: Iterable[str], game_key: str, game: str = "") -> int:
        """Move items to another game (「指定給…」 for unassigned codes; the Profiles page also
        calls it when a profile's game name changes). An item whose code already exists in the
        target game is removed as a duplicate. Notifies UPDATED / REMOVED. Returns the count moved."""
        raise NotImplementedError

    def games(self) -> list[tuple[str, str]]:
        """Distinct (game_key, game) pairs of the queued items in queue order ("" = unassigned)."""
        raise NotImplementedError

    def recover_after_crash(self) -> int:
        """At startup: RUNNING -> REVIEW (tr("上次執行中斷，請確認是否已兌換", "The last run was
        interrupted; check whether this code was redeemed")), COOLDOWN -> PENDING."""
        raise NotImplementedError

    def counts(self) -> dict[CodeStatus, int]:
        """Count per status (every CodeStatus present, zeros included)."""
        raise NotImplementedError

    def subscribe(self, callback: Callable[[QueueEvent], None]) -> Callable[[], None]:
        """Call ``callback(event)`` after every change. Returns an unsubscribe function."""
        raise NotImplementedError
