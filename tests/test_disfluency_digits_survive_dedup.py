"""Rule B (2-gram dedup) must never delete a dictated digit.

"my pin is 4 7 4 7" is a PIN, not a stutter. Before this guard the filter reduced it to
"my pin is 4 7", and "9 9 9 9 9 9 9 9" to "9 9", with no log. A 2-gram holding a Unicode
decimal digit or an English digit word (zero..ten) is now left alone.

Digit words in other languages are NOT covered, and non-digit repeats (including
"New York New York" and the Persian "خیلی خوب خیلی خوب") keep their old behaviour; the
golden table below was recorded by running the unguarded function on the base commit.
"""
from __future__ import annotations

import random
from collections import Counter

import pytest

from yazses.stt.filters.disfluency import (
    _dedup_2grams,
    _is_spoken_digit,
    filter_transcript,
)

REPRODUCED = [
    "my pin is 4 7 4 7",
    "9 9 9 9 9 9 9 9",
    "call 5 5 5 5 1 2 1 2",
    "۱ ۲ ۱ ۲",  # Persian digits
    "one two one two",
]


@pytest.mark.parametrize("text", REPRODUCED)
def test_reproduced_inputs_come_out_unchanged(text: str) -> None:
    assert filter_transcript(text).text == text
    assert _dedup_2grams(text) == text


@pytest.mark.parametrize(
    "text",
    [
        "۱ ۲ ۱ ۲",  # Extended Arabic-Indic (Persian)
        "١ ٢ ١ ٢",  # Arabic-Indic
        "१ २ १ २",  # Devanagari
        "１ ２ １ ２",  # fullwidth
        "۴۷ ۴۷ ۴۷ ۴۷",
        "room 4 7 4 7 4 7",
        "call 555, 12 555, 12 now",
        "Seven Eight seven eight",
        "the code is 3 3 3 3 3 3",
    ],
)
def test_digits_survive_in_every_script_and_mixed_context(text: str) -> None:
    assert filter_transcript(text).text == text


def test_digit_predicate() -> None:
    assert _is_spoken_digit("7") and _is_spoken_digit("7,") and _is_spoken_digit("Nine.")
    assert _is_spoken_digit("१") and _is_spoken_digit("１")
    assert not _is_spoken_digit("York") and not _is_spoken_digit("oh")


_DIGIT_WORDS = "zero one two three four five six seven eight nine ten oh".split()
_VOCAB = [*"0123456789", *_DIGIT_WORDS, "um", "uh", "like", "so", "cat", "dog", "go"]


def _digit_tokens(text: str) -> Counter[str]:
    return Counter(t for t in text.split() if _is_spoken_digit(t) or t == "oh")


def test_digit_multiset_is_preserved_by_filter_transcript() -> None:
    rng = random.Random(0)
    for _ in range(2000):
        text = " ".join(rng.choice(_VOCAB) for _ in range(rng.randint(3, 12)))
        out = filter_transcript(text).text
        assert _digit_tokens(out) == _digit_tokens(text), (text, out)


# Recorded from the base commit (a241a77b) before the guard existed.
NON_DIGIT_GOLDEN = {
    "the the cat the the cat sat": "the the cat the the cat sat",
    "New York New York is big": "New York is big",
    "go to go to the store": "go to the store",
    "I want I want a coffee": "I want a coffee",
    "very good very good indeed": "very good indeed",
    "on the on the table": "on the table",
    "hello world hello world": "hello world",
    "red car red car red car": "red car",
    "he said he said that": "he said that",
    "thank you thank you so much": "thank you so much",
    "Yazses Yazses is good good": "Yazses Yazses is good good",
    "so so so so what": "so so what",
    "ha ha ha ha": "ha ha",
    "bye bye bye bye": "bye bye",
    "let us let us go now": "let us go now",
    "in the in the morning": "in the morning",
    "a b a b a b": "a b",
    "fish and fish and chips": "fish and chips",
    "wait wait wait wait": "wait wait",
    "mama mia mama mia": "mama mia",
    "na na na na hey": "na na hey",
    "once upon once upon a time": "once upon a time",
}


@pytest.mark.parametrize(("text", "expected"), list(NON_DIGIT_GOLDEN.items()))
def test_non_digit_repeats_behave_as_on_base(text: str, expected: str) -> None:
    assert filter_transcript(text).text == expected
