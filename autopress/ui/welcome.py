# OWNED BY G5 - replace this stub
"""First-run welcome dialog (ux.md flow F1 step 1): what AutoPress does, the three rules (only
your own codes; official web pages are safer; you are responsible for each game's terms),
import profiles only from people you trust, language and theme choice, then "從範本建立設定檔"
(navigate to Profiles). ui.app shows it BEFORE MainWindow is built (parent None), so a language
picked here applies at once: set_language + translator switch, no restart (PX-28)."""

from __future__ import annotations

from PyQt6.QtWidgets import QDialog, QWidget

from ..context import AppContext

__stub__ = True


class WelcomeDialog(QDialog):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        raise NotImplementedError


def show_welcome_if_needed(ctx: AppContext, parent: QWidget | None = None) -> None:
    """Show WelcomeDialog when ``ctx.settings.first_run_done`` is False; set it afterwards."""
    raise NotImplementedError
