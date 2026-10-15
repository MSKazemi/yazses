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

## Schema (``protocol.task_version`` "1.1"; ``schema_version`` is the envelope's, shared with ``yazses.eyeeval.schema``)

``feature.name = "gaze"``, ``protocol.task = "gaze_field_measurement"``, ``study_mode`` is
the tester's declaration (``community_qa`` for a public report). ``metrics``:

``calibration``
    ``source`` ("explicit" | "implicit"), ``age_s``, ``topology_validity``
    ("valid" | "unverified" | "stale"), ``validation_points``, ``error_px_rmse``,
    ``error_px_mean``, ``error_px_max``, ``error_deg_mean`` (degrees; missing without
    geometry), ``implicit_candidate_delta_px`` (stored refinement evidence, if any).
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

``METRICS.md`` is explicit that "gaze accuracy" is three different things — coordinate error,
correct-window rate, tracker availability — and must never be one number. This report keeps
them apart: ``calibration.*`` is coordinate error, ``routing.*`` is the window-level outcome,
and ``confidence.*`` is the availability/quality signal.

## What it does not do

It states no threshold, grade or verdict: whether an error is *good* is a cross-person
question for ``EVALUATION.md``, not something one tester's session can declare.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from yazses.eyeeval.provenance import Provenance, as_sections, fingerprint
from yazses.eyeeval.runner import safe_settings
from yazses.eyeeval.schema import DATA_CLASS_FOR_MODE, SCHEMA_VERSION, validate_result

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
]

#: Stamped into ``software.generator`` and ``protocol.task_version``; bump when the shape
#: of what this writes changes.
GENERATOR = "yazses.eyeeval.gaze_field/1.1"
TASK = "gaze_field_measurement"
TASK_VERSION = "1.1"

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

    def __post_init__(self) -> None:
        object.__setattr__(self, "t_s", _finite("t_s", self.t_s))
        err = _finite("error_px", self.error_px)
        if err < 0:
            raise ValueError("error_px must be >= 0")
        object.__setattr__(self, "error_px", err)


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
        if not errors:
            return {
                "validation_points": 0,
                "error_px_rmse": _missing(),
                "error_px_mean": _missing(),
                "error_px_max": _missing(),
                "error_deg_mean": _missing(),
            }
        mean = sum(errors) / len(errors)
        return {
            "validation_points": len(errors),
            "error_px_rmse": round(math.sqrt(sum(e * e for e in errors) / len(errors)), 2),
            "error_px_mean": round(mean, 2),
            "error_px_max": round(max(errors), 2),
            "error_deg_mean": (
                _missing("not_measured") if geometry is None
                else round(degrees_from_px(mean, geometry), 3)
            ),
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
        session.record_point(PointError(t_s=clock() - started_at, error_px=error))
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
        "error_px_mean", "error_px_max", "error_deg_mean", "implicit_candidate_delta_px",
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


def report_problems(doc: Any) -> list[str]:
    """Every problem with a gaze field report: the shared envelope's, then this schema's."""
    problems = validate_result(doc)
    if not isinstance(doc, dict):
        return problems
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
    environment = metrics.get("environment")
    if isinstance(environment, dict):
        if environment.get("glasses") not in GLASSES:
            problems.append(f"metrics.environment.glasses: expected one of {GLASSES}.")
        if environment.get("lighting") not in LIGHTING:
            problems.append(f"metrics.environment.lighting: expected one of {LIGHTING}.")
    return problems


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
        f"max {show(cal.get('error_px_max'), ' px')}, mean angle {show(cal.get('error_deg_mean'), ' deg')}",
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
