"""End-to-end runs against tools/fake_redeem_app.py with REAL input, screen capture and OCR (G4).

Marked ``realinput`` (and ``slow``): skipped unless AUTOPRESS_REALINPUT=1. They show the fake app
on the desktop, focus it, type into it, click it and read it with the real OCR engine. Run them
alone, with nobody touching mouse or keyboard (physical input pauses the run - the tests then
stop the run and fail with the pause reason):

    AUTOPRESS_REALINPUT=1 .venv/Scripts/python.exe -m pytest -q -m realinput tests/test_e2e_runner.py

Codes are invented test strings. Consecutive codes are ordered so that two results in a row never
show the same message, except where that case is the subject (only_new_text, SPEC 5.3 / 11.12).
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

import pytest

from autopress.models import (
    BetweenSegments,
    ClickPointParams,
    ClickTextParams,
    CodeStatus,
    IssueLevel,
    OcrCheckParams,
    OcrSettings,
    Profile,
    RunSummary,
    Settings,
    SplitMode,
    StepType,
    StopReason,
    TargetMatch,
    TimeoutAction,
    TitleMatch,
    TypeCodeParams,
    UnknownAction,
    make_step,
    record_point,
    record_region,
)
from tests.fakes import FakeCodeQueue, FakeHistoryStore, skip_if_stub

pytestmark = [pytest.mark.realinput, pytest.mark.slow]

APP = Path(__file__).resolve().parent.parent / "tools" / "fake_redeem_app.py"
REQUIRED = ("autopress.capture", "autopress.ocr.engine", "autopress.ocr.service", "autopress.ocr.textfind",
            "autopress.ocr.imageio", "autopress.codes.normalize", "autopress.win32.input", "autopress.win32.windows",
            "autopress.win32.elevation", "autopress.win32.power", "autopress.win32.dpi", "autopress.win32.keys",
            "autopress.win32.clipboard")


class FakeApp:
    """tools/fake_redeem_app.py in its own process (windows platform via clean_env)."""

    def __init__(self, folder: Path, python_exe: str, env: dict[str, str], *args: str) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        self.title = f"AutoPress E2E {uuid.uuid4().hex[:8]}"
        self.info_path, self.log_path = folder / "info.json", folder / "events.jsonl"
        self.proc = subprocess.Popen([python_exe, str(APP), "--title", self.title, "--info", str(self.info_path),
                                      "--log", str(self.log_path), "--pos", "240,200", *args], env=env)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and not self.info_path.exists():
            time.sleep(0.1)
        assert self.info_path.exists(), "fake app did not start"
        time.sleep(1.0)  # placement settles (the info file is rewritten after moves)
        self.info: dict[str, Any] = json.loads(self.info_path.read_text(encoding="utf-8"))

    def events(self, kind: str | None = None) -> list[dict[str, Any]]:
        if not self.log_path.exists():
            return []
        out = [json.loads(line) for line in self.log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return [e for e in out if kind is None or e["ev"] == kind]

    def close(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


class E2E:
    def __init__(self, qtbot: Any, tmp_path: Path, python_exe: str, env: dict[str, str]) -> None:
        from autopress.ocr.service import OcrService
        from autopress.runner.engine import RunSession

        self.qtbot, self.tmp_path, self.python_exe, self.env = qtbot, tmp_path, python_exe, env
        self.ocr = OcrService(OcrSettings())
        self.ocr.start()
        qtbot.waitUntil(lambda: str(getattr(self.ocr.state, "value", self.ocr.state)) == "ready", timeout=120_000)
        self.queue, self.history = FakeCodeQueue(), FakeHistoryStore()
        self.session = RunSession(self.queue, self.history, self.ocr)  # RealBackend
        self.pauses: list[str] = []
        self.session.state_changed.connect(self._on_state)
        self.apps: list[FakeApp] = []

    def _on_state(self, state: str, reason: str) -> None:
        if state == "paused":  # nobody is there to resume: stop and let the test report the reason
            self.pauses.append(reason)
            self.session.stop()

    def app(self, *args: str) -> FakeApp:
        a = FakeApp(self.tmp_path / f"app{len(self.apps)}", self.python_exe, self.env, *args)
        self.apps.append(a)
        return a

    def run(self, profile: Profile, codes: list[str], timeout_ms: int = 180_000) -> tuple[RunSummary, list[str]]:
        res = self.queue.add_codes(codes, game_key=profile.game_key(), game=profile.game)
        assert len(res.added) == len(codes)
        settings = Settings()
        plan = self.session.build_plan(profile, settings, code_ids=res.added)
        report = self.session.preflight(plan)
        errors = [(i.key, i.message) for i in report.issues if i.level is IssueLevel.ERROR]
        assert not errors, errors
        with self.qtbot.waitSignal(self.session.finished, timeout=timeout_ms) as blocker:
            self.session.start(plan)
        assert not self.pauses, f"the run paused: {self.pauses}"
        return blocker.args[0], res.added

    def status(self, code_id: str) -> CodeStatus:
        item = self.queue.get(code_id)
        assert item is not None
        return item.status

    def close(self) -> None:
        self.session.shutdown(3.0)
        for a in self.apps:
            a.close()
        self.ocr.shutdown()


@pytest.fixture
def e2e(qtbot: Any, qapp: Any, tmp_path: Path, python_exe: str, clean_env: dict[str, str]) -> E2E:
    skip_if_stub(*REQUIRED)
    env = E2E(qtbot, tmp_path, python_exe, clean_env)
    yield env
    env.close()


def build_profile(app: FakeApp, *, split: SplitMode = SplitMode.NONE, between: BetweenSegments = BetweenSegments.NONE,
                  group_sizes: tuple[int, ...] = (), popup: bool = False) -> Profile:
    from autopress.win32 import windows

    hwnd = int(app.info["hwnd"])
    client = windows.client_rect(hwnd)
    dpi = windows.window_dpi(hwnd)

    def centre(rect: list[int]) -> Any:
        x, y, w, h = rect
        return record_point(client, x + w // 2, y + h // 2, dpi=dpi)

    p = Profile(name="E2E", game="E2E 測試遊戲",
                target=TargetMatch(exe="", title=app.title, title_mode=TitleMatch.EXACT, allow_same_process=popup))
    click_in = make_step(StepType.CLICK_POINT)
    assert isinstance(click_in.params, ClickPointParams)
    click_in.params.point, click_in.params.after_ms = centre(app.info["inputs"][0]), 150
    tc = make_step(StepType.TYPE_CODE)
    assert isinstance(tc.params, TypeCodeParams)
    tc.params.key_delay_ms, tc.params.after_ms = 15, 100
    tc.params.split, tc.params.between, tc.params.group_sizes = split, between, list(group_sizes)
    submit = make_step(StepType.CLICK_POINT)
    assert isinstance(submit.params, ClickPointParams)
    submit.params.point, submit.params.after_ms = centre(app.info["redeem_button"]), 150
    oc = make_step(StepType.OCR_CHECK)
    assert isinstance(oc.params, OcrCheckParams)
    if popup:  # the dialog opens over the middle of the window: read the whole client area
        oc.params.region = record_region(client, *client, dpi=dpi)
    else:
        x, y, w, h = app.info["result_rect"]
        oc.params.region = record_region(client, x - 6, y - 6, w + 12, h + 12, dpi=dpi)
    oc.params.initial_delay_ms, oc.params.timeout_ms, oc.params.poll_ms = 400, 5000, 300
    p.steps = [click_in, tc, submit, oc]
    if popup:
        close = make_step(StepType.CLICK_TEXT)
        assert isinstance(close.params, ClickTextParams)
        close.params.text, close.params.on_not_found = "確定|OK", TimeoutAction.CONTINUE
        close.params.timeout_ms, close.params.poll_ms, close.params.after_ms = 1500, 300, 300
        p.steps.append(close)
    pol = p.policy
    pol.interval_min_s, pol.interval_max_s = 1.0, 1.2
    pol.cooldown_s, pol.max_cooldowns = 10, 1
    pol.stop_after_failures, pol.pause_after_invalid = 0, 0
    pol.on_unknown = UnknownAction.CONTINUE
    return p


def test_five_codes_used_invalid_rate_limit(e2e: E2E) -> None:
    app = e2e.app("--valid", "AAAA-1111,BBBB-2222", "--used", "CCCC-3333", "--rate-limit", "3")
    profile = build_profile(app)
    codes = ["AAAA-1111", "CCCC-3333", "XXXX-0000", "BBBB-2222", "EXP-1234"]
    summary, ids = e2e.run(profile, codes)
    assert summary.stop_reason is StopReason.COMPLETED
    # the 4th submit within 10 s is rate-limited -> 10 s cool-down -> the same code again
    assert [e2e.status(i) for i in ids] == [CodeStatus.SUCCESS, CodeStatus.USED, CodeStatus.INVALID,
                                            CodeStatus.SUCCESS, CodeStatus.EXPIRED]
    assert [e["code"] for e in app.events("submit")] == ["AAAA-1111", "CCCC-3333", "XXXX-0000", "BBBB-2222",
                                                         "BBBB-2222", "EXP-1234"]
    assert [r.status for r in e2e.history.records() if r.code == "BBBB-2222"] == [CodeStatus.COOLDOWN,
                                                                                  CodeStatus.SUCCESS]
    assert all(r.evidence_path for r in e2e.history.records())


def test_three_boxes_and_unequal_groups(e2e: E2E) -> None:
    app = e2e.app("--boxes", "3", "--valid", "ABCDE-FGHIJ-KLMNO")
    summary, ids = e2e.run(build_profile(app, split=SplitMode.SEPARATOR, between=BetweenSegments.NONE),
                           ["ABCDE-FGHIJ-KLMNO", "ZZZZZ-YYYYY-XXXXX"])
    assert summary.stop_reason is StopReason.COMPLETED
    assert [e["boxes"] for e in app.events("submit")] == [["ABCDE", "FGHIJ", "KLMNO"], ["ZZZZZ", "YYYYY", "XXXXX"]]
    assert [e2e.status(i) for i in ids] == [CodeStatus.SUCCESS, CodeStatus.INVALID]
    app2 = e2e.app("--groups", "4,6,2", "--no-advance", "--valid", "ABCD-EFGHIJ-KL")
    profile2 = build_profile(app2, split=SplitMode.FIXED, between=BetweenSegments.TAB, group_sizes=(4, 6, 2))
    profile2.game = "E2E 第二個遊戲"
    summary2, ids2 = e2e.run(profile2, ["ABCD-EFGHIJ-KL", "WXYZ-123456-78"])
    assert summary2.stop_reason is StopReason.COMPLETED
    assert [e["boxes"] for e in app2.events("submit")] == [["ABCD", "EFGHIJ", "KL"], ["WXYZ", "123456", "78"]]
    assert [e2e.status(i) for i in ids2] == [CodeStatus.SUCCESS, CodeStatus.INVALID]


def test_later_boxes_holding_an_old_code_are_replaced(e2e: E2E) -> None:
    """Gate G-08: boxes 2..n still hold the previous code and the page's own focus() does not
    select them; type_code selects each later box before typing its segment."""
    app = e2e.app("--groups", "4,6,2", "--advance-no-select", "--prefill", "OLD1,OLDOLD,OL",
                  "--valid", "ABCD-EFGHIJ-KL")
    summary, ids = e2e.run(build_profile(app, split=SplitMode.SEPARATOR, between=BetweenSegments.NONE),
                           ["ABCD-EFGHIJ-KL"])
    assert summary.stop_reason is StopReason.COMPLETED
    assert [e["boxes"] for e in app.events("submit")] == [["ABCD", "EFGHIJ", "KL"]]
    assert [e2e.status(i) for i in ids] == [CodeStatus.SUCCESS]


def test_popup_dismissal_on_success(e2e: E2E) -> None:
    app = e2e.app("--popup", "dialog", "--popup-on", "success", "--valid", "AAAA-1111,BBBB-2222")
    summary, ids = e2e.run(build_profile(app, popup=True), ["AAAA-1111", "XXXX-0000", "BBBB-2222"])
    assert summary.stop_reason is StopReason.COMPLETED
    assert [e2e.status(i) for i in ids] == [CodeStatus.SUCCESS, CodeStatus.INVALID, CodeStatus.SUCCESS]
    assert len(app.events("popup_closed")) == 2  # click_text 確定 only when the dialog is there


def test_latency_with_persist_stale_and_identical_messages(e2e: E2E) -> None:
    from autopress.runner import messages as msg

    app = e2e.app("--latency-ms", "1500", "--persist", "--valid", "AAAA-1111")
    summary, ids = e2e.run(build_profile(app), ["XXXX-0000", "AAAA-1111", "YYYY-0000", "ZZZZ-0000"])
    assert summary.stop_reason is StopReason.COMPLETED
    # the stale 兌換碼無效 shown during the 1.5 s latency is in the baseline and ignored; the last code
    # shows the same message as the one before it -> UNKNOWN 「送出後結果區沒有變化」 (documented rule)
    assert [e2e.status(i) for i in ids] == [CodeStatus.INVALID, CodeStatus.SUCCESS, CodeStatus.INVALID,
                                            CodeStatus.REVIEW]
    assert e2e.queue.get(ids[3]).message == msg.no_change_after_submit()


def test_environment_notes() -> None:
    """Documentation check (always skipped with the module marker): the fake app script exists."""
    assert APP.is_file() and os.path.basename(APP) == "fake_redeem_app.py"
