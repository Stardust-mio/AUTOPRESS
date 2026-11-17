# OWNED BY G4
"""Fake redemption window for end-to-end tests and demos (a separate PyQt6 process).

    .venv/Scripts/python.exe tools/fake_redeem_app.py --title "AutoPress Fake 1234" \
        --lang zh-TW --boxes 1 --valid AAAA-1111,BBBB-2222 --rate-limit 0 \
        --popup label --popup-on always --latency-ms 0 --persist \
        --log C:/.../events.jsonl --info C:/.../info.json

Spec (SPEC section 8.4): label 請輸入兌換碼 / Enter your redeem code; 1 or 3 QLineEdits
(--boxes 3: auto-advance after 5 characters, or --groups 4,6,2 for unequal boxes); buttons
兌換 / Redeem and 取消 / Cancel; result messages 兌換成功 (valid, first time), 此序號已被使用
(valid, again), 兌換碼已過期 (codes starting with EXP), 操作過於頻繁，請稍後再試 (more than
--rate-limit submits within 10 s; 0 = off), 兌換碼無效 (otherwise) - English equivalents with
--lang en; --popup label|dialog (dialog = modal QDialog with a 確定 / OK button);
--popup-on success|always|never (which results open the dialog; the others show inline);
--latency-ms N (the result appears N ms after the submit); --persist (the label keeps the
previous result until the new one replaces it - stale-read tests for ocr_check only_new_text).
Logs every submit/result as JSON lines and writes HWND, pid and PHYSICAL rects of inputs,
buttons and result area to --info.

Additions: --used A,B (codes that count as already redeemed from the start), --no-advance
(multi-box pages that do NOT jump to the next box; Tab moves on), --advance-no-select (the jump
does not select the next box, like a web page's focus()), --prefill A,B,C (start texts of the
boxes: a page that kept the previous code), --pos X,Y and --size W,H
(logical window geometry). Codes are compared without whitespace, "-" and "_", case
kept. Auto-advance selects the next box's text, so typing replaces an old segment. Rects in the
info file and in ``popup_open`` events are physical [x, y, w, h]; the info file is rewritten
after every move / resize. The window never steals focus by itself and holds no global state:
tests start it with ``clean_env`` and find it by its unique title (or the info file's hwnd).
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QPoint, Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

TEXTS = {
    "zh-TW": {"prompt": "請輸入兌換碼", "redeem": "兌換", "cancel": "取消", "ok": "確定", "success": "兌換成功",
              "used": "此序號已被使用", "expired": "兌換碼已過期", "rate_limited": "操作過於頻繁，請稍後再試",
              "invalid": "兌換碼無效", "dialog_title": "兌換結果"},
    "en": {"prompt": "Enter your redeem code", "redeem": "Redeem", "cancel": "Cancel", "ok": "OK",
           "success": "Code redeemed successfully", "used": "This code has already been used",
           "expired": "This code has expired", "rate_limited": "Too many requests, please try again later",
           "invalid": "Invalid code", "dialog_title": "Result"},
}
RATE_WINDOW_S = 10.0


def code_key(text: str) -> str:
    return "".join(c for c in text if not c.isspace() and c not in "-_")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="AutoPress fake redeem window (tests and demos)")
    ap.add_argument("--title", default=f"AutoPress Fake {os.getpid()}")
    ap.add_argument("--lang", choices=sorted(TEXTS), default="zh-TW")
    ap.add_argument("--boxes", type=int, choices=(1, 3), default=1)
    ap.add_argument("--groups", default="", help="box sizes, e.g. 4,6,2 (overrides --boxes)")
    ap.add_argument("--no-advance", action="store_true", help="full boxes do not move the focus on")
    ap.add_argument("--advance-no-select", action="store_true",
                    help="auto-advance moves the focus like a web page's focus(): the next box's text is NOT selected")
    ap.add_argument("--prefill", default="", help="comma-separated start texts of the boxes (e.g. OLD1,OLDOLD,OL)")
    ap.add_argument("--valid", default="", help="comma-separated valid codes")
    ap.add_argument("--used", default="", help="comma-separated codes that are already redeemed")
    ap.add_argument("--rate-limit", type=int, default=0, help="max submits per 10 s (0 = off)")
    ap.add_argument("--popup", choices=("label", "dialog"), default="label")
    ap.add_argument("--popup-on", choices=("success", "always", "never"), default="always")
    ap.add_argument("--latency-ms", type=int, default=0)
    ap.add_argument("--persist", action="store_true")
    ap.add_argument("--log", default="")
    ap.add_argument("--info", default="")
    ap.add_argument("--pos", default="300,300")
    ap.add_argument("--size", default="560,340")
    a = ap.parse_args(argv)
    if a.groups:
        a.group_sizes = [int(g) for g in a.groups.split(",") if g.strip()]
        if not a.group_sizes or any(g <= 0 for g in a.group_sizes):
            ap.error("--groups needs positive sizes")
    elif a.boxes == 3:
        a.group_sizes = [5, 5, 5]
    else:
        a.group_sizes = []
    return a


def _client_origin(widget: QWidget) -> tuple[int, int] | None:
    """Physical screen position of the widget's top-level client area (ClientToScreen)."""
    if sys.platform != "win32":
        return None
    try:
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        user32.ClientToScreen.restype = wintypes.BOOL
        user32.IsWindow.argtypes = [wintypes.HWND]
        user32.IsWindow.restype = wintypes.BOOL
        hwnd = int(widget.window().winId())
        if not hwnd or not user32.IsWindow(hwnd):
            return None
        pt = wintypes.POINT(0, 0)
        if not user32.ClientToScreen(hwnd, ctypes.byref(pt)):
            return None
        return pt.x, pt.y
    except (OSError, AttributeError, ValueError):
        return None


