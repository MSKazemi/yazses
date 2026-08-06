"""Tests for Mid-Thought Undo (P1 templates) — "scratch that" buffer revision.

Spec: design/specs/mid-thought-undo.md. Pure logic, offline.
"""
from __future__ import annotations

import pytest

from yazses.commands.revise import DictationLedger, parse_revise

# --- parse_revise (whole-utterance only) -----------------------------------

@pytest.mark.parametrize("phrase", [
    "scratch that",
    "Scratch that.",
    "scratch this",
    "scratch last",
    "no scratch that",
    "delete that",
])
def test_parse_revise_recognizes_scratch_family(phrase):
    assert parse_revise(phrase) == "scratch_last"


@pytest.mark.parametrize("phrase", [
    "scratch the surface",            # trigger word, but not the command
    "I want to scratch that itch",    # in-sentence — must not fire mid-dictation
    "delete the last three words",    # handled by the existing grammar, not here
    "hello world",
    "",
])
def test_parse_revise_ignores_non_commands(phrase):
    assert parse_revise(phrase) is None


# --- DictationLedger (LIFO of injected-burst char counts) ------------------

def test_ledger_scratch_returns_last_burst_length_lifo():
    ledger = DictationLedger()
    ledger.record("hello ")     # 6
    ledger.record("world")      # 5
    assert ledger.scratch_last() == 5
    assert ledger.scratch_last() == 6
    assert ledger.scratch_last() == 0   # empty


def test_ledger_ignores_empty_text():
    ledger = DictationLedger()
    ledger.record("")
    ledger.record(None)  # type: ignore[arg-type]
    assert len(ledger) == 0
    assert ledger.scratch_last() == 0


def test_ledger_counts_unicode_by_characters_not_bytes():
    ledger = DictationLedger()
    ledger.record("café ☕")     # 6 characters
    assert ledger.scratch_last() == 6


def test_ledger_bounded_history_drops_oldest():
    ledger = DictationLedger(max_history=2)
    ledger.record("a")
    ledger.record("bb")
    ledger.record("ccc")        # evicts "a"
    assert len(ledger) == 2
    assert ledger.scratch_last() == 3   # "ccc"
    assert ledger.scratch_last() == 2   # "bb"
    assert ledger.scratch_last() == 0   # "a" was evicted


# --- Ledger text retention for Punch-In re-record (spec-punch-in) -----------

def test_ledger_last_text_returns_most_recent_burst_without_popping():
    ledger = DictationLedger()
    ledger.record("hello world")
    assert ledger.last_text() == "hello world"
    # Non-destructive: the char-count scratch path is unaffected.
    assert len(ledger) == 1


def test_ledger_last_text_empty_when_no_history():
    assert DictationLedger().last_text() == ""


def test_ledger_replace_last_swaps_text_and_count():
    ledger = DictationLedger()
    ledger.record("teh quick")
    ledger.replace_last("the quick")
    assert ledger.last_text() == "the quick"
    assert ledger.scratch_last() == len("the quick")  # count tracks corrected text


def test_ledger_replace_last_noop_when_empty():
    ledger = DictationLedger()
    ledger.replace_last("anything")  # must not raise
    assert len(ledger) == 0
