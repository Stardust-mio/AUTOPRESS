"""wb_windows_probe.py - window utilities + elevation probe (PMv2 process via QApplication).

Read-only against existing windows/processes. Own test windows are no-focus and shown
briefly on a spot that avoids other python windows and the cursor. Nothing is activated,
no input is injected. Writes OUT.json (full detail, may contain local window titles: keep it
out of the project) and prints an anonymised summary.
usage: python wb_windows_probe.py OUT.json
"""
from __future__ import annotations

import collections
import ctypes
import ctypes.wintypes as wt
import json
import os
import sys
import time
import winreg

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6 import sip  # noqa: E402
from PyQt6.QtCore import QPoint, QRect, QSize, Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

app = QApplication(sys.argv[:1])
import wb_win32 as w  # noqa: E402

GetWindowPlacement_ = w._f(w.user32, "GetWindowPlacement", wt.BOOL, wt.HWND, ctypes.c_void_p)


class WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [("length", wt.UINT), ("flags", wt.UINT), ("showCmd", wt.UINT), ("ptMinPosition", wt.POINT),
                ("ptMaxPosition", wt.POINT), ("rcNormalPosition", wt.RECT)]


def placement(hwnd) -> dict:
    wp = WINDOWPLACEMENT()
    wp.length = ctypes.sizeof(wp)
    GetWindowPlacement_(hwnd, ctypes.byref(wp))
    return {"showCmd": wp.showCmd, "normal": list(w.rect_tuple(wp.rcNormalPosition))}


def pump(ms: int) -> None:
    end = time.perf_counter() + ms / 1000
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.005)


R: dict = {"own_pid": os.getpid(), "own_awareness": w.process_awareness(), "own_token": w.token_info()}
R["own_exe"] = w.exe_path(os.getpid())[0]
fg0 = w.GetForegroundWindow()

# ---- UAC configuration (read-only registry) ----------------------------------------------
try:
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System") as k:
        R["uac"] = {n: winreg.QueryValueEx(k, n)[0] for n in ("EnableLUA", "ConsentPromptBehaviorAdmin", "PromptOnSecureDesktop")}
except OSError as e:
    R["uac"] = {"error": repr(e)}

# ---- 1. existing windows (read-only) ----------------------------------------------------
R["windows"] = []
for x in w.list_top_windows():
    rec = {"hwnd": x.hwnd, "exe": os.path.basename(x.exe) if x.exe else None, "exe_err": x.exe_err, "cls": x.cls,
           "title_len": len(x.title), "iconic": x.iconic, "window_rect": list(x.rect),
           "frame_bounds": list(w.frame_bounds(x.hwnd) or []), "client_screen": list(w.client_rect_screen(x.hwnd)),
           "dpi": w.GetDpiForWindow(x.hwnd), "awareness": w.awareness_name(w.GetWindowDpiAwarenessContext(x.hwnd)),
           "token": w.token_info(x.pid)}
    if x.iconic:
        rec["placement"] = placement(x.hwnd)
    R["windows"].append(rec)

# ---- 2. all processes: which token queries fail, and how --------------------------------
class WTS_PROCESS_INFOW(ctypes.Structure):
    _fields_ = [("SessionId", wt.DWORD), ("ProcessId", wt.DWORD), ("pProcessName", wt.LPWSTR), ("pUserSid", ctypes.c_void_p)]


wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)
WTSEnumerateProcessesW = w._f(wtsapi32, "WTSEnumerateProcessesW", wt.BOOL, wt.HANDLE, wt.DWORD, wt.DWORD,
                              ctypes.POINTER(ctypes.POINTER(WTS_PROCESS_INFOW)), ctypes.POINTER(wt.DWORD))
