"""A privacy-safe gaze field-measurement report, for attaching to issue #104 (#399).

Issue #104 asks the one question the lab cannot answer: *how well does webcam gaze work on
real people's real desks?* What it has received is anecdotes — "mostly works", "drifts after
a while" — which cannot be compared, pooled or reproduced. This module turns a short local
session into a document that can: derived numbers in a fixed schema, with every figure that
was not measured written as an explicit marker and never as a zero.

It is the gaze-specific half of the evaluation envelope in ``yazses.eyeeval``: the same
``schema_version``, provenance, privacy sweep and missing-data rules as ``yazses eye-eval``,
so a gaze field report and a gaze task result sit in one table and are validated by one
function. What it adds is the ``metrics`` a field study needs and the schema for them
(below).

## What is in the report — and what structurally cannot be

*In:* the calibration error at known on-screen targets (px, and degrees **only** when the
tester supplied the screen size and viewing distance), the distribution of per-sample
confidence, routing attempts / fallbacks / tester-marked wrong-target corrections when the
tester counted them, error by time block (drift), calibration age and source, and optional
volunteered context (glasses, lighting, viewing distance, a camera label the tester chose).

*Cannot be:* a frame, a face mesh or landmark, a screenshot, dictated or typed text, a window
title, or an identity. There is no field for any of them — the same structural rule
``eyeeval.schema.FORBIDDEN_FIELD_TOKENS`` enforces — and the document is swept for home
paths, e-mail addresses and this machine's own hostname and login before anything is
written. Confidence is kept as a ten-bin histogram plus a running mean, not as a time
series, so there is no per-moment trace to leak either.

## Schema (``protocol.task_version`` "1.2"; ``schema_version`` is the envelope's, shared with ``yazses.eyeeval.schema``)

``feature.name = "gaze"``, ``protocol.task = "gaze_field_measurement"``, ``study_mode`` is
the tester's declaration (``community_qa`` for a public report). ``metrics``:

``calibration``
    ``source`` ("explicit" | "implicit"), ``age_s``, ``topology_validity``
    ("valid" | "unverified" | "stale"), ``validation_points``, ``error_px_rmse``,
    ``error_px_mean``, ``error_px_p50``, ``error_px_p90`` (nearest-rank percentiles of the
    per-point error), ``error_px_max``, ``error_deg_mean`` (degrees; missing without
    geometry), ``zone_grid`` / ``zone_points`` / ``zone_hits`` / ``zone_hit_rate`` (how
    often the predicted point fell in the same cell of a 3x3 screen grid as the target --
    the look-to-*pane* outcome, measured rather than tester-counted; a prediction off the
    screen is a miss), ``implicit_candidate_delta_px`` (stored refinement evidence, if
    any).
``confidence``
    ``samples``, ``mean``, ``min``, ``max``, ``below_threshold_fraction`` (against the
    ``confidence_min`` the tester ran with), ``histogram`` (ten bins of width 0.1).
``routing``
    ``attempts``, ``gaze_routed``, ``fallback_no_route``, ``wrong_target_corrections``,
    ``wrong_target_rate``, ``fallback_rate`` — all tester-counted, all missing when not.
``session``
    ``duration_s``, ``block_s`` and ``drift_blocks``: per time block, the number of
    validation points and their mean error.
``environment``
    ``glasses``, ``lighting``, ``viewing_distance_cm``, ``camera_label`` — volunteered,
    each ``"not_stated"`` when omitted.
``sufficiency``
    Whether there is enough data for the figures above to mean anything, said in the
    document itself so a one-point report cannot travel as a finding: ``provisional``
    (always true), then ``validation_points`` / ``confidence_samples`` /
    ``routing_attempts`` / ``drift_blocks``, each ``{n, minimum, enough}`` (``n`` is a
    missing marker when the tester did not count), and ``statements`` — plain sentences,
    one per shortfall. The minimums are **provisional reporting floors**, not statistical
    power: they exist to stop a single point reading as a result, and nothing was fitted to
    synthetic data to choose them. How many people and sessions a *claim* needs is
    ``EVALUATION.md``'s question.

## What the validator refuses

``report_problems`` is the reader for this task, not only a self-check. Beyond the shared
envelope it rejects a document that **could leak**, whoever produced it: a value carrying a
home directory or an e-mail address (``runner.privacy_problems``, plus this machine's own
hostname and login when ``identifiers`` are given); a key under ``metrics`` that names a
coordinate, an angle, a frame, a mesh, an eye feature or a trajectory; and any list or
object under ``metrics`` that this schema does not define. That last rule is the one that
matters: per-sample coordinates can only travel as a series, so a field report has exactly
three lists (the confidence histogram, the drift blocks, the sufficiency statements) and a
fourth is refused rather than read. The histogram must sum to the sample count and the
drift blocks to the validation points, so neither can be widened into a trace either.
``report_problems_text`` / ``report_problems_file`` apply the same rules to a file someone
attached, and fail on input that is missing, empty, not UTF-8 or not JSON -- an unreadable
report is a problem, never an empty document that then passes.

``METRICS.md`` is explicit that "gaze accuracy" is three different things — coordinate error,
correct-window rate, tracker availability — and must never be one number. This report keeps
them apart: ``calibration.*`` is coordinate error (``zone_*`` is that error expressed at the
granularity routing uses, still against known targets), ``routing.*`` is the tester-counted
window-level outcome, and ``confidence.*`` is the availability/quality signal.

## What it does not do

It states no threshold, grade or verdict: whether an error is *good* is a cross-person
question for ``EVALUATION.md``, not something one tester's session can declare.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from yazses.eyeeval.provenance import LocalIdentifiers, Provenance, as_sections, fingerprint
from yazses.eyeeval.runner import privacy_problems, safe_settings
from yazses.eyeeval.schema import (
    DATA_CLASS_FOR_MODE,
    SCHEMA_VERSION,
    parse_result_text,
    read_result_file,
    validate_result,
)
from yazses.gaze.zones import grid_zone

__all__ = [
    "CONFIDENCE_BINS",
    "GENERATOR",
    "GLASSES",
    "LIGHTING",
    "MIN_CONFIDENCE_SAMPLES",
    "MIN_DRIFT_BLOCKS",
    "MIN_ROUTING_ATTEMPTS",
    "MIN_VALIDATION_POINTS",
    "REQUIRED_METRICS",
    "TASK",
    "TASK_VERSION",
    "ZONE_COLS",
    "ZONE_ROWS",
    "CalibrationFacts",
    "Environment",
    "Geometry",
    "MeasurementSession",
    "PointError",
    "RoutingCounts",
    "build_report",
    "collect_validation",
    "degrees_from_px",
    "render_markdown",
    "report_problems",
    "report_problems_file",
    "report_problems_text",
    "zone_hit",
]

#: Stamped into ``software.generator`` and ``protocol.task_version``; bump when the shape
#: of what this writes changes.
GENERATOR = "yazses.eyeeval.gaze_field/1.2"
TASK = "gaze_field_measurement"
TASK_VERSION = "1.2"

#: The zone hit rate is measured on this grid: the 3x3 layout the validation targets are
#: drawn on (``gaze.calibrate.default_targets`` puts one target in each cell), so a hit
#: means "the calibration put the gaze in the right ninth of the screen". Fixed rather than
#: read from ``[gaze] zones``: a 2x2 grid would put the centre target on a cell corner.
ZONE_ROWS = 3
ZONE_COLS = 3

#: Confidence is binned, not recorded as a series. Ten bins of width 0.1 over 0..1.
CONFIDENCE_BINS = 10

GLASSES = ("none", "glasses", "contacts", "not_stated")
LIGHTING = ("dim", "normal", "bright", "backlit", "not_stated")

#: A camera label is whatever the tester typed; this is the whole of what is accepted, so
#: it cannot carry a path, an address or a sentence. (A *serial number* can still fit —
#: the CLI help says not to include one — which is why the privacy sweep also runs.)
_LABEL_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ._+-")
_LABEL_MAX = 48

_MISSING_DEFAULT = "not_measured"

#: PROVISIONAL reporting floors (see the module docstring, ``sufficiency``). Not measured
#: from anything and not a power calculation: a default 9-point pass clears the first two,
#: and a one-point or three-attempt report clears none. Change them with field evidence
#: (#104), and bump ``TASK_VERSION`` when you do.
MIN_VALIDATION_POINTS = 5
MIN_CONFIDENCE_SAMPLES = 30
MIN_ROUTING_ATTEMPTS = 20
#: Drift is a *change* between time blocks, so one block cannot show it.
MIN_DRIFT_BLOCKS = 2


def _missing(reason: str = _MISSING_DEFAULT) -> dict[str, Any]:
    """The explicit missing-data marker: never ``0``, never a bare ``null``."""
    return {"value": None, "reason": reason}


def _finite(name: str, value: float) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    return number


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PointError:
    """The calibration's error at one known on-screen target, at one moment in the session."""

    t_s: float          # seconds since the session began
    error_px: float     # euclidean distance, predicted point to target
    #: Whether the predicted point fell in the target's grid cell; ``None`` when the screen
    #: size was not known, so the point counts toward the error but not the zone rate.
    zone_hit: bool | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "t_s", _finite("t_s", self.t_s))
        err = _finite("error_px", self.error_px)
        if err < 0:
            raise ValueError("error_px must be >= 0")
        object.__setattr__(self, "error_px", err)
        if self.zone_hit is not None and not isinstance(self.zone_hit, bool):
            raise ValueError("zone_hit must be True, False or omitted")


