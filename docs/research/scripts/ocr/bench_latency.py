"""Latency + cold-start benchmark (run on an otherwise idle machine).

Usage:
    python bench_latency.py U1_DIR --engines rapid_v6s,rapid_v6s@max960,rapid_v6t,rapid_v6t@max960,rapid_v5m
                            [--models DIR] [--threads -1,2] [--reps 3]
    python bench_latency.py U1_DIR --engines win_zh-Hant-TW
Cold start = fresh subprocess: import time, engine construction, first and second call on a
640x360 U1 image. Steady state = median ms over: 10 U1 images (640x360), 4 dialogs (800x500,
14 px labels) and 4 full-HD scenes (1920x1080), each image run --reps times.
"""
import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

COLD = r'''
import sys, time, json
sys.path.insert(0, %r)
t0 = time.perf_counter()
ENG = %r
if ENG.startswith("rapid_"):
    import rapidocr, onnxruntime
elif ENG.startswith("tess_"):
    import tesserocr
else:
    import winrt.windows.media.ocr
t1 = time.perf_counter()
from ocr_backends import make_backend
from ocr_common import load_image_bgr
be = make_backend(%r, [d for d in %r.split(";") if d] or None)
t2 = time.perf_counter()
img = load_image_bgr(%r)
t3 = time.perf_counter(); be.run(img); t4 = time.perf_counter(); be.run(img); t5 = time.perf_counter()
print(json.dumps({"import_s": t1 - t0, "ctor_s": t2 - t1, "first_s": t4 - t3, "second_s": t5 - t4}))
'''


def images(u1_dir):
    import numpy as np
    import bench_u2 as b2
    from ocr_common import load_image_bgr
    labels = json.loads((Path(u1_dir) / "labels.json").read_text(encoding="utf-8"))
    u1 = [load_image_bgr(Path(u1_dir) / labels[i]["file"]) for i in range(0, 240, 24)]
    rng = np.random.default_rng(5)
    dlg, hd = [], []
    for v in b2.VARIANTS:
        d, tg = b2.dialog(v, 14, rng)
        s, _ = b2.scene(d, tg, 14, rng)
        dlg.append(np.asarray(d)[:, :, ::-1].copy())
        hd.append(np.asarray(s)[:, :, ::-1].copy())
    return {"u1_640x360": u1, "dialog_800x500": dlg, "fullhd_1920x1080": hd}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("u1")
    ap.add_argument("--engines", required=True)
    ap.add_argument("--models", default="")
    ap.add_argument("--threads", default="-1")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--screen", action="store_true",
                    help="add a live mss capture of the primary monitor (memory only, text never printed)")
    a = ap.parse_args()
    from ocr_backends import RapidBackend, make_backend
    first_img = str(Path(a.u1) / "img_0000.png")
    sets = images(a.u1)
    if a.screen:
        import mss
        import numpy as np
        with mss.MSS() as sct:
            shot = np.ascontiguousarray(np.asarray(sct.grab(sct.monitors[1]))[:, :, :3])
        sets["live_screen_%dx%d" % (shot.shape[1], shot.shape[0])] = [shot]
    print("| engine | threads | import s | ctor s | 1st call s | 2nd call s | " +
          " | ".join("%s ms" % k for k in sets) + " |")
    print("|---|---|---|---|---|---|" + "---|" * len(sets))
    for eng in a.engines.split(","):
        p = subprocess.run([sys.executable, "-c", COLD % (str(HERE), eng, eng, a.models, first_img)],
                           capture_output=True, text=True)
        cold = json.loads(p.stdout.strip().splitlines()[-1])
        for th in ([int(x) for x in a.threads.split(",")] if eng.startswith("rapid_") else [-1]):
            be = make_backend(eng, [d for d in a.models.split(";") if d] or None)
            if th != -1:
                variant, _, det = eng[len("rapid_"):].partition("@")
                kw = {"det_limit_type": det[:3], "det_limit_side_len": int(det[3:])} if det else {}
                be = RapidBackend(variant, [d for d in a.models.split(";") if d] or None, threads=th, **kw)
            be.run(sets["u1_640x360"][0])
            cells = []
            for k, imgs in sets.items():
                ms = []
                for im in imgs:
                    for _ in range(a.reps):
                        t0 = time.perf_counter()
                        be.run(im)
                        ms.append((time.perf_counter() - t0) * 1000)
                cells.append("%.0f" % statistics.median(ms))
            print("| %s | %s | %.2f | %.2f | %.2f | %.2f | %s |" % (
                eng, "default" if th == -1 else th, cold["import_s"], cold["ctor_s"], cold["first_s"],
                cold["second_s"], " | ".join(cells)), flush=True)


if __name__ == "__main__":
    main()
