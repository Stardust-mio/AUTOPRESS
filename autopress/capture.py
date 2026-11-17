# OWNED BY G2
"""Screen capture with mss 10.2 (win32_windows.md section 4). Physical pixels everywhere.

* Create a Grabber only AFTER QApplication exists (mss.MSS() before it locks the process into
  per-monitor-v1 DPI awareness). Use ``mss.MSS()``, never the deprecated ``mss.mss()``.
* One Grabber per thread (the mss instance is created lazily in the first grab() call, in the
  calling thread). Construction costs 0.1-0.2 ms; a 400x150 grab about 8 ms.
* Results are COPIES (np.asarray(shot) is a view into mss memory that is reused).
* Exclusive-fullscreen games and a locked screen capture as black/uniform: the runner calls
  looks_blank() on every capture; a blank-looking REGION is re-checked on the whole client area
  and only a blank client pauses (PauseReason.CAPTURE_BLANK) instead of failing - an empty
  result area is uniform too and must not pause (integration, gate G-01).
* mss copies screen pixels, so AutoPress's own topmost windows (the mini bar) appear in
  captures: the runner masks them (ocr.imageio.mask_rects with RunSession.set_masked_rects);
  win32.windows.exclude_from_capture is applied too, but its effect on mss is UNVERIFIED.

Details (G2):
* A Grabber used from a second thread gets its own mss instance for that thread (GDI device
  contexts belong to the thread that created them); close() releases them all.
* The alpha channel of mss captures is meaningless ("may or may not be valid", mss docs): the
  returned BGRA copies have alpha = 255 everywhere.
* ``CaptureError``: ``str(exc)`` is the complete 7.1 sentence 「無法擷取畫面：{reason}。…」 and
  ``exc.reason`` the short reason. ``grab_client`` lets the ``OSError`` of
  ``win32.windows.client_rect`` for a closed window propagate (the runner pauses TARGET_LOST).
"""

from __future__ import annotations

import logging
import math
import threading

import numpy as np

from .i18n import tr
from .models import ClientRegion, CoordMode, Monitor, Rect, intersect_rect, resolve_region

log = logging.getLogger(__name__)


class CaptureError(RuntimeError):
    """Capture failed (rect outside every monitor, window gone, GDI error). Localized message."""

    def __init__(self, message: str = "", reason: str = "") -> None:
        super().__init__(message)
        self.reason = reason or message


def capture_failed(reason: str) -> CaptureError:
    """CaptureError with the 7.1 text 「無法擷取畫面：{reason}。目標視窗可能已關閉或移到螢幕外。」."""
    return CaptureError(tr("無法擷取畫面：{reason}。目標視窗可能已關閉或移到螢幕外。",
                           "Cannot capture the screen: {reason}. The target window may be closed or off-screen.")
                        .format(reason=reason), reason)


def _short(exc: BaseException) -> str:
    text = " ".join(f"{type(exc).__name__}: {exc}".split())
    return text if len(text) <= 160 else text[:159] + "…"


