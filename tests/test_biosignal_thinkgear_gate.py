"""The ThinkGear source-health veto composed with the existing gates and runner (#829).

ADR-v2-155 decision 3: an event is admitted only when source health, stream integrity
and waveform quality all permit it; missing provenance is untrusted; a veto releases a
held activation exactly once and drops pending double-blink state; the watchdog and the
one-release invariant are kept; and every other source kind is unchanged.

Real objects throughout: ``ThinkGearSource`` on a fake serial port and fake clock, the
``IntegrityGuard`` / ``IntegrityGate`` / ``SourceHealthGate`` stack from
``biosignal.source_gates``, the ``BiosignalPipeline`` built by ``build_parts`` with the
real ``BlinkDetector``, and the runner built by ``build_runner_from_config``. The trace
bytes are framed by hand (``tests/thinkgear_gate_trace.py``).
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pytest

from tests.thinkgear_gate_trace import (
    FakeClock,
    bad_checksum_raw,
    blink_counts,
    build_trace,
    quality,
    trace_source,
)
from yazses.biosignal import sources as sources_mod
from yazses.biosignal.integrity import IntegrityGate, IntegrityGuard
from yazses.biosignal.pipeline import BiosignalPipeline, PipelineParts
from yazses.biosignal.runner import BiosignalRunner, RunnerCallbacks, build_runner_from_config
from yazses.biosignal.source_gates import (
    SourceHealthGate,
    compose_quality_gate,
    guard_source,
    is_live,
    needs_source_health,
)
from yazses.biosignal.sources import SyntheticSource
from yazses.biosignal.thinkgear_health import HealthReason
from yazses.biosignal.types import BioEvent, ChannelInfo, EventKind, SampleBlock, SignalKind
from yazses.config import BiosignalConfig, Config

SPEC = "thinkgear:/dev/fake-thinkgear"
DURATION_S = 12.0
EARLY_PAIR = (4.3, 4.6)          # after the 2 s detector warm-up and the 1 s rearm
# After the rearm that follows a loss at 4.45 s (trusted again from ~6.1 s) *and* the
# detector's 2 s warm-up, which restarts at that first trusted block: nothing seen while
# rearming may feed an event. Earlier pairs are a false negative after reconnect, which
# ADR-v2-155 accepts. Not retuned: blink thresholds are frozen.
LATE_PAIR = (9.5, 9.8)
LOSS_AT = 4.45                   # between the two blinks of EARLY_PAIR


def _cfg(spec: str = SPEC, **bio: Any) -> Config:
    cfg = Config()
    cfg.biosignal = dataclasses.replace(BiosignalConfig(), enabled=True, source=spec,
                                        double_blink=True, **bio)
    return cfg


def _runner_over(monkeypatch: pytest.MonkeyPatch, source: Any, spec: str = SPEC,
                 callbacks: RunnerCallbacks | None = None) -> BiosignalRunner:
    """The daemon's runner, built from config, over ``source`` (via ``open_source``)."""
    monkeypatch.setattr(sources_mod, "open_source", lambda _spec, **_kw: source)
    runner = build_runner_from_config(_cfg(spec), callbacks or RunnerCallbacks(),
                                      ledger_path="", watchdog_seconds=0.0)
    assert runner is not None
    opened = runner._open()
    assert opened is not None
    runner._source = opened
    runner._pipeline = runner._pipeline_factory(opened)
    return runner


def _drain(runner: BiosignalRunner) -> None:
    for _ in range(100_000):
        if not runner.step() and not getattr(runner._source, "available", True):
            return
    raise AssertionError("trace never ended")


def _accepted(runner: BiosignalRunner) -> list[tuple[str, bool, str]]:
    return [(e["kind"], e["accepted"], e.get("reason", ""))
            for e in reversed(runner.recent_events(1000))]


def _double_blinks(runner: BiosignalRunner) -> list[float]:
    return [e[0] for e in runner._journal if e[1] == "double_blink" and e[2]]


