"""AutoPress shared data model: enums, dataclasses, JSON (de)serialisation, validation and the
client-relative coordinate math.

OWNED BY A1 (foundation). Groups import from here and NEVER edit this file; if something is
missing, add it in your own module and report it.

Conventions
* Every dataclass field has a default, so ``X()`` is always a valid object.
* ``to_dict(obj)`` gives a JSON-ready value; ``from_dict(cls, data)`` builds an instance.
  Loading is forward compatible: unknown keys are ignored, missing or invalid values fall
  back to the field default, numbers are clamped to the field's ``range`` metadata, unknown
  enum values fall back to the default, unknown step types are kept verbatim (``StepType.UNKNOWN``
  + ``UnknownParams``). Other unknown keys of a newer file ARE lost on re-save, so saving always
  writes the CURRENT ``schema_version`` (storage) and the UI warns before saving a newer profile.
  A recorded point / region with a missing or unusable coordinate loads as None (position not
  set), and positional lists (``_strict_list`` fields) are rejected whole when one element is bad.
* Files carry ``schema_version``; ``migrate(kind, data)`` upgrades old data step by step.
* Enum values are the JSON strings. Labels are resolved lazily (``.label()`` calls
  ``i18n.tr`` at call time) - never call ``tr`` at import time.
* Geometry is in PHYSICAL pixels (AutoPress is per-monitor-v2 DPI aware after QApplication
  exists). ``Rect`` = (x, y, w, h); profile points/regions are stored relative to the target
  window's CLIENT area (win32_windows.md section 6, verified math from wb_coords.py).
"""

from __future__ import annotations

import dataclasses
import enum
import logging
import math
import re
import types
import typing
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TypeVar

from .i18n import get_language, tr
from .textutil import clean_text, fuzzy_contains, split_alternatives, squash

log = logging.getLogger(__name__)

T_ = TypeVar("T_")

Rect = tuple[int, int, int, int]  # x, y, w, h in physical screen pixels
Point = tuple[int, int]  # x, y in physical screen pixels

PROFILE_SCHEMA_VERSION = 1
SETTINGS_SCHEMA_VERSION = 1
QUEUE_SCHEMA_VERSION = 1
HISTORY_SCHEMA_VERSION = 1
PROFILE_FILE_SUFFIX = ".autopress.json"


# =============================================================================== small helpers


def new_id() -> str:
    """Random 16-hex-digit id (profiles, steps, code items, attempts, runs)."""
    return uuid.uuid4().hex[:16]


