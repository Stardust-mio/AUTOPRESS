# OWNED BY G5 - replace this stub
"""Settings page (SPEC section 6.4.5): language (restart), theme (live), hotkeys (capture
fields, conflict check), failsafe, physical-input pause, countdown, resume countdown, confirm
threshold, default typing mode and delays, OCR (state, threads, warm-up; changes and
「重新啟動引擎」 call ctx.ocr.restart(settings.ocr)), history skip, evidence retention, data
folder (open / portable indicator / fallback note), about (version, licenses)."""

from __future__ import annotations

from PyQt6.QtWidgets import QWidget

from ..context import AppContext

__stub__ = True


class SettingsPage(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        raise NotImplementedError