def _run_trace(monkeypatch, blinks=EARLY_PAIR + LATE_PAIR, **trace_kw) -> BiosignalRunner:
    trace = build_trace(blink_counts(blinks, DURATION_S), **trace_kw)
    runner = _runner_over(monkeypatch, trace_source(trace))
    _drain(runner)
    return runner


def _n_double(runner: BiosignalRunner) -> int:
    return sum(1 for kind, ok, _ in _accepted(runner) if kind == "double_blink" and ok)


# ---------------------------------------------------------------- wiring


def test_a_thinkgear_runner_gets_the_source_health_gate(monkeypatch) -> None:
    trace = build_trace(blink_counts((), 1.0))
    runner = _runner_over(monkeypatch, trace_source(trace))
    gate = runner._pipeline._parts.quality
    assert isinstance(gate, SourceHealthGate)
    assert isinstance(gate.inner, IntegrityGate)          # the existing gate, kept inside
    assert isinstance(runner._source, IntegrityGuard)
    assert runner._live is True


@pytest.mark.parametrize("spec", [
    "synthetic:eog", "file:/tmp/x.csv", "brainflow:synthetic", "lsl:type=EEG",
    "bitalino:/dev/rfcomm0", "myo:AA:BB:CC:DD:EE:FF",
])
def test_tg13_every_other_source_kind_keeps_the_plain_integrity_gate(monkeypatch, spec) -> None:
    source = SyntheticSource("eog", seed=1, duration=1.0)
    runner = _runner_over(monkeypatch, source, spec)
    gate = runner._pipeline._parts.quality
    assert type(gate) is IntegrityGate
    assert not needs_source_health(source, spec)
    assert runner._live is is_live(spec) is (spec.split(":")[0] not in ("synthetic", "file"))
    assert runner._source.health_for(runner._source.read()) is None


def test_tg13_synthetic_events_are_identical_to_the_pre_change_wiring(monkeypatch) -> None:
    """The e2e clean pair of test_biosignal_integrity_e2e through the new constructor and
    through the hand-written wiring it replaced: the same accepted events, at the same
    times, with the same status."""

    def run(new: bool) -> tuple[list[tuple[str, float]], Any]:
        src = SyntheticSource("eog", seed=2, duration=9.0, mains_uv=0.0)
        src.schedule_blink(4.3)
        src.schedule_blink(4.6)
        if new:
            runner = _runner_over(monkeypatch, src, "synthetic:eog")
            pipeline = runner._pipeline
            guard = runner._source
        else:
            from yazses.biosignal.pipeline import PartsRequest, build_parts

            guard = IntegrityGuard(src, check_arrival_rate=False)
            guard.start()
            parts = build_parts(PartsRequest(fs=float(guard.fs), double_blink=True,
                                             channels=tuple(guard.channels),
                                             source_spec="synthetic:eog", with_ledger=True))
            parts.quality = IntegrityGate(guard, parts.quality)
            pipeline = BiosignalPipeline(parts)
        events = []
        status = None
        while True:
            try:
                block = guard.read()
            except EOFError:
                break
            if block is None:
                continue
            result = pipeline.process(block)
            events += [(e.kind.value, round(float(e.t), 6)) for e in result.events]
            status = result.status
        return events, status

    old_events, old_status = run(False)
    new_events, new_status = run(True)
    assert old_events == new_events and old_events
    assert (old_status.accepted, old_status.dropped, old_status.quality) == \
           (new_status.accepted, new_status.dropped, new_status.quality)


# ---------------------------------------------------------------- admission


def test_a_clean_trace_admits_both_pairs(monkeypatch) -> None:
    """Control for every veto below: the same waveform, healthy, is two double blinks."""
    runner = _run_trace(monkeypatch)
    assert _n_double(runner) == 2


def test_tg02_no_contact_report_ever_means_no_event(monkeypatch) -> None:
    runner = _run_trace(monkeypatch, contact=lambda second: None)
    assert _n_double(runner) == 0
    reasons = {why for kind, ok, why in _accepted(runner) if not ok}
    assert reasons and all(r in ("quality",) for r in reasons)
    assert "unknown_contact" in runner.status()["pipeline"]["reason"]


