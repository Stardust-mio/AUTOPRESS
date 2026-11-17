# OWNED BY G7
"""Dialogs of the Profiles page (private helper of ui.profiles_page): the Save / Discard /
Cancel prompt, the template gallery, the import safety card (PX-01 / PX-17) and the export
title-keyword question."""

from __future__ import annotations

from collections.abc import Sequence

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr
from ..models import PROFILE_SCHEMA_VERSION, CodeFormat, Profile
from . import widgets as w

# ----------------------------------------------------------------------------- texts


def newer_profile_text() -> str:
    """SPEC 7.1 'newer profile'."""
    return tr("此設定檔來自較新版本，部分內容可能被略過；儲存後這些內容會遺失。",
              "This profile comes from a newer version; some content may be skipped and is lost when you save.")


def import_warning_text() -> str:
    """SPEC 7.1 'import summary' (card text)."""
    return tr("這個設定檔會對你選的視窗送出下列按鍵與文字。只匯入你信任的人分享的設定檔。",
              "This profile sends the keys and text below to the window you pick. "
              "Import profiles only from people you trust.")


def format_summary(fmt: CodeFormat) -> str:
    label = fmt.id
    try:
        from ..codes import presets

        label = presets.format_label(fmt.id)
    except Exception:  # G1 stub
        pass
    groups = "-".join(str(g) for g in fmt.groups)
    extra = tr(f"，分段 {groups}", f", groups {groups}") if groups else ""
    return tr(f"{label}（字元 {fmt.charset}，長度 {fmt.min_len}–{fmt.max_len}{extra}）",
              f"{label} (characters {fmt.charset}, length {fmt.min_len}-{fmt.max_len}{extra})")


# ----------------------------------------------------------------------------- save prompt


