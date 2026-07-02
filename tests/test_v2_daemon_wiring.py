"""Daemon wiring for the v2 features that integrate into the pipeline.

Drives the real ``_on_hold_end`` with fakes to prove: Voiceprint Mind biasing
composes the STT ``initial_prompt``, and the Cocktail Filter gate drops
non-target-speaker frames before STT. Off by default → unchanged behaviour.
"""
from __future__ import annotations

import numpy as np

from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.platform import get_platform
from yazses.voiceprint.embedding import Embedding


class _FakeRecorder:
    def __init__(self, audio):
        self._audio = audio

    def stop(self):
        return self._audio


class _CapEngine:
    """Captures the initial_prompt and the audio length it was given."""

    def __init__(self):
        self.prompt = "UNSET"
        self.audio_len = -1

    def transcribe(self, audio, sample_rate=16000, initial_prompt=None, task=None):
        self.prompt = initial_prompt
        self.task = task
        self.audio_len = int(np.asarray(audio).size)
        return "hello world"


class _RecordingInjector:
    def __init__(self):
        self.calls = []
        self.key_calls = []

    def inject(self, text):
        self.calls.append(text)

    def inject_backspaces(self, n):
        pass

    def inject_key_sequence(self, keys):
        self.key_calls.append(keys)


def _base_daemon(audio):
    cfg = Config()
    cfg.filters.disfluency.enabled = False
    cfg.commands.enabled = False
    cfg.streaming.enabled = False
    cfg.injection.continuation_window_ms = 0
    d = Daemon(config=cfg, platform=get_platform())
    d._recorder = _FakeRecorder(audio)
    d._engine = _CapEngine()
    d._padding_buffer = None
    d._injector = _RecordingInjector()
    return d


# ---- Voiceprint Mind biasing -----------------------------------------------

def test_personalize_biases_initial_prompt(monkeypatch):
    monkeypatch.setenv("YAZSES_VOCABULARY", "Kubernetes,kubectl")
    d = _base_daemon(np.full(16000, 0.5, dtype="float32"))
    d._config.personalize.enabled = True
    d._config.stt.initial_prompt = "Notes."
    d._on_hold_end()
    assert "Kubernetes" in d._engine.prompt
    assert "kubectl" in d._engine.prompt
    assert "Notes." in d._engine.prompt


def test_personalize_off_passes_configured_prompt():
    d = _base_daemon(np.full(16000, 0.5, dtype="float32"))
    d._config.personalize.enabled = False
    d._config.stt.initial_prompt = "Plain prompt."
    d._on_hold_end()
    # The configured prompt is preserved, and the app name is always primed so
    # Whisper recognises the spoken word "YazSes" (built-in vocabulary).
    assert "Plain prompt." in d._engine.prompt
    assert "YazSes" in d._engine.prompt


# ---- Cocktail Filter gate ---------------------------------------------------

class _SignEmbedder:
    name = "fake"

    def embed(self, frame, sample_rate=16000):
        v = np.array([1.0, 0.0] if frame[0] >= 0 else [0.0, 1.0], dtype="float32")
        return Embedding(vector=v)


def test_cocktail_gate_drops_interferer_before_stt():
    # First half target (positive), second half interferer (negative).
    audio = np.concatenate([
        np.full(8000, 0.5, dtype="float32"),
        np.full(8000, -0.5, dtype="float32"),
    ])
    d = _base_daemon(audio)
    d._config.cocktail.enabled = True
    d._config.cocktail.window_ms = 10
    d._config.accessibility.pre_speech_padding_ms = 0  # isolate the gate (no lead-in)
    d._embedder = _SignEmbedder()
    d._voiceprint = np.array([1.0, 0.0], dtype="float32")
    d._on_hold_end()
    # The engine only ever saw the target (positive) half.
    assert d._engine.audio_len == 8000