def test_tg09_double_blink_straddling_contact_loss_is_refused(monkeypatch) -> None:
    """A lone POOR_SIGNAL=200 between the two blinks, in a packet with no raw rows: the
    pair is never admitted, nothing leaks on rearm, and the late pair after a full rearm
    is admitted again."""
    runner = _run_trace(monkeypatch, inject=((LOSS_AT, quality(200)),))
    assert _n_double(runner) == 1                      # only the late pair
    assert runner.status()["events"]["accepted"] == 1
    late = [t for t, kind, ok, _ in runner._journal if kind == "double_blink" and ok]
    assert len(late) == 1


@pytest.mark.parametrize("read_samples", [7, 51, 128, 333, 1024])
def test_tg09_no_block_split_lets_the_straddled_pair_through(monkeypatch, read_samples) -> None:
    trace = build_trace(blink_counts(EARLY_PAIR, 7.0), inject=((LOSS_AT, quality(200)),),
                        read_samples=read_samples)
    runner = _runner_over(monkeypatch, trace_source(trace))
    _drain(runner)
    assert _n_double(runner) == 0


def test_tg09_the_veto_resets_pending_detector_state(monkeypatch) -> None:
    """Resets at each trust boundary, and only there: the first trusted block (~1.1 s),
    the fault epoch (4.45 s) and the first trusted block after the rearm (~6.1 s)."""
    trace = build_trace(blink_counts(EARLY_PAIR, 7.0), inject=((LOSS_AT, quality(200)),))
    runner = _runner_over(monkeypatch, trace_source(trace))
    detector = runner._pipeline._parts.detectors[0]
    resets = []
    original = detector.reset
    monkeypatch.setattr(detector, "reset", lambda: (resets.append(1), original())[1])
    _drain(runner)
    assert len(resets) == 3


def _first_trusted_after(verdicts: list[tuple[float, bool]], t: float) -> float:
    return next(t0 for t0, ok in verdicts if ok and t0 >= t)


@pytest.mark.parametrize("onset", [round(5.6 + 0.05 * i, 2) for i in range(17)])
def test_tg09_no_admitted_gesture_uses_samples_from_a_rearming_read(monkeypatch, onset) -> None:
    """ADR-v2-155: no event before the next separate clean batch, and none spanning the
    boundary. Contact is lost for seconds 3-4 and rearmed by the reports at 5 s and 6 s;
    the first blink of a pair starts at ``onset`` (each blink lasts 0.3 s, the second
    starts 0.35 s after the first). Whatever the detector does, an accepted double blink
    must have *all* its samples in trusted reads: its first blink cannot start before the
    first trusted block. Judged from the scheduled blink times, not the detector's own
    (delayed) timestamps."""
    trace = build_trace(blink_counts((onset, onset + 0.35), 12.0),
                        contact=lambda s: 200 if s in (3, 4) else 0)
    source = trace_source(trace)
    runner = _runner_over(monkeypatch, source)
    verdicts: list[tuple[float, bool]] = []
    real_process = runner._pipeline.process

    def process(block: SampleBlock) -> Any:
        health = runner._source.health_for(block)
        verdicts.append((float(block.t0), bool(health is not None and health.trusted)))
        return real_process(block)

    monkeypatch.setattr(runner._pipeline, "process", process)
    _drain(runner)
    trusted_from = _first_trusted_after(verdicts, 4.0)
    assert 5.9 < trusted_from < 6.2                 # the hand-derived rearm point
    if _n_double(runner):
        assert onset >= trusted_from, (
            f"a pair whose first blink starts at {onset} s was admitted, but the stream "
            f"was only trusted from {trusted_from:.4f} s")


def test_tg03_zero_200_zero_in_one_read_vetoes_the_pair(monkeypatch) -> None:
    # 0 / 200 / 0 all inside the read that holds the first blink
    runner = _run_trace(monkeypatch, blinks=EARLY_PAIR, inject=(
        (4.30, quality(0)), (4.31, quality(200)), (4.32, quality(0))))
    assert _n_double(runner) == 0


