# OWNED BY G7
"""設定精靈 / 重新對準 (SPEC 6.4.2; private helper of ui.profiles_page).

A sequence of the normal pickers, cancellable at any point (the setup checklist remains):
1. 選擇目標視窗 (WindowPickerDialog; browsers keep a title keyword the user may shorten),
2. every ``missing_setup()`` position and result region in step order - with ``realign`` every
   recorded position (re-pick or keep), instruction = the step's own title, or for an untitled step
   what to pick (「點選第 2 步要點擊的位置」, 「框出結果訊息的範圍」),
3. 「選擇結果視窗的關閉方式」 (按確定 -> click_text 確定|OK with on_not_found continue / 按 Esc ->
   key Esc / 不用關),
4. 預覽點位, 5. 測試一筆 (with a paste box for one real code when the queue has none for this
   game; the code is queued for the profile's game).
Every finished step is saved at once, so a cancel keeps what was set up so far. The UI parts are
methods (``choose_window``, ``ask_position``, ``pick_position``, ``ask_close_choice``,
``preview``, ``ask_test``, ``start_test``) so tests can script them.

Progress (U39): ``run`` counts the screens up front (target if needed + positions + close choice
if an ocr_check step + test) and every wizard dialog shows 「設定精靈 k/n」 (「重新對準 k/n」) as a
small caption above its heading; the position dialog's heading is the instruction itself, with
the profile step it belongs to on a muted line under it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from PyQt6.QtWidgets import QButtonGroup, QDialog, QHBoxLayout, QLineEdit, QRadioButton, QVBoxLayout, QWidget

from ..i18n import tr
from ..models import (
    ClickPointParams,
    ClickTextParams,
    ClientPoint,
    CodeSource,
    KeyParams,
    OcrCheckParams,
    PlanMode,
    Profile,
    StepType,
    TimeoutAction,
    TypeCodeParams,
    WaitTextParams,
    make_step,
)
from ..textutil import clean_text
from . import widgets as w

if TYPE_CHECKING:
    from .profiles_page import ProfilesPage

log = logging.getLogger(__name__)

CLOSE_OK, CLOSE_ESC, CLOSE_NONE = "ok", "esc", "none"


@dataclass
class PositionItem:
    step_index: int
    field: str  # parameter name: point, region, fallback_point, verify_region
    kind: str  # "point" | "region"
    instruction: str
    has_value: bool
    step_label: str = ""  # the step type's name, e.g. 「點擊位置」 (muted line of the dialog)


def progress_text(progress: tuple[int, int] | None, realign: bool = False) -> str:
    """「設定精靈 2/5」 / 「重新對準 2/5」 ("" without progress)."""
    if not progress:
        return ""
    k, total = progress
    title = tr("重新對準", "Re-align") if realign else tr("設定精靈", "Setup wizard")
    return f"{title} {k}/{total}"


def untitled_instruction(n: int, params: Any, field: str) -> str:
    """The instruction for a position of step ``n`` (1-based) that has no title of its own (e.g. a
    step added 「從空白開始」): what to pick, as an imperative like a template's step name, instead
    of the bare step type (UI review U39)."""
    if isinstance(params, OcrCheckParams):  # the templates' name for this step
        return tr("框出結果訊息的範圍", "Drag over the result message area")
    if field == "fallback_point":
        return tr(f"點選第 {n} 步找不到文字時改點的位置", f"Pick where step {n} clicks when its text is not found")
    if field == "verify_region":
        return tr(f"框出第 {n} 步要核對的輸入框", f"Drag over the input box that step {n} checks")
    if field == "region":
        return tr(f"框出第 {n} 步找文字的範圍", f"Drag over the area where step {n} looks for its text")
    return tr(f"點選第 {n} 步要點擊的位置", f"Pick the position that step {n} clicks")


def _instruction(step: Any, n: int, field: str, part_zh: str = "", part_en: str = "") -> str:
    """The step's own title (+ 「：part」), or ``untitled_instruction`` for a step without one."""
    if not (step.label.strip() or step.label_en.strip()):
        return untitled_instruction(n, step.params, field)
    title = step.display_title()
    return tr(f"{title}：{part_zh}", f"{title}: {part_en}") if part_zh else title