def now_iso() -> str:
    """Local time with UTC offset, second precision: ``2026-11-17T15:04:05+08:00``."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _num(default: Any, lo: float | None = None, hi: float | None = None) -> Any:
    """Dataclass field with a numeric range; ``from_dict`` clamps loaded values into it."""
    return field(default=default, metadata={"range": (lo, hi)})


def _strict_list() -> Any:
    """List field whose elements are positional (sizes, coordinates, per-character values):
    ``from_dict`` rejects the WHOLE list (field default) when any element is invalid."""
    return field(default_factory=list, metadata={"strict": True})


def _clamp(value: Any, rng: tuple[float | None, float | None]) -> Any:
    lo, hi = rng
    if lo is not None and value < lo:
        value = type(value)(lo)
    if hi is not None and value > hi:
        value = type(value)(hi)
    return value


# =============================================================================== enums


class CodeStatus(enum.StrEnum):
    """State of one code in the queue (and the final status of a history record)."""

    PENDING = "pending"  # 待兌換: not tried yet (or interrupted before submit)
    REVIEW = "review"  # 需確認: OCR look-alikes, unknown result, or interrupted after submit
    RUNNING = "running"  # 兌換中
    SUCCESS = "success"  # 成功
    SUBMITTED = "submitted"  # 已送出（未確認）: submitted, but the profile has no result check
    USED = "used"  # 已使用
    INVALID = "invalid"  # 無效
    EXPIRED = "expired"  # 已過期
    COOLDOWN = "cooldown"  # 冷卻中: rate-limited, will be retried
    FAILED = "failed"  # 失敗: step error, ineligible (region/level/cap) ...
    SKIPPED = "skipped"  # 已略過: duplicate / already in history / user

    def label(self) -> str:
        zh, en, _tone, _glyph = _STATUS_INFO[self]
        return tr(zh, en)

    @property
    def tone(self) -> str:
        """Theme tone token prefix: neutral, warning, accent, success, violet, error, orange, info."""
        return _STATUS_INFO[self][2]

    @property
    def glyph(self) -> str:
        """Chip glyph: "dot", "ring" or "dash"."""
        return _STATUS_INFO[self][3]

    @property
    def is_runnable(self) -> bool:
        """Will be picked up by a run (PENDING, COOLDOWN)."""
        return self in (CodeStatus.PENDING, CodeStatus.COOLDOWN)

    @property
    def is_done(self) -> bool:
        """Finished for good (counts as "completed" in filters)."""
        return self in (CodeStatus.SUCCESS, CodeStatus.SUBMITTED, CodeStatus.USED,
                        CodeStatus.INVALID, CodeStatus.EXPIRED, CodeStatus.SKIPPED)


_STATUS_INFO: dict[CodeStatus, tuple[str, str, str, str]] = {
    CodeStatus.PENDING: ("待兌換", "Pending", "neutral", "ring"),
    CodeStatus.REVIEW: ("需確認", "Needs review", "warning", "dot"),
    CodeStatus.RUNNING: ("兌換中", "Running", "accent", "dot"),
    CodeStatus.SUCCESS: ("成功", "Redeemed", "success", "dot"),
    CodeStatus.SUBMITTED: ("已送出（未確認）", "Submitted (unconfirmed)", "success", "ring"),
    CodeStatus.USED: ("已使用", "Already used", "violet", "dot"),
    CodeStatus.INVALID: ("無效", "Invalid", "error", "dot"),
    CodeStatus.EXPIRED: ("已過期", "Expired", "orange", "dot"),
    CodeStatus.COOLDOWN: ("冷卻中", "Rate-limited", "info", "dot"),
    CodeStatus.FAILED: ("失敗", "Failed", "error", "ring"),
    CodeStatus.SKIPPED: ("已略過", "Skipped", "neutral", "dash"),
}


class ResultClass(enum.StrEnum):
    """Classification of a redemption result message (runner.classify)."""

    SUCCESS = "success"
    USED = "used"
    INVALID = "invalid"
    EXPIRED = "expired"
    RATE_LIMITED = "rate_limited"
    INELIGIBLE = "ineligible"  # region / server / level / usage cap
    UNKNOWN = "unknown"

    def label(self) -> str:
        zh, en = _RESULT_LABELS[self]
        return tr(zh, en)


_RESULT_LABELS: dict[ResultClass, tuple[str, str]] = {
    ResultClass.SUCCESS: ("成功", "Success"),
    ResultClass.USED: ("已使用", "Already used"),
    ResultClass.INVALID: ("無效", "Invalid"),
    ResultClass.EXPIRED: ("已過期", "Expired"),
    ResultClass.RATE_LIMITED: ("操作過於頻繁", "Rate-limited"),
    ResultClass.INELIGIBLE: ("不符資格（伺服器／等級／上限）", "Not eligible (server / level / limit)"),
    ResultClass.UNKNOWN: ("無法判讀", "Unknown"),
}


def status_for_result(result: ResultClass | None) -> CodeStatus:
    """Queue status after an attempt: None (no result check) -> SUBMITTED; RATE_LIMITED ->
    COOLDOWN; INELIGIBLE -> FAILED; UNKNOWN -> REVIEW; the rest map 1:1."""
    if result is None:
        return CodeStatus.SUBMITTED
    return {
        ResultClass.SUCCESS: CodeStatus.SUCCESS,
        ResultClass.USED: CodeStatus.USED,
        ResultClass.INVALID: CodeStatus.INVALID,
        ResultClass.EXPIRED: CodeStatus.EXPIRED,
        ResultClass.RATE_LIMITED: CodeStatus.COOLDOWN,
        ResultClass.INELIGIBLE: CodeStatus.FAILED,
        ResultClass.UNKNOWN: CodeStatus.REVIEW,
    }[result]


class CodeSource(enum.StrEnum):
    PASTE = "paste"
    FILE = "file"
    IMAGE = "image"
    CLIPBOARD = "clipboard"  # clipboard image
    SNIP = "snip"  # screen region
    MANUAL = "manual"

    def label(self) -> str:
        zh, en, _icon = _SOURCE_INFO[self]
        return tr(zh, en)

    @property
    def icon(self) -> str:
        return _SOURCE_INFO[self][2]

    @property
    def is_ocr(self) -> bool:
        return self in (CodeSource.IMAGE, CodeSource.CLIPBOARD, CodeSource.SNIP)


_SOURCE_INFO: dict[CodeSource, tuple[str, str, str]] = {
    CodeSource.PASTE: ("貼上", "Paste", "paste"),
    CodeSource.FILE: ("檔案", "File", "file"),
    CodeSource.IMAGE: ("圖片", "Image", "image"),
    CodeSource.CLIPBOARD: ("剪貼簿", "Clipboard", "clipimage"),
    CodeSource.SNIP: ("截圖", "Screen", "snip"),
    CodeSource.MANUAL: ("手動", "Manual", "edit"),
}


class StepType(enum.StrEnum):
    FOCUS_WINDOW = "focus_window"
    CLICK_POINT = "click_point"
    CLICK_TEXT = "click_text"
    TYPE_CODE = "type_code"
    TYPE_TEXT = "type_text"
    KEY = "key"
    WAIT = "wait"
    WAIT_TEXT = "wait_text"
    OCR_CHECK = "ocr_check"
    UNKNOWN = "unknown"  # loaded from a newer version; skipped at run time, kept on save

    def label(self) -> str:
        zh, en, _icon = _STEP_INFO[self]
        return tr(zh, en)

    @property
    def icon(self) -> str:
        """Icon name in ui.icons.ICONS (G5 must provide every one of these)."""
        return _STEP_INFO[self][2]

    @property
    def uses_ocr(self) -> bool:
        return self in (StepType.CLICK_TEXT, StepType.WAIT_TEXT, StepType.OCR_CHECK)

    @property
    def sends_input(self) -> bool:
        return self in (StepType.CLICK_POINT, StepType.CLICK_TEXT, StepType.TYPE_CODE,
                        StepType.TYPE_TEXT, StepType.KEY)


_STEP_INFO: dict[StepType, tuple[str, str, str]] = {
    StepType.FOCUS_WINDOW: ("切換到視窗", "Focus window", "target"),
    StepType.CLICK_POINT: ("點擊位置", "Click position", "pointer"),
    StepType.CLICK_TEXT: ("點擊文字（OCR）", "Click text (OCR)", "text_search"),
    StepType.TYPE_CODE: ("輸入序號", "Type code", "keyboard"),
    StepType.TYPE_TEXT: ("輸入文字", "Type text", "type"),
    StepType.KEY: ("按鍵／組合鍵", "Key / shortcut", "keycap"),
    StepType.WAIT: ("等待", "Wait", "clock"),
    StepType.WAIT_TEXT: ("等待文字出現", "Wait for text", "eye"),
    StepType.OCR_CHECK: ("辨識結果", "Read result", "scan"),
    StepType.UNKNOWN: ("未知步驟", "Unknown step", "alert"),
}


class TypingMode(enum.StrEnum):
    UNICODE = "unicode"  # KEYEVENTF_UNICODE, one atomic SendInput per character (default)
    CLIPBOARD = "clipboard"  # set clipboard + Ctrl+V, restore the clipboard afterwards
    VK = "vk"  # virtual-key + scan code ("game mode"; closes the target's IME while typing)

    def label(self) -> str:
        return {
            TypingMode.UNICODE: tr("模擬鍵入（建議）", "Simulated typing (recommended)"),
            TypingMode.CLIPBOARD: tr("貼上（剪貼簿）", "Paste (clipboard)"),
            TypingMode.VK: tr("遊戲模式（按鍵碼）", "Game mode (key codes)"),
        }[self]


class ClearMethod(enum.StrEnum):
    CTRL_A = "ctrl_a"  # Ctrl+A, Backspace
    END_SHIFT_HOME = "end_shift_home"  # End, Shift+Home, Delete
    BACKSPACE = "backspace"  # End + 40 x Backspace

    def label(self) -> str:
        return {
            ClearMethod.CTRL_A: tr("Ctrl+A 後刪除", "Ctrl+A, then delete"),
            ClearMethod.END_SHIFT_HOME: tr("End、Shift+Home 後刪除", "End, Shift+Home, delete"),
            ClearMethod.BACKSPACE: tr("連按退格鍵", "Repeated Backspace"),
        }[self]


class SplitMode(enum.StrEnum):
    NONE = "none"  # type the whole code into one field
    SEPARATOR = "separator"  # split on separator characters (e.g. "-")
    FIXED = "fixed"  # split into fixed group sizes (e.g. 5,5,5)

    def label(self) -> str:
        return {
            SplitMode.NONE: tr("不拆段", "Do not split"),
            SplitMode.SEPARATOR: tr("依分隔符號拆段", "Split at separators"),
            SplitMode.FIXED: tr("依固定字數拆段", "Split into fixed lengths"),
        }[self]


class BetweenSegments(enum.StrEnum):
    TAB = "tab"  # press Tab between segments
    NONE = "none"  # the page jumps to the next box by itself

    def label(self) -> str:
        return {BetweenSegments.TAB: tr("段與段之間按 Tab", "Press Tab between segments"),
                BetweenSegments.NONE: tr("不按（輸入框會自動跳格）", "Nothing (fields advance by themselves)")}[self]


class TextMatch(enum.StrEnum):
    EXACT = "exact"  # whole OCR line equals the text (after NFKC/casefold/no spaces) - safest
    CONTAINS = "contains"  # OCR line contains the text
    REGEX = "regex"  # Python regex searched in the OCR line text

    def label(self) -> str:
        return {TextMatch.EXACT: tr("完全相同", "Exact"), TextMatch.CONTAINS: tr("包含", "Contains"),
                TextMatch.REGEX: tr("正規表示式", "Regular expression")}[self]


class MouseButton(enum.StrEnum):
    LEFT = "left"
    RIGHT = "right"
    MIDDLE = "middle"

    def label(self) -> str:
        return {MouseButton.LEFT: tr("左鍵", "Left"), MouseButton.RIGHT: tr("右鍵", "Right"),
                MouseButton.MIDDLE: tr("中鍵", "Middle")}[self]


class Anchor(enum.StrEnum):
    """Which client edge an offset-mode point keeps its distance to."""

    TL = "tl"
    TR = "tr"
    BL = "bl"
    BR = "br"
    CENTER = "center"


class CoordMode(enum.StrEnum):
    AUTO = "auto"  # offset when the client size is unchanged, otherwise ratio
    OFFSET = "offset"  # exact pixels from the anchor
    RATIO = "ratio"  # scale with the client size

    def label(self) -> str:
        return {CoordMode.AUTO: tr("自動（建議）", "Automatic (recommended)"),
                CoordMode.OFFSET: tr("固定像素", "Fixed pixels"),
                CoordMode.RATIO: tr("依視窗比例", "Scale with window")}[self]


class TitleMatch(enum.StrEnum):
    CONTAINS = "contains"
    EXACT = "exact"
    REGEX = "regex"
    ANY = "any"

    def label(self) -> str:
        return {TitleMatch.CONTAINS: tr("標題包含", "Title contains"), TitleMatch.EXACT: tr("標題完全相同", "Title equals"),
                TitleMatch.REGEX: tr("標題符合正規表示式", "Title matches regex"), TitleMatch.ANY: tr("任何標題", "Any title")}[self]


class RateLimitAction(enum.StrEnum):
    STOP = "stop"
    COOLDOWN = "cooldown"  # wait policy.cooldown_s, then retry the same code


class UnknownAction(enum.StrEnum):
    PAUSE = "pause"  # pause and ask the user (default)
    CONTINUE = "continue"  # mark REVIEW and go on
    STOP = "stop"


class TimeoutAction(enum.StrEnum):
    FAIL = "fail"  # the code fails
    CONTINUE = "continue"  # go on with the next step


class Language(enum.StrEnum):
    AUTO = "auto"
    ZH_TW = "zh-TW"
    EN = "en"


class ThemeName(enum.StrEnum):
    DARK = "dark"
    LIGHT = "light"
    SYSTEM = "system"


class RunSelection(enum.StrEnum):
    UNFINISHED = "unfinished"  # every runnable code, in queue order
    CHECKED = "checked"  # only runnable codes whose checkbox is ticked

    def label(self) -> str:
        return {RunSelection.UNFINISHED: tr("全部未完成", "All unfinished"),
                RunSelection.CHECKED: tr("只跑勾選的", "Checked only")}[self]


class RunState(enum.StrEnum):
    IDLE = "idle"
    STARTING = "starting"  # preflight passed, countdown / thread start
    RUNNING = "running"
    PAUSING = "pausing"  # pause requested, finishing the current code
    PAUSED = "paused"
    COOLDOWN = "cooldown"  # rate-limit cool-down
    STOPPING = "stopping"
    FINISHED = "finished"

    def label(self) -> str:
        return {
            RunState.IDLE: tr("待命", "Idle"), RunState.STARTING: tr("準備中", "Starting"),
            RunState.RUNNING: tr("執行中", "Running"), RunState.PAUSING: tr("即將暫停", "Pausing"),
            RunState.PAUSED: tr("已暫停", "Paused"), RunState.COOLDOWN: tr("冷卻中", "Cooling down"),
            RunState.STOPPING: tr("正在停止", "Stopping"), RunState.FINISHED: tr("已結束", "Finished"),
        }[self]


class PauseReason(enum.StrEnum):
    USER = "user"  # button / pause hotkey
    FOCUS_LOST = "focus_lost"  # target is no longer the foreground window
    USER_INPUT = "user_input"  # physical mouse/keyboard input detected
    POINT_BLOCKED = "point_blocked"  # click point is covered by another window
    TARGET_LOST = "target_lost"  # target window closed / not found
    UNKNOWN_RESULT = "unknown_result"  # result message matched no keyword group (or was ambiguous)
    ERROR = "error"  # unexpected error, input blocked by Windows, ... (Attention carries the text)
    TITLE_CHANGED = "title_changed"  # the target's title no longer matches profile.target (tab changed)
    SIZE_CHANGED = "size_changed"  # the client size differs from the size at run start
    CAPTURE_BLANK = "capture_blank"  # captures are black / uniform (exclusive fullscreen, locked screen)
    INVALID_STREAK = "invalid_streak"  # RunPolicy.pause_after_invalid INVALID results in a row

    def label(self) -> str:
        return {
            PauseReason.USER: tr("使用者暫停", "Paused by you"),
            PauseReason.FOCUS_LOST: tr("目標視窗失去焦點", "The target window lost focus"),
            PauseReason.USER_INPUT: tr("偵測到滑鼠或鍵盤操作", "Mouse or keyboard input detected"),
            PauseReason.POINT_BLOCKED: tr("點擊位置被其他視窗遮住", "The click position is covered by another window"),
            PauseReason.TARGET_LOST: tr("找不到目標視窗", "The target window was not found"),
            PauseReason.UNKNOWN_RESULT: tr("無法判讀兌換結果", "The result could not be recognised"),
            PauseReason.ERROR: tr("發生錯誤", "An error occurred"),
            PauseReason.TITLE_CHANGED: tr("目標頁面標題已改變", "The target page title changed"),
            PauseReason.SIZE_CHANGED: tr("視窗大小改變了", "The window size changed"),
            PauseReason.CAPTURE_BLANK: tr("擷取到的畫面是全黑或單色", "The capture is black or uniform"),
            PauseReason.INVALID_STREAK: tr("連續多筆被判定無效", "Several codes in a row were judged invalid"),
        }[self]

    @property
    def opens_main_window(self) -> bool:
        """Pauses that need a decision: RunFlow restores the main window on the Run page (SPEC 2.4).
        USER, USER_INPUT, FOCUS_LOST and POINT_BLOCKED stay on the mini bar."""
        return self not in (PauseReason.USER, PauseReason.USER_INPUT, PauseReason.FOCUS_LOST,
                            PauseReason.POINT_BLOCKED)


class StopReason(enum.StrEnum):
    COMPLETED = "completed"
    USER = "user"  # button / stop hotkey
    FAILSAFE = "failsafe"  # mouse in the failsafe corner
    RATE_LIMITED = "rate_limited"
    FAILURES = "failures"  # too many consecutive failures
    TARGET_LOST = "target_lost"
    ERROR = "error"

    def label(self) -> str:
        return {
            StopReason.COMPLETED: tr("全部完成", "All done"),
            StopReason.USER: tr("使用者停止", "Stopped by you"),
            StopReason.FAILSAFE: tr("緊急停止（滑鼠移到左上角）", "Emergency stop (mouse in the top-left corner)"),
            StopReason.RATE_LIMITED: tr("操作過於頻繁，已停止", "Stopped: rate-limited"),
            StopReason.FAILURES: tr("連續失敗次數過多，已停止", "Stopped: too many failures in a row"),
            StopReason.TARGET_LOST: tr("找不到目標視窗，已停止", "Stopped: target window not found"),
            StopReason.ERROR: tr("發生錯誤，已停止", "Stopped: an error occurred"),
        }[self]


class PlanMode(enum.StrEnum):
    NORMAL = "normal"
    TEST_ONE = "test_one"  # one code, normal bookkeeping
    TEST_STEP = "test_step"  # one step with a sample code; no queue/history changes


class LogLevel(enum.StrEnum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


class IssueLevel(enum.StrEnum):
    ERROR = "error"  # blocks running
    WARNING = "warning"
    INFO = "info"


class PreviewKind(enum.StrEnum):
    POINT = "point"
    REGION = "region"
    SEARCH_REGION = "search_region"  # OCR search area of click_text / wait_text
    FALLBACK_POINT = "fallback_point"


class QueueEventKind(enum.StrEnum):
    RESET = "reset"  # whole list replaced / reloaded
    ADDED = "added"
    UPDATED = "updated"
    REMOVED = "removed"
    MOVED = "moved"


# =============================================================================== key names

_MODIFIERS = ("Ctrl", "Shift", "Alt", "Win")
_NAMED_KEYS = ("Enter", "Esc", "Tab", "Space", "Backspace", "Delete", "Insert", "Home", "End",
               "PageUp", "PageDown", "Up", "Down", "Left", "Right")
KEY_NAMES: frozenset[str] = frozenset(
    list(_MODIFIERS) + list(_NAMED_KEYS)
    + [chr(c) for c in range(ord("A"), ord("Z") + 1)]
    + [str(d) for d in range(10)]
    + [f"F{i}" for i in range(1, 25)]
)
"""Canonical key names accepted in key steps and hotkeys (win32.keys maps them to VKs)."""

_KEY_ALIASES: dict[str, str] = {
    "control": "Ctrl", "ctl": "Ctrl", "meta": "Win", "windows": "Win", "super": "Win",
    "return": "Enter", "escape": "Esc", "spacebar": "Space", "bksp": "Backspace", "bs": "Backspace",
    "del": "Delete", "ins": "Insert", "pgup": "PageUp", "pgdn": "PageDown", "pagedn": "PageDown",
    "arrowup": "Up", "arrowdown": "Down", "arrowleft": "Left", "arrowright": "Right",
}
_KEY_LOOKUP: dict[str, str] = {k.lower(): k for k in KEY_NAMES} | _KEY_ALIASES


def parse_combo_names(text: str) -> list[str]:
    """Parse ``"ctrl+shift+a"`` -> ``["Ctrl", "Shift", "A"]`` (modifiers first, in the order
    Ctrl, Shift, Alt, Win, then exactly one non-modifier key). Raises ValueError (message in
    English) for unknown names, duplicates, no key, or more than one non-modifier key."""
    raw = [p.strip() for p in (text or "").replace(" ", "").split("+")]
    if not raw or any(not p for p in raw):
        raise ValueError(f"empty key name in {text!r}")
    names: list[str] = []
    for p in raw:
        name = _KEY_LOOKUP.get(p.lower())
        if name is None:
            raise ValueError(f"unknown key {p!r}")
        if name in names:
            raise ValueError(f"duplicate key {name!r}")
        names.append(name)
    mods = [n for n in _MODIFIERS if n in names]
    keys = [n for n in names if n not in _MODIFIERS]
    if len(keys) != 1:
        raise ValueError("exactly one non-modifier key is required")
    return mods + keys


def format_combo(names: list[str]) -> str:
    """``["Ctrl", "A"]`` -> ``"Ctrl+A"``."""
    return "+".join(names)


def normalize_combo(text: str) -> str:
    """Canonical spelling (``"ctrl + a"`` -> ``"Ctrl+A"``); ValueError if invalid."""
    return format_combo(parse_combo_names(text))


def validate_hotkey(text: str) -> str | None:
    """None if ``text`` may be a global hotkey, else a localized reason. Rules: valid combo;
    no Win modifier (reserved by Windows); F12 is reserved for debuggers; a key without
    Ctrl/Alt must be F1-F24 (a bare letter would be swallowed system-wide)."""
    try:
        names = parse_combo_names(text)
    except ValueError:
        return tr("無法辨識的按鍵組合", "Unrecognised key combination")
    key = names[-1]
    if "Win" in names:
        return tr("不能使用 Win 鍵（保留給 Windows）", "The Win key is reserved by Windows")
    if key == "F12":
        return tr("F12 保留給偵錯工具，請改用其他按鍵", "F12 is reserved for debuggers; choose another key")
    is_fkey = key.startswith("F") and key[1:].isdigit()
    if not is_fkey and not ({"Ctrl", "Alt"} & set(names)):
        return tr("非 F1–F24 的按鍵必須搭配 Ctrl 或 Alt", "Keys other than F1-F24 need Ctrl or Alt")
    return None


_RISKY_COMBOS: frozenset[str] = frozenset({
    "Ctrl+L", "Alt+D", "F6", "Ctrl+K", "Ctrl+E", "Ctrl+T", "Ctrl+N", "Ctrl+Shift+N", "Ctrl+W",
    "Ctrl+Shift+W", "Ctrl+Shift+T", "Ctrl+Tab", "Ctrl+Shift+Tab", "Alt+Left", "Alt+Right", "Ctrl+O",
    "Ctrl+P", "Ctrl+S", "Ctrl+J",
})


def combo_risk(text: str) -> tuple[IssueLevel | None, str]:
    """Safety class of a key-step combo (a shared profile is executable input, SPEC 2.7):
    (ERROR, reason) - refused in key steps: any Win combo, Alt+Tab, Alt+Esc, Alt+F4, Alt+Space,
    Ctrl+Esc, Ctrl+Shift+Esc, Ctrl+Alt+Delete (they leave the target, open system UI or launch
    programs); (WARNING, reason) - allowed but highlighted (validation, import summary):
    shortcuts that move the focus or navigate in browsers / chat apps (Ctrl+L, Alt+D, F6, Ctrl+K,
    Ctrl+E, Ctrl+T, Ctrl+N, Ctrl+W, Ctrl+Tab, Alt+Left/Right, Ctrl+O/P/S/J ...);
    (None, "") otherwise, also for unparsable text (validation reports that separately)."""
    try:
        names = parse_combo_names(text)
    except ValueError:
        return None, ""
    key, mods = names[-1], set(names[:-1])
    forbidden = ("Win" in names
                 or ("Alt" in mods and key in ("Tab", "Esc", "F4", "Space"))
                 or ("Ctrl" in mods and key == "Esc")
                 or ({"Ctrl", "Alt"} <= mods and key == "Delete"))
    if forbidden:
        return IssueLevel.ERROR, tr(f"「{format_combo(names)}」是系統快捷鍵，設定檔不能使用",
                                    f"'{format_combo(names)}' is a system shortcut; profiles cannot use it")
    if format_combo(names) in _RISKY_COMBOS:
        return IssueLevel.WARNING, tr(f"「{format_combo(names)}」可能切換分頁、開網址列或開新視窗",
                                      f"'{format_combo(names)}' may switch tabs, open the address bar or a new window")
    return None, ""


# =============================================================================== charsets / code keys


def expand_charset(spec: str) -> str:
    """Expand a character-class body: ``"A-HJ-NP-Y0-9"`` -> ``"ABCDEFGHJKLMNPQRSTUVWXY0123456789"``
    (sorted, unique). A ``-`` at the start or end is literal. ValueError for a reversed range
    or an empty result."""
    out: set[str] = set()
    i = 0
    s = spec or ""
    while i < len(s):
        if i + 2 < len(s) and s[i + 1] == "-":
            a, b = s[i], s[i + 2]
            if ord(a) > ord(b):
                raise ValueError(f"reversed range {a}-{b}")
            out.update(chr(c) for c in range(ord(a), ord(b) + 1))
            i += 3
        else:
            out.add(s[i])
            i += 1
    if not out:
        raise ValueError("empty charset")
    return "".join(sorted(out))


SEPARATOR_CHARS = "-_"
"""Separator characters inside codes: kept as written for formats without ``groups``, never
counted in lengths, ignored by ``code_key`` (codes.normalize, SPEC 5.4)."""


def code_key(code: str) -> str:
    """Comparison key for de-duplication and history: whitespace, ``-`` and ``_`` removed,
    case kept (codes are already case-normalised by their CodeFormat at import)."""
    return "".join(c for c in code if not c.isspace() and c not in SEPARATOR_CHARS)


# =============================================================================== failsafe corner


def failsafe_corners(monitor_rects: Sequence[Rect]) -> list[Point]:
    """Top-left corners that are real OUTER corners of the desktop: the top-left (x, y) of every
    monitor rect whose left neighbour (x - 1, y) and upper neighbour (x, y - 1) lie on no
    monitor. One monitor -> [(0, 0)]. The research PC has its second monitor LEFT of the primary
    ((-1920, 0)): only (-1920, 0) counts, because the primary's (0, 0) sits on the shared top edge
    (pushing the mouse "into the top-left corner" ends at (-1920, 0)). Empty input -> [(0, 0)]."""
    rects = [r for r in monitor_rects if r[2] > 0 and r[3] > 0]
    if not rects:
        return [(0, 0)]

    def on_any(px: int, py: int) -> bool:
        return any(point_in_rect(r, px, py) for r in rects)

    out: list[Point] = []
    for x, y, _w, _h in rects:
        if not on_any(x - 1, y) and not on_any(x, y - 1) and (x, y) not in out:
            out.append((x, y))
    return out or [(min(r[0] for r in rects), min(r[1] for r in rects))]


def in_failsafe_corner(px: int, py: int, monitor_rects: Sequence[Rect], margin_px: int = 3) -> bool:
    """True when the physical cursor point is within ``margin_px`` of a ``failsafe_corners``
    corner (win32.input.failsafe_triggered uses this with win32.dpi.monitors())."""
    m = max(0, int(margin_px))
    return any(x <= px <= x + m and y <= py <= y + m for x, y in failsafe_corners(monitor_rects))


# =============================================================================== coordinates


@dataclass
class ClientPoint:
    """A point relative to the target's client area (physical px), stored as an offset AND a
    ratio so it survives window moves and resizes (win32_windows.md section 6)."""

    dx: int = 0  # offset from the client top-left when recorded
    dy: int = 0
    rx: float = 0.0  # pixel-centre ratio (dx + 0.5) / ref_w
    ry: float = 0.0
    ref_w: int = _num(1, 1, 100000)  # client size when recorded
    ref_h: int = _num(1, 1, 100000)
    anchor: Anchor = Anchor.TL  # offset mode: edge to keep the distance to
    ref_dpi: int = _num(96, 24, 2000)  # target DPI when recorded (offset mode scales by dpi / ref_dpi)

    # keys that must be present and valid in JSON, else the whole point loads as None (not set)
    _REQUIRED = ("dx", "dy", "rx", "ry")

    def describe(self) -> str:
        return f"({self.dx}, {self.dy})"


@dataclass
class ClientRegion:
    """A rectangle relative to the target's client area (physical px), offset + ratios."""

    dx: int = 0
    dy: int = 0
    w: int = _num(1, 1, 100000)
    h: int = _num(1, 1, 100000)
    rx: float = 0.0  # dx / ref_w
    ry: float = 0.0
    rw: float = 0.0  # w / ref_w
    rh: float = 0.0
    ref_w: int = _num(1, 1, 100000)
    ref_h: int = _num(1, 1, 100000)
    ref_dpi: int = _num(96, 24, 2000)

    _REQUIRED = ("dx", "dy", "w", "h", "rx", "ry", "rw", "rh")

    def describe(self) -> str:
        return f"({self.dx}, {self.dy}) {self.w}×{self.h}"


