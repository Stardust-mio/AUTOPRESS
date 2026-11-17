# OWNED BY G6
"""Candidate list shared by the PasteDialog and the OcrReviewDialog (private to G6).

* ``CandidateEntry``: one extracted candidate plus the dialog state (checked, reviewed = the
  「確認無誤」 tick, edited) and the checks against the queue and history of the import target
  (重複 / 已兌換過 badges).
* ``CandidateModel`` + delegates: check, code (mono with flagged / look-alike marks, raw text
  next to it when normalisation changed it; editable in the OCR dialog), confidence, source-line
  crop, badges, 確認 (a 「確認無誤」 tick per flagged candidate: the same words as the Codes page
  action that does the same for queued codes, and the 確認 of 需確認).
* ``ImportDialogBase``: 格式 combo, target line, summary 「將加入 {a} 筆，略過 {d} 筆重複、{h} 筆已兌換過」
  (a skip part is left out when its count is 0), 取消 / 加入 buttons, and the public
  ``candidates()`` / ``code_format()`` of both dialogs.

Duplicates and history-skipped candidates cannot be unticked: they stay in ``candidates()`` so
``CodeQueue.add_candidates`` counts them (the toast and the page header report the same numbers
as the dialog's summary).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QFontMetrics, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QTableView,
    QWidget,
)

from ..context import AppContext
from ..i18n import T, tr
from ..models import CodeCandidate, CodeFormat, CodeSource, CodeStatus, clone
from . import theme, widgets
from .codes_common import (
    default_format_choice,
    format_choices,
    game_name,
    import_target,
    resolve_format,
)
from .codes_model import (
    ROLE_CONFIDENCE,
    ROLE_FLAGGED,
    ROLE_ITEM,
    ROLE_LOOKALIKES,
    CellDelegate,
    CheckDelegate,
    CodeDelegate,
    ConfidenceDelegate,
)
from .codes_paint import CELL_PAD, paint_badge, paint_check, paint_code

PASTE_COLUMNS: tuple[str, ...] = ("check", "code", "badges")
OCR_COLUMNS: tuple[str, ...] = ("check", "code", "conf", "crop", "badges", "reviewed")
_TITLES: dict[str, T] = {"check": T("", ""), "code": T("序號", "Code"), "conf": T("信心", "Confidence"),
                         "crop": T("原圖", "Image"), "badges": T("標記", "Notes"), "reviewed": T("確認", "Review")}
_WIDTHS: dict[str, int] = {"check": 40, "conf": 116, "crop": 116, "reviewed": 104}
REVIEWED_LABEL = T("確認無誤", "Looks right")
"""Label of the review tick of a flagged candidate (a static action label: the tick shows the
state, the colour turns from warning to success) - the OCR dialog's hint names it."""


@dataclass
class CandidateEntry:
    cand: CodeCandidate
    checked: bool = True
    reviewed: bool = False  # 「確認無誤」 ticked: flagged characters confirmed by the user
    edited: bool = False  # code changed by the user (clears flags like an edit in the table)
    duplicate: bool = False  # same code already queued for the target game
    history_status: CodeStatus | None = None  # latest history status for the target game
    history_skip: bool = False  # the import skips it (history says it is done)
    crop: QPixmap | None = None  # source-line crop (OCR dialog)

    @property
    def checkable(self) -> bool:
        return not (self.duplicate or self.history_skip)

    @property
    def will_add(self) -> bool:
        return self.checkable and self.checked

    @property
    def included(self) -> bool:
        """Part of ``candidates()``: ticked ones, plus duplicates / history skips (counted, not added)."""
        return self.checked or not self.checkable

    @property
    def flagged(self) -> list[int]:
        return [] if (self.reviewed or self.edited) else list(self.cand.flagged)

    @property
    def needs_review(self) -> bool:
        return bool(self.flagged)

    def badges(self) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        if self.duplicate:  # skipped as a duplicate: the history does not matter any more
            out.append((tr("重複", "Duplicate"), "neutral"))
        elif self.history_skip:
            out.append((tr("已兌換過", "Already redeemed"), "violet"))
        elif self.history_status is not None:
            out.append((tr("紀錄：{s}", "History: {s}").format(s=self.history_status.label()), "info"))
        if not self.cand.likely:
            out.append((tr("不像序號", "Unlikely"), "neutral"))
        if self.edited:
            out.append((tr("已修改", "Edited"), "accent"))
        elif self.cand.repaired:
            out.append((tr("已修正字元", "Corrected"), "warning"))
        return out

    def result(self) -> CodeCandidate:
        c = clone(self.cand)
        c.flagged = self.flagged
        return c


