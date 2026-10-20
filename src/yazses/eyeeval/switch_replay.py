"""Deterministic replay of face-switch traces: phantom actions per hour, recall, latency, chatter.

EYE-BENCH-001 (#409), ``design/eye-control/ROADMAP.md`` P5.4. Given validated numeric traces
(:mod:`yazses.eyeeval.switch_trace`) it drives the *real* :class:`~yazses.facegesture.detector.GestureSwitch`
and :class:`~yazses.facegesture.switches.SwitchMapper` -- there is no second activation policy
here and no scoring of its own -- and reports what ``design/eye-control/METRICS.md`` names
for a face switch: intended activations, detections, misses, false activations, duration,
false activations per hour, recall and activation latency. Names match the ``face_switch``
block ``yazses.eyeeval.runner`` already writes, so a later volunteer report can be compared
without translation.

It reads no clock (time is the sample index over ``sample_rate_hz``), touches no file and
imports nothing outside the standard library and this repository's pure face-switch modules.
The same trace and configuration therefore produce byte-identical output anywhere, which is
what makes a committed report reviewable in a diff.

## What counts as what

* A **detection** is a switch ``start`` (a ``press`` reaching the mapper's handler) inside a
  *deliberate window*: the labelled ``deliberate`` interval, plus ``match_grace_samples``
  after it, clamped to the next deliberate interval. A ``deliberate`` interval with no start in
  its window is a **miss**. ``held_at_start`` says whether the switch was already held when the
  interval began (a phantom that was still open), because that interval is then a miss for a
  different reason than "the gesture was too small".
* A **false activation** (phantom action) is a start *outside* every deliberate window,
  attributed to the context that was labelled where it began. It is a count of actions, not of
  frames: one phantom hold that lasts two seconds is one phantom.
* **Chatter** is more than one start inside one deliberate window. The extra starts are not
  false activations (the person *was* gesturing) but each is a separate recording, which is the
  burst-of-one-word-transcripts failure the hysteresis exists to prevent.
* **Latency** is the first start's sample minus the interval's first sample, in milliseconds.
  It includes the debounce (``min_hold_frames``), which is the point.

A hold is **stuck open** when the switch stays held across a stretch in which the person was
labelled as not gesturing: it is still held at the first sample of a deliberate interval it did
not begin in (``held_at_start``), or it spans a whole labelled non-deliberate segment, or it is
still open when the trace ends in a non-deliberate segment (only the shutdown drain closed it). That is a
named failure of its own (``stuck_open``), not a phantom: a phantom is a count of actions, a stuck
hold is one action that never ended -- for hold-to-talk, a microphone open indefinitely. The
``longest_hold_s`` next to it is the longest single hold in the trace.

The **exposure** the phantom rate is divided by is every sample outside a deliberate window,
in wall-clock seconds, whether or not the face was tracked; ``non_deliberate_usable_fraction``
says how much of it carried a trustworthy reading. A stretch with no tracking contributes
exposure but cannot produce a phantom, so a mostly-blind trace would look safe; the report
therefore marks the rate missing (``tracking_unavailable``) when *none* of the exposure was
usable, and publishes the usable fraction otherwise so a reader can discount it.

## Zero denominators, decided rather than divided

1. **An empty trace is refused** by the validator and by :func:`replay_traces` when handed an
   empty list anyway. A harness that answered ``0.0`` on nothing would report a perfect run.
2. **A rate whose own denominator is zero is missing, never zero**:
   ``{"value": null, "reason": ...}`` with a reason from ``schema.MISSING_REASONS``.
   No non-deliberate time -> phantom rate ``not_measured``. No deliberate gestures -> recall,
   latency and chatter ``not_measured``. Exposure with no usable reading -> phantom rate
   ``tracking_unavailable``.
3. **A count of zero over a short trace is not zero per hour.** ``false_activations_per_hour``
   is the observed rate; next to it ``false_activations_per_hour_upper_95`` and
   ``false_activations_per_hour_lower_95`` are the exact one-sided 95% Poisson limits (together
   a two-sided 90% interval), so 0 phantoms in 5 minutes reads as "no more than about 36 an
   hour", not as 0. They assume independent events in one session, which a real workday does
   not, and say so in :data:`UPPER_BOUND_CAVEAT`. The limits appear on *every* rate -- the
   per-context ones too, where an exposure of twenty seconds is the norm -- and
   ``per_hour_extrapolated`` is ``true`` whenever the exposure behind a per-hour figure is under
   an hour, so no per-hour number travels without the number of seconds it was scaled up from.

## No product threshold follows from any of this

Every checked-in fixture is invented. A sweep over hold thresholds shows how phantoms and
recall trade off *on that trace*; it does not say which threshold to ship, and ``ROADMAP.md``
P5.4 forbids calling a switch recommended on synthetic evidence. The report says so in a
field (:data:`NO_THRESHOLD_NOTICE`), so a reader who sees only the JSON is told too.

## Which detector is measured

The harness owns the traces, the labels and the scoring; it does not own the activation
policy. A :class:`Detector` names one and builds a fresh instance of it per trace (anything
with the small :class:`SwitchDetector` surface ``GestureSwitch`` has), and every function here
takes one, defaulting to :data:`CURRENT_DETECTOR` -- ``GestureSwitch`` constructed the way the
backend constructs it. So a candidate detector (a timed minimum hold, a refractory period in
seconds) is measured over exactly the same traces and scored by exactly the same rules as the
one that ships, and the report says which one it measured (``detector``). The harness checks
what a detector tells it rather than trusting it: an event other than ``"start"``/``"end"``,
an ``"end"`` with no hold open, a second ``"start"`` while one is, or a frame status outside
:data:`FRAME_STATUSES` is a :class:`SwitchReplayError` -- an event the harness silently
ignored would read as a switch that never misfires.

## What is never in a report

No score, no sample, no description, no unknown field from a trace document: the report is
built from counts, rates, enum members and the validated ``trace_id`` only.
"""

