# OWNED BY G7
"""設定精靈 / 重新對準 (SPEC 6.4.2; private helper of ui.profiles_page).

A sequence of the normal pickers, cancellable at any point (the setup checklist remains):
1. 選擇目標視窗 (WindowPickerDialog; browsers keep a title keyword the user may shorten),
2. every ``missing_setup()`` position and result region in step order - with ``realign`` every
   recorded position (re-pick or keep), instruction = the step's display_title(),
3. 「結果視窗怎麼關？」 (按確定 -> click_text 確定|OK with on_not_found continue / 按 Esc ->
   key Esc / 不用關),
4. 預覽點位, 5. 測試一筆 (with a paste box for one real code when the queue has none for this
   game; the code is queued for the profile's game).
Every finished step is saved at once, so a cancel keeps what was set up so far. The UI parts are
methods (``choose_window``, ``ask_position``, ``pick_position``, ``ask_close_choice``,
``preview``, ``ask_test``, ``start_test``) so tests can script them.
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


def position_items(profile: Profile, realign: bool) -> list[PositionItem]:
    """Positions the wizard asks for, in step order."""
    out: list[PositionItem] = []
    missing = set(profile.missing_setup())
    for i, step in profile.enabled_steps():
        p = step.params
        title = step.display_title()
        cands: list[tuple[str, str, str]] = []
        if isinstance(p, ClickPointParams):
            cands.append(("point", "point", title))
        elif isinstance(p, OcrCheckParams):
            cands.append(("region", "region", title))
        elif realign and isinstance(p, ClickTextParams):
            cands += [("region", "region", tr(f"{title}：搜尋範圍", f"{title}: search region")),
                      ("fallback_point", "point", tr(f"{title}：找不到時改點的位置", f"{title}: fallback position"))]
        elif realign and isinstance(p, TypeCodeParams):
            cands.append(("verify_region", "region", tr(f"{title}：核對範圍", f"{title}: verify region")))
        elif realign and isinstance(p, WaitTextParams):
            cands.append(("region", "region", tr(f"{title}：搜尋範圍", f"{title}: search region")))
        for name, kind, text in cands:
            value = getattr(p, name)
            if realign and (value is not None or (i, name) in missing):
                out.append(PositionItem(i, name, kind, text, value is not None))
            elif not realign and (i, name) in missing:
                out.append(PositionItem(i, name, kind, text, False))
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
        step.label, step.label_en = "關閉結果視窗（按確定）", "Close the result (OK)"
    else:
        step = make_step(StepType.KEY)
        step.params.keys = "Esc"  # type: ignore[union-attr]
        step.label, step.label_en = "關閉結果視窗（按 Esc）", "Close the result (Esc)"
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
        if self._need_target():
            if not self._step_target():
                return False
        items = position_items(self.profile, self.realign)
        for n, item in enumerate(items, 1):
            if not self._step_position(n, len(items), item):
                return False
        if any(s.type is StepType.OCR_CHECK for _i, s in self.profile.enabled_steps()):
            current = find_close_step(self.profile)[1]
            choice = self.ask_close_choice(current)
            if choice is None:
                return False
            apply_close_choice(self.profile, choice)
            self._save("close")
        self.log.append("preview")
        self.preview()
        return self._step_test()

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

        return pick_target_window(self.ctx, self.profile.target, self.parent, suggested_exe=self.profile.suggested_exe)

    def ask_title_keyword(self, keyword: str) -> str | None:
        dlg = _KeywordDialog(keyword, self.parent)
        try:
            return dlg.keyword() if dlg.exec() == QDialog.DialogCode.Accepted else None
        finally:
            dlg.deleteLater()

    def ask_position(self, n: int, total: int, item: PositionItem) -> str:
        dlg = _PositionDialog(n, total, item, self.realign, self.parent)
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
        dlg = _CloseDialog(current, self.parent)
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
        dlg = _TestDialog(p, item.code if item else "", self.parent)
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


def _buttons(dlg: QDialog, lay: QVBoxLayout, specs: list[tuple[str, str, str]]) -> None:
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
    def __init__(self, n: int, total: int, item: PositionItem, realign: bool, parent: QWidget | None) -> None:
        super().__init__(parent)
        self.answer = "cancel"
        title = tr("重新對準", "Re-align") if realign else tr("設定精靈", "Setup wizard")
        self.setWindowTitle(f"{title} · {n}/{total}")
        self.setMinimumWidth(480)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)
        lay.addWidget(w.label(tr(f"第 {item.step_index + 1} 步：{item.instruction}",
                                 f"Step {item.step_index + 1}: {item.instruction}"), "title"))
        how = (tr("按「開始點選」後畫面會凍結，請在目標視窗上點一下這個位置。Esc 可取消。",
                  "After 'Pick' the screen freezes; click this position on the target window. Esc cancels.")
               if item.kind == "point" else
               tr("按「開始框選」後畫面會凍結，請按住滑鼠拖曳框出這個範圍。Esc 可取消。",
                  "After 'Drag' the screen freezes; hold the mouse button and drag around this area. Esc cancels."))
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
    def __init__(self, current: str, parent: QWidget | None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("設定精靈", "Setup wizard"))
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(8)
        lay.addWidget(w.label(tr("結果視窗怎麼關？", "How is the result closed?"), "title"))
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
    def __init__(self, keyword: str, parent: QWidget | None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("標題關鍵字", "Title keyword"))
        self.setMinimumWidth(480)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(8)
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
    def __init__(self, profile: Profile, queued_code: str, parent: QWidget | None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("測試一筆", "Test one"))
        self.setMinimumWidth(500)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(8)
        lay.addWidget(w.label(tr("用一筆真的序號測試", "Test with one real code"), "title"))
        game = profile.game or profile.name
        self.edit: QLineEdit | None = None
        if queued_code:
            text = tr(f"會用佇列中的第一筆序號「{queued_code}」實際跑一次，並把讀到的結果給你看。",
                      f"The first queued code '{queued_code}' is run once and the result it reads is shown.")
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
           "find_close_step", "position_items"]
