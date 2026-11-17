# OWNED BY G7
"""Result keyword editor: one row per ResultClass in KeywordConfig.order (label, a
comma-separated field, move up/down to change the order), fuzzy switch, "還原預設" (models.
default_keyword_groups), overlap warnings (KeywordConfig.overlaps)."""

from __future__ import annotations

import re

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from ..i18n import tr
from ..models import DEFAULT_CLASS_ORDER, KeywordConfig, ResultClass, default_keyword_groups
from ..textutil import clean_text, squash
from . import widgets as w

_SPLIT = re.compile(r"[,，、;；\n]+")


def parse_keywords(text: str) -> list[str]:
    """"兌換成功, 領取成功，已發送" -> ["兌換成功", "領取成功", "已發送"] (unique, order kept)."""
    out: list[str] = []
    seen: set[str] = set()
    for part in _SPLIT.split(clean_text(text or "")):
        kw = part.strip()
        key = squash(kw)
        if kw and key and key not in seen:
            seen.add(key)
            out.append(kw)
    return out


def format_keywords(keywords: list[str]) -> str:
    return ", ".join(keywords)


class KeywordsEditor(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._order: list[ResultClass] = list(DEFAULT_CLASS_ORDER)
        self._fields: dict[ResultClass, QLineEdit] = {}
        self._rows: dict[ResultClass, QWidget] = {}
        self._loading = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        hint = w.label(tr("每一類可填多個關鍵字，用逗號分隔；比對時忽略大小寫、空白與標點，由上往下，"
                          "第一個符合的類別勝出。「成功」和其他類別同時出現時會視為無法判讀並詢問你。",
                          "Several keywords per class, separated by commas. Matching ignores case, spaces "
                          "and punctuation; classes are tested top to bottom and the first hit wins. "
                          "'Success' together with another class counts as unknown and you are asked."), "muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self._rows_box = QVBoxLayout()
        self._rows_box.setSpacing(6)
        lay.addLayout(self._rows_box)
        for cls in DEFAULT_CLASS_ORDER:
            self._make_row(cls)

        bottom = QHBoxLayout()
        self.fuzzy = w.Switch(True)
        self.fuzzy.setAccessibleName(tr("容許辨識誤差", "Tolerate OCR errors"))
        self.fuzzy.toggled.connect(self._emit)
        bottom.addWidget(self.fuzzy)
        fuzzy_lb = w.label(tr("容許辨識誤差（9 個字元以上的英文關鍵字可差一個字）",
                              "Tolerate OCR errors (one character for English keywords of 9+ characters)"),
                           "secondary")
        fuzzy_lb.setWordWrap(True)  # wraps in a narrow editor instead of widening the Profiles page
        self.fuzzy_label = fuzzy_lb
        bottom.addWidget(fuzzy_lb, 1)
        self.reset_btn = w.push_button(tr("還原預設", "Restore defaults"), "ghost", "refresh")
        self.reset_btn.clicked.connect(self.restore_defaults)
        bottom.addWidget(self.reset_btn)
        lay.addLayout(bottom)

        self.warning = w.label("", "error")
        self.warning.setWordWrap(True)
        self.warning.hide()
        lay.addWidget(self.warning)
        self.set_config(KeywordConfig())

    # -- rows -----------------------------------------------------------------------------
    def _make_row(self, cls: ResultClass) -> None:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        name = w.label(cls.label(), "body")
        name.setFixedWidth(170)
        name.setWordWrap(True)
        name.setToolTip(cls.label())
        h.addWidget(name)
        field = QLineEdit()
        field.setAccessibleName(cls.label())
        field.setPlaceholderText(tr("（沒有關鍵字）", "(no keywords)"))
        field.textChanged.connect(self._emit)
        h.addWidget(field, 1)
        up = w.icon_button("arrow_up", tr(f"上移「{cls.label()}」", f"Move '{cls.label()}' up"))
        up.clicked.connect(lambda _c=False, c=cls: self.move_class(c, -1))
        down = w.icon_button("arrow_down", tr(f"下移「{cls.label()}」", f"Move '{cls.label()}' down"))
        down.clicked.connect(lambda _c=False, c=cls: self.move_class(c, 1))
        h.addWidget(up)
        h.addWidget(down)
        self._fields[cls] = field
        self._rows[cls] = row

    def _relayout(self) -> None:
        for cls in DEFAULT_CLASS_ORDER:
            self._rows_box.removeWidget(self._rows[cls])
        for cls in self._order:
            self._rows_box.addWidget(self._rows[cls])

    def order(self) -> list[ResultClass]:
        return list(self._order)

    def field(self, cls: ResultClass) -> QLineEdit:
        """The keyword field of one class (tests)."""
        return self._fields[cls]

    def move_class(self, cls: ResultClass, delta: int) -> None:
        i = self._order.index(cls)
        j = i + delta
        if not 0 <= j < len(self._order):
            return
        self._order[i], self._order[j] = self._order[j], self._order[i]
        self._relayout()
        self._emit()

    # -- API ------------------------------------------------------------------------------
    def set_config(self, config: KeywordConfig) -> None:
        self._loading = True
        try:
            order = [c for c in config.order if c in self._fields]
            order += [c for c in DEFAULT_CLASS_ORDER if c not in order]
            self._order = order
            for cls, field in self._fields.items():
                field.setText(format_keywords(list(config.groups.get(cls, []))))
                field.setCursorPosition(0)  # show the first keywords, not the end of the list
            self.fuzzy.setChecked(bool(config.fuzzy))
            self._relayout()
        finally:
            self._loading = False
        self._update_warning()

    def config(self) -> KeywordConfig:
        groups = {cls: parse_keywords(self._fields[cls].text()) for cls in DEFAULT_CLASS_ORDER}
        return KeywordConfig(groups=groups, order=list(self._order), fuzzy=self.fuzzy.isChecked())

    def add_keyword(self, result: ResultClass, keyword: str) -> None:
        """Used by the Run page's "加入關鍵字…" action."""
        result = ResultClass(result)
        kw = clean_text(keyword or "").strip()
        if result is ResultClass.UNKNOWN or result not in self._fields or not squash(kw):
            return
        current = parse_keywords(self._fields[result].text())
        if squash(kw) in {squash(k) for k in current}:
            return
        self._fields[result].setText(format_keywords(current + [kw]))

    def restore_defaults(self) -> None:
        self.set_config(KeywordConfig(groups=default_keyword_groups(), order=list(DEFAULT_CLASS_ORDER),
                                      fuzzy=True))
        self.changed.emit()

    # -- feedback -------------------------------------------------------------------------
    def _emit(self, *_args: object) -> None:
        if self._loading:
            return
        self._update_warning()
        self.changed.emit()

    def _update_warning(self) -> None:
        overlaps = self.config().overlaps()
        if not overlaps:
            self.warning.hide()
            self.warning.setText("")
            return
        lines = [tr(f"關鍵字「{kw}」同時出現在「{a.label()}」與「{b.label()}」，請只留在一類。",
                    f"Keyword '{kw}' is in both '{a.label()}' and '{b.label()}'; keep it in one class.")
                 for kw, a, b in overlaps[:4]]
        self.warning.setText("\n".join(lines))
        self.warning.show()
