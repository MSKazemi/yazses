"""Field-test protocol: measure the false-activation rate on your own body and board.

The central claim of the biosignal docs is that a trigger lives or dies on its
false-activation rate, and nobody reports it (Meta's electromyography paper included).
:mod:`yazses.biosignal.evaluate` measures it on a *generator*; that proves the logic, not
the real world. This module is the in-situ counterpart: a short, guided session in which
the user sits, talks, chews, types and moves with the switches live, then performs each
switch's deliberate gesture on cue. Every event is tagged with the phase it happened in,
so the report can say *where* the phantoms come from (usually chewing and talking), not
only how many there were.

Pure, deterministic and clock-injected: the phases advance on **signal** seconds (block
durations), never on wall time, so the same stream always gives the same report. The
injected ``clock`` is only used for the wall-time figure in :meth:`FieldTestSession.progress`
and the optional ``max_wall_s`` of :meth:`FieldTestSession.run`. Nothing here opens a
device, imports ``brainflow`` or touches the network; the caller supplies the blocks.

## What is counted, and what is not

* **Phantom activations** are accepted activating events (not ``SQUEEZE_OFF``) during a
  phase in which the user is *not* trying to trigger anything. By construction they are
  unintended, so this is a stricter number than the ledger's "cancelled" proxy. Single
  ``BLINK`` events are not counted by default (``trigger_kinds``): a natural blink is not
  a commit signal and is not mapped to an action (see the spec's event semantics), so
  counting it would drown every other signal. The raw per-kind counts still list it.
* **Exposure** is *usable* signal time only. A stretch the pipeline reports as BAD quality
  (or suspended) is excluded from the denominator, never counted as "no data, no false
  positives". The first ``settle_s`` seconds of each phase are excluded as well (reading
  the next prompt is itself a head movement). A phase with less than ``min_phase_s`` of
  usable signal is **inconclusive** and is left out of every pooled number.
* **Hit rate** (gesture phases): the phase schedules ``cues`` prompts; a cue is a *hit* when
  one of the phase's expected event kinds is accepted inside the cue's response window.
  A cue whose window overlaps unusable signal is *voided*, not scored as a miss.
  Latency is cue-to-event, so it includes the human's reaction time; it is **not** the
  detector's own latency (use :mod:`yazses.biosignal.evaluate` for that).

## Verdict ladder (every number is a DESIGN CHOICE, not a measured constant)

The ladder is deliberately falsifiable: each rung names the numbers that put you on it.

====================  ====================================================================
``inconclusive``      no no-intent phase has enough usable signal, or gesture phases were
                      planned but none produced enough scored cues.
``do_not_enable``     the *lower* 95% bound of the pooled phantom rate is above the budget
                      (credibly too many), or every conclusive gesture phase has a hit-rate
                      upper bound below 50% (credibly does not fire).
``needs_tuning``      the pooled phantom *estimate* is above the budget, or a conclusive
                      gesture phase has a hit rate below 80%.
``promising``         estimate within budget, hit rates fine, but the upper bound is still
                      above the budget (or an activity was not measured): not yet proven.
``usable``            the *upper* 95% bound of the pooled phantom rate is within the budget,
                      every conclusive gesture phase hits at least 80% of its cues, and every
                      activity with a workday weight was measured.
====================  ====================================================================

The budget is ``max_cancelled_per_hour`` when given, else the governor's default
(:class:`~yazses.biosignal.fprate.FalsePositiveBudget`). The asymmetry is intended: the
phantom side uses the *upper* bound because a false activation is the costly error, while
the hit side uses the point estimate because with a handful of cues a Wilson lower bound
above 80% is unattainable (eight of eight cues give about 68%); the Wilson interval is
printed beside it so the looseness is visible.

Because ``usable`` needs an *upper* bound within budget, a few minutes of data can never
reach it at a budget of 6 per hour: zero events in ``h`` hours only bounds the rate by about
``3 / h`` (the "rule of three"). That is the honest answer, and it is why
:class:`FieldTestAggregate` exists: repeated sessions accumulate into one estimate whose
upper bound shrinks as exposure grows.

## The workday estimate

The pooled number weights each no-intent phase by an *assumed activity mix*. The default
weights in :func:`default_protocol` (rest 0.20, talking 0.25, chewing 0.05, hands busy
0.35, moving 0.15) are an **illustrative design choice for a desk-bound day, not data**;
researchers set their own through ``Phase.workday_weight``. The weighted upper bound sums
per-phase upper bounds each taken at level ``0.05 / k`` (Bonferroni over the ``k`` phases
used), so the sum covers the true weighted rate with at least 95% probability under the
Poisson model and the cube-root (Wilson-Hilferty) approximation also used in
:mod:`yazses.biosignal.evaluate`. The raw per-phase numbers are always reported next to it.

## Privacy

A report holds aggregate counts, durations in whole seconds (floored, so exposure is never
overstated), activity labels and cue-to-event latencies to 0.1 s. It holds no raw signal,
no threshold, no amplitude and no event timestamp.
"""

from __future__ import annotations

import math
import statistics
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

from yazses.biosignal.fprate import (
    ACTIVATING_KINDS,
    FalsePositiveBudget,
    poisson_rate_lower_bound,
    wilson_interval,
)
from yazses.biosignal.types import BioEvent, EventKind, SampleBlock

__all__ = [
    "CAVEAT",
    "DEFAULT_TRIGGER_KINDS",
    "FieldTestAggregate",
    "FieldTestReport",
    "FieldTestSession",
    "PhaseResult",
    "Phase",
    "Progress",
    "Verdict",
    "WorkdayEstimate",
    "default_protocol",
    "format_report",
    "protocol_from_dict",
    "protocol_to_dict",
    "report_from_dict",
    "report_to_dict",
]

Clock = Callable[[], float]

SCHEMA = 1

# ---- design choices (see the module docstring) ----------------------------------------
DEFAULT_MIN_PHASE_S = 30.0       # usable signal a phase needs before it counts
DEFAULT_SETTLE_S = 3.0           # head start per phase: reading the prompt is a movement
MAX_OVERRUN = 3.0                # a phase is abandoned after this many times its length
MIN_SCORED_CUES = 3              # fewer scored cues than this: the hit rate is not reported
HIT_USABLE = 0.80                # point hit rate a conclusive gesture phase needs for "usable"
HIT_FAILS_UPPER = 0.50           # Wilson upper bound below this: the switch does not fire
_Z_ONE_SIDED_95 = 1.645          # per-phase displayed bounds
_ALPHA = 0.05                    # family-wise level for the pooled (Bonferroni) bound

# Single blinks are natural, unmapped events; every other activating kind is a trigger.
DEFAULT_TRIGGER_KINDS: frozenset[EventKind] = frozenset(ACTIVATING_KINDS) - {EventKind.BLINK}

DEFAULT_BUDGET_PER_HOUR: float = FalsePositiveBudget.max_cancelled_per_hour

