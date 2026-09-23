from __future__ import annotations

import json
from pathlib import Path

import pytest

from yazses.config import CommandsConfig, load_config_checked

from yazses.commands.grammar import IntentType, classify
from yazses.commands.grammars.registry import (
    get_grammar,
    resolve_command_language,
)
from yazses.commands.grammars.zh import SAFE_CORE_ACTIONS, parse_number_0_99


FIXTURES = Path(__file__).parent / "fixtures" / "commands"


def _positive_cases():
    return json.loads((FIXTURES / "zh_core.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", _positive_cases(), ids=lambda c: c["text"])
def test_mandarin_safe_core_maps_to_existing_canonical_actions(case):
    got = classify(case["text"], language="zh")

    assert got.intent is not IntentType.DICTATE
    assert got.action == case["action"]
    assert got.args == case["args"]
    assert got.raw_text == case["text"]


def test_every_shipped_mandarin_action_has_simplified_and_traditional_evidence():
    coverage: dict[str, set[str]] = {}
    for case in _positive_cases():
        coverage.setdefault(case["action"], set()).update(case["scripts"])

    assert set(coverage) == set(SAFE_CORE_ACTIONS)
    for action, scripts in coverage.items():
        assert scripts == {"simplified", "traditional"}, (
            f"{action} needs both Simplified and Traditional reviewed fixture coverage"
        )


def test_mandarin_negative_prose_never_becomes_a_command():
    lines = [
        line
        for line in (FIXTURES / "zh_dictation.txt").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) >= 30

    bad = []
    for text in lines:
        got = classify(text, language="zh")
        if got.intent is not IntentType.DICTATE:
            bad.append((text, got.action, got.args))

    assert bad == []


@pytest.mark.parametrize(
    ("spoken", "expected"),
    [
        ("0", "0"),
        ("00", "0"),
        ("99", "99"),
        ("零", "0"),
        ("〇", "0"),
        ("一", "1"),
        ("两", "2"),
        ("兩", "2"),
        ("十", "10"),
        ("十一", "11"),
        ("二十", "20"),
        ("二十三", "23"),
        ("九十九", "99"),
    ],
)
def test_bounded_mandarin_command_number_parser(spoken, expected):
    assert parse_number_0_99(spoken) == expected


@pytest.mark.parametrize("spoken", ["", "100", "一百", "百", "零十", "二十三四", "-1"])
def test_mandarin_command_number_parser_refuses_out_of_scope_forms(spoken):
    assert parse_number_0_99(spoken) is None


@pytest.mark.parametrize(
    "text",
    [
        "撤销100次",
        "选择100行",
        "转到第100行",
        "删除最后一百行",
        "删除最后二十三四行",
    ],
)
def test_out_of_scope_counts_do_not_become_commands(text):
    assert classify(text, language="zh").intent is IntentType.DICTATE


def test_terminal_and_open_ended_execution_are_not_in_mandarin_p1():
    for text in ("运行测试", "執行測試", "运行 rm -rf /", "執行 make deploy"):
        got = classify(text, language="zh")
        assert got.intent is IntentType.DICTATE
        assert got.action == "inject"


def test_tier_two_is_not_consulted_for_mandarin_prose():
    seen: list[str] = []

    class _DangerousRouter:
        def classify(self, text: str, profile: str = "default"):
            seen.append(text)
            raise AssertionError("Mandarin P1 must not call Tier 2")

    got = classify(
        "请保存这个想法供以后讨论",
        language="zh",
        slm_router=_DangerousRouter(),
    )

    assert got.intent is IntentType.DICTATE
    assert seen == []


def test_unknown_command_language_fails_closed_to_dictation_without_tier_two():
    seen: list[str] = []

    class _Router:
        def classify(self, text: str, profile: str = "default"):
            seen.append(text)
            return None

    got = classify("save", language="de", slm_router=_Router())

    assert got.intent is IntentType.DICTATE
    assert seen == []


@pytest.mark.parametrize(
    ("configured", "speech", "expected"),
    [
        ("auto", "en", "en"),
        ("auto", "en-US", "en"),
        ("auto", "zh", "zh"),
        ("auto", "zh-CN", "zh"),
        ("auto", "zh-TW", "zh"),
        ("auto", "zh-Hans", "zh"),
        ("auto", "zh-Hant", "zh"),
        ("auto", "zh-HK", "zh-hk"),
        ("auto", "de", "de"),
        ("zh", "en", "zh"),
        ("en", "zh", "en"),
    ],
)
def test_command_language_resolution(configured, speech, expected):
    assert resolve_command_language(configured, speech) == expected


def test_hong_kong_speech_tag_is_not_silently_treated_as_mandarin_command_grammar():
    language = resolve_command_language("auto", "zh-HK")
    assert language == "zh-hk"
    with pytest.raises(KeyError):
        get_grammar(language)


def test_default_classifier_stays_english_for_api_compatibility():
    got = classify("save file")
    assert got.action == "save"

    chinese = classify("保存文件")
    assert chinese.intent is IntentType.DICTATE



def test_commands_config_defaults_to_follow_stt_language():
    assert CommandsConfig().language == "auto"


def test_invalid_command_language_is_repaired_to_auto(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[commands]\nlanguage = "cantonese"\n',
        encoding="utf-8",
    )

    loaded = load_config_checked(path)

    assert loaded.config.commands.language == "auto"
    assert any(
        problem.section == "commands"
        and problem.key == "language"
        and "cantonese" in problem.detail
        for problem in loaded.problems
    )


def test_daemon_passes_resolved_language_to_both_classifier_paths():
    daemon = (
        Path(__file__).resolve().parent.parent
        / "src"
        / "yazses"
        / "core"
        / "daemon.py"
    ).read_text(encoding="utf-8")

    assert daemon.count("language=self._command_language") == 2
    assert "resolve_command_language(" in daemon
