# OWNED BY G7
"""Step list (44 px items: drag handle, StepType.icon, display_title + muted summary - led by a red
dot while required settings are missing, so the dot never narrows the name -, enable switch,
kebab menu; add / duplicate / delete / move up / move down) and the per-type parameter
forms. Point/region fields show "未設定" or the value, with 點選位置 / 框選範圍 (overlays.pick
with the target outline), 清除 and, for points, 對齊 (Anchor: 左上 / 右上 / 左下 / 右下 / 置中).
The title field edits ``label`` in the zh-TW UI and ``label_en`` in the English UI. click_text
shows 「找不到時」 (on_not_found: 視為失敗 / 略過這一步); ocr_check shows 「只看送出後新出現的
文字」 (only_new_text). Spin boxes: setKeyboardTracking(False), selectAll on focus."""

from __future__ import annotations

from PyQt6.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QPainter, QPaintEvent
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QVBoxLayout,
    QWidget,
)

from ..context import AppContext
from ..i18n import tr
from ..models import IssueLevel, Profile, Step, StepType, clone, make_step
from . import icons, theme
from . import widgets as w
from .step_forms import StepForm

ROLE_STEP_ID = Qt.ItemDataRole.UserRole + 1
ROW_H = 44


def _icon_label(name: str, token: str = "text_secondary", size: int = 16) -> QLabel:
    lb = QLabel()
    lb.setFixedSize(size + 4, size + 4)
    lb.setAlignment(Qt.AlignmentFlag.AlignCenter)
    try:
        lb.setPixmap(icons.icon_pixmap(name, token, size))
    except Exception:  # icons stub before G5
        pass
    return lb


class _IssueDot(QWidget):
    """The red dot in front of the summary of a step with required settings missing: painted in the
    theme's error colour (like a status chip's dot), the same size in every font and scale."""

    SIZE = 8

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)

    def paintEvent(self, event: QPaintEvent | None) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.color("error"))
        p.drawEllipse(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
        p.end()


class _StepRow(QWidget):
    """One 44 px row of the step list."""

    def __init__(self, owner: StepListWidget, index: int, step: Step, error: bool) -> None:
        super().__init__()
        self.owner = owner
        self.index = index
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 2, 4, 2)
        lay.setSpacing(6)
        grip = _icon_label("drag", "text_disabled", 14)
        grip.setToolTip(tr("拖曳調整順序", "Drag to reorder"))
        lay.addWidget(grip)
        lay.addWidget(_icon_label(step.type.icon, "accent" if step.enabled else "text_disabled"))
        col = QVBoxLayout()
        col.setSpacing(0)
        col.setContentsMargins(0, 0, 0, 0)
        self.title = w.ElidedLabel(f"{index + 1}. {step.display_title()}")  # long titles elide, never widen the list
        self.title.setProperty("role", "body" if step.enabled else "muted")
        self.title.setToolTip(step.type.label())
        col.addWidget(self.title)
        # the red "required setting missing" dot leads the summary line (「● 尚未設定位置」): beside the
        # name column it cost the name 18 px and cut 「5. 框出結果訊息的範圍」 in fresh template profiles
        line2 = QHBoxLayout()
        line2.setContentsMargins(0, 0, 0, 0)
        line2.setSpacing(4)
        self.issue = _IssueDot(self)
        self.issue.setToolTip(tr("這一步還有必填項目沒設定", "This step has required settings missing"))
        self.issue.setAccessibleName(self.issue.toolTip())
        self.issue.setVisible(error)
        line2.addWidget(self.issue, 0, Qt.AlignmentFlag.AlignVCenter)
        self.summary = w.ElidedLabel(step.summary() if step.enabled else tr("（已停用）", "(disabled)"))
        self.summary.setProperty("role", "muted")
        line2.addWidget(self.summary, 1)
        col.addLayout(line2)
        lay.addLayout(col, 1)
        self.enable = w.Switch(step.enabled)
        self.enable.setToolTip(tr("啟用這一步", "Enable this step"))
        self.enable.setAccessibleName(tr(f"啟用第 {index + 1} 步", f"Enable step {index + 1}"))
        self.enable.toggled.connect(lambda on: owner.set_enabled(self.index, on))
        lay.addWidget(self.enable)
        more = w.icon_button("more", tr("更多動作", "More actions"))
        more.clicked.connect(lambda: owner.show_row_menu(self.index, more))
        lay.addWidget(more)


