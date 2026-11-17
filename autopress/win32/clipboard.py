# OWNED BY G3 - replace this stub
"""Clipboard via ctypes (win32_input.md section 2): OpenClipboard retried 50 x 10 ms on
ERROR_ACCESS_DENIED; GMEM_MOVEABLE memory freed only when SetClipboardData fails; text writes
also set the privacy formats (ExcludeClipboardContentFromMonitorProcessing,
CanIncludeInClipboardHistory=0, CanUploadToCloudClipboard=0)."""

from __future__ import annotations

from dataclasses import dataclass, field

__stub__ = True


@dataclass
class ClipboardSnapshot:
    """Every HGLOBAL format of the clipboard: (format id, format name, bytes)."""

    formats: list[tuple[int, str, bytes]] = field(default_factory=list)


def set_text(text: str, hwnd: int = 0, private: bool = True) -> None:
    """Replace the clipboard with ``text`` (CF_UNICODETEXT). Raises input.ClipboardBusy."""
    raise NotImplementedError


def get_text(hwnd: int = 0) -> str | None:
    raise NotImplementedError


def snapshot(hwnd: int = 0) -> ClipboardSnapshot:
    raise NotImplementedError


def restore(snap: ClipboardSnapshot, hwnd: int = 0) -> None:
    """Put every saved format back (an empty snapshot empties the clipboard)."""
    raise NotImplementedError
