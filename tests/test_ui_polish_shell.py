"""G5 polish after the screenshot review (UI review U4, U7, U25, U26, U30, U42, U43): the shell
parts - status-bar target text, sidebar badge tooltips, disabled icon colour, scroll-area corner,
framed scroll canvas, current table-of-contents entry and the failsafe-corner sentence."""

from __future__ import annotations

import gc
from typing import Any

import pytest
from PyQt6.QtCore import QEvent, QRect, Qt
from PyQt6.QtGui import QColor, QFontMetrics, QIcon, QImage, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QScrollArea, QStyleOption, QVBoxLayout, QWidget

from autopress import i18n
from autopress.models import CodeCandidate, CodeSource, CodeStatus, WindowInfo
from autopress.ui import main_window as mw_mod
from autopress.ui import icons, shell_statusbar, shell_style, theme, widgets
from autopress.ui.shell_common import failsafe_corner_text

THIS = "tests.test_ui_polish_shell"
LEFT_OF_PRIMARY = [(0, 0, 1920, 1080), (-1920, 0, 1920, 1080)]
ABOVE_PRIMARY = [(0, 0, 1920, 1080), (0, -1080, 1920, 1080)]
LEFT_AND_LOWER = [(0, 0, 2560, 1440), (-1920, 300, 1920, 1080)]  # both top-left corners count


@pytest.fixture(autouse=True)
def _free_widgets(qapp: QApplication):
    yield
    gc.collect()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


@pytest.fixture
def dark_after(qapp: QApplication):
    """Tests that switch themes leave the shared application in the dark theme."""
    yield qapp
    theme.apply_theme(qapp, "dark")


class StandInPage(QWidget):
    """Replaces the other groups' pages: these tests only look at the shell."""

    def __init__(self, ctx: object) -> None:
        super().__init__()
        self.ctx = ctx


@pytest.fixture
def window(demo_ctx: Any, qtbot: Any, monkeypatch: pytest.MonkeyPatch) -> mw_mod.MainWindow:
    pages = dict(mw_mod.PAGE_CLASSES)
    for pid in ("codes", "profiles", "run", "history"):
        pages[pid] = (THIS, "StandInPage")
    monkeypatch.setattr(mw_mod, "PAGE_CLASSES", pages)
    monkeypatch.setattr(mw_mod, "_request_quit", lambda: None)
    w = mw_mod.MainWindow(demo_ctx)
    qtbot.addWidget(w)
    return w


def _card(qtbot: Any, *children: QWidget, vertical: bool = False, size: tuple[int, int] = (0, 0)) -> QFrame:
    """A shown card (known background colour) holding ``children``."""
    host = QFrame()
    host.setProperty("frameRole", "card")
    lay = QVBoxLayout(host) if vertical else QHBoxLayout(host)
    lay.setContentsMargins(20, 20, 20, 20)
    for c in children:
        lay.addWidget(c)
    qtbot.addWidget(host)
    if size != (0, 0):
        host.resize(*size)
    host.show()
    QApplication.processEvents()
    return host


def _opaque_colours(pm: QPixmap) -> set[tuple[int, int, int]]:
    img = pm.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    out: set[tuple[int, int, int]] = set()
    for x in range(img.width()):
        for y in range(img.height()):
            c = img.pixelColor(x, y)
            if c.alpha() >= 200:
                out.add((c.red(), c.green(), c.blue()))
    return out


def _near(rgb: tuple[int, int, int], want: QColor, tol: int = 8) -> bool:
    return all(abs(a - b) <= tol for a, b in zip(rgb, (want.red(), want.green(), want.blue())))


def _brightest(img: QImage, rect: QRect) -> int:
    return max(max(img.pixelColor(x, y).red(), img.pixelColor(x, y).green(), img.pixelColor(x, y).blue())
               for x in range(rect.left(), rect.right() + 1) for y in range(rect.top(), rect.bottom() + 1))


# ------------------------------------------------------------------------------------------ U7