def position_items(profile: Profile, realign: bool) -> list[PositionItem]:
    """Positions the wizard asks for, in step order. A step with its own title (every template
    step) is the instruction; an untitled step gets ``untitled_instruction``."""
    out: list[PositionItem] = []
    missing = set(profile.missing_setup())
    for i, step in profile.enabled_steps():
        p = step.params
        cands: list[tuple[str, str, str]] = []
        if isinstance(p, ClickPointParams):
            cands.append(("point", "point", _instruction(step, i + 1, "point")))
        elif isinstance(p, OcrCheckParams):
            cands.append(("region", "region", _instruction(step, i + 1, "region")))
        elif realign and isinstance(p, ClickTextParams):
            cands += [("region", "region", _instruction(step, i + 1, "region", "搜尋範圍", "search region")),
                      ("fallback_point", "point",
                       _instruction(step, i + 1, "fallback_point", "找不到時改點的位置", "fallback position"))]
        elif realign and isinstance(p, TypeCodeParams):
            cands.append(("verify_region", "region",
                          _instruction(step, i + 1, "verify_region", "核對範圍", "verify region")))
        elif realign and isinstance(p, WaitTextParams):
            cands.append(("region", "region", _instruction(step, i + 1, "region", "搜尋範圍", "search region")))
        for name, kind, text in cands:
            value = getattr(p, name)
            if realign and (value is not None or (i, name) in missing):
                out.append(PositionItem(i, name, kind, text, value is not None, step.type.label()))
            elif not realign and (i, name) in missing:
                out.append(PositionItem(i, name, kind, text, False, step.type.label()))
    return out


def find_close_step(profile: Profile) -> tuple[int, str]:
    """(index, choice) of the step that closes the result after the last ocr_check: a
    click_text with on_not_found continue (CLOSE_OK) or a key Esc (CLOSE_ESC); (-1, CLOSE_NONE)."""
    checks = [i for i, s in enumerate(profile.steps) if s.type is StepType.OCR_CHECK and s.enabled]
    start = checks[-1] + 1 if checks else 0
    for i in range(start, len(profile.steps)):
        s = profile.steps[i]
        if not s.enabled:
            continue
        if isinstance(s.params, ClickTextParams) and s.params.on_not_found is TimeoutAction.CONTINUE:
            return i, CLOSE_OK
        if isinstance(s.params, KeyParams) and s.params.keys.casefold() in ("esc", "escape"):
            return i, CLOSE_ESC
    return -1, CLOSE_NONE


def apply_close_choice(profile: Profile, choice: str) -> None:
    """Make the profile close the result as chosen (replace / insert / remove one step)."""
    idx, current = find_close_step(profile)
    if choice == current:
        return
    if choice == CLOSE_NONE:
        if idx >= 0:
            del profile.steps[idx]
        return
    if choice == CLOSE_OK:
        step = make_step(StepType.CLICK_TEXT)
        step.params.text = "確定|OK"  # type: ignore[union-attr]
        step.params.on_not_found = TimeoutAction.CONTINUE  # type: ignore[union-attr]
        step.label, step.label_en = "關閉結果（按確定）", "Close result (OK)"
    else:
        step = make_step(StepType.KEY)
        step.params.keys = "Esc"  # type: ignore[union-attr]
        step.label, step.label_en = "關閉結果（按 Esc）", "Close result (Esc)"
    if idx >= 0:
        profile.steps[idx] = step
        return
    checks = [i for i, s in enumerate(profile.steps) if s.type is StepType.OCR_CHECK and s.enabled]
    profile.steps.insert(checks[-1] + 1 if checks else len(profile.steps), step)


