"""AutoPress OCR recipe (rapidocr 3.10.0 + onnxruntime 1.32.0) with a self-test.

    python autopress_ocr_recipe.py --selftest OUT_JSON [--qthread]

The block between BEGIN/END RECIPE is copied verbatim into docs/research/ocr.md.
"""
# --- BEGIN RECIPE ---
import string
import unicodedata
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

def load_image_bgr(path):
    """Any Pillow format; the path may contain Chinese. Returns HxWx3 uint8 BGR."""
    with Image.open(path) as im:
        rgb = np.asarray(ImageOps.exif_transpose(im).convert("RGB"))
    return np.ascontiguousarray(rgb[:, :, ::-1])

def create_engine(model_dir, threads=-1, det_side=960):
    """One engine per OCR worker thread. Explicit paths = offline, no download/SHA256 step.
    det_side: never upscale, shrink inputs whose long side exceeds it (1920 for full screens)."""
    from rapidocr import RapidOCR
    d = Path(model_dir)
    return RapidOCR(params={
        "Global.log_level": "error",  # silent (a windowed exe has sys.stderr = None)
        "Global.use_cls": False,  # screen text is upright
        "Det.model_path": str(d / "PP-OCRv6_det_small.onnx"),
        "Rec.model_path": str(d / "PP-OCRv6_rec_small.onnx"),
        "Det.limit_type": "max", "Det.limit_side_len": det_side,
        "EngineConfig.onnxruntime.intra_op_num_threads": threads})  # -1 = ORT default

def run_ocr(engine, img_bgr, k=1):
    """-> [(text, quad float32 4x2 tl,tr,br,bl in input pixels, score)]; k = upscale factor."""
    if k > 1:
        h, w = img_bgr.shape[:2]
        pil = Image.fromarray(img_bgr[:, :, ::-1]).resize((w * k, h * k), Image.Resampling.BICUBIC)
        img_bgr = np.ascontiguousarray(np.asarray(pil)[:, :, ::-1])
    res = engine(img_bgr)
    if getattr(res, "boxes", None) is None or getattr(res, "txts", None) is None:
        return []
    return [(t, np.asarray(b, np.float32).reshape(4, 2) / k, float(s))
            for b, t, s in zip(res.boxes, res.txts, res.scores)]

def _norm(s):
    return "".join(c for c in unicodedata.normalize("NFKC", s) if not c.isspace()).casefold()

def find_text_center(items, target, exact=True):
    """Click point (x, y) for `target`: best box whose text equals it (exact) or contains it
    (exact=False -> proportional sub-box, CJK chars count double). None if not found."""
    t, best = _norm(target), None
    for text, quad, score in items:
        n = _norm(text)
        i = n.find(t)
        if not t or i < 0 or (exact and n != t):
            continue
        w = [2.0 if unicodedata.east_asian_width(c) in "WF" else 1.0 for c in n]
        a, b = sum(w[:i]) / sum(w), sum(w[:i + len(t)]) / sum(w)
        tl, tr, br, bl = quad
        cx = (tl[0] + (tr[0] - tl[0]) * (a + b) / 2 + bl[0] + (br[0] - bl[0]) * (a + b) / 2) / 2
        cy = float(quad[:, 1].mean())
        if best is None or (n == t, score) > best[0]:
            best = ((n == t, score), (float(cx), cy))
    return best[1] if best else None

def recognize_code_line(engine, img_bgr, quad, allowed=string.ascii_uppercase + string.digits + "-"):
    """Re-read one detected line with Latin-looking characters forced into `allowed`
    (charset-constrained CTC). Returns (text, per-character confidences)."""
    from rapidocr.utils.process_img import get_rotate_crop_image
    rec = engine._load_rec_model()  # internal API, pinned to rapidocr==3.10.0
    crop = get_rotate_crop_image(img_bgr, np.asarray(quad, np.float32).copy())
    _, ih, iw = rec.rec_image_shape
    x = rec.resize_norm_img(crop, max(iw / ih, crop.shape[1] / crop.shape[0]))[None]
    probs = rec.session(x.astype(np.float32))[0]  # (T, C) softmax
    chars = rec.postprocess_op.character  # index 0 = CTC blank
    latin = set(string.ascii_letters + string.digits + "-|!$")
    ok = np.array([i for i, c in enumerate(chars) if i and c in allowed])
    top = probs.argmax(1)
    pick = [ok[probs[t, ok].argmax()] if k and chars[k] in latin else k for t, k in enumerate(top)]
    text, confs, prev = [], [], 0
    for t, k in enumerate(pick):
        if k and k != prev:
            text.append(chars[k])
            confs.append(float(probs[t, k]))
        prev = k
    return "".join(text), confs
# --- END RECIPE ---

import sys  # noqa: E402  (self-test only)


