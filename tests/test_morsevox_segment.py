"""Vocal Morse producer (ADR-v2-105) — `morsevox/segment.py`, end to end on synthetic levels.

The stream here stands in for what `daemon._on_audio_chunk` already computes: one
``mean(|samples|)`` level per audio chunk, compared against a threshold. A 10 ms sample
period is a typical chunk length. Everything is synthetic and seeded — no audio, no
microphone, no model — so each test is deterministic.

Several tests are paired with a "without the guard" twin that must FAIL to decode. Those
twins are the point: a robustness test that would pass with the robustness switched off
is measuring the fixture, not the code.
"""
from __future__ import annotations

import math
import random

import pytest

from yazses.morsevox.decode import _MORSE, SK, MorseCalib
from yazses.morsevox.segment import (
    MorseStream,
    PulseSegmenter,
    Segment,
    SegmenterConfig,
)

_CODE = {v: k for k, v in _MORSE.items()}
STEP = 10.0            # ms between level samples
ON = 0.02              # on threshold (level units)
LOUD = 0.05            # level during a clean pulse
QUIET = 0.001          # level during clean silence


def timeline(text: str, *, dot=100.0, dash=350.0, sym_gap=150.0, letter_gap=800.0,
             word_gap=1800.0, lead=500.0, tail=2000.0):
    """Morse ``text`` -> list of (is_on, duration_ms) runs, with leading/trailing silence."""
    runs: list[tuple[bool, float]] = [(False, lead)]
    words = text.split(" ")
    for wi, word in enumerate(words):
        for li, ch in enumerate(word):
            code = _CODE[ch]
            for si, sym in enumerate(code):
                runs.append((True, dot if sym == "." else dash))
                if si < len(code) - 1:
                    runs.append((False, sym_gap))
            if li < len(word) - 1:
                runs.append((False, letter_gap))
        if wi < len(words) - 1:
            runs.append((False, word_gap))
    runs.append((False, tail))
    return runs


def code_timeline(codes: list[str], *, dot=100.0, dash=350.0, sym_gap=150.0,
                  letter_gap=800.0, lead=500.0, tail=2000.0):
    """Morse *codes* of one word -> (is_on, duration_ms) runs, as `timeline` builds them.

    Each code is keyed as ONE character (symbol gaps only inside it, a letter gap between
    codes), which is how a prosign such as SK (``...-.-``) is sent.
    """
    runs: list[tuple[bool, float]] = [(False, lead)]
    for ci, code in enumerate(codes):
        for si, sym in enumerate(code):
            runs.append((True, dot if sym == "." else dash))
            if si < len(code) - 1:
                runs.append((False, sym_gap))
        if ci < len(codes) - 1:
            runs.append((False, letter_gap))
    runs.append((False, tail))
    return runs


def sample(runs, *, step=STEP, level_on=lambda t, rng: LOUD, level_off=lambda t, rng: QUIET,
           rng=None):
    """Runs -> [(t_ms, level)] at a fixed sample period."""
    rng = rng or random.Random(0)
    out = []
    t = 0.0
    for is_on, dur in runs:
        end = t + dur
        while t < end - 1e-9:
            out.append((t, level_on(t, rng) if is_on else level_off(t, rng)))
            t += step
    return out


def decode(samples, stream: MorseStream) -> str:
    text = "".join(stream.push(t, lv) for t, lv in samples)
    return text + stream.flush(samples[-1][0] + STEP)


def stream(cfg: SegmenterConfig | None = None, **kw) -> MorseStream:
    cfg = cfg or SegmenterConfig.from_threshold(ON)
    return MorseStream(PulseSegmenter(cfg), **kw)


# ---- end to end: clean ------------------------------------------------------

def test_sos_decodes_to_sos():
    # The 2 s tail outlasts word_gap_ms, so the word is closed with a space — what a
    # typist would want before the next word, and what keeps live output word-separated.
    assert decode(sample(timeline("sos")), stream()) == "sos "


def test_sos_without_a_word_gap_tail_is_closed_by_flush():
    assert decode(sample(timeline("sos", tail=100.0)), stream()) == "sos"


def test_one_space_per_word_gap_and_none_for_leading_silence():
    assert decode(sample(timeline("sos sos", lead=3000.0, tail=5000.0)), stream()) == "sos sos "


