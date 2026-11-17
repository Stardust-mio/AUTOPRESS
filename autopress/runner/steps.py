# OWNED BY G4
"""Execution of one step (internal to the runner; the UI uses RunSession.test_step).

The runner (runner.worker) builds a StepContext per code and calls execute_step for every
enabled step. The context owns the capture rules that hold for EVERY capture (SPEC 2.1 / 2.5):
the RunSession's masked rects are blanked (ocr.imageio.mask_rects) before OCR, blank checks and
evidence; a capture that looks blank (capture.looks_blank) is re-checked on the whole client area
and raises CaptureBlank when the client is blank too (an empty result region on a web page is
uniform as well and must not pause the run). Every wait goes through RunControl.sleep; OCR uses
``OcrOptions(upscale=params.upscale or 1, det_side=settings.ocr.det_side)``.
"""

from __future__ import annotations

import logging
import math
import random
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

import numpy as np

from .. import capture as capture_mod
from ..codes import normalize
from ..i18n import tr
from ..models import (
    SEPARATOR_CHARS,
    BetweenSegments,
    ClearMethod,
    ClickPointParams,
    ClickTextParams,
    ClientPoint,
    ClientRegion,
    FocusWindowParams,
    IssueLevel,
    KeyParams,
    KeywordConfig,
    LogLevel,
    OcrCheckParams,
    OcrOptions,
    OcrResult,
    Point,
    Profile,
    Rect,
    ResultClass,
    Settings,
    SplitMode,
    Step,
    StepType,
    TextHit,
    TimeoutAction,
    TypeCodeParams,
    TypeTextParams,
    WaitParams,
    WaitTextParams,
    WindowInfo,
    combo_risk,
    intersect_rect,
    parse_combo_names,
    point_in_rect,
    resolve_point,
    resolve_region,
)
from ..ocr import imageio, textfind
from ..ocr.engine import OcrUnavailable
from ..ocr.service import OcrCancelled, OcrTimeout
from ..storage import StorageError
from ..textutil import nfkc, norm_match
from ..win32.input import ClipboardBusy, ForegroundLost, UnmappableChar
from . import messages as msg
from .classify import classify_text
from .control import RunControl

if TYPE_CHECKING:
    from .backend import Backend

log = logging.getLogger(__name__)

MAX_UPSCALED_SIDE = 4096  # auto upscale retries at 2x only while the long side stays <= 4096 px
STABLE_CLIENT_MAX_S = 5.0  # restored targets: wait until two client_rect reads 100 ms apart agree
SEGMENT_SELECT_SETTLE_S = 0.05  # type_code: before selecting a later box, let the page move the focus


class StepError(Exception):
    """A step could not do its job (text not found, OCR failed or timed out, capture failed,
    unmappable character, typed text mismatch...). ``str(exc)`` is localized (SPEC 7.1).
    Outcome (SPEC 2.5, PX-07): a result already read by ocr_check is KEPT (the error is logged
    as a warning); otherwise REVIEW when the attempt was possibly submitted; FAILED only for
    errors before submitting. Guard errors (InjectionAborted) pause instead."""


class CaptureBlank(Exception):
    """A capture of the target (and its whole client area) is black / uniform: the runner pauses
    with PauseReason.CAPTURE_BLANK (item handled as for guard trips)."""


class TargetGone(Exception):
    """The target window no longer exists (client_rect / capture of a closed window): the runner
    pauses with PauseReason.TARGET_LOST."""


class TitleChanged(Exception):
    """Right before a step that sends input, the target's CURRENT title no longer matches the
    profile's title rule (a browser keeps its HWND when the active tab changes; gate G-04): the
    runner pauses with PauseReason.TITLE_CHANGED (item handled as for guard trips)."""


@dataclass
class StepOutcome:
    ok: bool = True
    message: str = ""  # localized
    result: ResultClass | None = None  # set by ocr_check
    matched_keyword: str = ""
    ocr_text: str = ""
    point: Point | None = None
    rect: Rect | None = None
    evidence_path: str = ""
    sent_input: bool = False  # the step injected input (used for "possibly submitted")