def _selftest(out_json, use_qthread):
    import json
    import time
    from PIL import ImageDraw, ImageFont

    import rapidocr
    model_dir = Path(rapidocr.__file__).parent / "models"
    font = "C:/Windows/Fonts/msjh.ttc"

    def card(text, size=28, w=640, h=200, dark=True):
        img = Image.new("RGB", (w, h), (24, 26, 36) if dark else (245, 245, 245))
        ImageDraw.Draw(img).text((30, h // 2), text, font=ImageFont.truetype(font, size), anchor="lm",
                                 fill=(240, 240, 240) if dark else (20, 20, 20))
        return np.ascontiguousarray(np.asarray(img)[:, :, ::-1])

    def dialog(size):
        img = Image.new("RGB", (800, 500), (25, 28, 40))
        d = ImageDraw.Draw(img)
        f = ImageFont.truetype(font, size)
        d.text((120, 175), "請輸入兌換碼", font=f, fill=(200, 200, 205), anchor="ls")
        for cx, lab, fill, fg in [(290, "兌換", (214, 164, 60), (40, 25, 0)), (510, "取消", (78, 82, 98), (245, 245, 245))]:
            d.rounded_rectangle((cx - 60, 370, cx + 60, 410), radius=8, fill=fill)
            d.text((cx, 390), lab, font=f, fill=fg, anchor="mm")
        return np.ascontiguousarray(np.asarray(img)[:, :, ::-1])

    report = {}
    tmp_dir = Path(out_json).parent / "測試路徑_recipe"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    img_path = tmp_dir / "序號截圖.png"
    Image.fromarray(card("兌換碼：AB0O-1Il5-S8B2")[:, :, ::-1]).save(img_path)

    def work():
        r = {}
        t0 = time.perf_counter()
        eng = create_engine(model_dir)
        img = load_image_bgr(img_path)
        items = run_ocr(eng, img)
        r["init_plus_first_s"] = round(time.perf_counter() - t0, 2)
        r["u1_items"] = [[t, q.round(1).tolist(), round(s, 3)] for t, q, s in items]
        code_line = [it for it in items if "-" in it[0]]
        r["u1_constrained"] = recognize_code_line(eng, img, code_line[0][1]) if code_line else None
        dlg = dialog(14)
        t1 = time.perf_counter()
        items2 = run_ocr(eng, dlg)
        r["u2_ms"] = round((time.perf_counter() - t1) * 1000)
        r["u2_items"] = [[t, q.round(1).tolist(), round(s, 3)] for t, q, s in items2]
        r["u2_center_兌換"] = find_text_center(items2, "兌換")
        r["u2_center_取消"] = find_text_center(items2, "取消")
        r["u2_center_label_substring_兌換碼"] = find_text_center(items2, "兌換碼", exact=False)
        r["u2_small12_up2_center_兌換"] = find_text_center(run_ocr(eng, dialog(12), k=2), "兌換")
        r["u3_texts"] = [t for t, _, _ in run_ocr(eng, card("序號已被使用", 18, 360, 120, dark=False))]
        return r

    if use_qthread:
        from PyQt6.QtCore import QCoreApplication, QThread, QTimer
        app = QCoreApplication.instance() or QCoreApplication(sys.argv)
        box = {}

        class Worker(QThread):
            def run(self):
                try:
                    box["r"] = work()
                    box["thread_is_main"] = QThread.currentThread() is app.thread()
                except Exception:  # noqa: BLE001
                    import traceback
                    box["error"] = traceback.format_exc()

        w = Worker()
        w.finished.connect(app.quit)
        QTimer.singleShot(120000, app.quit)
        w.start()
        app.exec()
        w.wait(5000)
        if "error" in box:
            raise RuntimeError(box["error"])
        report = box["r"]
        report["ran_in_qthread"] = box.get("thread_is_main") is False
    else:
        report = work()

    c1, c2 = report["u2_center_兌換"], report["u2_center_取消"]
    checks = {
        "u1_code_read": any("AB0O-1" in t for t, _, _ in report["u1_items"]),
        "u2_兌換_center_in_button": bool(c1 and 230 <= c1[0] <= 350 and 370 <= c1[1] <= 410),
        "u2_取消_center_in_button": bool(c2 and 450 <= c2[0] <= 570 and 370 <= c2[1] <= 410),
        "u2_small12_up2_in_button": bool(report["u2_small12_up2_center_兌換"] and
                                         230 <= report["u2_small12_up2_center_兌換"][0] <= 350),
        "u3_read": "序號已被使用" in "".join(report["u3_texts"]),
    }
    report["checks"] = checks
    report["versions"] = {"python": sys.version.split()[0], "rapidocr": rapidocr.__version__ if hasattr(rapidocr, "__version__") else None}
    import importlib.metadata as md
    for p in ("rapidocr", "onnxruntime", "opencv-python-headless", "numpy", "Pillow", "PyQt6"):
        try:
            report["versions"][p] = md.version(p)
        except md.PackageNotFoundError:
            report["versions"][p] = None
    Path(out_json).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("checks:", checks)
    return all(checks.values())


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--selftest":
        sys.exit(0 if _selftest(sys.argv[2], "--qthread" in sys.argv) else 1)
    print(__doc__)