CAVEAT = (
    "Caveat: a few minutes of data bound a false-activation rate only loosely. Zero phantom "
    "activations in N minutes still allows a rate of about 180 / N per hour (rule of three), "
    "so read the upper bound, not the estimate. The activity mix behind the workday "
    "estimate is an illustrative design choice, not data. This measures one body, one "
    "board and one session; repeat it on different days before trusting it."
)

# switch name -> the event kinds that mean "the user triggered it"
SWITCHES: dict[str, tuple[EventKind, ...]] = {
    "squeeze": (EventKind.SQUEEZE_ON,),
    "double_blink": (EventKind.DOUBLE_BLINK,),
    "jaw_clench": (EventKind.JAW_CLENCH,),
}

_GESTURES: dict[str, tuple[str, str]] = {
    "squeeze": (
        "Deliberate squeeze",
        "When the cue says NOW, squeeze for about a second, then relax fully. Wait for the next cue.",
    ),
    "double_blink": (
        "Deliberate double blink",
        "When the cue says NOW, blink twice, quickly and firmly. Otherwise blink normally.",
    ),
    "jaw_clench": (
        "Deliberate jaw clench",
        "When the cue says NOW, clench your teeth for a moment, then relax. Do not talk or chew.",
    ),
}


# ======================================================================================
# Protocol
# ======================================================================================


class Verdict(Enum):
    """Where the evidence puts the switch. See the module docstring for the gates."""

    USABLE = "usable"
    PROMISING = "promising"
    NEEDS_TUNING = "needs_tuning"
    DO_NOT_ENABLE = "do_not_enable"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True)
class Phase:
    """One guided stretch of the protocol.

    ``name`` is a stable identifier (the report key), ``label`` the short activity label,
    ``prompt`` the instruction shown to the user. ``duration_s`` is the *usable* signal
    the phase collects before moving on. ``expects_intent`` says whether activations are
    wanted here (a gesture phase) or are phantoms (everything else).

    The remaining fields have defaults so a researcher can write the five-field form:
    ``expected`` the event kinds that count as a hit, ``cues`` how many prompts to schedule
    (evenly, after ``lead_in_s``), ``response_window_s`` how long after a cue a hit may
    land, ``workday_weight`` the phase's share of the assumed day (a design choice).
    """

    name: str
    label: str
    prompt: str
    duration_s: float
    expects_intent: bool
    expected: tuple[EventKind, ...] = ()
    cues: int = 0
    response_window_s: float = 3.0
    lead_in_s: float = 5.0
    workday_weight: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "expected", tuple(self.expected))
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("a phase needs a non-empty name")
        if not _finite(self.duration_s) or self.duration_s <= 0:
            raise ValueError(f"phase {self.name!r}: duration_s must be a positive number")
        if not all(isinstance(k, EventKind) for k in self.expected):
            raise ValueError(f"phase {self.name!r}: expected must be EventKind values")
        if self.cues < 0 or int(self.cues) != self.cues:
            raise ValueError(f"phase {self.name!r}: cues must be a non-negative integer")
        if not _finite(self.response_window_s) or self.response_window_s <= 0:
            raise ValueError(f"phase {self.name!r}: response_window_s must be > 0")
        if not _finite(self.lead_in_s) or self.lead_in_s < 0:
            raise ValueError(f"phase {self.name!r}: lead_in_s must be >= 0")
        if not _finite(self.workday_weight) or self.workday_weight < 0:
            raise ValueError(f"phase {self.name!r}: workday_weight must be >= 0")
        if self.cues:
            if not self.expects_intent:
                raise ValueError(f"phase {self.name!r}: cues only make sense when expects_intent")
            if not self.expected:
                raise ValueError(f"phase {self.name!r}: cues need at least one expected kind")
            spacing = (self.duration_s - self.lead_in_s) / self.cues
            if spacing < self.response_window_s:
                raise ValueError(
                    f"phase {self.name!r}: {self.cues} cues do not fit in {self.duration_s:g} s "
                    f"with a {self.response_window_s:g} s window after a {self.lead_in_s:g} s lead-in"
                )

    def cue_offsets(self) -> tuple[float, ...]:
        """Cue times in seconds from the start of the phase (evenly spaced after the lead-in)."""
        if not self.cues:
            return ()
        spacing = (self.duration_s - self.lead_in_s) / self.cues
        return tuple(self.lead_in_s + i * spacing for i in range(self.cues))


def default_protocol(
    switches: Iterable[str] = ("squeeze", "double_blink", "jaw_clench"),
    *,
    scale: float = 1.0,
    cues: int = 8,
) -> tuple[Phase, ...]:
    """The standard guided sequence: five no-intent phases, then one gesture phase per switch.

    ``switches`` names the enabled switches (``squeeze``, ``double_blink``, ``jaw_clench``);
    ``scale`` multiplies the no-intent durations; ``cues`` is the number of cues per gesture
    phase. The no-intent phases come first and the gestures last, so a tired user still
    gives the phantom-rate evidence that decides the verdict. The workday weights are an
    illustrative design choice for a desk-bound day, not data.
    """
    names = tuple(switches)
    unknown = [n for n in names if n not in SWITCHES]
    if unknown:
        raise ValueError(f"unknown switch {unknown[0]!r}; known: {', '.join(sorted(SWITCHES))}")
    if not _finite(scale) or scale <= 0:
        raise ValueError("scale must be a positive number")
    quiet = (
        ("rest", "Sit still", "Sit still and relax. Look at the screen. Do nothing on purpose.", 120, 0.20),
        ("speech", "Talk", "Read aloud or talk to yourself, as in a call. Keep your face natural.", 90, 0.25),
        ("chew", "Chew", "Chew gum or a snack. Keep chewing for the whole phase.", 60, 0.05),
        ("hands_busy", "Type and mouse", "Type or move the mouse as you would working. Do not trigger anything.", 120, 0.35),
        ("movement", "Look around", "Look around, turn your head, shift in your seat, stretch a little.", 60, 0.15),
    )
    phases = [
        Phase(name, label, prompt, float(secs) * scale, False, workday_weight=weight)
        for name, label, prompt, secs, weight in quiet
    ]
    for sw in dict.fromkeys(names):                # de-duplicated, order kept
        label, prompt = _GESTURES[sw]
        phases.append(
            Phase(
                f"gesture_{sw}", label, prompt, 5.0 + 5.0 * cues, True,
                expected=SWITCHES[sw], cues=cues, response_window_s=3.0, lead_in_s=5.0,
            )
        )
    return tuple(phases)


def protocol_to_dict(protocol: Sequence[Phase]) -> dict[str, Any]:
    """JSON-safe form of a protocol, for sharing and for ``protocol_from_dict``."""
    return {
        "schema": SCHEMA,
        "phases": [
            {
                "name": p.name,
                "label": p.label,
                "prompt": p.prompt,
                "duration_s": p.duration_s,
                "expects_intent": p.expects_intent,
                "expected": [k.value for k in p.expected],
                "cues": p.cues,
                "response_window_s": p.response_window_s,
                "lead_in_s": p.lead_in_s,
                "workday_weight": p.workday_weight,
            }
            for p in protocol
        ],
    }


