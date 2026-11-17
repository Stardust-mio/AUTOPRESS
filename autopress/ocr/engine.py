# OWNED BY G2
"""RapidOCR 3.10.0 + PP-OCRv6 small, offline from explicit model paths (ocr.md sections 1, 4).

Config: Global.log_level=error, Global.use_cls=False, Global.max_side_len=4096 (explicit: the
default 2000 silently shrinks larger inputs - and the recognition crops - before detection, so a
2x upscale of 1280x720 was read at 1.55x; T16, value UNVERIFIED: benchmark one 2560x1440 and one
3840x2160 screenshot and report latency and lines found), Det.limit_type=max,
Det.limit_side_len=det_side, explicit Det/Rec.model_path (no download, no hashing),
EngineConfig.onnxruntime.intra_op_num_threads=min(threads, os.cpu_count()) (-1 = default).
NOT thread-safe: one instance is owned by the OCR worker thread (service.py). rapidocr is
imported inside __init__ (lazy).

rapidocr keeps per-call overrides: NEVER pass call keyword overrides (``engine(img,
use_rec=False)`` disabled recognition for every later call - measured). A per-call det_side
sets ``text_det.limit_side_len`` (internal, pinned 3.10.0) and restores it in ``finally``; test
alternating det_side values.

Implementation notes:
* The detector and recognizer sessions are loaded in ``__init__`` (``_load_det_model`` /
  ``_load_rec_model``, internal, pinned 3.10.0), so a broken model file or ONNX Runtime raises
  OcrUnavailable at construction instead of failing every later call.
* ``OcrUnavailable``: ``str(exc)`` is the complete 7.1 sentence 「文字辨識引擎無法啟動：{reason}。…」,
  ``exc.reason`` the short localized reason (what ``OcrService.error`` reports).
* Every call holds an internal lock, so an accidental second thread waits instead of racing
  rapidocr's per-call state.
"""

from __future__ import annotations

import logging
import os
import re
import string
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from .. import paths
from ..i18n import tr
from ..models import OcrLine
from . import imageio

log = logging.getLogger(__name__)

DET_MODEL = "PP-OCRv6_det_small.onnx"
REC_MODEL = "PP-OCRv6_rec_small.onnx"
MAX_SIDE_LEN = 4096  # Global.max_side_len and the cap of every upscale (T16)
PINNED_RAPIDOCR = "3.10.0"

# Characters whose CTC frames the constrained re-read re-decides (recipe recognize_code_line).
LATIN_LIKE = frozenset(string.ascii_letters + string.digits + "-|!$")
# Lines worth a constrained re-read: a run of 4+ code-like characters (research LATIN_RUN).
CODE_LINE = re.compile(r"[A-Za-z0-9\-|!$]{4,}")


class OcrUnavailable(RuntimeError):
    """The engine cannot run (package or model files missing, ONNX Runtime failed).
    ``str(exc)`` is a localized message."""

    def __init__(self, message: str = "", reason: str = "") -> None:
        super().__init__(message)
        self.reason = reason or message


def unavailable_message(reason: str) -> str:
    """The 7.1 text 「文字辨識引擎無法啟動：{reason}。…」 in the UI language."""
    return tr("文字辨識引擎無法啟動：{reason}。請重新下載完整的壓縮檔並解壓縮，或檢查防毒軟體是否隔離了檔案。",
              "The OCR engine could not start: {reason}. Download and unzip the full package again, or check "
              "whether antivirus quarantined files.").format(reason=reason)


def unavailable(reason: str) -> OcrUnavailable:
    """OcrUnavailable carrying the full 7.1 sentence and the short ``reason``."""
    return OcrUnavailable(unavailable_message(reason), reason)


