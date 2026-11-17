# OWNED BY G5
"""Private helpers shared by G5's shell modules (main window, settings, help, welcome, app).

No widget imports here (avoids import cycles): headless detection, the Qt translator, theme
switching with the app-wide signal, opening folders, monitor rectangles and the failsafe-corner
description used by the status bar, the settings page and the help page.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import QLibraryInfo, QTranslator, QUrl
from PyQt6.QtGui import QDesktopServices, QGuiApplication

from ..i18n import get_language, tr
from ..models import Rect, ThemeName, failsafe_corners

if TYPE_CHECKING:
    from ..context import AppContext

log = logging.getLogger(__name__)

HEADLESS_PLATFORMS = ("offscreen", "minimal")
_translators: dict[str, QTranslator] = {}


def is_headless() -> bool:
    """True on Qt platforms nobody can see or click (``offscreen`` in tests): modal dialogs
    must not block there (nobody could answer them)."""
    app = QGuiApplication.instance()
    if app is None:
        return os.environ.get("QT_QPA_PLATFORM", "") in HEADLESS_PLATFORMS
    return QGuiApplication.platformName() in HEADLESS_PLATFORMS


def install_translator(app: QGuiApplication, lang: str | None = None) -> bool:
    """Qt's own strings (standard dialogs, context menus) in zh-TW: install qtbase_zh_TW when the
    language is zh-TW, remove it otherwise. Returns True when a translator is active."""
    lang = lang or get_language()
    old = _translators.pop("qtbase", None)
    if old is not None:
        app.removeTranslator(old)
    if lang != "zh-TW":
        return False
    tr_ = QTranslator(app)
    folder = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if not tr_.load("qtbase_zh_TW", folder):
        log.info("qtbase_zh_TW.qm not found in %s", folder)
        return False
    app.installTranslator(tr_)
    _translators["qtbase"] = tr_
    return True


def change_theme(ctx: AppContext, name: ThemeName | str, *, save: bool = True) -> str:
    """Apply a theme live (theme.apply_theme), store it in the settings and emit
    ``signals.theme_changed(resolved)``. Returns the resolved "dark" | "light"."""
    from PyQt6.QtWidgets import QApplication

    from . import theme

    value = ThemeName(str(getattr(name, "value", name)))
    app = QApplication.instance()
    resolved = theme.apply_theme(app, value) if app is not None else theme.resolve_theme(value)
    if save and ctx.settings.theme != value:
        ctx.settings.theme = value
        ctx.save_settings()
    ctx.signals.theme_changed.emit(resolved)
    return resolved


def open_folder(path: Path | str, create: bool = True) -> bool:
    """Open a folder (or, with ``create=False``, an existing file) with the shell; a missing
    folder is created first when ``create``."""
    p = Path(path)
    if create and not p.exists():
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    ok = QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))
    if not ok:
        log.warning("could not open %s", p)
    return ok


def monitor_rects() -> list[Rect]:
    """Physical monitor rects: win32.dpi.monitors() (G3); while that is unavailable, the Qt
    screens (origin in native pixels, size x devicePixelRatio)."""
    try:
        from ..win32 import dpi

        rects = [tuple(m.rect) for m in dpi.monitors()]
        if rects:
            return rects  # type: ignore[return-value]
    except Exception:  # noqa: BLE001 - G3 stub or no monitors: fall back to Qt
        pass
    out: list[Rect] = []
    if QGuiApplication.instance() is None:
        return out
    for s in QGuiApplication.screens():
        g = s.geometry()
        dpr = s.devicePixelRatio() or 1.0
        out.append((g.x(), g.y(), round(g.width() * dpr), round(g.height() * dpr)))
    return out


def failsafe_corner_text(rects: list[Rect] | None = None) -> str:
    """Which corner counts on this monitor layout (status-bar tooltip, settings hint)."""
    rects = monitor_rects() if rects is None else rects
    corners = failsafe_corners(rects)
    if len(rects) <= 1:
        return tr("把滑鼠推到螢幕最左上角，就會立刻緊急停止。",
                  "Push the mouse into the top-left corner of the screen to stop at once.")
    pts = "、".join(f"({x}, {y})" for x, y in corners)
    pts_en = ", ".join(f"({x}, {y})" for x, y in corners)
    left = min(r[0] for r in rects)
    if any(x == left for x, _y in corners) and left < 0:
        return tr(f"你有 {len(rects)} 個螢幕：要推到「最左邊那個螢幕」的左上角才算（座標 {pts}），"
                  "主螢幕的左上角不算。",
                  f"You have {len(rects)} screens: push the mouse into the top-left corner of the LEFT-most "
                  f"screen (at {pts_en}); the primary screen's corner does not count.")
    return tr(f"你有 {len(rects)} 個螢幕：算數的角落是 {pts}（桌面外側的左上角）。",
              f"You have {len(rects)} screens: the corners that count are {pts_en} (outer top-left corners).")