def record_point(client: Rect, px: int, py: int, anchor: Anchor | str = Anchor.TL, dpi: int = 96) -> ClientPoint:
    """Store the physical screen point (px, py) relative to ``client`` = (x, y, w, h)."""
    cx, cy, cw, ch = client
    if cw <= 0 or ch <= 0:
        raise ValueError("client area has no size")
    dx, dy = int(px) - cx, int(py) - cy
    return ClientPoint(dx, dy, (dx + 0.5) / cw, (dy + 0.5) / ch, cw, ch, Anchor(anchor), int(dpi))


def _dpi_scale(dpi: int, ref_dpi: int) -> float:
    return dpi / ref_dpi if dpi > 0 and ref_dpi > 0 and dpi != ref_dpi else 1.0


def resolve_point(client: Rect, p: ClientPoint, mode: CoordMode | str = CoordMode.AUTO, dpi: int = 0) -> Point:
    """Physical screen point for ``p`` in the current ``client`` rect. ``auto`` uses the offset
    when the client size (and, when ``dpi`` is given, the DPI) equals the recorded one, otherwise
    the ratio. ``offset`` with ``dpi`` > 0 different from ``p.ref_dpi`` scales the distances to
    the anchor by ``dpi / ref_dpi`` (web pages and dialogs grow with Windows scaling, SPEC 5.2).
    Callers pass ``dpi=win32.windows.window_dpi(hwnd)``; 0 = no DPI handling."""
    cx, cy, cw, ch = client
    mode = CoordMode(mode)
    s = _dpi_scale(dpi, p.ref_dpi)
    if mode is CoordMode.AUTO:
        mode = CoordMode.OFFSET if (cw, ch) == (p.ref_w, p.ref_h) and s == 1.0 else CoordMode.RATIO
    if mode is CoordMode.RATIO:
        return (cx + max(0, min(cw - 1, math.floor(p.rx * cw))),
                cy + max(0, min(ch - 1, math.floor(p.ry * ch))))

    def sc(v: int) -> int:
        return v if s == 1.0 else int(round(v * s))

    a = Anchor(p.anchor)
    if a in (Anchor.TL, Anchor.BL):
        ox = sc(p.dx)
    elif a in (Anchor.TR, Anchor.BR):
        ox = cw - sc(p.ref_w - p.dx)
    else:
        ox = (cw - p.ref_w) // 2 + p.dx if s == 1.0 else cw // 2 + sc(p.dx - p.ref_w // 2)
    if a in (Anchor.TL, Anchor.TR):
        oy = sc(p.dy)
    elif a in (Anchor.BL, Anchor.BR):
        oy = ch - sc(p.ref_h - p.dy)
    else:
        oy = (ch - p.ref_h) // 2 + p.dy if s == 1.0 else ch // 2 + sc(p.dy - p.ref_h // 2)
    return cx + ox, cy + oy


def record_region(client: Rect, x: int, y: int, w: int, h: int, dpi: int = 96) -> ClientRegion:
    """Store the physical screen rect (x, y, w, h) relative to ``client``."""
    cx, cy, cw, ch = client
    if cw <= 0 or ch <= 0:
        raise ValueError("client area has no size")
    w, h = max(1, int(w)), max(1, int(h))
    dx, dy = int(x) - cx, int(y) - cy
    return ClientRegion(dx, dy, w, h, dx / cw, dy / ch, w / cw, h / ch, cw, ch, int(dpi))


def resolve_region(client: Rect, r: ClientRegion, mode: CoordMode | str = CoordMode.AUTO, dpi: int = 0) -> Rect:
    """Physical screen rect for ``r`` in the current ``client`` rect (``auto`` and ``dpi`` as for
    points; offset mode keeps the top-left distance and scales position and size by dpi/ref_dpi)."""
    cx, cy, cw, ch = client
    mode = CoordMode(mode)
    s = _dpi_scale(dpi, r.ref_dpi)
    if mode is CoordMode.AUTO:
        mode = CoordMode.OFFSET if (cw, ch) == (r.ref_w, r.ref_h) and s == 1.0 else CoordMode.RATIO
    if mode is CoordMode.OFFSET:
        if s != 1.0:
            return (cx + int(round(r.dx * s)), cy + int(round(r.dy * s)),
                    max(1, int(round(r.w * s))), max(1, int(round(r.h * s))))
        return cx + r.dx, cy + r.dy, r.w, r.h
    x0, y0 = round(r.rx * cw), round(r.ry * ch)
    x1, y1 = round((r.rx + r.rw) * cw), round((r.ry + r.rh) * ch)
    return cx + x0, cy + y0, max(1, x1 - x0), max(1, y1 - y0)


