"""Engine-independent helpers for the AutoPress OCR research scripts.

Only numpy + Pillow are required here (works in both scratch venvs).
- load_image_bgr(): Chinese-path-safe loader (PIL opens the file itself, no cv2 path API).
- preprocess(): the benchmark preprocessing variants.
- group_rows(): merge engine boxes into reading-order rows.
- CodeSpec / extract_codes(): rule-based code extraction + confusable repair.
- ctc_constrained_decode(): greedy CTC decode restricted to the code charset.
- semi_global_align(): align a ground-truth code inside an OCR row (for confusion counts).
"""
import itertools
import re
import string
import unicodedata

import numpy as np
from PIL import Image, ImageOps

# ---------------------------------------------------------------- image I/O

def load_image_bgr(path):
    """Read any Pillow-supported image (PNG/JPG/BMP/GIF/WebP) from a path that may contain
    non-ASCII characters. Returns an HxWx3 uint8 BGR contiguous array."""
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        rgb = np.asarray(im.convert("RGB"))
    return np.ascontiguousarray(rgb[:, :, ::-1])


def bgra_to_bgr(arr):
    """mss.grab() / QImage.Format_ARGB32 buffers are BGRA in memory."""
    return np.ascontiguousarray(np.asarray(arr)[:, :, :3])


# ---------------------------------------------------------------- preprocessing

PREPROCS = ["none", "up2", "up3", "gray_ac", "invert"]


def is_dark(img_bgr):
    lum = img_bgr[:, :, 2] * 0.299 + img_bgr[:, :, 1] * 0.587 + img_bgr[:, :, 0] * 0.114
    return float(lum.mean()) < 110.0


def preprocess(img_bgr, variant):
    if variant == "none":
        return img_bgr
    pil = Image.fromarray(img_bgr[:, :, ::-1])
    if variant in ("up2", "up3"):
        k = 2 if variant == "up2" else 3
        pil = pil.resize((pil.width * k, pil.height * k), Image.Resampling.BICUBIC)
    elif variant == "gray_ac":
        pil = ImageOps.autocontrast(pil.convert("L"), cutoff=1).convert("RGB")
    elif variant == "invert":
        if not is_dark(img_bgr):
            return img_bgr
        pil = ImageOps.invert(pil)
    else:
        raise ValueError(variant)
    return np.ascontiguousarray(np.asarray(pil)[:, :, ::-1])


# ---------------------------------------------------------------- rows

def quad_bounds(quad):
    q = np.asarray(quad, dtype=float).reshape(4, 2)
    return q[:, 0].min(), q[:, 1].min(), q[:, 0].max(), q[:, 1].max()


def group_rows(items):
    """items: list of (text, quad, score[, char_confs]). Returns list of rows, each row a dict
    {text, confs, items} with boxes sorted left-to-right; rows sorted top-to-bottom.
    Two boxes share a row when their vertical overlap >= 50% of the smaller height."""
    boxes = []
    for it in items:
        text, quad, score = it[0], it[1], it[2]
        confs = it[3] if len(it) > 3 and it[3] is not None else [score] * len(text)
        x0, y0, x1, y1 = quad_bounds(quad)
        boxes.append((y0, y1, x0, text, list(confs), it))
    boxes.sort(key=lambda b: (b[0] + b[1]) / 2)
    rows = []
    for b in boxes:
        for r in rows:
            ov = min(r["y1"], b[1]) - max(r["y0"], b[0])
            if ov >= 0.5 * min(r["y1"] - r["y0"], b[1] - b[0]):
                r["b"].append(b)
                r["y0"], r["y1"] = min(r["y0"], b[0]), max(r["y1"], b[1])
                break
        else:
            rows.append({"y0": b[0], "y1": b[1], "b": [b]})
    out = []
    for r in rows:
        r["b"].sort(key=lambda b: b[2])
        out.append({"text": "".join(b[3] for b in r["b"]),
                    "confs": [c for b in r["b"] for c in b[4]],
                    "items": [b[5] for b in r["b"]]})
    return out


# ---------------------------------------------------------------- code extraction

UPPER = string.ascii_uppercase + string.digits
MIXED = string.ascii_letters + string.digits
# visually confusable groups; a character outside the allowed charset is replaced by the
# first member of its group that IS allowed (only then - valid characters are never touched)
CONFUSABLE = {
    "O": "0O", "0": "O0", "o": "O0", "Q": "O0", "D": "0O", "口": "O0",
    "I": "1I", "1": "I1", "l": "I1", "i": "I1", "|": "I1", "!": "I1", "丨": "I1", "工": "I1",
    "S": "5S", "5": "S5", "s": "S5", "$": "S5", "§": "S5",
    "B": "8B", "8": "B8", "Z": "2Z", "2": "Z2", "z": "Z2",
    "G": "6G", "6": "G6", "g": "9G", "q": "9Q", "U": "VU", "V": "UV", "u": "UV", "v": "VU",
}
DASHES = "‐‑‒–—―−－ー一_~"
RELAXED = re.compile(r"[A-Za-z0-9\-|!$§口丨工 ]+")


