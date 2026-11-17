"""File locations: bundled resources (frozen-aware) and the per-user data folder.

OWNED BY A1 (foundation). Pure Python, no Qt. Paths never depend on the working directory.

Data folder (``data_dir()``), first match wins:
1. ``%AUTOPRESS_HOME%`` if set (tests use this; never touch the real profile in tests);
2. portable mode: a file ``portable.txt`` exists in ``app_dir()`` -> ``app_dir()/data``
   (falls back to 3 when that folder cannot be created or written);
3. ``%APPDATA%/AutoPress`` (falls back to ``%TEMP%/AutoPress`` when it cannot be written).

The folder is RESOLVED ONCE (``resolve_data_dir``: one real write probe per process and
setting) and cached, so every later call - from any thread - returns the same folder without
touching the disk. ``resolve_data_dir()`` also tells ui.app whether a fallback happened, for the
「無法寫入資料資料夾」 banner (SPEC 7.1).

Layout inside the data folder::

    settings.json                 Settings (storage.load_settings / save_settings)
    profiles/<id>.autopress.json  one Profile per file (storage.ProfileStore)
    queue.json                    current code queue (codes.queue.CodeQueue)
    history.jsonl                 attempt history, one JSON object per line (codes.history)
    evidence/<yyyy-mm-dd>/*.png   result-region crops saved by ocr_check steps
    logs/autopress.log            rotating log (logsetup.setup_logging)
    instance.lock                 single-instance QLockFile (ui.app)
    cache/ui/*.svg                combo / spin box arrow images written by ui.theme (safe to delete)

Bundled read-only resources live in ``autopress/resources`` (templates, icon), which the
PyInstaller spec ships as ``autopress/resources`` inside the bundle.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
import tempfile
import threading
import uuid
from pathlib import Path

__all__ = [
    "APP_DIR_NAME",
    "ENV_HOME",
    "PORTABLE_MARKER",
    "app_dir",
    "bundle_dir",
    "data_dir",
    "ensure_dir",
    "evidence_dir",
    "history_path",
    "is_frozen",
    "is_portable",
    "is_writable_dir",
    "lock_path",
    "logs_dir",
    "ocr_model_dir",
    "package_dir",
    "profiles_dir",
    "queue_path",
    "resolve_data_dir",
    "resource_path",
    "settings_path",
    "templates_dir",
]

log = logging.getLogger(__name__)

APP_DIR_NAME = "AutoPress"
ENV_HOME = "AUTOPRESS_HOME"
PORTABLE_MARKER = "portable.txt"


def is_frozen() -> bool:
    """True inside a PyInstaller build."""
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> Path:
    """Root of the bundled files: ``sys._MEIPASS`` when frozen (onedir: ``<app>/_internal``),
    otherwise the project root (the folder that contains the ``autopress`` package)."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def app_dir() -> Path:
    """Folder of ``AutoPress.exe`` when frozen, otherwise the project root."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def package_dir() -> Path:
    """The ``autopress`` package folder (source tree or bundle)."""
    if getattr(sys, "_MEIPASS", None):
        return bundle_dir() / "autopress"
    return Path(__file__).resolve().parent


def resource_path(*parts: str) -> Path:
    """``autopress/resources/<parts...>``. Rejects absolute parts and ``..``."""
    for p in parts:
        pp = Path(p)
        if pp.is_absolute() or ".." in pp.parts:
            raise ValueError(f"invalid resource path part: {p!r}")
    return package_dir().joinpath("resources", *parts)


def templates_dir() -> Path:
    """Built-in profile templates (``*.autopress.json``, owned by G8)."""
    return resource_path("templates")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def is_writable_dir(path: Path) -> bool:
    """True if ``path`` exists (or can be created) and a file can be written in it.
    Uses a real write instead of ``os.access`` (which ignores ACLs on Windows); the probe file
    name is unique per call, so concurrent probes never collide."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".write-test-{os.getpid()}-{uuid.uuid4().hex[:12]}"
        probe.write_bytes(b"ok")
        probe.unlink()
        return True
    except OSError:
        return False


def is_portable() -> bool:
    """Portable mode: ``portable.txt`` next to the exe (or in the project root from source),
    and ``AUTOPRESS_HOME`` is not set."""
    if os.environ.get(ENV_HOME):
        return False
    return (app_dir() / PORTABLE_MARKER).is_file()


def _appdata_root() -> Path:
    base = os.environ.get("APPDATA")
    if base:
        return Path(base)
    return Path.home() / "AppData" / "Roaming"


_resolved: dict[tuple[str, str, bool], tuple[Path, Path | None]] = {}
_resolve_lock = threading.Lock()


def resolve_data_dir(refresh: bool = False) -> tuple[Path, Path | None]:
    """``(data folder, intended folder that could not be written or None)``.

    ``AUTOPRESS_HOME`` wins and is never probed. Otherwise the portable / %APPDATA% folder is
    probed with ONE real write the first time and the answer is cached per (app folder,
    %APPDATA%, portable marker) - later calls do no file writes, so threads cannot race on probe
    files and the folder never changes during a session. ``refresh`` probes again (tests)."""
    env = os.environ.get(ENV_HOME)
    if env:
        return Path(env).expanduser().resolve(), None
    portable = is_portable()
    key = (str(app_dir()), os.environ.get("APPDATA", ""), portable)
    with _resolve_lock:
        if not refresh and key in _resolved:
            return _resolved[key]
        intended: Path | None = None
        path = app_dir() / "data" if portable else _appdata_root() / APP_DIR_NAME
        if portable and not is_writable_dir(path):
            log.warning("portable data folder %s is not writable; using %%APPDATA%%", path)
            intended = path
            path = _appdata_root() / APP_DIR_NAME
        if not is_writable_dir(path):
            fallback = Path(tempfile.gettempdir()) / APP_DIR_NAME
            log.error("data folder %s is not writable; falling back to %s", path, fallback)
            intended = intended or path
            path = fallback
        _resolved[key] = (path, intended)
        return path, intended


def data_dir(create: bool = True) -> Path:
    """The per-user data folder (see module docstring; cached by ``resolve_data_dir``).
    Created when ``create`` is true."""
    path, _intended = resolve_data_dir()
    if create:
        ensure_dir(path)
    return path


def settings_path() -> Path:
    return data_dir() / "settings.json"


def profiles_dir() -> Path:
    return ensure_dir(data_dir() / "profiles")


def queue_path() -> Path:
    return data_dir() / "queue.json"


def history_path() -> Path:
    return data_dir() / "history.jsonl"


def evidence_dir() -> Path:
    return ensure_dir(data_dir() / "evidence")


def logs_dir() -> Path:
    return ensure_dir(data_dir() / "logs")


def lock_path() -> Path:
    return data_dir() / "instance.lock"


def ocr_model_dir() -> Path | None:
    """Folder holding ``PP-OCRv6_det_small.onnx`` / ``PP-OCRv6_rec_small.onnx``.
    Frozen: ``<bundle>/rapidocr/models``; source: the installed rapidocr package's ``models``
    folder (found without importing rapidocr). None when neither exists."""
    if getattr(sys, "_MEIPASS", None):
        cand = bundle_dir() / "rapidocr" / "models"
        return cand if cand.is_dir() else None
    try:
        spec = importlib.util.find_spec("rapidocr")
    except (ImportError, ValueError):
        spec = None
    if spec is None or not spec.submodule_search_locations:
        return None
    for loc in spec.submodule_search_locations:
        cand = Path(loc) / "models"
        if cand.is_dir():
            return cand
    return None