def zone_hit(
    predicted: tuple[float, float], target: tuple[float, float], screen: tuple[int, int]
) -> bool:
    """Whether *predicted* lies in the same ``ZONE_ROWS`` x ``ZONE_COLS`` cell as *target*.

    A prediction off the screen is a miss. ``zones.grid_zone`` clamps an off-screen point
    into the nearest edge cell -- right for routing, where something must be chosen, and
    wrong here, where it would score a gaze that left the screen as a hit on every edge
    target.
    """
    width, height = screen
    px, py = predicted
    if not (0 <= px < width and 0 <= py < height):
        return False
    return grid_zone(px, py, width, height, ZONE_ROWS, ZONE_COLS) == grid_zone(
        target[0], target[1], width, height, ZONE_ROWS, ZONE_COLS
    )


def _nearest_rank(sorted_values: list[float], percentile: float) -> float:
    """The nearest-rank percentile: an observed value, never an interpolated one."""
    rank = max(1, math.ceil(percentile / 100.0 * len(sorted_values)))
    return sorted_values[rank - 1]


@dataclass(frozen=True)
class RoutingCounts:
    """What the tester counted while using gaze routing. ``None`` = they did not count."""

    attempts: int | None = None
    fallback_no_route: int | None = None
    wrong_target_corrections: int | None = None

    def __post_init__(self) -> None:
        for name in ("attempts", "fallback_no_route", "wrong_target_corrections"):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or int(value) != value or value < 0):
                raise ValueError(f"{name} must be a non-negative whole number or omitted")
        a, f, w = self.attempts, self.fallback_no_route, self.wrong_target_corrections
        if a is not None and f is not None and f > a:
            raise ValueError("fallback_no_route cannot exceed attempts")
        if a is not None and w is not None and w > a:
            raise ValueError("wrong_target_corrections cannot exceed attempts")


