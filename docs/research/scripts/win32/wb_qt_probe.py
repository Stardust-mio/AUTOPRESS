"""wb_qt_probe.py - child-process probe, launched by wb_run_suite.py (one JSON file per run).

Measures: DPI awareness before/after QApplication (and the effect of importing/creating
mss before or after Qt), QScreen vs Win32 monitors, Qt logical -> physical mapping using
native (WA_NativeWindow) widgets in hidden windows, read-only cursor mapping
(GetCursorPos vs QCursor.pos), overlay math, and with --visible a pixel-exact capture of an
own no-focus, input-transparent window via mss and QScreen.grabWindow (+ thread tests).
Never activates a window, never injects input, never saves a screenshot.

usage: python wb_qt_probe.py OUT.json [--mss none|import|before|after] [--visible] [--timing]
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import math
import os
import statistics
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wb_win32 as w  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("out")
ap.add_argument("--mss", choices=["none", "import", "before", "after"], default="none")
ap.add_argument("--visible", action="store_true")
ap.add_argument("--timing", action="store_true")
args = ap.parse_args()

R: dict = {"env": {k: os.environ.get(k) for k in ("QT_SCALE_FACTOR", "QT_SCREEN_SCALE_FACTORS")}, "mss_mode": args.mss}


def aware() -> dict:
    return {"thread": w.thread_awareness(), "process": w.process_awareness()}


R["pre_qt"] = aware()
sct = None
if args.mss in ("import", "before"):
    import mss
    R["after_import_mss"] = aware()
    if args.mss == "before":
        sct = mss.MSS()
        R["after_mss_ctor"] = aware()

import numpy as np  # noqa: E402
from PyQt6 import sip  # noqa: E402
from PyQt6.QtCore import QPoint, QPointF, QRect, QSize, Qt, QThread, qInstallMessageHandler, qVersion  # noqa: E402
from PyQt6.QtGui import QCursor, QGuiApplication, QImage, QPainter  # noqa: E402
from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

MSGS: list[str] = []
qInstallMessageHandler(lambda mode, ctx, msg: MSGS.append(f"{mode.name}: {msg}"))
app = QApplication(sys.argv[:1])
R["qt_version"] = qVersion()
R["rounding_policy"] = QGuiApplication.highDpiScaleFactorRoundingPolicy().name
R["post_qt"] = aware()
pda = ctypes.c_int(-1)
R["post_qt"]["GetProcessDpiAwareness"] = [w.hr_hex(w.GetProcessDpiAwareness(None, ctypes.byref(pda))), pda.value]
R["post_qt"]["GetDpiForSystem"] = w.GetDpiForSystem()

if args.mss == "after":
    import mss
    sct = mss.MSS()
    R["after_mss_ctor"] = aware()
    spda = w.shcore.SetProcessDpiAwareness
    spda.argtypes, spda.restype = [ctypes.c_int], w.HRESULT
    R["after_mss_ctor"]["second_SetProcessDpiAwareness(2)"] = w.hr_hex(spda(2))

MONS = w.monitors()
R["win32_monitors"] = [{k: v for k, v in m.items() if k != "hmonitor"} for m in MONS]


def qrect(r) -> list:
    return [r.x(), r.y(), r.width(), r.height()]


def qround(v: float) -> int:
    """Qt's qRound: round half up (Python's round() is banker's rounding and differs at .5)."""
    return math.floor(v + 0.5)


def checkpoint() -> None:
    R["qt_messages"] = MSGS
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(R, fh, indent=1, default=str)


def mon_for(screen) -> dict | None:
    """QScreen.name() is the EDID friendly name in Qt 6.12, so match by native origin."""
    g = screen.geometry()
    return next((m for m in MONS if tuple(m["rect"][:2]) == (g.x(), g.y())), None)


R["screens"] = []
for s in app.screens():
    m = mon_for(s)
    d = s.devicePixelRatio()
    R["screens"].append({"name": s.name(), "geometry": qrect(s.geometry()), "available": qrect(s.availableGeometry()),
                         "dpr": d, "logicalDpi": s.logicalDotsPerInch(), "primary": s is app.primaryScreen(),
                         "win32_rect": list(m["rect"]) if m else None, "win32_device": m["device"] if m else None,
                         "origin_equal": m is not None,
                         "size_times_dpr": [qround(s.geometry().width() * d), qround(s.geometry().height() * d)]})


