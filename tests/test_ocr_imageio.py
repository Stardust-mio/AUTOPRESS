"""G2: ocr.imageio - Chinese paths, EXIF, alpha, QImage round trip, mask_rects, save_png via
storage.write_bytes_atomic, crop / upscale / to_bgr. No OCR engine, no screen."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from PyQt6.QtGui import QImage

from autopress import storage
from autopress.ocr import imageio


def pattern(h: int, w: int) -> np.ndarray:
    y, x = np.mgrid[0:h, 0:w]
    return np.dstack([(x * 7 + y * 3) % 256, (x * 5 + y * 11 + 40) % 256, (x ^ y) % 256]).astype(np.uint8)


def save_rgb(path: Path, bgr: np.ndarray, **kw: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.ascontiguousarray(bgr[:, :, ::-1])).save(path, **kw)


# ----------------------------------------------------------------------------- load / save


def test_load_image_chinese_path(tmp_path: Path) -> None:
    img = pattern(30, 50)
    p = tmp_path / "測試路徑" / "截圖 兌換碼.png"
    save_rgb(p, img)
    out = imageio.load_image(p)
    assert out.dtype == np.uint8 and out.shape == (30, 50, 3) and out.flags.c_contiguous
    assert np.array_equal(out, img)
    assert np.array_equal(imageio.load_image(str(p)), img)


def test_load_image_applies_exif_orientation(tmp_path: Path) -> None:
    img = np.zeros((20, 40, 3), np.uint8)
    img[0:4, 0:4] = (0, 0, 255)  # red marker top-left (BGR)
    pil = Image.fromarray(np.ascontiguousarray(img[:, :, ::-1]))
    exif = Image.Exif()
    exif[0x0112] = 6  # orientation: rotate 90 degrees clockwise to display
    p = tmp_path / "照片.jpg"
    pil.save(p, exif=exif, quality=100)
    out = imageio.load_image(p)
    assert out.shape == (40, 20, 3)  # width and height swapped
    assert out[1, -2, 2] > 200 and out[1, -2, 0] < 60  # the marker moved to the top-right corner


def test_load_image_first_frame_and_alpha(tmp_path: Path) -> None:
    frames = [Image.new("RGB", (16, 8), c) for c in ((255, 0, 0), (0, 255, 0))]
    gif = tmp_path / "動畫.gif"
    frames[0].save(gif, save_all=True, append_images=frames[1:], duration=50)
    out = imageio.load_image(gif)
    assert out.shape == (8, 16, 3) and out[0, 0, 2] > 200 and out[0, 0, 1] < 60  # red = first frame

    # dark text on a transparent background must stay readable: composited over white
    rgba = np.zeros((10, 20, 4), np.uint8)
    rgba[3:7, 5:15] = (20, 20, 20, 255)
    p = tmp_path / "透明.png"
    Image.fromarray(rgba).save(p)
    flat = imageio.load_image(p)
    assert tuple(flat[0, 0]) == (255, 255, 255) and tuple(flat[5, 10]) == (20, 20, 20)
    # light text on transparency -> black background
    rgba[3:7, 5:15] = (240, 240, 240, 255)
    Image.fromarray(rgba).save(p)
    flat = imageio.load_image(p)
    assert tuple(flat[0, 0]) == (0, 0, 0) and tuple(flat[5, 10]) == (240, 240, 240)


def test_load_image_errors_are_localized(tmp_path: Path) -> None:
    with pytest.raises(imageio.ImageLoadError) as e1:
        imageio.load_image(tmp_path / "不存在.png")
    assert "無法讀取圖片：不存在.png" in str(e1.value)
    bad = tmp_path / "壞掉.jpg"
    bad.write_bytes(b"this is not an image")
    with pytest.raises(imageio.ImageLoadError) as e2:
        imageio.load_image(bad)
    assert "壞掉.jpg" in str(e2.value) and "PNG" in str(e2.value)


def test_save_png_uses_write_bytes_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[Path, bytes]] = []
    real = storage.write_bytes_atomic

    def spy(path: Path, data: bytes) -> None:
        calls.append((Path(path), data))
        real(path, data)

    monkeypatch.setattr(storage, "write_bytes_atomic", spy)
    img = pattern(12, 20)
    target = tmp_path / "證據" / "2026-11-17" / "run_1.png"  # parents are created
    imageio.save_png(img, target)
    assert len(calls) == 1 and calls[0][0] == target and calls[0][1][:8] == b"\x89PNG\r\n\x1a\n"
    assert np.array_equal(imageio.load_image(target), img)
    assert [p.name for p in target.parent.iterdir()] == ["run_1.png"]  # no temp file left

    bgra = np.dstack([img, np.zeros((12, 20), np.uint8)])  # mss alpha: meaningless zeros
    imageio.save_png(bgra, target)
    assert np.array_equal(imageio.load_image(target), img)


def test_save_png_failure_raises_storage_error(tmp_path: Path) -> None:
    with pytest.raises(storage.StorageError):
        imageio.save_png(np.zeros((0, 0, 3), np.uint8), tmp_path / "empty.png")


# ----------------------------------------------------------------------------- conversions


def test_to_bgr_variants() -> None:
    bgr = pattern(4, 6)
    assert imageio.to_bgr(bgr) is bgr  # contiguous BGR: no copy
    nc = bgr[:, ::2]
    out = imageio.to_bgr(nc)
    assert out.flags.c_contiguous and np.array_equal(out, nc)
    bgra = np.dstack([bgr, np.full((4, 6), 7, np.uint8)])
    assert np.array_equal(imageio.to_bgr(bgra), bgr) and imageio.to_bgr(bgra).flags.c_contiguous
    gray = bgr[:, :, 0]
    g3 = imageio.to_bgr(gray)
    assert g3.shape == (4, 6, 3) and np.array_equal(g3[:, :, 2], gray)
    with pytest.raises(ValueError):
        imageio.to_bgr(np.zeros((2, 2, 5), np.uint8))


def test_qimage_round_trip(qapp: object) -> None:
    img = pattern(9, 13)  # odd sizes
    q = imageio.to_qimage(img, dpr=1.25)
    assert q.format() == QImage.Format.Format_RGB32 and q.devicePixelRatio() == pytest.approx(1.25)
    assert (q.width(), q.height()) == (13, 9)
    assert np.array_equal(imageio.qimage_to_bgr(q), img)
    del img  # the QImage owns its pixels (deep copy)
    assert imageio.qimage_to_bgr(q).shape == (9, 13, 3)
    assert imageio.to_qimage(np.zeros((0, 5, 3), np.uint8)).isNull()
    assert imageio.qimage_to_bgr(QImage()).shape == (0, 0, 3)


def test_qimage_to_bgr_handles_padding_and_formats(qapp: object) -> None:
    img = pattern(5, 7)
    bpl = 7 * 4 + 12  # padded rows
    buf = np.zeros((5, bpl), np.uint8)
    buf[:, : 7 * 4].reshape(5, 7, 4)[:, :, :3] = img
    raw = buf.tobytes()
    q = QImage(raw, 7, 5, bpl, QImage.Format.Format_RGB32)
    assert q.bytesPerLine() == bpl
    assert np.array_equal(imageio.qimage_to_bgr(q), img)
    rgb888 = QImage(np.ascontiguousarray(img[:, :, ::-1]).tobytes(), 7, 5, 21, QImage.Format.Format_RGB888)
    assert np.array_equal(imageio.qimage_to_bgr(rgb888), img)
    argb = QImage(4, 3, QImage.Format.Format_ARGB32)
    argb.fill(0)  # fully transparent -> composited over white
    assert np.all(imageio.qimage_to_bgr(argb) == 255)


def test_clipboard_image(qapp: object) -> None:
    from PyQt6.QtGui import QGuiApplication

    if QGuiApplication.platformName() != "offscreen":
        pytest.skip("only on the offscreen platform: never touch the user's real clipboard")
    cb = QGuiApplication.clipboard()
    img = pattern(6, 10)
    cb.setImage(imageio.to_qimage(img))
    got = imageio.clipboard_image()
    assert got is not None and np.array_equal(got, img)
    cb.setText("AB12-CD34")
    assert imageio.clipboard_image() is None


# ----------------------------------------------------------------------------- mask / crop / upscale


def test_mask_rects_blanks_own_windows_with_border_median() -> None:
    img = np.full((100, 200, 3), (40, 30, 20), np.uint8)
    img[60:80, 120:190] = (250, 250, 250)  # the mini bar's 「已使用 1」 chip, white
    origin = (1000, 500)
    out = imageio.mask_rects(img, origin, [(1000 + 115, 500 + 55, 80, 30)])
    assert out is not img
    assert np.all(out[55:85, 115:195] == (40, 30, 20))  # filled with the background
    assert np.array_equal(out[:55], img[:55]) and np.array_equal(out[:, :115], img[:, :115])
    assert np.array_equal(img[60:80, 120:190], np.full((20, 70, 3), 250, np.uint8))  # input untouched


def test_mask_rects_no_intersection_returns_input() -> None:
    img = pattern(50, 60)
    assert imageio.mask_rects(img, (0, 0), []) is img
    assert imageio.mask_rects(img, (0, 0), [(60, 0, 10, 10), (-20, -20, 20, 20), (5, 5, 0, 9)]) is img


def test_mask_rects_clips_and_ignores_covered_border() -> None:
    img = np.full((40, 80, 4), (10, 200, 10, 0), np.uint8)
    img[:, 60:] = (255, 0, 255, 0)  # a bar touching the right border (magenta)
    out = imageio.mask_rects(img, (-100, 0), [(-100 + 60, -10, 50, 60)])  # partly outside the image
    assert np.all(out[:, 60:] == (10, 200, 10, 0))  # magenta border pixels did not count
    assert np.array_equal(out[:, :60], img[:, :60])


def test_crop_clamps_and_copies() -> None:
    img = pattern(20, 30)
    c = imageio.crop(img, (25, -5, 10, 10))
    assert c.shape == (5, 5, 3) and np.array_equal(c, img[0:5, 25:30])
    c[:] = 0
    assert img[0, 25].any()  # a copy
    assert imageio.crop(img, (40, 40, 5, 5)).shape == (0, 0, 3)


def test_upscale_and_resize() -> None:
    img = pattern(10, 12)
    assert imageio.upscale(img, 1) is img and imageio.upscale(img, 0) is img
    up = imageio.upscale(img, 2)
    assert up.shape == (20, 24, 3) and up.dtype == np.uint8
    bgra = np.dstack([img, np.zeros((10, 12), np.uint8)])  # alpha 0 must not wipe the colours
    up4 = imageio.upscale(bgra, 3)
    assert up4.shape == (30, 36, 4) and up4[:, :, :3].mean() > 50 and not up4[:, :, 3].any()
    flat = np.full((8, 8, 3), 77, np.uint8)
    assert np.all(imageio.upscale(flat, 2) == 77)
    assert imageio.resize(img, 5, 7).shape == (7, 5, 3)
    assert imageio.resize(img[:, :, 0], 6, 6).shape == (6, 6)


def test_image_dialog_filter() -> None:
    f = imageio.image_dialog_filter()
    assert f.startswith("圖片 (") and "*.png" in f and "*.webp" in f and f.endswith(";;所有檔案 (*)")
