"""Pitch-Contour Gestures (ADR-v2-103): the pure core and its burst producer.

`test_hesitation_contour.py` holds the original four-point core tests; this file is the
contour feature's own home, adding the burst side (`yazses.contour.burst`) on synthetic hums
from `tests/synthetic_voice.py` — no recorded audio. numpy only, so no skip marker is needed.
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from tests.synthetic_voice import SR, glide, hum, silence, white_noise
from yazses.audio.pitch import track
from yazses.contour.burst import (
    burst_contour,
    burst_gesture,
    burst_to_command,
    is_hum_transcript,
    is_mostly_voiced,
    is_nonword_voiced_burst,
)
from yazses.contour.gesture import classify_contour, gesture_to_command, normalize_contour


def _rise_fall(seconds=0.8):
    half = seconds / 2
    return lambda t: np.where(t < half, 150.0 + 150.0 * t / half, 300.0 - 150.0 * (t - half) / half)


def _burst(f0, seconds=0.8):
    """A hum with 200 ms of quiet before and after, as a hold-to-talk burst would have."""
    return np.concatenate([silence(0.2), hum(f0, seconds, noise=5e-4), silence(0.2)])


# ---- the pure core ---------------------------------------------------------

def test_normalize_contour_is_in_semitones_from_the_mean():
    out = normalize_contour([100.0, 200.0])
    assert out[1] - out[0] == pytest.approx(12.0)  # an octave is twelve semitones
    assert out[0] < 0.0 < out[1]


def test_classify_contour_respects_the_slope_threshold():
    small_rise = normalize_contour([200.0, 205.0, 210.0, 215.0])  # ~1.2 semitones
    assert classify_contour(small_rise) == "flat"
    assert classify_contour(small_rise, slope_threshold=0.5) == "rise"


def test_gesture_to_command_with_an_empty_profile_maps_nothing():
    assert gesture_to_command("flat") is None  # unmapped by default (owner, 2026-10-21)
    assert gesture_to_command("rise") == "confirm"
    assert gesture_to_command("rise", profile={}) is None


# ---- burst -> gesture ------------------------------------------------------

@pytest.mark.parametrize(("f0", "gesture", "command"), [
    (glide(150.0, 300.0, 0.8), "rise", "confirm"),
    (glide(300.0, 150.0, 0.8), "fall", "cancel"),
    (_rise_fall(), "rise_fall", "undo"),
    (180.0, "flat", None),  # a flat hum is unmapped by default (owner, 2026-10-21)
])
def test_hummed_shapes_classify_as_the_adr_gestures(f0, gesture, command):
    audio = _burst(f0)
    frames = track(audio, SR)
    assert burst_gesture(frames) == gesture
    assert burst_to_command("", audio, SR) == command
    assert burst_to_command("Hmm.", audio, SR) == command


def test_burst_contour_smooths_a_single_frame_octave_slip():
    frames = list(track(_burst(180.0), SR))
    mid = next(i for i, f in enumerate(frames) if f.voiced) + 20
    frames[mid] = replace(frames[mid], f0_hz=360.0)  # one frame jumps an octave
    raw = burst_contour(frames, smooth=1)
    assert max(raw) == pytest.approx(360.0)
    smoothed = burst_contour(frames)
    assert len(smoothed) == len(raw) and max(smoothed) - min(smoothed) < 3.0
    assert burst_gesture(frames) == "flat"
    assert burst_contour([]) == []


def test_a_user_profile_overrides_the_default_map():
    audio = _burst(glide(150.0, 300.0, 0.8))
    assert burst_to_command("", audio, SR, profile={"rise": "accept"}) == "accept"


# ---- the non-word gate (a decision ADR-v2-103 has yet to ratify) -----------

@pytest.mark.parametrize("text", [
    "", None, "   ", "Hmm.", "mm", "Mhm", "mm-hmm", "uh", "Um...", "uhm", "ah", "erm", "hm hmm", "…",
    "hmmm", "Mmm.", "uhh", "umm", "ahh", "er", "eh",
])
def test_hum_transcripts(text):
    assert is_hum_transcript(text) is True


@pytest.mark.parametrize("text", [
    "no", "yes", "okay", "a", "oh", "Thank you.", "hmm okay", "send it", "نه",
    # Spellings that are also words or letters: a dictated "Hum." or "Err." must stay text.
    "hum", "Hum.", "err", "Err.", "em", "m", "u", "n", "nn", "uhm hum",
])
def test_any_real_word_keeps_the_burst_as_dictation(text):
    assert is_hum_transcript(text) is False


def test_a_spoken_word_with_a_falling_pitch_is_not_a_gesture():
    """'no' falls like a cancel hum. The transcript, not the contour, is what keeps it text."""
    audio = _burst(glide(300.0, 150.0, 0.8))
    assert burst_to_command("No.", audio, SR) is None


def test_a_hum_with_unvoiced_audio_is_not_a_gesture():
    assert burst_to_command("", white_noise(1.0), SR) is None
    assert burst_to_command("", silence(1.0), SR) is None
    assert is_mostly_voiced([]) is False


def test_a_short_hum_is_too_short_to_be_deliberate():
    # 300 ms: ~280 ms voiced once the onset/offset frames that straddle the hard edge
    # (unvoiced to YIN) are discounted — under the 400 ms default, over a 150 ms one.
    short = _burst(180.0, seconds=0.3)
    frames = track(short, SR)
    assert is_mostly_voiced(frames) is False
    assert is_mostly_voiced(frames, min_voiced_ms=150.0) is True
    assert burst_to_command("hmm", short, SR) is None


def test_speech_with_gaps_and_noise_is_not_mostly_voiced():
    """Alternating voiced and noisy stretches — a crude stand-in for consonants."""
    parts = []
    for i in range(5):
        parts.append(hum(160.0 + 10 * i, 0.12, noise=5e-4))
        parts.append(white_noise(0.12, level=0.006, seed=i))
    frames = track(np.concatenate(parts), SR)
    assert is_mostly_voiced(frames) is False
    assert is_nonword_voiced_burst("", frames) is False


def test_the_gate_needs_both_halves():
    frames = track(_burst(180.0), SR)
    assert is_nonword_voiced_burst("", frames) is True
    assert is_nonword_voiced_burst("repeat that", frames) is False
    assert is_nonword_voiced_burst("", track(white_noise(1.0), SR)) is False


def test_a_dictated_word_spelled_like_a_hum_is_not_a_gesture():
    """'Hum.' over a long, fully voiced burst passes the audio half; the transcript stops it."""
    audio = _burst(180.0)
    frames = track(audio, SR)
    assert is_mostly_voiced(frames) is True
    for text in ("Hum.", "Err.", "Em.", "U."):
        assert is_nonword_voiced_burst(text, frames) is False
        assert burst_to_command(text, audio, SR) is None
