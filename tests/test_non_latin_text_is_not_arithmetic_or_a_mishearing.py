"""Persian (and any non-Latin) prose must not be eaten by two English-shaped guards.

Both defects were found by running the real functions on Persian sentences:

* ``compute`` is seeded on and REPLACES the whole utterance with its answer. Its prose
  guard asked for an ASCII letter (``[a-z]``), so a Persian sentence with two numbers and a
  hyphen looked like pure arithmetic and "سال 1403 - 1404" was typed as ``-1``.
* ``corrdict`` compared "shapes" made of ``[a-z0-9]``. Every Persian word reduced to the
  empty string, every pair scored 1.0, and a plain rewording was mined as a mishearing.
"""

from __future__ import annotations

import pytest

from yazses.compute.evaluate import evaluate
from yazses.corrdict.mine import pairs_from_texts, similarity


@pytest.mark.parametrize(
    "sentence",
    [
        "تخفیف 15% است",
        "فصل 3 - فصل 1",
        "سال 1403 - 1404",
        "Привет 3 - 1 пока",
        "第 3 章 - 第 1 章",
    ],
)
def test_non_latin_prose_with_numbers_is_left_alone(sentence: str) -> None:
    assert evaluate(sentence) is None


@pytest.mark.parametrize(
    ("spoken", "answer"),
    [("15% of 240", "36"), ("what is 3 - 1", "2"), ("2 + 2", "4")],
)
def test_real_arithmetic_still_computes(spoken: str, answer: str) -> None:
    assert evaluate(spoken) == answer


def test_a_persian_rewording_is_not_a_mishearing() -> None:
    assert similarity("ارسال", "بفرست") < 0.6
    assert pairs_from_texts("لطفا ارسال کن", "لطفا بفرست کن") == []


def test_identical_persian_words_are_still_identical() -> None:
    assert similarity("کتاب", "کتاب") == 1.0


def test_english_pairs_keep_their_scores() -> None:
    assert round(similarity("yaz says", "YazSes"), 2) == 0.77
    assert similarity("send", "forward") < 0.6
