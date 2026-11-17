"""Shared pytest setup for AutoPress (OWNED BY A1 - groups add fixtures in their own test files).

Environment, set before anything imports Qt or numpy:
* ``QT_QPA_PLATFORM=offscreen`` unless ``AUTOPRESS_REALINPUT=1`` or QT_QPA_PLATFORM is already
  set: GUI tests never open windows on the user's desktop. Screenshots and layout checks need
  the real ``windows`` platform: use ``tools/snap_widget.py`` (separate process).
* ``OPENBLAS_NUM_THREADS=1`` (numpy commit memory, docs/research/ocr.md 3.4).
* ``AUTOPRESS_HOME`` -> a throw-away folder for the session and a fresh ``tmp_path`` folder for
  every test: the real %APPDATA%/AutoPress is never touched.
* UI fallbacks: while G5's theme / icons / widgets / toast modules are still stubs,
  ``tests/ui_fallback.py`` patches them with plain-Qt stand-ins (no effect once G5 lands).

Markers (pytest.ini): ``realinput`` - skipped unless ``AUTOPRESS_REALINPUT=1``; such tests hold
a lock file so two agents never inject input at the same time; run them on their own:
``AUTOPRESS_REALINPUT=1 .venv/Scripts/python.exe -m pytest -q -m realinput``.
``slow`` - deselect with ``-m "not slow"``.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from pathlib import Path

REALINPUT = os.environ.get("AUTOPRESS_REALINPUT") == "1"
if not REALINPUT:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
_SESSION_HOME = tempfile.mkdtemp(prefix="autopress-tests-")
os.environ["AUTOPRESS_HOME"] = _SESSION_HOME

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from tests import ui_fallback  # noqa: E402

ui_fallback.install()

from autopress import i18n  # noqa: E402
from autopress.models import (  # noqa: E402
    ClickPointParams,
    ClickTextParams,
    ClientPoint,
    ClientRegion,
    CodeItem,
    CodeSource,
    CodeStatus,
    OcrCheckParams,
    Profile,
    StepType,
    TargetMatch,
    TitleMatch,
    TypeCodeParams,
    TypeTextParams,
    WaitTextParams,
    make_step,
    record_point,
    record_region,
)

LOCK_PATH = ROOT / ".pytest_cache" / "autopress-realinput.lock"


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    shutil.rmtree(_SESSION_HOME, ignore_errors=True)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if REALINPUT:
        return
    skip = pytest.mark.skip(reason="injects real input; set AUTOPRESS_REALINPUT=1 to run")
    for item in items:
        if "realinput" in item.keywords:
            item.add_marker(skip)


# ----------------------------------------------------------------------------- isolation


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fresh, empty AUTOPRESS_HOME (data folder) for every test."""
    home = tmp_path / "autopress-home"
    home.mkdir()
    monkeypatch.setenv("AUTOPRESS_HOME", str(home))
    return home


@pytest.fixture(autouse=True)
def _language_zh() -> Iterator[None]:
    """Every test starts in zh-TW (deterministic tr())."""
    i18n.set_language("zh-TW")
    yield
    i18n.set_language("zh-TW")


@pytest.fixture(autouse=True)
def _realinput_lock(request: pytest.FixtureRequest) -> Iterator[None]:
    """Machine-wide exclusive lock for tests marked ``realinput`` (waits up to 15 min)."""
    if request.node.get_closest_marker("realinput") is None:
        yield
        return
    import msvcrt

    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    fh = open(LOCK_PATH, "a+b")  # noqa: SIM115 - held for the whole test
    deadline = time.monotonic() + 900
    while True:
        try:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            break
        except OSError:
            if time.monotonic() > deadline:
                fh.close()
                pytest.fail("another agent holds the real-input lock for more than 15 minutes")
            time.sleep(1.0)
    try:
        yield
    finally:
        try:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            fh.close()


@pytest.fixture
def clean_env() -> dict[str, str]:
    """Environment for child processes (fake_redeem_app, exe tests): no QT_QPA_PLATFORM (so
    they get the real windows platform), UTF-8 stdio, the test's AUTOPRESS_HOME."""
    env = dict(os.environ)
    env.pop("QT_QPA_PLATFORM", None)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