def point_in_rect(rect: Rect, px: int, py: int) -> bool:
    x, y, w, h = rect
    return x <= px < x + w and y <= py < y + h


def intersect_rect(a: Rect, b: Rect) -> Rect | None:
    """Intersection of two rects, or None when they do not overlap."""
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1 - x0, y1 - y0


# =============================================================================== code format / target


@dataclass
class CodeFormat:
    """How codes of one game look. Presets live in codes.presets (G1); a profile stores a full
    copy so it is self-contained."""

    id: str = "generic"  # preset id, or "custom"
    charset: str = "A-Za-z0-9"  # allowed code characters (character-class body, separators excluded)
    case_sensitive: bool = True  # True: case kept as written (generic); False: upper-cased at import
    min_len: int = _num(6, 1, 64)  # charset characters, separators not counted
    max_len: int = _num(24, 1, 64)
    groups: list[int] = _strict_list()  # e.g. [5, 5, 5] -> XXXXX-XXXXX-XXXXX
    separator: str = "-"  # inserted between groups (formats without groups keep the source separators)
    regex: str = ""  # optional full-match regex on the normalised code (advanced)

    def allowed_chars(self) -> str:
        """Expanded charset (upper-cased when not case-sensitive); "" if the spec is invalid."""
        try:
            chars = expand_charset(self.charset)
        except ValueError:
            return ""
        if not self.case_sensitive:
            chars = "".join(sorted(set(chars.upper())))
        return chars

    def total_length(self) -> int | None:
        return sum(self.groups) if self.groups else None

    def validate(self, path: str = "code_format") -> list[ValidationIssue]:
        out: list[ValidationIssue] = []
        try:
            expand_charset(self.charset)
        except ValueError:
            out.append(ValidationIssue(IssueLevel.ERROR, f"{path}.charset",
                                       tr("序號字元集格式錯誤", "Invalid code character set")))
        if self.min_len > self.max_len:
            out.append(ValidationIssue(IssueLevel.ERROR, f"{path}.min_len",
                                       tr("最短長度大於最長長度", "Minimum length is larger than maximum length")))
        if any(g <= 0 for g in self.groups):
            out.append(ValidationIssue(IssueLevel.ERROR, f"{path}.groups",
                                       tr("每段字數必須大於 0", "Group sizes must be positive")))
        if self.regex:
            try:
                re.compile(self.regex)
            except re.error:
                out.append(ValidationIssue(IssueLevel.ERROR, f"{path}.regex",
                                           tr("序號正規表示式有誤", "Invalid code regular expression")))
        return out


FORBIDDEN_TARGET_EXES: frozenset[str] = frozenset({
    "explorer.exe", "cmd.exe", "powershell.exe", "powershell_ise.exe", "pwsh.exe", "windowsterminal.exe",
    "wt.exe", "openconsole.exe", "conhost.exe", "mintty.exe", "putty.exe", "regedit.exe", "mmc.exe",
    "taskmgr.exe", "mshta.exe", "wscript.exe", "cscript.exe", "rundll32.exe", "msiexec.exe", "control.exe",
    "systemsettings.exe", "searchapp.exe", "searchhost.exe", "startmenuexperiencehost.exe",
    "shellexperiencehost.exe", "lockapp.exe", "consent.exe",
})
"""Shells, terminals and system UI: never a target (validation ERROR, preflight
``target_forbidden``, the window picker greys them out). Typing text + Enter there runs programs."""

BROWSER_EXES: frozenset[str] = frozenset({
    "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe", "whale.exe",
    "chromium.exe", "iexplore.exe",
})
"""Browsers: one process shows many unrelated pages, so a browser target needs a title keyword."""


@dataclass
class TargetMatch:
    """How to find the target window again (exe + title + class; handles are recycled)."""

    exe: str = ""  # process image file name, e.g. "chrome.exe" (case-insensitive; "" = any)
    title: str = ""
    title_mode: TitleMatch = TitleMatch.CONTAINS
    class_name: str = ""  # exact window class ("" = any)
    allow_same_process: bool = False  # other top-level windows of the target process count as the
    # target for the foreground check AND as click roots; never exported or imported (SPEC 2.7)

    def is_empty(self) -> bool:
        return not self.exe and not self.class_name and (self.title_mode is TitleMatch.ANY or not self.title)

    def is_forbidden(self) -> bool:
        """The exe is a shell / terminal / system UI (FORBIDDEN_TARGET_EXES)."""
        return self.exe.casefold() in FORBIDDEN_TARGET_EXES

    def is_browser(self) -> bool:
        return self.exe.casefold() in BROWSER_EXES

    def needs_title(self) -> bool:
        """A browser target without a title keyword would match any tab of that browser."""
        return self.is_browser() and (self.title_mode is TitleMatch.ANY or not self.title.strip())

    def pattern_error(self) -> str | None:
        """Localized error if ``title`` is an invalid regex in REGEX mode, else None."""
        if self.title_mode is TitleMatch.REGEX:
            try:
                re.compile(self.title)
            except re.error:
                return tr("視窗標題的正規表示式有誤", "Invalid window-title regular expression")
        return None

    def matches(self, exe_path: str, title: str, class_name: str) -> bool:
        """Pure matching rule used by win32.windows.find_windows (G3 must use this)."""
        if self.exe:
            name = exe_path.replace("\\", "/").rsplit("/", 1)[-1]
            if name.casefold() != self.exe.casefold():
                return False
        if self.class_name and class_name != self.class_name:
            return False
        mode = self.title_mode
        if mode is TitleMatch.ANY or not self.title:
            return True
        if mode is TitleMatch.CONTAINS:
            return self.title.casefold() in title.casefold()
        if mode is TitleMatch.EXACT:
            return title == self.title
        try:
            return re.search(self.title, title, re.IGNORECASE) is not None
        except re.error:
            return False

    def describe(self) -> str:
        parts = []
        if self.title and self.title_mode is not TitleMatch.ANY:
            parts.append(f"「{self.title}」")
        if self.exe:
            parts.append(self.exe)
        return " · ".join(parts) if parts else tr("（未設定）", "(not set)")


# =============================================================================== steps


@dataclass
class FocusWindowParams:
    restore_minimized: bool = True
    timeout_ms: int = _num(3000, 100, 60000)
    settle_ms: int = _num(200, 0, 10000)  # wait after the window is in front


@dataclass
class ClickPointParams:
    point: ClientPoint | None = None
    button: MouseButton = MouseButton.LEFT
    double: bool = False
    jitter_px: int = _num(0, 0, 50)  # random +-px added to x and y
    settle_ms: int = _num(30, 0, 5000)  # after moving, before the button goes down
    hold_ms: int = _num(30, 0, 5000)  # button down -> up
    after_ms: int = _num(120, 0, 60000)  # wait after the click


@dataclass
class ClickTextParams:
    text: str = ""  # alternatives separated by "|", e.g. "兌換|Redeem|確認" (REGEX mode: one pattern)
    match: TextMatch = TextMatch.EXACT
    region: ClientRegion | None = None  # None = whole client area
    nth: int = _num(0, 0, 50)  # 0 = best match; n >= 1 = n-th match in reading order
    offset_x: int = _num(0, -2000, 2000)  # added to the text centre, in px at 96 DPI (x window_dpi / 96)
    offset_y: int = _num(0, -2000, 2000)
    min_score: float = _num(0.5, 0.0, 1.0)
    upscale: int = _num(0, 0, 3)  # 0 = auto (retry once at 2x when not found)
    timeout_ms: int = _num(3000, 0, 120000)  # keep looking until found
    poll_ms: int = _num(500, 50, 10000)
    fallback_point: ClientPoint | None = None  # clicked when the text is not found
    on_not_found: TimeoutAction = TimeoutAction.FAIL  # no text and no fallback: FAIL = StepError,
    # CONTINUE = skip the click and go on ("click 確定 if the popup is there", SPEC 5.3)
    button: MouseButton = MouseButton.LEFT
    double: bool = False
    settle_ms: int = _num(30, 0, 5000)
    hold_ms: int = _num(30, 0, 5000)
    after_ms: int = _num(120, 0, 60000)


@dataclass
class TypeCodeParams:
    mode: TypingMode = TypingMode.UNICODE
    key_delay_ms: int = _num(15, 0, 1000)  # between characters
    hold_ms: int = _num(0, 0, 500)  # key down -> up (>= 20 in VK mode for polling games)
    clear_first: bool = True
    clear_method: ClearMethod = ClearMethod.CTRL_A
    split: SplitMode = SplitMode.NONE
    separators: str = "-_"  # SEPARATOR mode split characters; also removed by strip_separators
    group_sizes: list[int] = _strict_list()  # FIXED mode; [] = profile.code_format.groups
    between: BetweenSegments = BetweenSegments.TAB
    strip_separators: bool = False  # NONE mode: remove separator characters before typing (else the
    # code is typed exactly as shown in the queue)
    verify_region: ClientRegion | None = None  # optional: OCR this region after typing and compare
    after_ms: int = _num(100, 0, 60000)


@dataclass
class TypeTextParams:
    text: str = ""  # template; placeholders {code} {index} {date} {time}
    mode: TypingMode = TypingMode.UNICODE
    key_delay_ms: int = _num(15, 0, 1000)
    hold_ms: int = _num(0, 0, 500)
    clear_first: bool = False
    clear_method: ClearMethod = ClearMethod.CTRL_A
    after_ms: int = _num(100, 0, 60000)


@dataclass
class KeyParams:
    keys: str = "Enter"  # combo, e.g. "Enter", "Esc", "Ctrl+A", "Shift+Tab" (see KEY_NAMES)
    repeat: int = _num(1, 1, 100)
    interval_ms: int = _num(50, 0, 10000)  # between repeats
    hold_ms: int = _num(0, 0, 2000)
    after_ms: int = _num(100, 0, 60000)


@dataclass
class WaitParams:
    ms: int = _num(1000, 0, 600000)
    jitter_pct: int = _num(0, 0, 100)  # random +- percent


@dataclass
class WaitTextParams:
    text: str = ""
    match: TextMatch = TextMatch.CONTAINS
    region: ClientRegion | None = None
    appear: bool = True  # True: wait until present; False: wait until gone
    timeout_ms: int = _num(5000, 0, 600000)
    poll_ms: int = _num(500, 50, 10000)
    on_timeout: TimeoutAction = TimeoutAction.FAIL
    upscale: int = _num(0, 0, 3)


@dataclass
class OcrCheckParams:
    region: ClientRegion | None = None  # REQUIRED (validation ERROR when None; in missing_setup())
    initial_delay_ms: int = _num(800, 0, 60000)
    timeout_ms: int = _num(5000, 0, 120000)  # poll until a known class appears
    poll_ms: int = _num(500, 50, 10000)
    save_evidence: bool = True
    upscale: int = _num(0, 0, 3)
    only_new_text: bool = True  # classify only lines that are new or changed compared with a baseline
    # read of the region taken right before the submitting step (stale / static text ignored, SPEC 2.5)


@dataclass
class UnknownParams:
    """Parameters of a step type this version does not know (kept verbatim)."""

    type_name: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


StepParams = (FocusWindowParams | ClickPointParams | ClickTextParams | TypeCodeParams | TypeTextParams
              | KeyParams | WaitParams | WaitTextParams | OcrCheckParams | UnknownParams)

STEP_PARAM_TYPES: dict[StepType, type] = {
    StepType.FOCUS_WINDOW: FocusWindowParams,
    StepType.CLICK_POINT: ClickPointParams,
    StepType.CLICK_TEXT: ClickTextParams,
    StepType.TYPE_CODE: TypeCodeParams,
    StepType.TYPE_TEXT: TypeTextParams,
    StepType.KEY: KeyParams,
    StepType.WAIT: WaitParams,
    StepType.WAIT_TEXT: WaitTextParams,
    StepType.OCR_CHECK: OcrCheckParams,
}


