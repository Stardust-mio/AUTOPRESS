# OWNED BY G6
"""Bulk actions, row menu and export of the Codes page (private to G6; split out of
codes_page.py to keep modules small).

``CodesActionsMixin`` is mixed into ``CodesPage``, which provides ``ctx``, ``_profile``,
``_model`` (CodesTableModel), ``_proxy`` (CodesFilterProxy), ``_table`` (QTableView),
``_segments``, ``_search`` and ``refresh()``. Every action works on the table selection; rows of
the active run plan are read-only (SPEC 5.7: 「執行中，請先停止」). Status rules (SPEC 5.7):
確認無誤 (REVIEW -> PENDING) and 重設為待兌換 (final -> PENDING) are ``queue.reset``; 略過 /
取消略過 toggle SKIPPED (an un-skipped item with flagged characters goes back to REVIEW, so the
review gate of SPEC 5.4 holds); 標記為已兌換 = SUCCESS 「手動標記」 plus a history record with run_id
"manual" so later imports skip the code; 指定給目前遊戲 = ``queue.assign_game``; 清除已完成 removes
the codes of the 已完成 filter (SUCCESS, SUBMITTED, USED) in the current game scope; 匯出 CSV
exports the rows shown.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QItemSelectionModel, QModelIndex, QPoint
from PyQt6.QtGui import QAction, QGuiApplication
from PyQt6.QtWidgets import QAbstractItemView, QFileDialog, QMenu

from ..codes import csvexport
from ..i18n import tr
from ..models import AttemptRecord, CodeItem, CodeStatus, now_iso
from ..storage import StorageError
from . import widgets
from .codes_common import MANUAL_MARK, RUN_LOCKED, game_name
from .codes_model import COL_CODE, FILTER_STATUSES, FILTERS

SKIPPABLE = frozenset({CodeStatus.PENDING, CodeStatus.COOLDOWN, CodeStatus.REVIEW, CodeStatus.FAILED})
RESETTABLE = frozenset(set(CodeStatus) - {CodeStatus.PENDING, CodeStatus.RUNNING})
DONE = FILTER_STATUSES["done"]


class CodesActionsMixin:
    ctx: Any
    _profile: Any
    _model: Any
    _proxy: Any
    _table: Any
    _segments: Any
    _search: Any

    # -- selection ------------------------------------------------------------------------------
    def selected_items(self) -> list[CodeItem]:
        """Items of the selected rows, in queue order."""
        rows = sorted({ix.row() for ix in self._table.selectionModel().selectedRows()})
        return [it for r in rows if (it := self._proxy.item_at(r)) is not None]

    def visible_items(self) -> list[CodeItem]:
        return [it for r in range(self._proxy.rowCount()) if (it := self._proxy.item_at(r)) is not None]

    def select_ids(self, code_ids: list[str], scroll: bool = True) -> None:
        sel = self._table.selectionModel()
        sel.clearSelection()
        last = QModelIndex()
        for cid in code_ids:
            row = self._proxy.row_of(cid)
            if row >= 0:
                last = self._proxy.index(row, 0)
                sel.select(last, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        if last.isValid():
            sel.setCurrentIndex(last, QItemSelectionModel.SelectionFlag.NoUpdate)
            if scroll:
                self._table.scrollTo(last, QAbstractItemView.ScrollHint.EnsureVisible)

    def _writable(self, items: list[CodeItem]) -> list[CodeItem]:
        """Items that may change now; tells the user when rows of the running plan were left out."""
        ok = [it for it in items if self._model.can_edit(it)]
        if len(ok) < len(items):
            self.ctx.notify(str(RUN_LOCKED), "warning")
        return ok

    # -- actions ------------------------------------------------------------------------------
    def remove_selected(self) -> int:
        items = self._writable(self.selected_items())
        if not items:
            return 0
        if len(items) > 1 and not widgets.confirm(
                self, tr("移除序號", "Remove codes"),
                tr("要從清單移除 {n} 筆序號嗎？兌換紀錄不受影響。", "Remove {n} codes from the list? The history is kept.")
                .format(n=len(items)), tr("移除", "Remove"), danger=True):
            return 0
        with self._model.batch():
            n = self.ctx.queue.remove([it.id for it in items])
        self.ctx.notify(tr("已移除 {n} 筆序號", "Removed {n} code(s)").format(n=n), "info")
        return n

    def mark_redeemed(self) -> int:
        items = [it for it in self._writable(self.selected_items()) if it.status is not CodeStatus.SUCCESS]
        if not items:
            return 0
        msg, now, profile = str(MANUAL_MARK), now_iso(), self._profile
        with self._model.batch():
            for it in items:
                self.ctx.queue.set_status(it.id, CodeStatus.SUCCESS, msg)
                same = profile is not None and profile.game_key() == it.game_key
                self.ctx.history.append(AttemptRecord(
                    run_id="manual", code_id=it.id, code=it.code, game=it.game, game_key=it.game_key,
                    profile_id=profile.id if same else "", profile_name=profile.name if same else "",
                    status=CodeStatus.SUCCESS, result=None, message=msg, started_at=now, finished_at=now))
        self.ctx.notify(tr("已將 {n} 筆標記為已兌換", "Marked {n} code(s) as redeemed").format(n=len(items)), "success")
        return len(items)

    def confirm_ok(self) -> int:
        """確認無誤: REVIEW -> PENDING (flags cleared)."""
        items = [it for it in self._writable(self.selected_items()) if it.status is CodeStatus.REVIEW]
        if not items:
            return 0
        with self._model.batch():
            n = self.ctx.queue.reset([it.id for it in items])
        self.ctx.notify(tr("已確認 {n} 筆，改為待兌換", "{n} code(s) confirmed and pending").format(n=n), "success")
        return n

    def reset_pending(self) -> int:
        """重設為待兌換: any final status -> PENDING."""
        items = [it for it in self._writable(self.selected_items()) if it.status in RESETTABLE]
        if not items:
            return 0
        with self._model.batch():
            n = self.ctx.queue.reset([it.id for it in items])
        self.ctx.notify(tr("已將 {n} 筆重設為待兌換", "Reset {n} code(s) to pending").format(n=n), "info")
        return n

    def toggle_skip(self) -> int:
        items = self._writable(self.selected_items())
        if not items:
            return 0
        with self._model.batch():
            if all(it.status is CodeStatus.SKIPPED for it in items):
                for it in items:
                    self.ctx.queue.set_status(it.id, CodeStatus.REVIEW if it.flagged else CodeStatus.PENDING)
                text = tr("已取消略過 {n} 筆", "Un-skipped {n} code(s)")
                n = len(items)
            else:
                todo = [it for it in items if it.status in SKIPPABLE]
                for it in todo:
                    self.ctx.queue.set_status(it.id, CodeStatus.SKIPPED)
                text = tr("已略過 {n} 筆", "Skipped {n} code(s)")
                n = len(todo)
        if n:
            self.ctx.notify(text.format(n=n), "info")
        return n

    def assign_to_current(self) -> int:
        profile = self._profile
        if profile is None:
            return 0
        key = profile.game_key()
        items = [it for it in self._writable(self.selected_items()) if it.game_key != key]
        if not items:
            return 0
        before = len(self.ctx.queue)
        with self._model.batch():
            n = self.ctx.queue.assign_game([it.id for it in items], key, profile.game)
        text = tr("已把 {n} 筆指定給「{game}」", 'Assigned {n} code(s) to "{game}"').format(n=n, game=game_name(profile))
        removed = before - len(self.ctx.queue)
        if removed:
            text += tr("（{d} 筆重複已移除）", " ({d} duplicate(s) removed)").format(d=removed)
        self.ctx.notify(text, "success")
        return n

    def assign_unassigned(self) -> int:
        """Banner action: every unassigned code -> the active profile's game."""
        profile = self._profile
        if profile is None:
            return 0
        ids = [it.id for it in self.ctx.queue.items() if not it.game_key and self._model.can_edit(it)]
        if not ids:
            return 0
        with self._model.batch():
            n = self.ctx.queue.assign_game(ids, profile.game_key(), profile.game)
        self.ctx.notify(tr("已把 {n} 筆指定給「{game}」", 'Assigned {n} code(s) to "{game}"')
                        .format(n=n, game=game_name(profile)), "success")
        return n

    def move_selected(self, delta: int) -> None:
        items = self._writable(self.selected_items())
        if items:
            with self._model.batch():
                self.ctx.queue.move([it.id for it in items], delta)
            self._scroll_to_current()

    def move_selected_top(self) -> None:
        items = self._writable(self.selected_items())
        if items:
            with self._model.batch():
                self.ctx.queue.move_to([it.id for it in items], 0)
            self._scroll_to_current()

    def _scroll_to_current(self) -> None:
        rows = sorted(ix.row() for ix in self._table.selectionModel().selectedRows())
        if rows:
            self._table.scrollTo(self._proxy.index(rows[0], 0))

    def retry_failed(self) -> int:
        with self._model.batch():
            n = self.ctx.queue.retry_failed()
        if n:
            self.ctx.notify(tr("已將 {n} 筆失敗的序號改回待兌換", "{n} failed code(s) are pending again").format(n=n), "info")
        else:
            self.ctx.notify(tr("沒有失敗的序號", "No failed codes"), "info")
        return n

    def done_ids(self) -> list[str]:
        """Completed codes (filter 已完成) of the current game scope that may be removed."""
        return [it.id for it in self.ctx.queue.items()
                if it.status in DONE and self._proxy.game_accepts(it.game_key) and self._model.can_edit(it)]

    def clear_done(self) -> int:
        ids = self.done_ids()
        if not ids:
            self.ctx.notify(tr("沒有已完成的序號", "No completed codes"), "info")
            return 0
        if not widgets.confirm(self, tr("清除已完成", "Clear completed"),
                               tr("要從清單移除 {n} 筆已完成的序號嗎？兌換紀錄不受影響。",
                                  "Remove {n} completed codes from the list? The history is kept.").format(n=len(ids)),
                               tr("清除", "Clear"), danger=True):
            return 0
        with self._model.batch():
            n = self.ctx.queue.remove(ids)
        self.ctx.notify(tr("已清除 {n} 筆已完成的序號", "Cleared {n} completed code(s)").format(n=n), "info")
        return n

    def set_checked_visible(self, checked: bool) -> None:
        ids = [it.id for it in self.visible_items() if not self._model.is_locked(it.id)]
        if ids:
            with self._model.batch():
                self.ctx.queue.set_checked(ids, checked)

    def toggle_checked_selected(self) -> None:
        items = [it for it in self.selected_items() if not self._model.is_locked(it.id)]
        if items:
            with self._model.batch():
                self.ctx.queue.set_checked([it.id for it in items], not all(it.checked for it in items))

    def on_check_toggled(self, index: QModelIndex, checked: bool) -> None:
        """Check-box click: applies to every selected row when the clicked row is selected."""
        rows = {ix.row() for ix in self._table.selectionModel().selectedRows()}
        items = self.selected_items() if index.row() in rows else [self._proxy.item_at(index.row())]
        ids = [it.id for it in items if it is not None and not self._model.is_locked(it.id)]
        if ids:
            with self._model.batch():
                self.ctx.queue.set_checked(ids, checked)

    def copy_selected(self) -> int:
        items = self.selected_items()
        if items:
            QGuiApplication.clipboard().setText("\n".join(it.code for it in items))
            self.ctx.notify(tr("已複製 {n} 筆序號", "Copied {n} code(s)").format(n=len(items)), "info")
        return len(items)

    def edit_current(self) -> None:
        rows = sorted(ix.row() for ix in self._table.selectionModel().selectedRows())
        if rows:
            ix = self._proxy.index(rows[0], COL_CODE)
            self._table.setCurrentIndex(ix)
            self._table.edit(ix)

    def next_review(self) -> bool:
        """逐筆檢查: select the next REVIEW row after the current one (filters relaxed if needed)."""
        if not self._select_next_review():
            if self._proxy.filter_key() != "all" or self._proxy.search_text():
                self._segments.setCurrentIndex(FILTERS.index("all"))
                self._proxy.set_filter("all")
                self._search.clear()
            if not self._select_next_review():
                return False
        self._table.setFocus()
        return True

    def _select_next_review(self) -> bool:
        n = self._proxy.rowCount()
        cur = self._table.currentIndex().row()
        for k in range(1, n + 1):
            row = (cur + k) % n if cur >= 0 else k - 1
            it = self._proxy.item_at(row)
            if it is not None and it.status is CodeStatus.REVIEW:
                self.select_ids([it.id])
                return True
        return False

    def export_csv(self) -> bool:
        items = self.visible_items()
        if not items:
            self.ctx.notify(tr("沒有可匯出的序號", "No codes to export"), "info")
            return False
        name = f"autopress-codes-{datetime.now():%Y%m%d-%H%M}.csv"
        path, _ = QFileDialog.getSaveFileName(self, tr("匯出 CSV", "Export CSV"), str(Path.home() / name),
                                              tr("CSV 檔 (*.csv)", "CSV files (*.csv)"))
        if not path:
            return False
        try:
            csvexport.export_codes_csv(Path(path), items)
        except (StorageError, OSError) as exc:
            self.ctx.notify(str(exc), "error")
            return False
        self.ctx.notify(tr("已匯出 {n} 筆到 {name}", "Exported {n} code(s) to {name}").format(
            n=len(items), name=Path(path).name), "success")
        return True

    # -- menus ----------------------------------------------------------------------------------
    def _action(self, menu: QMenu, text: str, slot: Any, enabled: bool = True) -> QAction:
        act = menu.addAction(text)
        act.setEnabled(enabled)
        act.triggered.connect(lambda _checked=False: slot())
        return act

    def show_row_menu(self, proxy_row: int, global_pos: QPoint) -> QMenu | None:
        item = self._proxy.item_at(proxy_row)
        if item is None:
            return None
        if proxy_row not in {ix.row() for ix in self._table.selectionModel().selectedRows()}:
            self.select_ids([item.id], scroll=False)
        items = self.selected_items()
        free = [it for it in items if self._model.can_edit(it)]
        menu = QMenu(self)
        if len(free) < len(items):
            info = menu.addAction(str(RUN_LOCKED))
            info.setEnabled(False)
            menu.addSeparator()
        self._action(menu, tr("編輯", "Edit") + "\tF2", self.edit_current, len(items) == 1 and bool(free))
        if any(it.status is CodeStatus.REVIEW for it in free):
            self._action(menu, tr("確認無誤", "Looks right"), self.confirm_ok)
        if any(it.status in RESETTABLE and it.status is not CodeStatus.REVIEW for it in free):
            self._action(menu, tr("重設為待兌換", "Reset to pending"), self.reset_pending)
        if free and all(it.status is CodeStatus.SKIPPED for it in free):
            self._action(menu, tr("取消略過", "Un-skip"), self.toggle_skip)
        else:
            self._action(menu, tr("略過", "Skip"), self.toggle_skip, any(it.status in SKIPPABLE for it in free))
        profile = self._profile
        if profile is not None and any(it.game_key != profile.game_key() for it in free):
            self._action(menu, tr("指定給「{game}」", 'Assign to "{game}"').format(game=game_name(profile)),
                         self.assign_to_current)
        menu.addSeparator()
        self._action(menu, tr("複製", "Copy") + "\tCtrl+C", self.copy_selected)
        self._action(menu, tr("移除", "Remove") + "\tDelete", self.remove_selected, bool(free))
        if global_pos is not None:
            menu.popup(global_pos)
        return menu

    def populate_more_menu(self, menu: QMenu) -> None:
        menu.clear()
        items = self.selected_items()
        free = [it for it in items if self._model.can_edit(it)]
        self._action(menu, tr("移到最上", "Move to top"), self.move_selected_top, bool(free))
        self._action(menu, tr("重設為待兌換", "Reset to pending"), self.reset_pending,
                     any(it.status in RESETTABLE for it in free))
        profile = self._profile
        label = (tr("指定給目前遊戲「{game}」", 'Assign to the current game "{game}"').format(game=game_name(profile))
                 if profile is not None else tr("指定給目前遊戲", "Assign to the current game"))
        self._action(menu, label, self.assign_to_current,
                     profile is not None and any(it.game_key != profile.game_key() for it in free))
        menu.addSeparator()
        self._action(menu, tr("全部勾選", "Check all shown"), lambda: self.set_checked_visible(True))
        self._action(menu, tr("全部取消勾選", "Uncheck all shown"), lambda: self.set_checked_visible(False))
        menu.addSeparator()
        failed = sum(1 for it in self.ctx.queue.items() if it.status is CodeStatus.FAILED)
        self._action(menu, tr("重試失敗（{n}）", "Retry failed ({n})").format(n=failed), self.retry_failed, failed > 0)
        done = len(self.done_ids())
        self._action(menu, tr("清除已完成（{n}）", "Clear completed ({n})").format(n=done), self.clear_done, done > 0)
        menu.setToolTipsVisible(True)