from __future__ import annotations

import math
import statistics
from bisect import bisect_right
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Any, Protocol

from yazses.eyeeval.schema import MISSING_REASONS
from yazses.eyeeval.switch_trace import (
    CONTEXTS,
    DELIBERATE,
    NON_DELIBERATE_CONTEXTS,
    SwitchTrace,
)
from yazses.facegesture.detector import GestureSwitch
from yazses.facegesture.switches import ACTIONS, SwitchAction, SwitchMapper, make_intent

#: The report envelope version. ``MAJOR.MINOR``. 1.3 added ``detector``.
REPORT_VERSION = "1.3"

#: The one named failure the report carries beyond the counts: a hold that never let go.
STUCK_OPEN = "stuck_open"

#: Repeated verbatim into every report so a reader of the JSON alone is told.
NO_THRESHOLD_NOTICE = (
    "No product threshold, default or 'recommended' status follows from these numbers. "
    "Checked-in traces are synthetic and a threshold sweep only shows the phantom/recall "
    "trade-off on the trace it ran on. A facial switch is not recommended until "
    "false-activation evidence exists from real volunteer sessions across people "
    "(design/eye-control/ROADMAP.md P5.4, ADR-v2-150)."
)

#: The zero-denominator decision, in the document rather than only in the docstring.
ZERO_DENOMINATOR_RULE = (
    "An empty trace is refused. A rate whose own denominator is zero is reported as "
    '{"value": null, "reason": ...}, never as 0.0: no non-deliberate time -> not_measured; '
    "no deliberate gestures -> not_measured; non-deliberate time with no usable reading -> "
    "tracking_unavailable."
)

UPPER_BOUND_CAVEAT = (
    "Exact one-sided 95% Poisson lower and upper limits on the rate, assuming independent "
    "events in a single session; real phantoms cluster (a long conversation, a bad lighting "
    "spell), so treat them as a floor on the uncertainty, not a guarantee."
)

#: What each headline number means, so a reader of the JSON alone does not have to guess.
METRIC_DEFINITIONS = {
    "false_activations": "switch starts outside every deliberate window (one per action, not per frame)",
    "false_activations_per_hour": "false_activations / (non-deliberate seconds / 3600); "
    "non-deliberate time is every sample outside a deliberate window, tracked or not",
    "false_activations_per_hour_lower_95": "exact one-sided 95% Poisson lower limit of the same rate "
    "(0 when no phantom was seen); with the upper limit, a two-sided 90% interval",
    "false_activations_per_hour_upper_95": "exact one-sided 95% Poisson upper limit of the same rate",
    "per_hour_extrapolated": "true when the exposure behind a per-hour figure is under one hour: the "
    "figure is scaled up from a shorter observation, and only the limits say how far to trust it",
    "recall": "deliberate intervals with at least one start in their window / deliberate intervals",
    "activation_latency_ms": "first start sample minus the deliberate interval's first sample, "
    "debounce included",
    "chatter": "more than one start inside one deliberate window",
    "stuck_open_holds": "holds still open at the first sample of a deliberate interval they did not "
    "begin in, or spanning a whole non-deliberate labelled segment: a switch that never let go",
    "longest_hold_s": "the longest single hold, from its start to its end (or to the end of the trace "
    "if it never ended), in seconds",
    "failures": "named failures present in this block; 'stuck_open' when stuck_open_holds > 0",
}


