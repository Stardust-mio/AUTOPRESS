"""wa_drv_stuck.py - Test 6: stuck-key safety. (a) modifiers left down are released by
w.release_all_modifiers() (verified with GetAsyncKeyState); (b) an injector killed with TerminateProcess
mid-typing leaves Shift logically down when down/up are split across SendInput calls, never when each
character is one atomic SendInput batch.

Run from the project root:  .venv/Scripts/python.exe docs/research/scripts/win32/wa_drv_stuck.py
Output: wa_results/wa_result_stuck.json
"""
import os
import random
import subprocess
import sys
import time

import wa_harness as h
import wa_win32 as w

ALL = {"LSHIFT": w.VK_LSHIFT, "RSHIFT": w.VK_RSHIFT, "LCTRL": w.VK_LCONTROL, "RCTRL": w.VK_RCONTROL,
       "LALT": w.VK_LMENU, "RALT": w.VK_RMENU, "LWIN": w.VK_LWIN, "RWIN": w.VK_RWIN,
       "SHIFT": w.VK_SHIFT, "CTRL": w.VK_CONTROL, "ALT": w.VK_MENU}


def down_keys():
    return [n for n, v in ALL.items() if w.key_down(v)]


def kill_pid(pid):
    try:
        os.kill(pid, 9)        # TerminateProcess on Windows: no finally / atexit runs
    except OSError:
        pass


def main():
    w.set_dpi_aware()
    out = {"started": h.now_tag(), "down_at_start": down_keys(), "release": [], "kill": {}}
    t = h.Target("stuck", extra=["--ime", "off"])
    try:
        out["ensure_fg"] = h.ensure_foreground(t)
        g = w.Guard(t.hwnd)
        b = h.Bursts(t)
        # (a) press modifiers without releasing, then run the abort recipe
        for combo in (["LSHIFT"], ["LCTRL"], ["LSHIFT", "LCTRL"], ["RSHIFT", "RCTRL"], ["LSHIFT", "RCTRL"]):
            g.check("hold")
            vks = [ALL[n] for n in combo]
            w.send([w.vk_key(v) for v in vks])
            time.sleep(0.05)
            held = down_keys()
            released = w.release_all_modifiers(pressed_by_us=vks)
            time.sleep(0.05)
            out["release"].append({"pressed": combo, "down_before": held,
                                   "released": [hex(v) for v in released], "down_after": down_keys()})
        # (b) kill an injector at a random moment, 10x per mode
        rnd = random.Random(11)
        pidfile = h.RESULTS / "wa_tmp_child_pid.txt"
        for mode in ("split", "atomic"):
            rows = []
            for i in range(10):
                b.tick()
                if not w.wait_foreground(t.hwnd, 0.1):
                    h.ensure_foreground(t)
                if pidfile.exists():
                    pidfile.unlink()
                p = subprocess.Popen([h.PY, str(h.HERE / "wa_stuck_child.py"), "--hwnd", hex(t.hwnd), "--mode", mode,
                                      "--pidfile", str(pidfile)], cwd=str(h.HERE))
                end = time.time() + 5
                while not pidfile.exists() and time.time() < end:
                    time.sleep(0.01)
                time.sleep(0.05)
                pid = int(pidfile.read_text() or 0)
                time.sleep(rnd.uniform(0.2, 0.6))
                kill_pid(pid)
                p.kill()
                p.wait(5)
                time.sleep(0.05)
                stuck = down_keys()
                rel = w.release_all_modifiers()
                time.sleep(0.05)
                rows.append({"stuck_after_kill": stuck, "released": [hex(v) for v in rel], "down_after_release": down_keys()})
            out["kill"][mode] = {"kills": 10, "shift_stuck": sum("SHIFT" in r["stuck_after_kill"] for r in rows),
                                 "all_clear_after_release": all(not r["down_after_release"] for r in rows), "rows": rows}
            print(mode, {k: v for k, v in out["kill"][mode].items() if k != "rows"}, flush=True)
        out["skips"] = g.skips
        out["gaps"] = b.gaps
    except (w.ForegroundLost, h.UserActive) as e:
        out["aborted"] = repr(e)
    finally:
        out["final_release"] = h.release_safety()
        out["down_at_end"] = down_keys()
        t.close()
    for r in out["release"]:
        print(r)
    print("down_at_end", out["down_at_end"])
    print("saved", h.save_result("stuck", out))


if __name__ == "__main__":
    sys.exit(main())
