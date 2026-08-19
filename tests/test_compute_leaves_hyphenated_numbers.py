"""Inline compute turned a score, a range and a phone number into arithmetic.

`[compute] enabled` is seeded on by `system/firstrun.py` for **every new install**, so this
is the default experience rather than an opt-in risk. When `evaluate` returns a value the
daemon replaces the whole utterance with it — the text the user spoke is discarded, not
adjusted.

An earlier fix stopped it collapsing prose (`"I ran 5 miles over 2 days"` → `"2.5"`) by
refusing anything with letters left after the operator words are consumed. A string of
digits and hyphens has no letters:

    10-15      ->  -5        a range
    2024-2025  ->  -1        a span of years
    9-11       ->  -2
    555-1234   ->  -679      a phone number
    3-1        ->  2         a score
    2-2        ->  0         found in a real corpus

Measured over 1422 real transcripts, compute fired 3 times: two genuine sums and `2-2`,
which is at least as likely to be a score. After this change it fires twice, and both are
arithmetic.

## Why the rule is about the hyphen specifically

Dictated subtraction does not look hyphenated. "seven minus three" becomes `7 - 3`, because
the word substitution leaves the spaces it found, and someone typing an expression writes
`7 - 3` too. So a spaced hyphen still computes and a bare `N-N` does not.

`+`, `*` and `/` are left alone: they do not appear in dates, scores, phone numbers or
version strings, so `2+2*3` still works. And the rule only applies when the hyphen is the
*only* operator — `2+2-3` is unambiguously arithmetic.

## The asymmetry, which is what decides it

A missed computation costs the user typing the answer themselves. A false one silently
replaces what they said with a wrong number, which they may never re-read. The same
reasoning governs the ITN email guard, the self-repair guard and the article fixer.

`2026-08-19` was already rejected, but only by accident: `08` is not a valid Python integer
literal, so `_safe_eval` raised. `2026-8-19` would have evaluated to `1999`. That is pinned
below so the protection is a rule rather than a coincidence.
"""

from __future__ import annotations

import pytest

from yazses.compute.evaluate import evaluate


@pytest.mark.parametrize(
    "text",
    [
        "2-2",          # a score; found in a real corpus
        "3-1",
        "10-15",        # a range
        "2024-2025",    # a span of years
        "9-11",
        "1-2",          # a version
        "555-1234",     # a phone number
        "12.5-0.5",
        "2026-8-19",    # a date without the leading zero that accidentally saved it
    ],
)
def test_a_hyphenated_number_is_not_arithmetic(text: str) -> None:
    assert evaluate(text) is None, f"{text!r} was replaced by a number"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("7 - 3", "4"),
        ("7 minus 3", "4"),
        ("10 - 3 - 2", "5"),
        ("2 plus 2", "4"),
        ("122 times 2", "244"),
        ("15% of 240", "36"),
        ("100/4", "25"),
        ("2+2*3", "8"),
        ("2+2-3", "1"),
        ("what's 15 percent of 240", "36"),
    ],
)
def test_real_arithmetic_still_computes(text: str, expected: str) -> None:
    """The expensive direction to break: a guard that refused everything would pass
    every test above and silently delete the feature."""
    assert evaluate(text) == expected


def test_a_spaced_hyphen_is_still_subtraction() -> None:
    """The discriminator, stated directly: spacing is the whole signal."""
    assert evaluate("7-3") is None
    assert evaluate("7 - 3") == "4"


def test_the_rule_only_applies_when_the_hyphen_is_alone() -> None:
    """`2+2-3` is unambiguously arithmetic — no date or score carries a `+`."""
    assert evaluate("2+2-3") == "1"
    assert evaluate("2*3-1") == "5"


def test_prose_is_still_refused() -> None:
    """The earlier guard this builds on; both are needed and neither subsumes the other."""
    for text in ("I ran 5 miles over 2 days", "chapter 3 minus chapter 1",
                 "we met 2 times in 3 days"):
        assert evaluate(text) is None


def test_the_date_protection_is_a_rule_not_a_python_literal_accident() -> None:
    """`2026-08-19` was refused because `08` is not a valid int literal, which is luck.

    Both spellings must be refused for the same reason now.
    """
    assert evaluate("2026-08-19") is None
    assert evaluate("2026-8-19") is None
