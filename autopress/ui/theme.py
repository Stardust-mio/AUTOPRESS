# OWNED BY G5
"""Design tokens, fonts, QSS and palette (docs/research/ux.md section 6; helpers ported from
docs/research/scripts/ux/prototype.py). The constants and the DARK / LIGHT token tables below
are FINAL (copied verbatim from the prototype by A1): keep every name and value; you may add
tokens. Custom-painted widgets read colours at paint time through color(), so a theme switch
only needs apply_theme() + update().

How the look is built (SPEC 6.2):
* ``apply_theme`` installs ``shell_style.AppStyle`` (Fusion behind a proxy that paints the check
  / radio indicators and polishes spin boxes), the palette from ``build_palette`` and the
  application stylesheet from ``build_qss``; then it re-colours the themed icons
  (``icons.bind``) and repaints every widget. The application font (13 px Microsoft JhengHei UI)
  is set by ``ui.app.create_application`` - the QSS sets font sizes only through label roles,
  so ``widget.setFont(theme.font(...))`` is never overridden by a global rule.
* Styling hooks are dynamic properties: ``QPushButton[variant=primary|secondary|ghost|danger]``,
  ``QToolButton[variant=...|icon]``, ``QLabel[role=display|title|body|strong|secondary|muted|
  caption|mono|error|warning|success|info|keycap|status|brand|tone_<tone>]`` and
  ``QFrame[frameRole=card|banner|sidebar|statusbar|toast|minibar|segmented|inset|panel]``
  (the prototype's object names ``#Card #Banner #Sidebar #StatusBar #Toast #MiniBar
  #Segmented`` work too). Banner tones: ``QFrame[frameRole="banner"][tone="warning"]`` etc.
* Combo-box and spin-box arrows are small SVG files written once per colour into
  ``<data folder>/cache/ui`` (QSS needs a file for ``image:``; the files are 300 bytes).
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtWidgets import QApplication

from ..models import ThemeName

log = logging.getLogger(__name__)

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

TONES: tuple[str, ...] = ("neutral", "warning", "accent", "success", "violet", "error", "orange", "info")
"""Every tone of models.CodeStatus.tone (and Banner / toast kinds)."""

_state: dict[str, object] = {"name": "dark", "requested": "dark", "style": None, "scheme_hooked": False}


# =============================================================================== tokens


def resolve_theme(name: ThemeName | str) -> str:
    """"dark" | "light" for a setting value; "system" follows QStyleHints.colorScheme()
    (Unknown -> "dark")."""
    value = str(getattr(name, "value", name) or "").strip().lower()
    if value in THEMES:
        return value
    app = QApplication.instance()
    if app is not None:
        try:
            scheme = app.styleHints().colorScheme()  # type: ignore[union-attr]
        except AttributeError:
            scheme = Qt.ColorScheme.Unknown
        if scheme == Qt.ColorScheme.Light:
            return "light"
    return "dark"


def current_theme() -> str:
    """The theme applied last ("dark" before any apply_theme call)."""
    return str(_state["name"])


def tokens() -> dict[str, str]:
    """The active token table (DARK or LIGHT). Do not mutate it."""
    return THEMES[current_theme()]


def _parse(value: str) -> QColor:
    text = value.strip().lstrip("#")
    if len(text) in (6, 8) and all(c in "0123456789abcdefABCDEF" for c in text):
        r, g, b = int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)
        a = int(text[6:8], 16) if len(text) == 8 else 255
        return QColor(r, g, b, a)
    return QColor(value)


def color(token: str) -> QColor:
    """QColor of an active-theme token, or of a literal "#RRGGBB[AA]" string."""
    if isinstance(token, QColor):
        return QColor(token)
    value = tokens().get(token)
    if value is None:
        if not str(token).startswith("#"):
            log.debug("unknown colour token %r", token)
        value = str(token)
    return _parse(value)


def _css_of(c: QColor) -> str:
    return c.name() if c.alpha() == 255 else f"rgba({c.red()}, {c.green()}, {c.blue()}, {c.alpha()})"


def css(token: str) -> str:
    """CSS colour for QSS: "#rrggbb" or "rgba(r, g, b, a)" (token or literal)."""
    return _css_of(color(token))


def tone_colors(tone: str) -> tuple[QColor, QColor, QColor]:
    """(base, soft fill, text) for a tone (models.CodeStatus.tone: neutral, warning, accent,
    success, violet, error, orange, info)."""
    tone = tone if tone in TONES else "neutral"
    return color(tone), color(f"{tone}_soft"), color(f"{tone}_text")


def font(px: int = FS_BODY, *, bold: bool = False, mono: bool = False, tnum: bool = False,
         num: bool = False) -> QFont:
    """Pixel-sized font from FONT_UI (or FONT_MONO when ``mono``, FONT_NUM when ``num``);
    ``tnum`` = tabular figures (numbers that do not jump while they count)."""
    f = QFont()
    f.setFamilies(list(FONT_MONO if mono else FONT_NUM if num else FONT_UI))
    f.setPixelSize(int(px))
    if bold:
        f.setWeight(QFont.Weight.Bold)
    if tnum:
        f.setFeature(QFont.Tag("tnum"), 1)
    return f


# =============================================================================== palette


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
        QPalette.ColorRole.BrightText: t["on_accent"],
        QPalette.ColorRole.Highlight: t["accent_fill"],
        QPalette.ColorRole.HighlightedText: t["on_accent"],
        QPalette.ColorRole.ToolTipBase: t["overlay"],
        QPalette.ColorRole.ToolTipText: t["text"],
        QPalette.ColorRole.Link: t["accent"],
        QPalette.ColorRole.LinkVisited: t["accent"],
        QPalette.ColorRole.Mid: t["border_strong"],
        QPalette.ColorRole.Dark: t["border_strong"],
        QPalette.ColorRole.Shadow: t["border_strong"],
        QPalette.ColorRole.Midlight: t["surface_hover"],
        QPalette.ColorRole.Light: t["surface_hover"],
    }
    for role, value in roles.items():
        pal.setColor(role, _parse(value))
    disabled = _parse(t["text_disabled"])
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText,
                 QPalette.ColorRole.HighlightedText, QPalette.ColorRole.PlaceholderText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, disabled)
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base, _parse(t["surface_inset"]))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button, _parse(t["surface_inset"]))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, _parse(t["border_strong"]))
    return pal


# =============================================================================== QSS assets

_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{c}" '
        'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="{d}"/></svg>')
_ASSET_PATHS = {"down": "M7 10l5 5 5-5", "up": "M7 14l5-5 5 5"}
_asset_dir_cache: dict[str, Path | None] = {}


def _asset_dir() -> Path | None:
    from .. import paths

    key = str(paths.resolve_data_dir()[0])
    if key not in _asset_dir_cache:
        try:
            d = paths.data_dir() / "cache" / "ui"
            d.mkdir(parents=True, exist_ok=True)
            _asset_dir_cache[key] = d
        except OSError as exc:
            log.warning("cannot create the UI asset folder (%s); combo arrows fall back to none", exc)
            _asset_dir_cache[key] = None
    return _asset_dir_cache[key]


def qss_assets(t: dict[str, str]) -> dict[str, str]:
    """Arrow images for the QSS: {"down": path, "down_disabled": ..., "up": ..., "up_disabled":
    ...} as forward-slash paths; {} when the folder cannot be written (QSS then omits them)."""
    d = _asset_dir()
    if d is None:
        return {}
    out: dict[str, str] = {}
    for state, token in (("", "text_muted"), ("_disabled", "text_disabled")):
        hexcolor = _parse(t[token]).name()
        for name, path_d in _ASSET_PATHS.items():
            f = d / f"chevron-{name}-{hexcolor.lstrip('#')}.svg"
            try:
                if not f.is_file():
                    f.write_text(_SVG.format(c=hexcolor, d=path_d), encoding="utf-8")
            except OSError as exc:
                log.warning("cannot write %s: %s", f, exc)
                return {}
            out[name + state] = f.as_posix()
    return out


# =============================================================================== QSS


def build_qss(t: dict[str, str]) -> str:
    """Application stylesheet for a token table (SPEC section 6.2 lists the required selectors)."""
    c = {k: _css_of(_parse(v)) for k, v in t.items() if isinstance(v, str) and v.startswith("#")}
    alpha = 0x59 if t.get("name") == "dark" else 0x66
    for tone in TONES:  # derived tone borders (warning_border is a real token)
        base = _parse(t["accent" if tone == "accent" else tone])
        base.setAlpha(alpha)
        c.setdefault(f"{tone}_border", _css_of(base))
    assets = qss_assets(t)
    from . import shell_qss as q

    parts = [q.qss_base(c), q.qss_buttons(c), q.qss_inputs(c, assets), q.qss_views(c), q.qss_misc(c)]
    tone_rules = []
    for tone in TONES:
        soft = c[f"{tone}_soft"]
        tone_rules.append(
            f'QFrame[frameRole="banner"][tone="{tone}"] {{ background: {soft}; border: 1px solid {c[tone + "_border"]}; '
            f'border-radius: 10px; }}\n'
            f'QLabel[role="tone_{tone}"] {{ color: {c[tone + "_text"]}; }}\n'
            f'QPushButton[variant="ghost"][tone="{tone}"], QToolButton[variant="ghost"][tone="{tone}"] '
            f'{{ color: {c[tone + "_text"]}; }}\n')
    parts.append("".join(tone_rules))
    return "\n".join(parts)


# =============================================================================== apply


def install_style(app: QApplication) -> None:
    """Install shell_style.AppStyle (Fusion behind the proxy) once per application."""
    from .shell_style import AppStyle

    current = _state.get("style")
    if isinstance(current, AppStyle) and _state.get("style_app") is app:
        return
    style = AppStyle()
    app.setStyle(style)
    _state["style"] = style  # keep a Python reference
    _state["style_app"] = app


def _set_color_scheme(app: QApplication, requested: str) -> str:
    """Native title bar colour (QStyleHints.setColorScheme, pyqt-windows.md); "system" unsets it
    and reads the system scheme. Returns the resolved theme."""
    hints = app.styleHints()
    try:
        if requested in THEMES:
            hints.setColorScheme(Qt.ColorScheme.Dark if requested == "dark" else Qt.ColorScheme.Light)
            return requested
        hints.unsetColorScheme()
    except AttributeError:  # older Qt: nothing to do
        pass
    return resolve_theme("system")


def _on_system_scheme_changed(*_args: object) -> None:
    app = QApplication.instance()
    if app is not None and _state.get("requested") == "system" and not _state.get("applying"):
        if resolve_theme("system") != _state.get("name"):
            apply_theme(app, "system")  # type: ignore[arg-type]


def apply_theme(app: QApplication, name: ThemeName | str) -> str:
    """Fusion style + build_palette + build_qss for the resolved theme, then update() every
    widget. Returns the resolved name. (ui.app emits AppSignals.theme_changed afterwards.)"""
    requested = str(getattr(name, "value", name) or "dark").strip().lower()
    if requested not in THEMES and requested != "system":
        requested = "dark"
    install_style(app)
    _state["requested"] = requested  # before the scheme change: its signal must see the new request
    _state["applying"] = True
    try:
        resolved = _set_color_scheme(app, requested)
    finally:
        _state["applying"] = False
    _state["name"] = resolved
    if not _state.get("scheme_hooked"):
        try:
            app.styleHints().colorSchemeChanged.connect(_on_system_scheme_changed)
            _state["scheme_hooked"] = True
        except AttributeError:
            pass
    t = THEMES[resolved]
    app.setPalette(build_palette(t))
    app.setStyleSheet(build_qss(t))
    from . import icons

    icons.refresh_bound()
    for w in app.allWidgets():
        w.update()
    log.debug("theme applied: %s (requested %s)", resolved, requested)
    return resolved
