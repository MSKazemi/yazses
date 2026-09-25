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

`schema_version` is `"MAJOR.MINOR"`.

* **Same MAJOR — accepted.** Unknown fields, at any depth, are *ignored and preserved*,
  never an error. A later minor version may therefore add a field and older readers still
  work; a reader must not assume the keys it knows are all the keys present.
* **Different MAJOR — refused.** A major bump means a required field was removed or its
  meaning changed. Reading it anyway would produce a number that silently means something
  else, which is worse than refusing to read it.

So: add a field, bump the minor. Change or remove one, bump the major.

One reserved name follows from that: inside `metrics`, an object carrying `value` or
`reason` is read as a missing-data marker, never as a metric group. A metric group may
therefore not have a member called `value`.
"""

from __future__ import annotations

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
            if value.get("value") is None and reason not in MISSING_REASONS:
                return [
                    f"{path}{name}: a missing metric needs a reason; set 'reason' to one of "
                    f"{MISSING_REASONS}. Missing is never zero (METRICS.md 'Missing data')."
                ]
            return []
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
    if isinstance(value, (bool, int, float, str, list)):
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
    if not isinstance(version, str) or version.count(".") != 1 or not version.split(".")[0].isdigit():
        return [
            f"schema_version: missing or malformed (got {version!r}); expected "
            f'"MAJOR.MINOR", e.g. "{SCHEMA_VERSION}".'
        ]
    major = int(version.split(".")[0])
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
