"""The tray's input-level ring read full for ordinary speech.

The ring exists because the five badge colours all say what YazSes is *doing* and none says
whether the microphone is hearing anything — which come apart exactly when it matters. A
muted mic, stolen capture, or a gate above your voice all look like green while nothing is
typed.

It mapped the level linearly with full scale at **4× the gate**, and the comment said that
would "compress the tail so ordinary speech fills a useful amount of ring and a shout does
not simply peg". Measured against 1617 real recorded bursts, it did the opposite:

    threshold 0.01  (the default)   ring fully pegged on  44% of bursts
    threshold 0.004                                       81%
    threshold 0.0005                                      97%

A meter that reads full for half of normal speech carries about one bit.

## Why linear cannot work here, at any constant

The ratio is not scale-free across users. A well-calibrated gate sits just under the voice,
putting speech at 2–4×. A gate set too low puts the *same voice* at 40×. Any fixed linear
span is therefore wrong for somebody, which is why raising 4× to some larger number is not
the fix — it just moves which users are broken.

## The scale is conventional, not tuned

Logarithmic, with a 100× (40 dB) span above the gate — the ordinary range of an audio level
meter. Over the same 1617 bursts that is 0% pegged at the default threshold and 0% at 0.004,
and the *spread* of readings stays near-constant (σ ≈ 0.15) at every threshold, which is the
property the linear map lacked.

A gate set 40× below the voice still reads near full, and should: that is a real fault, and
the ring is entitled to show it. That case is the one this machine is actually in.
"""

from __future__ import annotations

import math

import pytest

from yazses.tray.menu import _GATE_AT, _RING_RANGE, level_ring

#: Percentiles of 1617 real recorded burst levels from the learning corpus.
REAL_P10, REAL_MEDIAN, REAL_P90 = 0.0088, 0.0363, 0.0786
DEFAULT_GATE = 0.01


def _ring(level: float, threshold: float = DEFAULT_GATE):
    return level_ring(
        {"state": "recording", "audio_level": level, "vad_threshold": threshold}
    )


@pytest.mark.parametrize("level", [REAL_MEDIAN, REAL_P90, 0.15])
def test_ordinary_speech_does_not_peg_the_ring(level: float) -> None:
    """The defect: 44% of real bursts read full at the default gate."""
    assert _ring(level).fraction < 0.95, (
        f"level {level} pegs the ring at the default gate — the meter is back to one bit"
    )


def test_the_real_speech_range_spreads_across_the_ring() -> None:
    """Not pegging is not enough; the readings have to differ from each other."""
    low = _ring(REAL_P10).fraction
    mid = _ring(REAL_MEDIAN).fraction
    high = _ring(REAL_P90).fraction
    assert low < mid < high
    assert high - low > 0.2, f"p10..p90 spans only {high - low:.2f} of the ring"


def test_a_gate_far_below_the_voice_still_reads_near_full() -> None:
    """A real fault the ring is entitled to show, and the state this machine is in.

    A ring that refused to peg at all would pass the tests above and hide this.
    """
    assert _ring(REAL_MEDIAN, threshold=0.0005).fraction > 0.9


def test_below_the_gate_still_maps_to_the_arc_before_the_notch() -> None:
    """Unchanged behaviour: you can see yourself approaching the gate, not only failing."""
    assert _ring(DEFAULT_GATE / 2).fraction == pytest.approx(_GATE_AT * 0.5, abs=0.01)
    assert _ring(DEFAULT_GATE / 2).above_gate is False


def test_the_gate_is_at_a_fixed_point_on_the_ring() -> None:
    """The load-bearing property: "past the notch" must mean the same on every mic."""
    for threshold in (0.0005, 0.004, 0.01, 0.05):
        just_under = _ring(threshold * 0.999, threshold)
        assert just_under.fraction == pytest.approx(_GATE_AT, abs=0.01)
        assert just_under.above_gate is False
        assert _ring(threshold * 1.001, threshold).above_gate is True


@pytest.mark.parametrize("threshold", [0.0005, 0.004, 0.01, 0.05])
def test_the_scale_behaves_the_same_at_every_threshold(threshold: float) -> None:
    """What linear could not do: a 10x-over-gate voice reads the same everywhere."""
    assert _ring(threshold * 10, threshold).fraction == pytest.approx(
        _GATE_AT + (1 - _GATE_AT) * math.log(10) / math.log(_RING_RANGE), abs=0.01
    )


def test_the_range_is_the_conventional_meter_span() -> None:
    """100x is 40 dB. Pinned so changing it is a decision rather than a nudge."""
    assert _RING_RANGE == 100.0


def test_the_ring_is_hidden_when_not_recording() -> None:
    """An idle badge with a ring implies YazSes is listening when it is not."""
    assert level_ring({"state": "idle", "audio_level": 0.05, "vad_threshold": 0.01}).show is False


def test_a_missing_or_useless_threshold_hides_the_ring() -> None:
    """Without a reference point the notch is meaningless and the ring is decoration."""
    assert level_ring({"state": "recording", "audio_level": 0.05}).show is False
    assert level_ring(
        {"state": "recording", "audio_level": 0.05, "vad_threshold": 0}
    ).show is False


def test_a_shout_pegs_but_only_a_shout() -> None:
    """The tail still ends somewhere; it just is not where ordinary speech lives."""
    assert _ring(DEFAULT_GATE * _RING_RANGE * 2).fraction == pytest.approx(1.0, abs=0.001)
