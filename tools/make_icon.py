# OWNED BY G8
"""Render the AutoPress app icon: ``autopress/resources/icon.ico`` and ``icon.png``.

    .venv/Scripts/python.exe tools/make_icon.py                       # writes both into autopress/resources
    .venv/Scripts/python.exe tools/make_icon.py --out-dir C:/.../tmp  # elsewhere (tests)
    .venv/Scripts/python.exe tools/make_icon.py --preview C:/.../sheet.png   # also a contact sheet

The drawing is the sidebar logo (docs/research/scripts/ux/prototype.py ICONS["logo"], ported by
G5 to ui/icons.py): a rounded accent square (#2F66F0) with a white ">_" prompt. Each size is
rendered on its own with QSvgRenderer (no down-scaling blur); sizes up to 24 px get a slightly
thicker stroke so the prompt stays readable. The .ico holds 16-256 px: 32-bit BMP entries below
256 px and a PNG entry at 256 px (the layout Windows Explorer, the PyInstaller exe resource and
Qt all read). icon.png is the 256 px image. Rendering uses the offscreen platform (no window).
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
PNG_SIZE = 256
ACCENT = "#2F66F0"  # ui/theme.py accent_fill (dark and light)


def logo_svg(size: int) -> str:
    """SVG of the logo for a ``size`` px raster (24-unit view box, as the sidebar icon)."""
    stroke = 2.2 if size > 24 else 2.6
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke-linecap="round" '
        f'stroke-linejoin="round"><rect x="2" y="2" width="20" height="20" rx="6" fill="{ACCENT}"/>'
        f'<path d="M7.5 8.5l3.5 3.5-3.5 3.5M13 15.5h4" stroke="#FFFFFF" stroke-width="{stroke}"/></svg>'
    )


def _app() -> object:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtGui import QGuiApplication

    return QGuiApplication.instance() or QGuiApplication([sys.argv[0]])


def render(size: int) -> object:
    """QImage (Format_ARGB32, straight alpha) of the logo at ``size`` x ``size`` px."""
    from PyQt6.QtCore import QByteArray, QRectF
    from PyQt6.QtGui import QColor, QImage, QPainter
    from PyQt6.QtSvg import QSvgRenderer

    _app()
    renderer = QSvgRenderer(QByteArray(logo_svg(size).encode("utf-8")))
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(0, 0, 0, 0))
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return img.convertToFormat(QImage.Format.Format_ARGB32)


def png_bytes(img: object) -> bytes:
    from PyQt6.QtCore import QBuffer, QByteArray, QIODevice

    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    if not img.save(buf, "PNG"):  # type: ignore[attr-defined]
        raise RuntimeError("PNG encoding failed")
    buf.close()
    return bytes(data)


def bmp_entry(img: object) -> bytes:
    """ICO image data for one size: BITMAPINFOHEADER (height doubled), 32-bit BGRA rows bottom-up,
    then the 1-bit AND mask (1 = transparent pixel), rows padded to 32 bits."""
    w, h = img.width(), img.height()  # type: ignore[attr-defined]
    stride = img.bytesPerLine()  # type: ignore[attr-defined]
    raw = img.constBits().asstring(img.sizeInBytes())  # type: ignore[attr-defined]  # BGRA, little-endian ARGB32
    rows = [raw[y * stride: y * stride + w * 4] for y in range(h)]
    mask_stride = (w + 31) // 32 * 4
    mask_rows = []
    for row in rows:
        bits = bytearray(mask_stride)
        for x in range(w):
            if row[x * 4 + 3] == 0:
                bits[x // 8] |= 0x80 >> (x % 8)
        mask_rows.append(bytes(bits))
    pixels = b"".join(reversed(rows))
    mask = b"".join(reversed(mask_rows))
    header = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, len(pixels) + len(mask), 0, 0, 0, 0)
    return header + pixels + mask


def ico_bytes(sizes: tuple[int, ...] = ICO_SIZES) -> bytes:
    """A complete .ico file with one entry per size (PNG for 256 px, BMP below)."""
    images = []
    for size in sizes:
        img = render(size)
        images.append((size, png_bytes(img) if size >= 256 else bmp_entry(img)))
    out = bytearray(struct.pack("<HHH", 0, 1, len(images)))
    offset = 6 + 16 * len(images)
    for size, data in images:
        dim = 0 if size >= 256 else size
        out += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    for _size, data in images:
        out += data
    return bytes(out)


def contact_sheet(path: Path) -> None:
    """Preview: every size on the dark and the light window background."""
    from PyQt6.QtGui import QColor, QImage, QPainter

    _app()
    width = sum(ICO_SIZES) + 16 * (len(ICO_SIZES) + 1)
    sheet = QImage(width, 2 * (PNG_SIZE + 32), QImage.Format.Format_ARGB32)
    painter = QPainter(sheet)
    for row, bg in enumerate(("#0E1014", "#F5F6F8")):  # theme.py bg_app dark / light
        y0 = row * (PNG_SIZE + 32)
        painter.fillRect(0, y0, width, PNG_SIZE + 32, QColor(bg))
        x = 16
        for size in ICO_SIZES:
            painter.drawImage(x, y0 + 16 + PNG_SIZE - size, render(size))
            x += size + 16
    painter.end()
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(str(path), "PNG")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--out-dir", default=str(ROOT / "autopress" / "resources"))
    ap.add_argument("--preview", default="", help="also write a contact sheet PNG here")
    a = ap.parse_args(argv)

    from autopress.storage import write_bytes_atomic

    out = Path(a.out_dir)
    write_bytes_atomic(out / "icon.ico", ico_bytes())
    write_bytes_atomic(out / "icon.png", png_bytes(render(PNG_SIZE)))
    if a.preview:
        contact_sheet(Path(a.preview))
    print(out / "icon.ico")
    print(out / "icon.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
