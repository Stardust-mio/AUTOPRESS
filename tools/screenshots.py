# OWNED BY G8
"""Numbered callouts and captions for the user guide (SPEC 10.4, requirement R7).

    # one image: callout "n:x,y" (badge centre) or "n:x,y,w,h" (outlined region, badge at its corner)
    .venv/Scripts/python.exe tools/screenshots.py annotate shot.png docs/images/codes.png \
        --callout 1:60,80 --callout 2:740,30,280,36 [--scale 1.0]

    # a whole manifest: capture (optional), annotate, write docs/images/*.png + a Markdown snippet
    .venv/Scripts/python.exe tools/screenshots.py build shots.json --out-dir docs/images \
        --markdown C:/.../guide_snippet.md [--capture]

Manifest (UTF-8 JSON; relative paths are relative to the manifest file)::

    {"images": [{
        "name": "codes_page",                          # -> <out-dir>/codes_page.png
        "source": "raw/codes_page.png",                # the real screenshot (PNG)
        "capture": {"target": "autopress.ui.codes_page:CodesPage", "theme": "dark",
                    "scale": 1.0, "size": "1280x800", "lang": "zh-TW", "empty": false},
        "title": "序號頁", "alt": "序號頁（深色模式，示範資料）",
        "callouts": [{"n": 1, "at": [60, 80], "text": "左側選單：..."},
                     {"n": 2, "rect": [740, 30, 280, 36], "text": "設定檔：..."}]}]}

``capture`` (used with ``--capture``, or when the source file is missing) renders the source
with tools/snap_widget.py - the real widget with demo data (tests/fakes.py), windows platform,
never shown on screen. Screens that need a running app (dialogs, wizard steps, the mini bar)
are captured separately and referenced by ``source``: use the PNGs of tools/guide_capture.py
(every README / guide screen in one demo state, demo desktop, privacy check; its ``--geometry``
JSON gives widget rects for the callouts). Coordinates are pixels of the source PNG
(a 150 % capture has 1.5x the pixels: give ``scale`` 1.5 so badges grow with it).

The callouts copy the design preview's look (docs/design-preview/codes_annotated.png): an
orange disc with a white ring and a white bold number; regions get an orange outline. The
Markdown snippet is plain Markdown that GitHub renders (no HTML): a heading, the image with a
relative path and one caption per number below it, in number order.
Writes only the files named on the command line (atomically).
"""

from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ORANGE = (249, 115, 22)  # callout colour of the design preview
RING = (255, 255, 255)
SHADOW = (0, 0, 0, 110)
BADGE_D = 26  # badge diameter at scale 1.0 (px)
OUTLINE_W = 3  # region outline width at scale 1.0
SUPERSAMPLE = 4
FONT_FILES = ("segoeuib.ttf", "arialbd.ttf", "msjhbd.ttc", "msjh.ttc")


@dataclass
class Callout:
    n: int
    at: tuple[int, int] | None = None  # badge centre
    rect: tuple[int, int, int, int] | None = None  # outlined region (x, y, w, h)
    text: str = ""

    def badge_centre(self, d: float) -> tuple[float, float]:
        if self.at is not None:
            return float(self.at[0]), float(self.at[1])
        assert self.rect is not None
        x, y, _w, _h = self.rect
        return x + d * 0.15, y + d * 0.15  # on the region's top-left corner, slightly inside


@dataclass
class Shot:
    name: str
    source: Path
    callouts: list[Callout] = field(default_factory=list)
    title: str = ""
    alt: str = ""
    scale: float = 1.0
    capture: dict[str, Any] | None = None


class ManifestError(ValueError):
    pass


# =============================================================================== parsing


def parse_callout(spec: str, text: str = "") -> Callout:
    """``"3:120,40"`` (badge centre) or ``"3:120,40,200,30"`` (region) -> Callout."""
    try:
        num, _, coords = spec.partition(":")
        values = [int(round(float(v))) for v in coords.split(",")]
        n = int(num)
    except ValueError as exc:
        raise ManifestError(f"bad callout {spec!r}: use n:x,y or n:x,y,w,h") from exc
    if len(values) == 2:
        return Callout(n, at=(values[0], values[1]), text=text)
    if len(values) == 4 and values[2] > 0 and values[3] > 0:
        return Callout(n, rect=(values[0], values[1], values[2], values[3]), text=text)
    raise ManifestError(f"bad callout {spec!r}: use n:x,y or n:x,y,w,h")


def _callout_from_json(item: dict[str, Any]) -> Callout:
    if not isinstance(item, dict) or "n" not in item:
        raise ManifestError(f"callout without a number: {item!r}")
    if "at" in item:
        x, y = item["at"]
        return Callout(int(item["n"]), at=(int(x), int(y)), text=str(item.get("text", "")))
    if "rect" in item:
        x, y, w, h = item["rect"]
        return Callout(int(item["n"]), rect=(int(x), int(y), int(w), int(h)), text=str(item.get("text", "")))
    raise ManifestError(f"callout {item.get('n')} needs 'at' [x, y] or 'rect' [x, y, w, h]")


