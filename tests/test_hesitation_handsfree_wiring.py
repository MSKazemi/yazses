"""Hesitation-hold wired into hands-free auto-stop (ADR-v2-101, WIRE-HESITATION-001, #164).

The owner's rule: ``[autostop] silence_timeout_ms`` stays the base threshold and hesitation
only *extends* it, by ``[hesitation] hold_extra_ms``, after a detected filled pause, and only
in a latched hands-free turn. A default install, and an ``[autostop]``-only install, must not
import or build anything from ``yazses.hesitation``.

Signals are synthetic (`tests/synthetic_voice.py`); no recorded audio, no microphone.
"""
from __future__ import annotations

import builtins
import logging
import threading

import numpy as np
import pytest

from tests.synthetic_voice import SR, glide, hum, silence
from yazses.config import Config


def _daemon(cfg: Config):
    from yazses.core.daemon import Daemon
    from yazses.platform import get_platform

    return Daemon(config=cfg, platform=get_platform())


def _cfg(*, autostop: bool = True, hesitation: bool = True) -> Config:
    cfg = Config()
    cfg.autostop.enabled = autostop
    cfg.hesitation.enabled = hesitation
    cfg.audio.sample_rate = SR
    return cfg


def _umm(seconds: float = 0.6):
    return hum(118.0, seconds, noise=5e-4)


def _phrase(seconds: float = 0.6):
    return hum(glide(210.0, 120.0, seconds), seconds, noise=5e-4)


