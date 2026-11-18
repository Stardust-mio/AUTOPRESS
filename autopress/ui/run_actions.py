# OWNED BY G7
"""Shared helpers of RunFlow, the Run page and the Profiles page (private G7 helper): target
lookup, target-from-window rules (browser title keyword), the dry-run preview (PreviewOverlay
on the live target, main window out of the way), the registry of the RunFlow that owns the
current run, and the preflight action buttons (SPEC 7.2 / 6.4.3)."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication, QWidget

from ..context import AppContext
from ..i18n import tr
from ..models import BROWSER_EXES, CodeStatus, PlanMode, Profile, TargetMatch, WindowInfo
from . import widgets as w

log = logging.getLogger(__name__)

_ACTIVE_FLOW = "g7.active_run_flow"
_PREVIEW = "g7.preview_overlay"
_BROWSER_WORDS = ("chrome", "edge", "firefox", "brave", "opera", "vivaldi", "whale", "chromium",
                  "internet explorer")


def call(fn: Callable[..., Any], *args: Any, default: Any = None, **kwargs: Any) -> Any:
    """Call another group's function; a stub (NotImplementedError) or an OS error gives
    ``default`` (logged), so pages keep working while modules are being integrated."""
    try:
        return fn(*args, **kwargs)
    except NotImplementedError:
        log.debug("%s is not implemented yet", getattr(fn, "__qualname__", fn))
    except Exception as exc:
        log.info("%s failed: %s", getattr(fn, "__qualname__", fn), exc)
    return default


def main_window(ctx: AppContext) -> QWidget | None:
    mw = getattr(ctx, "main_window", None)
    return mw if isinstance(mw, QWidget) else None


def active_flow(ctx: AppContext) -> Any:
    """The RunFlow that started the current run (None when idle)."""
    return ctx.extras.get(_ACTIVE_FLOW)


def set_active_flow(ctx: AppContext, flow: Any) -> None:
    if flow is None:
        ctx.extras.pop(_ACTIVE_FLOW, None)
    else:
        ctx.extras[_ACTIVE_FLOW] = flow


def dialog_parent(ctx: AppContext) -> QWidget | None:
    """The main window, or the mini bar while a run hides the main window (SPEC 2.8)."""
    mw = main_window(ctx)
    flow = active_flow(ctx)
    bar = getattr(flow, "minibar", None) if flow is not None else None
    if isinstance(bar, QWidget) and bar.isVisible() and (mw is None or not mw.isVisible()):
        return bar
    return mw


def find_target(profile: Profile | None) -> WindowInfo | None:
    if profile is None or profile.target.is_empty():
        return None
    from ..win32 import windows

    return call(windows.find_window, profile.target)


def title_keyword(info: WindowInfo) -> str:
    """The window title without the browser's own " - Google Chrome" style suffix."""
    title = (info.title or "").replace("\u200b", "").strip()
    if info.exe_name.casefold() not in BROWSER_EXES:
        return title
    parts = re.split(r"\s+[-–—]\s+", title)
    while len(parts) > 1 and any(word in parts[-1].casefold() for word in _BROWSER_WORDS):
        parts.pop()
    return " - ".join(parts).strip() or title


def target_from_window(info: WindowInfo) -> TargetMatch:
    """info.to_target() with the browser suffix removed from the title keyword."""
    target = info.to_target()
    target.title = title_keyword(info) or info.title
    target.allow_same_process = False
    return target


def window_not_found_text(profile: Profile) -> str:
    from .step_pick import window_not_found_text as text

    return text(profile)


# ----------------------------------------------------------------------------- preview


def preview_overlay(ctx: AppContext) -> Any:
    ov = ctx.extras.get(_PREVIEW)
    if ov is None:
        from .overlays import PreviewOverlay

        ov = PreviewOverlay()
        ctx.extras[_PREVIEW] = ov
    return ov


