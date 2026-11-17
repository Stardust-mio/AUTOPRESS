# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for AutoPress (SPEC 10.1). OWNED BY G8.
#
# Build: build.ps1 (clean build, self-tests, zip), or
#        .venv\Scripts\python.exe -m PyInstaller --noconfirm --clean autopress.spec
# Output: dist\AutoPress\AutoPress.exe + dist\AutoPress\_internal\ - a one-folder build (starts
#         in 4.3-4.8 s with OCR against 7.8 s for onefile, no %TEMP% extraction); ship the folder.
#
# Windowed (no console), asInvoker (never asks for admin rights; restart_as_admin is a user
# choice), no UPX, icon + version resource (generated from autopress.__version__ into
# version_info.txt). Bundled data: rapidocr's config files and PP-OCRv6 models
# (collect_data_files, docs/research/ocr.md 6) and autopress/resources (templates, icon).
# Left out: OpenCV's FFmpeg plugin (31 MB, LGPL, unused), Pillow's AVIF codec (7.9 MB), Qt
# modules / plugins AutoPress never uses (QtSvg stays: the icons are SVG), every Qt translation
# except qtbase_zh_TW. tests/test_packaging.py executes this file with stand-ins for Analysis /
# EXE / COLLECT and checks the filters and options below.

import fnmatch
import os
import sys

from PyInstaller.utils.hooks import collect_data_files

ROOT = os.path.abspath(SPECPATH)  # noqa: F821 - defined by PyInstaller
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
import autopress  # noqa: E402 - importing the package has no side effects (version only)

APP_NAME = "AutoPress"
ENTRY = os.path.join(ROOT, "main.py")
ICON = os.path.join(ROOT, "autopress", "resources", "icon.ico")
VERSION_FILE = os.path.join(ROOT, "version_info.txt")
if not os.path.isfile(ICON):
    raise SystemExit(f"{ICON} is missing - run: .venv\\Scripts\\python.exe tools\\make_icon.py")

# Python modules kept out of the bundle (never imported at run time).
EXCLUDES = [
    # other GUI toolkits, dev / test / packaging tools
    "tkinter", "_tkinter", "turtle", "turtledemo", "idlelib", "pydoc_data", "lib2to3",
    "ensurepip", "venv", "pip", "setuptools", "pkg_resources", "distutils", "_distutils_hack",
    "pytest", "_pytest", "pytestqt", "pluggy", "iniconfig", "pygments", "PyInstaller",
    "IPython", "matplotlib",
    # inference back ends rapidocr can use but AutoPress does not (it runs onnxruntime)
    "torch", "paddle", "openvino", "tensorrt", "MNN",
    # Pillow's AVIF codec (7.9 MB): AvifImagePlugin handles the missing module
    "PIL._avif",
]
# Qt modules AutoPress never imports (SPEC 10.1); QtCore / QtGui / QtWidgets / QtSvg stay.
QT_EXCLUDES = [
    "PyQt6.QtQml", "PyQt6.QtQuick", "PyQt6.QtQuickWidgets", "PyQt6.QtQuick3D",
    "PyQt6.QtWebEngineCore", "PyQt6.QtWebEngineWidgets", "PyQt6.QtWebEngineQuick", "PyQt6.QtWebChannel",
    "PyQt6.QtWebSockets", "PyQt6.QtMultimedia", "PyQt6.QtMultimediaWidgets", "PyQt6.QtSpatialAudio",
    "PyQt6.Qt3DCore", "PyQt6.Qt3DRender", "PyQt6.Qt3DInput", "PyQt6.Qt3DLogic", "PyQt6.Qt3DAnimation",
    "PyQt6.Qt3DExtras", "PyQt6.QtBluetooth", "PyQt6.QtNfc", "PyQt6.QtPositioning", "PyQt6.QtSql",
    "PyQt6.QtTest", "PyQt6.QtDesigner", "PyQt6.QtHelp", "PyQt6.QtOpenGL", "PyQt6.QtOpenGLWidgets",
    "PyQt6.QtPdf", "PyQt6.QtPdfWidgets", "PyQt6.QtSensors", "PyQt6.QtSerialPort", "PyQt6.QtRemoteObjects",
    "PyQt6.QtTextToSpeech", "PyQt6.QtDBus", "PyQt6.QtXml", "PyQt6.QtStateMachine", "PyQt6.uic",
]

# Qt files kept from what the PyQt6 hooks collect (paths below PyQt6/Qt6/).
KEEP_QT_PLUGINS = {
    "platforms/qwindows.dll",  # the Windows platform integration
    "imageformats/qico.dll",  # .ico files
    "imageformats/qsvg.dll",  # QImage / QPixmap from SVG data
    "iconengines/qsvgicon.dll",  # QIcon from SVG files
}
KEEP_QT_TRANSLATIONS = {"qtbase_zh_TW.qm"}  # Qt's own zh-TW strings (line-edit menu, dialogs)

