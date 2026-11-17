"""wa_drv_typing.py - Test 1 (typing modes) + IME / CapsLock variants, against wa_target_app.py.

Run from the project root with the project venv (each burst of real input <= ~14 s, 2 s gaps; the run
aborts if the user touches mouse/keyboard during a gap):
  .venv/Scripts/python.exe docs/research/scripts/win32/wa_drv_typing.py --plan main   # IME disabled field
  .venv/Scripts/python.exe docs/research/scripts/win32/wa_drv_typing.py --plan ime    # IME (zh-TW Bopomofo) on
  .venv/Scripts/python.exe docs/research/scripts/win32/wa_drv_typing.py --plan cliprestore
Options: --runs N (default 20). Output: wa_results/wa_result_typing_<plan>.json
The user's clipboard (all HGLOBAL formats) is snapshotted first and restored at the end; CapsLock is
restored to its original state.
"""
import argparse
import statistics as st
import sys
import time

import wa_harness as h
import wa_win32 as w

STRINGS = ["ABCD-1234-EFGH", "AbC-123_xyz", "a1B2c3D4e5F6g7H8", "測試ABC"]
ASCII = STRINGS[:3]
SENTINEL = "WA-SENTINEL-OLD"


class UserActive(RuntimeError):
    pass


class Bursts:
    def __init__(self, t, burst_s=14.0, gap_s=2.0):
        self.t, self.burst_s, self.gap_s = t, burst_s, gap_s
        self.t0 = time.perf_counter()
        self.gaps = []

    def tick(self):
        if time.perf_counter() - self.t0 < self.burst_s:
            return
        h.release_safety()
        time.sleep(self.gap_s)
        active = w.user_active_since_our_input(slack_ms=200)
        fg_ok = w.hwnd_int(w.GetForegroundWindow()) == self.t.hwnd
        self.gaps.append({"user_active": active, "fg_ok": fg_ok})
        if active or not fg_ok:
            raise UserActive(f"gap check: user_active={active} fg_ok={fg_ok}")
        self.t0 = time.perf_counter()


def run_one(t, g, mode, s, delay, restore_delay, ime_on):
    if ime_on:
        w.press(w.VK_ESCAPE, g, what="esc")          # cancel any IME composition left over
        time.sleep(0.01)
    if t.last_text() != "":
        m = t.mark()
        w.clear_field(g)
        t.wait_text("", m, timeout=0.6, quiet_s=0.15)
    m = t.mark()
    t0 = time.perf_counter_ns()
    if mode == "clip":
        w.paste_text(s, g, restore=True, restore_delay_ms=restore_delay)
    else:
        w.type_text(s, g, mode=mode, delay_ms=delay)
    t1 = time.perf_counter_ns()
    final, tf = t.wait_text(s, m, timeout=1.5, quiet_s=0.3)
    return {"ok": final == s, "final": final, "inj_ms": (t1 - t0) / 1e6,
            "e2e_ms": (tf - t0) / 1e6 if tf else None}


def summarize(rows):
    oks = [r for r in rows if r["ok"]]
    e2e = [r["e2e_ms"] for r in oks if r["e2e_ms"]]
    n = len(rows[0]["s"]) if rows else 0
    return {"runs": len(rows), "exact": len(oks), "rate": round(len(oks) / len(rows), 3) if rows else None,
            "e2e_ms_median": round(st.median(e2e), 2) if e2e else None,
            "cps_median": round(n / (st.median(e2e) / 1000), 1) if e2e else None,
            "fails": sorted({r["final"] for r in rows if not r["ok"]})[:5]}


def set_caps(t, g, want):
    if w.caps_lock_on() != want:
        w.press(w.VK_CAPITAL, g, what="capslock")
        time.sleep(0.15)
    return w.caps_lock_on() == want


