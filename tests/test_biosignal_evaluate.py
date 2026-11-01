"""Tests for ``yazses.biosignal.evaluate``: matching, scores, the harness, and the report.

Offline and deterministic: the harness is driven by tiny fake detectors over short
synthetic blocks, and the idle test uses the real EMG onset detector on a seeded
``SyntheticSource``.
"""

from __future__ import annotations

import json
import math
from types import SimpleNamespace

import numpy as np
import pytest

from yazses.biosignal.emg_onset import EmgOnsetDetector, OnsetThresholds
from yazses.biosignal.evaluate import (
    CAVEAT,
    EvaluationReport,
    IdleReport,
    KindStats,
    evaluate,
    evaluate_idle,
    format_idle_report,
    format_report,
    idle_report_to_dict,
    match_events,
    report_to_dict,
)
from yazses.biosignal.fprate import wilson_interval
from yazses.biosignal.sources import SyntheticSource
from yazses.biosignal.types import BioEvent, ChannelInfo, EventKind, SampleBlock, SignalKind

ON = EventKind.SQUEEZE_ON
OFF = EventKind.SQUEEZE_OFF
BLINK = EventKind.BLINK
DOUBLE = EventKind.DOUBLE_BLINK
CLENCH = EventKind.JAW_CLENCH

_CH = (ChannelInfo("EMG1", SignalKind.EMG),)


def ev(kind: EventKind, t: float) -> BioEvent:
    return BioEvent(kind, t)


def make_blocks(n: int, *, fs: float = 10.0, seconds_each: float = 1.0) -> list[SampleBlock]:
    """``n`` contiguous one-channel blocks of ``seconds_each`` s starting at t = 0."""
    size = int(fs * seconds_each)
    return [
        SampleBlock(data=np.zeros((1, size)), fs=fs, channels=_CH, t0=i * seconds_each)
        for i in range(n)
    ]


class FakeDetector:
    """Emits each scheduled event once, in the first block whose end has reached it."""

    def __init__(self, events: list[BioEvent]) -> None:
        self._all = sorted(events, key=lambda e: e.t)
        self._pending = list(self._all)
        self.resets = 0
        self.blocks_seen = 0

    def process(self, block: SampleBlock) -> list[BioEvent]:
        self.blocks_seen += 1
        end = block.t0 + block.duration
        out = [e for e in self._pending if e.t <= end]
        self._pending = [e for e in self._pending if e.t > end]
        return out

    def reset(self) -> None:
        self.resets += 1
        self._pending = list(self._all)


# ---------------------------------------------------------------------------
# match_events
# ---------------------------------------------------------------------------


def test_match_events_perfect_match_pairs_everything():
    """Identical detections and truth: all matches, no FP, no FN."""
    events = [ev(ON, 1.0), ev(ON, 5.0)]
    m = match_events(events, events)
    assert m.true_positives == 2
    assert m.false_positives == ()
    assert m.false_negatives == ()
    assert all(x.latency_s == 0.0 for x in m.matches)
    assert m.tolerance_s == 0.3


def test_match_events_empty_inputs():
    """No detections: every truth is a miss. No truth: every detection is false."""
    only_truth = match_events([], [ev(ON, 1.0)])
    assert (only_truth.true_positives, len(only_truth.false_negatives)) == (0, 1)
    only_det = match_events([ev(ON, 1.0)], [])
    assert (only_det.true_positives, len(only_det.false_positives)) == (0, 1)
    nothing = match_events([], [])
    assert nothing.matches == () and nothing.false_positives == () and nothing.false_negatives == ()


def test_match_events_tolerance_boundary_is_inclusive():
    """A gap of exactly the tolerance matches; a hair more does not."""
    on_edge = match_events([ev(ON, 1.3)], [ev(ON, 1.0)], tolerance_s=0.3)
    assert on_edge.true_positives == 1
    just_over = match_events([ev(ON, 1.31)], [ev(ON, 1.0)], tolerance_s=0.3)
    assert just_over.true_positives == 0
    assert len(just_over.false_positives) == 1
    assert len(just_over.false_negatives) == 1
    # Early detections are inside the same symmetric window.
    assert match_events([ev(ON, 0.7)], [ev(ON, 1.0)], tolerance_s=0.3).true_positives == 1