class SetupWizard:
    def __init__(self, page: ProfilesPage, profile_id: str, realign: bool = False) -> None:
        self.page = page
        self.ctx = page.ctx
        self.profile_id = profile_id
        self.realign = realign
        self.log: list[str] = []  # steps done (tests)
        self.progress: tuple[int, int] | None = None  # (screen k, of n) shown by the current dialog
        self.progress_log: list[tuple[int, int]] = []  # every progress value shown (tests)

    @property
    def profile(self) -> Profile:
        return self.page.working_profile()

    @property
    def parent(self) -> QWidget:
        return self.page.window()

    # -- the sequence ---------------------------------------------------------------------
    def run(self) -> bool:
        """True when the wizard reached its end (the test may still be running)."""
        p = self.profile
        if p is None:
            return False
        need_target = self._need_target()
        items = position_items(p, self.realign)  # positions do not depend on the target
        has_close = any(s.type is StepType.OCR_CHECK for _i, s in p.enabled_steps())
        total = int(need_target) + len(items) + int(has_close) + 1  # + 測試一筆
        screen = iter(range(1, total + 1))
        if need_target:
            self._at(next(screen), total)
            if not self._step_target():
                return False
        for n, item in enumerate(items, 1):
            self._at(next(screen), total)
            if not self._step_position(n, len(items), item):
                return False
        if has_close:
            self._at(next(screen), total)
            current = find_close_step(self.profile)[1]
            choice = self.ask_close_choice(current)
            if choice is None:
                return False
            apply_close_choice(self.profile, choice)
            self._save("close")
        self.log.append("preview")
        self.preview()
        self._at(next(screen), total)
        return self._step_test()

    def _at(self, k: int, total: int) -> None:
        self.progress = (k, total)
        self.progress_log.append(self.progress)

    def caption(self) -> str:
        """「設定精靈 k/n」 for the dialog shown now ("" outside ``run``)."""
        return progress_text(self.progress, self.realign)

    def _need_target(self) -> bool:
        p = self.profile
        if p.target.is_empty() or p.target.is_forbidden() or p.target.needs_title():
            return True
        if self.realign:
            from .run_actions import find_target

            return find_target(p) is None
        return False

    def _step_target(self) -> bool:
        info = self.choose_window()
        if info is None:
            return False
        from .run_actions import target_from_window

        target = target_from_window(info)
        if target.is_browser():
            keyword = self.ask_title_keyword(target.title)
            if keyword is None:
                return False
            target.title = keyword
        self.page.set_target(target)
        self._save("target")
        return True

    def _step_position(self, n: int, total: int, item: PositionItem) -> bool:
        while True:
            answer = self.ask_position(n, total, item)
            if answer == "cancel":
                return False
            if answer == "skip":
                self.log.append(f"skip:{item.step_index}.{item.field}")
                return True
            value, err = self.pick_position(item)
            if value is not None:
                step = self.profile.steps[item.step_index]
                setattr(step.params, item.field, value)
                self.page.replace_step(item.step_index, step)
                self._save(f"{item.step_index}.{item.field}")
                return True
            if err:
                w.message(self.parent, tr("設定精靈", "Setup wizard"), err, "warning")
            # cancelled picker or error: ask again

    def _step_test(self) -> bool:
        answer = self.ask_test()
        if answer is None:
            self.log.append("test:skipped")
            return True
        kind, value = answer
        code_id = value
        if kind == "paste":
            code_id = self._queue_code(value)
            if code_id is None:
                return True
        self.log.append(f"test:{code_id}")
        self.start_test([code_id])
        return True

    def _queue_code(self, text: str) -> str | None:
        p = self.profile
        code = clean_text(text).strip()
        if not code:
            return None
        res = self.ctx.queue.add_codes([code], CodeSource.PASTE, fmt=p.code_format, game_key=p.game_key(),
                                       game=p.game, source_detail=tr("設定精靈", "Setup wizard"))
        if res.added:
            return res.added[0]
        item = self.ctx.queue.find_code(code, p.game_key())
        if item is not None and item.status.is_runnable:
            return item.id
        w.message(self.parent, tr("測試一筆", "Test one"),
                  tr("這個序號無法加入佇列（格式不符，或已經處理過）。", "This code cannot be queued (wrong format or already done)."),
                  "warning")
        return None

    def _save(self, what: str) -> None:
        self.log.append(what)
        self.page.save_profile(confirm_newer=False)

    # -- UI parts (scripted in tests) -----------------------------------------------------
    def choose_window(self) -> Any:
        from .window_picker import pick_target_window

        return pick_target_window(self.ctx, self.profile.target, self.parent, suggested_exe=self.profile.suggested_exe,
                                  caption=self.caption())

    def ask_title_keyword(self, keyword: str) -> str | None:
        dlg = _KeywordDialog(keyword, self.parent, progress=self.progress, realign=self.realign)
        try:
            return dlg.keyword() if dlg.exec() == QDialog.DialogCode.Accepted else None
        finally:
            dlg.deleteLater()

    def ask_position(self, n: int, total: int, item: PositionItem) -> str:
        dlg = _PositionDialog(n, total, item, self.realign, self.parent, progress=self.progress)
        try:
            dlg.exec()
            return dlg.answer
        finally:
            dlg.deleteLater()

    def pick_position(self, item: PositionItem) -> tuple[Any, str]:
        from .step_pick import hide_list, pick_point, pick_region

        hide = hide_list(self.page, getattr(self.ctx, "main_window", None))
        if item.kind == "point":
            old = getattr(self.profile.steps[item.step_index].params, item.field)
            anchor = old.anchor if isinstance(old, ClientPoint) else "tl"
            return pick_point(self.profile, item.instruction, anchor=anchor, hide=hide)
        return pick_region(self.profile, item.instruction, hide=hide)

    def ask_close_choice(self, current: str) -> str | None:
        dlg = _CloseDialog(current, self.parent, progress=self.progress, realign=self.realign)
        try:
            return dlg.choice() if dlg.exec() == QDialog.DialogCode.Accepted else None
        finally:
            dlg.deleteLater()

    def preview(self) -> None:
        from .run_actions import show_preview

        show_preview(self.ctx, self.profile, wait=True, parent=self.parent)

    def ask_test(self) -> tuple[str, str] | None:
        """("queue", code_id) / ("paste", code text) / None = later."""
        from .run_actions import first_runnable

        p = self.profile
        cid = first_runnable(self.ctx, p)
        item = self.ctx.queue.get(cid) if cid else None
        dlg = _TestDialog(p, item.code if item else "", self.parent, progress=self.progress, realign=self.realign)
        try:
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return None
            if item is not None:
                return "queue", item.id
            return "paste", dlg.code()
        finally:
            dlg.deleteLater()

    def start_test(self, code_ids: list[str]) -> bool:
        return bool(self.page.run_flow().begin(self.profile, mode=PlanMode.TEST_ONE, code_ids=code_ids))


