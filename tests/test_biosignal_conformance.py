"""Tests for ``yazses.biosignal.conformance``: the source conformance kit.

The in-tree sources must pass; each deliberately broken fake must fail on exactly the
clause it breaks, with a message that says why. Offline: a fake clock whose ``sleep``
advances it keeps every run instant and deterministic.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import pytest

from yazses.biosignal.conformance import (
    MIN_RATE_SPAN_S,
    ConformanceReport,
    check_source,
)
from yazses.biosignal.integrity import IntegrityGuard, IntegrityThresholds
from yazses.biosignal.sources import FileReplaySource, SyntheticSource, iter_blocks, write_csv
from yazses.biosignal.types import ChannelInfo, SampleBlock, SignalKind

CH2 = (ChannelInfo("C3", SignalKind.EEG), ChannelInfo("C4", SignalKind.EEG))

ALL_CLAUSES = (
    "protocol", "stop_before_start", "start", "declared_fs", "declared_channels",
    "read_types", "first_block", "no_stall", "block_structure", "block_layout", "finite",
    "t0", "rate_t0", "rate_arrival", "read_after_eof", "stop", "stop_twice",
    "read_after_stop",
)


class FakeClock:
    def __init__(self) -> None:
        self.t = 50.0

    def __call__(self) -> float:
        return self.t

    def sleep(self, dt: float) -> None:
        self.t += dt


def run(source: Any, clock: FakeClock | None = None, **kw: Any) -> ConformanceReport:
    clock = clock or FakeClock()
    return check_source(source, clock=clock, sleep=clock.sleep, **kw)


def status(report: ConformanceReport, clause: str) -> str:
    return report.clause(clause).status


def failed(report: ConformanceReport) -> set[str]:
    return {c.clause for c in report.failures}


class Device:
    """A scripted driver. ``mutate(k, block)`` returns what ``read()`` hands out; with
    ``clock`` + ``arrival_fs`` every block costs its arrival time on the clock."""

    def __init__(self, *, fs: float = 250.0, n: int = 10,
                 channels: Any = CH2, stamp_fs: float | None = None,
                 limit: int | None = None,
                 mutate: Callable[[int, SampleBlock], Any] | None = None,
                 clock: FakeClock | None = None, arrival_fs: float | None = None) -> None:
        self.fs = fs
        self.channels = channels
        self._n, self._stamp, self._limit = n, stamp_fs or fs, limit
        self._mutate, self._clock, self._arrival = mutate, clock, arrival_fs
        self.k = 0
        self.stopped = False

    def start(self) -> None:
        self.k = 0
        self.stopped = False

    def read(self) -> Any:
        if self._limit is not None and self.k >= self._limit:
            raise EOFError("end")
        k = np.arange(self._n) + self.k * self._n
        data = np.vstack([np.sin(k / 9.0), np.cos(k / 7.0)]) * 30.0
        # Blocks carry the declared channels, or a valid pair when those are broken.
        chans = self.channels or CH2
        out: Any = SampleBlock(data, float(self.fs), chans, self.k * self._n / self._stamp)
        if self._mutate is not None:
            out = self._mutate(self.k, out)
        if self._clock is not None and self._arrival:
            self._clock.sleep(self._n / self._arrival)
        self.k += 1
        return out

    def stop(self) -> None:
        self.stopped = True


# ------------------------------------------------------------------ in-tree sources pass


@pytest.mark.parametrize("kind", ["emg", "eeg", "eog", "mixed"])
def test_finite_synthetic_source_passes_every_clause(kind: str) -> None:
    report = run(SyntheticSource(kind, duration=3.0))
    assert report.passed, report.format()
    assert tuple(c.clause for c in report.clauses) == ALL_CLAUSES
    assert status(report, "read_after_eof") == "pass"
    assert status(report, "rate_t0") == "pass"
    assert status(report, "rate_arrival") == "skip"          # faster than real time
    assert report.eof and report.blocks > 0 and not report.warnings


def test_endless_synthetic_source_stops_after_the_stream_budget() -> None:
    report = run(SyntheticSource("eeg"), seconds=4.0)
    assert report.passed, report.format()
    assert report.stream_s == pytest.approx(4.0, abs=0.05)
    assert status(report, "read_after_eof") == "skip"
    assert report.integrity is not None and report.integrity.ok


def test_realtime_synthetic_source_has_its_arrival_rate_judged() -> None:
    clock = FakeClock()
    source = SyntheticSource("eeg", realtime=True, clock=clock)
    report = run(source, clock, seconds=4.0)
    assert report.passed, report.format()
    assert status(report, "rate_arrival") == "pass"
    assert "250" in report.clause("rate_arrival").detail


def test_file_replay_source_passes(tmp_path) -> None:
    path = tmp_path / "rec.csv"
    write_csv(path, iter_blocks(SyntheticSource("mixed", duration=3.0), sleep=lambda _s: None))
    report = run(FileReplaySource(path))
    assert report.passed, report.format()
    assert report.eof and status(report, "read_after_eof") == "pass"


def test_file_replay_read_after_stop_mid_stream_is_only_a_warning(tmp_path) -> None:
    path = tmp_path / "long.csv"
    write_csv(path, iter_blocks(SyntheticSource("eeg", duration=10.0), sleep=lambda _s: None))
    report = run(FileReplaySource(path), seconds=3.0)
    # FileReplaySource.stop() is a no-op, so it keeps delivering: legal, but worth a word.
    assert report.passed, report.format()
    assert status(report, "read_after_stop") == "warn"


def test_the_integrity_guard_is_itself_a_conforming_source() -> None:
    report = run(IntegrityGuard(SyntheticSource("emg", duration=3.0)))
    assert report.passed, report.format()


def test_format_names_every_clause_and_the_verdict() -> None:
    report = run(SyntheticSource("eeg", duration=3.0))
    text = report.format()
    assert text.startswith("Source conformance: SyntheticSource — PASS")
    for clause in ALL_CLAUSES:
        assert clause in text
    assert not any(line.endswith(" ") for line in text.splitlines())


# ------------------------------------------------------------------ broken drivers fail


def test_missing_protocol_members() -> None:
    class Half:
        fs = 250.0

        def read(self) -> None:
            return None

    report = run(Half())
    assert status(report, "protocol") == "fail"
    assert "channels" in report.clause("protocol").detail and not report.passed


def test_stop_before_start_must_be_a_no_op() -> None:
    class Fragile(Device):
        started = False

        def start(self) -> None:
            super().start()
            self.started = True

        def stop(self) -> None:
            if not self.started:
                raise RuntimeError("not open")

    report = run(Fragile(limit=300))
    assert failed(report) == {"stop_before_start"}
    assert "RuntimeError: not open" in report.clause("stop_before_start").detail


def test_start_that_raises_still_gets_stopped_and_reported() -> None:
    class NoDevice(Device):
        def start(self) -> None:
            raise OSError("no such port")

    device = NoDevice()
    report = run(device)
    assert status(report, "start") == "fail" and "OSError" in report.clause("start").detail
    assert status(report, "stop") == "pass" and device.stopped


def test_bad_declared_rate_and_channels() -> None:
    class Unavailable(Device):
        last_error = "board busy"

    report = run(Unavailable(fs=0.0, channels=(), limit=10))
    assert {"declared_fs", "declared_channels"} <= failed(report)
    assert "last_error: board busy" in report.clause("declared_fs").detail

    dupes = run(Device(channels=(CH2[0], CH2[0]), limit=10))
    assert "duplicate channel name(s) ['C3']" in dupes.clause("declared_channels").detail


def test_read_raising_anything_but_eof() -> None:
    def boom(k: int, b: SampleBlock) -> Any:
        if k == 3:
            raise ValueError("bad packet")
        return b

    report = run(Device(mutate=boom))
    assert status(report, "read_types") == "fail"
    assert "ValueError: bad packet" in report.clause("read_types").detail


def test_read_returning_something_that_is_not_a_block() -> None:
    report = run(Device(limit=300, mutate=lambda k, b: b.data if k == 2 else b))
    assert status(report, "read_types") == "fail"
    assert "ndarray" in report.clause("read_types").detail


def test_a_source_that_never_delivers_is_a_stall() -> None:
    class Never(Device):
        def read(self) -> None:
            return None

    report = run(Never(), seconds=2.0)
    assert status(report, "first_block") == "fail"
    assert "only ever returned None" in report.clause("first_block").detail
    assert report.elapsed_s == pytest.approx(2.0, abs=0.01)


def test_a_mid_stream_silence_is_a_stall() -> None:
    clock = FakeClock()

    def freeze(k: int, b: SampleBlock) -> SampleBlock:
        if k == 20:
            clock.sleep(3.0)
        return b

    report = run(Device(limit=300, mutate=freeze), clock)
    assert status(report, "no_stall") == "fail"
    assert "3.00 s without a block" in report.clause("no_stall").detail


def test_malformed_blocks_fail_the_structure_clause() -> None:
    def wrong_shape(k: int, b: SampleBlock) -> SampleBlock:
        return SampleBlock(b.data[:1], b.fs, b.channels, b.t0) if k == 4 else b

    report = run(Device(limit=300, mutate=wrong_shape))
    assert status(report, "block_structure") == "fail"
    assert "shape (1, 10)" in report.clause("block_structure").detail


def test_empty_blocks_are_a_warning() -> None:
    def empty(k: int, b: SampleBlock) -> SampleBlock:
        return SampleBlock(np.zeros((2, 0)), b.fs, b.channels, b.t0) if k % 2 else b

    report = run(Device(limit=600, mutate=empty, stamp_fs=125.0))
    assert status(report, "block_structure") == "warn", report.format()


def test_channel_swap_mid_stream_fails_the_layout_clause() -> None:
    def swap(k: int, b: SampleBlock) -> SampleBlock:
        return SampleBlock(b.data[::-1], b.fs, (CH2[1], CH2[0]), b.t0) if k >= 10 else b

    report = run(Device(limit=300, mutate=swap))
    assert status(report, "block_layout") == "fail"
    assert "differ from the declared C3,C4" in report.clause("block_layout").detail


def test_block_rate_disagreeing_with_the_declared_rate() -> None:
    report = run(Device(limit=300, mutate=lambda k, b: SampleBlock(b.data, 500.0, b.channels,
                                                                   b.t0)))
    assert status(report, "block_layout") == "fail"
    assert "fs 500 Hz, declared 250 Hz" in report.clause("block_layout").detail


def test_nan_burst_fails_the_finite_clause() -> None:
    def nan(k: int, b: SampleBlock) -> SampleBlock:
        if k in (5, 6):
            d = b.data.copy()
            d[1, :4] = np.nan
            return SampleBlock(d, b.fs, b.channels, b.t0)
        return b

    report = run(Device(limit=300, mutate=nan))
    assert failed(report) == {"finite"}
    assert "4 non-finite sample(s)" in report.clause("finite").detail


def test_duplicated_t0_fails_the_t0_clause() -> None:
    def dup(k: int, b: SampleBlock) -> SampleBlock:
        return SampleBlock(b.data, b.fs, b.channels, 0.0) if k == 7 else b

    report = run(Device(limit=300, mutate=dup))
    assert status(report, "t0") == "fail"
    assert "t0_backwards" in report.clause("t0").detail
    assert status(report, "rate_t0") == "skip"


def test_dropped_packets_fail_the_t0_clause() -> None:
    def gap(k: int, b: SampleBlock) -> SampleBlock:
        return SampleBlock(b.data, b.fs, b.channels, b.t0 + 0.3) if k >= 50 else b

    report = run(Device(limit=300, mutate=gap))
    assert status(report, "t0") == "fail" and "gap" in report.clause("t0").detail


def test_t0_stamped_at_the_wrong_rate_fails_the_rate_clause() -> None:
    report = run(Device(limit=200, stamp_fs=245.0))       # 8 s of t0 at 245 Hz
    assert failed(report) == {"rate_t0"}, report.format()
    assert "245.00 Hz from t0" in report.clause("rate_t0").detail


def test_rate_is_not_judged_on_a_short_run() -> None:
    # 10-sample blocks stamped at 200 Hz: each moves t0 by 50 ms.
    blocks = int(MIN_RATE_SPAN_S / 0.05) - 5
    report = run(Device(limit=blocks, stamp_fs=200.0))
    assert status(report, "rate_t0") == "skip"
    assert run(Device(limit=blocks + 10, stamp_fs=200.0)).clause("rate_t0").status == "fail"


def test_a_realtime_device_delivering_too_slowly_fails_the_arrival_clause() -> None:
    clock = FakeClock()
    report = run(Device(clock=clock, arrival_fs=200.0), clock)
    assert status(report, "rate_arrival") == "fail", report.format()
    assert "200.00 samples/s" in report.clause("rate_arrival").detail


def test_read_after_eof_must_not_return_data() -> None:
    class Zombie(Device):
        def __init__(self) -> None:
            super().__init__(limit=100)
            self.ended = False

        def read(self) -> Any:
            if self.ended:
                return _block(0.0)                    # data after the end
            try:
                return super().read()
            except EOFError:
                self.ended = True
                raise

    report = run(Zombie())
    assert status(report, "read_after_eof") == "fail"


def _block(t0: float) -> SampleBlock:
    return SampleBlock(np.zeros((2, 10)), 250.0, CH2, t0)


def test_read_after_eof_raising_something_else() -> None:
    class Grumpy(Device):
        def __init__(self) -> None:
            super().__init__(limit=100)
            self.ended = False

        def read(self) -> Any:
            if self.ended:
                raise RuntimeError("closed")
            try:
                return super().read()
            except EOFError:
                self.ended = True
                raise

    report = run(Grumpy())
    assert status(report, "read_after_eof") == "fail"
    assert "RuntimeError" in report.clause("read_after_eof").detail


def test_double_stop_and_read_after_stop() -> None:
    class Brittle(Device):
        stops = 0

        def stop(self) -> None:
            self.stops += 1
            if self.stops == 3:                    # before-start, stop, then the second stop
                raise RuntimeError("already closed")

        def read(self) -> Any:
            if self.stops >= 2:
                raise RuntimeError("closed")
            return super().read()

    report = run(Brittle(limit=300))
    assert status(report, "stop") == "pass"
    assert status(report, "stop_twice") == "fail"
    assert status(report, "read_after_stop") == "fail"


def test_check_source_validates_seconds_and_never_raises_for_the_source() -> None:
    with pytest.raises(ValueError):
        check_source(Device(), seconds=0.0)

    class Chaos(Device):
        def start(self) -> None:
            raise RuntimeError("start")

        def stop(self) -> None:
            raise RuntimeError("stop")

    report = run(Chaos())
    assert {"stop_before_start", "start", "stop", "stop_twice"} <= failed(report)


def test_custom_thresholds_are_honoured() -> None:
    strict = IntegrityThresholds(rate_drift_tolerance=0.001)
    report = run(Device(limit=200, stamp_fs=250.0 * 1.005), thresholds=strict)
    assert status(report, "rate_t0") == "fail"
    assert run(Device(limit=200, stamp_fs=250.0 * 1.005)).passed