def load_manifest(path: Path) -> list[Shot]:
    data = json.loads(Path(path).read_bytes().decode("utf-8-sig"))
    base = Path(path).resolve().parent
    shots = []
    for entry in data.get("images", []):
        src = Path(entry["source"])
        shots.append(Shot(
            name=str(entry["name"]), source=src if src.is_absolute() else base / src,
            callouts=[_callout_from_json(c) for c in entry.get("callouts", [])],
            title=str(entry.get("title", "")), alt=str(entry.get("alt", entry.get("title", ""))),
            scale=float(entry.get("scale") or (entry.get("capture") or {}).get("scale") or 1.0),
            capture=entry.get("capture")))
    names = [s.name for s in shots]
    if len(set(names)) != len(names):
        raise ManifestError("image names must be unique")
    return shots


def check_callouts(callouts: list[Callout], size: tuple[int, int], require_text: bool = False) -> list[str]:
    """Problems: numbers not 1..n, points or regions outside the image, empty captions,
    badges that overlap each other."""
    problems = []
    nums = sorted(c.n for c in callouts)
    if nums != list(range(1, len(callouts) + 1)):
        problems.append(f"callout numbers must be 1..{len(callouts)}, got {nums}")
    w, h = size
    for c in callouts:
        if c.at is not None and not (0 <= c.at[0] < w and 0 <= c.at[1] < h):
            problems.append(f"callout {c.n}: point {c.at} is outside the {w}x{h} image")
        if c.rect is not None:
            x, y, rw, rh = c.rect
            if x < 0 or y < 0 or x + rw > w or y + rh > h:
                problems.append(f"callout {c.n}: region {c.rect} is outside the {w}x{h} image")
        if require_text and not c.text.strip():
            problems.append(f"callout {c.n}: no caption")
    return problems


def overlapping(callouts: list[Callout], scale: float = 1.0) -> list[tuple[int, int]]:
    d = BADGE_D * scale
    centres = [(c.n, c.badge_centre(d)) for c in callouts]
    out = []
    for i, (na, (xa, ya)) in enumerate(centres):
        for nb, (xb, yb) in centres[i + 1:]:
            if (xa - xb) ** 2 + (ya - yb) ** 2 < (d * 1.05) ** 2:
                out.append((na, nb))
    return out


# =============================================================================== drawing


def _font(px: int) -> Any:
    from PIL import ImageFont

    font_dir = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for name in FONT_FILES:
        f = font_dir / name
        if f.is_file():
            return ImageFont.truetype(str(f), px)
    return ImageFont.load_default(px)


def _badge(n: int, d: float) -> Any:
    """RGBA image of one numbered disc (anti-aliased by drawing at SUPERSAMPLE x)."""
    from PIL import Image, ImageDraw

    k = SUPERSAMPLE
    pad = max(2, int(round(d * 0.12)))  # room for the shadow
    size = int(round(d)) + 2 * pad
    big = Image.new("RGBA", (size * k, size * k), (0, 0, 0, 0))
    draw = ImageDraw.Draw(big)
    o = pad * k
    dd = int(round(d * k))
    shadow_off = max(1, int(round(d * 0.06 * k)))
    draw.ellipse((o, o + shadow_off, o + dd, o + dd + shadow_off), fill=SHADOW)
    draw.ellipse((o, o, o + dd, o + dd), fill=RING)
    ring = max(2, int(round(d * 0.09 * k)))
    draw.ellipse((o + ring, o + ring, o + dd - ring, o + dd - ring), fill=ORANGE)
    label = str(n)
    font = _font(int(round(d * (0.56 if len(label) < 2 else 0.48) * k)))
    draw.text((o + dd / 2, o + dd / 2), label, font=font, fill=(255, 255, 255), anchor="mm")
    return big.resize((size, size), Image.Resampling.LANCZOS), pad


def annotate(image: Any, callouts: list[Callout], scale: float = 1.0) -> Any:
    """Return a copy of the PIL image with region outlines first, then the numbered badges."""
    from PIL import Image, ImageDraw

    base = image.convert("RGBA")
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    lw = max(2, int(round(OUTLINE_W * scale)))
    radius = int(round(6 * scale))
    for c in callouts:
        if c.rect is not None:
            x, y, w, h = c.rect
            draw.rounded_rectangle((x, y, x + w - 1, y + h - 1), radius=radius, outline=ORANGE + (255,), width=lw)
    out = Image.alpha_composite(base, layer)
    d = BADGE_D * scale
    for c in sorted(callouts, key=lambda c: c.n):
        badge, pad = _badge(c.n, d)
        cx, cy = c.badge_centre(d)
        left = int(round(cx - d / 2)) - pad
        top = int(round(cy - d / 2)) - pad
        left = min(max(left, -pad), out.width - badge.width + pad)  # keep the disc inside the image
        top = min(max(top, -pad), out.height - badge.height + pad)
        out.alpha_composite(badge, (max(left, 0), max(top, 0)),
                            (max(-left, 0), max(-top, 0)))
    return out.convert("RGB")


