# OWNED BY G5
"""Private part of ui.main_window: the 220 px sidebar (SPEC 6.3, mock-up codes_dark.png).

Logo + "AutoPress" / 「序號自動輸入」, caption 「工作區」, nav 序號 / 設定檔 / 執行 / 紀錄 with count
pills (each pill's tooltip says what it counts), bottom 設定 / 說明, a divider, the 深色模式 switch
and the version line. The active item has the nav_active fill and a 3 px accent bar (custom
painted, colours read at paint time).
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QFontMetrics, QKeyEvent, QPainter, QPaintEvent, QPen
from PyQt6.QtWidgets import QAbstractButton, QButtonGroup, QFrame, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from .. import __version__
from ..i18n import T, tr
from . import icons, theme
from .widgets import Divider, Switch, icon_label, label

NAV_MAIN: tuple[tuple[str, str, T], ...] = (
    ("codes", "codes", T("序號", "Codes")),
    ("profiles", "profiles", T("設定檔", "Profiles")),
    ("run", "run", T("執行", "Run")),
    ("history", "history", T("紀錄", "History")),
)
NAV_BOTTOM: tuple[tuple[str, str, T], ...] = (
    ("settings", "settings", T("設定", "Settings")),
    ("help", "help", T("說明", "Help")),
)


class NavButton(QAbstractButton):
    """Sidebar item: icon, label, optional count badge; checked = soft fill + accent bar."""

    def __init__(self, page_id: str, icon_name: str, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.page_id = page_id
        self._icon = icon_name
        self._badge = ""
        self.setCheckable(True)
        self.setText(text)
        self.setAccessibleName(text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(theme.NAV_H)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def badge(self) -> str:
        return self._badge

    def setBadge(self, text: str, tooltip: str = "") -> None:
        """Count pill text ("" hides it); ``tooltip`` (also the accessible description) says what
        the number counts - the 序號 pill counts codes still to do, the others are totals."""
        self._badge = str(text or "")
        tip = str(tooltip or "") if self._badge else ""
        self.setAccessibleName(f"{self.text()} {self._badge}".strip())
        self.setToolTip(tip)
        self.setAccessibleDescription(tip)
        self.update()

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(theme.font(theme.FS_BODY, bold=True))
        w = 12 + 18 + 10 + fm.horizontalAdvance(self.text()) + 12
        if self._badge:
            w += QFontMetrics(theme.font(theme.FS_CAPTION, bold=True, num=True)).horizontalAdvance(self._badge) + 20
        return QSize(w, theme.NAV_H)

    def keyPressEvent(self, event: QKeyEvent | None) -> None:
        if event is not None and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.click()
            return
        super().keyPressEvent(event)

    def paintEvent(self, _event: QPaintEvent | None) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        on = self.isChecked()
        if on or self.underMouse():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.color("nav_active" if on else "hover"))
            p.drawRoundedRect(QRectF(0, 0, w, h), theme.R_MD, theme.R_MD)
        if on:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.color("accent"))
            p.drawRoundedRect(QRectF(0, h / 2 - 8, 3, 16), 1.5, 1.5)
        if self.hasFocus():
            p.setPen(QPen(theme.color("accent"), 1.4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(0.7, 0.7, w - 1.4, h - 1.4), theme.R_MD, theme.R_MD)
        p.drawPixmap(QPointF(12, (h - 18) / 2),
                     icons.icon_pixmap(self._icon, "accent_text" if on else "text_secondary", 18))
        right = w - 10
        if self._badge:
            bf = theme.font(theme.FS_CAPTION, bold=True, num=True, tnum=True)
            bw = QFontMetrics(bf).horizontalAdvance(self._badge) + 12
            br = QRectF(right - bw, (h - 18) / 2, bw, 18)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.color("accent_soft" if on else "neutral_soft"))
            p.drawRoundedRect(br, 9, 9)
            p.setFont(bf)
            p.setPen(theme.color("accent_text" if on else "text_secondary"))
            p.drawText(br, Qt.AlignmentFlag.AlignCenter, self._badge)
            right = int(br.left()) - 6
        p.setFont(theme.font(theme.FS_BODY, bold=on))
        p.setPen(theme.color("text" if on else "text_secondary"))
        p.drawText(QRectF(40, 0, max(0, right - 40), h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self.text())
        p.end()


class Sidebar(QFrame):
    """The sidebar frame. ``pageRequested(page_id)`` on a click; ``themeToggled(dark)``."""

    pageRequested = pyqtSignal(str)
    themeToggled = pyqtSignal(bool)

    def __init__(self, dark: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("frameRole", "sidebar")
        self.setObjectName("Sidebar")
        self.setFixedWidth(theme.SIDEBAR_W)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.SP[3], theme.SP[5], theme.SP[3], theme.SP[3])
        lay.setSpacing(2)

        brand = QWidget(self)
        b = QHBoxLayout(brand)
        b.setContentsMargins(theme.SP[2], 0, 0, 0)
        b.setSpacing(theme.SP[2] + 2)
        logo = icon_label("logo", "accent_fill", 30)
        b.addWidget(logo)
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(label("AutoPress", "brand"))
        names.addWidget(label(tr("序號自動輸入", "Code auto-entry"), "muted"))
        b.addLayout(names)
        b.addStretch(1)
        lay.addWidget(brand)
        lay.addSpacing(theme.SP[5])

        cap = label(tr("工作區", "Workspace"), "caption")
        cap.setContentsMargins(theme.SP[3], 0, 0, theme.SP[1])
        lay.addWidget(cap)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self.buttons: dict[str, NavButton] = {}
        for page_id, icon_name, text in NAV_MAIN:
            lay.addWidget(self._add(page_id, icon_name, str(text)))
        lay.addStretch(1)
        for page_id, icon_name, text in NAV_BOTTOM:
            lay.addWidget(self._add(page_id, icon_name, str(text)))
        lay.addSpacing(theme.SP[2])
        lay.addWidget(Divider(parent=self))
        lay.addSpacing(theme.SP[2])

        row = QHBoxLayout()
        row.setContentsMargins(theme.SP[3], 0, theme.SP[1], 0)
        row.setSpacing(theme.SP[2])
        self.theme_icon = icon_label("moon", "text_secondary", 16)
        row.addWidget(self.theme_icon)
        self.theme_label = label(tr("深色模式", "Dark mode"), "secondary")
        row.addWidget(self.theme_label)
        row.addStretch(1)
        self.theme_switch = Switch(dark, self)
        self.theme_switch.setAccessibleName(tr("深色模式", "Dark mode"))
        self.theme_switch.setToolTip(tr("切換深色／淺色外觀", "Switch between dark and light"))
        self.theme_switch.toggled.connect(self.themeToggled.emit)
        row.addWidget(self.theme_switch)
        lay.addLayout(row)
        lay.addSpacing(theme.SP[2])
        self.version_label = label(tr(f"v{__version__} · 離線運作，不連網", f"v{__version__} · offline, no network"),
                                   "muted")
        self.version_label.setContentsMargins(theme.SP[3], 0, 0, 0)
        lay.addWidget(self.version_label)

    def _add(self, page_id: str, icon_name: str, text: str) -> NavButton:
        btn = NavButton(page_id, icon_name, text, self)
        btn.clicked.connect(lambda _checked=False, pid=page_id: self.pageRequested.emit(pid))
        self._group.addButton(btn)
        self.buttons[page_id] = btn
        return btn

    def set_current(self, page_id: str) -> None:
        btn = self.buttons.get(page_id)
        if btn is not None and not btn.isChecked():
            btn.setChecked(True)

    def set_badge(self, page_id: str, text: str, tooltip: str = "") -> None:
        btn = self.buttons.get(page_id)
        if btn is not None:
            btn.setBadge(text, tooltip)

    def set_dark(self, dark: bool) -> None:
        """Reflect the applied theme without emitting themeToggled."""
        self.theme_switch.blockSignals(True)
        self.theme_switch.setChecked(dark)
        self.theme_switch.blockSignals(False)
        self.theme_switch.update()
