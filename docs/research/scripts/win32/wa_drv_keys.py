"""wa_drv_keys.py - Test 2: special keys / combos, extended-key flag, clear-field recipes, Enter latency.

Run from the project root:  .venv/Scripts/python.exe docs/research/scripts/win32/wa_drv_keys.py
Output: wa_results/wa_result_keys.json (target logs raw input too: --rawinput).
"""
import random
import statistics as st
import sys
import time

import wa_harness as h
import wa_win32 as w

QT_KEYPAD = 0x20000000


def main():
    w.set_dpi_aware()
    out = {"started": h.now_tag(), "numlock": w.GetKeyState(w.VK_NUMLOCK) & 1, "checks": [], "notes": []}
    t = h.Target("keys", extra=["--ime", "off", "--rawinput"])
    try:
        out["ensure_fg"] = h.ensure_foreground(t)
        g = w.Guard(t.hwnd)
        b = h.Bursts(t)

        def key(vk, ext=None, mods=()):
            g.check(f"vk{vk:#x}")
            seq = [w.vk_key(m) for m in mods] + [w.vk_key(vk, False, extended=ext), w.vk_key(vk, True, extended=ext)]
            seq += [w.vk_key(m, True) for m in reversed(mods)]
            w.send(seq)
            time.sleep(0.03)

        def scan_only(sc, ext):
            g.check(f"scan{sc:#x}")
            f = w.KEYEVENTF_SCANCODE | (w.KEYEVENTF_EXTENDEDKEY if ext else 0)
            w.send([w.kbd(0, sc, f), w.kbd(0, sc, f | w.KEYEVENTF_KEYUP)])
            time.sleep(0.03)

        def typ(s):
            w.type_text(s, g, "unicode", 0)

        def check(name, expect):
            time.sleep(0.12)
            got = t.last_text()
            out["checks"].append({"name": name, "expect": expect, "got": got, "ok": got == expect})

        def clear():
            if t.last_text():
                m = t.mark()
                w.clear_field(g)
                t.wait_text("", m, 0.6, 0.15)

        clear()
        typ("ABCD-1234"); check("type", "ABCD-1234")
        key(w.VK_HOME); typ("X"); check("Home(ext)+X", "XABCD-1234")
        key(w.VK_END); typ("Y"); check("End(ext)+Y", "XABCD-1234Y")
        key(w.VK_LEFT); key(w.VK_LEFT); key(w.VK_DELETE); check("Left,Left,Delete(ext)", "XABCD-123Y")
        key(w.VK_BACK); check("Backspace", "XABCD-12Y")
        key(w.VK_RIGHT); typ("Z"); check("Right(ext)+Z", "XABCD-12YZ")
        m = t.mark()
        key(w.VK_UP); key(w.VK_DOWN)
        out["up_down_events"] = [(e["kind"], e["key"], e["sc"]) for e in t.since(m, "key") if e["w"] == "edit"]
        key(ord("A"), mods=[w.VK_LCONTROL]); key(w.VK_BACK); check("Ctrl+A,Backspace", "")
        # Enter -> submit
        b.tick()
        typ("ENTER-TEST")
        m = t.mark()
        key(w.VK_RETURN)
        subs = t.since(m, "submit")
        out["checks"].append({"name": "Enter->submit", "expect": "ENTER-TEST",
                              "got": subs[-1]["text"] if subs else None, "ok": bool(subs) and subs[-1]["text"] == "ENTER-TEST"})
        # Tab / Shift+Tab focus moves
        m = t.mark()
        key(w.VK_TAB); time.sleep(0.1)
        f1 = [(e["w"], e["kind"]) for e in t.since(m, "focus")]
        m = t.mark()
        key(w.VK_TAB, mods=[w.VK_LSHIFT]); time.sleep(0.1)
        f2 = [(e["w"], e["kind"]) for e in t.since(m, "focus")]
        out["checks"].append({"name": "Tab moves focus edit->submit", "got": f1, "ok": ("submit", "in") in f1})
        out["checks"].append({"name": "Shift+Tab back to edit", "got": f2, "ok": ("edit", "in") in f2})
        m = t.mark()
        key(w.VK_ESCAPE); time.sleep(0.1)
        esc = [e for e in t.since(m, "key") if e["w"] == "edit" and e["key"] == 0x01000000]
        out["checks"].append({"name": "Esc reaches edit", "got": len(esc), "ok": len(esc) >= 1})
        # Extended flag: VK_LEFT with / without KEYEVENTF_EXTENDEDKEY, scan-code-only injection
        clear(); typ("AB")
        m = t.mark()
        key(w.VK_LEFT, ext=False); typ("X")
        ev = [e for e in t.since(m, "key") if e["w"] == "edit" and e["kind"] == "down" and e["vk"] == w.VK_LEFT]
        raw = [e for e in t.since(m, "raw") if e["vk"] == w.VK_LEFT]
        out["left_no_ext"] = {"qt": [(e["sc"], bool(e["mods"] & QT_KEYPAD)) for e in ev],
                              "raw": [(e["mk"], e["fl"]) for e in raw]}
        check("VK_LEFT without EXTENDEDKEY still moves caret (Qt)", "AXB")
        m = t.mark()
        key(w.VK_LEFT, ext=True)
        ev = [e for e in t.since(m, "key") if e["w"] == "edit" and e["kind"] == "down" and e["vk"] == w.VK_LEFT]
        raw = [e for e in t.since(m, "raw") if e["vk"] == w.VK_LEFT]
        out["left_ext"] = {"qt": [(e["sc"], bool(e["mods"] & QT_KEYPAD)) for e in ev],
                           "raw": [(e["mk"], e["fl"]) for e in raw]}
        clear(); typ("AB")
        m = t.mark()
        scan_only(0x4B, ext=False)
        time.sleep(0.1)
        out["scan_0x4B_no_ext"] = {"text": t.last_text(),
                                   "keys": [(e["vk"], e["sc"], e["text"]) for e in t.since(m, "key") if e["w"] == "edit" and e["kind"] == "down"]}
        m = t.mark()
        scan_only(0x4B, ext=True); typ("X")
        time.sleep(0.15)
        out["scan_0x4B_ext"] = {"text": t.last_text(),
                                "keys": [(e["vk"], e["sc"]) for e in t.since(m, "key") if e["w"] == "edit" and e["kind"] == "down"]}
        # wVk-only (wScan=0) vs wVk+scan: what raw-input / DirectInput style readers see
        m = t.mark()
        g.check("vk-only")
        w.send([w.kbd(ord("Q"), 0, 0), w.kbd(ord("Q"), 0, w.KEYEVENTF_KEYUP)])
        time.sleep(0.05)
        w.type_text("Q", g, "vk", 0)
        w.type_text("Q", g, "unicode", 0)
        time.sleep(0.1)
        out["raw_q"] = [(e["vk"], e["mk"], e["fl"], e["dev"], e["extra"]) for e in t.since(m, "raw")]
        out["qt_q"] = [(e["vk"], e["sc"], e["text"]) for e in t.since(m, "key") if e["w"] == "edit" and e["kind"] == "down"]
        # Enter latency (inject -> submit event), 20 runs
        lat = []
        for i in range(20):
            b.tick()
            clear(); typ(f"E{i}")
            time.sleep(0.03)
            m = t.mark()
            g.check("enter")
            t0 = time.perf_counter_ns()
            w.send(w.combo_inputs([w.VK_RETURN]))
            r, _ = t.wait(lambda evs: [e for e in evs if e["ev"] == "submit"], timeout=1.0, mark=m)
            if r:
                lat.append((r[0]["t_ns"] - t0) / 1e6)
        out["enter_to_submit_ms"] = {"n": len(lat), "median": round(st.median(lat), 2) if lat else None,
                                     "max": round(max(lat), 2) if lat else None}
        # Clear-field recipes, 20 runs each with the caret at a random position
        rnd = random.Random(7)
        recipes = {}
        for method in ("ctrl_a", "end_shift_home", "backspace"):
            ok = 0
            for i in range(20):
                b.tick()
                clear()
                s = "".join(rnd.choice("ABCDEFGH0123456789-") for _ in range(rnd.randint(4, 20)))
                typ(s)
                t.wait_text(s, t.mark() - 0, 0.3, 0.1)
                for _ in range(rnd.randint(0, len(s))):
                    key(w.VK_LEFT)
                m = t.mark()
                w.clear_field(g, method=method, n_backspace=25)
                got, _ = t.wait_text("", m, 0.8, 0.2)
                ok += got == ""
            recipes[method] = {"runs": 20, "cleared": ok}
            print("clear", method, ok, "/20", flush=True)
        out["clear_recipes"] = recipes
        out["skips"] = g.skips
        out["gaps"] = b.gaps
    except (w.ForegroundLost, h.UserActive) as e:
        out["aborted"] = repr(e)
    finally:
        out["released_modifiers"] = h.release_safety()
        t.close()
    for c in out["checks"]:
        print(("OK  " if c["ok"] else "FAIL"), c["name"], c.get("got"))
    for k in ("left_no_ext", "left_ext", "scan_0x4B_no_ext", "scan_0x4B_ext", "raw_q", "qt_q", "enter_to_submit_ms",
              "up_down_events"):
        print(k, out.get(k))
    print("saved", h.save_result("keys", out))


if __name__ == "__main__":
    sys.exit(main())
