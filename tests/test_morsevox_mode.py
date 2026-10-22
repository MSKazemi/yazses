"""Vocal Morse mode (ADR-v2-105) — `morsevox/mode.py`: when Morse starts and stops. Pure.

The samples stand in for the per-chunk ``mean(|samples|)`` level the runtime computes, at
a 20 ms period. Everything is synthetic: **these thresholds have never been measured on a
real voice**, and nothing here claims they have. What the tests pin is the *rule* — a long,
steady, unbroken tone enters; speech-shaped levels never do (ADR-021) — and the mode's
timings and exits.

Each guard of the hum trigger is paired with a twin that switches only that guard off and
must then fire, so a green test means the guard holds, not that the fixture is too weak to
trip anything.
"""
from __future__ import annotations

import math

import pytest

from tests.test_morsevox_segment import timeline
from yazses.morsevox.decode import MorseCalib
from yazses.morsevox.mode import (
    ARMED,
    ARMED_TIMEOUT_MS,
    IDLE,
    MORSE,
    HumDetector,
    ModeConfig,
    ModeStep,
    MorseMode,
    describe_status,
    is_enter_phrase,
    resolve,
)

STEP = 20.0      # ms between level samples
ON = 0.02        # on threshold (level units)
OFF = 0.012      # off threshold: ON * 0.6, as `resolve` derives it
LOUD = 0.05      # a steady hum
QUIET = 0.001    # a quiet room


def cfg(**kw) -> ModeConfig:
    return ModeConfig(on_level=ON, off_level=OFF, **kw)


def levels(runs, *, t0: float = 0.0):
    """[(duration_ms, level or level(t))] -> ([(t_ms, level)], end_t)."""
    out = []
    t = t0
    for dur, lv in runs:
        end = t + dur
        while t < end - 1e-9:
            out.append((t, lv(t) if callable(lv) else lv))
            t += STEP
    return out, t


def morse_runs(text: str, **kw):
    """`timeline` (is_on, ms) runs -> (ms, level) runs."""
    return [(dur, LOUD if on else QUIET) for on, dur in timeline(text, **kw)]


def drive(machine, samples, *, busy=lambda t: False):
    """Feed samples; return (typed text, [(t, step)] for every step that changed the mode)."""
    text = []
    changes: list[tuple[float, ModeStep]] = []
    for t, lv in samples:
        step = machine.push(t, lv, busy=busy(t))
        text.append(step.text)
        if step.entered or step.exited:
            changes.append((t, step))
    return "".join(text), changes


def hum_fires(samples, detector: HumDetector) -> list[float]:
    return [t for t, lv in samples if detector.push(t, lv)]


# Speech-shaped level streams. Syllables at ~4 Hz; the envelope of running speech.
def syllabic(t: float) -> float:
    """Each syllable rises and falls to silence: the dips between syllables cross OFF."""
    return LOUD * (0.5 - 0.5 * math.cos(2 * math.pi * 4.0 * t / 1000.0))


def breathless(t: float) -> float:
    """Running speech that never drops below OFF, but is modulated (CV ~0.42)."""
    return LOUD * (1.0 + 0.6 * math.sin(2 * math.pi * 4.0 * t / 1000.0))


def steady_hum(t: float) -> float:
    """A held "mmmm" with a little natural wobble (CV ~0.07)."""
    return LOUD * (1.0 + 0.1 * math.sin(2 * math.pi * 5.0 * t / 1000.0))


# --------------------------------------------------------------------------- #
# The spoken entry phrase — whole utterance only
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("said", ["morse mode", "Morse mode.", "MORSE MODE!", "Morse-mode", " morse  mode "])
def test_the_whole_utterance_morse_mode_enters(said):
    assert is_enter_phrase(said) is True


@pytest.mark.parametrize("said", [
    "", "morse", "mode", "switch to morse mode", "morse mode please",
    "I learned morse mode at school", "horse mode", None,
])
def test_anything_else_is_dictation(said):
    assert is_enter_phrase(said) is False


# --------------------------------------------------------------------------- #
# Config: repaired where it can be, refused where it cannot
# --------------------------------------------------------------------------- #
def test_resolve_builds_the_documented_defaults():
    mode_cfg, notes = resolve(1.5, 3.0, 0.02)
    assert notes == []
    assert mode_cfg is not None
    assert mode_cfg.entry_hum_ms == 1500.0 and mode_cfg.exit_silence_ms == 3000.0
    assert mode_cfg.on_level == 0.02 and mode_cfg.off_level == pytest.approx(0.012)
    assert mode_cfg.hum_entry is True
    assert mode_cfg.calib == MorseCalib()


