# OWNED BY G3
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

Delivery: Qt's event dispatcher hands every message of the GUI thread to the native event
filter before dispatching it (also for windows Qt did not create and while the window is
hidden); the filter consumes our (hwnd, id) pairs and ``triggered`` is emitted through a queued
connection, i.e. from the event loop, never inside the native filter. One filter per process,
installed with the first attach(); it holds weak references, so a dropped GlobalHotkeys object
never receives anything.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as W
import logging
import weakref
from dataclasses import dataclass

from PyQt6.QtCore import QAbstractNativeEventFilter, QCoreApplication, QObject, Qt, pyqtSignal

from ..i18n import tr
from ..models import normalize_combo, validate_hotkey
from . import api
from .keys import parse_hotkey

log = logging.getLogger(__name__)

ERROR_HOTKEY_ALREADY_REGISTERED = 1409
_ID_BASE = 0xA000  # application hotkey ids must be 0x0000-0xBFFF


@dataclass(frozen=True)
class HotkeyResult:
    ok: bool
    error: int = 0  # GetLastError (1409 = in use by another program)
    message: str = ""  # localized, "" when ok


def _msg_in_use(combo: str) -> str:
    return tr("快捷鍵 {combo} 已被其他程式使用，請在設定中更換；這次執行請用迷你控制列的按鈕或左上角緊急停止。",
              "Hotkey {combo} is used by another program; change it in Settings. "
              "For this run use the mini bar buttons or the top-left emergency stop.").format(combo=combo)


def _msg_other_action(combo: str) -> str:
    return tr("快捷鍵 {combo} 已用於其他動作。", "Hotkey {combo} is already used for another action.").format(combo=combo)


def _msg_not_attached() -> str:
    return tr("快捷鍵尚未綁定到視窗，無法註冊。", "Hotkeys are not attached to a window yet.")


def _msg_failed(combo: str, code: int) -> str:
    return tr("無法註冊快捷鍵 {combo}（錯誤 {code}）。",
              "Could not register hotkey {combo} (error {code}).").format(combo=combo, code=code)


class _HotkeyFilter(QAbstractNativeEventFilter):
    """App-wide filter: WM_HOTKEY for a registered (hwnd, id) -> owner, consumed (seen once)."""

    def __init__(self) -> None:
        super().__init__()
        self.routes: dict[tuple[int, int], weakref.ReferenceType[GlobalHotkeys]] = {}

    def nativeEventFilter(self, eventType, message):  # noqa: N802, ANN001, ANN201 - Qt override
        try:
            if message and self.routes:
                msg = W.MSG.from_address(int(message))
                if msg.message == api.WM_HOTKEY:
                    ref = self.routes.get((api.hwnd_int(msg.hWnd), int(msg.wParam)))
                    owner = ref() if ref is not None else None
                    if owner is not None:
                        owner._on_hotkey(int(msg.wParam))
                        return True, 0
        except Exception:  # never let an exception escape into Qt's dispatcher
            log.exception("hotkey filter failed")
        return False, 0


_filter: _HotkeyFilter | None = None


def _ensure_filter() -> _HotkeyFilter | None:
    """Install the process-wide filter once (needs a QCoreApplication)."""
    global _filter
    app = QCoreApplication.instance()
    if app is None:
        return None
    if _filter is None:
        _filter = _HotkeyFilter()
        app.installNativeEventFilter(_filter)
    return _filter


