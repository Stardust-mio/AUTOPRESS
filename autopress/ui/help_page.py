# OWNED BY G5
"""Help page (SPEC section 6.4.6): safety and terms of service (only trusted shared profiles;
chat-command redemption is public), how it works, troubleshooting (administrator games incl.
no drag-and-drop when elevated, fullscreen capture, DPI, Chinese IME, SmartScreen and antivirus
false positives), hotkeys, failsafe (which corner counts; games that lock the cursor need F9),
privacy.

The texts live in help_content.py (zh-TW + English). The failsafe section draws the user's own
monitor layout and marks the outer top-left corner(s) that count (``models.failsafe_corners``).
The table of contents scrolls to a section and keeps the entry of the section in view checked.
"""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QEvent, QObject, QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import QPainter, QPaintEvent, QPen
from PyQt6.QtWidgets import QButtonGroup, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from ..context import AppContext
from ..i18n import tr
from ..models import Rect, failsafe_corners
from . import theme, widgets
from .help_content import SECTIONS
from .shell_common import failsafe_corner_text, monitor_rects
from .widgets import Card, Keycap, icon_label, label


class FailsafeMap(QWidget):
    """The monitor layout, scaled to fit, with the corner(s) that stop a run."""

    def __init__(self, rects: list[Rect] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rects: list[Rect] = []
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.set_rects(rects if rects is not None else monitor_rects())

    def set_rects(self, rects: list[Rect]) -> None:
        self._rects = [r for r in rects if r[2] > 0 and r[3] > 0] or [(0, 0, 1920, 1080)]
        self.corners = failsafe_corners(self._rects)
        self.setAccessibleName(failsafe_corner_text(self._rects))
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(420, 160)

    def paintEvent(self, _event: QPaintEvent | None) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        x0 = min(r[0] for r in self._rects)
        y0 = min(r[1] for r in self._rects)
        x1 = max(r[0] + r[2] for r in self._rects)
        y1 = max(r[1] + r[3] for r in self._rects)
        pad = 18.0
        avail_w, avail_h = max(10.0, self.width() - 2 * pad), max(10.0, self.height() - 2 * pad)
        k = min(avail_w / max(1, x1 - x0), avail_h / max(1, y1 - y0))
        ox = (self.width() - (x1 - x0) * k) / 2
        oy = (self.height() - (y1 - y0) * k) / 2

        def map_pt(x: float, y: float) -> QPointF:
            return QPointF(ox + (x - x0) * k, oy + (y - y0) * k)

        p.setFont(theme.font(theme.FS_SMALL))
        for n, (x, y, w, h) in enumerate(self._rects):
            tl = map_pt(x, y)
            r = QRectF(tl.x() + 2, tl.y() + 2, w * k - 4, h * k - 4)
            p.setPen(QPen(theme.color("border_strong"), 1.2))
            p.setBrush(theme.color("surface_raised"))
            p.drawRoundedRect(r, 6, 6)
            p.setPen(theme.color("text_secondary"))
            name = tr("主螢幕", "Primary") if (x, y) == (0, 0) else tr(f"螢幕 {n + 1}", f"Screen {n + 1}")
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, name)
        for cx, cy in self.corners:
            c = map_pt(cx, cy) + QPointF(3, 3)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.color("error_soft"))
            p.drawEllipse(c, 11, 11)
            p.setBrush(theme.color("error"))
            p.drawEllipse(c, 4.5, 4.5)
            p.setPen(theme.color("error_text"))
            p.setFont(theme.font(theme.FS_CAPTION, bold=True))
            p.drawText(QRectF(c.x() + 12, c.y() - 2, 140, 18),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, tr("緊急停止", "Emergency stop"))
        p.end()


