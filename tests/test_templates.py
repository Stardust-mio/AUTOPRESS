# OWNED BY G8
"""Built-in profile templates (autopress/resources/templates/*.autopress.json) - SPEC 8.2 G8 row,
ux.md 5.8, decision log PX-08 / PX-09 / PX-23 / PX-32.

Every template: loads with profile_from_dict, validates without ERROR except the positions and
result regions of missing_setup(), uses only known step types, has a bilingual TemplateInfo and
label + label_en on every step, starts with a precondition wait_text, dismisses results with a
click_text whose on_not_found is continue; the in-game template types in VK mode with a 30 ms
hold. The JSON is checked key by key, because loading silently drops unknown keys and invalid
enum values (a typo would otherwise go unnoticed).
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from autopress import i18n, paths, storage
from autopress.models import (
    STEP_PARAM_TYPES,
    ClickTextParams,
    CoordMode,
    IssueLevel,
    KeywordConfig,
    OcrCheckParams,
    Profile,
    ResultClass,
    RunPolicy,
    StepType,
    TemplateInfo,
    TextMatch,
    TimeoutAction,
    TypeCodeParams,
    TypingMode,
    WaitTextParams,
    default_keyword_groups,
    profile_from_dict,
    to_dict,
)
from autopress.textutil import split_alternatives

TEMPLATE_DIR = paths.templates_dir()
EXPECTED_KEYS = ["web_generic", "hoyoverse_web", "game_dialog"]  # gallery order (web pages first, ux.md 1.3)
STEP_KEYS = {"type", "params", "enabled", "label", "label_en", "id"}
PROFILE_FIELDS = {f.name for f in dataclasses.fields(Profile)}

# HoYoverse API strings (genshin.py errors.py, ux.md source [1], fetched 2026-11-17) -> expected class
HOYOVERSE_MESSAGES = [
    ("Invalid redemption code.", ResultClass.INVALID),  # -1065 / -2004
    ("Redemption code has expired.", ResultClass.EXPIRED),  # -2001
    ("Redemption code is incorrectly formatted.", ResultClass.INVALID),  # -2003
    ("Redemption code has reached max usage limit.", ResultClass.INELIGIBLE),  # -2006
    ("Redemption code is not available in the account's region.", ResultClass.INELIGIBLE),  # -2008
    ("Redemption code not activated", ResultClass.INELIGIBLE),  # -2014: the template's extra keyword
    ("Redemption is on cooldown.", ResultClass.RATE_LIMITED),  # -2016
    ("Redemption code has been claimed already.", ResultClass.USED),  # -2017 / -2018
    ("Account has no game account bound to it.", ResultClass.UNKNOWN),  # -1073: the user decides
    ("兌換成功", ResultClass.SUCCESS),
    ("兌換碼已被使用", ResultClass.USED),
    ("兌換碼已過期", ResultClass.EXPIRED),
]
HOYOVERSE_EXTRA_KEYWORDS = {ResultClass.INELIGIBLE: ["not activated"]}


def _files() -> list[Path]:
    return sorted(TEMPLATE_DIR.glob("*.autopress.json"))


def _raw(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_bytes().decode("utf-8"))
    assert isinstance(data, dict)
    return data


def _templates() -> dict[str, tuple[Path, dict[str, Any], Profile]]:
    out: dict[str, tuple[Path, dict[str, Any], Profile]] = {}
    for f in _files():
        raw = _raw(f)
        p = profile_from_dict(raw)
        assert p.template is not None, f.name
        out[p.template.key] = (f, raw, p)
    return out


TEMPLATES = _templates()


def _each() -> list[Any]:
    return [pytest.param(key, id=key) for key in EXPECTED_KEYS]


def _index(p: Profile, pred: Any) -> int:
    return next(i for i, s in enumerate(p.steps) if pred(s))


# ----------------------------------------------------------------------------- files and loading


def test_template_files_are_plain_utf8_json() -> None:
    files = _files()
    assert [f.name for f in files] == sorted(f"{k}.autopress.json" for k in EXPECTED_KEYS)
    for f in files:
        data = f.read_bytes()
        assert not data.startswith(b"\xef\xbb\xbf"), f"{f.name}: no BOM"
        assert b"\r\n" not in data, f"{f.name}: LF line endings"
        assert isinstance(json.loads(data.decode("utf-8")), dict)


def test_load_templates_returns_every_template_in_gallery_order() -> None:
    loaded = storage.load_templates()
    assert [t.template.key for t in loaded if t.template] == EXPECTED_KEYS
    orders = [t.template.order for t in loaded if t.template]
    assert orders == sorted(orders) and len(set(orders)) == len(orders)
    assert len({t.id for t in loaded}) == len(loaded)


@pytest.mark.parametrize("key", _each())
def test_json_keys_and_values_survive_loading(key: str) -> None:
    """No typo'd key and no invalid enum value: every value written in the file is what loads."""
    _f, raw, p = TEMPLATES[key]
    assert set(raw) <= PROFILE_FIELDS
    assert raw["schema_version"] == 1 and p.schema_version == 1
    loaded = to_dict(p)
    for name in ("name", "game", "description", "author", "target", "suggested_exe", "coord_mode",
                 "code_format", "template", "last_test_ok_at"):
        assert loaded[name] == raw[name], name
    if "keywords" in raw:
        assert loaded["keywords"] == raw["keywords"]
    assert len(raw["steps"]) == len(p.steps)
    for i, (rs, step) in enumerate(zip(raw["steps"], p.steps)):
        assert set(rs) <= STEP_KEYS, i
        assert rs["type"] == step.type.value
        fields = {f.name for f in dataclasses.fields(STEP_PARAM_TYPES[step.type])}
        assert set(rs["params"]) <= fields, (i, set(rs["params"]) - fields)
        enc = to_dict(step.params)
        for k, v in rs["params"].items():
            assert enc[k] == v, (i, k)
        assert (step.label, step.label_en, step.id, step.enabled) == (rs["label"], rs["label_en"], rs["id"], rs["enabled"])


