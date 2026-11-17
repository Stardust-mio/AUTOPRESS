# OWNED BY G3
"""Helpers for the G3 win32 tests (not collected by pytest).

* ``hidden_window()`` - a real, never-shown native top-level window created with ctypes
  (CreateWindowExW of the predefined "STATIC" class without WS_VISIBLE): it has a real HWND on
  the offscreen Qt platform (T12), belongs to the calling thread and is destroyed on exit.
* ``SendRecorder`` - replaces ``api.SendInput``: records every batch as decoded tuples and
  returns the full count or a scripted short count (InputBlocked tests). Nothing reaches Windows.
* ``RecordingGuard`` - a stand-in for InjectGuard that records check() calls and can raise.
* ``FakeScreen`` - geometry()/devicePixelRatio() stand-in for the pure DPI math.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as W
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from PyQt6.QtCore import QRect

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


def _f(dll: Any, name: str, restype: Any, *argtypes: Any) -> Any:
    fn = getattr(dll, name)
    fn.restype = restype
    fn.argtypes = list(argtypes)
    return fn


CreateWindowExW = _f(_user32, "CreateWindowExW", W.HWND, W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD, ctypes.c_int,
                     ctypes.c_int, ctypes.c_int, ctypes.c_int, W.HWND, W.HMENU, W.HINSTANCE, W.LPVOID)
DestroyWindow = _f(_user32, "DestroyWindow", W.BOOL, W.HWND)
GetModuleHandleW = _f(_kernel32, "GetModuleHandleW", W.HMODULE, W.LPCWSTR)
PostMessageW = _f(_user32, "PostMessageW", W.BOOL, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
RegisterHotKey = _f(_user32, "RegisterHotKey", W.BOOL, W.HWND, ctypes.c_int, W.UINT, W.UINT)
UnregisterHotKey = _f(_user32, "UnregisterHotKey", W.BOOL, W.HWND, ctypes.c_int)
ShowWindow = _f(_user32, "ShowWindow", W.BOOL, W.HWND, ctypes.c_int)
SetWindowPos = _f(_user32, "SetWindowPos", W.BOOL, W.HWND, W.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                  ctypes.c_int, W.UINT)

WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_EX_TOOLWINDOW = 0x00000080
WM_HOTKEY = 0x0312
SW_MINIMIZE = 6
HWND_TOPMOST = W.HWND(-1)
SWP_NOACTIVATE = 0x0010


@contextmanager
def hidden_window(title: str = "AutoPress G3 hidden test window", rect: tuple[int, int, int, int] = (240, 160, 420, 300),
                  exstyle: int = 0, style: int = WS_OVERLAPPEDWINDOW) -> Iterator[int]:
    """A never-shown native top-level window of the calling thread; yields its HWND."""
    x, y, w, h = rect
    hwnd = CreateWindowExW(exstyle, "STATIC", title, style, x, y, w, h, None, None, GetModuleHandleW(None), None)
    if not hwnd:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield int(hwnd)
    finally:
        DestroyWindow(hwnd)


def decode(ev: Any) -> tuple:
    """INPUT -> ("key", vk, scan, flags) | ("mouse", dx, dy, flags); asserts the APRS tag."""
    from autopress.win32 import api
    from autopress.win32.input import EXTRA_TAG

    if ev.type == api.INPUT_KEYBOARD:
        assert ev.ki.dwExtraInfo == EXTRA_TAG
        return ("key", int(ev.ki.wVk), int(ev.ki.wScan), int(ev.ki.dwFlags))
    assert ev.type == api.INPUT_MOUSE
    assert ev.mi.dwExtraInfo == EXTRA_TAG
    return ("mouse", int(ev.mi.dx), int(ev.mi.dy), int(ev.mi.dwFlags))


class SendRecorder:
    """Stand-in for api.SendInput. ``script``: return values for successive calls (None = all)."""

    def __init__(self, script: list[int | None] | None = None) -> None:
        self.batches: list[list[tuple]] = []
        self.script = list(script or [])

    def __call__(self, n: int, arr: Any, size: int) -> int:
        from autopress.win32 import api

        assert size == ctypes.sizeof(api.INPUT) == 40
        self.batches.append([decode(arr[i]) for i in range(n)])
        ret = self.script.pop(0) if self.script else None
        return n if ret is None else ret

    @property
    def events(self) -> list[tuple]:
        return [e for b in self.batches for e in b]

    def keys(self) -> list[tuple[int, bool]]:
        """(vk, is_up) for every non-unicode key event."""
        from autopress.win32 import api

        return [(e[1], bool(e[3] & api.KEYEVENTF_KEYUP)) for e in self.events
                if e[0] == "key" and not e[3] & api.KEYEVENTF_UNICODE]


class RecordingGuard:
    """InjectGuard stand-in: ``hwnd``, a list of check() calls, optional exception at call n."""

    def __init__(self, hwnd: int = 0, raise_at: int | None = None, exc: BaseException | None = None) -> None:
        self.hwnd = hwnd
        self.calls: list[tuple[str, Any]] = []
        self.raise_at = raise_at
        self.exc = exc

    def check(self, what: str, point: Any = None) -> None:
        self.calls.append((what, point))
        if self.raise_at is not None and len(self.calls) - 1 == self.raise_at:
            assert self.exc is not None
            raise self.exc


class FakeScreen:
    """``geometry()`` (logical rect whose top-left is the native origin) + ``devicePixelRatio()``."""

    def __init__(self, x: int, y: int, w: int, h: int, dpr: float) -> None:
        self._geo = QRect(x, y, w, h)
        self._dpr = dpr

    def geometry(self) -> QRect:
        return self._geo

    def devicePixelRatio(self) -> float:  # noqa: N802 - Qt naming
        return self._dpr
