"""AutoPress static UI prototype (research agent R3) - Codes page, mini run bar, empty state.

Renders a NON-functional mock of the AutoPress main window with the real ``windows`` platform
plugin (real fonts, real DPI) plus ``WA_DontShowOnScreen`` - nothing appears on the desktop and
the ``offscreen`` platform is never used (it has no real fonts).

    .venv/Scripts/python.exe docs/research/scripts/ux/prototype.py            # all PNGs, 100 %
    .venv/Scripts/python.exe docs/research/scripts/ux/prototype.py --scale 1.5 --theme dark
    .venv/Scripts/python.exe docs/research/scripts/ux/prototype.py --live --theme light

Everything an implementer may reuse lives at the top of this file: colour tokens (DARK / LIGHT),
type / spacing / radius scales, the original line icons (inline SVG, drawn for this project,
no third-party icon pack), ``build_qss`` and ``build_palette``.  The widgets below them are
mock-quality (no behaviour) but show how each component is meant to look.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from PyQt6.QtCore import QByteArray, QItemSelectionModel, QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QIcon,
    QLinearGradient,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
    QStandardItem,
    QStandardItemModel,
)
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

ROOT = Path(__file__).resolve().parents[4]  # .../AUTOPRESS
DEFAULT_OUT = ROOT / "docs" / "research" / "ux"

# =============================================================================== design tokens
# Colours are "#RRGGBB" or "#RRGGBBAA" (alpha LAST, CSS order).  Text tokens are checked
# against the surfaces they sit on (see contrast_report()).

DARK: dict[str, str] = {
    "name": "dark",
    # background layers (back -> front)
    "bg_app": "#0E1014",
    "bg_sidebar": "#12151A",
    "surface": "#171A20",  # cards
    "surface_raised": "#1E222A",  # buttons, inputs
    "surface_hover": "#262B34",
    "surface_inset": "#101317",  # segmented-control track
    "seg_active": "#272C36",  # selected segment
    "overlay": "#1C2027",  # menus, toasts, mini bar
    "nav_active": "#1D2230",
    "row_selected": "#1C2638",  # opaque, so double-painted selection never darkens
    "border": "#242933",
    "border_strong": "#333A46",
    # text
    "text": "#E7E9EE",
    "text_secondary": "#A9B1BE",
    "text_muted": "#848C9B",
    "text_disabled": "#5C6370",
    # accent
    "accent": "#6B93FF",
    "accent_fill": "#2F66F0",  # primary button fill, white text 4.9:1
    "accent_fill_hover": "#4275F5",
    "accent_fill_pressed": "#2556D6",
    "on_accent": "#FFFFFF",
    "accent_soft": "#6B93FF24",
    "accent_text": "#A3BDFF",
    "hover": "#FFFFFF0D",
    # semantic: base (icons, bars), soft (chip / banner fill), text (small text on soft)
    "success": "#3DD68C", "success_soft": "#3DD68C1F", "success_text": "#74E6AE",
    "warning": "#F5B544", "warning_soft": "#F5B5441C", "warning_text": "#FFCD70",
    "warning_border": "#F5B54459",
    "error": "#F87171", "error_soft": "#F871711F", "error_text": "#FF9D9D",
    "info": "#5CC8FF", "info_soft": "#5CC8FF1C", "info_text": "#93DAFF",
    "violet": "#A78BFA", "violet_soft": "#A78BFA24", "violet_text": "#C9BBFF",
    "orange": "#FB923C", "orange_soft": "#FB923C1F", "orange_text": "#FDBA80",
    "neutral": "#8A93A3", "neutral_soft": "#A9B1BE1A", "neutral_text": "#B7BECA",
    # misc
    "scrollbar": "#FFFFFF24",
    "scrollbar_hover": "#FFFFFF42",
    "shadow": "#000000B0",
    "backdrop_a": "#1B2433",
    "backdrop_b": "#2B1F33",
}

LIGHT: dict[str, str] = {
    "name": "light",
    "bg_app": "#F5F6F8",
    "bg_sidebar": "#ECEFF3",
    "surface": "#FFFFFF",
    "surface_raised": "#FFFFFF",
    "surface_hover": "#F1F3F6",
    "surface_inset": "#EEF1F4",
    "seg_active": "#FFFFFF",
    "overlay": "#FFFFFF",
    "nav_active": "#DFE6F5",
    "row_selected": "#EAF0FE",
    "border": "#E3E7EC",
    "border_strong": "#CDD3DB",
    "text": "#14181F",
    "text_secondary": "#4A5361",
    "text_muted": "#646D7C",
    "text_disabled": "#9AA2AE",
    "accent": "#2F66F0",
    "accent_fill": "#2F66F0",
    "accent_fill_hover": "#2A5BD8",
    "accent_fill_pressed": "#224CB8",
    "on_accent": "#FFFFFF",
    "accent_soft": "#2F66F01A",
    "accent_text": "#1E4FD0",
    "hover": "#0F172A0A",
    "success": "#16A34A", "success_soft": "#16A34A1A", "success_text": "#13773A",
    "warning": "#D97706", "warning_soft": "#F59E0B1F", "warning_text": "#8A3D0B",
    "warning_border": "#F59E0B66",
    "error": "#DC2626", "error_soft": "#DC26261A", "error_text": "#B41C1C",
    "info": "#0284C7", "info_soft": "#0284C71A", "info_text": "#075985",
    "violet": "#7C3AED", "violet_soft": "#7C3AED1A", "violet_text": "#6127C9",
    "orange": "#EA580C", "orange_soft": "#EA580C1A", "orange_text": "#A93A08",
    "neutral": "#64748B", "neutral_soft": "#64748B1A", "neutral_text": "#475569",
    "scrollbar": "#0F172A26",
    "scrollbar_hover": "#0F172A45",
    "shadow": "#0F172A40",
    "backdrop_a": "#DCE6F7",
    "backdrop_b": "#EFE3F3",
}

THEMES = {"dark": DARK, "light": LIGHT}
T: dict[str, str] = DARK  # active token set; read by every custom paintEvent

# type scale (px) - Microsoft JhengHei UI has Regular / Bold / Light only, so "semibold" == Bold
FONT_UI = ("Microsoft JhengHei UI", "Segoe UI")  # JhengHei UI's Latin glyphs follow Segoe UI
FONT_MONO = ("Consolas", "Cascadia Mono", "Courier New")  # codes: slashed zero, distinct 1/l/I
FONT_NUM = ("Segoe UI", "Microsoft JhengHei UI")  # numbers, with tabular figures
FS_DISPLAY, FS_TITLE, FS_BODY, FS_SMALL, FS_CAPTION, FS_MONO = 22, 15, 13, 12, 11, 14
SP = (0, 4, 8, 12, 16, 20, 24, 32, 40)  # spacing scale, use SP[n]
R_SM, R_MD, R_LG, R_XL = 4, 8, 12, 14  # radii: keycap/chip-inner, control, card, floating
CONTROL_H = 32  # every button / input / combo; table rows 42; nav items 38; chips 22; keycaps 20


def qc(value: str) -> QColor:
    text = value.lstrip("#")
    r, g, b = int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)
    a = int(text[6:8], 16) if len(text) >= 8 else 255
    return QColor(r, g, b, a)


def css(value: str) -> str:
    c = qc(value)
    return c.name() if c.alpha() == 255 else f"rgba({c.red()}, {c.green()}, {c.blue()}, {c.alpha()})"


def font(px: int = FS_BODY, *, bold: bool = False, families: tuple[str, ...] = FONT_UI, tnum: bool = False) -> QFont:
    f = QFont()
    f.setFamilies(list(families))
    f.setPixelSize(px)
    if bold:
        f.setWeight(QFont.Weight.Bold)
    if tnum:
        f.setFeature(QFont.Tag("tnum"), 1)
    return f


# =============================================================================== icons
# Original 24x24 line icons drawn for AutoPress (stroke 1.8, round caps).  "{c}" = colour.
ICONS: dict[str, str] = {
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
    "more": '<circle cx="6" cy="12" r="1.5" fill="{c}" stroke="none"/><circle cx="12" cy="12" r="1.5" fill="{c}" stroke="none"/>'
    '<circle cx="18" cy="12" r="1.5" fill="{c}" stroke="none"/>',
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
    "drag": ''.join(f'<circle cx="{x}" cy="{y}" r="1.4" fill="{{c}}" stroke="none"/>' for x in (9, 15) for y in (6, 12, 18)),
    "flask": '<path d="M9.5 3.5h5M10.5 3.5v5L5 18a1.8 1.8 0 0 0 1.6 2.6h10.8A1.8 1.8 0 0 0 19 18l-5.5-9.5v-5"/><path d="M7.5 14.5h9"/>',
    "skip": '<path d="M6 6.5v11l8-5.5z"/><path d="M17.5 6.5v11"/>',
    "clock": '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
}

_icon_cache: dict[tuple, QPixmap] = {}


def icon_pixmap(name: str, color: str, size: int = 18, stroke: float = 1.8) -> QPixmap:
    screen = QGuiApplication.primaryScreen()
    dpr = screen.devicePixelRatio() if screen else 1.0
    key = (name, color, size, stroke, dpr)
    if key not in _icon_cache:
        hexcolor = qc(color).name()
        body = ICONS[name].replace("{c}", hexcolor)
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{hexcolor}" '
            f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
        )
        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        pm = QPixmap(round(size * dpr), round(size * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(p, QRectF(0, 0, size, size))
        p.end()
        _icon_cache[key] = pm
    return _icon_cache[key]


def icon(name: str, color: str, size: int = 16) -> QIcon:
    return QIcon(icon_pixmap(name, color, size))


# =============================================================================== QSS / palette


def build_palette(t: dict[str, str]) -> QPalette:
    pal = QPalette()
    roles = {
        QPalette.ColorRole.Window: t["bg_app"],
        QPalette.ColorRole.WindowText: t["text"],
        QPalette.ColorRole.Base: t["surface_raised"],
        QPalette.ColorRole.AlternateBase: t["surface_hover"],
        QPalette.ColorRole.Text: t["text"],
        QPalette.ColorRole.PlaceholderText: t["text_muted"],
        QPalette.ColorRole.Button: t["surface_raised"],
        QPalette.ColorRole.ButtonText: t["text"],
        QPalette.ColorRole.Highlight: t["accent_fill"],
        QPalette.ColorRole.HighlightedText: t["on_accent"],
        QPalette.ColorRole.ToolTipBase: t["overlay"],
        QPalette.ColorRole.ToolTipText: t["text"],
        QPalette.ColorRole.Link: t["accent"],
        QPalette.ColorRole.Mid: t["border_strong"],
        QPalette.ColorRole.Dark: t["border_strong"],
        QPalette.ColorRole.Light: t["surface_hover"],
    }
    for role, token in roles.items():
        pal.setColor(role, qc(token))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, qc(t["text_disabled"]))
    return pal


def build_qss(t: dict[str, str]) -> str:
    c = {k: css(v) for k, v in t.items() if v.startswith("#")}
    return f"""
