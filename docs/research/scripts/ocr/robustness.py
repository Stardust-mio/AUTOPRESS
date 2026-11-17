"""Robustness checks for rapidocr 3.10.0 + onnxruntime on Windows.

Usage:
    python robustness.py OUT_JSON WORK_DIR
WORK_DIR gets a sub-folder "測試路徑" (Chinese characters) for the path tests.
Checks:
  a) models copied to a Chinese-character directory, engine created with explicit model paths
  b) images under a Chinese path: cv2.imread vs the PIL-based load_image_bgr; numpy-only inference
  c) engine created inside a worker thread; one shared instance used by 2 threads concurrently
     (results compared with sequential runs); working-set memory before/after init and inference
  d) logging: bytes written to stdout/stderr with log_level info vs error; pythonw.exe run
     (sys.stdout = sys.stderr = None, like a windowed PyInstaller exe) incl. a warning path
"""
import ctypes
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


class _PMC(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


def mem_mb():
    k32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD]
    pmc = _PMC()
    pmc.cb = ctypes.sizeof(_PMC)
    psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
    return {"ws": round(pmc.WorkingSetSize / 2 ** 20, 1), "peak_ws": round(pmc.PeakWorkingSetSize / 2 ** 20, 1),
            "private": round(pmc.PagefileUsage / 2 ** 20, 1)}


