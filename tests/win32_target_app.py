# OWNED BY G3
"""Test target window for the G3 realinput tests (a separate PyQt6 process, modelled on
docs/research/scripts/win32/wa_target_app.py).

A QLineEdit, a "Submit" button and a status label; every event it receives (text changes,
submits with the field content, keys, mouse buttons, focus, activation, IME state) is appended
as one JSON line to ``--log``. ``--info`` gets (atomically, at start and after every move /
resize) the HWND, pid and PHYSICAL rects [x, y, w, h] of the client area, the line edit, the
Submit button, a point on the bare window background and - with ``--second-window`` - a second
top-level window of the same process with its own button.

    .venv/Scripts/python.exe tests/win32_target_app.py --log L.jsonl --info I.json
        [--title T] [--pos X,Y] [--size W,H] [--rect X,Y,W,H] [--ime on|off] [--topmost]
        [--second-window] [--quit-after-ms N]

``--rect`` places the native window at a PHYSICAL rect with SetWindowPos (cover windows);
``--topmost`` keeps it above normal windows; ``--ime off`` detaches the IME (ImmDisableIME
before the first window - Qt's WA_InputMethodEnabled alone did not, research); ``--quit-after-ms``
quits by itself (smoke tests on the offscreen platform). Launch it with the ``clean_env`` fixture
(real windows platform) and close it with WM_CLOSE.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as W
import json
import math
import os
import sys
import time

from PyQt6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_imm32 = ctypes.WinDLL("imm32", use_last_error=True)


def _f(dll: object, name: str, restype: object, *argtypes: object) -> object:
    fn = getattr(dll, name)
    fn.restype = restype
    fn.argtypes = list(argtypes)
    return fn


ClientToScreen = _f(_user32, "ClientToScreen", W.BOOL, W.HWND, ctypes.POINTER(W.POINT))
GetClientRect = _f(_user32, "GetClientRect", W.BOOL, W.HWND, ctypes.POINTER(W.RECT))
SetWindowPos = _f(_user32, "SetWindowPos", W.BOOL, W.HWND, W.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                  ctypes.c_int, W.UINT)
ImmGetContext = _f(_imm32, "ImmGetContext", W.HANDLE, W.HWND)
ImmReleaseContext = _f(_imm32, "ImmReleaseContext", W.BOOL, W.HWND, W.HANDLE)
ImmGetOpenStatus = _f(_imm32, "ImmGetOpenStatus", W.BOOL, W.HANDLE)
ImmGetConversionStatus = _f(_imm32, "ImmGetConversionStatus", W.BOOL, W.HANDLE, ctypes.POINTER(W.DWORD),
                            ctypes.POINTER(W.DWORD))
ImmDisableIME = _f(_imm32, "ImmDisableIME", W.BOOL, W.DWORD)
HWND_TOPMOST = W.HWND(-1)
SWP_NOACTIVATE = 0x0010


def qround(v: float) -> int:
    return int(math.floor(v + 0.5)) if v >= 0 else -int(math.floor(-v + 0.5))


class Logger:
    def __init__(self, path: str) -> None:
        self.f = open(path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 - process lifetime

    def __call__(self, ev: str, **kw: object) -> None:
        self.f.write(json.dumps({"t_ns": time.perf_counter_ns(), "ev": ev, **kw}, ensure_ascii=False) + "\n")
        self.f.flush()


def _int(v: object) -> int:
    return int(getattr(v, "value", v))


class Spy(QObject):
    def __init__(self, log: Logger) -> None:
        super().__init__()
        self.log = log

    def eventFilter(self, obj: QObject, ev: QEvent) -> bool:  # noqa: N802 - Qt override
        t = ev.type()
        name = obj.objectName()
        if t in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            self.log("key", w=name, kind="down" if t == QEvent.Type.KeyPress else "up", key=ev.key(),
                     text=ev.text(), vk=ev.nativeVirtualKey(), sc=ev.nativeScanCode(), mods=_int(ev.modifiers()))
        elif t in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick):
            kind = {QEvent.Type.MouseButtonPress: "press", QEvent.Type.MouseButtonRelease: "release"}.get(t, "dblclick")
            self.log("mouse", w=name, kind=kind, btn=_int(ev.button()))
        elif t in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            self.log("focus", w=name, kind="in" if t == QEvent.Type.FocusIn else "out")
        return False


def _phys(top: QWidget, w: QWidget) -> list[int]:
    """Physical [x, y, w, h] of ``w``: ClientToScreen(top HWND) + qRound(local * dpr)."""
    pt = W.POINT(0, 0)
    ClientToScreen(int(top.winId()), ctypes.byref(pt))
    dpr = top.devicePixelRatioF()
    off = w.mapTo(top, QPoint(0, 0)) if w is not top else QPoint(0, 0)
    return [pt.x + qround(off.x() * dpr), pt.y + qround(off.y() * dpr), qround(w.width() * dpr),
            qround(w.height() * dpr)]


class Second(QWidget):
    def __init__(self, log: Logger, title: str) -> None:
        super().__init__()
        self.setWindowTitle(title + " (second)")
        self.setObjectName("second")
        lay = QVBoxLayout(self)
        self.btn = QPushButton("Second", objectName="second_button")
        self.btn.setMinimumSize(110, 36)
        lay.addWidget(self.btn)
        self.btn.clicked.connect(lambda: log("second_click"))


class Target(QWidget):
    def __init__(self, a: argparse.Namespace) -> None:
        super().__init__()
        self.a = a
        self.log = Logger(a.log)
        self.setWindowTitle(a.title)
        self.setObjectName("window")
        flags = self.windowFlags()
        if a.topmost:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("AutoPress G3 input test target - do not type here"))
        row = QHBoxLayout()
        self.edit = QLineEdit(objectName="edit", placeholderText="code")
        self.btn = QPushButton("Submit", objectName="submit")
        self.btn.setMinimumSize(110, 36)
        row.addWidget(self.edit, 1)
        row.addWidget(self.btn)
        lay.addLayout(row)
        lay.addStretch(1)
        self.status = QLabel("ready", objectName="status")
        lay.addWidget(self.status)
        self.spy = Spy(self.log)
        for w in (self, self.edit, self.btn):
            w.installEventFilter(self.spy)
        self.edit.textChanged.connect(lambda s: self.log("text", text=s))
        self.edit.returnPressed.connect(lambda: self.submit("enter"))
        self.btn.clicked.connect(lambda: self.submit("click"))
        x, y = (int(v) for v in a.pos.split(","))
        w, h = (int(v) for v in a.size.split(","))
        self.setGeometry(x, y, w, h)
        self.second: Second | None = None
        if a.second_window:
            self.second = Second(self.log, a.title)
            self.second.setGeometry(x + w + 60, y, 260, 120)
            self.second.btn.installEventFilter(self.spy)
        self._ime_last: object = None
        self.timer = QTimer(self, interval=200, timeout=self.poll_ime)
        self.timer.start()

    def submit(self, src: str) -> None:
        self.log("submit", src=src, text=self.edit.text())
        self.status.setText(f"submitted ({src}): {self.edit.text()}")

    def hwnd(self) -> int:
        return int(self.winId())

    def poll_ime(self) -> None:
        h = self.hwnd()
        himc = ImmGetContext(h)
        state = None
        if himc:
            conv, sent = W.DWORD(), W.DWORD()
            ImmGetConversionStatus(himc, ctypes.byref(conv), ctypes.byref(sent))
            state = {"open": bool(ImmGetOpenStatus(himc)), "conv": conv.value}
            ImmReleaseContext(h, himc)
        if state != self._ime_last:
            self._ime_last = state
            self.log("ime_state", state=state)

    def place_physical(self) -> None:
        if not self.a.rect:
            return
        x, y, w, h = (int(v) for v in self.a.rect.split(","))
        after = HWND_TOPMOST if self.a.topmost else None
        flags = SWP_NOACTIVATE | (0 if self.a.topmost else 0x0004)  # 0x0004 = SWP_NOZORDER
        SetWindowPos(self.hwnd(), after, x, y, w, h, flags)

    def write_info(self) -> None:
        cr = W.RECT()
        GetClientRect(self.hwnd(), ctypes.byref(cr))
        client = _phys(self, self)
        client[2], client[3] = cr.right, cr.bottom
        info = {"hwnd": self.hwnd(), "pid": os.getpid(), "title": self.windowTitle(), "dpr": self.devicePixelRatioF(),
                "client_rect": client, "edit_rect": _phys(self, self.edit), "submit_rect": _phys(self, self.btn),
                "status_rect": _phys(self, self.status), "t_ns": time.perf_counter_ns()}
        sx, sy, sw, sh = info["status_rect"]
        info["blank_point"] = [client[0] + client[2] - 4, sy + sh // 2]  # right of the status text
        if self.second is not None:
            info["second_hwnd"] = int(self.second.winId())
            info["second_button_rect"] = _phys(self.second, self.second.btn)
        tmp = self.a.info + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(info, f, indent=1)
        os.replace(tmp, self.a.info)

    def event(self, ev: QEvent) -> bool:
        if ev.type() in (QEvent.Type.WindowActivate, QEvent.Type.WindowDeactivate):
            self.log("activate", on=ev.type() == QEvent.Type.WindowActivate)
        return super().event(ev)

    def moveEvent(self, ev: object) -> None:  # noqa: N802 - Qt override
        super().moveEvent(ev)
        if self.isVisible():
            QTimer.singleShot(50, self.write_info)

    def resizeEvent(self, ev: object) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(ev)
        if self.isVisible():
            QTimer.singleShot(50, self.write_info)

    def closeEvent(self, ev: object) -> None:  # noqa: N802 - Qt override
        self.log("quit")
        if self.second is not None:
            self.second.close()
        super().closeEvent(ev)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True)
    ap.add_argument("--info", required=True)
    ap.add_argument("--title", default=f"AutoPress G3 target {os.getpid()}")
    ap.add_argument("--pos", default="300,300")
    ap.add_argument("--size", default="480,190")
    ap.add_argument("--rect", default="")
    ap.add_argument("--ime", choices=["on", "off"], default="off")
    ap.add_argument("--topmost", action="store_true")
    ap.add_argument("--second-window", action="store_true")
    ap.add_argument("--quit-after-ms", type=int, default=0)
    a = ap.parse_args()
    if a.ime == "off":
        ImmDisableIME(0xFFFFFFFF)
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(True)
    w = Target(a)
    w.show()
    if w.second is not None:
        w.second.show()
    w.place_physical()
    w.log("start", pid=os.getpid(), hwnd=w.hwnd(), title=a.title, ime=a.ime)
    w.edit.setFocus()
    QTimer.singleShot(300, w.write_info)
    if a.quit_after_ms > 0:
        QTimer.singleShot(a.quit_after_ms, app.quit)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
