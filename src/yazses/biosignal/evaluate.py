"""Evaluation harness: score detectors and pipelines against a recording with known events.

The central claim of the biosignal docs is that a trigger lives or dies on its
false-activation rate, so this module exists to *measure* it instead of arguing about it.
Everything here is pure and deterministic: give it the same source (same seed) and the
same detectors and it returns the same numbers, which is what lets a test pin a result
and a CLI print one.

Two questions, two entry points:

* :func:`evaluate` -- a recording with scripted events: did the detector find them
  (recall), did it invent others (precision, false positives per hour), and how late was
  it (latency)?
* :func:`evaluate_idle` -- a recording with *no* events at all (noise, drift, mains and,
  optionally, electrode dropouts and pops): how often does the detector fire anyway?
  That is the "no phantom trigger" number, the one a user feels as the machine typing or
  clicking by itself.

## How events are matched

Detections and ground truth are matched **per** :class:`EventKind` (``SQUEEZE_ON`` and
``SQUEEZE_OFF`` are separate kinds), one-to-one, greedily by smallest time difference
inside ``tolerance_s``. A truth event can be claimed by only one detection; a second
detection of the same truth is a false positive, because a switch that fires twice for
one squeeze has fired once too often. The tolerance is a **design choice** (default
0.3 s, a human-scale "same moment"), not a standard; report it with the result.

## What the numbers are and are not

Latency is ``detected.t - truth.t``. It measures the detector's *event time* against the
scripted time, so a detector that reports the onset it found (rather than the moment it
decided) will look early or near zero; it is not the end-to-end delay a user feels.
``p95`` of a handful of matches is close to their maximum -- read it with the match count.

Results on synthetic signals prove the *logic* (the detector finds what the generator
put there, and stays quiet on noise the generator made). They do **not** show
real-world accuracy: real electrodes, real muscles and real rooms are not a generator.
:func:`format_report` says so on every report.
"""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from yazses.biosignal.types import BioEvent, EventKind, SampleBlock

__all__ = [
    "CAVEAT",
    "EvaluationReport",
    "IdleReport",
    "KindStats",
    "Match",
    "Matching",
    "evaluate",
    "evaluate_idle",
    "format_idle_report",
    "format_report",
    "idle_report_to_dict",
    "match_events",
    "report_to_dict",
]

CAVEAT = (
    "Caveat: results on synthetic signals prove the detection logic, not real-world "
    "accuracy. Measure on your own recordings before trusting a trigger."
)

# SQUEEZE_OFF is a release, not a new activation (same convention as fprate.py, kept local
# so this module imports nothing from its siblings at module level).
_ACTIVATING: frozenset[EventKind] = frozenset(EventKind) - {EventKind.SQUEEZE_OFF}

_SCHEMA = 1
_EPS = 1e-9
_Z_ONE_SIDED_95 = 1.645
_DEFAULT_IDLE_HOURS = 0.1

Runnable = Any
"""A ``StreamDetector``, a sequence of them, or a ``BiosignalPipeline``-like object."""


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Match:
    """One detection paired with the truth event it was credited to."""

    detected: BioEvent
    truth: BioEvent

    @property
    def latency_s(self) -> float:
        """Detected time minus truth time (negative = reported before the scripted time)."""
        return self.detected.t - self.truth.t


@dataclass(frozen=True)
class Matching:
    """The outcome of :func:`match_events`, each list ordered by event time."""

    matches: tuple[Match, ...]
    false_positives: tuple[BioEvent, ...]   # detections that matched no truth event
    false_negatives: tuple[BioEvent, ...]   # truth events no detection claimed
    tolerance_s: float

    @property
    def true_positives(self) -> int:
        return len(self.matches)


def _by_kind(events: Iterable[BioEvent], wanted: frozenset[EventKind] | None) -> dict[EventKind, list[BioEvent]]:
    grouped: dict[EventKind, list[BioEvent]] = {}
    for ev in events:
        if wanted is not None and ev.kind not in wanted:
            continue
        grouped.setdefault(ev.kind, []).append(ev)
    return grouped