def to_phys(screen, x: float, y: float) -> tuple[float, float]:
    """Claim under test: phys = screenOrigin + (logical - screenOrigin) * dpr (origin kept in native px)."""
    g, d = screen.geometry(), screen.devicePixelRatio()
    return (g.x() + (x - g.x()) * d, g.y() + (y - g.y()) * d)


def make_window(geom: QRect, hidden: bool, transparent: bool = False, cls=QWidget) -> QWidget:
    flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowDoesNotAcceptFocus
    if not hidden:
        flags |= Qt.WindowType.WindowStaysOnTopHint
    if transparent:
        flags |= Qt.WindowType.WindowTransparentForInput
    wdg = cls(None, flags)
    wdg.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    if hidden:
        wdg.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    wdg.setWindowTitle("wb_probe")
    wdg.setGeometry(geom)
    return wdg


def pump(ms: int) -> None:
    end = time.perf_counter() + ms / 1000
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.005)


# ---- 1. mapping with hidden windows (native child gives a measurable HWND) ----------------
R["mapping"] = []
for s in app.screens():
    g = s.geometry()
    top = make_window(QRect(g.topLeft() + QPoint(101, 67), QSize(301, 121)), hidden=True)
    child = QWidget(top)
    child.setGeometry(37, 23, 50, 41)
    child.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
    top.show()
    hw, ch = int(top.winId()), int(child.winId())
    pump(30)
    lt, lc = top.mapToGlobal(QPoint(0, 0)), child.mapToGlobal(QPoint(0, 0))
    ws = top.screen()
    mt, mc = w.client_rect_screen(hw), w.client_rect_screen(ch)
    pt, pc = to_phys(ws, lt.x(), lt.y()), to_phys(ws, lc.x(), lc.y())
    d = ws.devicePixelRatio()
    R["mapping"].append({
        "screen": s.name(), "window_screen": ws.name(), "dpr": d,
        "logical_top": [lt.x(), lt.y()], "measured_top_client": list(mt), "predicted_top": list(pt),
        "naive_global_scale_top": [lt.x() * d, lt.y() * d],
        "logical_child": [lc.x(), lc.y()], "measured_child_client": list(mc), "predicted_child": list(pc),
        "logical_size": [top.width(), top.height()],
        "ok_top": abs(pt[0] - mt[0]) < 1 and abs(pt[1] - mt[1]) < 1,
        "ok_child": abs(pc[0] - mc[0]) < 1 and abs(pc[1] - mc[1]) < 1,
        "ok_size": [mt[2], mt[3]] == [qround(top.width() * d), qround(top.height() * d)],
        "window_dpi": w.GetDpiForWindow(hw), "window_awareness": w.awareness_name(w.GetWindowDpiAwarenessContext(hw)),
        "visible_flag": bool(w.IsWindowVisible(hw)),
    })
    sip.delete(top)
    R["mapping"][-1]["IsWindow_after_delete"] = bool(w.IsWindow(hw))

# ---- 2. overlay math: full-screen hidden overlay per screen + native child rects ------------
R["overlay"] = []
for s in app.screens():
    g, d, m = s.geometry(), s.devicePixelRatio(), mon_for(s)
    ov = make_window(QRect(g), hidden=True)
    rects = [QRect(0, 0, 1, 1), QRect(7, 9, 13, 11), QRect(333, 211, 401, 151), QRect(g.width() - 31, g.height() - 17, 31, 17)]
    kids = []
    for r in rects:
        c = QWidget(ov)
        c.setGeometry(r)
        c.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        kids.append(c)
    ov.show()
    hov = int(ov.winId())
    pump(30)
    ox, oy = m["rect"][0], m["rect"][1]
    rec = {"screen": s.name(), "dpr": d, "overlay_logical": qrect(g), "overlay_physical": list(w.window_rect(hov)),
           "monitor_physical": list(m["rect"]), "cases": []}
    for r, c in zip(rects, kids):
        meas = list(w.window_rect(int(c.winId())))
        pred = [ox + qround(r.x() * d), oy + qround(r.y() * d), qround(r.width() * d), qround(r.height() * d)]
        rec["cases"].append({"local_logical": qrect(r), "measured": meas, "predicted": pred, "ok": meas == pred})
    R["overlay"].append(rec)
    sip.delete(ov)
