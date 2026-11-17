"""wb_capture_timing.py - mss 10.2 capture and numpy/PIL conversion timings (no windows shown).

Captured pixels stay in memory only and are discarded; nothing is written to disk except
the JSON with timings. Run in a per-monitor-aware process (QApplication created first) so
that coordinates are physical, exactly as AutoPress will run.
usage: python wb_capture_timing.py OUT.json
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv[:1])  # sets PMv2 before mss is created (see wb_qt_probe --mss before)
import mss  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

import wb_win32 as w  # noqa: E402


def med(fn, n: int) -> dict:
    ts = []
    for _ in range(n):
        a = time.perf_counter()
        fn()
        ts.append((time.perf_counter() - a) * 1000)
    return {"median_ms": round(statistics.median(ts), 3), "min_ms": round(min(ts), 3), "n": n}


R: dict = {"awareness": w.process_awareness(), "main_thread": w.thread_awareness(),
           "raw_thread_ctx": hex(w.GetThreadDpiAwarenessContext() or 0)}  # 0x22 here, i.e. NOT the pseudo handle -4


def _thread_awareness() -> dict:
    """Worker threads inherit the process default (PMv2) unless SetThreadDpiAwarenessContext is used."""
    import threading
    from PyQt6.QtCore import QThread
    out: dict = {}

    class T(QThread):
        def run(self):
            out["QThread"] = w.thread_awareness()

    t = T()
    t.start()
    t.wait()
    th = threading.Thread(target=lambda: out.__setitem__("threading.Thread", w.thread_awareness()))
    th.start()
    th.join()
    return out


R["worker_threads"] = _thread_awareness()
R["mss_ctor_close"] = med(lambda: mss.MSS().close(), 20)
with mss.MSS() as sct:
    mons = sct.monitors
    prim = sct.primary_monitor
    sec = next((m for m in mons[1:] if not m.get("is_primary")), None)
    cases = {"primary_1920x1080": prim, "all_monitors": mons[0],
             "region_400x150_primary": {"left": prim["left"] + 300, "top": prim["top"] + 300, "width": 400, "height": 150}}
    if sec:
        cases["region_400x150_secondary"] = {"left": sec["left"] + 300, "top": sec["top"] + 300, "width": 400, "height": 150}
        cases["secondary_full"] = sec
    for name, mon in cases.items():
        sct.grab(mon)  # warm-up (allocates the DIB section for this size)
        R[name] = med(lambda mon=mon: sct.grab(mon), 100 if "region" in name else 30)
    # alternating sizes re-create the DIB section every call
    R["alternating_region_sizes"] = med(lambda: (sct.grab(cases["region_400x150_primary"]), sct.grab(prim)), 15)
    shots = [sct.grab(prim) for _ in range(12)]
shot = shots[0]
arr = np.asarray(shot)  # zero-copy via ScreenShot.__array_interface__ -> (h, w, 4) uint8 BGRA
R["asarray_shape"] = list(arr.shape)
R["asarray_owndata"] = bool(arr.flags.owndata)  # False -> view on the screenshot buffer (no copy)
it = iter(shots[1:])
R["convert_1080p"] = {
    "np.asarray(shot) [zero-copy]": med(lambda: np.asarray(shot), 50),
    "np.frombuffer(shot.bgra) [bytes copy]": med(lambda: np.frombuffer(shot.bgra, np.uint8).reshape(shot.height, shot.width, 4), 30),
    "BGR copy arr[:, :, :3]": med(lambda: np.ascontiguousarray(arr[:, :, :3]), 30),
    "RGB copy arr[:, :, 2::-1]": med(lambda: np.ascontiguousarray(arr[:, :, 2::-1]), 30),
    "BGRA->gray float dot": med(lambda: (arr[:, :, :3] @ np.array([0.114, 0.587, 0.299], np.float32)).astype(np.uint8), 10),
    "shot.rgb first access (fresh shot)": med(lambda: next(it).rgb, 10),
    "PIL.Image.frombuffer(shot.bgra) BGRX->RGB": med(lambda: Image.frombuffer("RGB", shot.size, shot.bgra, "raw", "BGRX", 0, 1), 30),
}
del arr, shot, shots  # discard real screen content
with open(sys.argv[1], "w", encoding="utf-8") as fh:
    json.dump(R, fh, indent=1)
print(json.dumps(R, indent=1))
