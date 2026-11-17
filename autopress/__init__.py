"""AutoPress - general-purpose redeem-code auto-entry tool for Windows (PyQt6).

OWNED BY A1 (foundation). Groups read this module; they never edit it.
Importing the package has no side effects (no Qt, no ctypes, no file access).
"""

from __future__ import annotations

__all__ = ["APP_ID", "APP_NAME", "APP_NAME_ZH", "ORG_NAME", "__version__", "version_tuple"]

__version__ = "0.1.0"

APP_NAME = "AutoPress"
APP_NAME_ZH = "AutoPress 序號自動輸入"
APP_ID = "AutoPress"  # folder name under %APPDATA%, QApplication.applicationName()
ORG_NAME = "AutoPress"


def version_tuple() -> tuple[int, int, int]:
    """``__version__`` as a tuple of three ints (used by the PyInstaller version resource)."""
    parts = [int(p) for p in __version__.split(".")[:3]]
    while len(parts) < 3:
        parts.append(0)
    return parts[0], parts[1], parts[2]
