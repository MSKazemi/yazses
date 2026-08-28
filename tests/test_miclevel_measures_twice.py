"""`mic-level` now measures the room and the voice, and puts the gate between them.

The defect this closes is written up in `test_miclevel_cannot_hear_whether_you_spoke.py`,
which ends with a section headed *"Not done here"*. This is that work.

## Why one recording could never be enough

`analyze` recommends `mean(|audio|) x _HEADROOM` and has no way to know the clip was
speech. Recording an empty room four times on the author's laptop:

    mean level:            0.0036 / 0.0044 / 0.0048 / 0.0050
    recommended:           0.002  / 0.0022 / 0.0024 / 0.0025

Every recommendation is *below* the room noise that produced it. And the obvious rescue --
classify the single clip acoustically -- is disproved and stays disproved: the peak-to-mean
populations of speech and no-text clips overlap, with the no-text p90 *above* the speech
p90. So a second measurement is not a refinement; it supplies the one missing fact, which
is which of the two recordings was the room.

## The separation constant is derived, not chosen

The gate must sit at least `_AMBIENT_MARGIN` above the room and at most `_HEADROOM` of the
voice. Those bounds cross when the two recordings are too close, and the crossing IS the
refusal. `MIN_SEPARATION` is `_AMBIENT_MARGIN / _HEADROOM`, so it moves when either margin
moves — there is no third number to tune, and no way to make an empty room calibrate by
nudging one.

## Measured, so the 3.0x requirement is not a guess

Read off this project's own 1646-event learning corpus (`level` is stored in the clear and
is exactly `mean(|padded|)`, the value the VAD compares — `core/daemon.py:1261`):

    produced text (speech)   n=1396  p05 0.01382  median 0.03938  p95 0.08939
    cleared gate, no text    n= 189  p05 0.00290  median 0.00692  p95 0.01401

A 5.7x separation between the medians, against the 3.0x this needs. The independent check
that this is the right population: the no-text p10-p25 is 0.0039-0.0054, and the four
directly-measured empty-room readings above are 0.0036-0.0050. Two unrelated measurements
of the same room agree.

The populations still overlap at the tails (speech p05 0.01382 vs no-text p95 0.01401),
which is the same negative result as before and the reason this is a *two-recording*
design rather than a cleverer one-recording one.
"""

from __future__ import annotations

import numpy as np
import pytest

from yazses.system.miclevel import (
    _AMBIENT_MARGIN,
    _HEADROOM,
    _MIN_THRESHOLD,
    MIN_SEPARATION,
    analyze,
    calibrate,
)

#: `mean(|audio|)` percentiles from the 1646-event corpus described in the module
#: docstring. These are the populations the 3.0x requirement is judged against.
CORPUS_SPEECH = (0.01382, 0.03938, 0.08939)      # p05, median, p95 over 1396 clips
CORPUS_NO_TEXT = (0.00290, 0.00692, 0.01401)     # p05, median, p95 over 189 clips

#: Four direct readings of an empty room on the author's laptop.
EMPTY_ROOM_READINGS = (0.0036, 0.0044, 0.0048, 0.0050)


def _sample(mean: float, n: int = 16000) -> np.ndarray:
    return np.full(n, mean, dtype=np.float32)


def _stats(mean: float):
    return analyze(_sample(mean), 16000)


# --------------------------------------------------------------------------- the refusal


@pytest.mark.parametrize("room", EMPTY_ROOM_READINGS)
def test_an_empty_room_cannot_produce_a_recommendation(room: float) -> None:
    """The headline case: nobody spoke, so both recordings are the room.

    Every one of these four readings previously yielded a confident "recommended" below
    its own room noise.
    """
    result = calibrate(_stats(room), _stats(room))
    assert result.ok is False
    assert "apart" in result.reason


@pytest.mark.parametrize("room", EMPTY_ROOM_READINGS)
def test_an_empty_room_refuses_however_the_margins_move(room: float) -> None:
    """The refusal is structural, not a tuned threshold.

    Both recordings are the same number, so the separation is exactly 1.0. That is below
    `MIN_SEPARATION` for any margins where the gate must sit above the room and below the
    voice — i.e. wherever `_AMBIENT_MARGIN > _HEADROOM`, which is what those names mean.
    """
    assert _AMBIENT_MARGIN > _HEADROOM, (
        "the margins have crossed: the gate is now allowed below the room it must reject"
    )
    assert calibrate(_stats(room), _stats(room)).separation == pytest.approx(1.0)
    assert MIN_SEPARATION > 1.0


def test_a_silent_second_recording_says_so_rather_than_blaming_separation() -> None:
    """A dead mic and a quiet user are different problems with different fixes."""
    result = calibrate(_stats(0.004), _stats(0.0005))
    assert result.ok is False
    assert "silent" in result.reason


def test_a_refusal_still_carries_the_floor_not_a_wrong_number() -> None:
    """A caller that ignores `ok` must write a constant, never a bad measurement."""
    result = calibrate(_stats(0.004), _stats(0.0045))
    assert result.ok is False
    assert result.recommended_threshold == _MIN_THRESHOLD


# ------------------------------------------------------------------- the accepted case


def test_the_real_corpus_medians_calibrate() -> None:
    """The populations this is meant to serve are comfortably separable."""
    room_med, voice_med = CORPUS_NO_TEXT[1], CORPUS_SPEECH[1]
    result = calibrate(_stats(room_med), _stats(voice_med))
    assert result.ok is True
    assert result.separation > MIN_SEPARATION