QWidget {{ color: {c['text']}; font-size: {FS_BODY}px; }}
QFrame#Root, QFrame#Main {{ background: {c['bg_app']}; }}
QFrame#Sidebar {{ background: {c['bg_sidebar']}; border: none; border-right: 1px solid {c['border']}; }}
QFrame#Card {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: {R_LG}px; }}
QLabel {{ background: transparent; }}
QLabel[role="display"] {{ font-size: {FS_DISPLAY}px; font-weight: bold; }}
QLabel[role="brand"] {{ font-size: 16px; font-weight: bold; }}
QLabel[role="title"] {{ font-size: {FS_TITLE}px; font-weight: bold; }}
QLabel[role="strong"] {{ font-weight: bold; }}
QLabel[role="secondary"] {{ color: {c['text_secondary']}; }}
QLabel[role="muted"] {{ color: {c['text_muted']}; font-size: {FS_SMALL}px; }}
QLabel[role="caption"] {{ color: {c['text_muted']}; font-size: {FS_CAPTION}px; font-weight: bold; }}
QLabel[role="status"] {{ color: {c['text_secondary']}; font-size: {FS_SMALL}px; }}
QLabel[role="warning"] {{ color: {c['warning_text']}; }}
QLabel[role="keycap"] {{
    color: {c['text_secondary']}; font-size: {FS_CAPTION}px; font-weight: bold;
    background: {c['surface_raised']}; border: 1px solid {c['border_strong']}; border-bottom-width: 2px;
    border-radius: {R_SM}px; padding: 0px 5px;
}}
QFrame[role="divider"] {{ background: {c['border']}; border: none; min-height: 1px; max-height: 1px; }}
QFrame[role="vsep"] {{ background: {c['border_strong']}; border: none; min-width: 1px; max-width: 1px; }}

/* buttons: secondary (default) / primary / ghost / icon / danger */
QPushButton, QToolButton {{
    background: {c['surface_raised']}; color: {c['text']};
    border: 1px solid {c['border_strong']}; border-radius: {R_MD}px;
    padding: 0px 12px; min-height: 32px;
}}
QPushButton:hover, QToolButton:hover {{ background: {c['surface_hover']}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {c['border_strong']}; }}
QPushButton:disabled, QToolButton:disabled {{ color: {c['text_disabled']}; border-color: {c['border']}; }}
QPushButton[variant="primary"] {{
    background: {c['accent_fill']}; border: 1px solid {c['accent_fill']}; color: {c['on_accent']};
    font-weight: bold; padding: 0px 16px;
}}
QPushButton[variant="primary"]:hover {{ background: {c['accent_fill_hover']}; border-color: {c['accent_fill_hover']}; }}
QPushButton[variant="primary"]:pressed {{ background: {c['accent_fill_pressed']}; }}
QPushButton[variant="primary"]:disabled {{ background: {c['surface_inset']}; border-color: {c['border_strong']}; color: {c['text_disabled']}; }}
QPushButton[variant="ghost"], QToolButton[variant="ghost"] {{ background: transparent; border-color: transparent; color: {c['text_secondary']}; padding: 0px 10px; }}
QPushButton[variant="ghost"]:hover, QToolButton[variant="ghost"]:hover {{ background: {c['hover']}; color: {c['text']}; }}
QToolButton[variant="icon"] {{ background: transparent; border-color: transparent; padding: 0px; }}
QToolButton[variant="icon"]:hover {{ background: {c['hover']}; }}
QToolButton[variant="danger"] {{ color: {c['error_text']}; }}

