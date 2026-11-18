# OWNED BY G8
"""Packaging (SPEC 8.2 G8 row, 10.1, 10.2, 10.4): autopress.spec (executed with stand-ins for
Analysis / EXE / COLLECT - nothing is built), the version resource, build.ps1 (PowerShell parser),
the icon, LICENSE / THIRD-PARTY-NOTICES.md / licenses/, README and user-guide images, and the
optional smoke tests of a finished build (skipped while dist/ has none).
"""

from __future__ import annotations

import importlib.metadata
import json
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import autopress

ROOT = Path(__file__).resolve().parent.parent
SPEC_FILE = ROOT / "autopress.spec"
BUILD_PS1 = ROOT / "build.ps1"
LICENSES = ROOT / "licenses"
NOTICES = ROOT / "THIRD-PARTY-NOTICES.md"
SITE = Path(sys.prefix) / "Lib" / "site-packages"
DIST_EXE = ROOT / "dist" / "AutoPress" / "AutoPress.exe"


# ============================================================================= autopress.spec


class FakeAnalysis:
    """Stand-in for PyInstaller's Analysis: records its arguments, offers fake TOCs."""

    toc: dict[str, list[tuple[str, str, str]]] = {"binaries": [], "datas": [], "pure": []}

    def __init__(self, scripts: list[str], **kwargs: Any) -> None:
        self.scripts = scripts
        self.kwargs = kwargs
        self.binaries = list(self.toc["binaries"])
        self.datas = list(self.toc["datas"])
        self.pure = list(self.toc["pure"])


def exec_spec(monkeypatch: pytest.MonkeyPatch, **toc: list[tuple[str, str, str]]) -> dict[str, Any]:
    monkeypatch.setenv("AUTOPRESS_SPEC_CHECK", "1")  # the spec must not rewrite version_info.txt
    monkeypatch.setattr(FakeAnalysis, "toc", {"binaries": toc.get("binaries", []), "datas": toc.get("datas", []),
                                              "pure": toc.get("pure", [])})
    ns: dict[str, Any] = {
        "SPECPATH": str(ROOT),
        "Analysis": FakeAnalysis,
        "PYZ": lambda pure, *a, **k: ("PYZ", pure),
        "EXE": lambda *a, **k: ("EXE", a, k),
        "COLLECT": lambda *a, **k: ("COLLECT", a, k),
    }
    before = (ROOT / "version_info.txt").read_bytes()
    exec(compile(SPEC_FILE.read_text(encoding="utf-8"), str(SPEC_FILE), "exec"), ns)  # noqa: S102
    assert (ROOT / "version_info.txt").read_bytes() == before
    return ns


def test_spec_bundles_the_rapidocr_data_and_the_resources(monkeypatch: pytest.MonkeyPatch) -> None:
    ns = exec_spec(monkeypatch)
    a = ns["a"]
    assert a.scripts == [str(ROOT / "main.py")]
    datas = a.kwargs["datas"]
    dests = {Path(src).name: dest.replace("\\", "/") for src, dest in datas}
    for name in ("config.yaml", "default_models.yaml", "PP-OCRv6_det_small.onnx", "PP-OCRv6_rec_small.onnx"):
        assert name in dests, name
    assert dests["PP-OCRv6_det_small.onnx"] == "rapidocr/models"  # paths.ocr_model_dir() when frozen
    assert not any("pytorch" in src.replace("\\", "/").split("/") for src, _d in datas)
    assert (str(ROOT / "autopress" / "resources"), "autopress/resources") in datas
    assert "**/pytorch/**" in SPEC_FILE.read_text(encoding="utf-8")


def test_spec_bundles_every_autopress_module(monkeypatch: pytest.MonkeyPatch) -> None:
    """The self-test imports every module in the exe, so the spec must collect all of them."""
    from autopress import selftest

    hidden = exec_spec(monkeypatch)["a"].kwargs["hiddenimports"]
    assert set(selftest.SPEC_MODULES) <= set(hidden)
    assert "autopress.__main__" not in hidden and not any("__pycache__" in m for m in hidden)
    on_disk = {p.relative_to(ROOT).with_suffix("").as_posix().replace("/", ".").removesuffix(".__init__")
               for p in (ROOT / "autopress").rglob("*.py") if "__pycache__" not in p.parts and p.name != "__main__.py"}
    assert set(hidden) == on_disk