def make_entries(ctx: AppContext, candidates: Sequence[CodeCandidate], game_key: str,
                 skip_statuses: Sequence[CodeStatus]) -> list[CandidateEntry]:
    """Entries with the duplicate / history checks of the import target (``game_key`` "" = none)."""
    out = []
    for c in candidates:
        dup = ctx.queue.find_code(c.code, game_key)
        rec = ctx.history.latest(game_key, c.code) if game_key else None
        c.duplicate_of = dup.id if dup is not None else ""
        c.history_status = rec.status if rec is not None else None
        skip = rec is not None and rec.status in skip_statuses
        out.append(CandidateEntry(cand=c, checked=bool(c.likely), duplicate=dup is not None,
                                  history_status=c.history_status, history_skip=skip))
    return out


def summary_counts(entries: Sequence[CandidateEntry]) -> tuple[int, int, int, int]:
    """(to add, duplicates, history skips, to add but still needing review)."""
    add = sum(1 for e in entries if e.will_add)
    dup = sum(1 for e in entries if e.duplicate)
    hist = sum(1 for e in entries if e.history_skip and not e.duplicate)
    review = sum(1 for e in entries if e.will_add and e.needs_review)
    return add, dup, hist, review


def summary_text(add: int, dup: int, hist: int, review: int = 0) -> str:
    """「將加入 {a} 筆，略過 {d} 筆重複、{h} 筆已兌換過（{r} 筆需要確認）」; a skip part with a count of 0
    is left out (as in the import toast), and so is the review suffix."""
    skipped = []
    if dup:
        skipped.append(tr("{d} 筆重複", "{d} duplicate(s)").format(d=dup))
    if hist:
        skipped.append(tr("{h} 筆已兌換過", "{h} already redeemed").format(h=hist))
    text = tr("將加入 {a} 筆", "{a} will be added").format(a=add)
    if skipped:
        text += tr("，略過 {parts}", "; skipping {parts}").format(parts=tr("、", " and ").join(skipped))
    if review:
        text += tr("（{r} 筆需要確認）", " ({r} need review)").format(r=review)
    return text


# ============================================================================= model