def test_target_found_state_comes_first_and_survives_eliding(window: mw_mod.MainWindow, demo_ctx: Any, qtbot: Any,
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    from autopress.win32 import windows

    title = "示範遊戲 兌換頁 " + "活動公告與兌換說明 " * 10 + "- Google Chrome"
    monkeypatch.setattr(windows, "find_window", lambda match: WindowInfo(hwnd=5, title=title,
                                                                         exe_path="C:/x/chrome.exe"))
    window.resize(1280, 800)
    window.show()
    qtbot.waitExposed(window)
    window._refresh_target()
    item = window.status_bar.items["target"]
    assert window.status_text("target") == f"已找到目標視窗：{title}"
    assert item.toolTip() == title  # the whole title stays one hover away
    lab = item.text_label
    # the label elides on the right, so any width that holds the state keeps it (offscreen has no
    # real fonts, so the width comes from the font metrics, not from this layout)
    fm = QFontMetrics(lab.font())
    width = fm.horizontalAdvance("已找到目標視窗：") + 40
    shown = fm.elidedText(lab.text(), Qt.TextElideMode.ElideRight, width)
    assert shown != lab.text() and shown.startswith("已找到目標視窗：")
    old = fm.elidedText(f"目標視窗：{title}（已找到）", Qt.TextElideMode.ElideRight, width)
    assert "已找到" not in old  # the old order lost exactly the state
    assert lab.maximumWidth() == shell_statusbar.TARGET_MAX_W >= 480  # was 300
    window.resize(1900, 800)  # a wide window uses the spare room (nested layouts settle over a few events)
    qtbot.waitUntil(lambda: lab.width() > 300, timeout=3000)

    i18n.set_language("en")
    window._refresh_target()
    assert window.status_text("target") == f"Target found: {title}"


def test_target_states_do_not_keep_a_stale_tooltip(window: mw_mod.MainWindow, demo_ctx: Any, qtbot: Any,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    from autopress.win32 import windows

    monkeypatch.setattr(windows, "find_window", lambda match: WindowInfo(hwnd=5, title="兌換中心 - Chrome",
                                                                         exe_path="C:/x/chrome.exe"))
    window.show()
    window._refresh_target()
    item = window.status_bar.items["target"]
    assert item.toolTip() == "兌換中心 - Chrome"
    monkeypatch.setattr(windows, "find_window", lambda match: None)
    window._refresh_target()
    assert window.status_text("target") == "找不到目標視窗" and item.toolTip().startswith("找不到目標視窗：")
    demo_ctx.set_active_profile("")
    assert window.status_text("target") == "目標視窗：未選擇設定檔" and item.toolTip() == ""


# ------------------------------------------------------------------------------------------ U43


def test_sidebar_badges_say_what_they_count(window: mw_mod.MainWindow, demo_ctx: Any, qtbot: Any) -> None:
    from autopress.ui.codes_model import TODO_STATUSES  # the Codes header's 「待處理」 rule (repair round 3)

    counts = demo_ctx.queue.counts()
    todo = {s: counts.get(s, 0) for s in TODO_STATUSES}
    n = sum(todo.values())
    assert n and todo[CodeStatus.REVIEW]  # the demo queue has codes to do and codes to review
    codes = window.sidebar.buttons["codes"]
    assert codes.badge() == str(n)
    tip = codes.toolTip()
    assert tip.startswith(f"待處理的序號 {n} 筆：")
    for status, count in todo.items():
        assert (f"{status.label()} {count}" in tip) == bool(count)
    assert codes.accessibleDescription() == tip
    assert window.sidebar.buttons["profiles"].toolTip() == f"共 {len(demo_ctx.profiles.list())} 個設定檔"
    assert window.sidebar.buttons["history"].toolTip() == f"共 {len(demo_ctx.history.records())} 筆紀錄"

    demo_ctx.queue.add_candidates([CodeCandidate(code="NEWCODE123")], CodeSource.PASTE)
    qtbot.waitUntil(lambda: codes.toolTip().startswith(f"待處理的序號 {n + 1} 筆："))
    assert f"待兌換 {todo[CodeStatus.PENDING] + 1}" in codes.toolTip()

    window.set_badge("run", "3", "說明文字")
    assert window.sidebar.buttons["run"].toolTip() == "說明文字"
    window.set_badge("run", "", "說明文字")  # a hidden pill explains nothing
    assert window.sidebar.buttons["run"].toolTip() == ""


def test_sidebar_badge_tooltips_english(window: mw_mod.MainWindow, demo_ctx: Any) -> None:
    i18n.set_language("en")
    window._refresh_badges()
    counts = demo_ctx.queue.counts()
    n = sum(counts.get(s, 0) for s in (CodeStatus.PENDING, CodeStatus.COOLDOWN, CodeStatus.REVIEW))
    tip = window.sidebar.buttons["codes"].toolTip()
    assert tip.startswith(f"{n} codes to do: ") and "Needs review" in tip
    assert window.sidebar.buttons["profiles"].toolTip() == "1 profile"  # singular
    assert window.sidebar.buttons["history"].toolTip() == f"{len(demo_ctx.history.records())} history records"


# ------------------------------------------------------------------------------------------ U26


@pytest.mark.parametrize("name", ["dark", "light"])
def test_disabled_icons_use_the_disabled_text_colour(qtbot: Any, dark_after: QApplication, name: str) -> None:
    theme.apply_theme(dark_after, name)
    want = theme.color("text_disabled")
    primary = widgets.push_button("", "primary", "play")
    secondary = widgets.push_button("", "secondary", "flask")
    up = widgets.icon_button("arrow_up", "Up")
    mark = widgets.icon_label("shield", "success", 16)
    host = _card(qtbot, primary, secondary, up, mark)
    for wdg in (primary, secondary, up, mark):
        wdg.setEnabled(False)
    # what the styles paint: the button icons' Disabled pixmap, and a disabled QLabel's pixmap,
    # which Qt 6.12 keeps as a one-entry QIcon and asks the style to generate
    for b in (primary, secondary, up):
        colours = _opaque_colours(b.icon().pixmap(b.iconSize(), 1.0, QIcon.Mode.Disabled))
        assert colours and all(_near(c, want) for c in colours), (b, colours)
    label_disabled = QIcon(mark.pixmap()).pixmap(mark.pixmap().size(), 1.0, QIcon.Mode.Disabled)
    colours = _opaque_colours(label_disabled)
    assert colours and all(_near(c, want) for c in colours), colours
    # enabled icons keep their token colour
    assert all(_near(c, theme.color("on_accent")) for c in _opaque_colours(primary.icon().pixmap(16)))
    if name == "dark":  # on screen: no disabled icon is brighter than the disabled text colour
        QApplication.processEvents()
        img = host.grab().toImage()
        limit = max(want.red(), want.green(), want.blue()) + 8
        for wdg in (primary, secondary, up, mark):
            g = wdg.geometry()
            icon_rect = QRect(g.center().x() - 8, g.center().y() - 8, 16, 16)
            assert _brightest(img, icon_rect) <= limit, wdg


def test_generated_disabled_pixmap_keeps_multicolour_and_large_pictures(qapp: QApplication,
                                                                       dark_after: QApplication) -> None:
    theme.apply_theme(dark_after, "dark")
    style = QApplication.style()  # the style-sheet style in front of AppStyle
    opt = QStyleOption()
    opt.palette = QApplication.palette()
    want = theme.color("text_disabled")
    mono = icons.icon_pixmap("check", "#3DD68C", 16)
    tinted = style.generatedIconPixmap(QIcon.Mode.Disabled, mono, opt)
    assert all(_near(c, want) for c in _opaque_colours(tinted))
    assert tinted.size() == mono.size() and tinted.devicePixelRatio() == mono.devicePixelRatio()
    two = QPixmap(16, 16)  # a program icon: several colours -> Qt's own disabled look, not one flat colour
    two.fill(QColor("#FF0000"))
    p = QPainter(two)
    p.fillRect(8, 0, 8, 16, QColor("#0000FF"))
    p.end()
    gen = style.generatedIconPixmap(QIcon.Mode.Disabled, two, opt).toImage()
    assert gen.pixelColor(2, 8) != gen.pixelColor(13, 8)
    big = QPixmap(200, 200)  # pictures (crops, photos) are left to Qt too
    big.fill(QColor("#FFFFFF"))
    assert not _near(next(iter(_opaque_colours(style.generatedIconPixmap(QIcon.Mode.Disabled, big, opt)))), want)
    normal = style.generatedIconPixmap(QIcon.Mode.Normal, mono, opt)
    assert _opaque_colours(normal) == _opaque_colours(mono)
    assert shell_style.tint_monochrome(QPixmap(), want) is None


# ------------------------------------------------------------------------------------------ U4


def test_qss_has_the_new_hooks() -> None:
    qss = theme.build_qss(theme.DARK)
    for selector in ("QAbstractScrollArea::corner", 'QScrollArea[frameRole="inset"]',
                     'QToolButton[toc="true"]:checked', 'QToolButton[toc="true"]:checked:focus'):
        assert selector in qss, selector


@pytest.mark.parametrize("name", ["dark", "light"])
def test_scroll_area_corner_is_blank(qtbot: Any, dark_after: QApplication, name: str) -> None:
    theme.apply_theme(dark_after, name)
    area = QScrollArea()
    inner = QWidget()
    inner.setMinimumSize(600, 600)
    area.setWidget(inner)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
    area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
    host = _card(qtbot, area, size=(240, 190))
    img = host.grab().toImage()
    vp = area.viewport().geometry()
    corner = QRect(vp.right() + 1, vp.bottom() + 1, area.width() - vp.right() - 1, area.height() - vp.bottom() - 1)
    corner.translate(area.pos())
    assert corner.width() > 4 and corner.height() > 4
    card = theme.color("surface")
    stray = {img.pixelColor(x, y).name() for x in range(corner.left(), corner.right() + 1)
             for y in range(corner.top(), corner.bottom() + 1)} - {card.name()}
    assert not stray, stray  # no bordered square where the two scroll bars meet


# ------------------------------------------------------------------------------------------ U25


@pytest.mark.parametrize("name", ["dark", "light"])
def test_inset_scroll_area_is_a_framed_canvas(qtbot: Any, dark_after: QApplication, name: str) -> None:
    theme.apply_theme(dark_after, name)
    area = QScrollArea()
    area.setProperty("frameRole", "inset")
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    pm = QPixmap(300, 60)
    pm.fill(QColor("#FFFFFF"))  # a white crop: must not melt into the light dialog
    shot = QLabel()
    shot.setPixmap(pm)
    area.setWidget(shot)
    host = _card(qtbot, area, size=(320, 200))
    img = host.grab().toImage()
    g = area.geometry()
    assert img.pixelColor(g.center().x(), g.top()).name() == theme.color("border").name()
    assert img.pixelColor(g.left(), g.center().y()).name() == theme.color("border").name()
    vp = area.viewport().geometry()
    assert (vp.x(), vp.y()) == (5, 5) and vp.width() == g.width() - 10  # 1 px border + 4 px padding
    assert img.pixelColor(g.left() + 3, g.center().y()).name() == theme.color("surface_inset").name()


# ------------------------------------------------------------------------------------------ U42


@pytest.mark.parametrize("name", ["dark", "light"])
def test_current_toc_entry_has_soft_fill_and_no_accent_box(qtbot: Any, dark_after: QApplication, name: str) -> None:
    theme.apply_theme(dark_after, name)
    entries = []
    for text in ("關於 AutoPress", "安全守則"):
        b = widgets.tool_button("info", text, "ghost")
        b.setCheckable(True)
        b.setProperty("toc", True)
        entries.append(b)
    entries[0].setChecked(True)
    host = _card(qtbot, *entries, vertical=True, size=(260, 140))
    on, off = (b.geometry() for b in entries)

    def edges(img: QImage) -> set[str]:
        out = {img.pixelColor(x, on.center().y()).name() for x in (on.left(), on.right())}
        return out | {img.pixelColor(on.center().x(), y).name() for y in (on.top(), on.bottom())}

    for b in entries:  # showing the card gave the first entry the keyboard focus
        b.clearFocus()
    QApplication.processEvents()
    img = host.grab().toImage()
    fill, accent = theme.color("nav_active"), theme.color("accent")
    assert img.pixelColor(on.right() - 6, on.center().y()).name() == fill.name()
    # the 1 px edge is the anti-aliased rim of the soft fill, never the accent colour
    assert all(not _near((QColor(c).red(), QColor(c).green(), QColor(c).blue()), accent, 60) for c in edges(img)), \
        edges(img)
    assert img.pixelColor(off.right() - 6, off.center().y()).name() == theme.color("surface").name()
    entries[0].setFocus()  # keyboard focus still shows the accent ring
    QApplication.processEvents()
    if entries[0].hasFocus():
        assert edges(host.grab().toImage()) == {accent.name()}


# ------------------------------------------------------------------------------------------ U30


def test_failsafe_sentence_has_no_nested_brackets() -> None:
    zh = failsafe_corner_text(LEFT_OF_PRIMARY)
    assert zh == "你有 2 個螢幕：要推到「最左邊那個螢幕」的左上角（-1920, 0）才算，主螢幕的左上角不算。"
    assert "(" not in zh and ")" not in zh and "））" not in zh and "座標" not in zh
    i18n.set_language("en")
    en = failsafe_corner_text(LEFT_OF_PRIMARY)
    assert en == ("You have 2 screens: push the mouse into the top-left corner of the left-most screen, "
                  "at (-1920, 0); the primary screen's corner does not count.")
    assert "((" not in en and "))" not in en and "LEFT" not in en


def test_failsafe_sentence_lists_every_outer_corner() -> None:
    above = failsafe_corner_text(ABOVE_PRIMARY)
    assert above == "你有 2 個螢幕：要推到桌面外側的左上角才算，位置是（0, -1080）。"
    both = failsafe_corner_text(LEFT_AND_LOWER)  # the primary's corner counts here too
    assert both == "你有 2 個螢幕：要推到桌面外側的左上角才算，位置是（0, 0）、（-1920, 300）。"
    assert "不算" not in both
    for text in (above, both):
        assert "(" not in text and "））" not in text and "）（" not in text
    i18n.set_language("en")
    en = failsafe_corner_text(LEFT_AND_LOWER)
    assert en == ("You have 2 screens: push the mouse into an outer top-left corner of the desktop, "
                  "at (0, 0) or (-1920, 300).")
    assert failsafe_corner_text([(0, 0, 2560, 1440)]).startswith("Push the mouse into the top-left corner")