def test_image(text="兌換碼：AB12-CD34-EF56", w=640, h=200):
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (w, h), (24, 26, 36))
    ImageDraw.Draw(img).text((30, h // 2), text, font=ImageFont.truetype("C:/Windows/Fonts/msjh.ttc", 28),
                             fill=(240, 240, 240), anchor="lm")
    return np.asarray(img)[:, :, ::-1].copy()


def model_files():
    import rapidocr
    d = Path(rapidocr.__file__).parent / "models"
    return {"det": d / "PP-OCRv6_det_small.onnx", "rec": d / "PP-OCRv6_rec_small.onnx",
            "cls": d / "ch_ppocr_mobile_v2.0_cls_mobile.onnx"}


def make_engine(paths, log_level="error"):
    from rapidocr import RapidOCR
    return RapidOCR(params={"Global.log_level": log_level, "Global.use_cls": False,
                            "Det.model_path": str(paths["det"]), "Rec.model_path": str(paths["rec"]),
                            "Cls.model_path": str(paths["cls"])})


def texts(res):
    return list(res.txts) if getattr(res, "txts", None) else []


def check_memory():  # run in a fresh process
    m0 = mem_mb()
    import numpy  # noqa: F401
    import rapidocr  # noqa: F401
    m1 = mem_mb()
    eng = make_engine(model_files())
    m2 = mem_mb()
    eng(test_image())
    m3 = mem_mb()
    import numpy as np
    big = np.ascontiguousarray(np.tile(test_image(w=640, h=360), (3, 3, 1)))  # 1920x1080
    eng(big)
    m4 = mem_mb()
    print(json.dumps({"start": m0, "after_import": m1, "after_ctor": m2, "after_first_640x200": m3,
                      "after_1920x1080": m4}))


PYW_SCRIPT = r'''
import json, sys
sys.path.insert(0, %r)
out = {"launch_stdout_is_none": sys.stdout is None, "launch_stderr_is_none": sys.stderr is None}
sys.stdout = sys.stderr = None  # exactly what a windowed (console=False) PyInstaller exe sees
try:
    import numpy as np
    from robustness import make_engine, model_files, test_image, texts
    eng = make_engine(model_files(), log_level="info")
    out["texts"] = texts(eng(test_image()))
    out["empty_image_result"] = texts(eng(np.zeros((200, 400, 3), np.uint8)))
    out["ok"] = True
except Exception as e:
    import traceback
    out["ok"] = False
    out["error"] = traceback.format_exc()
open(%r, "w", encoding="utf-8").write(json.dumps(out, ensure_ascii=False))
'''

LOG_SCRIPT = r'''
import sys
sys.path.insert(0, %r)
from robustness import make_engine, model_files, test_image
import numpy as np
eng = make_engine(model_files(), log_level=%r)
eng(test_image())
eng(np.zeros((200, 400, 3), np.uint8))
'''


def main():
    out_json, work = Path(sys.argv[1]), Path(sys.argv[2])
    res = {}
    import numpy as np
    from ocr_common import load_image_bgr

    # a) Chinese model directory
    zh = work / "測試路徑" / "模型"
    zh.mkdir(parents=True, exist_ok=True)
    src = model_files()
    zpaths = {k: zh / v.name for k, v in src.items()}
    for k in src:
        shutil.copy2(src[k], zpaths[k])
    try:
        eng = make_engine(zpaths)
        res["a_chinese_model_dir"] = {"ok": True, "dir": str(zh), "texts": texts(eng(test_image()))}
    except Exception as e:  # noqa: BLE001
        res["a_chinese_model_dir"] = {"ok": False, "error": repr(e)}
        eng = make_engine(src)

    # b) Chinese image path
    import cv2
    from PIL import Image
    ip = work / "測試路徑" / "截圖 兌換碼.png"
    Image.fromarray(test_image()[:, :, ::-1]).save(ip)
    cv = cv2.imread(str(ip))
    arr = load_image_bgr(ip)
    res["b_chinese_image_path"] = {"cv2_imread_is_none": cv is None, "pil_loader_shape": list(arr.shape),
                                   "texts_from_numpy": texts(eng(arr))}

    # c) threads
    imgs = [test_image("兌換碼：%s" % c) for c in ["AB12-CD34", "ZX98-QW76", "MN55-OP44", "GH31-JK20"]]
    seq = [texts(eng(im)) for im in imgs]
    box = {}

    def worker():
        try:
            e2 = make_engine(src)
            box["texts"] = [texts(e2(im)) for im in imgs]
        except Exception as ex:  # noqa: BLE001
            box["error"] = repr(ex)
    t = threading.Thread(target=worker)
    t.start()
    t.join()
    shared, errs = {}, []

    def use_shared(tid):
        try:
            shared[tid] = [texts(eng(im)) for im in imgs * 5]
        except Exception as ex:  # noqa: BLE001
            errs.append(repr(ex))
    ths = [threading.Thread(target=use_shared, args=(i,)) for i in range(2)]
    t0 = time.perf_counter()
    for th in ths:
        th.start()
    for th in ths:
        th.join()
    res["c_threads"] = {"created_in_worker_matches": box.get("texts") == seq, "worker_error": box.get("error"),
                        "shared_2_threads_match_sequential": all(v == seq * 5 for v in shared.values()) and not errs,
                        "shared_errors": errs, "shared_wall_s": round(time.perf_counter() - t0, 2)}
    mem = subprocess.run([sys.executable, str(HERE / "robustness.py"), "--memory"], capture_output=True, text=True)
    res["c_memory_mb"] = json.loads(mem.stdout.strip().splitlines()[-1]) if mem.returncode == 0 else mem.stderr[-800:]

    # d) logging noise and pythonw
    for lvl in ("info", "error"):
        p = subprocess.run([sys.executable, "-c", LOG_SCRIPT % (str(HERE), lvl)], capture_output=True)
        res["d_log_%s" % lvl] = {"rc": p.returncode, "stdout_bytes": len(p.stdout), "stderr_bytes": len(p.stderr),
                                 "stderr_head": p.stderr[:300].decode("utf-8", "replace")}
    pyw = Path(sys.executable).with_name("pythonw.exe")
    rj = work / "測試路徑" / "pythonw_result.json"
    if rj.exists():
        rj.unlink()
    p = subprocess.run([str(pyw), "-c", PYW_SCRIPT % (str(HERE), str(rj))], capture_output=True, timeout=300)
    res["d_pythonw"] = {"rc": p.returncode, "result": json.loads(rj.read_text(encoding="utf-8")) if rj.exists() else None}
    out_json.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", out_json)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--memory":
        check_memory()
    else:
        main()