# ----------------------------------------------------------------------------- SPEC 8.2 rules


@pytest.mark.parametrize("key", _each())
def test_validates_without_errors_except_missing_setup(key: str) -> None:
    p = TEMPLATES[key][2]
    missing = p.missing_setup()
    assert missing, "a template always leaves the positions to the setup wizard"
    for issue in p.validate():
        if issue.level is IssueLevel.ERROR:
            field = issue.path.rsplit(".", 1)[-1]
            assert (issue.step_index, field) in missing, issue
            assert field in ("point", "region")
        elif issue.level is IssueLevel.WARNING:
            assert issue.path == "target", issue  # only "no target window selected yet"
    assert not p.keywords.overlaps()


@pytest.mark.parametrize("key", _each())
def test_uses_only_known_step_types(key: str) -> None:
    p = TEMPLATES[key][2]
    assert p.steps
    for s in p.steps:
        assert s.type is not StepType.UNKNOWN and s.type in STEP_PARAM_TYPES
        assert isinstance(s.params, STEP_PARAM_TYPES[s.type])
        assert s.enabled
    assert len({s.id for s in p.steps}) == len(p.steps)


@pytest.mark.parametrize("key", _each())
def test_bilingual_template_info_and_step_labels(key: str) -> None:
    p = TEMPLATES[key][2]
    info = p.template
    assert isinstance(info, TemplateInfo)
    assert all((info.key, info.title_zh, info.title_en, info.description_zh, info.description_en))
    assert info.title_zh != info.title_en and info.description_zh != info.description_en
    for s in p.steps:
        assert s.label.strip() and s.label_en.strip(), s.id
    i18n.set_language("en")
    try:
        assert info.title() == info.title_en
        assert [s.display_title() for s in p.steps] == [s.label_en for s in p.steps]
    finally:
        i18n.set_language("zh-TW")
    assert info.title() == info.title_zh
    assert [s.display_title() for s in p.steps] == [s.label for s in p.steps]