def short_error(exc: BaseException, limit: int = 160) -> str:
    """One-line ``Type: message`` (truncated) for reasons shown to the user and logged."""
    text = " ".join(f"{type(exc).__name__}: {exc}".split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _rapidocr_version() -> str:
    """rapidocr's version (its package does not export ``__version__``)."""
    try:
        from rapidocr._version import __version__

        return str(__version__)
    except Exception:  # noqa: BLE001 - informational only
        try:
            from importlib.metadata import version

            return version("rapidocr")
        except Exception:  # noqa: BLE001
            return "?"


def model_files(model_dir: Path | None = None) -> tuple[Path, Path]:
    """(det, rec) model paths in ``model_dir`` (default paths.ocr_model_dir()).
    Raises OcrUnavailable when a file is missing."""
    d = Path(model_dir) if model_dir is not None else paths.ocr_model_dir()
    if d is None:
        raise unavailable(tr("找不到模型資料夾（rapidocr/models）", "model folder not found (rapidocr/models)"))
    det, rec = d / DET_MODEL, d / REC_MODEL
    missing = [p.name for p in (det, rec) if not p.is_file()]
    if missing:
        raise unavailable(tr("缺少模型檔 {names}", "model file missing: {names}").format(names=", ".join(missing)))
    return det, rec


def constrained_decode(probs: np.ndarray, chars: Sequence[str], allowed: str,
                       allowed_idx: np.ndarray | None = None, latin_mask: np.ndarray | None = None
                       ) -> tuple[str, list[float]]:
    """Greedy CTC decode of one line's (T, C) softmax ``probs`` where every frame whose best
    symbol is Latin-like (LATIN_LIKE) is re-decided among ``allowed`` + "-" (blank excluded, so
    nothing is deleted); CJK, punctuation, space and blank frames keep their argmax.
    ``chars[0]`` is the CTC blank. Returns (text, per-character confidence)."""
    top = probs.argmax(axis=1)
    if allowed_idx is None:
        allowed_set = set(allowed) | {"-"}
        allowed_idx = np.array([i for i, c in enumerate(chars) if i and c in allowed_set], dtype=np.int64)
    if latin_mask is None:
        latin_mask = np.array([bool(i) and c in LATIN_LIKE for i, c in enumerate(chars)], dtype=bool)
    pick = top.copy()
    if allowed_idx.size:
        relabel = latin_mask[top]
        if relabel.any():
            pick[relabel] = allowed_idx[probs[relabel][:, allowed_idx].argmax(axis=1)]
    text: list[str] = []
    confs: list[float] = []
    prev = 0
    for t, k in enumerate(pick.tolist()):
        if k and k != prev:
            text.append(chars[k])
            confs.append(float(probs[t, k]))
        prev = k
    return "".join(text), confs


class OcrEngine:
    def __init__(self, model_dir: Path | None = None, threads: int = -1, det_side: int = 960,
                 max_side_len: int = MAX_SIDE_LEN) -> None:
        """Create the RapidOCR engine (about 0.8 s). Raises OcrUnavailable.
        ``max_side_len`` (addition, default 4096) exists for benchmarks only."""
        det_path, rec_path = model_files(model_dir)
        cpu = os.cpu_count() or 1
        n = int(threads)
        self._threads = -1 if n <= 0 else min(n, cpu)
        self._det_side = max(32, int(det_side))
        self._max_side = max(256, int(max_side_len))
        self._lock = threading.Lock()
        self._allowed_cache: dict[str, np.ndarray] = {}
        t0 = time.perf_counter()
        try:
            from rapidocr import RapidOCR
        except Exception as exc:  # noqa: BLE001 - ImportError / DLL load failure (OSError) alike
            raise unavailable(tr("無法載入文字辨識元件（{err}）", "cannot load the OCR components ({err})")
                              .format(err=short_error(exc))) from exc
        self._version = _rapidocr_version()
        if self._version != PINNED_RAPIDOCR:
            log.warning("rapidocr %s found, AutoPress is tested with %s (internal APIs in use)",
                        self._version, PINNED_RAPIDOCR)
        params: dict[str, Any] = {
            "Global.log_level": "error",  # silent (a windowed exe has sys.stderr = None)
            "Global.use_cls": False,  # screen text is upright
            "Global.max_side_len": self._max_side,
            "Det.model_path": str(det_path),
            "Rec.model_path": str(rec_path),
            "Det.limit_type": "max",
            "Det.limit_side_len": self._det_side,
            "EngineConfig.onnxruntime.intra_op_num_threads": self._threads,
        }
        try:
            self._ocr = RapidOCR(params=params)
            self._det = self._ocr._load_det_model()  # internal API, pinned 3.10.0
            self._rec = self._ocr._load_rec_model()
            chars = list(self._rec.postprocess_op.character)  # index 0 = CTC blank
        except Exception as exc:  # noqa: BLE001 - ONNX Runtime / config errors
            raise unavailable(tr("無法載入辨識模型（{err}）", "the OCR models could not be loaded ({err})")
                              .format(err=short_error(exc))) from exc
        self._chars = chars
        self._latin = np.array([bool(i) and c in LATIN_LIKE for i, c in enumerate(chars)], dtype=bool)
        self.load_seconds = time.perf_counter() - t0
        log.info("OCR engine created in %.2f s (rapidocr %s, threads %s, det_side %s, max_side_len %s)",
                 self.load_seconds, self._version, self._threads, self._det_side, self._max_side)

    # ------------------------------------------------------------------ diagnostics

    def info(self) -> dict[str, Any]:
        """Effective configuration (for the self-test, the settings page and tests)."""
        return {
            "rapidocr": self._version,
            "max_side_len": int(self._ocr.max_side_len),
            "cfg_max_side_len": int(self._ocr.cfg.Global.max_side_len),
            "det_side": int(self._det.limit_side_len),
            "det_limit_type": str(self._det.limit_type),
            "use_cls": bool(self._ocr.use_cls),
            "threads": self._threads,
            "load_seconds": round(self.load_seconds, 3),
        }

    # ------------------------------------------------------------------ OCR

    def _run(self, image_bgr: np.ndarray) -> Any:
        return self._ocr(image_bgr)

    def _scale_for(self, h: int, w: int, upscale: int) -> float:
        k = max(1, int(upscale or 1))
        if k <= 1 or h <= 0 or w <= 0:
            return 1.0
        return max(1.0, min(float(k), self._max_side / max(h, w)))

    def recognize(self, image_bgr: np.ndarray, upscale: int = 1, det_side: int | None = None) -> list[OcrLine]:
        """OCR one HxWx3 uint8 BGR image. ``upscale`` > 1 enlarges it (bicubic) first, but never
        beyond a long side of 4096 px (max_side_len); returned quads are always in the ORIGINAL
        image's pixels (divided by the factor really used). ``det_side`` overrides
        Det.limit_side_len for this call only (restored in finally). AutoPress uses 960 for every
        read: 1920 lost small text in sparse scenes (T13)."""
        img = imageio.to_bgr(image_bgr)
        h, w = img.shape[:2]
        if h == 0 or w == 0:
            return []
        scale = self._scale_for(h, w, upscale)
        sx = sy = 1.0
        if scale > 1.0:
            nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
            img = imageio.resize(img, nw, nh)
            sx, sy = nw / w, nh / h
        with self._lock:
            det = self._det
            old = det.limit_side_len
            if det_side:
                det.limit_side_len = int(det_side)
            try:
                res = self._run(img)
            finally:
                det.limit_side_len = old
        boxes = getattr(res, "boxes", None)
        txts = getattr(res, "txts", None)
        if boxes is None or txts is None or len(txts) == 0:
            return []
        scores = getattr(res, "scores", None)
        if scores is None or len(scores) != len(txts):
            scores = [1.0] * len(txts)
        lines: list[OcrLine] = []
        for box, text, score in zip(boxes, txts, scores):
            q = np.asarray(box, dtype=np.float64).reshape(-1, 2)
            if q.shape[0] != 4:
                continue
            q[:, 0] /= sx
            q[:, 1] /= sy
            lines.append(OcrLine(text=str(text), quad=[(float(x), float(y)) for x, y in q], score=float(score)))
        return lines

    def _allowed_idx(self, allowed: str) -> np.ndarray:
        idx = self._allowed_cache.get(allowed)
        if idx is None:
            allowed_set = set(allowed) | {"-"}
            idx = np.array([i for i, c in enumerate(self._chars) if i and c in allowed_set], dtype=np.int64)
            if len(self._allowed_cache) > 32:
                self._allowed_cache.clear()
            self._allowed_cache[allowed] = idx
        return idx

    def reread_line(self, image_bgr: np.ndarray, quad: Sequence[tuple[float, float]], allowed: str,
                    upscale: int = 1) -> tuple[str, list[float]]:
        """Charset-constrained CTC re-read of one detected line (recipe recognize_code_line):
        Latin-looking frames are re-decided among ``allowed`` (+ "-"), CJK frames untouched.
        Returns (text, per-character confidences). Uses rapidocr internals - pinned 3.10.0.
        ``upscale`` (addition) > 1 re-reads from a bicubic enlargement of the line's
        neighbourhood (same factor rule as recognize) - use the factor the line was read at."""
        from rapidocr.utils.process_img import get_rotate_crop_image

        img = imageio.to_bgr(image_bgr)
        q = np.asarray(quad, dtype=np.float32).reshape(4, 2).copy()
        h, w = img.shape[:2]
        if h == 0 or w == 0:
            return "", []
        scale = self._scale_for(h, w, upscale)
        if scale > 1.0:
            pad = 4
            x0 = max(0, int(np.floor(q[:, 0].min())) - pad)
            y0 = max(0, int(np.floor(q[:, 1].min())) - pad)
            x1 = min(w, int(np.ceil(q[:, 0].max())) + pad)
            y1 = min(h, int(np.ceil(q[:, 1].max())) + pad)
            if x1 <= x0 or y1 <= y0:
                return "", []
            sub = img[y0:y1, x0:x1]
            nw, nh = max(1, round(sub.shape[1] * scale)), max(1, round(sub.shape[0] * scale))
            img = imageio.resize(sub, nw, nh)
            q = (q - np.array([x0, y0], np.float32)) * np.array([nw / sub.shape[1], nh / sub.shape[0]], np.float32)
        with self._lock:
            crop = get_rotate_crop_image(img, q.copy())
            if crop.ndim != 3 or crop.shape[0] < 1 or crop.shape[1] < 1:
                return "", []
            rec = self._rec
            _, ih, iw = rec.rec_image_shape
            x = rec.resize_norm_img(crop, max(iw / ih, crop.shape[1] / crop.shape[0]))[None]
            probs = rec.session(x.astype(np.float32))[0]  # (T, C) softmax
        return constrained_decode(probs, self._chars, allowed, self._allowed_idx(allowed), self._latin)

    def warmup(self) -> float:
        """Run one small image through the engine (models load lazily). Returns seconds."""
        import cv2

        t0 = time.perf_counter()
        img = np.full((64, 256, 3), 255, np.uint8)
        cv2.putText(img, "AB12 CD34", (10, 44), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2, cv2.LINE_AA)
        self.recognize(img)
        return time.perf_counter() - t0