def test_spec_excludes_unused_modules_but_keeps_qtsvg(monkeypatch: pytest.MonkeyPatch) -> None:
    excludes = set(exec_spec(monkeypatch)["a"].kwargs["excludes"])
    for mod in ("PyQt6.QtQml", "PyQt6.QtQuick", "PyQt6.QtWebEngineCore", "PyQt6.QtWebEngineWidgets",
                "PyQt6.QtMultimedia", "PyQt6.Qt3DCore", "PyQt6.Qt3DRender", "PyQt6.QtBluetooth",
                "PyQt6.QtPositioning", "PyQt6.QtSql", "PyQt6.QtTest", "PIL._avif", "tkinter", "pytest"):
        assert mod in excludes, mod
    for kept in ("PyQt6.QtCore", "PyQt6.QtGui", "PyQt6.QtWidgets", "PyQt6.QtSvg", "PyQt6.QtNetwork",
                 "requests", "urllib3", "numpy", "cv2", "onnxruntime", "rapidocr", "PIL", "mss"):
        assert kept not in excludes, kept


def test_spec_builds_a_windowed_onedir_asinvoker_exe(monkeypatch: pytest.MonkeyPatch) -> None:
    ns = exec_spec(monkeypatch)
    _tag, args, exe = ns["exe"]
    assert exe["name"] == "AutoPress" and exe["console"] is False and exe["upx"] is False
    assert exe["exclude_binaries"] is True  # one-folder: binaries go to COLLECT
    assert exe.get("uac_admin", False) is False and not exe.get("uac_uiaccess", False)
    assert exe["icon"] == [str(ROOT / "autopress" / "resources" / "icon.ico")]
    assert Path(exe["version"]) == ROOT / "version_info.txt"
    _tag, cargs, coll = ns["coll"]
    assert coll["name"] == "AutoPress" and coll["upx"] is False
    assert cargs[0] is ns["exe"]


@pytest.mark.parametrize(("dest", "kept"), [
    ("cv2\\opencv_videoio_ffmpeg4130_64.dll", False),
    ("PyQt6\\Qt6\\bin\\opengl32sw.dll", False),
    ("PyQt6\\Qt6\\bin\\Qt6Pdf.dll", False),
    ("PyQt6\\Qt6\\bin\\Qt6Network.dll", False),
    ("ucrtbase.dll", False),
    ("api-ms-win-crt-runtime-l1-1-0.dll", False),
    ("PyQt6\\Qt6\\plugins\\platforms\\qwindows.dll", True),
    ("PyQt6\\Qt6\\plugins\\platforms\\qoffscreen.dll", False),
    ("PyQt6\\Qt6\\plugins\\imageformats\\qico.dll", True),
    ("PyQt6\\Qt6\\plugins\\imageformats\\qsvg.dll", True),
    ("PyQt6\\Qt6\\plugins\\imageformats\\qjpeg.dll", False),
    ("PyQt6\\Qt6\\plugins\\iconengines\\qsvgicon.dll", True),
    ("PyQt6\\Qt6\\plugins\\styles\\qmodernwindowsstyle.dll", False),
    ("PyQt6\\Qt6\\plugins\\generic\\qtuiotouchplugin.dll", False),
    ("PyQt6\\Qt6\\bin\\Qt6Core.dll", True),
    ("PyQt6\\Qt6\\bin\\Qt6Svg.dll", True),
    ("onnxruntime\\capi\\onnxruntime.dll", True),
    ("numpy.libs\\libscipy_openblas64_-1234.dll", True),
    ("shapely.libs\\geos_c-5678.dll", True),
])
def test_spec_binary_filter(monkeypatch: pytest.MonkeyPatch, dest: str, kept: bool) -> None:
    ns = exec_spec(monkeypatch)
    assert ns["keep_binary"]((dest, "C:/src/x.dll", "BINARY"), frozenset({"PyQt6.QtCore"})) is kept


