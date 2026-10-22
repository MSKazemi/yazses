"""Acoustic Context Profiles (ADR-v2-039, amended): the quiet/noisy classifier and its gate.

The property that matters is the negative one (AGENTS.md rule 9): the profile must never be able
to take away speech. The first version of this feature recommended absolute gates of 0.010-0.035,
which sit 6-10x above the real level of the owner's microphone (mean |x| of 0.003-0.005 at full
gain) and would have discarded every utterance. So these tests never assert a *level*; they assert
ratios, and they sweep the owner's real microphone range to show the gate cannot leave
``[configured, 1.5 x configured]`` and cannot touch a burst with speech-like dynamics.

Everything here is pure: lists of frame levels, no audio, no daemon.
"""
from __future__ import annotations

import itertools
import math

import pytest

from yazses.acoustic import profiles, scene
from yazses.acoustic.profiles import SCENES, policy_for, should_switch
from yazses.acoustic.scene import (
    MIN_FRAMES,
    SPEECH_SPREAD,
    FloorEstimate,
    SceneTracker,
    classify_scene,
    effective_gate,
    floor_estimate,
)

#: The owner's microphone: speech mean |x| lands in this band at full gain.
REAL_SPEECH_MEAN = (0.003, 0.005)


def _flat(level: float, n: int = 50) -> list[float]:
    """Stationary room noise as 20 ms frame levels: a few percent of wobble, nothing more."""
    return [level * (1.0 + 0.08 * math.sin(i * 1.7)) for i in range(n)]


def _speech(pause: float, word: float, n: int = 50) -> list[float]:
    """Frames alternating a word and a pause: 60 % word frames, 40 % pause frames."""
    return [word * (1.0 + 0.3 * math.sin(i)) if i % 5 < 3 else pause for i in range(n)]


def _mean(levels: list[float]) -> float:
    return sum(levels) / len(levels)


# ---- floor estimate ----------------------------------------------------------------------

def test_floor_is_the_mean_of_the_quietest_fifth() -> None:
    levels = [0.001] * 10 + [0.01] * 40
    est = floor_estimate(levels)
    assert est is not None
    assert est.floor == pytest.approx(0.001)
    assert est.loud == pytest.approx(0.01)
    assert est.frames == 50
    assert est.spread == pytest.approx(10.0)


def test_too_few_frames_is_no_estimate_not_a_guess() -> None:
    assert floor_estimate([0.01] * (MIN_FRAMES - 1)) is None
    assert floor_estimate([]) is None
    assert floor_estimate([0.01] * MIN_FRAMES) is not None


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.1])
def test_a_corrupt_frame_level_is_no_estimate(bad: float) -> None:
    assert floor_estimate([0.01] * 20 + [bad]) is None


def test_digital_silence_has_an_infinite_spread_and_so_is_never_raised() -> None:
    est = floor_estimate([0.0] * 30)
    assert est is not None and est.spread == math.inf
    assert effective_gate(0.0024, est, "noisy") == 0.0024


# ---- classification ---------------------------------------------------------------------

def test_the_floor_is_judged_against_the_configured_gate_not_an_absolute_level() -> None:
    est = FloorEstimate(floor=0.0012, loud=0.0013, frames=40)
    assert classify_scene(est, 0.0024) == "noisy"      # exactly half the gate
    assert classify_scene(est, 0.0025) == "quiet"      # a hair under half
    # The same floor on a microphone whose scale is 10x: still judged relative to ITS gate.
    assert classify_scene(FloorEstimate(0.012, 0.013, 40), 0.024) == "noisy"


@pytest.mark.parametrize("gate", [0.0, -1.0, float("nan"), float("inf")])
def test_a_nonsense_gate_is_quiet(gate: float) -> None:
    assert classify_scene(FloorEstimate(0.5, 0.5, 40), gate) == "quiet"


def test_no_estimate_is_quiet() -> None:
    assert classify_scene(None, 0.0024) == "quiet"


# ---- the gate ---------------------------------------------------------------------------

def test_a_quiet_room_never_moves_the_gate() -> None:
    est = floor_estimate(_flat(0.0003))
    assert effective_gate(0.0024, est, "quiet") == 0.0024


def test_flat_noise_in_a_noisy_room_raises_the_gate_just_above_it() -> None:
    est = floor_estimate(_flat(0.0030))
    assert est is not None
    gate = effective_gate(0.0024, est, "noisy")
    assert 0.0024 < gate <= 0.0024 * 1.5 + 1e-12


def test_a_burst_with_speech_like_dynamics_keeps_the_configured_gate() -> None:
    est = floor_estimate(_speech(pause=0.0015, word=0.006))
    assert est is not None and est.spread >= SPEECH_SPREAD
    assert effective_gate(0.0024, est, "noisy") == 0.0024


def test_the_gate_never_goes_below_what_the_user_configured() -> None:
    for base, level in itertools.product((0.0005, 0.0024, 0.01), (0.0, 1e-5, 0.0004, 0.003, 0.05)):
        est = floor_estimate(_flat(level)) if level else floor_estimate([0.0] * 40)
        for sc in SCENES:
            assert effective_gate(base, est, sc) >= base


