"""The privacy-safe grounding trace document: a versioned schema and a pure validator.

Phase P4 of ``design/specs/eye-grounded-targets.md`` (ADR-v2-151) replays
target/candidate/intent fixtures and reports grounded-correct, wrong-target, ambiguity
and abstention. This module is the *input* half of that: the envelope one replayable
trial arrives in, and a validator that turns a parsed document into the typed vocabulary
of ``src/yazses/grounding/contracts.py`` or into a list of problems.

The evaluator itself is ``src/yazses/grounding/replay.py``; the command-line front end is
``scripts/replay_grounding_trace.py``.

## What a trace may contain, and what it structurally cannot

A trace holds only what phase P0 already declared a value type: a coarse target (a
modality, a timestamp, a confidence, geometry in a named coordinate space), the
structured candidates a semantic source reported, the parsed intent hint, and the
ground-truth entity id. There is no place to put a screenshot, a camera frame, an
accessibility node, a window title or a transcript, and
:func:`~yazses.eyeeval.schema.forbidden_field_problems` refuses a document that invents
a key for one at any depth. That is the same list ``src/yazses/eyeeval/schema.py``
already enforces on result documents, imported rather than copied: a second list would
drift from the first, and the promise is one promise.

``study_mode`` is restricted to the two ``DATA_SHARING.md`` class-A modes. A trace is
checked into the repository and read by CI, so a mode that implies human-subject or
community data may not describe one.

Labels are permitted, because a hint like "click Save" needs something to match, and the
spec's privacy rule is that fixtures use invented labels. **No label is ever copied into
a report** — see the evaluator.

## Why an empty trace is an error rather than an empty report

A reporter that iterates is trivially green on a collection with nothing in it, and a
wrong-target rate of ``0.0`` computed over zero trials reads exactly like a perfect run.
So ``cases`` must be a non-empty list, a case must exist, and a trace that has none is a
*rule violation* — the same decision ``scripts/check_eye_validation_slots.py`` makes
about a registry with zero slots, and the same exit code.

For the same reason ``expected_entity_id`` must be **present** on every case even when it
is ``null``. ``null`` is the positive statement "no element is the right answer here, and
grounding anything would be a wrong target"; a missing key would be a typo that silently
became that statement.

## Versioning

``schema_version`` is ``"MAJOR.MINOR"`` and follows the rule
``src/yazses/eyeeval/schema.py`` sets: the same major is accepted and unknown fields at
any depth are ignored, a different major is refused rather than half-read.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, TypeVar

from yazses.eyeeval.schema import forbidden_field_problems
from yazses.grounding.contracts import (
    CoordinateSpace,
    IntentHint,
    Point,
    Rect,
    SemanticCandidate,
    SemanticSourceKind,
    TargetSnapshot,
    TargetSource,
)

#: The trace schema version this module implements and that the fixtures declare.
TRACE_SCHEMA_VERSION = "1.0"
SUPPORTED_MAJOR = 1

#: ``DATA_SHARING.md`` class A only. A checked-in trace describes invented geometry, so
#: it can never be a community or research artifact, and saying otherwise in the one
#: field that governs handling would be the relabelling ADR-v2-150 Rule 2 forbids.
STUDY_MODES = ("synthetic", "ci")

REQUIRED_TOP_LEVEL = ("schema_version", "trace_id", "study_mode", "space", "cases")
REQUIRED_CASE_KEYS = ("case_id", "now_s", "target", "candidates", "expected_entity_id")

#: Bound to the enum being read so a caller gets the member type back, not ``Any``.
_EnumT = TypeVar("_EnumT", bound=Enum)


class GroundingTraceError(ValueError):
    """One or more trace-schema violations, listed one per line."""


@dataclass(frozen=True)
class TraceCase:
    """One replayable trial: what the user pointed at, what was there, what they said.

    ``now_s`` is carried per case because the resolver reads no clock — it is a required
    keyword on ``TargetResolver.resolve`` — so the moment of resolution is part of the
    recorded trial rather than something the harness invents at replay time. That is what
    makes a stale-target case reproduce identically on any machine.

    ``expected_entity_id`` is the ground truth. ``None`` means abstention is the correct
    answer; see the module docstring.
    """

    case_id: str
    trace_id: str
    now_s: float
    target: TargetSnapshot
    candidates: tuple[SemanticCandidate, ...]
    hint: IntentHint | None
    expected_entity_id: str | None
    description: str = ""

    def candidate_by_id(self, entity_id: str) -> SemanticCandidate | None:
        for candidate in self.candidates:
            if candidate.entity_id == entity_id:
                return candidate
        return None


@dataclass(frozen=True)
class TraceDocument:
    """One validated trace file: an id, its provenance fields and its non-empty cases."""

    trace_id: str
    study_mode: str
    cases: tuple[TraceCase, ...]
    description: str = ""


# --------------------------------------------------------------------------- #
# Small typed readers. Each appends a problem and returns ``None`` rather than
# raising, so one malformed field does not hide the other nine.
# --------------------------------------------------------------------------- #
def _number(raw: Any, path: str, problems: list[str]) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        problems.append(f"{path}: expected a number, got {type(raw).__name__}.")
        return None
    if not math.isfinite(float(raw)):
        problems.append(f"{path}: expected a finite number, got {raw!r}.")
        return None
    return float(raw)


def _text(raw: Any, path: str, problems: list[str]) -> str | None:
    if not isinstance(raw, str) or not raw:
        problems.append(f"{path}: expected a non-empty string, got {raw!r}.")
        return None
    return raw


def _mapping(raw: Any, path: str, problems: list[str]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        problems.append(f"{path}: expected an object, got {type(raw).__name__}.")
        return None
    return raw


def _space(raw: Any, path: str, problems: list[str]) -> CoordinateSpace | None:
    body = _mapping(raw, path, problems)
    if body is None:
        return None
    label = _text(body.get("name"), f"{path}.name", problems)
    version = body.get("version", 0)
    if isinstance(version, bool) or not isinstance(version, int):
        problems.append(f"{path}.version: expected an integer, got {version!r}.")
        return None
    if label is None:
        return None
    try:
        return CoordinateSpace(label, version)
    except ValueError as exc:
        problems.append(f"{path}: {exc}")
        return None


def _point(raw: Any, path: str, problems: list[str]) -> Point | None:
    body = _mapping(raw, path, problems)
    if body is None:
        return None
    x = _number(body.get("x"), f"{path}.x", problems)
    y = _number(body.get("y"), f"{path}.y", problems)
    if x is None or y is None:
        return None
    try:
        return Point(x, y)
    except ValueError as exc:
        problems.append(f"{path}: {exc}")
        return None


def _rect(raw: Any, path: str, problems: list[str]) -> Rect | None:
    body = _mapping(raw, path, problems)
    if body is None:
        return None
    x = _number(body.get("x"), f"{path}.x", problems)
    y = _number(body.get("y"), f"{path}.y", problems)
    width = _number(body.get("width"), f"{path}.width", problems)
    height = _number(body.get("height"), f"{path}.height", problems)
    if x is None or y is None or width is None or height is None:
        return None
    try:
        return Rect(x, y, width, height)
    except ValueError as exc:
        problems.append(f"{path}: {exc}")
        return None


def _enum_member(
    raw: Any, path: str, problems: list[str], members: type[_EnumT]
) -> _EnumT | None:
    if not isinstance(raw, str):
        problems.append(f"{path}: expected a string, got {type(raw).__name__}.")
        return None
    try:
        return members(raw)
    except ValueError:
        allowed = tuple(member.value for member in members)
        problems.append(f"{path}: {raw!r} is not one of {allowed}.")
        return None


def _target(
    raw: Any, path: str, default_space: CoordinateSpace | None, problems: list[str]
) -> TargetSnapshot | None:
    body = _mapping(raw, path, problems)
    if body is None:
        return None
    modality = _enum_member(body.get("source"), f"{path}.source", problems, TargetSource)
    timestamp = _number(body.get("timestamp_s"), f"{path}.timestamp_s", problems)
    certainty = _number(body.get("confidence"), f"{path}.confidence", problems)
    space = (
        _space(body["space"], f"{path}.space", problems)
        if body.get("space") is not None
        else default_space
    )
    point = (
        _point(body["point"], f"{path}.point", problems)
        if body.get("point") is not None
        else None
    )
    bounds = (
        _rect(body["bounds"], f"{path}.bounds", problems)
        if body.get("bounds") is not None
        else None
    )
    window = body.get("window_id")
    if window is not None and not isinstance(window, str):
        problems.append(f"{path}.window_id: expected a string or null, got {window!r}.")
        return None
    if modality is None or timestamp is None or certainty is None:
        return None
    try:
        return TargetSnapshot(
            source=modality,
            timestamp_s=timestamp,
            confidence=certainty,
            space=space,
            point=point,
            bounds=bounds,
            window_id=window,
        )
    except ValueError as exc:
        problems.append(f"{path}: {exc}")
        return None


def _candidate(
    raw: Any, path: str, default_space: CoordinateSpace | None, problems: list[str]
) -> SemanticCandidate | None:
    body = _mapping(raw, path, problems)
    if body is None:
        return None
    kind = _enum_member(
        body.get("source"), f"{path}.source", problems, SemanticSourceKind
    )
    entity_id = _text(body.get("entity_id"), f"{path}.entity_id", problems)
    role = _text(body.get("role"), f"{path}.role", problems)
    captured = _number(body.get("captured_at_s"), f"{path}.captured_at_s", problems)
    certainty = _number(body.get("confidence"), f"{path}.confidence", problems)
    space = (
        _space(body["space"], f"{path}.space", problems)
        if body.get("space") is not None
        else default_space
    )
    bounds = (
        _rect(body["bounds"], f"{path}.bounds", problems)
        if body.get("bounds") is not None
        else None
    )
    label = body.get("label")
    if label is not None and not isinstance(label, str):
        problems.append(f"{path}.label: expected a string or null, got {label!r}.")
        return None
    raw_actions = body.get("actions", [])
    if not isinstance(raw_actions, list) or not all(
        isinstance(item, str) for item in raw_actions
    ):
        problems.append(f"{path}.actions: expected a list of strings.")
        return None
    if kind is None or entity_id is None or role is None:
        return None
    if captured is None or certainty is None:
        return None
    try:
        return SemanticCandidate(
            source=kind,
            entity_id=entity_id,
            role=role,
            captured_at_s=captured,
            confidence=certainty,
            space=space,
            bounds=bounds,
            label=label,
            actions=tuple(raw_actions),
        )
    except ValueError as exc:
        problems.append(f"{path}: {exc}")
        return None


def _hint(raw: Any, path: str, problems: list[str]) -> IntentHint | None:
    body = _mapping(raw, path, problems)
    if body is None:
        return None
    tokens = body.get("label_tokens", [])
    if not isinstance(tokens, list) or not all(
        isinstance(item, str) for item in tokens
    ):
        problems.append(f"{path}.label_tokens: expected a list of strings.")
        return None
    for key in ("verb", "role"):
        value = body.get(key)
        if value is not None and not isinstance(value, str):
            problems.append(f"{path}.{key}: expected a string or null, got {value!r}.")
            return None
    try:
        return IntentHint(
            verb=body.get("verb"),
            role=body.get("role"),
            label_tokens=tuple(tokens),
        )
    except ValueError as exc:
        problems.append(f"{path}: {exc}")
        return None


def _case(
    raw: Any,
    index: int,
    trace_id: str,
    default_space: CoordinateSpace | None,
    problems: list[str],
) -> TraceCase | None:
    path = f"cases[{index}]"
    body = _mapping(raw, path, problems)
    if body is None:
        return None
    for key in REQUIRED_CASE_KEYS:
        if key not in body:
            problems.append(
                f"{path}.{key}: missing required field. 'expected_entity_id' must be "
                f"written explicitly, as null when abstention is the correct answer — a "
                f"missing key is a typo that would silently become that claim."
            )
    case_id = _text(body.get("case_id"), f"{path}.case_id", problems)
    now_s = _number(body.get("now_s"), f"{path}.now_s", problems)
    target = _target(body.get("target"), f"{path}.target", default_space, problems)

    raw_candidates = body.get("candidates")
    candidates: list[SemanticCandidate] = []
    if not isinstance(raw_candidates, list):
        problems.append(f"{path}.candidates: expected a list (possibly empty).")
        raw_candidates = []
    for position, entry in enumerate(raw_candidates):
        built = _candidate(
            entry, f"{path}.candidates[{position}]", default_space, problems
        )
        if built is not None:
            candidates.append(built)

    hint = (
        _hint(body["hint"], f"{path}.hint", problems)
        if body.get("hint") is not None
        else None
    )

    expected = body.get("expected_entity_id")
    if expected is not None and not isinstance(expected, str):
        problems.append(
            f"{path}.expected_entity_id: expected a string or null, got {expected!r}."
        )
        expected = None
    elif isinstance(expected, str):
        if not any(item.entity_id == expected for item in candidates):
            problems.append(
                f"{path}.expected_entity_id: {expected!r} names no candidate in this "
                f"case, so the case can never be scored correct. Name a candidate, or "
                f"write null to state that abstention is the correct answer."
            )

    description = body.get("description", "")
    if not isinstance(description, str):
        problems.append(f"{path}.description: expected a string.")
        description = ""

    if case_id is None or now_s is None or target is None:
        return None
    return TraceCase(
        case_id=case_id,
        trace_id=trace_id,
        now_s=now_s,
        target=target,
        candidates=tuple(candidates),
        hint=hint,
        expected_entity_id=expected if isinstance(expected, str) else None,
        description=description,
    )


def _build(doc: Any) -> tuple[TraceDocument | None, list[str]]:
    """The single construction path: validation and loading are the same code.

    Two separate walks — one that checks and one that builds — drift, and the drift is
    invisible because both keep passing. So :func:`validate_trace` and
    :func:`load_trace` are two thin readings of this one result.
    """
    problems: list[str] = []
    if not isinstance(doc, dict):
        return None, [f"<root>: expected a JSON object, got {type(doc).__name__}."]

    version = doc.get("schema_version")
    if (
        not isinstance(version, str)
        or version.count(".") != 1
        or not version.split(".")[0].isdigit()
    ):
        return None, [
            f"schema_version: missing or malformed (got {version!r}); expected "
            f'"MAJOR.MINOR", e.g. "{TRACE_SCHEMA_VERSION}".'
        ]
    major = int(version.split(".")[0])
    if major != SUPPORTED_MAJOR:
        return None, [
            f"schema_version: {version!r} has major version {major}; this reader "
            f"implements {SUPPORTED_MAJOR}.x. A major bump changes or removes a required "
            f"field, so the trace cannot be replayed safely."
        ]

    problems += forbidden_field_problems(doc)

    for key in REQUIRED_TOP_LEVEL:
        if key not in doc:
            problems.append(f"{key}: missing required field.")

    trace_id = _text(doc.get("trace_id"), "trace_id", problems) or ""
    mode = doc.get("study_mode")
    if "study_mode" in doc and mode not in STUDY_MODES:
        problems.append(
            f"study_mode: {mode!r} is not one of {STUDY_MODES}. A checked-in trace is "
            f"invented geometry, so it may not describe itself as community or research "
            f"data (ADR-v2-150 Rule 2)."
        )
    default_space = (
        _space(doc["space"], "space", problems) if doc.get("space") is not None else None
    )
    if default_space is None and "space" in doc:
        problems.append(
            "space: a trace must name the coordinate space its geometry is expressed in; "
            "a point with no space is a number that looks comparable and is not."
        )

    raw_cases = doc.get("cases")
    if not isinstance(raw_cases, list):
        if "cases" in doc:
            problems.append(f"cases: expected a list, got {type(raw_cases).__name__}.")
        raw_cases = []
    elif not raw_cases:
        problems.append(
            "cases: a trace must contain at least one case. An evaluator that iterates "
            "is green on an empty trace, and a wrong-target rate computed over zero "
            "trials reads exactly like a perfect run."
        )

    cases: list[TraceCase] = []
    seen: set[str] = set()
    for index, entry in enumerate(raw_cases):
        built = _case(entry, index, trace_id, default_space, problems)
        if built is None:
            continue
        if built.case_id in seen:
            problems.append(f"cases[{index}].case_id: {built.case_id!r} is a duplicate.")
        seen.add(built.case_id)
        cases.append(built)

    description = doc.get("description", "")
    if not isinstance(description, str):
        problems.append("description: expected a string.")
        description = ""

    if problems:
        return None, problems
    return (
        TraceDocument(
            trace_id=trace_id,
            study_mode=str(mode),
            cases=tuple(cases),
            description=description,
        ),
        [],
    )


def validate_trace(doc: Any) -> list[str]:
    """Every problem with one parsed trace document. An empty list means valid."""
    return _build(doc)[1]


def check_trace(doc: Any) -> TraceDocument:
    """Return the typed trace, or raise :class:`GroundingTraceError` listing every problem."""
    built, problems = _build(doc)
    if built is None:
        raise GroundingTraceError(
            f"{len(problems)} grounding trace problem(s):\n  - " + "\n  - ".join(problems)
        )
    return built
