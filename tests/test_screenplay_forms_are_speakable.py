"""Every documented screenplay form must work when *spoken*, not only when typed.

`yazses screenplay` exists, in its own words, for "drafting a script by voice". All three
of its documented forms required punctuation no speech model emits:

    scene: interior coffee shop, day     colon AND comma
    Alice (character) hello there        literal parentheses
    transition: cut to                   colon

Said aloud, none matched, and `to_fountain` falls through to "anything else becomes an
action line" — so the raw words were passed straight into the screenplay, silently:

    "scene interior coffee shop day"  ->  scene interior coffee shop day

This is the third instance of one shape found in a single audit, after `gitvoice` branch
separators and `yazses case`'s mandatory colon: **the voice path required a character the
voice cannot produce.** Grouped here so the pattern is findable, not just the incident.

## The one that needed care

`scene` and `transition` are anchored on a distinctive leading keyword, so dropping the
colon costs nothing. `(character)` is different: bare "character" is an ordinary English
word, and without the parentheses "the character walks in" would become a cue for THE.
The spoken form is therefore accepted only when what precedes it looks like a name — at
most three words, not opening with a determiner. The parenthesised form stays exact and
is subject to neither check, so nothing that worked before can now be refused.
"""

from __future__ import annotations

import pytest

from yazses.screenplay.fountain import _MAX_NAME_WORDS, to_fountain

#: (spoken form, typed form, expected output). Both must give the same result.
EQUIVALENT = [
    ("scene interior coffee shop day", "scene: interior coffee shop, day",
     "INT. COFFEE SHOP - DAY"),
    ("scene exterior rooftop night", "scene: exterior rooftop, night",
     "EXT. ROOFTOP - NIGHT"),
    ("transition cut to", "transition: cut to", "CUT TO:"),
    ("Alice character hello there", "Alice (character) hello there",
     "ALICE\nhello there"),
]


@pytest.mark.parametrize("spoken,typed,expected", EQUIVALENT)
def test_spoken_and_typed_forms_agree(spoken: str, typed: str, expected: str) -> None:
    assert to_fountain(typed) == expected, "the typed form regressed"
    assert to_fountain(spoken) == expected, (
        f"{spoken!r} is the dictated form of {typed!r} and did not format; "
        "it would be written into the screenplay as raw words"
    )


def test_the_location_does_not_swallow_the_time_without_a_comma() -> None:
    """The subtle half of dropping the comma.

    With `(.+?)` lazy and the time-of-day group greedy, "coffee shop day" still splits.
    Had the location been greedy it would have produced `INT. COFFEE SHOP DAY - DAY`.
    """
    assert to_fountain("scene interior coffee shop day") == "INT. COFFEE SHOP - DAY"
    assert to_fountain("scene interior day spa evening") == "INT. DAY SPA - EVENING"


def test_a_scene_with_no_time_still_defaults() -> None:
    assert to_fountain("scene interior kitchen") == "INT. KITCHEN - DAY"


@pytest.mark.parametrize(
    "prose",
    [
        "the character walks in slowly",
        "a character enters",
        "she watched the main character leave the room",
        "this character has no name",
    ],
)
def test_prose_containing_character_stays_prose(prose: str) -> None:
    """The false positive the parentheses used to prevent."""
    assert to_fountain(prose) == prose, "an action line became a character cue"


def test_a_long_name_is_not_a_cue() -> None:
    """A cue is a name, not a sentence — the length guard, at its boundary."""
    short = " ".join(["Word"] * _MAX_NAME_WORDS)
    long = " ".join(["Word"] * (_MAX_NAME_WORDS + 1))
    assert to_fountain(f"{short} character hi").startswith(short.upper())
    assert to_fountain(f"{long} character hi") == f"{long} character hi"


def test_the_parenthesised_form_bypasses_both_guards() -> None:
    """Explicit punctuation is unambiguous, so nothing that worked may now be refused."""
    assert to_fountain("the narrator of this whole film (character) hello") == (
        "THE NARRATOR OF THIS WHOLE FILM\nhello"
    )