class Grabber:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._instances: dict[int, object] = {}  # thread id -> mss.MSS (created lazily)

    def _sct(self) -> object:
        tid = threading.get_ident()
        with self._lock:
            sct = self._instances.get(tid)
            if sct is None:
                try:
                    import mss

                    sct = mss.MSS()
                except Exception as exc:  # noqa: BLE001 - missing package / GDI failure
                    raise capture_failed(_short(exc)) from exc
                self._instances[tid] = sct
            return sct

    def monitor_rects(self) -> list[Rect]:
        """Physical rects of every monitor as mss enumerates them (EnumDisplayMonitors)."""
        sct = self._sct()
        try:
            mons = list(sct.monitors)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            raise capture_failed(_short(exc)) from exc
        return [(int(m["left"]), int(m["top"]), int(m["width"]), int(m["height"])) for m in mons[1:]]

    def grab(self, rect: Rect) -> np.ndarray:
        """(h, w, 4) uint8 BGRA copy of the physical screen rect (x, y, w, h)."""
        x, y, w, h = (int(v) for v in rect)
        if w <= 0 or h <= 0:
            raise capture_failed(tr("擷取範圍沒有大小", "the capture area is empty"))
        sct = self._sct()
        monitors = self.monitor_rects()
        if monitors and not any(intersect_rect((x, y, w, h), m) for m in monitors):
            raise capture_failed(tr("擷取範圍不在任何螢幕上", "the area is not on any screen"))
        try:
            shot = sct.grab({"left": x, "top": y, "width": w, "height": h})  # type: ignore[attr-defined]
            out = np.array(shot, dtype=np.uint8, copy=True)
        except Exception as exc:  # noqa: BLE001 - mss.ScreenShotError, GDI errors
            raise capture_failed(_short(exc)) from exc
        if out.shape != (h, w, 4):
            raise capture_failed(f"unexpected capture shape {out.shape}")
        out[:, :, 3] = 255
        return out

    def grab_monitor(self, monitor: Monitor) -> np.ndarray:
        """BGRA copy of one whole monitor (``monitor.rect``)."""
        return self.grab(monitor.rect)

    def _monitors(self) -> list[Monitor]:
        """win32.dpi.monitors() (primary first); mss's list when that is unavailable."""
        try:
            from .win32 import dpi

            mons = list(dpi.monitors())
            if mons:
                return mons
        except NotImplementedError:
            log.debug("win32.dpi.monitors is not implemented yet; using mss's monitor list")
        except Exception:  # noqa: BLE001 - fall back to mss's enumeration
            log.warning("win32.dpi.monitors failed; using mss's monitor list", exc_info=True)
        sct = self._sct()
        out: list[Monitor] = []
        for m in list(sct.monitors)[1:]:  # type: ignore[attr-defined]
            r = (int(m["left"]), int(m["top"]), int(m["width"]), int(m["height"]))
            out.append(Monitor(device=str(m.get("name", "")), rect=r, work=r, dpi=96,
                               primary=bool(m.get("is_primary", r[0] == 0 and r[1] == 0))))
        out.sort(key=lambda mon: not mon.primary)
        return out

    def grab_all(self) -> list[tuple[Monitor, np.ndarray]]:
        """Every monitor (win32.dpi.monitors() order) with its BGRA image (for picker overlays)."""
        return [(m, self.grab(m.rect)) for m in self._monitors()]

    def grab_client(self, hwnd: int, region: ClientRegion | None = None,
                    mode: CoordMode = CoordMode.AUTO) -> tuple[np.ndarray, Rect]:
        """The target's client area, or ``region`` resolved against it (models.resolve_region),
        clipped to the client area. Returns (BGRA image, physical rect captured).
        ``region`` is resolved with ``dpi=win32.windows.window_dpi(hwnd)`` (SPEC 5.2)."""
        from .win32 import windows

        client = tuple(int(v) for v in windows.client_rect(hwnd))  # OSError when the window is gone
        if client[2] <= 0 or client[3] <= 0:
            raise capture_failed(tr("視窗沒有可擷取的內容（可能已最小化）", "the window has no visible content (minimized?)"))
        rect: Rect = client  # type: ignore[assignment]
        if region is not None:
            resolved = resolve_region(rect, region, mode, dpi=int(windows.window_dpi(hwnd)))
            clipped = intersect_rect(resolved, rect)
            if clipped is None:
                raise capture_failed(tr("搜尋範圍在視窗之外", "the region lies outside the window"))
            rect = clipped
        return self.grab(rect), rect

    def close(self) -> None:
        """Release every mss instance (safe to call twice; the Grabber can be used again)."""
        with self._lock:
            instances, self._instances = list(self._instances.values()), {}
        for sct in instances:
            try:
                sct.close()  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001 - e.g. ReleaseDC from another thread
                log.debug("closing an mss instance failed", exc_info=True)

    def __enter__(self) -> Grabber:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def grab_rect(rect: Rect) -> np.ndarray:
    """One-shot capture with a temporary Grabber (any thread)."""
    with Grabber() as g:
        return g.grab(rect)


def looks_blank(image: np.ndarray, std_threshold: float = 2.0) -> bool:
    """True for an (almost) uniform image - typical for exclusive-fullscreen capture.
    The largest per-channel standard deviation (colour channels only) is compared with
    ``std_threshold``; an empty image counts as blank."""
    a = np.asarray(image)
    if a.size == 0 or a.ndim not in (2, 3):
        return True
    try:
        import cv2

        src = a if a.dtype == np.uint8 else np.clip(a, 0, 255).astype(np.uint8)
        _mean, std = cv2.meanStdDev(src)
        values = np.asarray(std, dtype=np.float64).ravel()
        if a.ndim == 3 and a.shape[2] == 4:
            values = values[:3]
        return float(values.max()) < std_threshold
    except Exception:  # noqa: BLE001 - OpenCV missing: numpy on a sample of at most ~250k pixels
        if a.ndim == 3 and a.shape[2] >= 3:
            a = a[:, :, :3]
        h, w = a.shape[:2]
        step = max(1, int(math.sqrt(h * w / 250_000)))
        s = a[::step, ::step].astype(np.float32)
        std = s.reshape(-1, s.shape[2]).std(axis=0).max() if s.ndim == 3 else s.std()
        return float(std) < std_threshold