class CandidateModel(QAbstractTableModel):
    changed = pyqtSignal()  # checked / 確認無誤 / code edits

    def __init__(self, columns: Sequence[str], parent: Any = None) -> None:
        super().__init__(parent)
        self.columns = tuple(columns)
        self.entries: list[CandidateEntry] = []
        self.editable = False
        self.on_edit: Callable[[CandidateEntry, str], bool] | None = None

    def col(self, key: str) -> int:
        return self.columns.index(key) if key in self.columns else -1

    def set_entries(self, entries: Sequence[CandidateEntry]) -> None:
        self.beginResetModel()
        self.entries = list(entries)
        self.endResetModel()
        self.changed.emit()

    def entry(self, row: int) -> CandidateEntry | None:
        return self.entries[row] if 0 <= row < len(self.entries) else None

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self.entries)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(self.columns):
            if role == Qt.ItemDataRole.DisplayRole:
                return str(_TITLES[self.columns[section]])
            if role == Qt.ItemDataRole.TextAlignmentRole:
                return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        e = self.entry(index.row()) if index.isValid() else None
        if e is None:
            return Qt.ItemFlag.NoItemFlags
        f = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        key = self.columns[index.column()]
        if key == "check" and e.checkable:
            f |= Qt.ItemFlag.ItemIsUserCheckable
        elif key == "code" and self.editable and e.checkable:
            f |= Qt.ItemFlag.ItemIsEditable
        elif key == "reviewed" and e.cand.flagged and not e.edited and e.checkable:
            f |= Qt.ItemFlag.ItemIsUserCheckable
        return f

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        e = self.entry(index.row()) if index.isValid() else None
        if e is None:
            return None
        key = self.columns[index.column()]
        if role == ROLE_ITEM:
            return e
        if role == ROLE_FLAGGED:
            return e.flagged
        if role == ROLE_LOOKALIKES:
            return list(e.cand.lookalikes)
        if role == ROLE_CONFIDENCE:
            return e.cand.confidence
        if role == Qt.ItemDataRole.CheckStateRole:
            if key == "check":
                return (Qt.CheckState.Checked if e.checked else Qt.CheckState.Unchecked) if e.checkable else None
            if key == "reviewed":
                if not e.cand.flagged or e.edited or not e.checkable:
                    return None
                return Qt.CheckState.Checked if e.reviewed else Qt.CheckState.Unchecked
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if key == "code":
                return e.cand.code
            if key == "conf":
                conf = e.cand.confidence
                return "—" if conf is None else f"{round(conf * 100)}%"
            if key == "badges" and role == Qt.ItemDataRole.DisplayRole:
                return " · ".join(text for text, _tone in e.badges())
            if (key == "reviewed" and role == Qt.ItemDataRole.DisplayRole and e.cand.flagged and not e.edited
                    and e.checkable):
                return str(REVIEWED_LABEL)  # ticked or not: ReviewedDelegate colours the state
        if role == Qt.ItemDataRole.DecorationRole and key == "crop":
            return e.crop
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip(e, key)
        return None

    def _tooltip(self, e: CandidateEntry, key: str) -> str | None:
        if key == "code":
            lines = []
            if e.cand.raw and e.cand.raw.strip() != e.cand.code:
                lines.append(tr("原文：{raw}", "Source text: {raw}").format(raw=e.cand.raw.strip()))
            if e.flagged:
                pos = "、".join(str(i + 1) for i in e.flagged)
                lines.append(tr("第 {pos} 個字元請對照原圖確認", "Compare character(s) {pos} with the image").format(pos=pos))
            if self.editable and e.checkable:
                lines.append(tr("雙擊可修改", "Double-click to edit"))
            return "\n".join(lines) or None
        if key == "badges":
            return " · ".join(text for text, _tone in e.badges()) or None
        if key == "reviewed" and e.cand.flagged and not e.edited:
            return tr("對照原圖，標示的字元都正確就勾選；勾選的序號會直接成為「待兌換」",
                      "Tick when the highlighted characters match the image; ticked codes become Pending")
        return None

    def setData(self, index: QModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:
        e = self.entry(index.row()) if index.isValid() else None
        if e is None:
            return False
        key = self.columns[index.column()]
        on = value in (Qt.CheckState.Checked, Qt.CheckState.Checked.value, True)
        if role == Qt.ItemDataRole.CheckStateRole and key == "check" and e.checkable:
            e.checked = on
        elif role == Qt.ItemDataRole.CheckStateRole and key == "reviewed" and e.cand.flagged and not e.edited:
            e.reviewed = on
        elif role == Qt.ItemDataRole.EditRole and key == "code" and self.on_edit is not None:
            if not self.on_edit(e, str(value)):
                return False
        else:
            return False
        self._row_changed(index.row())
        return True

    def set_all_reviewed(self) -> int:
        n = 0
        for e in self.entries:
            if e.cand.flagged and not e.edited and not e.reviewed and e.checkable:
                e.reviewed, n = True, n + 1
        if n:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.entries) - 1, len(self.columns) - 1))
            self.changed.emit()
        return n

    def _row_changed(self, row: int) -> None:
        self.dataChanged.emit(self.index(row, 0), self.index(row, len(self.columns) - 1))
        self.changed.emit()


# ============================================================================= delegates


class CandidateCodeDelegate(CodeDelegate):
    """Code with marks (the raw source text is shown in the 標記 column, BadgesDelegate)."""

    def paint_content(self, painter: QPainter, rect: QRectF, index: QModelIndex) -> None:
        e: CandidateEntry | None = index.data(ROLE_ITEM)
        if e is None:
            return
        token = "text" if e.will_add else "text_muted"
        paint_code(painter, rect, e.cand.code, e.flagged, e.cand.lookalikes, token)


