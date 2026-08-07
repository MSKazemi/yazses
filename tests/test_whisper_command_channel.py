"""Sotto-voce command channel: whispered burst → command, voiced → dictation.

Pins the DualVoice-pattern wiring of ADR-v2-100: `burst_is_whispered` (pure
numpy) and the daemon's routing of a whispered burst into command mode. Voiced
speech is synthesised as a harmonic (strong F0 → high voicing ratio); whisper as
white noise (no F0, flat spectrum) — the acoustic contrast the detector rests on.
"""
from __future__ import annotations

import numpy as np

from yazses.config import Config, WhispermodeConfig
from yazses.core.daemon import Daemon
from yazses.platform import get_platform
from yazses.whispermode.detect import burst_is_whispered

_FS = 16000


def _voiced(seconds: float = 1.0, f0: float = 120.0) -> np.ndarray:
    t = np.arange(int(_FS * seconds)) / _FS
    # A few harmonics of a 120 Hz fundamental — strongly periodic, steep tilt.
    x = sum(np.sin(2 * np.pi * f0 * k * t) / k for k in (1, 2, 3, 4))
    return (0.3 * x / np.max(np.abs(x))).astype(np.float32)


def _whispered(seconds: float = 1.0, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (0.2 * rng.standard_normal(int(_FS * seconds))).astype(np.float32)


# ---- pure detector ----------------------------------------------------------


def test_voiced_burst_is_not_whispered():
    assert not burst_is_whispered(_voiced(), _FS)


def test_noise_burst_is_whispered():
    assert burst_is_whispered(_whispered(), _FS)


def test_silence_is_not_whispered():
    assert not burst_is_whispered(np.zeros(_FS, dtype=np.float32), _FS)


def test_majority_rules_brief_noise_inside_voiced_speech():
    # 4/5 voiced, 1/5 noise → the median verdict stays voiced.
    burst = np.concatenate([_voiced(0.8), _whispered(0.2)])
    assert not burst_is_whispered(burst, _FS)


def test_long_burst_cost_is_capped(mocker):
    spy = mocker.spy(np, "correlate")
    burst_is_whispered(_whispered(20.0), _FS, max_frames=24)
    assert spy.call_count <= 24


# ---- config defaults --------------------------------------------------------


def test_whispermode_off_by_default_channel_on_when_enabled():
    cfg = WhispermodeConfig()
    assert cfg.enabled is False
    assert cfg.command_channel is True


# ---- daemon routing ---------------------------------------------------------


class _FakeRecorder:
    def __init__(self, audio):
        self._audio = audio

    def stop(self):
        return self._audio


class _FakeEngine:
    def __init__(self, text=""):
        self.text = text

    def transcribe(self, *args, **kwargs):
        return self.text


class _RecordingInjector:
    def __init__(self):
        self.texts = []
        self.keys = []

    def inject(self, text):
        self.texts.append(text)

    def inject_backspaces(self, count):
        pass

    def inject_key_sequence(self, keys):
        self.keys.append(keys)


def _daemon(audio: np.ndarray, text: str, **whisper_kw):
    cfg = Config()
    cfg.filters.disfluency.enabled = False
    cfg.streaming.enabled = False
    cfg.whispermode = WhispermodeConfig(enabled=True, **whisper_kw)
    d = Daemon(config=cfg, platform=get_platform())
    d._recorder = _FakeRecorder(audio)
    d._engine = _FakeEngine(text)
    d._padding_buffer = None
    inj = _RecordingInjector()
    d._injector = inj
    return d, inj


def test_whispered_burst_routes_to_command_mode():
    d, inj = _daemon(_whispered(), "undo")
    d._on_hold_end()
    assert inj.texts == []                 # never typed literally
    assert inj.keys == [["ctrl+z"]]        # dispatched as a command


def test_whispered_burst_with_unmatched_phrase_is_discarded_not_typed():
    d, inj = _daemon(_whispered(), "the quick brown fox jumps")
    d._on_hold_end()
    assert inj.texts == [] and inj.keys == []


def test_voiced_burst_still_dictates():
    d, inj = _daemon(_voiced(), "hello world")
    d._on_hold_end()
    assert inj.texts == ["hello world"] and inj.keys == []


def test_channel_off_keeps_whispered_burst_as_dictation():
    d, inj = _daemon(_whispered(), "hello world", command_channel=False)
    d._on_hold_end()
    assert inj.texts == ["hello world"]