def protocol_from_dict(data: Mapping[str, Any] | Sequence[Mapping[str, Any]]) -> tuple[Phase, ...]:
    """Build a protocol from ``protocol_to_dict`` output (or a bare list of phase mappings).

    Raises ``ValueError`` with the phase and field at fault; an invalid protocol never
    reaches a session half-built.
    """
    rows = data.get("phases") if isinstance(data, Mapping) else data
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)) or not rows:
        raise ValueError("protocol needs a non-empty list of phases")
    phases: list[Phase] = []
    for i, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise ValueError(f"phase #{i + 1} is not a mapping")
        for key in ("name", "duration_s"):
            if key not in row:
                raise ValueError(f"phase #{i + 1} is missing {key!r}")
        name = str(row["name"])
        try:
            expected = tuple(EventKind(str(v)) for v in row.get("expected", ()))
            phases.append(
                Phase(
                    name=name,
                    label=str(row.get("label", name)),
                    prompt=str(row.get("prompt", "")),
                    duration_s=float(row["duration_s"]),
                    expects_intent=bool(row.get("expects_intent", False)),
                    expected=expected,
                    cues=int(row.get("cues", 0)),
                    response_window_s=float(row.get("response_window_s", 3.0)),
                    lead_in_s=float(row.get("lead_in_s", 5.0)),
                    workday_weight=float(row.get("workday_weight", 0.0)),
                )
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"phase {name!r}: {exc}") from None
    _check_unique(phases)
    return tuple(phases)


def _check_unique(phases: Sequence[Phase]) -> None:
    seen: set[str] = set()
    for p in phases:
        if p.name in seen:
            raise ValueError(f"duplicate phase name {p.name!r}")
        seen.add(p.name)


# ======================================================================================
# Statistics (pure)
# ======================================================================================


def _finite(x: object) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)


def _poisson_upper(count: float, hours: float, z: float) -> float | None:
    """One-sided upper bound (events per hour) on a Poisson rate; ``None`` with no exposure.

    The cube-root (Wilson-Hilferty) approximation of the upper quantile, as in
    ``evaluate._poisson_upper`` but with the level as a parameter so the pooled estimate
    can use a Bonferroni-adjusted ``z``. Zero events give about ``2.97 / hours`` at
    ``z = 1.645``: the rule of three, never zero.
    """
    if hours <= 0:
        return None
    k1 = max(count, 0.0) + 1.0
    return k1 * (1.0 - 1.0 / (9.0 * k1) + z / (3.0 * math.sqrt(k1))) ** 3 / hours


def _bonferroni_z(k: int) -> float:
    """One-sided z for level ``0.05 / k`` (so ``k`` bounds hold together with >= 95%)."""
    return statistics.NormalDist().inv_cdf(1.0 - _ALPHA / max(k, 1))


def _hours(seconds: int) -> float:
    return seconds / 3600.0


def _round(x: float | None, nd: int = 3) -> float | None:
    if x is None or not math.isfinite(x):
        return None
    return round(x, nd)


# ======================================================================================
# Results
# ======================================================================================


@dataclass(frozen=True)
class PhaseResult:
    """What one phase measured. Seconds are whole and floored; see the privacy note."""

    name: str
    label: str
    expects_intent: bool
    status: str                       # "ok" | "inconclusive" | "not_run"
    planned_s: int
    signal_s: int                     # all signal seen, usable or not
    usable_s: int                     # exposure: good/degraded signal after the settle time
    degraded_s: int                   # subset of usable_s the quality gate called degraded
    excluded_s: int                   # bad quality or suspended: not exposure
    counts: tuple[tuple[str, int], ...]   # accepted events by kind during usable signal
    refused_events: int               # events a pipeline gate refused (any gate)
    phantom_activations: int          # trigger-kind events in a no-intent phase
    cues_total: int
    cues_scored: int
    cues_voided: int
    hits: int
    extra_activations: int            # trigger-kind events in a gesture phase that were not hits
    latencies_s: tuple[float, ...]    # cue-to-event, 0.1 s
    workday_weight: float = 0.0

    @property
    def usable_hours(self) -> float:
        return _hours(self.usable_s)

    @property
    def quality_fraction(self) -> float | None:
        """Share of the phase's counted signal that was usable; ``None`` with no counted signal."""
        total = self.usable_s + self.excluded_s
        return self.usable_s / total if total > 0 else None

    @property
    def phantom_per_hour(self) -> float | None:
        if self.expects_intent or self.usable_s <= 0:
            return None
        return self.phantom_activations / self.usable_hours

    @property
    def phantom_upper_per_hour(self) -> float | None:
        """One-sided 95% upper bound; nonzero even at zero events (the rule of three)."""
        if self.expects_intent:
            return None
        return _poisson_upper(self.phantom_activations, self.usable_hours, _Z_ONE_SIDED_95)

    @property
    def phantom_lower_per_hour(self) -> float | None:
        if self.expects_intent or self.usable_s <= 0:
            return None
        return poisson_rate_lower_bound(self.phantom_activations, self.usable_hours, _Z_ONE_SIDED_95)

    @property
    def hit_rate(self) -> float | None:
        if not self.expects_intent or self.cues_scored < MIN_SCORED_CUES:
            return None
        return self.hits / self.cues_scored

    @property
    def hit_ci(self) -> tuple[float, float] | None:
        """Wilson 95% interval of the hit rate; ``None`` below ``MIN_SCORED_CUES``."""
        if self.hit_rate is None:
            return None
        return wilson_interval(self.hits, self.cues_scored)

    @property
    def median_latency_s(self) -> float | None:
        return round(statistics.median(self.latencies_s), 1) if self.latencies_s else None

    @property
    def hit_grade(self) -> str | None:
        """``ok`` (>= 80%), ``fails`` (Wilson upper < 50%), else ``weak``; ``None`` if unscored."""
        rate, ci = self.hit_rate, self.hit_ci
        if rate is None or ci is None:
            return None
        if rate >= HIT_USABLE:
            return "ok"
        return "fails" if ci[1] < HIT_FAILS_UPPER else "weak"


@dataclass(frozen=True)
class WorkdayEstimate:
    """The pooled phantom rate under the assumed activity mix (a design choice, not data)."""

    phases_used: tuple[str, ...]
    phases_unmeasured: tuple[str, ...]     # weighted phases that were inconclusive or not run
    weights: tuple[tuple[str, float], ...]  # normalised over phases_used
    usable_s: int                           # usable seconds across phases_used
    activations: int
    per_hour: float | None
    lower_per_hour: float | None            # joint one-sided 95% (Bonferroni over phases)
    upper_per_hour: float | None
    raw_per_hour: float | None              # unweighted: all activations / all usable hours
    raw_upper_per_hour: float | None
    extra_hours_needed: float | None        # more usable hours (same mix, no new phantom) to be within budget


