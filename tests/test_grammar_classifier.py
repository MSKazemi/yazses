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


# ---- cost of a call: ratios, never a wall-clock budget ----------------------
#
# This used to assert ``< 5 ms`` per call.  An absolute budget measures the machine as
# much as the classifier: a starved CI runner (CI_POLICY section 13.1, or ``-n auto``
# contention) slows everything and fails a test that has no bug.  Compare with a fixed
# unit of plain-Python work measured in the same process, interleaved with it, and
# check how the cost grows with the input -- both cancel machine speed.  ``min`` over
# repeats discards the batches a noisy neighbour hit.

_SAMPLES = 200


def _machine_unit() -> int:
    """A fixed amount of pure-Python work: the yardstick for 'this machine, right now'."""
    total = 0
    for i in range(1000):
        total += i * i
    return total


def _best_seconds(fn, calls: int = 1) -> float:
    """Fastest per-call seconds of *fn*: the minimum over ``_SAMPLES`` batches of *calls*.

    Many short samples, not a few long ones.  Under heavy CPU contention the scheduler
    preempts a run that outlasts its time slice, so only a sample shorter than the slice
    can come back clean -- and the minimum needs just one of those.
    """
    best = float("inf")
    for _ in range(_SAMPLES):
        t0 = time.perf_counter()
        for _ in range(calls):
            fn()
        best = min(best, (time.perf_counter() - t0) / calls)
    return best


# Measured: one call is ~0.15 machine units.  The old 5 ms ceiling was ~100 units on the
# dev laptop; 50 still leaves two orders of magnitude and fails on a regression about the
# size the old test caught, without a clock in the assertion.
_MAX_UNITS_PER_CALL = 50


def test_a_call_costs_a_bounded_number_of_machine_units():
    call = _best_seconds(lambda: classify("delete last three words"), 20)
    unit = _best_seconds(_machine_unit)
    assert call < _MAX_UNITS_PER_CALL * unit, (
        f"classify() took {call / unit:.1f} machine units "
        f"(limit {_MAX_UNITS_PER_CALL}; 1 unit = {unit * 1e6:.1f} us here)"
    )


def test_cost_grows_linearly_with_the_utterance_not_quadratically():
    sentence = "the quick brown fox jumps over the lazy dog"

    def cost(copies: int) -> float:
        text = " ".join([sentence] * copies)
        return _best_seconds(lambda: classify(text))

    small, large = cost(1), cost(16)
    # Measured ~4.5x for 16x the words (fixed overhead dominates); quadratic is >100x.
    assert large < 40 * small, f"16x input cost {large / small:.0f}x -- not linear"


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