@dataclass(frozen=True)
class Geometry:
    """Screen and viewing geometry — the only thing that makes a degree figure honest."""

    screen_diagonal_in: float
    screen_width_px: int
    screen_height_px: int
    viewing_distance_cm: float

    def __post_init__(self) -> None:
        for name in ("screen_diagonal_in", "viewing_distance_cm"):
            if _finite(name, getattr(self, name)) <= 0:
                raise ValueError(f"{name} must be > 0")
        if self.screen_width_px <= 0 or self.screen_height_px <= 0:
            raise ValueError("the screen size in pixels must be positive")

    @property
    def pitch_cm(self) -> float:
        """Centimetres per pixel along the screen — diagonal over diagonal."""
        diagonal_px = math.hypot(self.screen_width_px, self.screen_height_px)
        return self.screen_diagonal_in * 2.54 / diagonal_px


def degrees_from_px(error_px: float, geometry: Geometry) -> float:
    """Visual angle subtended by *error_px* at the viewing distance (on-axis approximation)."""
    return math.degrees(math.atan2(error_px * geometry.pitch_cm, geometry.viewing_distance_cm))


@dataclass(frozen=True)
class Environment:
    """What the tester chose to tell us. Every field optional; omitted reads ``not_stated``."""

    glasses: str = "not_stated"
    lighting: str = "not_stated"
    viewing_distance_cm: float | None = None
    camera_label: str | None = None

    def __post_init__(self) -> None:
        if self.glasses not in GLASSES:
            raise ValueError(f"glasses must be one of {GLASSES}")
        if self.lighting not in LIGHTING:
            raise ValueError(f"lighting must be one of {LIGHTING}")
        if self.viewing_distance_cm is not None and not (
            math.isfinite(self.viewing_distance_cm) and self.viewing_distance_cm > 0
        ):
            raise ValueError("viewing_distance_cm must be a positive number")
        label = self.camera_label
        if label is not None:
            if not label.strip() or len(label) > _LABEL_MAX or not set(label) <= _LABEL_CHARS:
                raise ValueError(
                    f"camera_label must be 1-{_LABEL_MAX} characters of letters, digits, "
                    "space and . _ + - (no paths, addresses or serial numbers)"
                )


@dataclass(frozen=True)
class CalibrationFacts:
    """What is known about the calibration under test. Everything but the source is optional."""

    source: str = "explicit"
    age_s: float | None = None
    topology_validity: str = "unverified"
    implicit_candidate_delta_px: float | None = None


