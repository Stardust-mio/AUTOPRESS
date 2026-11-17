"""Step execution with a fake backend (G4): every step type, split modes, DPI-scaled offsets,
click_text fallbacks, masked captures, blank captures and ocr_check only_new_text."""

from __future__ import annotations

import re
import time
from collections.abc import Sequence
from typing import Any

import numpy as np
import pytest

import autopress.ocr.imageio as imageio_mod
from autopress.models import (
    Anchor,
    BetweenSegments,
    ClearMethod,
    ClientPoint,
    CoordMode,
    LogLevel,
    Rect,
    ResultClass,
    SplitMode,
    Step,
    StepType,
    TextMatch,
    TimeoutAction,
    TypeCodeParams,
    make_step,
    record_point,
    record_region,
)
from autopress.ocr.engine import OcrUnavailable
from autopress.ocr.service import OcrCancelled, OcrTimeout
from autopress.runner import messages as msg
from autopress.runner.control import RunControl, StopRequested
from autopress.runner.steps import (
    CaptureBlank,
    StepContext,
    StepError,
    TargetGone,
    baseline_texts,
    code_segments,
    execute_step,
    render_template,
)
from autopress.win32.input import ClipboardBusy, ForegroundLost, UnmappableChar
from tests.runner_helpers import FakeBackend, FakeGuard, FakeWorld, Item, fast_settings, make_profile, runner_standins

pytestmark = pytest.mark.usefixtures("runner_standins")
_ = runner_standins


def make_ctx(world: FakeWorld, profile: Any = None, *, code: str = "ABCD-1234", dry: bool = False,
             masks: Sequence[Rect] = (), backend: FakeBackend | None = None) -> StepContext:
    profile = profile or make_profile(world)
    backend = backend or FakeBackend(world)
    control = RunControl()
    logs: list[tuple[LogLevel, str]] = []
    ctx = StepContext(backend=backend, control=control, profile=profile, settings=fast_settings(),
                      target=world.info(), guard=None if dry else FakeGuard(world, world.hwnd, world.pid, False,
                                                                             control.checkpoint),
                      code=code, index=2, run_id="run1", dry_run=dry, masked_rects=lambda: list(masks),
                      log_fn=lambda lvl, t: logs.append((lvl, t)), evidence_seq=lambda: 7)
    ctx.logs = logs  # type: ignore[attr-defined]
    return ctx


def step(st: StepType, **params: Any) -> Step:
    s = make_step(st)
    for k, v in params.items():
        setattr(s.params, k, v)
    return s


def clicks(world: FakeWorld) -> list[tuple[int, int]]:
    return [(a[1], a[2]) for a in world.actions if a[0] == "click"]


# ----------------------------------------------------------------------------- templates / segments


