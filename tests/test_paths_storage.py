"""Tests for autopress.paths, autopress.storage, autopress.logsetup and autopress.context
(OWNED BY A1)."""

from __future__ import annotations

import json
import logging
import logging.handlers
from pathlib import Path

import pytest

from autopress import i18n, logsetup, paths, storage
from autopress import models as m

# ----------------------------------------------------------------------------- paths


def test_data_dir_follows_env(isolated_home: Path) -> None:
    assert paths.data_dir() == isolated_home.resolve()
    assert paths.settings_path().parent == isolated_home.resolve()
    assert paths.profiles_dir().is_dir() and paths.logs_dir().is_dir() and paths.evidence_dir().is_dir()
    assert paths.queue_path().name == "queue.json" and paths.history_path().name == "history.jsonl"
    assert not paths.is_portable()


def test_portable_and_appdata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = tmp_path / "app"
    app.mkdir()
    monkeypatch.delenv(paths.ENV_HOME, raising=False)
    monkeypatch.setattr(paths, "app_dir", lambda: app)
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    assert paths.data_dir() == tmp_path / "roaming" / "AutoPress"
    (app / paths.PORTABLE_MARKER).write_text("", encoding="utf-8")
    assert paths.is_portable()
    assert paths.data_dir() == app / "data"


def test_resource_paths() -> None:
    assert paths.templates_dir() == paths.package_dir() / "resources" / "templates"
    with pytest.raises(ValueError):
        paths.resource_path("..", "x")
    with pytest.raises(ValueError):
        paths.resource_path("C:/Windows")
    assert not paths.is_frozen()
    assert paths.bundle_dir() == paths.app_dir()


def test_ocr_model_dir_has_models() -> None:
    d = paths.ocr_model_dir()
    assert d is not None
    assert (d / "PP-OCRv6_det_small.onnx").is_file() and (d / "PP-OCRv6_rec_small.onnx").is_file()


def test_is_writable_dir(tmp_path: Path) -> None:
    assert paths.is_writable_dir(tmp_path / "new" / "deep")


# ----------------------------------------------------------------------------- storage


def test_json_atomic_roundtrip(tmp_path: Path) -> None:
    f = tmp_path / "sub" / "a.json"
    storage.write_json(f, {"名稱": "兌換", "bad": "x\ud800y"})
    raw = f.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    data = storage.read_json(f)
    assert data["名稱"] == "兌換" and data["bad"] == "x?y"
    assert list(f.parent.glob("*.tmp")) == []
    assert storage.read_json(tmp_path / "missing.json", {"d": 1}) == {"d": 1}


def test_broken_json_is_moved_aside_only_in_the_data_folder(tmp_path: Path, isolated_home: Path) -> None:
    f = isolated_home / "settings.json"
    f.write_text("{not json", encoding="utf-8")
    assert storage.read_json(f, "default") == "default"
    assert not f.exists()
    assert len(list(isolated_home.glob("settings.json.broken-*"))) == 1
    outside = tmp_path / "下載" / "朋友的設定檔.autopress.json"  # T06: a user-picked file is never renamed
    outside.parent.mkdir()
    outside.write_text("{not json", encoding="utf-8")
    assert storage.read_json(outside, None) is None and outside.exists()
    assert storage.read_json(outside, None, quarantine=True) is None and not outside.exists()


