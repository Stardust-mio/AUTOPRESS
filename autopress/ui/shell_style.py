# OWNED BY G5
"""Private helper of ui.theme: the application QStyle (Fusion behind a QProxyStyle).

Why a proxy style next to the QSS (ux.md section 6, prototype lessons):
* Check boxes and radio buttons: the QSS leaves ``::indicator`` alone, so QStyleSheetStyle asks
  the base style to draw it - this style paints the rounded 16 px box / circle with the theme
  tokens (the same look as the check column of the Codes table) and a focus ring.
* Spin boxes: QStyleSheetStyle places the inner line edit at the frame's left edge (the QSS
  padding is ignored - measured on Qt 6.12), so ``polish()`` sets the text margin of every
  spin box; it also applies the SPEC 6.5 / pyqt-windows.md rules app-wide:
  ``setKeyboardTracking(False)`` and select-all when the field gets the focus.
Colours are read at paint time through ``theme.color``, so a theme switch needs no restyle.
"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QPainter, QPen
from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QLineEdit,
    QProxyStyle,
    QRadioButton,
    QStyle,
    QStyleFactory,
    QStyleOption,
    QWidget,
)

__all__ = ["SPIN_TEXT_MARGIN", "AppStyle"]

SPIN_TEXT_MARGIN = 9  # + 1 px border = the 10 px text inset of line edits and combos
_INDICATOR = 16


class _SelectAllOnFocus(QObject):
    """Event filter for spin boxes: select the whole value when the field gets the focus, so
    typing replaces it (pyqt-windows.md: clicking into '00' and typing inserts). The spin box
    itself receives the focus (its line edit's focus proxy is the spin box); the deferred
    selectAll runs after the mouse press that gave the focus."""

    def eventFilter(self, obj: QObject | None, event: QEvent | None) -> bool:
        if event is not None and event.type() == QEvent.Type.FocusIn and isinstance(obj, QAbstractSpinBox):
            QTimer.singleShot(0, obj.selectAll)
        return False


class AppStyle(QProxyStyle):
    """Fusion + themed check / radio indicators + spin-box polish (see module docstring)."""

    def __init__(self) -> None:
        super().__init__(QStyleFactory.create("Fusion"))
        self.setObjectName("AutoPressStyle")
        self._select_all = _SelectAllOnFocus(self)

    # -- polish -------------------------------------------------------------------------
    def polish(self, arg):  # type: ignore[no-untyped-def]  # overloads: QWidget, QApplication, QPalette
        if isinstance(arg, QAbstractSpinBox):
            arg.setKeyboardTracking(False)
            arg.installEventFilter(self._select_all)
            edit = arg.findChild(QLineEdit)
            if edit is not None:
                edit.setTextMargins(SPIN_TEXT_MARGIN, 0, 0, 0)
        return super().polish(arg)

    # -- metrics ------------------------------------------------------------------------
    def pixelMetric(self, metric: QStyle.PixelMetric, option: QStyleOption | None = None,
                    widget: QWidget | None = None) -> int:
        if metric in (QStyle.PixelMetric.PM_IndicatorWidth, QStyle.PixelMetric.PM_IndicatorHeight,
                      QStyle.PixelMetric.PM_ExclusiveIndicatorWidth, QStyle.PixelMetric.PM_ExclusiveIndicatorHeight):
            return _INDICATOR
        if metric == QStyle.PixelMetric.PM_CheckBoxLabelSpacing:
            return 8
        return super().pixelMetric(metric, option, widget)

    def styleHint(self, hint: QStyle.StyleHint, option: QStyleOption | None = None, widget: QWidget | None = None,
                  returnData=None) -> int:  # type: ignore[no-untyped-def]
        if hint == QStyle.StyleHint.SH_DialogButtonBox_ButtonsHaveIcons:
            return 0
        return super().styleHint(hint, option, widget, returnData)

    # -- primitives ---------------------------------------------------------------------
    def drawPrimitive(self, element: QStyle.PrimitiveElement, option: QStyleOption | None,
                      painter: QPainter | None, widget: QWidget | None = None) -> None:
        if option is None or painter is None:
            return
        pe = QStyle.PrimitiveElement
        if element in (pe.PE_IndicatorCheckBox, pe.PE_IndicatorItemViewItemCheck):
            self._draw_check(option, painter)
            return
        if element == pe.PE_IndicatorRadioButton:
            self._draw_radio(option, painter)
            return
        if element == pe.PE_FrameFocusRect and isinstance(widget, (QCheckBox, QRadioButton)):
            return  # the indicator draws its own focus ring
        super().drawPrimitive(element, option, painter, widget)

    @staticmethod
    def _box(option: QStyleOption) -> QRectF:
        r = QRectF(option.rect)
        side = min(r.width(), r.height(), float(_INDICATOR))
        return QRectF(r.center().x() - side / 2, r.center().y() - side / 2, side, side)

    def _draw_check(self, option: QStyleOption, p: QPainter) -> None:
        from . import icons, theme

        st = QStyle.StateFlag
        state = option.state
        enabled = bool(state & st.State_Enabled)
        on = bool(state & st.State_On)
        partial = bool(state & st.State_NoChange)
        box = self._box(option).adjusted(0.5, 0.5, -0.5, -0.5)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if state & st.State_HasFocus:
            p.setPen(QPen(theme.color("accent"), 1.6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(box.adjusted(-2.5, -2.5, 2.5, 2.5), 6, 6)
        if on or partial:
            fill = theme.color("accent_fill" if enabled else "border_strong")
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fill)
            p.drawRoundedRect(box, 4, 4)
            mark = theme.color("on_accent" if enabled else "text_disabled")
            if partial and not on:
                p.setPen(QPen(mark, 2.0, cap=Qt.PenCapStyle.RoundCap))
                c = box.center()
                p.drawLine(QPointF(c.x() - 4, c.y()), QPointF(c.x() + 4, c.y()))
            else:
                size = int(box.width()) - 2
                pm = icons.icon_pixmap("check", mark.name(), size, 2.6)
                p.drawPixmap(QPointF(box.left() + 1, box.top() + 1), pm)
        else:
            hover = bool(state & st.State_MouseOver) and enabled
            p.setPen(QPen(theme.color("text_muted" if hover else "border_strong"), 1.2))
            p.setBrush(theme.color("surface_raised" if enabled else "surface_inset"))
            p.drawRoundedRect(box, 4, 4)
        p.restore()

    def _draw_radio(self, option: QStyleOption, p: QPainter) -> None:
        from . import theme

        st = QStyle.StateFlag
        state = option.state
        enabled = bool(state & st.State_Enabled)
        on = bool(state & st.State_On)
        box = self._box(option).adjusted(0.5, 0.5, -0.5, -0.5)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if state & st.State_HasFocus:
            p.setPen(QPen(theme.color("accent"), 1.6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(box.adjusted(-2.5, -2.5, 2.5, 2.5))
        if on:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.color("accent_fill" if enabled else "border_strong"))
            p.drawEllipse(box)
            p.setBrush(theme.color("on_accent" if enabled else "text_disabled"))
            c = box.center()
            p.drawEllipse(c, 3.2, 3.2)
        else:
            hover = bool(state & st.State_MouseOver) and enabled
            p.setPen(QPen(theme.color("text_muted" if hover else "border_strong"), 1.2))
            p.setBrush(theme.color("surface_raised" if enabled else "surface_inset"))
            p.drawEllipse(box)
        p.restore()
