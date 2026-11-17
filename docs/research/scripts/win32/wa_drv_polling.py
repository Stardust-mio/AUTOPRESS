"""wa_drv_polling.py - Test 8 support: what a game that POLLS key state once per frame (GetAsyncKeyState
every 16 ms, like many engines' gameplay input) or reads raw input / DirectInput-style scan codes would see,
versus the message path (WM_CHAR -> text box) that the Qt target uses.

Run from the project root:  .venv/Scripts/python.exe docs/research/scripts/win32/wa_drv_polling.py
Output: wa_results/wa_result_polling.json
"""
import sys
import time

import wa_harness as h
import wa_win32 as w

TEXT = "abcdefghij"


def main():
    w.set_dpi_aware()
    out = {"started": h.now_tag(), "text": TEXT, "configs": []}
    t = h.Target("polling", extra=["--ime", "off", "--poll", "--rawinput"])
    try:
        out["ensure_fg"] = h.ensure_foreground(t)
        g = w.Guard(t.hwnd)
        b = h.Bursts(t)
        for mode, hold, delay in (("vk", 0, 30), ("vk", 10, 30), ("vk", 20, 30), ("vk", 40, 30), ("unicode", 0, 30)):
            agg = {"mode": mode, "hold_ms": hold, "delay_ms": delay, "runs": 5, "keys": 0, "text_ok": 0,
                   "poll_edges": 0, "poll_edge_or_lsb": 0, "raw_keydowns": 0}
            for _ in range(5):
                b.tick()
                if t.last_text():
                    m = t.mark()
                    w.clear_field(g)
                    t.wait_text("", m, 0.6, 0.15)
                time.sleep(0.05)
                m = t.mark()
                w.type_text(TEXT, g, mode=mode, delay_ms=delay, hold_ms=hold)
                final, _ = t.wait_text(TEXT, m, 1.0, 0.25)
                time.sleep(0.05)
                evs = t.since(m)
                letters = {ord(c.upper()) for c in TEXT}
                edges = {e["vk"] for e in evs if e["ev"] == "poll_edge" and e["vk"] in letters}
                lsb = {e["vk"] for e in evs if e["ev"] == "poll_lsb" and e["vk"] in letters}
                raw = [e for e in evs if e["ev"] == "raw" and e["vk"] in letters and not (e["fl"] & 1)]
                agg["keys"] += len(TEXT)
                agg["text_ok"] += final == TEXT
                agg["poll_edges"] += len(edges)
                agg["poll_edge_or_lsb"] += len(edges | lsb)
                agg["raw_keydowns"] += len(raw)
            out["configs"].append(agg)
            print(agg, flush=True)
        out["skips"] = g.skips
        out["gaps"] = b.gaps
    except (w.ForegroundLost, h.UserActive) as e:
        out["aborted"] = repr(e)
    finally:
        out["released"] = h.release_safety()
        t.close()
    print("saved", h.save_result("polling", out))


if __name__ == "__main__":
    sys.exit(main())
