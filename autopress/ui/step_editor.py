# OWNED BY G7 - replace this stub
"""Step list (44 px items: drag handle, StepType.icon, display_title + muted summary, enable
switch, kebab menu; add / duplicate / delete / move up / move down) and the per-type parameter
forms. Point/region fields show "未設定" or the value, with 點選位置 / 框選範圍 (overlays.pick
with the target outline), 清除 and, for points, 對齊 (Anchor: 左上 / 右上 / 左下 / 右下 / 置中).
The title field edits ``label`` in the zh-TW UI and ``label_en`` in the English UI. click_text
shows 「找不到時」 (on_not_found: 視為失敗 / 略過這一步); ocr_check shows 「只看送出後新出現的
文字」 (only_new_text). Spin boxes: setKeyboardTracking(False), selectAll on focus."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget

from ..context import AppContext
from ..models import Profile, Step

__stub__ = True


class StepListWidget(QWidget):
    currentChanged = pyqtSignal(int)  # selected step index (-1 = none)
    stepsChanged = pyqtSignal()  # order / enabled / add / delete changed

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        raise NotImplementedError

    def set_steps(self, steps: list[Step]) -> None:
        raise NotImplementedError

    def steps(self) -> list[Step]:
        raise NotImplementedError

    def current_index(self) -> int:
        raise NotImplementedError


class StepEditor(QWidget):
    stepChanged = pyqtSignal(object)  # the edited Step (a new object each time)

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        raise NotImplementedError

    def set_step(self, step: Step | None, profile: Profile, index: int) -> None:
        """Show the form for ``step`` (None = empty state). ``profile`` gives the target and
        code format; ``index`` is used for messages and tests."""
        raise NotImplementedError

    def step(self) -> Step | None:
        raise NotImplementedError
