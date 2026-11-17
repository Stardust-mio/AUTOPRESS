"""wa_drv_hotkey.py - Test 5: RegisterHotKey + Qt (nativeEvent / QAbstractNativeEventFilter), MOD_NOREPEAT,
duplicate registration error, unregister on close, hotkey injected with SendInput while ANOTHER process
(wa_target_app) is foreground. Hotkey: Ctrl+Shift+F9 (no Alt / Win keys are ever injected).

Run from the project root:  .venv/Scripts/python.exe docs/research/scripts/win32/wa_drv_hotkey.py
Output: wa_results/wa_result_hotkey.json
"""
import sys
import time

import wa_harness as h
import wa_win32 as w

VK = w.VK_F9
WM_APP = 0x8000


def hk_app(name, *args):
    return h.Target(name, app="wa_hotkey_app.py", extra=list(args))


def inject_hotkey(g, n=1, gap=0.15):
    for _ in range(n):
        g.check("hotkey")
        w.send(w.combo_inputs([w.VK_LCONTROL, w.VK_LSHIFT, VK]))
        time.sleep(gap)


def inject_autorepeat(g, repeats=6):
    """Ctrl+Shift down, F9 down x repeats (what keyboard auto-repeat produces), then all up."""
    g.check("autorepeat")
    w.send([w.vk_key(w.VK_LCONTROL), w.vk_key(w.VK_LSHIFT)])
    try:
        for _ in range(repeats):
            g.check("autorepeat")
            w.send([w.vk_key(VK)])
            time.sleep(0.03)
    finally:
        w.send([w.vk_key(VK, True), w.vk_key(w.VK_LSHIFT, True), w.vk_key(w.VK_LCONTROL, True)])
    time.sleep(0.2)


def hotkeys(app, mark=0):
    return app.since(mark, "hotkey")