class MeasurementSession:
    """Accumulates one session's derived numbers, in bounded memory. Pure.

    Confidence samples are folded into a fixed histogram as they arrive; the raw sequence is
    never kept. Validation points are few (one per target per round) and are kept, because
    drift is a function of when each was taken.
    """

    def __init__(self, *, confidence_min: float = 0.5) -> None:
        self._confidence_min = _finite("confidence_min", confidence_min)
        self._bins = [0] * CONFIDENCE_BINS
        self._n = 0
        self._sum = 0.0
        self._min = math.inf
        self._max = -math.inf
        self._below = 0
        self._points: list[PointError] = []
        self._duration_s = 0.0
        self._confidence_unavailable = False

    def mark_confidence_unavailable(self) -> None:
        """The backend gives no per-sample confidence (L2CS returns a bare angle pair).

        Recorded so the report says *not supported* instead of printing an empty histogram
        that reads as "confidence was always zero", and never as a confidence of 1.0.
        """
        self._confidence_unavailable = True

    @property
    def confidence_samples(self) -> int:
        return self._n

    @property
    def confidence_min(self) -> float:
        return self._confidence_min

    @property
    def points(self) -> tuple[PointError, ...]:
        return tuple(self._points)

    @property
    def duration_s(self) -> float:
        """Session length: the later of the last validation point and any set duration."""
        return self._duration_s

    def record_confidence(self, confidence: float) -> None:
        value = _finite("confidence", confidence)
        if not 0.0 <= value <= 1.0:
            raise ValueError("confidence must be within 0..1")
        index = min(CONFIDENCE_BINS - 1, int(value * CONFIDENCE_BINS))
        self._bins[index] += 1
        self._n += 1
        self._sum += value
        self._min = min(self._min, value)
        self._max = max(self._max, value)
        if value < self._confidence_min:
            self._below += 1

    def record_point(self, point: PointError) -> None:
        self._points.append(point)
        self._duration_s = max(self._duration_s, point.t_s)

    def set_duration(self, duration_s: float) -> None:
        """The session's total length, when longer than the last point (e.g. the tester kept
        using gaze after the last validation)."""
        self._duration_s = max(self._duration_s, _finite("duration_s", duration_s))

    # -- derived -------------------------------------------------------------- #

    def confidence_block(self) -> dict[str, Any]:
        if self._n == 0:
            why = "not_supported" if self._confidence_unavailable else _MISSING_DEFAULT
            return {
                "samples": 0,
                "mean": _missing(why),
                "min": _missing(why),
                "max": _missing(why),
                "below_threshold_fraction": _missing(why),
                "threshold": self._confidence_min,
                "histogram": [0] * CONFIDENCE_BINS,
            }
        return {
            "samples": self._n,
            "mean": round(self._sum / self._n, 4),
            "min": round(self._min, 4),
            "max": round(self._max, 4),
            "below_threshold_fraction": round(self._below / self._n, 4),
            "threshold": self._confidence_min,
            "histogram": list(self._bins),
        }

    def error_block(self, geometry: Geometry | None) -> dict[str, Any]:
        errors = [p.error_px for p in self._points]
        zoned = [p.zone_hit for p in self._points if p.zone_hit is not None]
        hits = sum(1 for hit in zoned if hit)
        zone = {
            "zone_grid": f"{ZONE_ROWS}x{ZONE_COLS}",
            "zone_points": len(zoned),
            "zone_hits": hits if zoned else _missing(),
            "zone_hit_rate": round(hits / len(zoned), 4) if zoned else _missing(),
        }
        if not errors:
            return {
                "validation_points": 0,
                "error_px_rmse": _missing(),
                "error_px_mean": _missing(),
                "error_px_p50": _missing(),
                "error_px_p90": _missing(),
                "error_px_max": _missing(),
                "error_deg_mean": _missing(),
                **zone,
            }
        mean = sum(errors) / len(errors)
        ordered = sorted(errors)
        return {
            "validation_points": len(errors),
            "error_px_rmse": round(math.sqrt(sum(e * e for e in errors) / len(errors)), 2),
            "error_px_mean": round(mean, 2),
            "error_px_p50": round(_nearest_rank(ordered, 50), 2),
            "error_px_p90": round(_nearest_rank(ordered, 90), 2),
            "error_px_max": round(max(errors), 2),
            "error_deg_mean": (
                _missing("not_measured") if geometry is None
                else round(degrees_from_px(mean, geometry), 3)
            ),
            **zone,
        }

    def drift_blocks(self, block_s: float) -> list[dict[str, Any]]:
        """Mean error per fixed-length time block; blocks with no point are omitted, not zero."""
        if block_s <= 0 or not self._points:
            return []
        buckets: dict[int, list[float]] = {}
        for p in self._points:
            buckets.setdefault(max(0, int(p.t_s // block_s)), []).append(p.error_px)
        return [
            {
                "block": index,
                "start_s": round(index * block_s, 3),
                "points": len(values),
                "error_px_mean": round(sum(values) / len(values), 2),
            }
            for index, values in sorted(buckets.items())
        ]


    def sufficiency_block(self, routing: RoutingCounts, block_s: float) -> dict[str, Any]:
        """Whether there is enough data for the figures to mean anything. See the docstring."""
        points = len(self._points)
        blocks = len(self.drift_blocks(block_s))
        attempts = routing.attempts
        statements: list[str] = []

        def floor(n: int | None, minimum: int) -> dict[str, Any]:
            return {
                "n": _missing() if n is None else n,
                "minimum": minimum,
                "enough": n is not None and n >= minimum,
            }

        if points == 0:
            statements.append(
                "No validation point was measured, so there is no calibration error to report."
            )
        elif points < MIN_VALIDATION_POINTS:
            statements.append(
                f"Only {points} validation point(s) (at least {MIN_VALIDATION_POINTS} wanted): "
                "treat the error figures as indicative only."
            )
        if self._n == 0:
            statements.append(
                "This backend reports no per-sample confidence, so no confidence "
                "distribution exists."
                if self._confidence_unavailable
                else "No gaze sample was received, so there is no confidence distribution."
            )
        elif self._n < MIN_CONFIDENCE_SAMPLES:
            statements.append(
                f"Only {self._n} confidence sample(s) (at least {MIN_CONFIDENCE_SAMPLES} "
                "wanted): the confidence summary is indicative only."
            )
        if attempts is None:
            statements.append("Routing was not counted, so no routing rate is reported.")
        elif attempts < MIN_ROUTING_ATTEMPTS:
            statements.append(
                f"Only {attempts} routing attempt(s) (at least {MIN_ROUTING_ATTEMPTS} wanted): "
                "the routing rates are indicative only."
            )
        if blocks < MIN_DRIFT_BLOCKS:
            statements.append(
                f"{blocks} time block(s) with data (at least {MIN_DRIFT_BLOCKS} needed): "
                "drift cannot be assessed from this session."
            )
        return {
            "provisional": True,
            "validation_points": floor(points, MIN_VALIDATION_POINTS),
            "confidence_samples": floor(self._n, MIN_CONFIDENCE_SAMPLES),
            "routing_attempts": floor(attempts, MIN_ROUTING_ATTEMPTS),
            "drift_blocks": floor(blocks, MIN_DRIFT_BLOCKS),
            "statements": statements,
        }


# --------------------------------------------------------------------------- #
# Collecting a validation pass (I/O-agnostic, like gaze.calibrate.collect_samples)
# --------------------------------------------------------------------------- #


def collect_validation(
    backend: Any,
    calibration: Any,
    targets: Sequence[tuple[str, tuple[int, int]]],
    before_point: Callable[[str, tuple[int, int]], None],
    session: MeasurementSession,
    clock: Callable[[], float],
    *,
    per_point: int = 8,
    started_at: float = 0.0,
    screen: tuple[int, int] | None = None,
) -> int:
    """Measure the stored calibration at each target; return how many targets produced a point.

    For every target the tester is prompted, up to *per_point* samples are read, every
    sample's confidence goes into the histogram, and the **mean** gaze is mapped through the
    calibration to a screen point whose distance from the target is the error. A target with
    no usable sample contributes nothing — no point, not a zero-error point.

    *backend* is read through ``estimate_sample()`` (an object with ``x``/``y``/``confidence``)
    when it has one -- the MediaPipe backend does -- and through the ``GazeBackend`` protocol's
    plain ``estimate()`` (a bare ``(yaw, pitch)``) when it does not -- the L2CS backend
    does not, and calling ``estimate_sample`` on it would end a tester's session with an
    ``AttributeError`` after every target was already looked at. Such a backend reports no
    confidence, and the session says so (a *not supported* marker); a confidence is never
    invented for it. *calibration* needs ``predict(x, y)``. Both are duck-typed so the pass
    runs against fakes.

    A sample whose numbers are not finite, or whose confidence is outside 0..1, is a backend
    fault and is skipped like a no-face read: one such frame must not abort the pass, and
    must not become a NaN error figure either.

    With *screen* (``(width, height)`` of the desktop the targets are drawn on), each point
    also records whether the prediction landed in the target's grid cell (`zone_hit`).
    Only that yes/no is kept; the predicted coordinate is not.
    """
    sampler = getattr(backend, "estimate_sample", None)
    if sampler is None:
        session.mark_confidence_unavailable()
    produced = 0
    for label, xy in targets:
        before_point(label, xy)
        xs: list[float] = []
        ys: list[float] = []
        for _ in range(per_point):
            read = _read_sample(backend, sampler)
            if read is None:
                continue
            x, y, confidence = read
            if confidence is not None:
                session.record_confidence(confidence)
            xs.append(x)
            ys.append(y)
        if not xs:
            continue
        px, py = calibration.predict(sum(xs) / len(xs), sum(ys) / len(ys))
        error = math.hypot(px - xy[0], py - xy[1])
        if not math.isfinite(error):
            continue  # a calibration that predicts NaN measured nothing: no point, not a zero
        hit = None if screen is None else zone_hit((px, py), xy, screen)
        session.record_point(PointError(t_s=clock() - started_at, error_px=error, zone_hit=hit))
        produced += 1
    return produced


def _read_sample(backend: Any, sampler: Any) -> tuple[float, float, float | None] | None:
    """One usable ``(x, y, confidence-or-None)`` from *backend*, or ``None``."""
    if sampler is not None:
        sample = sampler()
        if sample is None:
            return None
        x, y, confidence = sample.x, sample.y, sample.confidence
    else:
        point = backend.estimate()
        if point is None:
            return None
        x, y = point
        confidence = None
    try:
        x, y = float(x), float(y)
        conf = None if confidence is None else float(confidence)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(x) and math.isfinite(y)):
        return None
    if conf is not None and not (math.isfinite(conf) and 0.0 <= conf <= 1.0):
        return None
    return x, y, conf


# --------------------------------------------------------------------------- #
# The document
# --------------------------------------------------------------------------- #


def _rate(numerator: int | None, denominator: int | None) -> Any:
    if numerator is None or denominator is None or denominator <= 0:
        return _missing()
    return round(numerator / denominator, 4)


def _count(value: int | None) -> Any:
    return _missing() if value is None else int(value)


def build_report(
    *,
    provenance: Provenance,
    timestamp: str,
    session: MeasurementSession,
    calibration: CalibrationFacts,
    study_mode: str = "community_qa",
    camera_class: str = "integrated",
    backend_name: str = "mediapipe",
    settings: dict[str, Any] | None = None,
    routing: RoutingCounts | None = None,
    geometry: Geometry | None = None,
    environment: Environment | None = None,
    block_s: float = 300.0,
) -> dict[str, Any]:
    """Assemble the report. Pure: no clock, no host, no disk, no validation, no output.

    *timestamp* and *provenance* are arguments so a golden test has a fixed document.
    """
    env = environment or Environment()
    counts = routing or RoutingCounts()
    sections = as_sections(provenance)
    safe = safe_settings(settings)
    gaze_routed = (
        None if counts.attempts is None or counts.fallback_no_route is None
        else counts.attempts - counts.fallback_no_route
    )

    calibration_block: dict[str, Any] = {
        "source": calibration.source,
        "age_s": _missing() if calibration.age_s is None else round(float(calibration.age_s), 1),
        "topology_validity": calibration.topology_validity,
        **session.error_block(geometry),
        "implicit_candidate_delta_px": (
            _missing() if calibration.implicit_candidate_delta_px is None
            else round(float(calibration.implicit_candidate_delta_px), 2)
        ),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "study_mode": study_mode,
        "timestamp": timestamp,
        "software": {
            **sections["software"],
            "perception_backend": {"name": backend_name, "asset_version": None},
            "generator": GENERATOR,
        },
        "machine": sections["machine"],
        "os_session": sections["os_session"],
        "display": sections["display"],
        "camera": {"camera_class": camera_class, "capture_mode": "live"},
        "feature": {"name": "gaze"},
        "config": {"config_hash": fingerprint(safe), "settings": safe},
        "protocol": {
            "task": TASK,
            "task_version": TASK_VERSION,
            "task_seed": None,
            "protocol_id": None,
        },
        "metrics": {
            "calibration": calibration_block,
            "confidence": session.confidence_block(),
            "routing": {
                "attempts": _count(counts.attempts),
                "gaze_routed": _count(gaze_routed),
                "fallback_no_route": _count(counts.fallback_no_route),
                "wrong_target_corrections": _count(counts.wrong_target_corrections),
                "wrong_target_rate": _rate(counts.wrong_target_corrections, counts.attempts),
                "fallback_rate": _rate(counts.fallback_no_route, counts.attempts),
            },
            "session": {
                "duration_s": round(session.duration_s, 1) if session.duration_s > 0 else _missing(),
                "block_s": block_s,
                "drift_blocks": session.drift_blocks(block_s),
            },
            "sufficiency": session.sufficiency_block(counts, block_s),
            "environment": {
                "glasses": env.glasses,
                "lighting": env.lighting,
                "viewing_distance_cm": (
                    _missing() if env.viewing_distance_cm is None
                    else round(float(env.viewing_distance_cm), 1)
                ),
                "camera_label": _missing() if env.camera_label is None else env.camera_label,
            },
        },
        "privacy": {
            "data_class": DATA_CLASS_FOR_MODE.get(study_mode),
            "raw_media_retained": False,
            "contains_personal_identifiers": False,
            "aggregates_only": True,
        },
    }


#: The metric groups and keys this report always carries — present even when empty, so a
#: reader never has to ask whether a key was omitted or never existed.
REQUIRED_METRICS: dict[str, tuple[str, ...]] = {
    "calibration": (
        "source", "age_s", "topology_validity", "validation_points", "error_px_rmse",
        "error_px_mean", "error_px_p50", "error_px_p90", "error_px_max", "error_deg_mean",
        "zone_grid", "zone_points", "zone_hits", "zone_hit_rate", "implicit_candidate_delta_px",
    ),
    "confidence": (
        "samples", "mean", "min", "max", "below_threshold_fraction", "threshold", "histogram",
    ),
    "routing": (
        "attempts", "gaze_routed", "fallback_no_route", "wrong_target_corrections",
        "wrong_target_rate", "fallback_rate",
    ),
    "session": ("duration_s", "block_s", "drift_blocks"),
    "environment": ("glasses", "lighting", "viewing_distance_cm", "camera_label"),
    "sufficiency": (
        "provisional", "validation_points", "confidence_samples", "routing_attempts",
        "drift_blocks", "statements",
    ),
}


#: The only lists a field report has, by path under ``metrics``. Per-sample coordinates
#: can only travel as a series, so any other list is refused rather than read.
_ALLOWED_LISTS = frozenset({"confidence.histogram", "session.drift_blocks", "sufficiency.statements"})

#: The only objects under ``metrics`` that are not missing-data markers.
_ALLOWED_OBJECTS = frozenset(
    {*REQUIRED_METRICS}
    | {f"sufficiency.{key}" for key in (
        "validation_points", "confidence_samples", "routing_attempts", "drift_blocks",
    )}
)

#: The exact keys of one drift block. A block that grows a key is a block that could carry
#: the points inside it.
_DRIFT_BLOCK_KEYS = frozenset({"block", "start_s", "points", "error_px_mean"})

#: Key names under ``metrics`` that would hold raw gaze rather than a summary of it. Exact
#: names are matched whole (``x`` must not fire on ``max``); tokens anywhere in the name.
#: Checked under ``metrics`` only: the shared envelope's ``display.displays`` legitimately
#: carries a monitor's ``x``/``y`` origin.
_RAW_KEY_NAMES = frozenset({"x", "y", "px", "py", "yaw", "pitch", "roll", "xy"})
_RAW_KEY_TOKENS = (
    "coordinate", "coords", "gaze_point", "frame", "mesh", "iris", "pupil", "eye_",
    "trajectory", "image", "pixels",
)


def _is_marker(node: Any) -> bool:
    return isinstance(node, dict) and ("value" in node or "reason" in node)


def _raw_data_problems(node: Any, path: str) -> list[str]:
    """Containers this schema does not define, and keys that name raw gaze, under metrics."""
    out: list[str] = []
    if isinstance(node, dict):
        if path and path not in _ALLOWED_OBJECTS and not _is_marker(node):
            out.append(
                f"metrics.{path}: an object this schema does not define. A field report "
                "carries summaries only; a per-sample series (coordinates, angles, frames) "
                "cannot be attached to it under any name."
            )
            return out
        for key, value in node.items():
            low = str(key).lower()
            where = f"{path}.{key}" if path else str(key)
            if low in _RAW_KEY_NAMES or any(token in low for token in _RAW_KEY_TOKENS):
                out.append(
                    f"metrics.{where}: the name describes raw gaze data, which a field report "
                    "never contains (DATA_SHARING.md). Remove the field; do not rename it."
                )
                continue
            out += _raw_data_problems(value, where)
    elif isinstance(node, list):
        if path not in _ALLOWED_LISTS:
            out.append(
                f"metrics.{path}: a list this schema does not define. The only lists are "
                f"{sorted(_ALLOWED_LISTS)}; a per-sample series is refused rather than read."
            )
        elif path == "session.drift_blocks":
            for index, block in enumerate(node):
                if not isinstance(block, dict) or set(block) != _DRIFT_BLOCK_KEYS:
                    out.append(
                        f"metrics.{path}.{index}: a drift block has exactly the keys "
                        f"{sorted(_DRIFT_BLOCK_KEYS)}."
                    )
        elif any(not isinstance(item, (str, int, float)) or isinstance(item, bool) for item in node):
            out.append(f"metrics.{path}: holds something other than plain numbers or sentences.")
    return out


def _consistency_problems(metrics: dict[str, Any]) -> list[str]:
    """The histogram sums to the samples and the drift blocks to the validation points.

    Without these, a "histogram" of thousands of bins or a "drift block" per sample would be
    a trace in summary's clothing; with them, each list is bounded by a count it summarises.
    """
    out: list[str] = []
    conf = metrics.get("confidence")
    if isinstance(conf, dict):
        histogram, samples = conf.get("histogram"), conf.get("samples")
        if isinstance(histogram, list) and len(histogram) == CONFIDENCE_BINS:
            if not all(isinstance(b, int) and not isinstance(b, bool) and b >= 0 for b in histogram):
                out.append("metrics.confidence.histogram: each bin is a non-negative count.")
            elif isinstance(samples, int) and sum(histogram) != samples:
                out.append("metrics.confidence.histogram: the bins do not add up to samples.")
    cal, session = metrics.get("calibration"), metrics.get("session")
    if isinstance(cal, dict) and isinstance(session, dict):
        blocks, points = session.get("drift_blocks"), cal.get("validation_points")
        if isinstance(blocks, list) and all(isinstance(b, dict) for b in blocks):
            counts = [b.get("points") for b in blocks]
            if not all(isinstance(c, int) and not isinstance(c, bool) and c >= 1 for c in counts):
                out.append("metrics.session.drift_blocks: each block holds at least one point.")
            elif isinstance(points, int) and sum(counts) != points:
                out.append(
                    "metrics.session.drift_blocks: the blocks do not add up to "
                    "calibration.validation_points."
                )
        zoned, hits = cal.get("zone_points"), cal.get("zone_hits")
        if isinstance(zoned, int) and isinstance(points, int) and zoned > points:
            out.append("metrics.calibration.zone_points: exceeds validation_points.")
        if isinstance(hits, int) and isinstance(zoned, int) and hits > zoned:
            out.append("metrics.calibration.zone_hits: exceeds zone_points.")
    return out


def report_problems(doc: Any, identifiers: LocalIdentifiers | None = None) -> list[str]:
    """Every problem with a gaze field report: the shared envelope's, then this schema's.

    Includes the privacy sweep (generic patterns always; this machine's own hostname and
    login only when *identifiers* are given -- a maintainer checking someone else's file has
    no way to know theirs) and the raw-data rules in the module docstring. Empty means the
    document is valid **and** carries nothing but aggregates.
    """
    problems = validate_result(doc)
    if not isinstance(doc, dict):
        return problems
    problems += privacy_problems(doc, identifiers)
    if (doc.get("protocol") or {}).get("task") != TASK:
        problems.append(f"protocol.task: expected {TASK!r}.")
    metrics = doc.get("metrics")
    if not isinstance(metrics, dict):
        return problems
    for group, keys in REQUIRED_METRICS.items():
        body = metrics.get(group)
        if not isinstance(body, dict):
            problems.append(f"metrics.{group}: missing or not an object.")
            continue
        for key in keys:
            if key not in body:
                problems.append(f"metrics.{group}.{key}: missing required field.")
    confidence = metrics.get("confidence")
    if isinstance(confidence, dict):
        histogram = confidence.get("histogram")
        if not (isinstance(histogram, list) and len(histogram) == CONFIDENCE_BINS):
            problems.append(f"metrics.confidence.histogram: expected {CONFIDENCE_BINS} bins.")
    problems += _sufficiency_problems(metrics)
    problems += _raw_data_problems(metrics, "")
    problems += _consistency_problems(metrics)
    environment = metrics.get("environment")
    if isinstance(environment, dict):
        if environment.get("glasses") not in GLASSES:
            problems.append(f"metrics.environment.glasses: expected one of {GLASSES}.")
        if environment.get("lighting") not in LIGHTING:
            problems.append(f"metrics.environment.lighting: expected one of {LIGHTING}.")
    return problems


def report_problems_text(text: str, identifiers: LocalIdentifiers | None = None) -> list[str]:
    """`report_problems` for JSON text. Empty, garbled or non-JSON text is a problem. Total."""
    doc, problems = parse_result_text(text)
    if problems:
        return problems
    try:
        return report_problems(doc, identifiers)
    except RecursionError:
        return ["<file>: nested too deeply to be a result document."]


def report_problems_file(path: str | Path, identifiers: LocalIdentifiers | None = None) -> list[str]:
    """`report_problems` for the report at *path*. A missing, empty, non-UTF-8 or non-JSON
    file is a problem, never an empty document that passes."""
    doc, problems = read_result_file(path)
    if problems:
        return problems
    try:
        return report_problems(doc, identifiers)
    except RecursionError:
        return ["<file>: nested too deeply to be a result document."]


def _sufficiency_problems(metrics: dict[str, Any]) -> list[str]:
    """``enough`` must follow from ``n`` and ``minimum``, and ``n`` from the metrics beside it.

    A report that says it has enough data while its own numbers show otherwise is the exact
    thing this block exists to prevent, so the validator checks the claim rather than the
    shape.
    """
    block = metrics.get("sufficiency")
    if not isinstance(block, dict):
        return []
    out: list[str] = []
    def group(name: str) -> dict[str, Any]:
        found = metrics.get(name)
        return found if isinstance(found, dict) else {}

    cal, conf, routing, session = (
        group("calibration"), group("confidence"), group("routing"), group("session")
    )
    expected = {
        "validation_points": cal.get("validation_points"),
        "confidence_samples": conf.get("samples"),
        "routing_attempts": routing.get("attempts"),
        "drift_blocks": (
            len(session["drift_blocks"]) if isinstance(session.get("drift_blocks"), list) else None
        ),
    }
    for key, observed in expected.items():
        entry = block.get(key)
        if not isinstance(entry, dict):
            continue  # already reported as a missing field
        n, minimum, enough = entry.get("n"), entry.get("minimum"), entry.get("enough")
        count = n if isinstance(n, int) and not isinstance(n, bool) else None
        if isinstance(observed, dict):
            observed = None  # a missing marker in the metric is a missing n here
        if count != observed:
            out.append(f"metrics.sufficiency.{key}.n: does not match the figure it summarises.")
        want = count is not None and isinstance(minimum, int) and count >= minimum
        if enough is not want:
            out.append(f"metrics.sufficiency.{key}.enough: contradicts n and minimum.")
    if not isinstance(block.get("statements"), list) or not all(
        isinstance(x, str) for x in block.get("statements", [])
    ):
        out.append("metrics.sufficiency.statements: expected a list of sentences.")
    return out


def render_markdown(doc: dict[str, Any]) -> str:
    """A short Markdown summary a tester can paste into #104 next to the JSON."""
    metrics = doc.get("metrics", {})
    cal = metrics.get("calibration", {})
    conf = metrics.get("confidence", {})
    routing = metrics.get("routing", {})
    session = metrics.get("session", {})
    env = metrics.get("environment", {})
    sufficiency = metrics.get("sufficiency", {})

    def show(value: Any, unit: str = "") -> str:
        if isinstance(value, dict) and "reason" in value:
            return f"not measured ({value['reason']})"
        return f"{value}{unit}"

    lines = [
        "## Gaze field measurement",
        "",
        f"- YazSes {doc.get('software', {}).get('yazses_version', 'unknown')}, "
        f"{doc.get('machine', {}).get('os_name', 'unknown')} "
        f"({doc.get('os_session', {}).get('session_type', 'unknown')}), "
        f"{doc.get('camera', {}).get('camera_class', 'unknown')} camera, "
        f"study mode `{doc.get('study_mode')}`",
        f"- Calibration: {cal.get('source')} map, topology {cal.get('topology_validity')}, "
        f"age {show(cal.get('age_s'), ' s')}",
        f"- Error at {cal.get('validation_points')} validation point(s): RMSE "
        f"{show(cal.get('error_px_rmse'), ' px')}, mean {show(cal.get('error_px_mean'), ' px')}, "
        f"median {show(cal.get('error_px_p50'), ' px')}, p90 {show(cal.get('error_px_p90'), ' px')}, "
        f"max {show(cal.get('error_px_max'), ' px')}, mean angle {show(cal.get('error_deg_mean'), ' deg')}",
        f"- Zone hits ({cal.get('zone_grid')} grid): {show(cal.get('zone_hits'))} of "
        f"{cal.get('zone_points')} point(s), rate {show(cal.get('zone_hit_rate'))}",
        f"- Confidence over {conf.get('samples')} sample(s): mean {show(conf.get('mean'))}, "
        f"below {conf.get('threshold')}: {show(conf.get('below_threshold_fraction'))}",
        f"- Routing (tester-counted): {show(routing.get('attempts'))} attempts, "
        f"{show(routing.get('fallback_no_route'))} fallbacks, "
        f"{show(routing.get('wrong_target_corrections'))} wrong-target corrections",
        f"- Session {show(session.get('duration_s'), ' s')} in {session.get('block_s')} s blocks",
    ]
    for block in session.get("drift_blocks", []):
        lines.append(
            f"  - block {block['block']} (from {block['start_s']} s): "
            f"{block['points']} point(s), mean {block['error_px_mean']} px"
        )
    lines.append(
        f"- Context: glasses {env.get('glasses')}, lighting {env.get('lighting')}, "
        f"distance {show(env.get('viewing_distance_cm'), ' cm')}, camera {show(env.get('camera_label'))}"
    )
    statements = sufficiency.get("statements", [])
    if statements:
        lines.append("- **Not enough data for a finding** (provisional floors, not statistics):")
        lines += [f"  - {sentence}" for sentence in statements]
    else:
        lines.append(
            "- Sample size: above the provisional reporting floors "
            "(a floor is not a statistical power claim)"
        )
    lines += [
        "",
        "Derived numbers only: no frames, landmarks, screenshots, text or window titles.",
        "A figure marked *not measured* was not measured; it is not zero.",
    ]
    return "\n".join(lines) + "\n"