/* segmented control */
QFrame#Segmented {{ background: {c['surface_inset']}; border: 1px solid {c['border']}; border-radius: 9px; }}
QFrame#Segmented QPushButton {{
    background: transparent; border: 1px solid transparent; border-radius: 7px;
    min-height: 26px; padding: 0px 12px; color: {c['text_secondary']};
}}
QFrame#Segmented QPushButton:hover {{ color: {c['text']}; }}
QFrame#Segmented QPushButton:checked {{ background: {c['seg_active']}; border-color: {c['border_strong']}; color: {c['text']}; }}

/* inputs */
QLineEdit, QComboBox {{
    background: {c['surface_raised']}; border: 1px solid {c['border_strong']}; border-radius: {R_MD}px;
    padding: 0px 10px; min-height: 32px;
    selection-background-color: {c['accent_fill']}; selection-color: {c['on_accent']};
}}
QLineEdit:hover, QComboBox:hover {{ border-color: {c['text_muted']}; }}
QLineEdit:focus, QComboBox:focus {{ border-color: {c['accent']}; }}
QComboBox {{ padding-right: 30px; combobox-popup: 0; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox::down-arrow {{ image: none; width: 0px; height: 0px; }}
QComboBox QAbstractItemView {{ background: {c['overlay']}; border: 1px solid {c['border_strong']}; outline: none; }}
/* QLineEdit's built-in action / clear buttons are QToolButtons: keep the button rules off them */
QLineEdit QToolButton {{ background: transparent; border: none; padding: 0px; min-height: 0px; min-width: 0px; }}

/* banners */
QFrame#Banner {{ background: {c['warning_soft']}; border: 1px solid {c['warning_border']}; border-radius: 10px; }}

/* table */
QTableView#CodeTable {{
    background: transparent; border: none; gridline-color: transparent; outline: 0;
    selection-background-color: {c['row_selected']}; selection-color: {c['text']};
}}
QTableView#CodeTable::item {{ border: none; border-bottom: 1px solid {c['border']}; padding: 0px; }}
QTableView#CodeTable::item:selected {{ background: {c['row_selected']}; color: {c['text']}; }}
QTableView#CodeTable::item:hover {{ background: {c['hover']}; }}
QHeaderView {{ background: transparent; border: none; }}
QHeaderView::section {{
    background: transparent; color: {c['text_muted']}; border: none; border-bottom: 1px solid {c['border_strong']};
    padding: 0px 12px; min-height: 34px; font-size: {FS_SMALL}px; font-weight: bold;
}}
QTableCornerButton::section {{ background: transparent; border: none; }}