def test_spec_keeps_qtnetwork_only_when_imported(monkeypatch: pytest.MonkeyPatch) -> None:
    net = ("PyQt6\\Qt6\\bin\\Qt6Network.dll", "C:/x/Qt6Network.dll", "BINARY")
    ffmpeg = ("cv2\\opencv_videoio_ffmpeg4130_64.dll", "C:/x/f.dll", "BINARY")
    core = ("PyQt6\\Qt6\\bin\\Qt6Core.dll", "C:/x/Qt6Core.dll", "BINARY")
    ns = exec_spec(monkeypatch, binaries=[net, ffmpeg, core], pure=[("autopress.models", "m.py", "PYMODULE")])
    assert ns["a"].binaries == [core]
    ns = exec_spec(monkeypatch, binaries=[net, ffmpeg, core], pure=[("PyQt6.QtNetwork", "n.pyd", "PYMODULE")])
    assert ns["a"].binaries == [net, core]


def test_spec_data_filter_keeps_only_the_zh_tw_qt_translation(monkeypatch: pytest.MonkeyPatch) -> None:
    datas = [("PyQt6\\Qt6\\translations\\qtbase_zh_TW.qm", "s", "DATA"),
             ("PyQt6\\Qt6\\translations\\qtbase_de.qm", "s", "DATA"),
             ("PyQt6\\Qt6\\translations\\qtmultimedia_zh_TW.qm", "s", "DATA"),
             ("rapidocr\\config.yaml", "s", "DATA"),
             ("autopress\\resources\\templates\\web_generic.autopress.json", "s", "DATA")]
    ns = exec_spec(monkeypatch, datas=datas)
    assert [d[0] for d in ns["a"].datas] == [datas[0][0], datas[3][0], datas[4][0]]


def test_spec_data_filter_drops_local_backup_copies(monkeypatch: pytest.MonkeyPatch) -> None:
    datas = [("autopress\\resources\\templates\\web_generic.autopress.json", "s", "DATA"),
             ("autopress\\resources\\templates\\web_generic.autopress.json.bak-20261118", "s", "DATA"),
             ("autopress\\resources\\icon.png", "s", "DATA"),
             ("autopress\\resources\\icon.png.BAK-20261118", "s", "DATA")]
    ns = exec_spec(monkeypatch, datas=datas)
    assert [d[0] for d in ns["a"].datas] == [datas[0][0], datas[2][0]]


def test_version_resource_matches_the_app(monkeypatch: pytest.MonkeyPatch) -> None:
    ns = exec_spec(monkeypatch)
    text = (ROOT / "version_info.txt").read_text(encoding="utf-8")
    assert text == ns["VERSION_TEXT"], "version_info.txt is stale: run a build (autopress.spec rewrites it)"
    from PyInstaller.utils.win32 import versioninfo

    info = versioninfo.load_version_info_from_text_file(str(ROOT / "version_info.txt"))
    v = autopress.version_tuple()
    assert (info.ffi.fileVersionMS >> 16, info.ffi.fileVersionMS & 0xFFFF, info.ffi.fileVersionLS >> 16) == v
    assert f"'{autopress.__version__}'" in text and "'AutoPress.exe'" in text


def test_pyinstaller_is_installed_without_changing_the_pinned_packages() -> None:
    assert importlib.metadata.version("pyinstaller") == "6.22.3"
    assert importlib.metadata.version("pyinstaller-hooks-contrib") == "2026.10"
    pins = re.findall(r"^([A-Za-z0-9_.-]+)==(\S+)", (ROOT / "requirements.txt").read_text(encoding="utf-8"), re.M)
    assert len(pins) > 20
    for name, version in pins:
        assert importlib.metadata.version(name) == version, name


# ============================================================================= build.ps1


