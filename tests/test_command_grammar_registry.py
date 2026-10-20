from __future__ import annotations

import subprocess
import sys

import pytest

from yazses.commands import grammar
from yazses.commands.grammars.en import ENGLISH_GRAMMAR
from yazses.commands.grammars.registry import get_grammar, registered_languages
from yazses.commands.types import CommandIntent, IntentType


def test_registry_keeps_english_and_registers_mandarin_lazily():
    assert registered_languages() == ("en", "zh")
    assert get_grammar("en") is ENGLISH_GRAMMAR
    assert get_grammar("en-US") is ENGLISH_GRAMMAR
    assert get_grammar("zh").language == "zh"


def test_unknown_language_is_not_silently_mapped_to_another_grammar():
    with pytest.raises(KeyError, match="No Tier-1 command grammar"):
        get_grammar("de")
    with pytest.raises(KeyError, match="No Tier-1 command grammar"):
        get_grammar("zh-HK")


def test_grammar_module_keeps_public_intent_import_compatibility():
    assert grammar.CommandIntent is CommandIntent
    assert grammar.IntentType is IntentType


def test_legacy_rule_view_is_sequence_identical_to_registry_rules():
    assert len(grammar._RULES) == len(ENGLISH_GRAMMAR.rules)
    for legacy, registered in zip(grammar._RULES, ENGLISH_GRAMMAR.rules):
        pattern, intent, action, arg_names = legacy
        assert pattern.pattern == registered.pattern.pattern
        assert pattern.flags == registered.pattern.flags
        assert intent is registered.intent
        assert action == registered.action
        assert tuple(arg_names) == registered.arg_names


@pytest.mark.parametrize(
    ("text", "intent", "action", "args"),
    [
        ("Undo.", IntentType.EDIT, "undo", {}),
        ("delete the last three words", IntentType.EDIT, "delete_words", {"n": "3"}),
        ("go to line ten", IntentType.NAVIGATE, "go_to_line", {"n": "10"}),
        ("run the tests", IntentType.TERMINAL, "run_tests", {}),
        ("save this thought for later", IntentType.DICTATE, "inject", {}),
    ],
)
def test_registry_refactor_preserves_representative_classification(
    text,
    intent,
    action,
    args,
):
    result = grammar.classify(text)

    assert result.intent is intent
    assert result.action == action
    assert result.args == args
    assert result.raw_text == text



def test_default_english_import_does_not_eagerly_import_mandarin_module():
    code = (
        "import sys; import yazses.commands.grammar; "
        "assert 'yazses.commands.grammars.zh' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
