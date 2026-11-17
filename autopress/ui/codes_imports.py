# OWNED BY G6
"""Imports, drag-and-drop and inline code editing of the Codes page (private to G6; split out of
codes_page.py). ``CodesImportsMixin`` is mixed into ``CodesPage``.

Import dialogs open window-modal (``open()``), one at a time: further imports (several dropped
files) wait in a queue. Accepted candidates go to ``CodeQueue.add_candidates`` as codes of the
active profile's game with the history skip of the settings (SPEC 6.4.1); the result is a toast.
An edited code is a new code: flags cleared (REVIEW -> PENDING), look-alikes re-computed, no OCR
confidence, and a final status goes back to PENDING."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QGuiApplication, QImage
from PyQt6.QtWidgets import QDialog, QFileDialog

from ..codes import extract, fileimport, normalize, presets
from ..i18n import tr
from ..models import CodeCandidate, CodeFormat, CodeItem, CodeSource, CodeStatus, clone
from ..ocr import imageio
from .codes_common import NOT_IMPLEMENTED, add_result_message, import_target
from .codes_model import ROLE_ITEM
from .ocr_review import OcrReviewDialog
from .paste_dialog import PasteDialog

log = logging.getLogger(__name__)


class CodesImportsMixin:
    """Import actions, the dialog queue, drag-and-drop and code edits of the Codes page."""

    # =========================================================================== imports
    def paste_text(self) -> None:
        """貼上文字: the PasteDialog pre-filled with the clipboard text (if any)."""
        text = QGuiApplication.clipboard().text() or ""
        self.import_text(text if len(text) <= 1_000_000 else "", CodeSource.PASTE)

    def _paste_shortcut(self) -> None:
        """Ctrl+V on the page: a clipboard image goes to the OCR review, text to the PasteDialog."""
        try:
            image = imageio.clipboard_image()
        except Exception:  # noqa: BLE001 - an unreadable clipboard falls back to text
            log.debug("clipboard image failed", exc_info=True)
            image = None
        if image is not None and image.size:
            self.import_image(image, CodeSource.CLIPBOARD)
        else:
            self.paste_text()

    def open_file_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, tr("開啟序號清單", "Open code list"), self._last_dir,
                                                fileimport.file_dialog_filter())
        for p in paths:
            self._last_dir = str(Path(p).parent)
            self.import_file(Path(p))

    def open_image_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, tr("選擇含有序號的圖片", "Choose an image with codes"), self._last_dir,
                                                imageio.image_dialog_filter())
        for p in paths:
            self._last_dir = str(Path(p).parent)
            self.import_file(Path(p))

    def import_clipboard_image(self) -> None:
        image = imageio.clipboard_image()
        if image is None or not image.size:
            self.ctx.notify(tr("剪貼簿裡沒有圖片。可以先按 Win+Shift+S 截圖，再按「剪貼簿圖片」。",
                               "There is no image on the clipboard. Take a screenshot with Win+Shift+S first."), "info")
            return
        self.import_image(image, CodeSource.CLIPBOARD)

    def snip_screen(self) -> None:
        """框選螢幕: hide the main window, overlays.pick("region"), then the OCR review."""
        try:
            from .overlays import pick

            hide = [w for w in {self.window(), self.ctx.main_window} if w is not None]
            result = pick("region", instruction=tr("拖曳框選含有序號的區域（Esc 取消）",
                                                   "Drag over the area with the codes (Esc cancels)"),
                          hide_windows=hide)
        except NotImplementedError:
            self.ctx.notify(str(NOT_IMPLEMENTED), "warning")
            return
        image = getattr(result, "image", None) if result is not None else None
        if image is not None and getattr(image, "size", 0):
            self.import_image(image, CodeSource.SNIP)

    def import_text(self, text: str, source: CodeSource = CodeSource.PASTE, detail: str = "") -> None:
        """Open the PasteDialog pre-filled with ``text`` (extraction preview, then add)."""
        self._enqueue(lambda: self._open_dialog(PasteDialog(self.ctx, text, source, detail, self, self.format_choice()),
                                                source, detail))

    def import_file(self, path: Path) -> None:
        """codes.fileimport.read_code_file, then import_text(..., CodeSource.FILE, file name).
        Errors -> toast with the localized CodeFileError message. Image files (imageio
        IMAGE_EXTENSIONS) go to the OCR review instead."""
        path = Path(path)
        if path.suffix.lower() in imageio.IMAGE_EXTENSIONS:
            try:
                image = imageio.load_image(path)
            except (imageio.ImageLoadError, OSError) as exc:
                self.ctx.notify(str(exc) or tr("無法讀取圖片：{name}", "Cannot read the image: {name}").format(
                    name=path.name), "error")
                return
            self.import_image(image, CodeSource.IMAGE, path.name)
            return
        try:
            text = fileimport.read_code_file(path)
        except fileimport.CodeFileError as exc:
            self.ctx.notify(str(exc), "error")
            return
        self.import_text(text, CodeSource.FILE, path.name)

    def import_image(self, image: np.ndarray, source: CodeSource = CodeSource.IMAGE, detail: str = "") -> None:
        """Open the OcrReviewDialog for a BGR/BGRA image, then add the accepted candidates."""
        self._enqueue(lambda: self._open_dialog(
            OcrReviewDialog(self.ctx, image, source, detail, self, self.format_choice()), source, detail))

    def current_dialog(self) -> QDialog | None:
        """The import dialog that is open now (None when idle)."""
        return self._dialog

    def _enqueue(self, opener: Callable[[], None]) -> None:
        self._pending.append(opener)
        if self._dialog is None:
            self._next_import()

    def _next_import(self) -> None:
        while self._pending and self._dialog is None:
            self._pending.popleft()()

    def _open_dialog(self, dlg: QDialog, source: CodeSource, detail: str) -> None:
        self._dialog = dlg
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        def finished(code: int) -> None:
            self._dialog = None
            if code == QDialog.DialogCode.Accepted:
                self.add_candidates(dlg.candidates(), source, detail)  # type: ignore[attr-defined]
            self._import_timer.start()

        dlg.finished.connect(finished)
        dlg.open()

    def add_candidates(self, candidates: list[CodeCandidate], source: CodeSource, detail: str = "") -> object:
        """Add to the queue as codes of the active profile's game (SPEC 6.4.1) and toast the result."""
        target = import_target(self.ctx, self._profile)
        res = self.ctx.queue.add_candidates(candidates, source, source_detail=detail, history=self.ctx.history,
                                            game_key=target.game_key, game=target.game,
                                            skip_statuses=target.skip_statuses)
        self._dupes_removed += res.duplicates
        review = sum(1 for cid in res.added if (it := self.ctx.queue.get(cid)) is not None
                     and it.status is CodeStatus.REVIEW)
        kind, text = add_result_message(res, review)
        self.ctx.notify(text, kind)
        self.refresh()
        if res.added:
            self._reveal(list(res.added))
        return res

    def _reveal(self, code_ids: list[str]) -> None:
        if any(self._proxy.row_of(cid) < 0 for cid in code_ids):
            self._segments.setCurrentIndex(0)
            self._proxy.set_filter("all")
            self._search.clear()
        self.select_ids(code_ids)

    # =========================================================================== drag and drop
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        md = event.mimeData()
        if md is not None and ((md.hasUrls() and any(u.isLocalFile() for u in md.urls())) or md.hasImage()
                               or md.hasText()):
            event.acceptProposedAction()
            self._drop_overlay.setGeometry(self.rect())
            self._drop_overlay.raise_()
            self._drop_overlay.show()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: object) -> None:
        self._drop_overlay.hide()

    def dropEvent(self, event: QDropEvent) -> None:
        self._drop_overlay.hide()
        md = event.mimeData()
        if md is None:
            event.ignore()
            return
        files = [Path(u.toLocalFile()) for u in md.urls() if u.isLocalFile()] if md.hasUrls() else []
        if files:
            for f in files:
                self.import_file(f)
        elif md.hasImage():
            data = md.imageData()
            image = imageio.qimage_to_bgr(data if isinstance(data, QImage) else QImage(data))
            if image.size:
                self.import_image(image, CodeSource.IMAGE)
        elif md.hasText() and md.text().strip():
            self.import_text(md.text(), CodeSource.PASTE)
        else:
            event.ignore()
            return
        event.acceptProposedAction()

    def resizeEvent(self, event: object) -> None:
        super().resizeEvent(event)  # type: ignore[arg-type]
        if self._drop_overlay.isVisible():
            self._drop_overlay.setGeometry(self.rect())

    # =========================================================================== editing
    def _format_for(self, item: CodeItem) -> CodeFormat:
        """Code format of the item's game: the active profile's, another profile of that game, or
        generic. Other games' formats are cached until the profiles change (the editor validates
        on every keystroke and ProfileStore reads the files on every call)."""
        p = self._profile
        if p is not None and item.game_key == p.game_key():
            return clone(p.code_format)
        cache: dict[str, CodeFormat] | None = getattr(self, "_format_cache", None)
        if cache is None:
            cache = self._format_cache = {}
        if item.game_key not in cache:
            fmt = next((other.code_format for other in self.ctx.profiles.list()
                        if item.game_key and other.game_key() == item.game_key), None)
            cache[item.game_key] = fmt if fmt is not None else presets.get_format("generic")
        return clone(cache[item.game_key])

    def validate_code_edit(self, item: CodeItem, text: str) -> tuple[str | None, str]:
        """(normalised code, "") or (None, localized reason): format rule + duplicates in the game."""
        code, reason = extract.validate_code(text, self._format_for(item))
        if code is None:
            return None, reason
        other = self.ctx.queue.find_code(code, item.game_key)
        if other is not None and other.id != item.id:
            return None, tr("這個序號已在清單中（第 {n} 筆）", "This code is already in the list (row {n})").format(
                n=self.ctx.queue.index_of(other.id) + 1)
        return code, ""

    def _validate_edit(self, index: object, text: str) -> tuple[str | None, str]:
        item = index.data(ROLE_ITEM) if hasattr(index, "data") else None  # type: ignore[attr-defined]
        if item is None:
            return None, ""
        return self.validate_code_edit(item, text)

    def _apply_code_edit(self, item: CodeItem, text: str) -> bool:
        """An edited code is a new code: flags cleared (REVIEW -> PENDING), look-alikes re-computed,
        no OCR confidence, and a final status goes back to PENDING."""
        code, reason = self.validate_code_edit(item, text)
        if code is None:
            self.ctx.notify(reason, "warning")
            return False
        changes: dict[str, object] = {"code": code, "lookalikes": normalize.lookalike_indices(code, self._format_for(item)),
                                      "confidence": None, "char_confs": []}
        if item.status not in (CodeStatus.PENDING, CodeStatus.REVIEW):
            changes.update(status=CodeStatus.PENDING, message="")
        self.ctx.queue.update(item.id, **changes)
        return True
