# OWNED BY G6 - replace this stub
"""OCR review dialog (ux.md flow F2): the image (zoomable) with detected line boxes on the
left; candidates on the right (checkbox, editable mono code with ``flagged`` characters
highlighted and ``lookalikes`` dotted-underlined, confidence, crop of the source line next to
the text, badges, a 「已核對」 tick per flagged candidate and 「全部已核對」); code-format combo
(re-extract on change), 重新辨識; states: loading (Spinner "辨識中…"), error (engine
unavailable, with the reason), no codes found. OCR runs through ctx.ocr.request with
OcrOptions(code_charset=fmt.allowed_chars() + fmt.separator, det_side=ctx.settings.ocr.det_side)
for every image size (det 1920 lost small text, T13). Candidates ticked 「已核對」 are returned
with ``flagged`` cleared, so they enter the queue as PENDING (PX-18)."""

from __future__ import annotations

import numpy as np
from PyQt6.QtWidgets import QDialog, QWidget

from ..context import AppContext
from ..models import CodeCandidate, CodeFormat, CodeSource

__stub__ = True


class OcrReviewDialog(QDialog):
    def __init__(self, ctx: AppContext, image: np.ndarray, source: CodeSource = CodeSource.IMAGE,
                 detail: str = "", parent: QWidget | None = None) -> None:
        raise NotImplementedError

    def candidates(self) -> list[CodeCandidate]:
        """The checked (possibly edited) candidates, valid after exec() returned Accepted."""
        raise NotImplementedError

    def code_format(self) -> CodeFormat:
        raise NotImplementedError
