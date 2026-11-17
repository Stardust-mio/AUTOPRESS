"""Screenshots for the README and the user guide: every page, dialog and overlay of AutoPress,
all built from ONE demo state, rendered with real fonts but never shown on screen.

    .venv/Scripts/python.exe tools/guide_capture.py OUTDIR --theme dark|light [--scale 1.5]
        [--lang zh-TW|en] [--only main,codes,...] [--geometry]
    .venv/Scripts/python.exe tools/guide_capture.py --list        # every screen and what it shows

One process renders one theme x scale x language (QT_SCALE_FACTOR must be set before Qt
starts), so run it once per combination. It writes, and nothing else:

* ``OUTDIR/<screen>_<theme>_<100|125|150>.png`` (``_en`` appended with ``--lang en``);
* ``OUTDIR/report_<theme>_<scale>[_en].txt``: per screen the size, plain labels whose text is
  clipped (labels that elide with "…" on purpose are not listed), table rows cut at the bottom,
  self-checks of the demo state, privacy problems and errors;
* with ``--geometry``: ``OUTDIR/<screen>_<theme>_<scale>[_en].json`` next to each PNG - the
  visible child widgets (objectName, class, visible text, accessibleName, rect [x, y, w, h] in
  PNG pixels, parent id), the visible table rows and header sections, and the painted marks of
  the overlay screens - to place numbered callouts exactly (tools/screenshots.py).

Safety and honesty:

* The real desktop never reaches a picture. Before any widget exists, every window lookup of
  autopress.win32.windows, the privilege probe (win32.elevation.input_permission), this process's
  elevation (is_elevated: no, can_elevate: yes - also when started from an elevated shell) and the
  monitor list (win32.dpi) are replaced by a demo desktop: the demo redeem page in a browser, a demo
  game and two neutral system windows on one 1280x800 monitor. Real window titles can hold e-mail
  addresses or account names.
* The demo profile is used as a profile made from the web template: its steps carry the
  template's names and it passed a 測試一筆 before the demo history.
* Nothing is shown and no input is sent: widgets are rendered on the real ``windows`` platform with
  WA_DontShowOnScreen; the run session (FakeRunSession), OCR and hotkeys are fakes; overlays are
  drawn over a painted mock redeem page instead of a screen capture.
* One demo state (tests/fakes.py demo_context with a fixed clock) everywhere: the same codes,
  counts, history (with times and evidence crops) and theme setting on every screen; the run
  screens replay one run in the engine's signal order with the runner's own messages.
* A privacy check refuses to write a picture whose texts contain the user's profile folder, the
  temp folder or the computer name; the Settings data-folder line shows a demo path.

Data lives in throw-away folders that are deleted at the end. Exit code 1 when a screen failed.
"""

from __future__ import annotations

import argparse
import inspect
import json
import os
import re
import shutil
import sys
import tempfile
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from autopress.models import (  # noqa: E402 - after the sys.path line
    Attention,
    CodeStatus,
    LogEntry,
    LogLevel,
    Monitor,
    PauseReason,
    PreflightReport,
    Profile,
    ResultClass,
    RunState,
    StepType,
    StopReason,
    TargetMatch,
    ThemeName,
    TimeoutAction,
    WindowInfo,
    make_step,
)

SCREEN_W, SCREEN_H, TASKBAR_H = 1280, 800, 40  # the demo monitor (logical px; x scale = physical)
CLIENT = (0, 0, 1280, 720)  # the demo browser's client area = the demo profile's recorded size
PAGE_SIZE = (1060, 764)  # a page inside the default 1280x800 main window (sidebar 220, status bar 36)
MAIN_SIZE = (1280, 800)  # default main window
MIN_SIZE = (1100, 700)  # minimum main window
DEMO_NOW = datetime(2026, 11, 16, 20, 36, 12)  # local time of the newest history record
RUN_START = datetime(2026, 11, 16, 20, 41, 3)  # local time the replayed run starts
DEMO_DATA_DIR = "C:\\Users\\Demo\\AppData\\Roaming\\AutoPress"  # shown instead of the throw-away folder
HWND_BROWSER, HWND_GAME, HWND_FILES, HWND_NOTES = 0x1111, 0x2222, 0x3333, 0x4444
SETTLE_S = 0.6  # event processing after show (the Run page re-checks after 400 ms)
# countdown: the browser window sits lower, away from the screen's top-left corner (the failsafe
# corner's ring, arrow and label are drawn on the desktop), its page below the countdown card: no
# text of the page is cut by the card's edge
COUNTDOWN_WINDOW_AT = (0, 330)
SHEET_CLIENT = (0, 0, 1180, 660)  # sheet: the browser window made smaller than when the positions were recorded


def _tr(zh: str, en: str) -> str:
    from autopress.i18n import tr

    return tr(zh, en)


def _demo(zh: str) -> str:
    from tests.fakes import demo_text

    return demo_text(zh)


# =============================================================================== demo desktop


def browser_title() -> str:
    return _tr("示範遊戲 兌換頁 - Google Chrome", "Demo Game Redeem - Google Chrome")


def demo_windows() -> list[WindowInfo]:
    """The windows of the demo desktop in z-order (topmost first). Titles follow the UI language."""
    return [
        WindowInfo(hwnd=HWND_BROWSER, title=browser_title(), class_name="Chrome_WidgetWin_1", pid=7412,
                   exe_path="C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", rect=CLIENT, client=CLIENT),
        WindowInfo(hwnd=HWND_GAME, title=_demo("示範遊戲"), class_name="DemoGameWindow", pid=7520,
                   exe_path="D:\\Games\\DemoGame\\DemoGame.exe", rect=(0, 0, 1280, 720), client=(0, 0, 1280, 720)),
        WindowInfo(hwnd=HWND_FILES, title=_tr("下載", "Downloads"), class_name="CabinetWClass", pid=6120,
                   exe_path="C:\\Windows\\explorer.exe", rect=(160, 120, 900, 560), client=(168, 151, 884, 521)),
        WindowInfo(hwnd=HWND_NOTES, title=_tr("序號清單.txt - 記事本", "codes.txt - Notepad"), class_name="Notepad",
                   pid=8836, exe_path="C:\\Windows\\System32\\notepad.exe", rect=(240, 160, 700, 480),
                   client=(248, 191, 684, 441)),
    ]


def demo_monitors() -> list[Monitor]:
    return [Monitor(device="\\\\.\\DISPLAY1", rect=(0, 0, SCREEN_W, SCREEN_H),
                    work=(0, 0, SCREEN_W, SCREEN_H - TASKBAR_H), dpi=96, primary=True)]


class DemoWorld:
    """The fake desktop every patched lookup answers from. A screen may change ``windows``
    (e.g. without the browser); ``reset()`` restores the default before the next screen."""

    def __init__(self) -> None:
        self.windows: list[WindowInfo] = []
        self.permissions: dict[int, str] = {}
        self.reset()

    def reset(self) -> None:
        self.windows = demo_windows()
        self.permissions = {HWND_GAME: "blocked_elevated"}  # games often run as administrator

    def get(self, hwnd: int) -> WindowInfo | None:
        return next((w for w in self.windows if w.hwnd == int(hwnd or 0)), None)

    def matching(self, match: TargetMatch) -> list[WindowInfo]:
        return [replace(w) for w in self.windows if match.matches(w.exe_path, w.title, w.class_name)]

    def at(self, x: int, y: int, scale: float = 1.0) -> int:
        for w in self.windows:
            rx, ry, rw, rh = (round(v * scale) for v in w.rect)
            if not w.minimized and rx <= x < rx + rw and ry <= y < ry + rh:
                return w.hwnd
        return 0

    def is_demo(self, hwnd: int) -> bool:
        return int(hwnd or 0) in (HWND_BROWSER, HWND_GAME, HWND_FILES, HWND_NOTES)


class _Patches:
    def __init__(self) -> None:
        self._saved: list[tuple[Any, str, Any]] = []

    def set(self, obj: Any, name: str, value: Any) -> None:
        self._saved.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def undo(self) -> None:
        for obj, name, old in reversed(self._saved):
            setattr(obj, name, old)
        self._saved.clear()


def install_demo_environment(world: DemoWorld) -> Callable[[], None]:
    """Replace the window lookups, the privilege probe and the monitor list with ``world``.
    App modules call them through the module (``windows.find_window(...)``), so the patch
    reaches every caller. Returns a function that restores the originals (tests)."""
    from autopress.win32 import dpi, elevation, windows

    p = _Patches()
    own_check, own_dpi = windows.is_own_window, windows.window_dpi

    def gone(hwnd: int) -> OSError:
        return OSError(f"window {hwnd:#x} does not exist (demo desktop)")

    def rect_of(hwnd: int, attr: str) -> tuple[int, int, int, int]:
        info = world.get(hwnd)
        if info is None:
            raise gone(int(hwnd or 0))
        return getattr(info, attr)

    p.set(windows, "list_windows", lambda alt_tab_only=True: [replace(w) for w in world.windows])
    p.set(windows, "find_windows", lambda match: world.matching(match))
    p.set(windows, "find_window", lambda match: next(iter(world.matching(match)), None))
    p.set(windows, "window_info", lambda hwnd: (lambda i: replace(i) if i else None)(world.get(hwnd)))
    p.set(windows, "window_at", lambda x, y, skip_own=False: world.at(int(x), int(y)) or None)
    p.set(windows, "client_rect", lambda hwnd: rect_of(hwnd, "client"))
    p.set(windows, "window_rect", lambda hwnd: rect_of(hwnd, "rect"))
    p.set(windows, "restored_rect", lambda hwnd: rect_of(hwnd, "rect"))
    p.set(windows, "frame_bounds", lambda hwnd: (lambda i: i.rect if i else None)(world.get(hwnd)))
    p.set(windows, "is_window", lambda hwnd: world.get(hwnd) is not None)
    p.set(windows, "is_alive", lambda info: world.get(getattr(info, "hwnd", 0)) is not None)
    p.set(windows, "is_minimized", lambda hwnd: bool(getattr(world.get(hwnd), "minimized", False)))
    p.set(windows, "foreground_window", lambda: 0)
    p.set(windows, "window_pid", lambda hwnd: getattr(world.get(hwnd), "pid", 0))
    p.set(windows, "is_own_window", lambda hwnd: False if world.is_demo(hwnd) else own_check(hwnd))
    p.set(windows, "window_dpi", lambda hwnd: 96 if world.is_demo(hwnd) else own_dpi(hwnd))
    perm = elevation.InputPermission
    p.set(elevation, "input_permission",
          lambda hwnd: perm(world.permissions.get(int(hwnd or 0), "ok")) if world.is_demo(hwnd) else perm.UNKNOWN)
    # AutoPress runs as a normal user that may elevate - also when the tool is started from an
    # elevated shell (the Codes page's no-drag-and-drop hint, the window picker's restart button)
    p.set(elevation, "is_elevated", lambda: False)
    p.set(elevation, "can_elevate", lambda: True)
    mons = demo_monitors()
    p.set(dpi, "monitors", lambda: list(mons))
    p.set(dpi, "primary_monitor", lambda: mons[0])
    p.set(dpi, "monitor_at", lambda x, y: mons[0])
    try:  # the window list shows exe icons: the generic one for the demo programs on every PC
        from PyQt6.QtCore import QFileInfo

        from autopress.ui import window_picker

        demo_exes = {Path(w.exe_path).name.casefold() for w in world.windows} - {"explorer.exe", "notepad.exe"}
        base = window_picker.QFileIconProvider

        class DemoIcons(base):  # type: ignore[misc, valid-type]
            def icon(self, what: Any) -> Any:
                if isinstance(what, QFileInfo) and what.fileName().casefold() in demo_exes:
                    what = QFileInfo(f"C:/autopress-demo-missing/{what.fileName()}")
                return super().icon(what)

        p.set(window_picker, "QFileIconProvider", DemoIcons)
    except (ImportError, AttributeError):  # no Qt widgets here (or the picker changed): plain icons
        pass
    return p.undo


