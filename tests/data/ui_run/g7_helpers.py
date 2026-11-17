# OWNED BY G7
"""Shared helpers for the G7 UI tests (tests/test_ui_profiles_*.py, tests/test_ui_run_*.py).

Not a test module (pytest only collects test_*.py). Import as ``tests.data.ui_run.g7_helpers``.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from PyQt6.QtWidgets import QWidget

from autopress.models import TargetMatch, WindowInfo


class FakeMainWindow(QWidget):
    """Records what RunFlow / the pages ask of the main window (the G5 API subset)."""

    def __init__(self) -> None:
        super().__init__()
        self.run_mode_calls: list[tuple[bool, bool]] = []
        self.navigated: list[str] = []
        self.pages: dict[str, QWidget] = {}

    def set_run_mode(self, active: bool, minimize: bool = False) -> None:
        self.run_mode_calls.append((bool(active), bool(minimize)))

    def navigate(self, page_id: str) -> None:
        self.navigated.append(page_id)

    def page(self, page_id: str) -> QWidget | None:
        return self.pages.get(page_id)


def attach_main_window(ctx: Any) -> FakeMainWindow:
    """ctx.main_window = a FakeMainWindow that also follows ctx.signals.navigate (as G5's does)."""
    mw = FakeMainWindow()
    ctx.main_window = mw
    ctx.signals.navigate.connect(mw.navigate)
    return mw


class DialogRecorder:
    """Stand-in for widgets.confirm / widgets.message: records titles and texts."""

    def __init__(self, answers: Iterable[bool] = (), default: bool = True) -> None:
        self.answers = list(answers)
        self.default = default
        self.confirms: list[tuple[str, str]] = []
        self.messages: list[tuple[str, str, str]] = []

    def confirm(self, parent: Any, title: str, text: str, ok_text: str | None = None,
                cancel_text: str | None = None, danger: bool = False) -> bool:
        self.confirms.append((title, text))
        return self.answers.pop(0) if self.answers else self.default

    def message(self, parent: Any, title: str, text: str, kind: str = "info") -> None:
        self.messages.append((title, text, kind))


def patch_dialogs(monkeypatch: Any, answers: Iterable[bool] = (), default: bool = True) -> DialogRecorder:
    from autopress.ui import widgets

    rec = DialogRecorder(answers, default)
    monkeypatch.setattr(widgets, "confirm", rec.confirm)
    monkeypatch.setattr(widgets, "message", rec.message)
    return rec


def window(hwnd: int, exe: str, title: str, cls: str = "Cls", client: tuple[int, int, int, int] = (100, 50, 1280, 720),
           minimized: bool = False) -> WindowInfo:
    return WindowInfo(hwnd=hwnd, title=title, class_name=cls, pid=hwnd * 10, exe_path=f"C:/Apps/{exe}",
                      rect=(client[0] - 8, client[1] - 31, client[2] + 16, client[3] + 39), client=client,
                      minimized=minimized)


def patch_target(monkeypatch: Any, info: WindowInfo | None, client: tuple[int, int, int, int] | None = None,
                 dpi: int = 96) -> None:
    """win32.windows.find_window / client_rect / window_dpi / is_minimized for one fake target."""
    from autopress.win32 import windows

    monkeypatch.setattr(windows, "find_window", lambda match: info if info is not None and isinstance(match, TargetMatch) else None)
    monkeypatch.setattr(windows, "client_rect", lambda hwnd: client or (info.client if info else (0, 0, 0, 0)))
    monkeypatch.setattr(windows, "window_dpi", lambda hwnd: dpi)
    monkeypatch.setattr(windows, "is_minimized", lambda hwnd: False)


__all__ = ["DialogRecorder", "FakeMainWindow", "attach_main_window", "patch_dialogs", "patch_target", "window"]
