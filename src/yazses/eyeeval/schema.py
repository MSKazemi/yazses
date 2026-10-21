"""The versioned eye/camera evaluation result schema, and a pure validator for it.

One number from a gaze run on a Windows laptop and one from a Linux CI runner only mean
the same thing if they arrive in the same envelope. `design/eye-control/METRICS.md` names
that envelope; this module is the machine-readable form of it, and
`design/eye-control/EVALUATION.md` lists "result schema validation" as an E0/E1 check that
runs with no camera attached.

Nothing here touches a camera, a file, a clock or the network. `validate_result` takes a
parsed document and returns a list of problems, so the whole contract is testable as pure
data — which is what lets the runner (#423) and the CI matrix (#424) reuse it unchanged.

Three rules this file exists to enforce, each of which has already gone wrong somewhere:

**Privacy is structural, not a review step.** A field that cannot exist cannot leak. The
envelope has no place to put a hostname, a login name, an email, a serial number, a raw
frame, a transcript or a window title, and `FORBIDDEN_FIELD_TOKENS` fails a document that
invents one at any depth. That is ADR-v2-150 Rule 4 and `DATA_SHARING.md` "never required
in a public issue", checked instead of trusted.

**A missing metric is never zero.** `METRICS.md` is explicit: missing data carries a
reason. A metric that could not be measured is written `{"value": null, "reason": ...}`
with a reason from `MISSING_REASONS`; a bare `null` is refused, because the difference
between "no false activations" and "false activations were not counted" is the whole
safety claim.

**Provenance travels with the number.** The section list mirrors `Provenance` in
`paper/benchmark/_common.py` rather than inventing a second vocabulary: `machine` is that
dataclass's `os`/`kernel`/`cpu_model`/`logical_cpus`/`ram_gb` fields, `software` is its
version block. A benchmark harness already learned that a number without the machine that
produced it is not a measurement; this reuses the lesson instead of relearning it.

## Versioning and compatibility rule

`schema_version` is `"MAJOR.MINOR"`, both parts plain decimal numbers (`parse_schema_version`);
`"1.x"` is malformed, `"1.999"` is a later 1.x.

* **Same MAJOR — accepted.** Unknown fields, at any depth, are *ignored and preserved*,
  never an error. A later minor version may therefore add a field and older readers still
  work; a reader must not assume the keys it knows are all the keys present.
* **Different MAJOR — refused.** A major bump means a required field was removed or its
  meaning changed. Reading it anyway would produce a number that silently means something
  else, which is worse than refusing to read it.

So: add a field, bump the minor. Change or remove one, bump the major.

**Accepted with a note.** A later minor is not an error, but it is not silent either:
`compatibility_note` returns a sentence saying the document was written by a newer minor and
that any field this reader does not know was not checked, and `validate_result_text` /
`scripts/check_eye_eval_result.py` print it. Reading a newer document as though it were the
one you know is how a reader ends up trusting a check it never ran.

One reserved name follows from that: inside `metrics`, an object carrying `value` or
`reason` is read as a missing-data marker, never as a metric group. A metric group may
therefore not have a member called `value`.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

#: The schema version this module implements and writes.
SCHEMA_VERSION = "1.0"
SUPPORTED_MAJOR = 1

#: ADR-v2-150 Rule 1-3. How the data was collected is a fact about the collection, so it
#: travels with the artifact and an analysis script never has to guess.
STUDY_MODES = ("ci", "synthetic", "community_qa", "research")

#: `DATA_SHARING.md` four data classes. Class D (raw face/screen/audio) is deliberately
#: absent: it needs its own ethics decision and storage plan, so it may not be described
#: by this schema at all.
DATA_CLASS_FOR_MODE = {"ci": "A", "synthetic": "A", "community_qa": "B", "research": "C"}

#: The metric groups `METRICS.md` defines. A closed set, so a typo is a failure rather
#: than a new silently-unaggregated feature name.
FEATURES = (
    "gaze",
    "head_pointer",
    "face_switch",
    "semantic_grounding",
    "hands_free_workflow",
)

CAMERA_CLASSES = ("integrated", "external", "virtual", "none")
CAPTURE_MODES = ("live", "synthetic_replay", "none")
SESSION_TYPES = (
    "x11", "wayland_gnome", "wayland_kde", "wayland_other", "windows", "macos", "headless",
)

#: `METRICS.md` "Missing data". Encoding missing as zero is the failure this prevents.
MISSING_REASONS = (
    "not_supported",
    "not_measured",
    "permission_denied",
    "tracking_unavailable",
    "participant_stopped",
    "technical_invalidation",
)

#: Required top-level sections, in the order `METRICS.md` lists the result envelope.
REQUIRED_SECTIONS: dict[str, tuple[str, ...]] = {
    "software": ("yazses_version", "git_commit", "python_version", "perception_backend", "generator"),
    "machine": ("os_name", "os_version", "kernel", "arch", "cpu_model", "logical_cpus", "ram_gb"),
    "os_session": ("session_type",),
    "display": ("display_count", "displays", "topology_fingerprint"),
    "camera": ("camera_class", "capture_mode"),
    "feature": ("name",),
    "config": ("config_hash", "settings"),
    "protocol": ("task", "task_version", "protocol_id"),
    "privacy": ("data_class", "raw_media_retained", "contains_personal_identifiers"),
}
REQUIRED_TOP_LEVEL = ("schema_version", "study_mode", "timestamp", *REQUIRED_SECTIONS, "metrics")

#: Substrings that may not appear in any key name, at any depth. Each is a field the
#: programme has promised never to collect; a document that grows one is rejected rather
#: than reviewed. Tokens are spelled so they cannot match an ordinary word -- `mac_address`
#: rather than `mac`, which would fire on `machine`.
FORBIDDEN_FIELD_TOKENS = (
    "hostname", "host_name", "username", "user_name", "login_name", "real_name",
    "email", "phone", "serial", "mac_address", "ip_address", "device_uuid",
    "raw_frame", "raw_video", "frame_bytes", "face_image", "screenshot", "landmark",
    "transcript", "dictated", "window_title", "home_path", "github",
)


# ASCII digits only and no leading zero: `str.isdigit()` is true for Arabic-Indic and
# superscript digits (some of which `int()` accepts and some of which it raises on), and
# "1.01" would otherwise be a second spelling of "1.1". The length caps keep `int()` far
# from its integer-string limit; no real schema will reach a four-digit major.
_VERSION = re.compile(r"(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,5})")


def parse_schema_version(value: Any) -> tuple[int, int] | None:
    """``"MAJOR.MINOR"`` as two integers, or ``None`` if it is not exactly that. Pure.

    Both halves are checked. The minor is *not* otherwise constrained: by the compatibility
    rule above any minor within a supported major is readable, so ``"1.999"`` parses and
    ``"1.x"`` does not. Shared with ``yazses.eyeeval.tasks`` so the result schema and the
    task fixtures cannot grow two version grammars.
    """
    if not isinstance(value, str):
        return None
    match = _VERSION.fullmatch(value)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def compatibility_note(doc: Any) -> str | None:
    """A sentence when *doc* was written by a later minor of this reader's major, else None.

    Pure and advisory: it never makes a document invalid. ``None`` also covers a document
    whose version is unreadable or of another major -- `validate_result` already refuses
    those, and a note would be a second, weaker message about the same fault.
    """
    parsed = parse_schema_version(doc.get("schema_version")) if isinstance(doc, dict) else None
    ours = parse_schema_version(SCHEMA_VERSION)
    if parsed is None or ours is None or parsed[0] != SUPPORTED_MAJOR or parsed[1] <= ours[1]:
        return None
    return (
        f"schema_version {doc['schema_version']!r} is a later minor than this reader's "
        f"{SCHEMA_VERSION!r}: it is accepted, but any field added since {SCHEMA_VERSION} was "
        f"not checked (see 'Versioning and compatibility rule' in yazses.eyeeval.schema)."
    )


class EyeEvalSchemaError(ValueError):
    """One or more schema violations, listed one per line."""


def _forbidden_keys(node: Any, path: str) -> list[str]:
    out: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            low = str(key).lower()
            for token in FORBIDDEN_FIELD_TOKENS:
                if token in low:
                    out.append(
                        f"{path}{key}: forbidden field -- the name contains {token!r}, which "
                        f"names data the programme promises never to collect "
                        f"(ADR-v2-150 Rule 4). Remove the field; do not rename it."
                    )
            out += _forbidden_keys(value, f"{path}{key}.")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            out += _forbidden_keys(value, f"{path}{i}.")
    return out


def forbidden_field_problems(doc: Any, path: str = "") -> list[str]:
    """Every key, at any depth, whose name contains a `FORBIDDEN_FIELD_TOKENS` entry.

    The same rule applies to anything the programme checks in, not only to a result
    document: a task fixture, an aggregate table or an exported row may not grow a place
    to put a hostname either. Exposed so `yazses.eyeeval.tasks` can reuse this one list
    instead of keeping a second copy that would drift from it.
    """
    return _forbidden_keys(doc, path)


def _check_metric(name: str, value: Any, path: str) -> list[str]:
    """A metric is a scalar, a nested group, a list, or an explicit missing marker."""
    if isinstance(value, dict):
        if "value" in value or "reason" in value:
            reason = value.get("reason")
            inner = value.get("value")
            if inner is None and reason not in MISSING_REASONS:
                return [
                    f"{path}{name}: a missing metric needs a reason; set 'reason' to one of "
                    f"{MISSING_REASONS}. Missing is never zero (METRICS.md 'Missing data')."
                ]
            if inner is not None and reason is not None:
                return [
                    f"{path}{name}: carries both a value and a missing-data reason; a metric "
                    f"is either measured or missing, never both."
                ]
            return _check_metric("value", inner, f"{path}{name}.") if inner is not None else []
        if not value:
            return [
                f"{path}{name}: an empty metric group says nothing; omit it, or write each "
                f"metric it would hold as a value or a missing-data marker."
            ]
        out: list[str] = []
        for key, sub in value.items():
            out += _check_metric(str(key), sub, f"{path}{name}.")
        return out
    if value is None:
        return [
            f"{path}{name}: bare null is not a metric value; write "
            f'{{"value": null, "reason": <one of {MISSING_REASONS}>}} so a reader can tell '
            f"'not measured' from zero."
        ]
    if isinstance(value, float) and not math.isfinite(value):
        return [
            f"{path}{name}: {value!r} is not a measurement, and NaN/Infinity are not valid "
            f"JSON; a metric that could not be computed is a missing-data marker."
        ]
    if isinstance(value, list):
        out = []
        for index, item in enumerate(value):
            out += _check_metric(str(index), item, f"{path}{name}.")
        return out
    if isinstance(value, (bool, int, float, str)):
        return []
    return [f"{path}{name}: unsupported metric type {type(value).__name__}."]


def validate_result(doc: Any) -> list[str]:
    """Return every problem with one parsed result document, most structural first.

    Empty list means valid. Unknown fields are not problems -- see the compatibility rule
    in the module docstring.
    """
    if not isinstance(doc, dict):
        return [f"<root>: expected a JSON object, got {type(doc).__name__}."]

    version = doc.get("schema_version")
    parsed = parse_schema_version(version)
    if parsed is None:
        return [
            f"schema_version: missing or malformed (got {version!r}); expected "
            f'"MAJOR.MINOR" with both parts plain decimal numbers, e.g. "{SCHEMA_VERSION}".'
        ]
    major = parsed[0]
    if major != SUPPORTED_MAJOR:
        return [
            f"schema_version: {version!r} has major version {major}; this reader implements "
            f"{SUPPORTED_MAJOR}.x. A major bump changes or removes a required field, so the "
            f"document cannot be read safely -- use a reader for {major}.x."
        ]

    problems = _forbidden_keys(doc, "")

    for field in REQUIRED_TOP_LEVEL:
        if field not in doc:
            problems.append(f"{field}: missing required field (see design/eye-control/METRICS.md).")
    for section, keys in REQUIRED_SECTIONS.items():
        body = doc.get(section)
        if section not in doc:
            continue
        if not isinstance(body, dict):
            problems.append(f"{section}: expected an object, got {type(body).__name__}.")
            continue
        for key in keys:
            if key not in body:
                problems.append(f"{section}.{key}: missing required field.")

    mode = doc.get("study_mode")
    if "study_mode" in doc and mode not in STUDY_MODES:
        problems.append(f"study_mode: {mode!r} is not one of {STUDY_MODES} (ADR-v2-150).")

    if "timestamp" in doc:
        stamp = doc["timestamp"]
        try:
            if not isinstance(stamp, str):
                raise ValueError(stamp)
            datetime.fromisoformat(stamp)
        except ValueError:
            problems.append(
                f"timestamp: expected an ISO-8601 string such as "
                f'"2026-09-25T10:14:02+00:00", got {stamp!r}.'
            )

    display = doc.get("display")
    if isinstance(display, dict) and "displays" in display and "display_count" in display:
        shown, count = display["displays"], display["display_count"]
        if not isinstance(shown, list):
            problems.append("display.displays: expected a list of displays.")
        elif isinstance(count, bool) or count != len(shown):
            problems.append(
                f"display.display_count: {count!r} does not match the {len(shown)} display(s) "
                f"listed; a topology that disagrees with itself cannot be compared across machines."
            )

    feature = doc.get("feature")
    if isinstance(feature, dict) and "name" in feature and feature["name"] not in FEATURES:
        problems.append(f"feature.name: {feature['name']!r} is not one of {FEATURES}.")

    camera = doc.get("camera")
    if isinstance(camera, dict):
        if "camera_class" in camera and camera["camera_class"] not in CAMERA_CLASSES:
            problems.append(f"camera.camera_class: expected one of {CAMERA_CLASSES}.")
        if "capture_mode" in camera and camera["capture_mode"] not in CAPTURE_MODES:
            problems.append(f"camera.capture_mode: expected one of {CAPTURE_MODES}.")

    session = doc.get("os_session")
    if isinstance(session, dict) and "session_type" in session:
        if session["session_type"] not in SESSION_TYPES:
            problems.append(f"os_session.session_type: expected one of {SESSION_TYPES}.")

    privacy = doc.get("privacy")
    if isinstance(privacy, dict):
        expected = DATA_CLASS_FOR_MODE.get(str(mode))
        if "data_class" in privacy and expected and privacy["data_class"] != expected:
            problems.append(
                f"privacy.data_class: study_mode {mode!r} is class {expected!r}, not "
                f"{privacy['data_class']!r}. The class is a fact about how the data was "
                f"collected, not a later choice (ADR-v2-150 Rule 6)."
            )
        for flag in ("raw_media_retained", "contains_personal_identifiers"):
            if flag in privacy and privacy[flag] is not False:
                problems.append(
                    f"privacy.{flag}: must be false. This schema describes derived metrics "
                    f"only; raw sensor data and identifiers need their own ethics decision "
                    f"(ADR-v2-150 Rule 4)."
                )

    protocol = doc.get("protocol")
    if mode == "research" and isinstance(protocol, dict) and not protocol.get("protocol_id"):
        problems.append(
            "protocol.protocol_id: study_mode 'research' requires a named, versioned "
            "protocol identifier. Relabelling an artifact after collection is not consent "
            "(ADR-v2-150 Rule 2)."
        )

    metrics = doc.get("metrics")
    if "metrics" in doc:
        if not isinstance(metrics, dict) or not metrics:
            problems.append("metrics: expected a non-empty object of metric name -> value.")
        else:
            for name, value in metrics.items():
                problems += _check_metric(str(name), value, "metrics.")

    return problems


def check_result(doc: Any) -> None:
    """Raise `EyeEvalSchemaError` listing every problem, or return None if valid."""
    problems = validate_result(doc)
    if problems:
        raise EyeEvalSchemaError(
            f"{len(problems)} eye-control evaluation schema problem(s):\n  - "
            + "\n  - ".join(problems)
        )


# --- reading a result from disk -------------------------------------------------------
#
# `validate_result` takes a parsed document, which is the right unit for a test. A checker
# pointed at a *file* has a failure the parsed document never sees: the file may be missing,
# empty, not UTF-8, not JSON, or JSON that Python parses more kindly than any other reader
# (`NaN`, a repeated key whose last copy silently wins). Each of those must be a reported
# problem. None may become `{}` or `None` and fall through to a check that passes.


class _UnreadableResult(ValueError):
    """Internal: the text is not a JSON document this schema could be applied to."""


def _reject_repeated_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise _UnreadableResult(
                f"the key {key!r} appears twice in one object; the last copy would silently "
                f"win and the first would never be checked."
            )
        seen[key] = value
    return seen


def _reject_constant(name: str) -> Any:
    raise _UnreadableResult(
        f"{name} is not valid JSON; a metric that could not be computed is a "
        f'{{"value": null, "reason": ...}} marker.'
    )


def parse_result_text(text: str) -> tuple[Any, list[str]]:
    """``(document, [])`` for readable JSON text, or ``(None, problems)`` when it is not.

    Total: it returns for any string, including an empty or garbled one. Shared by every
    reader of a result *file* -- `validate_result_text` here, and a task-specific checker
    such as `yazses.eyeeval.gaze_field.report_problems_text` -- so "unreadable" has one
    meaning and no second parser can be kinder about ``NaN`` or a repeated key.
    """
    if not text.strip():
        return None, ["<file>: empty; a result document must be a JSON object."]
    try:
        doc = json.loads(
            text, object_pairs_hook=_reject_repeated_keys, parse_constant=_reject_constant
        )
    except _UnreadableResult as exc:
        return None, [f"<file>: {exc}"]
    except RecursionError:
        return None, ["<file>: nested too deeply to be a result document."]
    except ValueError as exc:  # JSONDecodeError, or an integer past the interpreter's limit
        return None, [f"<file>: not valid JSON ({exc})."]
    return doc, []


def read_result_file(path: str | Path) -> tuple[Any, list[str]]:
    """``(document, [])`` for the file at *path*, or ``(None, problems)`` if unreadable."""
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        return None, [f"<file>: cannot be read ({exc.strerror or exc})."]
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None, ["<file>: not UTF-8 text."]
    return parse_result_text(text)


def validate_result_text(text: str) -> list[str]:
    """Problems with one result document given as JSON text. Empty list means valid.

    Total: it returns a list for any string, including an empty or garbled one.
    """
    doc, problems = parse_result_text(text)
    if problems:
        return problems
    try:
        return validate_result(doc)
    except RecursionError:
        return ["<file>: nested too deeply to be a result document."]


def validate_result_file(path: str | Path) -> list[str]:
    """Problems with the result document at *path*; an unreadable file is a problem."""
    doc, problems = read_result_file(path)
    if problems:
        return problems
    try:
        return validate_result(doc)
    except RecursionError:
        return ["<file>: nested too deeply to be a result document."]
