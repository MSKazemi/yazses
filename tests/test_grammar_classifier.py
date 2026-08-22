"""Tests for the code command grammar classifier."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from yazses.commands.grammar import IntentType, classify

COMMANDS_PATH = Path(__file__).parent / "fixtures" / "commands" / "command_phrases.json"
DICTATION_PATH = Path(__file__).parent / "fixtures" / "commands" / "dictation_corpus.txt"


def load_commands():
    with open(COMMANDS_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_dictation_sentences():
    text = DICTATION_PATH.read_text(encoding="utf-8")
    # Split into ~sentence-length chunks for testing
    sentences = [s.strip() for s in text.replace('\n', ' ').split('.') if s.strip()]
    return sentences


@pytest.mark.parametrize("entry", load_commands(), ids=lambda e: e["phrase"][:40])
def test_command_recognized(entry):
    result = classify(entry["phrase"])
    assert result.intent.value == entry["expected_intent"], (
        f"Phrase: {entry['phrase']!r}\n"
        f"Expected intent: {entry['expected_intent']}\n"
        f"Got: {result.intent.value}, action={result.action}"
    )
    if "expected_action" in entry and entry["expected_action"]:
        assert result.action == entry["expected_action"], (
            f"Phrase: {entry['phrase']!r}\n"
            f"Expected action: {entry['expected_action']}\n"
            f"Got: {result.action}"
        )


def test_command_precision():
    """At least 90% of command phrases must be correctly classified."""
    commands = load_commands()
    correct = sum(
        1 for e in commands
        if classify(e["phrase"]).intent.value == e["expected_intent"]
    )
    precision = correct / len(commands)
    assert precision >= 0.90, f"Command precision {precision:.1%} < 90% ({correct}/{len(commands)})"


def test_zero_false_positives_on_dictation():
    """No dictation sentence should trigger a non-DICTATE intent."""
    sentences = load_dictation_sentences()
    false_positives = [
        s for s in sentences
        if classify(s).intent != IntentType.DICTATE
    ]
    assert len(false_positives) == 0, (
        "False positive commands detected in dictation corpus:\n" +
        "\n".join(f"  {s!r} → {classify(s).action}" for s in false_positives[:5])
    )


def test_runtime_under_5ms():
    t0 = time.perf_counter()
    for _ in range(200):
        classify("delete last three words")
    elapsed_ms = (time.perf_counter() - t0) / 200 * 1000
    assert elapsed_ms < 5, f"classify() took {elapsed_ms:.2f} ms (> 5 ms)"


def test_number_word_normalisation():
    result = classify("delete last three words")
    assert result.intent == IntentType.EDIT
    assert result.action == "delete_words"
    assert result.args.get("n") == "3"


def test_dictate_fallthrough():
    result = classify("The quick brown fox jumps over the lazy dog")
    assert result.intent == IntentType.DICTATE
    assert result.action == "inject"


def test_go_to_line():
    result = classify("go to line 42")
    assert result.intent == IntentType.NAVIGATE
    assert result.action == "go_to_line"
    assert result.args.get("n") == "42"


def test_empty_text_is_dictate():
    result = classify("")
    assert result.intent == IntentType.DICTATE


def test_rename_symbol():
    result = classify("rename this to my_new_name")
    assert result.intent == IntentType.REFACTOR
    assert result.action == "rename_symbol"
    assert result.args.get("name") == "my_new_name"