# ----------------------------------------------------------------------------- dialogs


def _heading(dlg: QDialog, lay: QVBoxLayout, caption: str, title: str) -> None:
    """The progress caption (「設定精靈 2/5」, hidden when empty) right above the title: the same
    head on every wizard dialog. Sets ``dlg.caption`` and ``dlg.heading``."""
    head = QVBoxLayout()
    head.setSpacing(2)
    dlg.caption = w.label(caption, "caption")  # type: ignore[attr-defined]
    dlg.caption.setVisible(bool(caption))  # type: ignore[attr-defined]
    head.addWidget(dlg.caption)  # type: ignore[attr-defined]
    dlg.heading = w.label(title, "title")  # type: ignore[attr-defined]
    dlg.heading.setWordWrap(True)  # type: ignore[attr-defined]
    head.addWidget(dlg.heading)  # type: ignore[attr-defined]
    lay.addLayout(head)


def _buttons(dlg: QDialog, lay: QVBoxLayout, specs: list[tuple[str, str, str]]) -> None:
    lay.addStretch(1)  # spare height goes above the buttons, never into a label (same head everywhere)
    row = QHBoxLayout()
    row.addStretch(1)
    for text, variant, answer in specs:
        b = w.push_button(text, variant)
        b.clicked.connect(lambda _c=False, a=answer: dlg.done_with(a))  # type: ignore[attr-defined]
        if variant == "primary":
            b.setDefault(True)
        row.addWidget(b)
    lay.addLayout(row)