def test_the_gate_lands_above_the_room_and_below_the_voice() -> None:
    """The property the whole command exists for, stated directly."""
    room, voice = 0.0046, 0.0394
    result = calibrate(_stats(room), _stats(voice))
    assert result.ok is True
    assert result.recommended_threshold > room, (
        "a gate at or below the room is cleared by the room, which is the failure being fixed"
    )
    assert result.recommended_threshold < voice


def test_the_gate_stays_inside_its_own_band() -> None:
    """The band bounds are the contract; the midpoint is only how it picks within them."""
    result = calibrate(_stats(0.0046), _stats(0.0394))
    lo, hi = result.band
    assert lo <= result.recommended_threshold <= hi
    assert lo == pytest.approx(0.0046 * _AMBIENT_MARGIN, abs=1e-4)
    assert hi == pytest.approx(0.0394 * _HEADROOM, abs=1e-4)


def test_two_phase_is_never_more_permissive_than_the_old_one_clip_answer() -> None:
    """The old answer was the top of the band; the new one cannot exceed it.

    This matters because a HIGHER gate drops words. The change is allowed to make the
    gate more conservative, never less.
    """
    voice = 0.0394
    result = calibrate(_stats(0.0046), _stats(voice))
    assert result.recommended_threshold <= _stats(voice).recommended_threshold


def test_a_silent_room_falls_back_to_the_floor_rather_than_zero() -> None:
    """A perfect room measures 0.0; the geometric mean is then 0 and must not be used."""
    result = calibrate(_stats(0.0), _stats(0.0394))
    assert result.ok is True
    assert result.separation == float("inf")
    assert result.recommended_threshold >= _MIN_THRESHOLD


@pytest.mark.parametrize("voice", [0.0394, 0.0894])
def test_a_typical_room_calibrates_across_the_bulk_of_real_speech(voice: float) -> None:
    """Median and p95 of real speech against the median real room.

    A guard that only passed at one point would be inert on the users it is for, so the
    range is exercised rather than a single figure.
    """
    result = calibrate(_stats(CORPUS_NO_TEXT[1]), _stats(voice))
    assert result.ok is True, result.reason


def test_a_quiet_voice_calibrates_when_the_room_is_also_quiet() -> None:
    """p05 speech is servable — it needs a p05 room, which is the honest requirement."""
    result = calibrate(_stats(CORPUS_NO_TEXT[0]), _stats(CORPUS_SPEECH[0]))
    assert result.ok is True, result.reason


def test_a_quiet_voice_in_a_typical_room_is_refused_because_no_gate_exists() -> None:
    """The boundary case, and the reason it is a REFUSAL rather than a loose constant.

    p05 speech (0.01382) in a median room (0.00692) is 2.0x apart. It is tempting to read
    the refusal as the requirement being too strict and to lower `_AMBIENT_MARGIN` until
    it passes. That would be wrong, and the arithmetic below is why: at this separation
    every candidate gate is either at the room level — where the room clears it, the
    failure this whole module exists to prevent — or at the voice level, where it discards
    the voice. There is no third place to put it.

    The user's problem here is the microphone or the room, not the threshold, and the CLI
    says exactly that. Answering with a number would be answering the wrong question.
    """
    room, voice = CORPUS_NO_TEXT[1], CORPUS_SPEECH[0]
    result = calibrate(_stats(room), _stats(voice))
    assert result.ok is False
    assert result.separation == pytest.approx(2.0, abs=0.05)

    lo, hi = result.band
    assert hi < lo, "the band is empty — that emptiness IS the refusal"
    # Loosening the margin does not rescue this; it only moves the gate onto the voice.
    assert lo / voice >= 0.75, (
        "a gate admissible here would sit at three quarters of the speaker's own level "
        "and would discard most of their speech"
    )


# -------------------------------------------------------------- the constant is derived


def test_min_separation_is_derived_from_the_two_margins() -> None:
    """Not a third tunable. Changing either margin moves it, and this proves it does."""
    assert MIN_SEPARATION == pytest.approx(_AMBIENT_MARGIN / _HEADROOM)
    assert MIN_SEPARATION == pytest.approx(3.0), (
        "the requirement moved — re-check it against the corpus figures in this module's "
        "docstring (measured separation between the population medians is 5.7x)"
    )


def test_the_corpus_populations_are_far_enough_apart_to_justify_the_requirement() -> None:
    """The evidence, as arithmetic, so a future change to the margins is checked here.

    If someone raises `_AMBIENT_MARGIN` until `MIN_SEPARATION` exceeds the separation the
    real corpus shows, ordinary users stop being able to calibrate. That is the failure
    this asserts against.
    """
    measured = CORPUS_SPEECH[1] / CORPUS_NO_TEXT[1]
    assert measured == pytest.approx(5.7, abs=0.1)
    assert MIN_SEPARATION < measured, (
        f"the requirement ({MIN_SEPARATION:.1f}x) now exceeds what real speech and real "
        f"room noise are actually separated by ({measured:.1f}x) — real users would be "
        f"refused"
    )


def test_the_tails_still_overlap_which_is_why_two_recordings_are_needed() -> None:
    """The negative result carried forward: no single-clip cutoff exists."""
    assert CORPUS_NO_TEXT[2] > CORPUS_SPEECH[0], (
        "the populations have separated — if that is real, a one-recording cutoff became "
        "possible and this design should be revisited"
    )


def test_the_empty_room_readings_agree_with_the_corpus_no_text_population() -> None:
    """Two independent measurements of the same thing, used as a cross-check."""
    assert CORPUS_NO_TEXT[0] < min(EMPTY_ROOM_READINGS)
    assert max(EMPTY_ROOM_READINGS) < CORPUS_NO_TEXT[2]
