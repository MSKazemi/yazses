"""Involuntary-Vocalization Excision on audio (ADR-v2-102): cut coughs, never cut speech.

The detector's value is judged by how rarely it deletes something the user said (AGENTS.md rule 9),
so most of this file is the negative direction: speech-shaped fixtures -- pitched vowels with
formants and vibrato, fricative-tailed words, a plosive after a closure, a whispered-sounding
"shh" -- must come back untouched, and only an isolated, pitchless, abrupt burst may be silenced.

Fixtures are numpy-only (additive harmonic synthesis shaped by formant resonances; band-limited
noise made in the FFT domain) so no optional dependency is needed and the suite stays offline.
"""
from __future__ import annotations

import numpy as np
import pytest

from yazses.involuntary import audio as iv
from yazses.involuntary.audio import excise_involuntary_audio, find_involuntary_spans

SR = 16000


def _rng(seed: int = 0) -> np.random.Generator:
    return np.random.default_rng(seed)


def silence(dur: float, seed: int = 1) -> np.ndarray:
    return _rng(seed).standard_normal(int(dur * SR)) * 1e-4


def vowel(dur: float, f0: float = 130.0, formants=((700, 90), (1200, 110), (2500, 160)),
          amp: float = 0.25) -> np.ndarray:
    """Pitched, vibrato-modulated harmonic source shaped by formant resonances."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    phase = np.cumsum(f0 * (1 + 0.03 * np.sin(2 * np.pi * 5 * t))) / SR
    out = np.zeros(n)
    for k in range(1, 40):
        fk = k * f0
        gain = sum(1.0 / (1.0 + ((fk - fc) / bw) ** 2) for fc, bw in formants)
        out += gain * np.sin(2 * np.pi * k * phase)
    env = np.minimum(1.0, np.minimum(t / 0.03, (dur - t) / 0.05))
    out *= env
    return amp * out / np.max(np.abs(out))


def band_noise(dur: float, lo: float, hi: float, attack: float, decay: float, amp: float,
               seed: int = 2) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    spec = np.fft.rfft(_rng(seed).standard_normal(n))
    f = np.fft.rfftfreq(n, 1.0 / SR)
    spec[(f < lo) | (f > hi)] = 0
    x = np.fft.irfft(spec, n) * np.minimum(1.0, t / attack) * np.exp(-t / decay)
    return amp * x / np.max(np.abs(x))


def cough(dur: float = 0.25, amp: float = 0.7) -> np.ndarray:
    return band_noise(dur, 300, 1400, attack=0.005, decay=0.08, amp=amp)


def sneeze(dur: float = 0.3, amp: float = 0.8) -> np.ndarray:
    return band_noise(dur, 2500, 7000, attack=0.005, decay=0.1, amp=amp)


def throat_clear(dur: float = 0.4, amp: float = 0.5) -> np.ndarray:
    return band_noise(dur, 100, 700, attack=0.08, decay=0.3, amp=amp)


def utterance(*parts: np.ndarray) -> np.ndarray:
    return np.concatenate(parts).astype(np.float32)


def _sentence_with(between: np.ndarray) -> np.ndarray:
    return utterance(silence(0.3), vowel(0.5), silence(0.25), between, silence(0.25),
                     vowel(0.6, 120), silence(0.2))


# ---- what it removes --------------------------------------------------------

@pytest.mark.parametrize(
    "event,kinds",
    [(cough, {"cough"}), (sneeze, {"sneeze"}), (throat_clear, {"throat_clear"})],
)
def test_an_isolated_bodily_sound_between_phrases_is_flagged(event, kinds) -> None:
    spans = find_involuntary_spans(_sentence_with(event()), SR)
    assert len(spans) == 1 and {k for _, _, k in spans} == kinds
    start, end, _ = spans[0]
    assert 1.0 <= start < 1.1 and end <= 1.55   # sits where the event was inserted (1.05 s)


def test_two_coughs_are_both_cut_and_the_speech_either_side_is_bit_identical() -> None:
    x = utterance(silence(0.3), vowel(0.9), silence(0.25), cough(), silence(0.25), cough(),
                  silence(0.25), vowel(1.0, 120), silence(0.2))
    out, spans = excise_involuntary_audio(x, SR)
    assert len(spans) == 2
    assert out.shape == x.shape and out.dtype == x.dtype      # timings and dtype preserved
    assert np.array_equal(out[: int(1.4 * SR)], x[: int(1.4 * SR)])   # first phrase untouched
    assert np.array_equal(out[-int(0.7 * SR):], x[-int(0.7 * SR):])   # last phrase untouched
    for s, e, _ in spans:
        assert not np.any(out[int(s * SR):int(e * SR)])


def test_excising_does_not_mutate_the_callers_array() -> None:
    x = _sentence_with(cough())
    before = x.copy()
    out, spans = excise_involuntary_audio(x, SR)
    assert spans and out is not x
    assert np.array_equal(x, before)


# ---- what it must NOT remove ------------------------------------------------

def test_nothing_flagged_returns_the_very_same_object() -> None:
    x = utterance(silence(0.3), vowel(0.5), silence(0.2), vowel(0.6, 120), silence(0.2))
    out, spans = excise_involuntary_audio(x, SR)
    assert out is x and spans == []


def test_pitched_speech_with_fricatives_and_pauses_is_never_cut() -> None:
    # "ah (pause) s-eh (pause) ah": a fricative tail, vibrato, two F0s, normal between-word gaps.
    fric = band_noise(0.12, 4000, 7500, attack=0.03, decay=10.0, amp=0.08)
    x = utterance(silence(0.3), vowel(0.3, 130), silence(0.2), fric,
                  vowel(0.25, 150, ((500, 80), (1800, 120), (2600, 160))), silence(0.2),
                  vowel(0.4, 118), silence(0.2))
    assert find_involuntary_spans(x, SR) == []


@pytest.mark.parametrize("f0", [85.0, 110.0, 180.0, 240.0, 300.0])
def test_voiced_speech_across_pitch_ranges_is_never_a_candidate(f0) -> None:
    x = utterance(silence(0.3), vowel(0.45, f0), silence(0.25), vowel(0.35, f0 * 1.1),
                  silence(0.25), vowel(0.5, f0 * 0.9), silence(0.2))
    assert find_involuntary_spans(x, SR) == []


def test_a_short_isolated_voiced_word_is_kept_even_if_loud() -> None:
    # A one-syllable word ("no") with a pause on both sides is an island by itself and loud
    # relative to the burst -- but it is pitched, so it is speech.
    x = utterance(silence(0.3), vowel(0.6, 120, amp=0.2), silence(0.3),
                  vowel(0.2, 160, amp=0.3), silence(0.3), vowel(0.6, 120, amp=0.2), silence(0.2))
    assert find_involuntary_spans(x, SR) == []


def test_a_plosive_release_after_a_closure_does_not_split_off_a_word() -> None:
    # "ca-t": the closure gap (90 ms) is inside GAP_MS, so the unvoiced release stays attached.
    release = band_noise(0.03, 1500, 6000, attack=0.002, decay=0.01, amp=0.3)
    x = utterance(silence(0.3), vowel(0.4, 125), silence(0.09), release, silence(0.25),
                  vowel(0.5, 125), silence(0.2))
    assert find_involuntary_spans(x, SR) == []


def test_a_cough_glued_to_a_word_is_left_alone() -> None:
    # No quiet gap: the cough merges into the word's island, which is pitched. Missing a cough
    # is the cheap error; cutting into a word is the expensive one.
    x = utterance(silence(0.3), vowel(0.5), cough(), vowel(0.6, 120), silence(0.2))
    assert find_involuntary_spans(x, SR) == []


def test_a_cough_only_burst_is_left_alone() -> None:
    # Nothing in it proves the cut right; the Hallucination Guard owns this case.
    x = utterance(silence(0.3), cough(), silence(0.2))
    assert find_involuntary_spans(x, SR) == []


def test_a_burst_that_is_mostly_non_speech_is_left_alone() -> None:
    # One short word and three coughs: the detector is more likely wrong than the speaker.
    x = utterance(silence(0.2), vowel(0.25), silence(0.2), cough(), silence(0.2), cough(),
                  silence(0.2), cough(), silence(0.2))
    assert find_involuntary_spans(x, SR) == []


def test_a_pitchless_whisper_burst_is_left_alone() -> None:
    # Whispered speech has no pitch at all, so there is no voiced speech to anchor a cut on.
    whisper = band_noise(0.5, 300, 4000, attack=0.05, decay=10.0, amp=0.1)
    x = utterance(silence(0.3), whisper, silence(0.3), whisper, silence(0.3), cough(), silence(0.2))
    assert find_involuntary_spans(x, SR) == []


def test_a_quiet_isolated_hiss_next_to_loud_speech_is_not_a_cough() -> None:
    # "shh" at a fraction of the speech level: fails the energy gate.
    shh = band_noise(0.4, 4000, 7500, attack=0.05, decay=10.0, amp=0.02)
    assert find_involuntary_spans(_sentence_with(shh), SR) == []


def test_a_sound_longer_than_the_island_cap_is_not_a_candidate() -> None:
    long_noise = band_noise(1.2, 300, 1400, attack=0.005, decay=0.5, amp=0.7)
    assert find_involuntary_spans(_sentence_with(long_noise), SR) == []


# ---- robustness -------------------------------------------------------------

@pytest.mark.parametrize(
    "x",
    [
        np.zeros(0, dtype=np.float32),
        np.zeros(10, dtype=np.float32),
        np.zeros(SR, dtype=np.float32),
        np.full(SR, np.nan, dtype=np.float32),
        silence(1.0).astype(np.float32),
    ],
)
def test_degenerate_audio_is_returned_untouched(x) -> None:
    out, spans = excise_involuntary_audio(x, SR)
    assert out is x and spans == []


def test_the_classifier_is_the_one_in_excise() -> None:
    # The audio layer adds segmentation and feature extraction only; the decision stays in the
    # pure, already-tested classifier, so the two cannot drift apart.
    assert iv.is_involuntary_vocalization.__module__ == "yazses.involuntary.excise"


# ---- daemon wiring ----------------------------------------------------------

class _Recorder:
    def __init__(self, audio):
        self._audio = audio

    def stop(self):
        return self._audio


class _Engine:
    """Records the audio the decoder was handed."""

    def __init__(self):
        self.seen: list[np.ndarray] = []

    def transcribe(self, audio, *args, **kwargs):
        self.seen.append(np.array(audio, copy=True))
        return "hello world"


class _Injector:
    def __init__(self):
        self.texts: list[str] = []

    def inject(self, text):
        self.texts.append(text)

    def inject_backspaces(self, count):
        pass

    def inject_key_sequence(self, keys):
        pass


def _daemon(audio, *, enabled: bool):
    from yazses.config import Config
    from yazses.core.daemon import Daemon
    from yazses.platform import get_platform

    cfg = Config()
    cfg.filters.disfluency.enabled = False
    cfg.streaming.enabled = False
    cfg.involuntary.enabled = enabled
    d = Daemon(config=cfg, platform=get_platform())
    d._recorder = _Recorder(audio)
    d._engine = _Engine()
    d._padding_buffer = None
    d._injector = _Injector()
    return d


def _decoded_without_lead_in(d) -> np.ndarray:
    seen = d._engine.seen[-1]
    lead = int(d._config.accessibility.pre_speech_padding_ms * SR / 1000)
    return seen[lead:]


def test_enabled_daemon_hands_the_decoder_audio_with_the_cough_silenced() -> None:
    x = _sentence_with(cough())
    d = _daemon(x, enabled=True)
    d._on_hold_end()
    heard = _decoded_without_lead_in(d)
    assert d._injector.texts == ["hello world"]
    assert heard.shape == x.shape and not np.array_equal(heard, x)
    assert not np.any(heard[int(1.1 * SR):int(1.25 * SR)])        # inside the cough
    assert np.array_equal(heard[: int(0.9 * SR)], x[: int(0.9 * SR)])   # speech untouched


def test_disabled_daemon_decodes_exactly_what_was_recorded() -> None:
    x = _sentence_with(cough())
    d = _daemon(x, enabled=False)
    d._on_hold_end()
    assert np.array_equal(_decoded_without_lead_in(d), x)


def test_a_failing_detector_never_breaks_dictation(monkeypatch) -> None:
    def boom(*_a, **_k):
        raise RuntimeError("detector exploded")

    monkeypatch.setattr(iv, "excise_involuntary_audio", boom)
    x = _sentence_with(cough())
    d = _daemon(x, enabled=True)
    d._on_hold_end()
    assert d._injector.texts == ["hello world"]
    assert np.array_equal(_decoded_without_lead_in(d), x)


def test_the_feature_is_registered_off_and_reachable() -> None:
    from yazses.config import Config
    from yazses.system.features import feature_status, unwired_slugs

    assert Config().involuntary.enabled is False
    assert "involuntary" not in unwired_slugs()
    row = next(f for f in feature_status(Config()) if f.slug == "involuntary")
    assert row.wired and not row.on


def test_features_enable_writes_the_involuntary_key_instead_of_refusing() -> None:
    from yazses.config import Config
    from yazses.settingsui.controller import SettingsController

    writes: list[tuple] = []
    ctl = SettingsController(Config, lambda *a: writes.append(a), lambda mods: [])
    result = ctl.set_enabled("involuntary", True)
    assert result.ok and result.enabled
    assert writes == [("involuntary", "enabled", "true", False)]
