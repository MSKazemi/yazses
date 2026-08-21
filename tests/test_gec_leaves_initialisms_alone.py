"""The article fixer turned "an FBI agent" into "a FBI agent".

`_wants_an` decided purely on whether the following word's first *letter* is a vowel:

    return w[:1] in "aeiou"

An initialism's article depends on how it is **said**, not how it is spelled. "FBI" is
spelled out — "an eff-bee-eye" — so it takes "an", and nine of ten correct initialisms
were rewritten wrong:

    an FBI agent  ->  a FBI agent
    an MRI scan   ->  a MRI scan
    an SSD drive  ->  a SSD drive
    an XML file   ->  a XML file

A grammar corrector introducing grammar errors into text that was already right.

## Why the article is left alone rather than fixed

No rule keyed on spelling can separate the two kinds of acronym. "FBI" is spelled out and
takes "an"; "NATO" is said as a word and takes "a". Both are four-or-fewer capitals with a
consonant first letter, and nothing in the string distinguishes them.

So the user's own article stands. The asymmetry decides it, as it does for the ITN email
guard and the self-repair one: a missed correction costs nothing — the user wrote what
they meant — while a false one corrupts text that was correct.

Ordinary words are unaffected, including the genuinely hard ones the module was written
for: "an hour", "a user", "a university", "an honest man".
"""

from __future__ import annotations

import pytest

from yazses.gec.guard import fix_articles

INITIALISMS = [
    "an FBI agent",
    "an MRI scan",
    "an SSD drive",
    "an XML file",
    "an LED light",
    "an RSS feed",
    "an HR issue",
    "a NATO summit",
    "a SQL query",
    "an X-ray",
    "a UN resolution",
]


@pytest.mark.parametrize("text", INITIALISMS)
def test_an_initialism_keeps_the_article_it_was_given(text: str) -> None:
    assert fix_articles(text) == text, "the article before an acronym was rewritten"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("a apple", "an apple"),
        ("an dog", "a dog"),
        ("a elephant", "an elephant"),
        ("I saw a owl", "I saw an owl"),
    ],
)
def test_ordinary_words_are_still_corrected(text: str, expected: str) -> None:
    """A guard that stopped correcting anything would pass every test above."""
    assert fix_articles(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("a hour", "an hour"),          # silent h
        ("a honest man", "an honest man"),
        ("an user", "a user"),          # "yoo" onset
        ("a university", "a university"),
        ("a European trip", "a European trip"),
        ("a one-time fee", "a one-time fee"),
    ],
)
def test_the_hard_cases_the_module_exists_for(text: str, expected: str) -> None:
    """These are why the exception lists are there; the fix must not disturb them."""
    assert fix_articles(text) == expected


def test_a_capitalised_ordinary_word_is_not_an_initialism() -> None:
    """The check is all-caps, not capitalised — "Apple" must still be corrected.

    Keying on `word[0].isupper()` instead would have silently stopped correcting every
    sentence-initial and proper noun.
    """
    assert fix_articles("a Apple") == "an Apple"
    assert fix_articles("an Banana") == "a Banana"


def test_both_kinds_of_acronym_are_genuinely_indistinguishable() -> None:
    """The premise for leaving them alone, stated so the decision is not re-litigated.

    "FBI" takes "an" and "NATO" takes "a"; both are capitals starting with a consonant
    letter. Any spelling-based rule gets one of them wrong.
    """
    assert "FBI".isupper() and "NATO".isupper()
    assert "FBI"[0].lower() not in "aeiou"
    assert "NATO"[0].lower() not in "aeiou"
    assert fix_articles("an FBI agent") == "an FBI agent"
    assert fix_articles("a NATO summit") == "a NATO summit"
