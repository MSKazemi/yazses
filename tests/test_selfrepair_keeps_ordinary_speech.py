"""Dictating "that is not what I mean at all" must not type "that is not at all".

`_EDIT_TERMS` includes a bare ``i mean``, and the rule **deletes the word before the
editing term**. "I mean" is one of the commonest phrases in English, so an unguarded match
silently removes real speech:

    that is not what I mean at all     ->  that is not at all
    she said no I mean nothing by it   ->  she nothing by it

This is the same shape as a defect this project has already had once, in a different
module: the disfluency filter's self-correction triggers destroyed prose. The lesson had
not transferred to `selfrepair`.

## Why the guard is narrow

Only the **bare** term is restricted, and only by the word in front of it. The explicit
markers — "no I mean", "make that", "or rather", "no make it" — are unambiguous
corrections and stay unrestricted, which is why the feature's own advertised example
(`email Sarah no I mean Sara` → `email Sara`) is untouched.

The blocked words are those that make ``<X> I mean`` an ordinary construction: "what",
"know", "how" and the pronouns. Nobody corrects the word "what" into something else; the
whole phrase is prose.

## The asymmetry that decides it

A missed repair leaves the words exactly as spoken and the user reads them. A false repair
**deletes a word**, silently, in a dictation product. So the ambiguous case resolves
toward leaving the text alone — the same rule used for the ITN email guard.
"""

from __future__ import annotations

import pytest

from yazses.selfrepair.repair import _NOT_A_REPARANDUM, apply_self_repair

PROSE = [
    "that is not what I mean at all",
    "do you know what I mean",
    "I mean what I say",
    "this is exactly what I mean",
    "tell me how I mean to proceed",
    "I know what you mean",
    "say what you mean and mean what you say",
]

REPAIRS = [
    ("email Sarah no I mean Sara", "email Sara"),
    ("meet at three I mean four", "meet at four"),
    ("call Bob or rather Rob", "call Rob"),
    ("send it Tuesday make that Wednesday", "send it Wednesday"),
]


@pytest.mark.parametrize("text", PROSE)
def test_ordinary_speech_is_left_alone(text: str) -> None:
    assert apply_self_repair(text) == text, "a dictated word was deleted"


@pytest.mark.parametrize("spoken,expected", REPAIRS)
def test_real_repairs_still_apply(spoken: str, expected: str) -> None:
    """A guard that disabled the feature would pass every prose test perfectly."""
    assert apply_self_repair(spoken) == expected


def test_chained_repairs_still_resolve() -> None:
    """The documented behaviour: "A no I mean B no I mean C" collapses to C."""
    assert apply_self_repair("A no I mean B no I mean C") == "C"


def test_the_explicit_markers_are_not_restricted() -> None:
    """Only the bare term is guarded — an explicit marker means a correction.

    "what" is blocked before a bare "I mean" and must NOT be blocked after "no I mean",
    or the shipped example would stop working the moment someone corrected that word.
    """
    assert "what" in _NOT_A_REPARANDUM
    assert apply_self_repair("say what no I mean why") == "say why"
    assert apply_self_repair("pick what make that which") == "pick which"


def test_the_bare_term_still_repairs_after_an_ordinary_word() -> None:
    """The guard must be about the *word*, not about disabling the bare term."""
    assert apply_self_repair("meet at three I mean four") == "meet at four"
    assert apply_self_repair("send it Monday I mean Friday") == "send it Friday"


def test_the_blocklist_holds_no_correctable_word() -> None:
    """Cheap standing check that the list has not grown teeth.

    These are things a person plausibly says and then corrects; none should ever be
    protected from being a reparandum.
    """
    plausible = {"sarah", "three", "monday", "bob", "tuesday", "red", "london"}
    assert not (plausible & _NOT_A_REPARANDUM)


def test_empty_and_trivial_input() -> None:
    assert apply_self_repair("") == ""
    assert apply_self_repair("hello") == "hello"