def test_resolve_repairs_unusable_timings_and_says_so():
    mode_cfg, notes = resolve("soon", -2, 0.02)
    assert mode_cfg is not None
    assert (mode_cfg.entry_hum_ms, mode_cfg.exit_silence_ms) == (1500.0, 3000.0)
    assert len(notes) == 2 and "entry_hum_s" in notes[0] and "exit_silence_s" in notes[1]


@pytest.mark.parametrize("exit_s", [0.5, 1.4])
def test_an_exit_silence_inside_the_word_gap_is_raised_above_it(exit_s):
    """Otherwise the space between two words would end Morse mode."""
    mode_cfg, notes = resolve(1.5, exit_s, 0.02)
    assert mode_cfg is not None
    assert mode_cfg.exit_silence_ms == 2400.0  # word gap 1400 + 1000
    assert any("word gap" in n for n in notes)


def test_the_word_gap_used_is_the_configured_one():
    mode_cfg, _ = resolve(1.5, 3.0, 0.02, word_gap_ms=5000.0)
    assert mode_cfg is not None and mode_cfg.exit_silence_ms == 6000.0


def test_zero_turns_the_hum_entry_off():
    mode_cfg, notes = resolve(0, 3.0, 0.02)
    assert mode_cfg is not None and mode_cfg.hum_entry is False and notes == []


@pytest.mark.parametrize("threshold", [0, 0.0, -0.01, float("nan"), "loud", None])
def test_no_usable_threshold_means_no_mode(threshold):
    mode_cfg, notes = resolve(1.5, 3.0, threshold)
    assert mode_cfg is None
    assert len(notes) == 1 and "threshold" in notes[0]


@pytest.mark.parametrize("kw", [
    {"on_level": 0.0, "off_level": 0.0},
    {"on_level": 0.01, "off_level": 0.02},
    {"on_level": float("nan"), "off_level": 0.01},
    {"on_level": 0.02, "off_level": 0.01, "exit_silence_ms": 1400.0},
    {"on_level": 0.02, "off_level": 0.01, "min_hum_samples": 1},
    {"on_level": 0.02, "off_level": 0.01, "entry_hum_ms": -1.0},
])
def test_mode_config_refuses_a_contradiction(kw):
    with pytest.raises(ValueError):
        ModeConfig(**kw)


# --------------------------------------------------------------------------- #
# The entry hum: fires on a long steady tone, never on speech (ADR-021)
# --------------------------------------------------------------------------- #
def test_a_steady_hum_fires_once_when_it_has_lasted_the_entry_time():
    samples, _ = levels([(500, QUIET), (3000, steady_hum)])
    assert hum_fires(samples, HumDetector(cfg())) == [2000.0]  # 500 + 1500, and only once


def test_a_hum_just_short_of_the_entry_time_does_not_fire():
    samples, _ = levels([(500, QUIET), (1480, LOUD), (2000, QUIET)])
    assert hum_fires(samples, HumDetector(cfg())) == []


def test_one_drop_below_the_threshold_restarts_the_run():
    samples, _ = levels([(1000, LOUD), (40, QUIET), (1000, LOUD), (1000, QUIET)])
    assert hum_fires(samples, HumDetector(cfg())) == []
    # ...and a long enough run after the drop still fires, timed from the drop.
    samples, _ = levels([(1000, LOUD), (40, QUIET), (1600, LOUD)])
    assert hum_fires(samples, HumDetector(cfg())) == [1040.0 + 1500.0]


def test_a_level_between_the_thresholds_continues_a_run_but_cannot_start_one():
    between = (ON + OFF) / 2
    samples, _ = levels([(3000, between)])
    assert hum_fires(samples, HumDetector(cfg())) == []          # never reached ON
    samples, _ = levels([(100, LOUD), (2000, between)])
    # Started at ON; stays on above OFF (CV is high across the step, so it fires once the
    # window has slid past the loud start and holds only the steady part).
    assert hum_fires(samples, HumDetector(cfg())) != []


def test_syllabic_speech_never_fires():
    samples, _ = levels([(10_000, syllabic)])
    assert hum_fires(samples, HumDetector(cfg())) == []


def test_syllabic_speech_is_held_by_the_drops_not_by_luck():
    """Twin: even with the steadiness guard off, the dips between syllables reset the run."""
    samples, _ = levels([(10_000, syllabic)])
    assert hum_fires(samples, HumDetector(cfg(max_hum_cv=100.0))) == []