class SwitchReplayError(ValueError):
    """The harness was asked to report on something it cannot honestly report on."""


# --------------------------------------------------------------------------- #
# The detector under test
# --------------------------------------------------------------------------- #

#: Why a frame counted as it did -- ``GestureSwitch.last_frame``'s vocabulary. Only
#: ``"reading"`` is a trustworthy sample; the others make the phantom-rate exposure unusable.
FRAME_STATUSES = ("reading", "no_reading", "low_confidence", "unusable_baseline")

#: The only events a detector may return from ``update`` and ``reset``.
DETECTOR_EVENTS = ("start", "end")


class SwitchDetector(Protocol):
    """What the harness needs from an activation policy: the surface ``GestureSwitch`` has.

    ``update`` advances one sample (``now_s`` is the sample index over the trace's rate, never a
    clock) and returns ``"start"``, ``"end"`` or None; ``reset`` drains an open hold at the end
    of the trace. ``last_frame`` is one of :data:`FRAME_STATUSES`; ``thresholds`` and
    ``repaired_release`` are reported, not used.
    """

    repaired_release: bool

    @property
    def held(self) -> bool: ...

    @property
    def last_frame(self) -> str: ...

    @property
    def thresholds(self) -> tuple[float, float]: ...

    def update(
        self, score: float | None, confidence: float | None = None, now_s: float | None = None
    ) -> str | None: ...

    def reset(self) -> str | None: ...


#: Builds one fresh detector for one trace from ``(config, gesture, baseline_level_or_None)``.
#: It is given the trace's gesture (a policy may differ per gesture, as a blink switch's may)
#: and the baseline to apply -- never the samples.
DetectorFactory = Callable[["SwitchConfig", str, "float | None"], SwitchDetector]


@dataclass(frozen=True)
class Detector:
    """A named activation policy under test. ``name`` goes into the report verbatim."""

    name: str
    build: DetectorFactory


def _build_gesture_switch(config: SwitchConfig, gesture: str, baseline: float | None) -> SwitchDetector:
    """``GestureSwitch`` exactly as ``facegesture/backend.py`` builds one per watched gesture.

    Keyword for keyword: a test compares this call with the backend's, so when the backend
    starts passing a new argument (a timed minimum hold, say) this builder has to follow, and
    the committed report then measures the detector that ships rather than an older one.
    """
    del gesture  # the shipped constructor has no per-gesture rule; a candidate's may
    return GestureSwitch(
        hold_threshold=config.hold_threshold,
        release_threshold=config.release_threshold,
        min_hold_frames=config.min_hold_frames,
        min_release_frames=config.min_release_frames,
        baseline=baseline,
        confidence_floor=config.confidence_floor,
        refractory_frames=config.refractory_frames,
        max_hold_s=config.max_hold_s,
    )


#: The detector that ships: the default for every function in this module.
CURRENT_DETECTOR = Detector(name="yazses.facegesture.detector.GestureSwitch", build=_build_gesture_switch)


def _checked_event(
    event: object, *, open_hold: bool, detector: Detector, trace_id: str, sample: int
) -> str | None:
    """``event`` if it is one the harness can count, else :class:`SwitchReplayError`."""
    if event is None:
        return None
    where = f"detector {detector.name!r} on trace {trace_id!r} at sample {sample}"
    if not isinstance(event, str) or event not in DETECTOR_EVENTS:
        raise SwitchReplayError(
            f"{where} returned {event!r}; only None, 'start' and 'end' can be counted, and an "
            f"event the harness ignored would read as a switch that never misfires."
        )
    if event == "start" and open_hold:
        raise SwitchReplayError(f"{where} returned 'start' while its previous hold is still open.")
    if event == "end" and not open_hold:
        raise SwitchReplayError(f"{where} returned 'end' with no hold open.")
    return event