def test_match_events_zero_tolerance_needs_identical_times():
    """tolerance_s = 0 is legal: only equal times match."""
    assert match_events([ev(ON, 1.0)], [ev(ON, 1.0)], tolerance_s=0.0).true_positives == 1
    assert match_events([ev(ON, 1.001)], [ev(ON, 1.0)], tolerance_s=0.0).true_positives == 0


@pytest.mark.parametrize("bad", [-0.1, float("nan")])
def test_match_events_rejects_bad_tolerance(bad):
    """A negative or NaN tolerance is a ValueError, not a silent no-match."""
    with pytest.raises(ValueError, match="tolerance_s"):
        match_events([], [], tolerance_s=bad)


def test_match_events_one_detection_matches_only_once():
    """Two detections near one truth: the closer one counts, the other is a false positive."""
    m = match_events([ev(ON, 1.05), ev(ON, 1.20)], [ev(ON, 1.0)])
    assert m.true_positives == 1
    assert m.matches[0].detected.t == 1.05
    assert [e.t for e in m.false_positives] == [1.20]
    assert m.false_negatives == ()


def test_match_events_one_truth_is_claimed_once():
    """One detection between two truths claims the nearer; the other truth is missed."""
    m = match_events([ev(ON, 1.2)], [ev(ON, 1.0), ev(ON, 1.25)])
    assert m.true_positives == 1
    assert m.matches[0].truth.t == 1.25
    assert [e.t for e in m.false_negatives] == [1.0]


def test_match_events_is_greedy_by_smallest_gap():
    """The globally smallest gap is taken first, so an early detection cannot steal a better pair."""
    # det 1.00 is 0.2 from truth 1.2; det 1.25 is 0.05 from it. The 0.05 pair wins.
    m = match_events([ev(ON, 1.00), ev(ON, 1.25)], [ev(ON, 1.2)])
    assert [(x.detected.t, x.truth.t) for x in m.matches] == [(1.25, 1.2)]
    assert [e.t for e in m.false_positives] == [1.00]


def test_match_events_sorted_outputs_for_unsorted_input():
    """Results are ordered by time whatever the input order."""
    det = [ev(ON, 9.0), ev(ON, 1.0), ev(ON, 5.0)]
    tru = [ev(ON, 5.0), ev(ON, 1.0), ev(ON, 20.0), ev(ON, 15.0)]
    m = match_events(det, tru)
    assert [x.truth.t for x in m.matches] == [1.0, 5.0]
    assert [e.t for e in m.false_positives] == [9.0]
    assert [e.t for e in m.false_negatives] == [15.0, 20.0]


def test_match_events_squeeze_on_and_off_are_separate_kinds():
    """An ON detection can never satisfy an OFF truth at the same time."""
    m = match_events([ev(ON, 1.0)], [ev(OFF, 1.0)])
    assert m.true_positives == 0
    assert [e.kind for e in m.false_positives] == [ON]
    assert [e.kind for e in m.false_negatives] == [OFF]


def test_match_events_matches_each_kind_independently():
    """The same time on two kinds yields two matches, not a conflict."""
    m = match_events([ev(ON, 1.0), ev(OFF, 1.0)], [ev(ON, 1.0), ev(OFF, 1.1)])
    assert m.true_positives == 2
    assert {x.truth.kind for x in m.matches} == {ON, OFF}


