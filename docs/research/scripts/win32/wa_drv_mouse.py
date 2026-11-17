"""wa_drv_mouse.py - Test 3: absolute-coordinate normalization over the virtual desktop, clicks on the
target's Submit button (SendInput absolute vs SetCursorPos), edge precision, double-click, cursor restore.

Run from the project root:  .venv/Scripts/python.exe docs/research/scripts/win32/wa_drv_mouse.py
Output: wa_results/wa_result_mouse.json. Part A only MOVES the cursor (no clicks) and restores it.
"""
import random
import statistics as st
import sys
import time

import wa_harness as h
import wa_win32 as w


def wait_cursor(expect, timeout=0.06):
    end = time.perf_counter() + timeout
    p = w.cursor_pos()
    while p != expect and time.perf_counter() < end:
        time.sleep(0.001)
        p = w.cursor_pos()
    return p


def part_a(out):
    vx, vy, vw, vh = w.virtual_screen()
    out["virtual_screen"] = [vx, vy, vw, vh]
    rnd = random.Random(3)
    pts = [(vx, vy), (vx + vw - 1, vy + vh - 1), (vx, vy + vh - 1), (vx + vw - 1, vy), (-1, 500), (0, 500),
           (1, 500), (-1920, 0), (1919, 1079)]
    pts += [(rnd.randint(vx, vx + vw - 1), rnd.randint(vy, vy + vh - 1)) for _ in range(150)]
    old = w.cursor_pos()
    res = {}
    try:
        for formula in ("center", "classic"):
            hits, errs = 0, []
            for (x, y) in pts:
                nx, ny = w.to_absolute(x, y, formula)
                w.send([w.mouse(nx, ny, w.MOUSEEVENTF_MOVE | w.MOUSEEVENTF_ABSOLUTE | w.MOUSEEVENTF_VIRTUALDESK)])
                p = wait_cursor((x, y))
                if p == (x, y):
                    hits += 1
                else:
                    errs.append([x, y, p[0], p[1]])
            res[formula] = {"points": len(pts), "exact": hits, "misses": errs[:10]}
        # Without MOUSEEVENTF_VIRTUALDESK, 0..65535 maps onto the PRIMARY monitor only
        prim = []
        for (nx, ny) in ((0, 0), (65535, 65535), (32768, 32768)):
            w.send([w.mouse(nx, ny, w.MOUSEEVENTF_MOVE | w.MOUSEEVENTF_ABSOLUTE)])
            time.sleep(0.03)
            prim.append([nx, ny, *w.cursor_pos()])
        res["no_virtualdesk"] = prim
    finally:
        w.SetCursorPos(*old)
        res["cursor_restored"] = wait_cursor(old) == old
    out["normalization"] = res


