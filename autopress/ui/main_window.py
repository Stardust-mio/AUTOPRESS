# OWNED BY G5 - replace this stub
"""Main window shell: 220 px sidebar (logo, 序號 / 設定檔 / 執行 / 紀錄, bottom 設定 / 說明),
QStackedWidget of pages, always-on status bar, toasts (SPEC section 6.2)."""

from __future__ import annotations

from PyQt6.QtWidgets import QMainWindow, QWidget

from ..context import AppContext

__stub__ = True


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext) -> None:
        """Builds the pages: CodesPage(ctx), ProfilesPage(ctx), RunPage(ctx), HistoryPage(ctx),
        SettingsPage(ctx), HelpPage(ctx). A page whose constructor raises NotImplementedError
        is replaced by a "尚未實作 / Not implemented yet" placeholder. Connects
        ctx.signals.navigate, sets ctx.main_window, attaches ctx.hotkeys to its winId().
        closeEvent quits the application explicitly (the app does not quit on the last window,
        T02); during a run it asks first and then calls ctx.session.stop() before quitting."""
        raise NotImplementedError

    def navigate(self, page_id: str) -> None:
        """Show a page from context.PAGE_IDS (unknown ids are ignored)."""
        raise NotImplementedError

    def current_page(self) -> str:
        raise NotImplementedError

    def page(self, page_id: str) -> QWidget | None:
        raise NotImplementedError

    def set_badge(self, page_id: str, text: str) -> None:
        """Count pill on a sidebar item ("" hides it)."""
        raise NotImplementedError

    def set_status(self, key: str, text: str, tone: str = "neutral") -> None:
        """Status-bar item: key "target" | "ocr" | "guard" | "interval" | "run" (G5 creates them)."""
        raise NotImplementedError

    def set_run_mode(self, active: bool, minimize: bool = False) -> None:
        """True: remember geometry and hide (the mini bar takes over) - or, with ``minimize``,
        showMinimized() so the taskbar button stays (used when the mini bar is disabled);
        False: restore + raise (RunFlow does this for decisions during a paused run)."""
        raise NotImplementedError