def test_match_events_kinds_filter_ignores_other_kinds_on_both_sides():
    """Filtered-out kinds are neither false positives nor misses."""
    det = [ev(ON, 1.0), ev(DOUBLE, 3.0)]
    tru = [ev(ON, 1.0), ev(BLINK, 2.0)]
    m = match_events(det, tru, kinds=[ON])
    assert m.true_positives == 1
    assert m.false_positives == () and m.false_negatives == ()
    # Without the filter the unscripted DOUBLE_BLINK and unmatched BLINK both count.
    full = match_events(det, tru)
    assert [e.kind for e in full.false_positives] == [DOUBLE]
    assert [e.kind for e in full.false_negatives] == [BLINK]


def test_match_latency_is_detected_minus_truth():
    """Positive latency = the detector reported later than scripted."""
    late = match_events([ev(ON, 1.2)], [ev(ON, 1.0)]).matches[0]
    early = match_events([ev(ON, 0.9)], [ev(ON, 1.0)]).matches[0]
    assert late.latency_s == pytest.approx(0.2)
    assert early.latency_s == pytest.approx(-0.1)


# ---------------------------------------------------------------------------
# KindStats
# ---------------------------------------------------------------------------


def stats(tp: int, fp: int, fn: int, *, kind: EventKind | None = ON, duration_s: float = 3600.0):
    return KindStats(kind=kind, true_positives=tp, false_positives=fp, false_negatives=fn,
                     latency_median_ms=None, latency_p95_ms=None, duration_s=duration_s)


def test_kind_stats_scores_are_exact_fractions():
    """Precision, recall and F1 from known counts."""
    s = stats(8, 2, 4)
    assert s.n_detected == 10 and s.n_truth == 12
    assert s.precision == pytest.approx(0.8)
    assert s.recall == pytest.approx(8 / 12)
    assert s.f1 == pytest.approx(16 / 22)


def test_kind_stats_scores_are_none_when_undefined():
    """Nothing detected: no precision. Nothing to find: no recall. Neither: no F1."""
    nothing_detected = stats(0, 0, 3)
    assert nothing_detected.precision is None
    assert nothing_detected.recall == 0.0
    assert nothing_detected.f1 == 0.0
    nothing_to_find = stats(0, 4, 0)
    assert nothing_to_find.recall is None
    assert nothing_to_find.precision == 0.0
    assert nothing_to_find.f1 == 0.0
    empty = stats(0, 0, 0)
    assert (empty.precision, empty.recall, empty.f1) == (None, None, None)


def test_kind_stats_wilson_intervals_match_fprate_and_bracket_the_estimate():
    """CI bounds come from the shared Wilson helper and contain the point estimate."""
    s = stats(8, 2, 0)
    lo, hi = s.precision_ci
    assert (lo, hi) == wilson_interval(8, 10)
    assert lo == pytest.approx(0.490, abs=0.005)
    assert hi == pytest.approx(0.943, abs=0.005)
    assert 0.0 <= lo <= s.precision <= hi <= 1.0
    r_lo, r_hi = s.recall_ci
    assert (r_lo, r_hi) == wilson_interval(8, 8)
    assert r_hi == 1.0 and r_lo < 1.0


def test_kind_stats_ci_is_whole_range_without_data():
    """No detections and no truth: the interval carries no information."""
    s = stats(0, 0, 0)
    assert s.precision_ci == (0.0, 1.0)
    assert s.recall_ci == (0.0, 1.0)


def test_kind_stats_false_positives_per_hour():
    """FP/hour scales with the signal length; no signal gives None."""
    assert stats(1, 5, 0, duration_s=1800.0).false_positives_per_hour == pytest.approx(10.0)
    assert stats(1, 5, 0, duration_s=0.0).false_positives_per_hour is None


def test_kind_stats_label():
    """A kind labels by its value; the pooled row is 'overall'."""
    assert stats(1, 0, 0, kind=ON).label == "squeeze_on"
    assert stats(1, 0, 0, kind=None).label == "overall"


# ---------------------------------------------------------------------------
# evaluate: fake detectors
# ---------------------------------------------------------------------------

TRUTH = [ev(ON, 2.5), ev(OFF, 4.5), ev(DOUBLE, 7.0)]


