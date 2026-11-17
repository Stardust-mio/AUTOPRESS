# OWNED BY G3
"""Launch / observe tests/win32_target_app.py for the G3 realinput tests (modelled on
docs/research/scripts/win32/wa_harness.py). The HWND and pid come from the target's own info
file - never from the Popen pid (the venv python.exe is a launcher stub).

``desktop_state_restored()`` saves and restores what a realinput test may change on the user's
desktop; tests/conftest.py wraps every test marked ``realinput`` in it."""

from __future__ import annotations

import json
import subprocess
import sys
import time
import warnings
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
APP = Path(__file__).resolve().parent / "win32_target_app.py"
WM_CLOSE = 0x0010


def center(rect: Sequence[int]) -> tuple[int, int]:
    x, y, w, h = rect
    return x + w // 2, y + h // 2


def caps_lock_on() -> bool:
    from autopress.win32 import api

    return bool(api.GetKeyState(api.VK_CAPITAL) & 1)


@contextmanager
def desktop_state_restored() -> Iterator[None]:
    """Save what a realinput test may change on the user's desktop and put it back afterwards: keys
    and mouse buttons still down (release_all_modifiers), CapsLock, the clipboard (all formats;
    written back only when its sequence number changed) and the cursor position. Create the
    QApplication first (per-monitor-v2: the cursor position is then in physical pixels). A restore
    step that Windows refuses becomes a warning, never an error of the test."""
    from autopress.win32 import api, clipboard
    from autopress.win32 import input as inp

    try:
        snap: Any = clipboard.snapshot()
    except inp.ClipboardBusy:
        snap = None
    seq = int(api.GetClipboardSequenceNumber())  # read after the snapshot, which may render delayed formats
    caps = caps_lock_on()
    cursor = api.cursor_pos()
    try:
        yield
    finally:
        problems: list[str] = []
        inp.release_all_modifiers()
        if caps_lock_on() != caps:
            try:
                inp._send([inp._vk_event(api.VK_CAPITAL, False), inp._vk_event(api.VK_CAPITAL, True)], "capslock")
                time.sleep(0.15)
            except inp.InputBlocked as exc:
                problems.append(f"CapsLock not restored: {exc}")
        if snap is not None and int(api.GetClipboardSequenceNumber()) != seq:
            try:
                clipboard.restore(snap)
            except inp.ClipboardBusy as exc:
                problems.append(f"clipboard not restored: {exc}")
        if cursor is not None and api.cursor_pos() != cursor:
            api.SetCursorPos(*cursor)
        for text in problems:
            warnings.warn(f"realinput teardown: {text}", UserWarning, stacklevel=2)


class TargetApp:
    """A running win32_target_app.py plus a tail of its JSON-lines event log."""

    def __init__(self, folder: Path, env: dict[str, str], name: str, *, title: str | None = None,
                 extra: Sequence[str] = (), timeout_s: float = 25.0) -> None:
        self.name = name
        self.log_path = folder / f"{name}.jsonl"
        self.info_path = folder / f"{name}.json"
        for p in (self.log_path, self.info_path):
            p.unlink(missing_ok=True)
        self.title = title or f"AutoPress G3 {name} {time.time_ns() % 100000}"
        cmd = [sys.executable, str(APP), "--log", str(self.log_path), "--info", str(self.info_path),
               "--title", self.title, *extra]
        self.proc = subprocess.Popen(cmd, cwd=str(ROOT), env=env)
        self._off = 0
        self._buf = b""
        self.events: list[dict[str, Any]] = []
        deadline = time.monotonic() + timeout_s
        while not self.info_path.exists():
            if time.monotonic() > deadline or self.proc.poll() is not None:
                self.close()
                raise RuntimeError(f"target {name} did not start")
            time.sleep(0.05)
        time.sleep(0.1)
        self.info = self.read_info()

    # -- info ------------------------------------------------------------------------------
    def read_info(self) -> dict[str, Any]:
        for _ in range(40):
            try:
                return json.loads(self.info_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                time.sleep(0.025)
        raise RuntimeError("cannot read the target info")

    def refresh(self) -> dict[str, Any]:
        self.info = self.read_info()
        return self.info

    @property
    def hwnd(self) -> int:
        return int(self.info["hwnd"])

    @property
    def pid(self) -> int:
        return int(self.info["pid"])

    # -- log -------------------------------------------------------------------------------
    def poll(self) -> list[dict[str, Any]]:
        new: list[dict[str, Any]] = []
        try:
            with open(self.log_path, "rb") as f:
                f.seek(self._off)
                chunk = f.read()
        except OSError:
            return new
        self._off += len(chunk)
        lines = (self._buf + chunk).split(b"\n")
        self._buf = lines.pop()
        for line in lines:
            if line.strip():
                ev = json.loads(line.decode("utf-8"))
                self.events.append(ev)
                new.append(ev)
        return new

    def mark(self) -> int:
        self.poll()
        return len(self.events)

    def since(self, mark: int, ev: str | None = None) -> list[dict[str, Any]]:
        self.poll()
        return [e for e in self.events[mark:] if ev is None or e["ev"] == ev]

    def wait(self, pred: Callable[[list[dict[str, Any]]], Any], mark: int, timeout_s: float = 2.0) -> Any:
        """Wait until ``pred(events since mark)`` is truthy; returns it (None on timeout)."""
        deadline = time.monotonic() + timeout_s
        while True:
            self.poll()
            result = pred(self.events[mark:])
            if result or time.monotonic() > deadline:
                return result or None
            time.sleep(0.01)

    def last_text(self) -> str:
        self.poll()
        texts = [e["text"] for e in self.events if e["ev"] == "text"]
        return texts[-1] if texts else ""

    def wait_text(self, expected: str, timeout_s: float = 2.0, quiet_s: float = 0.3) -> str:
        """Wait until the field shows ``expected`` (or nothing changed for ``quiet_s``); returns
        the final text."""
        deadline = time.monotonic() + timeout_s
        seen = len(self.events)
        last_change = time.monotonic()
        while True:
            self.poll()
            if len(self.events) != seen:
                seen, last_change = len(self.events), time.monotonic()
            text = self.last_text()
            now = time.monotonic()
            if text == expected or now > deadline or now - last_change > quiet_s:
                return text
            time.sleep(0.01)

    # -- lifetime --------------------------------------------------------------------------
    def close(self) -> None:
        """WM_CLOSE (the venv launcher stub exits with its child); TerminateProcess of the REAL
        child pid only as a last resort."""
        import os

        from autopress.win32 import api

        info: dict[str, Any] = {}
        try:
            if self.info_path.exists():
                info = json.loads(self.info_path.read_text(encoding="utf-8"))
                api.PostMessageW(int(info["hwnd"]), WM_CLOSE, 0, 0)
            self.proc.wait(5)
        except Exception:  # noqa: BLE001 - last resort
            if info.get("pid"):
                try:
                    os.kill(int(info["pid"]), 9)
                except OSError:
                    pass
            self.proc.kill()
            self.proc.wait(5)