@dataclass
class Step:
    type: StepType = StepType.WAIT
    params: StepParams = field(default_factory=WaitParams)
    enabled: bool = True
    label: str = ""  # optional title (zh-TW; templates: the wizard instruction, e.g. 「點一下序號輸入框」)
    id: str = field(default_factory=new_id)
    label_en: str = ""  # English title; display_title() picks label / label_en by UI language

    def __post_init__(self) -> None:
        expected = STEP_PARAM_TYPES.get(self.type)
        if expected is not None and not isinstance(self.params, expected):
            raise TypeError(f"{self.type.value} step needs {expected.__name__}, got {type(self.params).__name__}")
        if self.type is StepType.UNKNOWN and not isinstance(self.params, UnknownParams):
            raise TypeError("unknown step needs UnknownParams")

    # -- serialisation hooks used by to_dict / from_dict
    def _encode(self) -> dict[str, Any]:
        if isinstance(self.params, UnknownParams):
            t, p = self.params.type_name, dict(self.params.raw)
        else:
            t, p = self.type.value, to_dict(self.params)
        out = {"type": t, "params": p, "enabled": self.enabled, "label": self.label, "id": self.id}
        if self.label_en:
            out["label_en"] = self.label_en  # omitted when empty (files stay as written)
        return out

    @classmethod
    def _decode(cls, data: Mapping[str, Any]) -> Step:
        raw_type = data.get("type")
        try:
            st = StepType(raw_type)
        except ValueError:
            st = StepType.UNKNOWN
        p = data.get("params")
        p = p if isinstance(p, Mapping) else {}
        if st is StepType.UNKNOWN:
            params: Any = UnknownParams(type_name=str(raw_type or ""), raw=dict(p))
        else:
            params = from_dict(STEP_PARAM_TYPES[st], p)
        enabled = data.get("enabled", True)
        label = data.get("label", "")
        label_en = data.get("label_en", "")
        sid = data.get("id")
        return cls(type=st, params=params, enabled=enabled if isinstance(enabled, bool) else True,
                   label=clean_text(label) if isinstance(label, str) else "",
                   id=sid if isinstance(sid, str) and sid else new_id(),
                   label_en=clean_text(label_en) if isinstance(label_en, str) else "")

    # -- presentation
    def display_title(self) -> str:
        """``label`` (zh-TW UI) or ``label_en`` (English UI); the other language's label when the
        preferred one is empty; else the type label."""
        first, second = (self.label_en, self.label) if get_language() == "en" else (self.label, self.label_en)
        for text in (first, second):
            if text.strip():
                return text.strip()
        if isinstance(self.params, UnknownParams):
            return tr(f"未知步驟「{self.params.type_name}」", f"Unknown step '{self.params.type_name}'")
        return self.type.label()

    def summary(self) -> str:
        """One-line, muted parameter summary for step lists and logs."""
        p = self.params
        if isinstance(p, FocusWindowParams):
            return tr("帶到最前面", "Bring to front")
        if isinstance(p, ClickPointParams):
            return p.point.describe() if p.point else tr("尚未設定位置", "Position not set")
        if isinstance(p, ClickTextParams):
            return f"「{p.text}」" if p.text else tr("尚未設定文字", "Text not set")
        if isinstance(p, TypeCodeParams):
            s = p.mode.label()
            if p.split is not SplitMode.NONE:
                s += " · " + p.split.label()
            return s
        if isinstance(p, TypeTextParams):
            return f"「{p.text}」" if p.text else tr("尚未設定文字", "Text not set")
        if isinstance(p, KeyParams):
            return p.keys + (f" ×{p.repeat}" if p.repeat > 1 else "")
        if isinstance(p, WaitParams):
            s = tr(f"{p.ms / 1000:g} 秒", f"{p.ms / 1000:g} s")
            return s + (f" ±{p.jitter_pct}%" if p.jitter_pct else "")
        if isinstance(p, WaitTextParams):
            verb = tr("出現", "appears") if p.appear else tr("消失", "disappears")
            return tr(f"等「{p.text}」{verb}", f"until '{p.text}' {verb}")
        if isinstance(p, OcrCheckParams):
            return tr("範圍已設定", "Region set") if p.region else tr("整個視窗", "Whole window")
        return ""

    def validate(self, index: int, profile: Profile | None = None) -> list[ValidationIssue]:
        """Issues for this step (``index`` is 0-based; messages say "第 n 步" with n = index+1)."""
        n = index + 1
        path = f"steps[{index}].params"
        out: list[ValidationIssue] = []

        def add(level: IssueLevel, sub: str, zh: str, en: str) -> None:
            out.append(ValidationIssue(level, f"{path}.{sub}" if sub else path,
                                       tr(f"第 {n} 步：{zh}", f"Step {n}: {en}"), index))

        p = self.params
        if isinstance(p, UnknownParams):
            add(IssueLevel.WARNING, "", f"較新版本的步驟類型「{p.type_name}」，執行時會略過",
                f"step type '{p.type_name}' is from a newer version and will be skipped")
            return out
        if isinstance(p, ClickPointParams) and p.point is None:
            add(IssueLevel.ERROR, "point", "尚未設定點擊位置", "the click position is not set")
        if isinstance(p, (ClickTextParams, WaitTextParams)):
            if p.match is TextMatch.REGEX:  # a regex has its own "|": never split into alternatives
                if not p.text.strip():
                    add(IssueLevel.ERROR, "text", "尚未設定要尋找的文字", "no text to look for")
                else:
                    try:
                        re.compile(p.text)
                    except re.error:
                        add(IssueLevel.ERROR, "text", "正規表示式有誤", "invalid regular expression")
            elif not split_alternatives(p.text):
                add(IssueLevel.ERROR, "text", "尚未設定要尋找的文字", "no text to look for")
            if p.region is None:
                add(IssueLevel.INFO, "region", "未設定搜尋範圍，將辨識整個視窗（較慢）",
                    "no search region; the whole window is read (slower)")
        if isinstance(p, TypeCodeParams):
            if p.split is SplitMode.SEPARATOR and not p.separators:
                add(IssueLevel.ERROR, "separators", "依分隔符號拆段需要設定分隔符號", "separator split needs separator characters")
            if p.split is SplitMode.FIXED:
                sizes = p.group_sizes or (profile.code_format.groups if profile else [])
                if not sizes or any(s <= 0 for s in sizes):
                    add(IssueLevel.ERROR, "group_sizes", "依固定字數拆段需要設定每段字數", "fixed split needs group sizes")
        if isinstance(p, TypeTextParams):
            if not p.text:
                add(IssueLevel.ERROR, "text", "尚未設定要輸入的文字", "no text to type")
            elif "{code}" not in p.text:
                add(IssueLevel.WARNING, "text", "輸入的文字不含 {code}，每筆都會輸入同樣的內容",
                    "the text has no {code}: the same text is typed for every code")
        if isinstance(p, KeyParams):
            try:
                parse_combo_names(p.keys)
            except ValueError:
                add(IssueLevel.ERROR, "keys", f"無法辨識的按鍵「{p.keys}」", f"unrecognised keys '{p.keys}'")
            else:
                level, reason = combo_risk(p.keys)
                if level is not None:
                    add(level, "keys", reason, reason)
        if isinstance(p, OcrCheckParams) and p.region is None:
            add(IssueLevel.ERROR, "region", "尚未設定結果範圍（結果訊息出現的位置）",
                "the result region (where the result message appears) is not set")
        return out


def make_step(step_type: StepType, delays: DelaySettings | None = None) -> Step:
    """New step with default parameters; timing defaults come from ``delays`` when given."""
    st = StepType(step_type)
    if st is StepType.UNKNOWN:
        raise ValueError("cannot create an unknown step")
    params = STEP_PARAM_TYPES[st]()
    if delays is not None:
        if isinstance(params, FocusWindowParams):
            params.settle_ms = delays.after_focus_ms
        if isinstance(params, (ClickPointParams, ClickTextParams)):
            params.after_ms = delays.after_click_ms
        if isinstance(params, (TypeCodeParams, TypeTextParams)):
            params.key_delay_ms = delays.key_delay_ms
    return Step(type=st, params=params)


# =============================================================================== result keywords

# Default keywords per class and language (ux.md section 4, bench_u3.py). Proposals: NOT
# verified against real games. The rule is KeywordConfig.classify (runner.classify delegates):
# squash both sides (NFKC, casefold, no spaces/punctuation), test classes in KeywordConfig.order,
# SUCCESS together with another class or a negation is ambiguous. Keywords must not overlap.
# Revised 2026-11-17 (SPEC decision log T05 / PX-04): no bare "redeemed" / "claimed" in SUCCESS
# (they occur in failure messages), no bare 過期 / 过期 / 有効期限 in EXPIRED (success messages
# mention when rewards expire), no Korean (the OCR model cannot read Hangul, ocr.md U3).
DEFAULT_KEYWORDS: dict[ResultClass, dict[str, list[str]]] = {
    ResultClass.RATE_LIMITED: {
        "zh-TW": ["過於頻繁", "太頻繁", "稍後再試"], "zh-CN": ["过于频繁", "太频繁", "稍后再试"],
        "en": ["too many", "too frequent", "try again later", "on cooldown", "rate limit"],
        "ja": ["しばらく", "時間をおいて"],
    },
    ResultClass.USED: {
        "zh-TW": ["已被使用", "已使用", "已兌換過", "已被兌換"], "zh-CN": ["已被使用", "已使用", "已兑换过", "已被兑换"],
        "en": ["already been used", "already used", "already redeemed", "already claimed", "claimed already",
               "redeemed already"],
        "ja": ["既に使用", "使用済み"],
    },
    ResultClass.EXPIRED: {
        "zh-TW": ["已過期", "已失效", "已逾期"], "zh-CN": ["已过期", "已失效"],
        "en": ["expired"], "ja": ["期限切れ", "有効期限が切れ"],
    },
    ResultClass.INVALID: {
        "zh-TW": ["無效", "不存在", "序號錯誤", "兌換碼錯誤", "輸入錯誤"], "zh-CN": ["无效", "不存在", "兑换码错误", "输入错误"],
        "en": ["invalid", "incorrect", "does not exist", "not found"], "ja": ["無効"],
    },
    ResultClass.INELIGIBLE: {
        "zh-TW": ["等級不足", "已達上限", "使用上限", "伺服器不符", "地區不符"],
        "zh-CN": ["等级不足", "已达上限", "使用上限", "服务器不符", "地区不符"],
        "en": ["level too low", "level requirement", "limit reached", "max usage", "not available in", "your region"],
        "ja": ["使用上限", "レベルが足り"],
    },
    ResultClass.SUCCESS: {
        "zh-TW": ["兌換成功", "領取成功", "成功兌換", "成功領取", "已發送", "已寄送", "發送成功"],
        "zh-CN": ["兑换成功", "领取成功", "成功兑换", "成功领取", "已发送", "发送成功"],
        "en": ["successfully", "redemption successful", "code redeemed", "code claimed"],
        "ja": ["交換しました", "成功しました", "受け取りました"],
    },
}

DEFAULT_CLASS_ORDER: tuple[ResultClass, ...] = (
    ResultClass.RATE_LIMITED, ResultClass.USED, ResultClass.EXPIRED,
    ResultClass.INVALID, ResultClass.INELIGIBLE, ResultClass.SUCCESS,
)

KEYWORD_LANGUAGES: tuple[str, ...] = ("zh-TW", "zh-CN", "en", "ja")

FUZZY_MIN_LEN = 9
"""With KeywordConfig.fuzzy, only non-CJK keywords of at least 9 squashed characters tolerate one
OCR edit ("successfully" yes; "expired" / "notfound" no: "expires" / "notbound" are other words)."""

NEGATION_MARKERS: tuple[str, ...] = (
    "cannot", "couldnot", "unable", "failed", "unsuccessful", "notsuccessful", "notredeemed",
    "無法", "失敗", "未成功", "未能", "无法", "失败", "できません",
)
"""Squashed markers that turn a SUCCESS hit into UNKNOWN ("未能成功兌換", "could not ... successfully")."""


def default_keyword_groups(languages: list[str] | None = None) -> dict[ResultClass, list[str]]:
    """Merged default keyword lists per class (KEYWORD_LANGUAGES unless ``languages`` given)."""
    langs = languages or list(KEYWORD_LANGUAGES)
    out: dict[ResultClass, list[str]] = {}
    for cls in DEFAULT_CLASS_ORDER:
        seen: list[str] = []
        for lang in langs:
            for kw in DEFAULT_KEYWORDS[cls].get(lang, []):
                if kw not in seen:
                    seen.append(kw)
        out[cls] = seen
    return out


