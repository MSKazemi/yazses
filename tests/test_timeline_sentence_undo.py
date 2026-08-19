""""Undo that sentence" deleted the whole burst whenever it ended with a full stop.

`_trailing_count` found the last sentence terminator with `rfind` over the entire string,
then refused it when it sat in the final position:

    idx = max(last.rfind("."), last.rfind("!"), last.rfind("?"))
    return len(last) - idx - 1 if 0 <= idx < len(last) - 1 else len(last)

A completed sentence *ends* with its terminator, so `rfind` finds that one, the guard
rejects it, and the fallback deletes everything:

    "One. Two three."   ->  15 backspaces, the whole burst gone
    "One. Two three"    ->  11 backspaces, leaving "One."       (correct)

The feature therefore worked only on a burst whose final sentence had **no** terminator —
and dictation ends sentences with one, whether from voice punctuation or from Whisper's own
punctuation. The common case was the broken one, and the failure is destructive: text the
user did not ask to remove.

## Why no test caught it

`test_undo_word_and_sentence` uses `"Hello world. Bye now"` — no trailing period. It pins
the intended semantics precisely (undo leaves `"Hello world."`) and never exercises the
shape that fails. That test still passes here unchanged; this file adds the terminated
one.

The fix ignores the burst's own final terminator before searching, so the boundary found
is the one *between* sentences.
"""

from __future__ import annotations

import pytest

from yazses.timeline.history import InjectionTimeline


def _undo(text: str, scope: str = "sentence") -> str:
    """What remains after one undo of *scope*."""
    timeline = InjectionTimeline()
    timeline.record(text)
    op = timeline.peek_undo(scope)
    assert op is not None
    return text[: len(text) - op.backspaces]


@pytest.mark.parametrize(
    "text,remaining",
    [
        pytest.param("One. Two three.", "One.", id="the-defect-terminated"),
        pytest.param("One. Two three", "One.", id="unterminated-still-works"),
        pytest.param("Hello world. Bye now", "Hello world.", id="the-existing-test-case"),
        pytest.param("One. Two. Three.", "One. Two.", id="three-sentences"),
        pytest.param("One! Two?", "One!", id="other-terminators"),
        pytest.param("One. Two. ", "One.", id="trailing-whitespace"),
    ],
)
def test_undo_removes_one_sentence(text: str, remaining: str) -> None:
    assert _undo(text) == remaining


def test_a_single_sentence_undoes_the_whole_burst() -> None:
    """There is no earlier sentence to fall back to, so everything is the right answer."""
    assert _undo("All done.") == ""
    assert _undo("hello world") == ""


def test_terminated_and_unterminated_agree() -> None:
    """The pair that shows the shape of the bug: only the full stop differed."""
    assert _undo("One. Two three.") == _undo("One. Two three") == "One."


def test_word_scope_is_unaffected() -> None:
    """A fix reaching into the wrong branch would show up here."""
    assert _undo("one two three", scope="word") == "one two"
    assert _undo("hello world ", scope="word") == "hello"


def test_burst_scope_is_unaffected() -> None:
    for scope in ("last", "burst", "all"):
        assert _undo("One. Two three.", scope=scope) == ""


def test_peek_does_not_mutate() -> None:
    """The property the class exists to provide; a scope change must not break it."""
    timeline = InjectionTimeline()
    timeline.record("One. Two three.")
    first = timeline.peek_undo("sentence")
    second = timeline.peek_undo("sentence")
    assert first == second
    assert timeline.text() == "One. Two three."


def test_undo_then_redo_round_trips() -> None:
    """The removed fragment must be exactly what redo puts back."""
    timeline = InjectionTimeline()
    timeline.record("One. Two three.")
    timeline.undo("sentence")
    assert timeline.text() == "One."
    op = timeline.redo()
    assert op is not None
    assert timeline.text() == "One. Two three."