def test_render_template_fills_known_placeholders_only() -> None:
    out = render_template("/redeem {code} #{index} {date} {time} {unknown} {", "AB-12", 3)
    assert out.startswith("/redeem AB-12 #3 ")
    assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \{unknown\} \{$", out)


@pytest.mark.parametrize(("code", "split", "seps", "sizes", "strip", "expected"), [
    ("ABCD-1234-EF", SplitMode.NONE, "-_", [], False, ["ABCD-1234-EF"]),
    ("ABCD-1234-EF", SplitMode.NONE, "-_", [], True, ["ABCD1234EF"]),
    ("ABCD-EFGHIJ-KL", SplitMode.SEPARATOR, "-_", [], False, ["ABCD", "EFGHIJ", "KL"]),
    ("ab_cd-ef", SplitMode.SEPARATOR, "-_", [], False, ["ab", "cd", "ef"]),
    ("ABCDE-FGHIJ-KLMNO", SplitMode.FIXED, "-_", [5, 5, 5], False, ["ABCDE", "FGHIJ", "KLMNO"]),
    ("ABCDEFGHIJKL", SplitMode.FIXED, "-_", [4, 6, 2], False, ["ABCD", "EFGHIJ", "KL"]),
])
def test_code_segments(code: str, split: SplitMode, seps: str, sizes: list[int], strip: bool,
                       expected: list[str]) -> None:
    world = FakeWorld()
    prof = make_profile(world)
    p = TypeCodeParams(split=split, separators=seps, group_sizes=sizes, strip_separators=strip)
    assert code_segments(code, p, prof) == expected


def test_code_segments_fixed_uses_profile_groups_and_needs_sizes() -> None:
    world = FakeWorld()
    prof = make_profile(world)
    prof.code_format.groups = [3, 3]
    assert code_segments("ABC-DEF", TypeCodeParams(split=SplitMode.FIXED), prof) == ["ABC", "DEF"]
    prof.code_format.groups = []
    with pytest.raises(StepError):
        code_segments("ABCDEF", TypeCodeParams(split=SplitMode.FIXED), prof)


# ----------------------------------------------------------------------------- focus / click_point


def test_focus_window_brings_target_to_front() -> None:
    world = FakeWorld(foreground=55)
    ctx = make_ctx(world)
    out = execute_step(step(StepType.FOCUS_WINDOW, settle_ms=0), ctx)
    assert out.ok and world.foreground == world.hwnd and not out.sent_input


def test_focus_window_failures_raise_foreground_lost() -> None:
    world = FakeWorld(foreground=55, focus_ok=False)
    with pytest.raises(ForegroundLost) as ei:
        execute_step(step(StepType.FOCUS_WINDOW), make_ctx(world))
    assert str(ei.value) == msg.focus_failed()
    world2 = FakeWorld(minimized=True)
    with pytest.raises(ForegroundLost):
        execute_step(step(StepType.FOCUS_WINDOW, restore_minimized=False), make_ctx(world2))


def test_click_point_resolves_and_sends_input() -> None:
    world = FakeWorld()
    ctx = make_ctx(world)
    pt = record_point(world.client, 740, 410)
    out = execute_step(step(StepType.CLICK_POINT, point=pt, after_ms=0), ctx)
    assert clicks(world) == [(740, 410)] and out.point == (740, 410) and out.sent_input


def test_click_point_dpi_scaled_offset() -> None:
    """Offset mode: distances to the anchor scale by window_dpi / ref_dpi (SPEC 5.2)."""
    world = FakeWorld(dpi=144)
    prof = make_profile(world)
    prof.coord_mode = CoordMode.OFFSET
    ctx = make_ctx(world, prof)
    cx, cy = world.client[:2]
    pt = ClientPoint(dx=100, dy=50, rx=0.08, ry=0.07, ref_w=1280, ref_h=720, anchor=Anchor.TL, ref_dpi=96)
    execute_step(step(StepType.CLICK_POINT, point=pt, after_ms=0), ctx)
    br = ClientPoint(dx=1180, dy=670, rx=0.92, ry=0.93, ref_w=1280, ref_h=720, anchor=Anchor.BR, ref_dpi=96)
    execute_step(step(StepType.CLICK_POINT, point=br, after_ms=0), ctx)
    assert clicks(world) == [(cx + 150, cy + 75), (cx + 1280 - 150, cy + 720 - 75)]


def test_click_point_jitter_stays_near_and_inside() -> None:
    world = FakeWorld()
    ctx = make_ctx(world)
    pt = record_point(world.client, 740, 410)
    for _ in range(30):
        execute_step(step(StepType.CLICK_POINT, point=pt, after_ms=0, jitter_px=4), ctx)
    assert all(abs(x - 740) <= 4 and abs(y - 410) <= 4 for x, y in clicks(world))


def test_click_point_missing_point_is_step_error() -> None:
    with pytest.raises(StepError):
        execute_step(make_step(StepType.CLICK_POINT), make_ctx(FakeWorld()))


def test_click_point_dry_run_reports_cover_but_ignores_own_windows() -> None:
    world = FakeWorld(covers=[((700, 380, 100, 100), 2002, "記事本", False)])
    pt = record_point(world.client, 740, 410)
    out = execute_step(step(StepType.CLICK_POINT, point=pt), make_ctx(world, dry=True))
    assert not out.ok and "記事本" in out.message and not world.actions
    world2 = FakeWorld(covers=[((700, 380, 100, 100), 3003, "AutoPress", True)])
    out2 = execute_step(step(StepType.CLICK_POINT, point=pt), make_ctx(world2, dry=True))
    assert out2.ok and out2.point == (740, 410) and not world2.actions


# ----------------------------------------------------------------------------- click_text


def click_text_step(world: FakeWorld, **kw: Any) -> Step:
    params = {"text": "兌換|Redeem", "timeout_ms": 0, "poll_ms": 50, "after_ms": 0,
              "region": record_region(world.client, world.client[0] + 80, world.client[1] + 260, 420, 100)}
    params.update(kw)
    return step(StepType.CLICK_TEXT, **params)


def test_click_text_clicks_found_text_centre_with_dpi_scaled_offset() -> None:
    world = FakeWorld(dpi=120)
    ctx = make_ctx(world)
    out = execute_step(click_text_step(world, offset_x=8, offset_y=-4), ctx)
    bx, by = world.center(world.button_rect)
    assert clicks(world) == [(bx + 10, by - 5)]  # 8 * 120/96 = 10, -4 * 1.25 = -5
    assert world.submitted and out.point == (bx + 10, by - 5)


def test_click_text_auto_upscale_retries_at_2x() -> None:
    world = FakeWorld()
    world.statics.append(Item("領取", world.at(320, 290, 60, 20), small=True))
    out = execute_step(click_text_step(world, text="領取"), make_ctx(world))
    assert [o.upscale for o in world.ocr_opts] == [1, 2]
    assert out.ok and clicks(world)
    assert all(o.det_side == 960 for o in world.ocr_opts)


def test_click_text_fixed_upscale_does_not_retry() -> None:
    world = FakeWorld()
    world.statics.append(Item("領取", world.at(320, 290, 60, 20), small=True))
    with pytest.raises(StepError):
        execute_step(click_text_step(world, text="領取", upscale=1), make_ctx(world))
    assert [o.upscale for o in world.ocr_opts] == [1]


def test_click_text_not_found_uses_fallback_point() -> None:
    world = FakeWorld()
    fb = record_point(world.client, 900, 500)
    out = execute_step(click_text_step(world, text="不存在", fallback_point=fb), make_ctx(world))
    assert clicks(world) == [(900, 500)] and out.point == (900, 500)


def test_click_text_on_not_found_continue_skips_the_click() -> None:
    world = FakeWorld()
    ctx = make_ctx(world)
    out = execute_step(click_text_step(world, text="確定|OK", on_not_found=TimeoutAction.CONTINUE), ctx)
    assert out.ok and not clicks(world) and not out.sent_input
    assert out.message == msg.text_skipped("確定|OK")
    assert (LogLevel.INFO, msg.text_skipped("確定|OK")) in ctx.logs  # type: ignore[attr-defined]


def test_click_text_on_not_found_fail_is_step_error_after_polling() -> None:
    world = FakeWorld()
    t0 = time.monotonic()
    with pytest.raises(StepError) as ei:
        execute_step(click_text_step(world, text="確定", timeout_ms=200, poll_ms=50), make_ctx(world))
    assert str(ei.value) == msg.text_not_found("確定")
    assert time.monotonic() - t0 >= 0.19
    assert len(world.grabs) >= 3  # polled


def test_click_text_regex_is_one_pattern() -> None:
    world = FakeWorld()
    execute_step(click_text_step(world, text="^(OK|兌換)$", match=TextMatch.REGEX), make_ctx(world))
    assert clicks(world)


def test_click_text_dry_run_finds_without_clicking() -> None:
    world = FakeWorld()
    out = execute_step(click_text_step(world), make_ctx(world, dry=True))
    assert out.ok and out.point == world.center(world.button_rect) and not world.actions


# ----------------------------------------------------------------------------- type_code / type_text / key


def type_step(**kw: Any) -> Step:
    params = {"key_delay_ms": 0, "after_ms": 0}
    params.update(kw)
    return step(StepType.TYPE_CODE, **params)


def test_type_code_clears_then_types_code_as_shown() -> None:
    world = FakeWorld()
    world.focused = 0
    world.boxes[0] = "OLD"
    out = execute_step(type_step(), make_ctx(world, code="AbCd-12_34"))
    assert world.boxes == ["AbCd-12_34"] and out.sent_input
    kinds = [a[0] for a in world.actions]
    assert kinds.index("clear") < kinds.index("type")


def test_type_code_strip_separators() -> None:
    world = FakeWorld()
    world.focused = 0
    execute_step(type_step(strip_separators=True), make_ctx(world, code="AbCd-12_34"))
    assert world.boxes == ["AbCd1234"]


def test_type_code_three_boxes_with_tab() -> None:
    world = FakeWorld(group_sizes=[5, 5, 5], auto_advance=False)
    world.focused = 0
    execute_step(type_step(split=SplitMode.FIXED, group_sizes=[5, 5, 5], between=BetweenSegments.TAB),
                 make_ctx(world, code="ABCDE-FGHIJ-KLMNO"))
    assert world.boxes == ["ABCDE", "FGHIJ", "KLMNO"]
    assert [a for a in world.actions if a[0] == "combo"] == [("combo", "Tab"), ("combo", "Ctrl+A")] * 2


def test_type_code_unequal_groups_auto_advance() -> None:
    world = FakeWorld(group_sizes=[4, 6, 2])
    world.focused = 0
    world.boxes = ["OLD1", "OLDOLD", "OL"]  # auto-advance selects the next box, so typing replaces it
    execute_step(type_step(split=SplitMode.SEPARATOR, between=BetweenSegments.NONE),
                 make_ctx(world, code="ABCD-EFGHIJ-KL"))
    assert world.boxes == ["ABCD", "EFGHIJ", "KL"]
    assert [a for a in world.actions if a[0] == "combo"] == [("combo", "Ctrl+A")] * 2


def test_type_code_replaces_what_later_boxes_still_hold() -> None:
    """Gate G-08: a page's own focus() does not select the next box; boxes 2..n still hold the
    previous code (kept after an error). Each later box is selected before its segment, so the
    new code replaces the old one instead of being rejected by the full maxlength box."""
    world = FakeWorld(group_sizes=[4, 6, 2], advance_selects=False)
    world.focused = 0
    world.boxes = ["OLD1", "OLDOLD", "OL"]
    execute_step(type_step(split=SplitMode.SEPARATOR, between=BetweenSegments.NONE),
                 make_ctx(world, code="ABCD-EFGHIJ-KL"))
    assert world.boxes == ["ABCD", "EFGHIJ", "KL"]
    world2 = FakeWorld(group_sizes=[4, 6, 2], advance_selects=False)  # without clear_first: nothing selected
    world2.focused = 0
    world2.boxes = ["", "OLDOLD", "OL"]
    execute_step(type_step(split=SplitMode.SEPARATOR, between=BetweenSegments.NONE, clear_first=False),
                 make_ctx(world2, code="ABCD-EFGHIJ-KL"))
    assert world2.boxes == ["ABCD", "OLDOLD", "OL"] and not [a for a in world2.actions if a[0] == "combo"]


def test_type_code_backspace_method_never_selects_later_boxes() -> None:
    world = FakeWorld(group_sizes=[4, 4])
    world.focused = 0
    execute_step(type_step(split=SplitMode.FIXED, group_sizes=[4, 4], between=BetweenSegments.NONE,
                           clear_method=ClearMethod.BACKSPACE), make_ctx(world, code="ABCD-EFGH"))
    assert world.boxes == ["ABCD", "EFGH"] and not [a for a in world.actions if a[0] == "combo"]


def test_type_code_verify_region_ok_and_mismatch() -> None:
    world = FakeWorld()
    world.focused = 0
    box = world.box_rects()[0]
    region = record_region(world.client, box[0] - 5, box[1] - 5, box[2] + 10, box[3] + 10)
    execute_step(type_step(verify_region=region), make_ctx(world, code="abcd-1234"))
    world2 = FakeWorld()
    world2.focused = 0
    world2.hooks["char"] = lambda w: w.boxes.__setitem__(0, w.boxes[0].replace("1", "ㄅ"))  # an IME rewrites it
    with pytest.raises(StepError) as ei:
        execute_step(type_step(verify_region=region), make_ctx(world2, code="abcd-1234"))
    assert str(ei.value) == msg.typed_mismatch()


def test_type_code_dry_run_reports_segments() -> None:
    world = FakeWorld()
    out = execute_step(type_step(split=SplitMode.SEPARATOR), make_ctx(world, code="AB-CD", dry=True))
    assert out.message == msg.would_type("AB / CD") and not world.actions


def test_type_code_clipboard_busy_and_unmappable_become_step_errors() -> None:
    world = FakeWorld()
    world.focused = 0

    class Busy(FakeBackend):
        def type_text(self, *a: Any, **k: Any) -> None:
            raise ClipboardBusy("busy")

    class Unmappable(FakeBackend):
        def type_text(self, *a: Any, **k: Any) -> None:
            raise UnmappableChar("ㄅ")

    with pytest.raises(StepError) as e1:
        execute_step(type_step(), make_ctx(world, backend=Busy(world)))
    assert str(e1.value) == msg.clipboard_busy()
    with pytest.raises(StepError) as e2:
        execute_step(type_step(), make_ctx(world, backend=Unmappable(world)))
    assert str(e2.value) == msg.unmappable_char("ㄅ")


def test_type_text_renders_template() -> None:
    world = FakeWorld()
    world.focused = 0
    execute_step(step(StepType.TYPE_TEXT, text="/redeem {code} {index}", key_delay_ms=0, after_ms=0),
                 make_ctx(world, code="AB-12"))
    assert world.boxes == ["/redeem AB-12 3"]  # index 2 (0-based) -> {index} 3


def test_key_step_repeat_and_system_shortcut_refused() -> None:
    world = FakeWorld()
    execute_step(step(StepType.KEY, keys="Tab", repeat=3, after_ms=0), make_ctx(world))
    assert [a for a in world.actions if a[0] == "combo"] == [("combo", "Tab")] * 3
    world2 = FakeWorld()
    with pytest.raises(StepError):
        execute_step(step(StepType.KEY, keys="Alt+F4"), make_ctx(world2))
    with pytest.raises(StepError):
        execute_step(step(StepType.KEY, keys="Ctrl+Nope"), make_ctx(world2))
    assert not world2.actions


# ----------------------------------------------------------------------------- wait / wait_text


def test_wait_with_jitter_and_dry_run() -> None:
    world = FakeWorld()
    t0 = time.monotonic()
    execute_step(step(StepType.WAIT, ms=200, jitter_pct=50), make_ctx(world))
    assert 0.09 <= time.monotonic() - t0 < 0.5
    t1 = time.monotonic()
    out = execute_step(step(StepType.WAIT, ms=5000), make_ctx(world, dry=True))
    assert time.monotonic() - t1 < 0.05 and out.message == msg.wait_skipped()


def test_wait_text_appear_and_disappear() -> None:
    world = FakeWorld()
    out = execute_step(step(StepType.WAIT_TEXT, text="請輸入兌換碼", timeout_ms=0), make_ctx(world))
    assert out.ok
    world.latency_s = 0.15
    world.persist = False
    world.result_text = "處理中"
    world.pending = (time.monotonic() + 0.15, "兌換成功", "success")
    out = execute_step(step(StepType.WAIT_TEXT, text="處理中", appear=False, timeout_ms=2000, poll_ms=50),
                       make_ctx(world))
    assert out.ok


def test_wait_text_timeout_fail_and_continue() -> None:
    world = FakeWorld()
    with pytest.raises(StepError) as ei:
        execute_step(step(StepType.WAIT_TEXT, text="兌換結果", timeout_ms=100, poll_ms=50), make_ctx(world))
    assert str(ei.value) == msg.wait_text_timeout("兌換結果", True)
    ctx = make_ctx(world)
    out = execute_step(step(StepType.WAIT_TEXT, text="兌換結果", timeout_ms=0, on_timeout=TimeoutAction.CONTINUE), ctx)
    assert out.ok and ctx.logs[-1][0] is LogLevel.WARNING  # type: ignore[attr-defined]


# ----------------------------------------------------------------------------- ocr_check


def ocr_step(world: FakeWorld, **kw: Any) -> Step:
    params = {"region": record_region(world.client, world.client[0] + 80, world.client[1] + 350, 900, 160),
              "initial_delay_ms": 0, "poll_ms": 50, "timeout_ms": 300}
    params.update(kw)
    return step(StepType.OCR_CHECK, **params)


def test_ocr_check_classifies_and_saves_evidence() -> None:
    world = FakeWorld(result_text="兌換成功")
    ctx = make_ctx(world)
    out = execute_step(ocr_step(world), ctx)
    assert out.result is ResultClass.SUCCESS and out.matched_keyword == "兌換成功"
    assert out.message == "兌換成功" and out.evidence_path.endswith("run1_7.png") and world.evidence == [("run1", 7)]
    assert not out.sent_input


def test_ocr_check_no_evidence_when_setting_off() -> None:
    world = FakeWorld(result_text="兌換成功")
    ctx = make_ctx(world)
    ctx.settings.save_evidence = False
    out = execute_step(ocr_step(world), ctx)
    assert out.evidence_path == "" and not world.evidence


def test_ocr_check_empty_region_is_unknown_with_message() -> None:
    world = FakeWorld()
    out = execute_step(ocr_step(world, timeout_ms=100), make_ctx(world))
    assert out.result is ResultClass.UNKNOWN and out.message == msg.no_text_read()


def test_ocr_check_only_new_text_ignores_static_text() -> None:
    world = FakeWorld()
    world.statics.append(Item("兌換成功後獎勵將寄至信箱", world.at(100, 450, 700, 30)))  # static, has a keyword
    s = ocr_step(world)
    ctx = make_ctx(world)
    ctx.step_index = 3
    _img, res = ctx.read(ctx.region(s.params.region))
    ctx.baselines[3] = baseline_texts(res.lines)
    world.result_text = "兌換碼無效"
    out = execute_step(s, ctx)
    assert out.result is ResultClass.INVALID
    # without the baseline the static sentence wins (it is SUCCESS + INVALID -> ambiguous)
    ctx2 = make_ctx(world)
    ctx2.step_index = 3
    out2 = execute_step(ocr_step(world, only_new_text=False), ctx2)
    assert out2.result is ResultClass.UNKNOWN


def test_ocr_check_stale_previous_message_waits_for_the_new_one() -> None:
    world = FakeWorld(result_text="兌換碼無效", persist=True)
    s = ocr_step(world, timeout_ms=2000)
    ctx = make_ctx(world)
    ctx.step_index = 3
    ctx.baselines[3] = {"兌換碼無效"}
    world.pending = (time.monotonic() + 0.3, "兌換成功", "success")  # the page answers after 300 ms
    out = execute_step(s, ctx)
    assert out.result is ResultClass.SUCCESS
    assert len(world.grabs) >= 3  # the stale message was read and ignored first


def test_ocr_check_identical_message_is_unknown_no_change() -> None:
    world = FakeWorld(result_text="兌換碼無效", persist=True)
    s = ocr_step(world, timeout_ms=150)
    ctx = make_ctx(world)
    ctx.step_index = 3
    ctx.baselines[3] = {"兌換碼無效"}
    world.pending = (time.monotonic(), "兌換碼無效", "invalid")  # same message replaced in place
    out = execute_step(s, ctx)
    assert out.result is ResultClass.UNKNOWN and out.message == msg.no_change_after_submit()


def test_ocr_check_dry_run_single_read_without_baseline() -> None:
    world = FakeWorld(result_text="此序號已被使用")
    ctx = make_ctx(world, dry=True)
    ctx.baselines[3] = {"此序號已被使用"}
    ctx.step_index = 3
    out = execute_step(ocr_step(world, initial_delay_ms=5000), ctx)
    assert out.result is ResultClass.USED and len(world.grabs) == 1 and not world.evidence


def test_ocr_check_without_region_is_step_error() -> None:
    with pytest.raises(StepError):
        execute_step(make_step(StepType.OCR_CHECK), make_ctx(FakeWorld()))


# ----------------------------------------------------------------------------- captures


def test_masked_rects_applied_to_every_capture(monkeypatch: pytest.MonkeyPatch) -> None:
    world = FakeWorld(result_text="兌換成功")
    real = imageio_mod.mask_rects
    calls: list[tuple[tuple[int, int], list[Rect]]] = []

    def spy(image: np.ndarray, origin: tuple[int, int], rects: Sequence[Rect]) -> np.ndarray:
        calls.append((tuple(origin), list(rects)))
        return real(image, origin, rects)

    monkeypatch.setattr(imageio_mod, "mask_rects", spy)
    bar = world.result_rect  # the mini bar sits exactly on the result message
    ctx = make_ctx(world, masks=[bar])
    out = execute_step(ocr_step(world, timeout_ms=120), ctx)
    assert out.result is ResultClass.UNKNOWN  # AutoPress's own window is never read
    assert calls and len(calls) == len(world.grabs)
    assert all(rects == [bar] for _o, rects in calls)
    calls.clear()
    n_grabs = len(world.grabs)
    execute_step(click_text_step(world), ctx)
    assert calls and len(calls) == len(world.grabs) - n_grabs


def test_capture_blank_raises_but_empty_region_does_not() -> None:
    world = FakeWorld(blank=True)
    with pytest.raises(CaptureBlank):
        execute_step(ocr_step(world), make_ctx(world))
    world2 = FakeWorld()
    ctx = make_ctx(world2)
    region = ctx.region(ocr_step(world2).params.region)
    world2.blank_rects.append(region)  # a uniform (empty) result area on a normal page
    out = execute_step(ocr_step(world2, timeout_ms=0), ctx)
    assert out.result is ResultClass.UNKNOWN
    assert tuple(world2.client) in [tuple(g) for g in world2.grabs]  # re-checked on the whole client


def test_capture_of_closed_window_is_target_gone_and_errors_are_step_errors() -> None:
    world = FakeWorld()
    ctx = make_ctx(world)
    world.alive = False
    with pytest.raises(TargetGone):
        execute_step(ocr_step(world), ctx)
    world2 = FakeWorld(grab_error=OSError("GDI failure"))
    with pytest.raises(StepError) as ei:
        execute_step(ocr_step(world2), make_ctx(world2))
    assert "GDI failure" in str(ei.value)


def test_ocr_errors_map_to_step_errors_and_stop() -> None:
    world = FakeWorld(ocr_error=OcrTimeout())
    with pytest.raises(StepError) as e1:
        execute_step(ocr_step(world), make_ctx(world))
    assert str(e1.value) == msg.ocr_timeout()
    world.ocr_error = OcrUnavailable("模型檔案遺失")
    with pytest.raises(StepError) as e2:
        execute_step(ocr_step(world), make_ctx(world))
    assert "模型檔案遺失" in str(e2.value)
    world.ocr_error = OcrCancelled()
    ctx = make_ctx(world)
    ctx.control.request_stop()
    with pytest.raises(StopRequested):
        execute_step(click_text_step(world), ctx)


def test_unknown_step_is_skipped() -> None:
    from autopress.models import UnknownParams

    out = execute_step(Step(type=StepType.UNKNOWN, params=UnknownParams(type_name="click_image")),
                       make_ctx(FakeWorld()))
    assert out.ok and not out.sent_input


def test_param_types_cover_every_step_type() -> None:
    """Every StepType except UNKNOWN has a handler (the dispatch table is complete)."""
    from autopress.runner.steps import _HANDLERS

    assert set(_HANDLERS) == {t for t in StepType if t is not StepType.UNKNOWN}