class _PositionDialog(QDialog):
    """One position to pick. ``n`` / ``total`` count the positions only; the caption shows the
    wizard's ``progress`` over all its screens (falls back to ``n`` / ``total``)."""

    def __init__(self, n: int, total: int, item: PositionItem, realign: bool, parent: QWidget | None,
                 *, progress: tuple[int, int] | None = None) -> None:
        super().__init__(parent)
        self.answer = "cancel"
        self.setWindowTitle(tr("重新對準", "Re-align") if realign else tr("設定精靈", "Setup wizard"))
        self.setMinimumWidth(480)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)
        _heading(self, lay, progress_text(progress or (n, total), realign), item.instruction)
        # the profile step this position belongs to (the step list's numbering), kept apart from the caption
        n_step = item.step_index + 1
        step = tr(f"設定檔的第 {n_step} 步", f"Step {n_step} of the profile")
        if item.step_label and item.step_label.strip() != item.instruction.strip():
            # a step without its own title already shows its type as the heading: not twice
            step += tr(f"：{item.step_label}", f": {item.step_label}")
        self.step_line = w.label(step, "secondary")
        lay.addWidget(self.step_line)
        # 「Esc 可取消。」 on a line of its own: at the dialog's width it otherwise wrapped as a lone 「消。」
        how = (tr("按「開始點選」後畫面會暫時定格，請在目標視窗上點一下這個位置。\nEsc 可取消。",
                  "After 'Pick' the screen pauses on a still image; click this position on the target window.\n"
                  "Esc cancels.")
               if item.kind == "point" else
               tr("按「開始框選」後畫面會暫時定格，請按住滑鼠拖曳框出這個範圍。\nEsc 可取消。",
                  "After 'Drag' the screen pauses on a still image; hold the mouse button and drag around this area.\n"
                  "Esc cancels."))
        hl = w.label(how, "muted")
        hl.setWordWrap(True)
        lay.addWidget(hl)
        specs = [(tr("取消精靈", "Cancel wizard"), "ghost", "cancel")]
        if item.has_value or realign:
            specs.append((tr("保留原位置", "Keep") if item.has_value else tr("略過", "Skip"), "secondary", "skip"))
        else:
            specs.append((tr("略過", "Skip"), "secondary", "skip"))
        specs.append((tr("開始點選", "Pick") if item.kind == "point" else tr("開始框選", "Drag"), "primary", "pick"))
        _buttons(self, lay, specs)

    def done_with(self, answer: str) -> None:
        self.answer = answer
        self.accept()


class _CloseDialog(QDialog):
    def __init__(self, current: str, parent: QWidget | None, *, progress: tuple[int, int] | None = None,
                 realign: bool = False) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("重新對準", "Re-align") if realign else tr("設定精靈", "Setup wizard"))
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(8)
        _heading(self, lay, progress_text(progress, realign), tr("選擇結果視窗的關閉方式", "Choose how the result is closed"))
        self.group = QButtonGroup(self)
        self.radios: dict[str, QRadioButton] = {}
        for key, text in ((CLOSE_OK, tr("按「確定」（找不到就略過）", "Click 'OK' (skipped when it is not there)")),
                          (CLOSE_ESC, tr("按 Esc", "Press Esc")),
                          (CLOSE_NONE, tr("不用關（結果不會擋住下一筆）", "No need (the result does not block the next code)"))):
            rb = QRadioButton(text)
            self.group.addButton(rb)
            self.radios[key] = rb
            lay.addWidget(rb)
        self.radios.get(current, self.radios[CLOSE_OK]).setChecked(True)
        _buttons(self, lay, [(tr("取消精靈", "Cancel wizard"), "ghost", "cancel"), (tr("下一步", "Next"), "primary", "ok")])

    def done_with(self, answer: str) -> None:
        if answer == "ok":
            self.accept()
        else:
            self.reject()

    def choice(self) -> str:
        return next((k for k, rb in self.radios.items() if rb.isChecked()), CLOSE_NONE)


