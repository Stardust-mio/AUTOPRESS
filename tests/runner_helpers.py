"""Test helpers for the runner (G4): a scripted fake desktop with one redeem window, a fake
Backend with a counting guard, profile builders, signal recorders and stand-ins for other
groups' functions while those modules are still stubs (OWNED BY G4).

The stand-ins (find_text, text_present, split_code, strip_separators, mask_rects, looks_blank)
follow the documented contracts of the G1 / G2 stubs and are installed ONLY while the real
module still carries ``__stub__`` (fixture ``runner_standins``); at integration the runner tests
exercise the real implementations.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pytest
from PyQt6.QtCore import Qt

from autopress.models import (
    BetweenSegments,
    ClickPointParams,
    ClickTextParams,
    CodeStatus,
    KeyParams,
    OcrCheckParams,
    OcrLine,
    OcrOptions,
    OcrResult,
    PlanItem,
    PlanMode,
    Profile,
    Rect,
    RunPlan,
    Settings,
    SplitMode,
    StepType,
    TargetMatch,
    TextHit,
    TextMatch,
    TimeoutAction,
    TitleMatch,
    TypeCodeParams,
    WindowInfo,
    make_step,
    point_in_rect,
    record_point,
    record_region,
)
from autopress.runner import messages as _runner_msg
from autopress.runner.control import RunControl
from autopress.runner.worker import Runner, SharedState
from autopress.textutil import norm_match, split_alternatives
from autopress.win32.input import ForegroundLost, PointNotOnTarget, UserActivity
from tests.fakes import is_stub

# ============================================================================ stand-ins (stub modules only)


def standin_find_all(lines: Sequence[OcrLine], query: str, match: TextMatch = TextMatch.EXACT,
                     min_score: float = 0.5) -> list[TextHit]:
    alts = [query] if match is TextMatch.REGEX else split_alternatives(query)
    hits: list[TextHit] = []
    for i, ln in enumerate(lines):
        if ln.score < min_score:
            continue
        t = norm_match(ln.text)
        for alt in alts:
            if match is TextMatch.EXACT:
                ok = t == norm_match(alt)
            elif match is TextMatch.CONTAINS:
                ok = bool(norm_match(alt)) and norm_match(alt) in t
            else:
                ok = re.search(alt, ln.text, re.IGNORECASE) is not None
            if ok:
                cx, cy = ln.center()
                hits.append(TextHit(x=cx, y=cy, line_index=i, text=ln.text, score=ln.score,
                                    exact=t == norm_match(alt)))
                break
    hits.sort(key=lambda h: (round(h.y / 10), h.x))
    return hits


def standin_find_text(lines: Sequence[OcrLine], query: str, match: TextMatch = TextMatch.EXACT, nth: int = 0,
                      min_score: float = 0.5) -> TextHit | None:
    hits = standin_find_all(lines, query, match, min_score)
    if not hits:
        return None
    if nth >= 1:
        return hits[nth - 1] if nth <= len(hits) else None
    return max(hits, key=lambda h: (h.exact, h.score))


def standin_text_present(lines: Sequence[OcrLine], query: str, match: TextMatch = TextMatch.CONTAINS,
                         min_score: float = 0.5) -> bool:
    return bool(standin_find_all(lines, query, match, min_score))


def standin_strip_separators(code: str, separators: str = "-_") -> str:
    return "".join(c for c in code if c not in separators and not c.isspace())


def standin_split_code(code: str, mode: SplitMode, separators: str = "-_", group_sizes: Sequence[int] = ()) -> list[str]:
    if mode is SplitMode.NONE:
        return [code]
    if mode is SplitMode.SEPARATOR:
        return [p for p in re.split("[" + re.escape(separators) + "]", code) if p]
    if not group_sizes:
        raise ValueError("FIXED split needs group sizes")
    s = standin_strip_separators(code, separators)
    out, pos = [], 0
    for g in group_sizes:
        if pos >= len(s):
            break
        out.append(s[pos:pos + g])
        pos += g
    if pos < len(s):
        out.append(s[pos:])
    return out


def standin_mask_rects(image: np.ndarray, origin: tuple[int, int], rects: Sequence[Rect]) -> np.ndarray:
    h, w = image.shape[:2]
    ox, oy = origin
    hits = []
    for x, y, rw, rh in rects:
        x0, y0 = max(0, x - ox), max(0, y - oy)
        x1, y1 = min(w, x - ox + rw), min(h, y - oy + rh)
        if x1 > x0 and y1 > y0:
            hits.append((x0, y0, x1, y1))
    if not hits:
        return image
    out = image.copy()
    border = np.concatenate([image[0], image[-1], image[:, 0], image[:, -1]], axis=0)
    fill = np.median(border, axis=0).astype(image.dtype)
    for x0, y0, x1, y1 in hits:
        out[y0:y1, x0:x1] = fill
    return out


def standin_looks_blank(image: np.ndarray, std_threshold: float = 2.0) -> bool:
    if image.size == 0:
        return True
    if image.ndim == 3:
        px = image[..., :3].reshape(-1, min(3, image.shape[2])).astype(np.float32)
        return float(px.std(axis=0).max()) < std_threshold
    return float(image.astype(np.float32).std()) < std_threshold


@pytest.fixture
def runner_standins(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install the stand-ins into the G1 / G2 modules that are still stubs (nothing otherwise)."""
    import autopress.capture
    import autopress.codes.normalize
    import autopress.ocr.imageio
    import autopress.ocr.textfind

    if is_stub("autopress.ocr.textfind"):
        monkeypatch.setattr(autopress.ocr.textfind, "find_text", standin_find_text)
        monkeypatch.setattr(autopress.ocr.textfind, "find_all", standin_find_all)
        monkeypatch.setattr(autopress.ocr.textfind, "text_present", standin_text_present)
    if is_stub("autopress.codes.normalize"):
        monkeypatch.setattr(autopress.codes.normalize, "split_code", standin_split_code)
        monkeypatch.setattr(autopress.codes.normalize, "strip_separators", standin_strip_separators)
    if is_stub("autopress.ocr.imageio"):
        monkeypatch.setattr(autopress.ocr.imageio, "mask_rects", standin_mask_rects)
    if is_stub("autopress.capture"):
        monkeypatch.setattr(autopress.capture, "looks_blank", standin_looks_blank)


