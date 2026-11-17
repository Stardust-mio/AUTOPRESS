"""wa_drv_misc.py - ctypes pitfalls and clipboard behaviour (no keystrokes or clicks are injected; only
zero-distance mouse moves for the GetLastInputInfo check). The user's clipboard is snapshotted and restored.

  .venv/Scripts/python.exe docs/research/scripts/win32/wa_drv_misc.py
Output: wa_results/wa_result_misc.json
Checks: INPUT sizes; SendInput with a wrong cbSize; GlobalLock/GlobalAlloc without restype (pointer
truncation); OpenClipboard contention + retry; OpenClipboard(NULL) then SetClipboardData; privacy formats;
MapVirtualKeyExW E0 scan codes; CapsLock-affected keys; GetLastInputInfo update latency after SendInput;
IME detach (Qt WA_InputMethodEnabled vs ImmDisableIME) - launches 3 target windows briefly.
"""
import ctypes
import ctypes.wintypes as W
import subprocess
import sys
import time

import wa_harness as h
import wa_win32 as w

HOLDER = r'''
import ctypes, ctypes.wintypes as W, sys, time
u = ctypes.WinDLL("user32", use_last_error=True)
u.OpenClipboard.argtypes = [W.HWND]
u.CreateWindowExW.restype = W.HWND
u.CreateWindowExW.argtypes = [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, W.HWND, W.HMENU, W.HINSTANCE, W.LPVOID]
hwnd = None
if sys.argv[2] == "hwnd":   # message-only window (HWND_MESSAGE) as clipboard owner
    hwnd = u.CreateWindowExW(0, "STATIC", "wa-holder", 0, 0, 0, 0, 0, W.HWND(-3), None, None, None)
ok = u.OpenClipboard(hwnd)
print("held" if ok else "nohold", flush=True)
time.sleep(float(sys.argv[1]))
u.CloseClipboard()
'''


