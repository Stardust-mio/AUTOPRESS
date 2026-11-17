# R1: OCR engine for AutoPress - feasibility and benchmark

Measured 2026-11-17 on Windows 10 LTSC 2021 (19044), i7-8700 6C/12T, 32 GB, CPU only, Python 3.12.10. Every number comes
from a run of the named script in `scripts/ocr/` (raw results in scratch); latencies (3.4) come from a separate run.
Names: `rapid_v6s` = RapidOCR + PP-OCRv6 small det/rec; `@max960` = `Det.limit_type=max, limit_side_len=960` (default `min/736`);
`v6t`/`v6m`/`v5m` = PP-OCRv6 tiny/medium, PP-OCRv5 mobile; `win` = Windows.Media.Ocr zh-Hant-TW; `tess` = Tesseract 5.5.4.

## 1. Recommendation
- **RapidOCR 3.10.0 on ONNX Runtime 1.32.0 (CPU) with the PP-OCRv6 small det + rec models shipped in the rapidocr wheel**
  (9.9 + 21.2 MB, Apache-2.0): one model reads zh-TW, zh-CN, English and Japanese; offline from explicit model paths
  (Chinese folders OK); no download. Installed in the project venv (dry-run first: PyQt6 6.12.1 / numpy 2.5.5 /
  Pillow 13.0.0 unchanged; `rapidocr` + `onnxruntime` alone resolve to exactly this set; `pip check` clean):
  `.venv\Scripts\python.exe -m pip install rapidocr==3.10.0 onnxruntime==1.32.0 opencv-python-headless==5.0.0.93 shapely==2.2.0 pyclipper==1.4.0 omegaconf==2.4.0 PyYAML==6.0.3 six==1.17.0 tqdm==4.70.1 colorlog==6.12.0 requests==2.34.2 urllib3==2.8.0 certifi==2026.10.23 charset-normalizer==3.5.2 idna==3.20 protobuf==7.36.2 flatbuffers==25.12.19`
- **Config** (as in the recipe): `Global.use_cls=False`, `Global.log_level=error`, `Det.limit_type=max, limit_side_len=960`
  for ROI crops - same U1/U2 accuracy as the default `min/736`, 1.9-2.9x faster (195 vs 563 ms per 640x360 crop, 416 vs
  1183 ms per full-HD frame); 1920 for whole-screen scans. No preprocessing except 2x upscaling of UI text < 16 px.
  One OCR worker thread owns the engine; OCR user-drawn ROIs instead of the whole screen.
- **Rejected**: Windows OCR as fallback (U1 23 % vs 80 %, U2 313 vs 494 of 512, U3 zh-TW 39 % vs 100 %, no scores, only
  installed OCR languages - zh-Hant-TW only here); Tesseract (U1 39 %); v6 tiny (no 兌認領獎勵, no kana); v5 mobile (U1 76 %,
  zh-TW 89 %, 兌->兑); v6 medium (U1 80 % like small, 139 MB download, 2.7-5.7 s/image); torch/paddle (100+ MB, not run).

## 2. Candidates (pypi_info.py, PyPI JSON 2026-11-17)
| package | version (upload) | license | wheel | notes |
|---|---|---|---|---|
| rapidocr | 3.10.0 (2026-10-08) | Apache-2.0 | 27.3 MB | bundles v6 small det/rec + v2.0 cls; pulls opencv-python-headless (5.0.0.93, 43.8 MB), shapely, pyclipper, omegaconf, PyYAML, Pillow, numpy<3, six, tqdm, requests, colorlog; **not** onnxruntime |
| onnxruntime | 1.32.0 (2026-11-13) | MIT | 16.7 MB | deps flatbuffers, numpy, packaging, protobuf |
| tesserocr | 2.13.0 (2026-11-12) | MIT | 23.2 MB | bundles Tesseract 5.5.4 DLLs; traineddata separate (tessdata_fast eng 4.1 + chi_tra 2.4 MB, benchmarked as `eng+chi_tra`) |
| winrt-runtime + winrt-Windows.Media.Ocr (+Imaging, Streams, Foundation, Globalization) | 4.1.0 / 4!10.0.28000.2957 | MIT | < 0.3 MB | OS OCR; languages = installed OCR packs |
| rapidocr_onnxruntime / onnxocr; paddleocr, easyocr, cnocr, python-doctr, surya-ocr | 1.4.4 / 4.0.0; 3.7.0, 1.7.2, 2.3.3, 1.1.0, 0.24.0 | Apache-2.0 | 14.9 / 75.2 MB; - | legacy (Py<3.13, GUI opencv) / same PP-OCRv5+v6 ONNX files + doc tools; paddleocr runs on the separately installed PaddlePaddle (104.8 MB wheel), easyocr/cnocr/doctr require torch (126.7 MB wheel), surya 0.24 has torch only in its `build` extra |

