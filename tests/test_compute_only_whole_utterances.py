"""Dictating "I ran 5 miles over 2 days" typed "2.5".

`evaluate` is documented as turning **a whole-utterance arithmetic expression** into its
answer. It did not check that. After mapping the operator words it stripped every
character that was not a digit or an operator:

    expr = re.sub(r"[^0-9+\\-*/().% ]", "", t)

so any sentence carrying two numbers and one operator word collapsed to an expression:

    "I ran 5 miles over 2 days"    ->  "2.5"
    "chapter 3 minus chapter 1"    ->  "2"
    "we met 2 times in 3 days"     ->  "6"

Six of eight ordinary sentences. "over" and "times" are common English words, and unlike
the other text transforms this one does not *mangle* the utterance — it **discards** it and
types a number instead.

Anything left after the lead-in words ("what's", "calculate", …) and the operator words
have been consumed means the utterance was prose, and prose is now returned untouched.

`[compute] enabled` is off by default, so this reached whoever turned it on — for whom the
feature is meant to be a convenience, not a way to lose a sentence.
"""

from __future__ import annotations

import pytest

from yazses.compute.evaluate import evaluate

PROSE = [
    "I ran 5 miles over 2 days",
    "chapter 3 minus chapter 1",
    "we met 2 times in 3 days",
    "section 4 over section 2",
    "put 3 items over 2 shelves",
    "he scored 3 times in 2 games",
    "from 9 to 5 plus 1 hour",
    "I have 2 cats and 3 dogs",
    "take the 2 over there",
    "add 3 more times if needed",
]


@pytest.mark.parametrize("text", PROSE)
def test_prose_is_never_replaced_by_a_number(text: str) -> None:
    assert evaluate(text) is None, "an ordinary sentence was discarded for its arithmetic"


@pytest.mark.parametrize(
    "text,answer",
    [
        ("2 plus 2", "4"),
        ("what's 15% of 240", "36"),
        ("what is 15 percent of 240", "36"),
        ("calculate 10 times 4", "40"),
        ("what is 100 divided by 4", "25"),
        ("compute 7 minus 2", "5"),
        ("3 plus 4 times 2", "11"),
        ("100 multiplied by 3", "300"),
    ],
)
def test_a_real_calculation_still_works(text: str, answer: str) -> None:
    """A guard that refused everything would pass every prose test perfectly."""
    assert evaluate(text) == answer


def test_the_two_that_already_worked_still_do() -> None:
    """These were among the eight and were already handled; they must not regress.

    "and" and "to" are not operator words, so the leftover expression never parsed.
    Keeping them pins that the fix did not come from breaking the parse instead.
    """
    assert evaluate("I have 2 cats and 3 dogs") is None
    assert evaluate("from 9 to 5 plus 1 hour") is None


def test_no_digits_or_no_operator_is_still_nothing() -> None:
    assert evaluate("hello world") is None
    assert evaluate("42") is None
    assert evaluate("") is None
    assert evaluate(None) is None


def test_division_by_zero_is_refused_not_raised() -> None:
    """The pre-existing safety: never raise into the dictation path."""
    assert evaluate("10 divided by 0") is None


def test_a_trailing_question_mark_is_fine() -> None:
    """Punctuation is not a letter, so it must not make an expression look like prose."""
    assert evaluate("what's 15% of 240?") == "36"