WTSFreeMemory = w._f(wtsapi32, "WTSFreeMemory", None, ctypes.c_void_p)
pinfo, count = ctypes.POINTER(WTS_PROCESS_INFOW)(), wt.DWORD()
WTSEnumerateProcessesW(None, 0, 1, ctypes.byref(pinfo), ctypes.byref(count))
procs = [(pinfo[i].ProcessId, pinfo[i].SessionId, pinfo[i].pProcessName) for i in range(count.value)]
WTSFreeMemory(pinfo)
own_sess = next(sess for pid, sess, _ in procs if pid == os.getpid())
survey = collections.Counter()
examples: dict = {}
for pid, sess, name in procs:
    where = "own_session" if sess == own_sess else f"session{sess}"
    t = w.token_info(pid)
    key = f"{where}: " + (f"ok IL={t.get('integrity')} elevated={t.get('elevated')} uiaccess={t.get('uiaccess')}" if t["ok"]
                          else f"FAIL {t['step']} err={t['error']}")
    survey[key] += 1
    if not t["ok"] or t.get("integrity") != "medium":
        examples.setdefault(key, set()).add(name)
R["process_survey"] = dict(survey)
R["process_survey_examples"] = {k: sorted(v)[:8] for k, v in examples.items()}
R["n_processes"] = len(procs)

# ---- 3. own windows: WindowFromPoint / GA_ROOT / frame rects / find / IsWindow ----------
own_pid = os.getpid()


def foreign_python_rects() -> list:
    return [x.rect for x in w.list_top_windows(include_untitled=True, include_tool=True)
            if x.pid != own_pid and x.exe and os.path.basename(x.exe).lower().startswith("python")]


def free_spot(screen, size: QSize) -> QPoint | None:
    a = screen.availableGeometry()
    cur = wt.POINT()
    w.GetCursorPos(ctypes.byref(cur))
    avoid = foreign_python_rects() + [(cur.x - 80, cur.y - 80, 160, 160)]
    for lx, ly in ((a.left() + 60, a.bottom() - size.height() - 60), (a.right() - size.width() - 60, a.bottom() - size.height() - 60)):
        r = (lx, ly, size.width(), size.height())  # dpr is 1.0 here (no QT_* variables in this probe)
        if not any(r[0] < b[0] + b[2] and b[0] < r[0] + r[2] and r[1] < b[1] + b[3] and b[1] < r[1] + r[3] for b in avoid):
            return QPoint(lx, ly)
    return None