def physical_rect(widget: QWidget) -> list[int]:
    """[x, y, w, h] in physical pixels (ClientToScreen of the top level + local offset x dpr)."""
    top = widget.window()
    dpr = top.devicePixelRatioF() or 1.0
    origin = _client_origin(top)
    if origin is None:  # offscreen / no native window: logical global position x dpr
        g = top.mapToGlobal(QPoint(0, 0))
        origin = (round(g.x() * dpr), round(g.y() * dpr))
    off = widget.mapTo(top, QPoint(0, 0)) if widget is not top else QPoint(0, 0)
    return [origin[0] + round(off.x() * dpr), origin[1] + round(off.y() * dpr),
            round(widget.width() * dpr), round(widget.height() * dpr)]


class EventLog:
    def __init__(self, path: str) -> None:
        self.path = path
        self.events: list[dict[str, Any]] = []

    def __call__(self, ev: str, **fields: Any) -> None:
        rec = {"t": round(time.time(), 3), "ev": ev, **fields}
        self.events.append(rec)
        if self.path:
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


class ResultDialog(QDialog):
    def __init__(self, parent: QWidget, title: str, text: str, ok: str) -> None:
        super().__init__(parent)
        self.setObjectName("result_dialog")
        self.setWindowTitle(title)
        self.setModal(True)
        lay = QVBoxLayout(self)
        self.label = QLabel(text, objectName="dialog_message")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f = self.label.font()
        f.setPointSize(14)
        self.label.setFont(f)
        lay.addWidget(self.label)
        self.ok = QPushButton(ok, objectName="dialog_ok")
        self.ok.setMinimumSize(100, 36)
        self.ok.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.ok)
        row.addStretch(1)
        lay.addLayout(row)
        self.resize(320, 150)


