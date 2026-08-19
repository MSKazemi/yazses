"""Dictating "look at the dot com boom" must not produce "look@the.com boom".

`_EMAIL_RE` matches ``<words> at <words with a spoken dot>``. Its comment justifies the
one guard it had:

    # The domain MUST contain a spoken "dot" so a plain "at" in ordinary speech
    # ("meet at noon") never matches.

That does stop "meet at noon". It does nothing about the far commoner shape — an ordinary
sentence containing *"at <word> dot <word>"*. Every one of these was rewritten:

    look at the dot com boom          ->  look@the.com boom
    point at the dot on the screen    ->  point@the.on the screen
    stare at the dot product formula  ->  stare@the.product formula
    meet me at the dot matrix printer ->  meet me@the.matrix printer

Eight of eight realistic sentences, corrupted into email addresses in the middle of
dictated prose.

## The two conditions

Every spoken address satisfies both; ordinary English rarely satisfies either.

* the **last** label is a real TLD — "the dot matrix" ends in "matrix";
* the **first** label is not an article — "look at **the** dot com boom" is prose, and no
  one says "at the gmail dot com".

Either alone is insufficient, which is why both are here: "look at the dot com boom" ends
in a genuine TLD and is still prose, and "at company dot headquarters" opens with a real
label and is still not an address.

When the check fails the words are left **exactly as spoken**. A missed address costs one
hand-typed line; a false one silently corrupts a sentence the user dictated and may never
re-read.

## Not fixed here

`dev at my-project dot io` is not recognised, because `_EMAIL_RE` uses `\\w+`, which
excludes the hyphen. Verified identical before and after this change — pre-existing, and
a separate question (spoken, that hyphen arrives as the word "dash" anyway).
"""

from __future__ import annotations

import pytest

from yazses.itn.normalize import _looks_like_a_domain, normalize_entities

PROSE = [
    "look at the dot com boom",
    "we met at the dot matrix era",
    "point at the dot on the screen",
    "aim at the dot com companies",
    "stare at the dot product formula",
    "a talk at the dot net conference",
    "she looked at the dot then away",
    "arrive at the dot com office tomorrow",
    "meet me at the dot matrix printer",
    "I put a dot at the end of the sentence",
    "look at the cat",
    "she is at home",
]

ADDRESSES = [
    ("john dot doe at gmail dot com", "john.doe@gmail.com"),
    ("sara at example dot org", "sara@example.org"),
    ("me at company dot co dot uk", "me@company.co.uk"),
    ("first dot last at university dot edu", "first.last@university.edu"),
    ("contact at site dot dev", "contact@site.dev"),
]


@pytest.mark.parametrize("text", PROSE)
def test_ordinary_speech_is_returned_untouched(text: str) -> None:
    assert normalize_entities(text) == text, (
        "a dictated sentence was rewritten into an email address"
    )


@pytest.mark.parametrize("spoken,written", ADDRESSES)
def test_real_addresses_still_convert(spoken: str, written: str) -> None:
    """A fix that stopped converting anything would pass the prose tests perfectly."""
    assert written in normalize_entities(spoken)


def test_both_conditions_are_load_bearing() -> None:
    """Either alone lets a real case through, which is why the fix uses both."""
    # Real TLD, but the domain opens with an article -> prose.
    assert not _looks_like_a_domain("the.com")
    # Sensible first label, but the last is not a TLD -> not an address.
    assert not _looks_like_a_domain("company.headquarters")
    # Both satisfied.
    assert _looks_like_a_domain("gmail.com")
    assert _looks_like_a_domain("company.co.uk")


def test_a_single_label_is_not_a_domain() -> None:
    assert not _looks_like_a_domain("com")
    assert not _looks_like_a_domain("")


def test_the_failure_mode_is_leaving_the_words_alone() -> None:
    """Not dropping them, not guessing — the spoken words are preserved verbatim."""
    text = "ping me at internal dot headquarters"
    assert normalize_entities(text) == text


def test_the_other_itn_rules_are_unaffected() -> None:
    """The email guard must not disturb the neighbouring conversions.

    Asserted against the version rule's *actual* output, confirmed identical before and
    after this change. My first attempt asserted "3.14" and failed — the rule produces
    `v3.1 four`, which is its own pre-existing behaviour and not something this fix
    touches.
    """
    assert normalize_entities("version two point zero") == "v2.0"
    assert normalize_entities("version three point one four") == "v3.1 four"
