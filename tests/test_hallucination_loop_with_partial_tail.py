"""A repetition loop that ends mid-phrase is still a repetition loop.

`is_repetition_loop` required the repeated unit to tile the text **exactly**:

    if n % unit != 0:
        continue

Real loops rarely oblige. The decoder stops at a segment or token boundary, so the last
repeat is usually cut short. Taken from a live corpus — this text was **typed into the
user's editor**:

    each machete de shiramasun  ×3  + "each"

Thirteen words. Thirteen is prime, so no unit divides it, and a textbook degenerate loop
scored as ordinary speech and went to the injector.

## How it was found

Not by reading the detector. `yazses transcribe` was run on a real 1.5 s clip pulled from
the corpus and produced **nothing**, while the daemon's stored transcript for the same
audio was that loop. Isolating the difference showed the daemon's pre-speech padding is
what provokes it:

    raw audio                  -> ''
    + 300 ms leading silence   -> 'Each machine they should have us in it.'

So the padding that stops the first word being clipped can also turn near-silence into
fabricated text — and the guard built to catch the result was missing the commonest shape
of it.

## What this does not change

`[hallucination] enabled` is still **false** by default; this only fixes what the guard
detects when it is on. Whether it should default on is a product decision, not a bug fix.

The tail must be a **prefix of the unit** — what an interrupted repeat looks like. A tail
that is anything else means the loop ended and speech resumed, and that text is left
alone: `"the the the cat sat on the mat"` is not dropped.
"""

from __future__ import annotations

import dataclasses

import pytest

from yazses.config import Config
from yazses.postprocess.hallucination import is_repetition_loop, should_drop

#: Verbatim from a real corpus, including the interrupted final repeat.
TYPED_INTO_THE_EDITOR = (
    "each machete de shiramasun each machete de shiramasun "
    "each machete de shiramasun each"
)


@pytest.mark.parametrize(
    "text",
    [
        pytest.param(TYPED_INTO_THE_EDITOR, id="the-real-one"),
        pytest.param("go to the store go to the store go to the store go to", id="tail-2-words"),
        pytest.param("the the the", id="exact-tiling-1-word"),
        pytest.param("um um um um", id="exact-tiling-4x"),
        pytest.param("a b a b a b a", id="tail-1-of-2"),
    ],
)
def test_a_loop_is_caught_whether_or_not_it_ends_cleanly(text: str) -> None:
    assert is_repetition_loop(text), f"missed a degenerate loop: {text!r}"


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("this is a normal sentence that repeats nothing at all", id="prose"),
        pytest.param("very very very good", id="legitimate-emphasis"),
        pytest.param("the the the cat sat on the mat and then slept", id="loop-then-speech"),
        pytest.param("I said hello and then I said hello again to her", id="natural-echo"),
        pytest.param("no", id="too-short"),
        pytest.param("", id="empty"),
    ],
)
def test_real_speech_is_never_dropped(text: str) -> None:
    """A guard that eats real dictation is worse than the hallucination it prevents.

    `very very very good` is the sharp one: three identical words in a row, and a person
    said them.
    """
    assert not is_repetition_loop(text), f"would have deleted real speech: {text!r}"


def test_the_old_rule_is_what_missed_it() -> None:
    """Pin the mechanism, so a revert to exact tiling fails here with the reason.

    Thirteen words, and 13 is prime — no unit could tile it, so every candidate unit was
    skipped before the words were even compared.
    """
    words = TYPED_INTO_THE_EDITOR.split()
    assert len(words) == 13
    assert all(len(words) % unit != 0 for unit in range(2, len(words))), (
        "the sample no longer has a prime word count, so it no longer demonstrates the "
        "exact-tiling failure"
    )


def test_the_guard_stays_off_by_default() -> None:
    """This fixes detection, not policy. Enabling it remains a product decision."""
    assert Config().hallucination.enabled is False
    assert should_drop(TYPED_INTO_THE_EDITOR, Config().hallucination) is False


def test_and_drops_it_once_enabled() -> None:
    enabled = dataclasses.replace(Config().hallucination, enabled=True)
    assert should_drop(TYPED_INTO_THE_EDITOR, enabled) is True


def test_drop_loops_still_switches_it_off() -> None:
    """The toggle must still mean something after the detector got broader."""
    cfg = dataclasses.replace(Config().hallucination, enabled=True, drop_loops=False)
    assert should_drop(TYPED_INTO_THE_EDITOR, cfg) is False