class StepListWidget(QWidget):
    currentChanged = pyqtSignal(int)  # selected step index (-1 = none)
    stepsChanged = pyqtSignal()  # order / enabled / add / delete changed

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._steps: list[Step] = []
        self._errors: set[int] = set()
        self._rebuilding = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setUniformItemSizes(True)
        self.list.setAccessibleName(tr("步驟清單", "Step list"))
        self.list.currentRowChanged.connect(self._on_row)
        self.list.model().rowsMoved.connect(self._on_rows_moved)
        lay.addWidget(self.list, 1)
        bar = QHBoxLayout()
        bar.setSpacing(4)
        self.add_btn = w.push_button(tr("新增步驟", "Add step"), "secondary", "plus")
        self.add_menu = QMenu(self.add_btn)
        for st in StepType:
            if st is StepType.UNKNOWN:
                continue
            act = self.add_menu.addAction(st.label())
            act.triggered.connect(lambda _c=False, t=st: self.add_step(t))
        self.add_btn.setMenu(self.add_menu)
        bar.addWidget(self.add_btn)
        bar.addStretch(1)
        self.up_btn = w.icon_button("arrow_up", tr("上移", "Move up"))
        self.up_btn.clicked.connect(lambda: self.move_step(self.current_index(), -1))
        self.down_btn = w.icon_button("arrow_down", tr("下移", "Move down"))
        self.down_btn.clicked.connect(lambda: self.move_step(self.current_index(), 1))
        self.dup_btn = w.icon_button("copy", tr("複製這一步", "Duplicate step"))
        self.dup_btn.clicked.connect(lambda: self.duplicate_step(self.current_index()))
        self.del_btn = w.icon_button("trash", tr("刪除這一步", "Delete step"))
        self.del_btn.clicked.connect(lambda: self.delete_step(self.current_index()))
        for b in (self.up_btn, self.down_btn, self.dup_btn, self.del_btn):
            bar.addWidget(b)
        lay.addLayout(bar)
        self._update_buttons()

    # -- data -----------------------------------------------------------------------------
    def set_steps(self, steps: list[Step]) -> None:
        self._steps = [clone(s) for s in steps]
        self._rebuild(0 if self._steps else -1)

    def steps(self) -> list[Step]:
        return [clone(s) for s in self._steps]

    def current_index(self) -> int:
        return self.list.currentRow() if self._steps else -1

    def set_current(self, index: int) -> None:
        if 0 <= index < len(self._steps):
            self.list.setCurrentRow(index)

    def set_error_rows(self, indices: set[int]) -> None:
        """Rows that get a red dot (validation errors of the profile)."""
        if indices != self._errors:
            self._errors = set(indices)
            self._rebuild(self.current_index())

    def update_step(self, index: int, step: Step) -> None:
        """Replace one step after an edit (no stepsChanged: the editor reports edits itself)."""
        if 0 <= index < len(self._steps):
            self._steps[index] = clone(step)
            item = self.list.item(index)
            row = self.list.itemWidget(item) if item is not None else None
            if isinstance(row, _StepRow):
                row.title.setText(f"{index + 1}. {step.display_title()}")
                row.summary.setText(step.summary() if step.enabled else tr("（已停用）", "(disabled)"))

    # -- editing --------------------------------------------------------------------------
    def add_step(self, step_type: StepType) -> int:
        step = make_step(step_type, self.ctx.settings.delays)
        if step_type in (StepType.TYPE_CODE, StepType.TYPE_TEXT):
            step.params.mode = self.ctx.settings.default_typing_mode  # type: ignore[union-attr]
        cur = self.current_index()
        at = cur + 1 if cur >= 0 else len(self._steps)
        self._steps.insert(at, step)
        self._rebuild(at)
        self.stepsChanged.emit()
        return at

    def duplicate_step(self, index: int) -> None:
        if 0 <= index < len(self._steps):
            copy = clone(self._steps[index])
            from ..models import new_id

            copy.id = new_id()
            self._steps.insert(index + 1, copy)
            self._rebuild(index + 1)
            self.stepsChanged.emit()

    def delete_step(self, index: int) -> None:
        if 0 <= index < len(self._steps):
            del self._steps[index]
            self._rebuild(min(index, len(self._steps) - 1))
            self.stepsChanged.emit()

    def move_step(self, index: int, delta: int) -> None:
        j = index + delta
        if 0 <= index < len(self._steps) and 0 <= j < len(self._steps):
            self._steps[index], self._steps[j] = self._steps[j], self._steps[index]
            self._rebuild(j)
            self.stepsChanged.emit()

    def set_enabled(self, index: int, on: bool) -> None:
        if 0 <= index < len(self._steps) and self._steps[index].enabled != on:
            self._steps[index].enabled = on
            cur = self.current_index()
            self._rebuild(cur)
            self.stepsChanged.emit()

    def show_row_menu(self, index: int, anchor: QWidget) -> None:
        self.set_current(index)
        menu = QMenu(self)
        menu.addAction(tr("複製這一步", "Duplicate step"), lambda: self.duplicate_step(index))
        up = menu.addAction(tr("上移", "Move up"), lambda: self.move_step(index, -1))
        up.setEnabled(index > 0)
        down = menu.addAction(tr("下移", "Move down"), lambda: self.move_step(index, 1))
        down.setEnabled(index < len(self._steps) - 1)
        menu.addSeparator()
        menu.addAction(tr("刪除這一步", "Delete step"), lambda: self.delete_step(index))
        menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    # -- view -----------------------------------------------------------------------------
    def _rebuild(self, select: int) -> None:
        self._rebuilding = True
        self.list.clear()
        for i, step in enumerate(self._steps):
            item = QListWidgetItem()
            item.setData(ROLE_STEP_ID, step.id)
            item.setSizeHint(QSize(200, ROW_H))
            item.setText("")
            self.list.addItem(item)
            self.list.setItemWidget(item, _StepRow(self, i, step, i in self._errors))
        self._rebuilding = False
        if 0 <= select < len(self._steps):
            self.list.setCurrentRow(select)
        else:
            self.currentChanged.emit(-1)
        self._update_buttons()

    def _on_row(self, row: int) -> None:
        if self._rebuilding:
            return
        self._update_buttons()
        self.currentChanged.emit(row if 0 <= row < len(self._steps) else -1)

    def _on_rows_moved(self, *_args: object) -> None:
        if self._rebuilding:
            return
        ids = [self.list.item(i).data(ROLE_STEP_ID) for i in range(self.list.count())]
        by_id = {s.id: s for s in self._steps}
        if sorted(ids) != sorted(by_id) or ids == [s.id for s in self._steps]:
            return
        moved_to = self.list.currentRow()
        self._steps = [by_id[i] for i in ids]
        self._rebuild(moved_to)
        self.stepsChanged.emit()

    def _update_buttons(self) -> None:
        i = self.list.currentRow() if self._steps else -1
        has = 0 <= i < len(self._steps)
        self.up_btn.setEnabled(has and i > 0)
        self.down_btn.setEnabled(has and i < len(self._steps) - 1)
        self.dup_btn.setEnabled(has)
        self.del_btn.setEnabled(has)


