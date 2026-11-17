# OWNED BY G6
"""Codes page (SPEC section 6.4.1; mock-up docs/research/ux/codes_dark.png): import toolbar
(貼上文字 Ctrl+V, 開啟檔案 Ctrl+O, 圖片辨識 + drag-and-drop, 剪貼簿圖片, 框選螢幕), active
profile + code format, game filter (active profile's game + unassigned; 「所有遊戲」), search,
status filter, the queue table, banners (no profile; unassigned codes; review), bulk actions,
empty state; switch 略過已兌換過的序號 (Settings.skip_history_on_import); bulk 移除 / 標記為已兌換
(SUCCESS + a history record) / 略過 / 確認無誤 and 重設為待兌換 (queue.reset) / 指定給目前遊戲
(queue.assign_game); buttons 試跑 1 筆 and 開始兌換 run through a page-owned ui.run_flow.RunFlow
that is created LAZILY on first click - while G7's RunFlow (or overlays.pick) still raises
NotImplementedError the click shows a 「尚未實作」 toast, so CodesPage(ctx) always builds (T11).
Disabled buttons say why (tooltip + inline hint). During a run the items of the active plan are
read-only (edit / remove / move disabled, 「執行中，請先停止」).

Layout notes: the 略過已兌換過的序號 switch sits in the import card (it is an import option) and
the table card's top row holds the 6 status segments, the game filter and the search, so the page
fits the 1100 px minimum window. Bulk actions act on the SELECTED rows; the check boxes are
``CodeItem.checked`` (「只跑勾選的」). Import dialogs open window-modal (``open()``), one at a time.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QDialog, QWidget

from ..context import AppContext
from ..i18n import tr
from ..models import CodeItem, CodeStatus, PlanMode, RunSelection
from . import widgets
from .codes_actions import CodesActionsMixin
from .codes_imports import CodesImportsMixin
from .codes_layout import CodesLayoutMixin, DropOverlay
from .codes_common import (
    AUTO_FORMAT,
    NO_PROFILE,
    NOT_IMPLEMENTED,
    default_format_choice,
    format_choices,
    game_name,
    skip_note,
)
from .codes_model import COL_CODE, COL_MORE, FILTER_LABELS, FILTERS, CodesFilterProxy, CodesTableModel, filter_accepts
from .codes_paint import code_column_width

log = logging.getLogger(__name__)


class CodesPage(CodesLayoutMixin, CodesImportsMixin, CodesActionsMixin, QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.setObjectName("CodesPage")
        self.setAcceptDrops(True)
        self._profile = ctx.active_profile()
        self._run_flow: object | None = None
        self._dupes_removed = 0
        self._review_dismissed = -1
        self._last_games: list[tuple[str, str]] | None = None
        self._segment_labels: list[str] = []
        self._format_keys: list[str] = []
        self._game_keys: list[str | None] = []
        self._dialog: QDialog | None = None
        self._pending: deque[Callable[[], None]] = deque()
        self._last_dir = ""
        self._format_cache: dict[str, object] = {}
        self._refresh_timer = self._timer(self.refresh)  # coalesces queue events into one refresh
        self._place_timer = self._timer(self._place_format_box)
        self._import_timer = self._timer(self._next_import)

        self._model = CodesTableModel(ctx.queue, self)
        self._model.code_editor = self._apply_code_edit
        self._proxy = CodesFilterProxy(self)
        self._proxy.setSourceModel(self._model)
        self._build_ui()
        self._drop_overlay = DropOverlay(self)
        self._connect()
        self._apply_profile()
        self._on_run_state("", "")

    def _timer(self, slot: Callable[[], None]) -> QTimer:
        # a child timer dies with the page, so a deferred call never reaches a deleted page
        t = QTimer(self)
        t.setSingleShot(True)
        t.setInterval(0)
        t.timeout.connect(slot)
        return t

    # =========================================================================== wiring
    def _connect(self) -> None:
        s = self.ctx.signals
        s.profiles_changed.connect(self._on_profiles_changed)
        s.active_profile_changed.connect(self._on_active_profile_changed)
        s.settings_changed.connect(self._on_settings_changed)
        s.theme_changed.connect(self._on_theme_changed)
        session = self.ctx.session
        session.state_changed.connect(self._on_run_state)
        session.finished.connect(self._on_run_finished)
        self._model.itemsChanged.connect(self._refresh_timer.start)
        for sig in (self._proxy.rowsInserted, self._proxy.rowsRemoved, self._proxy.modelReset,
                    self._proxy.layoutChanged):
            sig.connect(self._refresh_timer.start)
        for key, slot in ((QKeySequence.StandardKey.Paste, self._paste_shortcut),
                          (QKeySequence.StandardKey.Open, self.open_file_dialog)):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(slot)

    def _on_theme_changed(self, _name: str) -> None:
        self._table.viewport().update()
        self._drop_overlay.update()

    def _on_settings_changed(self, settings: object) -> None:
        want = bool(self.ctx.settings.skip_history_on_import)
        if self._skip_switch.isChecked() != want:
            self._skip_switch.blockSignals(True)
            self._skip_switch.setChecked(want)
            self._skip_switch.blockSignals(False)
        self._skip_note.setText(skip_note(self.ctx, self._profile))
        self.refresh()

    def _on_skip_toggled(self, on: bool) -> None:
        if bool(self.ctx.settings.skip_history_on_import) != bool(on):
            self.ctx.settings.skip_history_on_import = bool(on)
            self.ctx.save_settings()

    def _on_segment(self, index: int) -> None:
        if 0 <= index < len(FILTERS):
            self._proxy.set_filter(FILTERS[index])

    def _on_game_activated(self, index: int) -> None:
        if 0 <= index < len(self._game_keys):
            self._proxy.set_game(self._game_keys[index])
            self.refresh()

    def _clear_filters(self) -> None:
        if self._proxy.filter_key() != "all":
            self._segments.setCurrentIndex(0)
            self._proxy.set_filter("all")
        self._search.clear()
        if not self._scope_items() and len(self.ctx.queue):
            self._set_game(None)
        self.refresh()

    def _on_table_clicked(self, index: object) -> None:
        if getattr(index, "column", lambda: -1)() == COL_MORE:
            rect = self._table.visualRect(index)  # type: ignore[arg-type]
            self.show_row_menu(index.row(), self._table.viewport().mapToGlobal(rect.bottomLeft()))  # type: ignore[attr-defined]

    def _on_context_menu(self, pos: object) -> None:
        index = self._table.indexAt(pos)  # type: ignore[arg-type]
        if index.isValid():
            self.show_row_menu(index.row(), self._table.viewport().mapToGlobal(pos))  # type: ignore[arg-type]

    # =========================================================================== profile
    def _on_active_profile_changed(self, _profile_id: str) -> None:
        self._apply_profile()

    def _on_profiles_changed(self) -> None:
        """A profile was saved / renamed / deleted: reload, keeping the user's format and game
        choices while the active profile stays the same."""
        old = self._profile.id if self._profile is not None else ""
        new = self.ctx.active_profile()
        self._apply_profile(reset=(new.id if new is not None else "") != old)

    def _apply_profile(self, reset: bool = True) -> None:
        """(Re)load the active profile: profile combo, format combo, game filter, banners."""
        self._profile = self.ctx.active_profile()
        self._format_cache = {}
        self._reload_profile_combo()
        self._reload_formats(keep=not reset)
        self._rebuild_unassigned_banner()
        self._reload_games(reset=reset)
        self._skip_note.setText(skip_note(self.ctx, self._profile))
        self.refresh()

    def _reload_profile_combo(self) -> None:
        profiles = self.ctx.profiles.list()
        combo = self._profile_combo
        combo.blockSignals(True)
        combo.clear()
        for p in profiles:
            combo.addItem(p.name or tr("（未命名）", "(unnamed)"), p.id)
            combo.setItemData(combo.count() - 1, tr("遊戲：{game}", "Game: {game}").format(game=game_name(p)),
                              Qt.ItemDataRole.ToolTipRole)
        active = self._profile.id if self._profile is not None else ""
        combo.setPlaceholderText(tr("選擇設定檔…", "Choose a profile…") if profiles else tr("沒有設定檔", "No profiles"))
        combo.setCurrentIndex(next((n for n, p in enumerate(profiles) if p.id == active), -1))
        combo.setEnabled(bool(profiles))
        combo.blockSignals(False)

    def _on_profile_activated(self, index: int) -> None:
        pid = self._profile_combo.itemData(index)
        if pid and pid != self.ctx.settings.active_profile_id:
            self.ctx.set_active_profile(str(pid))  # emits active_profile_changed -> _apply_profile

    def _reload_formats(self, keep: bool = False) -> None:
        previous = self.format_choice() if keep and self._format_keys else ""
        choices = format_choices(self._profile)
        self._format_keys = [k for k, _label in choices]
        combo = self._format_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItems([label for _k, label in choices])
        want = previous if previous in self._format_keys else default_format_choice(self._profile)
        combo.setCurrentIndex(self._format_keys.index(want))
        combo.view().setMinimumWidth(combo.view().sizeHintForColumn(0) + 32)  # the popup shows full names
        combo.blockSignals(False)

    def format_choice(self) -> str:
        """Key of the 格式 combo (codes_common.format_choices) used for the next import."""
        i = self._format_combo.currentIndex()
        return self._format_keys[i] if 0 <= i < len(self._format_keys) else AUTO_FORMAT

    def _reload_games(self, reset: bool = False) -> None:
        p = self._profile
        entries: list[tuple[str, str | None]] = []
        if p is not None:
            entries.append((tr("{game}（含未指定）", "{game} (+ unassigned)").format(game=game_name(p)), p.game_key()))
        entries.append((tr("所有遊戲", "All games"), None))
        if p is None:
            entries.append((tr("未指定遊戲", "No game assigned"), ""))
        games = self.ctx.queue.games()
        self._last_games = list(games)
        for key, name in games:
            if key and (p is None or key != p.game_key()):
                entries.append((tr("{game}（含未指定）", "{game} (+ unassigned)").format(game=name or key), key))
        default = p.game_key() if p is not None else None
        want = default if reset else self._proxy.game()
        keys = [k for _label, k in entries]
        idx = keys.index(want) if want in keys else keys.index(default)
        combo = self._game_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItems([label for label, _k in entries])
        combo.setCurrentIndex(idx)
        combo.blockSignals(False)
        self._game_keys = keys
        self._proxy.set_game(keys[idx])

    def _set_game(self, game_key: str | None) -> None:
        if game_key in self._game_keys:
            self._game_combo.setCurrentIndex(self._game_keys.index(game_key))
            self._proxy.set_game(game_key)

    def _rebuild_unassigned_banner(self) -> None:
        if self._unassigned_banner is not None:
            self._banner_box.removeWidget(self._unassigned_banner)
            self._unassigned_banner.deleteLater()
            self._unassigned_banner = None
        if self._profile is None:
            return
        action = tr("指定給「{game}」", 'Assign to "{game}"').format(game=game_name(self._profile))
        banner = widgets.Banner("info", "", action, False)
        banner.actionClicked.connect(self.assign_unassigned)
        banner.hide()
        self._banner_box.insertWidget(1, banner)
        self._unassigned_banner = banner

    # =========================================================================== refresh
    def _scope_items(self) -> list[CodeItem]:
        """Queue items that pass the game filter (the counts and banners use this scope)."""
        return [it for it in self.ctx.queue.items() if self._proxy.game_accepts(it.game_key)]

    def refresh(self) -> None:
        """Counts, subtitle, banners, run buttons, empty state and bulk bar (normally coalesced)."""
        self._refresh_timer.stop()
        items = self.ctx.queue.items()
        games = self.ctx.queue.games()
        if games != self._last_games:
            self._reload_games(reset=False)
        scope = [it for it in items if self._proxy.game_accepts(it.game_key)]
        width = code_column_width(it.code for it in items)
        if width != self._table.columnWidth(COL_CODE):
            self._table.setColumnWidth(COL_CODE, width)
        labels = [f"{FILTER_LABELS[k]} {sum(1 for it in scope if filter_accepts(k, it.status))}" for k in FILTERS]
        if labels != self._segment_labels:
            current = FILTERS.index(self._proxy.filter_key())
            self._segments.blockSignals(True)
            self._segments.setItems(labels)
            if self._segments.currentIndex() != current:
                self._segments.setCurrentIndex(current)
            self._segments.blockSignals(False)
            self._segment_labels = labels
        self._subtitle.setText(self._subtitle_text(scope))
        self._update_banners(items, scope)
        self._update_run_buttons()
        if not scope:
            if items:
                others = len(items)
                self._no_match_label.setText(tr("「{game}」還沒有序號；其他遊戲有 {n} 筆。",
                                                'No codes for "{game}" yet; other games have {n}.')
                                             .format(game=game_name(self._profile), n=others))
                self._no_match_btn.setText(tr("顯示所有遊戲", "Show all games"))
                self._stack.setCurrentIndex(2)
            else:
                self._stack.setCurrentIndex(1)
        elif self._proxy.rowCount() == 0:
            self._no_match_label.setText(tr("沒有符合篩選條件的序號", "No codes match the filters"))
            self._no_match_btn.setText(tr("清除篩選", "Clear filters"))
            self._stack.setCurrentIndex(2)
        else:
            self._stack.setCurrentIndex(0)
        for w in self._bulk_widgets:
            w.setVisible(bool(scope))
        self._update_bulk_bar()

    def _subtitle_text(self, scope: list[CodeItem]) -> str:
        if not scope:
            text = tr("尚未新增序號", "No codes yet")
        else:
            parts = [tr("{n} 筆", "{n} codes").format(n=len(scope))]
            sources = len({it.source for it in scope})
            if sources > 1:
                parts.append(tr("來自 {s} 個來源", "from {s} sources").format(s=sources))
            text = " · ".join(parts)
        if self._dupes_removed:
            text += " · " + tr("已去除 {d} 筆重複", "{d} duplicates removed").format(d=self._dupes_removed)
        return text

    def _update_banners(self, items: list[CodeItem], scope: list[CodeItem]) -> None:
        self._no_profile_banner.setVisible(self._profile is None)
        unassigned = sum(1 for it in items if not it.game_key)
        if self._unassigned_banner is not None:
            self._unassigned_text = tr("{n} 筆序號尚未指定遊戲，這次不會執行。",
                                       "{n} codes have no game yet and will not run.").format(n=unassigned)
            self._unassigned_banner.setText(self._unassigned_text)  # type: ignore[attr-defined]
            self._unassigned_banner.setVisible(unassigned > 0)
        review = sum(1 for it in scope if it.status is CodeStatus.REVIEW)
        if review <= self._review_dismissed:
            self._review_dismissed = min(self._review_dismissed, review)
        else:
            self._review_dismissed = -1
        self._review_text = tr("{n} 筆序號需要確認（辨識信心偏低或字元已修正）",
                               "{n} codes need review (low OCR confidence or corrected characters)").format(n=review)
        self._review_banner.setText(self._review_text)
        self._review_banner.setVisible(review > 0 and self._review_dismissed < 0)

    def _dismiss_review(self) -> None:
        self._review_dismissed = sum(1 for it in self._scope_items() if it.status is CodeStatus.REVIEW)

    def banner_texts(self) -> dict[str, str]:
        """Visible banners -> text (for tests and screenshots)."""
        out = {}
        if self._no_profile_banner.isVisibleTo(self):
            out["no_profile"] = str(NO_PROFILE)
        if self._unassigned_banner is not None and self._unassigned_banner.isVisibleTo(self):
            out["unassigned"] = self._unassigned_text
        if self._review_banner.isVisibleTo(self):
            out["review"] = self._review_text
        return out

    def _update_bulk_bar(self, *_args: object) -> None:
        items = self.selected_items()
        free = [it for it in items if self._model.can_edit(it)]
        self._sel_label.setText(tr("已選取 {n} 筆", "{n} selected").format(n=len(items)))
        for b in (self._btn_remove, self._btn_up, self._btn_down):
            b.setEnabled(bool(free))
        self._btn_mark.setEnabled(any(it.status is not CodeStatus.SUCCESS for it in free))
        self._btn_confirm.setEnabled(any(it.status is CodeStatus.REVIEW for it in free))
        unskip = bool(free) and all(it.status is CodeStatus.SKIPPED for it in free)
        self._btn_skip.setText(tr("取消略過", "Un-skip") if unskip else tr("略過", "Skip"))
        self._btn_skip.setEnabled(unskip or any(it.status in (CodeStatus.PENDING, CodeStatus.COOLDOWN,
                                                              CodeStatus.REVIEW, CodeStatus.FAILED) for it in free))
        if len(free) < len(items):
            self._sel_label.setText(self._sel_label.text() + " · " + tr("執行中的序號不能修改", "running codes are read-only"))
        self._btn_export.setEnabled(self._proxy.rowCount() > 0)
        self._update_run_buttons()

    # =========================================================================== run
    def run_status(self) -> tuple[bool, str, bool, str]:
        """(開始兌換 enabled, its tooltip / reason, 試跑 1 筆 enabled, its tooltip / reason)."""
        if self.ctx.session.is_active():
            reason = tr("正在執行中", "A run is in progress")
            return False, reason, False, reason
        p = self._profile
        if p is None:
            return False, str(NO_PROFILE), False, str(NO_PROFILE)
        key = p.game_key()
        runnable = self.ctx.queue.runnable(RunSelection.UNFINISHED, key)
        if not runnable:
            unassigned = sum(1 for it in self.ctx.queue.items() if not it.game_key)
            if unassigned:
                reason = tr("沒有「{game}」可兌換的序號；{n} 筆序號尚未指定遊戲",
                            'No codes to redeem for "{game}"; {n} codes have no game yet').format(
                    game=game_name(p), n=unassigned)
            else:
                reason = tr("沒有「{game}」可兌換的序號", 'No codes to redeem for "{game}"').format(game=game_name(p))
            return False, reason, False, reason
        test = self._test_item()
        test_tip = tr("先實際兌換 1 筆看看結果：{code}", "Redeem one code first to check the result: {code}").format(
            code=test.code if test is not None else "")
        selection = RunSelection(self.ctx.settings.run_selection)
        todo = self.ctx.queue.runnable(selection, key)
        if not todo:
            return (False, tr("沒有勾選的待兌換序號（執行設定為「只跑勾選的」）",
                              "No checked codes to redeem (the run setting is 'Checked only')"), True, test_tip)
        return True, tr("依序兌換 {n} 筆「{game}」的序號", 'Redeem {n} codes of "{game}" one by one').format(
            n=len(todo), game=game_name(p)), True, test_tip

    def _update_run_buttons(self) -> None:
        start_ok, start_tip, test_ok, test_tip = self.run_status()
        self._start_btn.setEnabled(start_ok)
        self._start_btn.setToolTip(start_tip)
        self._test_btn.setEnabled(test_ok)
        self._test_btn.setToolTip(test_tip)
        hint = "" if start_ok else start_tip
        self._run_hint.setText(hint)
        self._run_hint.setVisible(bool(hint))

    def _test_item(self) -> CodeItem | None:
        p = self._profile
        if p is None:
            return None
        key = p.game_key()
        for it in self.selected_items():
            if it.status.is_runnable and it.game_key == key:
                return it
        runnable = self.ctx.queue.runnable(RunSelection.UNFINISHED, key)
        return runnable[0] if runnable else None

    def _ensure_run_flow(self) -> object | None:
        if self._run_flow is None:
            try:
                from .run_flow import RunFlow

                self._run_flow = RunFlow(self.ctx, self)
            except NotImplementedError:
                self.ctx.notify(str(NOT_IMPLEMENTED), "warning")
                return None
        return self._run_flow

    def start_run(self, test_one: bool = False) -> bool:
        """開始兌換 / 試跑 1 筆 through the page's RunFlow (created on first use)."""
        start_ok, reason, test_ok, test_reason = self.run_status()
        if not (test_ok if test_one else start_ok):
            self.ctx.notify(test_reason if test_one else reason, "warning")
            return False
        profile = self._profile
        flow = self._ensure_run_flow()
        if flow is None or profile is None:
            return False
        try:
            if test_one:
                item = self._test_item()
                if item is None:
                    return False
                return bool(flow.begin(profile, RunSelection.UNFINISHED, code_ids=[item.id],  # type: ignore[attr-defined]
                                       mode=PlanMode.TEST_ONE))
            return bool(flow.begin(profile, RunSelection(self.ctx.settings.run_selection)))  # type: ignore[attr-defined]
        except NotImplementedError:
            self.ctx.notify(str(NOT_IMPLEMENTED), "warning")
            return False

    def _on_run_state(self, _state: str, _reason: str) -> None:
        """While a run is active (also paused) the rows of its plan are read-only."""
        session = self.ctx.session
        plan = session.plan if session.is_active() else None
        self._model.set_locked([i.code_id for i in plan.items] if plan is not None else [])
        self._update_bulk_bar()

    def _on_run_finished(self, _summary: object) -> None:
        self._on_run_state("", "")
        self.refresh()
