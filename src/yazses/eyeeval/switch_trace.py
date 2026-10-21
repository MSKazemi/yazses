"""The privacy-safe face-switch trace document: a versioned schema and a pure validator.

EYE-BENCH-001 (#409), ``design/eye-control/ROADMAP.md`` P5.4. The ROADMAP's shipping
question for a facial switch is not classifier accuracy but *phantom actions over a
workday*, and the only honest way to ask it without a camera is to replay a **numeric**
trace: one gesture score per sample, an optional landmarker confidence per sample, and a
run-length label saying what the person was doing (``rest``, ``speech``, ...). This module
is the input half of that: the envelope one trace arrives in, and a validator that turns a
parsed document into a typed :class:`SwitchTrace` or into a list of problems. The evaluator
is :mod:`yazses.eyeeval.switch_replay`; the command-line front end is
``scripts/replay_face_switch_trace.py``.

It reads no file, no clock and no camera, and imports nothing outside the standard library
and this repository's own pure vocabulary.

## What a trace may contain, and what it structurally cannot

A trace is one ``gesture`` name, a ``sample_rate_hz``, a list of ``scores`` (and optionally
``confidences``) -- numbers in ``0..1`` or ``null`` for "no reading" -- and ``segments``,
which run-length-label those samples with a context from a closed list. There is no key for
a camera image, a face mesh, a landmark, a blendshape *vector*, a person, a session, a
recording path or a transcript, and a document that invents one at any depth is refused:
:func:`~yazses.eyeeval.schema.forbidden_field_problems` (the one list the result schema and
the grounding trace already share, imported rather than copied) plus the handful of extra
tokens in :data:`EXTRA_FORBIDDEN_TOKENS` that only make sense for a trace. Unknown fields
are otherwise ignored under the same-major rule, and **are never copied anywhere**: the
report is built from the typed fields below and never touches the raw document, so an
ignored field cannot reach an output by accident.

One gesture score per sample is deliberately all that is stored. A whole blendshape vector
is a facial signature; a single scalar for the one movement being tested is not.

``study_mode`` is ``synthetic``, ``ci`` or ``community_qa`` (ADR-v2-150). ``research`` is
refused: a research-mode artifact needs a named protocol and a consent process this
document has no field for, and relabelling after collection is not consent.

## Time is the sample index

There are no timestamps. Sample ``i`` is at ``i / sample_rate_hz`` seconds, so a trace is
uniformly sampled and a dropped frame is written as a ``null`` reading rather than being
left out. That is what keeps a duration (and therefore a per-hour rate) well defined.

## Why an empty trace is an error rather than an empty report

A rate computed over nothing is ``0.0``, and ``0.0`` phantom actions per hour reads exactly
like a switch that never misfires. So a trace needs at least one sample and at least one
segment, the segment lengths must add up to the number of samples, and an empty document is
a rule violation, not a short report. (A trace with samples but *no non-deliberate time*, or
no deliberate gesture, is valid; the evaluator reports the metric it cannot compute as
missing.)

## Versioning

``schema_version`` is ``"MAJOR.MINOR"`` with the rule ``src/yazses/eyeeval/schema.py`` sets:
same major accepted, a different major refused rather than half-read.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from yazses.eyeeval.schema import forbidden_field_problems
from yazses.facegesture.detector import GESTURES

#: The trace schema version this module implements and the fixtures declare. 1.1 added the
#: nuisance contexts ``blink``, ``yawn`` and ``look_down`` (additive: every 1.0 document is a
#: valid 1.1 document, and a 1.0 reader refuses a 1.1 one that uses them rather than mislabel it).
TRACE_SCHEMA_VERSION = "1.1"
SUPPORTED_MAJOR = 1

#: ADR-v2-150 classes A and B. ``research`` is absent on purpose; see the module docstring.
STUDY_MODES = ("synthetic", "ci", "community_qa")

#: The label a segment carries. A closed list so a typo is a failure, not a new
#: silently-unaggregated context. ``deliberate`` is the one that is *intended*; every other
#: context is exposure to accidental activation and counts toward the phantom rate.
#:
#: ``blink``, ``yawn`` and ``look_down`` (1.1) name the involuntary movements a switch most
#: plausibly mistakes for a gesture -- a spontaneous blink for ``eyes_closed``, a yawn for
#: ``jaw_open``, a glance at the keyboard (the lids lower, so eye-blink scores rise) for
#: ``eyes_closed`` -- so a report can say *which* nuisance produced a phantom instead of
#: folding it into ``other``. ``speech`` is talking.
DELIBERATE = "deliberate"
CONTEXTS = (
    "rest", "speech", "head_movement", "smile", "blink", "yawn", "look_down", DELIBERATE, "other",
)
NON_DELIBERATE_CONTEXTS = tuple(c for c in CONTEXTS if c != DELIBERATE)

#: Key-name fragments that name data a trace must never carry, beyond the shared list.
#: Substring match, like the shared list, so a renamed copy ("face_mesh_pts") still fails.
EXTRA_FORBIDDEN_TOKENS = (
    "frame", "image", "pixel", "mesh", "video", "audio", "participant", "identity",
    "subject", "face_id", "blendshape", "embedding", "voiceprint", "recording_path",
)

REQUIRED_TOP_LEVEL = (
    "schema_version", "trace_id", "study_mode", "gesture", "sample_rate_hz", "segments", "scores",
)

_TRACE_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,79}")
#: ``MAJOR.MINOR`` in ASCII digits only. ``str.isdigit`` accepts "\u00b2" and Arabic-Indic digits, and
#: ``int("\u00b2")`` then raises -- a traceback where a problem list belongs.
_VERSION = re.compile(r"[0-9]{1,6}\.[0-9]{1,6}")
MAX_DESCRIPTION = 280

#: A trace's rate must be one a camera or a down-sampler could plausibly have produced. Not a
#: product number: it only keeps ``duration = samples / rate`` and a per-hour rate finite and
#: meaningful (a 1e308 Hz trace is a duration of zero and a rate of infinity).
MIN_SAMPLE_RATE_HZ = 0.1
MAX_SAMPLE_RATE_HZ = 1000.0

#: Top-level key names that mean "this trace carries its own clock". Time is the sample index
#: here, so a document with timestamps cannot be honoured -- and silently ignoring them would
#: replay a trace with gaps, jitter or time running backwards as if it were evenly sampled and
#: report a duration (and so a per-hour rate) that is wrong. Refuse, and say how to fix it.
TIME_KEY_TOKENS = ("timestamp", "time_s", "time_ms", "times", "elapsed")
TIME_KEY_NAMES = ("t", "time", "dt", "ts")


class SwitchTraceError(ValueError):
    """One or more trace-schema violations, listed one per line."""


@dataclass(frozen=True)
class Segment:
    """``samples`` consecutive samples that share one ``context``."""

    context: str
    samples: int


@dataclass(frozen=True)
class SwitchTrace:
    """One validated trace. Every reading is a finite float in 0..1 or ``None``.

    ``None`` is "no reading" -- a ``null`` in the document, or a NaN that a JSON writer
    emitted for one. ``confidences`` is always the same length as ``scores``; it is all
    ``None`` when the document carried none (a source that reports no confidence, which
    is the landmarker's actual behaviour -- see ``ROADMAP.md`` P5.4).
    """

    trace_id: str
    study_mode: str
    gesture: str
    sample_rate_hz: float
    segments: tuple[Segment, ...]
    scores: tuple[float | None, ...]
    confidences: tuple[float | None, ...]
    baseline_level: float | None = None
    description: str = ""

    @property
    def samples(self) -> int:
        return len(self.scores)

    @property
    def duration_s(self) -> float:
        return len(self.scores) / self.sample_rate_hz


# --------------------------------------------------------------------------- #
# Small typed readers. Each appends a problem and returns a sentinel rather than
# raising, so one malformed field does not hide the other nine.
# --------------------------------------------------------------------------- #


def _extra_forbidden(node: Any, path: str = "") -> list[str]:
    out: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            low = str(key).lower()
            for token in EXTRA_FORBIDDEN_TOKENS:
                if token in low:
                    out.append(
                        f"{path}{key}: forbidden field -- the name contains {token!r}. A "
                        f"switch trace holds one numeric score per sample and a label, "
                        f"never an image, mesh, vector or identity. Remove the field; do "
                        f"not rename it."
                    )
            out += _extra_forbidden(value, f"{path}{key}.")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            out += _extra_forbidden(value, f"{path}{i}.")
    return out


def _time_key_problems(doc: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key in doc:
        low = str(key).lower()
        if low in TIME_KEY_NAMES or any(token in low for token in TIME_KEY_TOKENS):
            out.append(
                f"{key}: a trace carries no clock -- sample i is at i / sample_rate_hz seconds, so "
                f"a timestamp column would be silently ignored and a gap, jitter or time running "
                f"backwards would be replayed as an evenly sampled trace. Resample onto a uniform "
                f"grid first and write each dropped frame as a null reading."
            )
    return out


def _reading(raw: Any) -> tuple[bool, float | None]:
    """``(ok, value)``: ok is False for a value that is not a reading at all."""
    if raw is None:
        return True, None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return False, None
    value = float(raw)
    if math.isnan(value):
        return True, None  # a NaN is a missing reading, not a number
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        return False, None
    return True, value


def _column(raw: Any, name: str, problems: list[str]) -> tuple[float | None, ...] | None:
    if not isinstance(raw, list):
        problems.append(f"{name}: expected a list, got {type(raw).__name__}.")
        return None
    out: list[float | None] = []
    bad: list[int] = []
    for index, item in enumerate(raw):
        ok, value = _reading(item)
        if not ok:
            bad.append(index)
        out.append(value)
    if bad:
        shown = ", ".join(str(i) for i in bad[:5]) + (", ..." if len(bad) > 5 else "")
        problems.append(
            f"{name}: {len(bad)} entr{'y is' if len(bad) == 1 else 'ies are'} not null/NaN "
            f"or a finite number in 0..1 (indexes {shown})."
        )
        return None
    return tuple(out)


def _segments(raw: Any, problems: list[str]) -> tuple[Segment, ...] | None:
    if not isinstance(raw, list) or not raw:
        problems.append("segments: expected a non-empty list; an unlabelled trace has no exposure to count.")
        return None
    out: list[Segment] = []
    ok = True
    for index, item in enumerate(raw):
        where = f"segments[{index}]"
        if not isinstance(item, dict):
            problems.append(f"{where}: expected an object, got {type(item).__name__}.")
            ok = False
            continue
        context, count = item.get("context"), item.get("samples")
        if context not in CONTEXTS:
            problems.append(f"{where}.context: {context!r} is not one of {CONTEXTS}.")
            ok = False
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            problems.append(f"{where}.samples: expected an integer >= 1, got {count!r}.")
            ok = False
        if ok and isinstance(context, str) and isinstance(count, int):
            out.append(Segment(context, count))
    if not ok:
        return None
    for before, after in zip(out, out[1:], strict=False):
        if before.context == after.context == DELIBERATE:
            problems.append(
                "segments: two 'deliberate' segments are adjacent, which is indistinguishable "
                "from one longer gesture. Put a non-deliberate segment (the release) between "
                "them, or merge them."
            )
            return None
    return tuple(out)


def validate_trace(doc: Any) -> list[str]:
    """Every problem with one parsed trace document, most structural first. Empty means valid."""
    return _parse(doc)[1]


def check_trace(doc: Any) -> SwitchTrace:
    """Return the typed trace, or raise :class:`SwitchTraceError` listing every problem."""
    trace, problems = _parse(doc)
    if problems or trace is None:
        raise SwitchTraceError(
            f"{len(problems)} face-switch trace problem(s):\n  - " + "\n  - ".join(problems)
        )
    return trace


def _parse(doc: Any) -> tuple[SwitchTrace | None, list[str]]:
    if not isinstance(doc, dict):
        return None, [f"<root>: expected a JSON object, got {type(doc).__name__}."]

    version = doc.get("schema_version")
    if not isinstance(version, str) or _VERSION.fullmatch(version) is None:
        return None, [
            f"schema_version: missing or malformed (got {version!r}); expected "
            f'"MAJOR.MINOR", e.g. "{TRACE_SCHEMA_VERSION}".'
        ]
    major = int(version.split(".")[0])
    if major != SUPPORTED_MAJOR:
        return None, [
            f"schema_version: {version!r} has major version {major}; this reader implements "
            f"{SUPPORTED_MAJOR}.x. A major bump changes or removes a required field, so the "
            f"document cannot be read safely."
        ]

    problems = forbidden_field_problems(doc) + _extra_forbidden(doc) + _time_key_problems(doc)
    for name in REQUIRED_TOP_LEVEL:
        if name not in doc:
            problems.append(f"{name}: missing required field.")

    trace_id = doc.get("trace_id")
    if "trace_id" in doc and not (isinstance(trace_id, str) and _TRACE_ID.fullmatch(trace_id)):
        problems.append(
            f"trace_id: expected a short lowercase slug ([a-z0-9._-], up to 80 characters), got {trace_id!r}."
        )
    mode = doc.get("study_mode")
    if "study_mode" in doc and mode not in STUDY_MODES:
        problems.append(
            f"study_mode: {mode!r} is not one of {STUDY_MODES}. 'research' needs a named "
            f"protocol and consent process this document cannot carry (ADR-v2-150 Rule 2)."
        )
    gesture = doc.get("gesture")
    if "gesture" in doc and gesture not in GESTURES:
        problems.append(f"gesture: {gesture!r} is not one of {tuple(GESTURES)}.")
    rate = doc.get("sample_rate_hz")
    if "sample_rate_hz" in doc and (
        isinstance(rate, bool) or not isinstance(rate, (int, float))
        or not math.isfinite(float(rate))
        or not MIN_SAMPLE_RATE_HZ <= float(rate) <= MAX_SAMPLE_RATE_HZ
    ):
        problems.append(
            f"sample_rate_hz: expected a finite number from {MIN_SAMPLE_RATE_HZ} to "
            f"{MAX_SAMPLE_RATE_HZ} Hz, got {rate!r}."
        )
    description = doc.get("description", "")
    if not isinstance(description, str) or len(description) > MAX_DESCRIPTION:
        problems.append(f"description: expected a string of at most {MAX_DESCRIPTION} characters.")
        description = ""

    baseline_level: float | None = None
    baseline = doc.get("baseline")
    if baseline is not None:
        level = baseline.get("level") if isinstance(baseline, dict) else None
        if (
            not isinstance(baseline, dict) or isinstance(level, bool)
            or not isinstance(level, (int, float)) or not math.isfinite(float(level))
            or not 0.0 <= float(level) <= 1.0
        ):
            problems.append("baseline: expected an object with 'level' a finite number in 0..1.")
        elif "gesture" in baseline and baseline["gesture"] != gesture:
            problems.append(f"baseline.gesture: {baseline['gesture']!r} is not the trace's gesture {gesture!r}.")
        else:
            baseline_level = float(level)

    scores = _column(doc["scores"], "scores", problems) if "scores" in doc else None
    if scores is not None and not scores:
        problems.append("scores: an empty trace is refused -- a rate over zero samples reads as a perfect run.")
        scores = None
    segments = _segments(doc["segments"], problems) if "segments" in doc else None

    confidences: tuple[float | None, ...] | None = None
    if doc.get("confidences") is not None:
        confidences = _column(doc["confidences"], "confidences", problems)
        if confidences is not None and scores is not None and len(confidences) != len(scores):
            problems.append(
                f"confidences: {len(confidences)} entries for {len(scores)} scores; they must "
                f"line up one to one."
            )
            confidences = None

    if segments is not None and scores is not None:
        total = sum(s.samples for s in segments)
        if total != len(scores):
            problems.append(f"segments: the labels cover {total} samples but there are {len(scores)} scores.")

    if problems or scores is None or segments is None:
        return None, problems
    assert isinstance(trace_id, str) and isinstance(mode, str) and isinstance(gesture, str)
    assert isinstance(rate, (int, float))
    return (
        SwitchTrace(
            trace_id=trace_id,
            study_mode=mode,
            gesture=gesture,
            sample_rate_hz=float(rate),
            segments=segments,
            scores=scores,
            confidences=confidences if confidences is not None else (None,) * len(scores),
            baseline_level=baseline_level,
            description=description,
        ),
        problems,
    )
