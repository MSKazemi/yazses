"""The four check-digit schemes, characterised by what they are *defined* to catch.

`test_checkdigit_guard.py` covers the guard's behaviour — when it holds a number,
what it suggests, what it says. It validates one Luhn card. That leaves the
arithmetic itself checked by a single example, and these are interop formats: a
wrong table entry produces a validator that agrees with the real one on almost
every input and disagrees on the ones that matter.

Verhoeff is the reason this file exists. Its whole justification over Luhn is that
it detects **all** adjacent transpositions, and it gets that from three lookup
tables (a dihedral-group multiplication table, a permutation table, an inverse
table). Mistype one cell and it still validates its own output, still passes any
example-based test, and quietly stops catching a subset of errors — which is the
only property anyone chose it for.

So each scheme is pinned to its published error-detection profile, exactly: not
"catches a lot", but which classes it catches and which single class it does not.
That makes the tests fail for a weaker implementation *and* for a stronger one,
which is correct — a "better Luhn" is not Luhn, and these numbers are exchanged
with other systems.
"""
from __future__ import annotations

import random

import pytest

from yazses.checkdigit.validate import validate

# Published examples, none of them produced by this code.
KNOWN_GOOD = [
    ("4242424242424242", "luhn"),      # Stripe's test card
    ("79927398713", "luhn"),           # Luhn's Wikipedia worked example
    ("9780306406157", "isbn13"),       # ISBN-13 Wikipedia example
    ("0306406152", "isbn10"),          # the same book as ISBN-10
    ("2363", "verhoeff"),              # Verhoeff Wikipedia example
]
KNOWN_BAD = [
    ("4242424242424243", "luhn"),
    ("9780306406158", "isbn13"),
    ("030640615X", "isbn10"),
    ("2364", "verhoeff"),
]

LENGTHS = {"luhn": 16, "isbn13": 13, "isbn10": 10, "verhoeff": 8}


@pytest.mark.parametrize("digits, scheme", KNOWN_GOOD, ids=[s for _, s in KNOWN_GOOD])
def test_published_examples_validate(digits, scheme):
    assert validate(digits, scheme)[0] is True


@pytest.mark.parametrize("digits, scheme", KNOWN_BAD, ids=[s for _, s in KNOWN_BAD])
def test_published_examples_with_a_broken_check_digit_fail(digits, scheme):
    assert validate(digits, scheme)[0] is False


def _valid_numbers(scheme: str, count: int = 40) -> list[str]:
    """Real valid numbers, found by trying check digits — no generator to trust.

    Seeded: a failure here must be reproducible rather than appear once in CI.
    """
    rng = random.Random(7)
    length = LENGTHS[scheme]
    out: list[str] = []
    while len(out) < count:
        body = "".join(str(rng.randrange(10)) for _ in range(length - 1))
        for d in "0123456789X":
            if validate(body + d, scheme)[0]:
                out.append(body + d)
                break
    return out


@pytest.mark.parametrize("scheme", sorted(LENGTHS))
def test_every_scheme_catches_every_single_digit_error(scheme):
    """The property all four share, and the one a user is most likely to make."""
    missed = []
    for num in _valid_numbers(scheme):
        for i, ch in enumerate(num):
            if not ch.isdigit():
                continue
            for d in "0123456789":
                if d != ch and validate(num[:i] + d + num[i + 1:], scheme)[0]:
                    missed.append((num, i, ch, d))
    assert not missed, f"{scheme} accepted {len(missed)} single-digit errors, e.g. {missed[:3]}"


def _undetected_transposition_pairs(scheme: str) -> set[str]:
    pairs = set()
    for num in _valid_numbers(scheme):
        for i in range(len(num) - 1):
            a, b = num[i], num[i + 1]
            if a == b or not (a.isdigit() and b.isdigit()):
                continue
            if validate(num[:i] + b + a + num[i + 2:], scheme)[0]:
                pairs.add("".join(sorted((a, b))))
    return pairs


def test_verhoeff_catches_every_adjacent_transposition():
    """Its entire reason for existing, and what a mistyped table entry destroys."""
    assert _undetected_transposition_pairs("verhoeff") == set()


def test_isbn10_catches_every_adjacent_transposition():
    """The mod-11 weighting buys this; ISBN-13's mod-10 does not."""
    assert _undetected_transposition_pairs("isbn10") == set()


def test_luhn_misses_exactly_the_09_transposition_and_no_other():
    """Luhn's one documented blind spot. Pinned in both directions.

    Missing more would mean the doubling or the digit-sum is wrong. Missing fewer
    would mean this is not Luhn — and these numbers are handed to payment systems
    that implement the real one.
    """
    assert _undetected_transposition_pairs("luhn") == {"09"}


def test_isbn13_misses_exactly_the_pairs_differing_by_five():
    """EAN-13's known weakness: alternating 1,3 weights collapse a difference of 5."""
    assert _undetected_transposition_pairs("isbn13") == {"05", "16", "27", "38", "49"}


def test_an_unknown_scheme_is_an_error_not_a_silent_pass():
    """A typo'd scheme name must never read as "this number is fine"."""
    with pytest.raises(ValueError):
        validate("4242424242424242", "lhun")
