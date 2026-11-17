"""U2 benchmark: find button / label text in a mock dark game dialog and compute click points.

Usage:
    python bench_u2.py OUT_DIR --engines rapid_v6s,rapid_v6s@max960,rapid_v6t [--models DIR] [--screen]
    python bench_u2.py OUT_DIR --engines win_zh-Hant-TW [--screen]
Renders 800x500 dialogs (label font 10-24 px; button pairs 兌換/取消, 確認/領取, Redeem/Cancel,
Confirm/OK) and the same dialogs pasted into a 1920x1080 scene with small HUD text.
A target is OK when find_text_center() (autopress_ocr_recipe.py, strict whole-box match) returns a
point inside the button rectangle (buttons) or inside the text box + 3 px (title/label); the
substring-fallback mode (exact=False) is reported separately, including wrong clicks. --screen also times OCR on a live mss
capture of the primary monitor (kept in memory only; recognized text is never printed or saved).
Writes OUT_DIR/u2_<engine>.json, prints Markdown tables.
"""
import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ocr_backends import make_backend  # noqa: E402
from ocr_common import preprocess  # noqa: E402
from autopress_ocr_recipe import find_text_center  # noqa: E402

F = "C:/Windows/Fonts/"
SIZES = [10, 12, 13, 14, 16, 18, 20, 24]
VARIANTS = [("zh", "兌換獎勵", "請輸入兌換碼", "兌換", "取消"), ("zh", "系統提示", "請確認領取獎勵", "確認", "領取"),
            ("en", "Redeem Rewards", "Enter your redeem code", "Redeem", "Cancel"),
            ("en", "Notice", "Please confirm", "Confirm", "OK")]
HUD = ["Lv.45", "HP 1200/1200", "商城", "活動", "設定", "背包", "信箱 3", "好友"]


def font(lang, size, bold=False):
    if lang == "zh":
        return ImageFont.truetype(F + ("msjhbd.ttc" if bold else "msjh.ttc"), size)
    return ImageFont.truetype(F + ("segoeuib.ttf" if bold else "segoeui.ttf"), size)