Other models: ModelScope (`www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx/...`, SHA256-checked) into
`Global.model_root_dir`; `download_models.py` pre-fetches; explicit `Det/Rec.model_path` = no network, no hashing (self-test
passed with HTTP(S)_PROXY on a dead port). MB: v6 det tiny/small/medium 1.8/9.9/62.1, rec 4.5/21.2/76.6; v5 det 4.8, rec 16.6;
korean v5 rec 13.5. Dictionaries (model_vocab.py): v6 small/medium 18,708 (15,565 CJK, 86 hiragana, 94 katakana, no Hangul),
v6 tiny 6,904 (no kana), korean v5 11,945 (11,172 Hangul, no CJK).

## 3. Benchmarks
### 3.1 U1 - codes in images (gen_u1_codes.py -> bench_u1.py -> report_u1.py, via `run_u1.sh`)
240 crops >= 640x360: Chinese header/footer + code line (alone, `兌換碼：CODE`, in a sentence); Arial, Consolas, Segoe UI,
JhengHei, Times, Impact, Verdana, Bahnschrift, Tahoma at 12-48 px; light, dark, low-contrast, gradient, noisy game panel;
30 % JPEG. Codes 8-16 chars, A-Z0-9 (75 %) or mixed case, 40 % dashed, ~50 % from `0O1I5S8B2Z6GUV`(+`lo`). Cells: exact %
**raw / post / ctc** (verbatim in an OCR row / `extract_codes()` with declared charset+pattern / constrained CTC re-read).
Pre: up2/up3 = bicubic 2x/3x; gray_ac = grayscale + autocontrast; invert = invert images with mean luma < 110.

| engine | none | up2 | up3 | gray_ac | invert |
|---|---|---|---|---|---|
| rapid_v6s | 80/80/80 | 79/79/79 | 78/78/80 | 75/75/75 | 81/81/81 |
| rapid_v6s@max960 | 78/78/80 | 79/79/80 | 78/78/79 | 74/74/73 | 79/79/80 |
| rapid_v6m@max960 | 80/80/80 | | | | |
| rapid_v5m | 76/76/75 | | | | |
| rapid_v6t | 60/60/60 | 57/57/56 | 56/56/57 | 52/52/52 | 59/59/58 |
| tess | 37/39/- | 35/35/- | 36/37/- | | |
| win | 16/23/- | 18/24/- | 18/22/- | 16/21/- | 16/22/- |

`rapid_v6s` none/ctc by subset: 12-14 px 73, 16-20 px 89, 24-32 px 78, 40-48 px 79; light 92, dark 85, low-contrast 68/75,
gradient 90, game 72; A-Z0-9 82, mixed 75. Code line always detected; the 64 char errors are look-alike swaps or drops
(O->0 43, l->I 8, l->1 3, O/o dropped 4; win 753, tess 443). O->0 is a font issue: Bahnschrift 17/18, Impact 15/15, Consolas 8/19,
Arial/Segoe/Times/Verdana 0 letter-O read as 0; codes without a letter O: 121/129 exact. Preprocessing moved rapid_v6s <= 2 points.

### 3.2 U2 - find UI labels and click them (bench_u2.py)
Dark dialog 800x500 (title, label 請輸入兌換碼 / Enter your redeem code, input box, buttons 兌換/取消, 確認/領取, Redeem/Cancel,
Confirm/OK) at 10-24 px, alone and in a 1920x1080 HUD scene; 16 targets/size; OK = strict `find_text_center()` hit inside.

