# OWNED BY G7 - replace this stub
"""Run page (SPEC section 6.4.3): active profile, target window (change / refresh), selection
(全部未完成 / 只跑勾選的), preflight issue list with action buttons (restart_admin, pick_window,
preview, open_profile, wait_ocr, assign_codes, test_one, realign), 開始兌換 / 測試一筆 /
預覽點位; while running: ProgressRing, n / N, ETA, current code and step, state chip,
暫停／繼續 (F8) and 停止 (F9) with keycaps, live log, result counts; attention panel (shown when
RunFlow restores the main window for a paused run): reason, OCR text, evidence, 標記為…,
加入關鍵字…, 開啟紀錄檔 (errors), 繼續 (RunFlow.resume: countdown) / 停止; finished summary with
匯出結果 and 重試失敗項目."""

from __future__ import annotations

from PyQt6.QtWidgets import QWidget

from ..context import AppContext

__stub__ = True


class RunPage(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        raise NotImplementedError