@dataclass(frozen=True)
class FieldTestReport:
    phases: tuple[PhaseResult, ...]
    budget_per_hour: float
    min_phase_s: float
    trigger_kinds: tuple[str, ...]
    aborted: bool
    sessions: int
    workday: WorkdayEstimate
    verdict: Verdict
    reasons: tuple[str, ...]

    def phase(self, name: str) -> PhaseResult | None:
        return next((p for p in self.phases if p.name == name), None)


# ======================================================================================
# Assessment (shared by sessions, aggregates and report_from_dict)
# ======================================================================================


def _status_of(r: PhaseResult, min_phase_s: float) -> str:
    if r.signal_s <= 0 and r.usable_s <= 0:
        return "not_run"
    if r.usable_s < min_phase_s:
        return "inconclusive"
    if r.expects_intent and r.cues_total and r.cues_scored < MIN_SCORED_CUES:
        return "inconclusive"
    return "ok"


def _workday(quiet: Sequence[PhaseResult], budget: float) -> WorkdayEstimate:
    ok = [p for p in quiet if p.status == "ok"]
    weighted = [p for p in ok if p.workday_weight > 0]
    used = weighted or ok
    wanted = [p for p in quiet if p.workday_weight > 0] or list(quiet)
    missing = tuple(p.name for p in wanted if p.status != "ok")
    total_w = sum(p.workday_weight for p in used) if weighted else float(len(used))
    weights = [
        (p.name, (p.workday_weight if weighted else 1.0) / total_w) for p in used
    ] if used and total_w > 0 else []
    wmap = dict(weights)
    z = _bonferroni_z(len(used))
    point = lower = upper = None
    if used:
        point = sum(wmap[p.name] * p.phantom_activations / p.usable_hours for p in used)
        lower = sum(
            wmap[p.name] * poisson_rate_lower_bound(p.phantom_activations, p.usable_hours, z)
            for p in used
        )
        upper = sum(
            wmap[p.name] * (_poisson_upper(p.phantom_activations, p.usable_hours, z) or 0.0)
            for p in used
        )
    usable_s = sum(p.usable_s for p in used)
    acts = sum(p.phantom_activations for p in used)
    raw = acts / _hours(usable_s) if usable_s > 0 else None
    raw_up = _poisson_upper(acts, _hours(usable_s), _Z_ONE_SIDED_95)
    extra = None
    if upper is not None and upper > budget:
        extra = _extra_hours(used, wmap, z, budget)
    return WorkdayEstimate(
        phases_used=tuple(p.name for p in used), phases_unmeasured=missing,
        weights=tuple(weights), usable_s=usable_s, activations=acts, per_hour=point,
        lower_per_hour=lower, upper_per_hour=upper, raw_per_hour=raw, raw_upper_per_hour=raw_up,
        extra_hours_needed=extra,
    )


def _extra_hours(
    used: Sequence[PhaseResult], wmap: Mapping[str, float], z: float, budget: float
) -> float | None:
    """Extra usable hours, spread by weight, that bring the pooled upper bound within budget.

    Assumes no further phantom activation, so it is the *minimum* needed. Bisection on a
    decreasing function; ``None`` if it would take more than a million hours.
    """

    def bound(x: float) -> float:
        return sum(
            wmap[p.name] * (_poisson_upper(p.phantom_activations, p.usable_hours + x * wmap[p.name], z) or 0.0)
            for p in used
        )

    hi = 1e6
    if bound(hi) > budget:
        return None
    lo = 0.0
    for _ in range(80):
        mid = (lo + hi) / 2.0
        if bound(mid) > budget:
            lo = mid
        else:
            hi = mid
    return round(hi, 1)


def _assess(
    phases: Sequence[PhaseResult], budget: float, workday: WorkdayEstimate
) -> tuple[Verdict, tuple[str, ...]]:
    quiet_ok = [p for p in phases if not p.expects_intent and p.status == "ok"]
    gest_planned = [p for p in phases if p.expects_intent and p.cues_total > 0]
    gest = [p for p in gest_planned if p.status == "ok" and p.hit_grade is not None]
    reasons: list[str] = []

    if not quiet_ok:
        return Verdict.INCONCLUSIVE, (
            "No phase without intent collected enough usable signal, so the false-activation "
            "rate is unmeasured. Nothing can be said; bad-quality time is never counted as "
            "'no false positives'.",
        )

    w = workday
    assert w.per_hour is not None and w.lower_per_hour is not None and w.upper_per_hour is not None
    grades = {p.name: p.hit_grade for p in gest}
    all_fail = bool(gest) and all(g == "fails" for g in grades.values())
    weak = [p for p in gest if p.hit_grade in ("weak", "fails")]

    offenders = sorted(
        (p for p in quiet_ok if p.phantom_activations > 0),
        key=lambda p: p.phantom_activations / p.usable_hours,
        reverse=True,
    )
    where = ", ".join(f"{p.name} ({p.phantom_activations})" for p in offenders)

    if w.lower_per_hour > budget:
        reasons.append(
            f"The phantom rate is credibly above budget: even the lower 95% bound, "
            f"{w.lower_per_hour:.1f}/h, exceeds {budget:g}/h."
        )
        if where:
            reasons.append(f"Phantoms by phase: {where}.")
        return Verdict.DO_NOT_ENABLE, tuple(reasons)
    if all_fail:
        reasons.append(
            "The switch credibly does not fire on request: every conclusive gesture phase has "
            f"a hit-rate upper bound below {HIT_FAILS_UPPER:.0%}."
        )
        return Verdict.DO_NOT_ENABLE, tuple(reasons)

    if w.per_hour > budget:
        reasons.append(
            f"Estimated workday phantom rate {w.per_hour:.1f}/h exceeds the budget of {budget:g}/h "
            f"(not yet credibly: lower bound {w.lower_per_hour:.1f}/h)."
        )
        if where:
            reasons.append(f"Phantoms by phase: {where}.")
    for p in weak:
        ci = p.hit_ci or (0.0, 1.0)
        reasons.append(
            f"'{p.label}' hit {p.hits} of {p.cues_scored} cues (95% interval "
            f"{ci[0]:.0%}-{ci[1]:.0%}), below the {HIT_USABLE:.0%} bar."
        )
    if reasons:
        return Verdict.NEEDS_TUNING, tuple(reasons)

    if gest_planned and not gest:
        return Verdict.INCONCLUSIVE, (
            "The false-activation rate looks fine so far, but no gesture phase produced enough "
            "scored cues, so whether the switch fires when you want it is unmeasured.",
        )

    if w.phases_unmeasured:
        reasons.append("Not measured (too little usable signal): " + ", ".join(w.phases_unmeasured) + ".")
    if w.upper_per_hour <= budget and not w.phases_unmeasured:
        return Verdict.USABLE, (
            f"Upper 95% bound of the workday phantom rate {w.upper_per_hour:.1f}/h is within the "
            f"budget of {budget:g}/h, and every conclusive gesture phase hit at least "
            f"{HIT_USABLE:.0%} of its cues.",
        )
    if w.upper_per_hour > budget:
        extra = (
            f"about {w.extra_hours_needed:g} more usable hours in the same mix, with no new phantom"
            if w.extra_hours_needed is not None else "far more usable hours"
        )
        reasons.append(
            f"Within budget so far (estimate {w.per_hour:.1f}/h) but not proven: the upper 95% "
            f"bound is {w.upper_per_hour:.1f}/h against {budget:g}/h. Proving it needs {extra}. "
            "Repeat the session and merge the reports with FieldTestAggregate."
        )
    return Verdict.PROMISING, tuple(reasons)


