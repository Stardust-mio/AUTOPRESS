# OWNED BY G8
"""Packaged-build self-test: ``AutoPress.exe --selftest report.json`` (also ``main.py``).

Checks without showing windows and without injecting input: bundled resources and templates
load; OCR model files exist and the engine reads a rendered test image ("兌換碼：AB12-CD34" and
"兌換" on a dialog-like image); a QApplication starts on the default platform; DPI awareness is
per-monitor-v2 after QApplication; the data folder is writable. Writes a JSON report and
returns 0 when every check passed, 1 otherwise. ui.app.main dispatches ``--selftest`` BEFORE it
creates a QApplication; run() uses ``QApplication.instance() or QApplication([...])`` (T31).
build.ps1 also runs it from a folder whose path contains Chinese characters (users' names often
do; PX-21).

Checks, in this order (the QApplication comes first, so nothing can set another DPI awareness
before Qt makes the process per-monitor-v2 aware - SPEC 2.1):

=========== ======== ==========================================================================
name        required what
=========== ======== ==========================================================================
qt          yes      QApplication on the default platform; QtSvg renders the logo (icons need it)
qt_extras   no       Qt's zh-TW translation and the ico image plugin are bundled (warnings only)
dpi         yes*     process awareness is per-monitor-v2 (*only on the ``windows`` platform)
modules     yes      every ``autopress`` module imports (catches modules the spec excluded)
resources   yes      icon.ico, icon.png and the templates folder are bundled
templates   yes      every built-in template loads; no ERROR besides the positions to set up
ocr_models  yes      rapidocr's config files and the PP-OCRv6 det / rec models exist
ocr         yes      the OCR engine reads the code line and the separate 「兌換」 button
data_dir    yes      the data folder resolves and is writable (a fallback is reported, not failed)
=========== ======== ==========================================================================

The report is UTF-8 JSON written atomically::

    {"app": "AutoPress", "version": "0.1.0", "ok": true, "frozen": true, "python": "3.12.10",
     "qt": "6.12.0", "pyqt": "6.12.1", "platform": "windows", "executable": "...",
     "bundle_dir": "...", "started_at": "...", "seconds": 4.2,
     "checks": [{"name": "qt", "ok": true, "required": true, "detail": "...", "seconds": 0.1}, ...]}

Nothing is printed (the windowed exe has no stdout / stderr) and nothing is written except the
report (and the data folder's one-time write probe of ``paths.resolve_data_dir``).
"""

from __future__ import annotations

import ctypes
import importlib
import json
import os
import pkgutil
import platform
import sys
import time
import traceback
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

__all__ = ["CHECK_NAMES", "SPEC_MODULES", "TEST_BUTTON", "TEST_CODE", "TEST_LABEL", "render_test_image", "run"]

TEST_LABEL = "兌換碼："
TEST_CODE = "AB12-CD34"
TEST_BUTTON = "兌換"

CHECK_NAMES: tuple[str, ...] = (
    "qt", "qt_extras", "dpi", "modules", "resources", "templates", "ocr_models", "ocr", "data_dir",
)

# Every module of the SPEC 3.1 tree. pkgutil lists only the modules PyInstaller collected, so this
# explicit list also catches a module that is missing from the bundle altogether.
SPEC_MODULES: tuple[str, ...] = (
    "autopress", "autopress.models", "autopress.i18n", "autopress.paths", "autopress.textutil",
    "autopress.storage", "autopress.logsetup", "autopress.context", "autopress.capture",
    "autopress.selftest",
    *(f"autopress.codes.{m}" for m in ("normalize", "presets", "extract", "fileimport", "queue",
                                       "history", "csvexport")),
    *(f"autopress.ocr.{m}" for m in ("engine", "service", "textfind", "imageio")),
    *(f"autopress.win32.{m}" for m in ("api", "keys", "input", "clipboard", "windows", "elevation", "dpi",
                                       "hotkeys", "power")),
    *(f"autopress.runner.{m}" for m in ("control", "classify", "backend", "steps", "engine", "preflight",
                                        "preview")),
    *(f"autopress.ui.{m}" for m in ("app", "theme", "icons", "widgets", "toast", "main_window",
                                    "settings_page", "help_page", "welcome", "codes_page", "codes_model",
                                    "paste_dialog", "ocr_review", "history_page", "profiles_page",
                                    "step_editor", "keywords_editor", "window_picker", "overlays", "run_page",
                                    "minibar", "run_flow")),
)

