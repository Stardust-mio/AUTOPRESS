"""JSON persistence for settings, profiles and built-in templates.

OWNED BY A1 (foundation). Pure Python, no Qt. Call from the GUI thread only (not thread-safe).
The code queue and the history have their own stores (codes.queue / codes.history, G1); they
should use ``write_json`` / ``read_json`` from here for their files.

* All files are UTF-8 (no BOM), written atomically: a uniquely named temp file in the same
  folder created with ``O_CREAT | O_EXCL`` (never ``tempfile.mkstemp``: it retries up to
  2**31 times when an ACL denies file creation - measured hang, SPEC decision log T07), flush,
  fsync, ``os.replace``. A crash never leaves a half-written file; a denied folder raises
  StorageError at once. ``write_bytes_atomic`` is the shared helper (CSV export, PNG evidence).
* A file INSIDE the data folder that is not valid JSON is renamed to
  ``<name>.broken-<yyyymmdd-HHMMSS>`` and the caller gets defaults; files outside it (imports,
  templates) are never renamed.
* Profiles are ``profiles/<id>.autopress.json``. Imported profiles never overwrite an existing
  profile: an id clash gets a fresh id. Imports never keep the author's target (SPEC 6.4.2).
* Saving always writes the CURRENT ``schema_version`` (fields of a newer version are not kept).
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from . import paths
from .i18n import tr
from .models import (
    PROFILE_FILE_SUFFIX,
    PROFILE_SCHEMA_VERSION,
    SETTINGS_SCHEMA_VERSION,
    Profile,
    Settings,
    TitleMatch,
    new_id,
    now_iso,
    profile_from_dict,
    settings_from_dict,
    to_dict,
)

__all__ = [
    "ProfileStore",
    "StorageError",
    "load_settings",
    "load_templates",
    "profile_from_template",
    "read_json",
    "save_settings",
    "write_bytes_atomic",
    "write_json",
    "write_text_atomic",
]

log = logging.getLogger(__name__)


class StorageError(OSError):
    """A file could not be read or written. ``str(err)`` is a localized message."""


def _write_error(path: Path, exc: OSError) -> StorageError:
    return StorageError(tr(f"無法寫入檔案：{path}（{exc}）", f"Cannot write file: {path} ({exc})"))


def write_bytes_atomic(path: Path, data: bytes) -> None:
    """Write ``data`` atomically (temp file ``.<name>.<random>.tmp`` + ``os.replace``). The temp
    file is created ONCE with O_CREAT|O_EXCL: a folder that denies file creation raises
    StorageError immediately instead of looping. Any thread (callers write different files)."""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise _write_error(path, exc) from exc
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:12]}.tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o666)
    except OSError as exc:
        raise _write_error(path, exc) from exc
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except OSError as exc:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise _write_error(path, exc) from exc


def write_text_atomic(path: Path, text: str) -> None:
    """Write ``text`` as UTF-8 atomically. Lone surrogates are replaced, never crash."""
    write_bytes_atomic(Path(path), text.encode("utf-8", errors="replace"))


def write_json(path: Path, data: Any) -> None:
    """Atomic, pretty-printed (indent 2), ``ensure_ascii=False`` JSON."""
    write_text_atomic(Path(path), json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _inside_data_dir(path: Path) -> bool:
    try:
        root = paths.data_dir(create=False).resolve()
        Path(path).resolve().relative_to(root)
        return True
    except (ValueError, OSError):
        return False


def read_json(path: Path, default: Any = None, *, quarantine: bool | None = None) -> Any:
    """Parsed JSON of ``path``; ``default`` if the file is missing or not valid JSON. With
    ``quarantine`` (None = automatic: only for files inside ``paths.data_dir()``) an invalid
    file is renamed to ``*.broken-<timestamp>`` (logged) so it is not overwritten; files the
    user picked elsewhere (imports) and bundled templates are never renamed."""
    path = Path(path)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return default
    except OSError as exc:
        raise StorageError(tr(f"無法讀取檔案：{path}（{exc}）", f"Cannot read file: {path} ({exc})")) from exc
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        if quarantine is None:
            quarantine = _inside_data_dir(path)
        if not quarantine:
            log.warning("invalid JSON in %s (%s); left untouched", path, exc)
            return default
        broken = path.with_name(f"{path.name}.broken-{datetime.now():%Y%m%d-%H%M%S}")
        log.error("invalid JSON in %s (%s); moved to %s", path, exc, broken.name)
        try:
            os.replace(path, broken)
        except OSError:
            log.exception("could not move broken file %s", path)
        return default


# =============================================================================== settings


def load_settings(path: Path | None = None) -> Settings:
    """Settings from ``settings.json`` (defaults when missing or broken)."""
    data = read_json(path or paths.settings_path(), None)
    return settings_from_dict(data) if isinstance(data, dict) else Settings()


def save_settings(settings: Settings, path: Path | None = None) -> None:
    """Write ``settings`` (always as the current schema version)."""
    settings.schema_version = SETTINGS_SCHEMA_VERSION
    write_json(path or paths.settings_path(), to_dict(settings))


# =============================================================================== profiles


class ProfileStore:
    """Profiles as one JSON file each in ``profiles_dir``. Every method re-reads the folder,
    so several stores on the same folder stay consistent (no cache)."""

    def __init__(self, directory: Path | None = None) -> None:
        self._dir = Path(directory) if directory is not None else None

    @property
    def directory(self) -> Path:
        d = self._dir if self._dir is not None else paths.profiles_dir()
        d.mkdir(parents=True, exist_ok=True)
        return d

    def path_for(self, profile_id: str) -> Path:
        safe = "".join(c for c in profile_id if c.isalnum() or c in "-_") or "profile"
        return self.directory / f"{safe}{PROFILE_FILE_SUFFIX}"

    def list(self) -> list[Profile]:
        """All profiles, sorted by name (case-insensitive) then id. Broken files are skipped."""
        out: list[Profile] = []
        for f in sorted(self.directory.glob(f"*{PROFILE_FILE_SUFFIX}")):
            data = read_json(f, None)
            if isinstance(data, dict):
                p = profile_from_dict(data)
                if self.path_for(p.id) != f:  # file renamed by hand: trust the file name
                    p.id = f.name[: -len(PROFILE_FILE_SUFFIX)]
                out.append(p)
        out.sort(key=lambda p: (p.name.casefold(), p.id))
        return out

    def get(self, profile_id: str) -> Profile | None:
        if not profile_id:
            return None
        data = read_json(self.path_for(profile_id), None)
        if not isinstance(data, dict):
            return None
        p = profile_from_dict(data)
        p.id = profile_id
        return p

    def exists(self, profile_id: str) -> bool:
        return bool(profile_id) and self.path_for(profile_id).is_file()

    def save(self, profile: Profile, touch: bool = True) -> Path:
        """Write the profile (``updated_at`` refreshed when ``touch``). Returns the file path.
        Always writes the CURRENT schema version (and sets it on ``profile``): fields of a newer
        version are not kept, so the UI warns before saving a profile with a newer version."""
        if touch:
            profile.updated_at = now_iso()
        profile.schema_version = PROFILE_SCHEMA_VERSION
        path = self.path_for(profile.id)
        write_json(path, to_dict(profile))
        return path

    def delete(self, profile_id: str) -> bool:
        try:
            self.path_for(profile_id).unlink()
            return True
        except FileNotFoundError:
            return False

    def duplicate(self, profile_id: str, new_name: str | None = None) -> Profile:
        src = self.get(profile_id)
        if src is None:
            raise KeyError(profile_id)
        copy = src.clone(new_identity=True)
        copy.template = None
        copy.name = new_name if new_name is not None else tr(f"{src.name}（副本）", f"{src.name} (copy)")
        self.save(copy)
        return copy

    def read_file(self, path: Path) -> Profile:
        """Read a shared ``*.autopress.json`` WITHOUT saving or renaming anything, already made
        safe with ``Profile.prepare_import()`` (empty target, author's exe in ``suggested_exe``).
        The Profiles page shows ``action_lines()`` from it and saves only after the user
        confirms (``import_profile``). Raises StorageError (localized) for unreadable files and
        files that are not profiles (the user's file is left untouched)."""
        data = read_json(Path(path), None, quarantine=False)
        if not isinstance(data, dict) or not isinstance(data.get("steps", []), list):
            raise StorageError(tr("這不是 AutoPress 設定檔", "This is not an AutoPress profile"))
        p = profile_from_dict(data)
        p.prepare_import()
        return p

    def import_profile(self, profile: Profile) -> Profile:
        """Save a profile returned by ``read_file`` as a NEW profile (fresh id when its id is
        empty or taken; ``prepare_import`` applied again, so a target can never sneak in)."""
        profile.prepare_import()
        if not profile.id or self.exists(profile.id):
            profile.id = new_id()
        self.save(profile)
        return profile

    def import_file(self, path: Path) -> Profile:
        """``import_profile(read_file(path))`` - for tests and scripts; the UI shows the summary
        between the two calls."""
        return self.import_profile(self.read_file(path))

    def export_file(self, profile: Profile, path: Path, title_keyword: str = "") -> None:
        """Write a shareable copy (profiles never contain codes, history or screenshots). The
        target keeps exe and class only as a hint (imports never use it): the title is replaced
        by ``title_keyword`` (a short keyword the author confirmed; "" = none, so the author's
        window title - often an account or character name - is not shared) and
        ``allow_same_process`` / ``last_test_ok_at`` are cleared."""
        copy = profile.clone(new_identity=False)
        copy.target.title = title_keyword.strip()
        copy.target.title_mode = TitleMatch.CONTAINS
        copy.target.allow_same_process = False
        copy.last_test_ok_at = ""
        copy.template = None
        copy.schema_version = PROFILE_SCHEMA_VERSION
        write_json(Path(path), to_dict(copy))


# =============================================================================== templates


def load_templates(directory: Path | None = None) -> list[Profile]:
    """Built-in templates (``resources/templates/*.autopress.json``), sorted by
    ``template.order`` then name. Broken files are skipped (logged)."""
    d = Path(directory) if directory is not None else paths.templates_dir()
    out: list[Profile] = []
    if not d.is_dir():
        return out
    for f in sorted(d.glob(f"*{PROFILE_FILE_SUFFIX}")):
        data = read_json(f, None)
        if isinstance(data, dict):
            out.append(profile_from_dict(data))
        else:
            log.warning("template %s is not a JSON object", f.name)
    out.sort(key=lambda p: (p.template.order if p.template else 1000, p.name))
    return out


def profile_from_template(template: Profile) -> Profile:
    """A new user profile from a template: new ids, name = the template's localized title."""
    p = template.clone(new_identity=True)
    if template.template is not None:
        p.name = template.template.title() or p.name
        p.description = template.template.description() or p.description
    p.template = None
    return p