def run(detected: list[BioEvent], *, n_blocks: int = 10, truth=None, **kw) -> EvaluationReport:
    return evaluate(make_blocks(n_blocks), FakeDetector(detected),
                    TRUTH if truth is None else truth, **kw)


def test_evaluate_perfect_detector_scores_exactly():
    """Every scripted event found on time: all TP, nothing else."""
    report = run(list(TRUTH))
    assert (report.overall.true_positives, report.overall.false_positives,
            report.overall.false_negatives) == (3, 0, 0)
    assert report.overall.precision == 1.0 and report.overall.recall == 1.0
    assert report.overall.f1 == 1.0
    assert report.duration_s == pytest.approx(10.0)
    assert report.n_blocks == 10
    assert report.tolerance_s == 0.3
    assert {r.kind for r in report.per_kind} == {ON, OFF, DOUBLE}
    assert report.false_activations == 0
    assert report.false_activations_per_hour == 0.0
    assert report.overall.latency_median_ms == pytest.approx(0.0, abs=1e-6)


def test_evaluate_late_detector_reports_latency_in_ms():
    """Detections 0.2 s late are matched and reported as 200 ms latency."""
    late = [BioEvent(e.kind, e.t + 0.2) for e in TRUTH]
    report = run(late)
    assert report.overall.true_positives == 3
    assert report.overall.latency_median_ms == pytest.approx(200.0)
    assert report.overall.latency_p95_ms == pytest.approx(200.0)
    on_row = report.kind_stats(ON)
    assert on_row is not None and on_row.latency_median_ms == pytest.approx(200.0)


def test_evaluate_too_late_detector_falls_outside_tolerance():
    """The same 0.2 s lag fails under a 0.1 s tolerance: FP and FN for every event."""
    late = [BioEvent(e.kind, e.t + 0.2) for e in TRUTH]
    report = run(late, tolerance_s=0.1)
    assert (report.overall.true_positives, report.overall.false_positives,
            report.overall.false_negatives) == (0, 3, 3)
    assert report.overall.latency_median_ms is None
    assert report.tolerance_s == 0.1


def test_evaluate_latency_median_and_p95_from_known_lags():
    """Lags of 100/200/300 ms: median 200 ms, p95 interpolated to 290 ms."""
    truth = [ev(ON, 1.5), ev(ON, 4.5), ev(ON, 7.5)]
    detected = [ev(ON, 1.6), ev(ON, 4.7), ev(ON, 7.8)]
    report = run(detected, truth=truth, tolerance_s=0.5)
    assert report.overall.true_positives == 3
    assert report.overall.latency_median_ms == pytest.approx(200.0)
    assert report.overall.latency_p95_ms == pytest.approx(290.0)


def test_evaluate_noisy_detector_counts_false_positives():
    """Extra detections are false positives; the rate is per hour of signal."""
    noise = [ev(ON, 1.0), ev(BLINK, 9.0), ev(OFF, 9.5)]
    report = run(list(TRUTH) + noise)
    assert report.overall.true_positives == 3
    assert report.overall.false_positives == 3
    assert report.overall.false_negatives == 0
    assert report.overall.precision == pytest.approx(0.5)
    assert report.false_positives_per_hour == pytest.approx(3 / (10.0 / 3600.0))
    # SQUEEZE_OFF is a release: it is a false positive but not a false activation.
    assert report.false_activations == 2
    assert report.false_activations_per_hour == pytest.approx(2 / (10.0 / 3600.0))
    upper = report.false_activations_upper_per_hour
    assert upper is not None and upper > report.false_activations_per_hour


def test_evaluate_silent_detector_misses_everything():
    """A detector that never fires has recall 0 and an undefined precision."""
    report = run([])
    assert (report.overall.true_positives, report.overall.false_positives,
            report.overall.false_negatives) == (0, 0, 3)
    assert report.overall.precision is None
    assert report.overall.recall == 0.0
    assert report.false_activations == 0
    assert report.kind_stats(ON).false_negatives == 1


