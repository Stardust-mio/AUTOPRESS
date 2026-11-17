"""wa_check_doc.py - executes the ctypes snippet of docs/research/win32_input.md section 10 and syntax-checks the
API stub of section 11, then checks that every wa_*.py named in the document exists.
Injects one zero-distance mouse move; snapshots and restores the clipboard.

  .venv/Scripts/python.exe docs/research/scripts/win32/wa_check_doc.py
"""
import ast
import ctypes
import ctypes.wintypes as W
import re
import sys
from pathlib import Path

import wa_win32 as w

DOC = Path(__file__).resolve().parents[2] / "win32_input.md"


def blocks(text):
    return re.findall(r"```python\n(.*?)```", text, re.S)


def main():
    text = DOC.read_text(encoding="utf-8")
    b = blocks(text)
    assert len(b) == 2, len(b)
    ns = {"ctypes": ctypes, "W": W, "EXTRA_TAG": w.EXTRA_TAG, "EXTENDED_VKS": w.EXTENDED_VKS,
          "open_clipboard": w.open_clipboard}
    exec(compile(b[0], "win32_input.md#10", "exec"), ns)
    res = {}
    INPUT = ns["INPUT"]
    res["sizeof_INPUT"] = ctypes.sizeof(INPUT)
    k = ns["vk_key"](w.VK_LEFT)
    res["vk_left"] = (k.ki.wVk, hex(k.ki.wScan), k.ki.dwFlags)
    assert (k.ki.wScan, k.ki.dwFlags) == (0x4B, 1)
    k = ns["vk_key"](0x41, up=True)
    assert (k.ki.wScan, k.ki.dwFlags) == (0x1E, 2)
    u = ns["unicode_char_inputs"]("測")
    assert [(x.ki.wScan, x.ki.dwFlags) for x in u] == [(0x6E2C, 4), (0x6E2C, 6)]
    assert len(ns["unicode_char_inputs"]("\U0001F600")) == 4          # surrogate pair -> 2 units
    pts = [(-1920, 0), (-1, 539), (0, 0), (1919, 1079), (-1874, 850)]
    assert all(ns["to_absolute"](x, y) == w.to_absolute(x, y) for x, y in pts)
    res["to_absolute(-1920,0)"] = ns["to_absolute"](-1920, 0)
    mv = INPUT(type=0)                                               # the document's own classes
    mv.mi = ns["MOUSEINPUT"](0, 0, 0, w.MOUSEEVENTF_MOVE, 0, 0)
    arr = (INPUT * 1)(mv)
    res["SendInput_zero_move"] = ns["SendInput"](1, arr, ctypes.sizeof(INPUT))
    assert res["SendInput_zero_move"] == 1
    assert ns["kernel32"].GlobalLock.restype is ctypes.c_void_p
    snap = w.clipboard_snapshot()
    try:
        ns["set_clipboard_text"]("WA-DOC-CHECK", None)
        res["clipboard_roundtrip"] = w.get_clipboard_text() == "WA-DOC-CHECK"
        assert res["clipboard_roundtrip"]
    finally:
        w.clipboard_restore(snap)
    res["clipboard_restored_byte_exact"] = [(f, d) for f, n, d in w.clipboard_snapshot()] == [(f, d) for f, n, d in snap]
    ast.parse("from typing import Literal, Sequence, Iterable\n" + b[1])
    res["section11_parses"] = True
    here = Path(__file__).resolve().parent
    names = sorted(set(re.findall(r"wa_[a-z0-9_]+\.py", text)))
    missing = [n for n in names if not (here / n).exists()]
    res["scripts_named"] = len(names)
    res["scripts_missing"] = missing
    print(res)
    return 1 if missing or not res["clipboard_restored_byte_exact"] else 0


if __name__ == "__main__":
    sys.exit(main())
