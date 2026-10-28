#!/usr/bin/env python3
"""Metric code for the camera/gaze backend comparison protocol (issue #695).

The protocol is `design/hci-huggingface/CAMERA_GAZE_COMPARISON_PROTOCOL.md`. This module is the part
of it that can be tested with fake numbers and no camera: angular gaze error, a participant/session
leakage guard for splits, and a shape check for the comparison report. It runs no study, opens no
camera and reads no image; a live run needs hardware, informed participation and the ethics
determination in `design/eye-control/EVALUATION.md` (E7).

What it deliberately does not do:

* No rate per hour. The exposure rule for false-activation rates already exists in
  `yazses.eyeeval.analysis` (a provisional minimum exposure, below which the answer is
  "insufficient data"); use that, do not reimplement it here.
* No pixel-precision or "accuracy" figure. Coordinate error and angular error are reported as what
  they are, with the number of points they come from.
* No raw data. `validate_report` rejects a report that carries frames, images, landmarks, video,
  audio or embeddings (programme risk R-09: derived signals only).

Percentiles are nearest-rank (an observed value, never an interpolated one), the same convention as
`yazses.eyeeval.gaze_field`.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

PROTOCOL_VERSION = "0.1-proposed"

#: Keys that would mean a raw or identifying signal is in a report. Matched on the key name, at any depth.
RAW_DATA_KEYS = frozenset({"frame", "frames", "image", "images", "landmark", "landmarks", "video", "audio", "embedding"})

#: What a comparison report must contain (protocol section 10).
REPORT_KEYS = (
    "protocol_version",
    "question",
    "candidates",
    "sessions",
    "metrics",
    "negative_results",
    "limitations",
    "non_claims",
)
CANDIDATE_KEYS = ("name", "revision_or_hash", "licence")
SESSION_KEYS = ("participants", "devices", "sessions")
SPLITS = ("dev", "eval")


class MissingGeometry(ValueError):
    """Angular error needs the pixel pitch and the viewing distance; coordinate error does not."""


@dataclass(frozen=True)
class Geometry:
    """The display and seating a session recorded. Both numbers are required for an angle."""

    pixel_pitch_mm: float
    viewing_distance_mm: float

    def __post_init__(self) -> None:
        if not (self.pixel_pitch_mm > 0 and math.isfinite(self.pixel_pitch_mm)):
            raise ValueError("pixel_pitch_mm must be a positive number")
        if not (self.viewing_distance_mm > 0 and math.isfinite(self.viewing_distance_mm)):
            raise ValueError("viewing_distance_mm must be a positive number")


def nearest_rank(values: Sequence[float], percentile: float) -> float:
    """The nearest-rank percentile of `values` (an observed value). `values` must not be empty."""
    if not values:
        raise ValueError("no values")
    if not 0 < percentile <= 100:
        raise ValueError("percentile must be in (0, 100]")
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile / 100.0 * len(ordered)))
    return ordered[rank - 1]


def coordinate_error_px(target: tuple[float, float], estimate: tuple[float, float]) -> float:
    """Straight-line distance, in pixels, from the true target point to the estimated gaze point."""
    return math.hypot(estimate[0] - target[0], estimate[1] - target[1])


def angular_error_deg(error_px: float, geometry: Geometry | None) -> float:
    """The angle a pixel error subtends at the eye.

    The offset in millimetres is ``error_px * pixel_pitch_mm`` and the angle is
    ``atan(offset / viewing_distance)``. This assumes the eye is on the screen's normal near the
    target, which is a good approximation for small offsets and an underestimate far off-axis; the
    report must say so. Without both numbers there is no angle, only a pixel error.
    """
    if geometry is None:
        raise MissingGeometry("angular error needs pixel_pitch_mm and viewing_distance_mm")
    if error_px < 0 or not math.isfinite(error_px):
        raise ValueError("error_px must be a non-negative number")
    return math.degrees(math.atan(error_px * geometry.pixel_pitch_mm / geometry.viewing_distance_mm))


def summarize_errors(errors: Sequence[float]) -> dict[str, Any]:
    """Count, median and 95th percentile (nearest-rank). Always carries n; empty gives None, not 0."""
    if not errors:
        return {"n": 0, "median": None, "p95": None}
    return {"n": len(errors), "median": nearest_rank(errors, 50), "p95": nearest_rank(errors, 95)}


def summarize_session(
    pairs: Iterable[tuple[tuple[float, float], tuple[float, float]]],
    geometry: Geometry | None,
) -> dict[str, Any]:
    """Coordinate error always; angular error only when the geometry was recorded.

    `pairs` are (true target point, estimated gaze point) in pixels, one per validation point.
    """
    px = [coordinate_error_px(target, estimate) for target, estimate in pairs]
    out: dict[str, Any] = {"coordinate_error_px": summarize_errors(px)}
    if geometry is None:
        out["angular_error_deg"] = {"n": 0, "median": None, "p95": None, "reason": "geometry not recorded"}
    else:
        out["angular_error_deg"] = summarize_errors([angular_error_deg(e, geometry) for e in px])
    return out


def check_split(records: Iterable[Mapping[str, Any]]) -> list[str]:
    """Leakage between a development partition and an evaluation partition.

    Each record names its `participant`, `session` and `split` (`dev` or `eval`). Adjacent frames
    and trials are not independent, so no participant and no session may appear in both splits.
    Returns a list of problems; empty means no leakage.
    """
    problems: list[str] = []
    seen: dict[str, dict[str, set[str]]] = {"participant": {}, "session": {}}
    for i, record in enumerate(records):
        split = record.get("split")
        if split not in SPLITS:
            problems.append(f"record {i}: split {split!r} is not one of {SPLITS}")
            continue
        for unit in seen:
            ident = record.get(unit)
            if not isinstance(ident, str) or not ident:
                problems.append(f"record {i}: missing {unit}")
                continue
            seen[unit].setdefault(ident, set()).add(split)
    for unit, by_id in seen.items():
        for ident, splits in sorted(by_id.items()):
            if len(splits) > 1:
                problems.append(f"{unit} {ident!r} appears in both splits")
    return problems


def check_calibration_validation_disjoint(calibration_points: Iterable[Any], validation_points: Iterable[Any]) -> list[str]:
    """Error is measured on points the calibration did not use."""
    shared = set(calibration_points) & set(validation_points)
    return [f"point {p!r} is in both the calibration and the validation set" for p in sorted(shared, key=repr)]


def _walk_keys(node: Any, path: str = "") -> Iterable[tuple[str, str]]:
    if isinstance(node, Mapping):
        for key, value in node.items():
            where = f"{path}.{key}" if path else str(key)
            yield where, str(key)
            yield from _walk_keys(value, where)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _walk_keys(value, f"{path}[{i}]")


def validate_report(report: Mapping[str, Any]) -> list[str]:
    """Is this a complete comparison report, and does it carry nothing it must not?

    Returns a list of problems; empty means the shape is right. It checks shape, not truth.
    """
    problems: list[str] = []
    for key in REPORT_KEYS:
        if key not in report:
            problems.append(f"missing {key}")
    if problems:
        return problems
    candidates = report["candidates"]
    if not isinstance(candidates, list) or not candidates:
        problems.append("candidates must be a non-empty list")
    else:
        for i, candidate in enumerate(candidates):
            for key in CANDIDATE_KEYS:
                if not candidate.get(key):
                    problems.append(f"candidates[{i}] lacks {key} (a revision or hash is required, never 'latest')")
            if str(candidate.get("revision_or_hash", "")).lower() in {"latest", "main", "head"}:
                problems.append(f"candidates[{i}] names a moving ref instead of a revision or hash")
    sessions = report["sessions"]
    for key in SESSION_KEYS:
        if not isinstance(sessions.get(key), int) or isinstance(sessions.get(key), bool) or sessions[key] < 0:
            problems.append(f"sessions.{key} must be a non-negative integer (state the number of units)")
    if not isinstance(report["negative_results"], list):
        problems.append("negative_results must be a list (empty only if you say why in limitations)")
    if not isinstance(report["limitations"], list) or not report["limitations"]:
        problems.append("limitations must be a non-empty list: a report without them is incomplete")
    if not isinstance(report["non_claims"], list) or not report["non_claims"]:
        problems.append("non_claims must be a non-empty list")
    for where, key in _walk_keys(report):
        if key.lower() in RAW_DATA_KEYS:
            problems.append(f"{where}: raw or identifying data must not appear in a report")
    return problems
