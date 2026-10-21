"""Voice Guard (ADR-v2-018) is wired into the dictation path, and stays out of it when off.

Three layers, each pinned separately:

- the pure helpers in `voiceguard/admission.py` (when the guard refuses to run at all,
  and the per-burst decision from a whole-burst embedding);
- `Daemon._voiceguard_refusal`, the one daemon method that calls them;
- a real burst through `Daemon._on_hold_end`: a refused burst is never decoded and never
  typed, and records `voiceguard_rejected`; an admitted one is typed as before.

The speaker embedder is a stub that returns fixed vectors, so the thresholds here are
exercised on synthetic signals only -- nothing in this file says how often a real voice
clears `match_threshold`.
"""
from __future__ import annotations

import builtins
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from yazses.config import Config, VoiceguardConfig, VoiceprintConfig
from yazses.core.daemon import Daemon
from yazses.platform import get_platform
from yazses.voiceguard.admission import decide, inactive_reason
from yazses.voiceprint.embedding import Embedding

ME = np.array([1.0, 0.0, 0.0], dtype=np.float32)
SOMEONE_ELSE = np.array([0.0, 1.0, 0.0], dtype=np.float32)


class _Embedder:
    """Returns one fixed vector for any audio; counts the calls."""

    def __init__(self, vector: np.ndarray | None = None, error: Exception | None = None):
        self.vector = vector
        self.error = error
        self.calls = 0

    def embed(self, audio, sample_rate=16000):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return Embedding(self.vector)


def _cfg(**voiceguard) -> Config:
    base = Config()
    return replace(
        base,
        voiceguard=replace(VoiceguardConfig(), **{"enabled": True, **voiceguard}),
        voiceprint=replace(VoiceprintConfig(), enabled=True),
    )


# --- inactive_reason: the guard refuses to run rather than misjudge every burst ----------

def test_off_has_nothing_to_explain():
    assert inactive_reason(Config(), embedder_ready=False, enrolled=False) is None


def test_ready_and_enrolled_is_active():
    assert inactive_reason(_cfg(), embedder_ready=True, enrolled=True) is None


def test_no_enrolled_voiceprint_names_the_command_that_fixes_it():
    reason = inactive_reason(_cfg(), embedder_ready=True, enrolled=False)
    assert reason is not None and "yazses enroll-voice" in reason


def test_voiceprint_section_off_is_named():
    cfg = replace(_cfg(), voiceprint=VoiceprintConfig())
    reason = inactive_reason(cfg, embedder_ready=None, enrolled=True)
    assert reason is not None and "[voiceprint] enabled" in reason


def test_no_embedder_is_named():
    reason = inactive_reason(_cfg(), embedder_ready=False, enrolled=True)
    assert reason is not None and "embedder" in reason


def test_unknown_embedder_state_does_not_invent_a_problem():
    """`doctor` passes None: it does not load the model, so it must not claim one failed."""
    assert inactive_reason(_cfg(), embedder_ready=None, enrolled=True) is None


def test_fail_closed_is_refused_because_no_anti_spoof_score_exists():
    """With no anti-spoof producer, `fail_open = false` would refuse every burst."""
    reason = inactive_reason(_cfg(fail_open=False), embedder_ready=True, enrolled=True)
    assert reason is not None and "anti-spoof" in reason


# --- decide: whole-burst embedding -> cosine -> admit -----------------------------------

def _burst() -> np.ndarray:
    return np.full(16000, 0.5, dtype=np.float32)


def test_the_enrolled_speaker_is_admitted():
    d = decide(_burst(), 16000, _Embedder(ME), ME, _cfg().voiceguard)
    assert d.admit and d.reason == "admitted"


def test_another_speaker_is_refused_with_the_score_not_the_words():
    d = decide(_burst(), 16000, _Embedder(SOMEONE_ELSE), ME, _cfg().voiceguard)
    assert not d.admit
    assert "speaker mismatch" in d.reason and "0.00" in d.reason


def test_an_embedder_failure_admits_under_fail_open():
    d = decide(_burst(), 16000, _Embedder(error=RuntimeError("boom")), ME, _cfg().voiceguard)
    assert d.admit


def test_the_whole_burst_is_embedded_once():
    embedder = _Embedder(ME)
    decide(_burst(), 16000, embedder, ME, _cfg().voiceguard)
    assert embedder.calls == 1


# --- the daemon method --------------------------------------------------------------------