def test_evaluate_kind_stats_lookup_for_unseen_kind_is_none():
    """A kind that neither occurred nor was detected has no row."""
    report = run(list(TRUTH))
    assert report.kind_stats(CLENCH) is None


def test_evaluate_accepts_a_list_of_detectors():
    """Several detectors are fanned out and their events merged."""
    a = FakeDetector([ev(ON, 2.5), ev(OFF, 4.5)])
    b = FakeDetector([ev(DOUBLE, 7.0)])
    report = evaluate(make_blocks(10), [a, b], TRUTH)
    assert report.overall.true_positives == 3
    assert report.overall.false_positives == 0
    assert a.blocks_seen == b.blocks_seen == 10


def test_evaluate_accepts_a_pipeline_like_object():
    """Anything with .process(block) returning an object with .events works."""
    inner = FakeDetector(list(TRUTH))

    class PipelineLike:
        def process(self, block):
            return SimpleNamespace(events=tuple(inner.process(block)), status=None)

    report = evaluate(make_blocks(10), PipelineLike(), TRUTH)
    assert report.overall.true_positives == 3


def test_evaluate_accepts_none_from_process():
    """A runner that returns None for a quiet block is treated as no events."""

    class Quiet:
        def process(self, block):
            return None

    report = evaluate(make_blocks(3), Quiet(), [])
    assert report.overall.true_positives == 0 and report.n_blocks == 3


def test_evaluate_rejects_things_that_cannot_process():
    """An object without .process is a TypeError; an empty list a ValueError."""
    with pytest.raises(TypeError, match="process"):
        evaluate(make_blocks(1), object(), [])
    with pytest.raises(ValueError, match="no detectors"):
        evaluate(make_blocks(1), [], [])


def test_evaluate_max_seconds_stops_early_and_drops_truth_past_the_signal():
    """Truth after the processed signal is not counted as a miss."""
    detector = FakeDetector([ev(ON, 2.5)])
    truth = [ev(ON, 2.5), ev(ON, 8.0)]
    short = evaluate(make_blocks(10), detector, truth, max_seconds=5.0)
    assert short.duration_s == pytest.approx(5.0)
    assert short.n_blocks == 5
    assert short.overall.true_positives == 1
    assert short.overall.false_negatives == 0
    full = evaluate(make_blocks(10), FakeDetector([ev(ON, 2.5)]), truth)
    assert full.overall.false_negatives == 1


def test_evaluate_rejects_negative_max_seconds():
    """max_seconds < 0 is a ValueError."""
    with pytest.raises(ValueError, match="max_seconds"):
        evaluate(make_blocks(1), FakeDetector([]), [], max_seconds=-1.0)


def test_evaluate_reset_first_calls_reset_by_default():
    """A reused detector starts clean unless the caller opts out."""
    detector = FakeDetector([ev(ON, 2.5)])
    evaluate(make_blocks(5), detector, [ev(ON, 2.5)])
    assert detector.resets == 1
    second = evaluate(make_blocks(5), detector, [ev(ON, 2.5)])
    assert second.overall.true_positives == 1     # reset re-armed the pending event
    assert detector.resets == 2


def test_evaluate_without_reset_keeps_detector_state():
    """reset_first=False leaves the detector as it was (here: the event already spent)."""
    detector = FakeDetector([ev(ON, 2.5)])
    evaluate(make_blocks(5), detector, [ev(ON, 2.5)], reset_first=False)
    assert detector.resets == 0
    again = evaluate(make_blocks(5), detector, [ev(ON, 2.5)], reset_first=False)
    assert again.overall.true_positives == 0 and again.overall.false_negatives == 1


def test_evaluate_kinds_filter_scores_only_those_kinds():
    """Scoring can be limited to the kinds the truth source actually scripts."""
    report = run(list(TRUTH) + [ev(CLENCH, 3.0)], kinds=[ON, OFF])
    assert {r.kind for r in report.per_kind} == {ON, OFF}
    assert report.overall.false_positives == 0
    assert report.overall.false_negatives == 0