def test_build_script_is_utf8_bom_crlf_and_has_every_step() -> None:
    raw = BUILD_PS1.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "Windows PowerShell 5.1 needs the BOM for the Chinese strings"
    text = raw.decode("utf-8-sig")
    assert "\r\n" in text and "\n" not in text.replace("\r\n", "")
    for needle in ("autopress.spec", "--selftest", "AUTOPRESS_HOME", "中文 路徑", "請先解壓縮再執行.txt",
                   "AutoPress-$Version-win64.zip", "README.md", "LICENSE", "THIRD-PARTY-NOTICES.md",
                   "licenses", "-m PyInstaller", "--clean", "tools\\make_icon.py", "Start-Process",
                   "WaitForExit", "-m zipfile -c", "docs\\user_guide.md", "-Filter '*.png'"):
        assert needle in text, needle
    assert "&&" not in text and "||" not in text  # Windows PowerShell 5.1 has neither


@pytest.mark.skipif(shutil.which("powershell") is None, reason="Windows PowerShell not found")
def test_build_script_parses_without_errors() -> None:
    cmd = ("$t = $null; $e = $null; "
           f"[void][System.Management.Automation.Language.Parser]::ParseFile('{BUILD_PS1}', [ref]$t, [ref]$e); "
           "$e.Count; $e | ForEach-Object { $_.ToString() }")
    res = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip().splitlines()[0] == "0", res.stdout


# ============================================================================= icon


def _ico_entries(data: bytes) -> list[tuple[int, bytes]]:
    reserved, kind, count = struct.unpack_from("<HHH", data, 0)
    assert (reserved, kind) == (0, 1)
    out = []
    for i in range(count):
        w, _h, _c, _r, planes, bits, size, offset = struct.unpack_from("<BBBBHHII", data, 6 + 16 * i)
        assert (planes, bits) == (1, 32)
        out.append((w or 256, data[offset: offset + size]))
    return out


def test_icon_files_hold_every_size() -> None:
    from tools import make_icon

    ico = (ROOT / "autopress" / "resources" / "icon.ico").read_bytes()
    entries = _ico_entries(ico)
    assert [w for w, _d in entries] == list(make_icon.ICO_SIZES)
    for w, blob in entries:
        if w == 256:
            assert blob.startswith(b"\x89PNG\r\n\x1a\n")
        else:
            size, bw, bh, _planes, bits = struct.unpack_from("<IiiHH", blob, 0)
            assert (size, bw, bh, bits) == (40, w, 2 * w, 32)
    png = (ROOT / "autopress" / "resources" / "icon.png").read_bytes()
    assert png.startswith(b"\x89PNG") and struct.unpack(">II", png[16:24]) == (256, 256)


def test_qt_reads_the_icon(qapp: object) -> None:
    from PyQt6.QtGui import QIcon, QImageReader

    path = str(ROOT / "autopress" / "resources" / "icon.ico")
    assert b"ico" in [bytes(f) for f in QImageReader.supportedImageFormats()]
    sizes = {s.width() for s in QIcon(path).availableSizes()}
    assert {16, 32, 48, 256} <= sizes


def test_make_icon_renders_the_committed_drawing(tmp_path: Path, qapp: object) -> None:
    from PIL import Image

    from tools import make_icon

    assert make_icon.main(["--out-dir", str(tmp_path)]) == 0
    fresh = _ico_entries((tmp_path / "icon.ico").read_bytes())
    committed = _ico_entries((ROOT / "autopress" / "resources" / "icon.ico").read_bytes())
    assert [w for w, _ in fresh] == [w for w, _ in committed]
    import numpy as np

    a = Image.open(tmp_path / "icon.png").convert("RGBA")
    b = Image.open(ROOT / "autopress" / "resources" / "icon.png").convert("RGBA")
    diff = int(np.abs(np.asarray(a, np.int16) - np.asarray(b, np.int16)).max())
    assert diff <= 16, "the committed icon differs from tools/make_icon.py: re-run the tool"
    assert a.getpixel((128, 30))[:3] == (47, 102, 240)  # accent_fill
    assert a.getpixel((2, 2))[3] == 0  # transparent margin


# ============================================================================= licences

