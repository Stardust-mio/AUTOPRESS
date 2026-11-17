"""Offscreen self-check of tools/fake_redeem_app.py (G4): the window is built in-process on the
offscreen platform (never shown on the desktop); widgets are driven directly."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest

from autopress.models import KeywordConfig, ResultClass
from tools import fake_redeem_app as app


def build(qtbot: Any, tmp_path: Path, *args: str) -> app.FakeRedeemWindow:
    log, info = tmp_path / "events.jsonl", tmp_path / "info.json"
    w = app.build_window(["--title", "AutoPress Fake test", "--log", str(log), "--info", str(info), *args])
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    return w


def events(tmp_path: Path) -> list[dict[str, Any]]:
    path = tmp_path / "events.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def submit(w: app.FakeRedeemWindow, *parts: str) -> None:
    for edit, text in zip(w.inputs, parts, strict=False):
        edit.setText(text)
    w.redeem_btn.click()


def test_parse_args_boxes_and_groups() -> None:
    assert app.parse_args([]).group_sizes == []
    assert app.parse_args(["--boxes", "3"]).group_sizes == [5, 5, 5]
    assert app.parse_args(["--groups", "4,6,2"]).group_sizes == [4, 6, 2]
    with pytest.raises(SystemExit):
        app.parse_args(["--groups", "4,0"])


def test_results_and_event_log(qtbot: Any, tmp_path: Path) -> None:
    w = build(qtbot, tmp_path, "--valid", "AAAA-1111,BBBB-2222", "--used", "CCCC-3333")
    assert w.prompt.text() == "請輸入兌換碼" and w.redeem_btn.text() == "兌換" and w.cancel_btn.text() == "取消"
    expected = [("AAAA-1111", "兌換成功"), ("AAAA1111", "此序號已被使用"), ("CCCC-3333", "此序號已被使用"),
                ("EXP-0001", "兌換碼已過期"), ("XXXX-0000", "兌換碼無效"), ("aaaa-1111", "兌換碼無效")]
    for code, text in expected:
        submit(w, code)
        assert w.result.text() == text
    evs = events(tmp_path)
    assert [e["code"] for e in evs if e["ev"] == "submit"] == [c for c, _t in expected]
    assert [e["kind"] for e in evs if e["ev"] == "result"] == ["success", "used", "used", "expired", "invalid",
                                                                "invalid"]
    kw = KeywordConfig()
    assert [kw.classify(t)[0] for _c, t in expected[:5]] == [ResultClass.SUCCESS, ResultClass.USED, ResultClass.USED,
                                                              ResultClass.EXPIRED, ResultClass.INVALID]


def test_english_texts_classify(qtbot: Any, tmp_path: Path) -> None:
    w = build(qtbot, tmp_path, "--lang", "en", "--valid", "AAAA-1111", "--rate-limit", "4")
    assert w.prompt.text() == "Enter your redeem code" and w.redeem_btn.text() == "Redeem"
    kw = KeywordConfig()
    got = []
    for code in ("AAAA-1111", "AAAA-1111", "EXP-1", "ZZZ", "ZZZ"):
        submit(w, code)
        got.append(kw.classify(w.result.text())[0])
    assert got == [ResultClass.SUCCESS, ResultClass.USED, ResultClass.EXPIRED, ResultClass.INVALID,
                   ResultClass.RATE_LIMITED]


def test_rate_limit_window(qtbot: Any, tmp_path: Path) -> None:
    w = build(qtbot, tmp_path, "--rate-limit", "2")
    submit(w, "X1")
    submit(w, "X2")
    assert w.result.text() == "兌換碼無效"
    submit(w, "X3")
    assert w.result.text() == "操作過於頻繁，請稍後再試"
    w.submits = []  # the 10 s window passed
    submit(w, "X4")
    assert w.result.text() == "兌換碼無效"


def test_latency_without_and_with_persist(qtbot: Any, tmp_path: Path) -> None:
    w = build(qtbot, tmp_path, "--latency-ms", "150", "--valid", "AAAA-1111")
    submit(w, "XXXX")
    assert w.result.text() == ""
    qtbot.waitUntil(lambda: w.result.text() == "兌換碼無效", timeout=2000)
    submit(w, "AAAA-1111")
    assert w.result.text() == ""  # cleared at submit
    qtbot.waitUntil(lambda: w.result.text() == "兌換成功", timeout=2000)
    w2 = build(qtbot, tmp_path / "p", "--latency-ms", "150", "--persist", "--valid", "AAAA-1111") \
        if (tmp_path / "p").mkdir() is None else None
    assert w2 is not None
    submit(w2, "XXXX")
    qtbot.waitUntil(lambda: w2.result.text() == "兌換碼無效", timeout=2000)
    submit(w2, "AAAA-1111")
    assert w2.result.text() == "兌換碼無效"  # the previous result stays (stale-read case)
    qtbot.waitUntil(lambda: w2.result.text() == "兌換成功", timeout=2000)


def test_popup_on_success_dialog(qtbot: Any, tmp_path: Path) -> None:
    w = build(qtbot, tmp_path, "--popup", "dialog", "--popup-on", "success", "--valid", "AAAA-1111")
    submit(w, "XXXX")
    assert w.dialog is None and w.result.text() == "兌換碼無效"
    submit(w, "AAAA-1111")
    dlg = w.dialog
    assert dlg is not None and dlg.isVisible() and dlg.isModal()
    assert dlg.label.text() == "兌換成功" and dlg.ok.text() == "確定"
    assert w.result.text() == ""  # cleared at the submit (no --persist); the result is in the dialog
    qtbot.waitUntil(lambda: any(e["ev"] == "popup_open" for e in events(tmp_path)), timeout=2000)
    opened = next(e for e in events(tmp_path) if e["ev"] == "popup_open")
    assert len(opened["rect"]) == 4 and len(opened["ok_rect"]) == 4
    dlg.ok.click()
    qtbot.waitUntil(lambda: w.dialog is None, timeout=2000)
    assert [e for e in events(tmp_path) if e["ev"] == "popup_closed"][0]["text"] == "兌換成功"


@pytest.mark.parametrize(("popup_on", "dialog_for_invalid"), [("always", True), ("never", False)])
def test_popup_always_and_never(qtbot: Any, tmp_path: Path, popup_on: str, dialog_for_invalid: bool) -> None:
    w = build(qtbot, tmp_path, "--popup", "dialog", "--popup-on", popup_on)
    submit(w, "XXXX")
    assert (w.dialog is not None) is dialog_for_invalid
    if w.dialog is not None:
        w.dialog.close()


def test_three_boxes_auto_advance_and_joined_code(qtbot: Any, tmp_path: Path) -> None:
    w = build(qtbot, tmp_path, "--boxes", "3", "--valid", "ABCDE-FGHIJ-KLMNO")
    assert len(w.inputs) == 3 and [e.maxLength() for e in w.inputs] == [5, 5, 5]
    w.activateWindow()
    w.inputs[0].setFocus()
    qtbot.waitUntil(lambda: w.inputs[0].hasFocus(), timeout=2000)
    w.inputs[1].setText("OLD12")
    QTest.keyClicks(w.inputs[0], "ABCDE")
    assert w.inputs[1].hasFocus() and w.inputs[1].selectedText() == "OLD12"  # typing replaces the old segment
    QTest.keyClicks(w.inputs[1], "FGHIJ")
    QTest.keyClicks(w.inputs[2], "KLMNO")
    assert w.code() == "ABCDE-FGHIJ-KLMNO"
    QTest.keyClick(w.inputs[2], Qt.Key.Key_Return)
    assert w.result.text() == "兌換成功"
    sub = [e for e in events(tmp_path) if e["ev"] == "submit"][0]
    assert sub["boxes"] == ["ABCDE", "FGHIJ", "KLMNO"] and sub["src"] == "enter"


def test_unequal_groups(qtbot: Any, tmp_path: Path) -> None:
    w = build(qtbot, tmp_path, "--groups", "4,6,2", "--valid", "ABCD-EFGHIJ-KL")
    assert [e.maxLength() for e in w.inputs] == [4, 6, 2]
    submit(w, "ABCD", "EFGHIJ", "KL")
    assert w.result.text() == "兌換成功"


def test_cancel_clears(qtbot: Any, tmp_path: Path) -> None:
    w = build(qtbot, tmp_path)
    submit(w, "XXXX")
    w.cancel_btn.click()
    assert w.inputs[0].text() == "" and w.result.text() == ""
    assert events(tmp_path)[-1]["ev"] == "cancel"


def test_info_file_has_physical_rects(qtbot: Any, tmp_path: Path) -> None:
    w = build(qtbot, tmp_path, "--boxes", "3")
    w.write_info()
    info = json.loads((tmp_path / "info.json").read_text(encoding="utf-8"))
    assert info["title"] == "AutoPress Fake test" and info["pid"] > 0 and info["hwnd"]
    assert len(info["inputs"]) == 3 and info["group_sizes"] == [5, 5, 5]
    cx, cy, cw, ch = info["client_rect"]
    for key in ("redeem_button", "cancel_button", "result_rect", "prompt_rect"):
        x, y, rw, rh = info[key]
        assert rw > 0 and rh > 0 and cx <= x and cy <= y and x + rw <= cx + cw + 1 and y + rh <= cy + ch + 1, key
    assert info["texts"]["success"] == "兌換成功"


def test_no_advance_keeps_focus(qtbot: Any, tmp_path: Path) -> None:
    w = build(qtbot, tmp_path, "--boxes", "3", "--no-advance")
    w.activateWindow()
    w.inputs[0].setFocus()
    qtbot.waitUntil(lambda: w.inputs[0].hasFocus(), timeout=2000)
    QTest.keyClicks(w.inputs[0], "ABCDEF")  # maxLength 5: the 6th character is dropped
    assert w.inputs[0].hasFocus() and w.inputs[0].text() == "ABCDE"


def test_cli_entry_point_offscreen(tmp_path: Path, python_exe: str) -> None:
    """main() as a separate process on the OFFSCREEN platform (nothing appears on the desktop):
    it starts, logs "start" and writes the info file."""
    import os
    import subprocess
    import time

    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8")
    info, log = tmp_path / "info.json", tmp_path / "events.jsonl"
    script = Path(app.__file__)
    proc = subprocess.Popen([python_exe, str(script), "--title", "AutoPress Fake CLI", "--info", str(info),
                             "--log", str(log), "--boxes", "3"], env=env)
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not info.exists():
            time.sleep(0.1)
        assert info.exists(), "the fake app did not write its info file"
        data = json.loads(info.read_text(encoding="utf-8"))
        assert data["title"] == "AutoPress Fake CLI" and len(data["inputs"]) == 3
        assert json.loads(log.read_text(encoding="utf-8").splitlines()[0])["ev"] == "start"
    finally:
        proc.terminate()
        proc.wait(10)
