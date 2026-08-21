"""`fat arrow` was dictated as `fat ->` because a shorter phrase was substituted first.

`spoken_symbols` walks a list of spoken-phrase → punctuation pairs and substitutes each in
turn. The comment above that list says *"Longest phrases first so 'open paren' beats
'paren'"* — but the list is grouped by meaning, not sorted, and `("arrow", "->")` was
written above `("fat arrow", "=>")`. So `\\barrow\\b` matched inside "fat arrow" first:

    "fat arrow"      ->  "fat ->"        wanted "=>"
    "a fat arrow b"  ->  "a fat -> b"    wanted "a => b"

Every other pair happened to be in a safe order, which is what made this survive: the rule
was stated, mostly held, and enforced by nothing.

## Why the fix is a derived order rather than moving one line

Swapping those two entries fixes today's list and leaves the next contributor to rediscover
the rule. A word-bounded phrase can only ever be shadowed by a *longer* phrase, so
longest-first is correct by construction — `_ORDERED` sorts the authored list, the authored
list stays grouped for reading, and a new phrase added in the wrong place cannot reintroduce
the bug.

`test_no_phrase_shadows_a_later_one` is the real guard here: it is a property over the
whole table, so it fails on a bad *addition*, not only on today's known pair.

`code` is in `features._UNWIRED` — nothing calls this yet, so it reaches whoever wires it
rather than a user today. That is the reason to fix it now: they would inherit it.
"""

from __future__ import annotations

import re

import pytest

from yazses.code.spoken import _ORDERED, _SYMBOLS, spoken_symbols


@pytest.mark.parametrize(
    "spoken,expected",
    [
        ("fat arrow", "=>"),
        ("a fat arrow b", "a => b"),
        ("x fat arrow y fat arrow z", "x => y => z"),
    ],
)
def test_the_longer_phrase_wins(spoken: str, expected: str) -> None:
    assert spoken_symbols(spoken) == expected


@pytest.mark.parametrize(
    "spoken,expected",
    [
        ("a arrow b", "a -> b"),
        ("a less than or equal b", "a <= b"),
        ("a less than b", "a < b"),
        ("a greater than or equal b", "a >= b"),
        ("a double equals b", "a == b"),
        ("a not equals b", "a != b"),
        ("a equals b", "a = b"),
        ("x equals open paren a plus b close paren", "x = ( a + b )"),
    ],
)
def test_the_pairs_that_were_already_ordered_correctly(spoken: str, expected: str) -> None:
    """A sort that broke any of these would pass the tests above and still be wrong."""
    assert spoken_symbols(spoken) == expected


def test_no_phrase_shadows_a_later_one() -> None:
    """The property, so a phrase added in the wrong place fails here rather than in dictation.

    This is what the module comment always claimed and never enforced.
    """
    shadowed = [
        (a, b)
        for i, (a, _) in enumerate(_ORDERED)
        for j, (b, _) in enumerate(_ORDERED)
        if j > i and re.search(rf"\b{re.escape(a)}\b", b)
    ]
    assert not shadowed, (
        f"these phrases are substituted before a longer phrase that contains them, so the "
        f"longer one can never match: {shadowed}"
    )


def test_the_order_is_derived_not_authored() -> None:
    """The authored list stays grouped by meaning; only the substitution order is sorted.

    Pinned because the temptation is to "just sort `_SYMBOLS` in place", which makes the
    table unreadable and loses the grouping that explains it.
    """
    assert set(_ORDERED) == set(_SYMBOLS)
    assert len(_ORDERED) == len(_SYMBOLS)
    lengths = [len(p) for p, _ in _ORDERED]
    assert lengths == sorted(lengths, reverse=True)


def test_ordinary_dictation_is_untouched() -> None:
    """The whole module is code-mode only for this reason; the fix must not widen it."""
    assert spoken_symbols("just talking normally") == "just talking normally"
    assert spoken_symbols("") == ""


def test_case_insensitivity_survives_the_reorder() -> None:
    assert spoken_symbols("Fat Arrow") == "=>"
    assert spoken_symbols("Open Brace") == "{"