def match_events(
    detected: Iterable[BioEvent],
    truth: Iterable[BioEvent],
    *,
    tolerance_s: float = 0.3,
    kinds: Iterable[EventKind] | None = None,
) -> Matching:
    """Match detections to truth, one-to-one, per kind, nearest in time first.

    Every (detection, truth) pair of the same kind within ``tolerance_s`` is a candidate;
    candidates are taken smallest time difference first (ties broken by input order, so
    the result is deterministic) and each detection and each truth event is used at most
    once. ``kinds`` restricts scoring to those kinds -- useful when the truth source does
    not script a kind the detector emits (a synthetic recording lists ``BLINK`` truths but
    never ``DOUBLE_BLINK``, which is the detector's inference). Events of other kinds are
    ignored on *both* sides, so they count as neither false positives nor misses.
    """
    if tolerance_s < 0 or math.isnan(tolerance_s):
        raise ValueError("tolerance_s must be >= 0")
    wanted = None if kinds is None else frozenset(kinds)
    det_by = _by_kind(detected, wanted)
    tru_by = _by_kind(truth, wanted)

    matches: list[Match] = []
    false_pos: list[BioEvent] = []
    false_neg: list[BioEvent] = []

    for kind in sorted(set(det_by) | set(tru_by), key=lambda k: k.value):
        dets = det_by.get(kind, [])
        trus = sorted(range(len(tru_by.get(kind, []))), key=lambda i: tru_by[kind][i].t)
        tru_events = tru_by.get(kind, [])
        tru_times = [tru_events[i].t for i in trus]

        candidates: list[tuple[float, int, int]] = []
        for di, det in enumerate(dets):
            lo = bisect_left(tru_times, det.t - tolerance_s - _EPS)
            hi = bisect_right(tru_times, det.t + tolerance_s + _EPS)
            for pos in range(lo, hi):
                ti = trus[pos]
                candidates.append((abs(det.t - tru_events[ti].t), di, ti))
        candidates.sort()

        used_det: set[int] = set()
        used_tru: set[int] = set()
        for _gap, di, ti in candidates:
            if di in used_det or ti in used_tru:
                continue
            used_det.add(di)
            used_tru.add(ti)
            matches.append(Match(detected=dets[di], truth=tru_events[ti]))
        false_pos.extend(d for i, d in enumerate(dets) if i not in used_det)
        false_neg.extend(t for i, t in enumerate(tru_events) if i not in used_tru)

    matches.sort(key=lambda m: (m.truth.t, m.detected.t))
    false_pos.sort(key=lambda e: e.t)
    false_neg.sort(key=lambda e: e.t)
    return Matching(
        matches=tuple(matches),
        false_positives=tuple(false_pos),
        false_negatives=tuple(false_neg),
        tolerance_s=float(tolerance_s),
    )


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------


def _wilson(successes: int, n: int) -> tuple[float, float]:
    from yazses.biosignal.fprate import wilson_interval

    return wilson_interval(successes, n)


def _poisson_upper(count: int, hours: float) -> float | None:
    """One-sided 95% upper bound on an event rate (per hour) given ``count`` in ``hours``.

    Wilson-Hilferty cube-root approximation to the Poisson upper quantile; for zero
    events it is close to the "rule of three" (about 3 / hours). An approximation,
    reported as such. ``None`` when there was no exposure.
    """
    if hours <= 0:
        return None
    k1 = count + 1.0
    bound = k1 * (1.0 - 1.0 / (9.0 * k1) + _Z_ONE_SIDED_95 / (3.0 * math.sqrt(k1))) ** 3
    return bound / hours


