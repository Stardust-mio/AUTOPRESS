"""G5: icons for every name, the widgets API (incl. the ui_fallback compatibility attributes),
headless dialogs and the themed message dialog."""

from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QLineEdit, QToolButton, QVBoxLayout, QWidget

from autopress.models import CodeSource, CodeStatus, StepType
from autopress.ui import icons, theme, widgets
from autopress.ui.widgets_dialogs import MessageDialog


def _opaque_pixels(img: QImage) -> int:
    return sum(1 for x in range(img.width()) for y in range(img.height()) if img.pixelColor(x, y).alpha() > 0)


def test_every_icon_renders(qapp: QApplication) -> None:
    names = set(icons.ICON_NAMES) | {s.icon for s in StepType} | {s.icon for s in CodeSource}
    assert names <= set(icons.ICONS)
    for name in sorted(names):
        pm = icons.icon_pixmap(name, "text", 24)
        assert not pm.isNull(), name
        assert _opaque_pixels(pm.toImage()) > 10, f"icon {name!r} draws nothing"
        assert not icons.icon(name).isNull()


def test_icon_cache_colours_and_fallback(qapp: QApplication) -> None:
    a = icons.icon_pixmap("check", "#FF0000", 18)
    assert icons.icon_pixmap("check", "#FF0000", 18) is a  # cached
    red = a.toImage()
    colours = {red.pixelColor(x, y).name() for x in range(red.width()) for y in range(red.height())
               if red.pixelColor(x, y).alpha() == 255}
    assert colours == {"#ff0000"}
    assert icons.icon_pixmap("check", theme.color("accent"), 18).toImage() is not None  # QColor accepted
    assert not icons.icon_pixmap("does-not-exist", "text", 16).isNull()  # logged, falls back to "info"
    assert len(icons.app_icon().availableSizes()) >= 5


def test_icon_bind_and_refresh(qtbot: object) -> None:
    b = widgets.push_button("貼上文字", "secondary", "paste")
    qtbot.addWidget(b)
    assert not b.icon().isNull() and b.property("_apIcon") == "paste|text_secondary|16"
    icons.bind(b, "", "text")
    assert b.icon().isNull() and not b.property("_apIcon")


def test_basic_helpers(qtbot: object) -> None:
    lb = widgets.label("標題", "title")
    assert lb.property("role") == "title" and lb.text() == "標題"
    pb = widgets.push_button("開始兌換", "primary", "play")
    assert pb.property("variant") == "primary" and pb.height() == theme.CONTROL_H and not pb.icon().isNull()
    ib = widgets.icon_button("trash", "移除")
    assert isinstance(ib, QToolButton) and ib.toolTip() == "移除" and ib.accessibleName() == "移除"
    assert (ib.width(), ib.height()) == (32, 32) and ib.property("iconOnly") is True
    head = widgets.section_header("序號", "24 筆", [widgets.push_button("x")])
    texts = [w.text() for w in head.findChildren(QLabel)]
    assert "序號" in texts and "24 筆" in texts
    field = QLineEdit()
    row = widgets.form_row("名稱", field, "提示")
    assert field.parent() is row and [w.text() for w in row.findChildren(QLabel)] == ["名稱", "提示"]
    for w in (lb, pb, ib, head, row):
        qtbot.addWidget(w)


def test_switch_space_toggles(qtbot: object) -> None:
    host = QWidget()
    qtbot.addWidget(host)
    lay = QHBoxLayout(host)
    sw = widgets.Switch(False)
    lay.addWidget(sw)
    seen: list[bool] = []
    sw.toggled.connect(seen.append)
    host.show()
    host.activateWindow()
    sw.setFocus()
    qtbot.waitUntil(lambda: QApplication.focusWidget() is sw)
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Space)
    assert sw.isChecked() and seen == [True]
    assert sw.sizeHint().width() >= 34 and sw.sizeHint().height() >= 20


def test_segmented_control(qtbot: object) -> None:
    seg = widgets.SegmentedControl(["全部 3", "待兌換 1", "需確認 2"], 0)
    qtbot.addWidget(seg)
    got: list[int] = []
    seg.currentChanged.connect(got.append)
    qtbot.mouseClick(seg.buttons()[2], Qt.MouseButton.LeftButton)
    assert seg.currentIndex() == 2 and got == [2]
    seg.setItems(["全部 4", "待兌換 2", "需確認 2"])  # same count: texts only, no signal
    assert seg.currentIndex() == 2 and got == [2] and seg.buttons()[0].text() == "全部 4"
    seg.setCurrentIndex(2)
    assert got == [2]  # unchanged index: no signal
    seg.setCurrentIndex(0)
    assert got == [2, 0]
    seg.setItems(["一", "二"])  # different count: rebuilt, index kept when valid
    assert seg.currentIndex() == 0 and len(seg.buttons()) == 2


