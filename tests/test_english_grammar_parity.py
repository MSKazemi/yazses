"""English Tier-1 behaviour is byte-identical to before the language registry (#499 CMD-01).

The English rules moved from ``commands/grammar.py`` into ``commands/grammars/en.py``
when the Mandarin grammar was added. ``tests/test_command_grammar_registry.py`` checks
that the legacy ``_RULES`` view matches ``ENGLISH_GRAMMAR``, but both are built from the
same table, so that check cannot notice a change to the table itself.

``tests/fixtures/commands/en_grammar_parity.json`` is the independent oracle. It was
generated once by running the *pre-extraction* ``grammar.py`` (commit bbd285a5, the
parent of 8e2db38b) over every English vector the repository had: the command phrase
fixtures, the English dictation corpus, the contract grammar vectors, the English fuzz
seeds, the Mandarin fixtures (which the default path must still type as text) and a
set of punctuation/case/number edge cases. It records that commit's rule table and its
answer for each input. Nothing here regenerates it from today's code.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from yazses.commands import grammar
from yazses.commands.grammars.en import ENGLISH_GRAMMAR
from yazses.commands.grammars.registry import get_grammar
from yazses.commands.types import CommandIntent, IntentType

SNAPSHOT_PATH = Path(__file__).parent / "fixtures" / "commands" / "en_grammar_parity.json"
SNAPSHOT = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
CASES: list[dict] = SNAPSHOT["cases"]

#: Spellings of English that must all select the same grammar as the default call.
ENGLISH_TAGS = ("en", "EN", "en-US", "en_GB", " en ")


def _triple(result: CommandIntent) -> dict:
    return {"intent": result.intent.value, "action": result.action, "args": result.args}


def test_snapshot_is_the_pre_extraction_oracle_and_is_not_trivial():
    assert SNAPSHOT["source_commit"].startswith("bbd285a5")
    commands = [c for c in CASES if c["intent"] != "dictate"]
    dictation = [c for c in CASES if c["intent"] == "dictate"]
    # Both sides must be well populated, or "identical" proves little.
    assert len(commands) >= 100
    assert len(dictation) >= 150
    # Every pre-extraction action is exercised by at least one positive case.
    assert {r["action"] for r in SNAPSHOT["rules"]} <= {c["action"] for c in commands}


def test_english_rule_table_is_byte_identical_to_the_pre_extraction_table():
    current = [
        {
            "pattern": rule.pattern.pattern,
            "flags": int(rule.pattern.flags),
            "intent": rule.intent.value,
            "action": rule.action,
            "arg_names": list(rule.arg_names),
        }
        for rule in ENGLISH_GRAMMAR.rules
    ]
    assert current == SNAPSHOT["rules"]


@pytest.mark.parametrize("language", ENGLISH_TAGS)
def test_every_english_tag_selects_the_one_english_grammar(language):
    assert get_grammar(language) is ENGLISH_GRAMMAR


def test_default_call_matches_the_pre_extraction_classifier_on_every_vector():
    wrong = []
    for case in CASES:
        got = grammar.classify(case["input"])
        expected = {k: case[k] for k in ("intent", "action", "args")}
        if _triple(got) != expected or got.raw_text != case["input"]:
            wrong.append((case["input"], expected, _triple(got)))
    assert wrong == []


@pytest.mark.parametrize("language", ENGLISH_TAGS)
def test_explicit_english_language_is_identical_to_the_default_call(language):
    wrong = []
    for case in CASES:
        got = grammar.classify(case["input"], language=language)
        expected = {k: case[k] for k in ("intent", "action", "args")}
        if _triple(got) != expected:
            wrong.append((case["input"], expected, _triple(got)))
    assert wrong == []


def test_english_tier_two_is_consulted_exactly_where_it_was_before():
    """Pre-extraction: the router ran on every non-blank Tier-1 miss, with the profile."""

    class _Recorder:
        def __init__(self) -> None:
            self.seen: list[tuple[str, str]] = []

        def classify(self, text: str, profile: str) -> CommandIntent | None:
            self.seen.append((text, profile))
            return None

    router = _Recorder()
    for case in CASES:
        grammar.classify(case["input"], "vscode", slm_router=router)

    expected = [
        (c["input"], "vscode")
        for c in CASES
        if c["intent"] == "dictate" and c["input"].strip()
    ]
    assert router.seen == expected


def test_english_macro_tier_still_wins_before_the_grammar():
    class _Hit:
        trigger = "undo"

    class _Table:
        def match(self, text: str) -> _Hit | None:
            return _Hit() if text == "undo" else None

    got = grammar.classify("undo", macro_table=_Table(), language="en")
    assert (got.intent, got.action, got.args) == (
        IntentType.MACRO,
        "expand",
        {"trigger": "undo"},
    )
