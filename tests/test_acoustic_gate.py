"""Acoustic Context Profiles wired into the daemon (ADR-v2-039, amended).

Off: nothing changes and nothing is imported by the daemon. On: a hold over flat room noise that
sits near the configured gate types nothing, a hold with speech in it types as before, the
configured threshold and config.toml are never touched, and a failing profile means the gate the
user configured, never a crash.

Audio is numpy-only synthesis (Gaussian room noise plus a harmonic "voice" with an envelope), so
no optional dependency is needed and the suite stays offline.
"""
from __future__ import annotations

import numpy as np
import pytest

from yazses.acoustic.gate import AcousticGate, frame_levels

SR = 16000
#: A gate in the range the owner's microphone is calibrated to (mean |x| 0.003-0.005 for speech).
GATE = 0.0024


def _noise(dur: float, mean_abs: float, seed: int = 3) -> np.ndarray:
    """Gaussian noise whose mean |x| is ``mean_abs`` (E|x| = sigma * sqrt(2/pi))."""
    sigma = mean_abs / np.sqrt(2.0 / np.pi)
    return (np.random.default_rng(seed).standard_normal(int(dur * SR)) * sigma).astype(np.float32)


def _voice(dur: float, amp: float) -> np.ndarray:
    t = np.arange(int(dur * SR)) / SR
    wave = sum(np.sin(2 * np.pi * 140 * k * t) / k for k in (1, 2, 3, 4))
    env = np.sin(np.pi * t / dur) ** 2
    return (amp * env * wave / 2.0).astype(np.float32)


def _speech_in_room(room_mean: float, amp: float = 0.06, seed: int = 3) -> np.ndarray:
    x = _noise(2.0, room_mean, seed)
    x[int(0.5 * SR):int(1.0 * SR)] += _voice(0.5, amp)
    x[int(1.2 * SR):int(1.6 * SR)] += _voice(0.4, amp)
    return x


# ---- the numpy half --------------------------------------------------------------------

def test_frame_levels_are_the_mean_abs_the_gate_compares() -> None:
    x = np.concatenate([np.full(320, 0.5), np.full(320, -0.25), np.full(100, 9.0)]).astype(np.float32)
    assert frame_levels(x, SR) == pytest.approx([0.5, 0.25])      # the ragged tail is dropped
    assert frame_levels(np.zeros(10, np.float32), SR) == []


def test_a_burst_too_short_to_hear_a_floor_in_changes_nothing() -> None:
    g = AcousticGate(min_stable=1)
    d = g.decide(_noise(0.1, 0.003), SR, GATE)
    assert d.floor is None and d.gate == GATE and d.scene == "quiet"


def test_stationary_room_noise_is_flat_by_the_classifiers_own_measure() -> None:
    """The 2.5 spread cut-off is only meaningful if real stationary noise sits far below it."""
    from yazses.acoustic.scene import SPEECH_SPREAD, floor_estimate

    for seed in range(20):
        est = floor_estimate(frame_levels(_noise(2.0, 0.003, seed), SR))
        assert est is not None and est.spread < 1.6 < SPEECH_SPREAD, est.spread


def test_speech_in_a_noisy_room_keeps_the_configured_gate() -> None:
    g = AcousticGate(min_stable=1)
    d = g.decide(_speech_in_room(0.003), SR, GATE)
    assert d.scene == "noisy" and d.gate == GATE


def test_the_status_payload_is_numbers_and_a_label() -> None:
    g = AcousticGate(min_stable=1)
    assert g.status() is None
    g.decide(_noise(2.0, 0.003), SR, GATE)
    st = g.status()
    assert st is not None
    assert set(st) == {"scene", "floor", "base_gate", "gate", "bursts"}
    assert st["scene"] == "noisy" and st["base_gate"] == GATE and st["gate"] > GATE


# ---- the daemon -------------------------------------------------------------------------

class _Recorder:
    def __init__(self, audio):
        self._audio = audio

    def stop(self):
        return self._audio


class _Engine:
    def __init__(self):
        self.calls = 0

    def transcribe(self, audio, *args, **kwargs):
        self.calls += 1
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


def _daemon(*, enabled: bool, min_stable: int = 1):
    from yazses.config import Config
    from yazses.core.daemon import Daemon
    from yazses.platform import get_platform

    cfg = Config()
    cfg.filters.disfluency.enabled = False
    cfg.streaming.enabled = False
    cfg.accessibility.vad_threshold = GATE
    cfg.acoustic_profiles.enabled = enabled
    cfg.acoustic_profiles.min_stable = min_stable
    d = Daemon(config=cfg, platform=get_platform())
    d._recorder = _Recorder(None)
    d._engine = _Engine()
    d._padding_buffer = None
    d._injector = _Injector()
    return d


def _hold(d, audio) -> None:
    d._recorder._audio = audio
    d._on_hold_end()


def test_the_feature_is_off_by_default_and_registered_reachable() -> None:
    from yazses.config import Config
    from yazses.system.features import feature_status, unwired_slugs

    assert Config().acoustic_profiles.enabled is False
    assert "acoustic_profiles" not in unwired_slugs()
    row = next(f for f in feature_status(Config()) if f.slug == "acoustic_profiles")
    assert row.wired and not row.on


def test_off_flat_noise_above_the_configured_gate_is_decoded_exactly_as_before() -> None:
    d = _daemon(enabled=False)
    _hold(d, _noise(2.0, 0.003))
    assert d._engine.calls == 1 and d._injector.texts == ["hello world"]
    assert d._acoustic is None
    assert d._handle_status(None)["acoustic"] is None