def main():
    w.set_dpi_aware()
    out = {"started": h.now_tag()}
    out["sizes"] = {"INPUT": ctypes.sizeof(w.INPUT), "MOUSEINPUT": ctypes.sizeof(w.MOUSEINPUT),
                    "KEYBDINPUT": ctypes.sizeof(w.KEYBDINPUT), "HARDWAREINPUT": ctypes.sizeof(w.HARDWAREINPUT)}
    # wrong cbSize: harmless zero mouse move
    arr = (w.INPUT * 1)(w.mouse(0, 0, w.MOUSEEVENTF_MOVE))
    res = {}
    for cb in (28, 32, 36, 40, 44):
        ctypes.set_last_error(0)
        n = w.SendInput(1, arr, cb)
        res[cb] = [n, ctypes.get_last_error()]
    out["sendinput_cbsize"] = res
    # restype pitfall: default restype is c_int (32-bit) -> handles / pointers above 4 GB get truncated
    k = ctypes.WinDLL("kernel32")            # fresh function objects without our prototypes
    raw_alloc, raw_lock = k.GlobalAlloc, k.GlobalLock
    hglob = w.GlobalAlloc(w.GMEM_MOVEABLE, 64)
    p_ok = w.GlobalLock(hglob)
    raw_lock.argtypes = [ctypes.c_void_p]    # argtypes fixed, restype left as default c_int
    p_raw = raw_lock(hglob)
    w.GlobalUnlock(hglob)
    w.GlobalUnlock(hglob)
    w.GlobalFree(hglob)
    out["globallock_restype"] = {"correct": hex(p_ok or 0), "default_c_int": hex(p_raw & 0xFFFFFFFFFFFFFFFF),
                                 "truncated": (p_raw & 0xFFFFFFFFFFFFFFFF) != p_ok}
    h_raw = raw_alloc(w.GMEM_MOVEABLE, 64)   # default argtypes/restype (64 bytes leaked on purpose:
    out["globalalloc_default_handle"] = hex(h_raw & 0xFFFFFFFFFFFFFFFF)   # a truncated handle must not be freed)
    snap = w.clipboard_snapshot()
    try:
        # contention: another process holds the clipboard for 0.4 s, opened with NULL vs a real HWND
        out["contention"] = {}
        for mode in ("null", "hwnd"):
            hp = subprocess.Popen([h.PY, "-c", HOLDER, "0.4", mode], stdout=subprocess.PIPE, text=True)
            held = hp.stdout.readline().strip()
            holder_win = w.hwnd_int(w.GetOpenClipboardWindow())
            ctypes.set_last_error(0)
            first_ok = w.OpenClipboard(None)
            first_err = ctypes.get_last_error()
            if first_ok:
                w.CloseClipboard()
            t0 = time.perf_counter()
            attempts = w.set_clipboard_text("WA-CONTENTION-TEST")
            out["contention"][mode] = {"holder": held, "holder_open_window_nonzero": holder_win != 0,
                                       "first_open_ok": bool(first_ok), "first_err": first_err,
                                       "attempts_with_10ms_retry": attempts,
                                       "waited_ms": round((time.perf_counter() - t0) * 1000),
                                       "readback_ok": w.get_clipboard_text() == "WA-CONTENTION-TEST"}
            hp.wait(5)
        # OpenClipboard(NULL) + EmptyClipboard + SetClipboardData
        w.open_clipboard(None)
        try:
            w.EmptyClipboard()
            hh = w._hglobal_from_bytes("WA-NULL-OWNER".encode("utf-16-le") + b"\0\0")
            ctypes.set_last_error(0)
            r = w.SetClipboardData(w.CF_UNICODETEXT, hh)
            err = ctypes.get_last_error()
            if not r:
                w.GlobalFree(hh)
        finally:
            w.CloseClipboard()
        out["openclipboard_null"] = {"setclipboarddata_ok": bool(r), "err": err,
                                     "readback": w.get_clipboard_text() == "WA-NULL-OWNER"}
        # privacy formats present after set_clipboard_text(private=True)
        w.set_clipboard_text("WA-PRIVATE")
        names = [n for f, n, d in w.clipboard_snapshot()]
        out["privacy_formats_on_clipboard"] = [n for n in names if n.startswith(("Exclude", "CanInclude", "CanUpload"))]
    finally:
        w.clipboard_restore(snap)
        after = w.clipboard_snapshot()
        out["clipboard_restored"] = [(f, len(d)) for f, n, d in after] == [(f, len(d)) for f, n, d in snap]
        out["clipboard_restored_byte_exact"] = [(f, d) for f, n, d in after] == [(f, d) for f, n, d in snap]
        out["clipboard_formats"] = [(f, n, len(d)) for f, n, d in snap]
    # MapVirtualKeyExW: extended scan codes
    hkl = w.GetKeyboardLayout(0)
    out["mapvk_vsc_ex"] = {name: hex(w.MapVirtualKeyExW(vk, w.MAPVK_VK_TO_VSC_EX, hkl)) for name, vk in
                           (("LEFT", w.VK_LEFT), ("DELETE", w.VK_DELETE), ("HOME", w.VK_HOME), ("RCONTROL", w.VK_RCONTROL),
                            ("RMENU", w.VK_RMENU), ("RETURN", w.VK_RETURN), ("A", 0x41), ("LSHIFT", w.VK_LSHIFT),
                            ("DIVIDE", 0x6F), ("NUMLOCK", w.VK_NUMLOCK))}
    out["mapvk_vsc_plain_LEFT"] = hex(w.MapVirtualKeyExW(w.VK_LEFT, w.MAPVK_VK_TO_VSC, hkl))
    # CapsLock-affected keys (ToUnicodeEx) vs "letters only" rule, printable ASCII
    mism = []
    for c in range(0x21, 0x7F):
        r = w.VkKeyScanExW(chr(c), hkl)
        if r == -1:
            continue
        if w.caps_affects(r & 0xFF, hkl) != chr(c).isalpha():
            mism.append(chr(c))
    out["caps_affects_vs_isalpha_mismatches"] = mism
    out["layout"] = hex(hkl or 0)
    # GetLastInputInfo: does injected input update it, and how fast?
    lags = []
    for _ in range(10):
        before = w.last_input_tick()
        time.sleep(0.05)
        w.send([w.mouse(0, 0, w.MOUSEEVENTF_MOVE)])
        sent_tick = w.last_send_tick()
        end = time.perf_counter() + 0.5
        while w.last_input_tick() == before and time.perf_counter() < end:
            time.sleep(0.001)
        after = w.last_input_tick()
        lags.append(((after - sent_tick) & 0xFFFFFFFF) if after != before else None)
        time.sleep(0.05)
    out["lastinput_lag_after_sendinput_ms"] = lags
    # IME detach: Qt attribute alone vs ImmDisableIME(-1) (target launched, no input injected)
    out["ime_detach"] = {}
    for mode in ("qtattr", "off", "on"):
        t = h.Target(f"misc_ime_{mode}", extra=["--ime", mode])
        try:
            time.sleep(1.0)
            t.poll()
            st = [e["state"] for e in t.events if e["ev"] == "ime_state"]
            out["ime_detach"][mode] = {"in_process_state": st[-1] if st else None, "xproc_query": w.ime_query(t.hwnd)}
        finally:
            t.close()
    for k2, v in out.items():
        print(k2, v)
    print("saved", h.save_result("misc", out))


if __name__ == "__main__":
    sys.exit(main())
