"""UI polish for the settings, welcome, help and history screens (README screenshot review):
the settings hint gives no rule count, the welcome intro keeps its lead-in on its own line and
the terms rule speaks about terms, Help uses one word for codes and its table of contents marks
the section in view, the evidence viewer frames the crop and shows the attempt time."""

from __future__ import annotations

import gc
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from PyQt6 import sip
from PyQt6.QtCore import QEvent, QRect, QSize, Qt
from PyQt6.QtGui import QColor, QImage, QPixmap
from PyQt6.QtWidgets import QApplication, QLabel, QScrollArea, QWidget

from autopress import i18n
from autopress.i18n import T
from autopress.models import AttemptRecord, CodeStatus
from autopress.ui import theme
from autopress.ui import welcome as welcome_mod
from autopress.ui.help_content import SECTIONS
from autopress.ui.help_page import HelpPage
from autopress.ui.history_page import EvidenceDialog, format_time
from autopress.ui.settings_page import SettingsPage
from autopress.ui.welcome import WelcomeDialog

SECTION_IDS = [str(sec["id"]) for sec in SECTIONS]


@pytest.fixture(autouse=True)
def _free_widgets(qapp: QApplication) -> Iterator[None]:
    yield
    gc.collect()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


def _texts(w: Any) -> list[str]:
    return [lb.text() for lb in w.findChildren(QLabel)]


# ------------------------------------------------------------------ settings: welcome reset hint


@pytest.mark.parametrize("lang", ["zh-TW", "en"])
def test_settings_welcome_hint_gives_no_rule_count(demo_ctx: Any, qtbot: Any, lang: str) -> None:
    """The hint said 'three rules' while the welcome dialog lists four: no count, so it cannot drift."""
    i18n.set_language(lang)
    page = SettingsPage(demo_ctx)
    qtbot.addWidget(page)
    row = page.welcome_button.parentWidget()
    hints = [lb.text() for lb in row.findChildren(QLabel) if lb.property("role") == "muted"]
    assert len(hints) == 1
    hint = hints[0]
    assert ("歡迎畫面" if lang == "zh-TW" else "welcome screen") in hint and page.welcome_hint.text() == hint
    assert not re.search(r"[0-9一二兩三四五六七八九十]\s*條", hint), hint
    assert not re.search(r"\b(?:\d+|one|two|three|four|five|six)\b", hint, re.IGNORECASE), hint
    dlg = WelcomeDialog(demo_ctx)
    qtbot.addWidget(dlg)
    assert len(dlg.findChildren(welcome_mod._RuleIcon)) == 4  # the dialog's rule rows


# ------------------------------------------------------------------ welcome dialog


def test_welcome_intro_keeps_the_lead_in_on_its_own_line(demo_ctx: Any, qtbot: Any) -> None:
    """Wrapped CJK text broke inside 開始之前; the lead-in to the rules now starts its own line."""
    dlg = WelcomeDialog(demo_ctx)
    qtbot.addWidget(dlg)
    intro = next(t for t in _texts(dlg) if "開始之前" in t)
    assert "記下每筆結果。\n開始之前，請先看看這幾條原則：" in intro
    i18n.set_language("en")
    dlg_en = WelcomeDialog(demo_ctx)
    qtbot.addWidget(dlg_en)
    intro_en = next(t for t in _texts(dlg_en) if "Before you start" in t)
    assert "records every result.\nBefore you start, please read these rules:" in intro_en


@pytest.mark.parametrize("lang", ["zh-TW", "en"])
def test_welcome_terms_rule_speaks_about_the_terms(demo_ctx: Any, qtbot: Any, lang: str) -> None:
    """Rule 3 (each game's terms) ended with the pause-on-input feature; pausing is explained in Help
    and Settings, the rule now tells the user to check the game's rules."""
    i18n.set_language(lang)
    dlg = WelcomeDialog(demo_ctx)
    qtbot.addWidget(dlg)
    texts = _texts(dlg)
    if lang == "zh-TW":
        assert "各遊戲條款由你自己負責" in texts
        desc = next(t for t in texts if "巨集" in t)
        assert "暫停" not in desc and "滑鼠" not in desc and "規定" in desc
    else:
        assert "You are responsible for each game's terms" in texts
        desc = next(t for t in texts if "macros" in t)
        assert "pause" not in desc.lower() and "mouse" not in desc.lower() and "rules" in desc