def test_cocktail_dormant_without_voiceprint_passes_all_audio():
    audio = np.full(16000, 0.5, dtype="float32")
    d = _base_daemon(audio)
    d._config.cocktail.enabled = True
    d._config.accessibility.pre_speech_padding_ms = 0  # isolate the gate (no lead-in)
    d._embedder = _SignEmbedder()
    d._voiceprint = None  # not enrolled → gate is a no-op
    d._on_hold_end()
    assert d._engine.audio_len == 16000


def test_onset_lead_in_prepended_before_stt():
    # A silence lead-in is prepended before decode so faster-whisper doesn't drop
    # the opening word on an abrupt onset. 300 ms @ 16 kHz = 4800 samples.
    audio = np.full(16000, 0.5, dtype="float32")
    d = _base_daemon(audio)
    d._config.accessibility.pre_speech_padding_ms = 300
    d._on_hold_end()
    assert d._engine.audio_len == 16000 + 4800


def test_onset_lead_in_disabled_when_zero():
    audio = np.full(16000, 0.5, dtype="float32")
    d = _base_daemon(audio)
    d._config.accessibility.pre_speech_padding_ms = 0
    d._on_hold_end()
    assert d._engine.audio_len == 16000


# ---- Dedicated command key (force-command mode) ----------------------------

class _FixedEngine:
    """Returns a fixed transcript so we can drive the classifier."""

    def __init__(self, text):
        self._text = text

    def transcribe(self, audio, sample_rate=16000, initial_prompt=None, task=None):
        return self._text


def _command_daemon(text):
    d = _base_daemon(np.full(16000, 0.5, dtype="float32"))
    d._config.commands.enabled = True
    d._engine = _FixedEngine(text)
    return d


def test_command_mode_dispatches_matching_command_not_text():
    d = _command_daemon("save file")
    d._command_mode = True
    d._on_hold_end()
    inj = d._injector
    assert ["ctrl+s"] in inj.key_calls   # 'save' fired Ctrl+S
    assert inj.calls == []               # nothing was typed as literal text
    # flag is consumed so the next burst is normal dictation
    assert d._command_mode is False


def test_command_mode_ignores_unmatched_phrase():
    d = _command_daemon("hello world this is just talking")
    d._command_mode = True
    d._on_hold_end()
    inj = d._injector
    assert inj.calls == []        # not typed
    assert inj.key_calls == []    # no command fired — ignored


def test_without_command_mode_same_phrase_is_typed():
    # The exact phrase that would be a no-op in command mode is typed normally.
    d = _command_daemon("hello world this is just talking")
    d._command_mode = False
    d._on_hold_end()
    assert d._injector.calls == ["hello world this is just talking"]


def _daemon_with_fake_factory(command_key, dictation="right_alt"):
    from types import SimpleNamespace

    from yazses.config import Config
    from yazses.core.daemon import Daemon
    from yazses.platform import get_platform

    built = []

    def fake_factory(key, threshold, on_start, on_end):
        built.append(key)
        return ("backend", key)

    cfg = Config()
    cfg.hotkey.key = dictation
    cfg.hotkey.command_key = command_key
    d = Daemon(config=cfg, platform=get_platform())
    d._platform = SimpleNamespace(hotkey_factory=fake_factory, default_hotkey="space")
    return d, cfg, built


def test_command_key_builds_second_listener_when_distinct():
    d, cfg, built = _daemon_with_fake_factory("right_ctrl")
    backend = d._make_command_hotkey(cfg, cfg.hotkey.key)
    assert backend == ("backend", "right_ctrl")
    assert built == ["right_ctrl"]


def test_no_command_key_means_no_second_listener():
    d, cfg, built = _daemon_with_fake_factory("")
    assert d._make_command_hotkey(cfg, cfg.hotkey.key) is None
    assert built == []


def test_command_key_equal_to_dictation_key_is_ignored():
    d, cfg, built = _daemon_with_fake_factory("right_alt", dictation="right_alt")
    assert d._make_command_hotkey(cfg, cfg.hotkey.key) is None
    assert built == []


def test_command_hold_start_arms_mode():
    d = _base_daemon(np.full(16000, 0.5, dtype="float32"))
    d._tts = None
    d._command_mode = False
    d._on_command_hold_start(0)
    assert d._command_mode is True