class FakeSource:
    """A BlockSource with its own ground truth; records start/stop calls."""

    def __init__(self, blocks: list[SampleBlock], truth: list[BioEvent] | None = None) -> None:
        self._blocks = list(blocks)
        self._truth = truth
        self.started = 0
        self.stopped = 0
        if truth is not None:
            self.ground_truth = lambda: list(truth)

    def start(self) -> None:
        self.started += 1

    def read(self):
        if not self._blocks:
            raise EOFError
        return self._blocks.pop(0)

    def stop(self) -> None:
        self.stopped += 1


def test_evaluate_uses_source_ground_truth_and_stops_the_source():
    """truth=None asks the source; the source is started and stopped around the run."""
    source = FakeSource(make_blocks(10), truth=list(TRUTH))
    report = evaluate(source, FakeDetector(list(TRUTH)))
    assert report.overall.true_positives == 3
    assert (source.started, source.stopped) == (1, 1)


def test_evaluate_stops_the_source_when_max_seconds_ends_the_run_early():
    """Breaking out early still runs the source's stop()."""
    source = FakeSource(make_blocks(10), truth=[])
    evaluate(source, FakeDetector([]), max_seconds=3.0)
    assert source.stopped == 1


def test_evaluate_without_any_truth_is_an_error():
    """No truth argument and a source with no ground_truth(): refuse rather than score 0 FN."""
    with pytest.raises(ValueError, match="ground_truth"):
        evaluate(FakeSource(make_blocks(3)), FakeDetector([]))


def test_evaluate_empty_signal_has_no_rates():
    """No blocks: zero duration, rates are None rather than a division error."""
    report = evaluate([], FakeDetector([]), [])
    assert report.duration_s == 0.0 and report.n_blocks == 0
    assert report.false_positives_per_hour is None
    assert report.false_activations_per_hour is None
    assert report.false_activations_upper_per_hour is None
    assert "overall" in format_report(report)


def test_evaluate_real_emg_detector_on_scripted_synthetic_squeezes():
    """The real onset detector finds two scripted squeezes in a seeded synthetic recording."""
    thresholds = OnsetThresholds.from_calibration(8.9, 200.0)
    source = SyntheticSource("emg", seed=3, duration=40.0)
    source.schedule_squeeze(10.0, 1.5).schedule_squeeze(20.0, 1.0)
    report = evaluate(source, EmgOnsetDetector(thresholds))
    assert (report.overall.true_positives, report.overall.false_positives,
            report.overall.false_negatives) == (4, 0, 0)
    on_row = report.kind_stats(ON)
    assert on_row is not None
    # Latency is the detector's own confirmation delay: positive and well under tolerance.
    assert 0.0 < on_row.latency_median_ms < 300.0


# ---------------------------------------------------------------------------
# evaluate_idle
# ---------------------------------------------------------------------------


class ChecksumProbe:
    """Emits nothing; accumulates a checksum of every sample it sees."""

    def __init__(self) -> None:
        self.total = 0.0
        self.peak = 0.0

    def process(self, block):
        self.total += float(np.sum(block.data))
        self.peak = max(self.peak, float(np.max(np.abs(block.data))))
        return []

    def reset(self) -> None:
        self.total = 0.0
        self.peak = 0.0


def test_idle_real_emg_detector_has_no_phantom_activations():
    """On a quiet synthetic baseline a calibrated detector never fires."""
    thresholds = OnsetThresholds.from_calibration(8.9, 200.0)
    report = evaluate_idle(None, EmgOnsetDetector(thresholds), hours_simulated=0.02,
                           seed=5, kind="emg")
    assert isinstance(report, IdleReport)
    assert report.phantom_activations == 0
    assert report.counts == ()
    assert report.duration_s == pytest.approx(72.0)
    assert report.hours == pytest.approx(0.02)
    assert report.n_blocks == 1800
    assert report.seed == 5
    assert report.phantom_per_hour == 0.0


