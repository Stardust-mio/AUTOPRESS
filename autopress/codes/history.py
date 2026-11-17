# OWNED BY G1
"""Attempt history: append-only history.jsonl (one AttemptRecord per line, "schema_version"
on every line), in-memory index by (game_key, code_key). Pure Python, GUI thread only.
Corrupt lines are skipped (logged). remove()/clear() rewrite the file atomically.

Details:
* append() writes one line and fsyncs; a file whose last line was cut off by a crash gets a line
  break first, so the new record stays readable. Write errors are logged (``last_error``) and
  never raised: the record stays in memory for this session.
* update() / remove() / clear() / prune_evidence() rewrite the whole file with
  storage.write_bytes_atomic (corrupt lines are dropped then). If the file could not be read at
  load(), it is renamed ``history.jsonl.broken-<ts>`` before the first rewrite.
* remove() and clear() also delete the evidence PNGs of the removed records (evidence images may
  show account names) - only files inside ``<data folder>/evidence`` that no remaining record
  uses. evidence_path is relative to paths.data_dir() (SPEC 5.8).
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import time
from collections.abc import Callable, Collection, Iterable
from datetime import date, datetime, timedelta
from pathlib import Path

from .. import paths, storage
from ..models import (
    HISTORY_SCHEMA_VERSION,
    AttemptRecord,
    CodeStatus,
    ResultClass,
    code_key,
    from_dict,
    migrate,
    new_id,
    to_dict,
)

log = logging.getLogger(__name__)

_FIELDS = frozenset(f.name for f in dataclasses.fields(AttemptRecord))


def _id_list(ids: Iterable[str] | str) -> set[str]:
    return {ids} if isinstance(ids, str) else set(ids)


def _statuses(values: Iterable[object]) -> set[CodeStatus]:
    out: set[CodeStatus] = set()
    for v in values:
        try:
            out.add(CodeStatus(v))
        except ValueError:
            log.debug("unknown status %r ignored", v)
    return out


def _local_date(stamp: str) -> date | None:
    try:
        dt = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None
    return (dt.astimezone() if dt.tzinfo else dt).date()


class HistoryStore:
    def __init__(self, path: Path | None = None) -> None:
        """``path`` None -> paths.history_path(). Nothing is read until load()."""
        self._path = Path(path) if path is not None else None
        self._records: list[AttemptRecord] = []
        self._by_id: dict[str, AttemptRecord] = {}
        self._latest: dict[tuple[str, str], AttemptRecord] = {}
        self._subs: list[Callable[[], None]] = []
        self._move_aside = False
        self.last_error = ""
        """Localized text of the last failed read / write ("" after a successful write)."""
        self.skipped_lines = 0
        """Corrupt lines skipped by the last load()."""

    # -- persistence -----------------------------------------------------------------------
    @property
    def path(self) -> Path:
        """The history file (resolved lazily)."""
        return self._path if self._path is not None else paths.history_path()

    def load(self) -> None:
        """Read history.jsonl (missing -> empty; corrupt lines skipped); notify subscribers."""
        path = self.path
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            data = b""
        except OSError as exc:
            log.error("cannot read the history file %s: %s", path, exc)
            self.last_error = str(exc)
            self._move_aside = True
            data = b""
        if data.startswith(b"\xef\xbb\xbf"):
            data = data[3:]
        records: list[AttemptRecord] = []
        seen: set[str] = set()
        skipped = 0
        for number, line in enumerate(data.split(b"\n"), 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, ValueError, RecursionError) as exc:
                obj = None
                log.warning("%s line %d skipped (%s)", path.name, number, type(exc).__name__)
            if not isinstance(obj, dict):
                skipped += 1
                continue
            rec = from_dict(AttemptRecord, migrate("history", obj))
            if not rec.id or rec.id in seen:
                rec.id = new_id()
            seen.add(rec.id)
            records.append(rec)
        self._records = records
        self.skipped_lines = skipped
        self._reindex()
        self._notify()

    @staticmethod
    def _line(rec: AttemptRecord) -> str:
        return json.dumps({"schema_version": HISTORY_SCHEMA_VERSION, **to_dict(rec)}, ensure_ascii=False) + "\n"

    def _append_line(self, line: str) -> None:
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        data = line.encode("utf-8", errors="replace")
        with open(path, "a+b") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            if size:
                fh.seek(size - 1)
                if fh.read(1) != b"\n":
                    data = b"\n" + data  # the last line was cut off: keep the new record readable
            fh.write(data)  # append mode: always written at the end
            fh.flush()
            os.fsync(fh.fileno())

    def _rewrite(self) -> None:
        path = self.path
        if self._move_aside:
            self._move_aside = False
            if path.exists():
                aside = path.with_name(f"{path.name}.broken-{datetime.now():%Y%m%d-%H%M%S}")
                try:
                    os.replace(path, aside)
                    log.warning("kept the unreadable history file as %s", aside.name)
                except OSError as exc:
                    log.error("could not move %s aside: %s", path, exc)
        payload = "".join(self._line(r) for r in self._records).encode("utf-8", errors="replace")
        try:
            storage.write_bytes_atomic(path, payload)
            self.last_error = ""
        except storage.StorageError as exc:
            log.error("rewriting the history failed: %s", exc)
            self.last_error = str(exc)

    def _reindex(self) -> None:
        self._by_id = {r.id: r for r in self._records}
        self._latest = {}
        for r in self._records:
            self._latest[(r.game_key, code_key(r.code))] = r

    def _notify(self) -> None:
        for cb in list(self._subs):
            try:
                cb()
            except Exception:  # noqa: BLE001 - one broken view must not break the bookkeeping
                log.exception("history subscriber failed")

    # -- writing ---------------------------------------------------------------------------
    def append(self, record: AttemptRecord) -> None:
        """Append one line (flush) and notify subscribers. The store keeps ``record`` itself;
        an empty or already used id is replaced by a new one."""
        if not record.id or record.id in self._by_id:
            record.id = new_id()
        self._records.append(record)
        self._by_id[record.id] = record
        self._latest[(record.game_key, code_key(record.code))] = record
        try:
            self._append_line(self._line(record))
            self.last_error = ""
        except OSError as exc:
            log.error("appending to the history failed: %s", exc)
            self.last_error = str(exc)
        self._notify()

    def update(self, record_id: str, **changes: object) -> AttemptRecord:
        """Change fields of one record IN PLACE (same id, same position, so ``latest`` keeps its
        meaning) and rewrite the file atomically; notifies subscribers. KeyError if absent.
        Used by RunSession.resolve_attention (status / result / message of an unknown result).
        Unknown fields raise AttributeError and the id cannot change (ValueError); status /
        result strings are converted to their enums."""
        rec = self._by_id.get(record_id)
        if rec is None:
            raise KeyError(record_id)
        for name in changes:
            if name not in _FIELDS:
                raise AttributeError(name)
        if "id" in changes and changes["id"] != rec.id:
            raise ValueError("the id of a history record cannot change")
        for name, value in changes.items():
            if name == "status" and not isinstance(value, CodeStatus):
                value = CodeStatus(value)
            elif name == "result" and value is not None and not isinstance(value, ResultClass):
                value = ResultClass(value)
            setattr(rec, name, value)
        if "code" in changes or "game_key" in changes:
            self._reindex()
        self._rewrite()
        self._notify()
        return rec

    def remove(self, record_ids: Iterable[str]) -> int:
        """Remove records (and their evidence files); rewrite the file. Returns the count."""
        ids = _id_list(record_ids)
        gone = [r for r in self._records if r.id in ids]
        if not gone:
            return 0
        self._records = [r for r in self._records if r.id not in ids]
        self._reindex()
        self._rewrite()
        self._delete_evidence(gone)
        self._notify()
        return len(gone)

    def clear(self) -> int:
        """Remove every record (and their evidence files); the file is rewritten empty."""
        gone = self._records
        self._records = []
        self._reindex()
        self._rewrite()
        self._delete_evidence(gone)
        self._notify()
        return len(gone)

    # -- reading ---------------------------------------------------------------------------
    def records(self) -> list[AttemptRecord]:
        """All records, oldest first (a new list)."""
        return list(self._records)

    def __len__(self) -> int:
        return len(self._records)

    def latest(self, game_key: str, code: str) -> AttemptRecord | None:
        """Most recent record for this game and code (compared by models.code_key)."""
        return self._latest.get((game_key, code_key(code or "")))

    def is_done(self, game_key: str, code: str, statuses: Collection[CodeStatus]) -> bool:
        """True if latest(game_key, code).status is in ``statuses``."""
        rec = self.latest(game_key, code)
        return rec is not None and rec.status in _statuses(statuses)

    def query(self, text: str = "", statuses: Collection[CodeStatus] | None = None,
              game_key: str | None = None) -> list[AttemptRecord]:
        """Newest first; ``text`` matches code, message, game or profile name (case-insensitive;
        a code also matches without its separators, e.g. "ABCD1234" finds "ABCD-1234")."""
        needle = (text or "").strip().casefold()
        needle_key = code_key(needle)
        wanted = None if statuses is None else _statuses(statuses)
        out = []
        for r in reversed(self._records):
            if wanted is not None and r.status not in wanted:
                continue
            if game_key is not None and r.game_key != game_key:
                continue
            if needle:
                hay = f"{r.code}\n{r.message}\n{r.game}\n{r.profile_name}".casefold()
                if needle not in hay and not (needle_key and needle_key in code_key(r.code).casefold()):
                    continue
            out.append(r)
        return out

    def games(self) -> list[tuple[str, str]]:
        """Distinct (game_key, game display name) pairs, newest game first."""
        seen: dict[str, str] = {}
        for r in reversed(self._records):
            if r.game_key not in seen or (not seen[r.game_key] and r.game):
                seen[r.game_key] = r.game
        return list(seen.items())

    def attempts_on(self, day: date | None = None) -> int:
        """Records started (else finished) on ``day`` (local calendar day, default today),
        manual marks (run_id "manual") excluded - the count behind Settings.daily_cap."""
        day = day or date.today()
        return sum(1 for r in self._records
                   if r.run_id != "manual" and _local_date(r.started_at or r.finished_at) == day)

    # -- evidence --------------------------------------------------------------------------
    @staticmethod
    def _evidence_root() -> Path:
        return paths.data_dir(create=False) / "evidence"

    def _evidence_file(self, rel: str) -> Path | None:
        """Absolute evidence path for ``rel`` if it lies inside the evidence folder, else None."""
        if not rel:
            return None
        try:
            root = self._evidence_root().resolve()
            target = (paths.data_dir(create=False) / rel).resolve()
            target.relative_to(root)
        except (OSError, ValueError):
            return None
        return target

    def _delete_evidence(self, records: Iterable[AttemptRecord]) -> None:
        used = {p for p in (self._evidence_file(r.evidence_path) for r in self._records) if p}
        for rec in records:
            target = self._evidence_file(rec.evidence_path)
            if target is None or target in used:
                continue
            try:
                target.unlink(missing_ok=True)
            except OSError as exc:
                log.warning("could not delete evidence %s: %s", target.name, exc)
                continue
            parent = target.parent
            try:
                if parent != self._evidence_root().resolve() and not any(parent.iterdir()):
                    parent.rmdir()
            except OSError:
                pass

    def prune_evidence(self, keep_days: int) -> int:
        """Delete evidence PNGs older than ``keep_days`` (0 = keep all) and blank the paths of
        records that pointed to them. Returns the number of files deleted.
        Age = the date of the <yyyy-mm-dd> folder (the file's modification time otherwise); a
        file of exactly ``keep_days`` days ago is kept. Records whose evidence file is missing
        are blanked too, and empty date folders are removed."""
        try:
            keep = int(keep_days)
        except (TypeError, ValueError):
            return 0
        if keep <= 0:
            return 0
        root = self._evidence_root()
        deleted = 0
        if root.is_dir():
            cutoff_day = date.today() - timedelta(days=keep)
            cutoff_ts = time.time() - keep * 86400
            for f in list(root.rglob("*")):
                if not f.is_file() or f.suffix.lower() != ".png":
                    continue
                try:
                    folder_day = datetime.strptime(f.parent.name, "%Y-%m-%d").date() if f.parent != root else None
                except ValueError:
                    folder_day = None
                try:
                    old = folder_day < cutoff_day if folder_day else f.stat().st_mtime < cutoff_ts
                    if old:
                        f.unlink()
                        deleted += 1
                except OSError as exc:
                    log.warning("could not prune evidence %s: %s", f.name, exc)
            for d in sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
                try:
                    if not any(d.iterdir()):
                        d.rmdir()
                except OSError:
                    pass
        changed = False
        for r in self._records:
            target = self._evidence_file(r.evidence_path)
            if target is not None and not target.exists():
                r.evidence_path = ""
                changed = True
        if changed:
            self._rewrite()
            self._notify()
        if deleted:
            log.info("pruned %d evidence files older than %d days", deleted, keep)
        return deleted

    # -- observers -------------------------------------------------------------------------
    def subscribe(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Call ``callback()`` after every change. Returns an unsubscribe function."""
        self._subs.append(callback)

        def unsubscribe() -> None:
            if callback in self._subs:
                self._subs.remove(callback)

        return unsubscribe
