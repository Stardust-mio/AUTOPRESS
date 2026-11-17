"""OCR latency / lines benchmark on image files (OWNED BY G2; SPEC T16, engine.py docstring).

    .venv/Scripts/python.exe tools/ocr_bench.py SHOT.png [SHOT2.png ...] [--det-side 960]
        [--max-side 4096,2000] [--threads 4] [--upscale 1] [--runs 3] [--out result.json]

Reads each image (Pillow; Chinese paths fine), builds one OcrEngine per max_side_len value and
reports the median latency of ``--runs`` calls (after one warm-up call) and the lines found.
Nothing is captured from the screen and nothing is written except ``--out`` (keep it outside the
project folder). Example for the two screenshots T16 asks for: a 2560x1440 and a 3840x2160
full-screen PNG of a real game or redeem page.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autopress.ocr.engine import OcrEngine  # noqa: E402
from autopress.ocr.imageio import load_image  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("images", nargs="+", type=Path)
    ap.add_argument("--det-side", type=int, default=960)
    ap.add_argument("--max-side", default="4096,2000", help="comma-separated Global.max_side_len values")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--upscale", type=int, default=1)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    images = [(p, load_image(p)) for p in a.images]
    results = []
    for max_side in (int(v) for v in a.max_side.split(",") if v.strip()):
        eng = OcrEngine(threads=a.threads, det_side=a.det_side, max_side_len=max_side)
        for path, img in images:
            eng.recognize(img, upscale=a.upscale)  # warm-up for this size
            times, lines = [], []
            for _ in range(max(1, a.runs)):
                t0 = time.perf_counter()
                lines = eng.recognize(img, upscale=a.upscale)
                times.append((time.perf_counter() - t0) * 1000)
            row = {"image": path.name, "size": f"{img.shape[1]}x{img.shape[0]}", "max_side_len": max_side,
                   "det_side": a.det_side, "upscale": a.upscale, "threads": a.threads,
                   "median_ms": round(statistics.median(times)), "lines": len(lines),
                   "texts": [ln.text for ln in lines]}
            results.append(row)
            print(f"{row['image']} {row['size']} max_side_len={max_side}: {row['median_ms']} ms, {row['lines']} lines")
    if a.out:
        a.out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
