"""wa_target_app.py - Qt6 test target for the AutoPress Win32 input research (R2a).

A small window with a QLineEdit, a "Submit" QPushButton and a status label. Every event it receives
(text changes, submit with the line-edit content, key / IME / focus / mouse / activation events,
optional raw-input and GetAsyncKeyState polling) is appended as one JSON line to --log.
At startup (and after every move/resize) it writes its HWND and the PHYSICAL screen rects of the
client area, the line edit and the Submit button to --info.

Run (from the project root):
  .venv/Scripts/python.exe docs/research/scripts/win32/wa_target_app.py --log L.jsonl --info I.json
      [--title "WA Target x"] [--pos 300,300] [--ime on|off|qtattr] [--poll] [--rawinput]
Drivers normally launch it through wa_harness.Target.
"""
import argparse
import ctypes
import ctypes.wintypes as W
import json
import os
import sys
import time

from PyQt6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

user32 = ctypes.WinDLL("user32", use_last_error=True)
imm32 = ctypes.WinDLL("imm32", use_last_error=True)
user32.ClientToScreen.argtypes = [W.HWND, ctypes.POINTER(W.POINT)]
user32.ClientToScreen.restype = W.BOOL
user32.GetClientRect.argtypes = [W.HWND, ctypes.POINTER(W.RECT)]
user32.GetWindowRect.argtypes = [W.HWND, ctypes.POINTER(W.RECT)]
user32.GetWindowThreadProcessId.argtypes = [W.HWND, ctypes.POINTER(W.DWORD)]
user32.GetWindowThreadProcessId.restype = W.DWORD
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = W.SHORT
user32.GetKeyState.argtypes = [ctypes.c_int]
user32.GetKeyState.restype = W.SHORT
imm32.ImmGetContext.argtypes = [W.HWND]
imm32.ImmGetContext.restype = W.HANDLE
imm32.ImmReleaseContext.argtypes = [W.HWND, W.HANDLE]
imm32.ImmGetOpenStatus.argtypes = [W.HANDLE]
imm32.ImmGetOpenStatus.restype = W.BOOL
imm32.ImmGetConversionStatus.argtypes = [W.HANDLE, ctypes.POINTER(W.DWORD), ctypes.POINTER(W.DWORD)]
imm32.ImmGetConversionStatus.restype = W.BOOL


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [("usUsagePage", W.USHORT), ("usUsage", W.USHORT), ("dwFlags", W.DWORD), ("hwndTarget", W.HWND)]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [("dwType", W.DWORD), ("dwSize", W.DWORD), ("hDevice", W.HANDLE), ("wParam", W.WPARAM)]


class RAWKEYBOARD(ctypes.Structure):
    _fields_ = [("MakeCode", W.USHORT), ("Flags", W.USHORT), ("Reserved", W.USHORT), ("VKey", W.USHORT),
                ("Message", W.UINT), ("ExtraInformation", W.ULONG)]


class RAWINPUTKB(ctypes.Structure):
    _fields_ = [("header", RAWINPUTHEADER), ("keyboard", RAWKEYBOARD)]


user32.RegisterRawInputDevices.argtypes = [ctypes.POINTER(RAWINPUTDEVICE), W.UINT, W.UINT]
user32.RegisterRawInputDevices.restype = W.BOOL
user32.GetRawInputData.argtypes = [W.HANDLE, W.UINT, ctypes.c_void_p, ctypes.POINTER(W.UINT), W.UINT]
user32.GetRawInputData.restype = W.UINT
WM_INPUT, RID_INPUT = 0x00FF, 0x10000003


class Logger:
    def __init__(self, path):
        self.f = open(path, "a", encoding="utf-8", buffering=1)

    def __call__(self, ev, **kw):
        kw = {"t_ns": time.perf_counter_ns(), "ev": ev, **kw}
        self.f.write(json.dumps(kw, ensure_ascii=False) + "\n")
        self.f.flush()


def mods_int(m):
    try:
        return int(m.value)
    except AttributeError:
        return int(m)