# licenses/<file> -> the installed file it must equal byte for byte (SPEC 10.2: never retyped)
LICENCE_SOURCES = {
    "PyQt6-LICENSE.txt": SITE / "pyqt6-6.12.1.dist-info/licenses/LICENSE",
    "PyQt6-Qt6-LICENSE.txt": SITE / "pyqt6_qt6-6.12.0.dist-info/LICENSE",
    "PyQt6_sip-LICENSE.txt": SITE / "pyqt6_sip-13.13.1.dist-info/licenses/LICENSE",
    "PyInstaller-LICENSE.txt": SITE / "pyinstaller-6.22.3.dist-info/licenses/COPYING.txt",
    "Python-LICENSE.txt": Path(sys.base_prefix) / "LICENSE.txt",
    "rapidocr-LICENSE.txt": SITE / "rapidocr-3.10.0.dist-info/licenses/LICENSE",
    "rapidocr-MODEL_LICENSES.md": SITE / "rapidocr-3.10.0.dist-info/licenses/MODEL_LICENSES.md",
    "onnxruntime-LICENSE.txt": SITE / "onnxruntime/LICENSE",
    "onnxruntime-ThirdPartyNotices.txt": SITE / "onnxruntime/ThirdPartyNotices.txt",
    "opencv-python-headless-LICENSE.txt": SITE / "opencv_python_headless-5.0.0.93.dist-info/LICENSE.txt",
    "opencv-python-headless-LICENSE-3RD-PARTY.txt": SITE / "opencv_python_headless-5.0.0.93.dist-info/LICENSE-3RD-PARTY.txt",
    "numpy-LICENSE.txt": SITE / "numpy-2.5.5.dist-info/licenses/LICENSE.txt",
    "Pillow-LICENSE.txt": SITE / "pillow-13.0.0.dist-info/licenses/LICENSE",
    "mss-LICENSE.txt": SITE / "mss-10.2.0.dist-info/licenses/LICENSE.txt",
    "shapely-LICENSE.txt": SITE / "shapely-2.2.0.dist-info/licenses/LICENSE.txt",
    "shapely-LICENSE_GEOS.txt": SITE / "shapely-2.2.0.dist-info/licenses/LICENSE_GEOS",
    "shapely-LICENSE_win32.txt": SITE / "shapely-2.2.0.dist-info/licenses/LICENSE_win32",
    "pyclipper-LICENSE.txt": SITE / "pyclipper-1.4.0.dist-info/licenses/LICENSE",
    "omegaconf-LICENSE.txt": SITE / "omegaconf-2.4.0.dist-info/licenses/LICENSE",
    "omegaconf-LICENSE-antlr4.txt": SITE / "omegaconf-2.4.0.dist-info/licenses/ATTRIBUTION/LICENSE-antlr4",
    "PyYAML-LICENSE.txt": SITE / "pyyaml-6.0.3.dist-info/licenses/LICENSE",
    "protobuf-LICENSE.txt": SITE / "protobuf-7.36.2.dist-info/LICENSE",
    "flatbuffers-LICENSE-Apache-2.0.txt": SITE / "packaging-26.3.dist-info/licenses/LICENSE.APACHE",
    "requests-LICENSE.txt": SITE / "requests-2.34.2.dist-info/licenses/LICENSE",
    "requests-NOTICE.txt": SITE / "requests-2.34.2.dist-info/licenses/NOTICE",
    "urllib3-LICENSE.txt": SITE / "urllib3-2.8.0.dist-info/licenses/LICENSE.txt",
    "idna-LICENSE.md": SITE / "idna-3.20.dist-info/licenses/LICENSE.md",
    "certifi-LICENSE.txt": SITE / "certifi-2026.10.23.dist-info/licenses/LICENSE",
    "charset_normalizer-LICENSE.txt": SITE / "charset_normalizer-3.5.2.dist-info/licenses/LICENSE",
    "tqdm-LICENCE.txt": SITE / "tqdm-4.70.1.dist-info/licenses/LICENCE",
    "colorlog-LICENSE.txt": SITE / "colorlog-6.12.0.dist-info/licenses/LICENSE",
    "colorama-LICENSE.txt": SITE / "colorama-0.4.6.dist-info/licenses/LICENSE.txt",
    "six-LICENSE.txt": SITE / "six-1.17.0.dist-info/LICENSE",
    "packaging-LICENSE.txt": SITE / "packaging-26.3.dist-info/licenses/LICENSE",
    "packaging-LICENSE.APACHE.txt": SITE / "packaging-26.3.dist-info/licenses/LICENSE.APACHE",
    "packaging-LICENSE.BSD.txt": SITE / "packaging-26.3.dist-info/licenses/LICENSE.BSD",
}
COMPILED_LICENCES = {"Python-3.12.10-incorporated-software.txt", "Qt-6.12.0-third-party-notices.txt"}