def _build_report(
    phases: Sequence[PhaseResult],
    *,
    budget_per_hour: float,
    min_phase_s: float,
    trigger_kinds: Iterable[EventKind],
    aborted: bool,
    sessions: int,
) -> FieldTestReport:
    results = tuple(_with_status(p, min_phase_s) for p in phases)
    workday = _workday([p for p in results if not p.expects_intent], budget_per_hour)
    verdict, reasons = _assess(results, budget_per_hour, workday)
    return FieldTestReport(
        phases=results, budget_per_hour=budget_per_hour, min_phase_s=min_phase_s,
        trigger_kinds=tuple(sorted(k.value for k in trigger_kinds)), aborted=aborted,
        sessions=sessions, workday=workday, verdict=verdict, reasons=reasons,
    )


def _with_status(p: PhaseResult, min_phase_s: float) -> PhaseResult:
    return replace(p, status=_status_of(p, min_phase_s))


# ======================================================================================
# Session
# ======================================================================================


@dataclass(frozen=True)
class Progress:
    """Where the guided session stands, for a progress bar or a prompt line."""

    phase_index: int                 # 0-based; == n_phases once finished
    n_phases: int
    phase_name: str
    phase_usable_s: int
    phase_planned_s: int
    fraction: float                  # 0..1 over the whole protocol, by usable seconds
    wall_s: int                      # wall seconds since the first block (injected clock)
    finished: bool
    aborted: bool
    trusted: bool | None             # was the latest block usable? None before any block
    cue_now: bool                    # inside a cue's response window


class _State:
    """Mutable accumulator for the phase in progress."""

    def __init__(self, phase: Phase, settle_s: float) -> None:
        self.phase = phase
        self.elapsed = 0.0
        self.usable = 0.0
        self.degraded = 0.0
        self.excluded = 0.0
        self.settle = 0.0
        self.counts: dict[EventKind, int] = {}
        self.refused = 0
        self.trigger_events = 0
        self.expected_rel: list[float] = []
        self.cue_a = phase.cue_offsets()
        self.window = phase.response_window_s
        # a cue that starts before the settle time ends is unusable by construction
        self.void: set[int] = {i for i, a in enumerate(self.cue_a) if a < settle_s}

    def void_overlapping(self, start: float, end: float) -> None:
        for i, a in enumerate(self.cue_a):
            if a < end and a + self.window > start:
                self.void.add(i)

    def cue_now(self) -> bool:
        return any(a <= self.elapsed < a + self.window for a in self.cue_a)