def render_template(text: str, code: str, index: int) -> str:
    """Fill {code}, {index} (1-based: the runner passes plan index + 1), {date} (YYYY-MM-DD) and
    {time} (HH:MM:SS); unknown placeholders and stray braces are left as they are."""
    now = datetime.now()
    out = text or ""
    for key, value in (("{code}", code), ("{index}", str(index)), ("{date}", now.strftime("%Y-%m-%d")),
                       ("{time}", now.strftime("%H:%M:%S"))):
        out = out.replace(key, value)
    return out


def code_segments(code: str, p: TypeCodeParams, profile: Profile) -> list[str]:
    """The texts type_code types (SPEC 5.3): NONE - the code exactly as shown in the queue
    (separators removed only with ``strip_separators``); SEPARATOR - split at the separators the
    code kept from its source (segments may differ in length, e.g. 4-6-2); FIXED - group sizes
    (``group_sizes`` or the profile's code_format.groups)."""
    seps = p.separators or SEPARATOR_CHARS
    if p.split is SplitMode.NONE:
        return [normalize.strip_separators(code, seps) if p.strip_separators else code]
    if p.split is SplitMode.SEPARATOR:
        segs = normalize.split_code(code, SplitMode.SEPARATOR, seps)
    else:
        sizes = [int(s) for s in (p.group_sizes or profile.code_format.groups)]
        if not sizes or any(s <= 0 for s in sizes):
            raise StepError(tr("依固定字數拆段需要設定每段字數", "Fixed split needs group sizes"))
        segs = normalize.split_code(code, SplitMode.FIXED, seps, sizes)
    return [s for s in segs if s] or [code]


def is_in_front(backend: Backend, target: WindowInfo, allow_same_process: bool) -> bool:
    fg = backend.foreground()
    if fg == target.hwnd:
        return True
    return bool(allow_same_process and fg and backend.window_pid(fg) == target.pid)


def wait_stable_client(backend: Backend, control: RunControl, hwnd: int, max_s: float = STABLE_CLIENT_MAX_S) -> Rect:
    """Exclusive-fullscreen games switch display mode after a restore: wait until two
    client_rect reads 100 ms apart agree (max ``max_s``)."""
    end = time.monotonic() + max_s
    prev = backend.client_rect(hwnd)
    while time.monotonic() < end:
        control.sleep(0.1)
        cur = backend.client_rect(hwnd)
        if cur == prev and cur[2] > 0 and cur[3] > 0:
            return cur
        prev = cur
    return prev


def bring_target_to_front(backend: Backend, control: RunControl, target: WindowInfo, *, allow_same_process: bool,
                          timeout_s: float = 3.0, settle_s: float = 0.2, restore: bool = True) -> bool:
    """Foreground the target (restoring a minimized window) unless it already is in front;
    then wait for a stable client rect and ``settle_s``. False when it could not be activated."""
    minimized = backend.is_minimized(target.hwnd)
    if not minimized and is_in_front(backend, target, allow_same_process):
        return True
    if minimized and not restore:
        return False
    if not backend.bring_to_foreground(target.hwnd, control.sleep, timeout_s):
        return False
    wait_stable_client(backend, control, target.hwnd)
    if settle_s > 0:
        control.sleep(settle_s)
    return True


def _unmappable(exc: BaseException) -> str:
    for attr in ("char", "ch"):
        value = getattr(exc, attr, None)
        if isinstance(value, str) and value:
            return value
    for a in getattr(exc, "args", ()):
        if isinstance(a, str) and len(a) == 1:
            return a
    return "?"


