# OWNED BY G4
"""Everything the runner needs from the outside world, behind one interface so the engine can
be unit-tested with a fake backend (no real input, no screen, no OCR engine).

RealBackend delegates to win32.windows / win32.input / win32.elevation / win32.power (G3),
capture and the OcrService (G2), and ocr.imageio.save_png for evidence crops.

Division of work (G4-internal, see runner.steps.StepContext): ``grab`` returns the RAW capture;
the runner blanks the RunSession's masked rects (ocr.imageio.mask_rects) and runs the blank check
(capture.looks_blank) itself, so both rules hold for every backend and are unit-testable.
Guards returned by ``make_guard`` count the checks that passed in ``passed`` (an injection
follows every passed check), which is how the runner knows whether a step sent input - the
"possibly submitted" rule of SPEC 2.5.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from datetime import date
from typing import Any, Protocol

import numpy as np

from .. import capture as capture_mod
from .. import paths
from ..models import ClearMethod, MouseButton, OcrOptions, OcrResult, Rect, Settings, TargetMatch, TypingMode, WindowInfo
from ..ocr import imageio
from ..ocr.engine import OcrUnavailable
from ..win32 import elevation, power
from ..win32 import input as winput
from ..win32 import windows as winwin
from ..win32.input import InjectGuard, Sleep

log = logging.getLogger(__name__)


class Backend(Protocol):
    def find_target(self, match: TargetMatch) -> WindowInfo | None: ...
    def find_targets(self, match: TargetMatch) -> list[WindowInfo]: ...
    def window_info(self, hwnd: int) -> WindowInfo | None: ...
    def is_alive(self, info: WindowInfo) -> bool: ...
    def client_rect(self, hwnd: int) -> Rect: ...
    def is_minimized(self, hwnd: int) -> bool: ...
    def foreground(self) -> int: ...
    def window_pid(self, hwnd: int) -> int: ...
    def bring_to_foreground(self, hwnd: int, sleep: Sleep, timeout_s: float = 3.0) -> bool: ...
    def window_dpi(self, hwnd: int) -> int: ...
    def window_at(self, x: int, y: int, skip_own: bool = False) -> int: ...
    def is_own_window(self, hwnd: int) -> bool: ...
    def own_pid(self) -> int: ...
    def input_permission(self, hwnd: int) -> str: ...
    def can_elevate(self) -> bool: ...
    def make_guard(self, info: WindowInfo, settings: Settings, allow_same_process: bool,
                   cancel: Callable[[], None]) -> InjectGuard: ...
    def click(self, x: int, y: int, guard: InjectGuard, button: MouseButton, double: bool,
              settle_ms: int, hold_ms: int, sleep: Sleep) -> None: ...
    def type_text(self, text: str, guard: InjectGuard, mode: TypingMode, key_delay_ms: int,
                  hold_ms: int, restore_clipboard_ms: int, sleep: Sleep) -> None: ...
    def press_combo(self, combo: str, guard: InjectGuard, repeat: int, interval_ms: int,
                    hold_ms: int, sleep: Sleep) -> None: ...
    def clear_field(self, guard: InjectGuard, method: ClearMethod, sleep: Sleep) -> None: ...
    def release_all(self) -> None: ...
    def reset_input_baseline(self) -> None: ...
    def failsafe_hit(self, margin_px: int) -> bool: ...
    def user_active(self) -> bool: ...
    def grab(self, rect: Rect) -> np.ndarray: ...
    def ocr(self, image: np.ndarray, opts: OcrOptions, cancel: Callable[[], bool]) -> OcrResult: ...
    def ocr_ready(self, timeout_s: float, cancel: Callable[[], bool]) -> bool: ...
    def ocr_status(self) -> tuple[str, str]: ...
    def save_evidence(self, image: np.ndarray, run_id: str, index: int) -> str: ...
    def keep_awake(self, active: bool) -> bool: ...
    def close(self) -> None: ...


class _CountingGuard(InjectGuard):
    """InjectGuard that counts the checks that passed (an injection follows each one)."""

    passed: int = 0

    def check(self, what: str, point: Any = None) -> None:
        super().check(what, point)
        self.passed += 1


class RealBackend:
    """The production Backend. Create it IN the runner thread (it owns a capture.Grabber);
    preflight and preview create a short-lived one on the GUI thread (``ocr_service`` None)."""

    def __init__(self, ocr_service: object) -> None:
        self._ocr = ocr_service
        self._grabber: capture_mod.Grabber | None = None

    # ------------------------------------------------------------------ windows
    def find_target(self, match: TargetMatch) -> WindowInfo | None:
        return winwin.find_window(match)

    def find_targets(self, match: TargetMatch) -> list[WindowInfo]:
        return winwin.find_windows(match)

    def window_info(self, hwnd: int) -> WindowInfo | None:
        return winwin.window_info(hwnd) if hwnd else None

    def is_alive(self, info: WindowInfo) -> bool:
        return winwin.is_alive(info)

    def client_rect(self, hwnd: int) -> Rect:
        return winwin.client_rect(hwnd)

    def is_minimized(self, hwnd: int) -> bool:
        return winwin.is_minimized(hwnd)

    def foreground(self) -> int:
        return winwin.foreground_window()

    def window_pid(self, hwnd: int) -> int:
        return winwin.window_pid(hwnd) if hwnd else 0

    def bring_to_foreground(self, hwnd: int, sleep: Sleep, timeout_s: float = 3.0) -> bool:
        attempts = max(1, min(10, int(round(timeout_s / 1.0))))
        ok, how = winput.bring_to_foreground(hwnd, attempts=attempts, verify_s=0.25, sleep=sleep)
        log.debug("bring_to_foreground(%s): %s %s", hwnd, ok, how)
        return bool(ok)

    def window_dpi(self, hwnd: int) -> int:
        return winwin.window_dpi(hwnd)

    def window_at(self, x: int, y: int, skip_own: bool = False) -> int:
        return winwin.window_at(x, y, skip_own=skip_own) or 0

    def is_own_window(self, hwnd: int) -> bool:
        return winwin.is_own_window(hwnd)

    def own_pid(self) -> int:
        return os.getpid()

    def input_permission(self, hwnd: int) -> str:
        return str(elevation.input_permission(hwnd).value)

    def can_elevate(self) -> bool:
        return elevation.can_elevate()

    # ------------------------------------------------------------------ input
    def make_guard(self, info: WindowInfo, settings: Settings, allow_same_process: bool,
                   cancel: Callable[[], None]) -> InjectGuard:
        guard = _CountingGuard(info.hwnd, pid=info.pid, allow_same_process=allow_same_process,
                               check_user_input=settings.pause_on_user_input, slack_ms=200,
                               failsafe=settings.failsafe_enabled, failsafe_margin_px=settings.failsafe_margin_px,
                               cancel=cancel)
        guard.passed = 0
        return guard

    def click(self, x: int, y: int, guard: InjectGuard, button: MouseButton, double: bool,
              settle_ms: int, hold_ms: int, sleep: Sleep) -> None:
        winput.click(x, y, guard, button=button, double=double, settle_ms=settle_ms, hold_ms=hold_ms, sleep=sleep)

    def type_text(self, text: str, guard: InjectGuard, mode: TypingMode, key_delay_ms: int,
                  hold_ms: int, restore_clipboard_ms: int, sleep: Sleep) -> None:
        winput.type_text(text, guard, mode, key_delay_ms=key_delay_ms, hold_ms=hold_ms, close_ime=True,
                         restore_clipboard_ms=max(50, restore_clipboard_ms), sleep=sleep)

    def press_combo(self, combo: str, guard: InjectGuard, repeat: int, interval_ms: int,
                    hold_ms: int, sleep: Sleep) -> None:
        winput.press_combo(combo, guard, repeat=repeat, interval_ms=interval_ms, hold_ms=hold_ms, sleep=sleep)

    def clear_field(self, guard: InjectGuard, method: ClearMethod, sleep: Sleep) -> None:
        winput.clear_field(guard, method, sleep=sleep)

    def release_all(self) -> None:
        winput.release_all_modifiers()

    def reset_input_baseline(self) -> None:
        winput.reset_user_input_baseline()

    def failsafe_hit(self, margin_px: int) -> bool:
        return winput.failsafe_triggered(margin_px)

    def user_active(self) -> bool:
        return winput.user_active_since_last_injection(200)

    # ------------------------------------------------------------------ capture / OCR
    def grab(self, rect: Rect) -> np.ndarray:
        if self._grabber is None:
            self._grabber = capture_mod.Grabber()
        return self._grabber.grab(rect)

    def ocr(self, image: np.ndarray, opts: OcrOptions, cancel: Callable[[], bool]) -> OcrResult:
        if self._ocr is None:
            raise OcrUnavailable("OCR service not available")
        return self._ocr.recognize(image, opts, timeout_s=30.0, cancel=cancel, priority=0)  # type: ignore[attr-defined]

    def ocr_ready(self, timeout_s: float, cancel: Callable[[], bool]) -> bool:
        if self._ocr is None:
            return False
        return bool(self._ocr.wait_ready(timeout_s, cancel))  # type: ignore[attr-defined]

    def ocr_status(self) -> tuple[str, str]:
        if self._ocr is None:
            return "disabled", ""
        state = getattr(self._ocr, "state", "")
        return str(getattr(state, "value", state)), str(getattr(self._ocr, "error", "") or "")

    def save_evidence(self, image: np.ndarray, run_id: str, index: int) -> str:
        """``evidence/<yyyy-mm-dd>/<run_id>_<n>.png`` in the data folder; returns the path relative
        to the data folder (forward slashes). Raises storage.StorageError."""
        rel = f"evidence/{date.today().isoformat()}/{run_id}_{index}.png"
        imageio.save_png(image, paths.data_dir() / rel)
        return rel

    def keep_awake(self, active: bool) -> bool:
        return power.keep_awake(active)

    def close(self) -> None:
        if self._grabber is not None:
            try:
                self._grabber.close()
            except Exception:  # noqa: BLE001 - closing must never raise
                log.debug("grabber close failed", exc_info=True)
            self._grabber = None
