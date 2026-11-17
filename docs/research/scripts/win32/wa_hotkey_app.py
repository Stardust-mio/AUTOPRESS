"""wa_hotkey_app.py - Qt6 global-hotkey receiver for the AutoPress R2a research (RegisterHotKey, no hooks).

Modes:
  nativeevent   RegisterHotKey(widget HWND) + QWidget.nativeEvent override
  filter        RegisterHotKey(widget HWND) + QAbstractNativeEventFilter on the QApplication
  filter_thread RegisterHotKey(NULL)  (thread hotkey)  + QAbstractNativeEventFilter
Run (from the project root):
  .venv/Scripts/python.exe docs/research/scripts/win32/wa_hotkey_app.py --log L.jsonl --info I.json
      [--mode nativeevent] [--vk 0x78] [--mods 6] [--norepeat 1] [--ret int|voidptr]
Posting WM_APP+1 to its window makes it try SetForegroundWindow(itself) (control for the
"does a hotkey grant foreground rights" check, --activate-on-hotkey).
"""
import argparse
import ctypes
import ctypes.wintypes as W
import json
import os
import sys
import time

from PyQt6 import sip
from PyQt6.QtCore import QAbstractNativeEventFilter, Qt, QTimer
from PyQt6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.RegisterHotKey.argtypes = [W.HWND, ctypes.c_int, W.UINT, W.UINT]
user32.RegisterHotKey.restype = W.BOOL
user32.UnregisterHotKey.argtypes = [W.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = W.BOOL
user32.SetForegroundWindow.argtypes = [W.HWND]
user32.SetForegroundWindow.restype = W.BOOL
user32.GetForegroundWindow.restype = W.HWND
WM_HOTKEY, WM_APP = 0x0312, 0x8000
MOD_NOREPEAT = 0x4000


class Logger:
    def __init__(self, path):
        self.f = open(path, "a", encoding="utf-8", buffering=1)

    def __call__(self, ev, **kw):
        self.f.write(json.dumps({"t_ns": time.perf_counter_ns(), "ev": ev, **kw}) + "\n")
        self.f.flush()


def ret_value(kind):
    return 0 if kind == "int" else sip.voidptr(0)


class HotkeyFilter(QAbstractNativeEventFilter):
    """QAbstractNativeEventFilter variant. eventType is b'windows_dispatcher_MSG' (seen by the event
    dispatcher before DispatchMessage, also for thread messages with hwnd=NULL) or
    b'windows_generic_MSG' (seen again inside Qt's window procedure)."""

    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    def nativeEventFilter(self, eventType, message):
        msg = W.MSG.from_address(int(message))
        if msg.message == WM_HOTKEY:
            self.owner.on_hotkey(msg, via="filter:" + bytes(eventType).decode())
            if self.owner.a.filter_consume:      # True = handled: Qt stops processing (seen once)
                return True, ret_value(self.owner.a.ret)
        return False, ret_value(self.owner.a.ret)


class HotkeyWindow(QWidget):
    def __init__(self, a):
        super().__init__()
        self.a = a
        self.log = Logger(a.log)
        self.setWindowTitle(a.title)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        lay = QVBoxLayout(self)
        self.label = QLabel(f"hotkey receiver ({a.mode})")
        lay.addWidget(self.label)
        self.setGeometry(1300, 100, 320, 80)
        self.count = 0
        self.reg_hwnd = None

    def hwnd(self):
        return int(self.winId())

    def register(self):
        mods = self.a.mods | (MOD_NOREPEAT if self.a.norepeat else 0)
        self.reg_hwnd = None if self.a.mode == "filter_thread" else self.hwnd()
        ok = user32.RegisterHotKey(self.reg_hwnd, self.a.id, mods, self.a.vk)
        err = ctypes.get_last_error()
        dup_ok = user32.RegisterHotKey(self.reg_hwnd, self.a.id + 1, mods, self.a.vk)   # same combo again
        dup_err = ctypes.get_last_error()
        if dup_ok:
            user32.UnregisterHotKey(self.reg_hwnd, self.a.id + 1)
        res = {"ok": bool(ok), "err": err, "dup_same_process_ok": bool(dup_ok), "dup_err": dup_err,
               "mods": mods, "vk": self.a.vk, "hwnd_registered": self.reg_hwnd}
        self.log("register", **res)
        info = {"hwnd": self.hwnd(), "pid": os.getpid(), "mode": self.a.mode, **res}
        with open(self.a.info + ".tmp", "w", encoding="utf-8") as f:
            json.dump(info, f)
        os.replace(self.a.info + ".tmp", self.a.info)

    def on_hotkey(self, msg, via):
        self.count += 1
        lp = msg.lParam
        self.log("hotkey", via=via, id=msg.wParam, mods=lp & 0xFFFF, vk=(lp >> 16) & 0xFFFF, n=self.count,
                 msg_hwnd=int(msg.hWnd or 0))
        self.label.setText(f"WM_HOTKEY x{self.count}")
        if self.a.activate_on_hotkey:
            self.try_activate("hotkey")

    def try_activate(self, why):
        ok = user32.SetForegroundWindow(self.hwnd())
        time.sleep(0.05)
        self.log("activate_try", why=why, ret=bool(ok), fg_is_me=int(user32.GetForegroundWindow() or 0) == self.hwnd())

    def nativeEvent(self, eventType, message):
        """PyQt6 6.12 signature: nativeEvent(self, eventType: QByteArray, message: sip.voidptr)
        -> tuple[bool, sip.voidptr | int]. message points at a Win32 MSG."""
        msg = W.MSG.from_address(int(message))
        if msg.message == WM_HOTKEY and self.a.mode == "nativeevent":
            self.on_hotkey(msg, via="nativeEvent:" + bytes(eventType).decode())
            return True, ret_value(self.a.ret)
        if msg.message == WM_APP + 1:
            self.try_activate("control_postmessage")
            return True, ret_value(self.a.ret)
        return False, ret_value(self.a.ret)

    def closeEvent(self, ev):
        ok = user32.UnregisterHotKey(self.reg_hwnd, self.a.id)
        self.log("unregister", ok=bool(ok), err=ctypes.get_last_error())
        super().closeEvent(ev)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True)
    ap.add_argument("--info", required=True)
    ap.add_argument("--title", default=f"WA Hotkey {os.getpid()}")
    ap.add_argument("--pos", default="1300,100")
    ap.add_argument("--mode", choices=["nativeevent", "filter", "filter_thread"], default="nativeevent")
    ap.add_argument("--vk", type=lambda s: int(s, 0), default=0x78)          # F9
    ap.add_argument("--mods", type=lambda s: int(s, 0), default=0x6)         # MOD_CONTROL | MOD_SHIFT
    ap.add_argument("--norepeat", type=int, default=1)
    ap.add_argument("--id", type=int, default=1)
    ap.add_argument("--ret", choices=["int", "voidptr"], default="int")
    ap.add_argument("--activate-on-hotkey", action="store_true")
    ap.add_argument("--filter-consume", action="store_true")
    ap.add_argument("--ime", default="on")                                   # accepted for harness symmetry
    a = ap.parse_args()
    app = QApplication(sys.argv[:1])
    win = HotkeyWindow(a)
    if a.mode != "nativeevent":
        filt = HotkeyFilter(win)
        app.installNativeEventFilter(filt)
    win.show()
    QTimer.singleShot(100, win.register)
    if a.activate_on_hotkey:
        QTimer.singleShot(300, lambda: win.try_activate("startup"))   # use up the fresh-process right
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
