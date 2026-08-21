"""A suggested threshold that would still discard the bursts is not a suggestion.

`AdaptiveThreshold.suggest` promises *"a threshold that would have let the rejected bursts
through, or ``None``"*. It computed ``max(loudest * safety_factor, min_threshold)`` and
returned it whenever it was below the current gate — without checking the floor had not
raised it back above the audio it was meant to rescue.

With a muted or dead microphone the bursts sit at the digital noise floor. Levels around
0.00002 against ``MIN_THRESHOLD = 0.0005`` proposed **0.0005** — twenty-five times above
the audio it claimed to admit. Those bursts would still be discarded at the new gate.

So the change bought nothing and cost something: a lower silence gate admits more room
noise, and near-silence into the model is answered with invented text. Measured on a real
corpus in an earlier pass — 300 ms of leading silence turned a clip that decoded to
nothing into *"Each machine they should have us in it."*

This is precisely the case the class is careful about everywhere else. `suggest`'s own
docstring says a caller *"must never treat a suggestion as mandatory, because the same
symptom is produced by a muted or dead microphone, where lowering the gate fixes nothing
and only makes the next failure noisier"* — and then the floor let that case through as a
suggestion anyway.
"""

from __future__ import annotations

import pytest

from yazses.audio.adaptive_vad import (
    DEFAULT_MIN_DISCARDS,
    MIN_THRESHOLD,
    SAFETY_FACTOR,
    AdaptiveThreshold,
)

CURRENT = 0.0024  # a real threshold from the machine this feature was written on


def _suggest(levels, current: float = CURRENT):
    a = AdaptiveThreshold()
    for level in levels:
        a.observe_discard(level)
    return a.suggest(current)


def test_the_noise_floor_case_gets_no_suggestion() -> None:
    """A muted mic: the floor would raise the proposal above the audio it rescues."""
    assert _suggest([0.00001, 0.00002, 0.000015]) is None


def test_real_quiet_speech_still_gets_one() -> None:
    """A guard that refused everything would pass the test above and break the feature."""
    proposed = _suggest([0.0018, 0.0020, 0.0019])
    assert proposed is not None
    assert proposed < CURRENT, "it must actually lower the gate"
    assert proposed <= 0.0020, "and let the loudest rejected burst through"


@pytest.mark.parametrize(
    "levels",
    [
        pytest.param([0.0018, 0.0020, 0.0019], id="clearly-speech"),
        pytest.param([0.0009, 0.0010, 0.0009], id="just-above-the-floor"),
        pytest.param([0.0005, 0.0006, 0.0005], id="right-at-the-floor"),
    ],
)
def test_any_suggestion_admits_the_loudest_rejected_burst(levels) -> None:
    """The documented contract, asserted as a property rather than case by case.

    `is_silent` is ``mean < threshold``, so a burst at level L passes when
    ``L >= threshold``. A suggestion above the loudest discard cannot help.
    """
    proposed = _suggest(levels)
    if proposed is None:
        return
    assert proposed <= max(levels), (
        f"suggested {proposed} for bursts topping out at {max(levels)} — they would "
        "still be discarded"
    )


def test_bursts_above_the_gate_are_still_refused() -> None:
    """The pre-existing guard: the gate is not why those were dropped."""
    assert _suggest([0.05, 0.06, 0.055]) is None


def test_too_few_discards_is_still_refused() -> None:
    assert _suggest([0.0018] * (DEFAULT_MIN_DISCARDS - 1)) is None


def test_a_success_still_clears_the_streak() -> None:
    a = AdaptiveThreshold()
    a.observe_discard(0.0018)
    a.observe_discard(0.0020)
    a.observe_speech(0.02)
    a.observe_discard(0.0019)
    assert a.streak == 1
    assert a.suggest(CURRENT) is None


def test_the_floor_is_what_makes_this_reachable() -> None:
    """Pin the mechanism, so the constants moving is not silently a behaviour change."""
    assert MIN_THRESHOLD > 0, "with no floor the clamp could never raise the proposal"
    assert 0 < SAFETY_FACTOR <= 1, "a factor above 1 would raise every proposal"
    tiny = MIN_THRESHOLD / 10
    assert tiny * SAFETY_FACTOR < MIN_THRESHOLD, (
        "the floor no longer bites at these levels — this test proves nothing"
    )
    assert _suggest([tiny, tiny, tiny]) is None