def test_breathless_speech_with_no_dip_never_fires():
    samples, _ = levels([(10_000, breathless)])
    assert min(lv for _, lv in samples) >= OFF  # the fixture really has no dip
    assert hum_fires(samples, HumDetector(cfg())) == []


def test_breathless_speech_is_held_by_the_steadiness_guard():
    """Twin: switch the steadiness guard off and the same stream fires."""
    samples, _ = levels([(10_000, breathless)])
    assert hum_fires(samples, HumDetector(cfg(max_hum_cv=100.0))) != []


def test_a_noise_floor_below_the_threshold_never_fires():
    samples, _ = levels([(10_000, ON * 0.9)])
    assert hum_fires(samples, HumDetector(cfg())) == []


def test_too_few_samples_cannot_pass_as_steady():
    """Chunks 400 ms apart: four numbers in a window are not evidence of a steady tone."""
    det = HumDetector(cfg())
    fired = [t for t in range(0, 4000, 400) if det.push(float(t), LOUD)]
    assert fired == []
    twin = HumDetector(cfg(min_hum_samples=2))
    assert [t for t in range(0, 4000, 400) if twin.push(float(t), LOUD)] != []


def test_a_glitching_stream_cannot_fire_or_raise():
    det = HumDetector(cfg())
    assert det.push(1000.0, LOUD) is False
    assert det.push(500.0, LOUD) is False             # time went backwards: ignored
    assert det.push(float("nan"), LOUD) is False
    assert det.push(1020.0, float("nan")) is False    # NaN level is silence: the run resets
    assert det.in_run is False


# --------------------------------------------------------------------------- #
# The mode, end to end
# --------------------------------------------------------------------------- #
def test_a_long_hum_enters_and_the_hum_itself_is_not_decoded():
    m = MorseMode(cfg())
    runs = [(500, QUIET), (2000, LOUD)] + morse_runs("sos") + [(3500, QUIET)]
    samples, _ = levels(runs)
    text, changes = drive(m, samples)
    assert [(t, s.entered) for t, s in changes if s.entered] == [(2000.0, "hum")]
    # "sos" plus the space a word gap completes; no leading "t" from the entry hum.
    assert text == "sos "
    assert [s.exited for _, s in changes if s.exited] == ["silence"]
    assert m.state == IDLE


def test_the_mode_ends_after_the_exit_silence_and_not_before():
    m = MorseMode(cfg())
    m.enter(0.0)
    runs = [(200, QUIET), (100, LOUD), (5000, QUIET)]
    samples, _ = levels(runs)
    text, changes = drive(m, samples)
    assert text == "e "
    (t_exit, step), = changes
    assert step.exited == "silence"
    pulse_end = 300.0
    assert pulse_end + 3000.0 <= t_exit <= pulse_end + 3000.0 + 100.0


def test_the_spoken_command_enters_armed_then_decodes_once_it_is_quiet():
    m = MorseMode(cfg())
    step = m.enter(0.0, "command")
    assert step == ModeStep(entered="command")
    assert m.state == ARMED and m.active and m.entered_by == "command"
    m.push(20.0, QUIET)
    assert m.state == MORSE


def test_entering_does_nothing_while_already_active():
    m = MorseMode(cfg())
    m.enter(0.0)
    assert m.enter(10.0) == ModeStep()
    assert m.entered_by == "command"


def test_a_command_entry_followed_by_nothing_ends_after_the_exit_silence():
    m = MorseMode(cfg())
    m.enter(0.0)
    samples, _ = levels([(3500, QUIET)])
    text, changes = drive(m, samples)
    assert text == ""
    # Decoding starts on the first (quiet) sample at 0 ms; the exit silence runs from there.
    assert [(t, s.exited) for t, s in changes] == [(3000.0, "silence")]


def test_a_long_dash_inside_morse_mode_is_a_t_and_neither_exits_nor_re_enters():
    m = MorseMode(cfg())
    m.enter(0.0)
    samples, _ = levels([(200, QUIET), (2000, LOUD), (1000, QUIET)])
    text, changes = drive(m, samples)
    assert text == "t"
    assert changes == []
    assert m.state == MORSE


def test_morse_timing_while_idle_types_nothing_and_does_not_enter():
    m = MorseMode(cfg())
    samples, _ = levels(morse_runs("sos the quick"))
    text, changes = drive(m, samples)
    assert (text, changes) == ("", [])


