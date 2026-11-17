"""Preflight (every SPEC 7.2 key with its level and action) and preview marks (G4)."""

from __future__ import annotations

from typing import Any

import pytest

from autopress.models import (
    PREFLIGHT_ACTIONS,
    PREFLIGHT_KEYS,
    Anchor,
    ClientPoint,
    CoordMode,
    IssueLevel,
    KeyParams,
    OcrCheckParams,
    PreviewKind,
    Profile,
    StepType,
    TargetMatch,
    TitleMatch,
    TypeCodeParams,
    TypeTextParams,
    UnknownAction,
    WaitTextParams,
    make_step,
    record_point,
    record_region,
)
from autopress.runner import messages as msg
from autopress.runner.preflight import per_code_seconds, run_preflight
from autopress.runner.preview import preview_profile
from tests.runner_helpers import FakeBackend, FakeWorld, fast_settings, make_profile, runner_standins

pytestmark = pytest.mark.usefixtures("runner_standins")
_ = runner_standins

# SPEC 7.2: key -> (level, action)
EXPECTED: dict[str, tuple[IssueLevel, str]] = {
    "profile_errors": (IssueLevel.ERROR, "open_profile"),
    "profile_warnings": (IssueLevel.WARNING, "open_profile"),
    "points_missing": (IssueLevel.ERROR, "open_profile"),
    "no_codes": (IssueLevel.ERROR, ""),
    "unassigned_codes": (IssueLevel.INFO, "assign_codes"),
    "target_not_set": (IssueLevel.ERROR, "pick_window"),
    "target_forbidden": (IssueLevel.ERROR, "pick_window"),
    "target_title_required": (IssueLevel.ERROR, "pick_window"),
    "target_not_found": (IssueLevel.ERROR, "pick_window"),
    "target_is_self": (IssueLevel.ERROR, "pick_window"),
    "target_multiple": (IssueLevel.WARNING, "pick_window"),
    "target_minimized": (IssueLevel.INFO, ""),
    "elevation_unknown": (IssueLevel.WARNING, ""),
    "size_changed": (IssueLevel.WARNING, "realign"),
    "dpi_changed": (IssueLevel.WARNING, "realign"),
    "ocr_failed": (IssueLevel.ERROR, ""),
    "ocr_loading": (IssueLevel.INFO, "wait_ocr"),
    "capture_blank": (IssueLevel.WARNING, ""),
    "no_result_check": (IssueLevel.WARNING, "open_profile"),
    "no_verify": (IssueLevel.INFO, "open_profile"),
    "untested_profile": (IssueLevel.WARNING, "test_one"),
    "fast_interval": (IssueLevel.WARNING, "open_profile"),
    "estimate": (IssueLevel.INFO, ""),
}
SEEN: set[str] = set()


def good_profile(world: FakeWorld) -> Profile:
    p = make_profile(world)
    p.last_test_ok_at = "2026-11-17T12:00:00+08:00"
    p.policy.interval_min_s, p.policy.interval_max_s = 6.0, 8.0
    tc = p.steps[1].params
    assert isinstance(tc, TypeCodeParams)
    box = world.box_rects()[0]
    tc.verify_region = record_region(world.client, *box)
    return p


def check(world: FakeWorld, profile: Profile, *, code_count: int = 3, ocr_state: str = "ready",
          **kw: Any) -> dict[str, list[Any]]:
    report = run_preflight(profile, kw.pop("settings", fast_settings()), code_count=code_count, ocr_state=ocr_state,
                           backend=FakeBackend(world), **kw)
    by_key: dict[str, list[Any]] = {}
    for issue in report.issues:
        assert issue.key in PREFLIGHT_KEYS and issue.action in PREFLIGHT_ACTIONS + ("",)
        assert issue.message
        if issue.key in EXPECTED:
            assert (issue.level, issue.action) == EXPECTED[issue.key], issue.key
        SEEN.add(issue.key)
        by_key.setdefault(issue.key, []).append(issue)
    by_key["_report"] = [report]  # type: ignore[list-item]
    return by_key


def test_good_profile_only_estimate_and_no_input() -> None:
    world = FakeWorld()
    p = good_profile(world)
    issues = check(world, p, code_count=4)
    report = issues.pop("_report")[0]
    assert set(issues) == {"estimate"} and report.ok and report.target.hwnd == world.hwnd
    assert report.code_count == 4 and report.ocr_needed
    t = per_code_seconds(p) * 4
    assert issues["estimate"][0].message == msg.pf_estimate(4, 6.0, 8.0, t)
    assert not world.actions and not world.trips


