# OWNED BY G8
"""tools/screenshots.py: numbered callouts, captions and the Markdown snippet for the user guide
(SPEC 10.4). The slow test runs the real pipeline on a tools/snap_widget.py capture (windows
platform, never shown on screen)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from tools import screenshots as shots

ORANGE = np.array(shots.ORANGE)


def _canvas(w: int = 400, h: int = 240, color: tuple[int, int, int] = (20, 24, 32)) -> Image.Image:
    return Image.new("RGB", (w, h), color)


def _is_orange(px: np.ndarray) -> bool:
    return bool(np.abs(px.astype(int) - ORANGE).max() <= 12)


def test_parse_callout_point_and_region() -> None:
    c = shots.parse_callout("3:120,40")
    assert (c.n, c.at, c.rect) == (3, (120, 40), None)
    r = shots.parse_callout("2:10,20,200,30", text="設定檔")
    assert (r.n, r.at, r.rect, r.text) == (2, None, (10, 20, 200, 30), "設定檔")
    for bad in ("x:1,2", "1:1", "1:1,2,3", "1:1,2,0,5", "1"):
        with pytest.raises(shots.ManifestError):
            shots.parse_callout(bad)


def test_annotate_draws_orange_badges_and_region_outlines() -> None:
    img = _canvas()
    out = shots.annotate(img, [shots.parse_callout("1:60,60"), shots.parse_callout("2:150,120,200,80")])
    assert out.size == img.size and out.mode == "RGB"
    a = np.asarray(out)
    assert _is_orange(a[60, 60 - 8])  # inside the disc, left of the digit
    assert tuple(a[60, 60 - 12]) >= (230, 230, 230)  # the white ring
    assert _is_orange(a[160, 150 + 1])  # left edge of the region outline
    assert tuple(a[160, 250]) == (20, 24, 32)  # inside the region: untouched
    assert np.asarray(img).max() == 32  # the source image is not modified


def test_badges_stay_inside_the_image_at_the_corners() -> None:
    img = _canvas(200, 100, (250, 250, 250))
    out = np.asarray(shots.annotate(img, [shots.parse_callout("1:199,99"), shots.parse_callout("2:0,0")]))
    assert _is_orange(out[99 - 13, 199 - 13 - 6]) or _is_orange(out[99 - 13, 199 - 13])
    assert _is_orange(out[13, 13 - 6]) or _is_orange(out[13, 13])


def test_scale_makes_bigger_badges() -> None:
    small = np.asarray(shots.annotate(_canvas(), [shots.parse_callout("1:100,100")], scale=1.0))
    big = np.asarray(shots.annotate(_canvas(), [shots.parse_callout("1:100,100")], scale=1.5))
    count = [int(sum(_is_orange(px) for px in arr[100])) for arr in (small, big)]
    assert count[1] > count[0] * 1.3


def test_check_callouts_reports_numbering_bounds_captions() -> None:
    cs = [shots.Callout(1, at=(10, 10), text="a"), shots.Callout(3, at=(500, 10), text=""),
          shots.Callout(4, rect=(350, 200, 100, 100), text="d")]
    problems = shots.check_callouts(cs, (400, 240), require_text=True)
    assert any("1..3" in p for p in problems)
    assert any("callout 3: point" in p for p in problems)
    assert any("callout 4: region" in p for p in problems)
    assert any("callout 3: no caption" in p for p in problems)
    ok = [shots.Callout(1, at=(10, 10), text="a"), shots.Callout(2, rect=(20, 20, 50, 50), text="b")]
    assert shots.check_callouts(ok, (400, 240), require_text=True) == []


def test_overlapping_badges_are_reported() -> None:
    cs = [shots.Callout(1, at=(100, 100)), shots.Callout(2, at=(110, 104)), shots.Callout(3, at=(300, 100))]
    assert shots.overlapping(cs) == [(1, 2)]


def test_markdown_is_plain_and_has_one_caption_per_number() -> None:
    shot = shots.Shot(name="codes_page", source=Path("x.png"), title="序號頁", alt="序號頁（示範資料）",
                      callouts=[shots.Callout(2, at=(1, 1), text="設定檔"), shots.Callout(1, at=(2, 2), text="左側選單")])
    md = shots.markdown_for(shot, "images/codes_page.png")
    assert md == "### 序號頁\n\n![序號頁（示範資料）](images/codes_page.png)\n\n1. 左側選單\n2. 設定檔\n"
    assert "<" not in md


def test_build_writes_annotated_images_and_the_snippet(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    _canvas().save(raw / "page.png")
    _canvas(300, 200).save(raw / "dialog.png")
    manifest = tmp_path / "shots.json"
    manifest.write_text(json.dumps({"images": [
        {"name": "page", "source": "raw/page.png", "title": "頁面", "callouts": [
            {"n": 1, "at": [40, 40], "text": "第一區"}, {"n": 2, "rect": [100, 100, 120, 60], "text": "第二區"}]},
        {"name": "dialog", "source": "raw/dialog.png", "title": "對話框", "callouts": [
            {"n": 1, "at": [30, 30], "text": "按鈕"}]},
    ]}, ensure_ascii=False), encoding="utf-8")
    out_dir = tmp_path / "images"
    md = tmp_path / "snippet.md"
    assert shots.main(["build", str(manifest), "--out-dir", str(out_dir), "--markdown", str(md)]) == 0
    assert Image.open(out_dir / "page.png").size == (400, 240)
    assert Image.open(out_dir / "dialog.png").size == (300, 200)
    text = md.read_text(encoding="utf-8")
    assert "![頁面](images/page.png)" in text and "1. 第一區\n2. 第二區" in text and "1. 按鈕" in text


def test_build_refuses_images_with_missing_captions(tmp_path: Path) -> None:
    _canvas().save(tmp_path / "page.png")
    manifest = tmp_path / "shots.json"
    manifest.write_text(json.dumps({"images": [{"name": "page", "source": "page.png", "callouts": [
        {"n": 1, "at": [40, 40], "text": ""}]}]}), encoding="utf-8")
    out_dir = tmp_path / "images"
    assert shots.main(["build", str(manifest), "--out-dir", str(out_dir)]) == 1
    assert not (out_dir / "page.png").exists()


def test_build_reports_a_missing_source_and_continues(tmp_path: Path) -> None:
    _canvas().save(tmp_path / "ok.png")
    manifest = tmp_path / "shots.json"
    manifest.write_text(json.dumps({"images": [
        {"name": "missing", "source": "nope.png", "capture": None, "callouts": [{"n": 1, "at": [5, 5], "text": "a"}]},
        {"name": "ok", "source": "ok.png", "callouts": [{"n": 1, "at": [5, 5], "text": "b"}]},
    ]}), encoding="utf-8")
    assert shots.main(["build", str(manifest), "--out-dir", str(tmp_path / "images")]) == 1
    assert (tmp_path / "images" / "ok.png").is_file() and not (tmp_path / "images" / "missing.png").exists()


def test_annotate_command_rejects_out_of_range_callouts(tmp_path: Path) -> None:
    _canvas().save(tmp_path / "a.png")
    assert shots.main(["annotate", str(tmp_path / "a.png"), str(tmp_path / "b.png"), "--callout", "1:900,10"]) == 2
    assert not (tmp_path / "b.png").exists()
    assert shots.main(["annotate", str(tmp_path / "a.png"), str(tmp_path / "b.png"), "--callout", "1:90,10"]) == 0
    assert (tmp_path / "b.png").is_file()


@pytest.mark.slow
def test_pipeline_on_a_snap_widget_capture(tmp_path: Path) -> None:
    """capture (tools/snap_widget.py, real windows platform) -> callouts -> Markdown."""
    manifest = tmp_path / "shots.json"
    manifest.write_text(json.dumps({"images": [{
        "name": "calendar", "source": "raw/calendar.png", "title": "測試畫面", "alt": "snap_widget 截圖",
        "capture": {"target": "PyQt6.QtWidgets:QCalendarWidget", "theme": "light", "size": "640x400"},
        "callouts": [{"n": 1, "at": [40, 20], "text": "月份"}, {"n": 2, "rect": [10, 60, 620, 330], "text": "日期"}],
    }]}, ensure_ascii=False), encoding="utf-8")
    md = tmp_path / "guide.md"
    assert shots.main(["build", str(manifest), "--out-dir", str(tmp_path / "images"), "--markdown", str(md),
                       "--capture"]) == 0
    raw = Image.open(tmp_path / "raw" / "calendar.png")
    out = Image.open(tmp_path / "images" / "calendar.png").convert("RGB")
    assert raw.size == out.size == (640, 400)
    arr = np.asarray(out)
    assert np.asarray(raw.convert("RGB")).std() > 5, "snap_widget produced a blank image"
    assert _is_orange(arr[20, 40 - 8])
    assert "![snap_widget 截圖](images/calendar.png)" in md.read_text(encoding="utf-8")