def _percentile(values: Sequence[float], pct: float) -> float | None:
    """Linear-interpolation percentile; ``None`` for no data (numpy-free, deterministic)."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (pct / 100.0) * (len(ordered) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    frac = rank - lo
    return ordered[lo] + (ordered[hi] - ordered[lo]) * frac


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KindStats:
    """Counts and derived scores for one event kind (``kind is None``: all kinds pooled)."""

    kind: EventKind | None
    true_positives: int
    false_positives: int
    false_negatives: int
    latency_median_ms: float | None
    latency_p95_ms: float | None
    duration_s: float

    @property
    def label(self) -> str:
        return "overall" if self.kind is None else self.kind.value

    @property
    def n_truth(self) -> int:
        return self.true_positives + self.false_negatives

    @property
    def n_detected(self) -> int:
        return self.true_positives + self.false_positives

    @property
    def precision(self) -> float | None:
        """TP / (TP + FP); ``None`` when nothing was detected."""
        return self.true_positives / self.n_detected if self.n_detected else None

    @property
    def recall(self) -> float | None:
        """TP / (TP + FN); ``None`` when there was nothing to find."""
        return self.true_positives / self.n_truth if self.n_truth else None

    @property
    def f1(self) -> float | None:
        """2TP / (2TP + FP + FN); ``None`` when there is neither truth nor detection."""
        denom = 2 * self.true_positives + self.false_positives + self.false_negatives
        return 2 * self.true_positives / denom if denom else None

    @property
    def precision_ci(self) -> tuple[float, float]:
        """95% Wilson interval for precision (the whole range when nothing was detected)."""
        return _wilson(self.true_positives, self.n_detected)

    @property
    def recall_ci(self) -> tuple[float, float]:
        """95% Wilson interval for recall (the whole range when there was no truth)."""
        return _wilson(self.true_positives, self.n_truth)

    @property
    def false_positives_per_hour(self) -> float | None:
        """False positives per hour of signal; ``None`` with no signal."""
        hours = self.duration_s / 3600.0
        return self.false_positives / hours if hours > 0 else None


@dataclass(frozen=True)
class EvaluationReport:
    """Everything :func:`evaluate` measured, per kind and pooled."""

    per_kind: tuple[KindStats, ...]
    overall: KindStats
    duration_s: float
    tolerance_s: float
    n_blocks: int

    def kind_stats(self, kind: EventKind) -> KindStats | None:
        """The row for ``kind``, or ``None`` if it neither occurred nor was detected."""
        for row in self.per_kind:
            if row.kind is kind:
                return row
        return None

    @property
    def false_positives_per_hour(self) -> float | None:
        """All false positives (every kind) per hour of signal."""
        return self.overall.false_positives_per_hour

    @property
    def false_activations(self) -> int:
        """False positives of activating kinds -- ``SQUEEZE_OFF`` is a release, not an activation."""
        return sum(r.false_positives for r in self.per_kind if r.kind in _ACTIVATING)

    @property
    def false_activations_per_hour(self) -> float | None:
        """The headline: false activations per hour of signal."""
        hours = self.duration_s / 3600.0
        return self.false_activations / hours if hours > 0 else None

    @property
    def false_activations_upper_per_hour(self) -> float | None:
        """One-sided 95% upper bound on the false-activation rate (approximate)."""
        return _poisson_upper(self.false_activations, self.duration_s / 3600.0)


def _stats(kind: EventKind | None, tp: int, fp: int, fn: int, lat_s: Sequence[float],
           duration_s: float) -> KindStats:
    ms = [x * 1000.0 for x in lat_s]
    return KindStats(
        kind=kind,
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        latency_median_ms=_percentile(ms, 50.0),
        latency_p95_ms=_percentile(ms, 95.0),
        duration_s=float(duration_s),
    )


def _build_report(matching: Matching, duration_s: float, n_blocks: int) -> EvaluationReport:
    kinds = sorted(
        {m.truth.kind for m in matching.matches}
        | {e.kind for e in matching.false_positives}
        | {e.kind for e in matching.false_negatives},
        key=lambda k: k.value,
    )
    rows: list[KindStats] = []
    for kind in kinds:
        lats = [m.latency_s for m in matching.matches if m.truth.kind is kind]
        rows.append(_stats(
            kind,
            len(lats),
            sum(1 for e in matching.false_positives if e.kind is kind),
            sum(1 for e in matching.false_negatives if e.kind is kind),
            lats,
            duration_s,
        ))
    overall = _stats(
        None,
        len(matching.matches),
        len(matching.false_positives),
        len(matching.false_negatives),
        [m.latency_s for m in matching.matches],
        duration_s,
    )
    return EvaluationReport(
        per_kind=tuple(rows),
        overall=overall,
        duration_s=float(duration_s),
        tolerance_s=matching.tolerance_s,
        n_blocks=n_blocks,
    )


# ---------------------------------------------------------------------------
# Driving a detector / pipeline
# ---------------------------------------------------------------------------


def _events_of(result: Any) -> list[BioEvent]:
    """Normalise a ``process()`` return: a sequence of events, or an object with ``.events``."""
    if result is None:
        return []
    events = getattr(result, "events", result)
    return list(events)


class _Fanout:
    """Several ``StreamDetector``s presented as one (same contract as a single one)."""

    def __init__(self, parts: Sequence[Any]) -> None:
        if not parts:
            raise ValueError("no detectors given")
        self._parts = list(parts)

    def process(self, block: SampleBlock) -> list[BioEvent]:
        out: list[BioEvent] = []
        for part in self._parts:
            out.extend(_events_of(part.process(block)))
        out.sort(key=lambda e: e.t)
        return out

    def reset(self) -> None:
        for part in self._parts:
            reset = getattr(part, "reset", None)
            if callable(reset):
                reset()


def _as_runner(runner_like: Runnable) -> Any:
    if isinstance(runner_like, (list, tuple)):
        return _Fanout(runner_like)
    if not callable(getattr(runner_like, "process", None)):
        raise TypeError(
            "runner_like must be a detector, a list of detectors, or a pipeline "
            "(an object with .process(block))"
        )
    return runner_like


def _blocks(source: Any) -> Iterable[SampleBlock]:
    """Blocks from a ``BlockSource`` (driven via ``iter_blocks``) or a plain iterable."""
    if callable(getattr(source, "read", None)) and callable(getattr(source, "start", None)):
        from yazses.biosignal.sources import iter_blocks

        return iter_blocks(source)
    return source  # type: ignore[no-any-return]


@dataclass(frozen=True)
class _Run:
    events: list[BioEvent]
    duration_s: float
    n_blocks: int
    t_first: float


def _drive(source: Any, runner_like: Runnable, *, max_seconds: float | None,
           reset_first: bool) -> _Run:
    if max_seconds is not None and max_seconds < 0:
        raise ValueError("max_seconds must be >= 0")
    runner = _as_runner(runner_like)
    if reset_first:
        reset = getattr(runner, "reset", None)
        if callable(reset):
            reset()
    events: list[BioEvent] = []
    t_first: float | None = None
    t_end = 0.0
    n_blocks = 0
    blocks = _blocks(source)
    try:
        for block in blocks:
            if t_first is None:
                t_first = block.t0
            events.extend(_events_of(runner.process(block)))
            t_end = block.t0 + block.duration
            n_blocks += 1
            if max_seconds is not None and t_end - t_first >= max_seconds:
                break
    finally:
        close = getattr(blocks, "close", None)
        if callable(close):
            close()   # runs iter_blocks' finally: source.stop()
    duration = 0.0 if t_first is None else max(0.0, t_end - t_first)
    return _Run(events=events, duration_s=duration, n_blocks=n_blocks,
                t_first=0.0 if t_first is None else t_first)


def evaluate(
    source: Any,
    runner_like: Runnable,
    truth: Iterable[BioEvent] | None = None,
    *,
    tolerance_s: float = 0.3,
    max_seconds: float | None = None,
    kinds: Iterable[EventKind] | None = None,
    reset_first: bool = True,
) -> EvaluationReport:
    """Run ``runner_like`` over ``source`` and score its events against ``truth``.

    ``source`` is a :class:`BlockSource` (driven through ``sources.iter_blocks``, so it is
    started and stopped for you) or any iterable of ``SampleBlock``. ``runner_like`` is a
    ``StreamDetector``, a list of them (fanned out, events merged in time order), or a
    ``BiosignalPipeline`` -- anything with ``.process(block)`` that returns events or an
    object with ``.events``. ``truth=None`` asks the source for its own
    ``ground_truth()`` (a ``SyntheticSource`` has one); it is read *after* the run, so
    events scheduled mid-run are included.

    ``max_seconds`` stops after the block that reaches that much signal; truth events
    after the end of the processed signal are dropped rather than counted as misses.
    ``reset_first`` calls ``reset()`` on the runner so a reused object starts clean.
    """
    run = _drive(source, runner_like, max_seconds=max_seconds, reset_first=reset_first)
    if truth is None:
        getter = getattr(source, "ground_truth", None)
        if not callable(getter):
            raise ValueError("no truth given and the source has no ground_truth()")
        truth = getter()
    t_limit = None if max_seconds is None else (run.t_first + run.duration_s)
    truth_list = [ev for ev in truth if t_limit is None or ev.t <= t_limit + _EPS]
    matching = match_events(run.events, truth_list, tolerance_s=tolerance_s, kinds=kinds)
    return _build_report(matching, run.duration_s, run.n_blocks)



# ---------------------------------------------------------------------------
# Idle ("no phantom trigger") run
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IdleReport:
    """Phantom activations on a signal that contains no events at all."""

    duration_s: float
    n_blocks: int
    counts: tuple[tuple[EventKind, int], ...]   # every event kind seen, with its count
    phantom_activations: int                    # activating kinds only (not SQUEEZE_OFF)
    seed: int | None

    @property
    def hours(self) -> float:
        return self.duration_s / 3600.0

    @property
    def phantom_per_hour(self) -> float | None:
        """Phantom activations per hour of simulated signal; ``None`` with no signal."""
        return self.phantom_activations / self.hours if self.hours > 0 else None

    @property
    def phantom_upper_per_hour(self) -> float | None:
        """One-sided 95% upper bound on the phantom rate (approximate; ~3/h of exposure at zero)."""
        return _poisson_upper(self.phantom_activations, self.hours)


def _default_idle_source(hours: float, seed: int, kind: str, dropout_rate: float,
                         pop_rate: float) -> Any:
    from yazses.biosignal.sources import SyntheticSource

    return SyntheticSource(
        kind,
        seed=seed,
        duration=hours * 3600.0,
        dropout_rate=dropout_rate,
        pop_rate=pop_rate,
    )


def evaluate_idle(
    source_factory: Callable[[], Any] | None,
    detectors: Runnable,
    *,
    hours_simulated: float = _DEFAULT_IDLE_HOURS,
    seed: int = 0,
    kind: str = "mixed",
    dropout_rate: float = 0.0,
    pop_rate: float = 0.0,
    reset_first: bool = True,
) -> IdleReport:
    """Count phantom activations over ``hours_simulated`` of signal with nothing happening.

    This is the number that decides whether a trigger is usable: with no scripted event
    anywhere, every activation the detectors report is by definition a phantom. The
    default source is a ``SyntheticSource`` (``kind`` montage, noise + drift + mains
    only) capped at the requested duration; ``dropout_rate`` / ``pop_rate`` (faults per
    second, off by default) add the electrode faults that most often fool a detector.
    Pass ``source_factory`` (a zero-argument callable returning a ``BlockSource``) to use
    your own idle source; a source that reports scripted truth events is refused, since it
    would not be idle. Whatever the source, at most ``hours_simulated`` of signal is
    consumed, so an endless source is safe.

    Deterministic for a given ``seed``. A clean count of zero is evidence of a low rate,
    not of zero: :attr:`IdleReport.phantom_upper_per_hour` is the bound to quote.
    """
    if hours_simulated <= 0 or math.isnan(hours_simulated):
        raise ValueError("hours_simulated must be > 0")
    if source_factory is None:
        source = _default_idle_source(hours_simulated, seed, kind, dropout_rate, pop_rate)
        used_seed: int | None = seed
    else:
        source = source_factory()
        used_seed = None
        getter = getattr(source, "ground_truth", None)
        if callable(getter) and getter():
            raise ValueError("an idle source must not have scripted events")
    run = _drive(source, detectors, max_seconds=hours_simulated * 3600.0,
                 reset_first=reset_first)
    tally: dict[EventKind, int] = {}
    for ev in run.events:
        tally[ev.kind] = tally.get(ev.kind, 0) + 1
    counts = tuple(sorted(tally.items(), key=lambda kv: kv[0].value))
    phantom = sum(n for k, n in counts if k in _ACTIVATING)
    return IdleReport(
        duration_s=run.duration_s,
        n_blocks=run.n_blocks,
        counts=counts,
        phantom_activations=phantom,
        seed=used_seed,
    )


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _num(value: float | None, spec: str = ".2f") -> str:
    return "-" if value is None else format(value, spec)


def format_report(report: EvaluationReport) -> str:
    """An aligned plain-text table, ending with the synthetic-signal caveat."""
    header = ("kind", "TP", "FP", "FN", "precision", "recall", "F1",
              "lat med ms", "lat p95 ms", "FP/hour")
    rows: list[tuple[str, ...]] = []
    for row in (*report.per_kind, report.overall):
        rows.append((
            row.label,
            str(row.true_positives),
            str(row.false_positives),
            str(row.false_negatives),
            _num(row.precision),
            _num(row.recall),
            _num(row.f1),
            _num(row.latency_median_ms, ".0f"),
            _num(row.latency_p95_ms, ".0f"),
            _num(row.false_positives_per_hour, ".1f"),
        ))
    widths = [max(len(header[i]), *(len(r[i]) for r in rows)) for i in range(len(header))]

    def line(cells: Sequence[str]) -> str:
        first = cells[0].ljust(widths[0])
        rest = (c.rjust(w) for c, w in zip(cells[1:], widths[1:], strict=True))
        return "  ".join((first, *rest))

    rule = "  ".join("-" * w for w in widths)
    out = [line(header), rule, *(line(r) for r in rows[:-1]), rule, line(rows[-1]), ""]
    out.append(f"signal: {report.duration_s:.1f} s in {report.n_blocks} blocks; "
               f"match tolerance {report.tolerance_s:g} s")
    out.append(_ci_line("overall precision", report.overall.precision_ci, report.overall.n_detected))
    out.append(_ci_line("overall recall", report.overall.recall_ci, report.overall.n_truth))
    fa = report.false_activations_per_hour
    up = report.false_activations_upper_per_hour
    out.append(
        f"false activations: {report.false_activations} "
        f"({_num(fa, '.1f')}/hour; 95% upper bound {_num(up, '.1f')}/hour, approximate)"
    )
    out.append("")
    out.append(CAVEAT)
    return "\n".join(out)


def _ci_line(name: str, ci: tuple[float, float], n: int) -> str:
    if n == 0:
        return f"{name}: no data (95% Wilson interval is the whole range)"
    return f"{name}: 95% Wilson interval [{ci[0]:.2f}, {ci[1]:.2f}] (n={n})"


def _stats_to_dict(row: KindStats) -> dict[str, Any]:
    p_lo, p_hi = row.precision_ci
    r_lo, r_hi = row.recall_ci
    return {
        "kind": row.label,
        "true_positives": row.true_positives,
        "false_positives": row.false_positives,
        "false_negatives": row.false_negatives,
        "precision": row.precision,
        "recall": row.recall,
        "f1": row.f1,
        "precision_ci95": [p_lo, p_hi],
        "recall_ci95": [r_lo, r_hi],
        "latency_median_ms": row.latency_median_ms,
        "latency_p95_ms": row.latency_p95_ms,
        "false_positives_per_hour": row.false_positives_per_hour,
    }


def report_to_dict(report: EvaluationReport) -> dict[str, Any]:
    """A JSON-serialisable view of the report (``None`` where a score is undefined)."""
    return {
        "schema": _SCHEMA,
        "duration_s": report.duration_s,
        "n_blocks": report.n_blocks,
        "tolerance_s": report.tolerance_s,
        "per_kind": {row.label: _stats_to_dict(row) for row in report.per_kind},
        "overall": _stats_to_dict(report.overall),
        "false_positives_per_hour": report.false_positives_per_hour,
        "false_activations": report.false_activations,
        "false_activations_per_hour": report.false_activations_per_hour,
        "false_activations_upper95_per_hour": report.false_activations_upper_per_hour,
        "caveat": CAVEAT,
    }


def idle_report_to_dict(report: IdleReport) -> dict[str, Any]:
    """A JSON-serialisable view of an :class:`IdleReport`."""
    counts: Mapping[str, int] = {k.value: n for k, n in report.counts}
    return {
        "schema": _SCHEMA,
        "duration_s": report.duration_s,
        "hours": report.hours,
        "n_blocks": report.n_blocks,
        "seed": report.seed,
        "event_counts": dict(counts),
        "phantom_activations": report.phantom_activations,
        "phantom_per_hour": report.phantom_per_hour,
        "phantom_upper95_per_hour": report.phantom_upper_per_hour,
        "caveat": CAVEAT,
    }


def format_idle_report(report: IdleReport) -> str:
    """Plain-text summary of an idle run, ending with the synthetic-signal caveat."""
    seen = ", ".join(f"{k.value}={n}" for k, n in report.counts) or "none"
    seed = "" if report.seed is None else f", seed {report.seed}"
    return "\n".join([
        f"idle run: {report.duration_s:.1f} s ({report.hours:.3f} h) in {report.n_blocks} "
        f"blocks{seed}",
        f"events seen: {seen}",
        f"phantom activations: {report.phantom_activations} "
        f"({_num(report.phantom_per_hour, '.1f')}/hour; 95% upper bound "
        f"{_num(report.phantom_upper_per_hour, '.1f')}/hour, approximate)",
        "",
        CAVEAT,
    ])