# Marker attribute of unfinished development stubs (SPEC 0.2); reported, never expected in a release.
# Spelled in two parts so a search for leftover stub markers does not hit this file.
_STUB_FLAG = "__" + "stub__"

# The app logo (same drawing as the sidebar logo and tools/make_icon.py): QtSvg must render it.
_LOGO_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke-linecap="round" '
    'stroke-linejoin="round"><rect x="2" y="2" width="20" height="20" rx="6" fill="#2F66F0"/>'
    '<path d="M7.5 8.5l3.5 3.5-3.5 3.5M13 15.5h4" stroke="#FFFFFF" stroke-width="2.2"/></svg>'
)

# Fonts tried for the OCR test image (Pillow, real glyphs on every Qt platform); the first file
# that exists wins. Qt draws the image when none of them exists.
_FONT_FILES = ("msjh.ttc", "msjhbd.ttc", "msyh.ttc", "mingliub.ttc", "simsun.ttc", "msgothic.ttc")


@dataclass
class CheckResult:
    name: str
    ok: bool
    required: bool = True
    detail: str = ""
    seconds: float = 0.0


class _Skip(Exception):
    """Raised by a check that does not apply here (recorded as ok, not required)."""


# =============================================================================== entry point


def run(report_path: str, *, checks: Sequence[str] | None = None) -> int:
    """Run the self-test and write the JSON report to ``report_path``. Returns 0 when every
    required check passed, 1 otherwise (also when the report cannot be written). ``checks``
    (optional) runs only the named checks, in the fixed order of CHECK_NAMES (tests)."""
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    started = time.monotonic()
    started_at = _now()
    wanted = [n for n in CHECK_NAMES if checks is None or n in checks]
    results: list[CheckResult] = []
    for name in wanted:
        results.append(_run_check(name))
    ok = all(r.ok for r in results if r.required)
    report = _report_header(started_at)
    report.update(ok=ok, seconds=round(time.monotonic() - started, 3), checks=[asdict(r) for r in results])
    try:
        _write_report(Path(report_path), report)
    except Exception:  # noqa: BLE001 - a self-test never raises; the exit code tells the caller
        return 1
    return 0 if ok else 1


def _run_check(name: str) -> CheckResult:
    func: Callable[[], str] = globals()[f"_check_{name}"]
    required = name != "qt_extras"
    t0 = time.monotonic()
    try:
        detail = func()
        res = CheckResult(name, True, required, detail)
    except _Skip as exc:
        res = CheckResult(name, True, False, f"skipped: {exc}")
    except Exception as exc:  # noqa: BLE001 - every failure becomes a report entry
        tb = traceback.format_exc(limit=6)
        res = CheckResult(name, False, required, f"{type(exc).__name__}: {exc}\n{tb}".strip())
    res.seconds = round(time.monotonic() - t0, 3)
    return res


def _now() -> str:
    from datetime import datetime

    return datetime.now().astimezone().isoformat(timespec="seconds")


def _report_header(started_at: str) -> dict[str, Any]:
    from . import __version__, paths

    head: dict[str, Any] = {
        "app": "AutoPress",
        "version": __version__,
        "ok": False,
        "frozen": paths.is_frozen(),
        "python": platform.python_version(),
        "qt": "",
        "pyqt": "",
        "platform": "",
        "os": platform.platform(),
        "executable": sys.executable,
        "bundle_dir": str(paths.bundle_dir()),
        "started_at": started_at,
    }
    try:
        from PyQt6.QtCore import PYQT_VERSION_STR, qVersion
        from PyQt6.QtGui import QGuiApplication

        head["qt"] = qVersion()  # the Qt really loaded (QT_VERSION_STR is PyQt's build-time Qt)
        head["pyqt"] = PYQT_VERSION_STR
        if QGuiApplication.instance() is not None:
            head["platform"] = QGuiApplication.platformName()
    except Exception:  # noqa: BLE001
        pass
    return head