def test_search_combo_card_banner(qtbot: object) -> None:
    sf = widgets.SearchField("搜尋序號或訊息")
    assert sf.placeholderText() == "搜尋序號或訊息" and sf.isClearButtonEnabled() and sf.height() == 32
    c = widgets.combo(["自動偵測", "HoYoverse"], 160)
    assert isinstance(c, widgets.ChevronCombo) and c.count() == 2 and c.width() == 160
    card = widgets.Card()
    assert isinstance(card.layout(), QVBoxLayout) and card.property("frameRole") == "card"
    m = card.layout().contentsMargins()
    assert (m.left(), m.top(), m.right(), m.bottom()) == theme.CARD_MARGINS
    assert isinstance(widgets.Card(vertical=False).layout(), QHBoxLayout)
    b = widgets.Banner("warning", "2 筆需要確認", "逐筆檢查")
    for w in (sf, c, card, b):
        qtbot.addWidget(w)
    assert b.text() == "2 筆需要確認" and b.property("tone") == "warning"
    b.setText("3 筆需要確認")
    b.setTone("info")
    assert b.text() == "3 筆需要確認" and b.tone() == "info" and b.property("tone") == "info"
    clicked: list[bool] = []
    closed: list[bool] = []
    b.actionClicked.connect(lambda: clicked.append(True))
    b.closed.connect(lambda: closed.append(True))
    b.show()
    qtbot.mouseClick(b.action_button(), Qt.MouseButton.LeftButton)
    assert clicked == [True]
    close = [t for t in b.findChildren(QToolButton) if t.accessibleName() == "關閉"][0]
    qtbot.mouseClick(close, Qt.MouseButton.LeftButton)
    assert closed == [True] and b.isHidden()
    plain = widgets.Banner("error", "x", "", closable=False)
    qtbot.addWidget(plain)
    assert plain.action_button().isHidden()


def test_empty_state_keycap_divider_elided(qtbot: object) -> None:
    btn = widgets.push_button("貼上文字", "primary")
    es = widgets.EmptyState("codes", "還沒有任何序號", "貼上一段文字", [btn], ["Ctrl", "V"], "貼上序號")
    qtbot.addWidget(es)
    assert btn.parent() is not None
    assert [k.text() for k in es.findChildren(widgets.Keycap)] == ["Ctrl", "V"]
    k = widgets.Keycap("F8")
    qtbot.addWidget(k)
    assert k.height() == theme.KEYCAP_H and k.property("role") == "keycap"
    d = widgets.Divider()
    v = widgets.Divider(vertical=True)
    assert d.height() == 1 and v.width() == 1
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(1000, 40)
    el = widgets.ElidedLabel("目標視窗：一個非常非常長的視窗標題，會被截斷", host)
    el.setGeometry(0, 0, 60, 20)
    host.show()
    el.grab()  # renders through paintEvent
    assert el.width() == 60 and el.toolTip() == el.text()  # cut -> full text as tooltip
    el.setGeometry(0, 0, 900, 20)
    el.grab()
    assert el.toolTip() == ""
    assert el.minimumSizeHint().width() < 60  # never widens its parent


def test_status_chips(qtbot: object) -> None:
    img = QImage(400, 40, QImage.Format.Format_ARGB32)
    img.fill(0)
    for status in CodeStatus:
        p = QPainter(img)
        w = widgets.paint_status_chip(p, QRectF(0, 0, 400, 40), status)
        p.end()
        assert w == widgets.status_chip_width(status) > 30
        chip = widgets.StatusChip(status)
        qtbot.addWidget(chip)
        assert chip.status is status and chip.text is None and chip.width() == int(w)
    chip.setStatus(CodeStatus.SUCCESS, "成功 5")
    assert chip.text == "成功 5" and chip.width() == widgets.status_chip_width(CodeStatus.SUCCESS, "成功 5")
    assert widgets.status_chip_width(CodeStatus.SUCCESS, "很長的文字很長的文字") > widgets.status_chip_width(CodeStatus.SUCCESS)


def test_progress_ring_and_spinner(qtbot: object) -> None:
    ring = widgets.ProgressRing(40)
    qtbot.addWidget(ring)
    ring.setProgress(7, 15)
    ring.setTone("success")
    assert (ring.done, ring.total, ring.tone) == (7, 15, "success") and ring.width() == 40
    assert not ring.grab().isNull()
    sp = widgets.Spinner(20)
    qtbot.addWidget(sp)
    assert not sp.running
    sp.start()
    assert sp.running
    sp.stop()
    assert not sp.running


def test_headless_dialogs_never_block(qapp: QApplication) -> None:
    assert QApplication.platformName() == "offscreen"
    assert widgets.confirm(None, "刪除？", "確定要刪除嗎？", danger=True) is True
    assert widgets.message(None, "AutoPress", "訊息", "warning") is None


def test_message_dialog_buttons(qtbot: object) -> None:
    danger = MessageDialog(None, "清除？", "不能復原。", "question", "清除", None, danger=True, question=True)
    qtbot.addWidget(danger)
    assert danger.cancel_button is not None
    assert danger.cancel_button.isDefault() and not danger.ok_button.isDefault()  # Enter never deletes
    assert danger.ok_button.property("variant") == "danger"
    normal = MessageDialog(None, "繼續？", "說明", "question", None, None, danger=False, question=True)
    qtbot.addWidget(normal)
    assert normal.ok_button.isDefault() and normal.ok_button.property("variant") == "primary"
    assert normal.ok_button.text() == "確定" and normal.cancel_button.text() == "取消"
    normal.show()
    QTest.keyClick(normal, Qt.Key.Key_Escape)
    assert normal.result() == QDialog.DialogCode.Rejected
    info = MessageDialog(None, "AutoPress", "AutoPress 已在執行中。", "info")
    qtbot.addWidget(info)
    assert info.cancel_button is None and info.text_label.text() == "AutoPress 已在執行中。"
    info.show()
    qtbot.mouseClick(info.ok_button, Qt.MouseButton.LeftButton)
    assert info.result() == QDialog.DialogCode.Accepted