def test_tg05_a_corrupt_frame_beside_the_first_blink_vetoes_the_pair(monkeypatch) -> None:
    runner = _run_trace(monkeypatch, blinks=EARLY_PAIR, inject=((4.29, bad_checksum_raw()),))
    assert _n_double(runner) == 0


@pytest.mark.parametrize(("wire", "prefix", "category"), [
    (bad_checksum_raw(), "stream integrity: source corrupt_packet", "stream"),
    (quality(200), "source health: no_contact", "quality"),
    (quality(7), "source health: contact_contaminated", "quality"),
])
def test_tg04_the_refusal_names_contact_apart_from_transport(wire, prefix, category) -> None:
    """A transport fault is filed under the pipeline's existing ``stream`` refusal
    category and a contact fault under ``quality``; the reason line says which."""
    from yazses.biosignal import pipeline as pipeline_mod

    trace = build_trace(blink_counts((), 3.0), inject=((2.5, wire),))
    guard = guard_source(trace_source(trace), SPEC)
    guard.start()
    gate = compose_quality_gate(guard, None, SPEC)
    reasons = []
    while True:
        block = guard.read()
        if block is None:
            if not guard.available:
                break
            continue
        report = gate.update(block)
        if report.source_vetoed and report.source_health is not None \
                and report.source_health.epoch == 1:
            reasons.append(report.integrity_reason)
    assert reasons and reasons[0].startswith(prefix)
    is_stream = reasons[0].startswith(pipeline_mod._STREAM_REASON)
    assert ("stream" if is_stream else "quality") == category
    assert "/dev/" not in reasons[0]                    # no port, no value from the signal


def test_tg07_stale_contact_closes_the_gate(monkeypatch) -> None:
    # Reports stop after second 3: the pair at 7.5/7.8 is > 3 s past the last report.
    runner = _run_trace(monkeypatch, blinks=LATE_PAIR,
                        contact=lambda second: 0 if second <= 3 else None)
    assert _n_double(runner) == 0
    assert "contact_stale" in runner.status()["pipeline"]["reason"]


def test_unknown_provenance_is_vetoed(monkeypatch) -> None:
    """A source the spec says is ThinkGear but that gives no verdict: nothing passes."""
    src = SyntheticSource("eeg", fs=512.0, seed=2, duration=8.0, mains_uv=0.0)
    for t in EARLY_PAIR:
        src.schedule_blink(t)
    runner = _runner_over(monkeypatch, src, SPEC)
    assert isinstance(runner._pipeline._parts.quality, SourceHealthGate)
    while True:
        try:
            if not runner.step():
                continue
        except EOFError:
            break
    assert runner.status()["events"]["accepted"] == 0
    assert "unknown provenance" in runner.status()["pipeline"]["reason"]


# ---------------------------------------------------------------- TG-12 provenance


class _HealthSource:
    """A health-reporting source whose blocks carry NaN: the guard sanitizes a copy."""

    fs = 512.0
    channels = (ChannelInfo("Fp1", SignalKind.EEG),)

    def __init__(self, trusted: bool = True, explode: bool = False) -> None:
        self._t = 0
        self._trusted = trusted
        self._explode = explode
        self.verdicts: dict[int, Any] = {}

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def read(self) -> SampleBlock:
        data = np.zeros((1, 64))
        data[0, 3] = np.nan
        block = SampleBlock(data=data, fs=self.fs, channels=self.channels, t0=self._t / self.fs)
        self._t += 64
        self.verdicts[id(block)] = MagicMock(trusted=self._trusted, session=1, epoch=0,
                                             reason=HealthReason.TRUSTED)
        self._last = block
        return block

    def health_for(self, block: SampleBlock) -> Any:
        if self._explode:
            raise RuntimeError("health lookup broke")
        return self.verdicts.get(id(block))