| engine (input) | 10 px | 12 | 13 | 14 | 16 | 18 | 20 | 24 | all rows of the engine |
|---|---|---|---|---|---|---|---|---|---|
| rapid_v6s (dialog / 2x upscale) | 13/14 | 15/16 | 16/15 | 15/16 | 16 | 16 | 16 | 16 | 494/512 OK, 0 wrong clicks |
| rapid_v6s (full-HD scene) | 12 | 15 | 15 | 15 | 16 | 16 | 16 | 16 | |
| rapid_v6s@max960 (dialog / full-HD) | 13/10 | 16/16 | 14/15 | 16/15 | 15/16 | 16 | 16 | 16 | 493/512, 0 wrong |
| rapid_v6t (dialog) | 8 | 10 | 9 | 10 | 10 | 10 | 10 | 10 | 312/512, 0 wrong |
| win (dialog / 3x upscale) | 2/9 | 4/9 | 7/11 | 10/13 | 10/14 | 14/10 | 11/12 | 9/14 | 313/512, 6 wrong |

- `res.boxes`: N x 4 x 2 float, clockwise from top-left, in the pixel space of the array passed in; e.g. 14 px: `兌換` ->
  `[[273,380],[307,380],[307,401],[273,401]]`, score 0.997. Click = mean of the 4 points (error vs true text centre: median
  0.5 px, max 2.1). >= 16 px always found; 12-14 px 15/16 (2x ROI upscale fixes it); 10 px 13-14/16. 13 of the 18 misses
  were the two long labels, 5 buttons (兌換 x4, OK x1). Substring fallback (`exact=False`) adds wrong clicks (rapid 2-6/512,
  win 53/512): click only on strict matches. Windows OCR drops words (`Please confirm` -> `confirm` = the `Confirm` button).

### 3.3 U3 - result messages (bench_u3.py)
26 messages (兌換成功 / 序號已被使用 / 兌換碼無效 / 兌換碼已過期 / 操作過於頻繁，請稍後再試 / 獎勵已發送至信箱 + zh-CN, en, ja, ko
versions) at 14/18/24 px, dark + light = 156 popups. Cells: exact % / CER % / class accuracy % (`classify()` keyword lists).

| engine | zh-TW | zh-CN | en | ja | ko |
|---|---|---|---|---|---|
| rapid_v6s | 100/0/100 | 100/0/100 | 100/0/100 | 100/0/100 | 0/100/0 |
| v6 small det + korean_PP-OCRv5 rec | 0/100/0 | 0/100/0 | 100/0/100 | 0/100/0 | 100/0/100 |
| rapid_v5m | 89/3/100 | 90/2/100 | 100/0/100 | 100/0/100 | 0/100/0 |
| rapid_v6t | 17/21/100 | 100/0/100 | 100/0/100 | 0/71/60 | 0/100/0 |
| win | 39/18/81 | 33/24/87 | 40/6/93 | 0/69/67 | 0/100/0 |

Korean needs `korean_PP-OCRv5_rec_mobile.onnx` (13.5 MB) as `Rec.model_path` of a **second engine** (loses CJK); other
rec models in default_models.yaml: PP-OCRv5 latin, eslav, th, el, arabic, cyrillic, devanagari, ta, te, en; PP-OCRv4 ka.

### 3.4 Latency, cold start, memory (bench_latency.py, robustness.py)
Median ms per image (3 runs); cold start = fresh process, 640x360 image; live = mss capture of the 1920x1080 desktop.

