"""U1 benchmark: extract codes from the synthetic images made by gen_u1_codes.py.

Usage:
    python bench_u1.py DATA_DIR OUT_DIR --engine rapid_v6s [--pre none,up2,up3,gray_ac,invert]
                       [--models DIR;DIR] [--limit N]
Engines: rapid_v6s | rapid_v6t | rapid_v6m | rapid_v5m (rapidocr venv), win_zh-Hant-TW (pywinrt venv),
tess_eng+chi_tra (tesserocr venv, AUTOPRESS_TESSDATA=tessdata dir).
Writes OUT_DIR/u1_<engine>.jsonl: first line = timing meta, then one record per image x preprocessing.
Per record: raw_hit (ground truth appears verbatim in an OCR row, spaces removed),
post_hit (ground truth among extract_codes() candidates for the declared CodeSpec),
ctc_hit (rapid only: code-like lines re-recognized with charset-constrained CTC decoding).
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ocr_common import (MIXED, UPPER, CodeSpec, extract_codes, group_rows, load_image_bgr,  # noqa: E402
                        preprocess, semi_global_align)


def spec_for(lab):
    allowed = UPPER if lab["charset"] == "upper" else MIXED
    if len(lab["groups"]) > 1:
        return CodeSpec(allowed, groups=lab["groups"])
    return CodeSpec(allowed, min_len=8, max_len=16)


def best_alignment(gt, rows):
    best = None
    for r in rows:
        text = r["text"].replace(" ", "")
        confs = [c for ch, c in zip(r["text"], r["confs"]) if ch != " "]
        dist, ops = semi_global_align(gt, text)
        if best is None or dist < best[0]:
            best = (dist, ops, confs)
    if best is None:
        return {"dist": len(gt), "ops": [], "confs": []}
    dist, ops, confs = best
    return {"dist": dist, "ops": [[g, p, (confs[j] if j is not None and j < len(confs) else None)]
                                  for g, p, j in ops if g != p]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("out")
    ap.add_argument("--engine", required=True)
    ap.add_argument("--pre", default="none,up2,up3,gray_ac,invert")
    ap.add_argument("--models", default="")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    data, out = Path(a.data), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    labels = json.loads((data / "labels.json").read_text(encoding="utf-8"))
    if a.limit:
        labels = labels[:a.limit]
    pres = a.pre.split(",")

    t0 = time.perf_counter()
    if a.engine.startswith("rapid_"):
        import onnxruntime  # noqa: F401
        import rapidocr  # noqa: F401
    elif a.engine.startswith("tess_"):
        import tesserocr  # noqa: F401
    else:
        import winrt.windows.media.ocr  # noqa: F401
    t_import = time.perf_counter() - t0
    from ocr_backends import make_backend
    t1 = time.perf_counter()
    be = make_backend(a.engine, [d for d in a.models.split(";") if d] or None)
    t_ctor = time.perf_counter() - t1
    first = load_image_bgr(data / labels[0]["file"])
    t2 = time.perf_counter()
    be.run(first)
    t_first = time.perf_counter() - t2
    is_rapid = a.engine.startswith("rapid_")

    path = out / ("u1_%s.jsonl" % a.engine)
    n_raw = n_post = n_ctc = n = 0
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"meta": True, "engine": a.engine, "import_s": t_import, "ctor_s": t_ctor,
                             "first_call_s": t_first}) + "\n")
        for pre in pres:
            for lab in labels:
                img = preprocess(load_image_bgr(data / lab["file"]), pre)
                gt, spec = lab["code"], spec_for(lab)
                ts = time.perf_counter()
                items = be.run(img)
                ms = (time.perf_counter() - ts) * 1000
                rows = group_rows(items)
                texts = [r["text"] for r in rows]
                raw_hit = any(gt in t.replace(" ", "") for t in texts)
                cands = extract_codes(texts, spec)
                rec = {"engine": a.engine, "pre": pre, "file": lab["file"], "gt": gt, "rows": texts,
                       "ms": round(ms, 1), "raw_hit": raw_hit, "cands": cands, "post_hit": gt in cands,
                       "align": best_alignment(gt, rows)}
                if is_rapid:
                    ts = time.perf_counter()
                    citems = be.run_constrained(img, spec.allowed, items=items)
                    rec["ctc_ms"] = round((time.perf_counter() - ts) * 1000, 1)
                    crows = group_rows(citems)
                    rec["ctc_rows"] = [r["text"] for r in crows]
                    rec["ctc_cands"] = extract_codes(rec["ctc_rows"], spec)
                    rec["ctc_hit"] = gt in rec["ctc_cands"]
                    rec["ctc_align"] = best_alignment(gt, crows)
                    n_ctc += rec["ctc_hit"]
                n += 1
                n_raw += raw_hit
                n_post += rec["post_hit"]
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("%s: n=%d raw=%.3f post=%.3f ctc=%.3f import=%.2fs ctor=%.2fs first=%.2fs -> %s" % (
        a.engine, n, n_raw / n, n_post / n, n_ctc / n if is_rapid else float("nan"),
        t_import, t_ctor, t_first, path))


if __name__ == "__main__":
    main()
