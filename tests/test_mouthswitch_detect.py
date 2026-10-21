"""The mouth-sound producer (`yazses.mouthswitch.detect`) on synthetic signals — ADR-v2-097.

numpy only, so nothing here can be absent on any supported platform (FreeBSD included) and no
skip marker is needed. Every signal is synthesised here or by `tests/synthetic_voice.py`; no
recorded audio (AGENTS.md). The sounds are idealised stand-ins: a click is a two-sample impulse,
a "pop" is low-passed noise under a fast exponential decay (an aperiodic low-frequency
transient, as a lip release is), an "sh" is 3-8 kHz band noise held for 300 ms.

The false-fire half (rule 9) matters as much as the detection half: the speech stand-in is
voiced syllables with F0 glides, plosive and fricative onsets glued to them, word-final stop
releases after a closure, and pauses, over a noise floor. It measures what the guards were
written for; it cannot say anything about keyboard taps, mic bumps or real speech.
"""
from __future__ import annotations

import numpy as np
import pytest

from tests.synthetic_voice import SR, glide, hum
from yazses.mouthswitch import detect as detect_mod
from yazses.mouthswitch.detect import (
    DEFAULT_ACTIONS,
    MouthSoundDetector,
    detect,
    extract_features,
    spectral_centroid,
    spectral_flatness,
    zero_crossing_rate,
)
from yazses.mouthswitch.scan import ScanSelector, classify_mouth_sound

FLOOR = 3e-4  # background noise RMS; a quiet room, well under the onset level


def _noise(seconds: float, level: float = FLOOR, seed: int = 5) -> np.ndarray:
    return np.random.default_rng(seed).normal(0.0, level, int(round(SR * seconds)))


