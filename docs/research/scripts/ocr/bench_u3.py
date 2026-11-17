"""U3 benchmark: read short redeem-result messages (zh-TW, zh-CN, en, ja, ko) and classify them.

Usage:
    python bench_u3.py OUT_DIR --engines rapid_v6s,rapid_v6t,rapid_v5m,rapid_v6s_kor [--models DIR]
    python bench_u3.py OUT_DIR --engines win_zh-Hant-TW
Each message is rendered as a popup at 14/18/24 px on a dark and a light panel (6 renders per
message). Metrics per language: exact (OCR text == message after dropping spaces/punctuation),
CER (character error rate) and keyword-class accuracy (classify() below, fuzzy substring match).
Writes OUT_DIR/u3_<engine>.json, prints a Markdown table.
"""
import argparse
import json
import sys
import unicodedata
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ocr_backends import make_backend  # noqa: E402
from ocr_common import group_rows, semi_global_align  # noqa: E402

F = "C:/Windows/Fonts/"
FONTS = {"zh-TW": "msjh.ttc", "zh-CN": "msyh.ttc", "en": "segoeui.ttf", "ja": "YuGothM.ttc", "ko": "malgun.ttf"}
MESSAGES = {  # (language, text, class)
    "zh-TW": [("兌換成功", "success"), ("序號已被使用", "used"), ("兌換碼無效", "invalid"), ("兌換碼已過期", "expired"),
              ("操作過於頻繁，請稍後再試", "rate_limited"), ("獎勵已發送至信箱", "success")],
    "zh-CN": [("兑换成功", "success"), ("兑换码已被使用", "used"), ("兑换码无效", "invalid"), ("兑换码已过期", "expired"),
              ("操作过于频繁，请稍后再试", "rate_limited")],
    "en": [("Redeemed successfully", "success"), ("This code has already been used", "used"),
           ("Invalid code", "invalid"), ("Code expired", "expired"),
           ("Too many requests. Please try again later.", "rate_limited")],
    "ja": [("交換に成功しました", "success"), ("このコードは既に使用されています", "used"), ("無効なコードです", "invalid"),
           ("有効期限切れです", "expired"), ("しばらくしてから再度お試しください", "rate_limited")],
    "ko": [("교환 성공", "success"), ("이미 사용된 쿠폰입니다", "used"), ("유효하지 않은 코드입니다", "invalid"),
           ("기간이 만료되었습니다", "expired"), ("잠시 후 다시 시도해 주세요", "rate_limited")],
}
# Keyword table for result classification (checked in this order; first match wins)
KEYWORDS = [
    ("rate_limited", ["頻繁", "频繁", "稍後再試", "稍后再试", "toomany", "tryagainlater", "しばらく", "잠시후"]),
    ("used", ["已被使用", "已使用", "已兌換", "已兑换", "alreadybeenused", "alreadyused", "alreadyredeemed",
              "既に使用", "이미사용"]),
    ("expired", ["過期", "过期", "expired", "期限切れ", "만료"]),
    ("invalid", ["無效", "无效", "invalid", "無効", "유효하지않은", "错误", "錯誤"]),
    ("success", ["成功", "已發送", "已发送", "success", "redeemed", "成功しました", "성공"]),
]


def squash(s):
    return "".join(c for c in unicodedata.normalize("NFKC", s).casefold()
                   if not (c.isspace() or unicodedata.category(c).startswith("P")))


def levenshtein(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j - 1] + (ca != cb), prev[j] + 1, cur[j - 1] + 1))
        prev = cur
    return prev[-1]


def fuzzy_in(kw, text):
    """kw occurs in text with <= 1 edit when len(kw) >= 4 (exact otherwise)."""
    if kw in text:
        return True
    if len(kw) < 4 or not text:
        return False
    return semi_global_align(kw, text)[0] <= 1


def classify(text):
    t = squash(text)
    for cls, kws in KEYWORDS:
        if any(fuzzy_in(squash(k), t) for k in kws):
            return cls
    return "unknown"


def render(lang, text, size, dark):
    f = ImageFont.truetype(F + FONTS[lang], size)
    tw = int(f.getlength(text))
    W, H = max(360, tw + 120), max(160, size * 5)
    img = Image.new("RGB", (W, H), (30, 30, 36) if dark else (236, 236, 240))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([20, 20, W - 20, H - 20], radius=12, fill=(48, 48, 60) if dark else (255, 255, 255),
                        outline=(200, 170, 90) if dark else (180, 180, 190), width=2)
    d.text((W // 2, H // 2), text, font=f, fill=(245, 245, 245) if dark else (30, 30, 30), anchor="mm")
    return np.asarray(img)[:, :, ::-1].copy()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--engines", required=True)
    ap.add_argument("--models", default="")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    print("| engine | " + " | ".join("%s exact / CER / class" % lg for lg in MESSAGES) + " |")
    print("|---|" + "---|" * len(MESSAGES))
    for eng in a.engines.split(","):
        be = make_backend(eng, [d for d in a.models.split(";") if d] or None)
        recs = []
        for lang, msgs in MESSAGES.items():
            for text, cls in msgs:
                for size in (14, 18, 24):
                    for dark in (True, False):
                        items = be.run(render(lang, text, size, dark))
                        got = "".join(r["text"] for r in group_rows(items))
                        gt, pr = squash(text), squash(got)
                        cer = min(1.0, levenshtein(gt, pr) / len(gt))
                        recs.append({"lang": lang, "text": text, "size": size, "dark": dark, "ocr": got,
                                     "exact": gt == pr, "cer": cer, "cls": cls, "pred": classify(got)})
        cells = []
        for lang in MESSAGES:
            rr = [r for r in recs if r["lang"] == lang]
            cells.append("%.0f / %.0f / %.0f" % (100 * sum(r["exact"] for r in rr) / len(rr),
                                                 100 * sum(r["cer"] for r in rr) / len(rr),
                                                 100 * sum(r["cls"] == r["pred"] for r in rr) / len(rr)))
        print("| %s | %s |" % (eng, " | ".join(cells)))
        (out / ("u3_%s.json" % eng)).write_text(json.dumps(recs, ensure_ascii=False, indent=0), encoding="utf-8")


if __name__ == "__main__":
    main()
