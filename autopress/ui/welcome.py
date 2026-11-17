# OWNED BY G5
"""First-run welcome dialog (ux.md flow F1 step 1): what AutoPress does, the three rules (only
your own codes; official web pages are safer; you are responsible for each game's terms),
import profiles only from people you trust, language and theme choice, then "從範本建立設定檔"
(navigate to Profiles). ui.app shows it BEFORE MainWindow is built (parent None), so a language
picked here applies at once: set_language + translator switch, no restart (PX-28).

The dialog rebuilds its own texts after a language change. Choosing 「從範本建立設定檔」 opens the
Profiles page: directly when the main window exists, otherwise through
``ctx.extras["start_page"]`` (read by MainWindow).
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QPainter, QPaintEvent
from PyQt6.QtWidgets import QApplication, QDialog, QHBoxLayout, QVBoxLayout, QWidget

from .. import i18n
from ..context import AppContext
from ..i18n import tr
from ..models import Language, ThemeName
from . import icons, theme, widgets
from .shell_common import change_theme, install_translator, is_headless
from .widgets import SegmentedControl, icon_label, label, push_button

log = logging.getLogger(__name__)

LANGUAGES = (Language.AUTO, Language.ZH_TW, Language.EN)
THEMES = (ThemeName.DARK, ThemeName.LIGHT, ThemeName.SYSTEM)
CONTENT_W = 660


class _RuleIcon(QWidget):
    """36 px soft circle with an icon (colours read at paint time)."""

    def __init__(self, icon_name: str, tone: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icon, self._tone = icon_name, tone
        self.setFixedSize(36, 36)

    def paintEvent(self, _event: QPaintEvent | None) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.tone_colors(self._tone)[1])
        p.drawEllipse(QRectF(self.rect()))
        p.drawPixmap(QPointF(8, 8), icons.icon_pixmap(self._icon, self._tone, 20))
        p.end()


class WelcomeDialog(QDialog):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.choice = "later"  # "later" | "templates"
        self.setModal(True)
        self.setWindowIcon(icons.app_icon())
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._content: QWidget | None = None
        self._build()

    # -- content -------------------------------------------------------------------------------
    def _build(self) -> None:
        if self._content is not None:
            self._outer.removeWidget(self._content)
            self._content.hide()
            self._content.deleteLater()
        self.setWindowTitle(tr("歡迎使用 AutoPress", "Welcome to AutoPress"))
        content = QWidget(self)
        lay = QVBoxLayout(content)
        lay.setContentsMargins(theme.SP[7], theme.SP[6], theme.SP[7], theme.SP[6])
        lay.setSpacing(theme.SP[4])

        head = QHBoxLayout()
        head.setSpacing(theme.SP[3])
        head.addWidget(icon_label("logo", "accent_fill", 44), 0, Qt.AlignmentFlag.AlignVCenter)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label(tr("歡迎使用 AutoPress", "Welcome to AutoPress"), "display"))
        titles.addWidget(label(tr("遊戲兌換序號自動輸入工具", "Auto-entry for game redeem codes"), "muted"))
        head.addLayout(titles)
        head.addStretch(1)
        lay.addLayout(head)

        intro = label(tr("把手上的序號一次匯入，AutoPress 會照你設定的步驟，一筆接一筆自動輸入、送出，並記下每筆結果。"
                         "開始之前，請先看看這幾條原則：",
                         "Import your codes once and AutoPress types and submits them one by one, following the steps "
                         "you set up, and records every result. Before you start, please read these rules:"),
                      "secondary")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        rules = (
            ("check", "success", tr("只輸入你自己的序號", "Enter only your own codes"),
             tr("AutoPress 不會產生、猜測或暴力嘗試序號。", "AutoPress never generates, guesses or brute-forces codes.")),
            ("globe", "info", tr("優先使用官方兌換網頁", "Prefer official redeem web pages"),
             tr("網頁兌換最安全、結果最清楚；遊戲內輸入只在沒有網頁時使用。",
                "Web pages are the safest and clearest; use in-game entry only when there is no web page.")),
            ("shield", "warning", tr("各遊戲條款由你自己負責", "You are responsible for each game's terms"),
             tr("模擬輸入是偵測得到的，有些遊戲禁止巨集；執行時你一動滑鼠或鍵盤就會暫停。",
                "Simulated input can be detected and some games forbid macros; a run pauses as soon as you touch "
                "the mouse or keyboard.")),
            ("profiles", "violet", tr("只匯入你信任的人分享的設定檔", "Import profiles only from people you trust"),
             tr("設定檔就是一串按鍵與點擊；匯入前會列出每個動作讓你確認。",
                "A profile is a list of keystrokes and clicks; every action is listed for you before importing.")),
        )
        for icon_name, tone, title, desc in rules:
            row = QHBoxLayout()
            row.setSpacing(theme.SP[3])
            row.addWidget(_RuleIcon(icon_name, tone, content), 0, Qt.AlignmentFlag.AlignTop)
            col = QVBoxLayout()
            col.setSpacing(2)
            col.addWidget(label(title, "strong"))
            d = label(desc, "secondary")
            d.setWordWrap(True)
            col.addWidget(d)
            row.addLayout(col, 1)
            lay.addLayout(row)

        lay.addWidget(widgets.Divider())
        prefs = QHBoxLayout()
        prefs.setSpacing(theme.SP[3])
        prefs.addWidget(label(tr("語言", "Language"), "secondary"))
        self.language = widgets.combo([tr("自動（依系統語言）", "Automatic (system language)"), "繁體中文", "English"])
        lang = self.ctx.settings.language
        self.language.setCurrentIndex(LANGUAGES.index(lang) if lang in LANGUAGES else 0)
        self.language.setAccessibleName(tr("語言", "Language"))
        self.language.currentIndexChanged.connect(self._on_language)
        prefs.addWidget(self.language)
        prefs.addSpacing(theme.SP[4])
        prefs.addWidget(label(tr("外觀", "Appearance"), "secondary"))
        self.theme_seg = SegmentedControl([tr("深色", "Dark"), tr("淺色", "Light"), tr("跟隨系統", "System")])
        th = self.ctx.settings.theme
        self.theme_seg.setCurrentIndex(THEMES.index(th) if th in THEMES else 0)
        self.theme_seg.currentChanged.connect(self._on_theme)
        prefs.addWidget(self.theme_seg)
        prefs.addStretch(1)
        lay.addLayout(prefs)

        buttons = QHBoxLayout()
        buttons.setSpacing(theme.SP[2])
        buttons.addStretch(1)
        self.later_button = push_button(tr("稍後再說", "Maybe later"), "secondary")
        self.later_button.clicked.connect(self._later)
        buttons.addWidget(self.later_button)
        self.templates_button = push_button(tr("從範本建立設定檔", "Create a profile from a template"), "primary", "plus")
        self.templates_button.clicked.connect(self._templates)
        self.templates_button.setDefault(True)
        buttons.addWidget(self.templates_button)
        lay.addLayout(buttons)

        self._outer.addWidget(content)
        self._content = content
        # wrapped labels: a fixed width and the matching height-for-width, or lines get cut
        content.setFixedWidth(CONTENT_W)
        h = content.heightForWidth(CONTENT_W)
        if h > 0:
            content.setMinimumHeight(h)
            self.setFixedSize(CONTENT_W, h)
        self.templates_button.setFocus()

    # -- actions --------------------------------------------------------------------------------
    def _on_language(self, index: int) -> None:
        if not 0 <= index < len(LANGUAGES):
            return
        lang = LANGUAGES[index]
        self.ctx.settings.language = lang
        resolved = i18n.set_language(lang.value)
        app = QApplication.instance()
        if app is not None:
            install_translator(app, resolved)
        QTimer.singleShot(0, self._build)  # never delete the combo inside its own signal

    def _on_theme(self, index: int) -> None:
        if 0 <= index < len(THEMES):
            self.ctx.settings.theme = THEMES[index]
            change_theme(self.ctx, THEMES[index], save=False)

    def _later(self) -> None:
        self.choice = "later"
        self.accept()

    def _templates(self) -> None:
        self.choice = "templates"
        self.accept()


def _exec_dialog(dlg: QDialog) -> int:
    """Run the dialog modally (tests replace this); headless platforms cannot answer it."""
    if is_headless():
        log.info("welcome dialog skipped (headless platform)")
        return int(QDialog.DialogCode.Rejected)
    return dlg.exec()


def show_welcome_if_needed(ctx: AppContext, parent: QWidget | None = None) -> None:
    """Show WelcomeDialog when ``ctx.settings.first_run_done`` is False; set it afterwards."""
    if ctx.settings.first_run_done:
        return
    dlg = WelcomeDialog(ctx, parent)
    try:
        _exec_dialog(dlg)
        choice = dlg.choice
    finally:
        dlg.deleteLater()
    ctx.settings.first_run_done = True
    ctx.save_settings()
    if choice == "templates":
        if ctx.main_window is not None:
            ctx.navigate("profiles")
        else:
            ctx.extras["start_page"] = "profiles"