# ------------------------------------------------------------------ help: one word for codes


def _help_pairs(blocks: list[Any]) -> Iterator[T]:
    for block in blocks:
        for part in block[1:]:
            if isinstance(part, T):
                yield part
            elif isinstance(part, list):
                for sub in part:
                    if isinstance(sub, T):
                        yield sub
                    elif isinstance(sub, tuple):
                        yield from _help_pairs([sub])


def test_help_and_welcome_call_codes_xuhao(demo_ctx: Any, qtbot: Any) -> None:
    """The app's word for a code is 序號; Help's first paragraph said 兌換碼 (kept only in the match
    lists for game texts and file headers, which are not UI copy)."""
    pairs = [p for sec in SECTIONS for p in _help_pairs(sec["blocks"])]
    assert len(pairs) > 20  # the walk reaches paragraphs, bullets and troubleshooting items
    assert [p.zh for p in pairs if "兌換碼" in p.zh] == []
    page = HelpPage(demo_ctx)
    qtbot.addWidget(page)
    dlg = WelcomeDialog(demo_ctx)
    qtbot.addWidget(dlg)
    for w in (page, dlg):
        text = "\n".join(_texts(w))
        assert "序號" in text and "兌換碼" not in text


# ------------------------------------------------------------------ help: table of contents


def _destroy(w: QWidget) -> None:
    """Delete a widget through Qt's event loop while its Python wrapper is still alive. Leaving it to
    Python to free a Help page whose scroll bar had been wrapped (by scroll_to or by a test that scrolls)
    has crashed a later paint in the same test process (access violation, heap-layout dependent)."""
    w.hide()
    w.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    assert sip.isdeleted(w)


def _checked(page: HelpPage) -> list[str]:
    return [sid for sid, b in page.toc_buttons.items() if b.isChecked()]


