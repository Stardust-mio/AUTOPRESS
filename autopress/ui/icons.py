# OWNED BY G5
"""Original 24x24 line icons (stroke 1.8, round caps) as inline SVG, rendered with QSvgRenderer
at the device pixel ratio and recoloured per theme (ICONS / icon_pixmap ported from
docs/research/scripts/ux/prototype.py; the extra icons are drawn in the same style for this
project). No third-party icon pack.

``bind(widget, name, color_token, size)`` sets a themed icon on a button or label and remembers
it, so ``theme.apply_theme`` re-colours it after a theme switch (``refresh_bound``).
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QByteArray, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QAbstractButton, QApplication, QLabel, QWidget

log = logging.getLogger(__name__)

ICON_NAMES: tuple[str, ...] = (
    # the 32 prototype icons
    "logo", "codes", "profiles", "run", "history", "settings", "help", "paste", "file", "image",
    "clipimage", "snip", "search", "more", "check", "x", "alert", "export", "trash", "pause",
    "stop", "play", "shield", "gauge", "keyboard", "window", "chevron", "moon", "drag", "flask",
    "skip", "clock",
    # new (G5 draws them in the same style)
    "plus", "minus", "edit", "copy", "arrow_up", "arrow_down", "refresh", "save", "import",
    "folder", "crosshair", "region", "info", "external", "expand", "target", "pointer",
    "text_search", "type", "keycap", "eye", "scan",
)
"""Every name below must exist in ICONS (models.StepType.icon / CodeSource.icon use them)."""

_DOT = '<circle cx="{x}" cy="{y}" r="{r}" fill="{{c}}" stroke="none"/>'

# "{c}" = the icon colour (for filled parts). Stroke colour and width come from the <svg> element.
ICONS: dict[str, str] = {
    # --- prototype icons (docs/research/scripts/ux/prototype.py) ---
    "logo": '<rect x="2" y="2" width="20" height="20" rx="6" fill="{c}" stroke="none"/>'
    '<path d="M7.5 8.5l3.5 3.5-3.5 3.5M13 15.5h4" stroke="#FFFFFF" stroke-width="2.2"/>',
    "codes": '<path d="M4 7.5A2.5 2.5 0 0 1 6.5 5h11A2.5 2.5 0 0 1 20 7.5V9a3 3 0 0 0 0 6v1.5a2.5 2.5 0 0 1-2.5 2.5h-11'
    'A2.5 2.5 0 0 1 4 16.5V15a3 3 0 0 0 0-6z"/><path d="M14.5 5.5v13" stroke-dasharray="2 2.4"/>',
    "profiles": '<rect x="3.5" y="3.5" width="7" height="7" rx="2"/><rect x="13.5" y="13.5" width="7" height="7" rx="2"/>'
    '<path d="M10.5 7h3.5a3 3 0 0 1 3 3v3.5"/>',
    "run": '<circle cx="12" cy="12" r="9"/><path d="M10 8.6v6.8l5.6-3.4z"/>',
    "history": '<path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1"/><path d="M3.5 4.5v4h4"/><path d="M12 7.5V12l3 2"/>',
    "settings": '<path d="M4 7h9M17 7h3M4 12h3M11 12h9M4 17h11M19 17h1"/>'
    '<circle cx="15" cy="7" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="17" r="2"/>',
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9.6 9.4a2.5 2.5 0 1 1 3.4 2.3c-.6.3-1 .8-1 1.5v.6"/>'
    '<circle cx="12" cy="16.9" r="1.1" fill="{c}" stroke="none"/>',
    "paste": '<rect x="5.5" y="4.5" width="13" height="16" rx="2"/><rect x="9" y="2.8" width="6" height="3.6" rx="1.2"/>'
    '<path d="M9 11h6M9 15h4"/>',
    "file": '<path d="M14 3.5H7.5a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2V8z"/><path d="M14 3.5V8h4.5"/>'
    '<path d="M9 12.5h6M9 16h4"/>',
    "image": '<rect x="3.5" y="5" width="17" height="14" rx="2.5"/><circle cx="9" cy="10" r="1.6"/>'
    '<path d="M20.5 15.5l-4.5-4.5-8.5 8"/>',
    "clipimage": '<rect x="5.5" y="4.5" width="13" height="16" rx="2"/><rect x="9" y="2.8" width="6" height="3.6" rx="1.2"/>'
    '<path d="M8.5 17l2.5-3 2 2 1.5-1.5 1.5 2.5"/><circle cx="10" cy="10.5" r="1"/>',
    "snip": '<path d="M4 8.5V5.5a1.5 1.5 0 0 1 1.5-1.5h3M15.5 4h3A1.5 1.5 0 0 1 20 5.5v3M20 15.5v3a1.5 1.5 0 0 1-1.5 1.5'
    'h-3M8.5 20h-3A1.5 1.5 0 0 1 4 18.5v-3"/><path d="M12 9v6M9 12h6"/>',
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4 4"/>',
    "more": _DOT.format(x=6, y=12, r=1.5) + _DOT.format(x=12, y=12, r=1.5) + _DOT.format(x=18, y=12, r=1.5),
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "x": '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
    "alert": '<path d="M12 4l9 15.5H3z"/><path d="M12 10v4"/><circle cx="12" cy="16.9" r="1.1" fill="{c}" stroke="none"/>',
    "export": '<path d="M12 4v11M7.5 10.5L12 15l4.5-4.5M5 19.5h14"/>',
    "trash": '<path d="M4.5 7h15M10 11v6M14 11v6M6.5 7l.9 11.5a2 2 0 0 0 2 1.8h5.2a2 2 0 0 0 2-1.8L17.5 7M9.5 7V4.5h5V7"/>',
    "pause": '<rect x="6.5" y="5" width="3.8" height="14" rx="1.3" fill="{c}" stroke="none"/>'
    '<rect x="13.7" y="5" width="3.8" height="14" rx="1.3" fill="{c}" stroke="none"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="2.5" fill="{c}" stroke="none"/>',
    "play": '<path d="M8 5.8v12.4L18 12z"/>',
    "shield": '<path d="M12 3.2l7.5 3v5.6c0 4.4-3.1 8-7.5 9.2-4.4-1.2-7.5-4.8-7.5-9.2V6.2z"/><path d="M9 12.2l2.2 2.2 4-4.2"/>',
    "gauge": '<path d="M4.5 17.5a8.5 8.5 0 1 1 15 0"/><path d="M12 13.5l3.8-3.8"/><circle cx="12" cy="13.5" r="1.3"/>',
    "keyboard": '<rect x="2.5" y="6" width="19" height="12" rx="2.5"/><path d="M6.5 10h1M10.5 10h1M14.5 10h1M8 14h8"/>',
    "window": '<rect x="3" y="4.5" width="18" height="15" rx="2.5"/><path d="M3 9h18"/><circle cx="6.3" cy="6.8" r=".5"/>',
    "chevron": '<path d="M7 10l5 5 5-5"/>',
    "moon": '<path d="M19.5 14.5A8 8 0 1 1 9.5 4.5a6.5 6.5 0 0 0 10 10z"/>',
    "drag": "".join(_DOT.format(x=x, y=y, r=1.4) for x in (9, 15) for y in (6, 12, 18)),
    "flask": '<path d="M9.5 3.5h5M10.5 3.5v5L5 18a1.8 1.8 0 0 0 1.6 2.6h10.8A1.8 1.8 0 0 0 19 18l-5.5-9.5v-5"/>'
    '<path d="M7.5 14.5h9"/>',
    "skip": '<path d="M6 6.5v11l8-5.5z"/><path d="M17.5 6.5v11"/>',
    "clock": '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    # --- new icons, same grid and stroke ---
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "minus": '<path d="M5 12h14"/>',
    "edit": '<path d="M4.5 19.5l1-4.2L15.6 5.2a2.1 2.1 0 0 1 3 0l.2.2a2.1 2.1 0 0 1 0 3L8.7 18.5z"/><path d="M13.6 7.2l3.2 3.2"/>',
    "copy": '<rect x="8.5" y="8.5" width="11.5" height="11.5" rx="2.2"/>'
    '<path d="M15.5 8.5V6.2a2.2 2.2 0 0 0-2.2-2.2H6.2A2.2 2.2 0 0 0 4 6.2v7.1a2.2 2.2 0 0 0 2.2 2.2h2.3"/>',
    "arrow_up": '<path d="M12 19.5v-15M6 10.5l6-6 6 6"/>',
    "arrow_down": '<path d="M12 4.5v15M6 13.5l6 6 6-6"/>',
    "refresh": '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3"/><path d="M19.5 4.5v4h-4"/>',
    "save": '<path d="M5.5 4.5h10.2l3.8 3.8v10.2a1.5 1.5 0 0 1-1.5 1.5h-12.5A1.5 1.5 0 0 1 4 18.5v-12.5A1.5 1.5 0 0 1 5.5 4.5z"/>'
    '<path d="M8 4.5v4.2h7V4.5M7.8 20v-6h8.4v6"/>',
    "import": '<path d="M12 3.5v10.5M7.8 9.8L12 14l4.2-4.2"/><path d="M4.5 14v3.5a2.5 2.5 0 0 0 2.5 2.5h10a2.5 2.5 0 0 0 2.5-2.5V14"/>',
    "folder": '<path d="M3.5 7.5a2 2 0 0 1 2-2h3.9l2.1 2.4h7a2 2 0 0 1 2 2v7.6a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>',
    "crosshair": '<circle cx="12" cy="12" r="6.8"/><path d="M12 2.8v4.4M12 16.8v4.4M2.8 12h4.4M16.8 12h4.4"/>'
    '<circle cx="12" cy="12" r="1.1" fill="{c}" stroke="none"/>',
    "region": '<rect x="4" y="5.5" width="16" height="13" rx="2" stroke-dasharray="3.2 2.6"/>'
    '<path d="M2.8 9V5.2a1.5 1.5 0 0 1 1.5-1.5H8"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5"/><circle cx="12" cy="7.7" r="1.1" fill="{c}" stroke="none"/>',
    "external": '<path d="M13.5 4.5h6v6M19.5 4.5L11 13"/>'
    '<path d="M17 14v4a2 2 0 0 1-2 2H6.5a2 2 0 0 1-2-2V9.5a2 2 0 0 1 2-2h4"/>',
    "expand": '<path d="M14.5 4.5h5v5M9.5 19.5h-5v-5M19.5 4.5l-6 6M4.5 19.5l6-6"/>',
    "target": '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/>'
    '<circle cx="12" cy="12" r="1.3" fill="{c}" stroke="none"/>',
    "pointer": '<path d="M6 3.8l11.8 6.6-5.1 1.6-2.2 5z"/><path d="M12.7 12l4.5 4.5"/>',
    "text_search": '<path d="M4 6h11M4 10.5h7M4 15h5"/><circle cx="15.5" cy="15" r="3.4"/><path d="M18 17.5l2.5 2.5"/>',
    "type": '<path d="M5 7.5V5h14v2.5M12 5v14.5M9 19.5h6"/>',
    "keycap": '<rect x="4" y="4" width="16" height="16" rx="3.5"/><path d="M8 16h8"/><path d="M9.5 12.5l2.5-5 2.5 5"/>',
    "eye": '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>',
    "scan": '<path d="M4 8.5V6a2 2 0 0 1 2-2h2.5M15.5 4H18a2 2 0 0 1 2 2v2.5M20 15.5V18a2 2 0 0 1-2 2h-2.5'
    'M8.5 20H6a2 2 0 0 1-2-2v-2.5"/><path d="M7.5 12h9"/><path d="M9 8.5h6M9 15.5h4"/>',
    # --- extras for the settings / help pages ---
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2.8v2M12 19.2v2M2.8 12h2M19.2 12h2M5.5 5.5l1.4 1.4'
    'M17.1 17.1l1.4 1.4M5.5 18.5l1.4-1.4M17.1 6.9l1.4-1.4"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.4 2.5 3.6 5.5 3.6 9s-1.2 6.5-3.6 9'
    'c-2.4-2.5-3.6-5.5-3.6-9S9.6 5.5 12 3z"/>',
    "monitor": '<rect x="3" y="4.5" width="18" height="12" rx="2"/><path d="M9 20h6M12 16.5V20"/>',
    "lock": '<rect x="5" y="10.5" width="14" height="10" rx="2.5"/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5"/>',
    "mouse": '<rect x="7" y="3.5" width="10" height="17" rx="5"/><path d="M12 7v3.5"/>',
    "database": '<ellipse cx="12" cy="6" rx="7" ry="2.6"/><path d="M5 6v12c0 1.4 3.1 2.6 7 2.6s7-1.2 7-2.6V6'
    'M5 12c0 1.4 3.1 2.6 7 2.6s7-1.2 7-2.6"/>',
    "book": '<path d="M12 6.5C10.2 5 7.6 4.5 4 4.8v13.4c3.6-.3 6.2.2 8 1.7 1.8-1.5 4.4-2 8-1.7V4.8c-3.6-.3-6.2.2-8 1.7z"/>'
    '<path d="M12 6.5v13.4"/>',
    "sparkle": '<path d="M12 3.5l1.9 5.1 5.1 1.9-5.1 1.9-1.9 5.1-1.9-5.1-5.1-1.9 5.1-1.9z"/><path d="M18.5 15.5v4M16.5 17.5h4"/>',
}

_cache: dict[tuple[str, str, int, float, float], QPixmap] = {}
_warned: set[str] = set()
_BOUND = "_apIcon"


def _hex(color: str | QColor) -> str:
    from . import theme

    return theme.color(color).name() if not isinstance(color, QColor) else QColor(color).name()


def _dpr() -> float:
    screen = QGuiApplication.primaryScreen() if QGuiApplication.instance() is not None else None
    return float(screen.devicePixelRatio()) if screen is not None else 1.0


def icon_pixmap(name: str, color: str, size: int = 18, stroke: float = 1.8) -> QPixmap:
    """Cached pixmap at the primary screen's dpr; ``color`` is a token or "#RRGGBB"."""
    if name not in ICONS:
        if name not in _warned:
            log.warning("unknown icon %r (using 'info')", name)
            _warned.add(name)
        name = "info"
    hexcolor = _hex(color)
    dpr = _dpr()
    key = (name, hexcolor, int(size), float(stroke), dpr)
    pm = _cache.get(key)
    if pm is None:
        body = ICONS[name].replace("{c}", hexcolor)
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{hexcolor}" '
               f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')
        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        side = max(1, round(size * dpr))
        pm = QPixmap(side, side)
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(p, QRectF(0, 0, size, size))
        p.end()
        _cache[key] = pm
    return pm


