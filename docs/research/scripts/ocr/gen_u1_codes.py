"""Generate the synthetic U1 benchmark: redeem codes inside screenshot-like crops.

Usage:
    python gen_u1_codes.py OUT_DIR [--n 240] [--seed 7]

Writes OUT_DIR/img_0000.png ... and OUT_DIR/labels.json (ground truth + render params).
Each image is a 640x360-ish crop with a Chinese header line, the code line and a
Chinese footer line. The code line layout is one of:
    alone     "AB0O-1I5S-8B2Z"
    prefix    "兌換碼：AB0O-1I5S-8B2Z"
    sentence  "請在遊戲中輸入 AB0O1I5S 即可領取獎勵"
Codes: length 8-16 over A-Z0-9 (75%) or A-Za-z0-9 (25%), ~50% of characters drawn
from the confusable set, 40% grouped with dashes. Backgrounds: light, dark,
low-contrast light/dark, gradient, noisy "game UI" panel. 30% get a JPEG round trip.
"""
import argparse
import io
import json
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_DIR = "C:/Windows/Fonts/"
LATIN_FONTS = ["arial.ttf", "consola.ttf", "segoeui.ttf", "msjh.ttc", "times.ttf",
               "impact.ttf", "verdana.ttf", "bahnschrift.ttf", "tahoma.ttf"]
CJK_FONT = "msjh.ttc"
SIZES = [12, 14, 16, 18, 20, 24, 28, 32, 40, 48]
BGS = ["light", "dark", "lowc_light", "lowc_dark", "gradient", "game"]
LAYOUTS = ["alone", "prefix", "sentence"]
UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
MIXED = UPPER + "abcdefghijklmnopqrstuvwxyz"
CONF_UPPER = "0O1I5S8B2Z6GUV"
CONF_MIXED = CONF_UPPER + "lo"
HEADERS = ["【官方公告】冬季活動限定兌換碼", "感謝大家支持！本週禮包碼如下", "序號領取教學：設定 → 帳號 → 兌換",
           "週年慶回饋 限時領取", "新角色上線紀念禮包", "直播抽獎序號（每人限用一次）"]
FOOTERS = ["有效期限：2026/12/31 23:59", "每個帳號限兌換一次", "請於遊戲內「兌換」頁面輸入",
           "獎勵將於 5 分鐘內寄送至信箱", "如有問題請聯繫客服", "數量有限 兌完為止"]


def make_code(rng, charset_name):
    charset = UPPER if charset_name == "upper" else MIXED
    conf = CONF_UPPER if charset_name == "upper" else CONF_MIXED
    dashed = rng.random() < 0.4
    if dashed:
        g = rng.choice([4, 5])
        n_groups = rng.choice([2, 3]) if g == 5 else rng.choice([2, 3, 4])
        groups = [g] * n_groups
    else:
        groups = [rng.randint(8, 16)]
    chars = [(rng.choice(conf) if rng.random() < 0.5 else rng.choice(charset)) for _ in range(sum(groups))]
    out, i = [], 0
    for gl in groups:
        out.append("".join(chars[i:i + gl]))
        i += gl
    return "-".join(out), groups