@pytest.mark.parametrize("key", _each())
def test_starts_with_a_precondition_wait_text(key: str) -> None:
    """PX-09: nothing is typed unless the redeem page / dialog is visible."""
    p = TEMPLATES[key][2]
    first = p.steps[0]
    assert first.type is StepType.WAIT_TEXT
    prm = first.params
    assert isinstance(prm, WaitTextParams)
    assert prm.appear and prm.on_timeout is TimeoutAction.FAIL
    assert prm.match is TextMatch.CONTAINS and split_alternatives(prm.text)
    assert all(not s.type.sends_input for s in p.steps[:1])


@pytest.mark.parametrize("key", _each())
def test_dismisses_results_with_click_text_on_not_found_continue(key: str) -> None:
    """PX-08: 「按確定」 only when the popup is there; never an unconditional Esc."""
    p = TEMPLATES[key][2]
    check = _index(p, lambda s: s.type is StepType.OCR_CHECK)
    after = p.steps[check + 1:]
    dismiss = [s for s in after if isinstance(s.params, ClickTextParams)]
    assert dismiss, "a click_text after the result check"
    prm = dismiss[0].params
    assert isinstance(prm, ClickTextParams)
    assert prm.on_not_found is TimeoutAction.CONTINUE
    assert prm.match is TextMatch.EXACT and prm.fallback_point is None
    assert prm.timeout_ms <= 3000  # short: the popup appears together with the result
    assert {"確定", "OK"} <= set(split_alternatives(prm.text))
    assert not any(s.type is StepType.KEY for s in p.steps), "no Esc / Enter key steps in templates"


def test_in_game_template_uses_vk_mode_with_30ms_hold() -> None:
    """PX-32 / SPEC 11.11: raw-input and polling games see only VK input held >= 20 ms."""
    p = TEMPLATES["game_dialog"][2]
    tc = [s.params for s in p.steps if isinstance(s.params, TypeCodeParams)]
    assert len(tc) == 1
    assert tc[0].mode is TypingMode.VK and tc[0].hold_ms == 30
    assert tc[0].key_delay_ms >= 15
    assert p.coord_mode is CoordMode.AUTO  # game templates: auto (SPEC 5.2)


@pytest.mark.parametrize("key", ["web_generic", "hoyoverse_web"])
def test_web_templates_type_unicode_and_use_offset_coordinates(key: str) -> None:
    p = TEMPLATES[key][2]
    tc = [s.params for s in p.steps if isinstance(s.params, TypeCodeParams)]
    assert len(tc) == 1 and tc[0].mode is TypingMode.UNICODE and tc[0].clear_first
    assert p.coord_mode is CoordMode.OFFSET  # web pages scale with Windows DPI (SPEC 5.2)


# ----------------------------------------------------------------------------- flow details


@pytest.mark.parametrize("key", _each())
def test_submit_step_and_setup_order(key: str) -> None:
    """click input -> type -> submit (first_submit_index) -> read result -> dismiss; the setup
    wizard asks for the input position first, then the result region."""
    p = TEMPLATES[key][2]
    types = [s.type for s in p.steps]
    assert types == [StepType.WAIT_TEXT, StepType.CLICK_POINT, StepType.TYPE_CODE, StepType.CLICK_TEXT,
                     StepType.OCR_CHECK, StepType.CLICK_TEXT]
    submit = p.steps[p.first_submit_index()]
    assert p.first_submit_index() == 3
    assert isinstance(submit.params, ClickTextParams)
    assert submit.params.on_not_found is TimeoutAction.FAIL and submit.params.match is TextMatch.EXACT
    alts = split_alternatives(submit.params.text)
    assert len(alts) == len(set(alts)) and ("兌換" in alts or "確認" in alts)
    assert p.missing_setup() == [(1, "point"), (4, "region")]
    check = p.steps[4].params
    assert isinstance(check, OcrCheckParams) and check.only_new_text and check.save_evidence