class CropDelegate(CellDelegate):
    pad = 8

    def paint_content(self, painter: QPainter, rect: QRectF, index: QModelIndex) -> None:
        pm = index.data(Qt.ItemDataRole.DecorationRole)
        if not isinstance(pm, QPixmap) or pm.isNull():
            return
        dpr = pm.devicePixelRatio() or 1.0
        w, h = pm.width() / dpr, pm.height() / dpr
        scale = min(1.0, (rect.height() - 8) / max(1.0, h), rect.width() / max(1.0, w))
        target = QRectF(rect.left(), rect.center().y() - h * scale / 2, w * scale, h * scale)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(target, pm, QRectF(0, 0, pm.width(), pm.height()))
        painter.setPen(theme.color("border_strong"))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(target.adjusted(-0.5, -0.5, 0.5, 0.5))


class BadgesDelegate(CellDelegate):
    """The badges, then the raw source text in muted type when normalisation changed it (here and
    not after the code: the code column is narrow, so 「原文：ＱＲ５６…」 was cut off next to an
    empty 標記 cell)."""

    def paint_content(self, painter: QPainter, rect: QRectF, index: QModelIndex) -> None:
        e: CandidateEntry | None = index.data(ROLE_ITEM)
        if e is None:
            return
        x = rect.left()
        painter.setClipRect(rect)
        for text, tone in e.badges():
            x += paint_badge(painter, x, rect.center().y(), text, tone) + 6
            if x > rect.right():
                return
        raw = (e.cand.raw or "").strip()
        if raw and raw != e.cand.code:
            r = QRectF(x, rect.top(), max(0.0, rect.right() - x), rect.height())
            painter.setFont(theme.font(theme.FS_SMALL))
            painter.setPen(theme.color("text_muted"))
            text = painter.fontMetrics().elidedText(tr("原文：{raw}", "source: {raw}").format(raw=raw),
                                                    Qt.TextElideMode.ElideRight, int(r.width()))
            painter.drawText(r, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)


class ReviewedDelegate(CheckDelegate):
    """「確認無誤」 tick for flagged candidates (nothing for the others): the label stays the same,
    warning colour until ticked, success colour after."""

    def paint_content(self, painter: QPainter, rect: QRectF, index: QModelIndex) -> None:
        state = index.data(Qt.ItemDataRole.CheckStateRole)
        if state is None:
            return
        checked = state in (Qt.CheckState.Checked, Qt.CheckState.Checked.value)
        box = paint_check(painter, rect, checked, True)
        painter.setFont(theme.font(theme.FS_SMALL, bold=True))
        painter.setPen(theme.color("success_text" if checked else "warning_text"))
        painter.drawText(QRectF(box.right() + 6, rect.top(), rect.right() - box.right() - 6, rect.height()),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         str(index.data(Qt.ItemDataRole.DisplayRole) or ""))


def reviewed_column_width() -> int:
    """Width of the 確認 column: cell padding, the 16 px box, the gap and the bold label in the
    current language (the English label is wider than _WIDTHS["reviewed"])."""
    label = QFontMetrics(theme.font(theme.FS_SMALL, bold=True)).horizontalAdvance(str(REVIEWED_LABEL))
    return max(_WIDTHS["reviewed"], 2 * CELL_PAD + 16 + 6 + label + 4)


def setup_candidate_view(view: QTableView, model: CandidateModel) -> list[CellDelegate]:
    view.setModel(model)
    view.setShowGrid(False)
    view.setWordWrap(False)
    view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    view.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
    view.verticalHeader().setVisible(False)
    view.verticalHeader().setDefaultSectionSize(theme.ROW_H)
    header = view.horizontalHeader()
    header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    header.setHighlightSections(False)
    header.setStretchLastSection(False)
    delegates: list[CellDelegate] = []
    for n, key in enumerate(model.columns):
        d: CellDelegate = {"check": CheckDelegate, "code": CandidateCodeDelegate, "conf": ConfidenceDelegate,
                           "crop": CropDelegate, "badges": BadgesDelegate, "reviewed": ReviewedDelegate}[key](view)
        view.setItemDelegateForColumn(n, d)
        delegates.append(d)
        if key in _WIDTHS:
            header.setSectionResizeMode(n, QHeaderView.ResizeMode.Fixed)
            view.setColumnWidth(n, reviewed_column_width() if key == "reviewed" else _WIDTHS[key])
        else:
            header.setSectionResizeMode(n, QHeaderView.ResizeMode.Stretch)
    view._delegates = delegates  # type: ignore[attr-defined]  # keep the Python objects alive
    return delegates


# ============================================================================= dialog base


