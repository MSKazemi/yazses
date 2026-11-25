"""The speech-presence detector is loaded during start-up, not by the first dictation.

`audio/speech_presence.py::prime_detector` runs the detector once on silence; the daemon
calls it from `_build_pipeline` only when the check will run. Measured reason in
`docs/benchmarks.md` ("The first dictation after a start"): Silero's first call is ~36 ms
slower than every later one, and that first call was the user's first burst.

Pinned here: what the prime asks of the detector, that it never raises, that it changes
no later verdict, and when the daemon does and does not call it. No model is loaded.
"""
from __future__ import annotations

import dataclasses
import types

import numpy as np
import pytest

from yazses.audio import speech_presence
from yazses.audio.speech_presence import PRIME_SECONDS, holds_no_speech, prime_detector


def test_prime_runs_the_detector_once_on_silence() -> None:
    seen: list[tuple[np.ndarray, int]] = []
    took = prime_detector(16000, detector=lambda a, sr: seen.append((a, sr)) or False)
    (audio, rate), = seen
    assert rate == 16000
    assert audio.dtype == np.float32 and audio.size == int(16000 * PRIME_SECONDS)
    assert not audio.any()
    assert took is not None and took >= 0.0


def test_prime_never_raises_and_a_broken_detector_still_fails_open() -> None:
    def broken(audio, sr):
        raise RuntimeError("no onnxruntime")

    assert prime_detector(16000, detector=broken) is not None
    # And the gate it primes still decodes the burst, as it always did.
    assert holds_no_speech(np.ones(16000, dtype=np.float32), 16000, detector=broken) is False


def test_priming_changes_no_later_verdict() -> None:
    calls: list[int] = []

    def detector(audio, sr):
        calls.append(audio.size)
        return bool(audio.size == 3)

    burst = np.ones(3, dtype=np.float32)
    before = holds_no_speech(burst, 16000, detector=detector)
    prime_detector(16000, detector=detector)
    assert holds_no_speech(burst, 16000, detector=detector) is before is True


# ---- the daemon ----------------------------------------------------------------------


@pytest.fixture
def build(monkeypatch: pytest.MonkeyPatch):
    import yazses.core.daemon as daemon_mod
    import yazses.inject.auto as inject_auto
    from yazses.platform import get_platform

    primed: list[int] = []
    monkeypatch.setattr(daemon_mod, "prime_detector", lambda rate: primed.append(rate) or 1.0)
    monkeypatch.setattr(daemon_mod, "build_engine", lambda stt: types.SimpleNamespace(name="stub"))
    monkeypatch.setattr(inject_auto, "apply_injection_config", lambda injection: None)
    platform = dataclasses.replace(
        get_platform(),
        injector_factory=lambda: types.SimpleNamespace(name="stub"),
        hotkey_factory=lambda *a: types.SimpleNamespace(run=lambda: None, stop=lambda: None),
    )
    monkeypatch.setattr(platform.lifecycle, "clear_pid", lambda: None)
    made = []

    def _build(cfg):
        daemon = daemon_mod.Daemon(config=cfg, platform=platform)
        made.append(daemon)
        monkeypatch.setattr(daemon, "_announce_model_download", lambda cfg: None)
        daemon._build_pipeline()
        return primed

    yield _build
    for daemon in made:
        daemon._shutdown()


def test_a_default_daemon_primes_the_detector_at_start(build) -> None:
    from yazses.config import Config

    assert build(Config()) == [16000]


@pytest.mark.parametrize("change", [
    lambda c: setattr(c.accessibility, "speech_presence_check", False),
    lambda c: setattr(c.accessibility, "dysfluency_friendly", True),
    lambda c: (setattr(c.whispermode, "enabled", True),
               setattr(c.whispermode, "command_channel", True)),
])
def test_a_daemon_that_will_not_run_the_check_never_loads_the_detector(build, change) -> None:
    from yazses.config import Config

    cfg = Config()
    change(cfg)
    assert build(cfg) == []


def test_the_prime_goes_through_the_detector_the_bursts_use(monkeypatch) -> None:
    seen: list[int] = []
    monkeypatch.setattr(speech_presence, "_default_detector",
                        lambda audio, sr: seen.append(audio.size) or None)
    prime_detector(16000)
    assert seen == [int(16000 * PRIME_SECONDS)]