def _band(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(x.size, 1.0 / SR)
    spec[(f < lo) | (f > hi)] = 0.0
    return np.fft.irfft(spec, x.size)


def click(amp: float = 0.3) -> np.ndarray:
    x = np.zeros(int(SR * 0.01))
    x[0], x[1] = amp, -0.6 * amp
    return x


def pop(amp: float = 0.05, seed: int = 2) -> np.ndarray:
    n = int(SR * 0.04)
    t = np.arange(n) / SR
    x = _band(np.random.default_rng(seed).normal(0.0, 1.0, n), 0.0, 600.0) * np.exp(-t / 0.008)
    return amp * x / np.abs(x).max()


def sh(seconds: float = 0.3, amp: float = 0.02, seed: int = 3) -> np.ndarray:
    n = int(SR * seconds)
    x = _band(np.random.default_rng(seed).normal(0.0, 1.0, n), 3000.0, 7900.0)
    ramp = np.minimum(1.0, np.minimum(np.arange(n), n - np.arange(n)) / (0.02 * SR))
    return amp * x / x.std() * ramp


def placed(*sounds: np.ndarray, gap_s: float = 0.6) -> np.ndarray:
    parts = [np.zeros(int(SR * gap_s))]
    for s in sounds:
        parts += [s, np.zeros(int(SR * gap_s))]
    sig = np.concatenate(parts)
    return sig + _noise(sig.size / SR)


def speechlike(seconds: float, seed: int) -> np.ndarray:
    """Voiced syllables with consonant onsets, stop releases and pauses, over a noise floor."""
    rng = np.random.default_rng(seed)
    out: list[np.ndarray] = [np.zeros(int(SR * 0.3))]
    total = 0
    while total < SR * seconds:
        for _ in range(int(rng.integers(1, 4))):            # syllables in a word
            onset = rng.choice(["none", "plosive", "fricative"])
            if onset == "plosive":                           # burst runs into the vowel
                out.append(click(float(rng.uniform(0.02, 0.2))))
                out.append(_noise(float(rng.uniform(0.01, 0.04)), 2e-3, int(rng.integers(1e6))))
            elif onset == "fricative":
                out.append(sh(float(rng.uniform(0.05, 0.15)), float(rng.uniform(0.005, 0.02)),
                              int(rng.integers(1e6))))
            f0 = float(rng.uniform(90, 260))
            dur = float(rng.uniform(0.06, 0.3))
            out.append(hum(glide(f0, f0 * float(rng.uniform(0.8, 1.2)), dur), dur,
                           amp=float(rng.uniform(0.005, 0.03)), ramp_s=0.01,
                           seed=int(rng.integers(1e6))).astype(np.float64))
            out.append(np.zeros(int(SR * float(rng.uniform(0.0, 0.08)))))
        if rng.random() < 0.3:                               # word-final stop: closure, release
            out.append(np.zeros(int(SR * float(rng.uniform(0.05, 0.12)))))
            out.append(click(float(rng.uniform(0.01, 0.1))))
        out.append(np.zeros(int(SR * float(rng.uniform(0.05, 0.5)))))   # between words
        total = sum(p.size for p in out)
    sig = np.concatenate(out)
    return sig + _noise(sig.size / SR, seed=seed + 100)


# ---- the three target sounds ------------------------------------------------------------

def test_a_click_is_a_select():
    events = detect(placed(click()), SR)
    assert [(e.kind, e.action) for e in events] == [("click", "select")]
    assert events[0].burst and events[0].centroid_hz >= 2000


def test_a_pop_is_an_advance():
    events = detect(placed(pop()), SR)
    assert [(e.kind, e.action) for e in events] == [("pop", "advance")]
    assert events[0].burst and events[0].centroid_hz < 2000


def test_an_sh_is_recognised_but_unmapped_by_default():
    events = detect(placed(sh()), SR)
    assert [e.kind for e in events] == ["sh"]
    assert events[0].action is None and "sh" not in DEFAULT_ACTIONS
    assert events[0].duration_ms > 200 and events[0].zcr >= 0.3


def test_an_sh_maps_when_the_user_opts_it_in():
    events = detect(placed(sh()), SR, actions={"sh": "select", "pop": "advance"})
    assert [(e.kind, e.action) for e in events] == [("sh", "select")]


def test_onset_time_is_where_the_sound_starts():
    (ev,) = detect(placed(pop(), gap_s=0.6), SR)
    assert abs(ev.t_s - 0.6) < 0.01


def test_a_sequence_drives_the_scan_selector():
    sig = placed(pop(), pop(seed=7), click())
    selector = ScanSelector(["yes", "no", "help"], dwell_s=10.0)
    picked = [selector.on_switch(e.action, now=e.t_s) for e in detect(sig, SR) if e.action]
    assert picked == [None, None, "help"]


def test_chunk_size_does_not_change_the_answer():
    sig = placed(pop(), click(), sh())
    whole = detect(sig, SR)
    det = MouthSoundDetector(SR)
    chunked = [e for i in range(0, sig.size, 333) for e in det.feed(sig[i:i + 333])]
    assert [(e.kind, e.t_s) for e in chunked] == [(e.kind, e.t_s) for e in whole]
    assert len(whole) == 3


# ---- the guards (rule 9) ----------------------------------------------------------------

@pytest.mark.parametrize("seconds", [0.04, 0.06, 0.15, 0.4])
def test_a_voiced_blip_is_never_a_switch(seconds):
    assert detect(placed(hum(150, seconds, amp=0.02)), SR) == []


def test_two_sounds_inside_the_refractory_window_fire_once():
    sig = np.concatenate([np.zeros(int(SR * 0.6)), pop(), np.zeros(int(SR * 0.17)),
                          pop(seed=9), np.zeros(int(SR * 0.6))])
    assert len(detect(sig + _noise(sig.size / SR), SR)) == 1


def test_a_sound_without_quiet_before_it_is_ignored():
    # 100 ms of hum, 80 ms closure, then a release: a word-final stop, not a switch press.
    sig = np.concatenate([np.zeros(int(SR * 0.6)), hum(150, 0.1, amp=0.02),
                          np.zeros(int(SR * 0.08)), click(0.1), np.zeros(int(SR * 0.6))])
    assert detect(sig + _noise(sig.size / SR), SR) == []


def test_a_release_shortly_after_a_word_is_ignored_but_a_later_one_counts():
    # 330 ms after the hum: past PRE_QUIET_MS and the refractory time the rejected hum set,
    # inside CONTEXT_MS -> part of the word. (The hum is itself a rejected *active* segment,
    # the case whose frames the context once failed to record.)
    near = np.concatenate([np.zeros(int(SR * 0.6)), hum(150, 0.2, amp=0.02),
                           np.zeros(int(SR * 0.33)), click(0.1), np.zeros(int(SR * 0.6))])
    assert detect(near + _noise(near.size / SR), SR) == []
    far = np.concatenate([np.zeros(int(SR * 0.6)), hum(150, 0.2, amp=0.02),
                          np.zeros(int(SR * 0.6)), click(0.1), np.zeros(int(SR * 0.6))])
    assert [e.kind for e in detect(far + _noise(far.size / SR), SR)] == ["click"]


def test_a_long_fricative_glued_to_a_short_quiet_vowel_is_ignored():
    # "shuh": the vowel is a small share of the frames, but more than one of them is pitched.
    syllable = np.concatenate([sh(0.18, 0.02, seed=4), hum(140, 0.08, amp=0.006)])
    assert detect(placed(syllable), SR) == []


def test_a_plosive_running_into_a_vowel_is_ignored():
    sig = np.concatenate([np.zeros(int(SR * 0.6)), click(0.1), hum(150, 0.12, amp=0.02),
                          np.zeros(int(SR * 0.6))])
    assert detect(sig + _noise(sig.size / SR), SR) == []


def test_steady_and_drifting_noise_never_fire():
    steady = _noise(10.0, 0.01, seed=11)
    t = np.arange(steady.size) / SR
    drifting = steady * (1.0 + 0.8 * np.sin(2 * np.pi * 0.3 * t))
    assert detect(steady, SR) == [] and detect(drifting, SR) == []


def test_digital_silence_and_nonfinite_input_never_fire():
    det = MouthSoundDetector(SR)
    assert det.feed(np.zeros(SR)) == []
    assert det.feed(np.full(SR // 2, np.nan)) == []
    assert det.feed([]) == []


def _kinds(sig: np.ndarray) -> list[str]:
    return [e.kind for e in detect(sig, SR)]


def test_a_stream_that_opens_with_digital_zeros_still_hears_later_sounds():
    """Zeros seed the floor at FLOOR_MIN; the room noise after them is then all "sounding".

    Before the re-seed the floor never left FLOOR_MIN, no quiet run ever built up, and every
    later click and pop was silently dropped. The sounds sit past FLOOR_RESEED_MS of noise.
    """
    room = np.concatenate([_noise(1.5, seed=7), placed(click(), pop())])
    sig = np.concatenate([np.zeros(int(SR * 0.3)), room])
    assert _kinds(sig) == ["click", "pop"]


@pytest.mark.parametrize("level, expected", [
    (4 * FLOOR, ["click", "pop"]),   # a fan at 4x: the pop still clears 8x the new floor
    (10 * FLOOR, ["click"]),         # at 10x the pop is under the onset level, steady or not
])
def test_a_step_up_in_background_noise_does_not_deafen_the_detector(level, expected):
    """A fan switching on: a step of more than SUSTAIN_RATIO leaves no quiet frame to track.

    ``expected`` is what the same sounds give over that noise level from the first sample
    (``test_detection_after_a_step_matches_steady_noise_at_that_level``), so the step costs
    nothing once the floor has re-seeded — and the step itself fires nothing.
    """
    before = _noise(1.0, FLOOR, seed=1)
    fan = _noise(1.5, level, seed=2)
    tail = np.concatenate([np.zeros(int(SR * 0.6)), click(), np.zeros(int(SR * 0.6)), pop(),
                           np.zeros(int(SR * 0.6))])
    tail = tail + _noise(tail.size / SR, level, seed=3)
    assert _kinds(np.concatenate([before, fan, tail])) == expected


@pytest.mark.parametrize("level, expected", [(4 * FLOOR, ["click", "pop"]),
                                             (10 * FLOOR, ["click"])])
def test_detection_after_a_step_matches_steady_noise_at_that_level(level, expected):
    sig = np.concatenate([np.zeros(int(SR * 0.6)), click(), np.zeros(int(SR * 0.6)), pop(),
                          np.zeros(int(SR * 0.6))])
    assert _kinds(sig + _noise(sig.size / SR, level, seed=3)) == expected


@pytest.mark.parametrize("seed", range(4))
def test_speechlike_stream_false_fire_rate_is_zero(seed):
    """30 s of the speech stand-in per seed, 2 min in all: no switch event at all."""
    assert detect(speechlike(30.0, seed), SR) == []


def test_the_speech_stand_in_would_fire_without_the_voicing_guards(monkeypatch):
    """The zero above is the voicing guards' doing, not an inert stand-in."""
    monkeypatch.setattr(detect_mod, "MAX_VOICED_FRACTION", 2.0)
    monkeypatch.setattr(detect_mod, "PITCHED_FRAMES", 10**9)
    fired = sum(len(detect(speechlike(30.0, s), SR)) for s in range(4))
    assert fired > 0


# ---- feature extraction (pure) ----------------------------------------------------------

def test_feature_primitives():
    t = np.arange(SR // 10) / SR
    tone = np.sin(2 * np.pi * 1000 * t)
    assert abs(spectral_centroid(tone, SR) - 1000) < 20
    assert spectral_flatness(tone) < 0.05
    assert spectral_flatness(np.random.default_rng(0).normal(size=4096)) > 0.4
    assert abs(zero_crossing_rate(tone) - 2 * 1000 / SR) < 0.005
    assert spectral_centroid(np.zeros(100), SR) == 0.0
    assert zero_crossing_rate([1.0]) == 0.0


def test_extracted_features_feed_the_existing_classifier():
    feats = extract_features(pop(), SR, FLOOR)
    assert {"duration_ms", "centroid_hz", "zcr", "burst"} <= feats.keys()
    assert classify_mouth_sound(feats) == "pop"
    assert classify_mouth_sound(extract_features(sh(), SR, FLOOR)) == "sh"
    assert extract_features(hum(150, 0.15, amp=0.02), SR, FLOOR)["voiced"] is True