@dataclass
class KeywordConfig:
    groups: dict[ResultClass, list[str]] = field(default_factory=default_keyword_groups)
    order: list[ResultClass] = field(default_factory=lambda: list(DEFAULT_CLASS_ORDER))
    fuzzy: bool = True  # tolerate 1 OCR edit for non-CJK keywords of FUZZY_MIN_LEN (9)+ characters

    def _after_load(self) -> None:
        self.groups.pop(ResultClass.UNKNOWN, None)
        for cls in DEFAULT_CLASS_ORDER:
            self.groups.setdefault(cls, [])
        order: list[ResultClass] = []
        for cls in self.order:
            if cls is not ResultClass.UNKNOWN and cls not in order:
                order.append(cls)
        for cls in DEFAULT_CLASS_ORDER:
            if cls not in order:
                order.append(cls)
        self.order = order

    def _hit(self, keyword: str, text: str) -> bool:
        k = squash(keyword)
        if not k:
            return False
        if self.fuzzy:
            return fuzzy_contains(k, text, max_edits=1, min_len=FUZZY_MIN_LEN)
        return k in text

    def classify(self, text: str) -> tuple[ResultClass, str]:
        """THE result-classification rule (SPEC 5.5; runner.classify.classify_text delegates here).

        1. ``t = squash(text)``; empty -> (UNKNOWN, "").
        2. A keyword hits when its squashed form is a substring of ``t``; with ``fuzzy``, non-CJK
           keywords of FUZZY_MIN_LEN+ characters also hit with one edit (textutil.fuzzy_contains).
        3. For every class the first hitting keyword (list order) is noted.
        4. A SUCCESS hit together with a hit of any other class, or with a NEGATION_MARKERS entry
           in ``t``, is ambiguous -> (UNKNOWN, "") so the user is asked.
        5. Otherwise the first class in ``order`` with a hit wins: (class, its keyword).
        """
        t = squash(text or "")
        if not t:
            return ResultClass.UNKNOWN, ""
        hits: dict[ResultClass, str] = {}
        for cls in self.order:
            for kw in self.groups.get(cls, []):
                if self._hit(kw, t):
                    hits[cls] = kw
                    break
        if not hits:
            return ResultClass.UNKNOWN, ""
        if ResultClass.SUCCESS in hits and (len(hits) > 1 or any(m in t for m in NEGATION_MARKERS)):
            return ResultClass.UNKNOWN, ""
        for cls in self.order:
            if cls in hits:
                return cls, hits[cls]
        return ResultClass.UNKNOWN, ""

    def overlaps(self) -> list[tuple[str, ResultClass, ResultClass]]:
        """Keywords whose squashed form occurs in two groups: (keyword, class_a, class_b)."""
        seen: dict[str, ResultClass] = {}
        out: list[tuple[str, ResultClass, ResultClass]] = []
        for cls in self.order:
            for kw in self.groups.get(cls, []):
                key = squash(kw)
                if not key:
                    continue
                if key in seen and seen[key] is not cls:
                    out.append((kw, seen[key], cls))
                else:
                    seen.setdefault(key, cls)
        return out


# =============================================================================== profile


@dataclass
class RunPolicy:
    interval_min_s: float = _num(6.0, 1.0, 3600.0)  # wait between codes = uniform(min, max)
    interval_max_s: float = _num(8.0, 1.0, 3600.0)
    on_rate_limit: RateLimitAction = RateLimitAction.COOLDOWN
    cooldown_s: int = _num(300, 10, 86400)
    max_cooldowns: int = _num(1, 0, 20)  # a further rate-limit hit stops the run
    stop_after_failures: int = _num(3, 0, 1000)  # consecutive FAILED / REVIEW results; 0 = never
    on_unknown: UnknownAction = UnknownAction.PAUSE
    pause_after_invalid: int = _num(3, 0, 1000)  # consecutive INVALID results -> pause INVALID_STREAK
    # (a systematic typing problem looks like "every code is invalid"); 0 = never

    def _after_load(self) -> None:
        if self.interval_min_s > self.interval_max_s:
            self.interval_min_s, self.interval_max_s = self.interval_max_s, self.interval_min_s


@dataclass
class TemplateInfo:
    """Gallery metadata of a built-in template (None on user profiles)."""

    key: str = ""  # stable template id, e.g. "web_generic"
    title_zh: str = ""
    title_en: str = ""
    description_zh: str = ""
    description_en: str = ""
    order: int = 100

    def title(self) -> str:
        return tr(self.title_zh, self.title_en or self.title_zh)

    def description(self) -> str:
        return tr(self.description_zh, self.description_en or self.description_zh)


@dataclass
class ValidationIssue:
    level: IssueLevel = IssueLevel.WARNING
    path: str = ""  # e.g. "steps[2].params.point"
    message: str = ""  # localized
    step_index: int = -1  # 0-based, -1 = not about a step


@dataclass
class Profile:
    schema_version: int = PROFILE_SCHEMA_VERSION
    id: str = field(default_factory=new_id)
    name: str = ""
    game: str = ""  # game name; history key (game_key) groups codes of the same game
    description: str = ""
    author: str = ""
    target: TargetMatch = field(default_factory=TargetMatch)
    suggested_exe: str = ""  # hint from an imported file (the author's target exe); never used to match
    coord_mode: CoordMode = CoordMode.AUTO
    code_format: CodeFormat = field(default_factory=CodeFormat)
    steps: list[Step] = field(default_factory=list)
    keywords: KeywordConfig = field(default_factory=KeywordConfig)
    policy: RunPolicy = field(default_factory=RunPolicy)
    template: TemplateInfo | None = None
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    last_test_ok_at: str = ""  # set by RunFlow when a TEST_ONE run reached a result; "" = never tested

    def game_key(self) -> str:
        """History key: ``"game:<squashed game name>"``, or ``"profile:<id>"`` without a game."""
        g = squash(self.game)
        return f"game:{g}" if g else f"profile:{self.id}"

    def enabled_steps(self) -> list[tuple[int, Step]]:
        return [(i, s) for i, s in enumerate(self.steps) if s.enabled and s.type is not StepType.UNKNOWN]

    def first_submit_index(self) -> int:
        """Index of the step that (probably) submits the code: the first enabled input step
        (StepType.sends_input) after the first enabled type_code step - or the type_code step
        itself when no input step follows it (auto-submitting pages); without a type_code step,
        the first enabled input step. -1 when there is none. An attempt is "possibly submitted"
        once a step at or after this index has sent input (SPEC 2.5)."""
        steps = self.enabled_steps()
        tc = next((n for n, (_i, s) in enumerate(steps) if s.type is StepType.TYPE_CODE), None)
        for i, s in steps[tc + 1:] if tc is not None else steps:
            if s.type.sends_input:
                return i
        return steps[tc][0] if tc is not None else -1

    def uses_ocr(self) -> bool:
        for _i, s in self.enabled_steps():
            if s.type.uses_ocr:
                return True
            if isinstance(s.params, TypeCodeParams) and s.params.verify_region is not None:
                return True
        return False

    def has_result_check(self) -> bool:
        return any(s.type is StepType.OCR_CHECK for _i, s in self.enabled_steps())

    def missing_setup(self) -> list[tuple[int, str]]:
        """(step index, field name) of required positions that are not recorded yet: click_point
        ``point`` and ocr_check ``region`` (step order; the setup wizard walks this list)."""
        out: list[tuple[int, str]] = []
        for i, s in self.enabled_steps():
            if isinstance(s.params, ClickPointParams) and s.params.point is None:
                out.append((i, "point"))
            elif isinstance(s.params, OcrCheckParams) and s.params.region is None:
                out.append((i, "region"))
        return out

    def describe_actions(self) -> str:
        """Plain-language summary of what the enabled steps do, shown before an imported
        profile is saved: "此設定檔會：點擊 2 處、輸入序號、按 Enter" / "This profile will: ..."."""
        clicks = sum(1 for _i, s in self.enabled_steps() if s.type in (StepType.CLICK_POINT, StepType.CLICK_TEXT))
        parts: list[str] = []
        if clicks:
            parts.append(tr(f"點擊 {clicks} 處", f"click {clicks} place{'s' if clicks != 1 else ''}"))
        for _i, s in self.enabled_steps():
            p = s.params
            if isinstance(p, TypeCodeParams):
                parts.append(tr("輸入序號", "type the code"))
            elif isinstance(p, TypeTextParams):
                parts.append(tr(f"輸入文字「{p.text}」", f"type the text '{p.text}'"))
            elif isinstance(p, KeyParams):
                parts.append(tr(f"按 {p.keys}", f"press {p.keys}"))
            elif isinstance(p, OcrCheckParams):
                parts.append(tr("辨識結果", "read the result"))
        seen: list[str] = []
        for part in parts:
            if part not in seen:
                seen.append(part)
        if not seen:
            return tr("此設定檔不會做任何動作", "This profile does nothing")
        return tr("此設定檔會：", "This profile will: ") + tr("、", ", ").join(seen)

    def action_lines(self) -> list[tuple[str, bool]]:
        """Every enabled step as one literal line for the import summary, in order:
        ``(text, risky)``. Literal key combos and texts are shown verbatim (author labels are NOT
        used, so a label cannot disguise a step); ``risky`` marks combo_risk warnings, type_text
        without {code}, and click_text steps that are skipped when nothing is found."""
        out: list[tuple[str, bool]] = []
        for n, (_i, s) in enumerate(self.enabled_steps(), 1):
            p = s.params
            risky = False
            if isinstance(p, ClickPointParams):
                detail = p.point.describe() if p.point else tr("（位置未設定）", "(position not set)")
            elif isinstance(p, ClickTextParams):
                detail = f"「{p.text}」"
                if p.on_not_found is TimeoutAction.CONTINUE:
                    detail += tr("（找不到就略過）", " (skipped when not found)")
            elif isinstance(p, TypeCodeParams):
                detail = p.mode.label()
            elif isinstance(p, TypeTextParams):
                detail = f"「{p.text}」"
                risky = "{code}" not in p.text
            elif isinstance(p, KeyParams):
                level, reason = combo_risk(p.keys)
                detail = p.keys + (f" ×{p.repeat}" if p.repeat > 1 else "") + (f"（{reason}）" if reason else "")
                risky = level is not None
            else:
                detail = s.summary()
            out.append((f"{n}. {s.type.label()}：{detail}" if detail else f"{n}. {s.type.label()}", risky))
        return out

    def prepare_import(self) -> None:
        """Make a profile read from a shared file safe (SPEC 6.4.2): the author's target is never
        used - its exe becomes ``suggested_exe`` (a hint for the window picker; dropped when it is
        a FORBIDDEN_TARGET_EXES program) and ``target`` is reset, so the user must pick the
        window (allow_same_process is cleared with it). ``last_test_ok_at`` and ``template`` are
        cleared. The store gives the profile a fresh id when its id is taken."""
        exe = self.target.exe or self.suggested_exe
        self.suggested_exe = "" if exe.casefold() in FORBIDDEN_TARGET_EXES else exe
        self.target = TargetMatch()
        self.last_test_ok_at = ""
        self.template = None

    def reference_sizes(self) -> set[tuple[int, int]]:
        """Client sizes the recorded points/regions were captured at."""
        sizes: set[tuple[int, int]] = set()
        for _i, s in self.enabled_steps():
            for f in dataclasses.fields(s.params):
                v = getattr(s.params, f.name)
                if isinstance(v, (ClientPoint, ClientRegion)):
                    sizes.add((v.ref_w, v.ref_h))
        return sizes

    def validate(self) -> list[ValidationIssue]:
        out: list[ValidationIssue] = []

        def add(level: IssueLevel, path: str, zh: str, en: str) -> None:
            out.append(ValidationIssue(level, path, tr(zh, en)))

        if not self.name.strip():
            add(IssueLevel.WARNING, "name", "設定檔沒有名稱", "The profile has no name")
        if self.target.is_empty():
            add(IssueLevel.WARNING, "target", "尚未選擇目標視窗", "No target window selected")
        if self.target.is_forbidden():
            add(IssueLevel.ERROR, "target.exe",
                f"{self.target.exe} 是系統或命令列程式，不能當作目標，請改選遊戲或兌換網頁的視窗",
                f"{self.target.exe} is a system or command-line program and cannot be the target; "
                "pick the game or redeem page window")
        elif self.target.needs_title():
            add(IssueLevel.ERROR, "target.title", "瀏覽器目標必須設定標題關鍵字（例如「兌換」），以免輸入到其他分頁",
                "A browser target needs a title keyword (e.g. 'Redeem') so input never goes to another tab")
        err = self.target.pattern_error()
        if err:
            out.append(ValidationIssue(IssueLevel.ERROR, "target.title", err))
        out.extend(self.code_format.validate("code_format"))
        enabled = self.enabled_steps()
        if not enabled:
            add(IssueLevel.ERROR, "steps", "沒有任何啟用的步驟", "There are no enabled steps")
        elif not any(s.type is StepType.TYPE_CODE for _i, s in enabled):
            add(IssueLevel.WARNING, "steps", "沒有「輸入序號」步驟，序號不會被輸入", "No 'Type code' step: codes will not be typed")
        for i, s in enumerate(self.steps):
            if s.enabled:
                out.extend(s.validate(i, self))
        if not self.has_result_check() and enabled:
            add(IssueLevel.WARNING, "steps",
                "沒有「辨識結果」步驟：無法判斷是否兌換成功，也無法偵測「操作過於頻繁」；結果會標為「已送出（未確認）」",
                "No 'Read result' step: AutoPress cannot tell whether a code worked or detect rate limits; "
                "results are marked 'Submitted (unconfirmed)'")
        if self.policy.on_unknown is UnknownAction.CONTINUE:
            add(IssueLevel.WARNING, "policy.on_unknown", "無法判讀的結果會直接跳過，輸入到錯誤的地方時不會被發現",
                "Unrecognised results are skipped, so input that went to the wrong place goes unnoticed")
        for kw, a, b in self.keywords.overlaps():
            add(IssueLevel.WARNING, "keywords", f"關鍵字「{kw}」同時出現在「{a.label()}」與「{b.label()}」",
                f"Keyword '{kw}' is in both '{a.label()}' and '{b.label()}'")
        return out

    def clone(self, new_identity: bool = True) -> Profile:
        """Deep copy; with ``new_identity`` the copy gets new profile and step ids and timestamps."""
        p = from_dict(Profile, to_dict(self))
        if new_identity:
            p.id = new_id()
            p.created_at = p.updated_at = now_iso()
            for s in p.steps:
                s.id = new_id()
        return p