class StepContext:
    """Everything a step needs for one code. Created by the runner (or a step test)."""

    def __init__(self, *, backend: Backend, control: RunControl, profile: Profile, settings: Settings,
                 target: WindowInfo, guard: Any = None, code: str = "", index: int = 0, run_id: str = "",
                 dry_run: bool = False, keywords: Callable[[], KeywordConfig] | None = None,
                 masked_rects: Callable[[], Sequence[Rect]] | None = None,
                 log_fn: Callable[[LogLevel, str], None] | None = None,
                 evidence_seq: Callable[[], int] | None = None) -> None:
        self.backend = backend
        self.control = control
        self.profile = profile
        self.settings = settings
        self.target = target
        self.guard = guard
        self.code = code
        self.index = index  # 0-based position in the plan
        self.run_id = run_id
        self.dry_run = dry_run
        self._keywords = keywords
        self._masked = masked_rects
        self._log = log_fn
        self._evidence_seq = evidence_seq
        self.baselines: dict[int, set[str]] = {}  # ocr_check step index -> norm_match texts read before submit
        self.step_index = -1

    # ------------------------------------------------------------------ helpers
    def sleep(self, seconds: float) -> None:
        if self.dry_run:
            return
        if seconds > 0:
            self.control.sleep(seconds)
        else:
            self.control.checkpoint()

    def log(self, level: LogLevel, text: str) -> None:
        if self._log is not None:
            self._log(level, text)

    def masked_rects(self) -> list[Rect]:
        return [tuple(r) for r in (self._masked() if self._masked is not None else ())]  # type: ignore[misc]

    def keywords(self) -> KeywordConfig:
        return self._keywords() if self._keywords is not None else self.profile.keywords

    def classify(self, text: str) -> tuple[ResultClass, str]:
        return classify_text(text, self.keywords())

    def guard_passed(self) -> int:
        return int(getattr(self.guard, "passed", 0) or 0) if self.guard is not None else 0

    # ------------------------------------------------------------------ geometry
    def alive(self) -> bool:
        try:
            return bool(self.backend.is_alive(self.target))
        except Exception:  # noqa: BLE001 - a failing probe means "gone"
            return False

    def client(self) -> Rect:
        try:
            rect = self.backend.client_rect(self.target.hwnd)
        except OSError as exc:
            if not self.alive():
                raise TargetGone() from exc
            raise
        if rect[2] <= 0 or rect[3] <= 0:
            if not self.alive():
                raise TargetGone()
            raise StepError(msg.capture_failed(tr("視窗沒有大小（可能已縮到最小）", "the window has no size (minimized?)")))
        return rect

    def dpi(self) -> int:
        try:
            return int(self.backend.window_dpi(self.target.hwnd)) or 96
        except Exception:  # noqa: BLE001
            return 96

    def resolve(self, p: ClientPoint) -> Point:
        return resolve_point(self.client(), p, self.profile.coord_mode, dpi=self.dpi())

    def region(self, r: ClientRegion | None) -> Rect:
        """Physical rect of ``r`` (None = the whole client area), clipped to the client area."""
        client = self.client()
        if r is None:
            return client
        rect = resolve_region(client, r, self.profile.coord_mode, dpi=self.dpi())
        clipped = intersect_rect(rect, client)
        if clipped is None:
            raise StepError(msg.capture_failed(msg.region_outside()))
        return clipped

    def point_on_target(self, x: int, y: int) -> tuple[bool, str]:
        """Dry-run check of a click point: inside the client area and not covered by another
        window (AutoPress's own windows do not count)."""
        if not point_in_rect(self.client(), x, y):
            return False, tr("位置在目標視窗外", "The position is outside the target window")
        root = self.backend.window_at(x, y, skip_own=True)
        if not root or root == self.target.hwnd:
            return True, ""
        if self.profile.target.allow_same_process and self.backend.window_pid(root) == self.target.pid:
            return True, ""
        info = self.backend.window_info(root)
        title = info.title if info and info.title else "?"
        return False, tr(f"點擊位置被「{title}」遮住", f'The click position is covered by "{title}"')

    # ------------------------------------------------------------------ capture / OCR
    def _grab(self, rect: Rect) -> np.ndarray:
        try:
            return self.backend.grab(rect)
        except (capture_mod.CaptureError, OSError) as exc:
            if not self.alive():
                raise TargetGone() from exc
            # CaptureError's str() is already the full 7.1 sentence: wrap only its short reason (G2)
            raise StepError(msg.capture_failed(getattr(exc, "reason", "") or str(exc) or type(exc).__name__)) from exc

    def _mask(self, img: np.ndarray, rect: Rect, masks: list[Rect]) -> np.ndarray:
        if not masks:
            return img
        return imageio.mask_rects(img, (rect[0], rect[1]), masks)

    def capture(self, rect: Rect) -> np.ndarray:
        """Masked capture of a physical rect; CaptureBlank when it and the client are blank."""
        self.control.checkpoint()
        masks = self.masked_rects()
        img = self._mask(self._grab(rect), rect, masks)
        if capture_mod.looks_blank(img):
            client = self.client()
            if tuple(rect) == tuple(client):
                raise CaptureBlank()
            full = self._mask(self._grab(client), client, masks)
            if capture_mod.looks_blank(full):
                raise CaptureBlank()
        return img

    def ocr_image(self, img: np.ndarray, upscale: int = 1, origin: Point = (0, 0)) -> OcrResult:
        opts = OcrOptions(upscale=max(1, min(3, int(upscale or 1))), det_side=self.settings.ocr.det_side)
        try:
            res = self.backend.ocr(img, opts, lambda: self.control.stop_requested)
        except OcrCancelled as exc:
            self.control.checkpoint()  # a stop request -> StopRequested
            raise StepError(msg.ocr_timeout()) from exc
        except OcrTimeout as exc:
            raise StepError(msg.ocr_timeout()) from exc
        except OcrUnavailable as exc:
            # OcrUnavailable's str() is already the full 7.1 sentence: wrap only its short reason (G2)
            raise StepError(msg.ocr_failed(getattr(exc, "reason", "") or str(exc) or type(exc).__name__)) from exc
        self.control.checkpoint()  # OCR is the only non-interruptible wait: check right after it
        res.origin = (int(origin[0]), int(origin[1]))
        return res

    def read(self, rect: Rect, upscale: int = 1) -> tuple[np.ndarray, OcrResult]:
        img = self.capture(rect)
        return img, self.ocr_image(img, upscale, (rect[0], rect[1]))

    def save_evidence(self, img: np.ndarray) -> str:
        seq = self._evidence_seq() if self._evidence_seq is not None else 0
        try:
            return self.backend.save_evidence(img, self.run_id or "test", seq)
        except (StorageError, OSError, ValueError) as exc:
            log.warning("evidence not saved: %s", exc)
            self.log(LogLevel.WARNING, tr(f"無法儲存證據圖片：{exc}", f"Could not save the evidence image: {exc}"))
            return ""

    # ------------------------------------------------------------------ input (never in dry runs)
    def click(self, x: int, y: int, button: Any, double: bool, settle_ms: int, hold_ms: int) -> None:
        self.backend.click(int(x), int(y), self.guard, button, double, settle_ms, hold_ms, self.control.sleep)

    def type(self, text: str, mode: Any, key_delay_ms: int, hold_ms: int) -> None:
        try:
            self.backend.type_text(text, self.guard, mode, key_delay_ms, hold_ms,
                                   self.settings.delays.clipboard_restore_ms, self.control.sleep)
        except ClipboardBusy as exc:
            raise StepError(msg.clipboard_busy()) from exc
        except UnmappableChar as exc:
            raise StepError(msg.unmappable_char(_unmappable(exc))) from exc

    def combo(self, keys: str, repeat: int = 1, interval_ms: int = 50, hold_ms: int = 0) -> None:
        self.backend.press_combo(keys, self.guard, repeat, interval_ms, hold_ms, self.control.sleep)

    def clear(self, method: Any) -> None:
        self.backend.clear_field(self.guard, method, self.control.sleep)