class ImportDialogBase(QDialog):
    """Common parts of the PasteDialog and the OcrReviewDialog."""

    def __init__(self, ctx: AppContext, source: CodeSource, detail: str, parent: QWidget | None,
                 format_choice: str | None, columns: Sequence[str]) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._source = source
        self._detail = detail
        self._profile = ctx.active_profile()
        self._target = import_target(ctx, self._profile)
        choices = format_choices(self._profile)
        keys = [k for k, _label in choices]
        self._choice = format_choice if format_choice in keys else default_format_choice(self._profile)
        self._format: CodeFormat = CodeFormat()
        self._detected = ""
        self._model = CandidateModel(columns, self)
        self._model.changed.connect(self._update_summary)
        self._view = QTableView()
        self._view.setObjectName("CandidateTable")
        self._view.setAccessibleName(tr("找到的序號", "Codes found"))
        setup_candidate_view(self._view, self._model)

        self._format_combo = widgets.combo([label for _k, label in choices])
        self._format_combo.setMinimumWidth(180)
        self._format_keys = keys
        self._format_combo.setCurrentIndex(keys.index(self._choice))
        self._format_combo.setAccessibleName(tr("序號格式", "Code format"))
        self._format_combo.currentIndexChanged.connect(self._on_format_index)
        self._detected_label = widgets.label("", "muted")
        self._summary = widgets.label("", "secondary")
        self._summary.setWordWrap(True)
        if self._target.assigned:
            target_text = tr("加入到：{game}", "Adding to: {game}").format(game=game_name(self._profile))
        else:
            target_text = tr("沒有使用中的設定檔：序號會先加入「未指定遊戲」",
                             "No active profile: the codes are added without a game")
        self._target_label = widgets.label(target_text, "muted")
        self._cancel_btn = widgets.push_button(tr("取消", "Cancel"), "secondary")
        self._cancel_btn.clicked.connect(self.reject)
        self._add_btn = widgets.push_button(tr("加入", "Add"), "primary", "plus")
        self._add_btn.setDefault(True)
        self._add_btn.setAutoDefault(True)
        self._add_btn.clicked.connect(self.accept)

    # -- layout pieces ------------------------------------------------------------------------
    def _format_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(theme.SP[2])
        row.addWidget(widgets.label(tr("格式", "Format"), "secondary"))
        row.addWidget(self._format_combo)
        row.addWidget(self._detected_label, 1)
        return row

    def _footer(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(theme.SP[2])
        row.addWidget(self._summary, 1)
        row.addWidget(self._cancel_btn)
        row.addWidget(self._add_btn)
        return row

    # -- format -------------------------------------------------------------------------------
    def format_choice(self) -> str:
        return self._choice

    def _on_format_index(self, index: int) -> None:
        if 0 <= index < len(self._format_keys):
            self._choice = self._format_keys[index]
            self._on_format_changed()

    def _on_format_changed(self) -> None:  # subclasses re-extract
        pass

    def _resolve_format(self, text: str) -> CodeFormat:
        self._format, self._detected = resolve_format(self._choice, self._profile, text)
        if self._detected:
            from ..codes import presets

            self._detected_label.setText(tr("偵測為：{label}", "Detected: {label}").format(
                label=presets.format_label(self._detected)))
        else:
            self._detected_label.setText("")
        return self._format

    # -- candidates ---------------------------------------------------------------------------
    def _set_candidates(self, candidates: Sequence[CodeCandidate]) -> None:
        self._model.set_entries(make_entries(self.ctx, candidates, self._target.game_key, self._target.skip_statuses))

    def entries(self) -> list[CandidateEntry]:
        return list(self._model.entries)

    def summary_counts(self) -> tuple[int, int, int, int]:
        return summary_counts(self._model.entries)

    def _update_summary(self) -> None:
        add, dup, hist, review = self.summary_counts()
        self._summary.setText(summary_text(add, dup, hist, review))
        self._add_btn.setText(tr("加入 {n} 筆", "Add {n}").format(n=add))
        self._add_btn.setEnabled(add > 0)

    def candidates(self) -> list[CodeCandidate]:
        """Ticked candidates (edits applied; 確認無誤 / edited ones without flags), plus duplicates
        and history skips so the queue counts them. Valid after exec() returned Accepted."""
        return [e.result() for e in self._model.entries if e.included]

    def code_format(self) -> CodeFormat:
        return clone(self._format)