def test_atomic_write_fails_fast_when_creation_is_denied(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T07: no tempfile.mkstemp retry loop - the first PermissionError becomes StorageError."""
    import os
    import tempfile
    import time

    calls: list[str] = []

    def denied(path: object, flags: int, mode: int = 0o777) -> int:
        calls.append(str(path))
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(os, "open", denied)
    monkeypatch.setattr(tempfile, "mkstemp", lambda *a, **k: pytest.fail("mkstemp must not be used"))
    t0 = time.monotonic()
    with pytest.raises(storage.StorageError):
        storage.write_bytes_atomic(tmp_path / "export.csv", b"x")
    assert len(calls) == 1 and time.monotonic() - t0 < 1.0
    assert ".tmp" in calls[0] and "export.csv" in calls[0]


def test_data_dir_is_resolved_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T03: after the first probe no thread probes or races again; T22: the fallback is reported."""
    import threading

    monkeypatch.delenv(paths.ENV_HOME, raising=False)
    app = tmp_path / "app"
    app.mkdir()
    monkeypatch.setattr(paths, "app_dir", lambda: app)
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    first, intended = paths.resolve_data_dir(refresh=True)
    assert first == tmp_path / "roaming" / "AutoPress" and intended is None
    monkeypatch.setattr(paths, "is_writable_dir", lambda p: pytest.fail("probed again"))
    seen: list[Path] = []

    def worker() -> None:
        for _ in range(300):
            seen.append(paths.data_dir())

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert set(seen) == {first}
    monkeypatch.setattr(paths, "is_writable_dir", lambda p: "roaming" not in str(p))  # %APPDATA% denied
    path, intended = paths.resolve_data_dir(refresh=True)
    assert intended == tmp_path / "roaming" / "AutoPress" and path.name == "AutoPress" and path != intended


def test_settings_load_save(isolated_home: Path) -> None:
    s = storage.load_settings()
    assert m.to_dict(s) == m.to_dict(m.Settings())
    s.theme = m.ThemeName.LIGHT
    s.hotkeys.stop = "Ctrl+F9"
    storage.save_settings(s)
    again = storage.load_settings()
    assert again.theme is m.ThemeName.LIGHT and again.hotkeys.stop == "Ctrl+F9"
    assert json.loads(paths.settings_path().read_text(encoding="utf-8"))["schema_version"] == 1


def test_profile_store_crud(tmp_path: Path, sample_profile: m.Profile) -> None:
    store = storage.ProfileStore(tmp_path / "profiles")
    assert store.list() == []
    path = store.save(sample_profile)
    assert path.name == f"{sample_profile.id}{m.PROFILE_FILE_SUFFIX}"
    got = store.get(sample_profile.id)
    assert got is not None and m.to_dict(got)["steps"] == m.to_dict(sample_profile)["steps"]
    dup = store.duplicate(sample_profile.id)
    assert dup.id != sample_profile.id and dup.name.endswith("（副本）")
    assert [p.name for p in store.list()] == sorted([sample_profile.name, dup.name], key=str.casefold)
    assert store.delete(dup.id) and not store.delete(dup.id)
    assert store.get("missing") is None and store.get("") is None


def test_profile_import_export(tmp_path: Path, sample_profile: m.Profile) -> None:
    store = storage.ProfileStore(tmp_path / "profiles")
    sample_profile.target.title = "Hero-Kai 的帳號 - 測試遊戲"
    sample_profile.target.allow_same_process = True
    sample_profile.last_test_ok_at = m.now_iso()
    store.save(sample_profile)
    out = tmp_path / "分享" / "我的設定檔.autopress.json"
    store.export_file(sample_profile, out, title_keyword="測試遊戲")
    shared = json.loads(out.read_text(encoding="utf-8"))
    assert shared["target"]["title"] == "測試遊戲" and shared["target"]["allow_same_process"] is False
    assert shared["last_test_ok_at"] == ""
    store.export_file(sample_profile, tmp_path / "plain.autopress.json")
    assert json.loads((tmp_path / "plain.autopress.json").read_text(encoding="utf-8"))["target"]["title"] == ""
    preview = store.read_file(out)  # PX-17 / T23: read only - nothing saved yet
    assert len(store.list()) == 1
    assert preview.target.is_empty() and preview.suggested_exe == "game.exe"  # PX-01: target never imported
    imported = store.import_profile(preview)
    assert imported.id != sample_profile.id  # id clash -> fresh id, nothing overwritten
    assert len(store.list()) == 2 and store.get(imported.id).target.is_empty()
    bad = tmp_path / "bad.json"
    bad.write_text('["not", "a", "profile"]', encoding="utf-8")
    with pytest.raises(storage.StorageError):
        store.import_file(bad)
    broken = tmp_path / "broken.autopress.json"
    broken.write_text("{nope", encoding="utf-8")
    with pytest.raises(storage.StorageError):
        store.read_file(broken)
    assert broken.exists()  # T06: the user's file keeps its name


def test_saving_writes_the_current_schema_version(tmp_path: Path) -> None:
    """T19: a newer file that lost fields on load must not keep claiming the newer version."""
    store = storage.ProfileStore(tmp_path / "profiles")
    data = m.to_dict(m.Profile(name="new"))
    data["schema_version"] = 99
    p = m.profile_from_dict(data)
    assert p.schema_version == 99
    store.save(p)
    assert json.loads(store.path_for(p.id).read_text(encoding="utf-8"))["schema_version"] == m.PROFILE_SCHEMA_VERSION


def test_templates(tmp_path: Path) -> None:
    for key, order in (("b", 2), ("a", 1)):
        t = m.Profile(name=key, template=m.TemplateInfo(key=key, title_zh=f"範本{key}", title_en=f"Template {key}", order=order))
        storage.write_json(tmp_path / f"{key}{m.PROFILE_FILE_SUFFIX}", m.to_dict(t))
    (tmp_path / f"broken{m.PROFILE_FILE_SUFFIX}").write_text("[]", encoding="utf-8")
    temps = storage.load_templates(tmp_path)
    assert [t.template.key for t in temps] == ["a", "b"]
    i18n.set_language("en")
    p = storage.profile_from_template(temps[0])
    assert p.name == "Template a" and p.template is None and p.id != temps[0].id
    assert storage.load_templates(tmp_path / "nope") == []


# ----------------------------------------------------------------------------- logging / context


def test_logging_setup(tmp_path: Path) -> None:
    log_file = logsetup.setup_logging(log_dir=tmp_path, console=False)
    logging.getLogger("autopress.test").info("你好 %s", logsetup.mask_code("ABCD-1234-EFGH"))
    for h in logging.getLogger().handlers:
        h.flush()
    text = log_file.read_text(encoding="utf-8")
    assert "你好 ABC***GH" in text
    assert logsetup.mask_code("SHORT") == "***"
    logsetup.setup_logging(log_dir=tmp_path, console=False)  # idempotent: no duplicate handlers
    assert sum(isinstance(h, logging.handlers.RotatingFileHandler) for h in logging.getLogger().handlers) == 1
    for h in list(logsetup._configured_handlers):
        logging.getLogger().removeHandler(h)
        h.close()
    logsetup._configured_handlers.clear()


def test_context_helpers(demo_ctx: object) -> None:
    ctx = demo_ctx
    seen: list[object] = []
    ctx.signals.settings_changed.connect(seen.append)
    ctx.signals.toast.connect(lambda kind, text: seen.append((kind, text)))
    ctx.signals.active_profile_changed.connect(lambda pid: seen.append(("active", pid)))
    prof = ctx.active_profile()
    assert prof is not None and prof.name.startswith("示範")
    ctx.set_active_profile("")
    assert ctx.active_profile() is None and ("active", "") in seen
    assert storage.load_settings().active_profile_id == ""
    ctx.notify("完成", "success")
    assert ("success", "完成") in seen

