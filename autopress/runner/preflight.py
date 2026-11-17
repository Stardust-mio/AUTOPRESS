# OWNED BY G4
"""Checks before a run (SPEC section 7.2 lists every issue key, level, message and action)."""

from __future__ import annotations

import logging
from collections import Counter
from typing import TYPE_CHECKING, Any

import numpy as np

from .. import capture as capture_mod
from ..models import (
    FORBIDDEN_TARGET_EXES,
    ClientPoint,
    ClientRegion,
    CoordMode,
    FocusWindowParams,
    IssueLevel,
    OcrCheckParams,
    PreflightIssue,
    PreflightReport,
    Profile,
    Rect,
    Settings,
    TypeCodeParams,
    WaitParams,
    WindowInfo,
)
from . import messages as msg

if TYPE_CHECKING:
    from .backend import Backend

log = logging.getLogger(__name__)

BLANK_GRID = (12, 8)  # cells probed with window_at for the blank-capture check
MIN_BLANK_CELLS = 6  # fewer visible target cells -> the check is skipped (target mostly covered)


def per_code_seconds(profile: Profile) -> float:
    """Average seconds per code for the time estimate: the average interval plus the profile's
    fixed waits, initial delays and after_ms (SPEC 7.2 ``estimate``; cool-downs not included)."""
    fixed_ms = 0.0
    for _i, s in profile.enabled_steps():
        p = s.params
        if isinstance(p, WaitParams):
            fixed_ms += p.ms
        elif isinstance(p, OcrCheckParams):
            fixed_ms += p.initial_delay_ms
        elif isinstance(p, FocusWindowParams):
            fixed_ms += p.settle_ms
        fixed_ms += float(getattr(p, "after_ms", 0) or 0)
    pol = profile.policy
    lo, hi = min(pol.interval_min_s, pol.interval_max_s), max(pol.interval_min_s, pol.interval_max_s)
    return (lo + hi) / 2.0 + fixed_ms / 1000.0


def _issue(issues: list[PreflightIssue], level: IssueLevel, key: str, message: str, hint: str = "",
           action: str = "") -> None:
    issues.append(PreflightIssue(level=level, key=key, message=message, hint=hint, action=action))


def _recorded_geometry(profile: Profile) -> list[ClientPoint | ClientRegion]:
    out: list[ClientPoint | ClientRegion] = []
    for _i, s in profile.enabled_steps():
        for name in ("point", "region", "fallback_point", "verify_region"):
            v = getattr(s.params, name, None)
            if isinstance(v, (ClientPoint, ClientRegion)):
                out.append(v)
    return out


def _profile_issues(profile: Profile, issues: list[PreflightIssue]) -> None:
    missing = profile.missing_setup()
    covered = {(i, f) for i, f in missing}
    errors, warnings = [], []
    for v in profile.validate():
        if v.path == "target.exe" or (v.path == "target.title" and profile.target.needs_title()) or v.path == "target":
            continue  # reported as target_* issues
        if v.step_index >= 0 and any(v.path.endswith(f".{f}") for i, f in covered if i == v.step_index):
            continue  # reported as points_missing
        if v.level is IssueLevel.ERROR:
            errors.append(v)
        elif v.level is IssueLevel.WARNING:
            if v.path == "steps" and not profile.has_result_check() and (
                    "辨識結果" in v.message or "Read result" in v.message):
                continue  # reported as no_result_check
            warnings.append(v)
    for n, v in enumerate(errors[:3]):
        hint = msg.pf_more_errors(len(errors) - 3) if n == 2 and len(errors) > 3 else ""
        _issue(issues, IssueLevel.ERROR, "profile_errors", v.message, hint, "open_profile")
    for v in warnings[:3]:
        _issue(issues, IssueLevel.WARNING, "profile_warnings", v.message, "", "open_profile")
    if missing:
        steps = "、".join(str(i + 1) for i, _f in missing)
        _issue(issues, IssueLevel.ERROR, "points_missing", msg.pf_points_missing(steps), "", "open_profile")


def _find_target(profile: Profile, backend: Backend, target_hwnd: int,
                 issues: list[PreflightIssue]) -> WindowInfo | None:
    if target_hwnd:
        info = backend.window_info(target_hwnd)
        if info is not None and profile.target.matches(info.exe_path, info.title, info.class_name):
            return info
    found = backend.find_targets(profile.target)
    if not found:
        _issue(issues, IssueLevel.ERROR, "target_not_found", msg.target_not_found(profile.target.describe()), "",
               "pick_window")
        return None
    if len(found) > 1:
        _issue(issues, IssueLevel.WARNING, "target_multiple", msg.pf_target_multiple(len(found), found[0].title), "",
               "pick_window")
    return found[0]