def background(rng, kind, w, h):
    if kind == "light":
        c = rng.randint(232, 255)
        return Image.new("RGB", (w, h), (c, c, rng.randint(225, 255))), (rng.randint(0, 60),) * 3
    if kind == "dark":
        c = rng.randint(10, 40)
        return Image.new("RGB", (w, h), (c, c, c + rng.randint(0, 20))), (rng.randint(210, 255),) * 3
    if kind == "lowc_light":
        c = rng.randint(196, 220)
        t = c - rng.randint(55, 75)
        return Image.new("RGB", (w, h), (c, c, c)), (t, t, t)
    if kind == "lowc_dark":
        c = rng.randint(35, 60)
        t = c + rng.randint(55, 75)
        return Image.new("RGB", (w, h), (c, c, c)), (t, t, t)
    if kind == "gradient":
        c1 = np.array([rng.randint(0, 255) for _ in range(3)], np.float32)
        c2 = np.array([rng.randint(0, 255) for _ in range(3)], np.float32)
        t = np.linspace(0, 1, w if rng.random() < 0.5 else h, dtype=np.float32)
        grad = c1[None, :] * (1 - t[:, None]) + c2[None, :] * t[:, None]
        arr = np.broadcast_to(grad[None, :, :], (h, w, 3)) if len(t) == w else np.broadcast_to(grad[:, None, :], (h, w, 3))
        mean = float(arr.mean())
        fg = (0, 0, 0) if mean > 140 else (255, 255, 255)
        return Image.fromarray(np.ascontiguousarray(arr).astype(np.uint8)), fg
    # "game": dark blue/purple gradient, random translucent shapes, noise, framed panel
    top = np.array([rng.randint(10, 40), rng.randint(10, 40), rng.randint(50, 100)], np.float32)
    bot = np.array([rng.randint(40, 90), rng.randint(10, 40), rng.randint(60, 120)], np.float32)
    t = np.linspace(0, 1, h, dtype=np.float32)
    arr = (top[None, :] * (1 - t[:, None]) + bot[None, :] * t[:, None])
    img = Image.fromarray(np.broadcast_to(arr[:, None, :], (h, w, 3)).astype(np.uint8)).convert("RGBA")
    ov = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    for _ in range(rng.randint(4, 9)):
        x0, y0 = rng.randint(-50, w), rng.randint(-50, h)
        r = rng.randint(20, 120)
        col = (rng.randint(80, 255), rng.randint(60, 200), rng.randint(100, 255), rng.randint(25, 70))
        (d.ellipse if rng.random() < 0.5 else d.rectangle)([x0, y0, x0 + r, y0 + r], fill=col)
    img = Image.alpha_composite(img, ov.filter(ImageFilter.GaussianBlur(3)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([12, 12, w - 12, h - 12], radius=14, outline=(210, 170, 90, 255), width=3,
                        fill=(20, 20, 45, 150))
    arr = np.asarray(img.convert("RGB")).astype(np.int16)
    arr = arr + np.random.default_rng(rng.randint(0, 1 << 30)).normal(0, 9, arr.shape).astype(np.int16)
    fg = rng.choice([(255, 220, 120), (255, 255, 255), (140, 230, 255)])
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)), fg


def line_segments(layout, code, latin_font):
    if layout == "alone":
        return [(code, latin_font)]
    if layout == "prefix":
        return [("兌換碼：", CJK_FONT), (code, latin_font)]
    return [("請在遊戲中輸入 ", CJK_FONT), (code, latin_font), (" 即可領取獎勵", CJK_FONT)]


def seg_width(segs, size):
    return sum(ImageFont.truetype(FONT_DIR + f, size).getlength(t) for t, f in segs)


def draw_line(d, x, y_base, segs, size, fill, stroke):
    for text, f in segs:
        font = ImageFont.truetype(FONT_DIR + f, size)
        d.text((x, y_base), text, font=font, fill=fill, anchor="ls",
               stroke_width=stroke, stroke_fill=(0, 0, 0))
        x += font.getlength(text)


def render(rng, idx, out_dir):
    size = SIZES[idx % len(SIZES)]
    bg = BGS[(idx // len(SIZES)) % len(BGS)]
    latin_font = LATIN_FONTS[(idx * 7 + idx // 60) % len(LATIN_FONTS)]
    layout = LAYOUTS[(idx // 3) % len(LAYOUTS)]
    charset = "mixed" if idx % 4 == 3 else "upper"
    code, groups = make_code(rng, charset)
    segs = line_segments(layout, code, latin_font)
    head = rng.choice(HEADERS)
    foot = rng.choice(FOOTERS)
    side = max(12, int(size * 0.85))
    w = int(max(640, seg_width(segs, size) + 80, seg_width([(head, CJK_FONT)], side) + 80))
    h = int(max(360, size * 6))
    img, fg = background(rng, bg, w, h)
    d = ImageDraw.Draw(img)
    stroke = 1 if (bg == "game" and size >= 18 and rng.random() < 0.5) else 0
    x = rng.randint(30, max(31, w - int(seg_width(segs, size)) - 30))
    yc = h // 2 + rng.randint(-20, 20)
    draw_line(d, 30, yc - int(size * 1.9), [(head, CJK_FONT)], side, fg, 0)
    draw_line(d, x, yc + int(size * 0.35), segs, size, fg, stroke)
    draw_line(d, 30, yc + int(size * 2.4), [(foot, CJK_FONT)], side, fg, 0)
    jpeg = rng.random() < 0.3
    if jpeg:
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=rng.randint(60, 85))
        img = Image.open(io.BytesIO(buf.getvalue())).convert("RGB")
    name = "img_%04d.png" % idx
    img.save(out_dir / name)
    return {"file": name, "code": code, "groups": groups, "charset": charset, "size": size,
            "bg": bg, "font": latin_font, "layout": layout, "jpeg": jpeg, "stroke": stroke,
            "w": w, "h": h}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--n", type=int, default=240)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(a.seed)
    labels = [render(rng, i, out) for i in range(a.n)]
    (out / "labels.json").write_text(json.dumps(labels, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", len(labels), "images to", out)


if __name__ == "__main__":
    main()
