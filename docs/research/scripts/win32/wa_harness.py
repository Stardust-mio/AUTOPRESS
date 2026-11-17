"""wa_harness.py - launch / observe wa_target_app.py from a separate driver process (AutoPress R2a)."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import wa_win32 as w

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "wa_results"
RESULTS.mkdir(exist_ok=True)
PY = sys.executable          # the project venv python (drivers must be run with it)


def now_tag():
    return time.strftime("%Y%m%d_%H%M%S")


def save_result(name, data):
    p = RESULTS / f"wa_result_{name}.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return p


class Target:
    """A running wa_target_app.py instance plus a tail of its JSONL event log."""

    def __init__(self, name, title=None, pos="300,300", extra=(), app="wa_target_app.py", timeout=20):
        self.name = name
        self.log_path = RESULTS / f"wa_log_{name}.jsonl"
        self.info_path = RESULTS / f"wa_info_{name}.json"
        for p in (self.log_path, self.info_path):
            if p.exists():
                p.unlink()
        self.title = title or f"WA Target {name} {os.getpid()}"
        cmd = [PY, str(HERE / app), "--log", str(self.log_path), "--info", str(self.info_path),
               "--title", self.title, "--pos", pos, *extra]
        self.proc = subprocess.Popen(cmd, cwd=str(HERE))
        self._off = 0
        self._buf = b""
        self.events = []
        end = time.time() + timeout
        while not self.info_path.exists():
            if time.time() > end or self.proc.poll() is not None:
                raise RuntimeError(f"target {name} did not start")
            time.sleep(0.05)
        time.sleep(0.05)
        self.info = self.read_info()
        self.hwnd = self.info["hwnd"]

    def read_info(self):
        for _ in range(20):
            try:
                with open(self.info_path, encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, ValueError):
                time.sleep(0.02)
        raise RuntimeError("cannot read info")

    def poll(self):
        """Read new log lines; returns the list of new events."""
        new = []
        try:
            with open(self.log_path, "rb") as f:
                f.seek(self._off)
                chunk = f.read()
        except OSError:
            return new
        self._off += len(chunk)
        data = self._buf + chunk
        lines = data.split(b"\n")
        self._buf = lines.pop()
        for ln in lines:
            if ln.strip():
                ev = json.loads(ln.decode("utf-8"))
                self.events.append(ev)
                new.append(ev)
        return new

    def mark(self):
        self.poll()
        return len(self.events)

    def since(self, mark, ev=None):
        self.poll()
        out = self.events[mark:]
        return [e for e in out if ev is None or e["ev"] == ev]

    def last_text(self):
        self.poll()
        for e in reversed(self.events):
            if e["ev"] == "text":
                return e["text"]
        return ""

    def wait(self, pred, timeout=1.0, step=0.003, mark=None):
        """Wait until pred(events since `mark`) is truthy; returns (result, elapsed_s).
        Pass the mark taken BEFORE injecting: fast targets log the event before wait() starts."""
        m = self.mark() if mark is None else mark
        t0 = time.perf_counter()
        while True:
            r = pred(self.events[m:])
            if r:
                return r, time.perf_counter() - t0
            if time.perf_counter() - t0 > timeout:
                return None, time.perf_counter() - t0
            time.sleep(step)
            self.poll()

    def wait_text(self, expected, mark, timeout=1.0, quiet_s=0.25):
        """Wait until the last 'text' event since mark equals expected, or no new event for quiet_s
        (and timeout). Returns (final_text, t_ns_of_final_event_or_None)."""
        t0 = time.perf_counter()
        last_change = t0
        n_seen = len(self.events)
        while True:
            self.poll()
            if len(self.events) != n_seen:
                n_seen = len(self.events)
                last_change = time.perf_counter()
            texts = [e for e in self.events[mark:] if e["ev"] == "text"]
            cur = texts[-1]["text"] if texts else None
            if cur == expected:
                return cur, texts[-1]["t_ns"]
            el = time.perf_counter() - t0
            if el > timeout or (time.perf_counter() - last_change > quiet_s and el > quiet_s):
                return (cur if cur is not None else self.last_text()), None
            time.sleep(0.002)

    def close(self):
        try:
            w.PostMessageW(self.hwnd, w.WM_CLOSE, 0, 0)
            self.proc.wait(5)
        except Exception:
            try:
                os.kill(self.info["pid"], 9)
            except Exception:
                pass
            self.proc.kill()


class UserActive(RuntimeError):
    pass


class Bursts:
    """Real-input pacing: call tick() before each run. After burst_s of activity it releases modifiers, pauses
    gap_s and aborts (UserActive) if any keyboard/mouse input arrived during the pause (= the user is using the
    PC) or if the target lost the foreground."""

    def __init__(self, t, burst_s=14.0, gap_s=2.0):
        self.t, self.burst_s, self.gap_s = t, burst_s, gap_s
        self.t0 = time.perf_counter()
        self.gaps = []

    def tick(self):
        if time.perf_counter() - self.t0 < self.burst_s:
            return
        release_safety()
        before = w.last_input_tick()
        time.sleep(self.gap_s)
        active = w.last_input_tick() != before
        fg_ok = w.hwnd_int(w.GetForegroundWindow()) == self.t.hwnd
        self.gaps.append({"user_active": active, "fg_ok": fg_ok})
        if active or not fg_ok:
            raise UserActive(f"gap check: user_active={active} fg_ok={fg_ok}")
        self.t0 = time.perf_counter()


def ensure_foreground(t, attempts=3):
    ok, method, tries = w.bring_to_foreground(t.hwnd, attempts=attempts)
    return {"ok": ok, "method": method, "tries": tries}


def release_safety():
    """Always called in finally: no key left down by us."""
    try:
        return w.release_all_modifiers()
    except Exception as e:  # pragma: no cover
        return str(e)
