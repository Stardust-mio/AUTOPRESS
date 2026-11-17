# OWNED BY G5 - replace this stub
"""Original 24x24 line icons (stroke 1.8, round caps) as inline SVG, rendered with QSvgRenderer
at the device pixel ratio and recoloured per theme (port ICONS / icon_pixmap from
docs/research/scripts/ux/prototype.py). No third-party icon pack.
"""

from __future__ import annotations

from PyQt6.QtGui import QIcon, QPixmap

__stub__ = True

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


def icon(name: str, color_token: str = "text_secondary", size: int = 16) -> QIcon:
    """Icon in the colour of an active-theme token (or a literal "#RRGGBB")."""
    raise NotImplementedError


def icon_pixmap(name: str, color: str, size: int = 18, stroke: float = 1.8) -> QPixmap:
    """Cached pixmap at the primary screen's dpr; ``color`` is a token or "#RRGGBB"."""
    raise NotImplementedError


def app_icon() -> QIcon:
    """Window icon rendered from "logo" at 16-256 px."""
    raise NotImplementedError