def ask_save_changes(parent: QWidget | None, name: str) -> str:
    """"save" | "discard" | "cancel" for a profile with unsaved changes."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(tr("未儲存的變更", "Unsaved changes"))
    box.setText(tr(f"設定檔「{name}」有未儲存的變更，要儲存嗎？", f"The profile '{name}' has unsaved changes. Save them?"))
    save = box.addButton(tr("儲存", "Save"), QMessageBox.ButtonRole.AcceptRole)
    discard = box.addButton(tr("不儲存", "Discard"), QMessageBox.ButtonRole.DestructiveRole)
    cancel = box.addButton(tr("取消", "Cancel"), QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(save)
    box.setEscapeButton(cancel)
    box.exec()
    clicked = box.clickedButton()
    if clicked is save:
        return "save"
    if clicked is discard:
        return "discard"
    return "cancel"


# ----------------------------------------------------------------------------- gallery


class TemplateGallery(QWidget):
    """Cards for the built-in templates plus 「從空白開始」; ``chosen(template or None)``."""

    chosen = pyqtSignal(object)

    def __init__(self, templates: Sequence[Profile], parent: QWidget | None = None, show_header: bool = True) -> None:
        super().__init__(parent)
        self.templates = list(templates)
        self.buttons: list[object] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)
        if show_header:
            outer.addWidget(w.label(tr("從範本開始", "Start from a template"), "display"))
            sub = w.label(tr("選一個最接近的範本，接著精靈會帶你選目標視窗、點選位置並測試一筆。"
                             "有官方兌換網頁的遊戲，建議優先用網頁兌換。",
                             "Pick the closest template; the wizard then helps you choose the window, pick the "
                             "positions and test one code. Prefer the official web redeem page when there is one."),
                          "muted")
            sub.setWordWrap(True)
            outer.addWidget(sub)
        grid = QGridLayout()
        grid.setSpacing(12)
        items: list[Profile | None] = [*self.templates, None]
        for n, tpl in enumerate(items):
            grid.addWidget(self._card(tpl), n // 2, n % 2)
        outer.addLayout(grid)
        if not self.templates:
            note = w.label(tr("找不到內建範本（resources/templates），可以從空白開始。",
                              "No built-in templates were found; start from a blank profile."), "muted")
            note.setWordWrap(True)
            outer.addWidget(note)
        outer.addStretch(1)

    def _card(self, tpl: Profile | None) -> QWidget:
        card = w.Card(True, None, 6)
        lay = card.layout()
        if tpl is None:
            title, desc = tr("從空白開始", "Start from blank"), tr(
                "自己決定每一個步驟：點擊位置、輸入序號、按 Enter、辨識結果。",
                "Build the steps yourself: click, type the code, press Enter, read the result.")
        else:
            info = tpl.template
            title = info.title() if info and info.title() else tpl.name
            desc = info.description() if info and info.description() else tpl.description
        t = w.label(title, "title")
        t.setWordWrap(True)
        lay.addWidget(t)
        d = w.label(desc, "muted")
        d.setWordWrap(True)
        lay.addWidget(d)
        if tpl is not None:
            steps = len([s for s in tpl.steps if s.enabled])
            meta = w.label(tr(f"{steps} 個步驟 · {format_summary(tpl.code_format)}",
                              f"{steps} steps · {format_summary(tpl.code_format)}"), "caption")
            meta.setWordWrap(True)
            lay.addWidget(meta)
        lay.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        btn = w.push_button(tr("使用這個範本", "Use this template") if tpl is not None else tr("從空白開始", "Start blank"),
                            "primary" if tpl is not None and tpl is self.templates[0] else "secondary")
        btn.clicked.connect(lambda _c=False, t=tpl: self.chosen.emit(t))
        row.addWidget(btn)
        lay.addLayout(row)
        self.buttons.append(btn)
        return card


class GalleryDialog(QDialog):
    def __init__(self, templates: Sequence[Profile], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("從範本新增設定檔", "New profile from a template"))
        self.setMinimumSize(760, 520)
        self.result_template: Profile | None = None
        self.result_blank = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.gallery = TemplateGallery(templates)
        self.gallery.chosen.connect(self._chosen)
        scroll.setWidget(self.gallery)
        lay.addWidget(scroll, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = w.push_button(tr("取消", "Cancel"), "secondary")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        lay.addLayout(row)

    def _chosen(self, tpl: object) -> None:
        self.result_template = tpl if isinstance(tpl, Profile) else None
        self.result_blank = tpl is None
        self.accept()


def choose_template(templates: Sequence[Profile], parent: QWidget | None) -> tuple[bool, Profile | None]:
    """(accepted, template or None for blank)."""
    dlg = GalleryDialog(templates, parent)
    try:
        ok = dlg.exec() == QDialog.DialogCode.Accepted
        return ok, dlg.result_template
    finally:
        dlg.deleteLater()


# ----------------------------------------------------------------------------- import card


class ImportCardDialog(QDialog):
    """Literal summary of a shared profile; 匯入 only after 「我看得懂這些動作」 (PX-01)."""

    def __init__(self, profile: Profile, source_name: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.profile = profile
        self.setWindowTitle(tr("匯入設定檔", "Import profile"))
        self.setMinimumSize(620, 520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)
        lay.addWidget(w.label(tr(f"匯入「{profile.name or source_name}」", f"Import '{profile.name or source_name}'"),
                              "title"))
        self.banner = w.Banner("warning", import_warning_text(), "", False)
        lay.addWidget(self.banner)
        if profile.schema_version > PROFILE_SCHEMA_VERSION:
            lay.addWidget(w.Banner("warning", newer_profile_text(), "", False))
        meta = []
        if profile.game:
            meta.append(tr(f"遊戲：{profile.game}", f"Game: {profile.game}"))
        if profile.author:
            meta.append(tr(f"作者：{profile.author}", f"Author: {profile.author}"))
        if profile.description:
            meta.append(profile.description)
        if meta:
            m = w.label("\n".join(meta), "secondary")
            m.setWordWrap(True)
            lay.addWidget(m)

        lay.addWidget(w.label(tr("這個設定檔的動作（依順序）", "What this profile does (in order)"), "caption"))
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        self.action_labels: list[tuple[str, bool]] = []
        lines = profile.action_lines()
        for text, risky in lines:
            lb = w.label(("⚠ " if risky else "") + text, "error" if risky else "body")
            lb.setWordWrap(True)
            lb.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            if risky:
                lb.setToolTip(tr("請特別注意：這一行可能切換分頁、開網址列，或每次都輸入同樣的文字。",
                                 "Check this line: it may switch tabs, open the address bar or type fixed text."))
            v.addWidget(lb)
            self.action_labels.append((text, risky))
        if not lines:
            v.addWidget(w.label(tr("（沒有任何啟用的步驟）", "(no enabled steps)"), "muted"))
        self.policy_labels: list[tuple[str, bool]] = profile.policy_lines()  # gate G-02: changed safety stops
        if self.policy_labels:
            v.addSpacing(6)
            v.addWidget(w.label(tr("與預設不同的執行規則", "Run rules that differ from the defaults"), "caption"))
            for text, risky in self.policy_labels:
                lb = w.label(("⚠ " if risky else "") + text, "error" if risky else "body")
                lb.setWordWrap(True)
                if risky:
                    lb.setToolTip(tr("請特別注意：這條規則關掉或放寬了安全停止。",
                                     "Check this rule: it switches off or loosens a safety stop."))
                v.addWidget(lb)
        v.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(box)
        lay.addWidget(scroll, 1)

        exe = profile.suggested_exe
        target_text = (tr(f"作者使用的程式：{exe}（只是提示；匯入後要自己選目標視窗）",
                          f"The author's program: {exe} (a hint only; you pick the target window after importing)")
                       if exe else tr("匯入後要自己選目標視窗。", "You pick the target window after importing."))
        t = w.label(target_text, "secondary")
        t.setWordWrap(True)
        lay.addWidget(t)
        f = w.label(tr("序號格式：", "Code format: ") + format_summary(profile.code_format), "secondary")
        f.setWordWrap(True)
        lay.addWidget(f)

        self.check = QCheckBox(tr("我看得懂這些動作", "I understand these actions"))
        self.check.toggled.connect(self._update)
        lay.addWidget(self.check)
        row = QHBoxLayout()
        row.addStretch(1)
        self.cancel_btn = w.push_button(tr("取消", "Cancel"), "secondary")
        self.cancel_btn.clicked.connect(self.reject)
        self.import_btn = w.push_button(tr("匯入", "Import"), "primary")
        self.import_btn.clicked.connect(self.accept)
        row.addWidget(self.cancel_btn)
        row.addWidget(self.import_btn)
        lay.addLayout(row)
        self._update()

    def _update(self) -> None:
        self.import_btn.setEnabled(self.check.isChecked())
        self.import_btn.setDefault(self.check.isChecked())

    def accept(self) -> None:  # noqa: D401 - Qt override
        if self.check.isChecked():
            super().accept()


def confirm_import(profile: Profile, source_name: str, parent: QWidget | None) -> bool:
    dlg = ImportCardDialog(profile, source_name, parent)
    try:
        return dlg.exec() == QDialog.DialogCode.Accepted
    finally:
        dlg.deleteLater()


# ----------------------------------------------------------------------------- export


class ExportKeywordDialog(QDialog):
    def __init__(self, profile: Profile, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("匯出設定檔", "Export profile"))
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)
        lay.addWidget(w.label(tr(f"匯出「{profile.name}」", f"Export '{profile.name}'"), "title"))
        info = w.label(tr("分享的檔案不含你的序號、紀錄和截圖，也不含目標視窗的完整標題。"
                          "可以填一個簡短的標題關鍵字（例如「兌換」）讓別人比較好找到視窗；"
                          "不要填帳號或角色名稱。可以留空。",
                          "The shared file never contains your codes, history, screenshots or the full window "
                          "title. You may add a short title keyword (e.g. 'Redeem') to help others find the "
                          "window - never an account or character name. It may stay empty."), "muted")
        info.setWordWrap(True)
        lay.addWidget(info)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(tr("標題關鍵字（可留空）", "Title keyword (optional)"))
        self.edit.setMaxLength(60)
        lay.addWidget(w.form_row(tr("標題關鍵字", "Title keyword"), self.edit))
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = w.push_button(tr("取消", "Cancel"), "secondary")
        cancel.clicked.connect(self.reject)
        ok = w.push_button(tr("選擇存檔位置…", "Choose file…"), "primary")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)

    def keyword(self) -> str:
        from ..textutil import clean_text

        return clean_text(self.edit.text()).strip()


def ask_export_keyword(profile: Profile, parent: QWidget | None) -> str | None:
    """The optional title keyword, or None when cancelled."""
    dlg = ExportKeywordDialog(profile, parent)
    try:
        return dlg.keyword() if dlg.exec() == QDialog.DialogCode.Accepted else None
    finally:
        dlg.deleteLater()


__all__ = [
    "ExportKeywordDialog",
    "GalleryDialog",
    "ImportCardDialog",
    "TemplateGallery",
    "ask_export_keyword",
    "ask_save_changes",
    "choose_template",
    "confirm_import",
    "format_summary",
    "import_warning_text",
    "newer_profile_text",
]
