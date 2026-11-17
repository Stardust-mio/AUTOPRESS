# OWNED BY G7
"""Field widgets and per-type parameter forms of the step editor (private helper of
ui.step_editor). A form edits ``step.params`` of the editor's working copy in place and calls
``on_change()``; the editor then emits ``stepChanged`` with a fresh copy."""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable, Sequence
from enum import Enum
from typing import Any

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr
from ..models import (
    Anchor,
    BetweenSegments,
    ClearMethod,
    ClientPoint,
    ClientRegion,
    IssueLevel,
    MouseButton,
    SplitMode,
    Step,
    StepType,
    TextMatch,
    TimeoutAction,
    TypingMode,
    combo_risk,
    normalize_combo,
)
from ..textutil import clean_text
from . import widgets as w

Picker = Callable[[str, str], object]  # (kind "point" | "region", instruction) -> value or None


def anchor_labels() -> dict[Anchor, str]:
    return {Anchor.TL: tr("左上", "Top left"), Anchor.TR: tr("右上", "Top right"),
            Anchor.BL: tr("左下", "Bottom left"), Anchor.BR: tr("右下", "Bottom right"),
            Anchor.CENTER: tr("置中", "Centre")}


def parse_sizes(text: str) -> list[int] | None:
    """"5,5,5" / "5-5-5" / "5 5 5" -> [5, 5, 5]; "" -> []; None when invalid."""
    t = (text or "").strip()
    if not t:
        return []
    parts = [p for p in re.split(r"[\s,，、\-]+", t) if p]
    if not parts or not all(p.isdigit() and 0 < int(p) <= 64 for p in parts):
        return None
    return [int(p) for p in parts]


def field_range(params: object, name: str) -> tuple[float | None, float | None]:
    for f in dataclasses.fields(params):  # type: ignore[arg-type]
        if f.name == name:
            return f.metadata.get("range", (None, None))
    return None, None


