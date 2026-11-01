"""Tests for ``yazses.biosignal.integrity``: the stream-contract guard, its pipeline hook, and
the linear resampler.

Offline and deterministic: the in-tree ``SyntheticSource`` / ``FileReplaySource`` for the
"a correct source never trips it" side, small scripted fakes for every broken stream, and an
injected clock for stalls and arrival rate.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import pytest

from yazses.biosignal.integrity import (
    RECOVER_S,
    STALL_S,
    STARTUP_GRACE_S,
    GatedQualityReport,
    IntegrityGate,
    IntegrityGuard,
    IntegrityThresholds,
    LinearResampler,
    StreamIntegrityChecker,
    Violation,
    structural_problem,
)
from yazses.biosignal.pipeline import BiosignalPipeline, PipelineParts
from yazses.biosignal.quality import SignalQualityMonitor
from yazses.biosignal.sources import FileReplaySource, SyntheticSource, iter_blocks, write_csv
from yazses.biosignal.types import (
    BioEvent,
    BlockSource,
    ChannelInfo,
    EventKind,
    SampleBlock,
    SignalKind,
)

CH2 = (ChannelInfo("C3", SignalKind.EEG), ChannelInfo("C4", SignalKind.EEG))
SWAPPED = (CH2[1], CH2[0])


# ------------------------------------------------------------------ helpers


class FakeClock:
    def __init__(self, t: float = 100.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def blk(t0: float, n: int = 10, fs: float = 250.0,
        channels: tuple[ChannelInfo, ...] = CH2, data: Any = None) -> SampleBlock:
    if data is None:
        k = np.arange(n) + round(t0 * fs)
        data = np.vstack([np.sin(2 * np.pi * 7.0 * k / fs + i) * 20.0
                          for i in range(len(channels))])
    return SampleBlock(data=data, fs=fs, channels=channels, t0=t0)


def contiguous(n_blocks: int, n: int = 10, fs: float = 250.0, t0: float = 0.0,
               channels: tuple[ChannelInfo, ...] = CH2) -> list[SampleBlock]:
    return [blk(t0 + i * n / fs, n, fs, channels) for i in range(n_blocks)]


class FakeDevice:
    """A scripted ``BlockSource``. ``mutate(k, block)`` may return anything (or raise),
    which is how each broken driver is modelled. ``stamp_fs`` is the rate t0 is stamped
    at (a device clock disagreeing with the declared ``fs``). With ``clock`` and
    ``arrival_fs`` each delivered block advances the clock by its arrival time."""

    def __init__(self, *, fs: float = 250.0, n: int = 10,
                 channels: tuple[ChannelInfo, ...] = CH2, stamp_fs: float | None = None,
                 limit: int | None = None,
                 mutate: Callable[[int, SampleBlock], Any] | None = None,
                 clock: FakeClock | None = None, arrival_fs: float | None = None) -> None:
        self.fs = fs
        self.channels = channels
        self._n = n
        self._stamp = stamp_fs or fs
        self._limit = limit
        self._mutate = mutate
        self._clock = clock
        self._arrival = arrival_fs
        self.k = 0
        self.extra = "forwarded"

    def start(self) -> None:
        self.k = 0

    def read(self) -> Any:
        if self._limit is not None and self.k >= self._limit:
            raise EOFError("done")
        out: Any = blk(self.k * self._n / self._stamp, self._n, self.fs, self.channels)
        if self._mutate is not None:
            out = self._mutate(self.k, out)
        if self._clock is not None and self._arrival:
            self._clock.advance(self._n / self._arrival)
        self.k += 1
        return out

    def stop(self) -> None:
        return None


def drain_guard(guard: IntegrityGuard) -> list[SampleBlock | None]:
    out: list[SampleBlock | None] = []
    guard.start()
    while True:
        try:
            out.append(guard.read())
        except EOFError:
            return out


def check_all(blocks: list[Any], thresholds: IntegrityThresholds | None = None):
    checker = StreamIntegrityChecker(thresholds)
    verdicts = [checker.check(b) for b in blocks]
    return checker, verdicts


def codes(verdict) -> set[str]:
    return {v.code for v in verdict.violations}


# ------------------------------------------------------------------ correct sources


@pytest.mark.parametrize("kind", ["emg", "eeg", "eog", "mixed"])
def test_synthetic_source_never_trips_the_guard(kind: str) -> None:
    guard = IntegrityGuard(SyntheticSource(kind, duration=15.0, seed=3))
    blocks = drain_guard(guard)
    report = guard.report
    assert report.ok and report.violations == 0
    assert not report.gate_closed and report.dropped_blocks == 0
    assert all(b is not None for b in blocks)
    assert report.observed_fs == pytest.approx(guard.fs)   # a full rate window was judged


def test_clean_blocks_pass_through_unchanged_by_identity() -> None:
    inner = SyntheticSource("eeg", duration=1.0)
    raw = list(iter_blocks(SyntheticSource("eeg", duration=1.0), sleep=lambda _s: None))
    guarded = [b for b in drain_guard(IntegrityGuard(inner)) if b is not None]
    assert len(raw) == len(guarded)
    for a, b in zip(raw, guarded):
        np.testing.assert_array_equal(a.data, b.data)
        assert a.t0 == b.t0


def test_file_replay_never_trips_the_guard(tmp_path) -> None:
    path = tmp_path / "rec.csv"
    write_csv(path, iter_blocks(SyntheticSource("mixed", duration=12.0), sleep=lambda _s: None))
    guard = IntegrityGuard(FileReplaySource(path, block_samples=37))
    drain_guard(guard)
    assert guard.report.ok, guard.report.format()


def test_guard_is_a_block_source_and_forwards_attributes() -> None:
    inner = FakeDevice()
    guard = IntegrityGuard(inner)
    assert isinstance(guard, BlockSource)
    assert guard.extra == "forwarded"
    assert guard.inner is inner
    with pytest.raises(AttributeError):
        guard._nope  # noqa: B018 - private names are never forwarded


def test_guard_mirrors_declared_layout_known_only_after_start() -> None:
    class LateLayout(FakeDevice):
        def __init__(self) -> None:
            super().__init__()
            self.fs, self.channels = 0.0, ()

        def start(self) -> None:
            super().start()
            self.fs, self.channels = 250.0, CH2

    guard = IntegrityGuard(LateLayout())
    assert guard.fs == 0.0 and guard.channels == ()
    guard.start()
    assert guard.fs == 250.0 and guard.channels == CH2


def test_exceptions_of_the_inner_source_pass_through() -> None:
    def boom(_k: int, _b: SampleBlock) -> Any:
        raise RuntimeError("driver crashed")

    guard = IntegrityGuard(FakeDevice(mutate=boom))
    guard.start()
    with pytest.raises(RuntimeError, match="driver crashed"):
        guard.read()
    eof = IntegrityGuard(FakeDevice(limit=0))
    eof.start()
    with pytest.raises(EOFError):
        eof.read()


# ------------------------------------------------------------------ t0 contract


def test_duplicated_t0_closes_the_gate_then_recovers_on_clean_stream() -> None:
    blocks = contiguous(5)
    dup = blk(blocks[-1].t0)                         # the same buffer delivered twice
    tail = contiguous(40, t0=blocks[-1].t0 + 10 / 250.0)
    checker, verdicts = check_all(blocks + [dup] + tail)
    assert all(not v.gate_closed for v in verdicts[:5])
    assert codes(verdicts[5]) == {Violation.T0_BACKWARDS}
    assert "repeated" in verdicts[5].violations[0].detail
    # The tail continues from the duplicate's end, so the duplicate is the only breach.
    reopened = next(i for i, v in enumerate(verdicts) if i > 5 and not v.gate_closed)
    clean_s = sum(b.duration for b in (blocks + [dup] + tail)[6:reopened + 1])
    assert clean_s == pytest.approx(RECOVER_S, abs=10 / 250.0)
    assert checker.report.counts == {Violation.T0_BACKWARDS: 1}
    assert not checker.gate_closed


def test_t0_going_backwards_is_reported() -> None:
    _, verdicts = check_all([blk(1.0), blk(0.5)])
    assert codes(verdicts[1]) == {Violation.T0_BACKWARDS}
    assert "went back" in verdicts[1].violations[0].detail


def test_gap_is_dropped_packets_and_counts_lost_time() -> None:
    blocks = contiguous(3)
    after = blk(blocks[-1].t0 + 10 / 250.0 + 0.2)
    checker, verdicts = check_all(blocks + [after])
    assert codes(verdicts[-1]) == {Violation.GAP}
    assert verdicts[-1].gate_closed
    assert checker.report.lost_s == pytest.approx(0.2)
    assert "~50 sample(s)" in verdicts[-1].violations[0].detail


def test_overlap_is_a_resent_buffer() -> None:
    blocks = contiguous(3)
    early = blk(blocks[-1].t0 + 10 / 250.0 - 0.03)
    checker, verdicts = check_all(blocks + [early])
    assert codes(verdicts[-1]) == {Violation.OVERLAP}
    assert checker.report.overlap_s == pytest.approx(0.03)


def test_jitter_inside_the_tolerance_is_not_a_violation() -> None:
    fs, n = 250.0, 10
    rng = np.random.default_rng(0)
    jitter = rng.uniform(-0.004, 0.004, 50)          # 4 ms, well inside 20 ms
    blocks = [blk(i * n / fs + j, n, fs) for i, j in enumerate(jitter)]
    checker, verdicts = check_all(blocks)
    assert checker.report.ok, checker.report.format()


def test_tolerance_is_at_least_one_and_a_half_samples_at_a_low_rate() -> None:
    fs = 50.0                                        # 1.5 samples = 30 ms > 20 ms
    blocks = [blk(0.0, 5, fs), blk(5 / fs + 0.025, 5, fs)]
    checker, _ = check_all(blocks)
    assert checker.report.ok


def test_a_clockless_source_fails_closed_by_default_and_can_be_allowed() -> None:
    blocks = [blk(0.0) for _ in range(30)]
    strict, verdicts = check_all(blocks)
    assert strict.report.counts[Violation.T0_BACKWARDS] == 29
    assert all(v.gate_closed for v in verdicts[1:])
    lenient, _ = check_all(blocks, IntegrityThresholds(require_clock=False))
    assert lenient.report.ok


# ------------------------------------------------------------------ layout contract


def test_channel_swap_mid_stream_is_a_layout_change() -> None:
    blocks = contiguous(5)
    swapped = contiguous(40, t0=5 * 10 / 250.0, channels=SWAPPED)
    checker, verdicts = check_all(blocks + swapped)
    assert codes(verdicts[5]) == {Violation.LAYOUT_CHANGED}
    assert "order changed: C3,C4 -> C4,C3" in verdicts[5].violations[0].detail
    # The new layout is adopted: one violation, not one per block.
    assert checker.report.counts == {Violation.LAYOUT_CHANGED: 1}
    assert not verdicts[-1].gate_closed


def test_channel_kind_and_set_changes_are_described() -> None:
    relabelled = (ChannelInfo("C3", SignalKind.EMG), CH2[1])
    _, v1 = check_all([blk(0.0), blk(0.04, channels=relabelled)])
    assert "kind changed: C3:eeg->emg" in v1[1].violations[0].detail
    other = (CH2[0], ChannelInfo("Cz", SignalKind.EEG))
    _, v2 = check_all([blk(0.0), blk(0.04, channels=other)])
    assert "removed ['C4'], added ['Cz']" in v2[1].violations[0].detail


def test_sampling_rate_change_mid_stream() -> None:
    _, verdicts = check_all([blk(0.0, fs=250.0), blk(0.04, fs=500.0)])
    assert Violation.FS_CHANGED in codes(verdicts[1])


def test_block_disagreeing_with_the_declared_layout_is_flagged() -> None:
    device = FakeDevice(mutate=lambda k, b: blk(b.t0, fs=500.0) if k == 3 else b)
    guard = IntegrityGuard(device)
    out = drain_guard_n(guard, 6)
    assert Violation.DECLARED_MISMATCH in guard.report.counts
    assert out[3] is not None                        # passed on, but with the gate closed
    assert guard.gate_closed_for(out[3])


def drain_guard_n(guard: IntegrityGuard, n: int) -> list[SampleBlock | None]:
    guard.start()
    return [guard.read() for _ in range(n)]


# ------------------------------------------------------------------ samples


def test_nan_burst_is_sanitized_flagged_and_the_original_untouched() -> None:
    data = blk(0.04).data.copy()
    data[0, 2:5] = np.nan
    data[1, 7] = np.inf
    nan_block = blk(0.04, data=data)
    checker, verdicts = check_all([blk(0.0), nan_block, blk(0.08)])
    v = verdicts[1]
    assert codes(v) == {Violation.NON_FINITE}
    assert "4 non-finite sample(s) of 20" in v.violations[0].detail
    assert v.block is not None and v.block is not nan_block
    assert np.isfinite(v.block.data).all()
    assert (v.block.data[0, 2:5] == 0.0).all() and v.block.data[1, 7] == 0.0
    assert np.isnan(nan_block.data[0, 2])            # the caller's array is not mutated
    assert verdicts[2].gate_closed                   # still inside the hold-off


def test_nan_block_is_dropped_when_sanitizing_is_off() -> None:
    data = blk(0.0).data.copy()
    data[0, 0] = np.nan
    checker, verdicts = check_all([blk(0.0, data=data)],
                                  IntegrityThresholds(sanitize_non_finite=False))
    assert verdicts[0].block is None and checker.report.dropped_blocks == 1


def test_integer_samples_are_accepted() -> None:
    block = blk(0.0, data=np.zeros((2, 10), dtype=np.int32))
    checker, verdicts = check_all([block])
    assert verdicts[0].block is block and checker.report.ok


@pytest.mark.parametrize(("bad", "code"), [
    ("not a block", Violation.NOT_A_BLOCK),
    (SampleBlock(np.zeros(10), 250.0, CH2, 0.0), Violation.BAD_SHAPE),
    (SampleBlock(np.zeros((3, 10)), 250.0, CH2, 0.0), Violation.BAD_SHAPE),
    (SampleBlock([[0.0] * 10] * 2, 250.0, CH2, 0.0), Violation.BAD_SHAPE),  # type: ignore[arg-type]
    (SampleBlock(np.zeros((2, 10), dtype=complex), 250.0, CH2, 0.0), Violation.BAD_DTYPE),
    (SampleBlock(np.zeros((2, 10), dtype=object), 250.0, CH2, 0.0), Violation.BAD_DTYPE),
    (SampleBlock(np.zeros((2, 10)), 0.0, CH2, 0.0), Violation.BAD_FS),
    (SampleBlock(np.zeros((2, 10)), float("nan"), CH2, 0.0), Violation.BAD_FS),
    (SampleBlock(np.zeros((2, 10)), 250.0, (CH2[0], CH2[0]), 0.0), Violation.BAD_CHANNELS),
    (SampleBlock(np.zeros((0, 10)), 250.0, (), 0.0), Violation.BAD_CHANNELS),
    (SampleBlock(np.zeros((2, 10)), 250.0, CH2, float("inf")), Violation.T0_INVALID),
])
def test_unusable_blocks_are_dropped_and_counted(bad: Any, code: str) -> None:
    assert structural_problem(bad) is not None
    guard = IntegrityGuard(FakeDevice(mutate=lambda k, b: bad if k == 1 else b))
    out = drain_guard_n(guard, 3)
    assert out[0] is not None and out[1] is None and out[2] is not None
    assert guard.report.counts.get(code) == 1
    assert guard.report.dropped_blocks == 1
    assert guard.gate_closed                         # the hold-off runs from the drop


def test_empty_block_passes_without_moving_the_clock() -> None:
    empty = SampleBlock(np.zeros((2, 0)), 250.0, CH2, 0.04)
    checker, verdicts = check_all([blk(0.0), empty, blk(0.04)])
    assert checker.report.ok and verdicts[1].block is empty


# ------------------------------------------------------------------ rate


def test_rate_drift_from_device_timestamps() -> None:
    # A board that stamps its real 245 Hz clock while declaring 250 Hz: every block lands
    # 0.8 ms "late", far inside the gap tolerance, but 2 % adds up.
    guard = IntegrityGuard(FakeDevice(stamp_fs=245.0, limit=400))
    drain_guard(guard)
    report = guard.report
    assert Violation.RATE_DRIFT in report.counts
    assert Violation.GAP not in report.counts
    assert report.observed_fs == pytest.approx(245.0, rel=1e-3)
    assert report.gate_closed                        # a permanently wrong rate stays closed


def test_rate_inside_the_tolerance_is_fine() -> None:
    guard = IntegrityGuard(FakeDevice(stamp_fs=250.0 * 1.005, limit=400))
    drain_guard(guard)
    assert guard.report.ok and guard.report.observed_fs is not None


def test_rate_is_not_judged_before_a_full_window() -> None:
    guard = IntegrityGuard(FakeDevice(stamp_fs=200.0, limit=100))   # 5 s at 200 Hz
    drain_guard(guard)
    assert guard.report.observed_fs is None and guard.report.ok


def test_arrival_rate_is_opt_in_and_catches_a_slow_device() -> None:
    clock = FakeClock()
    slow = FakeDevice(limit=400, clock=clock, arrival_fs=200.0)
    guard = IntegrityGuard(slow, clock=clock, check_arrival_rate=True)
    drain_guard(guard)
    assert Violation.ARRIVAL_DRIFT in guard.report.counts
    assert guard.report.arrival_fs == pytest.approx(200.0, rel=1e-6)

    clock2 = FakeClock()
    off = IntegrityGuard(FakeDevice(limit=400, clock=clock2, arrival_fs=200.0), clock=clock2)
    drain_guard(off)
    assert off.report.ok and off.report.arrival_fs is None


def test_arrival_rate_on_time_is_fine() -> None:
    clock = FakeClock()
    guard = IntegrityGuard(FakeDevice(limit=400, clock=clock, arrival_fs=250.0),
                           clock=clock, check_arrival_rate=True)
    drain_guard(guard)
    assert guard.report.ok
    assert guard.report.arrival_fs == pytest.approx(250.0)


# ------------------------------------------------------------------ stalls


class Silent(FakeDevice):
    """Delivers ``deliver`` blocks, then returns None until ``resume_at`` blocks are owed."""

    def __init__(self, deliver: int, **kw: Any) -> None:
        super().__init__(**kw)
        self.deliver = deliver
        self.silent = False

    def read(self) -> Any:
        if self.silent or self.k >= self.deliver:
            return None
        return super().read()


def test_stall_is_flagged_once_by_the_injected_clock_and_clears_on_resume() -> None:
    clock = FakeClock()
    device = Silent(3)
    guard = IntegrityGuard(device, clock=clock)
    guard.start()
    for _ in range(3):
        assert guard.read() is not None
    for _ in range(10):                              # polled through a 2 s silence
        clock.advance(0.2)
        assert guard.read() is None
    report = guard.report
    assert report.counts == {Violation.STALL: 1}
    assert report.stalled and report.gate_closed
    assert "no block for" in report.last_violation.detail

    device.deliver = 100                             # the device comes back
    block = guard.read()
    assert block is not None
    assert not guard.report.stalled
    assert guard.gate_closed_for(block)              # held until RECOVER_S of clean stream


def test_no_stall_inside_the_limit() -> None:
    clock = FakeClock()
    guard = IntegrityGuard(Silent(2), clock=clock)
    guard.start()
    guard.read()
    guard.read()
    clock.advance(STALL_S * 0.9)
    assert guard.read() is None
    assert guard.report.ok


def test_startup_grace_then_stall_before_the_first_block() -> None:
    clock = FakeClock()
    guard = IntegrityGuard(Silent(0), clock=clock)
    guard.start()
    clock.advance(STARTUP_GRACE_S * 0.9)
    guard.read()
    assert guard.report.ok                           # a board may still be opening
    clock.advance(STARTUP_GRACE_S * 0.2)
    guard.read()
    assert guard.report.counts == {Violation.STALL: 1}


def test_a_silence_nobody_polled_through_is_still_a_stall() -> None:
    clock = FakeClock()
    guard = IntegrityGuard(FakeDevice(), clock=clock)
    guard.start()
    guard.read()
    clock.advance(STALL_S + 1.0)                     # e.g. read() itself blocked
    block = guard.read()
    assert guard.report.counts == {Violation.STALL: 1}
    assert guard.gate_closed_for(block)


def test_start_begins_a_fresh_judgement() -> None:
    guard = IntegrityGuard(FakeDevice(mutate=lambda k, b: blk(0.0) if k == 2 else b))
    drain_guard_n(guard, 4)
    assert not guard.report.ok
    guard.start()
    assert guard.report.ok and guard.report.blocks == 0


# ------------------------------------------------------------------ recovery


@pytest.mark.parametrize("n", [5, 10, 25])
def test_recovery_is_measured_in_stream_time_not_blocks(n: int) -> None:
    fs = 250.0
    head = contiguous(4, n, fs)
    gap_t0 = head[-1].t0 + n / fs + 0.5
    tail = contiguous(int(3 * fs / n), n, fs, t0=gap_t0)
    _, verdicts = check_all(head + tail)
    first_open = next(i for i, v in enumerate(verdicts) if i >= len(head) and not v.gate_closed)
    reopened_at = (head + tail)[first_open].t0 + n / fs
    # The gap block itself is not clean, so the clean second starts after it.
    assert reopened_at - (gap_t0 + n / fs) == pytest.approx(RECOVER_S, abs=1e-9)


def test_recover_zero_closes_only_the_offending_block() -> None:
    thr = IntegrityThresholds(recover_s=0.0)
    _, verdicts = check_all([blk(0.0), blk(1.0), blk(1.04)], thr)
    assert [v.gate_closed for v in verdicts] == [False, True, False]


# ------------------------------------------------------------------ report


def test_report_format_and_dict() -> None:
    checker, _ = check_all([blk(0.0), blk(0.5)])
    report = checker.report
    text = report.format()
    assert "gate CLOSED" in text and "gap x1" in text and "lost" in text
    d = report.as_dict()
    assert d["gate_closed"] is True and d["violations"] == {"gap": 1}
    assert d["last_violation"]["code"] == "gap" and d["last_violation"]["block"] == 2
    assert report.reason().startswith("stream integrity: gap")
    assert report.violations == 1 and not report.ok


def test_report_reason_is_empty_while_open() -> None:
    checker, _ = check_all(contiguous(3))
    assert checker.report.reason() == "" and "gate open" in checker.report.format()


# ------------------------------------------------------------------ the pipeline hook


class OnceSqueeze:
    """Detector double: SQUEEZE_ON on the first block, then nothing (holds forever)."""

    def __init__(self) -> None:
        self.fired = False

    def process(self, block: SampleBlock) -> list[BioEvent]:
        if self.fired:
            return []
        self.fired = True
        return [BioEvent(EventKind.SQUEEZE_ON, block.t0, 1.0)]

    def reset(self) -> None:
        return None


class BlinkEveryBlock:
    def process(self, block: SampleBlock) -> list[BioEvent]:
        return [BioEvent(EventKind.BLINK, block.t0, 1.0)]

    def reset(self) -> None:
        return None


def gap_after(k_gap: int, gap_s: float = 0.5) -> Callable[[int, SampleBlock], SampleBlock]:
    def mutate(k: int, b: SampleBlock) -> SampleBlock:
        return blk(b.t0 + gap_s, data=b.data) if k >= k_gap else b
    return mutate


def test_gate_closes_the_real_pipeline_and_releases_a_held_squeeze() -> None:
    guard = IntegrityGuard(FakeDevice(mutate=gap_after(5)))
    pipeline = BiosignalPipeline(PipelineParts(detectors=[OnceSqueeze()],
                                               quality=IntegrityGate(guard)))
    guard.start()
    first = pipeline.process(guard.read())
    assert [e.kind for e in first.events] == [EventKind.SQUEEZE_ON]
    for _ in range(4):
        pipeline.process(guard.read())
    assert pipeline.squeeze_active
    result = pipeline.process(guard.read())         # the gap block
    offs = [e for e in result.events if e.kind is EventKind.SQUEEZE_OFF]
    assert len(offs) == 1 and offs[0].detail.get("synthetic") is True
    assert not pipeline.squeeze_active
    assert result.status.quality == "bad"


def test_gate_drops_events_while_closed_and_reopens_after_clean_stream() -> None:
    guard = IntegrityGuard(FakeDevice(mutate=gap_after(3)))
    pipeline = BiosignalPipeline(PipelineParts(detectors=[BlinkEveryBlock()],
                                               quality=IntegrityGate(guard)))
    guard.start()
    results = [pipeline.process(guard.read()) for _ in range(40)]
    accepted = [len(r.events) for r in results]
    assert accepted[:3] == [1, 1, 1]
    assert accepted[3] == 0 and results[3].dropped[0].reason == "stream"
    closed_blocks = accepted.index(1, 3) - 3
    assert closed_blocks == round(RECOVER_S * 250.0 / 10)   # 1 s of 40 ms blocks
    assert all(a == 1 for a in accepted[3 + closed_blocks:])


def test_gate_fails_closed_on_a_block_it_did_not_emit() -> None:
    guard = IntegrityGuard(FakeDevice())
    gate = IntegrityGate(guard)
    guard.start()
    assert not gate.update(guard.read()).suppress_events
    stranger = blk(0.04)
    report = gate.update(stranger)
    assert report.suppress_events and report.overall == "BAD"
    assert report.integrity_closed


def test_gate_wraps_the_real_quality_monitor_without_hiding_it() -> None:
    guard = IntegrityGuard(SyntheticSource("eeg", duration=6.0))
    monitor = SignalQualityMonitor()
    gate = IntegrityGate(guard, monitor)
    guard.start()
    last: GatedQualityReport | None = None
    for _ in range(100):
        last = gate.update(guard.read())
    assert last is not None and not last.integrity_closed
    assert last.overall is monitor.report.overall    # the monitor's own verdict while open
    assert last.inner is monitor.report
    assert gate.report is monitor.report             # cli_impl reads parts.quality.report
    assert last.channels == monitor.report.channels  # unknown fields come from the inner report
    assert last.integrity_reason == ""
    gate.reset()
    assert monitor.report is None
    assert guard.report.blocks == 100                # the stream's history is kept


def test_a_failing_quality_monitor_leaves_the_integrity_gate_on() -> None:
    class Broken:
        report = None

        def update(self, block: SampleBlock) -> Any:
            raise RuntimeError("monitor bug")

        def reset(self) -> None:
            return None

    guard = IntegrityGuard(FakeDevice(mutate=gap_after(2)))
    gate = IntegrityGate(guard, Broken())
    guard.start()
    assert gate.update(guard.read()).overall == "GOOD"
    assert gate.inner is None
    gate.update(guard.read())
    closed = gate.update(guard.read())
    assert closed.suppress_events and closed.integrity_reason.startswith("stream integrity: gap")


def test_gated_report_without_inner_has_no_extra_attributes() -> None:
    guard = IntegrityGuard(FakeDevice())
    guard.start()
    report = IntegrityGate(guard).update(guard.read())
    with pytest.raises(AttributeError):
        report.channels  # noqa: B018


# ------------------------------------------------------------------ resampler


def sine_blocks(fs: float, seconds: float, sizes: list[int], f: float = 5.0) -> list[SampleBlock]:
    total = int(round(fs * seconds))
    k = np.arange(total)
    data = np.vstack([np.sin(2 * np.pi * f * k / fs), np.cos(2 * np.pi * f * k / fs)]) * 50.0
    out, pos, i = [], 0, 0
    while pos < total:
        n = min(sizes[i % len(sizes)], total - pos)
        out.append(SampleBlock(data[:, pos:pos + n], fs, CH2, pos / fs))
        pos += n
        i += 1
    return out


def run_resampler(blocks: list[SampleBlock], fs_out: float) -> list[SampleBlock]:
    rs = LinearResampler(fs_out)
    return [o for o in (rs.process(b) for b in blocks) if o is not None]


def test_resampler_tracks_a_slow_sine_and_keeps_time() -> None:
    out = run_resampler(sine_blocks(256.0, 4.0, [32]), 250.0)
    data = np.concatenate([o.data for o in out], axis=1)
    t = np.arange(data.shape[1]) / 250.0
    np.testing.assert_allclose(data[0], 50.0 * np.sin(2 * np.pi * 5.0 * t), atol=0.1)
    assert all(o.fs == 250.0 for o in out)
    for a, b in zip(out, out[1:]):                   # contiguous output time base
        assert b.t0 == pytest.approx(a.t0 + a.n_samples / 250.0)
    # The guard agrees: a resampled stream keeps the contract.
    checker, _ = check_all(out)
    assert checker.report.ok


def test_resampler_output_does_not_depend_on_block_size() -> None:
    a = run_resampler(sine_blocks(256.0, 3.0, [32]), 250.0)
    b = run_resampler(sine_blocks(256.0, 3.0, [1, 7, 64, 13]), 250.0)
    da = np.concatenate([o.data for o in a], axis=1)
    db = np.concatenate([o.data for o in b], axis=1)
    assert da.shape == db.shape
    np.testing.assert_allclose(da, db, rtol=0, atol=1e-9)


def test_resampler_upsamples_and_passes_equal_rates_through() -> None:
    block = SampleBlock(np.ones((2, 10)), 250.0, CH2, 0.0)
    assert LinearResampler(250.0).process(block) is block
    out = run_resampler(sine_blocks(125.0, 2.0, [25]), 250.0)
    assert sum(o.n_samples for o in out) == pytest.approx(500, abs=2)


def test_resampler_refuses_decimation_without_an_anti_alias_filter() -> None:
    with pytest.raises(ValueError, match="anti-alias"):
        LinearResampler(250.0).process(SampleBlock(np.zeros((2, 10)), 1000.0, CH2, 0.0))
    with pytest.raises(ValueError):
        LinearResampler(0.0)


def test_resampler_restarts_its_run_across_a_gap() -> None:
    blocks = sine_blocks(256.0, 1.0, [32])
    moved = [SampleBlock(b.data, b.fs, b.channels, b.t0 + 5.0) for b in blocks]
    rs = LinearResampler(250.0)
    for b in blocks:
        rs.process(b)
    first_after = rs.process(moved[0])
    assert first_after is not None and first_after.t0 == pytest.approx(5.0)
