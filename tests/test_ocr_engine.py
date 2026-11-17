"""G2: ocr.engine - the real RapidOCR engine on rendered cards (slow): code line, 兌換 / 取消 click
points inside their buttons, a 12 px label with upscale, max_side_len 4096, alternating
det_side values restored, constrained re-read, and a benchmark note for 2560x1440 / 3840x2160
(report only). Fast tests: model files, constrained CTC decoding, error texts."""

from __future__ import annotations

import os
import random
import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from autopress.ocr import engine as engine_mod
from autopress.ocr.engine import OcrEngine, OcrUnavailable, constrained_decode, model_files
from autopress.ocr.textfind import find_text

FONT = "C:/Windows/Fonts/msjh.ttc"
UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
BUTTONS = {"兌換": (230, 370, 350, 410), "取消": (450, 370, 570, 410)}  # x0, y0, x1, y1


def dialog(size: int) -> np.ndarray:
    """Dark 800x500 redeem dialog (ocr.md U2 / recipe self-test) with two buttons."""
    img = Image.new("RGB", (800, 500), (25, 28, 40))
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(FONT, size)
    d.text((120, 175), "請輸入兌換碼", font=f, fill=(200, 200, 205), anchor="ls")
    for lab, fill, fg in (("兌換", (214, 164, 60), (40, 25, 0)), ("取消", (78, 82, 98), (245, 245, 245))):
        x0, y0, x1, y1 = BUTTONS[lab]
        d.rounded_rectangle((x0, y0, x1, y1), radius=8, fill=fill)
        d.text(((x0 + x1) // 2, (y0 + y1) // 2), lab, font=f, fill=fg, anchor="mm")
    return np.ascontiguousarray(np.asarray(img)[:, :, ::-1])


def inside(hit: object, box: tuple[int, int, int, int]) -> bool:
    return hit is not None and box[0] <= hit.x <= box[2] and box[1] <= hit.y <= box[3]  # type: ignore[attr-defined]


@pytest.fixture(scope="module")
def engine() -> OcrEngine:
    return OcrEngine(threads=4)


# ----------------------------------------------------------------------------- fast


def test_model_files_found_and_missing(tmp_path: Path) -> None:
    det, rec = model_files()
    assert det.name == engine_mod.DET_MODEL and rec.name == engine_mod.REC_MODEL and det.is_file()
    folder = tmp_path / "模型"
    folder.mkdir()
    (folder / engine_mod.DET_MODEL).write_bytes(b"x")
    with pytest.raises(OcrUnavailable) as exc:
        model_files(folder)
    assert str(exc.value).startswith("文字辨識引擎無法啟動：") and engine_mod.REC_MODEL in str(exc.value)
    assert engine_mod.REC_MODEL in exc.value.reason and "防毒軟體" in str(exc.value)
    with pytest.raises(OcrUnavailable):
        OcrEngine(model_dir=tmp_path / "nowhere")


def test_unavailable_message_english() -> None:
    from autopress import i18n

    i18n.set_language("en")
    msg = engine_mod.unavailable_message("model file missing")
    assert msg.startswith("The OCR engine could not start: model file missing.")


def test_constrained_decode_rules() -> None:
    chars = ["blank", "A", "B", "0", "8", "o", "兌", "-", " "]
    eps = 1e-3

    def frame(best: int, alt: dict[int, float] | None = None) -> list[float]:
        p = [eps] * len(chars)
        p[best] = 0.9
        for k, v in (alt or {}).items():
            p[k] = v
        return p

    probs = np.array([
        frame(6),                 # 兌 (CJK) stays
        frame(5, {3: 0.05}),      # "o" is Latin-like -> re-decided among allowed: 0 beats A/B/8
        frame(5, {3: 0.05}),      # repeated frame collapses
        frame(0),                 # blank separates
        frame(5, {1: 0.07}),      # "o" -> A this time
        frame(8),                 # space stays
        frame(7),                 # "-" always allowed
        frame(2),                 # B allowed
    ], dtype=np.float32)
    text, confs = constrained_decode(probs, chars, "AB08")
    assert text == "兌0A -B"
    assert len(confs) == len(text)
    assert confs[1] == pytest.approx(0.05) and confs[2] == pytest.approx(0.07)
    plain, _ = constrained_decode(probs, chars, "")  # nothing allowed but "-": Latin frames -> "-"
    assert plain.startswith("兌-")


# ----------------------------------------------------------------------------- real engine (slow)


@pytest.mark.slow
def test_info_and_config(engine: OcrEngine) -> None:
    info = engine.info()
    assert info["max_side_len"] == 4096 and info["cfg_max_side_len"] == 4096
    assert info["det_side"] == 960 and info["det_limit_type"] == "max"
    assert info["use_cls"] is False and info["threads"] == 4
    assert info["rapidocr"] == engine_mod.PINNED_RAPIDOCR


@pytest.mark.slow
def test_thread_count_capped() -> None:
    assert OcrEngine(threads=999).info()["threads"] == os.cpu_count()
    assert OcrEngine(threads=0).info()["threads"] == -1


@pytest.mark.slow
def test_code_line_read(engine: OcrEngine, text_image) -> None:
    lines = engine.recognize(text_image("兌換碼：AB12-CD34"))
    assert any("AB12-CD34" in ln.text for ln in lines), [ln.text for ln in lines]
    light = engine.recognize(text_image("Code: 7KQX-M3PD-W9TZ", size=22, dark=False))
    assert any("7KQX-M3PD-W9TZ" in ln.text for ln in light), [ln.text for ln in light]
    assert engine.recognize(np.zeros((0, 0, 3), np.uint8)) == []
    assert engine.recognize(np.full((80, 200, 3), 255, np.uint8)) == []


@pytest.mark.slow
def test_click_points_inside_buttons(engine: OcrEngine) -> None:
    lines = engine.recognize(dialog(14))
    for label, box in BUTTONS.items():
        hit = find_text(lines, label)
        assert inside(hit, box), (label, hit, [ln.text for ln in lines])
    assert find_text(lines, "兌換").line_index != find_text(lines, "請輸入兌換碼").line_index


@pytest.mark.slow
def test_small_label_with_upscale(engine: OcrEngine) -> None:
    img = dialog(12)
    lines = engine.recognize(img, upscale=2)
    hit = find_text(lines, "兌換")
    assert inside(hit, BUTTONS["兌換"]), [ln.text for ln in lines]
    # quads are in ORIGINAL pixels, not the 1600x1000 upscaled ones
    assert max(x for ln in lines for x, _ in ln.quad) < 800 and max(y for ln in lines for _, y in ln.quad) < 500
    bgra = np.dstack([img, np.zeros(img.shape[:2], np.uint8)])  # mss alpha zeros must not matter
    assert find_text(engine.recognize(bgra, upscale=2), "兌換") is not None


@pytest.mark.slow
def test_max_side_len_4096_no_shrink_and_upscale_cap(engine: OcrEngine, monkeypatch: pytest.MonkeyPatch) -> None:
    ratios: list[float] = []
    real_pre = engine._ocr.preprocess_img

    def spy_pre(img: np.ndarray):
        out, rec = real_pre(img)
        ratios.append(rec["preprocess"]["ratio_w"])
        return out, rec

    monkeypatch.setattr(engine._ocr, "preprocess_img", spy_pre)
    shapes: list[tuple[int, ...]] = []
    real_run = engine._run

    def spy_run(img: np.ndarray):
        shapes.append(img.shape)
        return real_run(img)

    monkeypatch.setattr(engine, "_run", spy_run)
    wide = np.full((200, 3000, 3), 245, np.uint8)
    pil = Image.fromarray(wide)
    ImageDraw.Draw(pil).text((2500, 100), "兌換", font=ImageFont.truetype(FONT, 24), fill=(20, 20, 20), anchor="mm")
    wide = np.ascontiguousarray(np.asarray(pil)[:, :, ::-1])
    lines = engine.recognize(wide, upscale=2)
    assert shapes[-1][1] == 4096  # 2x of 3000 would be 6000: capped at the 4096 long side
    assert ratios[-1] == 1.0  # max_side_len 4096: the 4096-px input is not shrunk again
    hit = find_text(lines, "兌換")
    assert hit is not None and 2450 < hit.x < 2550 and 70 < hit.y < 130  # original pixels
    engine.recognize(np.full((300, 2600, 3), 255, np.uint8))
    assert ratios[-1] == 1.0  # the default max_side_len (2000) would have shrunk 2600 px


@pytest.mark.slow
def test_alternating_det_side_restores(engine: OcrEngine, text_image, monkeypatch: pytest.MonkeyPatch) -> None:
    det = engine._det
    seen: list[int] = []
    real = det.get_preprocess

    def spy():
        seen.append(det.limit_side_len)
        return real()

    monkeypatch.setattr(det, "get_preprocess", spy)
    img = text_image("兌換碼：AB12-CD34")
    for side in (1920, 640, None, 1280, 960, 1920):
        lines = engine.recognize(img, det_side=side)
        assert det.limit_side_len == 960
        assert any("AB12-CD34" in ln.text for ln in lines)
    assert seen == [1920, 640, 960, 1280, 960, 1920]

    def broken(_img: np.ndarray):
        raise RuntimeError("inference failed")

    monkeypatch.setattr(engine, "_run", broken)
    with pytest.raises(RuntimeError):
        engine.recognize(img, det_side=1600)
    assert det.limit_side_len == 960  # restored in finally


@pytest.mark.slow
def test_reread_line_constrains_latin_frames(engine: OcrEngine, text_image) -> None:
    img = text_image("Ab12-Cd34")  # lower-case letters trigger the charset rule
    lines = engine.recognize(img)
    assert lines and lines[0].text == "Ab12-Cd34"
    text, confs = engine.reread_line(img, lines[0].quad, UPPER)
    assert text == "AB12-CD34" and len(confs) == len(text)
    assert confs[1] < 0.5 and confs[6] < 0.5  # b and d were forced: low confidence -> review
    assert min(confs[0], confs[2], confs[3], confs[5]) > 0.95
    digits, _ = engine.reread_line(img, lines[0].quad, "0123456789")
    assert not any(c.isalpha() for c in digits)
    mixed = text_image("兌換碼：ab12-cd34")
    ml = engine.recognize(mixed)
    t2, c2 = engine.reread_line(mixed, ml[0].quad, UPPER)
    assert t2.startswith("兌換碼") and t2.endswith("AB12-CD34") and len(c2) == len(t2)  # CJK untouched
    t3, _ = engine.reread_line(mixed, ml[0].quad, UPPER, upscale=2)
    assert t3.endswith("AB12-CD34")
    assert engine.reread_line(img, [(5, 5), (5, 5), (5, 5), (5, 5)], UPPER) == ("", [])


@pytest.mark.slow
def test_warmup(engine: OcrEngine) -> None:
    assert 0 < engine.warmup() < 5


# ----------------------------------------------------------------------------- benchmark (report only)

_WORDS = ["兌換碼：", "請輸入兌換碼", "兌換", "取消", "序號已被使用", "獎勵已發送至信箱", "每日任務", "活動獎勵",
          "Redeem", "Settings", "Inventory", "Event rewards", "Lv.58", "Gold 12,345", "Mail (3)", "確認"]


def synthetic_screen(w: int, h: int, seed: int = 7) -> tuple[np.ndarray, list[str]]:
    """A busy game-like screen: dark background, panels with text lines of 14-28 px."""
    rnd = random.Random(seed)
    img = Image.new("RGB", (w, h), (18, 20, 28))
    d = ImageDraw.Draw(img)
    fonts = {s: ImageFont.truetype(FONT, s) for s in (14, 16, 18, 22, 28)}
    planted = []
    for p in range(10):
        pw, ph = rnd.randint(w // 8, w // 4), rnd.randint(h // 8, h // 4)
        x0, y0 = rnd.randint(0, w - pw), rnd.randint(0, h - ph)
        d.rounded_rectangle((x0, y0, x0 + pw, y0 + ph), radius=12, fill=(40, 44, 60))
        y = y0 + 16
        while y < y0 + ph - 40:
            size = rnd.choice(list(fonts))
            text = rnd.choice(_WORDS) + (f" {rnd.randint(10, 99)}" if rnd.random() < 0.3 else "")
            d.text((x0 + 16, y), text, font=fonts[size], fill=(230, 230, 235))
            y += int(size * 1.8)
    for size in (28, 14):
        label = f"BENCH-{w}-{size}"
        d.text((w // 2, h - 60 - size * 3), label, font=fonts[size], fill=(250, 250, 250))
        planted.append(label)
    return np.ascontiguousarray(np.asarray(img)[:, :, ::-1]), planted


@pytest.mark.slow
def test_benchmark_large_screens(engine: OcrEngine, capsys: pytest.CaptureFixture[str]) -> None:
    """Report only (T16): latency and lines found at det_side 960 with max_side_len 4096 vs the
    rapidocr default 2000. No timing assertion."""
    small_max = OcrEngine(threads=4, max_side_len=2000)
    rows = []
    for w, h in ((2560, 1440), (3840, 2160)):
        img, planted = synthetic_screen(w, h)
        for name, eng in (("max4096", engine), ("max2000", small_max)):
            eng.recognize(img)  # first call per size warms the arena
            t0 = time.perf_counter()
            lines = eng.recognize(img)
            ms = (time.perf_counter() - t0) * 1000
            found = [p for p in planted if any(p in ln.text for ln in lines)]
            rows.append(f"{w}x{h} {name}: {ms:.0f} ms, {len(lines)} lines, planted found {found}")
        assert any(planted[0] in ln.text for ln in engine.recognize(img))  # the 28 px label is read
    with capsys.disabled():
        print("\nOCR benchmark (synthetic screens, det_side 960, 4 threads):\n  " + "\n  ".join(rows))
