# OWNED BY G2 - replace this stub
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
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import numpy as np

from ..models import OcrLine

__stub__ = True

DET_MODEL = "PP-OCRv6_det_small.onnx"
REC_MODEL = "PP-OCRv6_rec_small.onnx"


class OcrUnavailable(RuntimeError):
    """The engine cannot run (package or model files missing, ONNX Runtime failed).
    ``str(exc)`` is a localized message."""


def model_files(model_dir: Path | None = None) -> tuple[Path, Path]:
    """(det, rec) model paths in ``model_dir`` (default paths.ocr_model_dir()).
    Raises OcrUnavailable when a file is missing."""
    raise NotImplementedError


class OcrEngine:
    def __init__(self, model_dir: Path | None = None, threads: int = -1, det_side: int = 960) -> None:
        """Create the RapidOCR engine (about 0.8 s). Raises OcrUnavailable."""
        raise NotImplementedError

    def recognize(self, image_bgr: np.ndarray, upscale: int = 1, det_side: int | None = None) -> list[OcrLine]:
        """OCR one HxWx3 uint8 BGR image. ``upscale`` > 1 enlarges it (bicubic) first, but never
        beyond a long side of 4096 px (max_side_len); returned quads are always in the ORIGINAL
        image's pixels (divided by the factor really used). ``det_side`` overrides
        Det.limit_side_len for this call only (restored in finally). AutoPress uses 960 for every
        read: 1920 lost small text in sparse scenes (T13)."""
        raise NotImplementedError

    def reread_line(self, image_bgr: np.ndarray, quad: Sequence[tuple[float, float]], allowed: str) -> tuple[str, list[float]]:
        """Charset-constrained CTC re-read of one detected line (recipe recognize_code_line):
        Latin-looking frames are re-decided among ``allowed`` (+ "-"), CJK frames untouched.
        Returns (text, per-character confidences). Uses rapidocr internals - pinned 3.10.0."""
        raise NotImplementedError

    def warmup(self) -> float:
        """Run one small image through the engine (models load lazily). Returns seconds."""
        raise NotImplementedError