class FieldTestSession:
    """Drive a pipeline through the guided protocol and measure the false-activation rate.

    ``source_or_blocks`` is optional: a ``BlockSource`` (started and stopped by
    :meth:`run`), any iterable of ``SampleBlock``, or ``None`` when the caller pushes
    blocks itself with :meth:`feed`. ``pipeline_factory`` returns the pipeline under test
    (anything with ``process(block)`` returning events or an object with ``.events``); it is
    called once, lazily, so a fresh pipeline measures the whole session. If the result
    (or the pipeline) exposes a ``status`` with ``quality`` and ``suspended``, bad-quality
    and suspended time is excluded from exposure; a bare detector is assumed always usable
    unless ``feed(block, trusted=False)`` says otherwise.

    Deterministic given a stream: phases advance on signal seconds only. ``clock`` (default
    ``time.monotonic``) feeds only the wall-time figure. ``max_cancelled_per_hour`` is the
    budget the verdict compares against (default: the governor's own).
    """

    def __init__(
        self,
        source_or_blocks: Any = None,
        pipeline_factory: Callable[[], Any] | Any = None,
        *,
        clock: Clock | None = None,
        protocol: Sequence[Phase] | None = None,
        min_phase_s: float = DEFAULT_MIN_PHASE_S,
        settle_s: float = DEFAULT_SETTLE_S,
        max_cancelled_per_hour: float | None = None,
        trigger_kinds: Iterable[EventKind] | None = None,
    ) -> None:
        if pipeline_factory is None:
            raise ValueError("pipeline_factory is required (a callable returning the pipeline)")
        self._source = source_or_blocks
        self._factory = pipeline_factory
        self._clock: Clock = clock or time.monotonic
        self._protocol = tuple(protocol) if protocol is not None else default_protocol()
        if not self._protocol:
            raise ValueError("protocol must contain at least one phase")
        _check_unique(self._protocol)
        if not _finite(min_phase_s) or min_phase_s < 0:
            raise ValueError("min_phase_s must be >= 0")
        if not _finite(settle_s) or settle_s < 0:
            raise ValueError("settle_s must be >= 0")
        for p in self._protocol:
            if p.duration_s < min_phase_s:
                raise ValueError(
                    f"phase {p.name!r} lasts {p.duration_s:g} s, shorter than min_phase_s="
                    f"{min_phase_s:g}: it could never be conclusive"
                )
        if max_cancelled_per_hour is not None and (
            not _finite(max_cancelled_per_hour) or max_cancelled_per_hour <= 0
        ):
            raise ValueError("max_cancelled_per_hour must be > 0")
        self._budget = (
            float(max_cancelled_per_hour) if max_cancelled_per_hour is not None
            else DEFAULT_BUDGET_PER_HOUR
        )
        self._min_phase_s = float(min_phase_s)
        self._settle_s = float(settle_s)
        self._triggers = frozenset(trigger_kinds) if trigger_kinds is not None else DEFAULT_TRIGGER_KINDS
        self._pipeline: Any = None
        self._index = 0
        self._state: _State | None = _State(self._protocol[0], self._settle_s)
        self._closed: list[PhaseResult] = []
        self._aborted = False
        self._trusted: bool | None = None
        self._last_dropped = 0
        self._wall0: float | None = None

    # ---- guidance ----------------------------------------------------------------

    @property
    def finished(self) -> bool:
        """True once every phase is done or the session was aborted."""
        return self._aborted or self._state is None

    @property
    def aborted(self) -> bool:
        return self._aborted

    @property
    def protocol(self) -> tuple[Phase, ...]:
        return self._protocol

    def prompt(self) -> str:
        """The instruction for the user right now (changes as phases and cues advance)."""
        st = self._state
        if self._aborted:
            return "Field test stopped."
        if st is None:
            return "Field test finished."
        p = st.phase
        left = max(0, math.ceil(p.duration_s - st.usable))
        head = f"Phase {self._index + 1}/{len(self._protocol)}: {p.label}"
        if st.elapsed < self._settle_s:
            return f"{head} - get ready. {p.prompt}"
        text = f"{head} - {p.prompt} ({left} s left)"
        return text + "  >>> NOW <<<" if st.cue_now() else text

    def progress(self) -> Progress:
        st = self._state
        total = sum(p.duration_s for p in self._protocol)
        done = sum(p.duration_s for p in self._protocol[: self._index])
        if st is not None and not self._aborted:
            done += min(st.usable, st.phase.duration_s)
        frac = 1.0 if (self._state is None and not self._aborted) else min(1.0, done / total)
        wall = 0 if self._wall0 is None else max(0, int(self._clock() - self._wall0))
        return Progress(
            phase_index=self._index if st is not None else len(self._protocol),
            n_phases=len(self._protocol),
            phase_name=st.phase.name if st is not None else "",
            phase_usable_s=int(st.usable) if st is not None else 0,
            phase_planned_s=int(st.phase.duration_s) if st is not None else 0,
            fraction=frac, wall_s=wall, finished=self.finished, aborted=self._aborted,
            trusted=self._trusted, cue_now=bool(st and not self._aborted and st.cue_now()),
        )

    # ---- driving -----------------------------------------------------------------

    def feed(self, block: SampleBlock, *, trusted: bool | None = None) -> list[BioEvent]:
        """Push one block through the pipeline and account it to the current phase.

        Returns the events the pipeline accepted for this block (empty once finished).
        ``trusted`` overrides the quality verdict when the caller knows better.
        """
        st = self._state
        if st is None or self._aborted:
            return []
        if self._wall0 is None:
            self._wall0 = self._clock()
        if self._pipeline is None:
            self._pipeline = self._factory() if not _is_pipeline(self._factory) else self._factory
        result = self._pipeline.process(block)
        events = _events_of(result)
        status = getattr(result, "status", None) or getattr(self._pipeline, "status", None)
        ok, degraded = _trust(status) if trusted is None else (bool(trusted), False)
        refused = max(0, int(getattr(status, "dropped", 0) or 0) - self._last_dropped)
        self._last_dropped += refused
        self._trusted = ok
        self._account(st, block, events, ok, degraded, refused)
        if st.usable >= st.phase.duration_s or st.elapsed >= MAX_OVERRUN * st.phase.duration_s:
            self._advance()
        return events

    def run(self, *, max_wall_s: float | None = None) -> FieldTestReport:
        """Pull blocks from the source until the protocol finishes, then return the report.

        Stops early (the report is then partial) when the source ends, the session is
        aborted, or ``max_wall_s`` of injected-clock time has passed.
        """
        if self._source is None:
            raise ValueError("no source_or_blocks was given; push blocks with feed()")
        start = self._clock()
        blocks = _iter_blocks(self._source)
        try:
            for block in blocks:
                self.feed(block)
                if self.finished:
                    break
                if max_wall_s is not None and self._clock() - start >= max_wall_s:
                    break
        finally:
            close = getattr(blocks, "close", None)
            if callable(close):
                close()
        return self.result()

    def abort(self) -> None:
        """End the session now; the phase in progress keeps what it measured."""
        if self._state is None:
            return                            # already finished or already aborted
        self._closed.append(self._snapshot(self._state))
        self._state = None
        self._aborted = True

    # ---- accounting --------------------------------------------------------------

    def _account(
        self, st: _State, block: SampleBlock, events: Sequence[BioEvent],
        ok: bool, degraded: bool, refused: int,
    ) -> None:
        dur = block.duration if _finite(block.duration) and block.duration > 0 else 0.0
        e0 = st.elapsed
        st.elapsed += dur
        settle_part = max(0.0, min(e0 + dur, self._settle_s) - e0)
        counted = dur - settle_part
        st.settle += settle_part
        st.refused += refused
        if counted > 0:
            if ok:
                st.usable += counted
                if degraded:
                    st.degraded += counted
            else:
                st.excluded += counted
        if not ok:
            st.void_overlapping(e0, e0 + dur)
            return
        if counted <= 0:
            return
        for ev in events:
            rel = e0 + (ev.t - block.t0) if _finite(ev.t) and _finite(block.t0) else e0 + dur
            rel = min(max(rel, e0 - 5.0), e0 + dur)
            if rel < self._settle_s:
                continue                      # the user was still reading the prompt
            st.counts[ev.kind] = st.counts.get(ev.kind, 0) + 1
            if ev.kind in self._triggers:
                st.trigger_events += 1
                if ev.kind in st.phase.expected:
                    st.expected_rel.append(rel)

    def _advance(self) -> None:
        if self._state is not None:
            self._closed.append(self._snapshot(self._state))
        self._index += 1
        if self._index >= len(self._protocol):
            self._state = None
        else:
            self._state = _State(self._protocol[self._index], self._settle_s)

    def _snapshot(self, st: _State) -> PhaseResult:
        """The result for a phase as it stands now. Does not mutate the state."""
        p = st.phase
        scored = hits = 0
        latencies: list[float] = []
        used = [False] * len(st.expected_rel)
        rels = st.expected_rel
        voided = 0
        for i, a in enumerate(st.cue_a):
            if i in st.void:
                voided += 1
                continue
            if a + st.window > st.elapsed:
                continue                      # window not finished: neither hit nor miss
            scored += 1
            for j, r in enumerate(rels):
                if not used[j] and a <= r <= a + st.window:
                    used[j] = True
                    hits += 1
                    latencies.append(round(r - a, 1))
                    break
        phantom = 0 if p.expects_intent else st.trigger_events
        extra = max(0, st.trigger_events - hits) if p.expects_intent else 0
        return _with_status(
            PhaseResult(
                name=p.name, label=p.label, expects_intent=p.expects_intent, status="ok",
                planned_s=int(p.duration_s), signal_s=int(st.elapsed), usable_s=int(st.usable),
                degraded_s=int(st.degraded), excluded_s=int(st.excluded),
                counts=tuple(sorted((k.value, n) for k, n in st.counts.items())),
                refused_events=st.refused, phantom_activations=phantom,
                cues_total=len(st.cue_a), cues_scored=scored, cues_voided=voided, hits=hits,
                extra_activations=extra, latencies_s=tuple(latencies),
                workday_weight=p.workday_weight,
            ),
            self._min_phase_s,
        )

    def result(self) -> FieldTestReport:
        """The report so far (callable at any time; phases not reached are ``not_run``)."""
        rows = list(self._closed)
        if self._state is not None and not self._aborted:
            rows.append(self._snapshot(self._state))
        done = {r.name for r in rows}
        for p in self._protocol:
            if p.name not in done:
                rows.append(_empty_result(p))
        order = {p.name: i for i, p in enumerate(self._protocol)}
        rows.sort(key=lambda r: order[r.name])
        return _build_report(
            rows, budget_per_hour=self._budget, min_phase_s=self._min_phase_s,
            trigger_kinds=self._triggers, aborted=self._aborted, sessions=1,
        )


