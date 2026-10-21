"""The Vocal Joystick's per-frame producer (`yazses.vocaljoystick.formants`) on synthetic vowels.

numpy only, so nothing here can be absent on any supported platform (FreeBSD included) and no
skip marker is needed. Vowels come from `tests/synthetic_voice.vowel`: a source-filter cascade
(impulse train through resonators at Peterson & Barney's 1952 adult-male averages), so the true
F1/F2 is known by construction. No recorded audio.
"""
from __future__ import annotations

import math
import time

import numpy as np
import pytest

from tests.synthetic_voice import PETERSON_BARNEY_MALE, SR, silence, vowel, white_noise
from yazses.vocaljoystick.control import VocalJoystick
from yazses.vocaljoystick.formants import (
    VocalFrameTracker,
    estimate_formants,
    loudness,
    lpc,
    track,
)

# Tolerances: measured max error over every frame was <= 35 Hz on F1 and F2 for these vowels at
# F0 100-200 Hz; the bounds leave headroom without admitting a wrong formant (the closest pair
# of true values that must stay distinct, /i/ F1 270 vs /u/ F1 300, is not compared this way).
F1_TOL_HZ = 60.0
F2_TOL_HZ = 90.0


def _steady(frames):
    """Drop the frames that straddle the signal's start and end."""
    return frames[5:-5]


def _median_formants(frames):
    mid = _steady(frames)
    return (float(np.median([f.f1_hz for f in mid])), float(np.median([f.f2_hz for f in mid])))


@pytest.mark.parametrize("name", sorted(PETERSON_BARNEY_MALE))
@pytest.mark.parametrize("f0", [100.0, 150.0, 200.0])
def test_every_frame_recovers_f1_and_f2_within_tolerance(name, f0):
    true = PETERSON_BARNEY_MALE[name]
    frames = _steady(track(vowel(true, 0.5, f0=f0), SR))
    assert frames and all(f.voiced for f in frames)
    for f in frames:
        assert abs(f.f1_hz - true[0]) < F1_TOL_HZ, (name, f0, f.f1_hz)
        assert abs(f.f2_hz - true[1]) < F2_TOL_HZ, (name, f0, f.f2_hz)


def test_vowels_are_ordered_correctly_in_f1_f2_space():
    est = {v: _median_formants(track(vowel(fm, 0.5), SR))
           for v, fm in PETERSON_BARNEY_MALE.items()}
    # /a/ is the open vowel: highest F1. /i/ is the front vowel: highest F2. /u/ is back: lowest.
    assert est["a"][0] > est["i"][0] and est["a"][0] > est["u"][0]
    assert est["i"][1] > est["a"][1] > est["u"][1]


def test_pitch_comes_from_the_shared_yin_tracker():
    frames = _steady(track(vowel(PETERSON_BARNEY_MALE["a"], 0.5, f0=130.0), SR))
    assert all(abs(f.pitch_hz - 130.0) < 1.5 for f in frames)


#: Screen coordinates (y grows downward). Close /i/ /u/ go up, open /a/ down; front /i/ goes
#: left, back /u/ /a/ right — the mapping `control.vowel_to_direction` documents.
@pytest.mark.parametrize(("name", "expected", "sx", "sy"),
                         [("i", "nw", -1, -1), ("u", "ne", 1, -1), ("a", "se", 1, 1)])
def test_each_vowel_steers_the_core_the_way_the_mapping_says(name, expected, sx, sy):
    frames = _steady(track(vowel(PETERSON_BARNEY_MALE[name], 0.5), SR))
    assert {f.direction for f in frames} == {expected}
    joy = VocalJoystick(max_speed=10.0)
    events = [joy.feed(*f.joystick_args()) for f in frames]
    assert all(e.kind == "move" for e in events)
    x, y = joy.position()
    assert math.copysign(1, x) == sx and math.copysign(1, y) == sy and x != 0 and y != 0


def test_loudness_is_monotonic_in_gain_and_bounded():
    gains = [0.0005, 0.001, 0.003, 0.01, 0.03, 0.1]
    levels = [float(np.median([f.loudness for f in
                               _steady(track(vowel(PETERSON_BARNEY_MALE["a"], 0.3, amp=g), SR))]))
              for g in gains]
    assert all(b > a for a, b in zip(levels, levels[1:], strict=False)), levels
    assert all(0.0 <= v <= 1.0 for v in levels)
    assert loudness(1e-9) == 0.0 and loudness(1.0) == 1.0 and loudness(0.0) == 0.0


