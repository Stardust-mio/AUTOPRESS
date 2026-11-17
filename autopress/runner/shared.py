# OWNED BY G4
"""State shared between RunSession (GUI thread) and the Runner (worker thread), and the payload
of the Runner's code_done signal (G4-internal)."""

from __future__ import annotations

import copy
import threading
from collections.abc import Sequence
from dataclasses import dataclass

from ..models import AttemptRecord, CodeStatus, KeywordConfig, Rect


class SharedState:
    """Lock-protected values the GUI thread changes while a run is active: the physical rects of
    AutoPress's own visible windows (masked in every capture) and updated keyword groups."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._masks: list[Rect] = []
        self._keywords: KeywordConfig | None = None
        self._resolved: dict[str, CodeStatus] = {}  # code_id -> status the user chose (resolve_attention)

    def set_masked_rects(self, rects: Sequence[Rect]) -> None:
        clean: list[Rect] = []
        for r in rects or ():
            x, y, w, h = (int(v) for v in r)
            if w > 0 and h > 0:
                clean.append((x, y, w, h))
        with self._lock:
            self._masks = clean

    def masked_rects(self) -> list[Rect]:
        with self._lock:
            return list(self._masks)

    def set_keywords(self, keywords: KeywordConfig | None) -> None:
        with self._lock:
            self._keywords = copy.deepcopy(keywords) if keywords is not None else None

    def keywords(self) -> KeywordConfig | None:
        with self._lock:
            return self._keywords

    def set_resolved(self, code_id: str, status: CodeStatus) -> None:
        """The user classified an unknown result while the run is paused (GUI thread)."""
        with self._lock:
            self._resolved[code_id] = CodeStatus(status)

    def take_resolved(self, code_id: str) -> CodeStatus | None:
        """The status the user chose for ``code_id`` since the last call (runner thread)."""
        with self._lock:
            return self._resolved.pop(code_id, None)


@dataclass
class CodeDone:
    """Payload of Runner.code_done: the attempt record plus what the queue item becomes."""

    record: AttemptRecord
    queue_status: CodeStatus
    queue_message: str
    persist: bool  # write the record to the history (False = interrupted before submit)