def test_help_toc_marks_the_section_in_view(demo_ctx: Any, qtbot: Any) -> None:
    page = HelpPage(demo_ctx)
    try:
        page.resize(1060, 740)
        page.show()
        bar = page.scroll.verticalScrollBar()
        qtbot.waitUntil(lambda: bar.maximum() > 0)
        assert _checked(page) == ["about"]
        qtbot.mouseClick(page.toc_buttons["safety"], Qt.MouseButton.LeftButton)
        assert bar.value() == page.sections["safety"].y() - theme.SP[3]
        assert _checked(page) == ["safety"]
        page.scroll_to("troubleshooting")
        assert _checked(page) == ["troubleshooting"]
        # a clicked entry stays checked even when the page cannot scroll its section to the top
        qtbot.mouseClick(page.toc_buttons["hotkeys"], Qt.MouseButton.LeftButton)
        assert _checked(page) == ["hotkeys"]
        bar.setValue(0)
        assert _checked(page) == ["about"]
        bar.setValue(bar.maximum())
        assert _checked(page) == ["privacy"]
        # scrolling through the page checks every entry once, in order: exactly one at a time
        seen: list[str] = []
        step = max(1, bar.maximum() // 500)
        for value in [*range(0, bar.maximum(), step), bar.maximum()]:
            bar.setValue(value)
            assert page._scroll_state()[:2] == (bar.value(), bar.maximum())  # the body agrees with the bar
            now = _checked(page)
            assert len(now) == 1, (value, now)
            if not seen or seen[-1] != now[0]:
                seen.append(now[0])
        assert seen == SECTION_IDS
        bar.setValue(0)
    finally:
        _destroy(page)


def test_help_toc_scroll_to_before_show_changes_nothing(demo_ctx: Any) -> None:
    page = HelpPage(demo_ctx)
    try:
        page.scroll_to("privacy")  # no layout yet: the first entry stays checked
        assert _checked(page) == ["about"]
    finally:
        _destroy(page)


# ------------------------------------------------------------------ history: evidence viewer

MAGENTA = QColor(255, 0, 255)


def _bounding_box(img: QImage, color: QColor) -> QRect | None:
    want = color.rgb()
    xs: list[int] = []
    ys: list[int] = []
    for y in range(img.height()):
        for x in range(img.width()):
            if img.pixel(x, y) == want:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return QRect(min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1)


def _ring(box: QRect) -> list[tuple[int, int]]:
    x0, y0, x1, y1 = box.left() - 1, box.top() - 1, box.right() + 1, box.bottom() + 1
    return ([(x, y0) for x in range(x0, x1 + 1)] + [(x, y1) for x in range(x0, x1 + 1)]
            + [(x0, y) for y in range(y0, y1 + 1)] + [(x1, y) for y in range(y0, y1 + 1)])


def test_evidence_dialog_frames_the_crop_and_shows_the_time(qapp: QApplication, qtbot: Any,
                                                            isolated_home: Path) -> None:
    """A light crop vanished on the light dialog: the image now has a 1 px border_strong frame. The
    header shows the attempt time like the table (finished_at, else started_at)."""
    before = theme.current_theme()
    theme.apply_theme(qapp, "light")
    try:
        path = isolated_home / "evidence" / "2026-11-17" / "r1_1.png"
        path.parent.mkdir(parents=True)
        img = QImage(200, 60, QImage.Format.Format_RGB32)
        img.fill(MAGENTA)  # a colour found nowhere else in the dialog
        assert img.save(str(path))
        rec = AttemptRecord(code="AP7K2QX9MZ4T", game="示範遊戲", status=CodeStatus.SUCCESS, message="兌換成功",
                            evidence_path="evidence/2026-11-17/r1_1.png", started_at="2026-11-17T19:30:00+08:00")
        dlg = EvidenceDialog(rec, path)
        try:
            dlg.show()
            qtbot.waitUntil(dlg.isVisible)
            shot = dlg.grab().toImage()
            box = _bounding_box(shot, MAGENTA)
            assert box is not None and box.size() == QSize(200, 60)  # natural size (offscreen: 100 %)
            frame = theme.color("border_strong").rgb()
            assert all(shot.pixel(x, y) == frame for x, y in _ring(box))
            assert format_time(rec.started_at) in _texts(dlg)
            scroll = dlg.findChild(QScrollArea)
            assert scroll is not None
            assert not scroll.horizontalScrollBar().isVisible() and not scroll.verticalScrollBar().isVisible()
        finally:
            _destroy(dlg)
    finally:
        theme.apply_theme(qapp, before)


def test_evidence_dialog_without_any_time_shows_no_empty_label(qtbot: Any, isolated_home: Path) -> None:
    path = isolated_home / "ev.png"
    pm = QPixmap(120, 40)
    pm.fill(MAGENTA)
    assert pm.save(str(path))
    dlg = EvidenceDialog(AttemptRecord(code="AP7K2QX9MZ4T", status=CodeStatus.SUCCESS), path)
    qtbot.addWidget(dlg)
    assert [lb for lb in dlg.findChildren(QLabel) if lb.property("role") == "muted" and not lb.text()] == []


def test_evidence_image_shows_one_image_pixel_per_screen_pixel(qtbot: Any) -> None:
    """The crop holds screen pixels: at 150 % it is drawn at 2/3 of its pixel size in Qt's units,
    i.e. at its natural size and sharp, instead of enlarged and blurred."""
    from autopress.ui.history_page import EvidenceImage

    pm = QPixmap(300, 150)
    pm.fill(MAGENTA)
    img = EvidenceImage(pm)
    qtbot.addWidget(img)
    assert img.sizeHint() == QSize(302, 152) == img.minimumSizeHint()  # 1 px frame on each side
    img.devicePixelRatioF = lambda: 1.5  # type: ignore[method-assign]  # a 150 % screen
    assert img.sizeHint() == QSize(202, 102)
    img.devicePixelRatioF = lambda: 1.25  # type: ignore[method-assign]
    assert img.sizeHint() == QSize(242, 122)