@pytest.fixture
def fast_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    """No 1 s minimum interval in unit tests (the clamp itself is tested separately)."""
    import autopress.runner.waits as waits

    monkeypatch.setattr(waits, "MIN_INTERVAL_S", 0.0)


# ============================================================================ fake desktop

ZH_RESULTS = {"success": "兌換成功", "used": "此序號已被使用", "expired": "兌換碼已過期",
              "rate_limited": "操作過於頻繁，請稍後再試", "invalid": "兌換碼無效"}

CLIENT: Rect = (100, 50, 1280, 720)


@dataclass
class Item:
    text: str
    rect: Rect
    small: bool = False  # only read with OcrOptions.upscale >= 2


@dataclass
class FakeWorld:
    """One target window with a redeem form; every action and capture is recorded."""

    hwnd: int = 1001
    pid: int = 4242
    title: str = "測試遊戲 - 兌換"
    exe_path: str = "C:/Games/game.exe"
    class_name: str = "GameWnd"
    client: Rect = CLIENT
    dpi: int = 96
    alive: bool = True
    minimized: bool = False
    foreground: int = 1001
    focus_ok: bool = True
    group_sizes: list[int] = field(default_factory=list)  # [] = one box
    auto_advance: bool = True  # multi-box pages jump to the next box when one is full
    advance_selects: bool = True  # False = like a browser page's focus(): the next box's text is NOT
    # selected, so a full maxlength box rejects new characters (gate G-08)
    valid: set[str] = field(default_factory=set)
    used: set[str] = field(default_factory=set)
    rate_limit: int = 0  # submits per 10 s, 0 = off
    latency_s: float = 0.0
    persist: bool = True
    popup_on: str = "never"  # never | success | always
    blank: bool = False
    blank_rects: list[Rect] = field(default_factory=list)  # grabs of exactly these rects are black
    statics: list[Item] = field(default_factory=list)  # extra static texts
    covers: list[tuple[Rect, int, str, bool]] = field(default_factory=list)  # (rect, hwnd, title, own)
    extra_matches: int = 0  # more windows matching the target (target_multiple)
    permission: str = "ok"
    can_elevate: bool = True
    own_pid: int = 777
    failsafe: bool = False
    user_active: bool = False
    # state
    boxes: list[str] = field(default_factory=list)
    focused: int | None = None
    replace_next: bool = False
    result_text: str = ""
    pending: tuple[float, str, str] | None = None
    popup_text: str = ""
    submitted: list[str] = field(default_factory=list)
    actions: list[tuple[Any, ...]] = field(default_factory=list)
    grabs: list[Rect] = field(default_factory=list)
    ocr_opts: list[OcrOptions] = field(default_factory=list)
    evidence: list[tuple[str, int]] = field(default_factory=list)
    checks: int = 0
    trips: list[list[Any]] = field(default_factory=list)  # [what, skip, exc]
    hooks: dict[str, Callable[[FakeWorld], None]] = field(default_factory=dict)
    ocr_error: BaseException | None = None
    grab_error: BaseException | None = None
    lock: threading.RLock = field(default_factory=threading.RLock)

    def __post_init__(self) -> None:
        self.boxes = [""] * max(1, len(self.group_sizes))

    # ---------------------------------------------------------------- layout (screen coordinates)
    def at(self, dx: int, dy: int, w: int, h: int) -> Rect:
        return self.client[0] + dx, self.client[1] + dy, w, h

    def box_rects(self) -> list[Rect]:
        n = len(self.boxes)
        width = 600 // n
        return [self.at(100 + i * width, 200, width - 10, 50) for i in range(n)]

    @property
    def prompt_rect(self) -> Rect:
        return self.at(100, 100, 300, 40)

    @property
    def button_rect(self) -> Rect:
        return self.at(100, 280, 160, 50)

    @property
    def cancel_rect(self) -> Rect:
        return self.at(300, 280, 160, 50)

    @property
    def result_rect(self) -> Rect:
        return self.at(100, 370, 800, 60)

    @property
    def popup_msg_rect(self) -> Rect:  # the dialog opens over the result area (inside the ocr_check region)
        return self.at(300, 375, 300, 40)

    @property
    def popup_ok_rect(self) -> Rect:
        return self.at(400, 425, 100, 40)

    def center(self, r: Rect) -> tuple[int, int]:
        return r[0] + r[2] // 2, r[1] + r[3] // 2

    # ---------------------------------------------------------------- window facts
    def info(self) -> WindowInfo:
        return WindowInfo(hwnd=self.hwnd, title=self.title, class_name=self.class_name, pid=self.pid,
                          exe_path=self.exe_path, rect=self.client, client=self.client, minimized=self.minimized)

    # ---------------------------------------------------------------- page behaviour
    def _hook(self, name: str) -> None:
        fn = self.hooks.get(name)
        if fn is not None:
            fn(self)

    def classify(self, code: str) -> str:
        now = time.monotonic()
        self._submit_times = [t for t in getattr(self, "_submit_times", []) if now - t < 10] + [now]
        if self.rate_limit and len(self._submit_times) > self.rate_limit:
            return "rate_limited"
        key = code.replace("-", "").replace("_", "")
        valid = {c.replace("-", "") for c in self.valid}
        used = {c.replace("-", "") for c in self.used}
        if key in valid or key in used:
            if key in used:
                return "used"
            self.used.add(key)
            return "success"
        if key.upper().startswith("EXP"):
            return "expired"
        return "invalid"

    def submit(self, src: str) -> None:
        code = "-".join(self.boxes) if len(self.boxes) > 1 else self.boxes[0]
        self.submitted.append(code)
        self.actions.append(("submit", src, code))
        kind = self.classify(code)
        if not self.persist:
            self.result_text = ""
        self.pending = (time.monotonic() + self.latency_s, ZH_RESULTS[kind], kind)
        self._hook("submit")

    def _apply_pending(self) -> None:
        if self.pending and time.monotonic() >= self.pending[0]:
            _due, text, kind = self.pending
            self.pending = None
            if self.popup_on == "always" or (self.popup_on == "success" and kind == "success"):
                self.popup_text = text
            else:
                self.result_text = text

    def do_click(self, x: int, y: int) -> None:
        self.actions.append(("click", x, y))
        self._apply_pending()
        if self.popup_text:
            if point_in_rect(self.popup_ok_rect, x, y):
                self.popup_text = ""
                self.actions.append(("popup_closed",))
            return
        for i, r in enumerate(self.box_rects()):
            if point_in_rect(r, x, y):
                self.focused, self.replace_next = i, False
                return
        if point_in_rect(self.button_rect, x, y):
            self.submit("click")
        elif point_in_rect(self.cancel_rect, x, y):
            self.boxes = [""] * len(self.boxes)

    def do_char(self, ch: str) -> None:
        self.actions.append(("char", ch))
        if self.focused is None:
            return
        i = self.focused
        if self.replace_next:
            self.boxes[i], self.replace_next = "", False
        size = self.group_sizes[i] if self.group_sizes else 0
        if size and len(self.boxes[i]) >= size:
            return
        self.boxes[i] += ch
        if self.auto_advance and size and len(self.boxes[i]) >= size and i + 1 < len(self.boxes):
            self.focused, self.replace_next = i + 1, self.advance_selects

    def do_combo(self, combo: str) -> None:
        self.actions.append(("combo", combo))
        if combo == "Enter":
            self.submit("enter")
        elif combo == "Tab" and self.focused is not None:
            self.focused = min(self.focused + 1, len(self.boxes) - 1)
            self.replace_next = True
        elif combo == "Esc":
            self.popup_text = ""
        elif combo in ("Ctrl+A", "Shift+Home") and self.focused is not None:
            self.replace_next = bool(self.boxes[self.focused])  # select all: the next character replaces it

    def do_clear(self) -> None:
        self.actions.append(("clear",))
        if self.focused is not None:
            self.boxes[self.focused] = ""

    def typed_text(self) -> str:
        return "".join(a[1] for a in self.actions if a[0] == "char")

    # ---------------------------------------------------------------- what is on the screen
    def items(self) -> list[Item]:
        self._apply_pending()
        out = [Item("請輸入兌換碼", self.prompt_rect), Item("兌換", self.button_rect), Item("取消", self.cancel_rect)]
        out += [Item(text, r) for text, r in zip(self.boxes, self.box_rects(), strict=True) if text]
        if self.result_text:
            out.append(Item(self.result_text, self.result_rect))
        if self.popup_text:
            out += [Item(self.popup_text, self.popup_msg_rect), Item("確定", self.popup_ok_rect)]
        return out + list(self.statics)

    def grab(self, rect: Rect) -> np.ndarray:
        with self.lock:
            self.grabs.append(tuple(rect))
            if self.grab_error is not None:
                raise self.grab_error
            if not self.alive:
                raise OSError("window closed")
        w, h = max(1, rect[2]), max(1, rect[3])
        if self.blank or tuple(rect) in [tuple(r) for r in self.blank_rects]:
            return np.zeros((h, w, 4), np.uint8)
        rng = np.random.default_rng(len(self.grabs))
        return rng.integers(0, 256, (h, w, 4), dtype=np.uint8)

    def ocr(self, image: np.ndarray, opts: OcrOptions) -> OcrResult:
        with self.lock:
            self.ocr_opts.append(opts)
            if self.ocr_error is not None:
                raise self.ocr_error
            h, w = image.shape[:2]
            rect = next((r for r in reversed(self.grabs) if (r[3], r[2]) == (h, w)), self.client)
        lines = []
        for it in self.items():
            if it.small and opts.upscale < 2:
                continue
            cx, cy = self.center(it.rect)
            if not point_in_rect(rect, cx, cy):
                continue
            x0, y0 = max(0, it.rect[0] - rect[0]), max(0, it.rect[1] - rect[1])
            x1, y1 = min(w, it.rect[0] + it.rect[2] - rect[0]), min(h, it.rect[1] + it.rect[3] - rect[1])
            patch = image[y0:y1, x0:x1, :3]
            if patch.size == 0 or float(patch.reshape(-1, 3).std(axis=0).max()) == 0.0:  # masked / blank
                continue
            qx, qy = it.rect[0] - rect[0], it.rect[1] - rect[1]
            quad = [(qx, qy), (qx + it.rect[2], qy), (qx + it.rect[2], qy + it.rect[3]), (qx, qy + it.rect[3])]
            lines.append(OcrLine(text=it.text, quad=[(float(a), float(b)) for a, b in quad], score=0.99))
        return OcrResult(lines=lines, width=w, height=h)