class HelpPage(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.sections: dict[str, QWidget] = {}
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        toc = QWidget(self)
        toc.setFixedWidth(196)
        t_lay = QVBoxLayout(toc)
        t_lay.setContentsMargins(theme.PAGE_MARGINS[0], theme.PAGE_MARGINS[1] + 56, theme.SP[2], theme.PAGE_MARGINS[3])
        t_lay.setSpacing(2)
        t_lay.addWidget(label(tr("本頁內容", "On this page"), "caption"))
        # the entry of the section in view is checked (the app style gives checked buttons the nav_active fill)
        self.toc_buttons: dict[str, Any] = {}
        self.toc_group = QButtonGroup(self)
        self.toc_group.setExclusive(True)
        self._toc_pin: tuple[str, int] | None = None  # a clicked entry and the scroll position it led to
        for sec in SECTIONS:
            b = widgets.tool_button(sec["icon"], str(sec.get("toc", sec["title"])), "ghost")
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            b.setCheckable(True)
            b.setProperty("toc", True)  # style hook for the current-section look
            b.clicked.connect(lambda _c=False, sid=sec["id"]: self.scroll_to(sid))
            self.toc_group.addButton(b)
            t_lay.addWidget(b)
            self.toc_buttons[sec["id"]] = b
        if self.toc_buttons:
            next(iter(self.toc_buttons.values())).setChecked(True)
        t_lay.addStretch(1)
        outer.addWidget(toc)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("HelpBody")
        col = QVBoxLayout(body)
        col.setContentsMargins(theme.SP[3], theme.PAGE_MARGINS[1], theme.PAGE_MARGINS[2], theme.PAGE_MARGINS[3])
        col.setSpacing(theme.SP[4])
        col.addWidget(widgets.section_header(tr("說明", "Help"),
                                             tr("安全守則、疑難排解與緊急停止。", "Safety rules, troubleshooting and the emergency stop.")))
        for sec in SECTIONS:
            card = self._section(sec)
            self.sections[sec["id"]] = card
            col.addWidget(card)
        col.addStretch(1)
        self.scroll.setWidget(body)
        outer.addWidget(self.scroll, 1)
        # the table of contents follows the body: scrolling moves it, layout changes resize it (an event
        # filter, so building the page wraps none of the scroll area's own children)
        self._body = body
        body.installEventFilter(self)
        self.scroll.installEventFilter(self)
        ctx.signals.settings_changed.connect(self._update_hotkeys)
        self._update_hotkeys()

    # -- building -------------------------------------------------------------------------------
    def _section(self, sec: dict[str, Any]) -> Card:
        card = Card(True, (theme.SP[5], theme.SP[4], theme.SP[5], theme.SP[4]), theme.SP[3])
        card.setObjectName(f"help_{sec['id']}")
        head = QHBoxLayout()
        head.setSpacing(theme.SP[2])
        head.addWidget(icon_label(sec["icon"], "accent_text" if sec["icon"] != "logo" else "accent_fill", 20))
        head.addWidget(label(str(sec["title"]), "title"))
        head.addStretch(1)
        card.layout().addLayout(head)
        for block in sec["blocks"]:
            self._add_block(card.layout(), block)
        return card

    def _paragraph(self, text: str, role: str = "secondary") -> QLabel:
        lb = label(widgets.keep_quoted(text), role)  # a quoted button name never splits across lines
        lb.setWordWrap(True)
        lb.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return lb

    def _add_block(self, lay: QVBoxLayout, block: tuple[Any, ...]) -> None:
        kind = block[0]
        if kind == "p":
            lay.addWidget(self._paragraph(str(block[1])))
        elif kind == "list":
            for item in block[1]:
                row = QHBoxLayout()
                row.setSpacing(theme.SP[2])
                dot = label("•", "secondary")
                dot.setFixedWidth(10)
                row.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)
                row.addWidget(self._paragraph(str(item)), 1)
                lay.addLayout(row)
        elif kind == "item":
            box = QWidget()
            b = QVBoxLayout(box)
            b.setContentsMargins(0, theme.SP[1], 0, theme.SP[1])
            b.setSpacing(theme.SP[1] + 2)
            b.addWidget(label(str(block[1]), "strong"))
            for sub in block[2]:
                self._add_block(b, sub)
            lay.addWidget(widgets.Divider())
            lay.addWidget(box)
        elif kind == "hotkeys":
            row = QHBoxLayout()
            row.setSpacing(theme.SP[2])
            self.pause_key = Keycap("F8")
            self.stop_key = Keycap("F9")
            row.addWidget(self.pause_key)
            row.addWidget(label(tr("暫停／繼續", "Pause / resume"), "body"))
            row.addSpacing(theme.SP[4])
            row.addWidget(self.stop_key)
            row.addWidget(label(tr("停止（倒數中按下會取消開始）", "Stop (during the countdown: cancel)"), "body"))
            row.addStretch(1)
            lay.addLayout(row)
        elif kind == "failsafe":
            self.failsafe_text = self._paragraph(failsafe_corner_text(), "body")
            lay.addWidget(self.failsafe_text)
            self.failsafe_map = FailsafeMap()
            lay.addWidget(self.failsafe_map)

    # -- behaviour --------------------------------------------------------------------------------
    def _update_hotkeys(self, *_args: object) -> None:
        hk = self.ctx.settings.hotkeys
        if hasattr(self, "pause_key"):
            self.pause_key.setText(hk.pause_resume)
            self.stop_key.setText(hk.stop)
        if hasattr(self, "failsafe_text"):
            text = failsafe_corner_text()
            if not self.ctx.settings.failsafe_enabled:
                text += tr("（目前在「設定」裡關閉了）", " (currently turned off in Settings)")
            self.failsafe_text.setText(text)

    def scroll_to(self, section_id: str) -> None:
        w = self.sections.get(section_id)
        if w is not None:
            self.scroll.verticalScrollBar().setValue(max(0, w.y() - theme.SP[3]))
            if self.isVisible():  # keep the clicked entry checked even if its section cannot reach the top
                self._toc_pin = (section_id, self._scroll_state()[0])
                self._sync_toc()

    def _scroll_state(self) -> tuple[int, int, int]:
        """(position, maximum, viewport height) of the scrolled help text, read from the body: the
        scroll area moves it to -position, and its height beyond the viewport is the maximum."""
        view_h = self.scroll.maximumViewportSize().height()
        return max(0, -self._body.y()), max(0, self._body.height() - view_h), view_h

    def current_section(self) -> str:
        """The id of the section in view: the last one whose top is above a reading line. The line runs
        from just below the top of the viewport (page at the top) down to the end of the page (page
        scrolled to the end), so short sections at the end, which never reach the top, still get a turn."""
        value, maximum, view_h = self._scroll_state()
        reach = float(theme.SP[3] + 1)  # scroll_to leaves SP[3] above a section
        if maximum > 0:
            reach += value / maximum * max(0.0, view_h - reach)
        current = next(iter(self.sections), "")
        for sid, w in self.sections.items():
            if w.y() <= value + reach:
                current = sid
        return current

    def _sync_toc(self) -> None:
        """Check the table-of-contents entry of the section in view (layout positions are only valid
        while the page is shown)."""
        if not self.isVisible():
            return
        value = self._scroll_state()[0]
        if self._toc_pin is not None and self._toc_pin[1] != value:
            self._toc_pin = None  # scrolled since the click
        sid = self._toc_pin[0] if self._toc_pin is not None else self.current_section()
        b = self.toc_buttons.get(sid)
        if b is not None and not b.isChecked():
            b.setChecked(True)

    def eventFilter(self, obj: QObject | None, event: QEvent | None) -> bool:
        if (event is not None and event.type() in (QEvent.Type.Move, QEvent.Type.Resize)
                and obj in (self._body, self.scroll)):
            self._sync_toc()  # scrolled (the body moved) or the layout / window size changed
        return super().eventFilter(obj, event)

    def showEvent(self, event: object) -> None:  # refresh the monitor layout each time the page shows
        super().showEvent(event)  # type: ignore[arg-type]
        if hasattr(self, "failsafe_map"):
            self.failsafe_map.set_rects(monitor_rects())
            self._update_hotkeys()
        self._sync_toc()