/* scroll bars */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px 1px; }}
QScrollBar::handle:vertical {{ background: {c['scrollbar']}; border-radius: 3px; min-height: 28px; margin: 0px 2px; }}
QScrollBar::handle:vertical:hover {{ background: {c['scrollbar_hover']}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 1px 2px; }}
QScrollBar::handle:horizontal {{ background: {c['scrollbar']}; border-radius: 3px; min-width: 28px; margin: 2px 0px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0px; height: 0px; border: none; background: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QFrame#StatusBar {{ background: {c['bg_sidebar']}; border: none; border-top: 1px solid {c['border']}; }}
QFrame#MiniBar {{ background: {c['overlay']}; border: 1px solid {c['border_strong']}; border-radius: {R_XL}px; }}
QFrame#MiniBar QToolButton[variant="icon"] {{ background: {c['surface_raised']}; border: 1px solid {c['border_strong']}; }}
QFrame#MiniBar QToolButton[variant="icon"]:hover {{ background: {c['surface_hover']}; }}
QFrame#Toast {{ background: {c['overlay']}; border: 1px solid {c['border_strong']}; border-radius: 10px; }}
QToolTip {{ background: {c['overlay']}; color: {c['text']}; border: 1px solid {c['border_strong']}; padding: 4px 8px; }}
"""


# =============================================================================== small widgets


def label(text: str, role: str | None = None) -> QLabel:
    w = QLabel(text)
    if role:
        w.setProperty("role", role)
    return w


def icon_label(name: str, color_token: str, size: int = 16) -> QLabel:
    w = QLabel()
    w.setPixmap(icon_pixmap(name, T[color_token], size))
    w.setFixedSize(size, size)
    return w


def vsep(height: int = 14) -> QFrame:
    f = QFrame()
    f.setProperty("role", "vsep")
    f.setFixedHeight(height)
    return f


def keycap(text: str) -> QLabel:
    """Keyboard key hint, e.g. F8.  Fixed 20 px high - add it with AlignVCenter."""
    w = label(text, "keycap")
    w.setFixedHeight(20)
    w.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return w


def add_center(layout: QHBoxLayout, *widgets: QWidget) -> None:
    for w in widgets:
        layout.addWidget(w, 0, Qt.AlignmentFlag.AlignVCenter)


def tool_button(icon_name: str, text: str, variant: str | None = None, color_token: str = "text_secondary") -> QToolButton:
    b = QToolButton()
    b.setText(text)
    b.setIcon(icon(icon_name, T[color_token], 16))
    b.setIconSize(QSize(16, 16))
    b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon if text else Qt.ToolButtonStyle.ToolButtonIconOnly)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if variant:
        b.setProperty("variant", variant)
    if variant == "icon":
        b.setFixedSize(CONTROL_H, CONTROL_H)
    else:
        b.setFixedHeight(CONTROL_H)
    return b


def push_button(text: str, variant: str | None = None, icon_name: str | None = None, color_token: str = "on_accent") -> QPushButton:
    b = QPushButton(text)
    if variant:
        b.setProperty("variant", variant)
    if icon_name:
        b.setIcon(icon(icon_name, T[color_token], 16))
        b.setIconSize(QSize(16, 16))
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setFixedHeight(CONTROL_H)
    return b


class SearchField(QLineEdit):
    """Line edit with a painted leading search icon (QLineEdit.addAction mis-centres under QSS)."""

    def __init__(self, placeholder: str) -> None:
        super().__init__()
        self.setPlaceholderText(placeholder)
        self.setTextMargins(22, 0, 0, 0)
        self.setFixedHeight(CONTROL_H)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        p = QPainter(self)
        p.drawPixmap(QPointF(10, (self.height() - 16) / 2), icon_pixmap("search", T["text_muted"], 16))


class Switch(QAbstractButton):
    """Toggle switch (34 x 20)."""

    def __init__(self, checked: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:
        return QSize(34, 20)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0.5, 0.5, 33, 19)
        on = self.isChecked()
        p.setPen(Qt.PenStyle.NoPen if on else QPen(qc(T["border_strong"]), 1))
        p.setBrush(qc(T["accent_fill"] if on else T["surface_inset"]))
        p.drawRoundedRect(r, 9.5, 9.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qc("#FFFFFF" if on else T["text_muted"]))
        d = 14
        x = r.right() - d - 3 if on else r.left() + 3
        p.drawEllipse(QRectF(x, r.top() + 2.5, d, d))


class ChevronCombo(QComboBox):
    """QComboBox whose arrow is the original chevron icon (QSS hides the native arrow)."""

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        p = QPainter(self)
        pm = icon_pixmap("chevron", T["text_muted"], 16)
        p.drawPixmap(QPointF(self.width() - 24, (self.height() - 16) / 2), pm)


def combo(items: list[str], width: int | None = None) -> ChevronCombo:
    c = ChevronCombo()
    c.addItems(items)
    c.setFixedHeight(CONTROL_H)
    if width:
        c.setFixedWidth(width)
    return c


def segmented(items: list[str], checked: int = 0) -> QFrame:
    frame = QFrame()
    frame.setObjectName("Segmented")
    lay = QHBoxLayout(frame)
    lay.setContentsMargins(3, 3, 3, 3)
    lay.setSpacing(2)
    group = QButtonGroup(frame)
    group.setExclusive(True)
    for i, text in enumerate(items):
        b = QPushButton(text)
        b.setCheckable(True)
        b.setChecked(i == checked)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        group.addButton(b)
        lay.addWidget(b)
    return frame


class NavButton(QAbstractButton):
    """Sidebar item: icon, label, optional count badge; checked = soft fill + accent bar."""

    def __init__(self, icon_name: str, text: str, badge: str | None = None) -> None:
        super().__init__()
        self.setCheckable(True)
        self.setText(text)
        self._icon = icon_name
        self._badge = badge
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(font(FS_BODY, bold=True))
        w = 12 + 18 + 10 + fm.horizontalAdvance(self.text()) + 12
        if self._badge:
            w += QFontMetrics(font(FS_CAPTION, families=FONT_NUM)).horizontalAdvance(self._badge) + 20
        return QSize(w, 38)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        on = self.isChecked()
        if on or self.underMouse():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qc(T["nav_active"] if on else T["hover"]))
            p.drawRoundedRect(QRectF(0, 0, w, h), R_MD, R_MD)
        if on:
            p.setBrush(qc(T["accent"]))
            p.drawRoundedRect(QRectF(0, h / 2 - 8, 3, 16), 1.5, 1.5)
        p.drawPixmap(QPointF(12, (h - 18) / 2), icon_pixmap(self._icon, T["accent_text" if on else "text_secondary"], 18))
        right = w - 10
        if self._badge:
            bf = font(FS_CAPTION, bold=True, families=FONT_NUM, tnum=True)
            bw = QFontMetrics(bf).horizontalAdvance(self._badge) + 12
            br = QRectF(right - bw, (h - 18) / 2, bw, 18)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qc(T["accent_soft"] if on else T["neutral_soft"]))
            p.drawRoundedRect(br, 9, 9)
            p.setFont(bf)
            p.setPen(qc(T["accent_text" if on else "text_secondary"]))
            p.drawText(br, Qt.AlignmentFlag.AlignCenter, self._badge)
            right = br.left() - 6
        p.setFont(font(FS_BODY, bold=on))
        p.setPen(qc(T["text" if on else "text_secondary"]))
        p.drawText(QRectF(40, 0, right - 40, h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())


# =============================================================================== status chips

# key -> (label zh-TW, label en, tone, glyph)  tone = token prefix (success / warning / ...)
STATUS = {
    "pending": ("待兌換", "Pending", "neutral", "ring"),
    "running": ("兌換中", "Running", "accent", "dot"),
    "review": ("需確認", "Review", "warning", "dot"),
    "success": ("成功", "Redeemed", "success", "dot"),
    "used": ("已使用", "Already used", "violet", "dot"),
    "invalid": ("無效", "Invalid", "error", "dot"),
    "expired": ("已過期", "Expired", "orange", "dot"),
    "cooldown": ("冷卻中", "Rate-limited", "info", "dot"),
    "skipped": ("已略過", "Skipped", "neutral", "dash"),
}


def tone_colors(tone: str) -> tuple[str, str, str]:
    """(base, soft fill, text) tokens for a tone."""
    if tone == "accent":
        return T["accent"], T["accent_soft"], T["accent_text"]
    return T[tone], T[f"{tone}_soft"], T[f"{tone}_text"]


def chip_width(status: str, text: str | None = None) -> int:
    return QFontMetrics(font(FS_SMALL, bold=True)).horizontalAdvance(text or STATUS[status][0]) + 30


def paint_chip(p: QPainter, rect: QRectF, status: str, text: str | None = None) -> None:
    label_text, _en, tone, glyph = STATUS[status]
    text = text or label_text
    base, soft, fg = tone_colors(tone)
    f = font(FS_SMALL, bold=True)
    w = chip_width(status, text)
    r = QRectF(rect.left(), rect.center().y() - 11, w, 22)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(qc(soft))
    p.drawRoundedRect(r, 11, 11)
    cx, cy = r.left() + 12, r.center().y()
    if glyph == "dot":
        p.setBrush(qc(base))
        p.drawEllipse(QPointF(cx, cy), 3.2, 3.2)
    elif glyph == "ring":
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(qc(base), 1.4))
        p.drawEllipse(QPointF(cx, cy), 3.0, 3.0)
    else:
        p.setPen(QPen(qc(base), 1.6, cap=Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(cx - 3, cy), QPointF(cx + 3, cy))
    p.setFont(f)
    p.setPen(qc(fg))
    p.drawText(r.adjusted(20, 0, -8, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
    p.restore()


class Chip(QWidget):
    def __init__(self, status: str, text: str | None = None) -> None:
        super().__init__()
        self.status, self.text = status, text
        self.setFixedSize(chip_width(status, text), 24)

    def paintEvent(self, _event) -> None:
        paint_chip(QPainter(self), QRectF(self.rect()), self.status, self.text)


# =============================================================================== table

ROLE_STATUS = Qt.ItemDataRole.UserRole + 1
ROLE_UNCERTAIN = Qt.ItemDataRole.UserRole + 2
ROLE_CONF = Qt.ItemDataRole.UserRole + 3
ROLE_SOURCE = Qt.ItemDataRole.UserRole + 4
ROLE_CHECKED = Qt.ItemDataRole.UserRole + 5

SOURCES = {"paste": ("paste", "貼上"), "file": ("file", "檔案"), "image": ("image", "圖片"),
           "clip": ("clipimage", "剪貼簿"), "snip": ("snip", "截圖")}

# fake data - invented strings, NOT real codes.  (code, source, ocr confidence or None, uncertain char
# indices, status, message)
ROWS = [
    ("AP7K2QX9MZ4T", "paste", None, [], "success", "兌換成功，獎勵已寄至信箱"),
    ("HV3N8RT2KD6W", "paste", None, [], "used", "此兌換碼已被使用"),
    ("Q8ZL0W3NBX5C", "image", 0.71, [4], "review", "第 5 碼可能是 0 或 O"),
    ("MX4T9PK2JR7D", "image", 0.97, [], "running", "正在輸入…"),
    ("ZK6WD2TQ9HNA", "file", None, [], "pending", ""),
    ("TRV6Y2NCBL1X", "snip", 0.64, [8, 10], "review", "B／8、1／I 可能混淆"),
    ("BZ2M5KQ8XH3P", "clip", 0.93, [], "pending", ""),
    ("JW8R3TD5QN2K", "paste", None, [], "invalid", "兌換碼無效"),
    ("EK5P9WM3ZT7V", "paste", None, [], "expired", "兌換碼已過期"),
    ("HV3N8RT2KD6W", "paste", None, [], "skipped", "與第 2 筆重複"),
    ("LN7C2XR9PB4Q", "snip", 0.88, [], "cooldown", "兌換過於頻繁，60 秒後重試"),
    ("GS4H8NM2VC6R", "snip", 0.91, [], "pending", ""),
    ("WQ9D3KF7TX2M", "file", None, [], "pending", ""),
    ("CY2B7RL5MK8P", "file", None, [], "pending", ""),
]
CHECKED_ROWS = (4, 6)
COLUMNS = ["", "#", "序號", "來源", "辨識信心", "狀態", "訊息", ""]
COL_WIDTHS = [40, 44, 220, 104, 128, 112, None, 44]


class CellDelegate(QStyledItemDelegate):
    """Base: lets the style draw the QSS item background/border, then paints custom content."""

    pad = 12

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        opt.icon = QIcon()
        opt.state &= ~QStyle.StateFlag.State_HasFocus
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.content(painter, QRectF(option.rect).adjusted(self.pad, 0, -self.pad, 0), index)
        painter.restore()

    def content(self, p: QPainter, r: QRectF, index) -> None:
        p.setFont(font(FS_BODY))
        p.setPen(qc(T["text_secondary"]))
        text = QFontMetrics(p.font()).elidedText(index.data() or "", Qt.TextElideMode.ElideRight, int(r.width()))
        p.drawText(r, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)


class CheckDelegate(CellDelegate):
    def content(self, p: QPainter, r: QRectF, index) -> None:
        on = bool(index.data(ROLE_CHECKED))
        box = QRectF(r.left(), r.center().y() - 8, 16, 16)
        p.setPen(Qt.PenStyle.NoPen if on else QPen(qc(T["border_strong"]), 1.2))
        p.setBrush(qc(T["accent_fill"] if on else T["surface_raised"]))
        p.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
        if on:
            p.drawPixmap(box.topLeft() + QPointF(1, 1), icon_pixmap("check", "#FFFFFF", 14, 2.6))


class IndexDelegate(CellDelegate):
    def content(self, p: QPainter, r: QRectF, index) -> None:
        p.setFont(font(FS_SMALL, families=FONT_NUM, tnum=True))
        p.setPen(qc(T["text_muted"]))
        p.drawText(r, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, index.data())


class CodeDelegate(CellDelegate):
    """Monospace code; characters OCR was unsure about get a warning tint + underline."""

    def content(self, p: QPainter, r: QRectF, index) -> None:
        code = index.data() or ""
        unsure = set(index.data(ROLE_UNCERTAIN) or [])
        status = index.data(ROLE_STATUS)
        f = font(FS_MONO, families=FONT_MONO)
        p.setFont(f)
        fm = QFontMetrics(f)
        x = r.left()
        base_y = r.center().y() + (fm.ascent() - fm.descent()) / 2
        muted = status in ("skipped", "expired", "invalid", "used")
        for i, ch in enumerate(code):
            adv = fm.horizontalAdvance(ch)
            if i in unsure:
                cell = QRectF(x - 1, r.center().y() - 11, adv + 2, 22)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(qc(T["warning_soft"]))
                p.drawRoundedRect(cell, 3, 3)
                p.setPen(QPen(qc(T["warning"]), 1.6))
                p.drawLine(QPointF(cell.left() + 1.5, cell.bottom() - 2), QPointF(cell.right() - 1.5, cell.bottom() - 2))
                p.setPen(qc(T["warning_text"]))
            else:
                p.setPen(qc(T["text_muted" if muted else "text"]))
            p.drawText(QPointF(x, base_y), ch)
            x += adv


class SourceDelegate(CellDelegate):
    def content(self, p: QPainter, r: QRectF, index) -> None:
        icon_name, text = SOURCES[index.data(ROLE_SOURCE)]
        p.drawPixmap(QPointF(r.left(), r.center().y() - 8), icon_pixmap(icon_name, T["text_muted"], 16))
        p.setFont(font(FS_BODY))
        p.setPen(qc(T["text_secondary"]))
        p.drawText(r.adjusted(24, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)


class ConfidenceDelegate(CellDelegate):
    """OCR confidence: 48 px bar + percentage; '—' for typed / pasted codes (not applicable)."""

    def content(self, p: QPainter, r: QRectF, index) -> None:
        conf = index.data(ROLE_CONF)
        p.setFont(font(FS_SMALL, families=FONT_NUM, tnum=True))
        if conf is None:
            p.setPen(qc(T["text_disabled"]))
            p.drawText(r, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "—")
            return
        tone = "success" if conf >= 0.9 else ("accent" if conf >= 0.8 else "warning")
        base = tone_colors(tone)[0]
        track = QRectF(r.left(), r.center().y() - 2, 48, 4)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qc(T["border_strong"]))
        p.drawRoundedRect(track, 2, 2)
        p.setBrush(qc(base))
        p.drawRoundedRect(QRectF(track.left(), track.top(), 48 * conf, 4), 2, 2)
        p.setPen(qc(T["warning_text"] if tone == "warning" else T["text_secondary"]))
        p.drawText(r.adjusted(58, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, f"{round(conf * 100)}%")


class StatusDelegate(CellDelegate):
    def content(self, p: QPainter, r: QRectF, index) -> None:
        paint_chip(p, r, index.data(ROLE_STATUS))


class MoreDelegate(CellDelegate):
    pad = 0

    def content(self, p: QPainter, r: QRectF, index) -> None:
        p.drawPixmap(QPointF(r.center().x() - 9, r.center().y() - 9), icon_pixmap("more", T["text_muted"], 18))


def build_table() -> QTableView:
    model = QStandardItemModel(len(ROWS), len(COLUMNS))
    model.setHorizontalHeaderLabels(COLUMNS)
    for row, (code, source, conf, unsure, status, msg) in enumerate(ROWS):
        values = ["", f"{row + 1}", code, "", "", "", msg, ""]
        for col, value in enumerate(values):
            item = QStandardItem(value)
            item.setData(status, ROLE_STATUS)
            item.setData(unsure, ROLE_UNCERTAIN)
            item.setData(conf, ROLE_CONF)
            item.setData(source, ROLE_SOURCE)
            item.setData(row in CHECKED_ROWS, ROLE_CHECKED)
            model.setItem(row, col, item)
    view = QTableView()
    view.setObjectName("CodeTable")
    view.setModel(model)
    view._model = model  # keep a reference
    view.setShowGrid(False)
    view.setWordWrap(False)
    view.setAlternatingRowColors(False)
    view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    view.verticalHeader().setVisible(False)
    view.verticalHeader().setDefaultSectionSize(42)
    header = view.horizontalHeader()
    header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    header.setHighlightSections(False)
    header.setFixedHeight(36)
    delegates = [CheckDelegate, IndexDelegate, CodeDelegate, SourceDelegate, ConfidenceDelegate, StatusDelegate,
                 CellDelegate, MoreDelegate]
    view._delegates = [cls(view) for cls in delegates]
    for col, (delegate, width) in enumerate(zip(view._delegates, COL_WIDTHS)):
        view.setItemDelegateForColumn(col, delegate)
        if width is None:
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        else:
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            view.setColumnWidth(col, width)
    sel = view.selectionModel()
    for row in CHECKED_ROWS:
        sel.select(model.index(row, 0), QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    return view


# =============================================================================== empty state


class EmptyArt(QWidget):
    """Large illustration for empty states: dashed drop zone with a ticket glyph."""

    def sizeHint(self) -> QSize:
        return QSize(120, 96)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        pen = QPen(qc(T["border_strong"]), 1.5, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(qc(T["surface_inset"]))
        p.drawRoundedRect(r, 16, 16)
        p.drawPixmap(QPointF(r.center().x() - 20, r.center().y() - 20), icon_pixmap("codes", T["accent"], 40, 1.6))


def build_empty_state() -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(SP[6], SP[8], SP[6], SP[8])
    lay.setSpacing(SP[3])
    lay.addStretch(1)
    art = EmptyArt()
    art.setFixedSize(120, 96)
    lay.addWidget(art, 0, Qt.AlignmentFlag.AlignHCenter)
    lay.addSpacing(SP[2])
    lay.addWidget(label("還沒有任何序號", "title"), 0, Qt.AlignmentFlag.AlignHCenter)
    hint = label("貼上一段文字、開啟 .txt／.csv，或框選畫面上的序號，AutoPress 會自動找出序號並去除重複。", "secondary")
    hint.setAlignment(Qt.AlignmentFlag.AlignHCenter)
    lay.addWidget(hint, 0, Qt.AlignmentFlag.AlignHCenter)
    lay.addSpacing(SP[2])
    row = QHBoxLayout()
    row.setSpacing(SP[2])
    row.addStretch(1)
    row.addWidget(push_button("貼上文字", "primary", "paste"))
    b = tool_button("file", "開啟檔案")
    row.addWidget(b)
    row.addWidget(tool_button("snip", "框選螢幕辨識"))
    row.addStretch(1)
    lay.addLayout(row)
    lay.addSpacing(SP[1])
    tip = QHBoxLayout()
    tip.setSpacing(SP[1])
    tip.addStretch(1)
    add_center(tip, label("也可以直接把圖片拖曳到這裡，或按", "muted"), keycap("Ctrl"), label("+", "muted"),
               keycap("V"), label("貼上剪貼簿裡的圖片", "muted"))
    tip.addStretch(1)
    lay.addLayout(tip)
    lay.addStretch(2)
    return w


# =============================================================================== main window


def card(margins=(SP[4], SP[3], SP[4], SP[3]), spacing=SP[2], vertical=False) -> tuple[QFrame, QHBoxLayout | QVBoxLayout]:
    f = QFrame()
    f.setObjectName("Card")
    lay = QVBoxLayout(f) if vertical else QHBoxLayout(f)
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    return f, lay


def build_sidebar(active: str = "codes", code_count: str | None = "24") -> QFrame:
    side = QFrame()
    side.setObjectName("Sidebar")
    side.setFixedWidth(220)
    lay = QVBoxLayout(side)
    lay.setContentsMargins(SP[3], SP[5], SP[3], SP[3])
    lay.setSpacing(2)

    brand = QHBoxLayout()
    brand.setSpacing(SP[2] + 2)
    logo = QLabel()
    logo.setPixmap(icon_pixmap("logo", T["accent_fill"], 30))
    logo.setFixedSize(30, 30)
    brand.addWidget(logo)
    names = QVBoxLayout()
    names.setSpacing(0)
    names.addWidget(label("AutoPress", "brand"))
    names.addWidget(label("序號自動輸入", "muted"))
    brand.addLayout(names)
    brand.addStretch(1)
    brand_box = QWidget()
    brand_box.setLayout(brand)
    brand.setContentsMargins(SP[2], 0, 0, 0)
    lay.addWidget(brand_box)
    lay.addSpacing(SP[5])

    cap = label("工作區", "caption")
    cap.setContentsMargins(SP[3], 0, 0, SP[1])
    lay.addWidget(cap)
    for key, text, badge in (("codes", "序號", code_count), ("profiles", "設定檔", "3"), ("run", "執行", None),
                             ("history", "紀錄", "128")):
        b = NavButton(key, text, badge)
        b.setChecked(key == active)
        lay.addWidget(b)
    lay.addStretch(1)
    for key, text in (("settings", "設定"), ("help", "說明")):
        lay.addWidget(NavButton(key, text))
    lay.addSpacing(SP[2])
    div = QFrame()
    div.setProperty("role", "divider")
    lay.addWidget(div)
    lay.addSpacing(SP[2])
    theme_row = QHBoxLayout()
    theme_row.setContentsMargins(SP[3], 0, SP[1], 0)
    theme_row.addWidget(icon_label("moon", "text_secondary", 16))
    theme_row.addSpacing(SP[2])
    theme_row.addWidget(label("深色模式", "secondary"))
    theme_row.addStretch(1)
    theme_row.addWidget(Switch(T["name"] == "dark"))
    lay.addLayout(theme_row)
    lay.addSpacing(SP[2])
    ver = label("v0.1 · 離線運作，不連網", "muted")
    ver.setContentsMargins(SP[3], 0, 0, 0)
    lay.addWidget(ver)
    return side


def build_codes_page(empty: bool = False) -> QFrame:
    page = QFrame()
    page.setObjectName("Main")
    outer = QVBoxLayout(page)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)

    content = QWidget()
    lay = QVBoxLayout(content)
    lay.setContentsMargins(SP[7] - 4, SP[5], SP[7] - 4, SP[4])
    lay.setSpacing(SP[4])

    # -- page header
    head = QHBoxLayout()
    head.setSpacing(SP[2])
    titles = QVBoxLayout()
    titles.setSpacing(2)
    titles.addWidget(label("序號", "display"))
    titles.addWidget(label("尚未新增序號" if empty else "24 筆 · 來自 5 個來源 · 已自動去除 1 筆重複", "muted"))
    head.addLayout(titles)
    head.addStretch(1)
    head.addWidget(label("設定檔", "secondary"))
    head.addWidget(combo(["原神 · 網頁兌換", "遊戲內兌換視窗（通用）", "網頁兌換（通用）"], 196))
    test = tool_button("flask", "試跑 1 筆")
    head.addWidget(test)
    start = push_button("開始兌換", "primary", "play")
    start.setEnabled(not empty)
    head.addWidget(start)
    lay.addLayout(head)

    # -- import toolbar
    imp, imp_lay = card()
    imp_lay.addWidget(label("新增序號", "strong"))
    imp_lay.addSpacing(SP[1])
    for icon_name, text in (("paste", "貼上文字"), ("file", "開啟檔案"), ("image", "圖片辨識"),
                            ("clipimage", "剪貼簿圖片"), ("snip", "框選螢幕")):
        imp_lay.addWidget(tool_button(icon_name, text))
    imp_lay.addStretch(1)
    imp_lay.addWidget(label("格式", "secondary"))
    imp_lay.addWidget(combo(["自動偵測", "HoYoverse（12 碼英數）", "Steam（5-5-5）", "自訂規則…"], 136))
    lay.addWidget(imp)

    if not empty:
        # -- review banner
        banner = QFrame()
        banner.setObjectName("Banner")
        b_lay = QHBoxLayout(banner)
        b_lay.setContentsMargins(SP[3] + 2, SP[2], SP[2], SP[2])
        b_lay.setSpacing(SP[2] + 2)
        b_lay.addWidget(icon_label("alert", "warning", 18))
        msg = label("2 筆序號的辨識信心偏低，請檢查以黃色標示的字元（例如 0／O、1／I、8／B）。", "warning")
        b_lay.addWidget(msg, 1)
        b_lay.addWidget(tool_button("check", "逐筆檢查", "ghost", "warning_text"))
        b_lay.addWidget(tool_button("x", "", "icon", "text_muted"))
        lay.addWidget(banner)

    # -- table card
    tbl, tbl_lay = card(margins=(SP[4], SP[3], SP[4], SP[2]), spacing=SP[2], vertical=True)
    top = QHBoxLayout()
    top.setSpacing(SP[3])
    if empty:
        top.addWidget(segmented(["全部 0", "待兌換 0", "需確認 0", "已完成 0", "略過 0"]))
    else:
        top.addWidget(segmented(["全部 24", "待兌換 13", "需確認 2", "已完成 6", "略過 3"]))
    top.addStretch(1)
    search = SearchField("搜尋序號或訊息")
    search.setFixedWidth(220)
    top.addWidget(search)
    top.addSpacing(SP[1])
    top.addWidget(Switch(True))
    top.addWidget(label("略過已兌換過的序號", "secondary"))
    tbl_lay.addLayout(top)
    if empty:
        tbl_lay.addWidget(build_empty_state(), 1)
    else:
        tbl_lay.addWidget(build_table(), 1)
        bottom = QHBoxLayout()
        bottom.setSpacing(SP[1])
        bottom.addWidget(label("已選取 2 筆", "secondary"))
        bottom.addSpacing(SP[2])
        bottom.addWidget(tool_button("trash", "移除", "ghost"))
        bottom.addWidget(tool_button("check", "標記為已兌換", "ghost"))
        bottom.addWidget(tool_button("skip", "略過", "ghost"))
        bottom.addStretch(1)
        bottom.addWidget(tool_button("export", "匯出 CSV", "ghost"))
        tbl_lay.addLayout(bottom)
    lay.addWidget(tbl, 1)
    outer.addWidget(content, 1)

    # -- status bar: the safety state is always visible
    bar = QFrame()
    bar.setObjectName("StatusBar")
    bar.setFixedHeight(36)
    s = QHBoxLayout(bar)
    s.setContentsMargins(SP[7] - 4, 0, SP[7] - 4, 0)
    s.setSpacing(SP[2])
    s.addWidget(icon_label("shield", "success", 16))
    s.addWidget(label("前景保護：開啟", "status"))
    s.addSpacing(SP[1])
    s.addWidget(vsep())
    s.addSpacing(SP[1])
    s.addWidget(icon_label("gauge", "text_muted", 16))
    s.addWidget(label("每筆間隔 6–8 秒", "status"))
    s.addSpacing(SP[1])
    s.addWidget(vsep())
    s.addSpacing(SP[1])
    add_center(s, keycap("F8"), label("暫停", "status"))
    s.addSpacing(SP[1])
    add_center(s, keycap("F9"), label("停止 · 滑鼠移到螢幕左上角也會緊急停止", "status"))
    s.addStretch(1)
    s.addWidget(icon_label("window", "text_muted", 16))
    s.addWidget(label("目標視窗：Microsoft Edge（已找到）", "status"))
    outer.addWidget(bar)
    return page


class MainWindow(QMainWindow):
    def __init__(self, empty: bool = False) -> None:
        super().__init__()
        self.setWindowTitle("AutoPress")
        root = QFrame()
        root.setObjectName("Root")
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(build_sidebar(code_count=None if empty else "24"))
        lay.addWidget(build_codes_page(empty), 1)
        self.setCentralWidget(root)


# =============================================================================== mini run bar


class ProgressRing(QWidget):
    def __init__(self, done: int, total: int, size: int = 40) -> None:
        super().__init__()
        self.done, self.total = done, total
        self.setFixedSize(size, size)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        p.setPen(QPen(qc(T["border_strong"]), 4))
        p.drawEllipse(r)
        pen = QPen(qc(T["accent"]), 4, cap=Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(r, 90 * 16, -round(360 * 16 * self.done / self.total))
        p.setFont(font(FS_CAPTION, bold=True, families=FONT_NUM, tnum=True))
        p.setPen(qc(T["text"]))
        p.drawText(QRectF(self.rect()), Qt.AlignmentFlag.AlignCenter, f"{self.done}/{self.total}")


class Backdrop(QFrame):
    """Fake 'game / browser' background so the floating bar is judged in context."""

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        g = QLinearGradient(0, 0, self.width(), self.height())
        g.setColorAt(0, qc(T["backdrop_a"]))
        g.setColorAt(1, qc(T["backdrop_b"]))
        p.fillRect(self.rect(), g)


def build_minibar_scene() -> QWidget:
    scene = Backdrop()
    scene.setFixedSize(600, 150)
    lay = QVBoxLayout(scene)
    lay.setContentsMargins(SP[7], SP[6], SP[7], SP[6])
    bar = QFrame()
    bar.setObjectName("MiniBar")
    shadow = QGraphicsDropShadowEffect(bar)
    shadow.setBlurRadius(28)
    shadow.setOffset(0, 8)
    shadow.setColor(qc(T["shadow"]))
    bar.setGraphicsEffect(shadow)
    b = QHBoxLayout(bar)
    b.setContentsMargins(SP[2], SP[2], SP[3], SP[2])
    b.setSpacing(SP[3])
    grip = icon_label("drag", "text_disabled", 16)
    grip.setToolTip("拖曳移動")
    b.addWidget(grip, 0, Qt.AlignmentFlag.AlignVCenter)
    b.addWidget(ProgressRing(7, 15))
    text = QVBoxLayout()
    text.setSpacing(1)
    line1 = QHBoxLayout()
    line1.setSpacing(SP[2])
    line1.addWidget(label("正在兌換", "strong"))
    code = QLabel("MX4T9PK2JR7D")
    code.setFont(font(FS_MONO, families=FONT_MONO))
    line1.addWidget(code)
    line1.addStretch(1)
    text.addLayout(line1)
    line2 = QHBoxLayout()
    line2.setSpacing(SP[1] + 2)
    add_center(line2, Chip("success", "成功 5"), Chip("used", "已使用 1"), label("· 下一筆 6 秒後", "muted"))
    line2.addStretch(1)
    text.addLayout(line2)
    b.addLayout(text, 1)
    pause = tool_button("pause", "", "icon", "text")
    pause.setToolTip("暫停（F8）")
    stop = tool_button("stop", "", "icon", "error")
    stop.setToolTip("停止（F9）")
    add_center(b, pause, keycap("F8"))
    b.addSpacing(SP[1])
    add_center(b, stop, keycap("F9"))
    lay.addWidget(bar)
    return scene


# =============================================================================== checks


def contrast(fg: str, bg: str) -> float:
    def lum(hexv: str, under: str | None = None) -> float:
        c = qc(hexv)
        if c.alpha() < 255 and under:  # composite over the background first
            u = qc(under)
            a = c.alphaF()
            c = QColor(round(c.red() * a + u.red() * (1 - a)), round(c.green() * a + u.green() * (1 - a)),
                       round(c.blue() * a + u.blue() * (1 - a)))

        def ch(v: int) -> float:
            s = v / 255
            return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

        return 0.2126 * ch(c.red()) + 0.7152 * ch(c.green()) + 0.0722 * ch(c.blue())

    l1, l2 = lum(fg), lum(bg)
    return (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)


def composite(top: str, under: str) -> str:
    c, u = qc(top), qc(under)
    a = c.alphaF()
    return QColor(round(c.red() * a + u.red() * (1 - a)), round(c.green() * a + u.green() * (1 - a)),
                  round(c.blue() * a + u.blue() * (1 - a))).name()


def contrast_report(t: dict[str, str]) -> list[str]:
    """Small-text pairs that must reach 4.5:1 (WCAG AA)."""
    rows = []
    pairs = [("text", "surface"), ("text_secondary", "surface"), ("text_muted", "surface"), ("text_muted", "bg_app"),
             ("text_secondary", "bg_sidebar"), ("on_accent", "accent_fill"), ("warning_text", "surface")]
    for fg, bg in pairs:
        rows.append((f"{fg} on {bg}", contrast(t[fg], t[bg])))
    for tone in ("success", "warning", "error", "info", "violet", "orange", "neutral"):
        chip_bg = composite(t[f"{tone}_soft"], t["surface"])
        rows.append((f"{tone}_text on {tone}_soft/surface", contrast(t[f"{tone}_text"], chip_bg)))
    chip_bg = composite(t["accent_soft"], t["surface"])
    rows.append(("accent_text on accent_soft/surface", contrast(t["accent_text"], chip_bg)))
    banner_bg = composite(t["warning_soft"], t["bg_app"])
    rows.append(("warning_text on banner", contrast(t["warning_text"], banner_bg)))
    return [f"{'OK ' if v >= 4.5 else 'LOW'} {v:5.2f}  {name}" for name, v in rows]


def clipped_widgets(root: QWidget) -> list[str]:
    """Labels / buttons whose text cannot fit: narrower than their size hint, or shorter than one
    line of their font.  (Height is checked against the font, not sizeHint: buttons are fixed at
    CONTROL_H on purpose, below Qt's padded hint.)"""
    issues = []
    for w in root.findChildren(QWidget):
        if not w.isVisible() or not isinstance(w, (QLabel, QAbstractButton)):
            continue
        if isinstance(w, QLabel) and (w.wordWrap() or w.pixmap() is not None and not w.pixmap().isNull()):
            continue
        if not w.text():  # icon-only button / custom painted widget: nothing to clip
            continue
        hint = w.sizeHint()
        line = QFontMetrics(w.font()).height()
        if w.width() + 1 < hint.width() or w.height() < line:
            issues.append(f"{type(w).__name__} {w.text()!r}: {w.width()}x{w.height()} < hint {hint.width()}x{hint.height()}"
                          f" / line {line}")
    return issues


# =============================================================================== main


def apply_theme(app: QApplication, name: str) -> None:
    global T
    T = THEMES[name]
    _icon_cache.clear()
    app.setPalette(build_palette(T))
    app.setStyleSheet(build_qss(T))


def settle(app: QApplication) -> None:
    for _ in range(4):
        app.processEvents()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the AutoPress UI prototype to PNG.")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--theme", choices=("dark", "light", "both"), default="both")
    parser.add_argument("--scale", type=float, default=None, help="QT_SCALE_FACTOR, e.g. 1.25 or 1.5")
    parser.add_argument("--size", default="1280x800", help="logical window size")
    parser.add_argument("--live", action="store_true", help="show the window instead of saving PNGs")
    args = parser.parse_args(argv)

    os.environ["QT_QPA_PLATFORM"] = "windows"  # real fonts; never 'offscreen' for visual checks
    if args.scale:
        os.environ["QT_SCALE_FACTOR"] = str(args.scale)
    app = QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    app.setFont(font(FS_BODY))
    width, height = (int(v) for v in args.size.lower().split("x"))
    themes = ("dark", "light") if args.theme == "both" else (args.theme,)

    if args.live:
        apply_theme(app, themes[0])
        win = MainWindow()
        win.resize(width, height)
        win.show()
        return app.exec()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    suffix = f"_{round(args.scale * 100)}pct" if args.scale else ""
    written = []
    for name in themes:
        apply_theme(app, name)
        for variant, empty in (("codes", False), ("codes_empty", True)):
            if empty and args.scale:
                continue
            win = MainWindow(empty=empty)
            win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
            win.resize(width, height)
            win.show()
            settle(app)
            path = out / f"{variant}_{name}{suffix}.png"
            win.grab().save(str(path), "PNG")
            written.append(path)
            for issue in clipped_widgets(win):
                print("CLIPPED", name, variant, ascii(issue))
            win.close()
        if not args.scale:
            scene = build_minibar_scene()
            scene.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
            scene.show()
            settle(app)
            path = out / f"minibar_{name}.png"
            scene.grab().save(str(path), "PNG")
            written.append(path)
            for issue in clipped_widgets(scene):
                print("CLIPPED", name, "minibar", ascii(issue))
            scene.close()
        for line in contrast_report(T):
            print("CONTRAST", name, line)
    for path in written:
        print("WROTE", path.as_posix())
    return 0


if __name__ == "__main__":
    sys.exit(main())