# =============================================================================== settings


@dataclass
class HotkeySettings:
    pause_resume: str = "F8"  # registered only while a run is active
    stop: str = "F9"

    def _after_load(self) -> None:
        for name, default in (("pause_resume", "F8"), ("stop", "F9")):
            value = getattr(self, name)
            try:
                value = normalize_combo(value)
            except ValueError:
                value = default
            if validate_hotkey(value) is not None:
                value = default
            setattr(self, name, value)
        if self.pause_resume == self.stop:
            self.pause_resume, self.stop = "F8", "F9"


@dataclass
class DelaySettings:
    """Defaults copied into NEW steps (make_step); running profiles use their step values."""

    after_focus_ms: int = _num(200, 0, 10000)
    after_click_ms: int = _num(120, 0, 10000)
    key_delay_ms: int = _num(15, 0, 1000)
    clipboard_restore_ms: int = _num(300, 50, 5000)  # Ctrl+V -> restore the user's clipboard


@dataclass
class OcrSettings:
    enabled: bool = True
    threads: int = _num(4, -1, 32)  # ONNX Runtime intra-op threads (capped at os.cpu_count()); -1 = all
    # cores. 4 keeps a polling run light on the game (ocr.md 3.4: 220 ms vs 195 ms at 640x360)
    det_side: int = _num(960, 320, 4096)  # Det.limit_side_len for EVERY read (SPEC 5.3)
    warmup_on_start: bool = True
    review_threshold: float = _num(0.95, 0.0, 1.0)  # char confidence below -> needs review


@dataclass
class Settings:
    schema_version: int = SETTINGS_SCHEMA_VERSION
    language: Language = Language.AUTO
    theme: ThemeName = ThemeName.DARK
    hotkeys: HotkeySettings = field(default_factory=HotkeySettings)
    failsafe_enabled: bool = True  # mouse in an outer top-left desktop corner aborts a run (failsafe_corners)
    failsafe_margin_px: int = _num(3, 0, 50)
    pause_on_user_input: bool = True
    countdown_s: int = _num(3, 0, 10)  # before a run and before a real step test
    resume_countdown_s: int = _num(2, 0, 10)  # before a paused run continues (input ignored meanwhile)
    confirm_run_over: int = _num(30, 0, 100000)  # ask before runs with more codes; 0 = never
    minibar_enabled: bool = True  # False: the main window is minimised (not hidden) during runs
    delays: DelaySettings = field(default_factory=DelaySettings)
    default_typing_mode: TypingMode = TypingMode.UNICODE
    ocr: OcrSettings = field(default_factory=OcrSettings)
    skip_history_on_import: bool = True
    history_skip_statuses: list[CodeStatus] = field(
        default_factory=lambda: [CodeStatus.SUCCESS, CodeStatus.USED])  # SUBMITTED is unconfirmed
    save_evidence: bool = True
    evidence_keep_days: int = _num(30, 0, 3650)  # 0 = keep forever
    daily_cap: int = _num(0, 0, 100000)  # max attempts per calendar day (all games); 0 = no cap
    active_profile_id: str = ""
    run_selection: RunSelection = RunSelection.UNFINISHED
    window_geometry: str = ""  # hex of QWidget.saveGeometry()
    minibar_pos: list[int] = _strict_list()  # [x, y] logical, [] = automatic
    first_run_done: bool = False

    def _after_load(self) -> None:
        if len(self.minibar_pos) not in (0, 2):
            self.minibar_pos = []

    def validate(self) -> list[ValidationIssue]:
        out = []
        for name in ("pause_resume", "stop"):
            reason = validate_hotkey(getattr(self.hotkeys, name))
            if reason:
                out.append(ValidationIssue(IssueLevel.ERROR, f"hotkeys.{name}", reason))
        if self.hotkeys.pause_resume == self.hotkeys.stop:
            out.append(ValidationIssue(IssueLevel.ERROR, "hotkeys",
                                       tr("暫停與停止不能用同一個快捷鍵", "Pause and stop need different hotkeys")))
        return out


# =============================================================================== codes


@dataclass
class CodeItem:
    """One code in the queue (codes.queue.CodeQueue)."""

    id: str = field(default_factory=new_id)
    code: str = ""  # normalised code that will be typed
    raw: str = ""  # text it was extracted from
    game_key: str = ""  # Profile.game_key() of the active profile at import; "" = no game assigned yet
    game: str = ""  # that profile's game name (display)
    source: CodeSource = CodeSource.MANUAL
    source_detail: str = ""  # file / image name
    confidence: float | None = None  # min OCR char confidence (None for text sources)
    char_confs: list[float] = _strict_list()  # per character of `code` (OCR only)
    flagged: list[int] = field(default_factory=list)  # low-confidence / repaired characters: REVIEW gate
    lookalikes: list[int] = field(default_factory=list)  # look-alike characters: highlighted only
    status: CodeStatus = CodeStatus.PENDING
    message: str = ""  # last result text / note (user-visible)
    checked: bool = True
    attempts: int = _num(0, 0, 1000000)
    added_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)


@dataclass
class CodeCandidate:
    """A code found by extraction, before it is added to the queue (codes.extract)."""

    code: str = ""
    raw: str = ""
    char_confs: list[float] | None = None
    flagged: list[int] = field(default_factory=list)  # low-confidence + repaired indices (-> REVIEW)
    lookalikes: list[int] = field(default_factory=list)  # look-alike indices (highlight only)
    repaired: list[int] = field(default_factory=list)  # indices changed by charset repair
    line_index: int = -1  # OcrResult.lines index (-1 for text sources)
    likely: bool = True  # False for word-like tokens (pre-unchecked in previews)
    duplicate_of: str = ""  # id of an existing queue item with the same code_key
    history_status: CodeStatus | None = None  # latest history status for the active game

    @property
    def confidence(self) -> float | None:
        return min(self.char_confs) if self.char_confs else None


@dataclass
class AddResult:
    added: list[str] = field(default_factory=list)  # ids of new queue items
    duplicates: int = 0
    skipped_history: int = 0
    invalid: int = 0


@dataclass
class QueueEvent:
    kind: QueueEventKind = QueueEventKind.RESET
    ids: list[str] = field(default_factory=list)


# =============================================================================== OCR


@dataclass
class OcrOptions:
    upscale: int = _num(1, 1, 3)  # bicubic factor before OCR (2 for text under ~16 px)
    det_side: int = _num(960, 320, 4096)  # Det.limit_side_len (max side); steps use Settings.ocr.det_side (960)
    code_charset: str = ""  # expanded allowed chars: re-read Latin-looking lines constrained to them
    min_score: float = _num(0.0, 0.0, 1.0)  # drop lines below this score


@dataclass
class OcrLine:
    text: str = ""
    quad: list[tuple[float, float]] = _strict_list()  # tl, tr, br, bl in image px
    score: float = 0.0
    char_confs: list[float] | None = None  # aligned with `text` after a constrained re-read

    def bounds(self) -> Rect:
        if not self.quad:
            return 0, 0, 0, 0
        xs = [q[0] for q in self.quad]
        ys = [q[1] for q in self.quad]
        x0, y0 = math.floor(min(xs)), math.floor(min(ys))
        return x0, y0, math.ceil(max(xs)) - x0, math.ceil(max(ys)) - y0

    def center(self) -> tuple[float, float]:
        if not self.quad:
            return 0.0, 0.0
        return (sum(q[0] for q in self.quad) / len(self.quad), sum(q[1] for q in self.quad) / len(self.quad))


@dataclass
class OcrRow:
    text: str = ""
    line_indices: list[int] = field(default_factory=list)


@dataclass
class OcrResult:
    lines: list[OcrLine] = field(default_factory=list)
    width: int = 0  # input image size (before upscaling)
    height: int = 0
    elapsed_ms: float = 0.0
    origin: Point = (0, 0)  # physical screen position of the image's top-left, if captured

    def rows(self) -> list[OcrRow]:
        """Lines grouped into reading-order rows: two lines share a row when their vertical
        overlap is at least half the smaller height (ocr_common.group_rows)."""
        boxes = []
        for i, ln in enumerate(self.lines):
            x, y, _w, h = ln.bounds()
            boxes.append((y, y + h, x, i))
        boxes.sort(key=lambda b: (b[0] + b[1]) / 2)
        rows: list[dict[str, Any]] = []
        for b in boxes:
            for r in rows:
                ov = min(r["y1"], b[1]) - max(r["y0"], b[0])
                if ov >= 0.5 * min(r["y1"] - r["y0"], b[1] - b[0]):
                    r["b"].append(b)
                    r["y0"], r["y1"] = min(r["y0"], b[0]), max(r["y1"], b[1])
                    break
            else:
                rows.append({"y0": b[0], "y1": b[1], "b": [b]})
        out = []
        for r in rows:
            r["b"].sort(key=lambda b: b[2])
            idx = [b[3] for b in r["b"]]
            out.append(OcrRow(text=" ".join(self.lines[i].text for i in idx), line_indices=idx))
        return out

    def text(self) -> str:
        return "\n".join(r.text for r in self.rows())

    def to_screen(self, x: float, y: float) -> Point:
        """Image pixel -> physical screen point (``origin`` + rounded offset)."""
        return self.origin[0] + int(math.floor(x + 0.5)), self.origin[1] + int(math.floor(y + 0.5))


@dataclass
class TextHit:
    x: float = 0.0  # click point in image pixels (mean of the matched quad, sub-box for "contains")
    y: float = 0.0
    line_index: int = -1
    text: str = ""  # full OCR line text
    score: float = 0.0
    exact: bool = False


# =============================================================================== windows / monitors


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int = 0
    title: str = ""
    class_name: str = ""
    pid: int = 0
    exe_path: str = ""  # full image path ("" if it could not be read)
    rect: Rect = (0, 0, 0, 0)  # GetWindowRect (includes invisible borders)
    client: Rect = (0, 0, 0, 0)  # client area in screen coordinates
    minimized: bool = False
    visible: bool = True

    @property
    def exe_name(self) -> str:
        return self.exe_path.replace("\\", "/").rsplit("/", 1)[-1] if self.exe_path else ""

    def to_target(self) -> TargetMatch:
        """Default match rule for this window: exe + class + title contains the current title."""
        return TargetMatch(exe=self.exe_name, title=self.title, title_mode=TitleMatch.CONTAINS,
                           class_name=self.class_name)


