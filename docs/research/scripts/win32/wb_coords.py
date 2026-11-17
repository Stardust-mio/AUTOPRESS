"""wb_coords.py - profile coordinate helpers: points/regions relative to a target window's
CLIENT area, stored both as physical-pixel offsets and as ratios of the client size.

All inputs/outputs are PHYSICAL screen pixels (valid in a per-monitor-aware process, i.e.
after QApplication was created; see win32_windows.md). Self-test: python wb_coords.py
(pure math + one hidden own window; nothing is shown, no input is injected).
"""
from __future__ import annotations

import math
import os
import sys
from dataclasses import asdict, dataclass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wb_win32 as w  # noqa: E402

Client = tuple[int, int, int, int]  # (left, top, width, height) of the client area, physical px


@dataclass
class ClientPoint:
    dx: int            # offset from client top-left when recorded (physical px)
    dy: int
    rx: float          # pixel-centre ratio (dx + 0.5) / ref_w, in 0..1
    ry: float
    ref_w: int         # client size when recorded
    ref_h: int
    anchor: str = "tl"  # offset mode anchor: tl | tr | bl | br | center
    ref_dpi: int = 96  # GetDpiForWindow(target) when recorded (diagnostics)


@dataclass
class ClientRegion:
    dx: int
    dy: int
    w: int
    h: int
    rx: float          # rx, ry, rw, rh = dx/ref_w, dy/ref_h, w/ref_w, h/ref_h
    ry: float
    rw: float
    rh: float
    ref_w: int
    ref_h: int
    ref_dpi: int = 96


def record_point(client: Client, px: int, py: int, anchor: str = "tl", dpi: int = 96) -> ClientPoint:
    cx, cy, cw, ch = client
    dx, dy = px - cx, py - cy
    return ClientPoint(dx, dy, (dx + 0.5) / cw, (dy + 0.5) / ch, cw, ch, anchor, dpi)