class FakeRedeemWindow(QWidget):
    def __init__(self, args: argparse.Namespace) -> None:
        super().__init__()
        self.args = args
        self.t = TEXTS[args.lang]
        self.log = EventLog(args.log)
        self.valid = {code_key(c) for c in args.valid.split(",") if c.strip()}
        self.redeemed = {code_key(c) for c in args.used.split(",") if c.strip()}
        self.submits: list[float] = []
        self.dialog: ResultDialog | None = None
        self.last_kind = ""
        self.setWindowTitle(args.title)
        self.setObjectName("window")
        lay = QVBoxLayout(self)
        self.prompt = QLabel(self.t["prompt"], objectName="prompt")
        big = self.prompt.font()
        big.setPointSize(14)
        self.prompt.setFont(big)
        lay.addWidget(self.prompt)
        row = QHBoxLayout()
        sizes = args.group_sizes or [0]
        self.inputs: list[QLineEdit] = []
        for n, size in enumerate(sizes):
            edit = QLineEdit(objectName=f"input{n}")
            edit.setFont(big)
            edit.setMinimumHeight(40)
            if size:
                edit.setMaxLength(size)
            edit.textChanged.connect(lambda _s, i=n: self._advance(i))
            edit.returnPressed.connect(lambda: self.submit("enter"))
            row.addWidget(edit, max(1, size))
            self.inputs.append(edit)
        lay.addLayout(row)
        for edit, text in zip(self.inputs, [t.strip() for t in args.prefill.split(",")] if args.prefill else []):
            edit.setText(text)  # a page that kept the previous code (gate G-08 e2e)
        buttons = QHBoxLayout()
        self.redeem_btn = QPushButton(self.t["redeem"], objectName="redeem")
        self.cancel_btn = QPushButton(self.t["cancel"], objectName="cancel")
        for b in (self.redeem_btn, self.cancel_btn):
            b.setFont(big)
            b.setMinimumSize(120, 40)
            buttons.addWidget(b)
        buttons.addStretch(1)
        self.redeem_btn.clicked.connect(lambda: self.submit("click"))
        self.cancel_btn.clicked.connect(self.cancel)
        lay.addLayout(buttons)
        self.result = QLabel("", objectName="result")
        self.result.setFont(big)
        self.result.setMinimumHeight(70)
        self.result.setWordWrap(True)
        self.result.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self.result)
        lay.addStretch(1)
        x, y = (int(v) for v in args.pos.split(","))
        w, h = (int(v) for v in args.size.split(","))
        self.setGeometry(x, y, w, h)

    # ---------------------------------------------------------------- behaviour
    def _advance(self, i: int) -> None:
        sizes = self.args.group_sizes
        if not sizes or self.args.no_advance or i + 1 >= len(self.inputs):
            return
        if len(self.inputs[i].text()) >= sizes[i] and self.inputs[i].hasFocus():
            nxt = self.inputs[i + 1]
            nxt.setFocus(Qt.FocusReason.OtherFocusReason)
            if self.args.advance_no_select:
                nxt.deselect()
                nxt.end(False)
            else:
                nxt.selectAll()

    def code(self) -> str:
        return "-".join(e.text() for e in self.inputs) if len(self.inputs) > 1 else self.inputs[0].text()

    def classify(self, code: str, now: float) -> str:
        self.submits = [t for t in self.submits if now - t < RATE_WINDOW_S] + [now]
        if self.args.rate_limit > 0 and len(self.submits) > self.args.rate_limit:
            return "rate_limited"
        key = code_key(code)
        if key in self.valid or key in self.redeemed:
            if key in self.redeemed:
                return "used"
            self.redeemed.add(key)
            return "success"
        if key.upper().startswith("EXP"):
            return "expired"
        return "invalid"

    def submit(self, src: str) -> None:
        code = self.code()
        kind = self.classify(code, time.monotonic())
        self.log("submit", src=src, code=code, boxes=[e.text() for e in self.inputs])
        if not self.args.persist:
            self.result.setText("")
        if self.args.latency_ms > 0:
            QTimer.singleShot(self.args.latency_ms, lambda k=kind: self.show_result(k))
        else:
            self.show_result(kind)

    def _uses_dialog(self, kind: str) -> bool:
        if self.args.popup != "dialog" or self.args.popup_on == "never":
            return False
        return self.args.popup_on == "always" or kind == "success"

    def show_result(self, kind: str) -> None:
        text = self.t[kind]
        self.last_kind = kind
        popup = self._uses_dialog(kind)
        self.log("result", kind=kind, text=text, popup=popup)
        if not popup:
            self.result.setText(text)
            return
        if self.dialog is not None:
            self.dialog.close()
        dlg = ResultDialog(self, self.t["dialog_title"], text, self.t["ok"])
        geo = dlg.frameGeometry()
        geo.moveCenter(self.frameGeometry().center())
        dlg.move(geo.topLeft())
        dlg.finished.connect(lambda _r: self._dialog_closed(text))
        self.dialog = dlg
        dlg.show()
        QTimer.singleShot(150, self._log_popup)

    def _log_popup(self) -> None:
        if self.dialog is not None and self.dialog.isVisible():
            self.log("popup_open", text=self.dialog.label.text(), rect=physical_rect(self.dialog),
                     ok_rect=physical_rect(self.dialog.ok))

    def _dialog_closed(self, text: str) -> None:
        self.log("popup_closed", text=text)
        self.dialog = None

    def cancel(self) -> None:
        for e in self.inputs:
            e.clear()
        self.result.setText("")
        self.log("cancel")
        self.inputs[0].setFocus()

    # ---------------------------------------------------------------- info file
    def info(self) -> dict[str, Any]:
        return {"hwnd": int(self.winId()), "pid": os.getpid(), "title": self.windowTitle(),
                "dpr": self.devicePixelRatioF(), "client_rect": physical_rect(self),
                "inputs": [physical_rect(e) for e in self.inputs], "group_sizes": list(self.args.group_sizes),
                "redeem_button": physical_rect(self.redeem_btn), "cancel_button": physical_rect(self.cancel_btn),
                "result_rect": physical_rect(self.result), "prompt_rect": physical_rect(self.prompt),
                "lang": self.args.lang, "texts": self.t}

    def write_info(self) -> None:
        if not self.args.info:
            return
        path = Path(self.args.info)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(self.info(), ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)

    def moveEvent(self, ev: Any) -> None:  # noqa: N802 - Qt override
        super().moveEvent(ev)
        if self.isVisible():
            QTimer.singleShot(50, self.write_info)

    def resizeEvent(self, ev: Any) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(ev)
        if self.isVisible():
            QTimer.singleShot(50, self.write_info)

    def closeEvent(self, ev: Any) -> None:  # noqa: N802 - Qt override
        self.log("quit")
        super().closeEvent(ev)


def build_window(argv: list[str] | None = None) -> FakeRedeemWindow:
    """Create (not show) the window; a QApplication must exist. Used by main() and tests."""
    return FakeRedeemWindow(parse_args(argv))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    w = FakeRedeemWindow(args)
    w.show()
    w.log("start", pid=os.getpid(), hwnd=int(w.winId()), title=args.title)
    w.inputs[0].setFocus()
    QTimer.singleShot(300, w.write_info)
    return int(app.exec())


if __name__ == "__main__":
    sys.exit(main())