def show_preview(ctx: AppContext, profile: Profile, *, hwnd: int = 0, duration_ms: int = 6000,
                 wait: bool = False, parent: QWidget | None = None) -> bool:
    """Numbered markers on the live target for ``duration_ms`` (runner.preview.preview_profile);
    the main window is minimised meanwhile so the target is visible. False when nothing could
    be shown (the reason is shown to the user)."""
    parent = parent or dialog_parent(ctx)
    if not hwnd:
        info = find_target(profile)
        hwnd = info.hwnd if info is not None else 0
    if not hwnd:
        w.message(parent, tr("預覽點位", "Preview positions"), window_not_found_text(profile), "warning")
        return False
    try:
        from ..runner import preview

        marks = preview.preview_profile(profile, hwnd)
    except NotImplementedError:
        ctx.notify(tr("預覽點位尚未實作", "Preview is not implemented yet"), "warning")
        return False
    except Exception as exc:
        log.warning("preview failed: %s", exc)
        ctx.notify(tr(f"無法預覽點位：{exc}", f"Cannot preview the positions: {exc}"), "error")
        return False
    if not marks:
        w.message(parent, tr("預覽點位", "Preview positions"),
                  tr("這個設定檔還沒有任何已設定的位置可以預覽。", "This profile has no recorded positions yet."), "info")
        return False
    mw = main_window(ctx)
    minimized = False
    if mw is not None and mw.isVisible() and not mw.isMinimized():
        mw.showMinimized()
        minimized = True

    def restore() -> None:
        if minimized and mw is not None:
            mw.showNormal()
            mw.raise_()
            mw.activateWindow()

    preview_overlay(ctx).show_marks(marks, duration_ms)
    bad = sum(1 for m in marks if not m.ok)
    if bad:
        ctx.notify(tr(f"有 {bad} 個位置不在目標視窗上（紅色標記）", f"{bad} positions are not on the target (red)"),
                   "warning")
    if wait:
        loop = QEventLoop()
        QTimer.singleShot(max(0, duration_ms), loop.quit)
        loop.exec()
        restore()
    else:
        QTimer.singleShot(max(0, duration_ms), restore)
    return True


# ----------------------------------------------------------------------------- pages


def profiles_page(ctx: AppContext) -> Any:
    mw = main_window(ctx)
    page = call(mw.page, "profiles") if mw is not None and hasattr(mw, "page") else None
    return page if page is not None and hasattr(page, "open_profile") else None


def open_profile(ctx: AppContext, profile_id: str, realign: bool = False) -> bool:
    ctx.navigate("profiles")
    page = profiles_page(ctx)
    if page is None:
        return False
    page.open_profile(profile_id)
    if realign:
        page.start_wizard(profile_id, realign=True)
    return True


def apply_target(ctx: AppContext, profile_id: str, info: WindowInfo) -> Profile | None:
    """Store ``info`` as the profile's target (saved at once) and notify the pages."""
    stored = ctx.profiles.get(profile_id)
    if stored is None:
        return None
    stored.target = target_from_window(info)
    ctx.profiles.save(stored)
    ctx.signals.profiles_changed.emit()
    return stored


def first_runnable(ctx: AppContext, profile: Profile, selection: Any = None) -> str | None:
    from ..models import RunSelection

    items = call(ctx.queue.runnable, selection or RunSelection.UNFINISHED, profile.game_key(), default=[]) or []
    return items[0].id if items else None


def restart_as_admin_flow(parent: QWidget | None, ctx: AppContext | None = None) -> bool:
    """「以系統管理員身分重新啟動」 (the pre-flight action and the window picker's button): confirm,
    then - with ``ctx`` - ask Save / Discard / Cancel for unsaved profile edits, then start the
    elevated instance (win32.elevation.restart_as_admin) and quit. The question comes BEFORE the
    elevated instance starts: that instance waits only app.LOCK_WAIT_MS for this one to quit, so a
    question from MainWindow.closeEvent after it had started made a slow answer, or 取消, end with no
    AutoPress running. 取消 (or a failed save) starts nothing; 不儲存 takes effect only when the
    restart started, so a cancelled consent prompt (explained) keeps the edits, still unsaved. True
    when the restart was started."""
    title = tr("以系統管理員身分重新啟動", "Restart as administrator")
    text = tr("要以系統管理員身分重新啟動 AutoPress 嗎？\n\n以系統管理員身分執行時，無法從檔案總管拖放檔案，請改用「開啟檔案」。",
              "Restart AutoPress as administrator?\n\nWhile running as administrator, files cannot be dragged "
              "in from Explorer; use Open file.")
    if not w.confirm(parent, title, text, tr("重新啟動", "Restart"), tr("取消", "Cancel")):
        return False
    page = profiles_page(ctx) if ctx is not None else None
    discard = False
    if page is not None and callable(getattr(page, "is_dirty", None)) and page.is_dirty():
        from . import profiles_dialogs

        profile = page.working_profile() if callable(getattr(page, "working_profile", None)) else None
        answer = profiles_dialogs.ask_save_changes(parent, getattr(profile, "name", "") or "")
        if answer == "save":
            if not page.save_profile():
                return False  # not saved (a storage error or the newer-version warning): keep running
        elif answer == "discard":
            discard = True
        else:
            return False  # 取消: nothing was started
    from ..win32 import elevation

    if call(elevation.restart_as_admin, default=False):
        if discard:
            call(page.discard_changes)  # closing must not ask again: the new instance is already waiting
        QApplication.quit()
        return True
    w.message(parent, title,
              tr("沒有重新啟動（可能取消了權限提示）。", "AutoPress was not restarted (the prompt may have been cancelled)."),
              "warning")
    return False


