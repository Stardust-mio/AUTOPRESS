"""Summarize bench_u1.py results into Markdown tables.

Usage:
    python report_u1.py LABELS_JSON RESULTS_DIR > report_u1.md
"""
import collections
import json
import statistics
import sys
from pathlib import Path

PRES = ["none", "up2", "up3", "gray_ac", "invert"]
SIZE_BUCKETS = [("12-14", 12, 14), ("16-20", 16, 20), ("24-32", 24, 32), ("40-48", 40, 48)]


def pct(k, n):
    return "-" if n == 0 else "%.0f" % (100.0 * k / n)


def load(res_dir):
    runs = {}
    for p in sorted(Path(res_dir).glob("u1_*.jsonl")):
        lines = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
        runs[lines[0]["engine"]] = (lines[0], lines[1:])
    return runs


def main():
    labels = {x["file"]: x for x in json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))}
    runs = load(sys.argv[2])
    print("# U1 code-extraction benchmark (%d images)\n" % len(labels))
    print("Cells: raw / post / ctc exact-match %. raw = code appears verbatim in an OCR row; post = "
          "rule-based extraction with the declared charset+pattern; ctc = code-like lines re-decoded "
          "with charset-constrained CTC (rapidocr only).\n")
    print("| engine | " + " | ".join(PRES) + " |")
    print("|---|" + "---|" * len(PRES))
    for eng, (meta, recs) in runs.items():
        cells = []
        for pre in PRES:
            rr = [r for r in recs if r["pre"] == pre]
            if not rr:
                cells.append("")
                continue
            c = "%s / %s" % (pct(sum(r["raw_hit"] for r in rr), len(rr)), pct(sum(r["post_hit"] for r in rr), len(rr)))
            if "ctc_hit" in rr[0]:
                c += " / " + pct(sum(r["ctc_hit"] for r in rr), len(rr))
            cells.append(c)
        print("| %s | %s |" % (eng, " | ".join(cells)))

    def best_key(r):
        return r.get("ctc_hit", r["post_hit"])

    print("\n## Best-metric (ctc for rapid, post for Windows OCR) by text size, background, charset\n")
    groups = [("size " + b, lambda lab, lo=lo, hi=hi: lo <= lab["size"] <= hi) for b, lo, hi in SIZE_BUCKETS]
    groups += [("bg " + g, lambda lab, g=g: lab["bg"] == g) for g in
               ["light", "dark", "lowc_light", "lowc_dark", "gradient", "game"]]
    groups += [("charset upper", lambda lab: lab["charset"] == "upper"),
               ("charset mixed", lambda lab: lab["charset"] == "mixed"),
               ("jpeg", lambda lab: lab["jpeg"]),
               ("layout alone", lambda lab: lab["layout"] == "alone"),
               ("layout prefix", lambda lab: lab["layout"] == "prefix"),
               ("layout sentence", lambda lab: lab["layout"] == "sentence")]
    cols = [(eng, pre) for eng in runs for pre in PRES if any(r["pre"] == pre for r in runs[eng][1])]
    print("| subset (n) | " + " | ".join("%s %s" % c for c in cols) + " |")
    print("|---|" + "---|" * len(cols))
    for gname, fn in groups:
        n = sum(1 for lab in labels.values() if fn(lab))
        cells = []
        for eng, pre in cols:
            rr = [r for r in runs[eng][1] if r["pre"] == pre and fn(labels[r["file"]])]
            cells.append(pct(sum(best_key(r) for r in rr), len(rr)))
        print("| %s (%d) | %s |" % (gname, n, " | ".join(cells)))

    print("\n## Top character confusions (pre=none, raw rows; gt->ocr, '_' = missing/extra)\n")
    for eng, (meta, recs) in runs.items():
        cnt = collections.Counter()
        for r in recs:
            if r["pre"] != "none":
                continue
            for g, p, _ in r["align"]["ops"]:
                cnt["%s->%s" % (g or "_", p or "_")] += 1
        total = sum(cnt.values())
        print("- **%s** (%d char errors): %s" % (eng, total, ", ".join("%s %d" % kv for kv in cnt.most_common(14))))
        if "ctc_align" in recs[0]:
            c2 = collections.Counter()
            for r in recs:
                if r["pre"] == "none":
                    for g, p, _ in r["ctc_align"]["ops"]:
                        c2["%s->%s" % (g or "_", p or "_")] += 1
            print("  - after ctc (%d char errors): %s" % (sum(c2.values()), ", ".join("%s %d" % kv for kv in c2.most_common(10))))

    print("\n## Latency per image (ms; median / p90; shared machine, indicative) and cold start\n")
    print("| engine | import s | ctor s | first call s | " + " | ".join(PRES) + " | ctc extra (none) |")
    print("|---|---|---|---|" + "---|" * len(PRES) + "---|")
    for eng, (meta, recs) in runs.items():
        cells = []
        for pre in PRES:
            ms = sorted(r["ms"] for r in recs if r["pre"] == pre)
            cells.append("%.0f / %.0f" % (statistics.median(ms), ms[int(0.9 * (len(ms) - 1))]) if ms else "")
        cm = [r["ctc_ms"] for r in recs if r["pre"] == "none" and "ctc_ms" in r]
        print("| %s | %.2f | %.2f | %.2f | %s | %s |" % (eng, meta["import_s"], meta["ctor_s"], meta["first_call_s"],
                                                         " | ".join(cells),
                                                         "%.0f" % statistics.median(cm) if cm else "-"))

    print("\n## Candidate precision (pre=none): images with exactly one candidate == ground truth\n")
    for eng, (meta, recs) in runs.items():
        rr = [r for r in recs if r["pre"] == "none"]
        key = "ctc_cands" if "ctc_cands" in rr[0] else "cands"
        one = sum(1 for r in rr if r[key] == [r["gt"]])
        wrong_only = sum(1 for r in rr if r[key] and r["gt"] not in r[key])
        none_ = sum(1 for r in rr if not r[key])
        print("- %s (%s): unique-correct %d/%d, wrong-candidate-only %d, no candidate %d" % (
            eng, key, one, len(rr), wrong_only, none_))


if __name__ == "__main__":
    main()