def dialog(variant, s, rng):
    lang, title, label, b1, b2 = variant
    W, H = 800, 500
    t = np.linspace(0, 1, H)[:, None, None]
    base = (np.array([14, 30, 40]) * (1 - t) + np.array([30, 18, 50]) * t)
    arr = np.broadcast_to(base, (H, W, 3)) + rng.normal(0, 6, (H, W, 3))
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([60, 40, 740, 460], radius=18, fill=(25, 28, 40), outline=(200, 160, 80), width=3)
    targets = []

    def text(xy, txt, f, fill, anchor, kind, rect=None):
        d.text(xy, txt, font=f, fill=fill, anchor=anchor)
        bb = d.textbbox(xy, txt, font=f, anchor=anchor)
        region = rect if rect else (bb[0] - 3, bb[1] - 3, bb[2] + 3, bb[3] + 3)
        targets.append({"text": txt, "kind": kind, "region": region,
                        "tcenter": ((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2)})

    text((400, 90), title, font(lang, int(s * 1.5), True), (240, 210, 140), "mm", "title")
    text((120, 175), label, font(lang, s), (200, 200, 205), "ls", "label")
    ih = max(36, int(s * 2.6))
    d.rectangle([120, 195, 680, 195 + ih], fill=(12, 12, 18), outline=(90, 90, 110), width=2)
    d.text((132, 195 + ih // 2), "XXXX-XXXX-XXXX", font=font("en", s), fill=(95, 95, 105), anchor="lm")
    bw, bh = max(120, s * 6), max(40, int(s * 2.8))
    for cx, lab, fill, fg in [(290, b1, (214, 164, 60), (40, 25, 0)), (510, b2, (78, 82, 98), (245, 245, 245))]:
        rect = (cx - bw // 2, 390 - bh // 2, cx + bw // 2, 390 + bh // 2)
        d.rounded_rectangle(rect, radius=8, fill=fill, outline=(240, 220, 160), width=2)
        text((cx, 390), lab, font(lang, s), fg, "mm", "button", rect)
    return img, targets


def scene(dlg, targets, s, rng):
    W, H = 1920, 1080
    t = np.linspace(0, 1, W)[None, :, None]
    base = np.array([20, 40, 30]) * (1 - t) + np.array([50, 30, 20]) * t
    arr = np.broadcast_to(base, (H, W, 3)) + rng.normal(0, 8, (H, W, 3))
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(img)
    for i, h in enumerate(HUD):
        d.text((30 + (i % 4) * 140, 20 + (i // 4) * 40), h, font=font("zh", max(12, s)), fill=(230, 230, 230))
    ox, oy = (W - dlg.width) // 2, (H - dlg.height) // 2
    img.paste(dlg, (ox, oy))
    moved = []
    for tg in targets:
        r = tg["region"]
        moved.append(dict(tg, region=(r[0] + ox, r[1] + oy, r[2] + ox, r[3] + oy),
                          tcenter=(tg["tcenter"][0] + ox, tg["tcenter"][1] + oy)))
    return img, moved


def evaluate(be, img_bgr, targets, k):
    t0 = time.perf_counter()
    items = be.run(img_bgr)  # line-level boxes for both engines
    ms = (time.perf_counter() - t0) * 1000
    items = [(t, q / k, s, c) for t, q, s, c in items]
    items3 = [(t, q, s) for t, q, s, _ in items]
    res = []
    for tg in targets:
        out = {"text": tg["text"], "kind": tg["kind"]}
        for mode, exact in (("", True), ("sub_", False)):  # strict whole-box match / substring fallback
            c = find_text_center(items3, tg["text"], exact=exact)
            ok, err = False, None
            if c:
                r = tg["region"]
                ok = bool(r[0] <= c[0] <= r[2] and r[1] <= c[1] <= r[3])
                err = float(np.hypot(c[0] - tg["tcenter"][0], c[1] - tg["tcenter"][1]))
            out.update({mode + "found": c is not None, mode + "ok": ok, mode + "err": err})
        res.append(out)
    return ms, res, items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--engines", required=True)
    ap.add_argument("--models", default="")
    ap.add_argument("--pre", default="none,up2,up3")
    ap.add_argument("--screen", action="store_true")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(3)
    cases = []
    for s in SIZES:
        for v in VARIANTS:
            dlg, tg = dialog(v, s, rng)
            sc, tg2 = scene(dlg, tg, s, rng)
            cases.append((s, v[0], v[3], "dialog", np.asarray(dlg)[:, :, ::-1].copy(), tg))
            cases.append((s, v[0], v[3], "fullhd", np.asarray(sc)[:, :, ::-1].copy(), tg2))
    Image.fromarray(cases[4 * 2 * 2][4][:, :, ::-1]).save(out / "sample_dialog_s13_zh.png")
    for eng in a.engines.split(","):
        be = make_backend(eng, [d for d in a.models.split(";") if d] or None)
        be.run(cases[0][4])
        recs, sample = [], None
        for s, lang, b1, kind, img, tg in cases:
            for pre in a.pre.split(","):
                if kind == "fullhd" and pre != "none":
                    continue
                k = {"none": 1, "up2": 2, "up3": 3}[pre]
                ms, res, items = evaluate(be, preprocess(img, pre), tg, k)
                recs.append({"size": s, "lang": lang, "b1": b1, "kind": kind, "pre": pre, "ms": ms, "targets": res})
                if sample is None and s == 14 and lang == "zh" and kind == "dialog" and pre == "none":
                    sample = [[t, np.round(q, 1).tolist(), round(sc, 3)] for t, q, sc, _ in items]
        screen = None
        if a.screen:
            import mss
            with mss.MSS() as sct:
                mon = sct.monitors[1]
                shot = np.ascontiguousarray(np.asarray(sct.grab(mon))[:, :, :3])
            times, nbox = [], 0
            for _ in range(3):
                t0 = time.perf_counter()
                nbox = len(be.run(shot))
                times.append((time.perf_counter() - t0) * 1000)
            screen = {"w": int(shot.shape[1]), "h": int(shot.shape[0]), "ms": times, "boxes": nbox}
            del shot
        (out / ("u2_%s.json" % eng)).write_text(json.dumps({"engine": eng, "records": recs, "sample": sample,
                                                            "screen": screen}, ensure_ascii=False, indent=0),
                                                encoding="utf-8")
        print("\n### %s\n" % eng)
        print("| case | pre | " + " | ".join("%dpx" % s for s in SIZES) + " | median ms |")
        print("|---|---|" + "---|" * len(SIZES) + "---|")
        for kind in ["dialog", "fullhd"]:
            for pre in a.pre.split(","):
                rr = [r for r in recs if r["kind"] == kind and r["pre"] == pre]
                if not rr:
                    continue
                cells = []
                for s in SIZES:
                    tt = [t for r in rr if r["size"] == s for t in r["targets"]]
                    cells.append("%d/%d" % (sum(t["ok"] for t in tt), len(tt)))
                print("| %s | %s | %s | %.0f |" % (kind, pre, " | ".join(cells), statistics.median(r["ms"] for r in rr)))
        misses = [(r["size"], r["kind"], r["pre"], t["text"]) for r in recs for t in r["targets"] if not t["ok"]]
        print("\nmisses (size, case, pre, target):", misses[:40], "... total", len(misses))
        allt = [t for r in recs for t in r["targets"]]
        print("strict whole-box match: ok %d, not found %d, WRONG click %d | substring fallback: ok %d, "
              "not found %d, WRONG click %d (of %d)" % (
                  sum(t["ok"] for t in allt), sum(not t["found"] for t in allt),
                  sum(t["found"] and not t["ok"] for t in allt), sum(t["sub_ok"] for t in allt),
                  sum(not t["sub_found"] for t in allt), sum(t["sub_found"] and not t["sub_ok"] for t in allt),
                  len(allt)))
        errs = [t["err"] for r in recs for t in r["targets"] if t["ok"] and t["err"] is not None]
        if errs:
            print("click-centre error vs true text centre (px, ok hits): median %.1f, max %.1f" % (
                statistics.median(errs), max(errs)))
        if screen:
            print("live screen %dx%d: ms %s, boxes %d" % (screen["w"], screen["h"],
                                                      [round(x) for x in screen["ms"]], screen["boxes"]))


if __name__ == "__main__":
    main()