def icon(name: str, color_token: str = "text_secondary", size: int = 16) -> QIcon:
    """Icon in the colour of an active-theme token (or a literal "#RRGGBB"). The Disabled mode
    uses ``text_disabled``, so a disabled button's icon dims with its text (integration, G6 note)."""
    ic = QIcon(icon_pixmap(name, color_token, size))
    ic.addPixmap(icon_pixmap(name, "text_disabled", size), QIcon.Mode.Disabled)
    return ic


def app_icon() -> QIcon:
    """Window icon rendered from "logo" at 16-256 px."""
    ic = QIcon()
    for size in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        ic.addPixmap(icon_pixmap("logo", "#2F66F0", size))
    return ic


# =============================================================================== themed binding


def bind(widget: QWidget, name: str, color_token: str = "text_secondary", size: int = 16) -> None:
    """Set a themed icon on a QAbstractButton (icon) or QLabel (pixmap) and remember it, so it is
    re-coloured after a theme switch. ``name`` "" removes the icon."""
    widget.setProperty(_BOUND, f"{name}|{color_token}|{int(size)}" if name else None)
    _apply(widget, name, color_token, int(size))


def _apply(widget: QWidget, name: str, token: str, size: int) -> None:
    if isinstance(widget, QAbstractButton):
        widget.setIcon(icon(name, token, size) if name else QIcon())
        if name:
            widget.setIconSize(QSize(size, size))
    elif isinstance(widget, QLabel):
        if name:
            widget.setPixmap(icon_pixmap(name, token, size))
        else:
            widget.clear()


def refresh_bound(root: QWidget | None = None) -> int:
    """Re-render every icon set with bind() (all widgets, or ``root`` and its children) in the
    active theme's colours. Returns how many widgets were updated."""
    if root is not None:
        widgets = [root, *root.findChildren(QWidget)]
    elif QApplication.instance() is not None:
        widgets = QApplication.allWidgets()
    else:
        return 0
    n = 0
    for w in widgets:
        spec = w.property(_BOUND)
        if not spec:
            continue
        name, token, size = str(spec).split("|")
        _apply(w, name, token, int(size))
        n += 1
    return n
