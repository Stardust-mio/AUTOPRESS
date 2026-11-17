# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the rapidocr packaging test (one-folder, windowed).
# Build (venv with rapidocr==3.10.0, onnxruntime==1.32.0, pyinstaller==6.22.3, pyinstaller-hooks-contrib==2026.10):
#   python -m PyInstaller --noconfirm --clean --distpath DIST --workpath WORK ocrpack.spec
# Run:  DIST/ocrpack/ocrpack.exe RESULT.json   (writes the OCR texts + timings, or the traceback)
# Set OCRPACK_ONEFILE=1 to build a single exe instead (used to measure the onefile size).
import os

from PyInstaller.utils.hooks import collect_data_files

ONEFILE = os.environ.get("OCRPACK_ONEFILE") == "1"
ROOT = os.path.abspath(SPECPATH)  # noqa: F821

# rapidocr needs config.yaml, default_models.yaml and models/*.onnx at runtime
datas = collect_data_files("rapidocr", excludes=["**/pytorch/**", "**/__pycache__/**"])

a = Analysis(  # noqa: F821
    [os.path.join(ROOT, "pack_test_app.py")],
    datas=datas,
    excludes=["torch", "paddle", "openvino", "tensorrt", "MNN", "tkinter", "matplotlib", "IPython"],
    noarchive=False,
)
# OpenCV's FFmpeg video plugin (31 MB) is never used by OCR
a.binaries = [b for b in a.binaries if "opencv_videoio_ffmpeg" not in b[0].lower()]
pyz = PYZ(a.pure)  # noqa: F821
opts = dict(name="ocrpack", debug=False, strip=False, upx=False, console=False)
if ONEFILE:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], runtime_tmpdir=None, **opts)  # noqa: F821
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **opts)  # noqa: F821
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="ocrpack")  # noqa: F821
