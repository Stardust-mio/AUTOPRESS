# OWNED BY G2
"""Image helpers. Images are numpy uint8 arrays: HxWx3 BGR (OCR input) or HxWx4 BGRA (mss).
NEVER pass a file path to OpenCV (Chinese paths fail silently): load and save with Pillow.

* ``load_image`` / ``save_png`` go through Pillow (any path, Chinese folders included); PNGs are
  encoded in memory and written with ``storage.write_bytes_atomic``.
* Transparent pixels (PNG / GIF / clipboard images with alpha) are composited over a background
  that contrasts with the opaque pixels (white behind dark content, black behind light content),
  so a dark code on a transparent background stays readable; opaque images just lose the alpha
  channel. mss captures carry a meaningless alpha channel: ``to_bgr`` simply drops it.
* ``mask_rects`` blanks AutoPress's own windows in captures (T01 / PX-03).
"""

from __future__ import annotations

import io
import logging
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from PyQt6.QtGui import QImage

from ..i18n import tr
from ..models import Point, Rect

log = logging.getLogger(__name__)

IMAGE_EXTENSIONS: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff")


class ImageLoadError(Exception):
    """``str(exc)`` is a localized message."""


def _unreadable(name: str) -> ImageLoadError:
    return ImageLoadError(tr("無法讀取圖片：{name}。請確認是 PNG、JPG 等圖片，或改用截圖貼上。",
                             "Cannot read the image: {name}. Use a PNG / JPG image or paste a screenshot.")
                          .format(name=name))