def test_formants_do_not_depend_on_gain():
    quiet = _median_formants(track(vowel(PETERSON_BARNEY_MALE["i"], 0.5, amp=0.001), SR))
    loud = _median_formants(track(vowel(PETERSON_BARNEY_MALE["i"], 0.5, amp=0.1), SR))
    assert abs(quiet[0] - loud[0]) < 5.0 and abs(quiet[1] - loud[1]) < 5.0


def test_silence_and_noise_never_steer():
    for audio in (silence(0.3), white_noise(0.3, level=0.01)):
        frames = track(audio, SR)
        assert frames and all(f.direction is None for f in frames)
        joy = VocalJoystick()
        assert {joy.feed(*f.joystick_args()).kind for f in frames} <= {"idle"}


def test_chunked_feeding_gives_the_same_frames_as_one_call():
    x = vowel(PETERSON_BARNEY_MALE["u"], 0.3)
    whole = track(x, SR)
    tr = VocalFrameTracker(SR)
    pieces = []
    for i in range(0, x.size, 333):
        pieces.extend(tr.feed(x[i:i + 333]))
    assert pieces == whole
    assert [round(f.t_s, 6) for f in whole[:3]] == [0.0, 0.01, 0.02]


def test_lpc_recovers_a_known_all_pole_filter():
    # x[n] = 1.3 x[n-1] - 0.8 x[n-2] + e[n]  =>  A(z) = 1 - 1.3 z^-1 + 0.8 z^-2.
    rng = np.random.default_rng(3)
    e = rng.normal(size=20000)
    x = np.zeros_like(e)
    for n in range(2, e.size):
        x[n] = 1.3 * x[n - 1] - 0.8 * x[n - 2] + e[n]
    a = lpc(x, 2)
    assert a[0] == 1.0
    assert abs(a[1] + 1.3) < 0.03 and abs(a[2] - 0.8) < 0.03


def test_degenerate_frames_yield_no_formants():
    assert estimate_formants(np.zeros(400), SR) is None
    assert estimate_formants(np.ones(3), SR) is None
    assert list(lpc(np.zeros(10), 4)) == [1.0, 0.0, 0.0, 0.0, 0.0]


def test_invalid_parameters_are_refused():
    with pytest.raises(ValueError):
        VocalFrameTracker(0)
    with pytest.raises(ValueError):
        VocalFrameTracker(SR, floor_db=-20.0, ceil_db=-60.0)
    with pytest.raises(ValueError):
        loudness(0.1, floor_db=-20.0, ceil_db=-20.0)


def test_per_frame_cost_fits_inside_the_hop():
    """Real-time means one frame's analysis must finish within one 10 ms hop.

    Measured on the development laptop at about 0.7-1.0 ms per frame. The bound is the hop
    itself, so a slow CI runner has ~10x headroom; the measured figure is printed (`-s`).
    """
    x = vowel(PETERSON_BARNEY_MALE["a"], 1.0)
    tr = VocalFrameTracker(SR)
    tr.feed(x[:2000])  # warm-up
    tr.reset()
    t0 = time.perf_counter()
    frames = tr.feed(x)
    per_frame_s = (time.perf_counter() - t0) / len(frames)
    print(f"vocaljoystick per-frame cost: {per_frame_s * 1000:.3f} ms over {len(frames)} frames")
    assert math.isfinite(per_frame_s) and per_frame_s < tr.hop_s


def test_a_high_voice_starting_from_silence_is_not_a_click():
    """Unvoiced frames carry pitch 0.0, so every onset is a 'jump' from zero.

    Before the core ignored jumps out of an unvoiced frame, any voice at or above
    ``click_pitch`` (250 Hz: many women's and most children's voices) clicked on its first
    voiced frame — a guard firing on no gesture at all (AGENTS.md rule 9).
    """
    audio = np.concatenate((silence(0.2), vowel(PETERSON_BARNEY_MALE["a"], 0.4, f0=280.0)))
    joy = VocalJoystick()
    kinds = [joy.feed(*f.joystick_args()).kind for f in track(audio, SR)]
    assert "click" not in kinds


def test_a_sharp_pitch_rise_inside_a_vowel_still_clicks():
    low = vowel(PETERSON_BARNEY_MALE["a"], 0.3, f0=150.0)
    high = vowel(PETERSON_BARNEY_MALE["a"], 0.3, f0=300.0)
    joy = VocalJoystick()
    kinds = [joy.feed(*f.joystick_args()).kind for f in track(np.concatenate((low, high)), SR)]
    assert "click" in kinds
