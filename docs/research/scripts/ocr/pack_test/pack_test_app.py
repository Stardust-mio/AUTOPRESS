"""Minimal windowed app used to verify that rapidocr + onnxruntime survive PyInstaller.

Build (from this folder, with a venv that has rapidocr, onnxruntime, pyinstaller):
    python -m PyInstaller --noconfirm --clean --distpath DIST --workpath WORK ocrpack.spec
Run:  DIST/ocrpack/ocrpack.exe RESULT.json   -> writes texts + timings (or the traceback)
"""
import json
import sys
import time
from pathlib import Path

t0 = time.perf_counter()
BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
out = {"frozen": bool(getattr(sys, "frozen", False)), "stdout_is_none": sys.stdout is None,
       "stderr_is_none": sys.stderr is None}
try:
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    from rapidocr import RapidOCR

    t1 = time.perf_counter()
    md = BASE / "rapidocr" / "models"
    eng = RapidOCR(params={"Global.log_level": "error", "Global.use_cls": False,
                           "Det.model_path": str(md / "PP-OCRv6_det_small.onnx"),
                           "Rec.model_path": str(md / "PP-OCRv6_rec_small.onnx")})
    img = Image.new("RGB", (640, 200), (24, 26, 36))
    ImageDraw.Draw(img).text((30, 100), "兌換碼：AB12-CD34-EF56", anchor="lm", fill=(240, 240, 240),
                             font=ImageFont.truetype("C:/Windows/Fonts/msjh.ttc", 28))
    res = eng(np.asarray(img)[:, :, ::-1].copy())
    res_empty = eng(np.zeros((200, 400, 3), np.uint8))  # exercises the logger.warning path
    t2 = time.perf_counter()
    out.update(ok=True, texts=list(res.txts or []), empty=list(getattr(res_empty, "txts", None) or []),
               import_s=round(t1 - t0, 2), total_s=round(t2 - t0, 2))
except Exception:  # noqa: BLE001
    import traceback
    out.update(ok=False, error=traceback.format_exc())
Path(sys.argv[1]).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
