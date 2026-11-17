# OWNED BY G1
"""The code queue: ordered CodeItems, persisted to queue.json, observable (pure Python).

Single writer: the GUI thread (pages and runner.engine.RunSession). Every mutating call
saves the file (when autosave) and then notifies subscribers synchronously.
File: {"schema_version": 1, "items": [CodeItem dicts]} via storage.write_json / read_json.

Every item belongs to ONE game (``CodeItem.game_key`` = Profile.game_key() of the active profile
at import, "" = not assigned yet): duplicates are detected per game, runs only take the codes of
the profile's game, and unassigned codes never run until assigned (SPEC 5.7, decision PX-02).
Persisted messages written here use tr() with both languages (e.g. the crash-recovery note).

Robustness: a failed autosave is logged (``last_error``) and never raises from a mutating call
(the in-memory queue stays usable; an explicit save() raises storage.StorageError). A subscriber
that raises is logged and does not stop the others. A file that cannot be read, or that holds
JSON of the wrong shape, starts an empty queue and is renamed ``queue.json.broken-<ts>`` before
the first write, so it is never overwritten (invalid JSON is quarantined by storage.read_json).
Items loaded from disk are sanitised: empty codes dropped, duplicate ids renewed, index lists
and per-character confidences that do not match the code reset.
"""

from __future__ import annotations

import dataclasses
import logging
import os
from collections.abc import Callable, Collection, Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .. import paths, storage
from ..i18n import tr
from ..models import (
    QUEUE_SCHEMA_VERSION,
    AddResult,
    CodeCandidate,
    CodeFormat,
    CodeItem,
    CodeSource,
    CodeStatus,
    QueueEvent,
    QueueEventKind,
    RunSelection,
    code_key,
    from_dict,
    migrate,
    new_id,
    now_iso,
    to_dict,
)
from ..textutil import clean_text
from .normalize import lookalike_indices, normalize_code

if TYPE_CHECKING:
    from .history import HistoryStore

log = logging.getLogger(__name__)

_FIELDS = frozenset(f.name for f in dataclasses.fields(CodeItem))
_ENUM_FIELDS: dict[str, type] = {"status": CodeStatus, "source": CodeSource}


def _id_list(ids: Iterable[str] | str) -> list[str]:
    """Ids in order without repeats (a single id string is accepted too)."""
    if isinstance(ids, str):
        ids = [ids]
    seen: set[str] = set()
    out: list[str] = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def _statuses(values: Collection[CodeStatus] | Iterable[str]) -> set[CodeStatus]:
    out: set[CodeStatus] = set()
    for v in values:
        try:
            out.add(CodeStatus(v))
        except ValueError:
            log.debug("unknown status %r ignored", v)
    return out


def _indices(values: Iterable[Any], n: int) -> list[int]:
    return sorted({i for i in values if isinstance(i, int) and not isinstance(i, bool) and 0 <= i < n})