class Spy(QObject):
    def __init__(self, log):
        super().__init__()
        self.log = log

    def eventFilter(self, obj, ev):
        t = ev.type()
        name = obj.objectName()
        if t in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            self.log("key", w=name, kind="down" if t == QEvent.Type.KeyPress else "up", key=ev.key(),
                     text=ev.text(), vk=ev.nativeVirtualKey(), sc=ev.nativeScanCode(), mods=mods_int(ev.modifiers()),
                     rep=ev.isAutoRepeat())
        elif t == QEvent.Type.InputMethod:
            self.log("im", w=name, preedit=ev.preeditString(), commit=ev.commitString())
        elif t in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            self.log("focus", w=name, kind="in" if t == QEvent.Type.FocusIn else "out", reason=mods_int(ev.reason()))
        elif t in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick):
            kind = {QEvent.Type.MouseButtonPress: "press", QEvent.Type.MouseButtonRelease: "release"}.get(t, "dblclick")
            p, g = ev.position(), ev.globalPosition()
            self.log("mouse", w=name, kind=kind, btn=mods_int(ev.button()), x=p.x(), y=p.y(), gx=g.x(), gy=g.y())
        return False


class Target(QWidget):
    def __init__(self, a):
        super().__init__()
        self.a = a
        self.log = Logger(a.log)
        self.setWindowTitle(a.title)
        self.setObjectName("window")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("AutoPress input test target - do not type here"))
        row = QHBoxLayout()
        self.edit = QLineEdit(objectName="edit", placeholderText="code")
        self.btn = QPushButton("Submit", objectName="submit")
        self.btn.setMinimumSize(110, 36)
        row.addWidget(self.edit, 1)
        row.addWidget(self.btn)
        lay.addLayout(row)
        self.status = QLabel("ready", objectName="status")
        lay.addWidget(self.status)
        if a.ime in ("off", "qtattr"):
            self.edit.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, False)
        self.spy = Spy(self.log)
        for w in (self, self.edit, self.btn):
            w.installEventFilter(self.spy)
        self.edit.textChanged.connect(lambda s: self.log("text", text=s))
        self.edit.returnPressed.connect(lambda: self.submit("enter"))
        self.btn.clicked.connect(lambda: self.submit("click"))
        x, y = (int(v) for v in a.pos.split(","))
        self.setGeometry(x, y, 480, 170)
        self._ime_last = None
        self._poll_prev = {}
        self.timer = QTimer(self, interval=250, timeout=self.poll_ime)
        self.timer.start()
        if a.poll:
            self.pt = QTimer(self, interval=16, timerType=Qt.TimerType.PreciseTimer, timeout=self.poll_keys)
            self.pt.start()

    # --- logging helpers
    def submit(self, src):
        self.log("submit", src=src, text=self.edit.text())
        self.status.setText(f"submitted ({src}): {self.edit.text()}")

    def hwnd(self):
        return int(self.winId())

    def poll_ime(self):
        h = self.hwnd()
        himc = imm32.ImmGetContext(h)
        state = None
        if himc:
            conv, sent = W.DWORD(), W.DWORD()
            imm32.ImmGetConversionStatus(himc, ctypes.byref(conv), ctypes.byref(sent))
            state = {"open": bool(imm32.ImmGetOpenStatus(himc)), "conv": conv.value}
            imm32.ImmReleaseContext(h, himc)
        caps = user32.GetKeyState(0x14) & 1
        cur = (json.dumps(state), caps)
        if cur != self._ime_last:
            self._ime_last = cur
            self.log("ime_state", state=state, caps=caps)

    def poll_keys(self):
        for vk in list(range(0x30, 0x3A)) + list(range(0x41, 0x5B)):
            s = user32.GetAsyncKeyState(vk)
            down = bool(s & 0x8000)
            if down and not self._poll_prev.get(vk):
                self.log("poll_edge", vk=vk)
            elif s & 1 and not down:
                self.log("poll_lsb", vk=vk)
            self._poll_prev[vk] = down

    def write_info(self):
        h = self.hwnd()
        pt = W.POINT(0, 0)
        user32.ClientToScreen(h, ctypes.byref(pt))
        dpr = self.devicePixelRatioF()

        def phys(w):
            off = w.mapTo(self, QPoint(0, 0))
            x0, y0 = pt.x + round(off.x() * dpr), pt.y + round(off.y() * dpr)
            return [x0, y0, x0 + round(w.width() * dpr), y0 + round(w.height() * dpr)]

        wr, cr = W.RECT(), W.RECT()
        user32.GetWindowRect(h, ctypes.byref(wr))
        user32.GetClientRect(h, ctypes.byref(cr))
        pid = W.DWORD()
        tid = user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        g = self.btn.mapToGlobal(QPoint(0, 0))
        info = {"hwnd": h, "pid": os.getpid(), "tid": tid, "title": self.windowTitle(), "dpr": dpr,
                "window_rect": [wr.left, wr.top, wr.right, wr.bottom],
                "client_rect": [pt.x, pt.y, pt.x + cr.right, pt.y + cr.bottom],
                "edit_rect": phys(self.edit), "submit_rect": phys(self.btn),
                "submit_logical_global": [g.x(), g.y(), self.btn.width(), self.btn.height()],
                "screen": self.screen().name() if self.screen() else None, "t_ns": time.perf_counter_ns()}
        tmp = self.a.info + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(info, f, indent=1)
        os.replace(tmp, self.a.info)

    # --- Qt overrides
    def event(self, ev):
        if ev.type() in (QEvent.Type.WindowActivate, QEvent.Type.WindowDeactivate):
            self.log("activate", on=ev.type() == QEvent.Type.WindowActivate)
        return super().event(ev)

    def moveEvent(self, ev):
        super().moveEvent(ev)
        if self.isVisible():
            QTimer.singleShot(50, self.write_info)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self.isVisible():
            QTimer.singleShot(50, self.write_info)

    def closeEvent(self, ev):
        self.log("quit")
        super().closeEvent(ev)

    def nativeEvent(self, eventType, message):
        if self.a.rawinput and eventType == b"windows_generic_MSG":
            msg = W.MSG.from_address(int(message))
            if msg.message == WM_INPUT:
                buf = RAWINPUTKB()
                size = W.UINT(ctypes.sizeof(buf))
                n = user32.GetRawInputData(msg.lParam, RID_INPUT, ctypes.byref(buf), ctypes.byref(size),
                                           ctypes.sizeof(RAWINPUTHEADER))
                if n != 0xFFFFFFFF and buf.header.dwType == 1:
                    k = buf.keyboard
                    self.log("raw", mk=k.MakeCode, fl=k.Flags, vk=k.VKey, msg=k.Message, extra=k.ExtraInformation,
                             dev=int(buf.header.hDevice or 0))
        return False, 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True)
    ap.add_argument("--info", required=True)
    ap.add_argument("--title", default=f"WA Target {os.getpid()}")
    ap.add_argument("--pos", default="300,300")
    ap.add_argument("--ime", choices=["on", "off", "qtattr"], default="on")   # qtattr: Qt attribute only
    ap.add_argument("--poll", action="store_true")
    ap.add_argument("--rawinput", action="store_true")
    a = ap.parse_args()
    if a.ime == "off":
        # WA_InputMethodEnabled=False alone did NOT detach the zh-TW Bopomofo (TSF) IME in Qt 6.12;
        # ImmDisableIME(-1) before the first window is created does (verified via ime_state=None).
        imm32.ImmDisableIME.argtypes = [W.DWORD]
        imm32.ImmDisableIME.restype = W.BOOL
        imm32.ImmDisableIME(0xFFFFFFFF)
    app = QApplication(sys.argv[:1])
    w = Target(a)
    w.show()
    w.log("start", pid=os.getpid(), hwnd=w.hwnd(), title=a.title, ime=a.ime)
    if a.rawinput:
        rid = RAWINPUTDEVICE(1, 6, 0x00000100, w.hwnd())     # keyboard, RIDEV_INPUTSINK
        ok = user32.RegisterRawInputDevices(ctypes.byref(rid), 1, ctypes.sizeof(rid))
        w.log("rawinput_registered", ok=bool(ok), err=ctypes.get_last_error())
    w.edit.setFocus()
    QTimer.singleShot(300, w.write_info)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