def test_every_letter_and_digit_decodes_through_the_level_path():
    text = " ".join("".join(sorted(_CODE))[i:i + 6] for i in range(0, 36, 6))
    assert decode(sample(timeline(text)), stream()) == text + " "


def test_letter_is_emitted_live_once_the_letter_gap_elapses():
    """No waiting for the next pulse: S appears ~600 ms after its last dot ends."""
    samples = sample(timeline("sos"))
    st = stream()
    last_dot_end = 500.0 + 3 * 100.0 + 2 * 150.0          # lead + 3 dots + 2 symbol gaps
    seen = ""
    for t, lv in samples:
        seen += st.push(t, lv)
        if t < last_dot_end + 600.0 - STEP:
            assert seen == "", f"letter emitted early at t={t}"
        if t >= last_dot_end + 600.0 + 60.0 + STEP:     # + bridge_ms confirmation
            break
    assert seen == "s"


def test_word_gap_space_is_emitted_live_and_only_once():
    samples = sample(timeline("e", tail=6000.0))
    st = stream()
    texts = [st.push(t, lv) for t, lv in samples]
    assert "".join(texts) == "e "
    assert sum(1 for x in texts if x) == 2                   # "e", then " " — no repeats
    assert st.flush(samples[-1][0]) == ""


# ---- robustness: jitter, noise, clicks, dropouts -----------------------------

def _jittered(text: str, rng: random.Random, jitter: float):
    def j(x):
        return x * (1.0 + rng.uniform(-jitter, jitter))
    runs = timeline(text)
    return [(on, j(d)) for on, d in runs]


def _noisy_levels(rng: random.Random):
    """A pulse that wavers and drops out briefly; a silence with a noise floor and clicks."""
    def on(t, r):
        if r.random() < 0.08:            # ~20 ms dropouts well below off_level
            return QUIET
        return LOUD * r.uniform(0.5, 1.4)   # wavers, sometimes under on_level

    def off(t, r):
        if r.random() < 0.02:            # single-sample clicks above on_level
            return LOUD * 1.5
        return abs(r.gauss(0.0, 0.003))   # floor under off_level (0.012) almost always
    return on, off


@pytest.mark.parametrize("seed", range(25))
def test_sos_survives_jitter_noise_clicks_and_dropouts(seed):
    rng = random.Random(seed)
    runs = _jittered("sos sos", rng, jitter=0.2)
    on, off = _noisy_levels(rng)
    samples = sample(runs, level_on=on, level_off=off, rng=rng)
    assert decode(samples, stream()) == "sos sos "


def test_the_same_noisy_streams_fail_without_debounce():
    """Twin of the test above: with min_pulse_ms and bridge_ms at 0 the noise gets through."""
    raw = SegmenterConfig.from_threshold(ON, min_pulse_ms=0.0, bridge_ms=0.0)
    failures = 0
    for seed in range(25):
        rng = random.Random(seed)
        runs = _jittered("sos sos", rng, jitter=0.2)
        on, off = _noisy_levels(rng)
        samples = sample(runs, level_on=on, level_off=off, rng=rng)
        failures += decode(samples, stream(raw)) != "sos sos "
    assert failures >= 20


