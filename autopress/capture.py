# OWNED BY G2 - replace this stub
"""Screen capture with mss 10.2 (win32_windows.md section 4). Physical pixels everywhere.

* Create a Grabber only AFTER QApplication exists (mss.MSS() before it locks the process into
  per-monitor-v1 DPI awareness). Use ``mss.MSS()``, never the deprecated ``mss.mss()``.
* One Grabber per thread (the mss instance is created lazily in the first grab() call, in the
  calling thread). Construction costs 0.1-0.2 ms; a 400x150 grab about 8 ms.
* Results are COPIES (np.asarray(shot) is a view into mss memory that is reused).
* Exclusive-fullscreen games and a locked screen capture as black/uniform: the runner calls
  looks_blank() on EVERY capture and pauses (PauseReason.CAPTURE_BLANK) instead of failing.
* mss copies screen pixels, so AutoPress's own topmost windows (the mini bar) appear in
  captures: the runner masks them (ocr.imageio.mask_rects with RunSession.set_masked_rects);
  win32.windows.exclude_from_capture is applied too, but its effect on mss is UNVERIFIED.
"""

from __future__ import annotations

import numpy as np

from .models import ClientRegion, CoordMode, Monitor, Rect

__stub__ = True


class CaptureError(RuntimeError):
    """Capture failed (rect outside every monitor, window gone, GDI error). Localized message."""


class Grabber:
    def __init__(self) -> None:
        raise NotImplementedError

    def grab(self, rect: Rect) -> np.ndarray:
        """(h, w, 4) uint8 BGRA copy of the physical screen rect (x, y, w, h)."""
        raise NotImplementedError

    def grab_monitor(self, monitor: Monitor) -> np.ndarray:
        raise NotImplementedError

    def grab_all(self) -> list[tuple[Monitor, np.ndarray]]:
        """Every monitor (win32.dpi.monitors() order) with its BGRA image (for picker overlays)."""
        raise NotImplementedError

    def grab_client(self, hwnd: int, region: ClientRegion | None = None,
                    mode: CoordMode = CoordMode.AUTO) -> tuple[np.ndarray, Rect]:
        """The target's client area, or ``region`` resolved against it (models.resolve_region),
        clipped to the client area. Returns (BGRA image, physical rect captured)."""
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def __enter__(self) -> Grabber:
        raise NotImplementedError

    def __exit__(self, *exc: object) -> None:
        raise NotImplementedError


def grab_rect(rect: Rect) -> np.ndarray:
    """One-shot capture with a temporary Grabber (any thread)."""
    raise NotImplementedError


def looks_blank(image: np.ndarray, std_threshold: float = 2.0) -> bool:
    """True for an (almost) uniform image - typical for exclusive-fullscreen capture."""
    raise NotImplementedError