def test_per_code_seconds_counts_waits_and_delays() -> None:
    world = FakeWorld()
    p = good_profile(world)
    oc = p.steps[3].params
    assert isinstance(oc, OcrCheckParams)
    oc.initial_delay_ms = 800
    w = make_step(StepType.WAIT)
    w.params.ms = 1500
    p.steps.append(w)
    p.steps[0].params.after_ms = 120
    assert per_code_seconds(p) == pytest.approx(7.0 + 0.8 + 1.5 + 0.12)


def test_points_missing_without_duplicate_profile_errors() -> None:
    world = FakeWorld()
    p = good_profile(world)
    p.steps[0].params.point = None
    p.steps[3].params.region = None
    issues = check(world, p)
    assert "points_missing" in issues and "profile_errors" not in issues
    assert issues["points_missing"][0].message == msg.pf_points_missing("1、4")


def test_profile_errors_first_three_and_warnings() -> None:
    world = FakeWorld()
    p = good_profile(world)
    ct = make_step(StepType.CLICK_TEXT)
    ct.params.text = ""  # error
    p.steps.append(ct)
    wt = make_step(StepType.WAIT_TEXT)
    assert isinstance(wt.params, WaitTextParams)
    wt.params.text = ""  # error
    p.steps.append(wt)
    k1 = make_step(StepType.KEY)
    assert isinstance(k1.params, KeyParams)
    k1.params.keys = "Alt+F4"  # error (system shortcut)
    p.steps.append(k1)
    k2 = make_step(StepType.KEY)
    k2.params.keys = "Ctrl+Nope"  # error (4th: hidden behind the hint)
    p.steps.append(k2)
    k3 = make_step(StepType.KEY)
    k3.params.keys = "Ctrl+L"  # warning (risky)
    p.steps.append(k3)
    tt = make_step(StepType.TYPE_TEXT)
    assert isinstance(tt.params, TypeTextParams)
    tt.params.text = "hello"  # warning: no {code}
    p.steps.append(tt)
    p.policy.on_unknown = UnknownAction.CONTINUE  # warning
    issues = check(world, p)
    assert len(issues["profile_errors"]) == 3 and issues["profile_errors"][2].hint == msg.pf_more_errors(1)
    assert len(issues["profile_warnings"]) == 3


def test_codes_and_unassigned() -> None:
    world = FakeWorld()
    issues = check(world, good_profile(world), code_count=0, unassigned_count=3)
    assert "no_codes" in issues and "estimate" not in issues
    assert issues["unassigned_codes"][0].message == msg.pf_unassigned(3)


@pytest.mark.parametrize(("target", "key"), [
    (TargetMatch(), "target_not_set"),
    (TargetMatch(exe="cmd.exe"), "target_forbidden"),
    (TargetMatch(exe="chrome.exe", title="", title_mode=TitleMatch.CONTAINS), "target_title_required"),
    (TargetMatch(exe="msedge.exe", title="兌換", title_mode=TitleMatch.ANY), "target_title_required"),
    (TargetMatch(exe="", title="兌換", title_mode=TitleMatch.CONTAINS), "target_exe_unknown"),
])
def test_target_rules(target: TargetMatch, key: str) -> None:
    world = FakeWorld()
    p = good_profile(world)
    p.target = target
    issues = check(world, p)
    assert key in issues and issues["_report"][0].target is None
    assert "target_not_found" not in issues
    assert "profile_errors" not in issues  # reported once, under the target key


def test_target_not_found_multiple_minimized_and_self() -> None:
    world = FakeWorld(alive=False)
    issues = check(world, good_profile(world))
    assert issues["target_not_found"][0].message == msg.target_not_found(good_profile(world).target.describe())
    world = FakeWorld(extra_matches=2)
    issues = check(world, good_profile(world))
    assert issues["target_multiple"][0].message == msg.pf_target_multiple(3, world.title)
    world = FakeWorld(minimized=True, blank=True, client=(0, 0, 160, 28))
    issues = check(world, good_profile(world))
    assert "target_minimized" in issues
    assert not {"capture_blank", "size_changed", "dpi_changed"} & set(issues)
    world = FakeWorld()
    world.pid = world.own_pid
    issues = check(world, good_profile(world))
    assert "target_is_self" in issues and not issues["_report"][0].ok


def test_found_window_of_a_forbidden_program() -> None:
    world = FakeWorld(exe_path="C:/Windows/explorer.exe")
    p = good_profile(world)
    p.target = TargetMatch(exe="", title=world.title, title_mode=TitleMatch.EXACT)  # exact: exe may be unknown
    issues = check(world, p)
    assert issues["target_forbidden"][0].message == msg.pf_forbidden("explorer.exe")


