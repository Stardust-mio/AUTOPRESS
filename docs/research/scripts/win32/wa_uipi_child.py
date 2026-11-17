"""wa_uipi_child.py - run by wa_drv_uipi.py at LOW or MEDIUM integrity; tries to type "UIPI" with
SendInput (KEYEVENTF_UNICODE) and to post WM_CHAR 'P' into the target. A low-IL process cannot write
files into the medium-IL project folder, so results come back packed in the exit code:
  bit0 guard_ok | bits1-8 SendInput return | bits9-20 GetLastError after SendInput |
  bit21 PostMessage ok | bits22-30 PostMessage GetLastError (capped 511) | bit31 never used
"""
import ctypes
import ctypes.wintypes as W
import sys

import wa_win32 as w

WM_CHAR = 0x0102


def main():
    hwnd = int(sys.argv[1], 0)
    guard_ok = w.hwnd_int(w.GetForegroundWindow()) == hwnd
    sent, err, pok, perr = 0, 0, 0, 0
    if guard_ok:
        seq = []
        for ch in "UIPI":
            seq += w.unicode_char_inputs(ch)
        arr = (w.INPUT * len(seq))(*seq)
        ctypes.set_last_error(0)
        sent = w.SendInput(len(seq), arr, ctypes.sizeof(w.INPUT))
        err = ctypes.get_last_error()
        ctypes.set_last_error(0)
        pok = 1 if w.PostMessageW(hwnd, WM_CHAR, ord("P"), 1) else 0
        perr = ctypes.get_last_error()
    code = (1 if guard_ok else 0) | ((sent & 0xFF) << 1) | ((err & 0xFFF) << 9) | (pok << 21) | (min(perr, 511) << 22)
    sys.exit(code)


if __name__ == "__main__":
    main()