class _KeywordDialog(QDialog):
    def __init__(self, keyword: str, parent: QWidget | None, *, progress: tuple[int, int] | None = None,
                 realign: bool = False) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("標題關鍵字", "Title keyword"))
        self.setMinimumWidth(480)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(8)
        _heading(self, lay, progress_text(progress, realign), tr("確認視窗標題的關鍵字", "Check the window title keyword"))
        info = w.label(tr("瀏覽器的每個分頁都是同一個程式，AutoPress 只會在視窗標題含有這個關鍵字時輸入。"
                          "可以縮短（例如只留「兌換」），但不能留空。",
                          "Every browser tab is the same program, so AutoPress only types while the window title "
                          "contains this keyword. You may shorten it (e.g. 'Redeem'), but not empty it."), "muted")
        info.setWordWrap(True)
        lay.addWidget(info)
        self.edit = QLineEdit(keyword)
        self.edit.setMaxLength(120)
        self.edit.textChanged.connect(self._update)
        lay.addWidget(self.edit)
        self.ok_btn = w.push_button(tr("確定", "OK"), "primary")
        self.ok_btn.clicked.connect(self.accept)
        cancel = w.push_button(tr("取消精靈", "Cancel wizard"), "ghost")
        cancel.clicked.connect(self.reject)
        lay.addStretch(1)  # spare height above the buttons (same head on every wizard dialog)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(self.ok_btn)
        lay.addLayout(row)
        self._update()

    def _update(self) -> None:
        self.ok_btn.setEnabled(bool(self.keyword()))

    def keyword(self) -> str:
        return clean_text(self.edit.text()).strip()


class _TestDialog(QDialog):
    def __init__(self, profile: Profile, queued_code: str, parent: QWidget | None, *,
                 progress: tuple[int, int] | None = None, realign: bool = False) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("測試一筆", "Test one"))
        self.setMinimumWidth(500)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(8)
        _heading(self, lay, progress_text(progress, realign), tr("用一筆真的序號測試", "Test with one real code"))
        game = profile.game or profile.name
        self.edit: QLineEdit | None = None
        if queued_code:
            text = tr(f"會用第一筆待兌換的序號「{queued_code}」實際跑一次，並把讀到的結果給你看。",
                      f"The first code waiting to be redeemed, '{queued_code}', is run once and the result it reads "
                      "is shown.")
        else:
            text = tr(f"佇列裡還沒有「{game}」的序號。貼上一個真的序號來測試（會加入佇列，屬於「{game}」）。",
                      f"There is no queued code for '{game}' yet. Paste one real code to test (it is queued for '{game}').")
        lb = w.label(text, "muted")
        lb.setWordWrap(True)
        lay.addWidget(lb)
        if not queued_code:
            self.edit = QLineEdit()
            self.edit.setPlaceholderText(tr("貼上一個序號", "Paste one code"))
            self.edit.textChanged.connect(self._update)
            lay.addWidget(self.edit)
        lay.addStretch(1)  # spare height above the buttons (same head on every wizard dialog)
        row = QHBoxLayout()
        row.addStretch(1)
        later = w.push_button(tr("稍後再說", "Later"), "ghost")
        later.clicked.connect(self.reject)
        self.ok_btn = w.push_button(tr("測試一筆", "Test one"), "primary")
        self.ok_btn.clicked.connect(self.accept)
        row.addWidget(later)
        row.addWidget(self.ok_btn)
        lay.addLayout(row)
        self._update()

    def _update(self) -> None:
        self.ok_btn.setEnabled(self.edit is None or bool(self.code()))

    def code(self) -> str:
        return clean_text(self.edit.text()).strip() if self.edit is not None else ""


__all__ = ["CLOSE_ESC", "CLOSE_NONE", "CLOSE_OK", "PositionItem", "SetupWizard", "apply_close_choice",
           "find_close_step", "position_items", "progress_text"]