def test_tg12_provenance_survives_the_sanitized_copy() -> None:
    inner = _HealthSource()
    guard = guard_source(inner, SPEC)
    guard.start()
    out = guard.read()
    assert out is not None and out is not inner._last           # a sanitized copy
    assert np.isfinite(out.data).all()
    assert guard.health_for(out) is inner.verdicts[id(inner._last)]
    assert guard.health_for(inner._last) is None                # only the emitted block
    assert guard.health_for(dataclasses.replace(out)) is None   # by identity, not equality


def test_tg12_a_health_lookup_error_fails_closed_without_raising() -> None:
    inner = _HealthSource(explode=True)
    guard = guard_source(inner, SPEC)
    guard.start()
    gate = compose_quality_gate(guard, None, SPEC)
    block = guard.read()
    report = gate.update(block)
    assert report.overall == "BAD" and report.suppress_events
    assert "unknown provenance" in report.integrity_reason


def test_an_inner_gate_error_fails_closed_and_keeps_the_veto() -> None:
    inner = _HealthSource()
    guard = guard_source(inner, SPEC)
    guard.start()
    broken = MagicMock()
    broken.update.side_effect = RuntimeError("quality monitor broke")
    gate = SourceHealthGate(guard, broken)
    report = gate.update(guard.read())
    assert report.overall == "BAD" and report.suppress_events and report.bad_during_update


def test_the_outer_gate_never_bypasses_an_inner_bad() -> None:
    inner = _HealthSource(trusted=True)
    guard = guard_source(inner, SPEC)
    guard.start()
    bad = MagicMock()
    bad.update.return_value = MagicMock(overall="BAD", suppress_events=True,
                                        bad_during_update=True, integrity_reason="")
    report = SourceHealthGate(guard, bad).update(guard.read())
    assert report.overall == "BAD" and report.suppress_events
    assert not report.source_vetoed


def test_a_health_gate_error_does_not_switch_the_pipeline_gate_off() -> None:
    """The pipeline drops a quality monitor that raises ("quality gate off"). The health
    gate must therefore never raise, whatever its collaborators do."""
    inner = _HealthSource(explode=True)
    guard = guard_source(inner, SPEC)
    guard.start()
    broken = MagicMock()
    broken.update.side_effect = RuntimeError("boom")
    parts = PipelineParts(quality=SourceHealthGate(guard, broken), detectors=[])
    pipeline = BiosignalPipeline(parts)
    for _ in range(3):
        pipeline.process(guard.read())
    assert "quality" not in pipeline._disabled
    assert pipeline.status.quality.lower() == "bad"


# ---------------------------------------------------------------- pipeline reset hook


class _Counting:
    def __init__(self) -> None:
        self.resets = 0

    def process(self, block: SampleBlock) -> list[BioEvent]:
        return []

    def reset(self) -> None:
        self.resets += 1


def _report(**kw: Any) -> Any:
    base = dict(overall="GOOD", suppress_events=False, bad_during_update=False,
                integrity_reason="")
    base.update(kw)
    return type("R", (), base)()


def test_the_pipeline_resets_detectors_only_when_asked() -> None:
    det = _Counting()
    quality = MagicMock()
    quality.update.return_value = _report()
    pipeline = BiosignalPipeline(PipelineParts(quality=quality, detectors=[det]))
    block = SampleBlock(data=np.zeros((1, 32)), fs=512.0,
                        channels=(ChannelInfo("Fp1", SignalKind.EEG),), t0=0.0)
    pipeline.process(block)
    assert det.resets == 0
    quality.update.return_value = _report(reset_detector_state=True, overall="BAD")
    pipeline.process(dataclasses.replace(block, t0=1.0))
    assert det.resets == 1
    quality.update.return_value = MagicMock()          # a Mock attribute is not a request
    pipeline.process(dataclasses.replace(block, t0=2.0))
    assert det.resets == 1


# ---------------------------------------------------------------- TG-15 held action