checkpoint()

# ---- 3. cursor mapping (read-only) -----------------------------------------------------
R["cursor"] = []
for _ in range(6):
    p1, p2 = wt.POINT(), wt.POINT()
    w.GetCursorPos(ctypes.byref(p1))
    q = QCursor.pos()
    w.GetCursorPos(ctypes.byref(p2))
    if (p1.x, p1.y) == (p2.x, p2.y):
        s = QGuiApplication.screenAt(q)
        pred = to_phys(s, q.x(), q.y()) if s else None
        R["cursor"].append({"phys": [p1.x, p1.y], "qt_logical": [q.x(), q.y()], "screen": s.name() if s else None,
                            "predicted_phys": list(pred) if pred else None,
                            "err": [round(pred[0] - p1.x, 3), round(pred[1] - p1.y, 3)] if pred else None,
                            "dpr": s.devicePixelRatio() if s else None})
    time.sleep(0.03)


# ---- 4. visible capture tests -----------------------------------------------------------
def pattern(wp: int, hp: int) -> np.ndarray:
    x = np.arange(wp, dtype=np.uint32)[None, :]
    y = np.arange(hp, dtype=np.uint32)[:, None]
    bgra = np.empty((hp, wp, 4), np.uint8)
    bgra[..., 0] = 0xA0 | ((x >> 8) & 3) | (((y >> 8) & 3) << 2)
    bgra[..., 1] = y & 255
    bgra[..., 2] = x & 255
    bgra[..., 3] = 255
    return bgra


class PatternWidget(QWidget):
    img: QImage | None = None

    def paintEvent(self, ev):  # noqa: N802
        if self.img is not None:
            p = QPainter(self)
            p.drawImage(QPointF(0, 0), self.img)
            p.end()


def to_np(shot) -> np.ndarray:
    return np.frombuffer(shot.bgra, np.uint8).reshape(shot.height, shot.width, 4)