# THIRD-PARTY-NOTICES.md table row label -> distribution whose installed version it must name
NOTICE_VERSIONS = {
    "PyQt6": "PyQt6", "PyQt6-Qt6": "PyQt6-Qt6", "PyQt6_sip": "PyQt6_sip", "PyInstaller": "pyinstaller",
    "rapidocr": "rapidocr", "onnxruntime": "onnxruntime", "opencv-python-headless": "opencv-python-headless",
    "numpy": "numpy", "Pillow": "pillow", "mss": "mss", "shapely": "shapely", "pyclipper": "pyclipper",
    "omegaconf": "omegaconf", "PyYAML": "PyYAML", "protobuf": "protobuf", "flatbuffers": "flatbuffers",
    "requests": "requests", "urllib3": "urllib3", "idna": "idna", "certifi": "certifi",
    "charset-normalizer": "charset-normalizer", "tqdm": "tqdm", "colorlog": "colorlog", "colorama": "colorama",
    "six": "six", "packaging": "packaging",
}


def test_licence_texts_are_unchanged_copies_of_the_installed_files() -> None:
    files = {p.name for p in LICENSES.iterdir() if p.is_file()}
    assert files == set(LICENCE_SOURCES) | COMPILED_LICENCES
    for name, src in LICENCE_SOURCES.items():
        assert (LICENSES / name).read_bytes() == src.read_bytes(), name
    vendored = SITE / "numpy-2.5.5.dist-info/licenses/numpy"
    expected = sorted(p.relative_to(vendored).as_posix() for p in vendored.rglob("*") if p.is_file())
    copied = sorted(p.relative_to(LICENSES / "numpy").as_posix() for p in (LICENSES / "numpy").rglob("*") if p.is_file())
    assert copied == expected
    for rel in expected:
        assert (LICENSES / "numpy" / rel).read_bytes() == (vendored / rel).read_bytes(), rel


def test_compiled_licence_files_name_their_sources() -> None:
    qt = (LICENSES / "Qt-6.12.0-third-party-notices.txt").read_text(encoding="utf-8")
    assert qt.startswith("Third-party notices for Qt 6.12.0")
    assert "qtbase-everywhere-src-6.12.0.tar.xz" in qt and "sha256 a951bd163c7b80fc" in qt
    assert importlib.metadata.version("PyQt6-Qt6") == "6.12.0"
    for name in ("Wintab API", "HarfBuzz-NG", "Freetype 2", "PCRE2", "Unicode Character Database (UCD)", "LibPNG"):
        assert f". {name}\n" in qt, name
    py = (LICENSES / "Python-3.12.10-incorporated-software.txt").read_text(encoding="utf-8")
    assert "CPython tag v3.12.10" in py.splitlines()[0]
    assert sys.version_info[:3] == (3, 12, 10)


def test_license_is_the_gpl3_text() -> None:
    lic = (ROOT / "LICENSE").read_bytes()
    assert lic == (LICENSES / "PyQt6-LICENSE.txt").read_bytes()
    head = lic.decode("utf-8")[:200]
    assert "GNU GENERAL PUBLIC LICENSE" in head and "Version 3, 29 June 2007" in head


