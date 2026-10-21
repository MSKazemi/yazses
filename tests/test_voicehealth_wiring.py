"""Vocal-Strain Guard wiring (ADR-v2-034, WIRE-VOICEHEALTH-001).

Three halves:

* the runtime (``voicehealth/runtime.py``) with a fake backend: it measures off the
  caller's thread, drops rather than queues when busy, raises ONE reminder per
  qualifying window, honours the history's cooldown, starts a new session after a long
  idle gap, and is inert -- no thread, ``submit`` a no-op, a reason -- when
  ``parselmouth`` is missing;
* the daemon hook: an enabled daemon hands each decoded burst to the runtime, a default
  daemon never imports the package on the burst path and types exactly as before;
* the house pattern for the missing extra: ``doctor``'s dormant-feature check names it.

Every signal here is synthetic. The thresholds have not been validated on real voices.
"""
from __future__ import annotations

import builtins
import threading
from dataclasses import dataclass

import numpy as np
import pytest

from tests.test_base_weight_budget import disabled_by_default_packages
from tests.test_dormant_features_stay_unimported import _DaemonImports
from tests.test_involuntary_audio import SR, silence, utterance, vowel
from yazses.voicehealth import runtime as vh_runtime
from yazses.voicehealth.biomarkers import (
    BREAK_SUGGESTION_BODY,
    BREAK_SUGGESTION_TITLE,
    DEFAULT_COOLDOWN_S,
    Biomarkers,
)
from yazses.voicehealth.runtime import SESSION_GAP_S, VoiceHealthRuntime

CALM = Biomarkers(jitter=0.004, shimmer=0.03, hnr=20.0)        # strain ~0.17
STRAINED = Biomarkers(jitter=0.02, shimmer=0.10, hnr=2.0)      # strain ~0.97


@dataclass
class _Cfg:
    enabled: bool = True
    threshold: float = 0.6
    min_samples: int = 3


class _Backend:
    """Returns the queued readings in order; the audio itself is ignored."""

    def __init__(self, readings):
        self.readings = list(readings)
        self.calls = 0

    def measure(self, audio, sample_rate):
        self.calls += 1
        return self.readings.pop(0) if self.readings else None


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _runtime(readings, **kw):
    notes: list[tuple[str, str]] = []
    clock = _Clock()
    rt = VoiceHealthRuntime(
        _Cfg(), backend=_Backend(readings), notify=lambda t, b: notes.append((t, b)),
        clock=clock, wall_clock=kw.pop("wall_clock", clock), start_thread=False, **kw,
    )
    return rt, notes, clock


def _feed(rt, clock, n, step=60.0):
    fired = []
    for _ in range(n):
        clock.now += step
        fired.append(rt.process(np.zeros(10), SR))
    return fired


# ---- runtime ------------------------------------------------------------------

def test_a_rising_voice_raises_exactly_one_reminder() -> None:
    rt, notes, clock = _runtime([CALM] * 3 + [STRAINED] * 6)
    fired = _feed(rt, clock, 9)
    assert fired.count(True) == 1
    assert notes == [(BREAK_SUGGESTION_TITLE, BREAK_SUGGESTION_BODY)]


def test_a_steady_voice_never_raises_one() -> None:
    """Rule 9, the negative direction: a voice that scores high from the start is its own
    baseline and never fires; neither does a calm one."""
    for reading in (CALM, STRAINED):
        rt, notes, clock = _runtime([reading] * 60)
        assert not any(_feed(rt, clock, 60))
        assert notes == []


def test_the_cooldown_holds_a_second_reminder_back() -> None:
    rt, notes, clock = _runtime([CALM] * 3 + [STRAINED] * 30)
    _feed(rt, clock, 6)                   # baseline + first reminder
    assert len(notes) == 1
    _feed(rt, clock, 20, step=60.0)       # 20 min of strained speech: inside cooldown
    assert len(notes) == 1
    clock.now += DEFAULT_COOLDOWN_S
    _feed(rt, clock, 3)
    assert len(notes) == 2


def test_a_long_idle_gap_starts_a_new_session() -> None:
    rt, notes, clock = _runtime([STRAINED] * 3 + [CALM] * 3 + [STRAINED] * 3)
    _feed(rt, clock, 3)                   # baseline high: never fires this session
    assert rt.history.baseline is not None and rt.history.baseline > 0.9
    clock.now += SESSION_GAP_S
    _feed(rt, clock, 6)                   # fresh calm baseline, then a rise
    assert len(notes) == 1