class CodeQueue:
    def __init__(self, path: Path | None = None, *, autosave: bool = True) -> None:
        """``path`` None -> paths.queue_path(). Nothing is read until load()."""
        self._path = Path(path) if path is not None else None
        self._autosave = autosave
        self._items: list[CodeItem] = []
        self._by_id: dict[str, CodeItem] = {}
        self._subs: list[Callable[[QueueEvent], None]] = []
        self._move_aside = False
        self.last_error = ""
        """Localized text of the last failed load / autosave ("" after a successful save)."""

    # -- persistence -----------------------------------------------------------------------
    @property
    def path(self) -> Path:
        """The queue file (resolved lazily, so the data folder is not touched before use)."""
        return self._path if self._path is not None else paths.queue_path()

    def load(self) -> None:
        """Read the file (missing/broken -> empty queue); notify RESET."""
        path = self.path
        try:
            data = storage.read_json(path, None)
        except storage.StorageError as exc:
            log.error("cannot read the queue file: %s", exc)
            self.last_error = str(exc)
            self._move_aside = True
            data = None
        items: list[CodeItem] = []
        if isinstance(data, dict):
            raw_items = migrate("queue", data).get("items")
            if isinstance(raw_items, list):
                seen: set[str] = set()
                for entry in raw_items:
                    if not isinstance(entry, dict):
                        continue
                    item = from_dict(CodeItem, entry)
                    item.code = item.code.strip()
                    if not item.code:
                        continue
                    if not item.id or item.id in seen:
                        item.id = new_id()
                    seen.add(item.id)
                    self._sanitize(item)
                    items.append(item)
        elif data is not None:
            log.warning("%s does not hold a queue; starting empty (the file is kept aside)", path)
            self._move_aside = True
        self._items = items
        self._by_id = {i.id: i for i in items}
        self._notify(QueueEventKind.RESET, [])

    @staticmethod
    def _sanitize(item: CodeItem) -> None:
        n = len(item.code)
        item.flagged = _indices(item.flagged, n)
        item.lookalikes = _indices(item.lookalikes, n)
        if item.char_confs and len(item.char_confs) != n:
            item.char_confs = []

    def save(self) -> None:
        """Write queue.json atomically (storage.write_json). Raises storage.StorageError."""
        path = self.path
        if self._move_aside:
            self._move_aside = False
            if path.exists():
                aside = path.with_name(f"{path.name}.broken-{datetime.now():%Y%m%d-%H%M%S}")
                try:
                    os.replace(path, aside)
                    log.warning("kept the unreadable queue file as %s", aside.name)
                except OSError as exc:
                    log.error("could not move %s aside: %s", path, exc)
        storage.write_json(path, {"schema_version": QUEUE_SCHEMA_VERSION, "items": [to_dict(i) for i in self._items]})
        self.last_error = ""

    def _store(self) -> None:
        if not self._autosave:
            return
        try:
            self.save()
        except storage.StorageError as exc:
            log.error("saving the queue failed: %s", exc)
            self.last_error = str(exc)

    def _notify(self, kind: QueueEventKind, ids: Sequence[str]) -> None:
        for cb in list(self._subs):
            try:
                cb(QueueEvent(kind, list(ids)))
            except Exception:  # noqa: BLE001 - one broken view must not break the bookkeeping
                log.exception("queue subscriber failed")

    def _commit(self, kind: QueueEventKind, ids: Sequence[str]) -> None:
        self._store()
        self._notify(kind, ids)

    # -- reading ---------------------------------------------------------------------------
    def items(self) -> list[CodeItem]:
        """The items in queue order (a new list; do not mutate the items - use update())."""
        return list(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def get(self, code_id: str) -> CodeItem | None:
        return self._by_id.get(code_id)

    def index_of(self, code_id: str) -> int:
        """Position of the item, -1 if absent."""
        item = self._by_id.get(code_id)
        if item is None:
            return -1
        return next(n for n, i in enumerate(self._items) if i is item)

    def find_code(self, code: str, game_key: str | None = None) -> CodeItem | None:
        """Item whose models.code_key equals code_key(code) - of game ``game_key`` when given
        (None = any game)."""
        key = code_key(code or "")
        return next((i for i in self._items
                     if code_key(i.code) == key and (game_key is None or i.game_key == game_key)), None)

    def annotate(self, candidates: Sequence[CodeCandidate], *, history: HistoryStore | None = None,
                 game_key: str = "") -> list[CodeCandidate]:
        """Fill ``duplicate_of`` (queue item of the same game) and ``history_status`` (latest
        history status for ``game_key``) of preview candidates IN PLACE; returns them as a list.
        For the 重複 / 已兌換過 badges and the import summary of the paste and OCR dialogs."""
        first: dict[str, str] = {}
        for i in self._items:
            if i.game_key == game_key:
                first.setdefault(code_key(i.code), i.id)
        for c in candidates:
            c.duplicate_of = first.get(code_key(c.code), "")
            rec = history.latest(game_key, c.code) if history is not None and game_key else None
            c.history_status = rec.status if rec is not None else None
        return list(candidates)

    # -- adding ----------------------------------------------------------------------------
    def add_candidates(self, candidates: Sequence[CodeCandidate], source: CodeSource, *,
                       source_detail: str = "", history: HistoryStore | None = None,
                       game_key: str = "", skip_statuses: Collection[CodeStatus] = (),
                       game: str = "") -> AddResult:
        """Append candidates as items of game ``game_key`` / ``game`` (copied into the items;
        "" = unassigned): PENDING, or REVIEW when ``flagged`` is non-empty (``lookalikes`` are
        copied, they do not cause REVIEW). Duplicates = same code_key AND same game_key
        (counted in ``duplicates``; the same code may be queued for two games). With
        ``history`` and a non-empty ``game_key``, codes whose latest history status for that
        game is in ``skip_statuses`` are not added (``skipped_history``). Notifies ADDED.
        Candidates with an empty code are counted in ``invalid``; ``char_confs`` are kept only
        when they match the code's length; indices outside the code are dropped."""
        source = CodeSource(source)
        skip = _statuses(skip_statuses) if skip_statuses else set()
        game = game if game_key else ""
        keys = {(i.game_key, code_key(i.code)) for i in self._items}
        res = AddResult()
        for cand in candidates:
            code = clean_text(cand.code or "").strip()
            if not code:
                res.invalid += 1
                continue
            key = (game_key, code_key(code))
            if key in keys:
                res.duplicates += 1
                continue
            if history is not None and game_key and skip and history.is_done(game_key, code, skip):
                res.skipped_history += 1
                continue
            n = len(code)
            flagged = _indices(cand.flagged, n)
            confs = [float(c) for c in cand.char_confs] if cand.char_confs and len(cand.char_confs) == n else []
            item = CodeItem(code=code, raw=cand.raw, game_key=game_key, game=game, source=source,
                            source_detail=source_detail, confidence=cand.confidence, char_confs=confs,
                            flagged=flagged, lookalikes=_indices(cand.lookalikes, n),
                            status=CodeStatus.REVIEW if flagged else CodeStatus.PENDING)
            self._items.append(item)
            self._by_id[item.id] = item
            keys.add(key)
            res.added.append(item.id)
        if res.added:
            self._commit(QueueEventKind.ADDED, res.added)
        return res

    def add_codes(self, codes: Sequence[str], source: CodeSource = CodeSource.MANUAL, *,
                  fmt: CodeFormat | None = None, **kwargs: Any) -> AddResult:
        """Convenience: normalise ``codes`` with ``fmt`` (invalid ones counted in ``invalid``;
        fmt None = take them as given) and call add_candidates with the same kwargs.
        Repaired characters are flagged (REVIEW) as for extraction."""
        if isinstance(codes, str):
            codes = [codes]
        cands: list[CodeCandidate] = []
        invalid = 0
        for raw in codes:
            text = str(raw)
            if fmt is None:
                code = clean_text(text).strip()
                if not code:
                    invalid += 1
                    continue
                cands.append(CodeCandidate(code=code, raw=text))
                continue
            fitted, repaired = normalize_code(text, fmt)
            if fitted is None:
                invalid += 1
                continue
            cands.append(CodeCandidate(code=fitted, raw=text, flagged=list(repaired),
                                       lookalikes=lookalike_indices(fitted, fmt), repaired=list(repaired)))
        res = self.add_candidates(cands, source, **kwargs)
        res.invalid += invalid
        return res

    # -- changing --------------------------------------------------------------------------
    def update(self, code_id: str, **changes: Any) -> CodeItem:
        """Set CodeItem fields (``updated_at`` refreshed). KeyError if absent. Editing ``code``
        clears ``flagged`` and turns REVIEW into PENDING. Notifies UPDATED.
        Unknown fields raise AttributeError and the id cannot change (ValueError); status /
        source strings are converted to their enums. Editing ``code`` also clears
        ``lookalikes`` and ``char_confs`` unless they are passed too (they would point at the
        wrong characters)."""
        item = self._by_id.get(code_id)
        if item is None:
            raise KeyError(code_id)
        for name in changes:
            if name not in _FIELDS:
                raise AttributeError(name)
        if "id" in changes and changes["id"] != item.id:
            raise ValueError("the id of a queue item cannot change")
        for name, value in changes.items():
            enum_type = _ENUM_FIELDS.get(name)
            if enum_type is not None and not isinstance(value, enum_type):
                value = enum_type(value)
            elif name == "code":
                value = clean_text(str(value)).strip()
            elif isinstance(value, list):
                value = list(value)
            setattr(item, name, value)
        if "code" in changes:
            item.flagged = []
            if "lookalikes" not in changes:
                item.lookalikes = []
            if "char_confs" not in changes:
                item.char_confs = []
            if item.status is CodeStatus.REVIEW:
                item.status = CodeStatus.PENDING
        item.updated_at = now_iso()
        self._commit(QueueEventKind.UPDATED, [code_id])
        return item

    def set_status(self, code_id: str, status: CodeStatus, message: str | None = None) -> CodeItem:
        changes: dict[str, Any] = {"status": status}
        if message is not None:
            changes["message"] = message
        return self.update(code_id, **changes)

    def remove(self, code_ids: Iterable[str]) -> int:
        """Remove the items; notifies REMOVED with the ids actually removed. Returns the count."""
        ids = set(_id_list(code_ids))
        removed = [i.id for i in self._items if i.id in ids]
        if not removed:
            return 0
        self._items = [i for i in self._items if i.id not in ids]
        for cid in removed:
            self._by_id.pop(cid, None)
        self._commit(QueueEventKind.REMOVED, removed)
        return len(removed)

    def clear(self, statuses: Collection[CodeStatus] | None = None) -> int:
        """Remove all items, or only those with a status in ``statuses``. Returns the count."""
        if statuses is None:
            return self.remove([i.id for i in self._items])
        wanted = _statuses(statuses)
        return self.remove([i.id for i in self._items if i.status in wanted])

    def _reorder(self, order: list[CodeItem], ids: Sequence[str]) -> None:
        if len(order) == len(self._items) and any(a is not b for a, b in zip(order, self._items)):
            self._items = order
            self._commit(QueueEventKind.MOVED, list(ids))

    def move(self, code_ids: Sequence[str], delta: int) -> None:
        """Move the items up (delta < 0) or down, keeping their relative order. Notifies MOVED.
        Items stop at the ends; a block of selected items moves together. No event when
        nothing moved."""
        ids = set(_id_list(code_ids))
        delta = int(delta)
        if not ids or not delta:
            return
        order = list(self._items)
        n = len(order)
        for _ in range(min(abs(delta), n)):
            moved = False
            if delta < 0:
                for k in range(1, n):
                    if order[k].id in ids and order[k - 1].id not in ids:
                        order[k - 1], order[k] = order[k], order[k - 1]
                        moved = True
            else:
                for k in range(n - 2, -1, -1):
                    if order[k].id in ids and order[k + 1].id not in ids:
                        order[k], order[k + 1] = order[k + 1], order[k]
                        moved = True
            if not moved:
                break
        self._reorder(order, [i.id for i in order if i.id in ids])

    def move_to(self, code_ids: Sequence[str], index: int) -> None:
        """Move the items (in queue order) so the first lands at ``index`` of the list without
        them (0 = top, len(queue) = bottom; clamped). Notifies MOVED when the order changed."""
        ids = set(_id_list(code_ids))
        moving = [i for i in self._items if i.id in ids]
        if not moving:
            return
        rest = [i for i in self._items if i.id not in ids]
        index = max(0, min(int(index), len(rest)))
        self._reorder(rest[:index] + moving + rest[index:], [i.id for i in moving])

    def set_checked(self, code_ids: Iterable[str], checked: bool) -> None:
        """Tick / untick items (notifies UPDATED with the ids that changed)."""
        changed = []
        for cid in _id_list(code_ids):
            item = self._by_id.get(cid)
            if item is not None and item.checked != bool(checked):
                item.checked = bool(checked)
                changed.append(cid)
        if changed:
            self._commit(QueueEventKind.UPDATED, changed)

    def runnable(self, selection: RunSelection = RunSelection.UNFINISHED,
                 game_key: str | None = None) -> list[CodeItem]:
        """Items a run would process, in order: status.is_runnable (and ``checked`` for CHECKED),
        restricted to items whose game_key equals ``game_key`` when given (runs pass
        profile.game_key(); unassigned items never match a profile)."""
        only_checked = RunSelection(selection) is RunSelection.CHECKED
        return [i for i in self._items
                if i.status.is_runnable and (i.checked or not only_checked)
                and (game_key is None or i.game_key == game_key)]

    def retry_failed(self) -> int:
        """FAILED items -> PENDING (message cleared). REVIEW items are NOT touched: they may have
        been redeemed already and need the user's decision (``reset``). Returns the count."""
        ids = []
        stamp = now_iso()
        for item in self._items:
            if item.status is CodeStatus.FAILED:
                item.status, item.message, item.updated_at = CodeStatus.PENDING, "", stamp
                ids.append(item.id)
        if ids:
            self._commit(QueueEventKind.UPDATED, ids)
        return len(ids)

    def reset(self, code_ids: Iterable[str]) -> int:
        """Selected items -> PENDING with ``flagged`` and ``message`` cleared (RUNNING items are
        skipped). Backs 「確認無誤」 (REVIEW -> PENDING) and 「重設為待兌換」 (any final status,
        e.g. INVALID caused by a typing problem). Notifies UPDATED. Returns the count."""
        ids = []
        stamp = now_iso()
        for cid in _id_list(code_ids):
            item = self._by_id.get(cid)
            if item is None or item.status is CodeStatus.RUNNING:
                continue
            item.status, item.flagged, item.message, item.updated_at = CodeStatus.PENDING, [], "", stamp
            ids.append(cid)
        if ids:
            self._commit(QueueEventKind.UPDATED, ids)
        return len(ids)

    def assign_game(self, code_ids: Iterable[str], game_key: str, game: str = "") -> int:
        """Move items to another game (「指定給…」 for unassigned codes; the Profiles page also
        calls it when a profile's game name changes). An item whose code already exists in the
        target game is removed as a duplicate. Notifies UPDATED / REMOVED. Returns the count moved.
        Items already in ``game_key`` only get the new display name (not counted); without
        ``game`` the display name of other items of that game is reused."""
        if not game and game_key:
            game = next((i.game for i in self._items if i.game_key == game_key and i.game), "")
        if not game_key:
            game = ""
        stamp = now_iso()
        updated: list[str] = []
        dupes: list[str] = []
        moved = 0
        for cid in _id_list(code_ids):
            item = self._by_id.get(cid)
            if item is None:
                continue
            if item.game_key == game_key:
                if game and item.game != game:
                    item.game, item.updated_at = game, stamp
                    updated.append(cid)
                continue
            key = code_key(item.code)
            if any(o is not item and o.game_key == game_key and code_key(o.code) == key for o in self._items):
                dupes.append(cid)
                continue
            item.game_key, item.game, item.updated_at = game_key, game, stamp
            updated.append(cid)
            moved += 1
        if dupes:
            gone = set(dupes)
            self._items = [i for i in self._items if i.id not in gone]
            for cid in dupes:
                self._by_id.pop(cid, None)
        if updated or dupes:
            self._store()
            if updated:
                self._notify(QueueEventKind.UPDATED, updated)
            if dupes:
                self._notify(QueueEventKind.REMOVED, dupes)
        return moved

    def games(self) -> list[tuple[str, str]]:
        """Distinct (game_key, game) pairs of the queued items in queue order ("" = unassigned).
        The first non-empty display name of a game is used."""
        seen: dict[str, str] = {}
        for item in self._items:
            if item.game_key not in seen or (not seen[item.game_key] and item.game):
                seen[item.game_key] = item.game
        return list(seen.items())

    def recover_after_crash(self) -> int:
        """At startup: RUNNING -> REVIEW (tr("上次執行中斷，請確認是否已兌換", "The last run was
        interrupted; check whether this code was redeemed")), COOLDOWN -> PENDING (its stale
        cool-down message cleared). Notifies UPDATED. Returns the count."""
        ids = []
        stamp = now_iso()
        note = tr("上次執行中斷，請確認是否已兌換", "The last run was interrupted; check whether this code was redeemed")
        for item in self._items:
            if item.status is CodeStatus.RUNNING:
                item.status, item.message = CodeStatus.REVIEW, note
            elif item.status is CodeStatus.COOLDOWN:
                item.status, item.message = CodeStatus.PENDING, ""
            else:
                continue
            item.updated_at = stamp
            ids.append(item.id)
        if ids:
            self._commit(QueueEventKind.UPDATED, ids)
        return len(ids)

    def counts(self) -> dict[CodeStatus, int]:
        """Count per status (every CodeStatus present, zeros included)."""
        out = {s: 0 for s in CodeStatus}
        for item in self._items:
            out[item.status] += 1
        return out

    def subscribe(self, callback: Callable[[QueueEvent], None]) -> Callable[[], None]:
        """Call ``callback(event)`` after every change. Returns an unsubscribe function."""
        self._subs.append(callback)

        def unsubscribe() -> None:
            if callback in self._subs:
                self._subs.remove(callback)

        return unsubscribe
