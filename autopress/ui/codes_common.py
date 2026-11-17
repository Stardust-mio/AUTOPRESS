# OWNED BY G6
"""Shared helpers of the Codes page and its import dialogs (private to G6).

* Code-format choices of the 格式 combos (SPEC 6.4.1): 自動偵測 (codes.presets.detect_format),
  設定檔格式 (the active profile's format) and every built-in preset except "custom" (which equals
  generic until the user edits it in a profile).
* The import target: game of the active profile (``game_key`` "" = 未指定遊戲 without a profile)
  and the history statuses to skip (Settings.skip_history_on_import).
* User-visible texts that several G6 modules show (7.1 wording where the SPEC gives one).
"""

from __future__ import annotations

import logging
import weakref
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PyQt6 import sip
from PyQt6.QtWidgets import QLabel

from ..codes import presets
from ..context import AppContext
from ..i18n import T, tr
from ..models import AddResult, CodeFormat, CodeStatus, Profile, clone

log = logging.getLogger(__name__)

AUTO_FORMAT = "auto"
PROFILE_FORMAT = "profile"

NOT_IMPLEMENTED = T("尚未實作", "Not implemented yet")
NO_PROFILE = T("先建立或選擇設定檔，才能開始兌換。", "Create or choose a profile to start redeeming.")
RUN_LOCKED = T("執行中，請先停止", "Running - stop the run first")
NO_CODES_FOUND = T("沒有找到符合格式的序號，請換一種序號格式或手動輸入。",
                   "No codes in this format; try another format or type them in.")
ELEVATED_DROP = T("以系統管理員身分執行時，無法從檔案總管拖放檔案，請改用「開啟檔案」。",
                  "While running as administrator, files cannot be dragged in from Explorer; use Open file.")
MANUAL_MARK = T("手動標記", "Marked manually")


def fit_wrapped_label(label: QLabel, max_width: int) -> None:
    """Give a word-wrapped label that sits in a layout with an alignment flag enough width and
    height for its text (QLabel's height-for-width is not honoured there, so the second line is
    cut off - seen with widgets.EmptyState's hint)."""
    width = min(max_width, label.fontMetrics().horizontalAdvance(label.text()) + 4)
    label.setMinimumWidth(width)
    label.setMinimumHeight(label.heightForWidth(width))


def game_name(profile: Profile | None) -> str:
    """Display name of the profile's game (the profile name when it has no game)."""
    if profile is None:
        return ""
    return profile.game.strip() or profile.name.strip() or tr("（未命名）", "(unnamed)")


def format_choices(profile: Profile | None) -> list[tuple[str, str]]:
    """(key, label) entries for a 格式 combo: AUTO_FORMAT, PROFILE_FORMAT (with a profile), preset ids."""
    out = [(AUTO_FORMAT, tr("自動偵測", "Auto-detect"))]
    if profile is not None:
        label = presets.format_label(profile.code_format.id)
        out.append((PROFILE_FORMAT, tr("設定檔格式（{label}）", "Profile format ({label})").format(label=label)))
    for fmt in presets.list_formats():
        if fmt.id != "custom":
            out.append((fmt.id, presets.format_label(fmt.id)))
    return out


def default_format_choice(profile: Profile | None) -> str:
    """自動偵測 without a profile or when the profile's format is "generic", else 設定檔格式."""
    if profile is None or profile.code_format.id == "generic":
        return AUTO_FORMAT
    return PROFILE_FORMAT


def resolve_format(choice: str, profile: Profile | None, text: str = "") -> tuple[CodeFormat, str]:
    """(format to use, detected preset id or "" when not auto-detecting)."""
    if choice == AUTO_FORMAT:
        if not text.strip():
            return presets.get_format("generic"), ""
        detected = presets.detect_format(text)
        return presets.get_format(detected), detected
    if choice == PROFILE_FORMAT and profile is not None:
        return clone(profile.code_format), ""
    if choice == PROFILE_FORMAT:
        return presets.get_format("generic"), ""
    return presets.get_format(choice), ""


@dataclass
class ImportTarget:
    """Where imported codes go: the active profile's game, and which history statuses skip a code."""

    game_key: str = ""
    game: str = ""
    skip_statuses: tuple[CodeStatus, ...] = ()
    profile: Profile | None = None

    @property
    def assigned(self) -> bool:
        return bool(self.game_key)


def import_target(ctx: AppContext, profile: Profile | None) -> ImportTarget:
    if profile is None:
        return ImportTarget()
    skip = tuple(CodeStatus(s) for s in ctx.settings.history_skip_statuses) if ctx.settings.skip_history_on_import else ()
    return ImportTarget(profile.game_key(), profile.game, skip, profile)


def skip_note(ctx: AppContext, profile: Profile | None) -> str:
    """Explanation under the 略過已兌換過的序號 switch."""
    if profile is None:
        return tr("（選擇設定檔後才會依遊戲比對紀錄）", "(needs an active profile: history is matched per game)")
    labels = "、".join(CodeStatus(s).label() for s in ctx.settings.history_skip_statuses) or "—"
    return tr("同一款遊戲紀錄為「{labels}」的序號不會再加入",
              "Codes whose history for this game says {labels} are not added again").format(labels=labels)


def add_result_message(res: AddResult, review: int = 0) -> tuple[str, str]:
    """(toast kind, text) for an import result."""
    skipped = []
    if res.duplicates:
        skipped.append(tr("{n} 筆重複", "{n} duplicate(s)").format(n=res.duplicates))
    if res.skipped_history:
        skipped.append(tr("{n} 筆已兌換過", "{n} already redeemed").format(n=res.skipped_history))
    if res.invalid:
        skipped.append(tr("{n} 筆格式不符", "{n} invalid").format(n=res.invalid))
    tail = tr("（略過 {parts}）", " (skipped {parts})").format(parts=tr("、", ", ").join(skipped)) if skipped else ""
    if not res.added:
        return "warning", tr("沒有加入新的序號", "No new codes were added") + tail
    text = tr("已加入 {n} 筆序號", "Added {n} code(s)").format(n=len(res.added)) + tail
    if review:
        text += tr("，其中 {r} 筆需要確認", "; {r} need review").format(r=review)
    return ("warning" if review else "success"), text


def once(fn: Callable[[], Any]) -> Callable[[], None]:
    """Wrap an unsubscribe function so that calling it twice is harmless."""
    done: list[bool] = []

    def run(*_args: Any) -> None:
        if done:
            return
        done.append(True)
        try:
            fn()
        except Exception:  # noqa: BLE001 - an unsubscribe must never break the caller
            log.debug("unsubscribe failed", exc_info=True)

    return run


def subscribe_weak(subscribe: Callable[[Callable[..., None]], Callable[[], Any]],
                   method: Callable[..., None]) -> Callable[[], None]:
    """Subscribe a bound method of a QObject to a store (CodeQueue / HistoryStore) without keeping
    the object alive; the subscription ends itself once the object is gone. Returns the
    (idempotent) unsubscribe function."""
    ref = weakref.WeakMethod(method)  # type: ignore[arg-type]
    box: list[Callable[[], None]] = []

    def callback(*args: Any) -> None:
        m = ref()
        owner = getattr(m, "__self__", None)
        if m is None or (isinstance(owner, sip.simplewrapper) and sip.isdeleted(owner)):
            if box:
                box[0]()
            return
        m(*args)

    box.append(once(subscribe(callback)))
    return box[0]