def _write_report(path: Path, report: dict[str, Any]) -> None:
    from .storage import write_text_atomic

    if not path.is_absolute():
        path = Path.cwd() / path
    write_text_atomic(path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")


# =============================================================================== Qt and DPI


_APP: Any = None  # keeps a QApplication created here alive (PyQt deletes it with its last reference)


def _application() -> Any:
    global _APP
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = _APP = QApplication([sys.argv[0] if sys.argv and sys.argv[0] else "AutoPress"])
    return app


def _check_qt() -> str:
    from PyQt6.QtCore import PYQT_VERSION_STR, QByteArray, qVersion
    from PyQt6.QtGui import QColor, QGuiApplication, QImage, QPainter
    from PyQt6.QtSvg import QSvgRenderer

    _application()
    renderer = QSvgRenderer(QByteArray(_LOGO_SVG.encode("utf-8")))
    if not renderer.isValid():
        raise RuntimeError("QtSvg could not parse the logo")
    img = QImage(32, 32, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(0, 0, 0, 0))
    painter = QPainter(img)
    renderer.render(painter)
    painter.end()
    corner, fill = img.pixelColor(0, 0), img.pixelColor(16, 6)
    if corner.alpha() != 0 or fill.alpha() < 200 or fill.blue() < 200:
        raise RuntimeError(f"QtSvg rendered the logo wrongly (corner {corner.name()}, fill {fill.name()})")
    return f"platform {QGuiApplication.platformName()}, Qt {qVersion()}, PyQt {PYQT_VERSION_STR}, QtSvg ok"


def _check_qt_extras() -> str:
    from PyQt6.QtCore import QLibraryInfo, QTranslator
    from PyQt6.QtGui import QImageReader

    _application()
    folder = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    translator = QTranslator()
    problems = []
    if not translator.load("qtbase_zh_TW", folder):
        problems.append(f"qtbase_zh_TW.qm not found in {folder}")
    formats = {bytes(f).decode() for f in QImageReader.supportedImageFormats()}
    if "ico" not in formats:
        problems.append("ico image plugin missing")
    if problems:
        raise RuntimeError("; ".join(problems))
    return f"qtbase_zh_TW.qm loaded; image formats: {', '.join(sorted(formats))}"


def _check_dpi() -> str:
    from PyQt6.QtGui import QGuiApplication

    _application()
    name = QGuiApplication.platformName()
    if name != "windows":
        raise _Skip(f"platform {name!r} (DPI awareness is set by the windows platform)")
    source = "win32.dpi"
    try:
        from .win32 import dpi

        awareness = dpi.process_awareness()
    except NotImplementedError:  # G3 stub (development only): use the private helper
        awareness, source = _process_awareness(), "selftest helper"
    if awareness != "pmv2":
        raise RuntimeError(f"process DPI awareness is {awareness!r}, expected 'pmv2' ({source})")
    return f"per-monitor-v2 ({source})"


def _process_awareness() -> str:
    """"unaware" | "system" | "pmv1" | "pmv2" | "unknown" for this process (ctypes, Win10 1803+)."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    user32.GetDpiAwarenessContextForProcess.argtypes = [ctypes.c_void_p]
    user32.GetDpiAwarenessContextForProcess.restype = ctypes.c_void_p
    user32.AreDpiAwarenessContextsEqual.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.AreDpiAwarenessContextsEqual.restype = ctypes.c_int
    ctx = user32.GetDpiAwarenessContextForProcess(kernel32.GetCurrentProcess())
    for value, name in ((-4, "pmv2"), (-3, "pmv1"), (-2, "system"), (-1, "unaware"), (-5, "unaware")):
        if user32.AreDpiAwarenessContextsEqual(ctx, ctypes.c_void_p(value & (2 ** 64 - 1))):
            return name
    return "unknown"


# =============================================================================== modules and resources


def _module_names() -> list[str]:
    import autopress

    names = set(SPEC_MODULES)
    for info in pkgutil.walk_packages(autopress.__path__, "autopress.", onerror=lambda _name: None):
        names.add(info.name)
    names.discard("autopress.__main__")  # importing it would be harmless, but it is the launcher
    return sorted(names)


def _check_modules() -> str:
    _application()
    failed = []
    names = _module_names()
    for name in names:
        try:
            importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{name}: {type(exc).__name__}: {exc}")
    if failed:
        raise RuntimeError(f"{len(failed)} of {len(names)} modules failed to import:\n" + "\n".join(failed))
    stubs = [n for n in names if getattr(sys.modules.get(n), _STUB_FLAG, False)]
    tail = f"; still stubs: {', '.join(stubs)}" if stubs else ""
    return f"{len(names)} modules imported{tail}"


def _check_resources() -> str:
    from . import paths

    sizes = {}
    for name in ("icon.ico", "icon.png"):
        f = paths.resource_path(name)
        if not f.is_file() or f.stat().st_size == 0:
            raise RuntimeError(f"missing resource {f}")
        sizes[name] = f.stat().st_size
    if not paths.templates_dir().is_dir():
        raise RuntimeError(f"missing templates folder {paths.templates_dir()}")
    return f"{paths.resource_path()} ({', '.join(f'{k} {v} B' for k, v in sizes.items())})"


def _check_templates() -> str:
    from . import paths, storage
    from .models import IssueLevel

    files = sorted(paths.templates_dir().glob("*.autopress.json"))
    loaded = storage.load_templates()
    if not files or len(loaded) != len(files):
        raise RuntimeError(f"{len(loaded)} of {len(files)} template files loaded from {paths.templates_dir()}")
    problems = []
    for t in loaded:
        missing = t.missing_setup()
        for issue in t.validate():
            if issue.level is IssueLevel.ERROR and (issue.step_index, issue.path.rsplit(".", 1)[-1]) not in missing:
                problems.append(f"{t.name}: {issue.message}")
        if t.template is None:
            problems.append(f"{t.name}: no template info")
    if problems:
        raise RuntimeError("; ".join(problems))
    return ", ".join(t.template.key for t in loaded if t.template)


# =============================================================================== OCR


def _model_dir() -> Path:
    from . import paths

    d = paths.ocr_model_dir()
    if d is None:
        raise RuntimeError("OCR model folder not found (rapidocr/models)")
    return d


def _check_ocr_models() -> str:
    from .ocr.engine import DET_MODEL, REC_MODEL

    d = _model_dir()
    parts = []
    for name in (DET_MODEL, REC_MODEL):
        f = d / name
        if not f.is_file() or f.stat().st_size < 1_000_000:
            raise RuntimeError(f"missing or truncated model {f}")
        parts.append(f"{name} {f.stat().st_size / 1e6:.1f} MB")
    for name in ("config.yaml", "default_models.yaml"):
        if not (d.parent / name).is_file():
            raise RuntimeError(f"missing rapidocr data file {d.parent / name}")
    return f"{d}: " + ", ".join(parts)


def render_test_image() -> Any:
    """The dialog-like BGR test image: 「兌換碼：AB12-CD34」 above a 「兌換」 and a 「取消」 button
    (Pillow with a Windows CJK font; Qt draws it when no font file exists)."""
    import numpy as np

    w, h = 720, 320
    font_dir = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    font_file = next((font_dir / f for f in _FONT_FILES if (font_dir / f).is_file()), None)
    if font_file is not None:
        from PIL import Image, ImageDraw, ImageFont

        img = Image.new("RGB", (w, h), (30, 34, 42))
        draw = ImageDraw.Draw(img)
        draw.text((48, 96), TEST_LABEL + TEST_CODE, font=ImageFont.truetype(str(font_file), 34),
                  fill=(231, 233, 238), anchor="lm")
        button = ImageFont.truetype(str(font_file), 30)
        draw.rounded_rectangle((48, 188, 228, 260), radius=10, fill=(47, 102, 240))
        draw.text((138, 224), TEST_BUTTON, font=button, fill=(255, 255, 255), anchor="mm")
        draw.rounded_rectangle((260, 188, 440, 260), radius=10, outline=(70, 78, 92), width=2)
        draw.text((350, 224), "取消", font=button, fill=(231, 233, 238), anchor="mm")
        return np.ascontiguousarray(np.asarray(img)[:, :, ::-1])
    return _render_with_qt(w, h)


def _render_with_qt(w: int, h: int) -> Any:
    import numpy as np
    from PyQt6.QtCore import QRectF, Qt
    from PyQt6.QtGui import QColor, QFont, QImage, QPainter

    _application()
    img = QImage(w, h, QImage.Format.Format_RGB888)
    img.fill(QColor(30, 34, 42))
    p = QPainter(img)
    font = QFont()
    font.setFamilies(["Microsoft JhengHei UI", "Microsoft JhengHei", "Microsoft YaHei", "SimSun"])
    font.setPixelSize(34)
    p.setFont(font)
    p.setPen(QColor(231, 233, 238))
    p.drawText(QRectF(48, 70, 640, 52), Qt.AlignmentFlag.AlignVCenter, TEST_LABEL + TEST_CODE)
    font.setPixelSize(30)
    p.setFont(font)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(47, 102, 240))
    p.drawRoundedRect(QRectF(48, 188, 180, 72), 10, 10)
    p.setPen(QColor(255, 255, 255))
    p.drawText(QRectF(48, 188, 180, 72), Qt.AlignmentFlag.AlignCenter, TEST_BUTTON)
    p.setPen(QColor(231, 233, 238))
    p.drawText(QRectF(260, 188, 180, 72), Qt.AlignmentFlag.AlignCenter, "取消")
    p.end()
    rows = np.frombuffer(img.constBits().asstring(img.sizeInBytes()), np.uint8).reshape(h, img.bytesPerLine())
    rgb = rows[:, : w * 3].reshape(h, w, 3)
    return np.ascontiguousarray(rgb[:, :, ::-1])


def _ocr_texts(image: Any) -> tuple[list[str], str]:
    """Texts read from ``image`` by the app's OCR engine (G2). While ocr.engine is still a
    development stub, rapidocr is called directly with the same configuration."""
    from .ocr import engine as engine_mod

    try:
        eng = engine_mod.OcrEngine(threads=4)
    except NotImplementedError:
        return _rapidocr_texts(image), "rapidocr (ocr.engine is a stub)"
    return [ln.text for ln in eng.recognize(image)], "ocr.engine.OcrEngine"


def _rapidocr_texts(image: Any) -> list[str]:
    from rapidocr import RapidOCR

    from .ocr.engine import DET_MODEL, REC_MODEL

    d = _model_dir()
    eng = RapidOCR(params={
        "Global.log_level": "error", "Global.use_cls": False,
        "Det.model_path": str(d / DET_MODEL), "Rec.model_path": str(d / REC_MODEL),
        "Det.limit_type": "max", "Det.limit_side_len": 960,
        "EngineConfig.onnxruntime.intra_op_num_threads": 4,
    })
    res = eng(image)
    return [str(t) for t in (getattr(res, "txts", None) or ())]


def _check_ocr() -> str:
    from .textutil import norm_match, squash

    image = render_test_image()
    texts, source = _ocr_texts(image)
    code_ok = any(squash(TEST_CODE) in squash(t) for t in texts)
    button_ok = any(norm_match(t) in ("兌換", "兑换") for t in texts)  # a separate line, as click_text needs
    shown = " | ".join(texts) or "(nothing)"
    if not (code_ok and button_ok):
        missing = [what for what, ok in ((TEST_CODE, code_ok), (TEST_BUTTON, button_ok)) if not ok]
        raise RuntimeError(f"OCR did not read {' and '.join(missing)}; read: {shown} [{source}]")
    return f"read: {shown} [{source}]"


# =============================================================================== data folder


def _check_data_dir() -> str:
    from . import paths

    path, intended = paths.resolve_data_dir()
    if not paths.is_writable_dir(path):
        raise RuntimeError(f"data folder {path} is not writable")
    if intended is not None:
        return f"{path} (fallback: {intended} is not writable)"
    return f"{path}{' (portable)' if paths.is_portable() else ''}"