# =============================================================================== step handlers


def _focus_window(p: FocusWindowParams, ctx: StepContext) -> StepOutcome:
    ok = bring_target_to_front(ctx.backend, ctx.control, ctx.target,
                               allow_same_process=ctx.profile.target.allow_same_process,
                               timeout_s=p.timeout_ms / 1000.0, settle_s=0.0, restore=p.restore_minimized)
    if not ok:
        raise ForegroundLost(msg.focus_failed())
    ctx.sleep(p.settle_ms / 1000.0)
    return StepOutcome(message=msg.focused())


def _click_point(p: ClickPointParams, ctx: StepContext) -> StepOutcome:
    if p.point is None:
        raise StepError(msg.position_not_set())
    x, y = ctx.resolve(p.point)
    if p.jitter_px > 0:
        cx, cy, cw, ch = ctx.client()
        x = min(max(x + random.randint(-p.jitter_px, p.jitter_px), cx), cx + cw - 1)
        y = min(max(y + random.randint(-p.jitter_px, p.jitter_px), cy), cy + ch - 1)
    if ctx.dry_run:
        ok, why = ctx.point_on_target(x, y)
        return StepOutcome(ok=ok, message=why or msg.would_click(x, y), point=(x, y))
    ctx.click(x, y, p.button, p.double, p.settle_ms, p.hold_ms)
    ctx.sleep(p.after_ms / 1000.0)
    return StepOutcome(message=msg.clicked(x, y), point=(x, y))