def test_target_hwnd_is_used_first() -> None:
    world = FakeWorld(extra_matches=3)
    issues = check(world, good_profile(world), target_hwnd=world.hwnd)
    assert "target_multiple" not in issues and issues["_report"][0].target.hwnd == world.hwnd


@pytest.mark.parametrize(("permission", "can", "key", "action", "text"), [
    ("blocked_elevated", True, "elevated", "restart_admin", "pf_target_elevated"),
    ("blocked_elevated", False, "elevated", "", "pf_target_elevated_standard_user"),
    ("unknown", True, "elevation_unknown", "", "pf_elevation_unknown"),
])
def test_elevation(permission: str, can: bool, key: str, action: str, text: str) -> None:
    world = FakeWorld(permission=permission, can_elevate=can)
    issues = check(world, good_profile(world))
    issue = issues[key][0]
    assert issue.action == action and issue.message == getattr(msg, text)()
    if key == "elevated":
        assert issue.level is IssueLevel.ERROR
        SEEN.add(key)


def test_size_and_dpi_changed() -> None:
    world = FakeWorld()
    p = good_profile(world)
    world.client = (100, 50, 1600, 900)
    world.dpi = 144
    issues = check(world, p)
    assert issues["size_changed"][0].message == msg.pf_size_changed("1280×720", "1600×900", True)
    assert issues["dpi_changed"][0].message == msg.pf_dpi_changed(100, 150)
    p.coord_mode = CoordMode.OFFSET
    assert check(world, p)["size_changed"][0].message == msg.pf_size_changed("1280×720", "1600×900", False)


@pytest.mark.parametrize(("state", "key"), [("failed", "ocr_failed"), ("disabled", "ocr_failed"),
                                            ("loading", "ocr_loading"), ("not_started", "ocr_loading")])
def test_ocr_states(state: str, key: str) -> None:
    world = FakeWorld()
    issues = check(world, good_profile(world), ocr_state=state, ocr_error="缺少模型檔")
    assert key in issues
    if state == "failed":
        assert issues[key][0].message == msg.ocr_failed("缺少模型檔")
    p = good_profile(world)
    p.steps = [s for s in p.steps if s.type is not StepType.OCR_CHECK]
    p.steps[1].params.verify_region = None
    assert key not in check(world, p, ocr_state=state)  # a profile without OCR does not care


def test_capture_blank_only_for_visible_target_pixels() -> None:
    world = FakeWorld(blank=True)
    assert "capture_blank" in check(world, good_profile(world))
    world = FakeWorld(blank=True, covers=[((0, 0, 4000, 3000), 3003, "AutoPress", True)])
    assert "capture_blank" not in check(world, good_profile(world))  # own window over the target: not sampled
    world = FakeWorld()
    assert "capture_blank" not in check(world, good_profile(world))


def test_result_check_verify_tested_interval() -> None:
    world = FakeWorld()
    p = good_profile(world)
    p.steps = [s for s in p.steps if s.type is not StepType.OCR_CHECK]
    p.steps[1].params.verify_region = None
    p.last_test_ok_at = ""
    p.policy.interval_min_s = 1.5
    issues = check(world, p)
    assert issues["no_result_check"][0].message == msg.pf_no_result_check()
    assert "profile_warnings" not in issues  # the validation warning is not repeated
    assert {"no_verify", "untested_profile", "fast_interval"} <= set(issues)


def test_daily_cap_issues() -> None:
    world = FakeWorld()
    s = fast_settings()
    s.daily_cap = 5
    issues = check(world, good_profile(world), code_count=0, settings=s, daily_cap_left=0, daily_cap_shortened=True)
    assert issues["daily_cap"][0].level is IssueLevel.ERROR and "no_codes" not in issues
    assert issues["daily_cap"][0].message == msg.pf_daily_cap_reached(5)
    s2 = fast_settings()
    s2.daily_cap = 5
    issues = check(world, good_profile(world), code_count=2, settings=s2, daily_cap_left=2, daily_cap_shortened=True)
    assert issues["daily_cap"][0].level is IssueLevel.INFO
    assert issues["daily_cap"][0].message == msg.pf_daily_cap_shortened(2)
    SEEN.add("daily_cap")