def resolve_point(client: Client, p: ClientPoint, mode: str = "auto") -> tuple[int, int]:
    """mode: 'offset' (exact pixels, honours anchor), 'ratio' (scales with the client),
    'auto' = offset when the client size is unchanged, otherwise ratio."""
    cx, cy, cw, ch = client
    if mode == "auto":
        mode = "offset" if (cw, ch) == (p.ref_w, p.ref_h) else "ratio"
    if mode == "ratio":
        return cx + min(cw - 1, math.floor(p.rx * cw)), cy + min(ch - 1, math.floor(p.ry * ch))
    ox = {"tl": p.dx, "bl": p.dx, "tr": cw - (p.ref_w - p.dx), "br": cw - (p.ref_w - p.dx),
          "center": (cw - p.ref_w) // 2 + p.dx}[p.anchor]
    oy = {"tl": p.dy, "tr": p.dy, "bl": ch - (p.ref_h - p.dy), "br": ch - (p.ref_h - p.dy),
          "center": (ch - p.ref_h) // 2 + p.dy}[p.anchor]
    return cx + ox, cy + oy


def record_region(client: Client, x: int, y: int, rw: int, rh: int, dpi: int = 96) -> ClientRegion:
    cx, cy, cw, ch = client
    dx, dy = x - cx, y - cy
    return ClientRegion(dx, dy, rw, rh, dx / cw, dy / ch, rw / cw, rh / ch, cw, ch, dpi)


def resolve_region(client: Client, r: ClientRegion, mode: str = "auto") -> tuple[int, int, int, int]:
    cx, cy, cw, ch = client
    if mode == "auto":
        mode = "offset" if (cw, ch) == (r.ref_w, r.ref_h) else "ratio"
    if mode == "offset":
        return cx + r.dx, cy + r.dy, r.w, r.h
    x0, y0 = round(r.rx * cw), round(r.ry * ch)
    x1, y1 = round((r.rx + r.rw) * cw), round((r.ry + r.rh) * ch)
    return cx + x0, cy + y0, max(1, x1 - x0), max(1, y1 - y0)


def inside(client: Client, px: int, py: int) -> bool:
    cx, cy, cw, ch = client
    return cx <= px < cx + cw and cy <= py < cy + ch


def _selftest() -> None:
    import random
    rnd = random.Random(7)
    n = 0
    # 1. round trips at the same size are exact for every mode/anchor (incl. negative origins)
    for _ in range(2000):
        cl = (rnd.randint(-3840, 1900), rnd.randint(-200, 900), rnd.randint(1, 2560), rnd.randint(1, 1440))
        px, py = cl[0] + rnd.randrange(cl[2]), cl[1] + rnd.randrange(cl[3])
        for anchor in ("tl", "tr", "bl", "br", "center"):
            p = record_point(cl, px, py, anchor)
            for mode in ("offset", "ratio", "auto"):
                assert resolve_point(cl, p, mode) == (px, py), (cl, px, py, anchor, mode)
                n += 1
        rw, rh = rnd.randint(1, cl[2] - (px - cl[0])), rnd.randint(1, cl[3] - (py - cl[1]))
        r = record_region(cl, px, py, rw, rh)
        for mode in ("offset", "ratio", "auto"):
            assert resolve_region(cl, r, mode) == (px, py, rw, rh), (cl, r, mode)
            n += 1
    # 2. uniform scaling (window resized 1280x720 -> 1920x1080): ratio lands on the scaled pixel
    small, big = (100, 50, 1280, 720), (-1800, 40, 1920, 1080)
    for _ in range(500):
        dx, dy = rnd.randrange(1280), rnd.randrange(720)
        p = record_point(small, small[0] + dx, small[1] + dy)
        gx, gy = resolve_point(big, p)
        # the resolved pixel must contain the scaled centre of the recorded pixel
        assert abs((gx - big[0] + 0.5) - (dx + 0.5) * 1.5) <= 0.5 and abs((gy - big[1] + 0.5) - (dy + 0.5) * 1.5) <= 0.5
        n += 1
    # 3. anchors keep the distance to their edge when the client grows
    p = record_point((0, 0, 800, 600), 790, 590, "br")
    assert resolve_point((10, 20, 1000, 700), p, "offset") == (10 + 990, 20 + 690)
    p = record_point((0, 0, 800, 600), 400, 300, "center")
    assert resolve_point((0, 0, 1000, 700), p, "offset") == (500, 350)
    n += 2
    print(f"pure-math checks passed: {n}")

    # 4. live: client rect of an own HIDDEN window before/after a resize (WA_DontShowOnScreen)
    from PyQt6.QtCore import QRect, Qt
    from PyQt6.QtWidgets import QApplication, QWidget
    app = QApplication.instance() or QApplication(sys.argv[:1])

    def hidden(rect: QRect) -> tuple[QWidget, int]:
        # NOTE: a later setGeometry() on a WA_DontShowOnScreen widget does NOT reach the HWND
        # (Qt defers it until show), so each size gets its own hidden window.
        wd = QWidget(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        wd.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        wd.setGeometry(rect)
        wd.show()
        app.processEvents()
        return wd, int(wd.winId())

    w1, h1 = hidden(QRect(-1700, 120, 800, 600))
    c1 = w.client_rect_screen(h1)
    p = record_point(c1, c1[0] + 100, c1[1] + 50, dpi=w.GetDpiForWindow(h1))
    r = record_region(c1, c1[0] + 200, c1[1] + 100, 300, 80)
    w2, h2 = hidden(QRect(300, 200, 1000, 750))
    c2 = w.client_rect_screen(h2)
    got_p, got_r = resolve_point(c2, p), resolve_region(c2, r)
    print("live:", "client A", c1, "client B", c2, "point", got_p, "region", got_r, "record", asdict(p))
    assert c2[2:] == (1000, 750) and got_p == (c2[0] + 125, c2[1] + 63) and got_r == (c2[0] + 250, c2[1] + 125, 375, 100)
    w1.close()
    w2.close()
    print("live check passed")


if __name__ == "__main__":
    _selftest()