class _Squeezer:
    """A scripted hold: SQUEEZE_ON in the first block it sees after ``on_at`` s."""

    def __init__(self, on_at: float) -> None:
        self.on_at = on_at
        self.fired = False

    def process(self, block: SampleBlock) -> list[BioEvent]:
        if not self.fired and block.t0 >= self.on_at:
            self.fired = True
            return [BioEvent(EventKind.SQUEEZE_ON, t=block.t0, confidence=1.0,
                             detail={"level": "light"})]
        return []

    def reset(self) -> None:
        pass


def _held_rig(trace, clock):
    starts: list[str] = []
    ends: list[int] = []
    source = trace_source(trace, clock)
    guard = guard_source(source, SPEC)
    squeezer = _Squeezer(on_at=2.0)

    def make_pipeline(src: Any) -> BiosignalPipeline:
        return BiosignalPipeline(PipelineParts(
            quality=compose_quality_gate(src, None, SPEC), detectors=[squeezer]))

    runner = BiosignalRunner(lambda: guard, make_pipeline,
                             RunnerCallbacks(on_mode_start=starts.append,
                                             on_mode_end=lambda: ends.append(1)),
                             watchdog_seconds=1.5, clock=clock)
    opened = runner._open()
    runner._source, runner._pipeline = opened, make_pipeline(opened)
    return runner, starts, ends, squeezer


def test_tg15_a_fault_releases_a_held_action_exactly_once(monkeypatch) -> None:
    clock = FakeClock()
    trace = build_trace(blink_counts((), 6.0), inject=((3.0, quality(200)),))
    runner, starts, ends, _ = _held_rig(trace, clock)
    _drain(runner)
    runner.check_watchdog(clock.t + 10.0)
    runner.stop()
    assert starts == ["full_text"] and ends == [1]


def test_tg15_health_fault_without_a_block_then_silence_is_released_by_the_watchdog() -> None:
    clock = FakeClock()
    trace = build_trace(blink_counts((), 2.6))
    trace.reads.append(quality(200))                    # health-only read, then silence
    trace.dt.append(0.05)
    runner, starts, ends, _ = _held_rig(trace, clock)
    _drain(runner)
    assert starts == ["full_text"] and ends == []       # still held: no block came
    assert runner.check_watchdog(clock.t + 1.6) is True
    assert runner.check_watchdog(clock.t + 9.0) is False
    runner.stop()
    assert ends == [1]


def test_tg15_no_new_activation_until_rearmed(monkeypatch) -> None:
    clock = FakeClock()
    # loss at 3.0 s; the scripted hold would fire at 3.5 s, inside the untrusted stretch
    trace = build_trace(blink_counts((), 7.0), inject=((3.0, quality(200)),))
    starts: list[str] = []
    ends: list[int] = []
    source = trace_source(trace, clock)
    guard = guard_source(source, SPEC)
    squeezer = _Squeezer(on_at=3.5)

    def make_pipeline(src: Any) -> BiosignalPipeline:
        return BiosignalPipeline(PipelineParts(
            quality=compose_quality_gate(src, None, SPEC), detectors=[squeezer]))

    runner = BiosignalRunner(lambda: guard, make_pipeline,
                             RunnerCallbacks(on_mode_start=starts.append,
                                             on_mode_end=lambda: ends.append(1)),
                             watchdog_seconds=0.0, clock=clock)
    opened = runner._open()
    runner._source, runner._pipeline = opened, make_pipeline(opened)
    _drain(runner)
    assert squeezer.fired and starts == [] and ends == []


def test_tg15_a_held_action_is_released_once_across_fault_watchdog_and_stop(caplog) -> None:
    clock = FakeClock()
    trace = build_trace(blink_counts((), 4.0), inject=((3.0, quality(1)),))
    runner, starts, ends, _ = _held_rig(trace, clock)
    with caplog.at_level(logging.DEBUG):
        _drain(runner)
        for dt in (2.0, 5.0, 60.0):
            runner.check_watchdog(clock.t + dt)
        runner.stop()
        runner.stop()
    assert starts == ["full_text"] and ends == [1]
