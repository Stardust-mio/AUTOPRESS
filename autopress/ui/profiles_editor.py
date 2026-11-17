# OWNED BY G7
"""Editor cards of the Profiles page (private helper of ui.profiles_page): basics (name, game
combo with a near-duplicate warning, description, author), 目標視窗, 序號格式, 座標模式,
執行規則 (RunPolicy). Each card edits the page's working Profile in place and calls
``on_change()``."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QComboBox, QFormLayout, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from ..context import AppContext
from ..i18n import tr
from ..models import (
    CodeFormat,
    CoordMode,
    Profile,
    RateLimitAction,
    TitleMatch,
    UnknownAction,
    clone,
)
from ..textutil import clean_text, levenshtein, squash
from . import theme
from . import widgets as w
from .step_forms import DoubleSpinBox, SpinBox, parse_sizes

log = logging.getLogger(__name__)

Change = Callable[[], None]


def known_game_names(ctx: AppContext, exclude_profile: str = "") -> list[str]:
    """Game names from the history, the queue and the other profiles (unique, sorted)."""
    names: list[str] = []

    def add(name: str) -> None:
        name = (name or "").strip()
        if name and name not in names:
            names.append(name)

    for source in (getattr(ctx.history, "games", None), getattr(ctx.queue, "games", None)):
        try:
            for _key, game in (source() if source else []):
                add(game)
        except Exception as exc:  # G1 stub
            log.debug("games() unavailable: %s", exc)
    try:
        for p in ctx.profiles.list():
            if p.id != exclude_profile:
                add(p.game)
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("profiles unavailable: %s", exc)
    return sorted(names, key=str.casefold)


def similar_game(name: str, known: Sequence[str]) -> str | None:
    """An existing game name that ``name`` is probably a variant of: same squash (different
    spelling of the same history key) or Levenshtein <= 2 between the squashed names (<= 1 when
    the shorter one has fewer than 4 characters). None for an exact match or no match."""
    s = squash(name)
    if not s or name.strip() in known:
        return None
    for k in known:
        ks = squash(k)
        if not ks:
            continue
        if ks == s:
            return k
        limit = 2 if min(len(ks), len(s)) >= 4 else 1
        if levenshtein(ks, s) <= limit:
            return k
    return None


def _form() -> QFormLayout:
    f = QFormLayout()
    f.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    f.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    f.setHorizontalSpacing(16)
    f.setVerticalSpacing(8)
    return f


def form_labels(forms: Sequence[QFormLayout]) -> list[QWidget]:
    """The label widgets of ``forms`` (rows without a label are skipped)."""
    out: list[QWidget] = []
    for f in forms:
        for row in range(f.rowCount()):
            item = f.itemAt(row, QFormLayout.ItemRole.LabelRole)
            if item is not None and item.widget() is not None:
                out.append(item.widget())
    return out


def align_form_labels(forms: Sequence[QFormLayout]) -> int:
    """Give every label of ``forms`` the width of the widest one, so the fields of the editor
    cards (basics, target, format, run rules) start at the same x (U35). Returns that width."""
    labels = form_labels(forms)
    for lb in labels:
        lb.setMinimumWidth(0)
        lb.ensurePolished()  # the role font (QSS) decides the width
    width = max((lb.sizeHint().width() for lb in labels), default=0)
    for lb in labels:
        lb.setMinimumWidth(width)
    return width


def _with_hint(widget: QWidget, hint: QWidget) -> QWidget:
    """``widget`` with a muted hint line under it (one form field)."""
    box = QWidget()
    v = QVBoxLayout(box)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(2)
    v.addWidget(widget)
    v.addWidget(hint)
    return box


def card(title: str, subtitle: str = "") -> tuple[QWidget, QVBoxLayout]:
    c = w.Card(True, None, 10)
    lay = c.layout()
    lay.addWidget(w.label(title, "title"))
    if subtitle:
        s = w.label(subtitle, "muted")
        s.setWordWrap(True)
        lay.addWidget(s)
    return c, lay


class BasicsCard(QWidget):
    def __init__(self, ctx: AppContext, on_change: Change, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.on_change = on_change
        self.profile: Profile | None = None
        self._loading = False
        self.known: list[str] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        c, lay = card(tr("基本資料", "Basics"))
        outer.addWidget(c)
        f = _form()
        self.name = QLineEdit()
        self.name.setMaxLength(80)
        self.name.setPlaceholderText(tr("例如：原神網頁兌換", "e.g. Genshin web redeem"))
        self.name.textChanged.connect(self._apply)
        f.addRow(w.label(tr("名稱", "Name"), "secondary"), self.name)
        self.game = QComboBox()
        self.game.setEditable(True)
        self.game.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.game.lineEdit().setPlaceholderText(tr("遊戲名稱（同一款遊戲的序號與紀錄會放在一起）",
                                                   "Game name (codes and history of one game belong together)"))
        self.game.currentTextChanged.connect(self._apply)
        game_box = QWidget()
        gv = QVBoxLayout(game_box)
        gv.setContentsMargins(0, 0, 0, 0)
        gv.setSpacing(2)
        gv.addWidget(self.game)
        self.game_warning = w.label("", "error")
        self.game_warning.setWordWrap(True)
        self.game_warning.hide()
        gv.addWidget(self.game_warning)
        f.addRow(w.label(tr("遊戲", "Game"), "secondary"), game_box)
        self.description = QLineEdit()
        self.description.setMaxLength(200)
        self.description.setPlaceholderText(tr("例如：官方網頁兌換，要先登入（可留空）",
                                               "e.g. Official web page, log in first (optional)"))
        self.description.textChanged.connect(self._apply)
        f.addRow(w.label(tr("說明", "Description"), "secondary"), self.description)
        self.author = QLineEdit()
        self.author.setMaxLength(60)
        self.author.setPlaceholderText(tr("分享時顯示的名字（可留空）", "Name shown when you share it (optional)"))
        self.author.textChanged.connect(self._apply)
        f.addRow(w.label(tr("作者", "Author"), "secondary"), self.author)
        lay.addLayout(f)
        self.form = f

    def load(self, profile: Profile) -> None:
        self._loading = True
        try:
            self.profile = profile
            self.known = known_game_names(self.ctx, profile.id)
            self.name.setText(profile.name)
            self.game.clear()
            self.game.addItems(self.known)
            self.game.setEditText(profile.game)
            self.description.setText(profile.description)
            self.author.setText(profile.author)
        finally:
            self._loading = False
        self._update_warning()

    def _apply(self, *_a: object) -> None:
        if self._loading or self.profile is None:
            return
        self.profile.name = clean_text(self.name.text())
        self.profile.game = clean_text(self.game.currentText()).strip()
        self.profile.description = clean_text(self.description.text())
        self.profile.author = clean_text(self.author.text())
        self._update_warning()
        self.on_change()

    def _update_warning(self) -> None:
        name = self.profile.game if self.profile else ""
        other = similar_game(name, self.known)
        if other is None:
            self.game_warning.hide()
            self.game_warning.setText("")
            return
        if squash(other) == squash(name):
            text = tr(f"和現有的「{other}」會被視為同一款遊戲（共用序號與紀錄）。",
                      f"This counts as the same game as '{other}' (shared codes and history).")
        else:
            text = tr(f"和「{other}」很像，是同一款遊戲嗎？若是，請從清單選擇「{other}」，才能共用序號與紀錄。",
                      f"Close to '{other}'. Same game? Then pick '{other}' from the list to share codes and history.")
        self.game_warning.setText(text)
        self.game_warning.show()


class TargetCard(QWidget):
    def __init__(self, ctx: AppContext, on_change: Change, on_pick: Change, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.on_change = on_change
        self.profile: Profile | None = None
        self._loading = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        c, lay = card(tr("目標視窗", "Target window"),
                      tr("AutoPress 只會對這個視窗輸入；每筆序號開始前都會重新確認。",
                         "AutoPress only types into this window and checks it again before every code."))
        outer.addWidget(c)
        row = QHBoxLayout()
        self.summary = w.label("", "body")
        self.summary.setWordWrap(True)
        row.addWidget(self.summary, 1)
        # a long window title elides (full text in the tooltip) instead of widening the page (U4)
        self.status = w.ElidedLabel("")
        self.status.setProperty("role", "muted")
        self.status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.status, 2)
        self.pick_btn = w.push_button(tr("選擇視窗…", "Choose window…"), "secondary", "window")
        self.pick_btn.clicked.connect(on_pick)
        row.addWidget(self.pick_btn)
        lay.addLayout(row)
        f = _form()
        title_row = QHBoxLayout()
        self.title_mode = QComboBox()
        for m in TitleMatch:
            self.title_mode.addItem(m.label(), m.value)
        self.title_mode.currentIndexChanged.connect(self._apply)
        title_row.addWidget(self.title_mode)
        self.title = QLineEdit()
        self.title.setPlaceholderText(tr("標題關鍵字，例如「兌換」", "Title keyword, e.g. 'Redeem'"))
        self.title.textChanged.connect(self._apply)
        title_row.addWidget(self.title, 1)
        tbox = QWidget()
        tbox.setLayout(title_row)
        title_row.setContentsMargins(0, 0, 0, 0)
        f.addRow(w.label(tr("視窗標題", "Window title"), "secondary"), tbox)
        self.same_process = w.Switch(False)
        self.same_process.setAccessibleName(tr("同程式的其他視窗也算目標", "Other windows of the program count"))
        self.same_process.toggled.connect(self._apply)
        sp_box = QWidget()
        sp = QHBoxLayout(sp_box)
        sp.setContentsMargins(0, 0, 0, 0)
        sp.addWidget(self.same_process)
        sp_hint = w.label(tr("同一個程式的其他視窗（例如彈窗）也算目標；匯出時不會保留",
                             "Other windows of the same program (popups) count too; never exported"), "muted")
        sp_hint.setWordWrap(True)  # wraps in a narrow window instead of widening the page (U4)
        sp.addWidget(sp_hint, 1)
        f.addRow(w.label(tr("彈窗", "Popups"), "secondary"), sp_box)
        lay.addLayout(f)
        self.form = f
        self.issue = w.label("", "error")
        self.issue.setWordWrap(True)
        self.issue.hide()
        lay.addWidget(self.issue)
        self.hint = w.label("", "muted")
        self.hint.setWordWrap(True)
        self.hint.hide()
        lay.addWidget(self.hint)

    def load(self, profile: Profile) -> None:
        self._loading = True
        try:
            self.profile = profile
            t = profile.target
            self.title.setText(t.title)
            self.title_mode.setCurrentIndex(max(0, self.title_mode.findData(t.title_mode.value)))
            self.same_process.setChecked(t.allow_same_process)
        finally:
            self._loading = False
        self.refresh_text()

    def _apply(self, *_a: object) -> None:
        if self._loading or self.profile is None:
            return
        t = self.profile.target
        t.title = clean_text(self.title.text())
        t.title_mode = TitleMatch(self.title_mode.currentData() or TitleMatch.CONTAINS.value)
        t.allow_same_process = self.same_process.isChecked()
        self.refresh_text()
        self.on_change()

    def refresh_text(self, live: object = None) -> None:
        """Update the summary; ``live`` = the found WindowInfo (or None)."""
        p = self.profile
        if p is None:
            return
        t = p.target
        if t.is_empty():
            self.summary.setText(tr("尚未選擇目標視窗", "No target window yet"))
            self.summary.setToolTip("")
            self.summary.setProperty("role", "error")
        else:
            # the window class is a developer detail: tooltip only, as in the window picker (U30)
            self.summary.setText(t.exe or tr("（任何程式）", "(any program)"))
            self.summary.setToolTip(tr(f"視窗類別：{t.class_name}", f"Window class: {t.class_name}") if t.class_name else "")
            self.summary.setProperty("role", "body")
        self.summary.style().unpolish(self.summary)
        self.summary.style().polish(self.summary)
        self.status.setToolTip("")
        if live is not None:
            from .window_picker import elevated_card_text, input_permission_of, unknown_badge, unknown_text

            title = getattr(live, "title", "")
            text = tr(f"已找到：{title}", f"Found: {title}")
            perm = input_permission_of(getattr(live, "hwnd", 0))
            if perm == "blocked_elevated":
                text += tr(" · 系統管理員", " · Administrator")
                self.status.setToolTip(f"{text}\n{elevated_card_text()}")
            elif perm == "unknown":
                text += " · " + unknown_badge()
                self.status.setToolTip(f"{text}\n{unknown_text()}")
            self.status.setText(text)
        elif not t.is_empty():
            self.status.setText(tr("目前找不到這個視窗", "Not found right now"))
        else:
            self.status.setText("")
        issues = []
        if t.is_forbidden():
            from .window_picker import forbidden_text

            issues.append(forbidden_text(t.exe))
        elif t.needs_title():
            issues.append(tr("瀏覽器目標必須設定標題關鍵字（例如「兌換」），以免輸入到其他分頁。請重新選擇視窗或填寫標題關鍵字。",
                             "A browser target needs a title keyword (e.g. \"Redeem\") so input never goes to another "
                             "tab. Pick the window again or enter a keyword."))
        err = t.pattern_error()
        if err:
            issues.append(err)
        self.issue.setText("\n".join(issues))
        self.issue.setVisible(bool(issues))
        hint = ""
        if p.suggested_exe and t.is_empty():
            hint = tr(f"匯入的設定檔建議使用：{p.suggested_exe}", f"The imported profile suggests: {p.suggested_exe}")
        self.hint.setText(hint)
        self.hint.setVisible(bool(hint))


class FormatCard(QWidget):
    def __init__(self, on_change: Change, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.on_change = on_change
        self.profile: Profile | None = None
        self._loading = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        c, lay = card(tr("序號格式與座標", "Code format and positions"))
        outer.addWidget(c)
        f = _form()
        self.preset = QComboBox()
        # the field grows to the full width anyway; the longest preset name must not set the card's
        # minimum width (in English it made the editor scroll sideways at the 1100 x 700 window)
        self.preset.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.preset.setMinimumContentsLength(12)
        self._formats = self._preset_list()
        for fmt in self._formats:
            self.preset.addItem(self._label(fmt.id), fmt.id)
        self.preset.view().setMinimumWidth(self.preset.view().sizeHintForColumn(0) + 32)  # full names in the popup
        self.preset.currentIndexChanged.connect(self._preset_changed)
        f.addRow(w.label(tr("序號格式", "Code format"), "secondary"), self.preset)
        self.example = w.label("", "muted")
        f.addRow(w.label("", "secondary"), self.example)
        self.charset = QLineEdit()
        self.charset.setPlaceholderText("A-Za-z0-9")
        self.charset.setToolTip(tr("進階：用「-」表示範圍，例如 A-Z0-9 是大寫英文與數字。",
                                   "Advanced: use - for ranges, e.g. A-Z0-9 = capital letters and digits."))
        self.charset.textChanged.connect(self._custom)
        # the allowed characters in plain words (U30): 「英文字母與數字」 instead of only "A-Za-z0-9"
        self.charset_hint = w.label("", "muted")
        self.charset_hint.setWordWrap(True)
        # a preset shows only the words; the editable rule appears with 「自訂」 (picking 自訂 keeps the
        # preset's rule, so nothing is lost), so a gamer never meets "A-Za-z0-9" unless they customise
        self.charset_words = w.label("", "body")
        self.charset_words.setMinimumHeight(theme.CONTROL_H)
        self.charset_words.setWordWrap(True)
        charset_box = _with_hint(self.charset, self.charset_hint)
        charset_box.layout().insertWidget(0, self.charset_words)
        f.addRow(w.label(tr("允許的字元", "Allowed characters"), "secondary"), charset_box)
        lens = QWidget()
        lh = QHBoxLayout(lens)
        lh.setContentsMargins(0, 0, 0, 0)
        self.min_len = SpinBox()
        self.min_len.setRange(1, 64)
        self.max_len = SpinBox()
        self.max_len.setRange(1, 64)
        self.min_len.valueChanged.connect(self._custom)
        self.max_len.valueChanged.connect(self._custom)
        lh.addWidget(self.min_len)
        lh.addWidget(w.label("–", "secondary"))
        lh.addWidget(self.max_len)
        lh.addStretch(1)
        # short label + hint: the old 「長度（不含分隔符號）」 set the width of the shared label column (U35)
        len_hint = w.label(tr("不含分隔符號", "Separators are not counted"), "muted")
        len_hint.setWordWrap(True)
        f.addRow(w.label(tr("長度", "Length"), "secondary"), _with_hint(lens, len_hint))
        self.groups = QLineEdit()
        self.groups.setPlaceholderText(tr("例如 5,5,5（可留空）", "e.g. 5,5,5 (optional)"))
        self.groups.textChanged.connect(self._custom)
        f.addRow(w.label(tr("分段", "Groups"), "secondary"), self.groups)
        self.case = w.Switch(True)
        self.case.toggled.connect(self._custom)
        f.addRow(w.label(tr("區分大小寫", "Case-sensitive"), "secondary"), self.case)
        self.coord = QComboBox()
        for m in CoordMode:
            self.coord.addItem(m.label(), m.value)
        self.coord.currentIndexChanged.connect(self._coord_changed)
        f.addRow(w.label(tr("座標模式", "Positions"), "secondary"), self.coord)
        lay.addLayout(f)
        self.form = f
        hint = w.label(tr("自動：視窗大小不變時用錄製的像素，改變時依比例換算。網頁建議「固定像素」，"
                          "畫面會跟著縮放的遊戲建議「依視窗比例」。",
                          "Automatic: recorded pixels while the window size is unchanged, otherwise scaled. "
                          "Web pages: fixed pixels; games whose UI scales: scale with window."), "muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.issue = w.label("", "error")
        self.issue.setWordWrap(True)
        self.issue.hide()
        lay.addWidget(self.issue)

    @staticmethod
    def _preset_list() -> list[CodeFormat]:
        try:
            from ..codes import presets

            return list(presets.list_formats())
        except Exception as exc:  # G1 stub
            log.debug("presets unavailable: %s", exc)
            return [CodeFormat(), CodeFormat(id="custom")]

    @staticmethod
    def _label(fmt_id: str) -> str:
        try:
            from ..codes import presets

            return presets.format_label(fmt_id)
        except Exception:
            return {"generic": tr("通用", "Generic"), "custom": tr("自訂", "Custom")}.get(fmt_id, fmt_id)

    @staticmethod
    def _example(fmt_id: str) -> str:
        try:
            from ..codes import presets

            return presets.format_example(fmt_id)
        except Exception:
            return ""

    def load(self, profile: Profile) -> None:
        self._loading = True
        try:
            self.profile = profile
            fmt = profile.code_format
            idx = self.preset.findData(fmt.id)
            if idx < 0:
                self.preset.addItem(fmt.id, fmt.id)
                idx = self.preset.count() - 1
            self.preset.setCurrentIndex(idx)
            self._show_format(fmt)
            self.coord.setCurrentIndex(max(0, self.coord.findData(profile.coord_mode.value)))
        finally:
            self._loading = False
        self._update_issue()

    def _show_format(self, fmt: CodeFormat) -> None:
        self.charset.setText(fmt.charset)
        self.min_len.setValue(fmt.min_len)
        self.max_len.setValue(fmt.max_len)
        self.groups.setText(",".join(str(g) for g in fmt.groups))
        self.case.setChecked(fmt.case_sensitive)
        ex = self._example(fmt.id)
        self.example.setText(tr(f"範例：{ex}", f"Example: {ex}") if ex else "")
        self._update_charset_hint()
        self._show_charset_as(fmt.id == "custom")

    def _show_charset_as(self, editable: bool) -> None:
        """The charset row: the editable rule with its words under it (自訂), or only the words."""
        self.charset.setVisible(editable)
        self.charset_hint.setVisible(editable)
        self.charset_words.setVisible(not editable)

    def _update_charset_hint(self) -> None:
        """「英文字母與數字」 for the charset field (and the case switch); a set without plain
        words gets the range rule instead."""
        charset = clean_text(self.charset.text()).strip()
        text = ""
        try:
            from ..codes import presets

            label = presets.charset_label(charset, self.case.isChecked()) if charset else ""
            if label and label != charset.replace("-", presets.NB_HYPHEN):  # not just the raw set again
                text = label
        except Exception as exc:  # G1 stub
            log.debug("charset_label unavailable: %s", exc)
        if not text:
            text = tr("用「-」表示範圍，例如 A-Z0-9 是大寫英文與數字", "Use - for ranges, e.g. A-Z0-9 = capital letters and digits")
            self.charset_words.setText(charset)  # a preset whose set has no plain words: the set itself
        else:
            self.charset_words.setText(text)
        self.charset_hint.setText(text)

    def _preset_changed(self) -> None:
        if self._loading or self.profile is None:
            return
        fid = self.preset.currentData()
        fmt = next((clone(f) for f in self._formats if f.id == fid), None)
        if fmt is None:
            return
        if fid == "custom":
            fmt = clone(self.profile.code_format)
            fmt.id = "custom"
        self._loading = True
        try:
            self.profile.code_format = fmt
            self._show_format(fmt)
        finally:
            self._loading = False
        self._update_issue()
        self.on_change()

    def _custom(self, *_a: object) -> None:
        self._update_charset_hint()
        if self._loading or self.profile is None:
            return
        fmt = self.profile.code_format
        fmt.charset = clean_text(self.charset.text()).strip() or fmt.charset
        fmt.min_len = int(self.min_len.value())
        fmt.max_len = int(self.max_len.value())
        sizes = parse_sizes(self.groups.text())
        if sizes is not None:
            fmt.groups = sizes
        fmt.case_sensitive = self.case.isChecked()
        if fmt.id != "custom":
            fmt.id = "custom"
            self._loading = True
            idx = self.preset.findData("custom")
            if idx >= 0:
                self.preset.setCurrentIndex(idx)
            self._loading = False
            self._show_charset_as(True)
        self._update_issue()
        self.on_change()

    def _coord_changed(self) -> None:
        if self._loading or self.profile is None:
            return
        self.profile.coord_mode = CoordMode(self.coord.currentData() or CoordMode.AUTO.value)
        self.on_change()

    def _update_issue(self) -> None:
        issues = [i.message for i in self.profile.code_format.validate()] if self.profile else []
        if self.groups.text().strip() and parse_sizes(self.groups.text()) is None:
            issues.append(tr("分段請輸入正整數，用逗號分隔，例如 5,5,5", "Groups: positive numbers, e.g. 5,5,5"))
        self.issue.setText("\n".join(issues))
        self.issue.setVisible(bool(issues))


class PolicyCard(QWidget):
    def __init__(self, on_change: Change, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.on_change = on_change
        self.profile: Profile | None = None
        self._loading = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        c, lay = card(tr("執行規則", "Run rules"),
                      tr("每筆之間的間隔、遇到「操作過於頻繁」怎麼辦、什麼時候自動停止。",
                         "The wait between codes, what to do on rate limits, and when to stop."))
        outer.addWidget(c)
        f = _form()
        iv = QWidget()
        ih = QHBoxLayout(iv)
        ih.setContentsMargins(0, 0, 0, 0)
        self.imin, self.imax = DoubleSpinBox(), DoubleSpinBox()
        for sb in (self.imin, self.imax):
            sb.setRange(1.0, 3600.0)
            sb.setDecimals(1)
            sb.setSingleStep(0.5)
            sb.setSuffix(tr(" 秒", " s"))
            sb.valueChanged.connect(self._apply)
        ih.addWidget(self.imin)
        ih.addWidget(w.label("–", "secondary"))
        ih.addWidget(self.imax)
        ih.addStretch(1)
        f.addRow(w.label(tr("每筆間隔", "Interval"), "secondary"), iv)
        self.rate = QComboBox()
        self.rate.addItem(tr("冷卻後重試這一筆", "Cool down, then retry the code"), RateLimitAction.COOLDOWN.value)
        self.rate.addItem(tr("停止", "Stop"), RateLimitAction.STOP.value)
        self.rate.currentIndexChanged.connect(self._apply)
        f.addRow(w.label(tr("操作過於頻繁時", "On rate limit"), "secondary"), self.rate)
        self.cooldown = SpinBox()
        self.cooldown.setRange(10, 86400)
        self.cooldown.setSuffix(tr(" 秒", " s"))
        self.cooldown.valueChanged.connect(self._apply)
        f.addRow(w.label(tr("冷卻時間", "Cool-down"), "secondary"), self.cooldown)
        self.max_cool = SpinBox()
        self.max_cool.setRange(0, 20)
        self.max_cool.setSuffix(tr(" 次", " times"))
        self.max_cool.valueChanged.connect(self._apply)
        f.addRow(w.label(tr("最多冷卻", "Max cool-downs"), "secondary"), self.max_cool)
        self.fail = SpinBox()
        self.fail.setRange(0, 1000)
        self.fail.setSpecialValueText(tr("不停止", "Never"))
        self.fail.valueChanged.connect(self._apply)
        f.addRow(w.label(tr("連續失敗幾筆就停止", "Stop after failures in a row"), "secondary"), self.fail)
        self.invalid = SpinBox()
        self.invalid.setRange(0, 1000)
        self.invalid.setSpecialValueText(tr("不暫停", "Never"))
        self.invalid.valueChanged.connect(self._apply)
        f.addRow(w.label(tr("連續無效幾筆就暫停", "Pause after invalid in a row"), "secondary"), self.invalid)
        self.unknown = QComboBox()
        self.unknown.addItem(tr("暫停並詢問我（建議）", "Pause and ask me (recommended)"), UnknownAction.PAUSE.value)
        self.unknown.addItem(tr("標為需確認並繼續", "Mark for review and continue"), UnknownAction.CONTINUE.value)
        self.unknown.addItem(tr("停止", "Stop"), UnknownAction.STOP.value)
        self.unknown.currentIndexChanged.connect(self._apply)
        f.addRow(w.label(tr("無法判讀結果時", "Unrecognised result"), "secondary"), self.unknown)
        lay.addLayout(f)
        self.form = f
        self.issue = w.label("", "error")
        self.issue.setWordWrap(True)
        self.issue.hide()
        lay.addWidget(self.issue)

    def load(self, profile: Profile) -> None:
        self._loading = True
        try:
            self.profile = profile
            pol = profile.policy
            self.imin.setValue(pol.interval_min_s)
            self.imax.setValue(pol.interval_max_s)
            self.rate.setCurrentIndex(max(0, self.rate.findData(pol.on_rate_limit.value)))
            self.cooldown.setValue(pol.cooldown_s)
            self.max_cool.setValue(pol.max_cooldowns)
            self.fail.setValue(pol.stop_after_failures)
            self.invalid.setValue(pol.pause_after_invalid)
            self.unknown.setCurrentIndex(max(0, self.unknown.findData(pol.on_unknown.value)))
        finally:
            self._loading = False
        self._update()

    def _apply(self, *_a: object) -> None:
        if self._loading or self.profile is None:
            return
        pol = self.profile.policy
        pol.interval_min_s = float(self.imin.value())
        pol.interval_max_s = float(self.imax.value())
        pol.on_rate_limit = RateLimitAction(self.rate.currentData() or RateLimitAction.COOLDOWN.value)
        pol.cooldown_s = int(self.cooldown.value())
        pol.max_cooldowns = int(self.max_cool.value())
        pol.stop_after_failures = int(self.fail.value())
        pol.pause_after_invalid = int(self.invalid.value())
        pol.on_unknown = UnknownAction(self.unknown.currentData() or UnknownAction.PAUSE.value)
        self._update()
        self.on_change()

    def _update(self) -> None:
        pol = self.profile.policy if self.profile else None
        issues = []
        if pol is not None:
            if pol.interval_min_s > pol.interval_max_s:
                issues.append(tr("最短間隔大於最長間隔，儲存時會自動對調。", "The minimum is above the maximum; they are swapped on save."))
            if pol.interval_min_s < 2:
                issues.append(tr("間隔小於 2 秒，容易被判定操作過於頻繁。", "Intervals under 2 s often trigger rate limits."))
            if pol.on_unknown is UnknownAction.CONTINUE:
                issues.append(tr("無法判讀的結果會直接跳過，輸入到錯誤的地方時不會被發現。",
                                 "Unrecognised results are skipped, so input that went to the wrong place goes unnoticed."))
        self.cooldown.setEnabled(pol is None or pol.on_rate_limit is RateLimitAction.COOLDOWN)
        self.max_cool.setEnabled(pol is None or pol.on_rate_limit is RateLimitAction.COOLDOWN)
        self.issue.setText("\n".join(issues))
        self.issue.setVisible(bool(issues))


__all__ = ["BasicsCard", "FormatCard", "PolicyCard", "TargetCard", "align_form_labels", "card", "form_labels",
           "known_game_names", "similar_game"]