def test_notices_link_every_licence_file_and_name_the_installed_versions() -> None:
    text = NOTICES.read_text(encoding="utf-8")
    links = set(re.findall(r"\]\((licenses/[^)#]+)\)", text))
    for link in links:
        assert (ROOT / link).exists(), link
    linked = {Path(link).name for link in links}
    for p in LICENSES.iterdir():
        if p.is_file():
            assert p.name in linked, f"licenses/{p.name} is not mentioned in THIRD-PARTY-NOTICES.md"
    assert "licenses/numpy/" in links
    rows = {m.group(1).split(" (")[0].strip(): m.group(2).strip()
            for m in re.finditer(r"^\| ([^|]+) \| ([^|]+) \|", text, re.M)}
    for label, dist in NOTICE_VERSIONS.items():
        assert rows.get(label) == importlib.metadata.version(dist), label
    assert rows["Python"] == ".".join(map(str, sys.version_info[:3]))
    for word in ("GEOS", "PP-OCRv6", "FreeType", "GPL-3.0", "LGPL-3.0", "Corresponding Source"):
        assert word in text, word


def test_gitattributes_keeps_licence_files_byte_exact() -> None:
    text = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert re.search(r"^licenses/\*\* -text$", text, re.M) and re.search(r"^LICENSE -text$", text, re.M)
    if shutil.which("git") is None:
        return
    res = subprocess.run(["git", "check-attr", "text", "--", "licenses/Python-LICENSE.txt", "build.ps1"],
                         cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert "licenses/Python-LICENSE.txt: text: unset" in res.stdout
    assert "build.ps1: text: set" in res.stdout


# ============================================================================= README and user guide

LOCAL_LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)\)")


def _local_links(md: Path) -> list[str]:
    return [t for t in LOCAL_LINK.findall(md.read_text(encoding="utf-8"))
            if not re.match(r"[a-z]+:", t) and not t.startswith("#")]


def test_readme_opens_with_unzip_smartscreen_and_antivirus_steps() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    first = text[: text.index("## 它能做什麼")]
    for needle in ("下載後先解壓縮", "Windows 已保護您的電腦", "其他資訊", "仍要執行", "防毒軟體",
                   "Source code (zip)"):  # the Releases page always offers the source zip next to the asset
        assert needle in first, needle
    assert "https://github.com/Stardust-mio/AUTOPRESS/releases/latest" in text  # PX-21: public repo + Releases
    assert "## 能用在哪裡" in text  # where it works, limits, tested status (requirements item 10)
    assert "## Quick start (English)" in text and "Run anyway" in text and "Unzip first" in text
    assert "docs/user_guide.md" in text and "portable.txt" in text
    assert "<img" not in text.lower()


def test_user_guide_opens_with_download_unzip_and_smartscreen_then_the_first_run_order() -> None:
    guide = ROOT / "docs" / "user_guide.md"
    if not guide.is_file():
        pytest.skip("docs/user_guide.md is written after integration (real screenshots, SPEC 10.4)")
    text = guide.read_text(encoding="utf-8")
    first = text[: text.index("## 目錄")]
    for needle in ("下載後先解壓縮", "Source code (zip)", "Windows 已保護您的電腦", "其他資訊", "仍要執行", "防毒軟體",
                   "https://github.com/Stardust-mio/AUTOPRESS/blob/main/docs/user_guide.md"):  # the zip copy has no pictures
        assert needle in first, needle
    order = [text.index(h) for h in ("## 第一次使用：照這個順序", "## 第一次開啟", "## 設定檔與設定精靈", "## 加入序號",
                                      "## 開始兌換")]
    assert order == sorted(order)  # the chapters follow the first-run order: profile before codes