class GlobalHotkeys(QObject):
    triggered = pyqtSignal(str)  # action name passed to register(), e.g. "pause_resume", "stop"
    _hit = pyqtSignal(str)  # internal: re-emitted as ``triggered`` through a queued connection

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._hwnd = 0
        self._active: dict[str, tuple[str, int]] = {}  # action -> (combo, hotkey id)
        self._hit.connect(self.triggered, type=Qt.ConnectionType.QueuedConnection)

    # -- internals -------------------------------------------------------------------------
    def _route(self, hk_id: int, on: bool) -> None:
        flt = _ensure_filter()
        if flt is None:
            return
        key = (self._hwnd, hk_id)
        if on:
            flt.routes[key] = weakref.ref(self)
        else:
            flt.routes.pop(key, None)

    def _on_hotkey(self, hk_id: int) -> None:
        for action, (_combo, i) in self._active.items():
            if i == hk_id:
                log.info("hotkey %s", action)
                self._hit.emit(action)
                return

    def _free_id(self) -> int:
        """Lowest id in 0xA000-0xBFFF not used on this window (by any GlobalHotkeys object)."""
        used = {i for _c, i in self._active.values()}
        if _filter is not None:
            used |= {i for (h, i) in _filter.routes if h == self._hwnd}
        return next(i for i in range(_ID_BASE, 0xC000) if i not in used)

    def _raw_register(self, combo: str) -> tuple[int, int]:
        """(hotkey id, 0) on success, (0, GetLastError) on failure. ValueError for invalid combos."""
        mods, vk = parse_hotkey(combo)
        hk_id = self._free_id()
        if api.RegisterHotKey(self._hwnd or None, hk_id, mods, vk):
            self._route(hk_id, True)
            return hk_id, 0
        return 0, ctypes.get_last_error()

    def _raw_unregister(self, hk_id: int) -> None:
        if not api.UnregisterHotKey(self._hwnd or None, hk_id):
            log.debug("UnregisterHotKey(%#x, %s) failed: error %s", self._hwnd, hk_id, ctypes.get_last_error())
        self._route(hk_id, False)

    # -- API -------------------------------------------------------------------------------
    def attach(self, hwnd: int) -> None:
        """Bind to a native window (the main window's ``int(winId())``) and install the filter.
        Re-attaching re-registers every active hotkey on the new HWND (a combo that fails there is
        dropped and logged). Never raises, also for invalid handles."""
        try:
            hwnd = int(hwnd or 0)
        except (TypeError, ValueError):
            hwnd = 0
        _ensure_filter()
        if hwnd == self._hwnd:
            return
        previous = dict(self._active)
        for _combo, hk_id in previous.values():
            self._raw_unregister(hk_id)
        self._active.clear()
        self._hwnd = hwnd
        if not hwnd:
            return
        for action, (combo, _old) in previous.items():
            try:
                hk_id, err = self._raw_register(combo)
            except ValueError:
                continue
            if hk_id:
                self._active[action] = (combo, hk_id)
            else:
                log.warning("hotkey %s (%s) not re-registered on %#x: error %s", action, combo, hwnd, err)

    def register(self, action: str, combo: str) -> HotkeyResult:
        """Register (or replace) the hotkey for ``action``. Not attached -> ok False. An invalid
        combo gives ok False with models.validate_hotkey's reason; error 1409 (in use) carries the
        SPEC 7.1 text. When a replacement fails, the previous combo of ``action`` stays active."""
        reason = validate_hotkey(combo)
        if reason is not None:
            return HotkeyResult(False, 0, reason)
        canonical = normalize_combo(combo)
        if not self._hwnd:
            return HotkeyResult(False, 0, _msg_not_attached())
        current = self._active.get(action)
        if current is not None and current[0] == canonical:
            return HotkeyResult(True)
        if any(c == canonical for a, (c, _i) in self._active.items() if a != action):
            return HotkeyResult(False, ERROR_HOTKEY_ALREADY_REGISTERED, _msg_other_action(canonical))
        if current is not None:
            self._raw_unregister(current[1])
            del self._active[action]
        hk_id, err = self._raw_register(canonical)
        if hk_id:
            self._active[action] = (canonical, hk_id)
            log.info("hotkey %s = %s registered on %#x", action, canonical, self._hwnd)
            return HotkeyResult(True)
        if current is not None:  # put the previous combo back (best effort)
            old_id, _err = self._raw_register(current[0])
            if old_id:
                self._active[action] = (current[0], old_id)
        log.info("hotkey %s = %s not registered: error %s", action, canonical, err)
        if err == ERROR_HOTKEY_ALREADY_REGISTERED:
            return HotkeyResult(False, err, _msg_in_use(canonical))
        return HotkeyResult(False, err, _msg_failed(canonical, err))

    def unregister(self, action: str) -> None:
        current = self._active.pop(action, None)
        if current is not None:
            self._raw_unregister(current[1])

    def unregister_all(self) -> None:
        for action in list(self._active):
            self.unregister(action)

    def registered(self) -> dict[str, str]:
        """action -> combo of the currently registered hotkeys."""
        return {action: combo for action, (combo, _i) in self._active.items()}

    def hwnd(self) -> int:
        """The attached native window (0 = not attached)."""
        return self._hwnd
