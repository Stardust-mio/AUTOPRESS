"""wa_fg_try.py - one foreground-activation attempt from a FRESH process (used by wa_drv_foreground.py).

  python wa_fg_try.py --hwnd 0x1234 --method plain|attach|input|restore|restore_input|routine|input_always --out r.json
Only zero-distance relative mouse moves are injected (methods input / restore_input / routine / input_always).
"""
import argparse
import json
import time

import wa_win32 as w


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hwnd", required=True)
    ap.add_argument("--method", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    w.set_dpi_aware()
    hwnd = int(a.hwnd, 0)
    r = {"method": a.method, "fg_before": w.hwnd_int(w.GetForegroundWindow()), "iconic_before": bool(w.IsIconic(hwnd)),
         "idle_ms_before": w.idle_ms()}
    t0 = time.perf_counter()
    ret = None
    if a.method == "plain":
        ret = w.fg_plain(hwnd)
    elif a.method == "attach":
        ret = w.fg_attach_trick(hwnd)
    elif a.method in ("input", "input_always"):
        ret = w.fg_input_trick(hwnd)
    elif a.method == "restore":
        ret = bool(w.ShowWindow(hwnd, w.SW_RESTORE))
    elif a.method == "restore_input":
        w.ShowWindow(hwnd, w.SW_RESTORE)
        ret = w.fg_input_trick(hwnd)
    elif a.method == "routine":
        ok, used, tries = w.bring_to_foreground(hwnd)
        r.update({"routine_method": used, "routine_tries": tries})
        ret = ok
    r["ret"] = ret
    r["ok"] = w.wait_foreground(hwnd, 0.3)
    r["ms"] = round((time.perf_counter() - t0) * 1000, 1)
    r["fg_after"] = w.hwnd_int(w.GetForegroundWindow())
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(r, f)


if __name__ == "__main__":
    main()
