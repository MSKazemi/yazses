"""A spoken repeat count is bounded before any key is sent.

The English grammar captures ``\\d+`` with no ceiling (commands/grammars/en.py), so on
8a72bbc6 a mis-heard "delete the last 1000000 words" sent a million Ctrl+BackSpace --
the whole document -- and blocked the daemon while doing it. The Mandarin grammar
already caps counts at 99 at parse time; dispatch now applies the same ceiling to every
language, at the single place that repeats keys, and refuses (nothing typed) above it.

Pure: a recording fake injector, no daemon, no audio, no model.
"""
from __future__ import annotations

import pytest

from yazses.commands.dispatch import MAX_REPEAT, dispatch
from yazses.commands.grammar import classify
from yazses.commands.types import CommandIntent, IntentType


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def inject(self, text: str) -> None:
        self.calls.append(("text", text))

    def inject_backspaces(self, count: int) -> None:
        self.calls.append(("backspaces", count))

    def inject_key_sequence(self, keys: list[str]) -> None:
        self.calls.append(("keys", list(keys)))


def _keys_sent(rec: _Recorder) -> int:
    return sum(1 for kind, _ in rec.calls if kind == "keys")


def test_the_ceiling_matches_the_mandarin_grammar() -> None:
    from yazses.commands.grammars.zh import MAX_COUNT

    assert MAX_REPEAT == MAX_COUNT == 99


@pytest.mark.parametrize("phrase", [
    "delete the last 1000000 words",
    "delete the last 500 lines",
    "undo 100 times",
    "select 250 lines",
])
def test_an_out_of_range_count_sends_nothing_and_types_nothing(phrase: str) -> None:
    intent = classify(phrase)
    # Classification is unchanged: the phrase is still a command (that is a grammar
    # decision this fix deliberately does not make).
    assert intent.intent != IntentType.DICTATE
    rec = _Recorder()
    dispatch(intent, rec)
    assert rec.calls == []


@pytest.mark.parametrize("phrase,action", [
    ("delete the last 99 words", "delete_words"),
    ("delete the last 99 lines", "delete_lines"),
    ("undo 99 times", "undo_n"),
])
def test_the_ceiling_itself_is_still_allowed(phrase: str, action: str) -> None:
    intent = classify(phrase)
    assert intent.action == action
    rec = _Recorder()
    dispatch(intent, rec)
    assert _keys_sent(rec) == 99
    assert not any(kind == "text" for kind, _ in rec.calls)


def test_select_lines_at_the_ceiling() -> None:
    rec = _Recorder()
    dispatch(classify("select 99 lines"), rec)
    # One lead chord plus 98 shift+Down.
    assert _keys_sent(rec) == 99


def test_ordinary_counts_are_unchanged() -> None:
    rec = _Recorder()
    dispatch(classify("delete the last three words"), rec)
    assert rec.calls == [("keys", ["ctrl+BackSpace"])] * 3


def test_a_huge_count_built_directly_is_refused_too() -> None:
    # Any producer of a CommandIntent (SLM router, activation pipeline) gets the bound.
    intent = CommandIntent(intent=IntentType.EDIT, action="delete_words",
                           args={"n": "10" * 6}, raw_text="delete the last lots words")
    rec = _Recorder()
    dispatch(intent, rec)
    assert rec.calls == []


def test_go_to_line_types_ascii_digits_for_a_unicode_numeral() -> None:
    # "\d" in the grammar also captures Arabic-Indic digits; the editor's dialog is
    # given ASCII.
    intent = classify("go to line ١٢")
    assert intent.action == "go_to_line"
    rec = _Recorder()
    dispatch(intent, rec)
    assert ("text", "12") in rec.calls
    assert ("text", "١٢") not in rec.calls
