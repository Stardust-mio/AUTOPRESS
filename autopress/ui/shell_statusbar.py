# OWNED BY G5
"""Private part of ui.main_window: the always-visible status bar (SPEC 6.3).

Left: 前景保護 · 間隔 · keycaps F8 暫停 F9 停止 · 左上角緊急停止; right: 文字辨識 · 目標視窗 · run
state. Items are addressed by key (``MainWindow.set_status``); unknown keys get a new item on
the right, "" hides an item. Tones colour the icon: neutral, success, warning, error, info,
accent.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

from ..i18n import tr
from . import icons, theme
from .widgets import ElidedLabel, Keycap, label

_TONE_TOKEN = {"neutral": "text_muted", "success": "success", "warning": "warning", "error": "error",
               "info": "info", "accent": "accent", "violet": "violet", "orange": "orange"}
_TEXT_ROLE = {"warning": "warning", "error": "error"}
TARGET_MAX_W = 480
"""Widest the target item's text gets (logical px); it elides on the right below that, so the
state that main_window puts first (「已找到目標視窗：」) stays visible down to the 1100 px window."""


class StatusItem(QWidget):
    """Icon + text; ``set(text, tone)``."""

    def __init__(self, key: str, icon_name: str = "", elide_width: int = 0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = key
        self._icon_name = icon_name
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.SP[2] - 2)
        self.icon = QLabel(self)
        self.icon.setFixedSize(16, 16)
        self.icon.setVisible(bool(icon_name))
        lay.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignVCenter)
        if elide_width:
            self.text_label: QLabel = ElidedLabel(self)
            self.text_label.setMaximumWidth(elide_width)
            self.text_label.setMinimumWidth(60)
        else:
            self.text_label = QLabel(self)
        self.text_label.setProperty("role", "status")
        lay.addWidget(self.text_label, 0 if not elide_width else 1, Qt.AlignmentFlag.AlignVCenter)
        self.tone = "neutral"
        self.set("", "neutral")

    def text(self) -> str:
        return self.text_label.text()

    def set(self, text: str, tone: str = "neutral", tooltip: str | None = None) -> None:
        self.tone = tone
        self.text_label.setText(text)
        role = _TEXT_ROLE.get(tone, "status")
        if self.text_label.property("role") != role:
            self.text_label.setProperty("role", role)
            st = self.text_label.style()
            if st is not None:
                st.unpolish(self.text_label)
                st.polish(self.text_label)
        if self._icon_name:
            icons.bind(self.icon, self._icon_name, _TONE_TOKEN.get(tone, "text_muted"), 16)
        if tooltip is not None:
            self.setToolTip(tooltip)
        self.setAccessibleName(text)
        self.setVisible(bool(text))


class HotkeyHint(QWidget):
    """Keycaps of the run hotkeys: [F8] 暫停  [F9] 停止."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.SP[1] + 2)
        self.pause_key = Keycap("F8", self)
        self.stop_key = Keycap("F9", self)
        self.pause_text = label(tr("暫停", "Pause"), "status")
        self.stop_text = label(tr("停止", "Stop"), "status")
        lay.addWidget(self.pause_key, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self.pause_text, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addSpacing(theme.SP[1])
        lay.addWidget(self.stop_key, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self.stop_text, 0, Qt.AlignmentFlag.AlignVCenter)
        self.setToolTip(tr("執行期間的快捷鍵（可在「設定」更換）", "Hotkeys during runs (change them in Settings)"))

    def set_combos(self, pause: str, stop: str) -> None:
        self.pause_key.setText(pause)
        self.stop_key.setText(stop)
        self.pause_key.adjustSize()
        self.stop_key.adjustSize()


def _vsep(parent: QWidget) -> QFrame:
    f = QFrame(parent)
    f.setProperty("role", "vsep")
    f.setFixedSize(1, 14)
    return f


class StatusBar(QFrame):
    """The bar; ``item(key)`` returns (and creates) an item."""

    LEFT = ("guard", "interval", "hotkeys", "failsafe")
    RIGHT = ("ocr", "target", "run")

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("frameRole", "statusbar")
        self.setObjectName("StatusBar")
        self.setFixedHeight(36)
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(theme.PAGE_MARGINS[0], 0, theme.PAGE_MARGINS[2], 0)
        self._lay.setSpacing(theme.SP[2])
        self.items: dict[str, StatusItem] = {}
        self.items["guard"] = StatusItem("guard", "shield", parent=self)
        self.items["interval"] = StatusItem("interval", "gauge", parent=self)
        self.hotkeys = HotkeyHint(self)
        self.items["failsafe"] = StatusItem("failsafe", "mouse", parent=self)
        for w in (self.items["guard"], _vsep(self), self.items["interval"], _vsep(self), self.hotkeys,
                  _vsep(self), self.items["failsafe"]):
            self._lay.addWidget(w, 0, Qt.AlignmentFlag.AlignVCenter)
        self._lay.addStretch(1)
        self._right_index = self._lay.count()
        self.items["ocr"] = StatusItem("ocr", "scan", parent=self)
        self.items["target"] = StatusItem("target", "window", elide_width=TARGET_MAX_W, parent=self)
        self.items["run"] = StatusItem("run", "play", parent=self)
        for key in self.RIGHT:
            self._lay.addWidget(self.items[key], 0, Qt.AlignmentFlag.AlignVCenter)

    def item(self, key: str) -> StatusItem:
        it = self.items.get(key)
        if it is None:
            it = StatusItem(key, "", parent=self)
            self._lay.addWidget(it, 0, Qt.AlignmentFlag.AlignVCenter)
            self.items[key] = it
        return it