def test_idle_zero_count_still_has_a_nonzero_upper_bound_near_rule_of_three():
    """Zero events in H hours bounds the rate at about 3/H, never at 0."""
    report = evaluate_idle(None, ChecksumProbe(), hours_simulated=0.02, kind="emg")
    assert report.phantom_activations == 0
    upper = report.phantom_upper_per_hour
    assert upper is not None and upper > 0.0
    assert 2.8 <= upper * report.hours <= 3.2


def test_idle_upper_bound_grows_with_the_count():
    """A non-zero count raises the bound above the zero-count bound."""
    zero = IdleReport(duration_s=360.0, n_blocks=1, counts=(), phantom_activations=0, seed=0)
    two = IdleReport(duration_s=360.0, n_blocks=1, counts=((ON, 2),), phantom_activations=2,
                     seed=0)
    assert two.phantom_upper_per_hour > two.phantom_per_hour
    assert two.phantom_upper_per_hour > zero.phantom_upper_per_hour


def test_idle_report_without_signal_has_no_rates():
    """Zero duration: per-hour numbers are None."""
    empty = IdleReport(duration_s=0.0, n_blocks=0, counts=(), phantom_activations=0, seed=None)
    assert empty.phantom_per_hour is None
    assert empty.phantom_upper_per_hour is None


def test_idle_is_deterministic_for_a_seed_and_differs_across_seeds():
    """Same seed, same samples; a different seed, different samples."""
    def checksum(seed: int) -> float:
        probe = ChecksumProbe()
        evaluate_idle(None, probe, hours_simulated=0.002, seed=seed, kind="emg")
        return probe.total

    assert checksum(3) == checksum(3)
    assert checksum(3) != checksum(4)


def test_idle_dropout_and_pop_rates_change_the_signal():
    """The electrode-fault knobs reach the default source."""
    clean, faulty = ChecksumProbe(), ChecksumProbe()
    evaluate_idle(None, clean, hours_simulated=0.01, seed=1, kind="emg")
    evaluate_idle(None, faulty, hours_simulated=0.01, seed=1, kind="emg",
                  dropout_rate=0.2, pop_rate=0.2)
    assert faulty.total != clean.total
    assert faulty.peak > clean.peak


def test_idle_counts_every_kind_but_only_activations_are_phantoms():
    """SQUEEZE_OFF is tallied but is not a phantom activation."""
    noisy = FakeDetector([ev(ON, 5.0), ev(OFF, 6.0), ev(BLINK, 7.0)])
    report = evaluate_idle(lambda: iter(make_blocks(20)), noisy, hours_simulated=0.01)
    assert dict(report.counts) == {ON: 1, OFF: 1, BLINK: 1}
    assert report.phantom_activations == 2
    assert report.seed is None
    assert report.phantom_per_hour == pytest.approx(2 / (20.0 / 3600.0))


def test_idle_refuses_a_source_with_scripted_truth():
    """A source that scripts events is not idle."""
    def busy():
        return SyntheticSource("emg", seed=0, duration=10.0).schedule_squeeze(2.0, 1.0)

    with pytest.raises(ValueError, match="idle"):
        evaluate_idle(busy, ChecksumProbe(), hours_simulated=0.01)


def test_idle_accepts_a_custom_source_with_no_truth_and_caps_endless_ones():
    """A source with an empty ground truth is fine, and an endless one is capped."""
    probe = ChecksumProbe()
    report = evaluate_idle(lambda: SyntheticSource("emg", seed=0), probe, hours_simulated=0.001)
    assert report.duration_s == pytest.approx(3.6, abs=0.1)
    assert report.seed is None


@pytest.mark.parametrize("hours", [0.0, -1.0, float("nan")])
def test_idle_rejects_non_positive_duration(hours):
    """hours_simulated must be a positive number."""
    with pytest.raises(ValueError, match="hours_simulated"):
        evaluate_idle(None, ChecksumProbe(), hours_simulated=hours)