class DemoBackend:
    """The runner Backend calls that run_preflight and preview_profile make, answered from the
    demo desktop at ``scale`` (no system calls, no input, no screen capture)."""

    def __init__(self, world: DemoWorld, page: RedeemPage, scale: float = 1.0) -> None:
        self.world, self.page, self.scale = world, page, scale

    def _scaled(self, rect: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        return tuple(round(v * self.scale) for v in rect)  # type: ignore[return-value]

    def _info(self, hwnd: int) -> WindowInfo | None:
        w = self.world.get(hwnd)
        return replace(w, rect=self._scaled(w.rect), client=self._scaled(w.client)) if w else None

    def find_targets(self, match: TargetMatch) -> list[WindowInfo]:
        return [self._info(w.hwnd) for w in self.world.matching(match)]  # type: ignore[misc]

    def find_target(self, match: TargetMatch) -> WindowInfo | None:
        return next(iter(self.find_targets(match)), None)

    def window_info(self, hwnd: int) -> WindowInfo | None:
        return self._info(hwnd)

    def is_alive(self, info: WindowInfo) -> bool:
        return self.world.get(info.hwnd) is not None

    def client_rect(self, hwnd: int) -> tuple[int, int, int, int]:
        info = self._info(hwnd)
        if info is None:
            raise OSError("window gone (demo desktop)")
        return info.client

    def is_minimized(self, hwnd: int) -> bool:
        return bool(getattr(self.world.get(hwnd), "minimized", False))

    def foreground(self) -> int:
        return HWND_BROWSER

    def window_pid(self, hwnd: int) -> int:
        return getattr(self.world.get(hwnd), "pid", 0)

    def bring_to_foreground(self, hwnd: int, sleep: Any = None, timeout_s: float = 3.0) -> bool:
        return True

    def window_dpi(self, hwnd: int) -> int:
        return round(96 * self.scale)

    def window_at(self, x: int, y: int, skip_own: bool = False) -> int:
        return self.world.at(int(x), int(y), self.scale)

    def is_own_window(self, hwnd: int) -> bool:
        return False

    def own_pid(self) -> int:
        return os.getpid()

    def input_permission(self, hwnd: int) -> str:
        return self.world.permissions.get(int(hwnd or 0), "ok")

    def can_elevate(self) -> bool:
        return True

    def grab(self, rect: tuple[int, int, int, int]) -> Any:
        import numpy as np

        x, y, w, h = rect
        shot = self.page.bgra(scale=self.scale)
        return np.ascontiguousarray(shot[max(0, y):y + h, max(0, x):x + w])

    def close(self) -> None:
        pass


# =============================================================================== the mock redeem page


@dataclass
class PageLayout:
    """Where the demo profile clicks and reads, in client px (scale 1)."""

    input_center: tuple[int, int] = (540, 250)
    button_center: tuple[int, int] = (600, 390)
    result_region: tuple[int, int, int, int] = (200, 150, 760, 140)

    @classmethod
    def from_profile(cls, profile: Profile | None) -> PageLayout:
        out = cls()
        if profile is None:
            return out
        for step in profile.steps:
            prm = step.params
            if step.type is StepType.CLICK_POINT and getattr(prm, "point", None) is not None:
                out.input_center = (prm.point.dx, prm.point.dy)
            elif step.type is StepType.CLICK_TEXT and getattr(prm, "region", None) is not None:
                r = prm.region
                out.button_center = (r.dx + r.w // 2, r.dy + r.h // 2)
            elif step.type is StepType.OCR_CHECK and getattr(prm, "region", None) is not None:
                r = prm.region
                out.result_region = (r.dx, r.dy, r.w, r.h)
        return out


TONES = {"success": (22, 150, 90), "warning": (190, 118, 10), "error": (205, 52, 52), "": (60, 66, 78)}
STATUS_TONE = {CodeStatus.SUCCESS: "success", CodeStatus.USED: "warning", CodeStatus.REVIEW: "warning",
               CodeStatus.INVALID: "error", CodeStatus.EXPIRED: "error", CodeStatus.FAILED: "error"}


class RedeemPage:
    """The demo redeem page in a browser window on the demo monitor, painted with PIL: a
    neutral browser frame (no logos), a code box where the demo profile clicks, a Redeem button
    inside its text-search region and a result line inside its result region."""

    def __init__(self, layout: PageLayout) -> None:
        self.layout = layout
        self._cache: dict[tuple[Any, ...], Any] = {}

    @staticmethod
    def _font(px: float, bold: bool = False, mono: bool = False) -> Any:
        from PIL import ImageFont

        fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        names = (("consolab.ttf", "consola.ttf") if mono else ()) + (
            ("msjhbd.ttc", "segoeuib.ttf", "arialbd.ttf") if bold else ("msjh.ttc", "segoeui.ttf", "arial.ttf"))
        for name in names:
            if (fonts / name).is_file():
                return ImageFont.truetype(str(fonts / name), max(6, round(px)))
        return ImageFont.load_default(max(6, round(px)))

    def screen(self, scale: float = 1.0, code: str = "", message: str = "", tone: str = "") -> Any:
        """The whole demo monitor (PIL RGB image, physical px = logical x ``scale``)."""
        key = ("screen", scale, code, message, tone, _tr("zh", "en"))
        if key not in self._cache:
            self._cache[key] = self._paint(scale, code, message, tone)
        return self._cache[key]

    def bgra(self, scale: float = 1.0, code: str = "", message: str = "", tone: str = "") -> Any:
        import numpy as np

        rgb = np.asarray(self.screen(scale, code, message, tone).convert("RGBA"))
        return np.ascontiguousarray(rgb[:, :, [2, 1, 0, 3]])

    def windowed(self, scale: float, at: tuple[int, int]) -> Any:
        """The demo monitor with the browser window moved to ``at`` (logical px; its bottom goes
        under the taskbar): the screen's top-left corner shows the desktop, so the countdown's corner
        ring and 「緊急停止」 label do not cover the tab title."""
        from PIL import Image, ImageDraw

        full = self.screen(scale)
        s = scale
        ox, oy = round(at[0] * s), round(at[1] * s)
        out = Image.new("RGB", full.size, (36, 43, 56))
        browser = full.crop((0, 0, round(CLIENT[2] * s), round(CLIENT[3] * s)))
        out.paste(browser, (ox, oy))
        d = ImageDraw.Draw(out)  # a thin window edge against the desktop
        if ox > 0:
            d.line([(ox - 1, oy), (ox - 1, out.height)], fill=(70, 78, 92), width=max(1, round(s)))
        if oy > 0:
            d.line([(ox, oy - 1), (out.width, oy - 1)], fill=(70, 78, 92), width=max(1, round(s)))
        taskbar_top = round((SCREEN_H - TASKBAR_H) * s)
        out.paste(full.crop((0, taskbar_top, full.width, full.height)), (0, taskbar_top))
        return out

    def result_crop(self, code: str, message: str, tone: str, scale: float = 1.0) -> Any:
        """The result region in physical px at ``scale`` - what the runner saves as evidence on a
        monitor at that scale (760 x 140 at 100 %, 1140 x 210 at 150 %)."""
        x, y, w, h = (round(v * scale) for v in self.layout.result_region)
        return self.screen(scale, code, message, tone).crop((x, y, x + w, y + h))

    def _paint(self, s: float, code: str, message: str, tone: str) -> Any:
        from PIL import Image, ImageDraw

        def r(*v: float) -> list[int]:
            return [round(a * s) for a in v]

        img = Image.new("RGB", (round(SCREEN_W * s), round(SCREEN_H * s)), (36, 43, 56))
        d = ImageDraw.Draw(img)
        cx0, cy0, cw, ch = CLIENT
        white, line, muted, ink = (255, 255, 255), (220, 224, 231), (110, 117, 130), (30, 34, 42)
        # taskbar: neutral squares only
        d.rectangle(r(0, SCREEN_H - TASKBAR_H, SCREEN_W, SCREEN_H), fill=(24, 28, 36))
        for k in range(5):
            x = SCREEN_W / 2 - 110 + k * 46
            d.rounded_rectangle(r(x, SCREEN_H - 31, x + 22, SCREEN_H - 9), radius=round(5 * s), fill=(70, 78, 92))
        d.text(r(SCREEN_W - 18, SCREEN_H - 20), RUN_START.strftime("%H:%M"), font=self._font(13 * s),
               fill=(220, 224, 231), anchor="rm")
        # browser frame
        d.rectangle(r(cx0, cy0, cx0 + cw, cy0 + ch), fill=(239, 242, 247))
        d.rectangle(r(cx0, cy0, cx0 + cw, cy0 + 36), fill=(222, 226, 232))
        d.rounded_rectangle(r(cx0 + 8, cy0 + 6, cx0 + 268, cy0 + 44), radius=round(8 * s), fill=white)
        tab = browser_title().rsplit(" - ", 1)[0]
        d.text(r(cx0 + 24, cy0 + 21), tab, font=self._font(13 * s), fill=ink, anchor="lm")
        d.rectangle(r(cx0, cy0 + 36, cx0 + cw, cy0 + 74), fill=white)
        d.line(r(cx0, cy0 + 74, cx0 + cw, cy0 + 74), fill=line, width=max(1, round(s)))
        for k in range(2):
            x = cx0 + 22 + k * 28
            d.ellipse(r(x - 8, cy0 + 47, x + 8, cy0 + 63), outline=(150, 156, 168), width=max(1, round(2 * s)))
        d.rounded_rectangle(r(cx0 + 84, cy0 + 42, cx0 + cw - 60, cy0 + 68), radius=round(13 * s), fill=(241, 243, 246))
        d.text(r(cx0 + 104, cy0 + 55), "redeem.example.com/demo", font=self._font(13 * s), fill=muted, anchor="lm")
        # the redeem card around the profile's positions
        lay = self.layout
        rx, ry, rw, rh = lay.result_region
        ix, iy = lay.input_center
        bx, by = lay.button_center
        left, right = min(rx, ix - 200) - 40, max(rx + rw, ix + 200) + 40
        top, bottom = min(cy0 + 88, ry - 62), by + 134
        d.rounded_rectangle(r(left, top, right, bottom), radius=round(14 * s), fill=white, outline=line,
                            width=max(1, round(s)))
        # the title stays above the result region and the preview's badge row (region top - 24)
        d.text(r(left + 40, top + 8), _tr("序號兌換", "Redeem a code"), font=self._font(20 * s, bold=True), fill=ink)
        if message:
            col = TONES.get(tone, TONES[""])
            d.ellipse(r(rx + 20, ry + 20, rx + 42, ry + 42), fill=col)
            if tone == "success":
                d.line(r(rx + 25, ry + 31, rx + 29.5, ry + 36, rx + 37, ry + 26), fill=white, width=max(2, round(3 * s)))
            else:
                d.text(r(rx + 31, ry + 31), "!" if tone else "i", font=self._font(15 * s, bold=True), fill=white,
                       anchor="mm")
            d.text(r(rx + 52, ry + 31), message, font=self._font(18 * s, bold=True), fill=col, anchor="lm")
        d.text(r(ix - 200, iy - 44), _tr("序號", "Code"), font=self._font(13 * s), fill=muted)
        d.rounded_rectangle(r(ix - 200, iy - 22, ix + 200, iy + 22), radius=round(7 * s), fill=white,
                            outline=(190, 197, 208), width=max(1, round(1.5 * s)))
        if code:
            d.text(r(ix - 184, iy), code, font=self._font(19 * s, mono=True), fill=ink, anchor="lm")
        else:
            d.text(r(ix - 184, iy), _tr("請輸入序號", "Enter your code"), font=self._font(16 * s), fill=(150, 156, 168),
                   anchor="lm")
        d.rounded_rectangle(r(bx - 70, by - 24, bx + 70, by + 24), radius=round(8 * s), fill=(48, 99, 226))
        d.text(r(bx, by), _tr("兌換", "Redeem"), font=self._font(17 * s, bold=True), fill=white, anchor="mm")
        d.text(r((left + right) / 2, by + 84), _tr("每個序號限兌換一次，獎勵會寄到遊戲內信箱。",
                                                    "Each code works once. Rewards arrive in your in-game mailbox."),
               font=self._font(13 * s), fill=muted, anchor="mm")
        return img


def qimage(img: Any, scale: float = 1.0) -> Any:
    """PIL RGB image -> QImage with device pixel ratio ``scale``."""
    from PyQt6.QtGui import QImage

    rgb = img.convert("RGB")
    q = QImage(rgb.tobytes("raw", "RGB"), rgb.width, rgb.height, 3 * rgb.width, QImage.Format.Format_RGB888).copy()
    q.setDevicePixelRatio(scale)
    return q


def ocr_demo_image(ctx: Any) -> Any:
    """A stream screenshot with three codes (BGR) and the matching fake OCR result."""
    import numpy as np
    from PIL import Image, ImageDraw

    from autopress.models import OcrLine, OcrResult

    font = RedeemPage._font(30)
    lines = [_tr("限時序號", "Limited-time codes"), "K8ZL0W3NBX5H", "MX4T9PK2JR7Z", "AP7K2QX9MZ4T"]
    img = Image.new("RGB", (520, 300), (24, 26, 36))
    d = ImageDraw.Draw(img)
    ocr_lines = []
    for i, ln in enumerate(lines):
        y = 30 + i * 64
        d.text((30, y), ln, font=font, fill=(240, 240, 240))
        w = int(font.getlength(ln))
        confs = [0.99] * len(ln)
        if i == 1:
            confs[4] = 0.62  # "0" or "O"?
        ocr_lines.append(OcrLine(text=ln, quad=[(26, y - 2), (34 + w, y - 2), (34 + w, y + 40), (26, y + 40)],
                                 score=0.95, char_confs=confs if i else None))
    ctx.ocr.result = OcrResult(lines=ocr_lines, width=520, height=300)
    return np.ascontiguousarray(np.asarray(img)[:, :, ::-1])


# =============================================================================== one screen's stage


def _iso(t: datetime) -> str:
    return t.astimezone().isoformat(timespec="seconds")


def _accepts(fn: Any, name: str) -> bool:
    try:
        return name in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def _kw(fn: Any, **kwargs: Any) -> dict[str, Any]:
    """Only the keyword arguments ``fn`` accepts (app signatures change while the guide is made)."""
    return {k: v for k, v in kwargs.items() if _accepts(fn, k)}


class Stage:
    """The context of one screen: a fresh data folder with the demo state, the demo desktop,
    the mock page, live preflight reports and the run replay helpers."""

    def __init__(self, opts: argparse.Namespace, world: DemoWorld, empty: bool = False) -> None:
        from tests.fakes import demo_context

        self.opts, self.world, self.scale = opts, world, float(opts.scale)
        self.home = Path(tempfile.mkdtemp(prefix="ap-guide-"))
        os.environ["AUTOPRESS_HOME"] = str(self.home)
        self.ctx = demo_context(self.home, with_data=not empty, now=DEMO_NOW)
        self.ctx.settings.theme = ThemeName(opts.theme)  # Appearance controls match the picture
        if not empty:
            self._like_a_template_profile()
        self.page = RedeemPage(PageLayout.from_profile(self.profile))
        self.ctx.session.preflight_provider = self.preflight
        self.keep: list[Any] = []

    @property
    def profile(self) -> Profile | None:
        return self.ctx.active_profile()

    def _like_a_template_profile(self) -> None:
        """The demo profile as a user has it after creating it from the web template and using it:
        its steps carry the template's names (the wizard, the step list and the run screens show
        what to click instead of the step type) and it passed a 測試一筆 before the demo history
        (whose successes would contradict a 'never tested' warning)."""
        from autopress.storage import load_templates

        p = self.profile
        if p is None:
            return
        names: dict[StepType, tuple[str, str]] = {}
        for t in load_templates():
            if t.template is not None and t.template.key == "web_generic":
                for step in t.steps:
                    names.setdefault(step.type, (step.label, step.label_en))
        for step in p.steps:
            if step.type in names and not (step.label or step.label_en):
                step.label, step.label_en = names[step.type]
        p.last_test_ok_at = _iso(DEMO_NOW - timedelta(hours=1))
        self.ctx.profiles.save(p, touch=False)

    def preflight(self, plan: Any) -> PreflightReport:
        """The real pre-flight check of ``plan`` against the demo desktop (100 % geometry)."""
        from autopress.runner.preflight import run_preflight

        unassigned = sum(1 for i in self.ctx.queue.items() if not i.game_key)
        state = getattr(self.ctx.ocr.state, "value", str(self.ctx.ocr.state))
        kwargs = _kw(run_preflight, code_count=len(plan.items), ocr_state=state, unassigned_count=unassigned,
                     backend=DemoBackend(self.world, self.page, 1.0), target_hwnd=plan.target_hwnd)
        return run_preflight(plan.profile, self.ctx.settings, **kwargs)

    def attach_evidence(self) -> None:
        """A result-area crop for every history record that went through a result check, saved
        where the runner saves evidence; the records point to it."""
        for rec in self.ctx.history.records():
            if rec.result is None or rec.evidence_path:
                continue
            rel = f"evidence/{(rec.finished_at or '')[:10] or 'demo'}/{rec.code}.png"
            self.write_evidence(rel, rec.code, rec.message, STATUS_TONE.get(rec.status, ""))
            self.ctx.history.update(rec.id, evidence_path=rel)

    def write_evidence(self, rel: str, code: str, message: str, tone: str) -> str:
        path = self.home / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        self.page.result_crop(code, message, tone, self.scale).save(path)  # as big as the UI around it
        return rel

    def code_ids(self, *statuses: CodeStatus) -> list[str]:
        return [i.id for i in self.ctx.queue.items() if i.status in statuses]


# the replayed run: (status, demo message) per runnable code, in queue order
DEMO_RUN = [(CodeStatus.SUCCESS, "兌換成功，獎勵已寄至信箱"), (CodeStatus.USED, "此序號已被使用"),
            (CodeStatus.SUCCESS, "兌換成功，獎勵已寄至信箱"), (CodeStatus.INVALID, "序號無效")]
UNKNOWN_TEXT = ("本活動序號每人限領一次", "One redemption per player for this event")
CODE_SECONDS, WAITS = 5.0, (7, 6, 8)  # per code; interval waits after code 1, 2, 3


class RunReplay:
    """One run of the demo plan, emitted in the engine's order (code_started, step_started per
    step, code_finished, progress, log; waiting between codes) with fixed times."""

    def __init__(self, st: Stage) -> None:
        self.st, self.s = st, st.ctx.session
        self.t = 0.0
        self.counts: dict[CodeStatus, int] = {}
        self.done = 0
        self.plan: Any = None

    def at(self, t: float | None = None) -> str:
        return _iso(RUN_START + timedelta(seconds=self.t if t is None else t))

    def start(self) -> RunReplay:
        p = self.st.profile
        self.plan = self.s.build_plan(p, self.st.ctx.settings)
        self.s.start(self.plan)
        return self

    def _log(self, level: LogLevel, text: str, code_id: str = "", step: int = -1) -> None:
        self.s.log.emit(LogEntry(time=self.at(), level=level, message=text, code_id=code_id, step_index=step))

    def steps(self) -> list[tuple[int, Any]]:
        return [(i, s) for i, s in enumerate(self.plan.profile.steps) if s.enabled and s.type is not StepType.UNKNOWN]

    def step_index(self, step_type: StepType) -> int:
        return next((i for i, s in self.steps() if s.type is step_type), self.steps()[-1][0])

    def begin(self, i: int, last_step: int | None = None) -> None:
        from autopress.runner import messages as msg

        item = self.plan.items[i]
        self.s.begin_code(item.code_id, i)
        self._log(LogLevel.INFO, msg.code_started(i + 1, len(self.plan.items), item.code), item.code_id)
        for idx, step in self.steps():
            if last_step is not None and idx > last_step:
                break
            self.s.step_started.emit(item.code_id, idx, step.display_title())

    def finish(self, i: int, status: CodeStatus, message: str, **record: Any) -> None:
        from autopress.runner import messages as msg

        item = self.plan.items[i]
        started = self.at()
        self.t += CODE_SECONDS
        self.s.finish_code(item.code_id, status, message, started_at=started, finished_at=self.at(),
                           duration_ms=int(CODE_SECONDS * 1000), **record)
        self.counts[status] = self.counts.get(status, 0) + 1
        self.done += 1
        left = len(self.plan.items) - self.done
        self.s.progress.emit(self.done, len(self.plan.items), self.t / self.done * left if left else 0.0)
        level = (LogLevel.SUCCESS if status in (CodeStatus.SUCCESS, CodeStatus.SUBMITTED)
                 else LogLevel.WARNING if status in (CodeStatus.REVIEW, CodeStatus.USED, CodeStatus.EXPIRED)
                 else LogLevel.ERROR if status in (CodeStatus.FAILED, CodeStatus.INVALID) else LogLevel.INFO)
        self._log(level, msg.code_result(item.code, status.label(), message), item.code_id)

    def wait(self, seconds: float) -> None:
        self.s.waiting.emit(float(seconds))
        self.t += seconds
        self.s.waiting.emit(0.0)

    def play(self, i: int) -> None:
        status, text = DEMO_RUN[i]
        self.begin(i)
        result = {CodeStatus.SUCCESS: ResultClass.SUCCESS, CodeStatus.USED: ResultClass.USED,
                  CodeStatus.INVALID: ResultClass.INVALID}.get(status)
        self.finish(i, status, _demo(text), result=result)
        if i < len(self.plan.items) - 1:
            self.wait(WAITS[i % len(WAITS)])

    def unknown_result(self, i: int) -> None:
        """Code ``i`` reads a result no keyword group knows: REVIEW, then a decision pause."""
        from autopress.runner import messages as msg

        item = self.plan.items[i]
        check = self.step_index(StepType.OCR_CHECK)
        self.begin(i, check)
        text = _tr(*UNKNOWN_TEXT)
        rel = self.st.write_evidence(f"evidence/{RUN_START:%Y-%m-%d}/{item.code}.png", item.code, text, "warning")
        self.finish(i, CodeStatus.REVIEW, text, result=ResultClass.UNKNOWN, evidence_path=rel)
        self._log(LogLevel.WARNING, msg.unknown_result(text), item.code_id, check)
        self.s.pause_for(Attention(kind=PauseReason.UNKNOWN_RESULT, message=msg.unknown_result(text),
                                   code_id=item.code_id, step_index=check, ocr_text=text, evidence_path=rel))

    def finish_run(self) -> None:
        from autopress.runner import messages as msg

        self.s.finish_run(StopReason.COMPLETED, msg.completed(len(self.plan.items)), counts=self.counts,
                          started_at=self.at(0), finished_at=self.at())

    def mid_run(self) -> None:
        """Codes 1-2 finished, code 3 at its click-text step (the moment of run_running)."""
        self.start()
        self.play(0)
        self.play(1)
        self.begin(2, self.step_index(StepType.CLICK_TEXT))


# =============================================================================== screens


@dataclass
class Built:
    widget: Any
    size: tuple[int, int] = (0, 0)  # (0, 0) = the widget's own size
    after_show: Callable[[], None] | None = None
    checks: list[Callable[[Any], str | None]] = field(default_factory=list)  # (grabbed QImage) -> problem
    extras: Callable[[], list[dict[str, Any]]] | None = None  # painted items, logical px
    trim: bool = True  # end the picture on a row / line boundary


@dataclass
class Screen:
    name: str
    about: str
    build: Callable[[Stage], Built]
    empty: bool = False


def _shared_profile() -> Profile:
    """A profile file a friend shared (import card): in-game redeem through the chat box, then a
    fixed chat command that opens the mailbox - a line the card highlights (fixed text with a line
    break), so the picture shows the warning column too."""
    p = Profile(name=_tr("朋友分享：遊戲內兌換", "Shared: in-game redeem"), game=_demo("示範遊戲"),
                author=_tr("示範玩家", "DemoPlayer"),
                description=_tr("在遊戲聊天框輸入兌換指令，關閉結果視窗後打開信箱。",
                                "Types the redeem command in the game chat, closes the result popup and opens the mailbox."),
                suggested_exe="DemoGame.exe")
    open_chat, send = make_step(StepType.KEY), make_step(StepType.KEY)
    open_chat.params.keys = send.params.keys = "Enter"
    command = make_step(StepType.TYPE_TEXT)
    command.params.text = "/redeem {code}"
    close = make_step(StepType.CLICK_TEXT)
    close.params.text = "確定|OK"
    close.params.on_not_found = TimeoutAction.CONTINUE
    mailbox = make_step(StepType.TYPE_TEXT)
    mailbox.params.text = "/mail\n"
    p.steps = [make_step(StepType.FOCUS_WINDOW), open_chat, command, send, make_step(StepType.OCR_CHECK), close,
               mailbox]
    return p


def _wizard_plan(st: Stage) -> tuple[Any, list[Any], int]:
    """(profile, position items, total screens) of a first setup of the demo profile: its click
    position and result region are not recorded yet; the target is chosen (SetupWizard.run)."""
    from autopress.ui import profiles_wizard as pw

    fresh = st.profile.clone(new_identity=False)
    for step in fresh.steps:
        if step.type is StepType.CLICK_POINT:
            step.params.point = None
        elif step.type is StepType.OCR_CHECK:
            step.params.region = None
    items = pw.position_items(fresh, False)
    has_close = any(s.type is StepType.OCR_CHECK for _i, s in fresh.enabled_steps())
    return fresh, items, len(items) + int(has_close) + 1


class _Backdrop:
    """Factory of a plain widget that paints an image (or a desktop gradient) - no style sheet,
    so nothing cascades into the overlay or the mini bars on top of it."""

    @staticmethod
    def make(image: Any = None) -> Any:
        from PyQt6.QtCore import QPointF
        from PyQt6.QtGui import QColor, QLinearGradient, QPainter
        from PyQt6.QtWidgets import QWidget

        class Backdrop(QWidget):
            def paintEvent(self, _event: Any) -> None:  # noqa: N802
                p = QPainter(self)
                if image is not None:
                    p.drawImage(self.rect(), image)
                else:
                    g = QLinearGradient(QPointF(0, 0), QPointF(0, self.height()))
                    g.setColorAt(0, QColor(46, 56, 74))
                    g.setColorAt(1, QColor(30, 36, 48))
                    p.fillRect(self.rect(), g)
                p.end()

        w = Backdrop()
        w.setObjectName("guideBackdrop")
        return w


def _overlay_child(host: Any, overlay: Any) -> Any:
    overlay.setParent(host)  # keeps the flags except the window type: a child now
    overlay.setGeometry(0, 0, SCREEN_W, SCREEN_H)
    return overlay


# -- pages ----------------------------------------------------------------------------------


def s_main(st: Stage) -> Built:
    from autopress.ui.main_window import MainWindow

    w = MainWindow(st.ctx)
    return Built(w, MAIN_SIZE, checks=[_check_history_badge(st, w)])


def s_main_empty(st: Stage) -> Built:
    from autopress.ui.main_window import MainWindow

    return Built(MainWindow(st.ctx), MIN_SIZE)


def s_codes(st: Stage) -> Built:
    from autopress.ui.codes_page import CodesPage

    return Built(CodesPage(st.ctx), PAGE_SIZE)


def s_codes_selected(st: Stage) -> Built:
    from autopress.ui.codes_page import CodesPage

    page = CodesPage(st.ctx)
    ids = st.code_ids(CodeStatus.REVIEW)  # the two codes OCR was unsure about

    def select() -> None:
        page.select_ids(ids, **_kw(page.select_ids, scroll=False))

    return Built(page, PAGE_SIZE, after_show=select)


def s_codes_running(st: Stage) -> Built:
    from autopress.ui.codes_page import CodesPage

    return Built(CodesPage(st.ctx), PAGE_SIZE, after_show=lambda: RunReplay(st).mid_run())


def s_codes_empty(st: Stage) -> Built:
    from autopress.ui.codes_page import CodesPage

    return Built(CodesPage(st.ctx), PAGE_SIZE)


def s_paste(st: Stage) -> Built:
    from autopress.ui.paste_dialog import PasteDialog

    # every line holds a code: no stray English word becomes an unticked 「不像序號」 row (U34)
    text = _tr("今天的直播序號：\nAB12-CD34-EF56\nAP7K2QX9MZ4T（重複）\n兌換碼：XY12ZW34QP\nＱＲ５６－ＳＴ７８ＵＶ\n",
               "Codes from today's stream:\nAB12-CD34-EF56\nAP7K2QX9MZ4T (again)\nCode: XY12ZW34QP\n"
               "ＱＲ５６－ＳＴ７８ＵＶ\n")
    return Built(PasteDialog(st.ctx, text, **_kw(PasteDialog.__init__, format_choice="generic")), (940, 600),
                 trim=False)


def s_ocr_review(st: Stage) -> Built:
    from autopress.ui.ocr_review import OcrReviewDialog

    dlg = OcrReviewDialog(st.ctx, ocr_demo_image(st.ctx), **_kw(OcrReviewDialog.__init__, format_choice="generic",
                                                                  detail=_tr("直播截圖.png", "stream.png")))
    return Built(dlg, (1120, 680), trim=False)


def s_profiles(st: Stage) -> Built:
    from autopress.ui.profiles_page import ProfilesPage

    return Built(ProfilesPage(st.ctx), PAGE_SIZE)


def s_profiles_steps(st: Stage) -> Built:
    from PyQt6.QtCore import QPoint

    from autopress.ui.profiles_page import ProfilesPage

    page = ProfilesPage(st.ctx)

    def show_steps() -> None:
        page.step_list.set_current(2)  # "type the code": the editor with the most options
        QApplicationProcess()
        area, content = page.editor_page, page.editor_page.widget()
        card = page.step_list
        while card.parentWidget() is not None and card.parentWidget() is not content:
            card = card.parentWidget()  # the steps card (a direct child of the editor content)
        area.verticalScrollBar().setValue(max(0, card.mapTo(content, QPoint(0, 0)).y() - 16))

    return Built(page, PAGE_SIZE, after_show=show_steps)


def s_profiles_missing(st: Stage) -> Built:
    from autopress.ui.profiles_page import ProfilesPage

    p = st.profile
    for step in p.steps:
        if step.type is StepType.CLICK_POINT:
            step.params.point = None  # one position not recorded
            break
    p.target = TargetMatch(exe="chrome.exe", title="")  # a browser target without a title keyword
    st.ctx.profiles.save(p)
    return Built(ProfilesPage(st.ctx), PAGE_SIZE)


def s_gallery(st: Stage) -> Built:
    from autopress.ui.profiles_page import ProfilesPage

    return Built(ProfilesPage(st.ctx), PAGE_SIZE)


def s_import_card(st: Stage) -> Built:
    from autopress.ui.profiles_dialogs import ImportCardDialog

    return Built(ImportCardDialog(_shared_profile(), "share.autopress.json"), trim=False)


def s_window_picker(st: Stage) -> Built:
    from autopress.ui.window_picker import WindowPickerDialog

    dlg = WindowPickerDialog(st.ctx, st.profile.target, None)
    dlg.select_hwnd(HWND_BROWSER)
    return Built(dlg, trim=False)


def s_wizard_position(st: Stage) -> Built:
    from autopress.ui import profiles_wizard as pw

    _fresh, items, total = _wizard_plan(st)
    cls = pw._PositionDialog  # noqa: SLF001 - the wizard's own dialog
    return Built(cls(1, len(items), items[0], False, None, **_kw(cls.__init__, progress=(1, total))), trim=False)


def s_wizard_close(st: Stage) -> Built:
    from autopress.ui import profiles_wizard as pw

    _fresh, items, total = _wizard_plan(st)
    cls = pw._CloseDialog  # noqa: SLF001
    current = pw.find_close_step(st.profile)[1]
    return Built(cls(current, None, **_kw(cls.__init__, progress=(len(items) + 1, total))), trim=False)


def s_wizard_test(st: Stage) -> Built:
    from autopress.ui import profiles_wizard as pw
    from autopress.ui.run_actions import first_runnable

    _fresh, _items, total = _wizard_plan(st)
    cls = pw._TestDialog  # noqa: SLF001
    first = st.ctx.queue.get(first_runnable(st.ctx, st.profile))
    return Built(cls(st.profile, first.code if first else "", None, **_kw(cls.__init__, progress=(total, total))),
                 trim=False)


def s_run_idle(st: Stage) -> Built:
    from autopress.ui.run_page import RunPage

    return Built(RunPage(st.ctx), PAGE_SIZE)


def s_run_preflight(st: Stage) -> Built:
    from autopress.ui.run_page import RunPage

    st.world.windows = [w for w in st.world.windows if w.hwnd != HWND_BROWSER]  # the redeem page is not open
    return Built(RunPage(st.ctx), PAGE_SIZE)


def s_run_running(st: Stage) -> Built:
    from autopress.ui.run_page import RunPage

    return Built(RunPage(st.ctx), PAGE_SIZE, after_show=lambda: RunReplay(st).mid_run())


def s_run_attention(st: Stage) -> Built:
    from autopress.ui.run_page import RunPage

    from PyQt6.QtCore import QPoint

    page = RunPage(st.ctx)

    def replay() -> None:
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QScrollArea

        run = RunReplay(st).start()
        run.play(0)
        run.play(1)
        run.unknown_result(2)
        QApplicationProcess(0.6)
        # drawn as in a window tall enough for the whole page, like run_summary: no page scroll bar narrows
        # the cards, so they end where they do on run_running and run_summary
        page.findChild(QScrollArea).setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        QApplicationProcess(0.2)
        # the picture ends 12 px below the decision card, its bottom border included, at every scale
        bottom = page.attention.mapTo(page, QPoint(0, page.attention.height())).y()
        page.resize(page.width(), min(page.height(), bottom + 12))

    return Built(page, PAGE_SIZE, after_show=replay, trim=False)


def s_run_summary(st: Stage) -> Built:
    from autopress.ui.run_page import RunPage

    page = RunPage(st.ctx)

    def replay() -> None:
        from PyQt6.QtWidgets import QScrollArea

        run = RunReplay(st).start()
        for i in range(len(run.plan.items)):
            run.play(i)
        run.finish_run()
        QApplicationProcess(0.6)  # the page re-checks after 400 ms
        body = page.findChild(QScrollArea).widget()
        page.resize(page.width(), min(page.height(), body.sizeHint().height()))  # no empty band at the bottom

    def log_kept(_img: Any) -> str | None:
        n = page.log_view.count() if hasattr(page, "log_view") else -1
        return None if n != 0 else "the live log is empty after the run"

    # up to 1000 px, taller than the window page: the summary and the run's log in one picture (then
    # as tall as the content)
    return Built(page, (PAGE_SIZE[0], 1000), after_show=replay, checks=[log_kept])


def s_sheet(st: Stage) -> Built:
    from autopress.ui.run_sheet import PreflightSheet

    # the moment the user presses Start after making the browser window smaller: the pre-flight warns that the
    # window size differs from the recording and the sheet asks to acknowledge it. The demo profile stays as on
    # every other screen (tested, the same codes), so the pictures do not contradict each other
    st.world.windows = [replace(w, rect=SHEET_CLIENT, client=SHEET_CLIENT) if w.hwnd == HWND_BROWSER else w
                        for w in st.world.windows]
    plan = st.ctx.session.build_plan(st.profile, st.ctx.settings)
    return Built(PreflightSheet(st.ctx, st.preflight(plan), plan), trim=False)


def _feed_bar(bar: Any, state: str, reason: str, done: int, eta: float, code: str, step: str,
              results: list[CodeStatus]) -> None:
    """Mini bar calls in RunFlow's order for one moment of the demo run."""
    bar.set_state(state, reason) if reason else bar.set_state(state)
    bar.set_progress(done, len(DEMO_RUN), eta)
    bar.set_current(code, step)
    for status in results:
        bar.add_result(status)


def _bar_moments(st: Stage) -> list[tuple[str, str, int, float, str, str, list[CodeStatus], float]]:
    """(state, reason, done, eta, code, step title, results, cool-down s) for: running at code 3,
    paused (focus lost) at code 3, rate-limit cool-down on code 2 (a moment before; no step runs
    while the code waits, as RunFlow shows it)."""
    p = st.profile
    codes = [i.code for i in st.ctx.queue.runnable(game_key=p.game_key())]
    title = {s.type: s.display_title() for s in reversed(p.steps)}
    return [
        (RunState.RUNNING.value, "", 2, 17.0, codes[2], title[StepType.CLICK_TEXT], [CodeStatus.SUCCESS, CodeStatus.USED], 0),
        (RunState.PAUSED.value, PauseReason.FOCUS_LOST.value, 2, 17.0, codes[2], title[StepType.CLICK_TEXT],
         [CodeStatus.SUCCESS, CodeStatus.USED], 0),
        (RunState.COOLDOWN.value, "", 1, 15.0, codes[1], "", [CodeStatus.SUCCESS], 287),  # no step runs while it waits
    ]


def s_minibar(st: Stage) -> Built:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QVBoxLayout

    from autopress.ui.minibar import MiniBar

    host = _Backdrop.make()
    lay = QVBoxLayout(host)
    lay.setContentsMargins(20, 20, 20, 20)
    lay.setSpacing(14)
    bars = []
    for state, reason, done, eta, code, step, results, cool in _bar_moments(st):
        bar = MiniBar(st.ctx)
        bar.setWindowFlags(Qt.WindowType.Widget)  # embedded for the picture
        _feed_bar(bar, state, reason, done, eta, code, step, results)
        if cool:
            bar.set_cooldown(cool)
        bar.set_compact(False)
        lay.addWidget(bar, 0, Qt.AlignmentFlag.AlignHCenter)
        bars.append(bar)
    return Built(host, checks=[_check_bar_fill(host, bars)], trim=False)


def s_minibar_real(st: Stage) -> Built:
    from autopress.ui.minibar import MiniBar

    bar = MiniBar(st.ctx)
    state, reason, done, eta, code, step, results, _cool = _bar_moments(st)[0]
    _feed_bar(bar, state, reason, done, eta, code, step, results)
    return Built(bar, trim=False)


def s_countdown(st: Stage) -> Built:
    from autopress.ui.overlays_geom import ScreenGeom
    from autopress.ui.overlays_widgets import CountdownWidget
    from autopress.ui.run_actions import countdown_hint

    host = _Backdrop.make(qimage(st.page.windowed(st.scale, COUNTDOWN_WINDOW_AT), st.scale))
    cw = CountdownWidget(ScreenGeom((0, 0, SCREEN_W, SCREEN_H), st.scale), countdown_hint(st.ctx), (0, 0))
    cw.set_value(3)
    _overlay_child(host, cw)
    return Built(host, (SCREEN_W, SCREEN_H), checks=[_check_not_flat], trim=False)


def s_marks(st: Stage) -> Built:
    from autopress.runner.preview import preview_profile
    from autopress.ui.overlays_geom import ScreenGeom
    from autopress.ui.overlays_widgets import MarksOverlay

    host = _Backdrop.make(qimage(st.page.screen(st.scale), st.scale))
    marks = preview_profile(st.profile, HWND_BROWSER, backend=DemoBackend(st.world, st.page, st.scale))
    _overlay_child(host, MarksOverlay(ScreenGeom((0, 0, SCREEN_W, SCREEN_H), st.scale), marks))

    def extras() -> list[dict[str, Any]]:
        out = []
        for m in marks:  # mark rects are physical = PNG pixels (the demo monitor starts at 0, 0)
            x, y, w, h = (v / st.scale for v in m.rect)
            item = {"class": "mark", "text": m.label, "step": m.step_index + 1, "ok": m.ok, "kind": str(m.kind)}
            if w <= 1 and h <= 1:  # a point: the painted ring, and the point itself
                item["point"] = [m.rect[0], m.rect[1]]
                x, y, w, h = x - 16, y - 16, 32, 32
            out.append({**item, "logical": [x, y, w, h]})
        return out

    return Built(host, (SCREEN_W, SCREEN_H), extras=extras, trim=False)


def s_picker(st: Stage) -> Built:
    from PyQt6.QtCore import QPointF

    from autopress.ui.overlays import ScreenPicker
    from autopress.ui.overlays_geom import ScreenGeom
    from autopress.ui.overlays_widgets import PickerOverlay

    p = st.profile
    first = st.ctx.queue.runnable(game_key=p.game_key())[0].code
    ocr = next(s for s in p.steps if s.type is StepType.OCR_CHECK)
    picker = ScreenPicker()
    picker.kind = "region"
    # the step editor's instruction for the result region (step_forms.StepForm.instruction)
    picker.instruction = ocr.display_title() if (ocr.label or ocr.label_en) else _tr(
        "框出結果訊息出現的範圍", "Drag around where the result message appears")
    picker.target_rect = tuple(round(v * st.scale) for v in CLIENT)
    shot = st.page.bgra(st.scale, first, _demo("兌換成功，獎勵已寄至信箱"), "success")  # after a test redeem
    ov = PickerOverlay(picker, ScreenGeom((0, 0, SCREEN_W, SCREEN_H), st.scale), shot)
    rx, ry, rw, rh = st.page.layout.result_region
    ov.drag_start, ov.cursor_local = QPointF(rx - 4, ry - 4), QPointF(rx + rw + 4, ry + rh + 4)
    st.keep.append(picker)

    def extras() -> list[dict[str, Any]]:
        return [{"class": "selection", "text": picker.instruction, "logical": [rx - 4, ry - 4, rw + 8, rh + 8]},
                {"class": "target_window", "text": "", "logical": list(CLIENT)}]

    return Built(ov, (SCREEN_W, SCREEN_H), extras=extras, trim=False)


def s_history(st: Stage) -> Built:
    from autopress.ui.history_page import HistoryPage

    st.attach_evidence()

    def times(_img: Any) -> str | None:
        bad = [r.code for r in st.ctx.history.records() if not (r.started_at or r.finished_at)]
        return f"records without a time: {bad}" if bad else None

    return Built(HistoryPage(st.ctx), PAGE_SIZE, checks=[times])


def s_evidence(st: Stage) -> Built:
    from autopress.ui.history_page import EvidenceDialog

    st.attach_evidence()
    rec = next(r for r in reversed(st.ctx.history.records()) if r.status is CodeStatus.SUCCESS and r.evidence_path)
    return Built(EvidenceDialog(rec, st.home / rec.evidence_path), trim=False)


def s_settings(st: Stage) -> Built:
    from autopress.ui.settings_page import SettingsPage

    w = SettingsPage(st.ctx)
    return Built(w, PAGE_SIZE, checks=[_check_theme_control(w), _check_monitors])


def s_help(st: Stage) -> Built:
    from autopress.ui.help_page import HelpPage

    return Built(HelpPage(st.ctx), PAGE_SIZE, checks=[_check_monitors])


def s_welcome(st: Stage) -> Built:
    from autopress.ui.welcome import WelcomeDialog

    w = WelcomeDialog(st.ctx)
    return Built(w, checks=[_check_theme_control(w)], trim=False)


SCREENS: list[Screen] = [
    Screen("main", "Main window on the Codes page: 12 demo codes, sidebar badges, status bar with the found target", s_main),
    Screen("main_empty", "First start at the minimum window size: no profile and no codes yet", s_main_empty, empty=True),
    Screen("codes", "Codes page: the queue with sources, OCR confidence, statuses and result messages", s_codes),
    Screen("codes_selected", "Codes page with the two needs-review codes selected (bulk actions enabled)", s_codes_selected),
    Screen("codes_running", "Codes page during the demo run: codes 1-2 done, code 3 running, rows locked", s_codes_running),
    Screen("codes_empty", "Codes page without codes or profile (empty state)", s_codes_empty, empty=True),
    Screen("paste", "Paste dialog: codes found in a chat message, one already queued", s_paste),
    Screen("ocr_review", "OCR review of a stream screenshot: three codes, one unsure character", s_ocr_review),
    Screen("profiles", "Profiles page: the demo web-redeem profile, target found, setup complete", s_profiles),
    Screen("profiles_steps", "Profiles page scrolled to the steps: step 3 (type the code) in the editor", s_profiles_steps),
    Screen("profiles_missing", "Profiles page with a missing click position and no window-title keyword (checklist)",
           s_profiles_missing),
    Screen("gallery", "Profiles page on first start: the template gallery", s_gallery, empty=True),
    Screen("import_card", "Import card of a profile file a friend shared (what it will do)", s_import_card),
    Screen("window_picker", "Choose-window dialog: the demo desktop's windows, the demo browser selected", s_window_picker),
    Screen("wizard_position", "Setup wizard 1/4: record the click position of the code box", s_wizard_position),
    Screen("wizard_close", "Setup wizard 3/4: how to close the result popup", s_wizard_close),
    Screen("wizard_test", "Setup wizard 4/4: test one code with the first queued code", s_wizard_test),
    Screen("run_idle", "Run page before the first run: what will run and the pre-flight check", s_run_idle),
    Screen("run_preflight", "Run page while the redeem page is not open: a blocking pre-flight problem", s_run_preflight),
    Screen("run_running", "Run page during the demo run: 2 of 4 done, code 3 at its click step, live log", s_run_running),
    Screen("run_attention", "Run page paused on an unrecognised result: the decision card for code 3", s_run_attention),
    Screen("run_summary", "Run page after the demo run: summary, the run's log, nothing left to run", s_run_summary),
    Screen("sheet", "Pre-flight sheet shown on Start: a warning to acknowledge (the profile has not passed a test)",
           s_sheet),
    Screen("minibar", "Mini bar in three moments of the demo run: running, paused (focus lost), cool-down", s_minibar),
    Screen("minibar_real", "The mini bar window itself (running, as on the desktop)", s_minibar_real),
    Screen("countdown", "Start countdown over the demo redeem page, with the emergency-stop corner", s_countdown),
    Screen("marks", "Preview of the recorded positions over the demo redeem page", s_marks),
    Screen("picker", "Region picker over the frozen redeem page: dragging around the result message", s_picker),
    Screen("history", "History page: six attempts with times and evidence thumbnails", s_history),
    Screen("evidence", "Evidence viewer: the result area saved for the successful code", s_evidence),
    Screen("settings", "Settings page (top): language, appearance, safety", s_settings),
    Screen("help", "Help page (top): what AutoPress is and the table of contents", s_help),
    Screen("welcome", "Welcome dialog: language, appearance and the principles", s_welcome),
]


def QApplicationProcess(seconds: float = 0.0) -> None:  # noqa: N802 - reads like the Qt call it wraps
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    end = time.monotonic() + seconds
    while True:
        app.processEvents()
        if time.monotonic() >= end:
            break
        time.sleep(0.02)


# =============================================================================== self-checks


def _check_theme_control(w: Any) -> Callable[[Any], str | None]:
    def check(_img: Any) -> str | None:
        from autopress.ui import theme

        seg = getattr(w, "theme_seg", None)
        if seg is None:
            return None
        want = [ThemeName.DARK, ThemeName.LIGHT, ThemeName.SYSTEM].index(ThemeName(theme.current_theme()))
        got = seg.currentIndex()
        return None if got == want else f"Appearance shows option {got}, the picture is theme option {want}"
    return check


def _check_history_badge(st: Stage, w: Any) -> Callable[[Any], str | None]:
    def check(_img: Any) -> str | None:
        from PyQt6.QtWidgets import QWidget

        n = str(len(st.ctx.history.records()))
        badges = [c.badge() for c in w.findChildren(QWidget) if callable(getattr(c, "badge", None))]
        if not badges:
            return None  # no badge API (any more): nothing to compare
        return None if n in badges else f"no sidebar badge shows the {n} history records (badges {badges})"
    return check


def _check_monitors(_img: Any) -> str | None:
    from autopress.ui.shell_common import monitor_rects

    got = [tuple(r) for r in monitor_rects()]
    want = [m.rect for m in demo_monitors()]
    return None if got == want else "the monitor list is not the demo layout"


def _check_not_flat(img: Any) -> str | None:
    from PyQt6.QtGui import QColor

    colors = {QColor(img.pixel(x, y)).name() for x in range(10, img.width(), max(1, img.width() // 16))
              for y in range(10, img.height(), max(1, img.height() // 12))}
    return None if len(colors) > 4 else "the overlay sits on a flat background"


def _check_bar_fill(host: Any, bars: list[Any]) -> Callable[[Any], str | None]:
    def check(img: Any) -> str | None:
        from PyQt6.QtCore import QPoint
        from PyQt6.QtGui import QColor
        from PyQt6.QtWidgets import QFrame

        from autopress.ui import theme

        want = theme.color("overlay")
        dpr = img.devicePixelRatio() or 1.0
        bad = []
        for n, bar in enumerate(bars, 1):
            frame = bar.findChild(QFrame, "MiniBar") or next(iter(bar.findChildren(QFrame)), None)
            if frame is None:
                continue
            o = frame.mapTo(host, QPoint(0, 0))
            pts = [(o.x() + frame.width() // 2, o.y() + frame.height() - 5), (o.x() + 6, o.y() + frame.height() // 2)]
            ok = False
            for x, y in pts:
                c = QColor(img.pixel(round(x * dpr), round(y * dpr)))
                if max(abs(c.red() - want.red()), abs(c.green() - want.green()), abs(c.blue() - want.blue())) <= 8:
                    ok = True
            if not ok:
                bad.append(n)
        return f"bar(s) {bad}: the card is not filled with the theme 'overlay' colour" if bad else None
    return check


# =============================================================================== privacy


def private_needles(extra_paths: list[str] = ()) -> list[tuple[str, re.Pattern[str]]]:
    """(kind, pattern) of text that must never appear in a picture: this PC's profile folder,
    temp folder and data folders (both slash styles), and the computer name."""
    out: list[tuple[str, re.Pattern[str]]] = []

    def add_path(kind: str, value: str | None) -> None:
        v = str(value or "").rstrip("\\/")
        if len(v) < 6:
            return
        for form in {v, v.replace("\\", "/"), v.replace("/", "\\")}:
            out.append((kind, re.compile(re.escape(form), re.IGNORECASE)))

    add_path("profile folder", os.environ.get("USERPROFILE") or str(Path.home()))
    add_path("temp folder", tempfile.gettempdir())
    for p in extra_paths:
        add_path("data folder", p)
    comp = os.environ.get("COMPUTERNAME", "")
    if len(comp) >= 3:
        out.append(("computer name", re.compile(rf"(?<![\w-]){re.escape(comp)}(?![\w-])", re.IGNORECASE)))
    return out


def privacy_problems(texts: list[str], needles: list[tuple[str, re.Pattern[str]]]) -> list[str]:
    """Kinds of private text found (never the text itself: the report is a file too)."""
    found = []
    for kind, pat in needles:
        if any(pat.search(t) for t in texts if t) and kind not in found:
            found.append(kind)
    return found


def _texts_of(wdg: Any) -> list[str]:
    from PyQt6.QtWidgets import QAbstractButton, QComboBox, QLabel, QLineEdit, QPlainTextEdit, QTextEdit

    out = [wdg.toolTip(), wdg.accessibleName(), wdg.windowTitle()]
    if isinstance(wdg, (QLabel, QAbstractButton)):
        out.append(wdg.text())
    elif isinstance(wdg, QLineEdit):
        out += [wdg.text(), wdg.placeholderText()]
    elif isinstance(wdg, QComboBox):
        out += [wdg.itemText(i) for i in range(wdg.count())]
    elif isinstance(wdg, (QPlainTextEdit, QTextEdit)):
        out.append(wdg.toPlainText())
    return out


def _column_count(model: Any) -> int:
    try:
        return int(model.columnCount())
    except TypeError:  # QAbstractListModel: columnCount() is private in PyQt6
        return 1


def all_texts(top: Any) -> list[str]:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QAbstractItemView, QWidget

    texts: list[str] = []
    for wdg in [top, *top.findChildren(QWidget)]:
        texts += _texts_of(wdg)
        if isinstance(wdg, QAbstractItemView) and wdg.model() is not None:
            m = wdg.model()
            for row in range(min(m.rowCount(), 300)):
                for col in range(_column_count(m)):
                    for role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
                        v = m.data(m.index(row, col), role)
                        if isinstance(v, str):
                            texts.append(v)
    return texts


def scrub_data_folder(top: Any, home: Path) -> None:
    """The Settings data-folder line shows the throw-away folder: show a demo path instead."""
    from PyQt6.QtWidgets import QLabel, QLineEdit, QWidget

    forms = {str(home), str(home.resolve()), str(home).replace("\\", "/"), str(home.resolve()).replace("\\", "/")}
    for wdg in [top, *top.findChildren(QWidget)]:
        if isinstance(wdg, (QLabel, QLineEdit)):
            text = wdg.text()
            for f in forms:
                if f and f.casefold() in text.casefold():
                    text = re.sub(re.escape(f), DEMO_DATA_DIR.replace("\\", "\\\\"), text, flags=re.IGNORECASE)
            if text != wdg.text():
                wdg.setText(text)
        tip = wdg.toolTip()
        for f in forms:
            if f and f.casefold() in tip.casefold():
                wdg.setToolTip(re.sub(re.escape(f), DEMO_DATA_DIR.replace("\\", "\\\\"), tip, flags=re.IGNORECASE))


# =============================================================================== layout helpers


def _inside_scroll_area(wdg: Any, top: Any) -> bool:
    from PyQt6.QtWidgets import QAbstractScrollArea

    p = wdg.parentWidget()
    while p is not None and p is not top:
        if isinstance(p, QAbstractScrollArea):
            return True
        p = p.parentWidget()
    return False


def _row_height(view: Any) -> int:
    m = view.model()
    if m is None or m.rowCount() == 0:
        return 0
    h = view.sizeHintForRow(0) if hasattr(view, "sizeHintForRow") else 0
    vh = getattr(view, "verticalHeader", None)
    if vh is not None and callable(vh) and vh() is not None:
        h = vh().sectionSize(0) or h
    return int(h)


def cut_rows(top: Any) -> list[str]:
    """Item views (outside scroll areas) whose last visible row is cut by the bottom edge."""
    from PyQt6.QtWidgets import QAbstractItemView

    out = []
    for view in top.findChildren(QAbstractItemView):
        if not view.isVisibleTo(top) or _inside_scroll_area(view, top):
            continue
        h, n = _row_height(view), view.model().rowCount() if view.model() else 0
        vh = view.viewport().height()
        if h > 4 and n * h > vh and vh % h:
            out.append(f"{type(view).__name__}: the last row shows {vh % h} of {h} px")
    return out


def _row_trim(top: Any) -> int:
    from PyQt6.QtWidgets import QAbstractItemView

    best = 0
    for view in top.findChildren(QAbstractItemView):
        if not view.isVisibleTo(top) or _inside_scroll_area(view, top):
            continue
        h, n = _row_height(view), view.model().rowCount() if view.model() else 0
        vh = view.viewport().height()
        if h > 4 and n * h > vh:
            best = max(best, vh % h)
    return best


def _atoms(content: Any, vp: Any) -> list[tuple[int, int]]:
    """(top, bottom) in viewport coordinates of everything that must not be sliced: leaf
    widgets, text widgets, single lines of word-wrapped labels and item-view rows."""
    from PyQt6.QtCore import QPoint
    from PyQt6.QtGui import QFontMetrics
    from PyQt6.QtWidgets import QAbstractButton, QAbstractItemView, QLabel, QScrollBar, QWidget

    out: list[tuple[int, int]] = []
    views = [v for v in content.findChildren(QAbstractItemView) if v.isVisibleTo(content)]
    for wdg in content.findChildren(QWidget):
        if not wdg.isVisibleTo(content) or isinstance(wdg, QScrollBar):
            continue
        if any(v is not wdg and v.isAncestorOf(wdg) for v in views):
            continue  # inside an item view: its rows count instead
        y0 = wdg.mapTo(vp, QPoint(0, 0)).y()
        if isinstance(wdg, QAbstractItemView):
            m, inner = wdg.model(), wdg.viewport().mapTo(vp, QPoint(0, 0)).y()
            out.append((y0, inner))  # frame + header
            rows = m.rowCount() if m else 0
            for row in range(rows):
                r = wdg.visualRect(m.index(row, 0))
                if r.height() > 0:
                    out.append((inner + r.top(), inner + r.bottom()))
            if not rows:  # an empty view may paint a placeholder text anywhere on its viewport
                out.append((inner, inner + wdg.viewport().height() - 1))
            continue
        kids = [c for c in wdg.findChildren(QWidget) if c.isVisibleTo(wdg) and c.parentWidget() is wdg]
        if isinstance(wdg, QLabel) and wdg.wordWrap() and wdg.text():
            ls = QFontMetrics(wdg.font()).lineSpacing()
            cr = wdg.contentsRect()
            if ls > 0 and cr.height() > 2 * ls:
                for k in range(cr.height() // ls + 1):
                    t = y0 + cr.top() + k * ls
                    out.append((t, min(t + ls - 1, y0 + cr.bottom())))
                continue
        if not kids or isinstance(wdg, (QLabel, QAbstractButton)):
            out.append((y0, y0 + wdg.height() - 1))
    return out


def _no_orphan_heading(content: Any, vp: Any, atoms: list[tuple[int, int]], cut: int,
                       clear_cut: Callable[[int], int], lowest: int) -> int:
    """``cut`` moved above a heading (a 'title' or 'strong' label) that would otherwise be the last
    whole element of the picture, without any of its text - and above a divider left right on top
    of it. ``lowest``: the highest allowed cut (the most that may be trimmed)."""
    from PyQt6.QtCore import QPoint
    from PyQt6.QtWidgets import QFrame, QLabel

    heads = []
    for lb in content.findChildren(QLabel):
        if lb.isVisibleTo(content) and lb.property("role") in ("title", "strong") and lb.text():
            t = lb.mapTo(vp, QPoint(0, 0)).y()
            heads.append((t, t + lb.height() - 1))
    rules = [f.mapTo(vp, QPoint(0, 0)).y() for f in content.findChildren(QFrame)
             if f.isVisibleTo(content) and f.property("role") == "divider"]
    for t, b in sorted(heads, reverse=True):
        if b >= cut:
            continue
        if any(b < a and bb < cut for a, bb in atoms):
            break  # text follows this heading inside the picture
        new = clear_cut(t)
        while True:  # a divider directly above the heading goes too
            above = [bb for a, bb in atoms if bb < new]
            last = max(above) if above else -1
            rule = next((r for r in rules if r <= last <= r + 1), None)
            if rule is None:
                break
            new = clear_cut(rule)
        return new if new >= lowest else cut
    return cut


def _scroll_trim(top: Any, max_trim: int) -> int:
    """How much to cut off the bottom so the main scroll area ends below a whole element."""
    from PyQt6.QtCore import QPoint
    from PyQt6.QtWidgets import QScrollArea

    from PyQt6.QtWidgets import QWidget

    for sa in top.findChildren(QScrollArea):
        if not sa.isVisibleTo(top) or _inside_scroll_area(sa, top) or sa.widget() is None:
            continue
        if sa.verticalScrollBar().maximum() <= 0:
            continue
        vp = sa.viewport()
        gap = top.height() - vp.mapTo(top, QPoint(0, vp.height())).y()
        if not 0 <= gap <= 64:
            continue  # not the area that grows and shrinks with the picture's height
        vh = vp.height()
        atoms = [(a, b) for a, b in _atoms(sa.widget(), vp) if b >= 0 and a < vh]

        def clear_cut(y: int) -> int:
            while True:  # move up until no element spans the line
                crossing = [a for a, b in atoms if a < y <= b]
                if not crossing:
                    break
                y = min(crossing)
            above = [b for a, b in atoms if b < y]
            return min(y, (max(above) + 1 + 12) if above else y)

        cut = clear_cut(vh)
        content = sa.widget()
        cut = _no_orphan_heading(content, vp, atoms, cut, clear_cut, vh - max_trim)
        cards = [c for c in content.children() if isinstance(c, QWidget) and c.isVisibleTo(content)]
        for card in cards:
            ct = card.mapTo(vp, QPoint(0, 0)).y()
            cb = ct + card.height() - 1
            if ct < vh <= cb and vh - ct < min(120, card.height() // 2):
                cut2 = clear_cut(ct)  # a card barely started at the bottom (a lone heading) goes too
                if vh - cut2 <= max_trim:
                    cut = min(cut, cut2)
                break
            if ct < cut <= cb < vh:
                cut = min(vh, cb + 1 + 12)  # keep a card's bottom edge when it fits
                break
        for card in cards:  # a cut in a card's bottom padding (12 px under its last line) keeps its border
            ct = card.mapTo(vp, QPoint(0, 0)).y()
            cb = ct + card.height() - 1
            if ct < cut <= cb + 1 and cb + 1 - cut <= 24 and cb + 1 + 12 <= vh:
                cut = cb + 1 + 12
        trim = vh - cut
        return trim if 0 < trim <= max_trim else 0
    return 0


def trim_to_boundaries(top: Any) -> int:
    """Shrink a page so its table ends on a row boundary, else its scroll area below a whole
    element (no half rows or sliced lines at the bottom). Returns the pixels removed."""
    removed = 0
    for _ in range(2):
        # at most 15 %: enough for a cut row or line; a bigger cut would drop whole cards
        trim = _row_trim(top) or (_scroll_trim(top, int(top.height() * 0.15)) if not removed else 0)
        if trim <= 0:
            break
        top.resize(top.width(), top.height() - trim)
        removed += trim
        QApplicationProcess(0.15)
    return removed


# =============================================================================== geometry JSON


def _plain(text: str) -> str:
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QTextDocument

    if text and Qt.mightBeRichText(text):
        doc = QTextDocument()
        doc.setHtml(text)
        return doc.toPlainText()
    return text


def _visible_text(wdg: Any) -> str:
    from PyQt6.QtWidgets import (
        QAbstractButton,
        QAbstractSpinBox,
        QComboBox,
        QLabel,
        QLineEdit,
        QPlainTextEdit,
        QTextEdit,
    )

    if isinstance(wdg, QLabel):
        return "" if wdg.pixmap() is not None and not wdg.pixmap().isNull() else _plain(wdg.text())
    if isinstance(wdg, QAbstractButton):
        return wdg.text()
    if isinstance(wdg, QLineEdit):
        return wdg.text() or wdg.placeholderText()
    if isinstance(wdg, QComboBox):
        return wdg.currentText()
    if isinstance(wdg, QAbstractSpinBox):
        return wdg.text()
    if isinstance(wdg, (QPlainTextEdit, QTextEdit)):
        return wdg.toPlainText()[:300]
    return ""


def _visible_rect(wdg: Any, top: Any) -> Any:
    from PyQt6.QtCore import QPoint, QRect

    r = QRect(wdg.mapTo(top, QPoint(0, 0)), wdg.size())
    p = wdg.parentWidget()
    while p is not None and p is not top and not r.isEmpty():
        r = r.intersected(QRect(p.mapTo(top, QPoint(0, 0)), p.size()))
        p = p.parentWidget()
    return r.intersected(top.rect())


def _px(r: Any, dpr: float) -> list[int]:
    x0, y0 = round(r.x() * dpr), round(r.y() * dpr)
    return [x0, y0, round((r.x() + r.width()) * dpr) - x0, round((r.y() + r.height()) * dpr) - y0]


def geometry(top: Any, dpr: float, extras: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Visible child widgets (with text, accessibleName or objectName, and item views with their
    rows and header sections) in PNG pixels."""
    from PyQt6.QtCore import QPoint, QRect, Qt
    from PyQt6.QtWidgets import QAbstractItemView, QScrollBar, QWidget

    items: list[dict[str, Any]] = []
    ids: dict[int, int] = {}

    def parent_id(wdg: Any) -> int | None:
        p = wdg.parentWidget()
        while p is not None:
            if id(p) in ids:
                return ids[id(p)]
            if p is top:
                return None
            p = p.parentWidget()
        return None

    for wdg in [top, *top.findChildren(QWidget)]:
        if wdg is not top and (not wdg.isVisibleTo(top) or isinstance(wdg, QScrollBar)
                               or wdg.objectName().startswith("qt_")):
            continue
        text, acc, name = _visible_text(wdg), wdg.accessibleName(), wdg.objectName()
        view = isinstance(wdg, QAbstractItemView)
        if wdg is not top and not (text or acc or name or view):
            continue
        r = _visible_rect(wdg, top)
        if r.isEmpty():
            continue
        entry = {"id": len(items), "parent": parent_id(wdg), "objectName": name, "class": type(wdg).__name__,
                 "text": text, "accessibleName": acc, "rect": _px(r, dpr)}
        ids[id(wdg)] = entry["id"]
        items.append(entry)
        if not view or wdg.model() is None:
            continue
        m, vp = wdg.model(), wdg.viewport()
        vis = _visible_rect(vp, top)
        cols = [c for c in range(_column_count(m)) if not (hasattr(wdg, "isColumnHidden") and wdg.isColumnHidden(c))]
        header = wdg.horizontalHeader() if hasattr(wdg, "horizontalHeader") else (
            wdg.header() if hasattr(wdg, "header") else None)
        if header is not None and header.isVisibleTo(top):
            for c in cols:
                x0 = header.sectionViewportPosition(c)
                hr = QRect(header.mapTo(top, QPoint(x0, 0)),
                           header.mapTo(top, QPoint(x0 + header.sectionSize(c) - 1, header.height() - 1))
                           ).intersected(_visible_rect(header, top))
                if not hr.isEmpty():
                    items.append({"id": len(items), "parent": entry["id"], "objectName": "", "class": "header",
                                  "text": str(m.headerData(c, Qt.Orientation.Horizontal) or ""), "accessibleName": "",
                                  "rect": _px(hr, dpr), "column": c})
        for row in range(m.rowCount()):
            first = wdg.visualRect(m.index(row, cols[0] if cols else 0))
            last = wdg.visualRect(m.index(row, cols[-1] if cols else 0))
            band = first.united(last)
            if band.bottom() < 0:
                continue
            if band.top() > vp.height():
                break
            rr = QRect(vp.mapTo(top, band.topLeft()), band.size()).intersected(vis)
            if rr.isEmpty():
                continue
            cells = [m.data(m.index(row, c), Qt.ItemDataRole.DisplayRole) for c in cols]
            items.append({"id": len(items), "parent": entry["id"], "objectName": "", "class": "row",
                          "text": " | ".join(str(v) for v in cells if isinstance(v, (str, int, float)) and str(v)),
                          "accessibleName": "", "rect": _px(rr, dpr), "row": row})
    for ex in extras:
        x, y, w, h = ex.pop("logical")
        items.append({"id": len(items), "parent": None, "objectName": "", **ex,
                      "rect": _px(QRect(round(x), round(y), max(1, round(w)), max(1, round(h))), dpr)})
    return items


# =============================================================================== the run


def capture_screen(screen: Screen, opts: argparse.Namespace, world: DemoWorld, out: Path, tag: str,
                   report: list[str], homes: list[Path]) -> bool:
    from PyQt6.QtCore import Qt

    from tools.snap_widget import clipped_labels

    world.reset()
    st = Stage(opts, world, empty=screen.empty)
    homes.append(st.home)
    built = screen.build(st)
    w = built.widget
    try:
        w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        if built.size != (0, 0):
            w.resize(*built.size)
        w.show()
        QApplicationProcess(SETTLE_S)
        if built.after_show is not None:
            built.after_show()
            QApplicationProcess(0.5)
        removed = trim_to_boundaries(w) if built.trim else 0
        scrub_data_folder(w, st.home)
        found = privacy_problems(all_texts(w), private_needles([str(h) for h in homes]))
        if found:
            report.append(f"{screen.name}: NOT WRITTEN - private text in the picture ({', '.join(found)})")
            return False
        img = w.grab()
        path = out / f"{screen.name}_{tag}.png"
        if not img.save(str(path), "PNG"):
            report.append(f"{screen.name}: SAVE FAILED {path.name}")
            return False
        qimg = img.toImage()
        qimg.setDevicePixelRatio(img.devicePixelRatio())
        line = f"{screen.name}: ok {img.width()}x{img.height()} px ({w.width()}x{w.height()} logical)"
        if removed:
            line += f", trimmed {removed} px at the bottom"
        report.append(line)
        report += [f"  {c}" for c in clipped_labels(w)]
        report += [f"  cut row: {c}" for c in cut_rows(w)] if built.trim else []
        for check in built.checks:
            try:
                problem = check(qimg)
            except Exception as exc:  # noqa: BLE001 - a broken check is reported, not fatal
                problem = f"check failed: {type(exc).__name__}: {exc}"
            if problem:
                report.append(f"  CHECK: {problem}")
        if opts.geometry:
            data = {"screen": screen.name, "about": screen.about, "png": path.name, "theme": opts.theme,
                    "scale": opts.scale, "lang": opts.lang, "png_size": [img.width(), img.height()],
                    "logical_size": [w.width(), w.height()], "device_pixel_ratio": img.devicePixelRatio(),
                    "widgets": geometry(w, img.devicePixelRatio(), built.extras() if built.extras else [])}
            texts = [str(e.get("text", "")) for e in data["widgets"]] + [str(e.get("accessibleName", ""))
                                                                       for e in data["widgets"]]
            if privacy_problems(texts, private_needles([str(h) for h in homes])):
                report.append("  geometry JSON NOT WRITTEN - private text")
            else:
                path.with_suffix(".json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                                                     encoding="utf-8")
        return True
    finally:
        w.hide()
        w.deleteLater()
        st.keep.clear()
        QApplicationProcess()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="AutoPress screenshots for the README and the user guide.")
    ap.add_argument("out", nargs="?", help="output folder")
    ap.add_argument("--theme", default="dark", choices=["dark", "light"])
    ap.add_argument("--scale", type=float, default=1.0, help="1.0, 1.25 or 1.5 (QT_SCALE_FACTOR)")
    ap.add_argument("--lang", default="zh-TW", choices=["zh-TW", "en"])
    ap.add_argument("--only", default="", help="comma-separated screen names")
    ap.add_argument("--geometry", action="store_true", help="also write a JSON of the visible widgets per PNG")
    ap.add_argument("--list", action="store_true", help="list the screens and exit")
    a = ap.parse_args(argv)
    if a.list:
        for s in SCREENS:
            print(f"{s.name:16} {s.about}")
        return 0
    if not a.out:
        ap.error("the output folder is required")
    names = [s.name for s in SCREENS]
    only = [n.strip() for n in a.only.split(",") if n.strip()]
    unknown = [n for n in only if n not in names]
    if unknown:
        ap.error(f"unknown screen(s) {', '.join(unknown)}; use --list")

    os.environ.pop("QT_QPA_PLATFORM", None)  # the real windows platform: offscreen has no real fonts
    if a.scale != 1.0:
        os.environ["QT_SCALE_FACTOR"] = str(a.scale)
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    session_home = Path(tempfile.mkdtemp(prefix="ap-guide-"))
    os.environ["AUTOPRESS_HOME"] = str(session_home)

    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([sys.argv[0]])
    from tests import ui_fallback

    ui_fallback.install()
    from autopress import i18n
    from autopress.ui import theme

    i18n.set_language(a.lang)
    world = DemoWorld()  # titles in the chosen language
    install_demo_environment(world)
    theme.apply_theme(app, a.theme)

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tag = f"{a.theme}_{int(round(a.scale * 100))}{'_en' if a.lang == 'en' else ''}"
    report: list[str] = [f"AutoPress guide capture - theme {a.theme}, scale {a.scale}, language {a.lang}"]
    homes: list[Path] = [session_home]
    failed = 0
    try:
        for screen in SCREENS:
            if only and screen.name not in only:
                continue
            try:
                if not capture_screen(screen, a, world, out, tag, report, homes):
                    failed += 1
            except Exception as exc:  # noqa: BLE001 - keep going, report it
                failed += 1
                report.append(f"{screen.name}: ERROR {type(exc).__name__}: {exc}")
                report.append(traceback.format_exc()[-1500:])
        done = sum(1 for s in SCREENS if not only or s.name in only)
        report.append(f"{done - failed} of {done} screens written, {failed} failed")
        text = "\n".join(report) + "\n"
        for _kind, pat in private_needles([str(h) for h in homes]):
            text = pat.sub("<private>", text)  # tracebacks may name temp paths
        (out / f"report_{tag}.txt").write_text(text, encoding="utf-8")
        print(text, end="")
    finally:
        for h in homes:
            shutil.rmtree(h, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
