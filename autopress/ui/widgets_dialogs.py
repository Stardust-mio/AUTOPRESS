# OWNED BY G5
"""Themed modal dialogs behind ``widgets.confirm`` / ``widgets.message``.

Enter = the default button, Esc = cancel (SPEC 6.5). For a ``danger`` question the default
button is Cancel, so an accidental Enter never deletes anything. On the headless ``offscreen``
platform (tests) nobody can see or answer a modal dialog: ``confirm`` returns True and
``message`` returns at once (the same answers as tests/ui_fallback.py; tests that need "no"
monkeypatch ``widgets.confirm``).
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QPainter, QPaintEvent
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout, QWidget

from ..i18n import tr
from . import icons, theme
from .shell_common import is_headless
from .widgets import label, push_button

log = logging.getLogger(__name__)

_KIND_ICON = {"info": ("info", "info"), "success": ("check", "success"), "warning": ("alert", "warning"),
              "error": ("alert", "error"), "question": ("help", "accent"), "danger": ("alert", "error")}


class _IconBadge(QWidget):
    """36 px soft-tone circle with the kind's icon (colours read at paint time)."""

    def __init__(self, kind: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._name, self._tone = _KIND_ICON.get(kind, _KIND_ICON["info"])
        self.setFixedSize(36, 36)

    def paintEvent(self, _event: QPaintEvent | None) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        _base, soft, _text = theme.tone_colors(self._tone)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(soft)
        p.drawEllipse(QRectF(self.rect()))
        p.drawPixmap(QPointF(8, 8), icons.icon_pixmap(self._name, self._tone, 20))
        p.end()


class MessageDialog(QDialog):
    """Title, text and buttons; ``danger`` makes the OK button red and Cancel the default."""

    def __init__(self, parent: QWidget | None, title: str, text: str, kind: str = "info",
                 ok_text: str | None = None, cancel_text: str | None = None, danger: bool = False,
                 question: bool = False) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(theme.SP[6], theme.SP[5], theme.SP[6], theme.SP[5])
        outer.setSpacing(theme.SP[5])
        row = QHBoxLayout()
        row.setSpacing(theme.SP[4])
        badge = _IconBadge("danger" if danger else ("question" if question else kind), self)
        row.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(theme.SP[2])
        self.title_label = label(title, "title")
        self.title_label.setWordWrap(True)
        col.addWidget(self.title_label)
        self.text_label = label(text, "secondary")
        self.text_label.setWordWrap(True)
        self.text_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.text_label.setMinimumWidth(320)
        self.text_label.setMaximumWidth(460)
        col.addWidget(self.text_label)
        row.addLayout(col, 1)
        outer.addLayout(row)
        buttons = QHBoxLayout()
        buttons.setSpacing(theme.SP[2])
        buttons.addStretch(1)
        self.cancel_button = None
        if question:
            self.cancel_button = push_button(cancel_text or tr("取消", "Cancel"), "secondary")
            self.cancel_button.clicked.connect(self.reject)
            buttons.addWidget(self.cancel_button)
        self.ok_button = push_button(ok_text or (tr("確定", "OK")), "danger" if danger else "primary")
        self.ok_button.clicked.connect(self.accept)
        buttons.addWidget(self.ok_button)
        outer.addLayout(buttons)
        if danger and self.cancel_button is not None:
            self.ok_button.setAutoDefault(False)
            self.cancel_button.setDefault(True)
            self.cancel_button.setFocus()
        else:
            self.ok_button.setDefault(True)
            self.ok_button.setFocus()


def _run(dialog: QDialog) -> int:
    return dialog.exec()


def confirm(parent: QWidget | None, title: str, text: str, ok_text: str | None = None,
            cancel_text: str | None = None, danger: bool = False) -> bool:
    if is_headless():
        log.info("confirm (headless, answered yes): %s", title)
        return True
    dlg = MessageDialog(parent, title, text, "question", ok_text, cancel_text, danger, question=True)
    try:
        return _run(dlg) == QDialog.DialogCode.Accepted
    finally:
        dlg.deleteLater()


def message(parent: QWidget | None, title: str, text: str, kind: str = "info") -> None:
    if is_headless():
        log.info("message (headless, not shown): %s - %s", title, text)
        return
    dlg = MessageDialog(parent, title, text, kind if kind in _KIND_ICON else "info")
    try:
        _run(dlg)
    finally:
        dlg.deleteLater()
