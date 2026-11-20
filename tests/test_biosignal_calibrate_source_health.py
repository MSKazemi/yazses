"""``yazses biosignal calibrate`` honours the source's own health verdict (#887).

Calibration opened the configured source directly, so for a ThinkGear headset it learned
thresholds from reads the source itself refused (no skin contact, a corrupt frame, a stale
contact report). Now a source that judges its own signal is read through the same guard
the daemon, ``monitor`` and ``field-test`` use (``source_gates``), and an untrusted read
never reaches the profile: a step it interrupts is discarded and repeated, the excluded
time is reported, and a source that never becomes trusted fails the calibration with a
reason instead of saving anything.

Synthetic wire traces only (``tests/thinkgear_gate_trace``); no headset.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import numpy as np
import pytest

from tests.thinkgear_gate_trace import (
    FakeClock,
    blink_counts,
    build_trace,
    quality,
    trace_source,
)
from yazses.biosignal import calibration as cal
from yazses.biosignal import cli_impl, source_gates
from yazses.biosignal.calibration import (
    CalibrationConfig,
    CalibrationPhase,
    CalibrationSession,
    IssueCode,
)
from yazses.biosignal.cli_impl import run_calibrate
from yazses.biosignal.types import ChannelInfo, SampleBlock, SignalKind
from yazses.config import BiosignalConfig, Config

SPEC = "thinkgear:/dev/fake-thinkgear"
FS = 512.0
CH = (ChannelInfo("Fp1", SignalKind.EEG),)


# ------------------------------------------------------------------ the pure session


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def _block(seconds: float, t0: float = 0.0, seed: int = 1) -> SampleBlock:
    n = round(seconds * FS)
    data = np.random.default_rng(seed).normal(0.0, 5.0, size=(1, n))
    return SampleBlock(data=data, fs=FS, channels=CH, t0=t0)


def _session(clock: Clock, **cfg: Any) -> CalibrationSession:
    return CalibrationSession("thinkgear", CH, FS, include_squeeze=False,
                              config=CalibrationConfig(**cfg), clock=clock)


def test_an_untrusted_read_discards_the_step_it_interrupts() -> None:
    clock = Clock()
    session = _session(clock)
    assert session.feed(_block(2.0)) is None
    assert session.progress().phase_fraction > 0
    issue = session.feed_untrusted(_block(0.5, 2.0), "no_contact: the headset reports no skin contact")
    assert issue is not None and issue.code is IssueCode.SOURCE_UNTRUSTED
    assert not issue.fatal and issue.attempt == 1
    assert "no_contact" in issue.message
    assert session.progress().phase_fraction == 0.0           # the window starts again
    assert session.excluded_s == pytest.approx(0.5)


def test_untrusted_reads_with_nothing_collected_are_only_counted() -> None:
    clock = Clock()
    session = _session(clock)
    for i in range(10):
        clock.t += 0.1
        assert session.feed_untrusted(_block(0.1, 0.1 * i), "rearming") is None
    assert session.excluded_s == pytest.approx(1.0, abs=0.01)
    assert session.phase is CalibrationPhase.RELAX
    # Untrusted reads are data arriving, not a stall.
    clock.t += 4.9
    assert session.tick() is None


def test_a_source_that_never_becomes_trusted_fails_with_a_reason() -> None:
    clock = Clock()
    session = _session(clock, untrusted_timeout_s=30.0)
    issue = None
    while issue is None and clock.t < 40.0:
        clock.t += 0.1
        issue = session.feed_untrusted(_block(0.1), "no_contact: no skin contact")
    assert issue is not None and issue.fatal
    assert issue.code is IssueCode.SOURCE_UNTRUSTED
    assert clock.t == pytest.approx(30.1, abs=0.11)
    assert "Source health: trusted" in issue.message
    assert session.phase is CalibrationPhase.FAILED
    with pytest.raises(cal.CalibrationError):
        session.result()


def test_trust_returning_restarts_the_timeout() -> None:
    clock = Clock()
    session = _session(clock, untrusted_timeout_s=3.0, relax_s=60.0)
    for _ in range(25):
        clock.t += 0.1
        assert session.feed_untrusted(_block(0.1), "rearming") is None
    clock.t += 0.1
    assert session.feed(_block(0.1)) is None
    for _ in range(25):
        clock.t += 0.1
        session.feed_untrusted(_block(0.1), "rearming")
    assert session.phase is not CalibrationPhase.FAILED


# ------------------------------------------------------------------ run_calibrate


def _cfg() -> Config:
    cfg = Config()
    cfg.biosignal = dataclasses.replace(BiosignalConfig(), enabled=True, source=SPEC,
                                        emg=False, double_blink=False, jaw_clench=False)
    return cfg


def _drive(monkeypatch: pytest.MonkeyPatch, trace: Any) -> list[float]:
    """Point calibrate at ``trace`` with one fake clock for the source and the session;
    return the t0 of every block the session was allowed to learn from."""
    clock = FakeClock()
    monkeypatch.setattr(cli_impl, "_open", lambda spec, realtime=False: trace_source(trace, clock))
    monkeypatch.setattr(cal, "_monotonic", clock)
    learned: list[float] = []
    real_feed = CalibrationSession.feed

    def feed(self: CalibrationSession, block: Any) -> Any:
        if block is not None:
            learned.append(float(block.t0))
        return real_feed(self, block)

    monkeypatch.setattr(CalibrationSession, "feed", feed)
    return learned


def test_calibrate_learns_only_from_trusted_reads(monkeypatch, tmp_path, capsys) -> None:
    # Contact is good, except a lone POOR_SIGNAL=200 at 4.0 s inside the resting step.
    # Trusted ~1.1-3.9 s, then rearming until the 5 s and 6 s zero reports.
    trace = build_trace(blink_counts((), 16.0), inject=((4.0, quality(200)),))
    learned = _drive(monkeypatch, trace)
    code = run_calibrate(_cfg(), tmp_path, yes=True)
    out = capsys.readouterr()
    assert code == cli_impl.OK, out.err
    assert learned, "nothing reached the session"
    assert min(learned) >= 1.0 - 1e-9                            # nothing from the first rearm
    assert not [t for t in learned if 3.9 < t < 6.0]             # nor from the contact loss
    assert "samples of this step were discarded" in out.out
    assert "Left out" in out.out
    assert cli_impl.profile_path(_cfg().biosignal, tmp_path).exists()


def test_calibrate_with_no_skin_contact_fails_and_saves_nothing(monkeypatch, tmp_path,
                                                                capsys) -> None:
    trace = build_trace(blink_counts((), 40.0), contact=lambda second: 200)
    learned = _drive(monkeypatch, trace)
    code = run_calibrate(_cfg(), tmp_path, yes=True)
    err = capsys.readouterr().err
    assert code == cli_impl.FAILED
    assert learned == []
    assert "has not reported a trustworthy signal" in err
    assert not cli_impl.profile_path(_cfg().biosignal, tmp_path).exists()


def test_a_source_without_health_is_read_as_before(monkeypatch, tmp_path) -> None:
    """Only a source that judges itself is wrapped; any other is calibrated unchanged."""

    class Plain:
        fs = FS
        channels = CH
        available = True

        def __init__(self) -> None:
            self.left = 8

        def start(self) -> None: ...
        def stop(self) -> None: ...

        def read(self) -> SampleBlock:
            if not self.left:
                raise EOFError
            self.left -= 1
            return _block(1.0, seed=self.left)

    def no_guard(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a plain source must not be wrapped")

    monkeypatch.setattr(cli_impl, "_open", lambda spec, realtime=False: Plain())
    monkeypatch.setattr(source_gates, "guard_source", no_guard)
    cfg = _cfg()
    cfg.biosignal = dataclasses.replace(cfg.biosignal, source="file:/nonexistent.edf")
    assert run_calibrate(cfg, tmp_path, yes=True) == cli_impl.OK