def _find_text_once(p: ClickTextParams, ctx: StepContext, rect: Rect) -> tuple[TextHit | None, str]:
    img, res = ctx.read(rect, p.upscale or 1)
    hit = textfind.find_text(res.lines, p.text, p.match, p.nth, p.min_score)
    text = res.text()
    if hit is None and p.upscale == 0:
        h, w = img.shape[:2]
        if max(h, w) * 2 <= MAX_UPSCALED_SIDE:
            res2 = ctx.ocr_image(img, 2, (rect[0], rect[1]))
            hit = textfind.find_text(res2.lines, p.text, p.match, p.nth, p.min_score)
            text = res2.text() or text
    return hit, text


def _click_text(p: ClickTextParams, ctx: StepContext) -> StepOutcome:
    rect = ctx.region(p.region)
    deadline = time.monotonic() + p.timeout_ms / 1000.0
    while True:
        hit, seen = _find_text_once(p, ctx, rect)
        if hit is not None or ctx.dry_run or time.monotonic() >= deadline:
            break
        ctx.sleep(p.poll_ms / 1000.0)
    if hit is not None:
        scale = ctx.dpi() / 96.0
        x = rect[0] + int(math.floor(hit.x + 0.5)) + int(round(p.offset_x * scale))
        y = rect[1] + int(math.floor(hit.y + 0.5)) + int(round(p.offset_y * scale))
        found = msg.text_found(hit.text, x, y)
        if ctx.dry_run:
            ok, why = ctx.point_on_target(x, y)
            return StepOutcome(ok=ok, message=why or found, point=(x, y), rect=rect, ocr_text=seen)
        ctx.click(x, y, p.button, p.double, p.settle_ms, p.hold_ms)
        ctx.sleep(p.after_ms / 1000.0)
        return StepOutcome(message=found, point=(x, y), rect=rect, ocr_text=hit.text)
    if p.fallback_point is not None:
        x, y = ctx.resolve(p.fallback_point)
        note = tr(f"沒有找到「{p.text}」，改點備用位置 ({x}, {y})", f'"{p.text}" not found; clicking the fallback ({x}, {y})')
        if ctx.dry_run:
            ok, why = ctx.point_on_target(x, y)
            return StepOutcome(ok=ok, message=why or note, point=(x, y), rect=rect, ocr_text=seen)
        ctx.log(LogLevel.INFO, note)
        ctx.click(x, y, p.button, p.double, p.settle_ms, p.hold_ms)
        ctx.sleep(p.after_ms / 1000.0)
        return StepOutcome(message=note, point=(x, y), rect=rect, ocr_text=seen)
    if p.on_not_found is TimeoutAction.CONTINUE:
        note = msg.text_skipped(p.text)
        if not ctx.dry_run:
            ctx.log(LogLevel.INFO, note)
        return StepOutcome(ok=True, message=note, rect=rect, ocr_text=seen)
    if ctx.dry_run:
        return StepOutcome(ok=False, message=msg.text_not_found(p.text), rect=rect, ocr_text=seen)
    raise StepError(msg.text_not_found(p.text))


def _verify_typed(p: TypeCodeParams, ctx: StepContext, code: str) -> None:
    seps = set(SEPARATOR_CHARS) | set(p.separators or "")

    def flat(s: str) -> str:
        return "".join(c for c in nfkc(s).casefold() if not c.isspace() and c not in seps)

    want = flat(code)
    rect = ctx.region(p.verify_region)
    img, res = ctx.read(rect, 1)
    if want in flat(res.text()):
        return
    h, w = img.shape[:2]
    if max(h, w) * 2 <= MAX_UPSCALED_SIDE and want in flat(ctx.ocr_image(img, 2, (rect[0], rect[1])).text()):
        return
    raise StepError(msg.typed_mismatch())