def qimage_np(img: QImage) -> np.ndarray:
    img = img.convertToFormat(QImage.Format.Format_RGB32)
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    a = np.frombuffer(ptr, np.uint8).reshape(img.height(), img.bytesPerLine() // 4, 4)
    return a[:, : img.width()].copy()


def frac_equal(a: np.ndarray, pat: np.ndarray) -> float:
    hh, ww = min(a.shape[0], pat.shape[0]), min(a.shape[1], pat.shape[1])
    if hh == 0 or ww == 0:
        return 0.0
    return float((a[:hh, :ww, :3] == pat[:hh, :ww, :3]).all(axis=2).mean())


def foreign_python_rects() -> list:
    me = os.getpid()
    return [x.rect for x in w.list_top_windows(include_untitled=True, include_tool=True)
            if x.pid != me and x.exe and os.path.basename(x.exe).lower().startswith("python")]


def intersects(a, b) -> bool:
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def choose_spot(s, size: QSize) -> QPoint | None:
    """Corner of the available area that avoids other python windows (agent R2a) and the cursor."""
    a, d = s.availableGeometry(), s.devicePixelRatio()
    cur = wt.POINT()
    w.GetCursorPos(ctypes.byref(cur))
    avoid = foreign_python_rects() + [(cur.x - 60, cur.y - 60, 120, 120)]
    mx, my = 30, 30
    for lx, ly in ((a.left() + mx, a.bottom() - size.height() - my), (a.right() - size.width() - mx, a.bottom() - size.height() - my),
                   (a.left() + mx, a.top() + my), (a.right() - size.width() - mx, a.top() + my)):
        px, py = to_phys(s, lx, ly)
        if not any(intersects((px, py, size.width() * d, size.height() * d), r) for r in avoid):
            return QPoint(lx, ly)
    return None


def capture_test(s, do_threads: bool) -> dict:
    import mss
    global sct
    if sct is None:
        sct = mss.MSS()
    size = QSize(400, 150)
    spot = choose_spot(s, size)
    if spot is None:
        return {"screen": s.name(), "skipped": "no free spot"}
    fg_before = w.GetForegroundWindow()
    wdg = make_window(QRect(spot, size), hidden=False, transparent=True, cls=PatternWidget)
    hw = int(wdg.winId())
    x0, y0, wp, hp = w.client_rect_screen(hw)
    pat = pattern(wp, hp)
    img = QImage(pat.tobytes(), wp, hp, wp * 4, QImage.Format.Format_RGB32).copy()
    img.setDevicePixelRatio(wdg.devicePixelRatioF())
    wdg.img = img
    t_show = time.perf_counter()
    wdg.show()
    res: dict = {"screen": s.name(), "dpr": s.devicePixelRatio(), "logical_rect": [spot.x(), spot.y(), 400, 150],
                 "physical_client": [x0, y0, wp, hp], "exstyle": hex(w.GetWindowLongPtrW(hw, w.GWL_EXSTYLE) & 0xFFFFFFFF)}
    m = 4
    frac0, t_match = 0.0, None
    while time.perf_counter() - t_show < 2.0:
        app.processEvents()
        big = to_np(sct.grab({"left": x0 - m, "top": y0 - m, "width": wp + 2 * m, "height": hp + 2 * m}))
        frac0 = frac_equal(big[m:m + hp, m:m + wp], pat)
        if frac0 == 1.0:
            t_match = round((time.perf_counter() - t_show) * 1000)
            break
        time.sleep(0.01)
    best = max(((frac_equal(big[m + dy:m + dy + hp, m + dx:m + dx + wp], pat), dx, dy)
                for dx in range(-m, m + 1) for dy in range(-m, m + 1)))
    res.update({"mss_frac_at_computed_rect": frac0, "ms_until_match": t_match, "best_offset": [best[1], best[2], best[0]],
                "second_best_frac": sorted((frac_equal(big[m + dy:m + dy + hp, m + dx:m + dx + wp], pat)
                                            for dx in range(-m, m + 1) for dy in range(-m, m + 1)))[-2]})
    # QScreen.grabWindow(0, x, y, w, h): x, y logical relative to the screen's top-left
    g, lt = s.geometry(), wdg.mapToGlobal(QPoint(0, 0))
    pm = s.grabWindow(0, lt.x() - g.x(), lt.y() - g.y(), wdg.width(), wdg.height())
    res["grabWindow_screen_relative"] = {"pixmap": [pm.width(), pm.height()], "dpr": pm.devicePixelRatio(),
                                         "frac": frac_equal(qimage_np(pm.toImage()), pat)}
    pm2 = s.grabWindow(0, lt.x(), lt.y(), wdg.width(), wdg.height())
    res["grabWindow_global_logical"] = {"pixmap": [pm2.width(), pm2.height()], "frac": frac_equal(qimage_np(pm2.toImage()), pat)}
    if do_threads:
        res["threads"] = thread_tests(s, (x0, y0, wp, hp), pat, lt.x() - g.x(), lt.y() - g.y(), wdg.width(), wdg.height())
    res["foreground_unchanged"] = w.GetForegroundWindow() == fg_before
    res["foreground_is_mine"] = w.GetForegroundWindow() == hw
    res["visible_ms"] = round((time.perf_counter() - t_show) * 1000)
    sip.delete(wdg)
    app.processEvents()
    return res


class MssThread(QThread):
    def __init__(self, rect, pat, n):
        super().__init__()
        self.rect, self.pat, self.n, self.result = rect, pat, n, None

    def run(self):
        import mss
        try:
            x, y, ww, hh = self.rect
            good = 0
            t = time.perf_counter()
            with mss.MSS() as own:
                for _ in range(self.n):
                    good += frac_equal(to_np(own.grab({"left": x, "top": y, "width": ww, "height": hh})), self.pat) == 1.0
            self.result = {"good": good, "n": self.n, "ms_per_grab": round((time.perf_counter() - t) * 1000 / self.n, 2)}
        except Exception as e:  # noqa: BLE001
            self.result = {"error": repr(e)}


class GrabWindowThread(QThread):
    def __init__(self, screen, xywh, pat):
        super().__init__()
        self.screen_, self.xywh, self.pat, self.result = screen, xywh, pat, None

    def run(self):
        try:
            pm = self.screen_.grabWindow(0, *self.xywh)
            self.result = {"null": pm.isNull(), "pixmap": [pm.width(), pm.height()], "frac": frac_equal(qimage_np(pm.toImage()), self.pat)}
        except Exception as e:  # noqa: BLE001
            self.result = {"error": repr(e)}


def wait_threads(ths) -> None:
    while any(t.isRunning() for t in ths):
        app.processEvents()
        time.sleep(0.005)


def thread_tests(s, rect, pat, rx, ry, lw, lh) -> dict:
    out: dict = {}
    n_msgs = len(MSGS)
    ths = [MssThread(rect, pat, 20) for _ in range(2)]
    for t in ths:
        t.start()
    wait_threads(ths)
    out["one_mss_per_qthread"] = [t.result for t in ths]
    shared_res: list = [None, None, None]

    def worker(i):
        try:
            good = 0
            for _ in range(20):
                good += frac_equal(to_np(sct.grab({"left": rect[0], "top": rect[1], "width": rect[2], "height": rect[3]})), pat) == 1.0
            shared_res[i] = {"good": good, "n": 20}
        except Exception as e:  # noqa: BLE001
            shared_res[i] = {"error": repr(e)}

    pts = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
    for t in pts:
        t.start()
    while any(t.is_alive() for t in pts):
        app.processEvents()
        time.sleep(0.005)
    out["shared_mss_3_threads"] = shared_res
    checkpoint()
    gt = GrabWindowThread(s, (rx, ry, lw, lh), pat)
    gt.start()
    wait_threads([gt])
    out["grabWindow_in_qthread"] = gt.result
    out["qt_messages_during_threads"] = MSGS[n_msgs:]
    return out


def timing_tests() -> dict:
    import mss
    from PIL import Image
    out: dict = {}
    with mss.MSS() as t:
        mons = t.monitors
        out["mss_monitors"] = mons
        prim = next(m for m in mons[1:] if m.get("is_primary"))
        region = {"left": prim["left"] + 200, "top": prim["top"] + 200, "width": 400, "height": 150}
        for name, mon, n in (("primary_full", prim, 20), ("all_monitors", mons[0], 10), ("region_400x150", region, 100)):
            ts = []
            for _ in range(n):
                a = time.perf_counter()
                shot = t.grab(mon)
                ts.append((time.perf_counter() - a) * 1000)
            out[name] = {"size": list(shot.size), "median_ms": round(statistics.median(ts), 2), "min_ms": round(min(ts), 2)}
        out["per_monitor_sizes"] = [list(t.grab(m).size) for m in mons[1:]]
        shot = t.grab(prim)

        def tm(fn, n=20):
            ts = []
            for _ in range(n):
                a = time.perf_counter()
                fn()
                ts.append((time.perf_counter() - a) * 1000)
            return round(statistics.median(ts), 2)

        arr = np.frombuffer(shot.bgra, np.uint8).reshape(shot.height, shot.width, 4)
        out["convert_1080p_ms"] = {
            "frombuffer_reshape_view": tm(lambda: np.frombuffer(shot.bgra, np.uint8).reshape(shot.height, shot.width, 4)),
            "bgr_contiguous_copy": tm(lambda: np.ascontiguousarray(arr[:, :, :3])),
            "rgb_contiguous_copy": tm(lambda: np.ascontiguousarray(arr[:, :, 2::-1])),
            "shot_rgb_bytes": tm(lambda: shot.rgb, 5),
            "PIL_frombytes_BGRX": tm(lambda: Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")),
        }
        del arr, shot  # real screen content is never written anywhere
    return out


if args.visible:
    R["capture"] = []
    for i, s in enumerate(sorted(app.screens(), key=lambda sc: sc is app.primaryScreen())):  # secondary first
        R["capture"].append(capture_test(s, do_threads=(i == 0 and args.timing)))
if args.timing:
    R["timing"] = timing_tests()
if sct is not None:
    sct.close()
R["completed"] = True
checkpoint()