def _empty_result(p: Phase) -> PhaseResult:
    return PhaseResult(
        name=p.name, label=p.label, expects_intent=p.expects_intent, status="not_run",
        planned_s=int(p.duration_s), signal_s=0, usable_s=0, degraded_s=0, excluded_s=0,
        counts=(), refused_events=0, phantom_activations=0, cues_total=len(p.cue_offsets()),
        cues_scored=0, cues_voided=0, hits=0, extra_activations=0, latencies_s=(),
        workday_weight=p.workday_weight,
    )


def _is_pipeline(obj: Any) -> bool:
    """A factory may be the pipeline itself (an object with ``process`` and not callable)."""
    return callable(getattr(obj, "process", None)) and not callable(obj)


def _events_of(result: Any) -> list[BioEvent]:
    """A ``process()`` return: a sequence of events, or an object with ``.events``."""
    if result is None:
        return []
    return list(getattr(result, "events", result))


def _trust(status: Any) -> tuple[bool, bool]:
    """(usable, degraded) from a pipeline status; no status means usable."""
    if status is None:
        return True, False
    quality = str(getattr(status, "quality", "unknown")).lower()
    suspended = bool(getattr(status, "suspended", False))
    return not (suspended or quality == "bad"), quality == "degraded"


def _iter_blocks(source: Any) -> Any:
    if callable(getattr(source, "read", None)) and callable(getattr(source, "start", None)):
        from yazses.biosignal.sources import iter_blocks

        return iter_blocks(source)
    return iter(source)


# ======================================================================================
# Aggregate
# ======================================================================================


class FieldTestAggregate:
    """Merge several reports into one estimate: sum counts and seconds, recompute bounds.

    Repeated sessions are the only way a few-minute measurement tightens: the upper bound
    shrinks with exposure. Phases are matched by ``name``; a phase that was inconclusive
    in each session can become conclusive once the usable seconds add up. The budget is
    ``max_cancelled_per_hour`` if given, else the strictest of the reports'; reports built
    with different ``trigger_kinds`` are not comparable and are refused.
    """

    def __init__(
        self,
        reports: Iterable[FieldTestReport] = (),
        *,
        min_phase_s: float | None = None,
        max_cancelled_per_hour: float | None = None,
    ) -> None:
        self._reports: list[FieldTestReport] = []
        self._min_phase_s = min_phase_s
        self._budget = max_cancelled_per_hour
        for r in reports:
            self.add(r)

    @property
    def sessions(self) -> int:
        return sum(r.sessions for r in self._reports)

    def add(self, report: FieldTestReport) -> None:
        if self._reports and report.trigger_kinds != self._reports[0].trigger_kinds:
            raise ValueError("reports count different trigger kinds and cannot be merged")
        for p in report.phases:
            for q in (x for r in self._reports for x in r.phases if x.name == p.name):
                if q.expects_intent != p.expects_intent:
                    raise ValueError(f"phase {p.name!r} is a gesture phase in one report only")
        self._reports.append(report)

    def report(self) -> FieldTestReport:
        if not self._reports:
            raise ValueError("no reports to merge")
        merged: dict[str, PhaseResult] = {}
        for r in self._reports:
            for p in r.phases:
                if p.status == "not_run":
                    merged.setdefault(p.name, p)
                    continue
                prev = merged.get(p.name)
                merged[p.name] = p if prev is None or prev.status == "not_run" else _merge(prev, p)
        budget = self._budget if self._budget is not None else min(
            r.budget_per_hour for r in self._reports
        )
        min_s = self._min_phase_s if self._min_phase_s is not None else max(
            r.min_phase_s for r in self._reports
        )
        return _build_report(
            list(merged.values()), budget_per_hour=budget, min_phase_s=min_s,
            trigger_kinds=[EventKind(v) for v in self._reports[0].trigger_kinds],
            aborted=False, sessions=self.sessions,
        )


def _merge(a: PhaseResult, b: PhaseResult) -> PhaseResult:
    counts: dict[str, int] = dict(a.counts)
    for k, n in b.counts:
        counts[k] = counts.get(k, 0) + n
    return replace(
        a,
        planned_s=a.planned_s + b.planned_s, signal_s=a.signal_s + b.signal_s,
        usable_s=a.usable_s + b.usable_s, degraded_s=a.degraded_s + b.degraded_s,
        excluded_s=a.excluded_s + b.excluded_s, counts=tuple(sorted(counts.items())),
        refused_events=a.refused_events + b.refused_events,
        phantom_activations=a.phantom_activations + b.phantom_activations,
        cues_total=a.cues_total + b.cues_total, cues_scored=a.cues_scored + b.cues_scored,
        cues_voided=a.cues_voided + b.cues_voided, hits=a.hits + b.hits,
        extra_activations=a.extra_activations + b.extra_activations,
        latencies_s=a.latencies_s + b.latencies_s,
    )


# ======================================================================================
# Output
# ======================================================================================


def _phase_to_dict(p: PhaseResult) -> dict[str, Any]:
    ci = p.hit_ci
    return {
        "name": p.name, "label": p.label, "expects_intent": p.expects_intent, "status": p.status,
        "planned_s": p.planned_s, "signal_s": p.signal_s, "usable_s": p.usable_s,
        "degraded_s": p.degraded_s, "excluded_s": p.excluded_s,
        "quality_fraction": _round(p.quality_fraction),
        "counts": {k: n for k, n in p.counts}, "refused_events": p.refused_events,
        "phantom_activations": p.phantom_activations,
        "phantom_per_hour": _round(p.phantom_per_hour, 2),
        "phantom_lower_per_hour": _round(p.phantom_lower_per_hour, 2),
        "phantom_upper_per_hour": _round(p.phantom_upper_per_hour, 2),
        "cues_total": p.cues_total, "cues_scored": p.cues_scored, "cues_voided": p.cues_voided,
        "hits": p.hits, "hit_rate": _round(p.hit_rate),
        "hit_ci": None if ci is None else [_round(ci[0]), _round(ci[1])],
        "hit_grade": p.hit_grade, "median_latency_s": p.median_latency_s,
        "latencies_s": list(p.latencies_s), "extra_activations": p.extra_activations,
        "workday_weight": p.workday_weight,
    }