| engine | import / ctor / 1st / 2nd call (s) | 640x360 | 800x500 | 1920x1080 | live desktop |
|---|---|---|---|---|---|
| rapid_v6s (default `min/736`) | 0.22 / 0.81 / 0.90 / 0.56 | 563 | 505 | 1183 | 4471 |
| rapid_v6s@max960 | 0.19 / 0.76 / 0.46 / 0.18 | 195 | 265 | 416 | 1692 |
| rapid_v6s@max960, 4 / 2 ORT threads | - | 220 / 334 | 314 / 479 | 487 / 728 | 2080 / 2822 |
| rapid_v6s@max1920 | 0.19 / 0.83 / 0.50 / 0.17 | 201 | 262 | 1396 | 4495 |
| rapid_v5m | 0.20 / 0.83 / 0.93 / 0.45 | 488 | 422 | 1104 | 9032 |
| rapid_v6t | 0.21 / 0.80 / 0.40 / 0.18 | 190 | 176 | 412 | 1376 |
| rapid_v6m@max960 (1 run) | 0.19 / 0.74 / 3.64 / 2.49 | 2710 | 3514 | 5655 | 45907 |
| win | 0.09 / 0.10 / 0.07 / 0.02 | 20 | 28 | 78 | 739 |
| tess | 0.04 / 0.25 / 0.09 / 0.08 | 137 | 96 | 269 | 6367 |

Memory (rapid_v6s): working set 58 MB after construction, 127 MB after the first call, peak 409 MB on 1920x1080; numpy's
OpenBLAS adds +362 MB *commit* (not RAM) at import - `OPENBLAS_NUM_THREADS=1` before importing numpy -> +8 MB, same speed.

## 4. Verified recipe (`scripts/ocr/autopress_ocr_recipe.py`, code between the BEGIN/END RECIPE markers)
Project venv, after the install: `python autopress_ocr_recipe.py --selftest OUT.json --qthread` (engine built and used in
a QThread, network blocked by a dead proxy): 5/5 checks passed - U1 code read, 兌換/取消 click points inside their buttons,
12 px label found with `k=2`, U3 text read; first result 1.14 s after engine creation, then 313 ms per 800x500 dialog.

