# OWNED BY G7 - replace this stub
"""Target-window picker: list of win32.windows.list_windows() (exe icon via
QFileIconProvider, title, exe name, 「系統管理員」 badge when elevation.input_permission is
BLOCKED_ELEVATED, 「未知權限」 when UNKNOWN), search, refresh, and 「點選視窗」 (overlays.pick
"window" crosshair). Windows of models.FORBIDDEN_TARGET_EXES are shown disabled with
「系統程式，不能當目標」; the profile's ``suggested_exe`` (imports) is listed first. Returns the
chosen WindowInfo; the caller stores info.to_target() (browser targets keep the title keyword
it contains; the user may shorten it, but not to empty)."""

from __future__ import annotations

from PyQt6.QtWidgets import QDialog, QWidget

from ..context import AppContext
from ..models import TargetMatch, WindowInfo

__stub__ = True


class WindowPickerDialog(QDialog):
    def __init__(self, ctx: AppContext, current: TargetMatch | None = None, parent: QWidget | None = None) -> None:
        raise NotImplementedError

    def selected(self) -> WindowInfo | None:
        raise NotImplementedError


def pick_target_window(ctx: AppContext, current: TargetMatch | None = None,
                       parent: QWidget | None = None) -> WindowInfo | None:
    """Modal convenience wrapper; None when cancelled."""
    raise NotImplementedError
