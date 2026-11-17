# OWNED BY G3 - replace this stub
"""Global hotkeys: RegisterHotKey bound to a window HWND + an app-wide
QAbstractNativeEventFilter that returns (True, 0) for our WM_HOTKEY (so it is seen once).
MOD_NOREPEAT always. No low-level keyboard hook. Error 1409 = combo already registered by
another program (win32_input.md section 6). GUI thread only.

AutoPress registers the run hotkeys only while a run or a real step test is active (RunFlow /
Profiles page, G7) so F8/F9 keep working in other programs the rest of the time.

The main window is HIDDEN during runs; delivery of WM_HOTKEY to a hidden window must be tested
(SPEC 11.2). Tests run on the offscreen platform, where ``QWidget.winId()`` is not a real HWND:
attach() to an invalid handle must not raise (register() then returns ok False), and G3's own
tests use a hidden native window created with ctypes (CreateWindowExW without WS_VISIBLE, or an
HWND_MESSAGE window) - or a ``clean_env`` child process (T12).
"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import QObject, pyqtSignal

__stub__ = True

ERROR_HOTKEY_ALREADY_REGISTERED = 1409


@dataclass(frozen=True)
class HotkeyResult:
    ok: bool
    error: int = 0  # GetLastError (1409 = in use by another program)
    message: str = ""  # localized, "" when ok


class GlobalHotkeys(QObject):
    triggered = pyqtSignal(str)  # action name passed to register(), e.g. "pause_resume", "stop"

    def __init__(self, parent: QObject | None = None) -> None:
        raise NotImplementedError

    def attach(self, hwnd: int) -> None:
        """Bind to a native window (the main window's ``int(winId())``) and install the filter.
        Re-attaching re-registers every active hotkey on the new HWND."""
        raise NotImplementedError

    def register(self, action: str, combo: str) -> HotkeyResult:
        """Register (or replace) the hotkey for ``action``. Not attached -> ok False."""
        raise NotImplementedError

    def unregister(self, action: str) -> None:
        raise NotImplementedError

    def unregister_all(self) -> None:
        raise NotImplementedError

    def registered(self) -> dict[str, str]:
        """action -> combo of the currently registered hotkeys."""
        raise NotImplementedError