def _missing(reason: str) -> dict[str, Any]:
    """``METRICS.md``'s missing-data marker. Missing is never zero."""
    assert reason in MISSING_REASONS
    return {"value": None, "reason": reason}


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SwitchConfig:
    """One :class:`GestureSwitch` configuration plus the mapping and matching rules.

    The numeric defaults are ``GestureSwitch``'s own constructor defaults, so a bare
    ``SwitchConfig()`` replays the behaviour that ships -- a test pins that they agree. They
    are *not* a recommendation, and nothing here was tuned.

    ``use_trace_baseline`` applies the baseline a trace declares (the user's resting level
    in force when it was recorded) to the switch. It defaults off, which is the absolute
    behaviour of an install that never calibrated.
    """

    hold_threshold: float = 0.5
    release_threshold: float = 0.35
    min_hold_frames: int = 3
    min_release_frames: int = 2
    confidence_floor: float = 0.0
    refractory_frames: int = 0
    use_trace_baseline: bool = False
    action: str = "hold_to_talk"
    match_grace_samples: int = 0
    max_hold_s: float = 0.0

    def problems(self) -> list[str]:
        out: list[str] = []
        for name in ("hold_threshold", "release_threshold", "confidence_floor"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.0 <= value <= 1.0:
                out.append(f"{name}: expected a finite number in 0..1, got {value!r}.")
        for name, low in (("min_hold_frames", 1), ("min_release_frames", 1),
                          ("refractory_frames", 0), ("match_grace_samples", 0)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < low:
                out.append(f"{name}: expected an integer >= {low}, got {value!r}.")
        if self.action not in ACTIONS:
            out.append(f"action: {self.action!r} is not one of {ACTIONS}.")
        mh = self.max_hold_s
        if isinstance(mh, bool) or not isinstance(mh, (int, float)) or not math.isfinite(mh) or mh < 0.0:
            out.append(f"max_hold_s: expected a finite number of seconds >= 0 (0 = off), got {mh!r}.")
        return out

    def check(self) -> None:
        problems = self.problems()
        if problems:
            raise SwitchReplayError("invalid switch configuration:\n  - " + "\n  - ".join(problems))

    def to_document(self) -> dict[str, Any]:
        return {
            "hold_threshold": self.hold_threshold,
            "release_threshold": self.release_threshold,
            "min_hold_frames": self.min_hold_frames,
            "min_release_frames": self.min_release_frames,
            "confidence_floor": self.confidence_floor,
            "refractory_frames": self.refractory_frames,
            "use_trace_baseline": self.use_trace_baseline,
            "action": self.action,
            "match_grace_samples": self.match_grace_samples,
            "max_hold_s": self.max_hold_s,
        }


# --------------------------------------------------------------------------- #
# One trace
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class IntervalOutcome:
    """One labelled deliberate interval and the starts attributed to it."""

    start: int                 # first sample of the interval
    end: int                   # one past its last sample
    starts: tuple[int, ...]    # sample index of every switch start in its window
    held_at_start: bool        # the switch was already held when the interval began

    @property
    def detected(self) -> bool:
        return bool(self.starts)


@dataclass(frozen=True)
class TraceResult:
    """Everything one trace replayed under one configuration produced. Counts and indexes only."""

    trace_id: str
    study_mode: str
    gesture: str
    sample_rate_hz: float
    samples: int
    config: SwitchConfig
    effective_hold: float
    effective_release: float
    release_repaired: bool
    baseline_applied: float | None
    intervals: tuple[IntervalOutcome, ...]
    stuck_open_holds: int                          # holds that never let go (see the module docstring)
    longest_hold_samples: int                      # longest single hold, in samples
    phantom_samples: tuple[int, ...]               # sample index of every phantom start
    phantom_contexts: tuple[str, ...]              # context each phantom began in
    exposure_samples: dict[str, int]               # non-deliberate samples per context
    exposure_usable: dict[str, int]                # ... of which carried a trustworthy reading
    deliberate_samples: int
    deliberate_usable: int
    sample_status: dict[str, int]

    @property
    def duration_s(self) -> float:
        return self.samples / self.sample_rate_hz


def replay_trace(
    trace: SwitchTrace,
    config: SwitchConfig | None = None,
    *,
    detector: Detector = CURRENT_DETECTOR,
) -> TraceResult:
    """Replay one validated trace through ``detector`` (the shipped switch by default) and the
    real mapper. Pure, as long as the detector is."""
    config = config or SwitchConfig()
    config.check()
    n = trace.samples
    rate = trace.sample_rate_hz

    # --- the labels, expanded once ------------------------------------------------------
    context_at: list[str] = []
    seg_starts: list[int] = []
    deliberate: list[tuple[int, int]] = []
    cursor = 0
    for segment in trace.segments:
        seg_starts.append(cursor)
        context_at.extend([segment.context] * segment.samples)
        if segment.context == DELIBERATE:
            deliberate.append((cursor, cursor + segment.samples))
        cursor += segment.samples

    windows: list[tuple[int, int]] = []        # [start, end) in which a start is a detection
    in_window = bytearray(n)                   # 1 where the sample is not phantom exposure
    for k, (start, end) in enumerate(deliberate):
        limit = deliberate[k + 1][0] if k + 1 < len(deliberate) else n
        window_end = min(end + config.match_grace_samples, limit)
        windows.append((start, window_end))
        for i in range(start, window_end):
            in_window[i] = 1

    # --- the real switch, behind the real mapper ----------------------------------------
    baseline = trace.baseline_level if config.use_trace_baseline else None
    switch = detector.build(config, trace.gesture, baseline)
    cursor_frame = 0
    presses: list[int] = []
    held_at: list[bool] = [False] * n

    def on_press() -> None:
        presses.append(cursor_frame)

    handler = SwitchAction(press=on_press, release=lambda: None)
    mapper = SwitchMapper({trace.gesture: config.action}, {config.action: handler})

    status = bytearray(n)  # 1 = a trustworthy reading
    sample_status: Counter[str] = Counter()
    spans: list[tuple[int, int]] = []  # (sample of a hold's start, sample of its end or n)
    open_at: int | None = None
    for i in range(n):
        cursor_frame = i
        held_at[i] = switch.held
        event = _checked_event(
            switch.update(trace.scores[i], trace.confidences[i], now_s=i / rate),
            open_hold=open_at is not None, detector=detector, trace_id=trace.trace_id, sample=i,
        )
        frame_status = switch.last_frame
        if frame_status not in FRAME_STATUSES:
            raise SwitchReplayError(
                f"detector {detector.name!r} on trace {trace.trace_id!r} at sample {i} reported "
                f"frame status {frame_status!r}, not one of {FRAME_STATUSES}."
            )
        sample_status[frame_status] += 1
        status[i] = 1 if frame_status == "reading" else 0
        if event == "start":
            open_at = i
        elif event == "end" and open_at is not None:
            spans.append((open_at, i))
            open_at = None
        if event is not None:
            mapper.handle(make_intent(trace.gesture, event, trace.confidences[i], now_s=i / rate))
    if open_at is not None:
        spans.append((open_at, n))  # never ended: only the shutdown drain below closes it
    end_event = _checked_event(
        switch.reset(), open_hold=open_at is not None, detector=detector, trace_id=trace.trace_id, sample=n,
    )
    if end_event is not None:
        mapper.handle(make_intent(trace.gesture, end_event, None, now_s=n / rate))
    mapper.release_all()

    # --- attribute every action to a deliberate window or to a phantom ----------------------
    window_starts = [w[0] for w in windows]
    per_window: list[list[int]] = [[] for _ in windows]
    phantom_samples: list[int] = []
    phantom_contexts: list[str] = []
    for frame in presses:
        k = bisect_right(window_starts, frame) - 1
        if k >= 0 and frame < windows[k][1]:
            per_window[k].append(frame)
        else:
            phantom_samples.append(frame)
            phantom_contexts.append(context_at[frame])
    intervals = tuple(
        IntervalOutcome(start=start, end=end, starts=tuple(per_window[k]), held_at_start=held_at[start])
        for k, (start, end) in enumerate(deliberate)
    )
    stuck = _stuck_open_holds(spans, deliberate, trace, n)

    exposure: Counter[str] = Counter()
    usable: Counter[str] = Counter()
    deliberate_usable = 0
    deliberate_total = 0
    for i in range(n):
        if in_window[i]:
            deliberate_total += 1
            deliberate_usable += status[i]
        else:
            exposure[context_at[i]] += 1
            usable[context_at[i]] += status[i]

    return TraceResult(
        trace_id=trace.trace_id,
        study_mode=trace.study_mode,
        gesture=trace.gesture,
        sample_rate_hz=rate,
        samples=n,
        config=config,
        effective_hold=switch.thresholds[0],
        effective_release=switch.thresholds[1],
        release_repaired=bool(switch.repaired_release),
        baseline_applied=baseline,
        intervals=intervals,
        stuck_open_holds=stuck,
        longest_hold_samples=max((e - b for b, e in spans), default=0),
        phantom_samples=tuple(phantom_samples),
        phantom_contexts=tuple(phantom_contexts),
        exposure_samples=dict(exposure),
        exposure_usable=dict(usable),
        deliberate_samples=deliberate_total,
        deliberate_usable=deliberate_usable,
        sample_status=dict(sample_status),
    )


def _stuck_open_holds(
    spans: Sequence[tuple[int, int]],
    deliberate: Sequence[tuple[int, int]],
    trace: SwitchTrace,
    n: int,
) -> int:
    """How many holds never let go across a stretch labelled as not gesturing.

    A hold started at sample ``b`` and ended at ``e`` (``n`` when it never did) is on for the
    samples ``b+1 .. e`` as the switch saw them. It is stuck open when that covers the first
    sample of a deliberate interval it did not begin in, or every sample of a non-deliberate
    labelled segment, or when it never ended and the trace's last segment is non-deliberate (it
    was still open after the person had been labelled at rest right up to the end). All are plain
    index comparisons: the harness decides nothing about scores.
    """
    quiet: list[tuple[int, int]] = []
    cursor = 0
    for segment in trace.segments:
        if segment.context != DELIBERATE:
            quiet.append((cursor, cursor + segment.samples))
        cursor += segment.samples
    ends_quiet = bool(trace.segments) and trace.segments[-1].context != DELIBERATE
    count = 0
    for b, e in spans:
        last_on = min(e, n - 1)
        if (
            any(b < d <= last_on for d, _ in deliberate)
            or any(b < a and last_on >= z - 1 for a, z in quiet)
            or (e >= n and ends_quiet)
        ):
            count += 1
    return count


# --------------------------------------------------------------------------- #
# Aggregation: one path for a single trace and for a pooled set
# --------------------------------------------------------------------------- #


def poisson_upper_95(events: int) -> float:
    """Exact one-sided 95% upper confidence limit for a Poisson mean given ``events``. Pure.

    The ``lambda`` for which ``P(X <= events | lambda) = 0.05``; for 0 events that is
    ``-ln(0.05)`` = 2.996, the "rule of three". Bisection, so no external statistics package.
    """
    if events < 0:
        raise ValueError("events must be >= 0")

    def cdf(lam: float) -> float:
        total = 0.0
        for k in range(events + 1):
            total += math.exp(k * math.log(lam) - lam - math.lgamma(k + 1))
        return total

    low, high = 1e-9, float(events) + 10.0 * math.sqrt(events + 1.0) + 10.0
    for _ in range(200):
        mid = (low + high) / 2.0
        if cdf(mid) > 0.05:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def poisson_lower_95(events: int) -> float:
    """Exact one-sided 95% lower confidence limit for a Poisson mean given ``events``. Pure.

    The ``lambda`` for which ``P(X >= events | lambda) = 0.05``; ``0.0`` for 0 events, because
    nothing seen cannot support a rate above zero. Bisection, like :func:`poisson_upper_95`.
    """
    if events < 0:
        raise ValueError("events must be >= 0")
    if events == 0:
        return 0.0

    def survival(lam: float) -> float:  # P(X >= events)
        below = 0.0
        for k in range(events):
            below += math.exp(k * math.log(lam) - lam - math.lgamma(k + 1))
        return 1.0 - below

    low, high = 1e-9, float(events) + 1.0
    for _ in range(200):
        mid = (low + high) / 2.0
        if survival(mid) < 0.05:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def _rate_per_hour(count: int, exposure_s: float, usable: int) -> dict[str, Any]:
    """The phantom-rate fields for one exposure, each missing rather than 0.0 when undefined.

    The rate never travels alone: both limits and the extrapolation flag are on every one.
    """
    if exposure_s <= 0.0:
        value: Any = _missing("not_measured")
        upper: Any = _missing("not_measured")
        lower: Any = _missing("not_measured")
        extrapolated: Any = _missing("not_measured")
    elif usable == 0:
        value = _missing("tracking_unavailable")
        upper = _missing("tracking_unavailable")
        lower = _missing("tracking_unavailable")
        extrapolated = _missing("tracking_unavailable")
    else:
        hours = exposure_s / 3600.0
        value = round(count / hours, 3)
        upper = round(poisson_upper_95(count) / hours, 3)
        lower = round(poisson_lower_95(count) / hours, 3)
        extrapolated = exposure_s < 3600.0
    return {
        "false_activations_per_hour": value,
        "false_activations_per_hour_lower_95": lower,
        "false_activations_per_hour_upper_95": upper,
        "per_hour_extrapolated": extrapolated,
    }


def aggregate(results: Sequence[TraceResult]) -> dict[str, Any]:
    """The report block for one or more results that share a gesture and a configuration.

    The same function serves a single trace and a pooled set, so a rate is computed by one
    code path. Pooling adds counts and seconds and recomputes; it never averages rates.
    """
    if not results:
        raise SwitchReplayError("refusing to aggregate zero results: every rate would read as a perfect run.")

    intervals = [iv for r in results for iv in r.intervals]
    intended = len(intervals)
    detections = sum(1 for iv in intervals if iv.detected)
    attributed = sum(len(iv.starts) for iv in intervals)
    phantoms = sum(len(r.phantom_samples) for r in results)
    duration_s = sum(r.duration_s for r in results)

    exposure_s = sum(sum(r.exposure_samples.values()) / r.sample_rate_hz for r in results)
    usable_n = sum(sum(r.exposure_usable.values()) for r in results)
    exposure_n = sum(sum(r.exposure_samples.values()) for r in results)
    deliberate_s = sum(r.deliberate_samples / r.sample_rate_hz for r in results)
    deliberate_n = sum(r.deliberate_samples for r in results)
    deliberate_usable_n = sum(r.deliberate_usable for r in results)

    latencies: list[float] = []
    for r in results:
        for iv in r.intervals:
            if iv.detected:
                latencies.append((iv.starts[0] - iv.start) * 1000.0 / r.sample_rate_hz)

    by_context: dict[str, Any] = {}
    for context in NON_DELIBERATE_CONTEXTS:
        seconds = sum(r.exposure_samples.get(context, 0) / r.sample_rate_hz for r in results)
        if not any(r.exposure_samples.get(context, 0) for r in results):
            continue  # a context the traces never visit is absent, not a row of zeros
        count = sum(
            1 for r in results for c in r.phantom_contexts if c == context
        )
        context_usable = sum(r.exposure_usable.get(context, 0) for r in results)
        by_context[context] = {
            "duration_s": round(seconds, 6),
            "false_activations": count,
            **_rate_per_hour(count, seconds, context_usable),
        }

    statuses: Counter[str] = Counter()
    for r in results:
        statuses.update(r.sample_status)
    total_samples = sum(r.samples for r in results)
    stuck_open = sum(r.stuck_open_holds for r in results)

    first = results[0]
    chatter: dict[str, Any]
    if intended == 0:
        chatter = {
            "chattering_gestures": _missing("not_measured"),
            "starts_per_detected_gesture": _missing("not_measured"),
            "max_starts_per_gesture": _missing("not_measured"),
            "extra_starts": _missing("not_measured"),
        }
    else:
        chatter = {
            "chattering_gestures": sum(1 for iv in intervals if len(iv.starts) > 1),
            "starts_per_detected_gesture": (
                round(attributed / detections, 6) if detections else _missing("not_measured")
            ),
            "max_starts_per_gesture": max(len(iv.starts) for iv in intervals),
            "extra_starts": attributed - detections,
        }

    return {
        "intended_activations": intended,
        "detections": detections,
        "misses": intended - detections,
        "recall": round(detections / intended, 6) if intended else _missing("not_measured"),
        "false_activations": phantoms,
        "duration_s": round(duration_s, 6),
        "non_deliberate_s": round(exposure_s, 6),
        "deliberate_s": round(deliberate_s, 6),
        "non_deliberate_usable_fraction": (
            round(usable_n / exposure_n, 6) if exposure_n else _missing("not_measured")
        ),
        "deliberate_usable_fraction": (
            round(deliberate_usable_n / deliberate_n, 6) if deliberate_n else _missing("not_measured")
        ),
        **_rate_per_hour(phantoms, exposure_s, usable_n),
        "activation_latency_ms": (
            {
                "count": len(latencies),
                "median": round(statistics.median(latencies), 3),
                "max": round(max(latencies), 3),
            }
            if latencies
            else _missing("not_measured")
        ),
        "chatter": chatter,
        "intervals_held_at_start": sum(1 for iv in intervals if iv.held_at_start),
        "stuck_open_holds": stuck_open,
        "longest_hold_s": round(max(r.longest_hold_samples / r.sample_rate_hz for r in results), 6),
        "failures": [STUCK_OPEN] if stuck_open else [],
        "by_context": by_context,
        "sample_status": {
            name: statuses.get(name, 0) for name in FRAME_STATUSES
        },
        "samples": total_samples,
        "effective_thresholds": {
            "hold": round(first.effective_hold, 6),
            "release": round(first.effective_release, 6),
            "release_repaired": first.release_repaired,
        },
    }


# --------------------------------------------------------------------------- #
# A set of traces, a sweep, the report
# --------------------------------------------------------------------------- #


def _group_by_gesture(results: Iterable[TraceResult]) -> dict[str, list[TraceResult]]:
    grouped: dict[str, list[TraceResult]] = {}
    for result in results:
        grouped.setdefault(result.gesture, []).append(result)
    return dict(sorted(grouped.items()))


def _check_traces(traces: Sequence[SwitchTrace]) -> tuple[SwitchTrace, ...]:
    ordered = tuple(traces)
    if not ordered:
        raise SwitchReplayError(
            "refusing to report on zero traces: every rate would be 0.0, which is "
            "indistinguishable in the output from a switch that never misfires. Supply at "
            "least one trace."
        )
    duplicates = sorted(t for t, c in Counter(x.trace_id for x in ordered).items() if c > 1)
    if duplicates:
        raise SwitchReplayError(
            f"trace ids must be unique across the whole set, or one silently replaces another: {duplicates}"
        )
    return ordered


def sweep_thresholds(thresholds: Iterable[float]) -> tuple[float, ...]:
    """The validated, sorted, de-duplicated hold thresholds of a sweep. Refuses an empty one."""
    values = list(thresholds)
    if not values:
        raise SwitchReplayError(
            "refusing an empty threshold sweep: it would report no trade-off and look like success."
        )
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.0 < value <= 1.0:
            raise SwitchReplayError(f"hold threshold {value!r} must be a finite number in (0, 1].")
    if len(set(values)) != len(values):
        raise SwitchReplayError(f"duplicate hold thresholds in the sweep: {sorted(values)}")
    return tuple(sorted(float(v) for v in values))


def replay_traces(
    traces: Sequence[SwitchTrace],
    config: SwitchConfig | None = None,
    *,
    sweep: Iterable[float] | None = None,
    detector: Detector = CURRENT_DETECTOR,
) -> dict[str, Any]:
    """Replay every trace and return the report document. Raises on an empty trace list.

    ``detector`` is the activation policy under test (the shipped ``GestureSwitch`` by default);
    the sweep replays the same one, and the report names it.

    ``sweep`` is a list of hold thresholds replayed over the *same* traces with every other
    setting held as in ``config`` (including the release threshold, which the switch repairs
    to ``0.7 x hold`` whenever it is not below it -- the row says so). Output order does not
    depend on input order.
    """
    ordered = _check_traces(traces)
    config = config or SwitchConfig()
    config.check()
    grid = sweep_thresholds(sweep) if sweep is not None else None

    ordered = tuple(sorted(ordered, key=lambda t: t.trace_id))
    results = [replay_trace(t, config, detector=detector) for t in ordered]
    document: dict[str, Any] = {
        "report_version": REPORT_VERSION,
        "no_threshold_notice": NO_THRESHOLD_NOTICE,
        "zero_denominator_rule": ZERO_DENOMINATOR_RULE,
        "metric_definitions": METRIC_DEFINITIONS,
        "upper_bound_caveat": UPPER_BOUND_CAVEAT,
        "evidence_class": (
            "synthetic" if all(t.study_mode in ("synthetic", "ci") for t in ordered) else "includes_community_qa"
        ),
        "detector": detector.name,
        "config": config.to_document(),
        "total_traces": len(ordered),
        "traces": [
            {
                "trace_id": r.trace_id,
                "study_mode": r.study_mode,
                "gesture": r.gesture,
                "sample_rate_hz": r.sample_rate_hz,
                "baseline_applied": r.baseline_applied,
                **aggregate([r]),
            }
            for r in results
        ],
        "pooled_by_gesture": {g: aggregate(rs) for g, rs in _group_by_gesture(results).items()},
    }
    if grid is not None:
        rows = []
        for hold in grid:
            swept = [
                replay_trace(t, replace(config, hold_threshold=hold), detector=detector) for t in ordered
            ]
            rows.append(
                {
                    "hold_threshold": hold,
                    "by_gesture": {g: aggregate(rs) for g, rs in _group_by_gesture(swept).items()},
                }
            )
        document["sweep"] = rows
    return document


__all__ = [
    "CONTEXTS",
    "CURRENT_DETECTOR",
    "DETECTOR_EVENTS",
    "FRAME_STATUSES",
    "NO_THRESHOLD_NOTICE",
    "REPORT_VERSION",
    "STUCK_OPEN",
    "ZERO_DENOMINATOR_RULE",
    "Detector",
    "DetectorFactory",
    "IntervalOutcome",
    "SwitchConfig",
    "SwitchDetector",
    "SwitchReplayError",
    "TraceResult",
    "aggregate",
    "poisson_lower_95",
    "poisson_upper_95",
    "replay_trace",
    "replay_traces",
    "sweep_thresholds",
]
