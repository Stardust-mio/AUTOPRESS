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
* Disabled icons: ``icons.icon`` adds a ``text_disabled`` pixmap for buttons, but Qt generates
  the disabled look itself wherever a QIcon has no Disabled entry - every disabled QLabel
  (Qt 6.12 keeps a label pixmap as a one-entry QIcon), and any QIcon built from a bare pixmap.
  Qt's formula lightens towards the window colour, so on the dark theme a disabled icon came
  out almost as bright as an enabled one (UI review U26). ``generatedIconPixmap`` therefore
  recolours single-colour icons to ``text_disabled`` (the disabled text colour); pictures with
  several colours (program icons in the window picker) keep Qt's version.
Colours are read at paint time through ``theme.color``, so a theme switch needs no restyle.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap
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

__all__ = ["SPIN_TEXT_MARGIN", "AppStyle", "tint_monochrome"]

log = logging.getLogger(__name__)

SPIN_TEXT_MARGIN = 9  # + 1 px border = the 10 px text inset of line edits and combos
_INDICATOR = 16
_TINT_MAX_PIXELS = 128 * 128  # icon-sized only (64 px at 200 %); bigger pictures keep Qt's version
_TINT_MIN_ALPHA = 96  # pixels at least this opaque decide whether an icon has one colour
_TINT_SPREAD = 12  # largest per-channel difference still "one colour" (anti-aliasing rounding)


def tint_monochrome(pixmap: QPixmap, color: QColor) -> QPixmap | None:
    """``pixmap`` recoloured to ``color`` through its own alpha (same size and device pixel
    ratio), or None when it is not a single-colour icon: several colours, nothing opaque, or
    larger than ``_TINT_MAX_PIXELS``."""
    w, h = pixmap.width(), pixmap.height()
    if pixmap.isNull() or w * h > _TINT_MAX_PIXELS:
        return None
    img = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    ptr = img.constBits()
    if ptr is None:
        return None
    ptr.setsize(img.sizeInBytes())
    data = bytes(ptr)  # ARGB32 rows are 4 * width bytes; little-endian byte order B, G, R, A
    alpha = data[3::4]
    opaque = [i for i, a in enumerate(alpha) if a >= _TINT_MIN_ALPHA]
    if not opaque:
        return None
    for channel in (data[0::4], data[1::4], data[2::4]):
        values = [channel[i] for i in opaque]
        if max(values) - min(values) > _TINT_SPREAD:
            return None
    img.setDevicePixelRatio(1.0)
    out = QImage(img.size(), QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.drawImage(0, 0, img)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    p.fillRect(out.rect(), QColor(color))
    p.end()
    result = QPixmap.fromImage(out)
    result.setDevicePixelRatio(pixmap.devicePixelRatio())
    return result


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
    """Fusion + themed check / radio indicators + spin-box polish + disabled icon colour (see the
    module docstring)."""

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

    # -- icons --------------------------------------------------------------------------
    def generatedIconPixmap(self, iconMode: QIcon.Mode, pixmap: QPixmap,
                            opt: QStyleOption | None) -> QPixmap:
        """Disabled single-colour icons in the theme's ``text_disabled`` (module docstring);
        everything else as Fusion generates it. Qt caches the result per pixmap and palette."""
        if iconMode == QIcon.Mode.Disabled and pixmap is not None:
            try:
                from . import theme

                tinted = tint_monochrome(pixmap, theme.color("text_disabled"))
                if tinted is not None:
                    return tinted
            except Exception:  # noqa: BLE001 - a paint-time helper must never take the app down
                log.debug("tinting a disabled icon failed", exc_info=True)
        return super().generatedIconPixmap(iconMode, pixmap, opt)

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