def _select_box(p: TypeCodeParams, ctx: StepContext) -> None:
    """Select the text of the focused (later) box so the next segment replaces it. Presses no
    deleting key: Backspace in an EMPTY auto-advance box jumps back to the previous box on
    OTP-style pages, so the BACKSPACE clear method selects nothing here."""
    if p.clear_method is ClearMethod.CTRL_A:
        ctx.combo("Ctrl+A", 1, 0, p.hold_ms)
    elif p.clear_method is ClearMethod.END_SHIFT_HOME:
        ctx.combo("End", 1, 0, p.hold_ms)
        ctx.combo("Shift+Home", 1, 0, p.hold_ms)


def _type_code(p: TypeCodeParams, ctx: StepContext) -> StepOutcome:
    segments = code_segments(ctx.code, p, ctx.profile)
    shown = " / ".join(segments)
    if ctx.dry_run:
        return StepOutcome(message=msg.would_type(shown))
    if p.clear_first:
        ctx.clear(p.clear_method)
    for n, seg in enumerate(segments):
        if n > 0:
            if p.between is BetweenSegments.TAB:
                ctx.combo("Tab", 1, 0, p.hold_ms)
                ctx.sleep(p.key_delay_ms / 1000.0)
            if p.clear_first and p.clear_method is not ClearMethod.BACKSPACE:
                # gate G-08: a later box may still hold an old code (pages keep it after an error;
                # a retried attempt finds its own segments). A page's own focus() does not select
                # it, so typing into a full maxlength box would be rejected: select it first.
                ctx.sleep(max(p.key_delay_ms / 1000.0, SEGMENT_SELECT_SETTLE_S))
                _select_box(p, ctx)
        ctx.type(seg, p.mode, p.key_delay_ms, p.hold_ms)
    if p.verify_region is not None:
        _verify_typed(p, ctx, ctx.code)
    ctx.sleep(p.after_ms / 1000.0)
    return StepOutcome(message=msg.typed(shown))


def _type_text(p: TypeTextParams, ctx: StepContext) -> StepOutcome:
    text = render_template(p.text, ctx.code, ctx.index + 1)
    if ctx.dry_run:
        return StepOutcome(message=msg.would_type(text))
    if p.clear_first:
        ctx.clear(p.clear_method)
    if text:
        ctx.type(text, p.mode, p.key_delay_ms, p.hold_ms)
    ctx.sleep(p.after_ms / 1000.0)
    return StepOutcome(message=msg.typed(text))


def _key(p: KeyParams, ctx: StepContext) -> StepOutcome:
    try:
        parse_combo_names(p.keys)
    except ValueError as exc:
        raise StepError(tr(f"無法辨識的按鍵「{p.keys}」", f"Unrecognised keys '{p.keys}'")) from exc
    level, reason = combo_risk(p.keys)
    if level is IssueLevel.ERROR:  # SPEC 2.7: system shortcuts are refused even from a shared profile
        raise StepError(reason or msg.system_shortcut(p.keys))
    shown = p.keys + (f" ×{p.repeat}" if p.repeat > 1 else "")
    if ctx.dry_run:
        return StepOutcome(message=msg.would_press(shown))
    ctx.combo(p.keys, p.repeat, p.interval_ms, p.hold_ms)
    ctx.sleep(p.after_ms / 1000.0)
    return StepOutcome(message=msg.pressed(shown))


def _wait(p: WaitParams, ctx: StepContext) -> StepOutcome:
    if ctx.dry_run:
        return StepOutcome(message=msg.wait_skipped())
    j = p.jitter_pct / 100.0
    seconds = max(0.0, random.uniform(p.ms * (1 - j), p.ms * (1 + j)) / 1000.0)
    ctx.sleep(seconds)
    return StepOutcome(message=msg.waited(seconds))