@pytest.mark.parametrize("key", _each())
def test_templates_carry_no_target_codes_or_test_state(key: str) -> None:
    _f, raw, p = TEMPLATES[key]
    assert p.target.is_empty() and not p.target.allow_same_process and p.suggested_exe == ""
    assert p.last_test_ok_at == "" and p.game == ""  # the user names the game (history key)
    assert p.policy == RunPolicy()  # interval 6-8 s, cool-down, failure and invalid limits (SPEC 5.2)
    text = json.dumps(raw, ensure_ascii=False)
    assert "AB12" not in text and "TEST-" not in text


@pytest.mark.parametrize("key", _each())
def test_profile_from_template_gives_a_fresh_localized_profile(key: str, isolated_home: Path) -> None:
    tpl = TEMPLATES[key][2]
    p = storage.profile_from_template(tpl)
    assert p.id != tpl.id and p.template is None
    assert not {s.id for s in p.steps} & {s.id for s in tpl.steps}
    assert p.name == tpl.template.title_zh and p.description == tpl.template.description_zh
    assert [s.label for s in p.steps] == [s.label for s in tpl.steps]
    i18n.set_language("en")
    try:
        assert storage.profile_from_template(tpl).name == tpl.template.title_en
    finally:
        i18n.set_language("zh-TW")
    store = storage.ProfileStore()
    store.save(p)
    again = store.get(p.id)
    assert again is not None and to_dict(again.steps) == to_dict(p.steps)
    assert [(i.level, i.path) for i in again.validate()] == [(i.level, i.path) for i in tpl.validate()]


# ----------------------------------------------------------------------------- keywords and formats


def test_generic_templates_use_the_default_keywords() -> None:
    for key in ("web_generic", "game_dialog"):
        _f, raw, p = TEMPLATES[key]
        assert "keywords" not in raw  # follows models.DEFAULT_KEYWORDS
        assert to_dict(p.keywords) == to_dict(KeywordConfig())


def test_hoyoverse_keywords_are_the_defaults_plus_the_genshin_py_pack() -> None:
    p = TEMPLATES["hoyoverse_web"][2]
    defaults = default_keyword_groups()
    for cls, words in defaults.items():
        got = p.keywords.groups[cls]
        assert got[: len(words)] == words, cls  # defaults first, unchanged
        assert got[len(words):] == HOYOVERSE_EXTRA_KEYWORDS.get(cls, []), cls
    assert p.keywords.order == KeywordConfig().order and p.keywords.fuzzy
    assert not p.keywords.overlaps()


@pytest.mark.parametrize(("text", "expected"), HOYOVERSE_MESSAGES)
def test_hoyoverse_template_classifies_the_api_messages(text: str, expected: ResultClass) -> None:
    assert TEMPLATES["hoyoverse_web"][2].keywords.classify(text)[0] is expected


def test_hoyoverse_template_uses_the_hoyoverse_code_format() -> None:
    fmt = TEMPLATES["hoyoverse_web"][2].code_format
    assert (fmt.id, fmt.charset, fmt.case_sensitive, fmt.min_len, fmt.max_len, fmt.groups) == \
        ("hoyoverse", "A-Za-z0-9", True, 6, 16, [])
    for key in ("web_generic", "game_dialog"):
        g = TEMPLATES[key][2].code_format
        assert (g.id, g.charset, g.case_sensitive, g.min_len, g.max_len, g.groups) == \
            ("generic", "A-Za-z0-9", True, 6, 24, [])


def test_template_formats_match_the_g1_presets() -> None:
    from tests.fakes import skip_if_stub

    skip_if_stub("autopress.codes.presets")
    from autopress.codes import presets

    for key in EXPECTED_KEYS:
        fmt = TEMPLATES[key][2].code_format
        assert to_dict(fmt) == to_dict(presets.get_format(fmt.id)), key
