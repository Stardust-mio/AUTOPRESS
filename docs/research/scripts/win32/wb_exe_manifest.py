"""wb_exe_manifest.py - print the embedded RT_MANIFEST of an exe WITHOUT running it (read-only).

Used to check whether an interpreter / PyInstaller exe pre-declares DPI awareness, which
would make Qt's SetProcessDpiAwarenessContext(PMv2) fail (see wb_qt_probe --mss before).
usage: python wb_exe_manifest.py EXE [EXE ...]
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import re
import sys

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.LoadLibraryExW.argtypes, k32.LoadLibraryExW.restype = [wt.LPCWSTR, wt.HANDLE, wt.DWORD], wt.HMODULE
k32.FindResourceW.argtypes, k32.FindResourceW.restype = [wt.HMODULE, ctypes.c_void_p, ctypes.c_void_p], wt.HANDLE
k32.LoadResource.argtypes, k32.LoadResource.restype = [wt.HMODULE, wt.HANDLE], wt.HANDLE
k32.LockResource.argtypes, k32.LockResource.restype = [wt.HANDLE], ctypes.c_void_p
k32.SizeofResource.argtypes, k32.SizeofResource.restype = [wt.HMODULE, wt.HANDLE], wt.DWORD
k32.FreeLibrary.argtypes, k32.FreeLibrary.restype = [wt.HMODULE], wt.BOOL
LOAD_LIBRARY_AS_DATAFILE, LOAD_LIBRARY_AS_IMAGE_RESOURCE, RT_MANIFEST = 0x2, 0x20, 24


def manifest(path: str) -> str | None:
    h = k32.LoadLibraryExW(path, None, LOAD_LIBRARY_AS_DATAFILE | LOAD_LIBRARY_AS_IMAGE_RESOURCE)
    if not h:
        raise OSError(ctypes.get_last_error(), path)
    try:
        for rid in (1, 2):  # CREATEPROCESS_MANIFEST_RESOURCE_ID = 1
            r = k32.FindResourceW(h, ctypes.c_void_p(rid), ctypes.c_void_p(RT_MANIFEST))
            if r:
                size = k32.SizeofResource(h, r)
                return ctypes.string_at(k32.LockResource(k32.LoadResource(h, r)), size).decode("utf-8", "replace")
        return None
    finally:
        k32.FreeLibrary(h)


for exe in sys.argv[1:]:
    m = manifest(exe)
    print(f"== {exe}")
    if m is None:
        print("   no RT_MANIFEST")
        continue
    for tag in ("dpiAware", "dpiAwareness", "requestedExecutionLevel", "longPathAware", "activeCodePage"):
        hits = re.findall(rf"<[^>]*{tag}[^>]*>[^<]*(?:</[^>]*>)?", m)
        print(f"   {tag}: {hits if hits else 'absent'}")
