# OWNED BY G7 - replace this stub
"""Profiles page (SPEC section 6.4.2): profile list (new from template, import, export,
duplicate, delete) + editor (name, game - an editable combo of known game names with a
near-duplicate warning -, target window, code format, coordinate mode, setup checklist banner,
step list, step editor, run policy, keywords) with explicit 儲存, dirty marker and a Save /
Discard / Cancel prompt (and a warning before saving a profile from a newer version); template
gallery when there are no profiles; buttons 預覽點位 (PreviewOverlay), 測試此步驟
(RunSession.test_step: dry run by default; a real test shows the countdown, registers the stop
hotkey, offers 停止測試 and warns when the step submits the sample code), 設為使用中.

Import (PX-01 / PX-17): ProfileStore.read_file (nothing saved, nothing renamed) -> a warning
card listing Profile.action_lines() verbatim (risky lines highlighted), the suggested exe, the
code format and 「只匯入你信任的人分享的設定檔」 -> the 匯入 button is enabled only after the
checkbox 「我看得懂這些動作」 -> ProfileStore.import_profile -> the setup wizard opens on 「選擇
目標視窗」 (an imported profile never has a target). Export asks for an optional title keyword
(ProfileStore.export_file(..., title_keyword)). Renaming the game offers to move the queued
codes of the old game (CodeQueue.assign_game).
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QWidget

from ..context import AppContext

__stub__ = True


class ProfilesPage(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        raise NotImplementedError

    def open_profile(self, profile_id: str) -> None:
        raise NotImplementedError

    def new_from_template(self, template_key: str | None = None) -> None:
        """Create a profile from a built-in template (gallery dialog when ``template_key`` is None)."""
        raise NotImplementedError

    def import_profile_file(self, path: Path) -> None:
        """The import flow above for one file (also used by drag-and-drop of *.autopress.json)."""
        raise NotImplementedError

    def start_wizard(self, profile_id: str, realign: bool = False) -> None:
        """The setup wizard (SPEC 6.4.2): target window, every missing_setup() position, the
        result-close choice, 預覽點位, 測試一筆 (with a paste box for one real code). ``realign``
        = 「重新對準」: re-pick every recorded position (preflight actions size_changed /
        dpi_changed, after an import)."""
        raise NotImplementedError