def test_idle_reset_first_resets_the_detector():
    """The detector is reset before the run unless the caller says otherwise."""
    detector = FakeDetector([])
    evaluate_idle(None, detector, hours_simulated=0.001, kind="emg")
    assert detector.resets == 1
    evaluate_idle(None, detector, hours_simulated=0.001, kind="emg", reset_first=False)
    assert detector.resets == 1


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def test_format_report_ends_with_the_caveat_and_shows_every_row():
    """The synthetic-signal caveat is the last thing a report says."""
    report = run(list(TRUTH) + [ev(ON, 1.0)])
    text = format_report(report)
    assert text.endswith(CAVEAT)
    assert "squeeze_on" in text and "double_blink" in text and "overall" in text
    assert "Wilson" in text
    assert "false activations: 1" in text
    assert "match tolerance 0.3 s" in text


def test_format_report_marks_undefined_scores_with_dashes():
    """A silent detector prints '-' for precision rather than a made-up number."""
    text = format_report(run([]))
    overall = next(line for line in text.splitlines() if line.startswith("overall"))
    assert "-" in overall.split()
    assert "no data" in text          # precision CI: nothing detected
    assert text.endswith(CAVEAT)


def test_report_to_dict_is_strict_json_and_carries_the_caveat():
    """Undefined scores become null, and nothing is NaN or Infinity."""
    for detected in (list(TRUTH), [], list(TRUTH) + [ev(BLINK, 1.0)]):
        payload = report_to_dict(run(detected))
        text = json.dumps(payload, allow_nan=False)
        back = json.loads(text)
        assert back["caveat"] == CAVEAT
        assert back["schema"] == 1
        assert back["n_blocks"] == 10
        assert set(back["overall"]) >= {"precision", "recall", "f1", "precision_ci95",
                                        "recall_ci95", "latency_median_ms"}


def test_report_to_dict_values_for_a_silent_detector():
    """None, not NaN, for the scores that do not exist."""
    payload = report_to_dict(run([]))
    assert payload["overall"]["precision"] is None
    assert payload["overall"]["recall"] == 0.0
    assert payload["overall"]["latency_median_ms"] is None
    assert payload["per_kind"]["squeeze_on"]["false_negatives"] == 1
    assert payload["false_activations"] == 0
    assert payload["false_activations_upper95_per_hour"] > 0


def test_report_to_dict_of_an_empty_run_is_json_safe():
    """Zero signal: every rate is null and the dict still serialises."""
    payload = report_to_dict(evaluate([], FakeDetector([]), []))
    json.dumps(payload, allow_nan=False)
    assert payload["false_positives_per_hour"] is None
    assert payload["per_kind"] == {}


def test_idle_report_text_and_dict_end_with_the_caveat():
    """Idle output carries the same caveat and is JSON-serialisable."""
    report = IdleReport(duration_s=360.0, n_blocks=9, counts=((ON, 1), (OFF, 1)),
                        phantom_activations=1, seed=7)
    text = format_idle_report(report)
    assert text.endswith(CAVEAT)
    assert "seed 7" in text and "squeeze_on=1" in text and "phantom activations: 1" in text
    payload = idle_report_to_dict(report)
    back = json.loads(json.dumps(payload, allow_nan=False))
    assert back["caveat"] == CAVEAT
    assert back["event_counts"] == {"squeeze_on": 1, "squeeze_off": 1}
    assert back["phantom_activations"] == 1
    assert back["seed"] == 7
    assert back["phantom_per_hour"] == pytest.approx(10.0)
    assert math.isfinite(back["phantom_upper95_per_hour"])


def test_idle_report_text_with_no_events_says_none():
    """An empty tally reads 'none', and a custom source prints no seed."""
    text = format_idle_report(
        IdleReport(duration_s=36.0, n_blocks=1, counts=(), phantom_activations=0, seed=None))
    assert "events seen: none" in text
    assert "seed" not in text