# ============================================================================ fake guard / backend


class FakeGuard:
    """Same contract as win32.input.InjectGuard.check plus the ``passed`` counter."""

    def __init__(self, world: FakeWorld, hwnd: int, pid: int, allow_same_process: bool,
                 cancel: Callable[[], None] | None, check_user_input: bool = False) -> None:
        self.world, self.hwnd, self.pid = world, hwnd, pid
        self.allow_same_process = allow_same_process
        self.cancel = cancel
        self.check_user_input = check_user_input
        self.passed = 0

    def check(self, what: str, point: tuple[int, int] | None = None) -> None:
        if self.cancel is not None:
            self.cancel()
        w = self.world
        with w.lock:
            w.checks += 1
            for trip in w.trips:
                if trip[0] in (None, what):
                    if trip[1] > 0:
                        trip[1] -= 1
                        continue
                    w.trips.remove(trip)
                    raise trip[2]
        if self.check_user_input and w.user_active:  # like InjectGuard: input since our last injection
            raise UserActivity(_runner_msg.user_input())
        if w.foreground != self.hwnd:
            raise ForegroundLost("目標視窗失去焦點，已暫停。")
        if point is not None:
            for rect, _hwnd, title, own in w.covers:
                if point_in_rect(rect, *point):
                    raise PointNotOnTarget("迷你控制列擋住了點擊位置" if own else f"點擊位置被「{title}」遮住，已暫停。")
        self.passed += 1


