# OWNED BY G6
"""Layout of the Codes page (private to G6; split out of codes_page.py): header, import card,
banners, table card with the 6 status segments, game filter, search, table, empty state and the
bulk bar. ``CodesLayoutMixin`` is mixed into ``CodesPage`` (which provides ``ctx``, the model and
proxy, the action / import slots and ``_timer``).

The 格式 combo sits at the end of the import buttons when they fit, else at the end of the second
row (narrow windows, English labels), so the page never forces a window wider than the 1100 px
minimum; the empty state scrolls instead of growing the page."""

from __future__ import annotations

import logging

from PyQt6.QtCore import QEvent, QRectF, QSize, Qt
from PyQt6.QtGui import QKeySequence, QPainter, QPen, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr
from . import theme, widgets
from .codes_common import ELEVATED_DROP, NO_PROFILE, fit_wrapped_label
from .codes_model import (
    COL_CHECK,
    COL_CODE,
    COL_CONF,
    COL_INDEX,
    COL_MESSAGE,
    COL_MORE,
    COL_SOURCE,
    COL_STATUS,
    COLUMN_WIDTHS,
    FILTER_LABELS,
    FILTERS,
    CellDelegate,
    CheckDelegate,
    CodeDelegate,
    ConfidenceDelegate,
    IndexDelegate,
    MoreDelegate,
    SourceDelegate,
    StatusDelegate,
)
from .codes_paint import status_column_width

log = logging.getLogger(__name__)


def _is_elevated() -> bool:
    try:
        from ..win32 import elevation

        return bool(elevation.is_elevated())
    except Exception:  # noqa: BLE001 - a failed check must never break the page
        log.debug("elevation check failed", exc_info=True)
        return False


class _ShrinkBox(QWidget):
    """A box whose minimum width is 0, so a layout can squeeze it instead of growing the page."""

    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())


