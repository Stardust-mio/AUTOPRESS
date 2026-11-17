# OWNED BY G3
"""win32.clipboard with the clipboard API MOCKED (the user's real clipboard is touched only by the
realinput round-trip test): retries + ClipboardBusy, privacy formats, memory ownership, format
filtering in snapshots, registered formats looked up by name on restore."""

from __future__ import annotations

import ctypes

import pytest

from autopress.win32 import api, clipboard
from autopress.win32.input import ClipboardBusy

CF_TEXT_FMT = 13


class FakeClip:
    """Patched OpenClipboard / Empty / Set / Get / Enum; memory comes from the real GlobalAlloc."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, open_ok: bool = True, set_ok: bool = True) -> None:
        self.open_calls = 0
        self.open_ok, self.set_ok = open_ok, set_ok
        self.data: dict[int, int] = {}  # format -> HGLOBAL (as SetClipboardData stored it)
        self.freed: list[int] = []
        self.closed = 0
        monkeypatch.setattr(clipboard, "OPEN_DELAY_S", 0.0)
        monkeypatch.setattr(api, "OpenClipboard", self.open)
        monkeypatch.setattr(api, "CloseClipboard", self.close)
        monkeypatch.setattr(api, "EmptyClipboard", lambda: self.data.clear() or 1)
        monkeypatch.setattr(api, "SetClipboardData", self.set)
        monkeypatch.setattr(api, "GetClipboardData", lambda fmt: self.data.get(fmt))
        monkeypatch.setattr(api, "IsClipboardFormatAvailable", lambda fmt: int(fmt in self.data))
        monkeypatch.setattr(api, "EnumClipboardFormats", self.enum)
        monkeypatch.setattr(api, "GetOpenClipboardWindow", lambda: 0)
        real_free = api.GlobalFree
        monkeypatch.setattr(api, "GlobalFree", lambda h: self.freed.append(int(h)) or real_free(h))

    def open(self, hwnd: object) -> int:
        self.open_calls += 1
        return int(self.open_ok)

    def close(self) -> int:
        self.closed += 1
        return 1

    def set(self, fmt: int, handle: int) -> int:
        if not self.set_ok:
            return 0
        self.data[int(fmt)] = int(handle)
        return int(handle)

    def enum(self, fmt: int) -> int:
        keys = list(self.data)
        if fmt == 0:
            return keys[0] if keys else 0
        i = keys.index(fmt) + 1
        return keys[i] if i < len(keys) else 0

    def read(self, fmt: int) -> bytes:
        h = self.data[fmt]
        p = api.GlobalLock(h)
        try:
            return ctypes.string_at(p, api.GlobalSize(h))
        finally:
            api.GlobalUnlock(h)

    def put(self, fmt: int, payload: bytes) -> None:
        self.data[fmt] = clipboard._hglobal(payload)

    def release(self) -> None:
        for h in self.data.values():
            ctypes.WinDLL("kernel32").GlobalFree(ctypes.c_void_p(h))
        self.data.clear()


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeClip:
    f = FakeClip(monkeypatch)
    yield f
    f.release()


def test_set_text_writes_unicode_text_and_the_privacy_formats(fake: FakeClip) -> None:
    clipboard.set_text("AB-12 測")
    assert fake.read(CF_TEXT_FMT) == "AB-12 測".encode("utf-16-le") + b"\x00\x00"
    privacy = clipboard._privacy_formats()
    assert len(privacy) == 3 and all(p >= 0xC000 for p in privacy)
    for p in privacy:
        assert fake.read(p) == b"\x00\x00\x00\x00"
    assert fake.closed == 1 and fake.freed == []  # on success the system owns the memory
    assert clipboard.get_text() == "AB-12 測"


def test_set_text_without_privacy(fake: FakeClip) -> None:
    clipboard.set_text("x", private=False)
    assert list(fake.data) == [CF_TEXT_FMT]


def test_failed_set_frees_the_memory_and_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    f = FakeClip(monkeypatch, set_ok=False)
    with pytest.raises(OSError):
        clipboard.set_text("x")
    assert len(f.freed) == 1 and f.closed == 1


def test_busy_clipboard_retries_then_raises_clipboard_busy(monkeypatch: pytest.MonkeyPatch) -> None:
    f = FakeClip(monkeypatch, open_ok=False)
    with pytest.raises(ClipboardBusy) as info:
        clipboard.set_text("x")
    assert f.open_calls == clipboard.OPEN_RETRIES == 50
    assert "剪貼簿被其他程式佔用" in str(info.value) and isinstance(info.value, OSError)
    for fn in (clipboard.get_text, clipboard.snapshot):
        with pytest.raises(ClipboardBusy):
            fn()
    with pytest.raises(ClipboardBusy):
        clipboard.restore(clipboard.ClipboardSnapshot())
    assert f.closed == 0  # never closed what was not opened


def test_get_text_without_text(fake: FakeClip) -> None:
    assert clipboard.get_text() is None
    fake.put(0xC123, b"\x01\x02")
    assert clipboard.get_text() is None


def test_snapshot_skips_gdi_and_private_formats(fake: FakeClip, monkeypatch: pytest.MonkeyPatch) -> None:
    fake.put(CF_TEXT_FMT, "hi".encode("utf-16-le") + b"\x00\x00")
    fake.put(2, b"bitmap handle")  # CF_BITMAP
    fake.put(0x0201, b"private")
    fake.put(0x0305, b"gdi object")
    fake.put(0xC0DE, b"\x89PNG data")
    monkeypatch.setattr(clipboard, "_format_name", lambda fmt: "PNG" if fmt == 0xC0DE else "")
    snap = clipboard.snapshot()
    assert [(f, n) for f, n, _d in snap.formats] == [(CF_TEXT_FMT, ""), (0xC0DE, "PNG")]
    assert snap.formats[1][2].startswith(b"\x89PNG data")


def test_restore_puts_every_format_back_and_reregisters_names(fake: FakeClip, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "RegisterClipboardFormatW", lambda name: 0xC555 if name == "PNG" else 0)
    snap = clipboard.ClipboardSnapshot([(CF_TEXT_FMT, "", b"o\x00k\x00\x00\x00"), (0xC0DE, "PNG", b"\x89PNG")])
    fake.put(0xC999, b"to be replaced")
    clipboard.restore(snap)
    assert sorted(fake.data) == [CF_TEXT_FMT, 0xC555]
    assert fake.read(CF_TEXT_FMT) == b"o\x00k\x00\x00\x00" and fake.read(0xC555) == b"\x89PNG"
    clipboard.restore(clipboard.ClipboardSnapshot())  # an empty snapshot empties the clipboard
    assert fake.data == {}