class _DaemonImports:
    """Every ``yazses.*`` name an ``import`` statement in `core/daemon.py` executes."""

    def __init__(self) -> None:
        self.names: list[str] = []
        self._real = builtins.__import__

    def __call__(self, name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
        if level == 0 and (globals or {}).get("__name__") == "yazses.core.daemon":
            self.names.append(name)
        return self._real(name, globals, locals, fromlist, level)


# ---- off by default: nothing imported, nothing built, hot path unchanged ---------------------

@pytest.mark.parametrize("autostop", [False, True])
def test_without_hesitation_the_daemon_imports_and_builds_nothing_of_it(monkeypatch, autostop):
    cfg = _cfg(autostop=autostop, hesitation=False)
    recorder = _DaemonImports()
    monkeypatch.setattr(builtins, "__import__", recorder)
    daemon = _daemon(cfg)
    turn = daemon._build_autostop(cfg)
    monkeypatch.setattr(builtins, "__import__", recorder._real)
    assert not [n for n in recorder.names if n.startswith("yazses.hesitation")]
    assert daemon._hesitation is None
    if autostop:
        assert turn is not None and turn._endpoint is None  # the plain-threshold machine
    else:
        assert turn is None


def test_a_default_daemon_has_the_default_and_no_monitor():
    cfg = Config()
    assert cfg.hesitation.enabled is False
    assert cfg.hesitation.commit_ms == 0.0  # "derive from [autostop]"
    daemon = _daemon(cfg)
    assert daemon._hesitation is None


def test_the_audio_callback_is_unchanged_without_a_monitor(monkeypatch):
    """With [hesitation] off the chunk handler publishes the level and pushes nothing new."""
    from yazses.hesitation import stream

    def _boom(self, chunk):  # pragma: no cover - must not run
        raise AssertionError("HesitationMonitor.push reached from a default daemon")

    monkeypatch.setattr(stream.HesitationMonitor, "push", _boom)
    for cfg in (Config(), _cfg(autostop=True, hesitation=False)):
        daemon = _daemon(cfg)
        daemon._autostop = daemon._build_autostop(cfg)
        if daemon._autostop is not None:
            daemon._autostop.press(0.0)
            daemon._autostop.release(0.1)  # latched: the only state that could feed it
        daemon._on_audio_chunk(np.full(160, 0.25, dtype=np.float32))
        assert daemon._state.audio_level == pytest.approx(0.25)


# ---- enabled: one base threshold, extended only ------------------------------------------

def test_the_monitor_takes_the_autostop_timeout_as_its_commit_threshold():
    cfg = _cfg()
    cfg.autostop.silence_timeout_ms = 950
    cfg.hesitation.hold_extra_ms = 700.0
    daemon = _daemon(cfg)
    turn = daemon._build_autostop(cfg)
    monitor = daemon._hesitation
    assert monitor is not None
    assert turn._endpoint == monitor.decision
    assert monitor._commit_ms == 950.0
    assert monitor._hold_extra_ms == 700.0


def test_the_commit_threshold_respects_the_autostop_floor():
    from yazses.endpoint.autostop import MIN_SILENCE_TIMEOUT_MS
    from yazses.hesitation.handsfree import commit_ms_for

    cfg = _cfg()
    cfg.autostop.silence_timeout_ms = 10
    assert commit_ms_for(cfg.autostop) == float(MIN_SILENCE_TIMEOUT_MS)


@pytest.mark.parametrize("extra", [-500.0, float("nan"), float("-inf"), "x"])
def test_hold_extra_can_never_shorten_the_turn(extra):
    from yazses.hesitation.handsfree import hold_extra_ms_for

    cfg = _cfg()
    cfg.hesitation.hold_extra_ms = extra  # type: ignore[assignment]
    assert hold_extra_ms_for(cfg.hesitation) == 0.0


def test_a_legacy_commit_ms_is_ignored_with_a_warning(caplog):
    cfg = _cfg()
    cfg.hesitation.commit_ms = 400.0
    daemon = _daemon(cfg)
    with caplog.at_level(logging.WARNING, logger="yazses.hesitation.handsfree"):
        daemon._build_autostop(cfg)
    assert daemon._hesitation._commit_ms == float(cfg.autostop.silence_timeout_ms)
    assert any("commit_ms" in r.getMessage() and "ignored" in r.getMessage()
               for r in caplog.records)


def test_hesitation_without_autostop_builds_nothing_and_says_so(caplog):
    cfg = _cfg(autostop=False, hesitation=True)
    from yazses.hesitation.handsfree import build_monitor

    with caplog.at_level(logging.INFO, logger="yazses.hesitation.handsfree"):
        assert build_monitor(cfg.hesitation, cfg.autostop, SR) is None
    assert any("[autostop] is off" in r.getMessage() for r in caplog.records)
    caplog.clear()
    daemon = _daemon(cfg)
    with caplog.at_level(logging.INFO, logger="yazses.hesitation.handsfree"):
        assert daemon._build_autostop(cfg) is None
    assert daemon._hesitation is None
    # The daemon path itself must say why the toggle is inert, not only build_monitor.
    assert any("[autostop] is off" in r.getMessage() for r in caplog.records)


def test_enabling_hesitation_without_autostop_prints_a_caveat():
    from yazses.system.features import enable_caveat

    caveat = enable_caveat("hesitation", _cfg(autostop=False, hesitation=True))
    assert caveat is not None and "yazses features enable autostop" in caveat
    assert enable_caveat("hesitation", _cfg(autostop=True, hesitation=True)) is None


# ---- the three hook points ----------------------------------------------------------------

class _FakeMonitor:
    def __init__(self) -> None:
        self.pushed = 0
        self.resets = 0

    def push(self, chunk) -> None:
        self.pushed += 1

    def reset(self) -> None:
        self.resets += 1

    def decision(self, silence_ms: float) -> str:
        return "commit"


def test_chunks_reach_the_monitor_only_inside_a_latched_turn():
    cfg = _cfg()
    daemon = _daemon(cfg)
    daemon._autostop = daemon._build_autostop(cfg)
    fake = _FakeMonitor()
    daemon._hesitation = fake
    chunk = np.zeros(160, dtype=np.float32)
    daemon._on_audio_chunk(chunk)
    assert fake.pushed == 0  # hold-to-talk / not latched: nothing queued
    daemon._autostop.press(0.0)
    daemon._autostop.release(0.1)
    daemon._on_audio_chunk(chunk)
    assert fake.pushed == 1


def test_the_audio_thread_never_runs_the_pitch_tracker(monkeypatch):
    """`_on_audio_chunk` only queues; YIN runs when the watcher thread asks for a decision."""
    from yazses.hesitation import stream

    cfg = _cfg()
    daemon = _daemon(cfg)
    daemon._autostop = daemon._build_autostop(cfg)
    monitor = daemon._hesitation
    analysed: list[str] = []
    real = stream.HesitationMonitor._analyse

    def _spy(self):
        analysed.append(threading.current_thread().name)
        return real(self)

    monkeypatch.setattr(stream.HesitationMonitor, "_analyse", _spy)
    daemon._autostop.press(0.0)
    daemon._autostop.release(0.1)
    audio = np.concatenate([_phrase(), _umm()])

    def _audio_thread():
        for i in range(0, audio.size, 512):
            daemon._on_audio_chunk(audio[i:i + 512])

    t = threading.Thread(target=_audio_thread, name="fake-audio-callback")
    t.start()
    t.join(timeout=10)
    assert analysed == []
    assert monitor.last_was_filled_pause is True
    assert analysed == [threading.current_thread().name]


def test_a_new_turn_resets_the_monitor_but_a_second_tap_does_not(monkeypatch):
    cfg = _cfg()
    daemon = _daemon(cfg)
    daemon._autostop = daemon._build_autostop(cfg)
    fake = _FakeMonitor()
    daemon._hesitation = fake
    monkeypatch.setattr(daemon, "_detect_target_async", lambda: None)
    monkeypatch.setattr("yazses.core.daemon.time.monotonic", lambda: 0.0)
    daemon._on_hold_start(0)
    assert fake.resets == 1
    daemon._autostop.release(0.1)  # a tap: latched
    assert daemon._autostop.latched
    daemon._on_hold_start(0)  # the second tap's press is swallowed
    assert fake.resets == 1


# ---- end to end: the latched turn waits longer after "umm", not after a phrase --------------

def _run_turn(daemon, audio) -> tuple[bool, bool]:
    """Latch, stream ``audio`` through the chunk handler, then tick through the silence.

    Returns (stopped at commit + 100 ms, stopped at commit + extra + 100 ms).
    """
    turn = daemon._autostop
    turn.press(0.0)
    turn.release(0.1)
    for i in range(0, audio.size, 512):
        daemon._on_audio_chunk(audio[i:i + 512])
    turn.tick(0.5, True)
    turn.tick(1.3, False)  # silence starts
    commit = daemon._hesitation._commit_ms / 1000.0
    extra = daemon._hesitation._hold_extra_ms / 1000.0
    early = turn.tick(1.3 + commit + 0.1, False)
    late = early or turn.tick(1.3 + commit + extra + 0.1, False)
    return early, late


def test_a_filled_pause_extends_the_hands_free_timeout_end_to_end():
    cfg = _cfg()
    daemon = _daemon(cfg)
    daemon._autostop = daemon._build_autostop(cfg)
    early, late = _run_turn(daemon, np.concatenate([_phrase(), _umm(), silence(0.3)]))
    assert early is False  # past [autostop] silence_timeout_ms, still held after "umm"
    assert late is True    # ... and committed once hold_extra_ms has passed


def test_a_turn_ending_in_ordinary_speech_commits_at_the_base_timeout():
    cfg = _cfg()
    daemon = _daemon(cfg)
    daemon._autostop = daemon._build_autostop(cfg)
    early, _ = _run_turn(daemon, np.concatenate([_phrase(), silence(0.3)]))
    assert early is True


# ---- the registry -------------------------------------------------------------------------

def test_hesitation_is_wired_and_marked_experimental():
    from yazses.system.features import EXPERIMENTAL, _registry, feature_status, unwired_slugs

    assert "hesitation" not in unwired_slugs()
    definition = next(d for d in _registry() if d.slug == "hesitation")
    assert definition.tier == EXPERIMENTAL
    assert "[autostop]" in definition.why
    feature = next(f for f in feature_status(Config()) if f.slug == "hesitation")
    assert feature.wired is True