class CodeSpec:
    """allowed: allowed code characters. groups: e.g. [4, 4, 4] for XXXX-XXXX-XXXX, or None.
    Without groups a code is allowed+ with min_len..max_len characters and no dashes."""

    def __init__(self, allowed=UPPER, groups=None, min_len=6, max_len=24):
        self.allowed = set(allowed)
        self.groups = list(groups) if groups else None
        self.min_len, self.max_len = min_len, max_len

    def repair_char(self, ch):
        if ch in self.allowed:
            return ch
        for cand in CONFUSABLE.get(ch, ""):
            if cand in self.allowed:
                return cand
        for cand in (ch.upper(), ch.lower()):  # plain case error (c/C, w/W, ...)
            if cand in self.allowed:
                return cand
        return None

    def normalize(self, s):
        alnum = s.replace("-", "")
        fixed = []
        for ch in alnum:
            r = self.repair_char(ch)
            if r is None:
                return None
            fixed.append(r)
        alnum = "".join(fixed)
        if self.groups:
            if len(alnum) != sum(self.groups):
                return None
            out, i = [], 0
            for g in self.groups:
                out.append(alnum[i:i + g])
                i += g
            return "-".join(out)
        if "-" in s.strip("-") or not (self.min_len <= len(alnum) <= self.max_len):
            return None
        return alnum


def normalize_text(t):
    t = unicodedata.normalize("NFKC", t)
    return "".join("-" if c in DASHES else c for c in t)


def extract_codes(row_texts, spec):
    """Return de-duplicated candidate codes (in reading order) from OCR row texts."""
    out = []
    for row in row_texts:
        for m in RELAXED.finditer(normalize_text(row)):
            toks = [t for t in m.group(0).split(" ") if t]
            for i, j in itertools.combinations(range(len(toks) + 1), 2):
                cand = spec.normalize("".join(toks[i:j]).strip("-"))
                if cand and cand not in out:
                    out.append(cand)
    return out


# ---------------------------------------------------------------- constrained CTC decoding

LATINISH = set(string.ascii_letters + string.digits + "-|!$§")


def ctc_constrained_decode(probs, character, allowed, latinish=LATINISH):
    """probs: (T, C) softmax output of a CTC recognizer for ONE text line; character: index->str
    list (index 0 = CTC blank). Frames whose best symbol is Latin-like are re-decided among the
    allowed characters (blank excluded, so no character is deleted); other frames (CJK, blank)
    keep their argmax. Returns (text, per-char confidence list)."""
    top = probs.argmax(axis=1)
    allow_idx = np.array([i for i, ch in enumerate(character) if i and (ch in allowed or ch == "-")])
    chosen = top.copy()
    for t, k in enumerate(top):
        if k and character[k] in latinish:
            chosen[t] = allow_idx[int(np.argmax(probs[t, allow_idx]))]
    text, confs, prev = [], [], -1
    for t, k in enumerate(chosen):
        if k != prev and k != 0:
            text.append(character[k])
            confs.append(float(probs[t, k]))
        prev = k
    return "".join(text), confs


# ---------------------------------------------------------------- evaluation helpers

def semi_global_align(gt, text):
    """Best alignment of gt inside text (free leading/trailing text). Returns (dist, ops) where
    ops is a list of (gt_char|None, text_char|None, text_index|None)."""
    n, m = len(gt), len(text)
    D = np.zeros((n + 1, m + 1), dtype=np.int32)
    D[:, 0] = np.arange(n + 1)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            D[i, j] = min(D[i - 1, j - 1] + (gt[i - 1] != text[j - 1]), D[i - 1, j] + 1, D[i, j - 1] + 1)
    j = int(np.argmin(D[n])) if m else 0
    dist, i, ops = int(D[n, j]), n, []
    while i > 0:
        if j > 0 and D[i, j] == D[i - 1, j - 1] + (gt[i - 1] != text[j - 1]):
            ops.append((gt[i - 1], text[j - 1], j - 1))
            i, j = i - 1, j - 1
        elif D[i, j] == D[i - 1, j] + 1:
            ops.append((gt[i - 1], None, None))
            i -= 1
        else:
            ops.append((None, text[j - 1], j - 1))
            j -= 1
    return dist, ops[::-1]
