# OWNED BY G3
"""Private: the localized messages (SPEC 7.1) and the exception classes of win32.input.

Import them from ``autopress.win32.input`` (the public names are re-exported there); this module
only keeps input.py focused (SPEC 9) and lets win32.clipboard import ClipboardBusy without an
import cycle. ``tr`` runs when a message is built, never at import time.
"""

from __future__ import annotations

from ..i18n import tr
from ..models import Point


# ================================================================================ messages


def _msg_focus_lost() -> str:
    return tr("目標視窗失去焦點，已暫停。切回目標視窗後按「繼續」(F8)。",
              "The target window lost focus; paused. Switch back and press Resume (F8).")


def _msg_user_input() -> str:
    return tr("偵測到滑鼠或鍵盤操作，已暫停以免輸入到錯誤的地方。按「繼續」(F8) 接著做。",
              "Mouse or keyboard input detected; paused so nothing goes to the wrong place. Press Resume (F8).")


def _msg_covered(title: str) -> str:
    return tr("點擊位置被「{title}」遮住，已暫停。請移開該視窗後按「繼續」。",
              "The click position is covered by \"{title}\"; paused. Move that window away and press Resume."
              ).format(title=title)


def _msg_covered_generic() -> str:
    return tr("點擊位置被其他視窗遮住，已暫停。請移開該視窗後按「繼續」。",
              "The click position is covered by another window; paused. Move that window away and press Resume.")


def _msg_covered_minibar() -> str:
    return tr("AutoPress 的迷你控制列擋住了點擊位置，已暫停。請把它拖到別處後按「繼續」。",
              "AutoPress's mini bar covers the click position; paused. Drag it elsewhere and press Resume.")


def _msg_offscreen() -> str:
    return tr("點擊位置不在目標視窗上（可能在螢幕外），已暫停。請確認視窗位置後按「繼續」。",
              "The click position is not on the target window (off-screen?); paused. "
              "Check the window position and press Resume.")


def _msg_input_blocked() -> str:
    return tr("Windows 擋下了模擬輸入（可能出現了 UAC 視窗、螢幕已鎖定，或目標權限較高），已暫停。處理後按「繼續」。",
              "Windows blocked the simulated input (UAC prompt, locked screen or a higher-privilege target?); "
              "paused. Fix it and press Resume.")


def _msg_failsafe() -> str:
    return tr("滑鼠移到螢幕左上角，已緊急停止。", "Mouse moved to the top-left corner: emergency stop.")


def _msg_clipboard_busy() -> str:
    return tr("剪貼簿被其他程式佔用，無法貼上序號。請稍後再試，或改用「模擬鍵入」。",
              "The clipboard is held by another program; the code could not be pasted. "
              "Try again or use simulated typing.")


def _msg_unmappable(ch: str) -> str:
    return tr("遊戲模式無法輸入字元「{ch}」（目前的鍵盤配置沒有這個鍵）。請改用「模擬鍵入」或「貼上」。",
              "Game mode cannot type \"{ch}\" (no such key on the keyboard layout). "
              "Use simulated typing or paste mode.").format(ch=ch)


# ================================================================================ exceptions


class InjectionAborted(RuntimeError):
    """Base class: an injection was refused for safety. ``str(exc)`` is localized."""

    def __init__(self, message: str = "", *, what: str = "") -> None:
        super().__init__(message or self.default_message())
        self.what = what

    @classmethod
    def default_message(cls) -> str:
        return tr("已停止模擬輸入。", "Simulated input was stopped.")


class ForegroundLost(InjectionAborted):
    """The target is not the foreground window."""

    def __init__(self, message: str = "", *, what: str = "", foreground_hwnd: int = 0) -> None:
        super().__init__(message, what=what)
        self.foreground_hwnd = foreground_hwnd

    @classmethod
    def default_message(cls) -> str:
        return _msg_focus_lost()


class PointNotOnTarget(InjectionAborted):
    """The click point's root window (WindowFromPoint + GA_ROOT) is not the target. The message
    names the covering window: AutoPress's own mini bar -> 「AutoPress 的迷你控制列擋住了點擊
    位置…」, another window -> its title (SPEC 7.1)."""

    def __init__(self, message: str = "", *, what: str = "", point: Point | None = None, covering_hwnd: int = 0,
                 covering_title: str = "", covering_is_own: bool = False, covering_is_minibar: bool = False) -> None:
        super().__init__(message, what=what)
        self.point = point
        self.covering_hwnd = covering_hwnd
        self.covering_title = covering_title
        self.covering_is_own = covering_is_own
        self.covering_is_minibar = covering_is_minibar

    @classmethod
    def default_message(cls) -> str:
        return _msg_covered_generic()


class UserActivity(InjectionAborted):
    """Physical input happened after our last injection (GetLastInputInfo)."""

    @classmethod
    def default_message(cls) -> str:
        return _msg_user_input()


class FailsafeTriggered(InjectionAborted):
    """The mouse cursor is in a failsafe corner (models.failsafe_corners of the monitors)."""

    def __init__(self, message: str = "", *, what: str = "", cursor: Point | None = None) -> None:
        super().__init__(message, what=what)
        self.cursor = cursor

    @classmethod
    def default_message(cls) -> str:
        return _msg_failsafe()


class InputBlocked(InjectionAborted):
    """SendInput inserted fewer events than requested: Windows refused the input (UAC prompt,
    locked screen, secure desktop, input desktop switched). Localized message (SPEC 7.1)."""

    def __init__(self, message: str = "", *, what: str = "", sent: int = 0, requested: int = 0,
                 error: int = 0) -> None:
        super().__init__(message, what=what)
        self.sent = sent
        self.requested = requested
        self.error = error

    @classmethod
    def default_message(cls) -> str:
        return _msg_input_blocked()


class ClipboardBusy(OSError):
    """OpenClipboard kept failing (another program holds the clipboard). Localized message."""

    def __init__(self, message: str = "", *, error: int = 0) -> None:
        super().__init__(message or _msg_clipboard_busy())
        self.error = error


class UnmappableChar(ValueError):
    """VK mode: a character has no key on the target's keyboard layout. Localized message."""

    def __init__(self, ch: str = "", message: str = "") -> None:
        super().__init__(message or _msg_unmappable(ch))
        self.ch = ch