def test_on_flat_room_noise_near_the_gate_types_nothing() -> None:
    d = _daemon(enabled=True)
    _hold(d, _noise(2.0, 0.003))
    assert d._engine.calls == 0 and d._injector.texts == []
    # Not a dead-mic symptom: no streak, no retune evidence, nothing for the user to act on.
    assert d._state.silent_streak == 0
    assert d._adaptive_vad.streak == 0
    room = d._handle_status(None)["acoustic"]
    assert room["scene"] == "noisy" and room["gate"] > room["base_gate"] == GATE


def test_on_a_hold_with_speech_in_it_still_types_even_in_a_noisy_room() -> None:
    d = _daemon(enabled=True)
    _hold(d, _speech_in_room(0.003))
    assert d._engine.calls == 1 and d._injector.texts == ["hello world"]
    assert d._handle_status(None)["acoustic"]["gate"] == GATE


def test_on_a_quiet_room_changes_nothing_at_all() -> None:
    d = _daemon(enabled=True)
    _hold(d, _speech_in_room(0.0004))
    assert d._injector.texts == ["hello world"]
    room = d._handle_status(None)["acoustic"]
    assert room["scene"] == "quiet" and room["gate"] == room["base_gate"]


def test_on_the_scene_needs_min_stable_bursts_before_the_gate_moves() -> None:
    d = _daemon(enabled=True, min_stable=3)
    for _ in range(2):
        _hold(d, _noise(2.0, 0.003))
    assert d._engine.calls == 2                       # still "quiet": hysteresis
    _hold(d, _noise(2.0, 0.003))
    assert d._engine.calls == 2 and d._handle_status(None)["acoustic"]["scene"] == "noisy"


def test_the_override_is_in_memory_only(monkeypatch) -> None:
    from yazses.system import miclevel

    def boom(*_a, **_k):
        raise AssertionError("the profile must never write config.toml")

    monkeypatch.setattr(miclevel, "update_threshold_in_config", boom)
    d = _daemon(enabled=True)
    for _ in range(5):
        _hold(d, _noise(2.0, 0.003))
    assert d._config.accessibility.vad_threshold == GATE
    assert d._engine.calls == 0


def test_a_burst_below_the_configured_gate_is_still_an_ordinary_silent_discard() -> None:
    """The profile only ever adds the new 'flat noise' reason; a dead mic keeps its own path."""
    d = _daemon(enabled=True)
    _hold(d, _noise(2.0, 0.0005))
    assert d._engine.calls == 0
    assert d._state.silent_streak == 1


def test_a_failing_profile_never_breaks_dictation(monkeypatch) -> None:
    def boom(self, *_a, **_k):
        raise RuntimeError("scene exploded")

    monkeypatch.setattr(AcousticGate, "decide", boom)
    d = _daemon(enabled=True)
    _hold(d, _noise(2.0, 0.003))
    assert d._injector.texts == ["hello world"]


def test_whisper_mode_keeps_its_lowered_gate_untouched() -> None:
    """Whisper Mode asked for quiet speech to pass; the profile must not fight it."""
    d = _daemon(enabled=True)
    d._config.continuum.enabled = True
    d._config.continuum.whisper_mode = True
    d._config.continuum.whisper_threshold_factor = 0.5
    _hold(d, _noise(2.0, 0.003))
    assert d._acoustic is None and d._injector.texts == ["hello world"]


def test_a_raised_gate_is_not_whisper_mode_to_the_speech_presence_check(monkeypatch) -> None:
    """The #598 check exempts Whisper Mode by comparing the gate to the configured one.

    A gate the profile raised differs from the configured one too, and must not be read as
    Whisper Mode: a flat burst loud enough to clear the raised gate still gets asked whether
    it holds speech, and a detector that finds none still keeps it from being typed.
    """
    from yazses.audio import speech_presence

    monkeypatch.setattr(speech_presence, "_default_detector", lambda _audio, _sr: True)
    d = _daemon(enabled=True)
    burst = _noise(2.0, 0.004)
    _hold(d, burst)
    room = d._handle_status(None)["acoustic"]
    assert room["scene"] == "noisy" and room["gate"] > GATE           # the profile raised it
    assert float(np.abs(burst).mean()) >= room["gate"]                # and the burst cleared it
    assert d._engine.calls == 0 and d._injector.texts == []           # the #598 check still ran


def _fake_platform(tmp_path, payload):
    import types

    return types.SimpleNamespace(
        name="linux",
        paths=types.SimpleNamespace(
            data_dir=tmp_path, config_file=tmp_path / "config.toml",
            ipc_socket=tmp_path / "daemon.sock",
        ),
        lifecycle=types.SimpleNamespace(is_running=lambda: True, read_pid=lambda: 4242),
        ipc_client_factory=lambda _sock: types.SimpleNamespace(call=lambda _m, **_k: payload),
    )


def _status_output(tmp_path, monkeypatch, payload) -> str:
    from typer.testing import CliRunner

    import yazses.cli as cli

    monkeypatch.setattr(cli, "get_platform", lambda: _fake_platform(tmp_path, payload))
    result = CliRunner().invoke(cli.app, ["status"])
    assert result.exit_code == 0, result.output
    return result.output


def test_yazses_status_shows_the_room_and_the_raise(tmp_path, monkeypatch) -> None:
    room = {"scene": "noisy", "floor": 0.0028, "base_gate": 0.0024, "gate": 0.0036, "bursts": 4}
    out = _status_output(tmp_path, monkeypatch, {"state": "idle", "acoustic": room})
    assert "room:" in out and "noisy" in out and "raised from 0.0024" in out


def test_yazses_status_is_silent_about_the_room_when_off_or_on_an_older_daemon(
    tmp_path, monkeypatch
) -> None:
    for payload in ({"state": "idle", "acoustic": None}, {"state": "idle"}):
        out = _status_output(tmp_path, monkeypatch, payload)
        assert "YazSes is running" in out and "room:" not in out