def report_to_dict(report: FieldTestReport) -> dict[str, Any]:
    """JSON-safe dict of a report (aggregate counts, whole seconds, labels; no signal)."""
    w = report.workday
    return {
        "schema": SCHEMA,
        "verdict": report.verdict.value,
        "reasons": list(report.reasons),
        "budget_per_hour": report.budget_per_hour,
        "min_phase_s": report.min_phase_s,
        "trigger_kinds": list(report.trigger_kinds),
        "aborted": report.aborted,
        "sessions": report.sessions,
        "workday": {
            "phases_used": list(w.phases_used),
            "phases_unmeasured": list(w.phases_unmeasured),
            "weights": {k: _round(v) for k, v in w.weights},
            "usable_s": w.usable_s,
            "activations": w.activations,
            "per_hour": _round(w.per_hour, 2),
            "lower_per_hour": _round(w.lower_per_hour, 2),
            "upper_per_hour": _round(w.upper_per_hour, 2),
            "raw_per_hour": _round(w.raw_per_hour, 2),
            "raw_upper_per_hour": _round(w.raw_upper_per_hour, 2),
            "extra_hours_needed": _round(w.extra_hours_needed, 1),
            "weights_note": "assumed activity mix: an illustrative design choice, not data",
        },
        "phases": [_phase_to_dict(p) for p in report.phases],
        "caveat": CAVEAT,
    }


def report_from_dict(data: Mapping[str, Any]) -> FieldTestReport:
    """Rebuild a report from ``report_to_dict`` output, recomputing every derived number.

    Only the counted fields are read, so a stored report cannot disagree with its own
    counts. Raises ``ValueError`` for a malformed or unsupported dictionary.
    """
    try:
        if int(data.get("schema", 0)) != SCHEMA:
            raise ValueError(f"unsupported field-test schema {data.get('schema')!r}")
        phases = []
        for row in data["phases"]:
            phases.append(
                PhaseResult(
                    name=str(row["name"]), label=str(row.get("label", row["name"])),
                    expects_intent=bool(row["expects_intent"]), status="ok",
                    planned_s=int(row["planned_s"]), signal_s=int(row["signal_s"]),
                    usable_s=int(row["usable_s"]), degraded_s=int(row.get("degraded_s", 0)),
                    excluded_s=int(row.get("excluded_s", 0)),
                    counts=tuple(sorted((str(k), int(n)) for k, n in dict(row.get("counts", {})).items())),
                    refused_events=int(row.get("refused_events", 0)),
                    phantom_activations=int(row["phantom_activations"]),
                    cues_total=int(row.get("cues_total", 0)), cues_scored=int(row.get("cues_scored", 0)),
                    cues_voided=int(row.get("cues_voided", 0)), hits=int(row.get("hits", 0)),
                    extra_activations=int(row.get("extra_activations", 0)),
                    latencies_s=tuple(float(x) for x in row.get("latencies_s", ())),
                    workday_weight=float(row.get("workday_weight", 0.0)),
                )
            )
        kinds = [EventKind(str(v)) for v in data["trigger_kinds"]]
        return _build_report(
            phases, budget_per_hour=float(data["budget_per_hour"]),
            min_phase_s=float(data["min_phase_s"]), trigger_kinds=kinds,
            aborted=bool(data.get("aborted", False)), sessions=int(data.get("sessions", 1)),
        )
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"malformed field-test report: {exc!r}") from None


def _num(x: float | None, spec: str = ".1f") -> str:
    return "-" if x is None else format(x, spec)


def _table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    widths = [max(len(header[i]), *(len(r[i]) for r in rows)) if rows else len(header[i])
              for i in range(len(header))]

    def line(cells: Sequence[str]) -> str:
        first = cells[0].ljust(widths[0])
        rest = "  ".join(c.rjust(widths[i + 1]) for i, c in enumerate(cells[1:]))
        return f"  {first}  {rest}".rstrip()

    return [line(header), line(["-" * w for w in widths]), *(line(r) for r in rows)]


def format_report(report: FieldTestReport) -> str:
    """Aligned plain text; ends with the honest caveat. Read the upper bounds."""
    out: list[str] = []
    n = report.sessions
    out.append(
        f"Field test: {n} session{'s' if n != 1 else ''}"
        f"{' (stopped early)' if report.aborted else ''}, budget {report.budget_per_hour:g} "
        f"phantom activations per hour"
    )
    out.append(f"Verdict: {report.verdict.value.upper().replace('_', ' ')}")
    out.extend(f"  - {r}" for r in report.reasons)

    quiet = [p for p in report.phases if not p.expects_intent]
    if quiet:
        out += ["", "Phantom activations (phases with no intent; usable signal only):"]
        rows = [
            [f"{p.label}" + ("" if p.status == "ok" else f" [{p.status.replace('_', ' ')}]"),
             str(p.usable_s), _num(None if p.quality_fraction is None else p.quality_fraction * 100, ".0f"),
             str(p.phantom_activations), _num(p.phantom_per_hour), _num(p.phantom_upper_per_hour)]
            for p in quiet
        ]
        out += _table(["phase", "usable s", "quality %", "count", "per hour", "upper 95% /h"], rows)

    gest = [p for p in report.phases if p.expects_intent]
    if gest:
        out += ["", "Deliberate gestures (an activation is wanted):"]
        rows = []
        for p in gest:
            ci = p.hit_ci
            rows.append([
                p.label + ("" if p.status == "ok" else f" [{p.status.replace('_', ' ')}]"),
                f"{p.hits}/{p.cues_scored}" + (f" (+{p.cues_voided} void)" if p.cues_voided else ""),
                _num(None if p.hit_rate is None else p.hit_rate * 100, ".0f"),
                "-" if ci is None else f"{ci[0] * 100:.0f}-{ci[1] * 100:.0f}",
                _num(p.median_latency_s), str(p.extra_activations),
            ])
        out += _table(["phase", "hits", "hit %", "95% CI %", "median s", "extra"], rows)
        out.append("  median s is cue-to-event, so it includes your reaction time.")

    w = report.workday
    out += ["", "Workday estimate (weighted by an assumed activity mix, a design choice, not data):"]
    if w.per_hour is None:
        out.append("  not available: no phase had enough usable signal.")
    else:
        out.append(
            f"  estimate {w.per_hour:.1f}/h, 95% bounds {_num(w.lower_per_hour)} to "
            f"{_num(w.upper_per_hour)}/h, from {w.usable_s} s of usable signal "
            f"({w.activations} phantom{'s' if w.activations != 1 else ''})"
        )
        out.append(
            f"  unweighted: {_num(w.raw_per_hour)}/h, upper {_num(w.raw_upper_per_hour)}/h"
        )
        out.append("  weights: " + ", ".join(f"{k} {v:.2f}" for k, v in w.weights))
    if w.phases_unmeasured:
        out.append("  not measured: " + ", ".join(w.phases_unmeasured))
    out += ["", CAVEAT]
    return "\n".join(out)