def png_bytes(image: Any) -> bytes:
    buf = io.BytesIO()
    image.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def write_png(image: Any, path: Path) -> None:
    from autopress.storage import write_bytes_atomic

    write_bytes_atomic(Path(path), png_bytes(image))


# =============================================================================== markdown


def markdown_for(shot: Shot, image_href: str) -> str:
    """Heading, image (relative path) and one caption per callout number - plain Markdown."""
    lines = []
    if shot.title:
        lines += [f"### {shot.title}", ""]
    lines += [f"![{shot.alt or shot.title or shot.name}]({image_href})", ""]
    for c in sorted(shot.callouts, key=lambda c: c.n):
        lines.append(f"{c.n}. {c.text.strip()}")
    return "\n".join(lines).rstrip() + "\n"


# =============================================================================== capture


def capture(shot: Shot, out_png: Path, python: str = sys.executable) -> Path:
    """Render ``shot.capture`` with tools/snap_widget.py (windows platform, never shown)."""
    cfg = dict(shot.capture or {})
    if not cfg.get("target"):
        raise ManifestError(f"{shot.name}: nothing to capture (no capture.target)")
    cmd = [python, str(ROOT / "tools" / "snap_widget.py"), str(cfg["target"]), "--out", str(out_png),
           "--theme", str(cfg.get("theme", "dark")), "--size", str(cfg.get("size", "1280x800")),
           "--lang", str(cfg.get("lang", "zh-TW"))]
    if cfg.get("scale"):
        cmd += ["--scale", str(cfg["scale"])]
    if cfg.get("empty"):
        cmd.append("--empty")
    env = dict(os.environ)
    env.pop("QT_QPA_PLATFORM", None)
    env["PYTHONIOENCODING"] = "utf-8"
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                         env=env, timeout=180)
    if res.returncode != 0 or not out_png.is_file():
        raise RuntimeError(f"snap_widget failed for {shot.name}: {res.stdout}{res.stderr}")
    return out_png


# =============================================================================== CLI


def _annotate_cmd(a: argparse.Namespace) -> int:
    from PIL import Image

    callouts = [parse_callout(s) for s in a.callout]
    with Image.open(a.source) as im:
        img = im.copy()
    problems = check_callouts(callouts, img.size)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 2
    write_png(annotate(img, callouts, a.scale), Path(a.out))
    for na, nb in overlapping(callouts, a.scale):
        print(f"warning: callouts {na} and {nb} overlap")
    print(a.out)
    return 0


def _build_cmd(a: argparse.Namespace) -> int:
    from PIL import Image

    shots = load_manifest(Path(a.manifest))
    out_dir = Path(a.out_dir)
    snippets, failed = [], False
    for shot in shots:
        if shot.capture and (a.capture or not shot.source.is_file()):
            shot.source.parent.mkdir(parents=True, exist_ok=True)
            capture(shot, shot.source)
        if not shot.source.is_file():
            failed = True
            print(f"{shot.name}: source {shot.source} not found (and no capture entry)", file=sys.stderr)
            continue
        with Image.open(shot.source) as im:
            img = im.copy()
        problems = check_callouts(shot.callouts, img.size, require_text=True)
        if problems:
            failed = True
            print(f"{shot.name}:\n  " + "\n  ".join(problems), file=sys.stderr)
            continue
        target = out_dir / f"{shot.name}.png"
        write_png(annotate(img, shot.callouts, shot.scale), target)
        for na, nb in overlapping(shot.callouts, shot.scale):
            print(f"warning: {shot.name}: callouts {na} and {nb} overlap")
        snippets.append(markdown_for(shot, f"{a.href_prefix}{shot.name}.png"))
        print(target)
    if a.markdown:
        from autopress.storage import write_text_atomic

        write_text_atomic(Path(a.markdown), "\n".join(snippets))
        print(a.markdown)
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Numbered callouts and captions for the user guide.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("annotate", help="draw callouts on one PNG")
    p1.add_argument("source")
    p1.add_argument("out")
    p1.add_argument("--callout", action="append", default=[], metavar="N:X,Y[,W,H]")
    p1.add_argument("--scale", type=float, default=1.0)
    p2 = sub.add_parser("build", help="annotate every image of a manifest and write the Markdown")
    p2.add_argument("manifest")
    p2.add_argument("--out-dir", default=str(ROOT / "docs" / "images"))
    p2.add_argument("--markdown", default="", help="write the Markdown snippet here")
    p2.add_argument("--href-prefix", default="images/", help="image path prefix in the Markdown")
    p2.add_argument("--capture", action="store_true", help="re-capture sources that have a 'capture' entry")
    a = ap.parse_args(argv)
    try:
        return _annotate_cmd(a) if a.cmd == "annotate" else _build_cmd(a)
    except ManifestError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
