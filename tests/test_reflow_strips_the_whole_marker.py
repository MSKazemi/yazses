"""`yazses reflow` mangled "Firstly" into "ly", and never stripped a filler.

Two defects in the command whose stated purpose is turning "a long rambling monologue"
into an outline.

**The marker was cut in the wrong place.** `_BULLET_MARKERS` lists "first" before
"firstly" and "second" before "secondly", and the strip loop broke on the first match:

    "Firstly we fix the tray."   ->  "- ly we fix the tray"
    "Secondly we ship it."       ->  "- ly we ship it"

Three of the commonest spoken outline markers each produced nonsense, in the output the
user keeps. This is the same longest-match-first rule that `yazses case` needs for
"snake" vs "snake case" and `gitvoice` needs for its separators — the third place in one
audit where overlapping alternatives had to be ordered by length.

**Fillers were never in the list at all.** Only ordering words were stripped, so the
single commonest thing in a rambling monologue survived into the outline:

    "Um we should fix the tray."       ->  "- Um we should fix the tray"
    "So basically the icon dies."      ->  "- So basically the icon dies"

The filler list is taken from `DisfluencyConfig.filler_words` — the one the dictation
filter already uses — rather than copied, so the two cannot drift. Only the
*sentence-initial* extras ("so", "well", "right", "basically") are local, and they are
local for a reason: mid-sentence those are ordinary words.

Stripping now repeats, because speech stacks markers: "so um basically we should" opens
with three.
"""

from __future__ import annotations

import pytest

from yazses.config import DisfluencyConfig
from yazses.reflow.outline import _BULLET_MARKERS, _leading_marker, reflow


@pytest.mark.parametrize(
    "said,expected",
    [
        ("Firstly we fix the tray.", "- we fix the tray"),
        ("Secondly we ship it.", "- we ship it"),
        ("Thirdly we tell people.", "- we tell people"),
        ("First of all we plan.", "- we plan"),
    ],
)
def test_the_whole_marker_is_removed(said: str, expected: str) -> None:
    """The defect, at the exact words that triggered it."""
    got = reflow(said)
    assert got == expected
    assert not got.startswith("- ly"), "the marker was cut mid-word"


def test_the_overlapping_pairs_are_still_in_the_list() -> None:
    """The premise. If these stop overlapping, the ordering rule stops mattering."""
    for short, long in (("first", "firstly"), ("second", "secondly"), ("third", "thirdly")):
        assert short in _BULLET_MARKERS and long in _BULLET_MARKERS


def test_longest_match_wins() -> None:
    assert _leading_marker("firstly we go") == "firstly"
    assert _leading_marker("first we go") == "first"
    assert _leading_marker("so basically we go") == "so basically"


@pytest.mark.parametrize(
    "said,expected",
    [
        ("Um we should fix the tray.", "- we should fix the tray"),
        ("So basically the icon dies.", "- the icon dies"),
        ("You know it just vanishes.", "- it just vanishes"),
        ("Well we could ship it.", "- we could ship it"),
    ],
)
def test_a_leading_filler_is_stripped(said: str, expected: str) -> None:
    assert reflow(said) == expected


def test_stacked_markers_are_all_stripped() -> None:
    """Real speech stacks them; one pass left the rest behind."""
    assert reflow("So um basically I need to update the docs.") == (
        "- [ ] I need to update the docs"
    )


def test_the_filler_list_is_shared_with_the_dictation_filter() -> None:
    """Not a second copy — that is how two lists come to disagree."""
    for filler in DisfluencyConfig().filler_words:
        assert _leading_marker(f"{filler} something") is not None, (
            f"{filler!r} is filtered during dictation but not by reflow"
        )


def test_action_detection_survives_the_strip() -> None:
    """The checkbox is decided on the whole sentence, so stripping must not lose it."""
    assert reflow("Also I need to call them.").startswith("- [ ] ")
    assert reflow("Also we should call them.").startswith("- ")
    assert not reflow("Also we should call them.").startswith("- [ ] ")


def test_a_sentence_that_is_only_a_marker_is_kept() -> None:
    """Stripping to nothing would emit a bare bullet; keeping the word is honest."""
    assert reflow("Anyway.") == "- Anyway"
    assert reflow("Finally.") == "- Finally"


def test_ordinary_prose_is_untouched() -> None:
    """Only *leading* markers count. "So" mid-sentence is an ordinary word."""
    assert reflow("We ship it so people can use it.") == (
        "- We ship it so people can use it"
    )
