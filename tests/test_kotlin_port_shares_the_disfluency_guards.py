"""The Android port's rollback guard must know every word the Python one does.

`triggerIsGoverned` in the Kotlin port carried only the *negation and modal* half of
the guard. The other half -- determiners, possessives, reporting verbs and copulas --
was added to Python by `906ac76`/`25b19a3` and never ported, so on Android these still
lost their first half and read as fluent text the user never said::

    "he said never mind the cost and left"   ->  "the cost and left"
    "the no wait policy applies to walk-ins" ->  "policy applies to walk-ins"
    "there is no wait time at this branch"   ->  "time at this branch"

That is the output the filter's own docstring names as the worst it can produce: it
does not garble the meaning, it inverts it.

**Why a test here and not another contract vector.** ADR-MOB-008 makes the vectors the
definition of behaviour, and one vector did catch this -- exactly one. Of the 33 words
in the phrase-context list, the corpus names `said` and nothing else, so the Android
leg reported a single red for a defect with 33 instances and the other 32 would have
survived the fix that closed it. A vector proves one *example*; only comparing the
sets proves the *set*. Both halves are checked separately because they are two
different pieces of evidence about the same trigger, and a port that merged them into
one blob would still pass a total-count check while dropping a category.

This runs in the Python suite deliberately: it executes on every platform leg, whereas
the Kotlin tests run only in the Android job.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from yazses.stt.filters.disfluency import (
    _NEGATIONS_BEFORE_TRIGGER,
    _PHRASE_CONTEXT_BEFORE_TRIGGER,
)

ROOT = Path(__file__).resolve().parent.parent
KOTLIN = (
    ROOT
    / "android/core/postprocess/src/main/kotlin/com/yazses/core/postprocess/Disfluency.kt"
)

#: Kotlin constant -> the Python tuple it mirrors.
PAIRS = {
    "GOVERNING_WORDS": _NEGATIONS_BEFORE_TRIGGER,
    "PHRASE_CONTEXT_WORDS": _PHRASE_CONTEXT_BEFORE_TRIGGER,
}


def _kotlin_set(name: str) -> set[str]:
    """The literal words in `private val <name> = setOf( ... )`.

    Parsed rather than restated: a copy of the list written here would agree with
    whichever side it was copied from and disagree with the other, which is the
    failure being guarded against.
    """
    source = KOTLIN.read_text(encoding="utf-8")
    match = re.search(rf"val\s+{name}\s*=\s*setOf\((.*?)\n\)", source, re.DOTALL)
    assert match, (
        f"{KOTLIN.name} no longer declares `{name}` as a `setOf(...)`. Either the "
        "port was restructured -- in which case point this guard at the new "
        "declaration -- or the guard is now blind, which is worse than absent."
    )
    body = re.sub(r"//[^\n]*", "", match.group(1))  # drop the category comments
    return set(re.findall(r'"([^"]*)"', body))


def test_the_kotlin_source_is_where_this_guard_thinks_it_is() -> None:
    """Guards against every test below passing on a file that moved."""
    assert KOTLIN.is_file(), f"{KOTLIN.relative_to(ROOT)} is missing"


@pytest.mark.parametrize("name", sorted(PAIRS))
def test_the_port_knows_every_word_python_does(name: str) -> None:
    expected = set(PAIRS[name])
    actual = _kotlin_set(name)
    missing = sorted(expected - actual)
    assert not missing, (
        f"{name} in the Android port is missing {len(missing)} word(s) the Python "
        f"filter guards on: {missing}. A trigger preceded by one of those is prose, "
        "and rolling back on it deletes the first half of the user's sentence and "
        "leaves a fluent remainder they never said. Add them to "
        f"{KOTLIN.relative_to(ROOT)}."
    )


@pytest.mark.parametrize("name", sorted(PAIRS))
def test_the_port_has_not_widened_the_guard_on_its_own(name: str) -> None:
    """Extra words are a defect in the other direction: every entry here biases the
    filter away from rolling back, so a word only the port knows means a real
    correction is silently kept on Android and dropped everywhere else."""
    expected = set(PAIRS[name])
    extra = sorted(_kotlin_set(name) - expected)
    assert not extra, (
        f"{name} in the Android port guards on {extra}, which Python does not. The "
        "two platforms would then disagree about whether a real self-correction is "
        "performed. Add the word to the Python constant, or remove it here."
    )


def test_the_two_halves_have_not_been_merged() -> None:
    """A port that folded both lists into one set would pass the membership tests
    while losing the distinction the comments carry, and the next word added to
    either Python constant would have no obvious home."""
    assert not (_kotlin_set("GOVERNING_WORDS") & _kotlin_set("PHRASE_CONTEXT_WORDS")), (
        "the two Kotlin sets now overlap; they mirror two disjoint Python constants "
        "and an overlap means one of them has absorbed the other."
    )