```python
import string
import unicodedata
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

def load_image_bgr(path):
    """Any Pillow format; the path may contain Chinese. Returns HxWx3 uint8 BGR."""
    with Image.open(path) as im:
        rgb = np.asarray(ImageOps.exif_transpose(im).convert("RGB"))
    return np.ascontiguousarray(rgb[:, :, ::-1])

def create_engine(model_dir, threads=-1, det_side=960):
    """One engine per OCR worker thread. Explicit paths = offline, no download/SHA256 step.
    det_side: never upscale, shrink inputs whose long side exceeds it (1920 for full screens)."""
    from rapidocr import RapidOCR
    d = Path(model_dir)
    return RapidOCR(params={
        "Global.log_level": "error",  # silent (a windowed exe has sys.stderr = None)
        "Global.use_cls": False,  # screen text is upright
        "Det.model_path": str(d / "PP-OCRv6_det_small.onnx"),
        "Rec.model_path": str(d / "PP-OCRv6_rec_small.onnx"),
        "Det.limit_type": "max", "Det.limit_side_len": det_side,
        "EngineConfig.onnxruntime.intra_op_num_threads": threads})  # -1 = ORT default

def run_ocr(engine, img_bgr, k=1):
    """-> [(text, quad float32 4x2 tl,tr,br,bl in input pixels, score)]; k = upscale factor."""
    if k > 1:
        h, w = img_bgr.shape[:2]
        pil = Image.fromarray(img_bgr[:, :, ::-1]).resize((w * k, h * k), Image.Resampling.BICUBIC)
        img_bgr = np.ascontiguousarray(np.asarray(pil)[:, :, ::-1])
    res = engine(img_bgr)
    if getattr(res, "boxes", None) is None or getattr(res, "txts", None) is None:
        return []
    return [(t, np.asarray(b, np.float32).reshape(4, 2) / k, float(s))
            for b, t, s in zip(res.boxes, res.txts, res.scores)]

def _norm(s):
    return "".join(c for c in unicodedata.normalize("NFKC", s) if not c.isspace()).casefold()

def find_text_center(items, target, exact=True):
    """Click point (x, y) for `target`: best box whose text equals it (exact) or contains it
    (exact=False -> proportional sub-box, CJK chars count double). None if not found."""
    t, best = _norm(target), None
    for text, quad, score in items:
        n = _norm(text)
        i = n.find(t)
        if not t or i < 0 or (exact and n != t):
            continue
        w = [2.0 if unicodedata.east_asian_width(c) in "WF" else 1.0 for c in n]
        a, b = sum(w[:i]) / sum(w), sum(w[:i + len(t)]) / sum(w)
        tl, tr, br, bl = quad
        cx = (tl[0] + (tr[0] - tl[0]) * (a + b) / 2 + bl[0] + (br[0] - bl[0]) * (a + b) / 2) / 2
        cy = float(quad[:, 1].mean())
        if best is None or (n == t, score) > best[0]:
            best = ((n == t, score), (float(cx), cy))
    return best[1] if best else None

def recognize_code_line(engine, img_bgr, quad, allowed=string.ascii_uppercase + string.digits + "-"):
    """Re-read one detected line with Latin-looking characters forced into `allowed`
    (charset-constrained CTC). Returns (text, per-character confidences)."""
    from rapidocr.utils.process_img import get_rotate_crop_image
    rec = engine._load_rec_model()  # internal API, pinned to rapidocr==3.10.0
    crop = get_rotate_crop_image(img_bgr, np.asarray(quad, np.float32).copy())
    _, ih, iw = rec.rec_image_shape
    x = rec.resize_norm_img(crop, max(iw / ih, crop.shape[1] / crop.shape[0]))[None]
    probs = rec.session(x.astype(np.float32))[0]  # (T, C) softmax
    chars = rec.postprocess_op.character  # index 0 = CTC blank
    latin = set(string.ascii_letters + string.digits + "-|!$")
    ok = np.array([i for i, c in enumerate(chars) if i and c in allowed])
    top = probs.argmax(1)
    pick = [ok[probs[t, ok].argmax()] if k and chars[k] in latin else k for t, k in enumerate(top)]
    text, confs, prev = [], [], 0
    for t, k in enumerate(pick):
        if k and k != prev:
            text.append(chars[k])
            confs.append(float(probs[t, k]))
        prev = k
    return "".join(text), confs
```
- **U1**: numpy BGR (`load_image_bgr`; mss BGRA -> drop channel 3) -> `run_ocr` -> `recognize_code_line` on Latin lines ->
  `extract_codes` (section 7) -> review UI. **U2**: OCR the user's ROI (`k=2` if text < 16 px), strict
  `find_text_center(items, "兌換")` + ROI offset -> click (physical pixels, DPI-aware process); not found -> retry/stop.
  **U3**: OCR the popup ROI, join texts, per-profile keywords (`bench_u3.classify()`); `unknown`/`rate_limited` -> stop.

## 5. Pitfalls (observed)
- `cv2.imread` returns None (plus a WARN) for `...\測試路徑\截圖 兌換碼.png`: pass numpy arrays, load with PIL. ONNX files in
  a Chinese folder load fine via explicit `model_path` (robustness.py a/b). Models load lazily: warm up at app start.
- rapidocr logs coloured INFO to stderr (627-779 bytes per engine start); `log_level: error` -> 0 bytes. With
  `sys.stdout = sys.stderr = None` logging is dropped silently (pythonw test and the windowed PyInstaller exe).
- Engine built/used in a worker thread or QThread: OK; 2 threads sharing one instance: identical results (40 calls), but
  `RapidOCR.__call__` mutates instance state for per-call overrides (`update_params`) - one OCR worker owns the engine.
- `recognize_code_line` uses rapidocr internals (`_load_rec_model`, `rec_image_shape`, `resize_norm_img`, `session`,
  `postprocess_op.character`): pin `rapidocr==3.10.0`, unit-test on upgrade. mss 10.2: `mss.MSS()` (`mss.mss()` is deprecated).
- Never auto-try O/0 or I/1 variants of a rejected code - that is guessing; ask the user.

