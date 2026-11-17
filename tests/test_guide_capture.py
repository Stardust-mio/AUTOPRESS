"""tools/guide_capture.py (screenshots for the README and the user guide) and the demo state of
tests/fakes.py that every screen is built from. The capture itself needs the real ``windows``
platform (real fonts), so one screen is rendered in a child process without QT_QPA_PLATFORM;
everything else runs offscreen here."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

from autopress.models import CodeStatus, PreviewKind, TargetMatch
from tests.fakes import DEMO_ROWS, demo_context, demo_profile
from tools import guide_capture as gc

ROOT = Path(__file__).resolve().parent.parent


def _opts(theme: str = "dark", scale: float = 1.0) -> argparse.Namespace:
    return argparse.Namespace(theme=theme, scale=scale, lang="zh-TW", geometry=False)


# ----------------------------------------------------------------------------- the tool


def test_every_screen_has_a_unique_name_and_a_description() -> None:
    names = [s.name for s in gc.SCREENS]
    assert len(names) == len(set(names)) and len(names) >= 30
    assert all(s.about.strip() and callable(s.build) for s in gc.SCREENS)
    for expected in ("main", "codes", "history", "evidence", "run_running", "minibar", "marks", "settings"):
        assert expected in names


def test_list_option_prints_every_screen(capsys: pytest.CaptureFixture[str]) -> None:
    assert gc.main(["--list"]) == 0
    out = capsys.readouterr().out
    assert all(s.name in out for s in gc.SCREENS)


def test_unknown_screen_names_are_refused() -> None:
    with pytest.raises(SystemExit):
        gc.main(["somewhere", "--only", "main,no_such_screen"])


def test_demo_desktop_replaces_every_window_lookup(qapp: object) -> None:
    from autopress.win32 import dpi, elevation, windows

    world = gc.DemoWorld()
    undo = gc.install_demo_environment(world)
    try:
        assert [w.hwnd for w in windows.list_windows()] == [gc.HWND_BROWSER, gc.HWND_GAME, gc.HWND_FILES,
                                                             gc.HWND_NOTES]
        target = demo_profile().target
        found = windows.find_window(target)
        assert found is not None and found.hwnd == gc.HWND_BROWSER and found.title == gc.browser_title()
        assert windows.find_windows(TargetMatch(exe="nothing.exe")) == []
        assert windows.window_info(0xDEAD) is None and windows.client_rect(gc.HWND_BROWSER) == gc.CLIENT
        with pytest.raises(OSError):
            windows.client_rect(0xDEAD)
        assert windows.window_at(100, 100) == gc.HWND_BROWSER and windows.foreground_window() == 0
        assert str(elevation.input_permission(gc.HWND_BROWSER)) == "ok"
        assert str(elevation.input_permission(gc.HWND_GAME)) == "blocked_elevated"
        assert [m.rect for m in dpi.monitors()] == [(0, 0, gc.SCREEN_W, gc.SCREEN_H)]
        # the capturing process's own elevation never reaches a picture (repair round 1)
        assert elevation.is_elevated() is False and elevation.can_elevate() is True
        world.windows = [w for w in world.windows if w.hwnd != gc.HWND_BROWSER]  # the page is closed
        assert windows.find_window(target) is None
    finally:
        undo()
    assert windows.find_window.__name__ == "find_window" and dpi.monitors.__name__ == "monitors"
    assert elevation.is_elevated.__name__ == "is_elevated" and elevation.can_elevate.__name__ == "can_elevate"


def test_preflight_and_preview_run_against_the_demo_desktop(qapp: object) -> None:
    from autopress.runner.preview import preview_profile

    world = gc.DemoWorld()
    undo = gc.install_demo_environment(world)
    st = None
    try:
        st = gc.Stage(_opts(), world)
        plan = st.ctx.session.build_plan(st.profile, st.ctx.settings)
        keys = [i.key for i in st.ctx.session.preflight(plan).issues]  # the live provider
        # the demo profile passed a test before its history (repair round 1: no "never tested" warning
        # next to earlier successes)
        assert "estimate" in keys and "untested_profile" not in keys
        # the web template's step names: the wizard says what to click, not the step type
        names = {s.type.value: s.display_title() for s in st.profile.steps}
        assert names["click_point"] == "點一下序號輸入框" and names["ocr_check"] == "框出結果訊息的範圍"
        assert st.profile.last_test_ok_at
        assert not {"target_not_found", "capture_blank", "size_changed", "elevation_unknown"} & set(keys)
        world.windows = [w for w in world.windows if w.hwnd != gc.HWND_BROWSER]
        assert "target_not_found" in [i.key for i in st.ctx.session.preflight(plan).issues]
        world.reset()
        marks = preview_profile(st.profile, gc.HWND_BROWSER, backend=gc.DemoBackend(world, st.page, 1.5))
        assert marks and all(m.ok for m in marks)
        point = next(m for m in marks if m.kind is PreviewKind.POINT)
        x, y = st.page.layout.input_center
        assert abs(point.rect[0] - x * 1.5) <= 2 and abs(point.rect[1] - y * 1.5) <= 2  # on the drawn code box
    finally:
        undo()
        if st is not None:
            shutil.rmtree(st.home, ignore_errors=True)


def test_privacy_check_finds_private_text_without_echoing_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USERPROFILE", "C:\\Users\\SomeOne")
    monkeypatch.setenv("COMPUTERNAME", "DESK-4711")
    needles = gc.private_needles(["D:\\Shots\\ap-guide-1"])
    found = gc.privacy_problems(["資料夾 C:/Users/SomeOne/AppData/Roaming/AutoPress", "AutoPress on desk-4711"],
                                needles)
    assert found == ["profile folder", "computer name"]
    assert gc.privacy_problems(["data in d:/shots/AP-GUIDE-1/evidence"], needles) == ["data folder"]
    assert gc.privacy_problems(["Restart as administrator", "C:/Program Files/App/app.exe", "DESK-47110"],
                               needles) == []


def test_scrub_shows_a_demo_data_folder(qapp: object, tmp_path: Path) -> None:
    from PyQt6.QtWidgets import QLabel, QWidget

    top = QWidget()
    lb = QLabel(str(tmp_path), top)
    lb.setToolTip(f"{tmp_path}\\evidence")
    gc.scrub_data_folder(top, tmp_path)
    assert lb.text() == gc.DEMO_DATA_DIR and lb.toolTip() == gc.DEMO_DATA_DIR + "\\evidence"


def test_evidence_crops_match_the_history_records(qapp: object) -> None:
    from PIL import Image

    world = gc.DemoWorld()
    st = gc.Stage(_opts(), world)
    try:
        st.attach_evidence()
        recs = st.ctx.history.records()
        with_check = [r for r in recs if r.result is not None]
        assert with_check and all(r.evidence_path for r in with_check)
        assert all(not r.evidence_path for r in recs if r.result is None)  # no result check, no crop
        img = Image.open(st.home / with_check[0].evidence_path)
        assert img.size == st.page.layout.result_region[2:]  # what the runner saves: the result region
    finally:
        shutil.rmtree(st.home, ignore_errors=True)


@pytest.mark.slow
@pytest.mark.skipif(sys.platform != "win32", reason="the capture needs the Qt windows platform (real fonts)")
def test_one_screen_is_captured_in_a_child_process(tmp_path: Path) -> None:
    from PIL import Image, ImageStat

    out = tmp_path / "shots"
    env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}
    env["PYTHONIOENCODING"] = "utf-8"
    res = subprocess.run([sys.executable, str(ROOT / "tools" / "guide_capture.py"), str(out), "--theme", "light",
                          "--only", "wizard_close", "--geometry"], capture_output=True, text=True, encoding="utf-8",
                         errors="replace", env=env, timeout=180, cwd=str(ROOT))
    if res.returncode != 0 and "qt.qpa" in res.stderr:
        pytest.skip(f"no Qt windows platform in this session: {res.stderr[-300:]}")
    assert res.returncode == 0, res.stdout + res.stderr
    png = out / "wizard_close_light_100.png"
    assert sorted(p.name for p in out.iterdir()) == ["report_light_100.txt", "wizard_close_light_100.json",
                                                      png.name]  # nothing else is written
    img = Image.open(png).convert("RGB")
    assert img.width > 200 and img.height > 100 and max(ImageStat.Stat(img).stddev) > 5
    assert "wizard_close: ok" in (out / "report_light_100.txt").read_text(encoding="utf-8")
    data = json.loads((out / "wizard_close_light_100.json").read_text(encoding="utf-8"))
    assert data["png_size"] == [img.width, img.height] and data["screen"] == "wizard_close"
    widgets = data["widgets"]
    assert any(w["class"] == "QPushButton" and w["text"] for w in widgets)
    for w in widgets:
        x, y, ww, hh = w["rect"]
        assert x >= 0 and y >= 0 and ww > 0 and hh > 0 and x + ww <= img.width and y + hh <= img.height


# ----------------------------------------------------------------------------- the demo state


def test_demo_state_is_one_the_app_can_show_at_rest(isolated_home: Path) -> None:
    ctx = demo_context(isolated_home, now=datetime(2026, 11, 16, 20, 36, 12))
    items = ctx.queue.items()
    assert not {CodeStatus.RUNNING, CodeStatus.COOLDOWN} & {i.status for i in items}  # a run's end clears them
    assert all(not i.message for i in items if i.status is CodeStatus.REVIEW)  # the queue keeps no OCR note
    recs = ctx.history.records()
    assert len(recs) == sum(1 for row in DEMO_ROWS if row[4] not in (CodeStatus.PENDING, CodeStatus.REVIEW))
    assert all(r.started_at and r.finished_at and r.started_at < r.finished_at for r in recs)
    assert len({r.finished_at for r in recs}) == len(recs)  # one time per attempt
    newest = ctx.history.query()[0]
    assert newest.status is CodeStatus.SUCCESS and newest.finished_at.startswith("2026-11-16T20:36:12")
    assert len(ctx.queue.runnable(game_key=ctx.active_profile().game_key())) == 4


def test_demo_texts_follow_the_ui_language(isolated_home: Path) -> None:
    from autopress import i18n

    i18n.set_language("en")
    ctx = demo_context(isolated_home)
    p = ctx.active_profile()
    assert (p.name, p.game, p.target.title) == ("Demo: web redeem", "Demo Game", "Redeem")
    messages = {i.message for i in ctx.queue.items() if i.message} | {r.message for r in ctx.history.records()}
    assert messages and all(m.isascii() for m in messages)


def test_fake_session_replays_a_run_in_the_engine_order(demo_ctx: object, qtbot: object) -> None:
    ctx = demo_ctx
    s = ctx.session
    plan = s.build_plan(ctx.active_profile(), ctx.settings)
    s.start(plan)
    first, second = plan.items[0], plan.items[1]
    s.begin_code(first.code_id, 0)
    assert ctx.queue.get(first.code_id).status is CodeStatus.RUNNING
    rec = s.finish_code(first.code_id, CodeStatus.SUCCESS, "ok", started_at="2026-11-16T20:41:03+08:00",
                        finished_at="2026-11-16T20:41:08+08:00")
    item = ctx.queue.get(first.code_id)
    assert item.status is CodeStatus.SUCCESS and item.attempts == 1 and rec.profile_name == plan.profile.name
    assert (rec.started_at, rec.finished_at) == ("2026-11-16T20:41:03+08:00", "2026-11-16T20:41:08+08:00")
    s.begin_code(second.code_id, 1)
    states: list[tuple[str, str]] = []
    s.state_changed.connect(lambda st, why: states.append((st, why)))
    with qtbot.waitSignal(s.finished):  # type: ignore[attr-defined]
        summary = s.finish_run(counts={CodeStatus.SUCCESS: 1})
    assert ctx.queue.get(second.code_id).status is CodeStatus.REVIEW  # interrupted mid-code
    assert states[-1] == ("finished", "completed") and summary.done == 1 and not s.is_active()
