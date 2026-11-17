"""U1: can per-character confidences flag the wrong characters of a code for user review?

Usage:
    python bench_u1_flags.py DATA_DIR OUT_JSON [--engine rapid_v6s] [--models DIR]
For every image (pre=none): OCR -> code-like lines re-decoded with charset-constrained CTC ->
ground truth aligned inside the best row -> (gt char, ocr char, confidence) for every aligned
position. Prints a Markdown table: for confidence thresholds T, the share of wrong characters
with conf < T (caught), the share of correct characters with conf < T (false flags), and the
share of wrong / correct codes that would show at least one flag; plus the same for a
"confusable glyph" rule (flag every 0 O 1 I l 5 S 8 B 2 Z character) and for the union.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_u1 import spec_for  # noqa: E402
from ocr_backends import make_backend  # noqa: E402
from ocr_common import group_rows, load_image_bgr, semi_global_align  # noqa: E402

CONFUSABLE_GLYPHS = set("0O1Il5S8B2Z")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("out")
    ap.add_argument("--engine", default="rapid_v6s")
    ap.add_argument("--models", default="")
    a = ap.parse_args()
    labels = json.loads((Path(a.data) / "labels.json").read_text(encoding="utf-8"))
    be = make_backend(a.engine, [d for d in a.models.split(";") if d] or None)
    codes = []
    for lab in labels:
        img = load_image_bgr(Path(a.data) / lab["file"])
        rows = group_rows(be.run_constrained(img, spec_for(lab).allowed))
        best = None
        for r in rows:
            text = "".join(c for c in r["text"] if c != " ")
            confs = [cf for c, cf in zip(r["text"], r["confs"]) if c != " "]
            d, ops = semi_global_align(lab["code"], text)
            if best is None or d < best[0]:
                best = (d, ops, confs)
        pos = []
        if best:
            for g, p, j in best[1]:
                if g is None:
                    continue
                pos.append([g, p, best[2][j] if j is not None else 0.0])
        codes.append({"file": lab["file"], "gt": lab["code"], "pos": pos,
                      "ok": bool(best) and best[0] == 0})
    Path(a.out).write_text(json.dumps(codes, ensure_ascii=False), encoding="utf-8")
    chars = [p for c in codes for p in c["pos"]]
    wrong = [p for p in chars if p[0] != p[1]]
    right = [p for p in chars if p[0] == p[1]]
    bad_codes = [c for c in codes if not c["ok"]]
    good_codes = [c for c in codes if c["ok"]]
    print("codes %d (exact %d), aligned chars %d, wrong chars %d" % (len(codes), len(good_codes), len(chars), len(wrong)))
    print("\n| rule | wrong chars flagged | correct chars flagged | wrong codes with >=1 flag | correct codes with >=1 flag |")
    print("|---|---|---|---|---|")

    def row(name, flag):
        def frac(xs, f):
            return "%.0f%%" % (100.0 * sum(1 for x in xs if f(x)) / len(xs)) if xs else "-"
        print("| %s | %s | %s | %s | %s |" % (
            name, frac(wrong, flag), frac(right, flag),
            frac(bad_codes, lambda c: any(flag(p) for p in c["pos"])),
            frac(good_codes, lambda c: any(flag(p) for p in c["pos"]))))
    for t in (0.5, 0.8, 0.9, 0.95, 0.99):
        row("conf < %.2f" % t, lambda p, t=t: p[1] is None or p[2] < t)
    row("confusable glyph", lambda p: p[1] is None or p[1] in CONFUSABLE_GLYPHS)
    row("conf < 0.90 OR glyph in {0,O}", lambda p: p[1] is None or p[2] < 0.9 or p[1] in "0O")


if __name__ == "__main__":
    main()
