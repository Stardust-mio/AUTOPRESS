# OWNED BY G5
"""Settings page (SPEC section 6.4.5): language (restart), theme (live), hotkeys (capture
fields, conflict check), failsafe, physical-input pause, countdown, resume countdown, confirm
threshold, default typing mode and delays, OCR (state, threads, warm-up; changes and
「重新啟動引擎」 call ctx.ocr.restart(settings.ocr)), history skip, evidence retention, data
folder (open / portable indicator / fallback note), about (version, licenses).

Every change is written at once (``ctx.save_settings()``, which emits ``settings_changed``);
the page reloads its controls when another part of the app changes the settings (e.g. the
sidebar's dark-mode switch). Engine-related OCR changes are debounced (600 ms) before
``ctx.ocr.restart``; OCR and hotkey changes are locked while a run is active.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import __version__, paths
from ..context import AppContext
from ..i18n import tr
from ..models import CodeStatus, Language, ThemeName, TypingMode
from . import theme, widgets
from .settings_hotkey import HotkeyEdit
from .shell_common import change_theme, failsafe_corner_text, open_folder
from .settings_widgets import Section, spin_box
from .widgets import ElidedLabel, SegmentedControl, Spinner, Switch, label, push_button

log = logging.getLogger(__name__)

HOTKEY_TEST_ACTION = "settings_test"  # never "pause_resume" / "stop": those belong to RunFlow
OCR_RESTART_DELAY_MS = 600
REPO_URL = "https://github.com/Stardust-mio/AUTOPRESS"  # 關於: source code and releases (shown as text)
LANGUAGES = (Language.AUTO, Language.ZH_TW, Language.EN)
THEMES = (ThemeName.DARK, ThemeName.LIGHT, ThemeName.SYSTEM)
TYPING_MODES = (TypingMode.UNICODE, TypingMode.CLIPBOARD, TypingMode.VK)
SKIP_CHOICES = (CodeStatus.SUCCESS, CodeStatus.USED, CodeStatus.SUBMITTED, CodeStatus.INVALID, CodeStatus.EXPIRED)
_OCR_STATE = {
    "not_started": (("未啟動", "Not started"), "neutral"),
    "loading": (("載入中…", "Loading…"), "info"),
    "ready": (("就緒", "Ready"), "success"),
    "failed": (("無法使用", "Unavailable"), "error"),
    "disabled": (("已關閉", "Off"), "neutral"),
}


class SettingsPage(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self._loading = False
        self._saving = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(self.scroll)
        body = QWidget()
        body.setObjectName("SettingsBody")
        self._col = QVBoxLayout(body)
        self._col.setContentsMargins(*theme.PAGE_MARGINS)
        self._col.setSpacing(theme.SP[4])
        self._col.addWidget(widgets.section_header(tr("設定", "Settings"),
                                                   tr("變更會立即儲存。", "Changes are saved immediately.")))
        self._ocr_timer = QTimer(self)
        self._ocr_timer.setSingleShot(True)
        self._ocr_timer.setInterval(OCR_RESTART_DELAY_MS)
        self._ocr_timer.timeout.connect(self.restart_ocr)
        for build in (self._build_general, self._build_safety, self._build_input, self._build_ocr,
                      self._build_history, self._build_data, self._build_about):
            self._col.addWidget(build())
        self._col.addStretch(1)
        self.scroll.setWidget(body)

        ctx.signals.settings_changed.connect(self._on_settings_changed)
        try:
            ctx.ocr.state_changed.connect(self._update_ocr_state)
        except Exception:  # noqa: BLE001 - OCR service stub
            log.debug("OCR state signal unavailable", exc_info=True)
        try:
            ctx.session.state_changed.connect(self._update_locks)
        except Exception:  # noqa: BLE001
            log.debug("session state signal unavailable", exc_info=True)
        self.load()
        self._update_ocr_state()
        self._update_locks()

    # ===================================================================== persistence
    def save(self) -> None:
        """Write the settings (``ctx.save_settings``) without reloading this page."""
        self._saving = True
        try:
            self.ctx.save_settings()
        finally:
            self._saving = False

    def _on_settings_changed(self, _settings: object) -> None:
        if not self._saving:
            self.load()

    def _bind(self, setter: Callable[[object], None]) -> Callable[..., None]:
        """Slot wrapper: apply ``setter(value)`` and save, unless the page is loading."""

        def slot(value: object = None, *_rest: object) -> None:
            if self._loading:
                return
            setter(value)
            self.save()

        return slot

    # ===================================================================== cards
    def _build_general(self) -> QWidget:
        s = Section("globe", tr("一般", "General"))
        self.language = widgets.combo([tr("自動（依系統語言）", "Automatic (system language)"), "繁體中文", "English"])
        self.language.currentIndexChanged.connect(self._bind(self._set_language))
        _row, self.language_note = s.add_row(tr("語言", "Language"), self.language,
                                             tr("重新啟動 AutoPress 後生效。", "Takes effect after restarting AutoPress."))
        self.theme_seg = SegmentedControl([tr("深色", "Dark"), tr("淺色", "Light"), tr("跟隨系統", "System")])
        self.theme_seg.currentChanged.connect(self._on_theme)
        s.add_row(tr("外觀", "Appearance"), self.theme_seg, tr("立即套用。", "Applied at once."))
        self.welcome_button = push_button(tr("再顯示一次", "Show again"), "secondary", "sparkle")
        self.welcome_button.clicked.connect(self._reset_welcome)
        # no rule count in the hint, so it cannot drift from the welcome dialog's list
        _row, self.welcome_hint = s.add_row(
            tr("歡迎畫面", "Welcome screen"), self.welcome_button,
            tr("下次啟動時再顯示歡迎畫面與使用原則。", "Show the welcome screen and its rules again at the next start."))
        return s

    def _build_safety(self) -> QWidget:
        s = Section("shield", tr("安全", "Safety"))
        self.failsafe = Switch()
        self.failsafe.toggled.connect(self._bind(lambda v: setattr(self.ctx.settings, "failsafe_enabled", bool(v))))
        _row, self.failsafe_hint = s.add_row(tr("左上角緊急停止", "Top-left emergency stop"), self.failsafe,
                                             failsafe_corner_text())
        self.user_input = Switch()
        self.user_input.toggled.connect(self._bind(lambda v: setattr(self.ctx.settings, "pause_on_user_input", bool(v))))
        s.add_row(tr("偵測到滑鼠或鍵盤操作時暫停", "Pause on mouse or keyboard input"), self.user_input,
                  tr("執行中你一動滑鼠或鍵盤，AutoPress 會在下一次輸入或點擊之前暫停，避免輸入到錯誤的地方。",
                     "If you move the mouse or type during a run, AutoPress pauses before its next keystroke or "
                     "click, so nothing goes to the wrong place."))
        self.countdown = spin_box(0, 10, tr(" 秒", " s"), tr("不倒數", "None"))
        self.countdown.valueChanged.connect(self._bind(lambda v: setattr(self.ctx.settings, "countdown_s", int(v))))
        s.add_row(tr("開始前倒數", "Countdown before a run"), self.countdown,
                  tr("開始兌換、測試一筆，或以「真的執行」測試步驟前，先倒數讓你放開滑鼠。",
                     "Before a run, Test one or a step test with 'Run for real', so you can let go of the mouse."))
        self.resume_countdown = spin_box(0, 10, tr(" 秒", " s"), tr("不倒數", "None"))
        self.resume_countdown.valueChanged.connect(
            self._bind(lambda v: setattr(self.ctx.settings, "resume_countdown_s", int(v))))
        s.add_row(tr("繼續前倒數", "Countdown before resuming"), self.resume_countdown,
                  tr("暫停後按「繼續」時，先倒數再接著做。", "After a pause, Resume counts down first."))
        self.confirm_over = spin_box(0, 100000, tr(" 筆", " codes"), tr("不確認", "Never ask"), 5)
        self.confirm_over.valueChanged.connect(self._bind(lambda v: setattr(self.ctx.settings, "confirm_run_over", int(v))))
        s.add_row(tr("超過幾筆先確認", "Ask before runs over"), self.confirm_over,
                  tr("一次要兌換的序號超過這個數量時，開始前再問一次。", "Ask once more before runs with more codes than this."))
        self.daily_cap = spin_box(0, 100000, tr(" 筆", " codes"), tr("不限制", "No limit"), 5)
        self.daily_cap.valueChanged.connect(self._bind(lambda v: setattr(self.ctx.settings, "daily_cap", int(v))))
        s.add_row(tr("每日上限", "Daily limit"), self.daily_cap,
                  tr("每天（所有遊戲合計）最多嘗試幾筆；0 表示不限制。", "Attempts per day over all games; 0 means no limit."))
        self.minibar = Switch()
        self.minibar.toggled.connect(self._bind(lambda v: setattr(self.ctx.settings, "minibar_enabled", bool(v))))
        s.add_row(tr("執行時顯示迷你控制列", "Show the mini bar during runs"), self.minibar,
                  tr("關閉時主視窗會縮到工作列；快捷鍵註冊失敗時仍會顯示。",
                     "When off, the main window is minimised; it is still shown when a hotkey fails."))
        hk = QWidget()
        hk_lay = QVBoxLayout(hk)
        hk_lay.setContentsMargins(0, theme.SP[2] + 2, 0, theme.SP[2] + 2)
        hk_lay.setSpacing(theme.SP[2])
        self.hotkey_pause = HotkeyEdit()
        self.hotkey_stop = HotkeyEdit()
        self.hotkey_pause.setAccessibleName(tr("暫停／繼續快捷鍵", "Pause / resume hotkey"))
        self.hotkey_stop.setAccessibleName(tr("停止快捷鍵", "Stop hotkey"))
        for title, edit, action in ((tr("暫停／繼續", "Pause / resume"), self.hotkey_pause, "pause_resume"),
                                    (tr("停止", "Stop"), self.hotkey_stop, "stop")):
            line = QHBoxLayout()
            line.setSpacing(theme.SP[4])
            t = label(tr(f"快捷鍵：{title}", f"Hotkey: {title}"), "body")
            t.setBuddy(edit)
            line.addWidget(t, 1)
            line.addWidget(edit, 0, Qt.AlignmentFlag.AlignRight)
            hk_lay.addLayout(line)
            edit.comboChanged.connect(lambda combo, a=action: self.set_hotkey(a, combo))
            edit.rejected.connect(lambda reason: self._hotkey_note(reason, "error"))
        self.hotkey_hint = label(tr("只在執行期間與「真的執行」的步驟測試時註冊，平常不會佔用這些按鍵。點一下欄位，再按下新的組合鍵。",
                                    "Registered only during runs and step tests with 'Run for real'. Click a field, then "
                                    "press the new keys."),
                                 "muted")
        self.hotkey_hint.setWordWrap(True)
        hk_lay.addWidget(self.hotkey_hint)
        self.hotkey_message = label("", "muted")
        self.hotkey_message.setWordWrap(True)
        self.hotkey_message.hide()
        hk_lay.addWidget(self.hotkey_message)
        s.add_widget(hk)
        return s

    def _build_input(self) -> QWidget:
        s = Section("keyboard", tr("輸入", "Input"))
        self.typing_mode = widgets.combo([m.label() for m in TYPING_MODES])
        self.typing_mode.currentIndexChanged.connect(
            self._bind(lambda i: setattr(self.ctx.settings, "default_typing_mode", TYPING_MODES[int(i)])))
        s.add_row(tr("預設輸入方式", "Default typing mode"), self.typing_mode,
                  tr("新增「輸入序號」步驟時預設使用的方式；注音輸入法開著時建議「模擬鍵入」或「貼上」。",
                     "Used by new 'Type code' steps; with a Chinese IME on, use simulated typing or paste."))
        self.delay_spins: dict[str, QSpinBox] = {}
        for attr, title, hint, lo, hi, step in (
                ("after_focus_ms", tr("切換視窗後等待", "Wait after focusing"),
                 tr("切到目標視窗後，等它準備好再動作。", "Let the target settle after it comes to the front."), 0, 10000, 50),
                ("after_click_ms", tr("點擊後等待", "Wait after a click"),
                 tr("點擊之後的預設等待時間。", "Default wait after a click."), 0, 10000, 20),
                ("key_delay_ms", tr("按鍵間隔", "Delay between keys"),
                 tr("每個字元之間的間隔；遊戲漏字時調高。", "Between characters; raise it when a game drops keys."), 0, 1000, 5),
                ("clipboard_restore_ms", tr("貼上後還原剪貼簿", "Restore the clipboard after"),
                 tr("用「貼上」輸入後，過多久把你原本的剪貼簿內容放回去。", "When to put your clipboard back after a paste."),
                 50, 5000, 50)):
            sp = spin_box(lo, hi, " ms", "", step)
            sp.valueChanged.connect(self._bind(lambda v, a=attr: setattr(self.ctx.settings.delays, a, int(v))))
            self.delay_spins[attr] = sp
            s.add_row(title, sp, hint)
        note = label(tr("這些是新步驟的預設值；已建立的步驟各自保留自己的設定。",
                        "These are defaults for new steps; existing steps keep their own values."), "muted")
        note.setWordWrap(True)
        s.add_widget(note)
        return s

    def _build_ocr(self) -> QWidget:
        s = Section("scan", tr("文字辨識", "Text recognition (OCR)"))
        state = QWidget()
        st_lay = QHBoxLayout(state)
        st_lay.setContentsMargins(0, theme.SP[2] + 2, 0, theme.SP[2] + 2)
        st_lay.setSpacing(theme.SP[2])
        col = QVBoxLayout()
        col.setSpacing(2)
        line = QHBoxLayout()
        line.setSpacing(theme.SP[2])
        line.addWidget(label(tr("引擎狀態", "Engine"), "body"))
        self.ocr_spinner = Spinner(14)
        line.addWidget(self.ocr_spinner, 0, Qt.AlignmentFlag.AlignVCenter)
        self.ocr_state_label = label("", "secondary")
        line.addWidget(self.ocr_state_label)
        line.addStretch(1)
        col.addLayout(line)
        self.ocr_error = label("", "error")
        self.ocr_error.setWordWrap(True)
        self.ocr_error.hide()
        col.addWidget(self.ocr_error)
        st_lay.addLayout(col, 1)
        self.ocr_restart_button = push_button(tr("重新啟動引擎", "Restart engine"), "secondary", "refresh")
        self.ocr_restart_button.clicked.connect(self.restart_ocr)
        st_lay.addWidget(self.ocr_restart_button, 0, Qt.AlignmentFlag.AlignVCenter)
        s.add_widget(state)
        self.ocr_enabled = Switch()
        self.ocr_enabled.toggled.connect(self._bind(lambda v: self._set_ocr("enabled", bool(v))))
        s.add_row(tr("啟用文字辨識", "Use text recognition"), self.ocr_enabled,
                  tr("關閉後無法辨識圖片中的序號，也無法用「點擊文字」和「辨識結果」步驟。",
                     "When off, codes cannot be read from images and OCR steps cannot run."))
        self.ocr_threads = spin_box(0, 32, "", tr("全部核心", "All cores"))
        self.ocr_threads.valueChanged.connect(self._bind(lambda v: self._set_ocr("threads", int(v) or -1)))
        s.add_row(tr("使用的 CPU 執行緒", "CPU threads"), self.ocr_threads,
                  tr(f"預設 4，執行時不會拖慢遊戲；這台電腦有 {os.cpu_count() or 1} 個。",
                     f"Default 4 keeps runs light on the game; this PC has {os.cpu_count() or 1}."))
        self.ocr_warmup = Switch()
        self.ocr_warmup.toggled.connect(self._bind(lambda v: self._set_ocr("warmup_on_start", bool(v))))
        s.add_row(tr("啟動時預先載入", "Load at startup"), self.ocr_warmup,
                  tr("開啟 AutoPress 時先載入引擎，第一次辨識比較快。", "Load the engine at start so the first read is fast."))
        self.review_threshold = QDoubleSpinBox()
        self.review_threshold.setRange(0.5, 1.0)
        self.review_threshold.setSingleStep(0.01)
        self.review_threshold.setDecimals(2)
        self.review_threshold.setKeyboardTracking(False)
        self.review_threshold.setFixedWidth(130)
        self.review_threshold.valueChanged.connect(
            self._bind(lambda v: setattr(self.ctx.settings.ocr, "review_threshold", round(float(v), 2))))
        s.add_row(tr("需確認門檻", "Review threshold"), self.review_threshold,
                  tr("辨識信心低於這個值的字元會標成「需確認」（預設 0.95）。",
                     "Characters read with a lower confidence are marked 'Needs review' (default 0.95)."))
        return s

    def _build_history(self) -> QWidget:
        s = Section("history", tr("紀錄", "History"))
        self.skip_history = Switch()
        self.skip_history.toggled.connect(
            self._bind(lambda v: setattr(self.ctx.settings, "skip_history_on_import", bool(v))))
        s.add_row(tr("略過已兌換過的序號", "Skip codes already redeemed"), self.skip_history,
                  tr("匯入與開始兌換時，紀錄裡同一款遊戲已是下列狀態的序號會自動略過。",
                     "On import and before a run, codes of the same game with these statuses are skipped."))
        boxes = QWidget()
        b_lay = QHBoxLayout(boxes)
        b_lay.setContentsMargins(0, theme.SP[2], 0, theme.SP[2])
        b_lay.setSpacing(theme.SP[4])
        self.skip_boxes: dict[CodeStatus, QCheckBox] = {}
        for st in SKIP_CHOICES:
            cb = QCheckBox(st.label())
            cb.setCursor(Qt.CursorShape.PointingHandCursor)
            cb.toggled.connect(self._bind(lambda _v: self._set_skip_statuses()))
            self.skip_boxes[st] = cb
            b_lay.addWidget(cb)
        b_lay.addStretch(1)
        s.add_widget(boxes)
        self.save_evidence = Switch()
        self.save_evidence.toggled.connect(self._bind(lambda v: setattr(self.ctx.settings, "save_evidence", bool(v))))
        s.add_row(tr("保存結果截圖", "Keep result screenshots"), self.save_evidence,
                  tr("「辨識結果」步驟把結果區的截圖存成證據；截圖可能含有你的帳號名稱。",
                     "'Read result' steps keep a crop of the result area; it may show your account name."))
        self.keep_days = spin_box(0, 3650, tr(" 天", " days"), tr("永久保留", "Keep forever"), 5)
        self.keep_days.valueChanged.connect(self._bind(lambda v: setattr(self.ctx.settings, "evidence_keep_days", int(v))))
        s.add_row(tr("截圖保留天數", "Keep screenshots for"), self.keep_days,
                  tr("較舊的截圖會在啟動時刪除。", "Older screenshots are deleted at startup."))
        self.clear_history_button = push_button(tr("清除紀錄…", "Clear history…"), "danger", "trash")
        self.clear_history_button.clicked.connect(self.clear_history)
        s.add_row(tr("清除所有兌換紀錄", "Clear all history"), self.clear_history_button,
                  tr("刪除後，之前兌換過的序號不會再被自動略過。", "Afterwards, earlier codes are no longer skipped."))
        return s

    def _build_data(self) -> QWidget:
        s = Section("database", tr("資料", "Data"))
        path, intended = paths.resolve_data_dir()
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, theme.SP[2] + 2, 0, theme.SP[2] + 2)
        lay.setSpacing(theme.SP[2])
        line = QHBoxLayout()
        line.setSpacing(theme.SP[3])
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(label(tr("資料資料夾", "Data folder"), "body"))
        self.data_path = ElidedLabel(str(path))
        self.data_path.setProperty("role", "secondary")
        col.addWidget(self.data_path)
        line.addLayout(col, 1)
        open_btn = push_button(tr("開啟資料夾", "Open folder"), "secondary", "folder")
        open_btn.clicked.connect(lambda: open_folder(paths.data_dir()))
        line.addWidget(open_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(line)
        info = label(tr("設定、設定檔、序號佇列、紀錄與截圖都只存在這台電腦。",
                        "Settings, profiles, the code queue, history and screenshots stay on this PC."), "muted")
        info.setWordWrap(True)
        lay.addWidget(info)
        s.add_widget(box)
        portable = paths.is_portable()
        self.portable_label = label(tr("開（資料存在程式資料夾的 data 裡）", "On (data next to the program)") if portable
                                    else tr("關", "Off"), "secondary")
        s.add_row(tr("可攜模式", "Portable mode"), self.portable_label,
                  tr("在 AutoPress.exe 旁邊放一個 portable.txt 檔案，重新啟動後資料就會存在程式資料夾裡（可放隨身碟）。",
                     "Put a file portable.txt next to AutoPress.exe and restart: data then lives in the program folder."))
        self.fallback_note = label("", "warning")
        self.fallback_note.setWordWrap(True)
        if intended is not None:
            self.fallback_note.setText(tr(f"無法寫入資料資料夾 {intended}，改用 {path}。",
                                          f"Cannot write to {intended}; using {path}."))
            s.add_widget(self.fallback_note)
        return s

    def _build_about(self) -> QWidget:
        s = Section("info", tr("關於", "About"))
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, theme.SP[2] + 2, 0, theme.SP[2] + 2)
        lay.setSpacing(theme.SP[1] + 2)
        self.version_label = label(f"AutoPress v{__version__}", "strong")
        lay.addWidget(self.version_label)
        for text in (tr("以 GPL-3.0 授權釋出的開放原始碼軟體。", "Open-source software under the GPL-3.0 licence."),
                     tr("離線運作：不連網、不檢查更新、沒有遙測；序號只存在這台電腦。",
                        "Works offline: no network, no update checks, no telemetry; codes stay on this PC."),
                     tr(f"原始碼與新版下載：{REPO_URL}", f"Source code and new versions: {REPO_URL}")):
            lb = label(text, "secondary")
            lb.setWordWrap(True)
            if REPO_URL in text:  # plain text the user can select and copy (AutoPress never opens it)
                lb.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lay.addWidget(lb)
        row = QHBoxLayout()
        row.setSpacing(theme.SP[2])
        for text, name in ((tr("授權條款", "Licence"), "LICENSE"),
                           (tr("第三方授權", "Third-party notices"), "THIRD-PARTY-NOTICES.md")):
            b = push_button(text, "ghost", "file")
            target = paths.app_dir() / name
            b.setEnabled(target.is_file())
            if not target.is_file():
                b.setToolTip(tr("發佈版本才會附上這個檔案。", "This file ships with the release build."))
            b.clicked.connect(lambda _c=False, t=target: open_folder(t, create=False))
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        s.add_widget(box)
        return s

    # ===================================================================== load
    def load(self) -> None:
        """Show ``ctx.settings`` in every control (no saving while loading)."""
        st = self.ctx.settings
        self._loading = True
        try:
            self.language.setCurrentIndex(LANGUAGES.index(st.language) if st.language in LANGUAGES else 0)
            self.theme_seg.setCurrentIndex(THEMES.index(st.theme) if st.theme in THEMES else 0)
            self.failsafe.setChecked(st.failsafe_enabled)
            self.failsafe_hint.setText(failsafe_corner_text())
            self.user_input.setChecked(st.pause_on_user_input)
            self.countdown.setValue(st.countdown_s)
            self.resume_countdown.setValue(st.resume_countdown_s)
            self.confirm_over.setValue(st.confirm_run_over)
            self.daily_cap.setValue(st.daily_cap)
            self.minibar.setChecked(st.minibar_enabled)
            self.hotkey_pause.setCombo(st.hotkeys.pause_resume)
            self.hotkey_stop.setCombo(st.hotkeys.stop)
            mode = st.default_typing_mode
            self.typing_mode.setCurrentIndex(TYPING_MODES.index(mode) if mode in TYPING_MODES else 0)
            for attr, sp in self.delay_spins.items():
                sp.setValue(int(getattr(st.delays, attr)))
            self.ocr_enabled.setChecked(st.ocr.enabled)
            self.ocr_threads.setValue(max(0, st.ocr.threads))
            self.ocr_warmup.setChecked(st.ocr.warmup_on_start)
            self.review_threshold.setValue(st.ocr.review_threshold)
            self.skip_history.setChecked(st.skip_history_on_import)
            for status, cb in self.skip_boxes.items():
                cb.setChecked(status in st.history_skip_statuses)
            self.save_evidence.setChecked(st.save_evidence)
            self.keep_days.setValue(st.evidence_keep_days)
        finally:
            self._loading = False

    # ===================================================================== general
    def _set_language(self, index: object) -> None:
        lang = LANGUAGES[int(index)] if 0 <= int(index) < len(LANGUAGES) else Language.AUTO  # type: ignore[arg-type]
        changed = lang != self.ctx.settings.language
        self.ctx.settings.language = lang
        if changed:
            self.language_note.setText(tr("已儲存，重新啟動 AutoPress 後生效。", "Saved; restart AutoPress to apply it."))
            self.language_note.setProperty("role", "warning")
            self.language_note.style().unpolish(self.language_note)
            self.language_note.style().polish(self.language_note)

    def _on_theme(self, index: int) -> None:
        if self._loading or not 0 <= index < len(THEMES):
            return
        self._saving = True
        try:
            change_theme(self.ctx, THEMES[index])
        finally:
            self._saving = False

    def _reset_welcome(self) -> None:
        self.ctx.settings.first_run_done = False
        self.save()
        self.ctx.notify(tr("下次啟動時會再顯示歡迎畫面。", "The welcome screen appears at the next start."), "success")

    # ===================================================================== hotkeys
    def _hotkey_note(self, text: str, tone: str) -> None:
        self.hotkey_message.setText(text)
        self.hotkey_message.setProperty("role", {"error": "error", "success": "success"}.get(tone, "muted"))
        st = self.hotkey_message.style()
        st.unpolish(self.hotkey_message)
        st.polish(self.hotkey_message)
        self.hotkey_message.setVisible(bool(text))

    def set_hotkey(self, action: str, combo: str) -> bool:
        """Validate, test against other programs (temporary register + unregister) and save
        ``combo`` for ``action`` ("pause_resume" | "stop"). Returns True when saved."""
        hk = self.ctx.settings.hotkeys
        edit = self.hotkey_pause if action == "pause_resume" else self.hotkey_stop
        other = hk.stop if action == "pause_resume" else hk.pause_resume
        if self._run_active():
            self._hotkey_note(tr("執行中不能更換快捷鍵。", "Hotkeys cannot be changed during a run."), "error")
            return False
        if combo == other:
            self._hotkey_note(tr("暫停與停止不能用同一個快捷鍵。", "Pause and stop need different hotkeys."), "error")
            return False
        note = ""
        try:
            res = self.ctx.hotkeys.register(HOTKEY_TEST_ACTION, combo)
            if getattr(res, "ok", False):
                self.ctx.hotkeys.unregister(HOTKEY_TEST_ACTION)
            elif getattr(res, "error", 0) == 1409:
                self._hotkey_note(tr(f"快捷鍵 {combo} 已被其他程式使用，請換一個。",
                                     f"Hotkey {combo} is used by another program; choose another one."), "error")
                return False
            else:
                note = tr("（目前無法檢查是否被其他程式使用）", " (could not check other programs)")
        except Exception:  # noqa: BLE001 - hotkey service unavailable: save without the check
            log.debug("hotkey conflict test failed", exc_info=True)
            note = tr("（目前無法檢查是否被其他程式使用）", " (could not check other programs)")
        setattr(hk, action, combo)
        self.save()
        edit.setCombo(combo)
        self._hotkey_note(tr(f"已改成 {combo}。", f"Changed to {combo}.") + note, "success")
        return True

    # ===================================================================== OCR
    def _set_ocr(self, attr: str, value: object) -> None:
        setattr(self.ctx.settings.ocr, attr, value)
        self._ocr_timer.start()

    def restart_ocr(self) -> None:
        """「重新啟動引擎」: ctx.ocr.restart(settings.ocr) (also after debounced OCR changes)."""
        self._ocr_timer.stop()
        if self._run_active():
            self.ctx.notify(tr("執行中不能重新啟動文字辨識引擎。", "The OCR engine cannot restart during a run."), "warning")
            return
        try:
            self.ctx.ocr.restart(self.ctx.settings.ocr)
        except Exception:  # noqa: BLE001
            log.exception("OCR restart failed")
        self._update_ocr_state()

    def _update_ocr_state(self, *_args: object) -> None:
        try:
            state = str(getattr(self.ctx.ocr.state, "value", self.ctx.ocr.state))
            error = self.ctx.ocr.error if state == "failed" else ""
        except Exception:  # noqa: BLE001 - service stub
            state, error = "not_started", ""
        (zh_en, tone) = _OCR_STATE.get(state, _OCR_STATE["not_started"])
        self.ocr_state_label.setText(tr(*zh_en))
        role = {"success": "success", "error": "error", "info": "info"}.get(tone, "secondary")
        self.ocr_state_label.setProperty("role", role)
        self.ocr_state_label.style().unpolish(self.ocr_state_label)
        self.ocr_state_label.style().polish(self.ocr_state_label)
        if state == "loading":
            self.ocr_spinner.start()
        else:
            self.ocr_spinner.stop()
        if error:
            self.ocr_error.setText(tr(f"文字辨識引擎無法啟動：{error}。請重新下載完整的壓縮檔並解壓縮，或檢查防毒軟體是否隔離了檔案。",
                                      f"The OCR engine could not start: {error}. Download and unzip the full package "
                                      "again, or check whether antivirus quarantined files."))
        self.ocr_error.setVisible(bool(error))

    # ===================================================================== history
    def _set_skip_statuses(self) -> None:
        self.ctx.settings.history_skip_statuses = [s for s in SKIP_CHOICES if self.skip_boxes[s].isChecked()]

    def clear_history(self) -> int:
        """Confirm, then remove every history record. Returns the number removed (0 = cancelled)."""
        if self._run_active():
            return 0
        parent = self.window() if self.window() is not None else self
        if not widgets.confirm(parent, tr("清除所有兌換紀錄？", "Clear all history?"),
                               tr("所有兌換紀錄都會刪除（截圖檔案保留到期滿）。之後匯入的序號不會再依紀錄自動略過。",
                                  "Every history record is removed (screenshots stay until they expire). Later imports "
                                  "are no longer skipped by history."),
                               tr("清除", "Clear"), danger=True):
            return 0
        try:
            n = int(self.ctx.history.clear())
        except Exception:  # noqa: BLE001
            log.exception("clearing the history failed")
            self.ctx.notify(tr("無法清除紀錄（已記錄在紀錄檔）。", "The history could not be cleared (see the log)."), "error")
            return 0
        self.ctx.notify(tr(f"已清除 {n} 筆紀錄。", f"Removed {n} records."), "success")
        return n

    # ===================================================================== locks
    def _run_active(self) -> bool:
        try:
            return bool(self.ctx.session.is_active())
        except Exception:  # noqa: BLE001
            return False

    def _update_locks(self, *_args: object) -> None:
        """While a run (or a real step test) is active: hotkeys, OCR engine and history clearing
        are locked (they would disturb the run)."""
        active = self._run_active()
        tip = tr("執行中無法變更", "Locked during a run") if active else ""
        for w in (self.hotkey_pause, self.hotkey_stop, self.ocr_enabled, self.ocr_threads, self.ocr_warmup,
                  self.ocr_restart_button, self.clear_history_button):
            w.setEnabled(not active)
            if active:
                w.setToolTip(tip)
        if not active:
            self.ocr_restart_button.setToolTip("")
            self.clear_history_button.setToolTip("")