def _flatten_alpha(bgr: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """Composite ``bgr`` (HxWx3) with ``alpha`` (HxW) over a contrasting background colour.

    Fully opaque images are returned unchanged. The background is white when the opaque pixels
    are dark on average (luminance < 128) and black otherwise (same rule as rapidocr's
    ``cvt_four_to_three``), so text never disappears into a background of its own colour."""
    if alpha.size == 0 or int(alpha.min()) == 255:
        return bgr
    opaque = alpha > 0
    if opaque.any():
        px = bgr[opaque].astype(np.float32)
        lum = float((0.114 * px[:, 0] + 0.587 * px[:, 1] + 0.299 * px[:, 2]).mean())
        bg = 255 if lum < 128 else 0
    else:
        bg = 255
    a = alpha.astype(np.uint32)[:, :, None]
    out = (bgr.astype(np.uint32) * a + bg * (255 - a) + 127) // 255
    return np.ascontiguousarray(out.astype(np.uint8))


def load_image(path: Path | str) -> np.ndarray:
    """BGR image from any Pillow format (EXIF orientation applied, first frame, alpha dropped -
    transparent pixels composited over a contrasting background). Raises ImageLoadError."""
    from PIL import Image, ImageOps

    p = Path(path)
    try:
        with Image.open(p) as im:
            im.seek(0)  # first frame of GIF / WebP / TIFF animations
            im = ImageOps.exif_transpose(im) or im
            has_alpha = im.mode in ("RGBA", "LA", "PA", "RGBa", "La") or "transparency" in im.info
            if has_alpha:
                rgba = np.asarray(im.convert("RGBA"))
                bgr = np.ascontiguousarray(rgba[:, :, 2::-1])
                return _flatten_alpha(bgr, np.ascontiguousarray(rgba[:, :, 3]))
            rgb = np.asarray(im.convert("RGB"))
            return np.ascontiguousarray(rgb[:, :, ::-1])
    except Exception as exc:  # noqa: BLE001 - every Pillow / OS failure becomes the 7.1 message
        log.info("cannot read image %s: %s: %s", p.name, type(exc).__name__, exc)
        raise _unreadable(p.name) from exc


def to_bgr(image: np.ndarray) -> np.ndarray:
    """BGRA / BGR / grayscale -> contiguous BGR (a copy only when needed)."""
    a = np.asarray(image)
    if a.dtype != np.uint8:
        a = np.clip(a, 0, 255).astype(np.uint8)
    if a.ndim == 2:
        return np.ascontiguousarray(np.repeat(a[:, :, None], 3, axis=2))
    if a.ndim == 3:
        channels = a.shape[2]
        if channels == 3:
            return a if a.flags.c_contiguous else np.ascontiguousarray(a)
        if channels == 4:
            return np.ascontiguousarray(a[:, :, :3])
        if channels == 1:
            return np.ascontiguousarray(np.repeat(a, 3, axis=2))
    raise ValueError(f"unsupported image shape {a.shape}")


def qimage_to_bgr(image: QImage) -> np.ndarray:
    """Any QImage -> BGR copy (handles bytesPerLine padding). Transparent pixels are composited
    like ``load_image`` does; a null image gives a 0x0x3 array."""
    if image is None or image.isNull():
        return np.zeros((0, 0, 3), np.uint8)
    alpha = image.hasAlphaChannel()
    img = image.convertToFormat(QImage.Format.Format_ARGB32 if alpha else QImage.Format.Format_RGB32)
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    # little-endian (A)RGB32 = bytes B, G, R, A per pixel
    buf = np.frombuffer(ptr, np.uint8).reshape(h, bpl)[:, : w * 4].reshape(h, w, 4)
    bgr = np.ascontiguousarray(buf[:, :, :3])
    if alpha:
        return _flatten_alpha(bgr, np.ascontiguousarray(buf[:, :, 3]))
    return bgr


def to_qimage(image: np.ndarray, dpr: float = 1.0) -> QImage:
    """BGR/BGRA -> QImage Format_RGB32 (deep copy) with setDevicePixelRatio(dpr)."""
    bgr = to_bgr(image)
    h, w = bgr.shape[:2]
    if h == 0 or w == 0:
        return QImage()
    buf = np.empty((h, w, 4), np.uint8)
    buf[:, :, :3] = bgr
    buf[:, :, 3] = 255
    q = QImage(buf.data, w, h, w * 4, QImage.Format.Format_RGB32).copy()  # copy: own the pixels
    q.setDevicePixelRatio(float(dpr) if dpr and dpr > 0 else 1.0)
    return q


def clipboard_image() -> np.ndarray | None:
    """BGR image on the clipboard, or None (GUI thread only; uses QGuiApplication.clipboard()).
    An image file copied in Explorer (a local file URL with an image extension) is loaded too."""
    from PyQt6.QtGui import QGuiApplication

    if not isinstance(QGuiApplication.instance(), QGuiApplication):
        return None
    cb = QGuiApplication.clipboard()
    if cb is None:
        return None
    md = cb.mimeData()
    if md is None:
        return None
    if md.hasImage():
        img = cb.image()
        if not img.isNull():
            return qimage_to_bgr(img)
    if md.hasUrls():
        for url in md.urls():
            if not url.isLocalFile():
                continue
            p = Path(url.toLocalFile())
            if p.suffix.lower() in IMAGE_EXTENSIONS and p.is_file():
                try:
                    return load_image(p)
                except ImageLoadError:
                    log.info("clipboard file %s is not a readable image", p.name)
                    return None
    return None


def save_png(image: np.ndarray, path: Path | str) -> None:
    """Write BGR/BGRA as PNG with Pillow: encode to bytes in memory, then
    storage.write_bytes_atomic (never tempfile.mkstemp); parents created. Raises
    storage.StorageError. The alpha channel of BGRA input (meaningless for mss captures) is
    dropped; grayscale is written as an 8-bit grayscale PNG."""
    from PIL import Image

    from .. import storage

    p = Path(path)
    try:
        a = np.asarray(image)
        if a.ndim == 2:
            pil = Image.fromarray(a if a.dtype == np.uint8 else np.clip(a, 0, 255).astype(np.uint8))
        else:
            pil = Image.fromarray(np.ascontiguousarray(to_bgr(a)[:, :, ::-1]))
        out = io.BytesIO()
        pil.save(out, format="PNG")
        data = out.getvalue()
    except Exception as exc:  # noqa: BLE001 - encoding problems become a StorageError like write errors
        raise storage.StorageError(tr("無法寫入圖片：{path}（{err}）", "Cannot write the image: {path} ({err})")
                                   .format(path=p, err=exc)) from exc
    storage.write_bytes_atomic(p, data)


def _border_fill(image: np.ndarray, parts: Sequence[tuple[int, int, int, int]]) -> np.ndarray:
    """Median colour of the image border, ignoring border pixels inside ``parts``
    (x0, y0, x1, y1 in image pixels); all border pixels when every one is covered."""
    h, w = image.shape[:2]
    xs = np.concatenate([np.arange(w), np.arange(w), np.zeros(max(0, h - 2), int), np.full(max(0, h - 2), w - 1)])
    ys = np.concatenate([np.zeros(w, int), np.full(w, h - 1), np.arange(1, h - 1), np.arange(1, h - 1)])
    covered = np.zeros(xs.shape[0], bool)
    for x0, y0, x1, y1 in parts:
        covered |= (xs >= x0) & (xs < x1) & (ys >= y0) & (ys < y1)
    keep = ~covered if (~covered).any() else np.ones_like(covered)
    values = image[ys[keep], xs[keep]]
    return np.round(np.median(values, axis=0)).astype(image.dtype)


def mask_rects(image: np.ndarray, origin: Point, rects: Sequence[Rect]) -> np.ndarray:
    """Copy of a captured image (whose top-left is the physical screen point ``origin``) with
    every part covered by one of ``rects`` (physical screen rects - AutoPress's own windows,
    RunSession.set_masked_rects) filled with the median colour of the image border, so OCR can
    never read AutoPress's own text (e.g. the mini bar's 「已使用 1」 chip, T01 / PX-03). The
    input is returned unchanged (no copy) when no rect intersects it. Border pixels that lie
    under a masked rect do not count for the median (the mini bar may touch the border)."""
    h, w = image.shape[:2]
    ox, oy = int(origin[0]), int(origin[1])
    parts: list[tuple[int, int, int, int]] = []
    for r in rects or ():
        x, y, rw, rh = (int(v) for v in r)
        if rw <= 0 or rh <= 0:
            continue
        x0, y0 = max(0, x - ox), max(0, y - oy)
        x1, y1 = min(w, x - ox + rw), min(h, y - oy + rh)
        if x1 > x0 and y1 > y0:
            parts.append((x0, y0, x1, y1))
    if not parts:
        return image
    fill = _border_fill(image, parts)
    out = image.copy()
    for x0, y0, x1, y1 in parts:
        out[y0:y1, x0:x1] = fill
    return out


def crop(image: np.ndarray, rect: Rect) -> np.ndarray:
    """Copy of ``image[y:y+h, x:x+w]`` with the rect clamped to the image (may be empty)."""
    h, w = image.shape[:2]
    x, y, rw, rh = (int(v) for v in rect)
    x0, y0 = min(max(0, x), w), min(max(0, y), h)
    x1, y1 = max(x0, min(w, x + rw)), max(y0, min(h, y + rh))
    return image[y0:y1, x0:x1].copy()


def resize(image: np.ndarray, width: int, height: int) -> np.ndarray:
    """Bicubic resize (Pillow, as measured in ocr.md) to ``width`` x ``height``; 1-, 3- and
    4-channel uint8 images (the alpha plane is resized separately, never premultiplied)."""
    from PIL import Image

    a = np.asarray(image)
    width, height = max(1, int(width)), max(1, int(height))
    if a.shape[0] == 0 or a.shape[1] == 0:
        return np.zeros((height, width) + a.shape[2:], np.uint8)
    if a.dtype != np.uint8:
        a = np.clip(a, 0, 255).astype(np.uint8)

    def rs(plane: np.ndarray) -> np.ndarray:
        img = Image.fromarray(np.ascontiguousarray(plane))
        return np.asarray(img.resize((width, height), Image.Resampling.BICUBIC))

    if a.ndim == 2:
        return np.ascontiguousarray(rs(a))
    if a.shape[2] == 1:
        return np.ascontiguousarray(rs(a[:, :, 0])[:, :, None])
    if a.shape[2] == 3:
        return np.ascontiguousarray(rs(a))
    if a.shape[2] == 4:
        out = np.empty((height, width, 4), np.uint8)
        out[:, :, :3] = rs(a[:, :, :3])
        out[:, :, 3] = rs(a[:, :, 3])
        return out
    raise ValueError(f"unsupported image shape {a.shape}")


def upscale(image: np.ndarray, k: int) -> np.ndarray:
    """Bicubic enlargement by integer ``k`` (k <= 1 returns the input)."""
    k = int(k)
    if k <= 1:
        return image
    h, w = image.shape[:2]
    return resize(image, w * k, h * k)


def image_dialog_filter() -> str:
    """QFileDialog filter, e.g. "圖片 (*.png *.jpg ...);;所有檔案 (*)"."""
    patterns = " ".join("*" + ext for ext in IMAGE_EXTENSIONS)
    return f"{tr('圖片', 'Images')} ({patterns});;{tr('所有檔案', 'All files')} (*)"
