"""G5: tokens, theme application (both themes), QSS contract, palette, fonts, AppStyle."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from PyQt6.QtGui import QFont, QPalette
from PyQt6.QtWidgets import QApplication, QCheckBox, QDoubleSpinBox, QLabel, QLineEdit, QSpinBox, QWidget

from autopress.models import CodeStatus, ThemeName
from autopress.ui import icons, shell_style, theme


@pytest.fixture
def dark_after(qapp: QApplication):
    """Every test leaves the shared application in the dark theme."""
    yield qapp
    theme.apply_theme(qapp, "dark")


def test_token_tables_complete_and_parse() -> None:
    assert set(theme.DARK) == set(theme.LIGHT)
    for table in (theme.DARK, theme.LIGHT):
        for key, value in table.items():
            if key == "name":
                continue
            assert re.fullmatch(r"#[0-9A-F]{6}([0-9A-F]{2})?", value), (key, value)
            assert theme._parse(value).isValid()
    assert theme.THEMES == {"dark": theme.DARK, "light": theme.LIGHT}


def test_color_css_and_tones(dark_after: QApplication) -> None:
    theme.apply_theme(dark_after, "dark")
    c = theme.color("accent_soft")  # alpha last: #6B93FF24
    assert (c.red(), c.green(), c.blue(), c.alpha()) == (0x6B, 0x93, 0xFF, 0x24)
    assert theme.css("accent_soft") == "rgba(107, 147, 255, 36)"
    assert theme.css("text") == "#e7e9ee"
    assert theme.color("#112233").name() == "#112233"
    for status in CodeStatus:
        base, soft, text = theme.tone_colors(status.tone)
        assert base.isValid() and soft.isValid() and text.isValid()
        assert soft.alpha() < 255  # soft fills are translucent
    assert theme.tone_colors("accent")[2] == theme.color("accent_text")
    assert theme.tone_colors("no-such-tone")[0] == theme.color("neutral")


def test_resolve_theme() -> None:
    assert theme.resolve_theme("dark") == "dark"
    assert theme.resolve_theme(ThemeName.LIGHT) == "light"
    assert theme.resolve_theme("system") in ("dark", "light")  # offscreen: Unknown -> dark
    assert theme.resolve_theme("nonsense") in ("dark", "light")


@pytest.mark.parametrize("name", ["dark", "light"])
def test_apply_theme_both(dark_after: QApplication, name: str) -> None:
    app = dark_after
    assert theme.apply_theme(app, name) == name
    assert theme.current_theme() == name and theme.tokens() is theme.THEMES[name]
    t = theme.THEMES[name]
    assert app.palette().color(QPalette.ColorRole.Window).name().upper() == t["bg_app"]
    assert app.palette().color(QPalette.ColorRole.Highlight).name().upper() == t["accent_fill"]
    qss = app.styleSheet()
    assert qss and theme._parse(t["surface"]).name() in qss
    assert isinstance(shell_style.AppStyle, type) and theme._state["style"] is not None


def test_qss_contract_selectors() -> None:
    qss = theme.build_qss(theme.DARK)
    required = [
        'QPushButton[variant="primary"]', 'QPushButton[variant="ghost"]', 'QPushButton[variant="danger"]',
        'QToolButton[variant="ghost"]', 'QToolButton[variant="icon"]', "QLineEdit QToolButton",
        *[f'QLabel[role="{r}"]' for r in ("display", "title", "body", "secondary", "muted", "caption", "mono",
                                          "error", "keycap")],
        "QLineEdit", "QComboBox", "combobox-popup: 0", "QAbstractSpinBox", "QPlainTextEdit",
        "QTableView", "QHeaderView::section", "QScrollBar:vertical", "QMenu", "QToolTip", "QCheckBox", "QTabBar",
        'QFrame[frameRole="card"]', 'QFrame[frameRole="banner"][tone="warning"]', 'QFrame[frameRole="sidebar"]',
        'QFrame[frameRole="statusbar"]', "QFrame#Card", "QFrame#MiniBar",
        "QPushButton:focus", "QLineEdit:focus", 'QFrame[frameRole="segmented"] QPushButton:focus',
    ]
    missing = [s for s in required if s not in qss]
    assert not missing, missing
    # opaque table selection (prototype lesson: alpha selections darken when painted twice)
    assert f"selection-background-color: {theme._parse(theme.DARK['row_selected']).name()}" in qss
    # a bare QToolButton rule would leak into QLineEdit's clear button: every QToolButton rule is
    # scoped by [variant] or is the QLineEdit / QAbstractSpinBox reset rule
    for m in re.finditer(r"(\S*)\s*QToolButton(?!\[)", qss):
        assert m.group(1) in ("QLineEdit", "QAbstractSpinBox,", "QAbstractSpinBox"), qss[m.start() - 40:m.end() + 20]
    # the QWidget base rule sets no font size, so widget.setFont(theme.font(...)) is never overridden
    base = re.search(r"QWidget \{([^}]*)\}", qss)
    assert base is not None and "font" not in base.group(1)
    for tone in theme.TONES:
        assert f'QFrame[frameRole="banner"][tone="{tone}"]' in qss
        assert f'QLabel[role="tone_{tone}"]' in qss


def test_qss_light_differs_and_assets_exist(isolated_home: Path) -> None:
    dark, light = theme.build_qss(theme.DARK), theme.build_qss(theme.LIGHT)
    assert dark != light
    urls = re.findall(r'url\("([^"]+)"\)', light)
    assert urls, "combo / spin box arrows need image files"
    for u in urls:
        p = Path(u)
        assert p.is_file() and p.suffix == ".svg"
        assert isolated_home in p.parents  # inside the data folder (cache/ui)


def test_qss_assets_with_chinese_data_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                             dark_after: QApplication) -> None:
    home = tmp_path / "資料 夾"
    monkeypatch.setenv("AUTOPRESS_HOME", str(home))
    theme.apply_theme(dark_after, "light")
    urls = re.findall(r'url\("([^"]+)"\)', dark_after.styleSheet())
    assert urls and all(Path(u).is_file() and "資料 夾" in u for u in urls)


def test_fonts() -> None:
    f = theme.font(theme.FS_TITLE, bold=True)
    assert f.pixelSize() == 15 and f.weight() == QFont.Weight.Bold
    assert f.families()[:2] == list(theme.FONT_UI)
    m = theme.font(theme.FS_MONO, mono=True)
    assert m.families()[0] == "Consolas" and m.pixelSize() == 14
    n = theme.font(12, num=True, tnum=True)
    assert n.families()[0] == "Segoe UI"
    assert QFont.Tag("tnum") in n.featureTags()


def test_build_palette_disabled_text() -> None:
    pal = theme.build_palette(theme.LIGHT)
    assert pal.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text).name().upper() == theme.LIGHT["text_disabled"]
    assert pal.color(QPalette.ColorRole.PlaceholderText).name().upper() == theme.LIGHT["text_muted"]


def test_app_style_spinbox_polish(qtbot: object, dark_after: QApplication) -> None:
    theme.apply_theme(dark_after, "dark")
    host = QWidget()
    qtbot.addWidget(host)
    spin = QSpinBox(host)
    dspin = QDoubleSpinBox(host)
    other = QLineEdit(host)
    host.show()
    qtbot.waitExposed(host)
    for s in (spin, dspin):
        assert not s.keyboardTracking()  # SPEC 6.5, applied app-wide by AppStyle.polish
        edit = s.findChild(QLineEdit)
        assert edit.textMargins().left() == shell_style.SPIN_TEXT_MARGIN
    spin.setValue(42)
    other.setFocus()
    spin.setFocus()
    qtbot.waitUntil(lambda: spin.findChild(QLineEdit).hasSelectedText(), timeout=2000)
    assert spin.findChild(QLineEdit).selectedText() == "42"


def test_app_style_paints_check_indicators(qtbot: object, dark_after: QApplication) -> None:
    for name in ("dark", "light"):
        theme.apply_theme(dark_after, name)
        on, off = QCheckBox("on"), QCheckBox("off")
        on.setChecked(True)
        qtbot.addWidget(on)
        qtbot.addWidget(off)
        img_on, img_off = on.grab().toImage(), off.grab().toImage()
        accent = theme.color("accent_fill")
        found = any(img_on.pixelColor(x, y).name() == accent.name()
                    for x in range(min(18, img_on.width())) for y in range(img_on.height()))
        assert found, f"checked indicator not drawn in accent_fill ({name})"
        assert not any(img_off.pixelColor(x, y).name() == accent.name()
                       for x in range(min(18, img_off.width())) for y in range(img_off.height()))


def test_theme_switch_recolours_bound_icons(qtbot: object, dark_after: QApplication) -> None:
    theme.apply_theme(dark_after, "dark")
    lb = QLabel()
    qtbot.addWidget(lb)
    icons.bind(lb, "check", "text", 16)
    before = lb.pixmap().toImage()
    theme.apply_theme(dark_after, "light")
    after = lb.pixmap().toImage()
    assert before != after  # re-rendered in LIGHT's text colour
    assert icons.refresh_bound(lb) == 1


def test_label_roles_follow_theme(qtbot: object, dark_after: QApplication) -> None:
    from autopress.ui import widgets

    theme.apply_theme(dark_after, "dark")
    lb = widgets.label("x", "display")
    qtbot.addWidget(lb)
    lb.ensurePolished()
    assert lb.font().pixelSize() == theme.FS_DISPLAY and lb.font().bold()
    mono = widgets.label("AB12", "mono")
    qtbot.addWidget(mono)
    mono.ensurePolished()
    assert mono.font().pixelSize() == theme.FS_MONO and "Consolas" in mono.font().family()
    plain = QLabel("y")
    plain.setFont(theme.font(theme.FS_MONO, mono=True))
    qtbot.addWidget(plain)
    plain.ensurePolished()
    assert plain.font().pixelSize() == theme.FS_MONO  # no global font rule overrides setFont