def test_every_preflight_key_was_produced() -> None:
    """The scenarios of this module produce every key of SPEC 7.2 (re-run here, so the check does
    not depend on test order)."""
    test_good_profile_only_estimate_and_no_input()
    test_points_missing_without_duplicate_profile_errors()
    test_profile_errors_first_three_and_warnings()
    test_codes_and_unassigned()
    for target in (TargetMatch(), TargetMatch(exe="cmd.exe"), TargetMatch(exe="chrome.exe")):
        world = FakeWorld()
        p = good_profile(world)
        p.target = target
        check(world, p)
    test_target_not_found_multiple_minimized_and_self()
    for permission, can in (("blocked_elevated", True), ("unknown", True)):
        world = FakeWorld(permission=permission, can_elevate=can)
        check(world, good_profile(world))
        SEEN.add("elevated") if permission == "blocked_elevated" else None
    test_size_and_dpi_changed()
    for state in ("failed", "loading"):
        world = FakeWorld()
        check(world, good_profile(world), ocr_state=state)
    test_capture_blank_only_for_visible_target_pixels()
    test_result_check_verify_tested_interval()
    test_daily_cap_issues()
    assert set(PREFLIGHT_KEYS) <= SEEN, sorted(set(PREFLIGHT_KEYS) - SEEN)


# ----------------------------------------------------------------------------- preview


def preview_world_profile() -> tuple[FakeWorld, Profile]:
    world = FakeWorld()
    p = make_profile(world, submit="click_text")
    ct = p.steps[2].params
    ct.fallback_point = record_point(world.client, 300, 360)
    p.steps[1].params.verify_region = record_region(world.client, 200, 250, 600, 50)
    wt = make_step(StepType.WAIT_TEXT)
    wt.params.text = "兌換"
    wt.params.region = record_region(world.client, 150, 120, 500, 300)
    p.steps.insert(0, wt)
    off = make_step(StepType.CLICK_POINT)
    off.params.point = record_point(world.client, 700, 400)
    off.enabled = False
    p.steps.append(off)
    return world, p


def test_preview_marks_in_step_order() -> None:
    world, p = preview_world_profile()
    marks = preview_profile(p, world.hwnd, backend=FakeBackend(world))
    kinds = [(m.step_index, m.kind) for m in marks]
    assert kinds == [(0, PreviewKind.SEARCH_REGION), (1, PreviewKind.POINT), (2, PreviewKind.REGION),
                     (3, PreviewKind.SEARCH_REGION), (3, PreviewKind.FALLBACK_POINT), (4, PreviewKind.REGION)]
    assert marks[1].rect == (*world.center(world.box_rects()[0]), 1, 1)
    assert marks[1].label == "2 點一下序號輸入框" and marks[1].step_id == p.steps[1].id
    assert all(m.ok for m in marks)
    assert not world.actions


def test_preview_ok_false_for_covered_or_outside_and_own_windows_ignored() -> None:
    world, p = preview_world_profile()
    pt = world.center(world.box_rects()[0])
    world.covers.append(((pt[0] - 5, pt[1] - 5, 10, 10), 2002, "記事本", False))
    marks = preview_profile(p, world.hwnd, backend=FakeBackend(world))
    assert [m.ok for m in marks if m.kind is PreviewKind.POINT] == [False]
    world.covers[0] = ((0, 0, 4000, 3000), 3003, "AutoPress", True)  # the main window of AutoPress
    marks = preview_profile(p, world.hwnd, backend=FakeBackend(world))
    assert all(m.ok for m in marks)
    p.coord_mode = CoordMode.OFFSET
    world.covers.clear()
    world.client = (100, 50, 500, 300)  # smaller window: offsets fall outside
    marks = preview_profile(p, world.hwnd, backend=FakeBackend(world))
    assert not all(m.ok for m in marks)


def test_preview_dpi_scaled_offsets_and_gone_window() -> None:
    world = FakeWorld(dpi=120)
    p = make_profile(world)
    p.coord_mode = CoordMode.OFFSET
    p.steps[0].params.point = ClientPoint(dx=80, dy=40, rx=0.06, ry=0.06, ref_w=1280, ref_h=720,
                                         anchor=Anchor.TL, ref_dpi=96)
    marks = preview_profile(p, world.hwnd, backend=FakeBackend(world))
    assert marks[0].rect[:2] == (world.client[0] + 100, world.client[1] + 50)
    world.alive = False
    assert preview_profile(p, world.hwnd, backend=FakeBackend(world)) == []
    assert preview_profile(p, 0, backend=FakeBackend(world)) == []


def test_preview_same_process_cover_counts_as_target() -> None:
    world, p = preview_world_profile()
    pt = world.center(world.box_rects()[0])
    world.covers.append(((pt[0] - 5, pt[1] - 5, 10, 10), world.pid - 1, "子視窗", False))  # window_pid -> pid
    p.target.allow_same_process = True
    marks = preview_profile(p, world.hwnd, backend=FakeBackend(world))
    assert [m.ok for m in marks if m.kind is PreviewKind.POINT] == [True]
