"""A hold-release with no hold-start must type nothing -- not the previous dictation again.

Seen live on 2026-10-18 with the eyes-closed face switch: one deliberate closure was typed, then
two more "Recording stopped" lines with no "Recording started" re-typed the same 9.9 s clip
(identical duration and level). Two things combined. `SwitchMapper` delivers a release whose
press the safety gate refused (deliberately: dropping a release is the worse failure), and
`AudioRecorder.stop()` kept its chunks, so `_on_hold_end` transcribed the last clip again.
"""
from __future__ import annotations

import numpy as np
import pytest

from yazses.audio import recorder
from yazses.audio.recorder import AudioRecorder
from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.platform import get_platform
from yazses.platform.base import TrayState


@pytest.fixture()
def sd(mocker):
    fake = mocker.MagicMock(name="sounddevice")
    mocker.patch.object(recorder, "_sd", return_value=fake)
    return fake


def test_stop_hands_the_clip_over_once(sd):
    rec = AudioRecorder()
    rec.start()
    rec._callback(np.ones((10, 1), dtype=np.float32), 10, None, None)
    assert rec.has_clip
    assert rec.stop().shape[0] == 10
    assert not rec.has_clip
    assert rec.stop().size == 0, "a second stop() returned the previous clip"


class _Engine:
    def __init__(self):
        self.calls = 0

    def transcribe(self, *args, **kwargs):
        self.calls += 1
        return "this sentence is written by my voice"


class _Injector:
    def __init__(self):
        self.injected: list[str] = []

    def inject(self, text):
        self.injected.append(text)

    def inject_backspaces(self, count):
        pass

    def inject_key_sequence(self, keys):
        pass


def _daemon(sd) -> Daemon:
    cfg = Config()
    cfg.filters.disfluency.enabled = False
    cfg.streaming.enabled = False
    cfg.injection.continuation_window_ms = 0
    d = Daemon(config=cfg, platform=get_platform())
    d._recorder = AudioRecorder()
    d._engine = _Engine()
    d._padding_buffer = None
    d._injector = _Injector()
    d._state.target_ok = True
    d._detect_target_async = lambda: None
    return d


def test_a_stray_release_after_a_dictation_types_nothing(sd):
    d = _daemon(sd)
    d._on_hold_start(0)
    assert d._state.state is TrayState.RECORDING
    loud = np.full((16000, 1), 0.5, dtype=np.float32)
    d._recorder._callback(loud, 16000, None, None)
    d._on_hold_end()
    assert len(d._injector.injected) == 1 and d._engine.calls == 1

    streak = d._silent_streak.streak
    d._on_hold_end()  # the release whose press the gate refused
    d._on_hold_end()
    assert len(d._injector.injected) == 1, "the last dictation was typed again"
    assert d._engine.calls == 1, "a stray release re-ran speech recognition"
    assert d._silent_streak.streak == streak, "a stray release counted as a silent clip"