class FakeBackend:
    """runner.backend.Backend over a FakeWorld (no real input, screen or OCR)."""

    def __init__(self, world: FakeWorld) -> None:
        self.world = world
        self.keep_awake_calls: list[bool] = []
        self.released = 0
        self.baseline_resets = 0
        self.closed = False
        self.focus_calls = 0

    # windows
    def find_target(self, match: TargetMatch) -> WindowInfo | None:
        w = self.world
        if w.alive and match.matches(w.exe_path, w.title, w.class_name):
            return w.info()
        return None

    def find_targets(self, match: TargetMatch) -> list[WindowInfo]:
        info = self.find_target(match)
        if info is None:
            return []
        return [info] + [WindowInfo(hwnd=5000 + i, title=f"{self.world.title} {i}", pid=9000 + i,
                                    exe_path=self.world.exe_path, class_name=self.world.class_name)
                         for i in range(self.world.extra_matches)]

    def window_info(self, hwnd: int) -> WindowInfo | None:
        w = self.world
        if hwnd == w.hwnd:
            return w.info() if w.alive else None
        for _rect, other, title, _own in w.covers:
            if other == hwnd:
                return WindowInfo(hwnd=other, title=title, pid=other + 1)
        return None

    def is_alive(self, info: WindowInfo) -> bool:
        w = self.world
        return w.alive and info.hwnd == w.hwnd and info.pid == w.pid

    def client_rect(self, hwnd: int) -> Rect:
        if hwnd != self.world.hwnd or not self.world.alive:
            raise OSError("invalid window handle")
        return self.world.client

    def is_minimized(self, hwnd: int) -> bool:
        return self.world.minimized

    def foreground(self) -> int:
        return self.world.foreground

    def window_pid(self, hwnd: int) -> int:
        return self.world.pid if hwnd == self.world.hwnd else hwnd + 1

    def bring_to_foreground(self, hwnd: int, sleep: Callable[[float], None], timeout_s: float = 3.0) -> bool:
        self.focus_calls += 1
        w = self.world
        if not (w.focus_ok and w.alive and hwnd == w.hwnd):
            return False
        w.foreground, w.minimized = hwnd, False
        return True

    def window_dpi(self, hwnd: int) -> int:
        return self.world.dpi

    def window_at(self, x: int, y: int, skip_own: bool = False) -> int:
        w = self.world
        for rect, hwnd, _title, own in w.covers:
            if point_in_rect(rect, x, y) and not (own and skip_own):
                return hwnd
        return w.hwnd if point_in_rect(w.client, x, y) else 0

    def is_own_window(self, hwnd: int) -> bool:
        return any(own and h == hwnd for _r, h, _t, own in self.world.covers)

    def own_pid(self) -> int:
        return self.world.own_pid

    def input_permission(self, hwnd: int) -> str:
        return self.world.permission

    def can_elevate(self) -> bool:
        return self.world.can_elevate

    # input
    def make_guard(self, info: WindowInfo, settings: Settings, allow_same_process: bool,
                   cancel: Callable[[], None]) -> FakeGuard:
        return FakeGuard(self.world, info.hwnd, info.pid, allow_same_process, cancel,
                         check_user_input=settings.pause_on_user_input)

    def click(self, x: int, y: int, guard: Any, button: Any, double: bool, settle_ms: int, hold_ms: int,
              sleep: Callable[[float], None]) -> None:
        guard.check("click", (x, y))
        self.world.do_click(x, y)
        self.world._hook("click")

    def type_text(self, text: str, guard: Any, mode: Any, key_delay_ms: int, hold_ms: int, restore_clipboard_ms: int,
                  sleep: Callable[[float], None]) -> None:
        self.world.actions.append(("type", text, str(mode)))
        for ch in text:
            guard.check("type")
            self.world.do_char(ch)
            self.world._hook("char")

    def press_combo(self, combo: str, guard: Any, repeat: int, interval_ms: int, hold_ms: int,
                    sleep: Callable[[float], None]) -> None:
        for _ in range(max(1, repeat)):
            guard.check("key")
            self.world.do_combo(combo)

    def clear_field(self, guard: Any, method: Any, sleep: Callable[[float], None]) -> None:
        guard.check("clear")
        self.world.do_clear()

    def release_all(self) -> None:
        self.released += 1

    def reset_input_baseline(self) -> None:
        self.baseline_resets += 1
        self.world.user_active = False

    def failsafe_hit(self, margin_px: int) -> bool:
        return self.world.failsafe

    def user_active(self) -> bool:
        return self.world.user_active

    # capture / OCR
    def grab(self, rect: Rect) -> np.ndarray:
        return self.world.grab(rect)

    def ocr(self, image: np.ndarray, opts: OcrOptions, cancel: Callable[[], bool]) -> OcrResult:
        return self.world.ocr(image, opts)

    def ocr_ready(self, timeout_s: float, cancel: Callable[[], bool]) -> bool:
        return True

    def ocr_status(self) -> tuple[str, str]:
        return "ready", ""

    def save_evidence(self, image: np.ndarray, run_id: str, index: int) -> str:
        self.world.evidence.append((run_id, index))
        return f"evidence/2026-11-17/{run_id}_{index}.png"

    def keep_awake(self, active: bool) -> bool:
        self.keep_awake_calls.append(active)
        return True

    def close(self) -> None:
        self.closed = True