def _wait_text(p: WaitTextParams, ctx: StepContext) -> StepOutcome:
    rect = ctx.region(p.region)
    deadline = time.monotonic() + p.timeout_ms / 1000.0
    while True:
        _img, res = ctx.read(rect, p.upscale or 1)
        present = textfind.text_present(res.lines, p.text, p.match)
        if present == p.appear:
            return StepOutcome(message=msg.text_present(p.text, present), rect=rect, ocr_text=res.text())
        if ctx.dry_run:
            return StepOutcome(ok=False, message=msg.text_present(p.text, present), rect=rect, ocr_text=res.text())
        if time.monotonic() >= deadline:
            break
        ctx.sleep(p.poll_ms / 1000.0)
    note = msg.wait_text_timeout(p.text, p.appear)
    if p.on_timeout is TimeoutAction.CONTINUE:
        ctx.log(LogLevel.WARNING, note)
        return StepOutcome(ok=True, message=note, rect=rect)
    raise StepError(note)


def baseline_texts(lines: Sequence[Any]) -> set[str]:
    """norm_match keys of a baseline read (empty lines dropped)."""
    return {k for k in (norm_match(ln.text) for ln in lines) if k}


def _ocr_check(p: OcrCheckParams, ctx: StepContext) -> StepOutcome:
    if p.region is None:
        raise StepError(msg.region_not_set())
    rect = ctx.region(p.region)
    baseline = ctx.baselines.get(ctx.step_index) if (p.only_new_text and not ctx.dry_run) else None
    ctx.sleep(p.initial_delay_ms / 1000.0)
    deadline = time.monotonic() + p.timeout_ms / 1000.0
    cls, keyword, text, new_seen = ResultClass.UNKNOWN, "", "", False
    img: np.ndarray | None = None
    while True:
        img, res = ctx.read(rect, p.upscale or 1)
        lines = res.lines
        if baseline is not None:  # only lines that were not in the region before the submit (SPEC 2.5)
            lines = [ln for ln in lines if norm_match(ln.text) and norm_match(ln.text) not in baseline]
        text = OcrResult(lines=list(lines)).text().strip()
        new_seen = new_seen or bool(lines)
        cls, keyword = ctx.classify(text)
        if cls is not ResultClass.UNKNOWN or ctx.dry_run or time.monotonic() >= deadline:
            break
        ctx.sleep(p.poll_ms / 1000.0)
    flat = " ".join(text.split())
    if cls is ResultClass.UNKNOWN and baseline is not None and not new_seen:
        message = msg.no_change_after_submit()
    else:
        message = flat[:200] if flat else msg.no_text_read()
    evidence = ""
    if not ctx.dry_run and p.save_evidence and ctx.settings.save_evidence and img is not None:
        evidence = ctx.save_evidence(img)
    if ctx.dry_run:
        message = msg.result_read(cls.label(), message)
    return StepOutcome(ok=True, message=message, result=cls, matched_keyword=keyword, ocr_text=text, rect=rect,
                       evidence_path=evidence)


_HANDLERS: dict[StepType, Callable[[Any, StepContext], StepOutcome]] = {
    StepType.FOCUS_WINDOW: _focus_window,
    StepType.CLICK_POINT: _click_point,
    StepType.CLICK_TEXT: _click_text,
    StepType.TYPE_CODE: _type_code,
    StepType.TYPE_TEXT: _type_text,
    StepType.KEY: _key,
    StepType.WAIT: _wait,
    StepType.WAIT_TEXT: _wait_text,
    StepType.OCR_CHECK: _ocr_check,
}


def execute_step(step: Step, ctx: object) -> StepOutcome:
    """Run ``step`` with the runner's step context (G4-internal type). Raises StepError,
    win32.input.InjectionAborted subclasses and control.StopRequested. Rules from SPEC 5.3:
    click_text not found -> fallback_point, else on_not_found (FAIL = StepError, CONTINUE = log
    and go on); click_text offsets x window_dpi / 96; ocr_check with only_new_text classifies
    only lines absent from the baseline read taken before profile.first_submit_index()."""
    assert isinstance(ctx, StepContext)
    handler = _HANDLERS.get(step.type)
    if handler is None:  # StepType.UNKNOWN (from a newer version): skipped
        return StepOutcome(ok=True, message=msg.unknown_step())
    before = ctx.guard_passed()
    out = handler(step.params, ctx)
    out.sent_input = out.sent_input or ctx.guard_passed() > before
    return out