def perform_action(ctx: AppContext, action: str, profile: Profile, parent: QWidget | None = None,
                   flow: Any = None, code_ids: list[str] | None = None) -> bool:
    """Run a preflight action button (models.PREFLIGHT_ACTIONS). True when something changed
    and the preflight should be repeated."""
    parent = parent or dialog_parent(ctx)
    if action == "restart_admin":
        restart_as_admin_flow(parent, ctx)
        return False
    if action == "pick_window":
        from .window_picker import pick_target_window

        info = pick_target_window(ctx, profile.target, parent, suggested_exe=profile.suggested_exe)
        if info is None:
            return False
        apply_target(ctx, profile.id, info)
        return True
    if action == "preview":
        show_preview(ctx, profile, parent=parent)
        return False
    if action == "open_profile":
        if not open_profile(ctx, profile.id):
            ctx.notify(tr("請到「設定檔」頁修改這個設定檔。", "Open the Profiles page to edit this profile."), "info")
        return False
    if action == "realign":
        if not open_profile(ctx, profile.id, realign=True):
            ctx.notify(tr("請到「設定檔」頁按「重新對準」。", "Open the Profiles page and click Re-align."), "info")
        return True
    if action == "wait_ocr":
        state = str(getattr(ctx.ocr, "state", ""))
        if state.endswith("not_started"):
            call(ctx.ocr.start)
        ctx.notify(tr("文字辨識引擎載入中，就緒後會自動重新檢查。", "The OCR engine is loading; the check repeats when it is ready."),
                   "info")
        return False
    if action == "assign_codes":
        ids = [i.id for i in ctx.queue.items() if not i.game_key and i.status is not CodeStatus.RUNNING]
        n = call(ctx.queue.assign_game, ids, profile.game_key(), profile.game, default=0) or 0
        game = profile.game or profile.name
        ctx.notify(tr(f"已把 {n} 筆序號指定給「{game}」", f"Assigned {n} codes to '{game}'"), "success")
        return True
    if action == "test_one":
        if flow is None:
            return False
        ids = code_ids or ([first_runnable(ctx, profile)] if first_runnable(ctx, profile) else None)
        flow.begin(profile, mode=PlanMode.TEST_ONE, code_ids=ids)
        return True
    log.debug("unknown preflight action %r", action)
    return False


def monitor_rect_for(rect: tuple[int, int, int, int] | None) -> tuple[int, int, int, int] | None:
    """Physical rect of the monitor that shows most of ``rect`` (None = unknown)."""
    if rect is None:
        return None
    from .overlays_geom import monitor_rects, overlap_area

    mons = monitor_rects()
    best = max(mons, key=lambda m: overlap_area(m, rect), default=None)
    return best if best is not None and overlap_area(best, rect) > 0 else (mons[0] if mons else None)


def countdown_hint(ctx: AppContext) -> str:
    """「F9 停止 · 滑鼠移到 ↖ 這個角落＝緊急停止」 with the configured stop key."""
    stop = ctx.settings.hotkeys.stop
    if ctx.settings.failsafe_enabled:
        return tr(f"{stop} 停止 · 滑鼠移到 ↖ 這個角落＝緊急停止", f"{stop} stops · mouse to the ↖ corner = emergency stop")
    return tr(f"{stop} 停止", f"{stop} stops")


def action_label(action: str, profile: Profile | None = None) -> str:
    if action == "assign_codes" and profile is not None:
        game = profile.game or profile.name
        return tr(f"指定給「{game}」", f"Assign to \"{game}\"")
    return {
        "restart_admin": tr("以系統管理員身分重新啟動", "Restart as administrator"),
        "pick_window": tr("選擇視窗", "Choose window"),
        "preview": tr("預覽點位", "Preview positions"),
        "open_profile": tr("編輯設定檔", "Edit profile"),
        "wait_ocr": tr("啟動文字辨識", "Start OCR"),
        "assign_codes": tr("指定給這款遊戲", "Assign to this game"),
        "test_one": tr("測試一筆", "Test one"),
        "realign": tr("重新對準", "Re-align"),
    }.get(action, action)


__all__ = [
    "action_label",
    "active_flow",
    "countdown_hint",
    "monitor_rect_for",
    "apply_target",
    "call",
    "dialog_parent",
    "find_target",
    "first_runnable",
    "main_window",
    "open_profile",
    "perform_action",
    "preview_overlay",
    "profiles_page",
    "restart_as_admin_flow",
    "set_active_flow",
    "show_preview",
    "target_from_window",
    "title_keyword",
    "window_not_found_text",
]
