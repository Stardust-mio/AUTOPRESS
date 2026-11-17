"""G2: ocr.service.OcrService with an injected fake engine - states, priority, cancel, timeout,
GUI-thread callbacks, failing factory, restart (same object), shutdown during a slow inference.
One slow test runs the real engine through the service."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

import numpy as np
import pytest

from autopress.models import OcrLine, OcrOptions, OcrResult, OcrSettings, clone
from autopress.ocr.engine import OcrUnavailable, unavailable
from autopress.ocr.service import OcrCancelled, OcrService, OcrState, OcrTimeout

MAIN = threading.get_ident()


def quad(x: float, y: float, w: float, h: float) -> list[tuple[float, float]]:
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


class FakeEngine:
    """Records every call; ``gate`` (an Event) blocks the first ``block`` recognize calls."""

    def __init__(self, gate: threading.Event | None = None, block: int = 1, delay: float = 0.0) -> None:
        self.gate = gate
        self.block = block
        self.delay = delay
        self.calls: list[dict] = []
        self.rereads: list[tuple[str, int]] = []
        self.warmed = False
        self.lines = [OcrLine(text="兌換碼：ab12-cd34", quad=quad(10, 10, 200, 24), score=0.99),
                      OcrLine(text="請輸入兌換碼", quad=quad(10, 50, 120, 20), score=0.97),
                      OcrLine(text="faint", quad=quad(10, 90, 50, 20), score=0.6)]

    def warmup(self) -> float:
        self.warmed = True
        return 0.0

    def recognize(self, image_bgr: np.ndarray, upscale: int = 1, det_side: int | None = None) -> list[OcrLine]:
        self.calls.append({"shape": image_bgr.shape, "upscale": upscale, "det_side": det_side,
                           "marker": int(image_bgr[0, 0, 0]), "thread": threading.get_ident()})
        if self.gate is not None and len(self.calls) <= self.block:
            self.gate.wait(20)
        if self.delay:
            time.sleep(self.delay)
        return [clone(ln) for ln in self.lines]

    def reread_line(self, image_bgr: np.ndarray, quad: object, allowed: str, upscale: int = 1) -> tuple[str, list[float]]:
        self.rereads.append((allowed, upscale))
        return "兌換碼：AB12-CD34", [0.99] * 13


def img(marker: int = 0, channels: int = 3) -> np.ndarray:
    a = np.zeros((30, 40, channels), np.uint8)
    a[0, 0, 0] = marker
    return a


def wait_for(cond: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached")
        time.sleep(0.005)


@pytest.fixture
def make_service(qapp: object):
    made: list[OcrService] = []

    def make(engine: object | None = None, settings: OcrSettings | None = None,
             factory: Callable[[], object] | None = None) -> OcrService:
        eng = engine if engine is not None else FakeEngine()
        svc = OcrService(settings or OcrSettings(), engine_factory=factory or (lambda: eng))
        made.append(svc)
        return svc

    yield make
    for svc in made:
        svc.shutdown(timeout_s=0.5)


def test_states_and_signal_on_gui_thread(make_service, qtbot) -> None:
    eng = FakeEngine()
    svc = make_service(eng)
    seen: list[tuple[str, int]] = []
    svc.state_changed.connect(lambda s: seen.append((s, threading.get_ident())))
    assert svc.state is OcrState.NOT_STARTED and svc.error == ""
    svc.start()
    assert svc.state in (OcrState.LOADING, OcrState.READY)
    qtbot.waitUntil(lambda: bool(seen) and seen[-1][0] == "ready", timeout=5000)
    assert [s for s, _ in seen] == ["loading", "ready"]
    assert all(t == MAIN for _, t in seen)  # delivered on the GUI thread
    assert eng.warmed  # warmup_on_start
    svc.start()  # idempotent
    qtbot.wait(50)
    assert [s for s, _ in seen] == ["loading", "ready"]
    assert svc.wait_ready(1.0)
    assert OcrState.READY.label() == "就緒"


def test_no_warmup_when_disabled_in_settings(make_service) -> None:
    eng = FakeEngine()
    svc = make_service(eng, OcrSettings(warmup_on_start=False))
    assert svc.wait_ready(5.0)
    assert not eng.warmed


def test_disabled_service(make_service, qtbot) -> None:
    svc = make_service(settings=OcrSettings(enabled=False))
    assert svc.state is OcrState.DISABLED
    svc.start()
    assert svc.state is OcrState.DISABLED and svc.error == ""
    fut = svc.submit(img())
    with pytest.raises(OcrUnavailable) as exc:
        fut.result(1)
    assert "設定" in str(exc.value)
    assert not svc.wait_ready(0.2)


def test_failing_factory_gives_failed(make_service, qtbot) -> None:
    def boom() -> object:
        raise RuntimeError("onnx exploded")

    svc = make_service(factory=boom)
    states: list[str] = []
    svc.state_changed.connect(states.append)
    svc.start()
    qtbot.waitUntil(lambda: svc.state is OcrState.FAILED, timeout=5000)
    assert "onnx exploded" in svc.error
    assert svc.error_message.startswith("文字辨識引擎無法啟動：") and "onnx exploded" in svc.error_message
    with pytest.raises(OcrUnavailable) as exc:
        svc.submit(img()).result(1)
    assert str(exc.value) == svc.error_message and exc.value.reason == svc.error
    errors: list[tuple[Exception, int]] = []
    svc.request(img(), None, lambda r: None, lambda e: errors.append((e, threading.get_ident())))
    qtbot.waitUntil(lambda: bool(errors), timeout=5000)
    assert isinstance(errors[0][0], OcrUnavailable) and errors[0][1] == MAIN
    assert not svc.wait_ready(0.5)
    svc.start()  # idempotent: FAILED stays until restart()
    assert svc.state is OcrState.FAILED
    qtbot.waitUntil(lambda: states[-1:] == ["failed"], timeout=2000)


def test_factory_unavailable_keeps_reason_and_fails_pending_jobs(make_service) -> None:
    release = threading.Event()

    def slow_missing() -> object:
        release.wait(5)
        raise unavailable("缺少模型檔 PP-OCRv6_det_small.onnx")

    svc = make_service(factory=slow_missing)
    fut = svc.submit(img())  # lazy start; queued while LOADING
    assert svc.state is OcrState.LOADING
    release.set()
    with pytest.raises(OcrUnavailable) as exc:
        fut.result(5)
    assert exc.value.reason == "缺少模型檔 PP-OCRv6_det_small.onnx"
    assert svc.error == "缺少模型檔 PP-OCRv6_det_small.onnx"


def test_priority_runner_jobs_first(make_service) -> None:
    gate = threading.Event()
    eng = FakeEngine(gate=gate, block=1)
    svc = make_service(eng)
    first = svc.submit(img(1), priority=1)
    wait_for(lambda: len(eng.calls) == 1)  # job 1 is running (blocked)
    later = [svc.submit(img(2), priority=1), svc.submit(img(3), priority=1), svc.submit(img(4), priority=0)]
    gate.set()
    for f in [first, *later]:
        f.result(5)
    assert [c["marker"] for c in eng.calls] == [1, 4, 2, 3]
    assert all(c["thread"] != MAIN for c in eng.calls)


def test_recognize_cancel_stops_waiting_and_skips_queued_job(make_service) -> None:
    gate = threading.Event()
    eng = FakeEngine(gate=gate, block=1)
    svc = make_service(eng)
    busy = svc.submit(img(1))
    wait_for(lambda: len(eng.calls) == 1)
    polls = {"n": 0}

    def cancel() -> bool:
        polls["n"] += 1
        return polls["n"] > 3

    t0 = time.monotonic()
    with pytest.raises(OcrCancelled):
        svc.recognize(img(2), cancel=cancel, timeout_s=10)
    assert time.monotonic() - t0 < 1.0 and polls["n"] == 4
    after = svc.submit(img(3))
    gate.set()
    busy.result(5)
    after.result(5)
    assert [c["marker"] for c in eng.calls] == [1, 3]  # the cancelled job never ran


def test_recognize_timeout(make_service) -> None:
    eng = FakeEngine(delay=1.5)
    svc = make_service(eng)
    assert svc.wait_ready(5)
    t0 = time.monotonic()
    with pytest.raises(OcrTimeout) as exc:
        svc.recognize(img(), timeout_s=0.2)
    assert time.monotonic() - t0 < 0.8
    assert str(exc.value).startswith("文字辨識逾時")
    assert isinstance(exc.value, TimeoutError)


def test_recognize_result_bgra_origin_and_options(make_service) -> None:
    eng = FakeEngine()
    svc = make_service(eng)
    res = svc.recognize(img(5, channels=4), OcrOptions(upscale=2, det_side=640), origin=(100, 200))
    assert isinstance(res, OcrResult)
    assert eng.calls[0]["shape"] == (30, 40, 3)  # BGRA converted to BGR before the engine
    assert (eng.calls[0]["upscale"], eng.calls[0]["det_side"]) == (2, 640)
    assert (res.width, res.height, res.origin) == (40, 30, (100, 200))
    assert [ln.text for ln in res.lines][:2] == ["兌換碼：ab12-cd34", "請輸入兌換碼"]
    assert all(ln.char_confs is None for ln in res.lines)  # no charset: no re-read
    assert res.elapsed_ms >= 0


def test_code_charset_rereads_latin_lines_only(make_service) -> None:
    eng = FakeEngine()
    svc = make_service(eng)
    res = svc.recognize(img(), OcrOptions(code_charset="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-", upscale=2,
                                          min_score=0.9))
    texts = [ln.text for ln in res.lines]
    assert texts == ["兌換碼：AB12-CD34", "請輸入兌換碼"]  # "faint" (0.6) dropped by min_score
    assert res.lines[0].char_confs == [0.99] * 13
    assert res.lines[1].char_confs is None  # no Latin run -> not re-read
    assert eng.rereads == [("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-", 2)]


def test_opts_none_uses_settings_det_side(make_service) -> None:
    eng = FakeEngine()
    svc = make_service(eng, OcrSettings(det_side=1280))
    svc.recognize(img())
    assert eng.calls[0]["det_side"] == 1280


def test_request_callbacks_on_gui_thread_not_synchronously(make_service, qtbot) -> None:
    svc = make_service()
    got: list[tuple[OcrResult, int]] = []
    job = svc.request(img(), OcrOptions(), lambda r: got.append((r, threading.get_ident())), origin=(7, 8))
    assert isinstance(job, int) and got == []  # never inside request()
    qtbot.waitUntil(lambda: bool(got), timeout=5000)
    assert got[0][1] == MAIN and got[0][0].origin == (7, 8)
    job2 = svc.request(img(), None, lambda r: got.append((r, 0)))
    assert job2 != job


def test_cancel_request_drops_callbacks(make_service, qtbot) -> None:
    gate = threading.Event()
    eng = FakeEngine(gate=gate, block=1)
    svc = make_service(eng)
    calls: list[object] = []
    job = svc.request(img(), None, calls.append, calls.append)
    wait_for(lambda: len(eng.calls) == 1)  # running: cancel only stops the delivery
    svc.cancel_request(job)
    gate.set()
    qtbot.wait(200)
    assert calls == []
    queued_gate = threading.Event()
    eng2 = FakeEngine(gate=queued_gate, block=1)
    svc2 = make_service(eng2)
    svc2.submit(img(1))
    wait_for(lambda: len(eng2.calls) == 1)
    job2 = svc2.request(img(2), None, calls.append, calls.append)  # still queued
    svc2.cancel_request(job2)
    queued_gate.set()
    qtbot.wait(200)
    assert calls == [] and [c["marker"] for c in eng2.calls] == [1]
    svc2.cancel_request(12345)  # unknown id: no error


def test_callback_exception_goes_to_excepthook(make_service, qtbot, monkeypatch) -> None:
    import sys

    hooked: list[type] = []
    monkeypatch.setattr(sys, "excepthook", lambda t, v, tb: hooked.append(t))
    svc = make_service()

    def bad(_r: OcrResult) -> None:
        raise ValueError("callback bug")

    svc.request(img(), None, bad)
    qtbot.waitUntil(lambda: bool(hooked), timeout=5000)
    assert hooked == [ValueError]


def test_callback_on_deleted_widget_is_ignored(make_service, qtbot, monkeypatch) -> None:
    import sys

    from PyQt6 import sip
    from PyQt6.QtWidgets import QLabel

    hooked: list[type] = []
    monkeypatch.setattr(sys, "excepthook", lambda t, v, tb: hooked.append(t))
    gate = threading.Event()
    eng = FakeEngine(gate=gate, block=1)
    svc = make_service(eng)
    label = QLabel()
    ran: list[int] = []

    def on_done(_r: OcrResult) -> None:
        ran.append(1)
        label.setText("done")  # RuntimeError: wrapped C/C++ object ... has been deleted

    svc.request(img(), None, on_done)
    wait_for(lambda: len(eng.calls) == 1)
    sip.delete(label)  # the dialog closed while OCR was running
    gate.set()
    qtbot.waitUntil(lambda: bool(ran), timeout=5000)
    qtbot.wait(50)
    assert hooked == []


def test_restart_same_object_disabled_then_new_settings(make_service, qtbot) -> None:
    engines: list[FakeEngine] = []

    def factory() -> FakeEngine:
        engines.append(FakeEngine())
        return engines[-1]

    svc = make_service(factory=factory)
    assert svc.wait_ready(5)
    qtbot.wait(50)  # deliver the queued loading / ready emissions of the first start
    states: list[str] = []
    svc.state_changed.connect(states.append)
    ident = id(svc)
    svc.restart(OcrSettings(enabled=False))
    assert svc.state is OcrState.DISABLED and id(svc) == ident
    with pytest.raises(OcrUnavailable):
        svc.submit(img()).result(1)
    svc.restart(OcrSettings(enabled=True, det_side=1280))
    assert svc.state in (OcrState.LOADING, OcrState.READY)  # non-blocking; the fake loads instantly
    assert svc.wait_ready(5) and len(engines) == 2
    assert svc.settings.det_side == 1280
    svc.recognize(img())
    assert engines[1].calls[0]["det_side"] == 1280
    svc.restart()  # None keeps the settings
    assert svc.wait_ready(5) and svc.settings.det_side == 1280 and len(engines) == 3
    qtbot.waitUntil(lambda: states[-1:] == ["ready"], timeout=3000)
    assert states == ["disabled", "loading", "ready", "loading", "ready"]


def test_restart_hands_pending_jobs_to_new_worker(make_service) -> None:
    gate = threading.Event()
    engines: list[FakeEngine] = []

    def factory() -> FakeEngine:
        engines.append(FakeEngine(gate=gate if not engines else None, block=1))
        return engines[-1]

    svc = make_service(factory=factory)
    running = svc.submit(img(1))
    wait_for(lambda: bool(engines) and len(engines[0].calls) == 1)
    pending = svc.submit(img(2))
    svc.restart()
    res = pending.result(5)  # served by the new engine
    assert isinstance(res, OcrResult) and [c["marker"] for c in engines[1].calls] == [2]
    gate.set()
    assert isinstance(running.result(5), OcrResult)  # the old worker finished its job normally


def test_shutdown_during_slow_inference(make_service) -> None:
    gate = threading.Event()
    eng = FakeEngine(gate=gate, block=1)
    svc = make_service(eng)
    running = svc.submit(img(1))
    wait_for(lambda: len(eng.calls) == 1)
    pending = svc.submit(img(2))
    worker_threads = [t for t in threading.enumerate() if t.name == "AutoPress-OCR"]
    assert worker_threads and all(t.daemon for t in worker_threads)
    t0 = time.monotonic()
    svc.shutdown(timeout_s=0.3)
    assert time.monotonic() - t0 < 1.0  # abandoned, no hang
    for fut in (running, pending):
        with pytest.raises(OcrCancelled):
            fut.result(1)
    assert svc.state is OcrState.NOT_STARTED
    svc.shutdown()  # twice is fine
    with pytest.raises(OcrCancelled):
        svc.submit(img(3)).result(1)
    gate.set()  # the abandoned inference finishes; its result is dropped without errors
    for t in worker_threads:
        t.join(5)
    assert [c["marker"] for c in eng.calls] == [1]
    svc.start()  # explicit start after shutdown works again
    assert svc.wait_ready(5)


def test_wait_ready_cancel_and_timeout(make_service) -> None:
    release = threading.Event()

    def slow() -> FakeEngine:
        release.wait(5)
        return FakeEngine()

    svc = make_service(factory=slow)
    t0 = time.monotonic()
    assert not svc.wait_ready(10, cancel=lambda: time.monotonic() - t0 > 0.2)
    assert time.monotonic() - t0 < 1.0
    assert not svc.wait_ready(0.1)
    release.set()
    assert svc.wait_ready(5)


def test_submit_rejects_non_images(make_service) -> None:
    svc = make_service()
    with pytest.raises(TypeError):
        svc.submit("C:/picture.png")  # type: ignore[arg-type]
    res = svc.recognize(np.zeros((0, 10, 3), np.uint8))
    assert res.lines == [] and (res.width, res.height) == (10, 0)


@pytest.mark.slow
def test_real_engine_through_service(qapp, qtbot, text_image) -> None:
    svc = OcrService(OcrSettings(threads=4))
    try:
        svc.start()
        assert svc.wait_ready(60), svc.error
        res = svc.recognize(text_image("兌換碼：AB12-CD34"), OcrOptions(code_charset="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"))
        code_lines = [ln for ln in res.lines if "AB12-CD34" in ln.text]
        assert code_lines and code_lines[0].char_confs and len(code_lines[0].char_confs) == len(code_lines[0].text)
        got: list[OcrResult] = []
        svc.request(text_image("序號已被使用", size=18, dark=False), None, got.append)
        qtbot.waitUntil(lambda: bool(got), timeout=20000)
        assert "序號已被使用" in got[0].text()
    finally:
        svc.shutdown()