@pytest.fixture
def python_exe() -> str:
    """The project venv interpreter running the tests (never the Anaconda python on PATH)."""
    return sys.executable


# ----------------------------------------------------------------------------- test data

FONT_DIR = Path("C:/Windows/Fonts")


@pytest.fixture
def text_image() -> Callable[..., object]:
    """Factory: render text lines to a BGR numpy image with a real Windows font.

    ``text_image("兌換碼：AB12-CD34", size=28, dark=True, width=None, height=None,
    font="msjh.ttc", padding=24)`` -> HxWx3 uint8 BGR. Lines are separated by "\\n".
    """
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    def make(text: str, size: int = 28, dark: bool = True, width: int | None = None,
             height: int | None = None, font: str = "msjh.ttc", padding: int = 24) -> np.ndarray:
        f = ImageFont.truetype(str(FONT_DIR / font), size)
        lines = text.split("\n")
        line_h = int(size * 1.6)
        w = width or max(int(f.getlength(ln)) for ln in lines) + 2 * padding
        h = height or line_h * len(lines) + 2 * padding
        bg, fg = ((24, 26, 36), (240, 240, 240)) if dark else ((245, 245, 245), (20, 20, 20))
        img = Image.new("RGB", (w, h), bg)
        draw = ImageDraw.Draw(img)
        for i, ln in enumerate(lines):
            draw.text((padding, padding + i * line_h + line_h // 2), ln, font=f, fill=fg, anchor="lm")
        return np.ascontiguousarray(np.asarray(img)[:, :, ::-1])

    return make


@pytest.fixture
def sample_profile() -> Profile:
    """A valid, fully set-up profile using every step type (client area 1280x720 at 96 DPI)."""
    client = (100, 50, 1280, 720)
    p = Profile(name="測試設定檔", game="測試遊戲",
                target=TargetMatch(exe="game.exe", title="測試遊戲", title_mode=TitleMatch.CONTAINS))
    for st in StepType:
        if st is StepType.UNKNOWN:
            continue
        p.steps.append(make_step(st))
    for s in p.steps:
        prm = s.params
        if isinstance(prm, ClickPointParams):
            prm.point = record_point(client, 740, 410)
        elif isinstance(prm, ClickTextParams):
            prm.text = "兌換|Redeem"
            prm.region = record_region(client, 400, 500, 600, 120)
        elif isinstance(prm, TypeCodeParams):
            prm.verify_region = None
        elif isinstance(prm, TypeTextParams):
            prm.text = "/redeem {code}"
        elif isinstance(prm, WaitTextParams):
            prm.text = "兌換結果"
            prm.region = record_region(client, 300, 200, 700, 300)
        elif isinstance(prm, OcrCheckParams):
            prm.region = record_region(client, 300, 200, 700, 300)
    assert isinstance(p.steps[1].params.point, ClientPoint)
    assert isinstance(p.steps[2].params.region, ClientRegion)
    return p


@pytest.fixture
def make_items() -> Callable[..., list[CodeItem]]:
    """Factory: ``make_items(5, status=CodeStatus.PENDING, source=CodeSource.PASTE)`` ->
    CodeItems with invented codes ``TESTA0001`` ... (never real codes)."""

    def make(n: int, status: CodeStatus = CodeStatus.PENDING, source: CodeSource = CodeSource.PASTE) -> list[CodeItem]:
        return [CodeItem(code=f"TEST{chr(65 + i % 26)}{i:04d}", raw=f"TEST{chr(65 + i % 26)}{i:04d}",
                         source=source, status=status) for i in range(n)]

    return make


@pytest.fixture
def demo_ctx(qapp: object, isolated_home: Path) -> object:
    """An AppContext built by tests/fakes.py: demo_context() (real G1 stores when implemented,
    fake OCR / session / hotkeys) inside the test's data folder."""
    from tests.fakes import demo_context

    return demo_context(isolated_home)
