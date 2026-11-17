# OWNED BY G5 - replace this stub
"""Design tokens, fonts, QSS and palette (docs/research/ux.md section 6; port the helpers from
docs/research/scripts/ux/prototype.py). The constants and the DARK / LIGHT token tables below
are FINAL (copied verbatim from the prototype by A1): keep every name and value; you may add
tokens. Custom-painted widgets read colours at paint time through color(), so a theme switch
only needs apply_theme() + update().
"""

from __future__ import annotations

from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtWidgets import QApplication

from ..models import ThemeName

__stub__ = True

FONT_UI: tuple[str, ...] = ("Microsoft JhengHei UI", "Segoe UI")  # JhengHei UI Latin glyphs follow Segoe UI
FONT_MONO: tuple[str, ...] = ("Consolas", "Cascadia Mono", "Courier New")  # codes: slashed zero, distinct 1/l/I
FONT_NUM: tuple[str, ...] = ("Segoe UI", "Microsoft JhengHei UI")  # numbers, with tabular figures (tnum)
FS_DISPLAY, FS_TITLE, FS_BODY, FS_SMALL, FS_CAPTION, FS_MONO = 22, 15, 13, 12, 11, 14
SP: tuple[int, ...] = (0, 4, 8, 12, 16, 20, 24, 32, 40)  # spacing scale, use SP[n]
R_SM, R_MD, R_LG, R_XL = 4, 8, 12, 14  # radii: keycap/chip-inner, control, card, floating
CONTROL_H = 32  # buttons, inputs, combos
ROW_H = 42  # table rows
NAV_H = 38  # sidebar items
CHIP_H = 22
KEYCAP_H = 20
SIDEBAR_W = 220
PAGE_MARGINS: tuple[int, int, int, int] = (24, 20, 24, 20)  # left, top, right, bottom
CARD_MARGINS: tuple[int, int, int, int] = (16, 12, 16, 12)

# Colours are "#RRGGBB" or "#RRGGBBAA" (alpha LAST, CSS order).
DARK: dict[str, str] = {
    "name": "dark",
    "bg_app": "#0E1014",
    "bg_sidebar": "#12151A",
    "surface": "#171A20",
    "surface_raised": "#1E222A",
    "surface_hover": "#262B34",
    "surface_inset": "#101317",
    "seg_active": "#272C36",
    "overlay": "#1C2027",
    "nav_active": "#1D2230",
    "row_selected": "#1C2638",
    "border": "#242933",
    "border_strong": "#333A46",
    "text": "#E7E9EE",
    "text_secondary": "#A9B1BE",
    "text_muted": "#848C9B",
    "text_disabled": "#5C6370",
    "accent": "#6B93FF",
    "accent_fill": "#2F66F0",
    "accent_fill_hover": "#4275F5",
    "accent_fill_pressed": "#2556D6",
    "on_accent": "#FFFFFF",
    "accent_soft": "#6B93FF24",
    "accent_text": "#A3BDFF",
    "hover": "#FFFFFF0D",
    "success": "#3DD68C",
    "success_soft": "#3DD68C1F",
    "success_text": "#74E6AE",
    "warning": "#F5B544",
    "warning_soft": "#F5B5441C",
    "warning_text": "#FFCD70",
    "warning_border": "#F5B54459",
    "error": "#F87171",
    "error_soft": "#F871711F",
    "error_text": "#FF9D9D",
    "info": "#5CC8FF",
    "info_soft": "#5CC8FF1C",
    "info_text": "#93DAFF",
    "violet": "#A78BFA",
    "violet_soft": "#A78BFA24",
    "violet_text": "#C9BBFF",
    "orange": "#FB923C",
    "orange_soft": "#FB923C1F",
    "orange_text": "#FDBA80",
    "neutral": "#8A93A3",
    "neutral_soft": "#A9B1BE1A",
    "neutral_text": "#B7BECA",
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
    "success": "#16A34A",
    "success_soft": "#16A34A1A",
    "success_text": "#13773A",
    "warning": "#D97706",
    "warning_soft": "#F59E0B1F",
    "warning_text": "#8A3D0B",
    "warning_border": "#F59E0B66",
    "error": "#DC2626",
    "error_soft": "#DC26261A",
    "error_text": "#B41C1C",
    "info": "#0284C7",
    "info_soft": "#0284C71A",
    "info_text": "#075985",
    "violet": "#7C3AED",
    "violet_soft": "#7C3AED1A",
    "violet_text": "#6127C9",
    "orange": "#EA580C",
    "orange_soft": "#EA580C1A",
    "orange_text": "#A93A08",
    "neutral": "#64748B",
    "neutral_soft": "#64748B1A",
    "neutral_text": "#475569",
    "scrollbar": "#0F172A26",
    "scrollbar_hover": "#0F172A45",
    "shadow": "#0F172A40",
    "backdrop_a": "#DCE6F7",
    "backdrop_b": "#EFE3F3",
}

THEMES: dict[str, dict[str, str]] = {"dark": DARK, "light": LIGHT}


def resolve_theme(name: ThemeName | str) -> str:
    """"dark" | "light" for a setting value; "system" follows QStyleHints.colorScheme()
    (Unknown -> "dark")."""
    raise NotImplementedError


def apply_theme(app: QApplication, name: ThemeName | str) -> str:
    """Fusion style + build_palette + build_qss for the resolved theme, then update() every
    widget. Returns the resolved name. (ui.app emits AppSignals.theme_changed afterwards.)"""
    raise NotImplementedError


def current_theme() -> str:
    """The theme applied last ("dark" before any apply_theme call)."""
    raise NotImplementedError


def tokens() -> dict[str, str]:
    """The active token table (DARK or LIGHT)."""
    raise NotImplementedError


def color(token: str) -> QColor:
    """QColor of an active-theme token, or of a literal "#RRGGBB[AA]" string."""
    raise NotImplementedError


def css(token: str) -> str:
    """CSS colour for QSS: "#rrggbb" or "rgba(r, g, b, a)" (token or literal)."""
    raise NotImplementedError


def tone_colors(tone: str) -> tuple[QColor, QColor, QColor]:
    """(base, soft fill, text) for a tone (models.CodeStatus.tone: neutral, warning, accent,
    success, violet, error, orange, info)."""
    raise NotImplementedError


def font(px: int = FS_BODY, *, bold: bool = False, mono: bool = False, tnum: bool = False) -> QFont:
    """Pixel-sized font from FONT_UI (or FONT_MONO when ``mono``); ``tnum`` = tabular figures."""
    raise NotImplementedError


def build_qss(t: dict[str, str]) -> str:
    """Application stylesheet for a token table (SPEC section 6.3 lists the required selectors)."""
    raise NotImplementedError


def build_palette(t: dict[str, str]) -> QPalette:
    raise NotImplementedError