# ============================================================================ profiles / plans


def make_profile(world: FakeWorld, *, submit: str = "click_point", result_check: bool = True,
                 only_new_text: bool = True, split: SplitMode = SplitMode.NONE,
                 between: BetweenSegments = BetweenSegments.TAB, group_sizes: Sequence[int] = (),
                 dismiss_popup: bool = False, game: str = "測試遊戲") -> Profile:
    """click input -> type_code -> submit (click_point / click_text / enter) -> ocr_check
    [-> click_text 確定 (on_not_found continue)], every delay tiny, interval 0 (fast_runner)."""
    client = world.client
    p = Profile(name="測試設定檔", game=game,
                target=TargetMatch(exe="game.exe", title="兌換", title_mode=TitleMatch.CONTAINS))
    click_in = make_step(StepType.CLICK_POINT)
    assert isinstance(click_in.params, ClickPointParams)
    click_in.params.point = record_point(client, *world.center(world.box_rects()[0]))
    click_in.params.after_ms = 0
    click_in.label = "點一下序號輸入框"
    tc = make_step(StepType.TYPE_CODE)
    assert isinstance(tc.params, TypeCodeParams)
    tc.params.key_delay_ms, tc.params.after_ms = 0, 0
    tc.params.split, tc.params.between, tc.params.group_sizes = split, between, list(group_sizes)
    steps = [click_in, tc]
    if submit == "click_point":
        s = make_step(StepType.CLICK_POINT)
        assert isinstance(s.params, ClickPointParams)
        s.params.point = record_point(client, *world.center(world.button_rect))
        s.params.after_ms = 0
    elif submit == "click_text":
        s = make_step(StepType.CLICK_TEXT)
        assert isinstance(s.params, ClickTextParams)
        s.params.text = "兌換|Redeem"
        s.params.region = record_region(client, client[0] + 80, client[1] + 260, 420, 100)
        s.params.timeout_ms, s.params.poll_ms, s.params.after_ms = 200, 50, 0
    else:
        s = make_step(StepType.KEY)
        assert isinstance(s.params, KeyParams)
        s.params.keys, s.params.after_ms = "Enter", 0
    steps.append(s)
    if result_check:
        oc = make_step(StepType.OCR_CHECK)
        assert isinstance(oc.params, OcrCheckParams)
        oc.params.region = record_region(client, client[0] + 80, client[1] + 350, 900, 160)
        oc.params.initial_delay_ms, oc.params.poll_ms, oc.params.timeout_ms = 0, 50, 300
        oc.params.only_new_text = only_new_text
        steps.append(oc)
    if dismiss_popup:
        d = make_step(StepType.CLICK_TEXT)
        assert isinstance(d.params, ClickTextParams)
        d.params.text = "確定|OK"
        d.params.on_not_found = TimeoutAction.CONTINUE
        d.params.timeout_ms, d.params.poll_ms, d.params.after_ms = 0, 50, 0
        steps.append(d)
    p.steps = steps
    pol = p.policy
    pol.interval_min_s = pol.interval_max_s = 0.0
    pol.cooldown_s = 0  # tests set what they need
    return p