## 6. Packaging (PyInstaller 6.22.3 + hooks-contrib 2026.10; `scripts/ocr/pack_test/ocrpack.spec`, built and run)
- Contrib hooks cover onnxruntime (`collect_dynamic_libs`), cv2, shapely, numpy, PIL; rapidocr needs
  `datas = collect_data_files("rapidocr", excludes=["**/pytorch/**"])` (config.yaml, default_models.yaml, models/*.onnx);
  no hidden imports. Drop OpenCV's FFmpeg plugin (31 MB, LGPL, unused): filter `opencv_videoio_ffmpeg` out of a.binaries.
  `model_dir` = `Path(sys._MEIPASS) / "rapidocr" / "models"` when frozen, `Path(rapidocr.__file__).parent / "models"` in dev.
- OCR-only app: one-folder 204 MB, onefile 105.5 MB (cv2.pyd 85.8, onnxruntime 46.2, models 31.7, OpenBLAS 20.6, PIL `_avif`
  7.9 - excludable, libcrypto 5.2: rapidocr always imports `requests` + `hashlib`); with TIMER's trimmed PyQt6 onefile (20.1 MB) expect
  ~125 MB for AutoPress (estimate). Windowed exe via ShellExecute (stdout/stderr None): correct text after 4.3-4.8 s
  (onefile 7.8 s). Ship notices: rapidocr LICENSE + MODEL_LICENSES.md (PP-OCRv6 weights Apache-2.0, (c) Baidu/PaddleOCR,
  attribution required), onnxruntime MIT, OpenCV Apache-2.0 + LICENSE-3RD-PARTY.txt, GEOS LGPL-2.1, BSD/MPL rest.

## 7. U1 post-processing (`ocr_common.py`: `CodeSpec`, `extract_codes`, `ctc_constrained_decode`)
1. Per game the user declares charset (default A-Z0-9), groups (`XXXX-XXXX-XXXX`) or length range, and whether ambiguous
   letters occur (many games omit O/I/L - then repairing them is safe). 2. Normalize rows (NFKC; `－–—ー一_~` -> `-`);
   candidates = runs of `[A-Za-z0-9-|!$§口丨工 ]`, every window of tokens. 3. Repair a character **only if it is outside the
   charset** (first allowed member of its confusable group: `o->O/0`, `l i | ! -> I/1`, `$ § -> S/5`, `z -> Z/2` ..., else
   a case change); re-insert dashes per the groups if the count fits. 4. Constrained CTC (`recognize_code_line`): Latin-like
   frames re-decided among allowed characters (blank excluded), CJK frames untouched -> in-charset text + per-char confidence.
Effect: rule repair adds nothing for RapidOCR (its errors are in-charset O->0 swaps) but lifts win from 16 to 23 %;
constrained CTC moves exact match by -1 to +2 points. Review flags (bench_u1_flags.py, rapid_v6s, 62 wrong of 3,083 chars):

| flag rule | wrong chars flagged | correct chars flagged | wrong codes flagged | correct codes flagged |
|---|---|---|---|---|
| conf < 0.90 | 31 % | 2 % | 47 % | 16 % |
| conf < 0.95 | 48 % | 3 % | 66 % | 22 % |
| conf < 0.90 or glyph in {0, O} | 82 % | 9 % | 98 % | 70 % |

The model is confidently wrong on O/0: highlight conf < 0.95 **and** always mark 0/O (1/I/l for mixed case), show the
source crop next to the text, and auto-repair only when the declared charset rules a glyph out.

## 8. Reproduce (Git Bash; R = python of a venv with the section-1 packages, S = scratch dir as a C:/... path)
- `bash run_u1.sh $S $R [winocr_py] [tesserocr_py]` -> `$S/res/report_u1.md` (`LIMIT=6` smoke run verified, 96 s).
- `$R bench_u1_flags.py $S/u1 $S/flags.json --models $S/models_dl`; `$R bench_u2.py $S/u2 --engines rapid_v6s,rapid_v6s@max960,rapid_v6t
  --models $S/models_dl` (win: pywinrt venv); `$R bench_u3.py $S/u3 --engines rapid_v6s,rapid_v6t,rapid_v5m,rapid_v6s_kor --models
  $S/models_dl`; `$R bench_latency.py $S/u1 --engines <list> --threads=-1,4,2 --models $S/models_dl --screen` (note the `=`);
  `$R robustness.py $S/rob.json $S`; `$R model_vocab.py <rec.onnx ...>`; `python pypi_info.py out.json`; pack test: `pack_test/ocrpack.spec` header.
