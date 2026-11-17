# OWNED BY G7
"""Real-desktop checks for the run UI (marked ``realinput``: they show windows on the user's
desktop, so they are skipped unless AUTOPRESS_REALINPUT=1; SPEC 8.1). They inject no input.

* the mini bar never takes the foreground (WindowDoesNotAcceptFocus -> WS_EX_NOACTIVATE,
  SPEC 11.6), is topmost and a tool window, and the frame rect published for masking equals
  the real window rect;
* a countdown overlay is click-through (WS_EX_TRANSPARENT) and does not activate.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

CHILD = r'''
import ctypes, json, sys, time
from ctypes import wintypes as wt
sys.path.insert(0, sys.argv[1])
from PyQt6.QtWidgets import QApplication
app = QApplication([sys.argv[0]])
from tests import ui_fallback
ui_fallback.install()
from autopress.ui import theme
theme.apply_theme(app, "dark")
from tests.fakes import demo_context
from autopress.ui.minibar import MiniBar
from autopress.ui.overlays import CountdownOverlay

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetForegroundWindow.restype = wt.HWND
user32.GetForegroundWindow.argtypes = []
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
user32.GetWindowRect.restype = wt.BOOL
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]

def pump(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.02)

def rect(hwnd):
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return [r.left, r.top, r.right - r.left, r.bottom - r.top]

ctx = demo_context()
fg_before = user32.GetForegroundWindow() or 0
bar = MiniBar(ctx)
bar.move(40, 40)
bar.show()
pump(0.4)
hwnd = int(bar.winId())
ex = user32.GetWindowLongPtrW(hwnd, -20)
fg_after = user32.GetForegroundWindow() or 0
out = {"noactivate": bool(ex & 0x08000000), "topmost": bool(ex & 0x8), "toolwindow": bool(ex & 0x80),
       "fg_same": fg_before == fg_after, "frame_rect": list(bar.frame_rect_physical()), "window_rect": rect(hwnd)}
bar.close()
cd = CountdownOverlay()
cd.start(2, None, "F9")
pump(0.3)
cw = cd.widget
cex = user32.GetWindowLongPtrW(int(cw.winId()), -20) if cw is not None else 0
out["countdown_transparent"] = bool(cex & 0x20)
out["countdown_fg_same"] = (user32.GetForegroundWindow() or 0) == fg_before
cd.cancel()
pump(0.1)
print(json.dumps(out))
'''


@pytest.mark.realinput
def test_minibar_and_countdown_never_activate(clean_env: dict[str, str], python_exe: str, tmp_path: Path) -> None:
    script = tmp_path / "g7_bar_child.py"
    script.write_text(CHILD, encoding="utf-8")
    proc = subprocess.run([python_exe, str(script), str(ROOT)], env=clean_env, cwd=str(ROOT),
                          capture_output=True, text=True, encoding="utf-8", timeout=90)
    assert proc.returncode == 0, proc.stderr[-2000:]
    data = json.loads(proc.stdout.strip().splitlines()[-1])
    assert data["noactivate"] and data["topmost"] and data["toolwindow"], data
    assert data["fg_same"], "the mini bar took the foreground"
    assert data["frame_rect"] == data["window_rect"], data
    assert data["countdown_transparent"] and data["countdown_fg_same"], data
