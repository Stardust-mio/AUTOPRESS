"""OCR backends for the AutoPress research benchmarks.

RapidBackend  - rapidocr 3.10.0 + onnxruntime 1.32.0, explicit local model paths, CPU.
WinOcrBackend - Windows.Media.Ocr via pywinrt 4.x (lives in a separate venv).
TessBackend   - Tesseract 5.5 via tesserocr 2.13 (separate venv; AUTOPRESS_TESSDATA = tessdata dir).
run(img_bgr) -> list of (text, quad float ndarray 4x2 [tl,tr,br,bl], score, char_confs|None).
"""
import os
import re
from pathlib import Path

import numpy as np

from ocr_common import ctc_constrained_decode

RAPID_MODELS = {  # name -> (det file, rec file)
    "v6s": ("PP-OCRv6_det_small.onnx", "PP-OCRv6_rec_small.onnx"),
    "v6t": ("PP-OCRv6_det_tiny.onnx", "PP-OCRv6_rec_tiny.onnx"),
    "v6m": ("PP-OCRv6_det_medium.onnx", "PP-OCRv6_rec_medium.onnx"),
    "v5m": ("ch_PP-OCRv5_det_mobile.onnx", "ch_PP-OCRv5_rec_mobile.onnx"),
    "v6s_kor": ("PP-OCRv6_det_small.onnx", "korean_PP-OCRv5_rec_mobile.onnx"),
}
LATIN_RUN = re.compile(r"[A-Za-z0-9\-|!$]{4,}")


def find_model(name, dirs):
    for d in dirs:
        p = Path(d) / name
        if p.is_file():
            return str(p)
    raise FileNotFoundError(name)


def default_model_dirs():
    import importlib.util
    spec = importlib.util.find_spec("rapidocr")
    dirs = [str(Path(spec.origin).parent / "models")] if spec else []
    extra = os.environ.get("AUTOPRESS_OCR_MODELS", "")
    return [d for d in extra.split(";") if d] + dirs


class RapidBackend:
    def __init__(self, variant="v6s", model_dirs=None, det_limit_type="min", det_limit_side_len=736,
                 use_cls=False, threads=-1):
        from rapidocr import RapidOCR
        dirs = list(model_dirs or []) + default_model_dirs()
        det, rec = RAPID_MODELS[variant]
        params = {
            "Global.log_level": "error",
            "Global.use_cls": use_cls,
            "Det.model_path": find_model(det, dirs),
            "Rec.model_path": find_model(rec, dirs),
            "Det.limit_type": det_limit_type,
            "Det.limit_side_len": det_limit_side_len,
            "EngineConfig.onnxruntime.intra_op_num_threads": threads,
        }
        if use_cls:
            params["Cls.model_path"] = find_model("ch_ppocr_mobile_v2.0_cls_mobile.onnx", dirs)
        self.engine = RapidOCR(params=params)
        self.name = "rapid_" + variant

    def run(self, img_bgr, char_boxes=False):
        if char_boxes:
            res = self.engine(img_bgr, return_word_box=True, return_single_char_box=True)
        else:
            res = self.engine(img_bgr)
        boxes, txts = getattr(res, "boxes", None), getattr(res, "txts", None)
        if boxes is None or txts is None or len(txts) == 0:
            return []
        scores = getattr(res, "scores", None) or [1.0] * len(txts)
        items = [(t, np.asarray(b, dtype=float).reshape(4, 2), float(s), None)
                 for b, t, s in zip(boxes, txts, scores)]
        if char_boxes:
            self.last_word_results = res.word_results
        return items

    # ---- constrained re-recognition of code-like lines (needs model probabilities)
    def rec_probs(self, crop_bgr):
        tr = self.engine._load_rec_model()
        _, img_h, img_w = tr.rec_image_shape
        h, w = crop_bgr.shape[:2]
        ratio = max(img_w / img_h, w / max(h, 1))
        x = tr.resize_norm_img(crop_bgr, ratio)[None].astype(np.float32)
        return tr.session(x)[0], tr.postprocess_op.character

    def run_constrained(self, img_bgr, allowed, items=None):
        from rapidocr.utils.process_img import get_rotate_crop_image
        items = self.run(img_bgr) if items is None else items
        out = []
        for text, quad, score, _ in items:
            if LATIN_RUN.search(text):
                crop = get_rotate_crop_image(img_bgr, quad.astype(np.float32).copy())
                probs, chars = self.rec_probs(crop)
                t2, confs = ctc_constrained_decode(probs, chars, set(allowed))
                out.append((t2, quad, score, confs))
            else:
                out.append((text, quad, score, None))
        return out