def test_an_unknown_or_missing_scene_changes_nothing() -> None:
    est = floor_estimate(_flat(0.003))
    assert effective_gate(0.0024, est, "") == 0.0024
    assert effective_gate(0.0024, est, "cafe") == 0.0024   # the retired scene labels
    assert effective_gate(0.0024, None, "noisy") == 0.0024


def test_the_clamps_hold_across_the_whole_grid() -> None:
    """gate in [base, 1.5 x base] and never above max(base, 2 x floor), for every combination."""
    bases = (0.0005, 0.001, 0.0024, 0.005, 0.01, 0.03)
    floors = (0.0, 0.0001, 0.0005, 0.001, 0.003, 0.005, 0.02, 0.1)
    spreads = (1.0, 1.2, 2.0, 2.49, 2.5, 5.0, 40.0)
    for base, floor, spread in itertools.product(bases, floors, spreads):
        est = FloorEstimate(floor=floor, loud=floor * spread, frames=40)
        for sc in SCENES:
            gate = effective_gate(base, est, sc)
            assert base <= gate <= base * 1.5 + 1e-12, (base, floor, spread, sc, gate)
            assert gate <= max(base, 2.0 * floor) + 1e-12, (base, floor, spread, sc, gate)


# ---- the owner's real microphone: speech must survive --------------------------------------

@pytest.mark.parametrize("speech_mean", [0.003, 0.0035, 0.004, 0.0045, 0.005])
@pytest.mark.parametrize("room", [0.0001, 0.0004, 0.0008, 0.0012, 0.0015, 0.002])
@pytest.mark.parametrize("base", [0.0005, 0.001, 0.0018, 0.0024])
def test_speech_at_the_real_mic_level_is_never_dropped_by_the_profile(
    speech_mean: float, room: float, base: float
) -> None:
    """Whatever the room, a burst the user's own gate keeps is also kept with the profile on.

    The word level is solved so the whole burst's mean |x| lands on ``speech_mean``; the room
    is the pause level. Any burst with a clear pause-vs-word contrast is speech-like and keeps
    the configured gate; and even a burst without one cannot lose more than the 1.5x clamp.
    """
    if speech_mean < base:
        pytest.skip("the user's own gate would already reject this; not the profile's doing")
    shape = _speech(pause=room, word=1.0)
    word_scale = (speech_mean * len(shape) - sum(v for v in shape if v == room)) / sum(
        v for v in shape if v != room
    )
    levels = [v * word_scale if v != room else v for v in shape]
    assert _mean(levels) == pytest.approx(speech_mean, rel=1e-6)
    est = floor_estimate(levels)
    # A tracker that has settled on "noisy" is the worst case for the speaker.
    gate = effective_gate(base, est, "noisy")
    # `mean < gate` is the silence test, so landing exactly on the gate is kept; the slack
    # only absorbs float rounding at that boundary (room 0.002, speech 0.003 = exactly 1.5x).
    assert _mean(levels) >= gate * (1 - 1e-9), (base, room, speech_mean, gate)


def test_the_retired_absolute_gates_are_gone() -> None:
    """The table that would have silenced the owner (0.010-0.035) must not come back."""
    assert set(profiles._POLICIES) == set(SCENES) == {"quiet", "noisy"}
    for pol in profiles._POLICIES.values():
        assert not hasattr(pol, "vad_threshold")
        assert 0.0 <= pol.floor_multiple <= 2.0
        assert 1.0 <= pol.max_raise <= 1.5
    assert policy_for("quiet").floor_multiple == 0.0
    assert policy_for("cafe").scene == "quiet"
    assert policy_for(None).scene == "quiet"
    assert scene.MAX_FLOOR_MULTIPLE == 2.0


# ---- hysteresis --------------------------------------------------------------------------

def test_should_switch_hysteresis() -> None:
    assert should_switch("noisy", "quiet", stable_count=3, min_stable=3) is True
    assert should_switch("noisy", "quiet", stable_count=2, min_stable=3) is False
    assert should_switch("noisy", "noisy", stable_count=99) is False


def test_the_tracker_needs_min_stable_consecutive_observations() -> None:
    t = SceneTracker(min_stable=3)
    assert t.current == "quiet"
    assert [t.observe("noisy") for _ in range(3)] == ["quiet", "quiet", "noisy"]
    # One quiet burst does not undo it; a run of them does.
    assert t.observe("quiet") == "noisy"
    assert t.observe("noisy") == "noisy"            # run broken and restarted
    assert [t.observe("quiet") for _ in range(3)] == ["noisy", "noisy", "quiet"]


def test_an_interrupted_run_restarts_the_count() -> None:
    t = SceneTracker(min_stable=3)
    t.observe("noisy")
    t.observe("noisy")
    t.observe("quiet")
    assert t.observe("noisy") == "quiet"
    assert t.observe("noisy") == "quiet"
    assert t.observe("noisy") == "noisy"


@pytest.mark.parametrize("bad", [0, -4])
def test_a_nonsense_min_stable_still_needs_one_observation(bad: int) -> None:
    t = SceneTracker(min_stable=bad)
    assert t.min_stable == 1
    assert t.observe("noisy") == "noisy"
