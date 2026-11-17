"""RunControl (thread-safe pause / resume / stop, interruptible sleep) and classify_text (G4)."""

from __future__ import annotations

import threading
import time

import pytest

from autopress.models import KeywordConfig, ResultClass, StopReason
from autopress.runner.classify import classify_text
from autopress.runner.control import RunControl, StopRequested


def test_sleep_runs_tick_every_slice_and_returns() -> None:
    ticks = []
    rc = RunControl(tick=lambda: ticks.append(time.monotonic()), slice_s=0.02)
    t0 = time.monotonic()
    rc.sleep(0.2)
    elapsed = time.monotonic() - t0
    assert 0.19 <= elapsed < 0.6
    assert len(ticks) >= 6  # ~10 slices of 20 ms
    gaps = [b - a for a, b in zip(ticks, ticks[1:], strict=False)]
    assert max(gaps) < 0.1  # never more than one slice (+ scheduling) between checks


def test_slice_is_capped_at_50ms() -> None:
    ticks = []
    rc = RunControl(tick=lambda: ticks.append(time.monotonic()), slice_s=5.0)
    rc.sleep(0.3)
    assert len(ticks) >= 5


def test_stop_interrupts_sleep_within_100ms() -> None:
    rc = RunControl()
    out: dict[str, float] = {}

    def worker() -> None:
        try:
            rc.sleep(10)
        except StopRequested as exc:
            out["t"] = time.monotonic()
            out["reason"] = exc.reason  # type: ignore[assignment]

    th = threading.Thread(target=worker)
    th.start()
    time.sleep(0.15)
    t_stop = time.monotonic()
    rc.request_stop(StopReason.FAILURES)
    th.join(2)
    assert not th.is_alive()
    assert out["t"] - t_stop < 0.1
    assert out["reason"] is StopReason.FAILURES


def test_first_stop_reason_wins_and_checkpoint_raises() -> None:
    rc = RunControl()
    rc.checkpoint()
    assert not rc.stop_requested and rc.stop_reason is None
    rc.request_stop(StopReason.FAILSAFE)
    rc.request_stop(StopReason.USER)
    assert rc.stop_requested and rc.stop_reason is StopReason.FAILSAFE
    with pytest.raises(StopRequested) as ei:
        rc.checkpoint()
    assert ei.value.reason is StopReason.FAILSAFE
    with pytest.raises(StopRequested):
        rc.sleep(0)


def test_tick_exception_propagates_from_sleep() -> None:
    class Boom(RuntimeError):
        pass

    calls = []

    def tick() -> None:
        calls.append(1)
        if len(calls) == 3:
            raise Boom

    rc = RunControl(tick=tick, slice_s=0.01)
    with pytest.raises(Boom):
        rc.sleep(5)
    assert len(calls) == 3


def test_wait_while_paused_blocks_until_resume_without_ticks() -> None:
    ticks = []
    rc = RunControl(tick=lambda: ticks.append(1))
    rc.request_pause()
    assert rc.pause_requested
    released = threading.Event()

    def worker() -> None:
        rc.wait_while_paused()
        released.set()

    th = threading.Thread(target=worker)
    th.start()
    time.sleep(0.3)
    assert not released.is_set()
    t0 = time.monotonic()
    rc.request_resume()
    assert released.wait(1)
    assert time.monotonic() - t0 < 0.1
    th.join(1)
    assert not ticks  # a paused run never trips the input guard
    assert not rc.pause_requested


def test_stop_releases_wait_while_paused() -> None:
    rc = RunControl()
    rc.request_pause()
    out = []

    def worker() -> None:
        try:
            rc.wait_while_paused()
        except StopRequested as exc:
            out.append(exc.reason)

    th = threading.Thread(target=worker)
    th.start()
    time.sleep(0.1)
    rc.request_stop()
    th.join(1)
    assert out == [StopReason.USER]


def test_not_paused_returns_at_once_and_set_tick() -> None:
    rc = RunControl()
    t0 = time.monotonic()
    rc.wait_while_paused()
    assert time.monotonic() - t0 < 0.05
    seen = []
    rc.set_tick(lambda: seen.append(1))
    rc.sleep(0.01)
    assert seen
    rc.set_tick(None)
    rc.sleep(0.01)


def test_classify_delegates_to_keyword_config(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def spy(self: KeywordConfig, text: str) -> tuple[ResultClass, str]:
        calls.append(text)
        return ResultClass.EXPIRED, "spy"

    monkeypatch.setattr(KeywordConfig, "classify", spy)
    assert classify_text("anything", KeywordConfig()) == (ResultClass.EXPIRED, "spy")
    assert calls == ["anything"]


@pytest.mark.parametrize(("text", "expected"), [
    ("兌換成功", ResultClass.SUCCESS),
    ("此序號已被使用", ResultClass.USED),
    ("兌換碼已過期", ResultClass.EXPIRED),
    ("操作過於頻繁，請稍後再試", ResultClass.RATE_LIMITED),
    ("兌換碼無效", ResultClass.INVALID),
    ("未能成功兌換", ResultClass.UNKNOWN),  # SUCCESS + negation -> ambiguous
    ("", ResultClass.UNKNOWN),
    ("Code redeemed successfully", ResultClass.SUCCESS),
    ("This code has already been used", ResultClass.USED),
])
def test_classify_fake_app_messages(text: str, expected: ResultClass) -> None:
    cls, kw = classify_text(text, KeywordConfig())
    assert cls is expected
    assert (kw == "") == (expected is ResultClass.UNKNOWN)