def test_user_guide_images_carry_the_manifest_captions_in_order() -> None:
    """Each image of docs/images/shots.json appears once, in manifest order, followed by its numbered captions
    exactly as tools/screenshots.py draws them (the guide's captions are the manifest's texts)."""
    guide = ROOT / "docs" / "user_guide.md"
    if not guide.is_file():
        pytest.skip("docs/user_guide.md is written after integration (real screenshots, SPEC 10.4)")
    text = guide.read_text(encoding="utf-8")
    manifest = json.loads((ROOT / "docs" / "images" / "shots.json").read_text(encoding="utf-8"))
    pos = -1
    for img in manifest["images"]:
        captions = [f"{c['n']}. {c['text'].strip()}" for c in sorted(img["callouts"], key=lambda c: c["n"])]
        block = "\n".join([f"![{img['alt']}](images/{img['name']}.png)", "", *captions])
        assert text.count(f"(images/{img['name']}.png)") == 1, img["name"]
        at = text.find(block)
        assert at > pos, f"{img['name']}: image block missing, changed or out of order"
        pos = at
        assert (guide.parent / "images" / f"{img['name']}.png").is_file(), img["name"]


SHIPPED_DOCS = ("README.md", "CHANGELOG.md", "THIRD-PARTY-NOTICES.md", "docs/user_guide.md")


def _in_release_zip(rel: str) -> bool:
    """build.ps1 stages README, LICENSE, THIRD-PARTY-NOTICES.md, CHANGELOG.md, licenses/, docs/user_guide.md
    and the top-level docs/images/*.png - nothing else of the repo (no SPEC.md, no docs/images/raw/)."""
    if rel in ("README.md", "LICENSE", "THIRD-PARTY-NOTICES.md", "CHANGELOG.md", "docs/user_guide.md", "licenses"):
        return True
    return rel.startswith("licenses/") or re.fullmatch(r"docs/images/[^/]+\.png", rel) is not None


@pytest.mark.parametrize("doc", SHIPPED_DOCS)
def test_shipped_docs_link_only_files_that_are_in_the_zip(doc: str) -> None:
    md = ROOT / doc
    if not md.is_file():
        pytest.skip(f"{doc} not written yet")
    build = BUILD_PS1.read_text(encoding="utf-8-sig")
    assert "'README.md', 'LICENSE', 'THIRD-PARTY-NOTICES.md', 'CHANGELOG.md'" in build and "docs\\user_guide.md" in build
    for target in _local_links(md):
        path = target.split("#", 1)[0]
        if not path:
            continue
        rel = (md.parent / path).resolve().relative_to(ROOT.resolve()).as_posix()
        assert _in_release_zip(rel), f"{doc}: {target} is not in the release zip; link it by its GitHub URL"


def test_settings_about_names_the_repository_the_docs_link() -> None:
    from autopress.ui.settings_page import REPO_URL

    assert f"{REPO_URL}/releases/latest" in (ROOT / "README.md").read_text(encoding="utf-8")
    assert "發佈後提供連結" not in (ROOT / "autopress" / "ui" / "settings_page.py").read_text(encoding="utf-8")


@pytest.mark.parametrize("doc", ["README.md", "THIRD-PARTY-NOTICES.md", "CHANGELOG.md", "docs/user_guide.md"])
def test_local_links_and_images_exist(doc: str) -> None:
    md = ROOT / doc
    if not md.is_file():
        pytest.skip(f"{doc} not written yet (needs real screenshots after integration, SPEC 10.4)")
    for target in _local_links(md):
        path = target.split("#", 1)[0]
        assert not path.startswith("/") and "\\" not in path and ":" not in path, target
        if path == "docs/user_guide.md" and not (ROOT / path).exists():
            continue  # linked from README before the guide exists (written at integration)
        assert (md.parent / path).exists(), f"{doc}: {target}"


def test_user_guide_images_are_real_relative_and_exist() -> None:
    guide = ROOT / "docs" / "user_guide.md"
    if not guide.is_file():
        pytest.skip("docs/user_guide.md is written after integration (real screenshots, SPEC 10.4)")
    text = guide.read_text(encoding="utf-8")
    images = re.findall(r"!\[[^\]]*\]\(([^)\s]+)\)", text)
    assert images, "the guide is made of annotated screenshots"
    assert "<img" not in text.lower()
    for img in images:
        assert img.startswith("images/") and img.endswith(".png"), img
        assert "design-preview" not in img and "research" not in img
        assert (guide.parent / img).is_file(), img