class StepEditor(QWidget):
    stepChanged = pyqtSignal(object)  # the edited Step (a new object each time)

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._step: Step | None = None
        self._profile: Profile | None = None
        self._index = -1
        self.form: StepForm | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        head = QHBoxLayout()
        self.icon = _icon_label("profiles", "accent", 18)
        head.addWidget(self.icon)
        self.header = w.label("", "title")
        head.addWidget(self.header, 1)
        lay.addLayout(head)
        self.form_host = QVBoxLayout()
        lay.addLayout(self.form_host)
        self.issues = w.label("", "error")
        self.issues.setWordWrap(True)
        self.issues.hide()
        lay.addWidget(self.issues)
        self.empty = w.label(tr("選擇左邊的步驟來編輯，或按「新增步驟」。", "Select a step to edit, or click 'Add step'."),
                             "muted")
        self.empty.setWordWrap(True)
        lay.addWidget(self.empty)
        lay.addStretch(1)
        self.set_step(None, Profile(), -1)

    def set_step(self, step: Step | None, profile: Profile, index: int) -> None:
        """Show the form for ``step`` (None = empty state). ``profile`` gives the target and
        code format; ``index`` is used for messages and tests."""
        self._profile = profile
        self._index = index
        self._step = clone(step) if step is not None else None
        if self.form is not None:
            self.form_host.removeWidget(self.form)
            self.form.hide()
            self.form.deleteLater()
            self.form = None
        if self._step is None:
            self.header.setText(tr("步驟設定", "Step settings"))
            self.empty.show()
            self.issues.hide()
            return
        self.empty.hide()
        self.header.setText(tr(f"第 {index + 1} 步：{self._step.type.label()}", f"Step {index + 1}: {self._step.type.label()}"))
        try:
            self.icon.setPixmap(icons.icon_pixmap(self._step.type.icon, "accent", 18))
        except Exception:
            pass
        self.form = StepForm(self._step, self._on_form_change, self._pick, profile.code_format.groups)
        self.form_host.addWidget(self.form)
        self._update_issues()

    def step(self) -> Step | None:
        return clone(self._step) if self._step is not None else None

    def index(self) -> int:
        return self._index

    def field(self, name: str) -> QWidget | None:
        """The widget of a parameter (tests): parameter name, or "title"."""
        return self.form.fields.get(name) if self.form is not None else None

    # -- internals ------------------------------------------------------------------------
    def _on_form_change(self) -> None:
        if self._step is None:
            return
        self._update_issues()
        self.stepChanged.emit(clone(self._step))

    def _update_issues(self) -> None:
        if self._step is None or self._profile is None:
            self.issues.hide()
            return
        issues = [i for i in self._step.validate(max(0, self._index), self._profile)
                  if i.level in (IssueLevel.ERROR, IssueLevel.WARNING)]
        self.issues.setText("\n".join(i.message for i in issues))
        self.issues.setVisible(bool(issues))

    def _pick(self, kind: str, instruction: str) -> tuple[object, str]:
        from .step_pick import hide_list, pick_point, pick_region

        if self._profile is None:
            return None, ""
        hide = hide_list(self, getattr(self.ctx, "main_window", None))
        if kind == "point":
            return pick_point(self._profile, instruction, hide=hide)
        return pick_region(self._profile, instruction, hide=hide)