class DropOverlay(QWidget):
    """Dashed drop zone shown over the page while files are dragged onto it."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.hide()

    def paintEvent(self, _event: object) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = theme.color("bg_app")
        bg.setAlpha(215)
        p.fillRect(self.rect(), bg)
        r = QRectF(self.rect()).adjusted(16, 16, -16, -16)
        p.setPen(QPen(theme.color("accent"), 2, Qt.PenStyle.DashLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, theme.R_LG, theme.R_LG)
        p.setPen(theme.color("text"))
        p.setFont(theme.font(theme.FS_TITLE, bold=True))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter,
                   tr("放開滑鼠即可匯入（序號清單檔或圖片）", "Drop to import (code lists or images)"))
        p.end()


class CodesLayoutMixin:
    """Widget construction of the Codes page."""

    # =========================================================================== layout
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(*theme.PAGE_MARGINS)
        root.setSpacing(theme.SP[4])
        root.addLayout(self._build_header())
        root.addWidget(self._build_import_card())
        self._banner_box = QVBoxLayout()
        self._banner_box.setSpacing(theme.SP[2])
        self._no_profile_banner = widgets.Banner("info", str(NO_PROFILE), tr("選擇設定檔", "Choose a profile"), False)
        self._no_profile_banner.actionClicked.connect(lambda: self.ctx.navigate("profiles"))
        self._unassigned_banner: QWidget | None = None
        self._unassigned_text = ""
        self._review_text = ""
        self._review_banner = widgets.Banner("warning", "", tr("逐筆檢查", "Check one by one"), True)
        self._review_banner.actionClicked.connect(self.next_review)
        self._review_banner.closed.connect(self._dismiss_review)
        self._banner_box.addWidget(self._no_profile_banner)
        self._banner_box.addWidget(self._review_banner)
        root.addLayout(self._banner_box)
        root.addWidget(self._build_table_card(), 1)

    def _build_header(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(theme.SP[2])
        grid.setVerticalSpacing(2)
        grid.addWidget(widgets.label(tr("序號", "Codes"), "display"), 0, 0)
        self._subtitle = widgets.label("", "muted")
        grid.addWidget(self._subtitle, 1, 0)
        grid.setColumnStretch(1, 1)
        right = QHBoxLayout()
        right.setSpacing(theme.SP[2])
        right.addWidget(widgets.label(tr("設定檔", "Profile"), "secondary"))
        self._profile_combo = widgets.combo([], 200)
        self._profile_combo.setAccessibleName(tr("使用中的設定檔", "Active profile"))
        self._profile_combo.activated.connect(self._on_profile_activated)
        right.addWidget(self._profile_combo)
        self._test_btn = widgets.push_button(tr("試跑 1 筆", "Test 1 code"), "secondary", "flask")
        self._test_btn.clicked.connect(lambda: self.start_run(test_one=True))
        right.addWidget(self._test_btn)
        self._start_btn = widgets.push_button(tr("開始兌換", "Start"), "primary", "play")
        self._start_btn.clicked.connect(lambda: self.start_run(test_one=False))
        right.addWidget(self._start_btn)
        grid.addLayout(right, 0, 2, Qt.AlignmentFlag.AlignRight)
        self._run_hint = widgets.label("", "muted")
        self._run_hint.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(self._run_hint, 1, 2, Qt.AlignmentFlag.AlignRight)
        return grid

    def _build_import_card(self) -> QWidget:
        card = widgets.Card(vertical=True, spacing=theme.SP[2])
        lay = card.layout()
        row = QHBoxLayout()
        row.setSpacing(theme.SP[2])
        row.addWidget(widgets.label(tr("新增序號", "Add codes"), "title"))
        row.addSpacing(theme.SP[1])
        self._import_buttons: dict[str, QWidget] = {}
        for key, icon_name, text, tip, slot in (
            ("paste", "paste", tr("貼上文字", "Paste text"),
             tr("貼上剪貼簿的文字並找出序號（Ctrl+V）", "Paste the clipboard text and find the codes (Ctrl+V)"),
             self.paste_text),
            ("file", "file", tr("開啟檔案", "Open file"),
             tr("開啟 .txt／.csv／.tsv／.json／.log 序號清單（Ctrl+O）", "Open a .txt / .csv / .tsv / .json / .log code list (Ctrl+O)"),
             self.open_file_dialog),
            ("image", "image", tr("圖片辨識", "Image"),
             tr("選一張圖片用文字辨識找出序號；也可以把圖片拖曳到這裡", "Pick an image and read the codes with OCR; you can also drop images here"),
             self.open_image_dialog),
            ("clipboard", "clipimage", tr("剪貼簿圖片", "Clipboard image"),
             tr("辨識剪貼簿裡的圖片（例如按 Win+Shift+S 截圖之後）", "Read the image on the clipboard (e.g. after Win+Shift+S)"),
             self.import_clipboard_image),
            ("snip", "snip", tr("框選螢幕", "Screen region"),
             tr("暫時隱藏 AutoPress，框選畫面上含有序號的區域（Esc 取消）", "Hide AutoPress and select the screen area with the codes (Esc cancels)"),
             self.snip_screen),
        ):
            btn = widgets.push_button(text, "secondary", icon_name)
            btn.setToolTip(tip)
            btn.clicked.connect(lambda _c=False, s=slot: s())
            row.addWidget(btn)
            self._import_buttons[key] = btn
        row.addStretch(1)
        self._format_combo = widgets.combo([], None)
        self._format_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._format_combo.setMinimumContentsLength(13)
        self._format_combo.setAccessibleName(tr("匯入時使用的序號格式", "Code format for imports"))
        self._format_combo.setToolTip(tr("從文字或圖片找序號時使用的格式；自動偵測會選最符合的格式",
                                         "Format used to find codes in text or images; auto-detect picks the best fit"))
        self._format_box = _ShrinkBox()
        self._format_box.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        fl = QHBoxLayout(self._format_box)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(theme.SP[2])
        fl.addWidget(widgets.label(tr("格式", "Format"), "secondary"))
        fl.addWidget(self._format_combo)
        row.addWidget(self._format_box)
        lay.addLayout(row)
        row2 = QHBoxLayout()
        row2.setSpacing(theme.SP[2])
        self._skip_switch = widgets.Switch(bool(self.ctx.settings.skip_history_on_import))
        self._skip_switch.setAccessibleName(tr("略過已兌換過的序號", "Skip codes already redeemed"))
        self._skip_switch.toggled.connect(self._on_skip_toggled)
        row2.addWidget(self._skip_switch)
        row2.addWidget(widgets.label(tr("略過已兌換過的序號", "Skip codes already redeemed"), "secondary"))
        self._skip_note = widgets.ElidedLabel("")
        self._skip_note.setProperty("role", "muted")
        row2.addWidget(self._skip_note, 1)
        lay.addLayout(row2)
        self._import_rows = (row, row2)
        self._import_card = card
        card.installEventFilter(self)
        self._elevated_hint = widgets.label(str(ELEVATED_DROP), "muted")
        self._elevated_hint.setWordWrap(True)
        self._elevated_hint.setVisible(_is_elevated())
        lay.addWidget(self._elevated_hint)
        return card

    def eventFilter(self, obj: object, event: object) -> bool:
        if obj is getattr(self, "_import_card", None) and event.type() == QEvent.Type.Resize:  # type: ignore[attr-defined]
            self._place_timer.start()
        return super().eventFilter(obj, event)  # type: ignore[arg-type]

    def _place_format_box(self) -> None:
        """The 格式 combo sits at the end of the import buttons when they fit, else at the end of
        the second row (narrow windows, English labels): the page never forces a wide minimum."""
        row1, row2 = self._import_rows
        need = sum(row1.itemAt(i).widget().sizeHint().width() for i in range(row1.count())
                   if row1.itemAt(i).widget() is not None and row1.itemAt(i).widget() is not self._format_box)
        need += row1.spacing() * row1.count() + self._format_box.sizeHint().width() + theme.SP[1]
        m = self._import_card.layout().contentsMargins()
        avail = self._import_card.width() - m.left() - m.right()
        in_row1 = row1.indexOf(self._format_box) >= 0
        if in_row1 and avail < need:
            row1.removeWidget(self._format_box)
            row2.addWidget(self._format_box)
        elif not in_row1 and avail >= need:
            row2.removeWidget(self._format_box)
            row1.addWidget(self._format_box)

    def format_box_row(self) -> int:
        """1 or 2: the import-card row that holds the 格式 combo (layout tests)."""
        return 1 if self._import_rows[0].indexOf(self._format_box) >= 0 else 2

    def _build_table_card(self) -> QWidget:
        card = widgets.Card(vertical=True, margins=(theme.SP[4], theme.SP[3], theme.SP[4], theme.SP[2]),
                            spacing=theme.SP[2])
        lay = card.layout()
        top = QHBoxLayout()
        top.setSpacing(theme.SP[3])
        self._segments = widgets.SegmentedControl([str(FILTER_LABELS[k]) for k in FILTERS], 0)
        self._segments.setAccessibleName(tr("狀態篩選", "Status filter"))
        self._segments.currentChanged.connect(self._on_segment)
        top.addWidget(self._segments)
        top.addStretch(1)
        self._game_combo = widgets.combo([], None)
        self._game_combo.setMinimumWidth(140)
        self._game_combo.setMaximumWidth(260)
        self._game_combo.setAccessibleName(tr("遊戲篩選", "Game filter"))
        self._game_combo.activated.connect(self._on_game_activated)
        top.addWidget(self._game_combo)
        self._search = widgets.SearchField(tr("搜尋序號或訊息", "Search codes or messages"))
        self._search.setMinimumWidth(130)
        self._search.setMaximumWidth(240)
        self._search.setAccessibleName(tr("搜尋序號或訊息", "Search codes or messages"))
        self._search.textChanged.connect(self._proxy.set_search)
        top.addWidget(self._search)
        lay.addLayout(top)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_table())
        empty = QScrollArea()  # the empty state may be taller than a small window: scroll, never grow
        empty.setObjectName("CodesEmptyScroll")
        empty.setWidgetResizable(True)
        empty.setFrameShape(QFrame.Shape.NoFrame)
        empty.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        empty_state = self._build_empty_state()
        empty_state.setObjectName("CodesEmptyState")
        empty.setWidget(empty_state)
        empty.setStyleSheet("QScrollArea#CodesEmptyScroll, QScrollArea#CodesEmptyScroll > QWidget, "
                            "QWidget#CodesEmptyState { background: transparent; border: none; }")
        self._stack.addWidget(empty)
        self._stack.addWidget(self._build_no_match())
        lay.addWidget(self._stack, 1)
        lay.addLayout(self._build_bulk_bar())
        return card

    def _build_table(self) -> QTableView:
        t = QTableView()
        t.setObjectName("CodeTable")
        t.setAccessibleName(tr("序號清單", "Code list"))
        t.setModel(self._proxy)
        t.setShowGrid(False)
        t.setWordWrap(False)
        t.setAlternatingRowColors(False)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        t.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        t.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        t.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        t.customContextMenuRequested.connect(self._on_context_menu)
        t.clicked.connect(self._on_table_clicked)
        t.verticalHeader().setVisible(False)
        t.verticalHeader().setDefaultSectionSize(theme.ROW_H)
        header = t.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setHighlightSections(False)
        header.setFixedHeight(36)
        self._check_delegate = CheckDelegate(t)
        self._check_delegate.on_toggle = self.on_check_toggled
        self._code_delegate = CodeDelegate(t)
        self._code_delegate.validator = self._validate_edit
        self._code_delegate.edit_rejected.connect(lambda reason: self.ctx.notify(reason, "warning"))
        delegates: dict[int, CellDelegate] = {
            COL_CHECK: self._check_delegate, COL_INDEX: IndexDelegate(t), COL_CODE: self._code_delegate,
            COL_SOURCE: SourceDelegate(t), COL_CONF: ConfidenceDelegate(t), COL_STATUS: StatusDelegate(t),
            COL_MESSAGE: CellDelegate(t), COL_MORE: MoreDelegate(t),
        }
        self._delegates = delegates
        for col, delegate in delegates.items():
            t.setItemDelegateForColumn(col, delegate)
            width = COLUMN_WIDTHS[col]
            if width < 0:
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
            else:
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
                t.setColumnWidth(col, width or status_column_width())
        t.selectionModel().selectionChanged.connect(self._update_bulk_bar)
        for key, slot in ((QKeySequence.StandardKey.Delete, self.remove_selected),
                          (QKeySequence.StandardKey.Copy, self.copy_selected)):
            sc = QShortcut(QKeySequence(key), t)
            sc.setContext(Qt.ShortcutContext.WidgetShortcut)
            sc.activated.connect(slot)
        space = QShortcut(QKeySequence(Qt.Key.Key_Space), t)
        space.setContext(Qt.ShortcutContext.WidgetShortcut)
        space.activated.connect(self.toggle_checked_selected)
        self._table = t
        return t

    def _build_empty_state(self) -> QWidget:
        actions = []
        for text, icon_name, variant, slot in (
            (tr("貼上文字", "Paste text"), "paste", "primary", self.paste_text),
            (tr("開啟檔案", "Open file"), "file", "secondary", self.open_file_dialog),
            (tr("框選螢幕辨識", "Read a screen region"), "snip", "secondary", self.snip_screen),
        ):
            b = widgets.push_button(text, variant, icon_name)
            b.clicked.connect(lambda _c=False, s=slot: s())
            actions.append(b)
        hint = tr("貼上一段文字、開啟 .txt／.csv，或框選畫面上的序號，AutoPress 會自動找出序號並去除重複。",
                  "Paste some text, open a .txt / .csv file or select codes on the screen; AutoPress finds the codes "
                  "and removes duplicates.")
        state = widgets.EmptyState(
            "codes", tr("還沒有任何序號", "No codes yet"), hint, actions=actions, tip_keys=["Ctrl", "V"],
            tip_text=tr("貼上剪貼簿裡的序號或圖片，也可以直接把檔案或圖片拖曳到這裡",
                        "pastes codes or an image from the clipboard; you can also drop files or images here"))
        for lb in state.findChildren(QLabel):
            if lb.text() == hint and lb.wordWrap():
                fit_wrapped_label(lb, 560)
        return state

    def _build_no_match(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addStretch(1)
        self._no_match_label = widgets.label("", "secondary")
        self._no_match_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._no_match_label.setWordWrap(True)
        lay.addWidget(self._no_match_label)
        row = QHBoxLayout()
        row.addStretch(1)
        self._no_match_btn = widgets.push_button(tr("清除篩選", "Clear filters"), "secondary")
        self._no_match_btn.clicked.connect(self._clear_filters)
        row.addWidget(self._no_match_btn)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(2)
        return w

    def _build_bulk_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(theme.SP[1])
        self._sel_label = widgets.label("", "secondary")
        bar.addWidget(self._sel_label)
        bar.addSpacing(theme.SP[2])
        self._btn_remove = widgets.push_button(tr("移除", "Remove"), "ghost", "trash")
        self._btn_remove.clicked.connect(self.remove_selected)
        self._btn_mark = widgets.push_button(tr("標記為已兌換", "Mark redeemed"), "ghost", "check")
        self._btn_mark.setToolTip(tr("手動標記為成功，並寫入紀錄（之後匯入會自動略過）",
                                     "Mark as redeemed and record it in the history (later imports skip it)"))
        self._btn_mark.clicked.connect(self.mark_redeemed)
        self._btn_confirm = widgets.push_button(tr("確認無誤", "Looks right"), "ghost", "eye")
        self._btn_confirm.setToolTip(tr("已核對「需確認」的序號，改為待兌換", "The codes needing review are correct: make them pending"))
        self._btn_confirm.clicked.connect(self.confirm_ok)
        self._btn_skip = widgets.push_button(tr("略過", "Skip"), "ghost", "skip")
        self._btn_skip.clicked.connect(self.toggle_skip)
        self._btn_up = widgets.icon_button("arrow_up", tr("上移", "Move up"))
        self._btn_up.clicked.connect(lambda: self.move_selected(-1))
        self._btn_down = widgets.icon_button("arrow_down", tr("下移", "Move down"))
        self._btn_down.clicked.connect(lambda: self.move_selected(1))
        self._more_menu = QMenu(self)
        self._more_menu.aboutToShow.connect(lambda: self.populate_more_menu(self._more_menu))
        self._btn_more = widgets.push_button(tr("更多", "More"), "ghost", "more")
        self._btn_more.setMenu(self._more_menu)
        for b in (self._btn_remove, self._btn_mark, self._btn_confirm, self._btn_skip, self._btn_up, self._btn_down,
                  self._btn_more):
            bar.addWidget(b)
        bar.addStretch(1)
        self._btn_export = widgets.push_button(tr("匯出 CSV", "Export CSV"), "ghost", "export")
        self._btn_export.setToolTip(tr("匯出目前列出的序號（UTF-8，Excel 可直接開啟）",
                                       "Export the codes shown (UTF-8, opens in Excel)"))
        self._btn_export.clicked.connect(self.export_csv)
        bar.addWidget(self._btn_export)
        self._bulk_widgets = [self._sel_label, self._btn_remove, self._btn_mark, self._btn_confirm, self._btn_skip,
                              self._btn_up, self._btn_down, self._btn_more, self._btn_export]
        return bar
