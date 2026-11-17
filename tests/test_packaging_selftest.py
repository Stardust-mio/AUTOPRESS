# OWNED BY G8
"""autopress.selftest (``AutoPress.exe --selftest report.json``) and the optional smoke tests of
a finished build (SPEC 8.2 G8 row: "build smoke (slow, optional) incl. selftest from a path with
Chinese characters"; 10.1).

In-process runs use pytest's offscreen QApplication (the dpi check is skipped there: only the
windows platform sets per-monitor-v2). The slow test runs the whole self-test, real OCR included,
in a child process on the windows platform from folders with Chinese names. Nothing here shows a
window, captures the screen or sends input.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import numpy as np
import pytest

from autopress import selftest

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
DIST_EXE = DIST / "AutoPress" / "AutoPress.exe"
FAST_CHECKS = ["qt", "qt_extras", "dpi", "modules", "resources", "templates", "ocr_models", "data_dir"]


def _report(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_interface_is_run_with_a_report_path() -> None:
    import inspect

    params = list(inspect.signature(selftest.run).parameters.values())
    assert params[0].name == "report_path" and params[0].default is inspect.Parameter.empty
    assert all(p.default is not inspect.Parameter.empty for p in params[1:])
    assert not getattr(selftest, "__stub__", False)
    assert selftest.CHECK_NAMES[0] == "qt"  # the QApplication comes before anything else


def test_fast_checks_pass_offscreen_and_write_a_report(qapp: object, tmp_path: Path, isolated_home: Path) -> None:
    report = tmp_path / "報告 資料夾" / "selftest.json"
    assert selftest.run(str(report), checks=FAST_CHECKS) == 0
    data = _report(report)
    assert data["ok"] is True and data["app"] == "AutoPress" and data["frozen"] is False
    assert data["platform"] == "offscreen" and data["qt"] and data["python"] == "3.12.10"
    names = [c["name"] for c in data["checks"]]
    assert names == FAST_CHECKS
    by = {c["name"]: c for c in data["checks"]}
    assert by["dpi"]["ok"] and not by["dpi"]["required"] and by["dpi"]["detail"].startswith("skipped")
    assert by["templates"]["detail"] == "web_generic, hoyoverse_web, game_dialog"
    assert str(isolated_home) in by["data_dir"]["detail"]
    assert int(by["modules"]["detail"].split()[0]) >= len(selftest.SPEC_MODULES)
    for c in data["checks"]:
        assert set(c) == {"name", "ok", "required", "detail", "seconds"}


def test_a_failing_check_gives_exit_code_1_and_the_other_checks_still_run(
        qapp: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> str:
        raise RuntimeError("missing resource icon.ico")

    monkeypatch.setattr(selftest, "_check_resources", broken)
    report = tmp_path / "selftest.json"
    assert selftest.run(str(report), checks=["qt", "resources", "templates"]) == 1
    data = _report(report)
    assert data["ok"] is False
    by = {c["name"]: c for c in data["checks"]}
    assert not by["resources"]["ok"] and "missing resource icon.ico" in by["resources"]["detail"]
    assert by["templates"]["ok"] and by["qt"]["ok"]


def test_a_failing_optional_check_does_not_fail_the_run(
        qapp: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def no_translation() -> str:
        raise RuntimeError("qtbase_zh_TW.qm not found")

    monkeypatch.setattr(selftest, "_check_qt_extras", no_translation)
    report = tmp_path / "selftest.json"
    assert selftest.run(str(report), checks=["qt", "qt_extras"]) == 0
    extras = _report(report)["checks"][1]
    assert extras["ok"] is False and extras["required"] is False


def test_an_unwritable_report_path_gives_exit_code_1(qapp: object, tmp_path: Path) -> None:
    folder = tmp_path / "a folder, not a file"
    folder.mkdir()
    assert selftest.run(str(folder), checks=["qt"]) == 1


def test_a_missing_module_fails_the_modules_check(
        qapp: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(selftest, "SPEC_MODULES", selftest.SPEC_MODULES + ("autopress.not_bundled",))
    report = tmp_path / "selftest.json"
    assert selftest.run(str(report), checks=["modules"]) == 1
    assert "autopress.not_bundled" in _report(report)["checks"][0]["detail"]


@pytest.mark.parametrize(("texts", "ok"), [
    (["兌換碼：AB12-CD34", "兌換", "取消"], True),
    (["兌換碼:AB12CD34", "兑换"], True),  # separators / simplified glyph are fine
    (["兌換碼：AB12-CD34 兌換"], False),  # the button must be its own line (click_text EXACT)
    (["兌換", "取消"], False),
    ([], False),
])
def test_ocr_check_needs_the_code_and_a_separate_button(
        texts: list[str], ok: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(selftest, "_ocr_texts", lambda image: (texts, "fake engine"))
    if ok:
        assert "fake engine" in selftest._check_ocr()
    else:
        with pytest.raises(RuntimeError, match="OCR did not read"):
            selftest._check_ocr()


def test_render_test_image_is_a_dialog_like_bgr_image() -> None:
    img = selftest.render_test_image()
    assert img.shape == (320, 720, 3) and img.dtype == np.uint8 and img.flags["C_CONTIGUOUS"]
    b, g, r = (int(v) for v in img[200, 60])  # inside the blue 「兌換」 button
    assert b > 200 and r < 80
    assert img[96, 48:400].std() > 20  # the text line is drawn


@pytest.mark.slow
def test_full_selftest_in_a_child_process_from_chinese_paths(clean_env: dict, python_exe: str, tmp_path: Path) -> None:
    """Real QApplication on the windows platform, DPI awareness, real OCR of the test image."""
    report = tmp_path / "中文 報告" / "selftest.json"
    home = tmp_path / "使用者 資料"
    env = dict(clean_env, AUTOPRESS_HOME=str(home))
    code = "import sys; from autopress import selftest; sys.exit(selftest.run(sys.argv[1]))"
    res = subprocess.run([python_exe, "-c", code, str(report)], cwd=ROOT, env=env, capture_output=True,
                         text=True, encoding="utf-8", errors="replace", timeout=300)
    assert report.is_file(), res.stderr
    data = _report(report)
    failed = [c for c in data["checks"] if not c["ok"]]
    assert res.returncode == 0 and data["ok"], failed
    by = {c["name"]: c for c in data["checks"]}
    assert data["platform"] == "windows"
    assert by["dpi"]["required"] and by["dpi"]["detail"].startswith("per-monitor-v2")
    assert "AB12-CD34" in by["ocr"]["detail"]
    assert str(home) in by["data_dir"]["detail"]


# ============================================================================= finished build (optional)


@pytest.mark.slow
@pytest.mark.skipif(not DIST_EXE.is_file(), reason="no build in dist/AutoPress (build.ps1 makes one)")
def test_build_smoke_selftest_from_a_chinese_path(tmp_path: Path, clean_env: dict) -> None:
    target = tmp_path / "中文 路徑" / "AutoPress"
    shutil.copytree(DIST_EXE.parent, target)
    report = tmp_path / "報告" / "selftest.json"
    env = dict(clean_env, AUTOPRESS_HOME=str(tmp_path / "資料"))
    res = subprocess.run([str(target / "AutoPress.exe"), "--selftest", str(report)], env=env, timeout=300)
    data = _report(report)
    assert res.returncode == 0 and data["ok"], [c for c in data["checks"] if not c["ok"]]
    assert data["frozen"] is True
    assert not any("still stubs" in c["detail"] for c in data["checks"])


@pytest.mark.skipif(not list(DIST.glob("AutoPress-*-win64.zip")), reason="no release zip in dist/")
def test_release_zip_layout() -> None:
    zpath = sorted(DIST.glob("AutoPress-*-win64.zip"))[-1]
    version = zpath.name[len("AutoPress-"): -len("-win64.zip")]
    names = zipfile.ZipFile(zpath).namelist()
    top = {n.split("/")[0] for n in names}
    assert top == {f"AutoPress-{version}", "請先解壓縮再執行.txt"}
    for need in ("AutoPress.exe", "README.md", "LICENSE", "THIRD-PARTY-NOTICES.md", "licenses/PyQt6-LICENSE.txt"):
        assert f"AutoPress-{version}/{need}" in names, need
    assert not any("portable.txt" in n for n in names)  # SPEC 5.1
    assert not any("opencv_videoio_ffmpeg" in n for n in names)
    assert sys.platform == "win32"
