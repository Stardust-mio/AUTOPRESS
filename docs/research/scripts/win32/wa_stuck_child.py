"""wa_stuck_child.py - injector that gets killed mid-typing by wa_drv_stuck.py (Test 6).

  python wa_stuck_child.py --hwnd 0x1234 --mode split|atomic --pidfile p.txt
split : Shift down / A down / A up / Shift up as SEPARATE SendInput calls with sleeps in between
atomic: the same four events in ONE SendInput call per character
Stops as soon as the target window is not foreground (guard).
"""
import argparse
import os
import time

import wa_win32 as w


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hwnd", required=True)
    ap.add_argument("--mode", required=True)
    ap.add_argument("--pidfile", required=True)
    a = ap.parse_args()
    with open(a.pidfile, "w") as f:
        f.write(str(os.getpid()))
    g = w.Guard(int(a.hwnd, 0))
    sh_d, sh_u = w.vk_key(w.VK_LSHIFT), w.vk_key(w.VK_LSHIFT, True)
    a_d, a_u = w.vk_key(ord("A")), w.vk_key(ord("A"), True)
    end = time.time() + 8
    while time.time() < end:
        g.check()
        if a.mode == "atomic":
            w.send([sh_d, a_d, a_u, sh_u])
            time.sleep(0.02)
        else:
            w.send([sh_d])
            time.sleep(0.02)
            w.send([a_d, a_u])
            time.sleep(0.02)
            w.send([sh_u])
            time.sleep(0.005)


if __name__ == "__main__":
    try:
        main()
    except w.ForegroundLost:
        pass
