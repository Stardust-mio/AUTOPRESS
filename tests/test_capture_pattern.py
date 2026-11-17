"""G2 (realinput): pixel-exact capture of a pattern window shown on the desktop by a child
process (win32_windows.md section 4). Marked ``realinput`` because a window appears on the
desktop; no input is injected. Run with the user present:

    AUTOPRESS_REALINPUT=1 .venv/Scripts/python.exe -m pytest -q -m realinput tests/test_capture_pattern.py

The child (this file run as a script with ``--pattern-window``) shows a frameless, topmost,
input-transparent tool window that never takes focus, paints a per-pixel pattern in PHYSICAL
pixels (QImage with the window's device pixel ratio), prints one JSON line (hwnd + physical
client rect from GetClientRect / ClientToScreen) and closes on WM_CLOSE or after 15 s.
"""

from __future__ import annotations

import ctypes
import json
import queue
import subprocess
import sys
import threading
import time
from ctypes import wintypes as wt
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
WM_CLOSE = 0x0010


def pattern(w: int, h: int) -> np.ndarray:
    """BGR pattern in which no shifted copy matches (x and y mixed with co-prime factors)."""
    y, x = np.mgrid[0:h, 0:w]
    return np.dstack([(x * 7 + y * 3) % 256, (x * 5 + y * 11 + 64) % 256, ((x ^ y) * 3 + x // 7) % 256]).astype(np.uint8)


# ----------------------------------------------------------------------------- child process


def _child_main(argv: list[str]) -> int:
    from PyQt6.QtCore import Qt, QTimer
    from PyQt6.QtGui import QImage, QPainter
    from PyQt6.QtWidgets import QApplication, QWidget

    app = QApplication(argv[:1])

    class PatternWindow(QWidget):
        def paintEvent(self, _event: object) -> None:  # noqa: N802 - Qt override
            dpr = self.devicePixelRatioF()
            pw, ph = round(self.width() * dpr), round(self.height() * dpr)
            bgra = np.empty((ph, pw, 4), np.uint8)
            bgra[:, :, :3] = pattern(pw, ph)
            bgra[:, :, 3] = 255
            self._buf = bgra  # keep the memory alive while the QImage uses it
            img = QImage(bgra.data, pw, ph, pw * 4, QImage.Format.Format_RGB32)
            img.setDevicePixelRatio(dpr)
            p = QPainter(self)
            p.drawImage(0, 0, img)
            p.end()

    win = PatternWindow()
    win.setWindowTitle("AutoPress capture pattern")
    win.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                       | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.WindowTransparentForInput)
    win.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    win.setFixedSize(240, 120)
    screen = app.primaryScreen().availableGeometry()
    win.move(screen.left() + 160, screen.top() + 160)
    win.show()

    def report() -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
        user32.GetClientRect.restype = wt.BOOL
        user32.ClientToScreen.argtypes = [wt.HWND, ctypes.POINTER(wt.POINT)]
        user32.ClientToScreen.restype = wt.BOOL
        hwnd = int(win.winId())
        rc = wt.RECT()
        pt = wt.POINT(0, 0)
        user32.GetClientRect(hwnd, ctypes.byref(rc))
        user32.ClientToScreen(hwnd, ctypes.byref(pt))
        print(json.dumps({"hwnd": hwnd, "client": [pt.x, pt.y, rc.right - rc.left, rc.bottom - rc.top],
                          "dpr": win.devicePixelRatioF()}), flush=True)

    QTimer.singleShot(400, report)
    QTimer.singleShot(15000, app.quit)
    return app.exec()


# ----------------------------------------------------------------------------- tests


def _start_child(python_exe: str, env: dict[str, str]) -> tuple[subprocess.Popen[str], dict]:
    proc = subprocess.Popen([python_exe, str(Path(__file__)), "--pattern-window"], cwd=str(ROOT), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
    lines: queue.Queue[str] = queue.Queue()
    threading.Thread(target=lambda: lines.put(proc.stdout.readline()), daemon=True).start()  # type: ignore[union-attr]
    try:
        info = json.loads(lines.get(timeout=20))
    except Exception:
        proc.kill()
        raise
    time.sleep(0.25)  # let the window paint
    return proc, info


def _close_child(proc: subprocess.Popen[str], hwnd: int) -> None:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    user32.PostMessageW.restype = wt.BOOL
    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    try:
        proc.wait(5)
    except subprocess.TimeoutExpired:
        proc.kill()


def _match_ratio(img: np.ndarray, expected: np.ndarray) -> float:
    return float((img[:, :, :3] == expected).all(axis=2).mean())


@pytest.mark.realinput
def test_grab_pattern_window_pixel_exact(qapp: object, clean_env: dict[str, str], python_exe: str) -> None:
    from autopress.capture import Grabber, looks_blank

    proc, info = _start_child(python_exe, clean_env)
    try:
        x, y, w, h = info["client"]
        assert w > 0 and h > 0
        with Grabber() as g:
            img = g.grab((x, y, w, h))
            assert img.shape == (h, w, 4) and np.all(img[:, :, 3] == 255)
            assert not looks_blank(img), "capture is blank: locked screen or no desktop session"
            ratio = _match_ratio(img, pattern(w, h))
            assert ratio == 1.0, f"only {ratio:.1%} of the pixels match at offset (0, 0)"
            shifted = g.grab((x + 1, y, w, h))
            assert _match_ratio(shifted, pattern(w, h)) < 0.05  # a 1-px shift does not match
    finally:
        _close_child(proc, info["hwnd"])


@pytest.mark.realinput
def test_grab_client_of_pattern_window(qapp: object, clean_env: dict[str, str], python_exe: str) -> None:
    from tests.fakes import skip_if_stub

    skip_if_stub("autopress.win32.windows")
    from autopress.capture import Grabber
    from autopress.models import record_region

    proc, info = _start_child(python_exe, clean_env)
    try:
        x, y, w, h = info["client"]
        with Grabber() as g:
            img, rect = g.grab_client(info["hwnd"])
            assert rect == (x, y, w, h)
            assert _match_ratio(img, pattern(w, h)) == 1.0
            region = record_region(rect, x + 20, y + 10, 100, 50)
            part, prect = g.grab_client(info["hwnd"], region)
            assert prect == (x + 20, y + 10, 100, 50)
            assert _match_ratio(part, pattern(w, h)[10:60, 20:120]) == 1.0
    finally:
        _close_child(proc, info["hwnd"])


if __name__ == "__main__" and "--pattern-window" in sys.argv:
    sys.exit(_child_main(sys.argv))
