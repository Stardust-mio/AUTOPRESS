# OWNED BY G3
"""Clipboard via ctypes (win32_input.md section 2): OpenClipboard retried 50 x 10 ms on
ERROR_ACCESS_DENIED; GMEM_MOVEABLE memory freed only when SetClipboardData fails; text writes
also set the privacy formats (ExcludeClipboardContentFromMonitorProcessing,
CanIncludeInClipboardHistory=0, CanUploadToCloudClipboard=0).

OpenClipboard(NULL) works for setting data (measured, although the docs say it should fail);
pass a window of the calling thread when there is one. Any thread may call these functions; each
call opens and closes the clipboard itself.
"""

from __future__ import annotations

import ctypes
import logging
import time
from dataclasses import dataclass, field

from . import api
from ._errors import ClipboardBusy  # public name: win32.input.ClipboardBusy

log = logging.getLogger(__name__)

OPEN_RETRIES = 50
OPEN_DELAY_S = 0.01
# GDI-handle / owner-display formats cannot be copied as HGLOBAL bytes (the system re-creates
# CF_BITMAP etc. from CF_DIB); 0x200-0x3FF are private and GDI-object ranges.
_NON_HGLOBAL = frozenset({2, 3, 9, 14, 0x80, 0x82, 0x83, 0x8E})
_PRIVACY_NAMES = ("ExcludeClipboardContentFromMonitorProcessing", "CanIncludeInClipboardHistory",
                  "CanUploadToCloudClipboard")
_privacy_ids: list[int] = []


@dataclass
class ClipboardSnapshot:
    """Every HGLOBAL format of the clipboard: (format id, format name, bytes)."""

    formats: list[tuple[int, str, bytes]] = field(default_factory=list)


def _open(hwnd: int) -> None:
    """OpenClipboard with retries (another process may hold it). Raises ClipboardBusy."""
    err = 0
    for _attempt in range(OPEN_RETRIES):
        if api.OpenClipboard(int(hwnd or 0) or None):
            return
        err = ctypes.get_last_error()
        time.sleep(OPEN_DELAY_S)
    holder = api.hwnd_int(api.GetOpenClipboardWindow())
    log.warning("OpenClipboard failed %d times (error %s, holder %#x)", OPEN_RETRIES, err, holder)
    raise ClipboardBusy(error=err)  # SPEC 7.1 "clipboard busy" text


def _hglobal(data: bytes) -> int:
    h = api.GlobalAlloc(api.GMEM_MOVEABLE, max(1, len(data)))
    if not h:
        raise ctypes.WinError(ctypes.get_last_error())
    p = api.GlobalLock(h)
    if not p:
        err = ctypes.get_last_error()
        api.GlobalFree(h)
        raise ctypes.WinError(err)
    try:
        if data:
            ctypes.memmove(p, data, len(data))
    finally:
        api.GlobalUnlock(h)
    return int(h)


def _set(fmt: int, data: bytes) -> bool:
    """SetClipboardData with a fresh HGLOBAL; frees it only when the call fails."""
    h = _hglobal(data)
    if not api.SetClipboardData(fmt, h):
        api.GlobalFree(h)
        return False
    return True


def _privacy_formats() -> list[int]:
    if not _privacy_ids:
        _privacy_ids.extend(int(api.RegisterClipboardFormatW(n)) for n in _PRIVACY_NAMES)
    return _privacy_ids


def set_text(text: str, hwnd: int = 0, private: bool = True) -> None:
    """Replace the clipboard with ``text`` (CF_UNICODETEXT). Raises input.ClipboardBusy.
    ``private`` also keeps it out of Win+V history, cloud sync and clipboard monitors."""
    data = str(text).encode("utf-16-le") + b"\x00\x00"
    _open(hwnd)
    try:
        if not api.EmptyClipboard():
            raise ctypes.WinError(ctypes.get_last_error())
        if not _set(api.CF_UNICODETEXT, data):
            raise ctypes.WinError(ctypes.get_last_error())
        if private:
            for fmt in _privacy_formats():
                if fmt and not _set(fmt, b"\x00\x00\x00\x00"):
                    log.debug("privacy clipboard format %s not set", fmt)
    finally:
        api.CloseClipboard()


def get_text(hwnd: int = 0) -> str | None:
    """CF_UNICODETEXT of the clipboard, None when there is no text. Raises input.ClipboardBusy."""
    _open(hwnd)
    try:
        if not api.IsClipboardFormatAvailable(api.CF_UNICODETEXT):
            return None
        h = api.GetClipboardData(api.CF_UNICODETEXT)
        if not h:
            return None
        p = api.GlobalLock(h)
        if not p:
            return None
        try:
            return ctypes.wstring_at(p)
        finally:
            api.GlobalUnlock(h)
    finally:
        api.CloseClipboard()


def _format_name(fmt: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    n = api.GetClipboardFormatNameW(fmt, buf, len(buf))
    return buf.value if n > 0 else ""


def snapshot(hwnd: int = 0) -> ClipboardSnapshot:
    """Copy every HGLOBAL clipboard format (text, HTML, PNG, DIB ...). CF_BITMAP and other GDI /
    private formats are skipped (the system re-synthesizes bitmaps from CF_DIB). Raises
    input.ClipboardBusy."""
    snap = ClipboardSnapshot()
    _open(hwnd)
    try:
        fmt = 0
        while True:
            fmt = int(api.EnumClipboardFormats(fmt))
            if not fmt:
                break
            if fmt in _NON_HGLOBAL or 0x200 <= fmt <= 0x3FF:
                continue
            h = api.GetClipboardData(fmt)
            if not h:
                continue
            size = int(api.GlobalSize(h))
            p = api.GlobalLock(h)
            if not p:
                continue
            try:
                data = ctypes.string_at(p, size)
            finally:
                api.GlobalUnlock(h)
            snap.formats.append((fmt, _format_name(fmt), data))
    finally:
        api.CloseClipboard()
    return snap


def restore(snap: ClipboardSnapshot, hwnd: int = 0) -> None:
    """Put every saved format back (an empty snapshot empties the clipboard). Registered formats
    are looked up again by name. Raises input.ClipboardBusy."""
    _open(hwnd)
    try:
        api.EmptyClipboard()
        for fmt, name, data in snap.formats:
            if fmt >= 0xC000 and name:
                fmt = int(api.RegisterClipboardFormatW(name)) or fmt
            if not _set(fmt, data):
                log.debug("clipboard format %s (%s) not restored: error %s", fmt, name, ctypes.get_last_error())
    finally:
        api.CloseClipboard()
