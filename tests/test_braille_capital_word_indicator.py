"""An all-caps word and a Title-Case word produced identical braille.

`_encode_word` emitted one capital indicator whenever the first letter was upper case:

    prefix = _CAPITAL if word[:1].isupper() else ""

In UEB a single ``⠠`` capitalises **only the letter after it**. A word in capitals takes
the *capitals word indicator*, ``⠠⠠``. So:

    "ABC"  ->  ⠠⠁⠃⠉
    "Abc"  ->  ⠠⠁⠃⠉      identical

A reader gets "Abc" either way, on a refreshable display or an embossed page, with no way
to tell which was written. Acronyms are common in dictated text — "API", "NASA", "PDF" —
and this is output that nobody sighted proofreads, which is exactly why it stayed wrong.

Checked against the standard rather than against the code: single capital letter → one
indicator, capitalised word → two. "I" and "A" are one letter and correctly keep the
single form, because `"I".isupper()` is True but the word is not *a word in capitals*.

## Not fixed here

A mixed-case word ("McDonald", "iPhone") still gets one leading indicator. UEB would mark
each capital individually (``⠠⠍⠉⠠⠙…``), which needs per-letter handling rather than a
prefix. That is a separate change with a much larger blast radius, and unlike the all-caps
case it is not silently *ambiguous* — it is visibly under-marked. Recorded rather than
half-done.
"""

from __future__ import annotations

import pytest

from yazses.brailleout.ueb import to_braille

CAP = "⠠"  # ⠠ dot-6, the capital indicator


@pytest.mark.parametrize(
    "word,expected",
    [
        ("ABC", "⠠⠠⠁⠃⠉"),
        ("abc", "⠁⠃⠉"),
        ("Abc", "⠠⠁⠃⠉"),
    ],
)
def test_the_three_cases_are_distinct(word: str, expected: str) -> None:
    assert to_braille(word) == expected


def test_all_caps_and_title_case_no_longer_collide() -> None:
    """The defect, stated as the thing a reader could not distinguish."""
    assert to_braille("ABC") != to_braille("Abc"), (
        "an acronym and a Title-Case word still produce the same cells"
    )


@pytest.mark.parametrize("word", ["I", "A"])
def test_a_one_letter_capital_keeps_the_single_indicator(word: str) -> None:
    """`"I".isupper()` is True, but "I" is not a word *in capitals*."""
    out = to_braille(word)
    assert out.startswith(CAP)
    assert not out.startswith(CAP * 2), f"{word!r} took the capitals-word indicator"


@pytest.mark.parametrize("word", ["NASA", "PDF", "API"])
def test_real_acronyms_are_marked_as_capitalised_words(word: str) -> None:
    assert to_braille(word).startswith(CAP * 2), word


def test_lower_case_is_untouched() -> None:
    """A fix that prefixed everything would pass most of the tests above."""
    assert not to_braille("hello world").startswith(CAP)
    assert CAP not in to_braille("hello world")


def test_the_surrounding_text_still_translates() -> None:
    """Digits, punctuation, spacing and contractions must be unaffected."""
    out = to_braille("Item 3: DONE")
    assert "⠼" in out, "the number indicator is gone"
    assert "⠒" in out, "the colon is gone"
    assert out.count(" ") == 2


def test_grade_one_gets_the_indicator_too() -> None:
    """Capitalisation is not a contraction; it applies at both grades."""
    assert to_braille("ABC", grade=1).startswith(CAP * 2)
    assert to_braille("Abc", grade=1).startswith(CAP)


def test_a_capitalised_wordsign_still_contracts() -> None:
    """"THE" is both a wordsign and a capitalised word; it must be both."""
    out = to_braille("THE")
    assert out.startswith(CAP * 2)
    assert out.endswith("⠮"), f"the wordsign for 'the' was lost: {out!r}"