class SpinBox(QSpinBox):
    """Applies on Enter / focus-out only (setKeyboardTracking(False)); focus selects all."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setKeyboardTracking(False)
        self.setMinimumWidth(110)

    def focusInEvent(self, event) -> None:  # noqa: N802
        super().focusInEvent(event)
        QTimer.singleShot(0, self.selectAll)


class DoubleSpinBox(QDoubleSpinBox):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setKeyboardTracking(False)
        self.setMinimumWidth(110)

    def focusInEvent(self, event) -> None:  # noqa: N802
        super().focusInEvent(event)
        QTimer.singleShot(0, self.selectAll)


class PositionField(QWidget):
    """「未設定」 or the recorded value, with 點選位置 / 框選範圍, 清除 and (points) 對齊."""

    changed = pyqtSignal(object)  # ClientPoint | ClientRegion | None

    def __init__(self, kind: str, value: object, picker: Picker | None, instruction: str,
                 required: bool = False, none_text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kind = kind  # "point" | "region"
        self.value = value
        self.picker = picker
        self.instruction = instruction
        self.required = required
        self.none_text = none_text
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.value_label = w.label("", "body")
        row.addWidget(self.value_label, 1)
        pick_text = tr("點選位置", "Pick position") if kind == "point" else tr("框選範圍", "Drag region")
        self.pick_btn = w.push_button(pick_text, "secondary", "crosshair" if kind == "point" else "region")
        self.pick_btn.setToolTip(tr("在目標視窗上點選（目標視窗的內容區會被框出來）",
                                    "Pick it on the target window (its client area is outlined)"))
        self.pick_btn.clicked.connect(self._pick)
        self.pick_btn.setEnabled(picker is not None)
        row.addWidget(self.pick_btn)
        self.clear_btn = w.push_button(tr("清除", "Clear"), "ghost")
        self.clear_btn.clicked.connect(lambda: self.set_value(None, emit=True))
        row.addWidget(self.clear_btn)
        lay.addLayout(row)
        self.anchor = None
        if kind == "point":
            arow = QHBoxLayout()
            arow.addWidget(w.label(tr("對齊", "Align to"), "secondary"))
            self.anchor = QComboBox()
            for a, text in anchor_labels().items():
                self.anchor.addItem(text, a.value)
            self.anchor.setToolTip(tr("「固定像素」模式下，這個點跟視窗哪個角的距離保持不變",
                                      "In fixed-pixel mode the distance to this corner of the window is kept"))
            self.anchor.currentIndexChanged.connect(self._anchor_changed)
            arow.addWidget(self.anchor)
            arow.addStretch(1)
            lay.addLayout(arow)
        self.error = w.label("", "error")
        self.error.setWordWrap(True)
        self.error.hide()
        lay.addWidget(self.error)
        self.set_value(value, emit=False)

    def set_value(self, value: object, emit: bool = False) -> None:
        self.value = value
        if value is None:
            text = self.none_text or tr("未設定", "Not set")
            self.value_label.setProperty("role", "error" if self.required else "muted")
        else:
            text = value.describe()  # type: ignore[attr-defined]
            text += tr(f"（錄製時視窗 {value.ref_w}×{value.ref_h}）",  # type: ignore[attr-defined]
                       f" (window {value.ref_w}×{value.ref_h} when recorded)")  # type: ignore[attr-defined]
            self.value_label.setProperty("role", "body")
        self.value_label.setText(text)
        self.value_label.style().unpolish(self.value_label)
        self.value_label.style().polish(self.value_label)
        self.clear_btn.setEnabled(value is not None)
        if self.anchor is not None:
            self.anchor.blockSignals(True)
            a = value.anchor.value if isinstance(value, ClientPoint) else Anchor.TL.value
            self.anchor.setCurrentIndex(max(0, self.anchor.findData(a)))
            self.anchor.setEnabled(isinstance(value, ClientPoint))
            self.anchor.blockSignals(False)
        if emit:
            self.changed.emit(value)

    def current_anchor(self) -> Anchor:
        if self.anchor is None:
            return Anchor.TL
        return Anchor(self.anchor.currentData() or Anchor.TL.value)

    def _anchor_changed(self) -> None:
        if isinstance(self.value, ClientPoint):
            self.value = dataclasses.replace(self.value, anchor=self.current_anchor())
            self.changed.emit(self.value)

    def show_error(self, text: str) -> None:
        self.error.setText(text)
        self.error.setVisible(bool(text))

    def _pick(self) -> None:
        if self.picker is None:
            return
        self.show_error("")
        result = self.picker(self.kind, self.instruction)
        if isinstance(result, tuple):
            value, err = result
        else:
            value, err = result, ""
        if err:
            self.show_error(err)
        if isinstance(value, (ClientPoint, ClientRegion)):
            if isinstance(value, ClientPoint) and self.anchor is not None:
                value = dataclasses.replace(value, anchor=self.current_anchor())
            self.set_value(value, emit=True)


class StepForm(QWidget):
    """Form for one step: ``fields`` maps parameter names (and "title") to their widgets."""

    def __init__(self, step: Step, on_change: Callable[[], None], picker: Picker | None,
                 code_groups: Sequence[int] = (), parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.step = step
        self.on_change = on_change
        self.picker = picker
        self.code_groups = list(code_groups)
        self.fields: dict[str, QWidget] = {}
        self._rows: dict[str, tuple[QWidget, QWidget]] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.main = QFormLayout()
        self.main.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.main.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.main.setHorizontalSpacing(16)
        self.main.setVerticalSpacing(8)
        lay.addLayout(self.main)
        self.adv_btn = QToolButton()
        self.adv_btn.setText(tr("進階設定", "Advanced"))
        self.adv_btn.setCheckable(True)
        self.adv_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.adv_btn.setArrowType(Qt.ArrowType.RightArrow)
        self.adv_box = QWidget()
        self.adv = QFormLayout(self.adv_box)
        self.adv.setContentsMargins(0, 0, 0, 0)
        self.adv.setHorizontalSpacing(16)
        self.adv.setVerticalSpacing(8)
        self.adv_box.hide()
        self.adv_btn.toggled.connect(self._toggle_adv)
        lay.addWidget(self.adv_btn)
        lay.addWidget(self.adv_box)
        self._title_field()
        build = _BUILDERS.get(step.type)
        if build is not None:
            build(self)
        if self.adv.rowCount() == 0:
            self.adv_btn.hide()
        self.update_visibility()

    # -- infrastructure -------------------------------------------------------------------
    def _toggle_adv(self, on: bool) -> None:
        self.adv_box.setVisible(on)
        self.adv_btn.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)

    def _add(self, name: str, text: str, widget: QWidget, advanced: bool = False, hint: str = "") -> QWidget:
        form = self.adv if advanced else self.main
        label = w.label(text, "secondary")
        if hint:
            box = QWidget()
            v = QVBoxLayout(box)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(2)
            v.addWidget(widget)
            hl = w.label(hint, "muted")
            hl.setWordWrap(True)
            v.addWidget(hl)
            form.addRow(label, box)
            self._rows[name] = (label, box)
        else:
            form.addRow(label, widget)
            self._rows[name] = (label, widget)
        widget.setAccessibleName(text)
        self.fields[name] = widget
        return widget

    def set_row_visible(self, name: str, visible: bool) -> None:
        if name in self._rows:
            for wdg in self._rows[name]:
                wdg.setVisible(visible)

    def _set(self, name: str, value: Any) -> None:
        if getattr(self.step.params, name) != value:
            setattr(self.step.params, name, value)
            self.update_visibility()
            self.on_change()

    def update_visibility(self) -> None:
        p = self.step.params
        if self.step.type is StepType.TYPE_CODE:
            split = p.split
            self.set_row_visible("separators", split is SplitMode.SEPARATOR or (split is SplitMode.NONE and p.strip_separators))
            self.set_row_visible("group_sizes", split is SplitMode.FIXED)
            self.set_row_visible("between", split is not SplitMode.NONE)
            self.set_row_visible("strip_separators", split is SplitMode.NONE)
        if self.step.type in (StepType.TYPE_CODE, StepType.TYPE_TEXT):
            self.set_row_visible("clear_method", bool(p.clear_first))

    # -- field kinds ----------------------------------------------------------------------
    def _title_field(self) -> None:
        from ..i18n import is_zh

        attr = "label" if is_zh() else "label_en"
        other = self.step.label_en if attr == "label" else self.step.label
        edit = QLineEdit(getattr(self.step, attr))
        edit.setPlaceholderText(other or self.step.type.label())
        edit.setMaxLength(80)

        def apply(text: str) -> None:
            value = clean_text(text)
            if getattr(self.step, attr) != value:
                setattr(self.step, attr, value)
                self.on_change()

        edit.textChanged.connect(apply)
        self._add("title", tr("步驟名稱", "Step title"), edit,
                  hint=tr("精靈會用這個名稱提示你，例如「點一下序號輸入框」。", "The wizard shows it, e.g. 'Click the code box'."))

    def spin(self, name: str, text: str, suffix: str = "", advanced: bool = False, hint: str = "",
             step: int = 0) -> SpinBox:
        lo, hi = field_range(self.step.params, name)
        sb = SpinBox()
        sb.setRange(int(lo if lo is not None else -100000), int(hi if hi is not None else 100000))
        sb.setValue(int(getattr(self.step.params, name)))
        if suffix:
            sb.setSuffix(suffix)
        if step:
            sb.setSingleStep(step)
        sb.valueChanged.connect(lambda v, n=name: self._set(n, int(v)))
        self._add(name, text, sb, advanced, hint)
        return sb

    def ms(self, name: str, text: str, advanced: bool = False, hint: str = "") -> SpinBox:
        return self.spin(name, text, tr(" 毫秒", " ms"), advanced, hint, step=50)

    def dspin(self, name: str, text: str, decimals: int = 2, advanced: bool = False, hint: str = "") -> DoubleSpinBox:
        lo, hi = field_range(self.step.params, name)
        sb = DoubleSpinBox()
        sb.setDecimals(decimals)
        sb.setRange(float(lo if lo is not None else 0.0), float(hi if hi is not None else 1.0))
        sb.setSingleStep(0.05)
        sb.setValue(float(getattr(self.step.params, name)))
        sb.valueChanged.connect(lambda v, n=name: self._set(n, float(v)))
        self._add(name, text, sb, advanced, hint)
        return sb

    def switch(self, name: str, text: str, advanced: bool = False, hint: str = "") -> QWidget:
        sw = w.Switch(bool(getattr(self.step.params, name)))
        sw.toggled.connect(lambda on, n=name: self._set(n, bool(on)))
        self._add(name, text, sw, advanced, hint)
        return sw

    def choice(self, name: str, text: str, items: Sequence[tuple[Any, str]], advanced: bool = False,
               hint: str = "") -> QComboBox:
        cb = QComboBox()
        current = getattr(self.step.params, name)
        for value, label in items:
            cb.addItem(label, value.value if isinstance(value, Enum) else value)
        idx = cb.findData(current.value if isinstance(current, Enum) else current)
        cb.setCurrentIndex(max(0, idx))
        enum_cls = type(current) if isinstance(current, Enum) else None

        def apply(_i: int, n: str = name) -> None:
            data = cb.currentData()
            self._set(n, enum_cls(data) if enum_cls is not None else data)

        cb.currentIndexChanged.connect(apply)
        self._add(name, text, cb, advanced, hint)
        return cb

    def enum_choice(self, name: str, text: str, enum_cls: type[Enum], advanced: bool = False,
                    hint: str = "") -> QComboBox:
        return self.choice(name, text, [(m, m.label()) for m in enum_cls], advanced, hint)  # type: ignore[attr-defined]

    def text(self, name: str, text: str, placeholder: str = "", hint: str = "", advanced: bool = False) -> QLineEdit:
        edit = QLineEdit(str(getattr(self.step.params, name)))
        edit.setPlaceholderText(placeholder)
        edit.textChanged.connect(lambda t, n=name: self._set(n, clean_text(t)))
        self._add(name, text, edit, advanced, hint)
        return edit

    def position(self, name: str, text: str, kind: str, instruction: str, required: bool = False,
                 none_text: str = "", hint: str = "") -> PositionField:
        fld = PositionField(kind, getattr(self.step.params, name), self.picker, instruction, required, none_text)
        fld.changed.connect(lambda v, n=name: self._set(n, v))
        self._add(name, text, fld, hint=hint)
        return fld

    def instruction(self, fallback: str) -> str:
        return self.step.display_title() if (self.step.label or self.step.label_en) else fallback


# ----------------------------------------------------------------------------- per type


def _focus(f: StepForm) -> None:
    f.switch("restore_minimized", tr("最小化時先還原", "Restore when minimized"))
    f.ms("settle_ms", tr("切換後等待", "Wait after switching"))
    f.ms("timeout_ms", tr("最多等待", "Timeout"), advanced=True)


def _click_common(f: StepForm, advanced_button: bool) -> None:
    f.ms("after_ms", tr("點擊後等待", "Wait after the click"))
    f.choice("button", tr("滑鼠按鍵", "Mouse button"), [(b, b.label()) for b in MouseButton], advanced=advanced_button)
    f.switch("double", tr("雙擊", "Double-click"), advanced=advanced_button)
    f.ms("settle_ms", tr("移到位置後等待再按下", "Wait before pressing"), advanced=True)
    f.ms("hold_ms", tr("按住時間", "Hold time"), advanced=True)


def _click_point(f: StepForm) -> None:
    f.position("point", tr("點擊位置", "Click position"), "point",
               f.instruction(tr("點一下要點擊的位置", "Click the position")), required=True)
    _click_common(f, advanced_button=False)
    f.spin("jitter_px", tr("隨機偏移", "Random offset"), tr(" 像素", " px"), advanced=True,
           hint=tr("每次點擊在 ±N 像素內隨機移動一點", "Each click moves randomly within ±N px"))


def _not_found_items() -> list[tuple[TimeoutAction, str]]:
    return [(TimeoutAction.FAIL, tr("視為失敗", "Treat as failure")),
            (TimeoutAction.CONTINUE, tr("略過這一步", "Skip this step"))]


def _upscale_items() -> list[tuple[int, str]]:
    return [(0, tr("自動", "Automatic")), (1, "1×"), (2, "2×"), (3, "3×")]


def _click_text(f: StepForm) -> None:
    f.text("text", tr("要點擊的文字", "Text to click"), "兌換|Redeem",
           hint=tr("多個候選用 | 分隔（例如 兌換|Redeem|確認）；正規表示式模式下整段是一個式子。",
                   "Separate alternatives with | (e.g. Redeem|OK); in regex mode the whole text is one pattern."))
    f.enum_choice("match", tr("比對方式", "Matching"), TextMatch)
    f.position("region", tr("搜尋範圍", "Search region"), "region",
               f.instruction(tr("框出要找文字的範圍", "Drag the area to search")),
               none_text=tr("未設定（辨識整個視窗，較慢）", "Not set (whole window, slower)"))
    f.choice("on_not_found", tr("找不到時", "When not found"), _not_found_items(),
             hint=tr("「略過這一步」適合「有彈窗才按確定」這種情況", "'Skip this step' fits 'click OK only if the popup is there'"))
    f.position("fallback_point", tr("找不到時改點這裡", "Fallback position"), "point",
               tr("點一下找不到文字時要點的位置", "Click the fallback position"),
               none_text=tr("未設定（可不設）", "Not set (optional)"))
    f.ms("timeout_ms", tr("最多找多久", "Keep looking for"))
    _click_common(f, advanced_button=True)
    f.spin("nth", tr("第幾個符合的", "Which match"), advanced=True,
           hint=tr("0 = 最像的；1 = 由上往下第 1 個", "0 = best match; 1 = first in reading order"))
    f.spin("offset_x", tr("點擊位置水平偏移", "Click offset X"), tr(" 像素", " px"), advanced=True,
           hint=tr("以 100% 縮放的像素計，會依視窗縮放比例換算", "Pixels at 100 % scaling; scaled with the window DPI"))
    f.spin("offset_y", tr("點擊位置垂直偏移", "Click offset Y"), tr(" 像素", " px"), advanced=True)
    f.dspin("min_score", tr("最低辨識信心", "Minimum OCR score"), advanced=True)
    f.choice("upscale", tr("放大辨識", "Upscale"), _upscale_items(), advanced=True)
    f.ms("poll_ms", tr("重新辨識間隔", "Poll interval"), advanced=True)


def _type_code(f: StepForm) -> None:
    f.enum_choice("mode", tr("輸入方式", "Typing mode"), TypingMode,
                  hint=tr("注音輸入法會改寫按鍵時，請用「模擬鍵入」或「貼上」。",
                          "If an IME rewrites keystrokes, use simulated typing or paste."))
    f.switch("clear_first", tr("輸入前先清空", "Clear the box first"))
    f.enum_choice("clear_method", tr("清空方式", "How to clear"), ClearMethod)
    f.enum_choice("split", tr("拆成多格輸入", "Split into boxes"), SplitMode)
    f.text("separators", tr("分隔符號", "Separators"), "-_")
    groups = ",".join(str(g) for g in f.code_groups)
    sizes = QLineEdit(",".join(str(g) for g in f.step.params.group_sizes))
    sizes.setPlaceholderText(groups or "5,5,5")
    err = w.label("", "error")

    def apply_sizes(text: str) -> None:
        parsed = parse_sizes(text)
        err.setText("" if parsed is not None else tr("請輸入正整數，用逗號分隔，例如 5,5,5", "Enter positive numbers, e.g. 5,5,5"))
        if parsed is not None:
            f._set("group_sizes", parsed)

    sizes.textChanged.connect(apply_sizes)
    box = QWidget()
    v = QVBoxLayout(box)
    v.setContentsMargins(0, 0, 0, 0)
    v.addWidget(sizes)
    v.addWidget(err)
    f._add("group_sizes", tr("每段字數", "Group sizes"), box,
           hint=tr(f"留空 = 使用序號格式的分段（{groups or '未設定'}）", f"Empty = the code format's groups ({groups or 'none'})"))
    f.fields["group_sizes_edit"] = sizes
    f.enum_choice("between", tr("段與段之間", "Between segments"), BetweenSegments)
    f.switch("strip_separators", tr("輸入前移除分隔符號", "Remove separators before typing"))
    f.position("verify_region", tr("核對範圍", "Verify region"), "region",
               tr("框出序號輸入框（輸入後用文字辨識核對）", "Drag around the code box (checked by OCR after typing)"),
               none_text=tr("未設定（可不設）", "Not set (optional)"),
               hint=tr("設定後會辨識輸入框的內容，跟序號不符就停下來，避免輸入法改寫。",
                       "When set, the box is read after typing and a mismatch stops the code."))
    f.ms("after_ms", tr("輸入後等待", "Wait after typing"))
    f.ms("key_delay_ms", tr("每個字的間隔", "Delay between keys"), advanced=True)
    f.ms("hold_ms", tr("按鍵按住時間", "Key hold time"), advanced=True,
         hint=tr("遊戲模式建議 20–30 毫秒", "Game mode: 20-30 ms recommended"))


def _type_text(f: StepForm) -> None:
    f.text("text", tr("要輸入的文字", "Text to type"), "/redeem {code}",
           hint=tr("可用 {code}（序號）、{index}（第幾筆）、{date}、{time}", "Placeholders: {code}, {index}, {date}, {time}"))
    f.enum_choice("mode", tr("輸入方式", "Typing mode"), TypingMode)
    f.switch("clear_first", tr("輸入前先清空", "Clear the box first"))
    f.enum_choice("clear_method", tr("清空方式", "How to clear"), ClearMethod)
    f.ms("after_ms", tr("輸入後等待", "Wait after typing"))
    f.ms("key_delay_ms", tr("每個字的間隔", "Delay between keys"), advanced=True)
    f.ms("hold_ms", tr("按鍵按住時間", "Key hold time"), advanced=True)


def _key(f: StepForm) -> None:
    edit = QLineEdit(f.step.params.keys)
    edit.setPlaceholderText("Enter")
    msg = w.label("", "muted")
    msg.setWordWrap(True)

    def check(text: str) -> None:
        try:
            canon = normalize_combo(text)
        except ValueError:
            msg.setProperty("role", "error")
            msg.setText(tr("無法辨識的按鍵；例如 Enter、Esc、Tab、Ctrl+A、Shift+Tab", "Unrecognised keys; e.g. Enter, Esc, Tab, Ctrl+A, Shift+Tab"))
            f._set("keys", clean_text(text).strip())
        else:
            level, reason = combo_risk(canon)
            msg.setProperty("role", "error" if level is IssueLevel.ERROR else "muted")
            msg.setText(reason or tr("例如 Enter、Esc、Tab、Ctrl+A、Shift+Tab", "e.g. Enter, Esc, Tab, Ctrl+A, Shift+Tab"))
            f._set("keys", canon)
        msg.style().unpolish(msg)
        msg.style().polish(msg)

    edit.textChanged.connect(check)
    edit.editingFinished.connect(lambda: edit.setText(f.step.params.keys))
    box = QWidget()
    v = QVBoxLayout(box)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(2)
    v.addWidget(edit)
    v.addWidget(msg)
    f._add("keys", tr("按鍵或組合鍵", "Key or shortcut"), box)
    f.fields["keys_edit"] = edit
    check(edit.text())
    f.spin("repeat", tr("按幾次", "Repeat"))
    f.ms("after_ms", tr("按完後等待", "Wait afterwards"))
    f.ms("interval_ms", tr("每次間隔", "Interval"), advanced=True)
    f.ms("hold_ms", tr("按住時間", "Hold time"), advanced=True)


def _wait(f: StepForm) -> None:
    f.ms("ms", tr("等待", "Wait"))
    f.spin("jitter_pct", tr("隨機增減", "Random ±"), " %", hint=tr("每次在 ±N% 內隨機", "Random within ±N % each time"))


def _wait_text(f: StepForm) -> None:
    f.text("text", tr("要等的文字", "Text to wait for"), tr("兌換", "Redeem"),
           hint=tr("多個候選用 | 分隔", "Separate alternatives with |"))
    f.enum_choice("match", tr("比對方式", "Matching"), TextMatch)
    f.choice("appear", tr("等到", "Wait until"), [(True, tr("文字出現", "the text appears")),
                                                 (False, tr("文字消失", "the text disappears"))])
    f.position("region", tr("搜尋範圍", "Search region"), "region",
               f.instruction(tr("框出要找文字的範圍", "Drag the area to search")),
               none_text=tr("未設定（辨識整個視窗，較慢）", "Not set (whole window, slower)"))
    f.ms("timeout_ms", tr("最多等待", "Timeout"))
    f.choice("on_timeout", tr("逾時時", "On timeout"), [(TimeoutAction.FAIL, tr("視為失敗", "Treat as failure")),
                                                      (TimeoutAction.CONTINUE, tr("繼續下一步", "Continue"))])
    f.ms("poll_ms", tr("重新辨識間隔", "Poll interval"), advanced=True)
    f.choice("upscale", tr("放大辨識", "Upscale"), _upscale_items(), advanced=True)


def _ocr_check(f: StepForm) -> None:
    f.position("region", tr("結果範圍", "Result region"), "region",
               f.instruction(tr("框出結果訊息出現的範圍", "Drag around where the result message appears")),
               required=True, none_text=tr("未設定（必填）", "Not set (required)"))
    f.switch("only_new_text", tr("只看送出後新出現的文字", "Only text that appears after submitting"),
             hint=tr("忽略畫面上本來就有的文字與上一筆的訊息；結果訊息每次都一模一樣的頁面請關閉。",
                     "Ignores static text and the previous message; turn off for pages that show the same text every time."))
    f.ms("initial_delay_ms", tr("送出後先等", "Wait before reading"))
    f.ms("timeout_ms", tr("最多等待結果", "Wait for the result up to"))
    f.switch("save_evidence", tr("保存結果截圖", "Save a result screenshot"))
    f.ms("poll_ms", tr("重新辨識間隔", "Poll interval"), advanced=True)
    f.choice("upscale", tr("放大辨識", "Upscale"), _upscale_items(), advanced=True)


def _unknown(f: StepForm) -> None:
    name = getattr(f.step.params, "type_name", "")
    note = w.label(tr(f"這是較新版本的步驟類型「{name}」。這個版本會略過它，但儲存時會保留內容。",
                      f"Step type '{name}' comes from a newer version. It is skipped here but kept when saving."),
                   "muted")
    note.setWordWrap(True)
    f._add("unknown", tr("說明", "Note"), note)


_BUILDERS: dict[StepType, Callable[[StepForm], None]] = {
    StepType.FOCUS_WINDOW: _focus,
    StepType.CLICK_POINT: _click_point,
    StepType.CLICK_TEXT: _click_text,
    StepType.TYPE_CODE: _type_code,
    StepType.TYPE_TEXT: _type_text,
    StepType.KEY: _key,
    StepType.WAIT: _wait,
    StepType.WAIT_TEXT: _wait_text,
    StepType.OCR_CHECK: _ocr_check,
    StepType.UNKNOWN: _unknown,
}

__all__ = ["DoubleSpinBox", "PositionField", "SpinBox", "StepForm", "anchor_labels", "parse_sizes"]