# Binaries never needed (matched against the lower-case file name).
DROP_BINARIES = [
    "opencv_videoio_ffmpeg*.dll",  # OpenCV's FFmpeg video plugin: 31 MB, LGPL, OCR never reads video
    "opengl32sw.dll",  # software OpenGL renderer - QtWidgets paints with the raster engine
    "qt6pdf.dll",  # only for the dropped imageformats/qpdf plugin
    # Universal CRT: part of Windows 10+ (which Qt 6 requires anyway); without this rule a copy
    # can be picked up from another directory on PATH (e.g. an Anaconda install).
    "ucrtbase.dll",
    "api-ms-win-*.dll",
]
# Qt libraries dropped unless the matching PyQt6 module was imported: only dropped plugins
# (generic/qtuiotouchplugin, tls, networkinformation) pull them in otherwise.
DROP_UNLESS_IMPORTED = {"qt6network.dll": "PyQt6.QtNetwork"}

QT_PREFIX = "pyqt6/qt6/"


def _dest(entry):
    """Normalised (lower-case, forward slashes) bundle path of a TOC entry."""
    return entry[0].replace("\\", "/").lower()


def keep_binary(entry, imported=frozenset()):
    dest = _dest(entry)
    name = dest.rsplit("/", 1)[-1]
    if any(fnmatch.fnmatch(name, pattern) for pattern in DROP_BINARIES):
        return False
    if name in DROP_UNLESS_IMPORTED and DROP_UNLESS_IMPORTED[name] not in imported:
        return False
    if dest.startswith(QT_PREFIX + "plugins/"):
        return dest[len(QT_PREFIX + "plugins/"):] in {p.lower() for p in KEEP_QT_PLUGINS}
    return True


def keep_data(entry):
    dest = _dest(entry)
    if dest.startswith(QT_PREFIX + "translations/"):
        return dest.rsplit("/", 1)[-1] in {t.lower() for t in KEEP_QT_TRANSLATIONS}
    return True


def version_file_text(version, description):
    """Text of the Windows version resource (PyInstaller's VSVersionInfo format)."""
    v4 = tuple(int(n) for n in version) + (0,)
    s = ".".join(str(n) for n in v4[:3])
    return (
        "# -*- coding: utf-8 -*-\n"
        "# Windows version resource of AutoPress.exe. GENERATED by autopress.spec from\n"
        "# autopress.__version__ at every build - do not edit by hand.\n"
        "# Language 0x0404 = Chinese (Traditional, Taiwan); code page 1200 = Unicode (UTF-16).\n"
        "VSVersionInfo(\n"
        "  ffi=FixedFileInfo(\n"
        f"    filevers={v4},\n"
        f"    prodvers={v4},\n"
        "    mask=0x3f,\n"
        "    flags=0x0,\n"
        "    OS=0x40004,\n"
        "    fileType=0x1,\n"
        "    subtype=0x0,\n"
        "    date=(0, 0)\n"
        "  ),\n"
        "  kids=[\n"
        "    StringFileInfo([\n"
        "      StringTable(\n"
        "        '040404B0',\n"
        "        [\n"
        f"          StringStruct('CompanyName', '{APP_NAME}'),\n"
        f"          StringStruct('FileDescription', '{description}'),\n"
        f"          StringStruct('FileVersion', '{s}'),\n"
        f"          StringStruct('InternalName', '{APP_NAME}'),\n"
        f"          StringStruct('OriginalFilename', '{APP_NAME}.exe'),\n"
        f"          StringStruct('ProductName', '{APP_NAME}'),\n"
        f"          StringStruct('ProductVersion', '{s}'),\n"
        "        ],\n"
        "      )\n"
        "    ]),\n"
        "    VarFileInfo([VarStruct('Translation', [0x0404, 1200])]),\n"
        "  ]\n"
        ")\n"
    )


VERSION_TEXT = version_file_text(autopress.version_tuple(), autopress.APP_NAME_ZH)
if os.environ.get("AUTOPRESS_SPEC_CHECK") != "1":  # tests execute this file without writing
    _old = open(VERSION_FILE, encoding="utf-8").read() if os.path.isfile(VERSION_FILE) else None
    if _old != VERSION_TEXT:
        with open(VERSION_FILE, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(VERSION_TEXT)

def autopress_modules():
    """Every module of the autopress package, found on disk without importing anything: all of
    them are bundled, so the self-test's "modules" check can import each one in the exe."""
    out = []
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, "autopress")):
        dirnames[:] = sorted(d for d in dirnames if os.path.isfile(os.path.join(dirpath, d, "__init__.py")))
        package = os.path.relpath(dirpath, ROOT).replace(os.sep, ".")
        for name in sorted(filenames):
            if name.endswith(".py") and name != "__main__.py":
                out.append(package if name == "__init__.py" else f"{package}.{name[:-3]}")
    return out


DATAS = collect_data_files("rapidocr", excludes=["**/pytorch/**", "**/__pycache__/**"])
DATAS += [(os.path.join(ROOT, "autopress", "resources"), "autopress/resources")]
HIDDEN_IMPORTS = autopress_modules()

a = Analysis(  # noqa: F821
    [ENTRY],
    pathex=[ROOT],
    binaries=[],
    datas=DATAS,
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES + QT_EXCLUDES,
    noarchive=False,
    optimize=0,
)
IMPORTED = frozenset(entry[0] for entry in a.pure)
a.binaries = [entry for entry in a.binaries if keep_binary(entry, IMPORTED)]
a.datas = [entry for entry in a.datas if keep_data(entry)]

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=False,  # asInvoker manifest: AutoPress never needs admin rights (SPEC 9)
    icon=[ICON],
    version=VERSION_FILE,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, upx_exclude=[], name=APP_NAME)  # noqa: F821