def _blank_check(backend: Backend, info: WindowInfo, client: Rect) -> bool:
    """True when the target's visible part captures as black / uniform. Only cells whose window
    under the centre is the target are sampled: AutoPress's own windows (and other covering
    windows) are never sampled. Too few visible cells -> False (cannot tell)."""
    cx, cy, cw, ch = client
    cols, rows = BLANK_GRID
    cell_w, cell_h = cw // cols, ch // rows
    if cell_w < 2 or cell_h < 2:
        return False
    cells = []
    for r in range(rows):
        for c in range(cols):
            x0, y0 = c * cell_w, r * cell_h
            if backend.window_at(cx + x0 + cell_w // 2, cy + y0 + cell_h // 2, False) == info.hwnd:
                cells.append((x0, y0))
    if len(cells) < MIN_BLANK_CELLS:
        return False
    img = backend.grab(client)
    patches = [img[y0:y0 + cell_h, x0:x0 + cell_w] for x0, y0 in cells]
    patches = [p for p in patches if p.shape[0] == cell_h and p.shape[1] == cell_w]
    if len(patches) < MIN_BLANK_CELLS:
        return False
    return bool(capture_mod.looks_blank(np.ascontiguousarray(np.concatenate(patches, axis=0))))


def _target_issues(profile: Profile, backend: Backend, info: WindowInfo, issues: list[PreflightIssue]) -> None:
    exe = info.exe_name
    if exe and exe.casefold() in FORBIDDEN_TARGET_EXES:
        _issue(issues, IssueLevel.ERROR, "target_forbidden", msg.pf_forbidden(exe), "", "pick_window")
        return
    try:
        own = backend.is_own_window(info.hwnd) or (info.pid and info.pid == backend.own_pid())
    except Exception:  # noqa: BLE001
        own = False
    if own:
        _issue(issues, IssueLevel.ERROR, "target_is_self", msg.pf_target_is_self(), "", "pick_window")
        return
    try:
        permission = str(backend.input_permission(info.hwnd))
    except Exception:  # noqa: BLE001 - treat an unreadable token as unknown
        permission = "unknown"
    if permission == "blocked_elevated":
        if _safe_bool(backend.can_elevate):
            _issue(issues, IssueLevel.ERROR, "elevated", msg.pf_target_elevated(), "", "restart_admin")
        else:
            _issue(issues, IssueLevel.ERROR, "elevated", msg.pf_target_elevated_standard_user(), "", "")
    elif permission == "unknown":
        _issue(issues, IssueLevel.WARNING, "elevation_unknown", msg.pf_elevation_unknown())
    minimized = _safe_bool(lambda: backend.is_minimized(info.hwnd)) or info.minimized
    if minimized:
        _issue(issues, IssueLevel.INFO, "target_minimized", msg.pf_target_minimized())
        return
    try:
        client = backend.client_rect(info.hwnd)
    except OSError:
        return
    geometry = _recorded_geometry(profile)
    if geometry and client[2] > 0 and client[3] > 0:
        sizes = Counter((g.ref_w, g.ref_h) for g in geometry)
        if (client[2], client[3]) not in sizes:
            (rw, rh), _n = sizes.most_common(1)[0]
            ratio = profile.coord_mode is not CoordMode.OFFSET
            _issue(issues, IssueLevel.WARNING, "size_changed",
                   msg.pf_size_changed(f"{rw}×{rh}", f"{client[2]}×{client[3]}", ratio), "", "realign")
        try:
            dpi = int(backend.window_dpi(info.hwnd)) or 96
        except Exception:  # noqa: BLE001
            dpi = 96
        dpis = Counter(g.ref_dpi for g in geometry)
        if dpi not in dpis:
            ref, _n = dpis.most_common(1)[0]
            _issue(issues, IssueLevel.WARNING, "dpi_changed",
                   msg.pf_dpi_changed(round(ref * 100 / 96), round(dpi * 100 / 96)), "", "realign")
    try:
        if client[2] > 0 and client[3] > 0 and _blank_check(backend, info, client):
            _issue(issues, IssueLevel.WARNING, "capture_blank", msg.capture_blank())
    except Exception as exc:  # noqa: BLE001 - a failed probe is not a blank capture
        log.debug("blank check skipped: %s", exc)


def _safe_bool(fn: Any) -> bool:
    try:
        return bool(fn())
    except Exception:  # noqa: BLE001
        return False


def run_preflight(profile: Profile, settings: Settings, *, code_count: int, ocr_state: str,
                  target_hwnd: int = 0, backend: Backend | None = None,
                  unassigned_count: int = 0, ocr_error: str = "", daily_cap_left: int = -1,
                  daily_cap_shortened: bool = False) -> PreflightReport:
    """Validate the profile (errors, first three warnings), check the target rules (forbidden
    exe, browser title keyword), find the target (``target_hwnd`` first when still alive),
    check elevation/UIPI, client size and DPI vs recorded ones, OCR availability, blank capture
    (only when the target is not minimized; AutoPress's own windows are ignored, never sampled),
    codes (``unassigned_count`` = queued codes without a game), tested state, interval, and add
    the ``estimate`` line. Every key of SPEC 7.2. Sends no input. ``backend`` None -> a
    RealBackend without OCR.

    G4 additions: ``ocr_error`` (OcrService.error, shown in ``ocr_failed``), ``daily_cap_left``
    (attempts left today, -1 = no cap) and ``daily_cap_shortened`` (the plan was cut by the cap)
    for the ``daily_cap`` issue."""
    own_backend = backend is None
    if backend is None:
        from .backend import RealBackend

        backend = RealBackend(None)
    issues: list[PreflightIssue] = []
    report = PreflightReport(issues=issues, code_count=code_count, ocr_needed=profile.uses_ocr())
    try:
        _profile_issues(profile, issues)
        t = profile.target
        if t.is_empty():
            _issue(issues, IssueLevel.ERROR, "target_not_set", msg.pf_target_not_set(), "", "pick_window")
        elif t.is_forbidden():
            _issue(issues, IssueLevel.ERROR, "target_forbidden", msg.pf_forbidden(t.exe), "", "pick_window")
        elif t.needs_title():
            _issue(issues, IssueLevel.ERROR, "target_title_required", msg.pf_title_required(), "", "pick_window")
        elif t.exe_unknown():  # gate G-03: would match a window of any program
            _issue(issues, IssueLevel.ERROR, "target_exe_unknown", msg.pf_target_exe_unknown(), "", "pick_window")
        else:
            try:
                info = _find_target(profile, backend, target_hwnd, issues)
            except Exception as exc:  # noqa: BLE001 - window enumeration failed: report as not found
                log.warning("target lookup failed: %s", exc)
                info = None
                _issue(issues, IssueLevel.ERROR, "target_not_found", msg.target_not_found(t.describe()), "",
                       "pick_window")
            if info is not None:
                report.target = info
                _target_issues(profile, backend, info, issues)
        if report.ocr_needed:
            state = (ocr_state or "").lower()
            if state == "failed":
                _issue(issues, IssueLevel.ERROR, "ocr_failed", msg.ocr_failed(ocr_error or "?"))
            elif state == "disabled":
                _issue(issues, IssueLevel.ERROR, "ocr_failed", msg.pf_ocr_disabled())
            elif state in ("loading", "not_started"):
                _issue(issues, IssueLevel.INFO, "ocr_loading", msg.pf_ocr_loading(), "", "wait_ocr")
        cap_reached = daily_cap_left == 0 and settings.daily_cap > 0
        if code_count <= 0 and not (cap_reached and daily_cap_shortened):
            _issue(issues, IssueLevel.ERROR, "no_codes", msg.pf_no_codes())
        if unassigned_count > 0:
            _issue(issues, IssueLevel.INFO, "unassigned_codes", msg.pf_unassigned(unassigned_count), "",
                   "assign_codes")
        if settings.daily_cap > 0 and daily_cap_left >= 0:
            if daily_cap_left == 0:
                _issue(issues, IssueLevel.ERROR, "daily_cap", msg.pf_daily_cap_reached(settings.daily_cap))
            elif daily_cap_shortened:
                _issue(issues, IssueLevel.INFO, "daily_cap", msg.pf_daily_cap_shortened(code_count))
        if profile.enabled_steps() and not profile.has_result_check():
            _issue(issues, IssueLevel.WARNING, "no_result_check", msg.pf_no_result_check(), "", "open_profile")
        if any(isinstance(s.params, TypeCodeParams) and s.params.verify_region is None
               for _i, s in profile.enabled_steps()):
            _issue(issues, IssueLevel.INFO, "no_verify", msg.pf_no_verify(), "", "open_profile")
        if not profile.last_test_ok_at:
            _issue(issues, IssueLevel.WARNING, "untested_profile", msg.pf_untested(), "", "test_one")
        pol = profile.policy
        if min(pol.interval_min_s, pol.interval_max_s) < 2:
            _issue(issues, IssueLevel.WARNING, "fast_interval", msg.pf_fast_interval(min(pol.interval_min_s,
                                                                                         pol.interval_max_s)),
                   "", "open_profile")
        if code_count > 0:
            lo, hi = min(pol.interval_min_s, pol.interval_max_s), max(pol.interval_min_s, pol.interval_max_s)
            _issue(issues, IssueLevel.INFO, "estimate",
                   msg.pf_estimate(code_count, lo, hi, per_code_seconds(profile) * code_count))
    finally:
        if own_backend:
            try:
                backend.close()
            except Exception:  # noqa: BLE001
                pass
    return report


__all__ = ["per_code_seconds", "run_preflight"]