def test_an_overnight_suspend_starts_a_new_session() -> None:
    # CLOCK_MONOTONIC does not advance while suspended: the monotonic clock sees only a
    # minute between the evening and the morning, the wall clock sees ten hours.
    wall = _Clock()
    rt, notes, clock = _runtime([STRAINED] * 3 + [CALM] * 3 + [STRAINED] * 3,
                                wall_clock=wall)

    def feed(n):
        out = []
        for _ in range(n):
            clock.now += 60.0
            wall.now += 60.0
            out.append(rt.process(np.zeros(10), SR))
        return out

    assert not any(feed(3))               # high baseline: never fires this session
    clock.now += 60.0                     # suspended overnight: monotonic barely moves
    wall.now += 10 * 60 * 60.0
    feed(6)                               # fresh calm baseline, then a rise
    assert len(notes) == 1


def test_a_failing_notifier_never_escapes() -> None:
    def boom(_t, _b):
        raise RuntimeError("no desktop")

    rt = VoiceHealthRuntime(_Cfg(), backend=_Backend([CALM] * 3 + [STRAINED] * 3),
                            notify=boom, clock=_Clock(), start_thread=False)
    assert [rt.process(np.zeros(1), SR) for _ in range(6)].count(True) == 1


def test_submit_measures_on_a_worker_and_drops_when_busy() -> None:
    gate, entered = threading.Event(), threading.Event()
    seen: list[str] = []

    class _Slow:
        def measure(self, audio, sample_rate):
            seen.append(threading.current_thread().name)
            entered.set()
            gate.wait(5)
            return None

    rt = VoiceHealthRuntime(_Cfg(), backend=_Slow(), notify=lambda *a: None)
    try:
        assert rt.submit(np.zeros(10), SR) is True
        assert entered.wait(5)
        assert rt.submit(np.zeros(10), SR) is True     # fills the one slot
        assert rt.submit(np.zeros(10), SR) is False    # busy and full: dropped, not queued
    finally:
        gate.set()
        rt.close()
    assert seen and all(name == "voicehealth" for name in seen)


def test_without_parselmouth_the_runtime_is_inert() -> None:
    rt = VoiceHealthRuntime(_Cfg(), missing=lambda: ["parselmouth"])
    assert rt.active is False
    assert rt.inactive_reason and "parselmouth" in rt.inactive_reason
    assert "prosody" in rt.inactive_reason
    assert rt._thread is None
    assert rt.submit(np.zeros(10), SR) is False
    assert rt.process(np.zeros(10), SR) is False
    rt.close()


# ---- daemon hook --------------------------------------------------------------

class _Recorder:
    def __init__(self, audio):
        self._audio = audio

    def stop(self):
        return self._audio


class _Engine:
    def transcribe(self, audio, *args, **kwargs):
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


def _speech() -> np.ndarray:
    return utterance(silence(0.2), vowel(0.8), silence(0.2))


def _daemon(audio, *, enabled: bool):
    from yazses.config import Config
    from yazses.core.daemon import Daemon
    from yazses.platform import get_platform

    cfg = Config()
    cfg.filters.disfluency.enabled = False
    cfg.streaming.enabled = False
    cfg.voicehealth.enabled = enabled
    d = Daemon(config=cfg, platform=get_platform())
    d._recorder = _Recorder(audio)
    d._engine = _Engine()
    d._padding_buffer = None
    d._injector = _Injector()
    return d


class _FakeRuntime:
    def __init__(self) -> None:
        self.inactive_reason = None
        self.submitted: list[tuple[np.ndarray, int]] = []
        self.closed = False

    def submit(self, audio, sample_rate):
        self.submitted.append((np.array(audio, copy=True), sample_rate))
        return True

    def close(self):
        self.closed = True


def test_an_enabled_daemon_hands_the_decoded_burst_to_the_monitor(monkeypatch) -> None:
    fake = _FakeRuntime()
    monkeypatch.setattr(vh_runtime, "build_runtime", lambda cfg, **kw: fake)
    x = _speech()
    d = _daemon(x, enabled=True)
    try:
        d._on_hold_end()
        assert d._injector.texts == ["hello world"]
        assert len(fake.submitted) == 1
        audio, rate = fake.submitted[0]
        assert rate == d._config.audio.sample_rate
        assert np.array_equal(audio, x)       # the recorded burst, no lead-in zeros
    finally:
        d._shutdown()
    assert fake.closed is True