def test_hysteresis_keeps_a_hovering_hum_as_one_dash():
    """A level alternating just above/below on_level is one pulse with hysteresis."""
    def hover(t, r):
        return ON * (1.15 if int(t // STEP) % 2 == 0 else 0.85)
    runs = [(False, 300.0), (True, 400.0), (False, 2000.0)]
    with_h = SegmenterConfig.from_threshold(ON, hysteresis=0.6, bridge_ms=0.0)
    no_h = SegmenterConfig.from_threshold(ON, hysteresis=1.0, bridge_ms=0.0, min_pulse_ms=0.0)
    assert decode(sample(runs, level_on=hover), stream(with_h)) == "t "
    assert decode(sample(runs, level_on=hover), stream(no_h)) != "t "


# ---- segmenter details ------------------------------------------------------

def _segments(cfg, samples, t_end):
    seg = PulseSegmenter(cfg)
    out: list[Segment] = []
    for t, lv in samples:
        out += seg.push(t, lv)
    return out + seg.flush(t_end)


def test_segment_durations_match_the_input_to_one_sample():
    runs = [(False, 500.0), (True, 120.0), (False, 300.0), (True, 400.0), (False, 1000.0)]
    segs = _segments(SegmenterConfig.from_threshold(ON), sample(runs), 2320.0)
    assert [s.kind for s in segs] == ["pulse", "gap", "pulse"]   # no lead/tail gap
    for got, want in zip((s.duration_ms for s in segs), (120.0, 300.0, 400.0)):
        assert abs(got - want) <= STEP


def test_silence_ms_is_none_before_the_first_pulse_and_during_a_pulse():
    seg = PulseSegmenter(SegmenterConfig.from_threshold(ON))
    seg.push(0.0, QUIET)
    assert seg.silence_ms(1000.0) is None
    for t in range(10, 200, 10):
        seg.push(float(t), LOUD)
    assert seg.in_pulse and seg.silence_ms(200.0) is None
    for t in range(200, 400, 10):
        seg.push(float(t), QUIET)
    assert not seg.in_pulse
    assert seg.silence_ms(400.0) == pytest.approx(200.0)


def test_silence_is_frozen_while_a_rising_edge_is_debounced():
    seg = PulseSegmenter(SegmenterConfig.from_threshold(ON, min_pulse_ms=40.0))
    for t, lv in [(0.0, LOUD), (50.0, LOUD), (100.0, QUIET), (300.0, QUIET), (590.0, LOUD)]:
        seg.push(t, lv)
    # silence began at 100; candidate onset at 590 → frozen at 490 until confirmed
    assert seg.silence_ms(620.0) == pytest.approx(490.0)
    seg.push(620.0, QUIET)            # 30 ms voiced < min_pulse_ms ...
    seg.push(700.0, QUIET)            # ... closed after bridge_ms: a click, silence goes on
    assert seg.silence_ms(700.0) == pytest.approx(600.0)
    assert seg.silence_ms(900.0) == pytest.approx(800.0)


def test_backwards_time_and_non_finite_input_are_ignored_not_raised():
    seg = PulseSegmenter(SegmenterConfig.from_threshold(ON))
    assert seg.push(100.0, LOUD) == []
    assert seg.push(50.0, LOUD) == []            # clock went backwards: ignored
    assert seg.push(math.nan, LOUD) == []
    assert seg.push(200.0, math.nan) == []        # NaN level → silence (starts the drop)
    segs = seg.push(300.0, QUIET)
    assert segs == [Segment("pulse", 100.0, 100.0)]


def test_flush_closes_a_pulse_still_in_progress():
    seg = PulseSegmenter(SegmenterConfig.from_threshold(ON))
    for t in range(0, 300, 10):
        seg.push(float(t), LOUD)
    assert seg.flush(300.0) == [Segment("pulse", 0.0, 300.0)]
    assert seg.flush(400.0) == []


def test_flush_accepts_a_candidate_pulse_that_reaches_min_pulse_only_at_the_flush():
    # Capture stops a few samples into a hum: at the last sample the pulse has 30 ms of
    # voiced time, under min_pulse_ms=40, so it is still a candidate. Only the voiced time
    # flush() adds (up to t_ms) carries it past the minimum. That acceptance happens in
    # _close, not _resolve; drop it and the final dot vanishes along with the gap before it.
    seg = PulseSegmenter(SegmenterConfig.from_threshold(ON))
    pushed: list[Segment] = []
    for t, lv in [(0.0, LOUD), (10.0, LOUD), (100.0, QUIET), (200.0, QUIET),
                  (400.0, LOUD), (410.0, LOUD), (420.0, LOUD), (430.0, LOUD)]:
        pushed += seg.push(t, lv)
    assert pushed == [Segment("pulse", 0.0, 100.0)]  # the earlier pulse; its gap is open
    assert not seg.in_pulse                         # still only a candidate at 430 ms
    assert seg.flush(450.0) == [Segment("gap", 100.0, 300.0), Segment("pulse", 400.0, 50.0)]


def test_flush_drops_a_candidate_pulse_still_under_min_pulse():
    # The twin: the same flush on a candidate that stays under min_pulse_ms is a click.
    seg = PulseSegmenter(SegmenterConfig.from_threshold(ON))
    seg.push(0.0, QUIET)
    seg.push(10.0, LOUD)
    seg.push(20.0, LOUD)
    assert seg.flush(30.0) == []


def test_stream_flush_emits_pending_letter_without_space():
    st = stream()
    for t, lv in sample([(False, 100.0), (True, 100.0), (False, 100.0)]):
        assert st.push(t, lv) == ""
    assert st.flush(300.0) == "e"


@pytest.mark.parametrize("kwargs", [
    {"on_level": 0.01, "off_level": 0.02},
    {"on_level": -0.01, "off_level": -0.02},
    {"on_level": 0.01, "off_level": 0.005, "min_pulse_ms": -1.0},
    {"on_level": math.inf, "off_level": 0.0},
])
def test_config_rejects_inconsistent_values(kwargs):
    with pytest.raises(ValueError):
        SegmenterConfig(**kwargs)


def test_from_threshold_and_stream_argument_guards():
    cfg = SegmenterConfig.from_threshold(0.01, hysteresis=0.5)
    assert (cfg.on_level, cfg.off_level) == (0.01, 0.005)
    with pytest.raises(ValueError):
        SegmenterConfig.from_threshold(0.01, hysteresis=0.0)
    with pytest.raises(ValueError):
        SegmenterConfig.from_threshold(0.01, hysteresis=1.5)
    with pytest.raises(ValueError):
        MorseStream(PulseSegmenter(cfg), window=1)
    with pytest.raises(ValueError):
        MorseStream(PulseSegmenter(cfg), window=4, min_samples=6)   # could never refit


# ---- adaptive dot threshold -------------------------------------------------

def _slow(text: str):
    """A tiring user: every pulse 3x the default timing, so dots exceed dot_max_ms=200."""
    return timeline(text, dot=300.0, dash=900.0, sym_gap=300.0, letter_gap=1000.0,
                    word_gap=2400.0)


def test_slow_rhythm_misreads_without_adaptation():
    assert decode(sample(_slow("aaaa sos")), stream()) == "mmmm ooo "


def test_adaptive_threshold_recovers_a_slow_rhythm():
    st = stream(adapt=True)
    out = decode(sample(_slow("aaaa sos")), st)
    assert out.endswith(" sos ")
    assert 400.0 < st.calib.dot_max_ms < 650.0
    assert (st.calib.letter_gap_ms, st.calib.word_gap_ms) == (600.0, 1400.0)


def test_adaptation_waits_for_a_two_cluster_rhythm():
    """All dots has no dash cluster; refitting would drag the threshold into the dots."""
    st = stream(adapt=True)
    assert decode(sample(timeline("hhhh 5")), st) == "hhhh 5 "
    assert st.calib == MorseCalib()


def test_adaptation_is_off_unless_asked():
    st = stream()
    decode(sample(_slow("aaaa")), st)
    assert st.calib == MorseCalib()


# ---- the end-of-work prosign SK -----------------------------------------------

def test_sk_keyed_as_one_character_types_nothing_not_even_a_space():
    # The 2 s tail outlasts the word gap: an ordinary letter would be followed by " ".
    st = stream()
    assert decode(sample(code_timeline([SK])), st) == ""
    assert st.take_prosign() == "SK"
    assert st.take_prosign() is None


def test_s_and_k_with_a_letter_gap_are_typed_as_sk():
    st = stream()
    assert decode(sample(timeline("sk")), st) == "sk "
    assert st.take_prosign() is None


def test_letters_before_sk_in_the_same_word_are_typed_and_sk_is_not():
    st = stream()
    assert decode(sample(code_timeline([".-", "-...", SK])), st) == "ab"
    assert st.take_prosign() == "SK"


def test_sk_is_reported_live_once_the_letter_gap_after_it_elapses():
    samples = sample(code_timeline([SK]))
    st = stream()
    sk_end = 500.0 + 4 * 100.0 + 2 * 350.0 + 5 * 150.0   # lead + 4 dots + 2 dashes + 5 gaps
    seen_at = None
    for t, lv in samples:
        assert st.push(t, lv) == ""
        if st.take_prosign() == "SK":
            seen_at = t
            break
    assert seen_at is not None
    assert sk_end + 600.0 - STEP <= seen_at <= sk_end + 600.0 + 60.0 + 2 * STEP
