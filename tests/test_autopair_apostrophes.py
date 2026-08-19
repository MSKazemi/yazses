"""Dictating "it's fine" appended a stray apostrophe.

`balance_delimiters` tracked `'` in the same stack as brackets, so every apostrophe read
as an *opening single quote* and got a closer appended:

    "it's fine"            ->  "it's fine'"
    "the user's file"      ->  "the user's file'"
    "I can't see O'Brien"  ->  unchanged, because the two happened to pair up

That last one is the worst of the three: the behaviour depends on whether the utterance
contains an **odd or even** number of contractions, so it is unpredictable rather than
consistently wrong — and contractions are among the commonest words in English.

`autopair` is wired into the dictation path (`core/daemon.py`) and off by default, so this
reached anyone who turned it on, on most sentences they spoke.

## The rule

A quotation never opens directly after a letter or digit — there is a space or a line
start first — while an apostrophe always follows one ("it's", "users'", "1990's"). Closing
is not decided by position: once a `'` has opened, the next one closes it, so
`he said 'hi'` still balances.

Only `'` is ambiguous. `"` and `` ` `` are unaffected, and so are all three bracket pairs.
"""

from __future__ import annotations

import pytest

from yazses.autopair.balance import _opens_a_quote, balance_delimiters

PROSE = [
    "it's fine",
    "don't do that",
    "the user's file",
    "I can't see O'Brien",
    "the users' files",
    "in the 1990's",
    "it's the user's, isn't it",
]


@pytest.mark.parametrize("text", PROSE)
def test_an_apostrophe_never_grows_a_closer(text: str) -> None:
    assert balance_delimiters(text) == text, "a stray apostrophe was appended"


def test_the_odd_even_shape_is_gone() -> None:
    """One contraction and two must behave the same; they did not.

    The old code appended a closer for an odd count and none for an even one, which is
    why this looked intermittent rather than broken.
    """
    assert balance_delimiters("it's") == "it's"
    assert balance_delimiters("it's the user's") == "it's the user's"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("he said 'hi", "he said 'hi'"),
        ("he said 'hi'", "he said 'hi'"),
        ("'quoted", "'quoted'"),
        ('say "hello', 'say "hello"'),
        ("run `cmd", "run `cmd`"),
    ],
)
def test_real_quoting_still_balances(text: str, expected: str) -> None:
    """A fix that stopped tracking `'` entirely would fail these."""
    assert balance_delimiters(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("foo(bar", "foo(bar)"),
        ("a[b{c", "a[b{c}]"),
        ('f("x"', 'f("x")'),
        ("all closed (ok)", "all closed (ok)"),
        ("", ""),
    ],
)
def test_brackets_are_unaffected(text: str, expected: str) -> None:
    assert balance_delimiters(text) == expected


def test_the_predicate_only_second_guesses_the_apostrophe() -> None:
    """`"` and backtick are never ambiguous and must not be touched by the rule."""
    assert _opens_a_quote('say "x', 4) is True
    assert _opens_a_quote("run `x", 4) is True
    # An apostrophe after a letter or digit is not opening anything.
    assert _opens_a_quote("it's", 2) is False
    assert _opens_a_quote("1990's", 4) is False
    # After a space, or at the very start, it is.
    assert _opens_a_quote("said 'hi", 5) is True
    assert _opens_a_quote("'hi", 0) is True


def test_a_quote_inside_brackets_still_closes_in_order() -> None:
    """The nesting the stack exists for, which the fix must not disturb."""
    assert balance_delimiters('f("x') == 'f("x")'
    assert balance_delimiters("f('x") == "f('x')"