def test_a_failing_monitor_never_breaks_dictation(monkeypatch) -> None:
    def boom(cfg, **kw):
        raise RuntimeError("monitor exploded")

    monkeypatch.setattr(vh_runtime, "build_runtime", boom)
    d = _daemon(_speech(), enabled=True)
    try:
        d._on_hold_end()
        assert d._injector.texts == ["hello world"]
    finally:
        d._shutdown()


def test_a_runtime_that_cannot_start_is_reported_once_and_never_retried(
    monkeypatch, caplog
) -> None:
    attempts: list[int] = []

    def boom(cfg, **kw):
        attempts.append(1)
        raise RuntimeError("monitor exploded")

    monkeypatch.setattr(vh_runtime, "build_runtime", boom)
    d = _daemon(_speech(), enabled=True)
    try:
        with caplog.at_level("WARNING", logger="yazses.core.daemon"):
            d._on_hold_end()
            d._recorder = _Recorder(_speech())
            d._on_hold_end()
        assert [t.strip() for t in d._injector.texts] == ["hello world", "hello world"]
        assert len(attempts) == 1
        warnings = [r.getMessage() for r in caplog.records if "[voicehealth]" in r.getMessage()]
        assert len(warnings) == 1 and "monitor exploded" in warnings[0]
    finally:
        d._shutdown()


def test_an_enabled_daemon_without_the_extra_warns_once_and_stays_dormant(
    monkeypatch, caplog
) -> None:
    monkeypatch.setattr(vh_runtime, "_default_missing", lambda: ["parselmouth"])
    d = _daemon(_speech(), enabled=True)
    try:
        with caplog.at_level("WARNING", logger="yazses.core.daemon"):
            d._on_hold_end()
            d._recorder = _Recorder(_speech())
            d._on_hold_end()
        assert [t.strip() for t in d._injector.texts] == ["hello world", "hello world"]
        assert d._voicehealth is not None and d._voicehealth.active is False
        warnings = [r.getMessage() for r in caplog.records if "[voicehealth]" in r.getMessage()]
        assert len(warnings) == 1 and "parselmouth" in warnings[0]
    finally:
        d._shutdown()


def test_a_default_daemon_never_imports_voicehealth_on_the_burst_path(monkeypatch) -> None:
    assert "voicehealth" in disabled_by_default_packages()
    recorder = _DaemonImports(disabled_by_default_packages())
    monkeypatch.setattr(builtins, "__import__", recorder)
    d = _daemon(_speech(), enabled=False)
    try:
        d._on_hold_end()
    finally:
        d._shutdown()
    monkeypatch.undo()
    assert "voicehealth" not in recorder.packages()
    assert d._voicehealth is None
    assert d._injector.texts == ["hello world"]


# ---- doctor / status: the missing extra is named ---------------------------------

def test_doctor_names_the_missing_prosody_extra_when_enabled() -> None:
    from yazses.config import Config
    from yazses.system.dormant import dormant_features

    cfg = Config()
    cfg.voicehealth.enabled = True
    found = {d.slug: d for d in dormant_features(cfg, missing=lambda mods: list(mods))}
    assert "voicehealth" in found
    assert "parselmouth" in found["voicehealth"].missing

    off = {d.slug for d in dormant_features(Config(), missing=lambda mods: list(mods))}
    assert "voicehealth" not in off


def test_the_registry_marks_it_experimental_and_wired() -> None:
    from yazses.system.features import EXPERIMENTAL, _registry, unwired_slugs

    row = next(d for d in _registry() if d.slug == "voicehealth")
    assert row.tier == EXPERIMENTAL
    assert "voicehealth" not in unwired_slugs()


@pytest.mark.parametrize("reading", [CALM, STRAINED])
def test_readings_are_floats_only(reading) -> None:
    """The history keeps strain levels, never the clip it was measured from."""
    rt, _notes, clock = _runtime([reading] * 5)
    _feed(rt, clock, 5)
    assert all(isinstance(v, float) for v in rt.history.window)