screens = sorted(app.screens(), key=lambda s: s is app.primaryScreen())  # secondary first
scr = screens[0]
spot = free_spot(scr, QSize(320, 160))
R["own"] = {"screen": scr.name(), "spot": [spot.x(), spot.y()] if spot else None}
if spot is not None:
    base_flags = Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.WindowStaysOnTopHint
    # (a) framed (normal) window: GetWindowRect vs DWM frame vs client
    framed = QWidget(None, base_flags | Qt.WindowType.Window)
    framed.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    framed.setWindowTitle("wb_probe_find_me")
    framed.setGeometry(QRect(spot + QPoint(0, 40), QSize(320, 120)))
    # (b) frameless window with a native child for WindowFromPoint
    plain = QWidget(None, base_flags | Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
    plain.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    plain.setGeometry(QRect(spot + QPoint(400, 0), QSize(200, 100)))
    kid = QWidget(plain)
    kid.setGeometry(20, 20, 60, 40)
    kid.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
    kid.setStyleSheet("background: #3a7")
    # (c) input-transparent window on top of the same spot
    ghost = QWidget(None, base_flags | Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowTransparentForInput)
    ghost.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    ghost.setGeometry(QRect(spot + QPoint(700, 0), QSize(200, 100)))
    hf, hp, hk, hg = int(framed.winId()), int(plain.winId()), int(kid.winId()), int(ghost.winId())
    R["own"]["IsWindowVisible_before_show"] = bool(w.IsWindowVisible(hf))
    t0 = time.perf_counter()
    for wd in (framed, plain, ghost):
        wd.show()
    pump(150)
    kc = w.client_rect_screen(hk)
    pk = (kc[0] + kc[2] // 2, kc[1] + kc[3] // 2)
    pp = (w.client_rect_screen(hp)[0] + 150, w.client_rect_screen(hp)[1] + 80)
    gc = w.client_rect_screen(hg)
    pg = (gc[0] + 100, gc[1] + 50)
    under_g = w.window_from_point_root(*pg)
    fx = w.find_window("python.exe", r"^wb_probe_find_me$")
    R["own"].update({
        "framed": {"window_rect": list(w.window_rect(hf)), "frame_bounds": list(w.frame_bounds(hf) or []),
                   "client_screen": list(w.client_rect_screen(hf)), "qt_frameGeometry": [framed.frameGeometry().x(), framed.frameGeometry().y(),
                   framed.frameGeometry().width(), framed.frameGeometry().height()], "qt_geometry": [framed.x(), framed.y(), framed.width(), framed.height()]},
        "wfp_native_child": {"point": pk, "result_is_child": w.window_from_point_root(*pk)[0] == hk,
                             "root_is_top": w.window_from_point_root(*pk)[1] == hp},
        "wfp_alien_area": {"point": pp, "result_is_top": w.window_from_point_root(*pp)[0] == hp},
        "wfp_transparent_window": {"point": pg, "result_is_ghost": under_g[0] == hg, "root_is_ghost": under_g[1] == hg,
                                   "root_class_below": w.class_name(under_g[1]) if under_g[1] else None},
        "find_window_by_exe_and_title": {"found": fx, "matches_own": fx == hf},
        "IsWindowVisible_shown": bool(w.IsWindowVisible(hf)), "IsIconic_shown": bool(w.IsIconic(hf)),
        "visible_ms": round((time.perf_counter() - t0) * 1000),
        "foreground_unchanged": w.GetForegroundWindow() == fg0,
    })
    for wd in (framed, plain, ghost):
        wd.hide()
    app.processEvents()
    R["own"]["IsWindowVisible_after_hide"] = bool(w.IsWindowVisible(hf))
    R["own"]["IsWindow_after_hide"] = bool(w.IsWindow(hf))
    for wd in (framed, plain, ghost):
        sip.delete(wd)
    app.processEvents()
    R["own"]["IsWindow_after_delete"] = bool(w.IsWindow(hf))
    R["own"]["find_after_delete"] = w.find_window("python.exe", r"^wb_probe_find_me$")

# ---- 4. taskbar hit-test (read-only) ----------------------------------------------------
prim = app.primaryScreen().geometry()
h, root = w.window_from_point_root(prim.x() + prim.width() // 2, prim.y() + prim.height() - 5)
R["taskbar_wfp"] = {"deepest_class": w.class_name(h) if h else None, "root_class": w.class_name(root) if root else None,
                    "deepest_is_root": h == root}
R["foreground_unchanged_end"] = w.GetForegroundWindow() == fg0

with open(sys.argv[1], "w", encoding="utf-8") as fh:
    json.dump(R, fh, indent=1, default=str)

# anonymised summary
print("own:", R["own_pid"], R["own_exe"], R["own_awareness"], R["own_token"], "uac:", R["uac"])
for x in R["windows"]:
    print(" win", x["exe"], x["cls"], "iconic" if x["iconic"] else "", "rect", x["window_rect"], "frame", x["frame_bounds"],
          "client", x["client_screen"], "dpi", x["dpi"], x["awareness"], "token", x["token"], x.get("placement", ""))
print("processes:", R["n_processes"])
for k, v in sorted(R["process_survey"].items()):
    print(f"  {v:4d}  {k}  e.g. {R['process_survey_examples'].get(k, '')}")
print("own windows:", json.dumps(R["own"], default=str))
print("taskbar:", R["taskbar_wfp"], "foreground unchanged:", R["foreground_unchanged_end"])