class _DaemonImports:
    """Records `yazses.voiceguard` imports made by `core/daemon.py` itself."""

    def __init__(self):
        self.names: list[str] = []
        self._real = builtins.__import__

    def __call__(self, name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
        if (globals or {}).get("__name__") == "yazses.core.daemon" and name.startswith(
            "yazses.voiceguard"
        ):
            self.names.append(name)
        return self._real(name, globals, locals, fromlist, level)


def _daemon(cfg: Config) -> Daemon:
    return Daemon(config=cfg, platform=get_platform())


def test_a_default_daemon_never_imports_voiceguard(monkeypatch):
    recorder = _DaemonImports()
    monkeypatch.setattr(builtins, "__import__", recorder)
    d = _daemon(Config())
    d._embedder = _Embedder(SOMEONE_ELSE)     # even with an embedder and a voiceprint
    d._voiceprint = ME                        # present, an off guard does nothing
    assert d._voiceguard_refusal(_burst()) is None
    assert recorder.names == []
    assert d._embedder.calls == 0


def test_enabled_without_a_voiceprint_lets_bursts_through_and_says_why(caplog):
    d = _daemon(_cfg())
    d._embedder = _Embedder(SOMEONE_ELSE)
    d._voiceprint = None
    with caplog.at_level("WARNING", logger="yazses.core.daemon"):
        assert d._voiceguard_refusal(_burst()) is None
        assert d._voiceguard_refusal(_burst()) is None
    warned = [r for r in caplog.records if "[voiceguard]" in r.getMessage()]
    assert len(warned) == 1, "the inactive reason is logged once, not per burst"
    assert "yazses enroll-voice" in warned[0].getMessage()
    assert d._embedder.calls == 0


def test_enabled_and_enrolled_refuses_another_speaker():
    d = _daemon(_cfg())
    d._embedder = _Embedder(SOMEONE_ELSE)
    d._voiceprint = ME
    reason = d._voiceguard_refusal(_burst())
    assert reason is not None and "speaker mismatch" in reason


def test_enabled_and_enrolled_admits_the_user():
    d = _daemon(_cfg())
    d._embedder = _Embedder(ME)
    d._voiceprint = ME
    assert d._voiceguard_refusal(_burst()) is None


# --- a real burst through _on_hold_end ----------------------------------------------------

class _Recorder:
    current_device_name = "test mic"

    def __init__(self, audio):
        self._audio = audio

    def stop(self):
        return self._audio


class _Engine:
    def __init__(self, text="hello world"):
        self.text = text
        self.calls = 0

    def transcribe(self, *args, **kwargs):
        self.calls += 1
        return self.text


class _Injector:
    def __init__(self):
        self.injected: list[str] = []

    def inject(self, text):
        self.injected.append(text)

    def inject_backspaces(self, count):
        pass

    def inject_key_sequence(self, keys):
        pass


def _burst_daemon(cfg: Config, speaker: np.ndarray, captured: list[dict]) -> Daemon:
    cfg.filters.disfluency.enabled = False
    cfg.streaming.enabled = False
    cfg.injection.continuation_window_ms = 0
    cfg.accessibility.speech_presence_check = False   # a constant tone is not speech
    d = _daemon(cfg)
    d._recorder = _Recorder(_burst())
    d._engine = _Engine()
    d._padding_buffer = None
    d._injector = _Injector()
    d._state.target_ok = True
    d._embedder = _Embedder(speaker)
    d._voiceprint = ME
    # The corpus is where the daemon hands every finished burst's event; a stub that
    # keeps them is how the recorded discard reason is read back.
    d._corpus = SimpleNamespace(write=lambda event, audio, sr: captured.append(dict(event)))
    return d


def test_a_refused_burst_is_never_decoded_or_typed():
    captured: list[dict] = []
    d = _burst_daemon(_cfg(), SOMEONE_ELSE, captured)
    d._on_hold_end()
    assert d._engine.calls == 0, "a refused burst must not reach STT"
    assert d._injector.injected == []
    assert [e.get("discard_reason") for e in captured] == ["voiceguard_rejected"]
    assert "hello" not in repr(captured), "no words exist for a refused burst"


def test_the_users_own_burst_is_typed():
    d = _burst_daemon(_cfg(), ME, [])
    d._on_hold_end()
    assert d._engine.calls == 1
    assert "".join(d._injector.injected).strip().lower().startswith("hello world")


def test_a_default_daemon_types_the_same_burst_without_embedding_it():
    """The hot path is unchanged while off: another speaker's burst is typed, and the
    embedder is never asked."""
    d = _burst_daemon(Config(), SOMEONE_ELSE, [])
    d._on_hold_end()
    assert d._engine.calls == 1
    assert d._embedder.calls == 0
    assert "".join(d._injector.injected).strip().lower().startswith("hello world")


# --- doctor -------------------------------------------------------------------------------

def test_doctor_is_silent_while_off(tmp_path: Path):
    from yazses.system.doctor import _voiceguard_check

    assert _voiceguard_check(Config(), tmp_path) is None


def test_doctor_warns_when_nothing_is_enrolled(tmp_path: Path):
    from yazses.system.doctor import _voiceguard_check

    row = _voiceguard_check(_cfg(), tmp_path)
    assert row is not None and row[1] == "WARN" and "yazses enroll-voice" in row[2]


def test_doctor_reports_on_and_says_there_is_no_anti_spoof(tmp_path: Path):
    from yazses.system.doctor import _voiceguard_check

    (tmp_path / "voiceprint.enc").write_bytes(b"x")
    row = _voiceguard_check(_cfg(), tmp_path)
    assert row is not None and row[1] == "OK" and "anti-spoof" in row[2]


@pytest.mark.parametrize("reason", ["voiceguard_rejected"])
def test_the_discard_reason_is_classified_as_doubting_capture(reason):
    from yazses.audio.device_monitor import capture_proved

    assert capture_proved(reason) is False


def test_simple_namespace_config_without_sections_is_inactive():
    """`inactive_reason` reads defensively: a config missing the section explains nothing."""
    assert inactive_reason(SimpleNamespace(), embedder_ready=True, enrolled=True) is None