@dataclass(frozen=True)
class Monitor:
    device: str = ""  # \\.\DISPLAY1
    rect: Rect = (0, 0, 0, 0)  # physical
    work: Rect = (0, 0, 0, 0)  # physical work area (without the taskbar)
    dpi: int = 96
    primary: bool = False

    @property
    def scale(self) -> float:
        return self.dpi / 96.0


# =============================================================================== runs


@dataclass
class AttemptRecord:
    """One finished attempt; also the history record (codes.history, one JSON line each)."""

    id: str = field(default_factory=new_id)
    run_id: str = ""
    code_id: str = ""
    code: str = ""
    game: str = ""  # profile.game at attempt time (display)
    game_key: str = ""  # profile.game_key()
    profile_id: str = ""
    profile_name: str = ""
    status: CodeStatus = CodeStatus.FAILED
    result: ResultClass | None = None  # None when the profile has no result check
    message: str = ""  # OCR result text or error message
    matched_keyword: str = ""
    started_at: str = ""
    finished_at: str = ""
    duration_ms: int = 0
    evidence_path: str = ""  # relative to paths.data_dir(), "" if none


@dataclass
class PlanItem:
    code_id: str = ""
    code: str = ""


@dataclass
class RunPlan:
    run_id: str = field(default_factory=new_id)
    profile: Profile = field(default_factory=Profile)
    items: list[PlanItem] = field(default_factory=list)
    target_hwnd: int = 0  # resolved by preflight; the runner re-finds it if it dies
    mode: PlanMode = PlanMode.NORMAL
    step_index: int = -1  # TEST_STEP only
    dry_run: bool = False  # TEST_STEP only: locate / OCR, but send no input
    sample_code: str = "TEST-1234"  # TEST_STEP only
    settings: Settings = field(default_factory=Settings)  # snapshot at start


@dataclass
class LogEntry:
    time: str = field(default_factory=now_iso)
    level: LogLevel = LogLevel.INFO
    message: str = ""  # localized
    code_id: str = ""
    step_index: int = -1


@dataclass
class Attention:
    """Something the user must look at; the run is paused (or stopped) when this is emitted."""

    kind: PauseReason = PauseReason.ERROR
    message: str = ""  # localized
    code_id: str = ""
    step_index: int = -1
    ocr_text: str = ""
    evidence_path: str = ""


@dataclass
class RunSummary:
    run_id: str = ""
    profile_id: str = ""
    profile_name: str = ""
    mode: PlanMode = PlanMode.NORMAL
    started_at: str = ""
    finished_at: str = ""
    total: int = 0
    done: int = 0  # codes that reached a final status in this run
    counts: dict[CodeStatus, int] = field(default_factory=dict)
    stop_reason: StopReason = StopReason.COMPLETED
    message: str = ""


PREFLIGHT_KEYS: tuple[str, ...] = (
    "profile_errors", "points_missing", "no_codes", "target_not_set", "target_not_found", "target_is_self",
    "target_multiple", "target_minimized", "elevated", "elevation_unknown", "size_changed", "ocr_failed",
    "ocr_loading", "capture_blank", "no_result_check", "fast_interval", "daily_cap",
    "profile_warnings", "target_forbidden", "target_title_required", "unassigned_codes", "untested_profile",
    "dpi_changed", "no_verify", "estimate",
)
"""Every PreflightIssue.key runner.preflight may produce (SPEC section 7.2)."""

PREFLIGHT_ACTIONS: tuple[str, ...] = ("restart_admin", "pick_window", "preview", "open_profile", "wait_ocr",
                                      "assign_codes", "test_one", "realign")
"""PreflightIssue.action tokens; the Run page maps each to a button ("" = no button)."""


@dataclass
class PreflightIssue:
    level: IssueLevel = IssueLevel.WARNING
    key: str = ""  # one of PREFLIGHT_KEYS
    message: str = ""  # localized
    hint: str = ""  # localized
    action: str = ""  # one of PREFLIGHT_ACTIONS, or ""


@dataclass
class PreflightReport:
    issues: list[PreflightIssue] = field(default_factory=list)
    target: WindowInfo | None = None
    code_count: int = 0
    ocr_needed: bool = False

    @property
    def ok(self) -> bool:
        return not any(i.level is IssueLevel.ERROR for i in self.issues)


@dataclass
class PreviewMark:
    step_index: int = 0  # 0-based
    step_id: str = ""
    kind: PreviewKind = PreviewKind.POINT
    rect: Rect = (0, 0, 1, 1)  # physical; points are 1x1
    label: str = ""  # e.g. "2 點擊位置"
    ok: bool = True  # inside the client area and on the target window


@dataclass
class StepTestResult:
    ok: bool = False
    step_index: int = -1
    message: str = ""  # localized
    point: Point | None = None  # where it clicked / found text (physical)
    rect: Rect | None = None  # region it read (physical)
    ocr_text: str = ""
    result: ResultClass | None = None
    duration_ms: int = 0


# =============================================================================== (de)serialisation


class _Invalid(Exception):
    pass


_HINTS: dict[type, dict[str, Any]] = {}


def _type_hints(cls: type) -> dict[str, Any]:
    h = _HINTS.get(cls)
    if h is None:
        h = typing.get_type_hints(cls)
        _HINTS[cls] = h
    return h


def to_dict(obj: Any) -> Any:
    """JSON-ready copy: dataclasses -> dicts, enums -> values, tuples -> lists."""
    enc = getattr(obj, "_encode", None)
    if enc is not None and dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return enc()
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_dict(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, enum.Enum):
        return obj.value
    if isinstance(obj, Mapping):
        return {(k.value if isinstance(k, enum.Enum) else str(k)): to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_dict(v) for v in obj]
    return obj


def _convert(tp: Any, value: Any) -> Any:
    if tp is Any:
        return value
    origin = typing.get_origin(tp)
    if origin is typing.Union or origin is types.UnionType:
        args = typing.get_args(tp)
        if value is None:
            if type(None) in args:
                return None
            raise _Invalid
        for a in args:
            if a is type(None):
                continue
            try:
                return _convert(a, value)
            except _Invalid:
                continue
        raise _Invalid
    if origin is list:
        (a,) = typing.get_args(tp) or (Any,)
        if not isinstance(value, (list, tuple)):
            raise _Invalid
        out = []
        for v in value:
            try:
                out.append(_convert(a, v))
            except _Invalid:
                log.debug("dropping invalid list element %r", v)
        return out
    if origin is dict:
        ka, va = typing.get_args(tp) or (Any, Any)
        if not isinstance(value, Mapping):
            raise _Invalid
        res = {}
        for k, v in value.items():
            try:
                res[_convert(ka, k)] = _convert(va, v)
            except _Invalid:
                log.debug("dropping invalid dict entry %r", k)
        return res
    if origin is tuple:
        args = typing.get_args(tp)
        if not isinstance(value, (list, tuple)):
            raise _Invalid
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(_convert(args[0], v) for v in value)
        if len(value) != len(args):
            raise _Invalid
        return tuple(_convert(a, v) for a, v in zip(args, value))
    if isinstance(tp, type):
        if issubclass(tp, enum.Enum):
            try:
                return tp(value)
            except ValueError:
                raise _Invalid from None
        if dataclasses.is_dataclass(tp):
            if isinstance(value, tp):
                return value
            if not isinstance(value, Mapping):
                raise _Invalid
            required = getattr(tp, "_REQUIRED", ())
            if required:  # e.g. a recorded point: an unusable coordinate means "not set", not (0, 0)
                hints = _type_hints(tp)
                for key in required:
                    if key not in value:
                        raise _Invalid
                    _convert(hints[key], value[key])
            return from_dict(tp, value)
        if tp is bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, int) and value in (0, 1):
                return bool(value)
            if isinstance(value, str) and value.strip().lower() in ("true", "false"):
                return value.strip().lower() == "true"
            raise _Invalid
        if tp is int:
            if isinstance(value, bool):
                raise _Invalid
            if isinstance(value, int):
                return value
            if isinstance(value, float) and math.isfinite(value) and value.is_integer():
                return int(value)
            if isinstance(value, str):
                try:
                    return int(value.strip())
                except ValueError:
                    raise _Invalid from None
            raise _Invalid
        if tp is float:
            if isinstance(value, bool):
                raise _Invalid
            if isinstance(value, (int, float)):
                f = float(value)
                if math.isfinite(f):
                    return f
                raise _Invalid
            if isinstance(value, str):
                try:
                    f = float(value.strip())
                except ValueError:
                    raise _Invalid from None
                if math.isfinite(f):
                    return f
            raise _Invalid
        if tp is str:
            if isinstance(value, str):
                return clean_text(value)
            raise _Invalid
        if isinstance(value, tp):
            return value
        raise _Invalid
    return value


def from_dict(cls: type[T_], data: Any) -> T_:
    """Build ``cls`` from JSON data; never raises for bad content (falls back to defaults).
    ``data`` that is not a mapping gives ``cls()``."""
    dec = getattr(cls, "_decode", None)
    if dec is not None:
        return dec(data if isinstance(data, Mapping) else {})
    if not isinstance(data, Mapping):
        data = {}
    hints = _type_hints(cls)
    kwargs: dict[str, Any] = {}
    for f in dataclasses.fields(cls):  # type: ignore[arg-type]
        if not f.init or f.name not in data:
            continue
        try:
            value = _convert(hints[f.name], data[f.name])
            if f.metadata.get("strict") and isinstance(value, list) and (
                    not isinstance(data[f.name], (list, tuple)) or len(value) != len(data[f.name])):
                raise _Invalid  # a positional list lost an element: reject the whole list
        except _Invalid:
            log.debug("%s.%s: invalid value %r, using default", cls.__name__, f.name, data[f.name])
            continue
        rng = f.metadata.get("range")
        if rng and isinstance(value, (int, float)) and not isinstance(value, bool):
            value = _clamp(value, rng)
        kwargs[f.name] = value
    obj = cls(**kwargs)
    hook = getattr(obj, "_after_load", None)
    if hook is not None:
        hook()
    return obj


def clone(obj: T_) -> T_:
    """Deep copy of a serialisable dataclass through to_dict / from_dict."""
    return from_dict(type(obj), to_dict(obj))


# -- schema migrations -------------------------------------------------------------------

_CURRENT_VERSIONS = {"profile": PROFILE_SCHEMA_VERSION, "settings": SETTINGS_SCHEMA_VERSION,
                     "queue": QUEUE_SCHEMA_VERSION, "history": HISTORY_SCHEMA_VERSION}
_MIGRATIONS: dict[str, dict[int, Callable[[dict[str, Any]], dict[str, Any]]]] = {k: {} for k in _CURRENT_VERSIONS}


def register_migration(kind: str, from_version: int, fn: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
    """Register ``fn`` upgrading ``kind`` data from ``from_version`` to ``from_version + 1``."""
    _MIGRATIONS[kind][from_version] = fn


def migrate(kind: str, data: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of ``data`` upgraded to the current schema of ``kind`` ("profile",
    "settings", "queue", "history"). Missing ``schema_version`` counts as 1. Data from a NEWER
    version is returned as is (loading ignores unknown keys)."""
    out = dict(data)
    current = _CURRENT_VERSIONS[kind]
    v = out.get("schema_version", 1)
    v = v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 1
    while v < current:
        fn = _MIGRATIONS[kind].get(v)
        if fn is not None:
            out = fn(out)
        v += 1
    if v <= current:
        out["schema_version"] = current
    return out


def is_newer_schema(kind: str, data: Mapping[str, Any]) -> bool:
    v = data.get("schema_version", 1)
    return isinstance(v, int) and not isinstance(v, bool) and v > _CURRENT_VERSIONS[kind]


def profile_from_dict(data: Any) -> Profile:
    """Load a profile (migrations + forward-compatible decoding). Never raises."""
    if not isinstance(data, Mapping):
        return Profile()
    newer = is_newer_schema("profile", data)
    p = from_dict(Profile, migrate("profile", data))
    if not newer:
        p.schema_version = PROFILE_SCHEMA_VERSION
    return p


def settings_from_dict(data: Any) -> Settings:
    """Load settings (migrations + forward-compatible decoding). Never raises."""
    if not isinstance(data, Mapping):
        return Settings()
    newer = is_newer_schema("settings", data)
    s = from_dict(Settings, migrate("settings", data))
    if not newer:
        s.schema_version = SETTINGS_SCHEMA_VERSION
    return s