def build_plan(plan):
    items = []   # (label, mode, strings, delays, caps, restore_delay, ime_action)
    if plan == "main":
        items += [("unicode", "unicode", STRINGS, [0, 5, 15], False, 0, None),
                  ("vk", "vk", ASCII, [0, 5, 15], False, 0, None),
                  ("vk_capslock_on", "vk", ASCII, [0, 5, 15], True, 0, None),
                  ("unicode_capslock_on", "unicode", ASCII, [0], True, 0, None),
                  ("clip", "clip", STRINGS, [0], False, 100, None),
                  ("clip_capslock_on", "clip", ASCII[:1], [0], True, 100, None)]
    elif plan == "ime":
        items += [("ime_unicode", "unicode", STRINGS, [5], False, 0, None),
                  ("ime_vk", "vk", ASCII, [5], False, 0, None),
                  ("ime_clip", "clip", STRINGS, [0], False, 100, None),
                  ("ime_closed_vk", "vk", ASCII, [5], False, 0, "close")]
    elif plan == "cliprestore":
        for rd in (0, 2, 10, 30, 100):
            items.append((f"clip_restore_{rd}ms", "clip", ASCII[:1], [0], False, rd, None))
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", default="main", choices=["main", "ime", "cliprestore"])
    ap.add_argument("--runs", type=int, default=20)
    a = ap.parse_args()
    w.set_dpi_aware()
    ime_on = a.plan == "ime"
    out = {"plan": a.plan, "started": h.now_tag(), "layout": hex(w.GetKeyboardLayout(0) or 0), "results": [],
           "notes": []}
    snap = w.clipboard_snapshot()
    out["clipboard_formats_saved"] = [(f, n, len(d)) for f, n, d in snap]
    caps0 = w.caps_lock_on()
    t = h.Target(f"typing_{a.plan}", extra=["--ime", "on" if ime_on else "off"])
    ime0 = None
    try:
        out["ensure_fg"] = h.ensure_foreground(t)
        g = w.Guard(t.hwnd)
        ime0 = w.ime_query(t.hwnd)
        out["ime_state_start_xproc"] = ime0
        w.set_clipboard_text(SENTINEL)
        b = Bursts(t)
        for label, mode, strings, delays, caps, rd, ime_action in build_plan(a.plan):
            if not set_caps(t, g, caps):
                out["notes"].append(f"{label}: could not set CapsLock={caps}")
                continue
            if ime_action == "close":
                out["ime_close_sent"] = w.ime_set_open(t.hwnd, False)
                time.sleep(0.2)
                out["ime_state_after_close_xproc"] = w.ime_query(t.hwnd)
            for s in strings:
                for d in delays:
                    rows = []
                    for _ in range(a.runs):
                        b.tick()
                        r = run_one(t, g, mode, s, d, rd, ime_on)
                        r["s"] = s
                        rows.append(r)
                    summ = summarize(rows)
                    summ.update({"label": label, "mode": mode, "string": s, "delay_ms": d, "capslock": caps,
                                 "restore_delay_ms": rd})
                    out["results"].append(summ)
                    print(f"{label:22s} {s!r:22} d={d:2d} rd={rd:3d} -> {summ['exact']}/{summ['runs']} "
                          f"cps={summ['cps_median']}", flush=True)
            if ime_action == "close" and ime0 and ime0.get("open") is not None:
                w.ime_set_open(t.hwnd, bool(ime0["open"]))
                time.sleep(0.2)
                out["ime_state_restored_xproc"] = w.ime_query(t.hwnd)
        out["skips"] = g.skips
        out["gaps"] = b.gaps
    except (w.ForegroundLost, UserActive) as e:
        out["aborted"] = repr(e)
        print("ABORTED:", e, flush=True)
    finally:
        out["released_modifiers"] = h.release_safety()
        try:
            if w.caps_lock_on() != caps0:
                if w.hwnd_int(w.GetForegroundWindow()) != t.hwnd:
                    w.bring_to_foreground(t.hwnd)
                set_caps(t, w.Guard(t.hwnd), caps0)
        except Exception as e:
            out["notes"].append(f"caps restore problem: {e!r}")
        out["capslock_restored"] = w.caps_lock_on() == caps0
        w.clipboard_restore(snap)
        out["clipboard_restored"] = [(f, len(d)) for f, n, d in w.clipboard_snapshot()] == \
            [(f, len(d)) for f, n, d in snap]
        t.close()
        t.poll()
        out["ime_states_logged"] = [e["state"] for e in t.events if e["ev"] == "ime_state"][:10]
        p = h.save_result(f"typing_{a.plan}", out)
        print("saved", p, "caps_restored", out["capslock_restored"], "clip_restored", out["clipboard_restored"])


if __name__ == "__main__":
    sys.exit(main())
