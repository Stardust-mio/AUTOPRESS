"""wa_drv_foreground.py - Test 4: bringing the target window to the foreground from a process that is NOT
the foreground process. Before every trial a decoy window (also ours) is made foreground by a separate
helper process; then one method is tried on the target either from a fresh process (wa_fg_try.py) or
in-process from this long-running driver. Verified with GetForegroundWindow.

Run from the project root:  .venv/Scripts/python.exe docs/research/scripts/win32/wa_drv_foreground.py [--trials 10]
Output: wa_results/wa_result_foreground.json
"""
import argparse
import json
import subprocess
import sys
import time

import wa_harness as h
import wa_win32 as w

SW_SHOWNOACTIVATE, SW_SHOWMINNOACTIVE = 4, 7
FRESH = ["plain", "attach", "input", "restore", "restore_input", "routine"]
INPROC = ["inproc_plain", "inproc_attach", "inproc_input", "inproc_restore", "inproc_routine"]


def run_try(hwnd, method):
    out = h.RESULTS / "wa_tmp_fg.json"
    if out.exists():
        out.unlink()
    subprocess.run([h.PY, str(h.HERE / "wa_fg_try.py"), "--hwnd", hex(hwnd), "--method", method, "--out", str(out)],
                   timeout=15, cwd=str(h.HERE))
    with open(out, encoding="utf-8") as f:
        return json.load(f)


def inproc(hwnd, method):
    t0 = time.perf_counter()
    base = method.replace("inproc_", "")
    if base == "plain":
        ret = w.fg_plain(hwnd)
    elif base == "attach":
        ret = w.fg_attach_trick(hwnd)
    elif base == "input":
        ret = w.fg_input_trick(hwnd)
    elif base == "routine":
        ret, used, tries = w.bring_to_foreground(hwnd)
        return {"method": method, "ret": ret, "ok": w.wait_foreground(hwnd, 0.3), "routine_method": used,
                "routine_tries": tries, "ms": round((time.perf_counter() - t0) * 1000, 1)}
    else:
        ret = bool(w.ShowWindow(hwnd, w.SW_RESTORE))
    ok = w.wait_foreground(hwnd, 0.3)
    return {"method": method, "ret": ret, "ok": ok, "ms": round((time.perf_counter() - t0) * 1000, 1)}


def gap(gap_s=2.0):
    before = w.last_input_tick()
    time.sleep(gap_s)
    return w.last_input_tick() != before      # True = somebody (the user) produced input during the gap


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=10)
    ap.add_argument("--methods", default=",".join(FRESH + INPROC), help="comma list; default all")
    ap.add_argument("--tag", default="", help="suffix for the result file name")
    a = ap.parse_args()
    w.set_dpi_aware()
    out = {"started": h.now_tag(), "lock_timeout_ms": None, "trials": [], "decoy_activation": []}
    v = w.W.DWORD()
    w.user32.SystemParametersInfoW(0x2000, 0, w.ctypes.byref(v), 0)
    out["lock_timeout_ms"] = v.value
    T = h.Target("fg_target", pos="300,300", extra=["--ime", "off"])
    D = h.Target("fg_decoy", pos="900,300", extra=["--ime", "off"])
    try:
        time.sleep(0.5)
        out["fg_after_launch"] = {"is_target": w.hwnd_int(w.GetForegroundWindow()) == T.hwnd,
                                  "is_decoy": w.hwnd_int(w.GetForegroundWindow()) == D.hwnd}
        burst0 = time.perf_counter()
        methods = a.methods.split(",")
        out["methods"] = methods
        for trial in range(a.trials):
            for method in methods:
                if time.perf_counter() - burst0 > 14:
                    if gap():
                        raise RuntimeError("user input during gap - aborting")
                    burst0 = time.perf_counter()
                if w.IsIconic(T.hwnd):
                    w.ShowWindow(T.hwnd, SW_SHOWNOACTIVATE)
                    time.sleep(0.1)
                dr = run_try(D.hwnd, "input_always")
                if not dr["ok"]:
                    dr = run_try(D.hwnd, "routine")
                out["decoy_activation"].append({"ok": dr["ok"], "ret": dr["ret"], "method": dr.get("routine_method", "input")})
                if not w.wait_foreground(D.hwnd, 0.3):
                    out["trials"].append({"method": method, "skipped": "decoy not foreground"})
                    continue
                if "restore" in method:
                    w.ShowWindow(T.hwnd, SW_SHOWMINNOACTIVE)
                    time.sleep(0.15)
                    if not w.IsIconic(T.hwnd) or not w.wait_foreground(D.hwnd, 0.2):
                        out["trials"].append({"method": method, "skipped": "could not minimize"})
                        continue
                r = inproc(T.hwnd, method) if method.startswith("inproc") else run_try(T.hwnd, method)
                r["trial"] = trial
                out["trials"].append(r)
        summ = {}
        for r in out["trials"]:
            s = summ.setdefault(r["method"], {"n": 0, "ok": 0, "ret_true": 0, "skipped": 0, "routine_methods": {}})
            if "skipped" in r:
                s["skipped"] += 1
                continue
            s["n"] += 1
            s["ok"] += bool(r["ok"])
            s["ret_true"] += bool(r.get("ret"))
            if r.get("routine_method"):
                s["routine_methods"][r["routine_method"]] = s["routine_methods"].get(r["routine_method"], 0) + 1
        out["summary"] = summ
        for k, s in summ.items():
            print(f"{k:16s} ok {s['ok']}/{s['n']} ret_true {s['ret_true']} skipped {s['skipped']} {s['routine_methods']}")
        da = out["decoy_activation"]
        print("decoy activation ok", sum(d["ok"] for d in da), "/", len(da))
    except Exception as e:
        out["aborted"] = repr(e)
        print("ABORTED", e)
    finally:
        h.release_safety()
        for t in (T, D):
            if w.IsIconic(t.hwnd):
                w.ShowWindow(t.hwnd, SW_SHOWNOACTIVATE)
            t.close()
    print("saved", h.save_result("foreground" + a.tag, out))


if __name__ == "__main__":
    sys.exit(main())
