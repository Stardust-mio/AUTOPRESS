"""G2: capture.Grabber against a fake mss (no real screen is captured) and looks_blank.
The pixel-exact check on a real window is tests/test_capture_pattern.py (realinput)."""

from __future__ import annotations

import threading

import numpy as np
import pytest

from autopress import capture
from autopress.capture import CaptureError, Grabber, grab_rect, looks_blank
from autopress.models import ClientRegion, CoordMode, Monitor, record_region

# this PC's layout: primary at (0, 0), a second monitor LEFT of it
MONITORS = [
    {"left": -1920, "top": 0, "width": 3840, "height": 1080},
    {"left": 0, "top": 0, "width": 1920, "height": 1080, "is_primary": True, "name": "Generic PnP Monitor"},
    {"left": -1920, "top": 0, "width": 1920, "height": 1080, "is_primary": False, "name": "Generic PnP Monitor"},
]


def screen_pixel(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """The fake desktop: BGRA value as a function of the GLOBAL physical position."""
    return np.dstack([(x * 3 + y) % 256, (y * 5) % 256, (x + 2 * y + 7) % 256, np.zeros_like(x)]).astype(np.uint8)


class FakeShot:
    def __init__(self, left: int, top: int, width: int, height: int) -> None:
        y, x = np.mgrid[top:top + height, left:left + width]
        self.raw = bytearray(screen_pixel(x, y).tobytes())
        self.width, self.height = width, height

    @property
    def __array_interface__(self) -> dict:
        return {"version": 3, "shape": (self.height, self.width, 4), "typestr": "|u1", "data": self.raw}


class FakeMSS:
    instances: list[FakeMSS] = []
    fail_grab = False

    def __init__(self) -> None:
        self.thread = threading.get_ident()
        self.closed = False
        self.grabs: list[dict] = []
        self.last: FakeShot | None = None
        FakeMSS.instances.append(self)

    @property
    def monitors(self) -> list[dict]:
        return MONITORS

    def grab(self, mon: dict) -> FakeShot:
        if FakeMSS.fail_grab:
            from mss.exception import ScreenShotError

            raise ScreenShotError("BitBlt failed")
        self.grabs.append(dict(mon))
        self.last = FakeShot(mon["left"], mon["top"], mon["width"], mon["height"])
        return self.last

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def fake_mss(monkeypatch: pytest.MonkeyPatch) -> type[FakeMSS]:
    import mss

    FakeMSS.instances = []
    FakeMSS.fail_grab = False
    monkeypatch.setattr(mss, "MSS", FakeMSS)
    return FakeMSS


def expected(x: int, y: int, w: int, h: int) -> np.ndarray:
    yy, xx = np.mgrid[y:y + h, x:x + w]
    out = screen_pixel(xx, yy)
    out[:, :, 3] = 255
    return out


def test_grab_returns_bgra_copy_with_opaque_alpha() -> None:
    g = Grabber()
    assert FakeMSS.instances == []  # lazy: nothing created before the first grab
    img = g.grab((-100, 20, 300, 40))  # spans both monitors, negative coordinates
    assert img.shape == (40, 300, 4) and img.dtype == np.uint8 and img.flags.writeable
    assert np.array_equal(img, expected(-100, 20, 300, 40))
    sct = FakeMSS.instances[0]
    assert sct.grabs == [{"left": -100, "top": 20, "width": 300, "height": 40}]
    sct.last.raw[:] = b"\x00" * len(sct.last.raw)  # mss memory reused / changed later
    assert np.array_equal(img, expected(-100, 20, 300, 40))  # our copy is unaffected
    g.close()


def test_grab_errors_are_capture_errors() -> None:
    with Grabber() as g:
        with pytest.raises(CaptureError) as e1:
            g.grab((0, 0, 0, 10))
        assert str(e1.value).startswith("無法擷取畫面：") and "螢幕外" in str(e1.value)
        with pytest.raises(CaptureError) as e2:
            g.grab((5000, 5000, 10, 10))  # outside every monitor
        assert e2.value.reason and e2.value.reason in str(e2.value)
        with pytest.raises(CaptureError):
            g.grab((-1920, 1080, 50, 50))  # below both monitors (touching is not overlapping)
        FakeMSS.fail_grab = True
        with pytest.raises(CaptureError) as e3:
            g.grab((0, 0, 10, 10))
        assert "BitBlt failed" in str(e3.value)


def test_one_mss_per_thread_and_close() -> None:
    g = Grabber()
    g.grab((0, 0, 4, 4))
    g.grab((10, 10, 4, 4))
    out: dict[str, object] = {}

    def other() -> None:
        out["img"] = g.grab((0, 0, 4, 4))

    t = threading.Thread(target=other)
    t.start()
    t.join(5)
    assert len(FakeMSS.instances) == 2
    assert FakeMSS.instances[0].thread == threading.get_ident()
    assert FakeMSS.instances[1].thread == t.ident
    g.close()
    assert all(s.closed for s in FakeMSS.instances)
    g.close()  # twice is fine
    g.grab((0, 0, 4, 4))  # usable again: a new instance
    assert len(FakeMSS.instances) == 3
    g.close()


def test_context_manager_and_grab_rect() -> None:
    with Grabber() as g:
        g.grab((0, 0, 2, 2))
    assert FakeMSS.instances[-1].closed
    img = grab_rect((1, 2, 3, 4))
    assert np.array_equal(img, expected(1, 2, 3, 4)) and FakeMSS.instances[-1].closed


def test_grab_monitor_and_grab_all_with_dpi_monitors(monkeypatch: pytest.MonkeyPatch) -> None:
    from autopress.win32 import dpi

    mons = [Monitor(device=r"\\.\DISPLAY1", rect=(0, 0, 1920, 1080), work=(0, 0, 1920, 1040), dpi=96, primary=True),
            Monitor(device=r"\\.\DISPLAY2", rect=(-1920, 0, 1920, 1080), work=(-1920, 0, 1920, 1040), dpi=120)]
    monkeypatch.setattr(dpi, "monitors", lambda: mons)
    with Grabber() as g:
        shots = g.grab_all()
        assert [m for m, _ in shots] == mons
        assert np.array_equal(shots[1][1][:3, :3], expected(-1920, 0, 3, 3))
        assert g.grab_monitor(mons[1]).shape == (1080, 1920, 4)


def test_grab_all_falls_back_to_mss_monitors(monkeypatch: pytest.MonkeyPatch) -> None:
    from autopress.win32 import dpi

    def stub() -> list[Monitor]:
        raise NotImplementedError

    monkeypatch.setattr(dpi, "monitors", stub)
    with Grabber() as g:
        shots = g.grab_all()
        assert [m.rect for m, _ in shots] == [(0, 0, 1920, 1080), (-1920, 0, 1920, 1080)]  # primary first
        assert shots[0][0].primary and not shots[1][0].primary
        assert g.monitor_rects() == [(0, 0, 1920, 1080), (-1920, 0, 1920, 1080)]


@pytest.fixture
def fake_window(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    from autopress.win32 import windows

    state: dict[str, object] = {"client": (100, 50, 800, 600), "dpi": 96, "gone": False}

    def client_rect(hwnd: int) -> tuple[int, int, int, int]:
        if state["gone"]:
            raise OSError(1400, "Invalid window handle")
        return state["client"]  # type: ignore[return-value]

    monkeypatch.setattr(windows, "client_rect", client_rect)
    monkeypatch.setattr(windows, "window_dpi", lambda hwnd: state["dpi"])
    return state


def test_grab_client_whole_and_region(fake_window: dict[str, object]) -> None:
    with Grabber() as g:
        img, rect = g.grab_client(1234)
        assert rect == (100, 50, 800, 600) and np.array_equal(img, expected(100, 50, 800, 600))
        region = record_region((100, 50, 800, 600), 400, 300, 200, 100)
        img, rect = g.grab_client(1234, region)
        assert rect == (400, 300, 200, 100) and np.array_equal(img, expected(400, 300, 200, 100))
        # partly outside the client area -> clipped
        edge = record_region((100, 50, 800, 600), 800, 600, 300, 100)
        _, rect = g.grab_client(1234, edge)
        assert rect == (800, 600, 100, 50)
        outside = ClientRegion(dx=900, dy=0, w=50, h=50, rx=1.2, ry=0.0, rw=0.06, rh=0.08, ref_w=800, ref_h=600)
        with pytest.raises(CaptureError):
            g.grab_client(1234, outside)


def test_grab_client_dpi_and_ratio(fake_window: dict[str, object]) -> None:
    region = record_region((100, 50, 800, 600), 200, 100, 100, 50, dpi=96)
    with Grabber() as g:
        fake_window["dpi"] = 144  # 150 %: offset mode scales by 144 / 96
        _, rect = g.grab_client(1, region, CoordMode.OFFSET)
        assert rect == (100 + 150, 50 + 75, 150, 75)
        fake_window["dpi"] = 96
        fake_window["client"] = (0, 0, 1600, 1200)  # resized 2x: auto -> ratio
        _, rect = g.grab_client(1, region, CoordMode.AUTO)
        assert rect == (200, 100, 200, 100)


def test_grab_client_window_gone_raises_oserror(fake_window: dict[str, object]) -> None:
    fake_window["gone"] = True
    with Grabber() as g:
        with pytest.raises(OSError):
            g.grab_client(99)
    fake_window["gone"] = False
    fake_window["client"] = (0, 0, 0, 0)  # minimized
    with Grabber() as g:
        with pytest.raises(CaptureError):
            g.grab_client(99)


# ----------------------------------------------------------------------------- looks_blank


def test_looks_blank() -> None:
    black = np.zeros((1080, 1920, 4), np.uint8)
    assert looks_blank(black)
    uniform = np.full((300, 700, 3), (40, 30, 20), np.uint8)
    assert looks_blank(uniform)
    rng = np.random.default_rng(1)
    noisy = np.clip(uniform.astype(int) + rng.integers(-1, 2, uniform.shape), 0, 255).astype(np.uint8)
    assert looks_blank(noisy)  # +-1 noise: std < 2
    text_like = uniform.copy()
    text_like[140:152, 100:400] = 240  # one thin text line on a uniform panel
    assert not looks_blank(text_like)
    alpha_noise = black.copy()
    alpha_noise[:, :, 3] = rng.integers(0, 256, alpha_noise.shape[:2])  # alpha is ignored
    assert looks_blank(alpha_noise)
    assert looks_blank(np.zeros((0, 10, 3), np.uint8))
    gray = np.zeros((50, 50), np.uint8)
    assert looks_blank(gray)
    gray[10:20, 10:20] = 255
    assert not looks_blank(gray)
    assert looks_blank(text_like, std_threshold=1000.0)


def test_looks_blank_without_opencv(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "cv2", None)  # import cv2 -> ImportError
    uniform = np.full((300, 700, 3), 33, np.uint8)
    assert looks_blank(uniform)
    uniform[100:120, 100:300] = 250
    assert not looks_blank(uniform)


def test_capture_error_is_runtime_error() -> None:
    err = capture.capture_failed("x")
    assert isinstance(err, RuntimeError) and err.reason == "x"