def main():
    w.set_dpi_aware()
    out = {"started": h.now_tag(), "double_click_time_ms": w.user32.GetDoubleClickTime()}
    part_a(out)
    print("normalization", {k: (v["exact"], v["points"]) if isinstance(v, dict) and "exact" in v else v
                            for k, v in out["normalization"].items()}, flush=True)
    t = h.Target("mouse", pos="400,420", extra=["--ime", "off"])
    old = w.cursor_pos()
    try:
        out["ensure_fg"] = h.ensure_foreground(t)
        g = w.Guard(t.hwnd)
        b = h.Bursts(t)
        info = t.read_info()
        out["info"] = info
        L, T, R, B = info["submit_rect"]
        dpr = info["dpr"]
        rnd = random.Random(5)
        methods = {}
        for name, kw in (("sendinput_atomic", dict(method="sendinput")),
                         ("setcursorpos", dict(method="setcursorpos")),
                         ("sendinput_settle30_hold30", dict(method="sendinput", settle_ms=30, hold_ms=30))):
            ok, pos_err, lat = 0, [], []
            prev = (-99, -99)
            for i in range(20):
                b.tick()
                # consecutive points >4 px apart: otherwise 2 clicks within GetDoubleClickTime() and
                # SM_CXDOUBLECLK/SM_CYDOUBLECLK become a double-click (Qt then reports 'dblclick', not 'press')
                while True:
                    x, y = rnd.randint(L + 3, R - 4), rnd.randint(T + 3, B - 4)
                    if abs(x - prev[0]) > 4 or abs(y - prev[1]) > 4:
                        break
                prev = (x, y)
                m = t.mark()
                t0 = time.perf_counter_ns()
                w.click(x, y, g, **kw)
                r, _ = t.wait(lambda evs: [e for e in evs if e["ev"] == "submit"], timeout=1.0, mark=m)
                presses = [e for e in t.since(m, "mouse") if e["w"] == "submit" and e["kind"] in ("press", "dblclick")]
                if r and presses:
                    ok += 1
                    p = presses[0]
                    pos_err.append(max(abs(p["x"] - (x - L) / dpr), abs(p["y"] - (y - T) / dpr)))
                    lat.append((presses[0]["t_ns"] - t0) / 1e6)
                time.sleep(0.05)
            methods[name] = {"runs": 20, "submit_ok": ok, "max_pos_err_px": max(pos_err) if pos_err else None,
                             "press_latency_ms_median": round(st.median(lat), 2) if lat else None}
            print(name, methods[name], flush=True)
        out["click_methods"] = methods
        # Edge precision: 1 px inside each corner (should submit) and 1 px outside (should not)
        edge = []
        for (x, y, inside) in ((L, T, True), (R - 1, T, True), (L, B - 1, True), (R - 1, B - 1, True),
                               (L - 1, T + 5, False), (R, T + 5, False), (L + 5, T - 1, False), (L + 5, B, False)):
            b.tick()
            m = t.mark()
            w.click(x, y, g, method="sendinput")
            time.sleep(0.15)
            got = bool(t.since(m, "submit"))
            edge.append({"pt": [x, y], "inside": inside, "submitted": got, "ok": got == inside})
        out["edge_precision"] = edge
        print("edge", [e["ok"] for e in edge], flush=True)
        # Double-click on the line edit
        E = info["edit_rect"]
        dbl = {}
        for name, kw in (("atomic", dict()), ("hold20_gap", dict(settle_ms=20, hold_ms=20))):
            ok = 0
            for i in range(20):
                b.tick()
                x, y = rnd.randint(E[0] + 5, E[2] - 6), rnd.randint(E[1] + 3, E[3] - 4)
                m = t.mark()
                w.click(x, y, g, method="sendinput", double=True, **kw)
                time.sleep(0.12)
                ok += any(e["kind"] == "dblclick" and e["w"] == "edit" for e in t.since(m, "mouse"))
                time.sleep(w.user32.GetDoubleClickTime() / 1000 + 0.05)   # avoid triple-click chaining
            dbl[name] = {"runs": 20, "dblclick_events": ok}
        out["double_click"] = dbl
        print("double", dbl, flush=True)
        # Two SINGLE clicks on the same spot: 100 ms apart vs > GetDoubleClickTime() apart
        chain = {}
        for name, gap_s in (("gap_100ms", 0.1), ("gap_dblclicktime_plus_100ms", w.user32.GetDoubleClickTime() / 1000 + 0.1)):
            kinds, subs = [], 0
            for i in range(5):
                b.tick()
                time.sleep(w.user32.GetDoubleClickTime() / 1000 + 0.1)
                x, y = L + 20 + 10 * i, (T + B) // 2
                m = t.mark()
                w.click(x, y, g, method="sendinput")
                time.sleep(gap_s)
                w.click(x, y, g, method="sendinput")
                time.sleep(0.15)
                kinds.append([e["kind"] for e in t.since(m, "mouse") if e["w"] == "submit" and e["kind"] != "release"])
                subs += len(t.since(m, "submit"))
            chain[name] = {"pairs": 5, "second_click_was_dblclick": sum(k[-1:] == ["dblclick"] for k in kinds),
                           "submits_of_10_clicks": subs, "kinds": kinds}
        out["single_click_chaining"] = chain
        print("chaining", {k: v["second_click_was_dblclick"] for k, v in chain.items()}, flush=True)
        # Click -> focus latency (focus on Submit first, then click the edit)
        lat = []
        for i in range(10):
            b.tick()
            w.click((L + R) // 2, (T + B) // 2, g, method="sendinput")
            time.sleep(0.1)
            m = t.mark()
            t0 = time.perf_counter_ns()
            w.click((E[0] + E[2]) // 2, (E[1] + E[3]) // 2, g, method="sendinput")
            r, _ = t.wait(lambda evs: [e for e in evs if e["ev"] == "focus" and e["w"] == "edit" and e["kind"] == "in"],
                          timeout=1.0, mark=m)
            if r:
                lat.append((r[0]["t_ns"] - t0) / 1e6)
        out["click_to_focus_ms"] = {"n": len(lat), "median": round(st.median(lat), 2) if lat else None,
                                    "max": round(max(lat), 2) if lat else None}
        print("click->focus", out["click_to_focus_ms"], flush=True)
        # restore_cursor option
        before = w.cursor_pos()
        w.click((L + R) // 2, (T + B) // 2, g, method="sendinput", restore_cursor=True)
        out["restore_cursor_option"] = {"before": before, "after": wait_cursor(before, 0.1)}
        out["skips"] = g.skips
        out["gaps"] = b.gaps
    except (w.ForegroundLost, h.UserActive) as e:
        out["aborted"] = repr(e)
        print("ABORTED", e)
    finally:
        h.release_safety()
        w.SetCursorPos(*old)
        out["cursor_restored_end"] = wait_cursor(old, 0.1) == old
        t.close()
    print("saved", h.save_result("mouse", out))


if __name__ == "__main__":
    sys.exit(main())