def fast_settings() -> Settings:
    s = Settings()
    s.delays.after_focus_ms = 0
    return s


def make_plan(profile: Profile, codes: Sequence[str], *, settings: Settings | None = None,
              mode: PlanMode = PlanMode.NORMAL, target_hwnd: int = 0) -> RunPlan:
    return RunPlan(profile=profile, items=[PlanItem(code_id=f"id{i}", code=c) for i, c in enumerate(codes)],
                   mode=mode, settings=settings or fast_settings(), target_hwnd=target_hwnd)


# ============================================================================ running the worker directly


class SyncRun:
    """Run a Runner in the calling thread (or a Python thread) with direct signal delivery.
    ``on_pause``: "resume" (default), "stop", None (stay paused) or a callable(SyncRun, reason)
    called when PAUSED is emitted (before the runner blocks)."""

    NAMES = ("state_changed", "progress", "code_started", "step_started", "code_done", "log", "cooldown", "waiting",
             "attention", "run_finished", "test_finished")

    def __init__(self, plan: RunPlan, world: FakeWorld, *, on_pause: Any = "resume",
                 shared: SharedState | None = None) -> None:
        self.world = world
        self.control = RunControl()
        self.shared = shared or SharedState()
        self.backends: list[FakeBackend] = []

        def factory() -> FakeBackend:
            b = FakeBackend(world)
            self.backends.append(b)
            return b

        self.runner = Runner(plan, self.control, factory, self.shared)
        self.events: list[tuple[str, tuple[Any, ...]]] = []
        self.on_pause = on_pause
        self.lock = threading.Lock()
        for name in self.NAMES:
            getattr(self.runner, name).connect(lambda *a, n=name: self._record(n, a),
                                               type=Qt.ConnectionType.DirectConnection)

    def _record(self, name: str, args: tuple[Any, ...]) -> None:
        with self.lock:
            self.events.append((name, args))
        if name == "state_changed" and args[0] == "paused":
            if self.on_pause == "resume":
                self.control.request_resume()
            elif self.on_pause == "stop":
                self.control.request_stop()
            elif callable(self.on_pause):
                self.on_pause(self, args[1])

    def run(self) -> SyncRun:
        self.runner.run()
        return self

    def start_thread(self) -> threading.Thread:
        t = threading.Thread(target=self.runner.run, daemon=True)
        t.start()
        return t

    def of(self, name: str) -> list[tuple[Any, ...]]:
        with self.lock:
            return [a for n, a in self.events if n == name]

    @property
    def summary(self) -> Any:
        return self.of("run_finished")[-1][0]

    @property
    def test_result(self) -> Any:
        return self.of("test_finished")[-1][0]

    def states(self) -> list[tuple[str, str]]:
        return [(a[0], a[1]) for a in self.of("state_changed")]

    def pauses(self) -> list[str]:
        return [r for s, r in self.states() if s == "paused"]

    def done(self) -> list[Any]:
        """CodeDone payloads in order."""
        return [a[1] for a in self.of("code_done")]

    def final_status(self) -> dict[str, CodeStatus]:
        out: dict[str, CodeStatus] = {}
        for cid, payload in self.of("code_done"):
            out[cid] = payload.queue_status
        return out

    def attentions(self) -> list[Any]:
        return [a[0] for a in self.of("attention")]

    def logs(self) -> list[str]:
        return [a[0].message for a in self.of("log")]

    @property
    def backend(self) -> FakeBackend:
        return self.backends[-1]


def wait_until(pred: Callable[[], bool], timeout: float = 5.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.005)
    return pred()