def test_ten_seconds_of_speech_shaped_levels_never_enter():
    for shape in (syllabic, breathless):
        m = MorseMode(cfg())
        samples, _ = levels([(10_000, shape)])
        assert drive(m, samples) == ("", []), shape.__name__


def test_without_the_hum_trigger_a_long_hum_does_nothing():
    m = MorseMode(cfg(entry_hum_ms=0.0))
    samples, _ = levels([(6000, LOUD)])
    assert drive(m, samples) == ("", [])


def test_dictation_starting_ends_the_mode():
    m = MorseMode(cfg())
    m.enter(0.0)
    m.push(20.0, QUIET)
    step = m.push(40.0, LOUD, busy=True)
    assert step.exited == "dictation" and m.state == IDLE


def test_a_hum_while_dictation_records_is_not_an_entry_and_the_clock_restarts_after():
    m = MorseMode(cfg())
    samples, _ = levels([(4000, LOUD)])
    _, changes = drive(m, samples, busy=lambda t: t < 2000.0)
    # Busy until 2000 ms; the hum then has to last the full 1.5 s on its own.
    assert [(t, s.entered) for t, s in changes] == [(3500.0, "hum")]


def test_a_sound_that_never_stops_gives_up_instead_of_staying_armed():
    m = MorseMode(cfg())
    m.enter(0.0)
    samples, _ = levels([(ARMED_TIMEOUT_MS + 5000, LOUD)])
    _, changes = drive(m, samples)
    # Gives up once, and the same unbroken sound cannot then count as a new entry hum.
    assert [(s.entered, s.exited) for _, s in changes] == [(None, "no_release")]
    assert m.state == IDLE


def test_a_steady_noise_above_the_threshold_enters_at_most_once():
    """A known limit, pinned so it cannot get worse: a fan louder than the voice threshold
    *is* a long steady tone. It enters once, gives up when it never stops, and stays out."""
    m = MorseMode(cfg())
    samples, _ = levels([(40_000, LOUD)])
    _, changes = drive(m, samples)
    assert [(t, s.entered, s.exited) for t, s in changes] == [
        (1500.0, "hum", None), (1500.0 + ARMED_TIMEOUT_MS, None, "no_release"),
    ]
    # Once it does stop, a real hum enters again.
    samples, _ = levels([(100, QUIET), (2000, LOUD)], t0=40_000.0)
    _, changes = drive(m, samples)
    assert [s.entered for _, s in changes] == ["hum"]


def test_an_explicit_exit_drops_a_half_keyed_letter():
    m = MorseMode(cfg())
    m.enter(0.0)
    samples, _ = levels([(200, QUIET), (100, LOUD), (100, QUIET)])  # one dot, no letter gap yet
    drive(m, samples)
    step = m.exit(400.0, "paused")
    assert step == ModeStep(exited="paused")
    step = m.exit(420.0)
    assert step == ModeStep()  # already idle
    m.enter(440.0)
    samples, _ = levels([(200, QUIET), (350, LOUD), (1000, QUIET)], t0=460.0)
    text, _ = drive(m, samples)
    assert text == "t"  # not "a" (".-"): the earlier dot did not survive the exit


def test_the_mode_ignores_backwards_time_and_nan_levels():
    m = MorseMode(cfg())
    m.enter(1000.0)
    m.push(1000.0, LOUD)
    assert m.push(500.0, QUIET) == ModeStep()          # time went backwards: ignored...
    assert m.state == ARMED                            # ...so the quiet did not start decoding
    assert m.push(float("nan"), QUIET) == ModeStep()
    assert m.state == ARMED
    assert m.push(1020.0, float("nan")) == ModeStep()  # NaN = silence: decoding starts
    assert m.state == MORSE


# --------------------------------------------------------------------------- #
# The `yazses status` line
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("block,expected", [
    ({"active": True, "entered_by": "hum"}, "ON — decoding Morse (entered by a long hum)"),
    ({"active": True, "entered_by": "command"}, "ON — decoding Morse (entered by \"morse mode\")"),
    ({"active": False, "paused": True, "hum_entry": True}, "off — paused"),
    ({"active": False, "hum_entry": True, "listening": True}, "listening for a long steady hum"),
    ({"active": False, "hum_entry": True, "listening": False}, "not listening"),
    ({"active": False, "hum_entry": False}, "say \"morse mode\" to start"),
    ({"fault": "runtime error: ValueError"}, "stopped (runtime error: ValueError)"),
    ("garbage", "unknown"),
])
def test_describe_status(block, expected):
    assert expected in describe_status(block)  # type: ignore[arg-type]
