"""A burst that is loud but holds no speech must not reach the decoder (#598).

Whisper does not answer a burst of fan noise with nothing: it answers with the words it
was primed with. Reproduced 2026-10-18 with the real ``small`` model on synthetic audio
only (seeded white / brown / hum noise, mean level 0.01-0.03, no speech anywhere): the
built-in vocabulary prompt came back as the transcript for every one, including levels
the default energy gate (0.01) lets through. A personal vocabulary came back the same way.

Three things are pinned here:

* the policy: fail open, exempt the modes built for voices a detector under-hears;
* the daemon: a no-speech burst is discarded *before* the decoder, even when the decoder
  would return the prompt, and a burst with speech still decodes and types;
* the real detector, on seeded noise and on the repo's public-domain speech sample, so the
  claim "noise is rejected and speech is not" is not only a statement about a stub.
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import pytest

from tests.decoder_stack import needs_faster_whisper
from yazses.audio import speech_presence
from yazses.audio.speech_presence import holds_no_speech, speech_check_applies
from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.platform import get_platform
from yazses.stt.vocabulary import BUILTIN_PROMPT

# Captured at import, before any fixture replaces it, so a test can ask for the real one.
_REAL_DETECTOR = speech_presence._default_detector

JFK = Path(__file__).resolve().parents[1] / "data" / "librispeech-sample" / "jfk.wav"


# ---- the policy --------------------------------------------------------------------


@pytest.mark.parametrize(
    "verdict,expected",
    [(True, True), (False, False), (None, False)],
)
def test_only_a_positive_finding_of_no_speech_drops_the_burst(verdict, expected) -> None:
    assert holds_no_speech(np.zeros(10), 16000, detector=lambda a, sr: verdict) is expected


def test_a_detector_that_raises_fails_open() -> None:
    def boom(_a, _sr):
        raise RuntimeError("onnx runtime is not installed")

    assert holds_no_speech(np.zeros(10), 16000, detector=boom) is False


def test_the_check_applies_by_default_and_can_be_switched_off() -> None:
    assert speech_check_applies(enabled=True) is True
    assert speech_check_applies(enabled=False) is False


@pytest.mark.parametrize("mode", ["whisper_mode", "dysfluency_friendly", "sotto_voce"])
def test_the_modes_built_for_voices_a_detector_under_hears_are_exempt(mode) -> None:
    assert speech_check_applies(enabled=True, **{mode: True}) is False


# ---- the daemon --------------------------------------------------------------------


class _Recorder:
    def __init__(self, audio):
        self._audio = audio

    def stop(self):
        return self._audio


class _Engine:
    """Answers every decode with the built-in prompt, as Whisper does on non-speech."""

    def __init__(self, text=BUILTIN_PROMPT):
        self.text = text
        self.calls = 0

    def transcribe(self, *_a, **_k):
        self.calls += 1
        return self.text

    def transcribe_words(self, *_a, **_k):
        self.calls += 1
        return self.text, []


class _Injector:
    def __init__(self):
        self.calls = []

    def inject(self, text):
        self.calls.append(text)

    def inject_backspaces(self, count):
        pass

    def inject_key_sequence(self, keys):
        pass


def _daemon(monkeypatch, *, verdict, configure=lambda cfg: None, text=BUILTIN_PROMPT, audio=None):
    cfg = Config()
    cfg.filters.disfluency.enabled = False
    cfg.commands.enabled = False
    cfg.streaming.enabled = False
    cfg.injection.continuation_window_ms = 0
    configure(cfg)
    monkeypatch.setattr(
        speech_presence, "_default_detector",
        _REAL_DETECTOR if verdict == "real" else (lambda _a, _sr: verdict),
    )
    d = Daemon(config=cfg, platform=get_platform())
    # Loud enough to clear the 0.01 energy gate: the case the energy gate cannot decide.
    d._recorder = _Recorder(
        np.full(16000, 0.05, dtype="float32") if audio is None else audio
    )
    d._engine = _Engine(text)
    d._padding_buffer = None
    d._injector = _Injector()
    return d


def test_a_loud_burst_with_no_speech_is_never_decoded_or_typed(monkeypatch) -> None:
    d = _daemon(monkeypatch, verdict=True)
    d._on_hold_end()
    assert d._engine.calls == 0, "the decoder was reached with audio holding no speech"
    assert d._injector.calls == []


def test_the_exact_prompt_is_typed_when_the_audio_does_hold_speech(monkeypatch) -> None:
    """A user may really say the sentence; the rule is about the audio, not the text."""
    d = _daemon(monkeypatch, verdict=False)
    d._on_hold_end()
    assert d._engine.calls == 1
    assert d._injector.calls == [BUILTIN_PROMPT]


def test_a_detector_that_cannot_run_decodes_as_before(monkeypatch) -> None:
    d = _daemon(monkeypatch, verdict=None)
    d._on_hold_end()
    assert d._engine.calls == 1
    assert d._injector.calls == [BUILTIN_PROMPT]


@needs_faster_whisper
def test_seeded_noise_through_the_real_detector_and_a_decoder_that_echoes_the_prompt(
    monkeypatch,
) -> None:
    """The acceptance case in #598, end to end but for the model itself: audio above the
    amplitude gate, a decoder that returns the exact built-in prompt, the real speech
    detector. Nothing may be typed."""
    audio = _noise("white", 3.0, 0.03, seed=5)
    d = _daemon(monkeypatch, verdict="real", audio=audio)
    d._on_hold_end()
    assert d._engine.calls == 0
    assert d._injector.calls == []


@needs_faster_whisper
def test_real_speech_through_the_real_detector_still_types(monkeypatch) -> None:
    d = _daemon(monkeypatch, verdict="real", audio=_jfk()[: 8 * 16000], text="And so, my fellow Americans,")
    d._on_hold_end()
    assert d._injector.calls == ["And so, my fellow Americans,"]


def test_the_config_key_turns_the_check_off(monkeypatch) -> None:
    d = _daemon(
        monkeypatch, verdict=True,
        configure=lambda cfg: setattr(cfg.accessibility, "speech_presence_check", False),
    )
    d._on_hold_end()
    assert d._engine.calls == 1


def test_whisper_mode_is_exempt(monkeypatch) -> None:
    d = _daemon(
        monkeypatch, verdict=True,
        configure=lambda cfg: setattr(cfg.accessibility, "dysfluency_friendly", True),
    )
    d._on_hold_end()
    assert d._engine.calls == 1


def test_a_no_speech_discard_is_logged_with_metrics_and_no_text(monkeypatch, caplog) -> None:
    import logging

    d = _daemon(monkeypatch, verdict=True)
    with caplog.at_level(logging.INFO, logger="yazses.core.daemon"):
        d._on_hold_end()
    line = next(r.getMessage() for r in caplog.records if "No speech in a" in r.getMessage())
    assert "level 0.0500" in line and "1.0s" in line
    assert BUILTIN_PROMPT not in caplog.text


# ---- the real detector --------------------------------------------------------------


def _noise(kind: str, secs: float, mean_abs: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(16000 * secs)
    x = rng.standard_normal(n).astype(np.float32)
    if kind == "brown":
        x = np.cumsum(x)
        x -= np.convolve(x, np.ones(2000) / 2000, mode="same")
    return (x / np.abs(x).mean() * mean_abs).astype(np.float32)


def _jfk() -> np.ndarray:
    with wave.open(str(JFK)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768


@needs_faster_whisper
@pytest.mark.parametrize("kind", ["white", "brown"])
@pytest.mark.parametrize("secs", [0.5, 1.0, 3.0])
@pytest.mark.parametrize("level", [0.012, 0.03])
def test_the_real_detector_rejects_seeded_noise_above_the_energy_gate(
    monkeypatch, kind, secs, level
) -> None:
    monkeypatch.setattr(speech_presence, "_default_detector", _REAL_DETECTOR)
    audio = _noise(kind, secs, level, seed=99)
    assert float(np.abs(audio).mean()) >= Config().accessibility.vad_threshold
    assert holds_no_speech(audio, 16000) is True


@needs_faster_whisper
@pytest.mark.parametrize("gain", [1.0, 0.1, 0.02])
def test_the_real_detector_keeps_speech_even_when_it_is_quiet(monkeypatch, gain) -> None:
    monkeypatch.setattr(speech_presence, "_default_detector", _REAL_DETECTOR)
    assert holds_no_speech(_jfk()[: 8 * 16000] * gain, 16000) is False


@needs_faster_whisper
def test_the_real_detector_keeps_a_short_snippet_of_speech(monkeypatch) -> None:
    monkeypatch.setattr(speech_presence, "_default_detector", _REAL_DETECTOR)
    assert holds_no_speech(_jfk()[16000 : int(1.8 * 16000)], 16000) is False


# ---- every activation shares the one gate (#598) --------------------------------------


def _daemon_methods() -> dict:
    import ast
    import inspect

    import yazses.core.daemon as mod

    tree = ast.parse(inspect.getsource(mod))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Daemon")
    return {fn.name: fn for fn in cls.body if isinstance(fn, ast.FunctionDef)}


def _decoder_calls(fn) -> list[int]:
    import ast

    return sorted(
        n.lineno
        for n in ast.walk(fn)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr in {"transcribe", "transcribe_words", "commit"}
        and "engine" in ast.dump(n.func.value)
    )


def test_the_gate_runs_before_the_first_decode_in_on_hold_end() -> None:
    import ast

    fn = _daemon_methods()["_on_hold_end"]
    gate = [
        n.lineno for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "holds_no_speech"
    ]
    assert gate, "_on_hold_end never asks whether the burst holds speech"
    assert gate[0] < _decoder_calls(fn)[0], "the speech check must precede the decoder"


def test_no_other_burst_reaches_the_decoder_around_the_gate() -> None:
    """Hotkey, face gesture and the command key all end in ``_on_hold_end``, so one gate
    covers them. A new method that decodes a recorded burst would bypass it: judge it."""
    deciders = {name for name, fn in _daemon_methods().items() if _decoder_calls(fn)}
    assert deciders == {"_on_hold_end", "_record_respeak", "_ask_human_listener"}, (
        f"{sorted(deciders)}: a Daemon method that decodes audio is not behind the "
        "speech-presence gate. Route it through _on_hold_end or apply the gate there "
        "(the other two are the re-speak flow and the ask-a-human listener)."
    )


def test_a_no_speech_burst_in_streaming_mode_removes_the_partials_already_typed(
    monkeypatch,
) -> None:
    """Streaming partials carry no prompt (``decode_window`` passes none), so they cannot
    echo it, but they are typed live during the hold. The discard must take them back."""

    class _StreamInjector:
        def __init__(self):
            self.cancelled = 0
            self.committed = []

        def cancel(self):
            self.cancelled += 1

        def commit(self, text):
            self.committed.append(text)

    class _StreamEngine:
        def request_stop(self):
            pass

        def commit(self):
            raise AssertionError("a no-speech burst must not be decoded")

    d = _daemon(
        monkeypatch, verdict=True,
        configure=lambda cfg: setattr(cfg.streaming, "enabled", True),
    )
    d._stream_engine = _StreamEngine()
    inj = _StreamInjector()
    d._stream_injector = inj
    d._on_hold_end()
    assert inj.cancelled == 1 and inj.committed == []
    assert d._injector.calls == []


# ---- the real model, when one is already on this machine ------------------------------


def _local_engine(monkeypatch):
    """A real tiny.en engine from the local cache, or skip. Never downloads."""
    # faster_whisper imports huggingface_hub at module scope, and the hub copies
    # HF_HUB_OFFLINE into a module constant at that first import. Import it here,
    # under the real environment, and patch the constant alongside the variable:
    # setting only the variable first left the constant True for the rest of the
    # process, so a later cache-first test saw offline mode already requested.
    pytest.importorskip("faster_whisper")
    from huggingface_hub import constants as hub_constants

    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setattr(hub_constants, "HF_HUB_OFFLINE", True)
    from yazses.stt.faster_whisper import FasterWhisperEngine

    try:
        return FasterWhisperEngine("tiny.en")
    except Exception as exc:  # noqa: BLE001 - no cached model on this machine
        pytest.skip(f"tiny.en is not in the local cache: {type(exc).__name__}")


@needs_faster_whisper
def test_with_the_real_model_noise_types_nothing_and_speech_still_types(monkeypatch) -> None:
    """The #598 acceptance case on a real decoder (skipped where no model is cached; the
    suite never downloads one).

    The ungated decode is checked first: if this machine's model does not echo the prompt
    on this noise, there is nothing for the gate to prove and the test says so by skipping
    rather than passing vacuously.
    """
    engine = _local_engine(monkeypatch)
    noise = _noise("white", 3.0, 0.03, seed=5)
    if "YazS" not in engine.transcribe(noise, 16000, initial_prompt=BUILTIN_PROMPT):
        pytest.skip("this model did not echo the prompt on this noise; nothing to prove")

    d = _daemon(monkeypatch, verdict="real", audio=noise)
    d._engine = engine
    d._on_hold_end()
    assert d._injector.calls == []

    d = _daemon(monkeypatch, verdict="real", audio=_jfk()[: 8 * 16000])
    d._engine = engine
    d._on_hold_end()
    assert d._injector.calls and "Americans" in d._injector.calls[0]


@needs_faster_whisper
def test_a_quiet_one_word_burst_is_not_discarded_at_the_gates_threshold(monkeypatch) -> None:
    """The threshold is lower than Silero's default so a short, quiet word is kept. The
    word "my" of the JFK sample (0.15 s of lead either side, as a press and release
    leaves it) at one tenth volume is judged to hold no speech by the library default
    (0.5) and to hold speech at the gate's threshold; the first assertion is what makes
    the second one mean something."""
    from yazses.recimport.audio_io import holds_no_speech as library_default

    word = _jfk()[int(0.71 * 16000) : int(1.35 * 16000)] * 0.1
    assert library_default(word, 16000) is True, "the library default no longer drops it"
    monkeypatch.setattr(speech_presence, "_default_detector", _REAL_DETECTOR)
    assert holds_no_speech(word, 16000) is False