class WinOcrBackend:
    def __init__(self, lang_tag="zh-Hant-TW"):
        from winrt.windows.globalization import Language
        from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
        from winrt.windows.media.ocr import OcrEngine
        self._sb, self._fmt, self._alpha = SoftwareBitmap, BitmapPixelFormat.BGRA8, BitmapAlphaMode.PREMULTIPLIED
        self.engine = OcrEngine.try_create_from_language(Language(lang_tag))
        if self.engine is None:
            raise RuntimeError("Windows OCR language not installed: " + lang_tag)
        self.maxdim = int(OcrEngine.max_image_dimension)
        self.name = "win_" + lang_tag

    def run(self, img_bgr, words=False):
        h, w = img_bgr.shape[:2]
        scale = 1.0
        if max(h, w) > self.maxdim:
            from PIL import Image
            scale = self.maxdim / max(h, w)
            pil = Image.fromarray(img_bgr[:, :, ::-1]).resize((int(w * scale), int(h * scale)))
            img_bgr = np.asarray(pil)[:, :, ::-1]
            h, w = img_bgr.shape[:2]
        bgra = np.empty((h, w, 4), np.uint8)
        bgra[:, :, :3] = img_bgr
        bgra[:, :, 3] = 255
        sb = self._sb.create_copy_from_buffer(bgra.tobytes(), self._fmt, w, h, self._alpha)
        res = self.engine.recognize_async(sb).get()
        items = []
        for line in res.lines:
            rects = [(wd.text, wd.bounding_rect) for wd in line.words]
            quads = [np.array([[r.x, r.y], [r.x + r.width, r.y], [r.x + r.width, r.y + r.height],
                               [r.x, r.y + r.height]], dtype=float) / scale for _, r in rects]
            if words:
                items.extend((t, q, 1.0, None) for (t, _), q in zip(rects, quads))
            elif quads:
                allq = np.concatenate(quads)
                x0, y0 = allq.min(0)
                x1, y1 = allq.max(0)
                items.append((line.text, np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]]), 1.0, None))
        return items


class TessBackend:
    """Tesseract 5 via tesserocr (wheel bundles the DLLs; traineddata from tessdata_fast)."""

    def __init__(self, langs="eng+chi_tra", tessdata=None):
        import tesserocr
        self._t = tesserocr
        self.api = tesserocr.PyTessBaseAPI(path=tessdata or os.environ.get("AUTOPRESS_TESSDATA", ""), lang=langs)
        self.name = "tess_" + langs

    def run(self, img_bgr):
        from PIL import Image
        t = self._t
        self.api.SetImage(Image.fromarray(np.ascontiguousarray(img_bgr[:, :, ::-1])))
        self.api.Recognize()
        items = []
        for r in t.iterate_level(self.api.GetIterator(), t.RIL.TEXTLINE):
            text = (r.GetUTF8Text(t.RIL.TEXTLINE) or "").strip()
            box = r.BoundingBox(t.RIL.TEXTLINE)
            if text and box:
                x0, y0, x1, y1 = box
                items.append((text, np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=float),
                              r.Confidence(t.RIL.TEXTLINE) / 100.0, None))
        return items


def make_backend(name, model_dirs=None):
    """rapid_<variant>[@min736|@max960|...], win_<language tag> or tess_<langs>."""
    if name.startswith("tess_"):
        return TessBackend(name[len("tess_"):])
    if name.startswith("rapid_"):
        variant, _, det = name[len("rapid_"):].partition("@")
        kw = {}
        if det:
            kw = {"det_limit_type": det[:3], "det_limit_side_len": int(det[3:])}
        be = RapidBackend(variant, model_dirs=model_dirs, **kw)
        be.name = name
        return be
    if name.startswith("win_"):
        return WinOcrBackend(name[len("win_"):])
    raise ValueError(name)
