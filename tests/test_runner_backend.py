"""RealBackend parts that need no real input (G4): OCR delegation, evidence paths, the counting
guard. Win32 calls themselves are G3's and are exercised by the realinput e2e tests."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from autopress.models import OcrLine, OcrOptions, OcrResult, Settings, WindowInfo
from autopress.ocr.engine import OcrUnavailable
from autopress.runner.backend import RealBackend
from tests.fakes import FakeOcrService, skip_if_stub


def test_real_backend_without_ocr_service() -> None:
    b = RealBackend(None)
    with pytest.raises(OcrUnavailable):
        b.ocr(np.zeros((4, 4, 4), np.uint8), OcrOptions(), lambda: False)
    assert b.ocr_status() == ("disabled", "")
    assert b.ocr_ready(0.01, lambda: False) is False
    assert b.own_pid() == os.getpid()
    b.close()
    b.close()


def test_real_backend_delegates_ocr_with_runner_priority(qapp: object) -> None:
    result = OcrResult(lines=[OcrLine(text="兌換成功", quad=[(0, 0), (10, 0), (10, 5), (0, 5)], score=0.9)])
    svc = FakeOcrService(result=result)
    b = RealBackend(svc)
    img = np.zeros((5, 10, 4), np.uint8)
    opts = OcrOptions(upscale=2, det_side=960)
    assert b.ocr(img, opts, lambda: False) is result
    assert svc.requests[-1] == (img, opts)
    assert b.ocr_status() == ("ready", "")
    assert b.ocr_ready(0.01, lambda: False) is True


def test_save_evidence_path_in_data_folder(isolated_home: Path) -> None:
    skip_if_stub("autopress.ocr.imageio")
    rel = RealBackend(None).save_evidence(np.full((8, 8, 4), 120, np.uint8), "run42", 3)
    assert rel == f"evidence/{date.today().isoformat()}/run42_3.png"
    assert (isolated_home / rel).is_file()


def test_counting_guard_counts_passed_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    skip_if_stub("autopress.win32.input")
    import autopress.win32.input as winput

    calls = []
    monkeypatch.setattr(winput.InjectGuard, "check", lambda self, what, point=None: calls.append(what))
    guard = RealBackend(None).make_guard(WindowInfo(hwnd=0x1234, pid=99), Settings(), False, lambda: None)
    guard.check("type")
    guard.check("click", (1, 2))
    assert guard.passed == 2 and calls == ["type", "click"]

    def refuse(self: object, what: str, point: object = None) -> None:
        raise winput.ForegroundLost("x")

    monkeypatch.setattr(winput.InjectGuard, "check", refuse)
    with pytest.raises(winput.ForegroundLost):
        guard.check("type")
    assert guard.passed == 2
