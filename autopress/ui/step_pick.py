# OWNED BY G7
"""Record step positions against the live target window (private helper of the step editor and
the setup wizard).

Positions are stored client-relative with the window DPI (SPEC 5.2):
``models.record_point(win32.windows.client_rect(hwnd), x, y, anchor, dpi=window_dpi(hwnd))``.
The picker overlay outlines the target's client rect; AutoPress's own windows are hidden while
picking (``hide_windows``) so they never end up in the frozen screenshot.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass

from PyQt6.QtWidgets import QWidget

from ..i18n import tr
from ..models import (
    Anchor,
    ClientPoint,
    ClientRegion,
    Profile,
    Rect,
    intersect_rect,
    point_in_rect,
    record_point,
    record_region,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TargetGeometry:
    hwnd: int
    client: Rect
    dpi: int


def window_not_found_text(profile: Profile) -> str:
    """SPEC 7.1 'window not found'."""
    target = profile.target.describe()
    return tr(f"找不到目標視窗：{target}。請先開啟遊戲或兌換網頁，或重新選擇視窗。",
              f"Target window not found: {target}. Open the game or redeem page first, or pick the window again.")


def resolve_target(profile: Profile) -> tuple[TargetGeometry | None, str]:
    """(geometry of the live target window, "") or (None, localized reason)."""
    if profile.target.is_empty():
        return None, tr("請先選擇目標視窗。", "Choose the target window first.")
    try:
        from ..win32 import windows

        info = windows.find_window(profile.target)
        if info is None:
            return None, window_not_found_text(profile)
        if info.minimized or windows.is_minimized(info.hwnd):
            return None, tr("目標視窗已最小化，請先把它還原到桌面上再點選位置。",
                            "The target window is minimized; restore it before picking positions.")
        client = tuple(windows.client_rect(info.hwnd))
        dpi = int(windows.window_dpi(info.hwnd) or 96)
    except NotImplementedError:
        return None, tr("這個功能還無法使用（視窗模組尚未完成）。", "Not available yet (the window module is missing).")
    except OSError as exc:
        log.info("target window vanished: %s", exc)
        return None, window_not_found_text(profile)
    if client[2] <= 0 or client[3] <= 0:
        return None, tr("目標視窗沒有可見的內容區，請把它還原或放大後再試。",
                        "The target window has no visible client area; restore or enlarge it and try again.")
    return TargetGeometry(info.hwnd, client, dpi), ""  # type: ignore[arg-type]


def hide_list(*widgets: QWidget | None) -> list[QWidget]:
    """Top-level windows to hide while picking (dialogs, the main window), without duplicates."""
    out: list[QWidget] = []
    for wdg in widgets:
        while wdg is not None:
            top = wdg.window()
            if top not in out:
                out.append(top)
            wdg = top.parentWidget()
    return out


def _fresh_client(geo: TargetGeometry) -> Rect:
    try:
        from ..win32 import windows

        rect = tuple(windows.client_rect(geo.hwnd))
        if rect[2] > 0 and rect[3] > 0:
            return rect  # type: ignore[return-value]
    except Exception as exc:
        log.debug("client_rect after pick failed: %s", exc)
    return geo.client


def pick_point(profile: Profile, instruction: str, *, anchor: Anchor | str = Anchor.TL,
               hide: Iterable[QWidget] = ()) -> tuple[ClientPoint | None, str]:
    """Let the user click a position on the target: (point, "") / (None, "") when cancelled /
    (None, localized error)."""
    geo, err = resolve_target(profile)
    if geo is None:
        return None, err
    from . import overlays

    res = overlays.pick("point", instruction=instruction, target_hwnd=geo.hwnd, hide_windows=list(hide))
    if res is None or res.point is None:
        return None, ""
    client = _fresh_client(geo)
    if not point_in_rect(client, res.point[0], res.point[1]):
        return None, tr("這個位置不在目標視窗的內容區內，請點在目標視窗裡面。",
                        "That position is outside the target window's client area; click inside the target.")
    return record_point(client, res.point[0], res.point[1], anchor=anchor, dpi=geo.dpi), ""


def pick_region(profile: Profile, instruction: str, *,
                hide: Iterable[QWidget] = ()) -> tuple[ClientRegion | None, str]:
    """Let the user drag a region on the target (clipped to the client area)."""
    geo, err = resolve_target(profile)
    if geo is None:
        return None, err
    from . import overlays

    res = overlays.pick("region", instruction=instruction, target_hwnd=geo.hwnd, hide_windows=list(hide))
    if res is None or res.rect is None:
        return None, ""
    client = _fresh_client(geo)
    rect = intersect_rect(res.rect, client)
    if rect is None or rect[2] < 2 or rect[3] < 2:
        return None, tr("這個範圍不在目標視窗的內容區內，請框在目標視窗裡面。",
                        "That region is outside the target window's client area; drag inside the target.")
    return record_region(client, *rect, dpi=geo.dpi), ""