def main():
    w.set_dpi_aware()
    out = {"started": h.now_tag(), "steps": {}}
    apps = []
    T = None
    try:
        H1 = hk_app("hk1", "--mode", "nativeevent", "--norepeat", "1", "--ret", "int")
        apps.append(H1)
        T = h.Target("hk_target", extra=["--ime", "off"])
        out["H1_register"] = H1.read_info()
        out["ensure_fg"] = h.ensure_foreground(T)
        g = w.Guard(T.hwnd)
        b = h.Bursts(T)
        # 1) basic: 5 injected hotkeys while the target (other process) is foreground
        b.tick()
        m1, mt = H1.mark(), T.mark()
        inject_hotkey(g, 5)
        time.sleep(0.2)
        hk = hotkeys(H1, m1)
        tkeys = [e for e in T.since(mt, "key") if e["w"] == "edit"]
        out["steps"]["basic_nativeevent"] = {
            "injected": 5, "received": len(hk), "via": sorted({e["via"] for e in hk}),
            "lparam_mods_vk": sorted({(e["mods"], e["vk"]) for e in hk}),
            "target_saw_F9": [(e["kind"], e["vk"]) for e in tkeys if e["vk"] == VK],
            "target_saw_modifiers": sorted({(e["kind"], e["vk"]) for e in tkeys if e["vk"] in (16, 17)})}
        # 2) auto-repeat with MOD_NOREPEAT
        b.tick()
        m1 = H1.mark()
        inject_autorepeat(g, 6)
        out["steps"]["autorepeat_norepeat"] = {"keydowns": 6, "received": len(hotkeys(H1, m1))}
        # 3) duplicate registration from another process
        H2 = hk_app("hk2", "--mode", "nativeevent")
        apps.append(H2)
        out["steps"]["dup_other_process"] = H2.read_info()
        h.ensure_foreground(T)
        # 4) close H1 -> unregister, then a new process can register the same combo
        H1.close()
        H1.poll()
        out["steps"]["H1_unregister"] = [e for e in H1.events if e["ev"] == "unregister"]
        H3 = hk_app("hk3", "--mode", "filter", "--norepeat", "0", "--ret", "voidptr")
        apps.append(H3)
        out["steps"]["register_after_close"] = H3.read_info()
        out["ensure_fg2"] = h.ensure_foreground(T)
        # 5) filter variant (window hotkey), no MOD_NOREPEAT
        b.tick()
        m3 = H3.mark()
        inject_hotkey(g, 3)
        time.sleep(0.2)
        hk = hotkeys(H3, m3)
        out["steps"]["filter_window_hotkey"] = {"injected": 3, "sightings": len(hk), "via": [e["via"] for e in hk][:6],
                                                "msg_hwnd_nonzero": all(e["msg_hwnd"] for e in hk)}
        b.tick()
        m3 = H3.mark()
        inject_autorepeat(g, 6)
        hk = hotkeys(H3, m3)
        out["steps"]["autorepeat_without_norepeat"] = {"keydowns": 6, "sightings": len(hk),
                                                       "dispatcher_sightings": sum("dispatcher" in e["via"] for e in hk)}
        H3.close()
        H2.close()
        # 5b) filter variant that returns True for WM_HOTKEY (consumes it)
        H3b = hk_app("hk3b", "--mode", "filter", "--norepeat", "1", "--filter-consume")
        apps.append(H3b)
        h.ensure_foreground(T)
        b.tick()
        m = H3b.mark()
        inject_hotkey(g, 3)
        time.sleep(0.2)
        hk = hotkeys(H3b, m)
        out["steps"]["filter_window_hotkey_consume"] = {"injected": 3, "sightings": len(hk)}
        H3b.close()
        # 6) thread hotkey (hwnd NULL) + filter
        H4 = hk_app("hk4", "--mode", "filter_thread", "--norepeat", "1")
        apps.append(H4)
        out["steps"]["thread_register"] = H4.read_info()
        h.ensure_foreground(T)
        b.tick()
        m4 = H4.mark()
        inject_hotkey(g, 3)
        time.sleep(0.2)
        hk = hotkeys(H4, m4)
        out["steps"]["filter_thread_hotkey"] = {"injected": 3, "sightings": len(hk), "via": sorted({e["via"] for e in hk}),
                                                "msg_hwnd": sorted({e["msg_hwnd"] for e in hk})}
        H4.close()
        # 7) does receiving WM_HOTKEY let the receiver take the foreground? (control: posted WM_APP+1)
        H5 = hk_app("hk5", "--mode", "nativeevent", "--activate-on-hotkey")
        apps.append(H5)
        time.sleep(0.6)                             # H5 uses up its fresh-process activation right at startup
        out["ensure_fg3"] = h.ensure_foreground(T)
        m5 = H5.mark()
        w.PostMessageW(H5.hwnd, WM_APP + 1, 0, 0)   # control: no input involved
        time.sleep(0.3)
        out["ensure_fg4"] = h.ensure_foreground(T)
        g = w.Guard(T.hwnd)
        inject_hotkey(g, 1)
        time.sleep(0.3)
        out["steps"]["activate_on_hotkey"] = [{k: e[k] for k in ("why", "ret", "fg_is_me")}
                                              for e in H5.since(0, "activate_try")]
        out["ensure_fg5"] = h.ensure_foreground(T)
        H5.close()
        out["skips"] = g.skips
        out["gaps"] = b.gaps
    except (w.ForegroundLost, h.UserActive) as e:
        out["aborted"] = repr(e)
        print("ABORTED", e)
    finally:
        out["released_modifiers"] = h.release_safety()
        out["keys_down_after"] = {hex(v): w.key_down(v) for v in (w.VK_SHIFT, w.VK_CONTROL, VK)}
        for a in apps:
            if a.proc.poll() is None:
                a.close()
        if T:
            T.close()
    for k, v in out["steps"].items():
        print(k, v)
    print("saved", h.save_result("hotkey", out))


if __name__ == "__main__":
    sys.exit(main())
