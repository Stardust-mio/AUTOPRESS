# OWNED BY G2 - replace this stub
"""Image helpers. Images are numpy uint8 arrays: HxWx3 BGR (OCR input) or HxWx4 BGRA (mss).
NEVER pass a file path to OpenCV (Chinese paths fail silently): load and save with Pillow.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import numpy as np
from PyQt6.QtGui import QImage

from ..models import Point, Rect

__stub__ = True

IMAGE_EXTENSIONS: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff")


class ImageLoadError(Exception):
    """``str(exc)`` is a localized message."""


def load_image(path: Path | str) -> np.ndarray:
    """BGR image from any Pillow format (EXIF orientation applied, first frame, alpha dropped).
    Raises ImageLoadError."""
    raise NotImplementedError


def to_bgr(image: np.ndarray) -> np.ndarray:
    """BGRA / BGR / grayscale -> contiguous BGR (a copy only when needed)."""
    raise NotImplementedError


def qimage_to_bgr(image: QImage) -> np.ndarray:
    """Any QImage -> BGR copy (handles bytesPerLine padding)."""
    raise NotImplementedError


def to_qimage(image: np.ndarray, dpr: float = 1.0) -> QImage:
    """BGR/BGRA -> QImage Format_RGB32 (deep copy) with setDevicePixelRatio(dpr)."""
    raise NotImplementedError


def clipboard_image() -> np.ndarray | None:
    """BGR image on the clipboard, or None (GUI thread only; uses QGuiApplication.clipboard())."""
    raise NotImplementedError


def save_png(image: np.ndarray, path: Path | str) -> None:
    """Write BGR/BGRA as PNG with Pillow: encode to bytes in memory, then
    storage.write_bytes_atomic (never tempfile.mkstemp); parents created. Raises
    storage.StorageError."""
    raise NotImplementedError


def mask_rects(image: np.ndarray, origin: Point, rects: Sequence[Rect]) -> np.ndarray:
    """Copy of a captured image (whose top-left is the physical screen point ``origin``) with
    every part covered by one of ``rects`` (physical screen rects - AutoPress's own windows,
    RunSession.set_masked_rects) filled with the median colour of the image border, so OCR can
    never read AutoPress's own text (e.g. the mini bar's 「已使用 1」 chip, T01 / PX-03). The
    input is returned unchanged (no copy) when no rect intersects it."""
    raise NotImplementedError


def crop(image: np.ndarray, rect: Rect) -> np.ndarray:
    """Copy of ``image[y:y+h, x:x+w]`` with the rect clamped to the image (may be empty)."""
    raise NotImplementedError


def upscale(image: np.ndarray, k: int) -> np.ndarray:
    """Bicubic enlargement by integer ``k`` (k <= 1 returns the input)."""
    raise NotImplementedError


def image_dialog_filter() -> str:
    """QFileDialog filter, e.g. "圖片 (*.png *.jpg ...);;所有檔案 (*)"."""
    raise NotImplementedError
