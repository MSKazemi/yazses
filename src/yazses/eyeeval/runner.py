"""Run one eye-control evaluation task locally and write a privacy-safe result.

`schema.py` says what a finished result looks like; `tasks.py` says what the tester was
asked to do. This module is the part in the middle -- it turns a task, a set of trial
outcomes and a `Provenance` into a document that has been validated *before* anything
touches the disk, and into a summary a human can read before deciding to share the file.

Nothing here opens a camera, reads a config file, or transmits anything. The host facts
live in `yazses.eyeeval.provenance`; the caller passes them in. That split is what lets
every rule below be tested with a fake task and a fake machine, which is how the privacy
sweep gets a test that can actually fail.

## Four properties this file exists to hold

**Validation happens before the write, not after it.** `write_result` runs the schema
validator *and* the identifier sweep, and raises without creating the file if either
finds anything. A validator that runs after a save is a report on a leak that already
happened; one that never runs is a promise. `design/eye-control/EVALUATION.md` E3 step 10
is "save privacy-safe result JSON", and the adjective is the whole step.

**Only aggregates reach the document.** A per-trial record supplied by a tester is read,
counted and dropped; no record, and no field of one, is ever copied into the result. So
even a hand-edited outcomes file carrying something it should not cannot put it in the
artifact. The record-key allowlist (`check_records`) refuses an unknown field as well,
which catches the typo that would otherwise become a silent zero.

**A count that was not measured is never zero.** Every metric this module can emit is
either a real count or `{"value": null, "reason": ...}`. A blocked run therefore has no
numbers at all rather than a page of zeros, and a synthetic run reports its timings as
`not_measured` because a run with no camera measured no time. `METRICS.md` "Missing data"
is the rule; this is where it is applied.

**A verdict is about the protocol, not about the person.** `PASS` means every scored
trial the task asks for was recorded and none was invalid. It says nothing about whether
gaze routing was accurate, and it deliberately contains no threshold on any rate: a
threshold would be a promotion gate, and `design/eye-control/EVALUATION.md` sets those
from cross-person evidence, not from one QA run. `EVALUATION.md` "Failure reporting" also
says the tester selects the verdict, so a tester-stated verdict overrides the computed
one and both are recorded.

## Study mode is a fact about the collection, not a label

`study_mode` is supplied by the caller and never inferred. `ADR-v2-150` Rule 2: research
mode needs a named protocol identifier, and the schema refuses a `research` document
without one. The CLI additionally refuses to call a synthetic run `community_qa` or a
human-operated one `ci` -- a class is not a thing a run can talk itself into.
"""

from __future__ import annotations

import json
import re
import statistics
from pathlib import Path
from typing import Any

from yazses.eyeeval.provenance import LocalIdentifiers, Provenance, as_sections, fingerprint
from yazses.eyeeval.schema import (
    DATA_CLASS_FOR_MODE,
    MISSING_REASONS,
    SCHEMA_VERSION,
    validate_result,
)
from yazses.eyeeval.tasks import (
    FACE_SWITCH_TASK,
    GAZE_TASK,
    HEAD_POINTER_TASK,
    TASK_FEATURES,
    TASK_IDS,
    TASK_OUTCOMES,
    TASK_RECORDS,
)

#: Stamped into `software.generator` so a reader knows which tool wrote the file. Bumped
#: when the *shape* of what this writes changes, independently of `SCHEMA_VERSION`: two
#: runners can implement the same envelope and still disagree about what they put in it.
GENERATOR = "yazses.eyeeval.runner/1.0"

#: `design/eye-control/EVALUATION.md` "Failure reporting". A closed set, in the order a
#: reader should read them: best, degraded, failed, never ran.
VERDICTS = ("PASS", "PARTIAL", "FAIL", "BLOCKED")

#: Outcomes that mean the trial produced no usable observation -- the tracker dropped out
#: or the tester gave up -- as distinct from a trial that produced a *bad* result. The
#: distinction is the one `METRICS.md` insists on for gaze ("fallback is safer than
#: wrong-target and must not be collapsed into one error"), applied to completeness: a
#: wrong target is data, a lost tracker is not.
UNUSABLE_OUTCOMES: dict[str, tuple[str, ...]] = {
    GAZE_TASK: ("invalid_tracking",),
    HEAD_POINTER_TASK: ("tracking_lost", "abandoned"),
    FACE_SWITCH_TASK: (),
}

#: The nominal-success outcome each task's synthetic dry run records. A dry run proves the
#: pipeline -- task -> records -> metrics -> schema -> privacy sweep -> file -- with no
#: camera; it is not a simulation of a person, and it invents no failures, because a
#: fabricated error rate in an artifact labelled with a study mode is exactly the kind of
#: number that gets quoted later.
_SYNTHETIC_OUTCOME: dict[str, str] = {
    GAZE_TASK: "correct",
    HEAD_POINTER_TASK: "hit",
    FACE_SWITCH_TASK: "detected",
}

#: Where a leak would show up as a *value* rather than as a field name. The schema already
#: refuses a key called `hostname`; these catch the same data arriving inside a string on
#: a machine whose identifiers `local_identifiers()` failed to enumerate.
_LEAK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("a POSIX home directory", re.compile(r"/home/[A-Za-z0-9_.-]+")),
    ("a macOS home directory", re.compile(r"/Users/[A-Za-z0-9_.-]+")),
    ("a Windows profile directory", re.compile(r"[A-Za-z]:\\+Users\\+[A-Za-z0-9_.-]+")),
    ("an email address", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z]{2,}")),
)

#: Shorter than this and a "match" is noise: a two-letter login name occurs inside
#: ordinary words, and a guard that fires on a CPU model teaches people to ignore it
#: (ADR-021). The structural guarantee -- no field exists that could hold an identifier --
#: is the primary defence; this sweep is the second one.
_MIN_IDENTIFIER_LEN = 3


class EyeEvalRunError(RuntimeError):
    """A run could not produce a result, or produced one that must not be written."""


def _missing(reason: str) -> dict[str, Any]:
    """The explicit missing-data marker. Never `0`, never a bare `null`."""
    return {"value": None, "reason": reason}


def _tidy(value: float) -> float | int:
    """A whole number as an `int`. JSON has one number type; a human reading the file does
    not, and `false_activation_count_total: 0.0` reads as a measurement that was rounded."""
    return int(value) if float(value).is_integer() else value


def _median(values: list[float]) -> float | int | None:
    return _tidy(round(float(statistics.median(values)), 1)) if values else None


def _numbers(records: list[dict[str, Any]], key: str) -> list[float]:
    out: list[float] = []
    for record in records:
        value = record.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out.append(float(value))
    return out


def _median_metric(records: list[dict[str, Any]], key: str) -> Any:
    got = _median(_numbers(records, key))
    return _missing("not_measured") if got is None else got


def _sum_metric(records: list[dict[str, Any]], key: str) -> Any:
    """The total of *key* across records, or a missing marker when no record carries it.

    The marker is the point. Summing an absent field gives `0`, and `0 accidental clicks`
    and `nobody counted accidental clicks` are the two readings a safety number must never
    collapse (`METRICS.md` "Missing data").
    """
    values = _numbers(records, key)
    return _missing("not_measured") if not values else _tidy(round(sum(values), 3))


def _rate(numerator: int, denominator: int) -> Any:
    return _missing("not_measured") if denominator <= 0 else round(numerator / denominator, 4)


def _scored(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Records that carry an outcome. A face-switch block summary carries none."""
    return [r for r in records if isinstance(r, dict) and "outcome" in r]


def _outcome_counts(task_id: str, records: list[dict[str, Any]]) -> dict[str, int]:
    scored = _scored(records)
    return {name: sum(1 for r in scored if r.get("outcome") == name) for name in TASK_OUTCOMES[task_id]}


def expected_scored_trials(task: dict[str, Any]) -> int:
    """How many scored trials the task asks for, straight out of the fixture."""
    value = task.get("scored_trials")
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def scored_duration_s(task: dict[str, Any]) -> float | None:
    """Total scored wall-clock the task defines, for a per-hour rate. None when it defines none."""
    total = 0.0
    found = False
    for block in task.get("blocks", []):
        if isinstance(block, dict) and block.get("kind") == "scored":
            duration = block.get("duration_s")
            if isinstance(duration, (int, float)) and not isinstance(duration, bool):
                total += float(duration)
                found = True
    return total if found else None


# --- trial records ------------------------------------------------------------------


def synthetic_records(task: dict[str, Any]) -> list[dict[str, Any]]:
    """Deterministic no-camera trial records for *task*: every scored trial succeeds.

    The outcome is the only thing filled in. No timing is invented, so every timing metric
    comes out as an explicit `not_measured` marker -- which means the dry run exercises the
    missing-data path as well as the counting path, and a reader of the file can see at a
    glance that nothing was timed.
    """
    task_id = str(task.get("task_id"))
    outcome = _SYNTHETIC_OUTCOME[task_id]
    records: list[dict[str, Any]] = []
    for block in task.get("blocks", []):
        if not isinstance(block, dict) or block.get("kind") != "scored":
            continue
        if task_id == FACE_SWITCH_TASK:
            for cue_index in range(len(block.get("cue_times_ms", []))):
                records.append(
                    {
                        "block_id": block["block_id"],
                        "block_type": block["block_type"],
                        "cue_index": cue_index,
                        "outcome": outcome,
                    }
                )
            records.append(
                {
                    "block_id": block["block_id"],
                    "block_type": block["block_type"],
                    "false_activation_count": 0,
                }
            )
            continue
        for trial in block.get("trials", []):
            record: dict[str, Any] = {"trial_index": trial["trial_index"], "outcome": outcome}
            for key in ("intended_target_id", "target_id"):
                if key in trial:
                    record[key] = trial[key]
            records.append(record)
    return records


def check_records(task: dict[str, Any], records: Any) -> list[str]:
    """Every problem with a supplied outcomes file, most structural first.

    The key allowlist is `tasks.TASK_RECORDS`, which is deliberately narrow: there is no
    field in it that could hold desktop text, a frame or who the tester is. Refusing an
    unknown key is therefore a privacy rule as well as a typo check -- and the typo check
    matters on its own, because `miss_cnt` would otherwise be dropped silently and turn an
    unmeasured count into a zero.
    """
    task_id = str(task.get("task_id"))
    if task_id not in TASK_IDS:
        return [f"<task>: unknown task_id {task_id!r}; expected one of {TASK_IDS}."]
    if not isinstance(records, list):
        return [f"<records>: expected a JSON list of trial records, got {type(records).__name__}."]
    allowed = set(TASK_RECORDS[task_id])
    outcomes = TASK_OUTCOMES[task_id]
    problems: list[str] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            problems.append(f"records.{index}: expected an object, got {type(record).__name__}.")
            continue
        for key in record:
            if key not in allowed:
                problems.append(
                    f"records.{index}.{key}: not a field this task records. Allowed: "
                    f"{sorted(allowed)}. An unknown field is refused rather than ignored, "
                    f"so a misspelled count cannot become a silent zero."
                )
        if "outcome" in record and record["outcome"] not in outcomes:
            problems.append(
                f"records.{index}.outcome: {record['outcome']!r} is not one of {outcomes}."
            )
        for key, value in record.items():
            # Only the keys the allowlist accepted: an unknown key has already been
            # reported, and saying it is also not a number is a second line about one
            # mistake. A problem list is read to be acted on, not counted.
            if key not in allowed or key in ("block_id", "block_type", "outcome"):
                continue
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                problems.append(f"records.{index}.{key}: expected a number, got {value!r}.")
    return problems


# --- metrics ------------------------------------------------------------------------


def tally(task: dict[str, Any], records: list[dict[str, Any]], *, blocked_reason: str | None = None) -> dict[str, Any]:
    """The `metrics` block for one run: real counts, or an explicit marker for each.

    `blocked_reason` produces the same key set with every value a missing marker, derived
    from an empty tally rather than from a second hand-written list -- a hand-written set
    beside a generated one drifts, and the drift is invisible until a metric quietly stops
    being reported.
    """
    task_id = str(task.get("task_id"))
    if blocked_reason is not None:
        return {key: _missing(blocked_reason) for key in tally(task, [])}

    scored = _scored(records)
    counts = _outcome_counts(task_id, records)
    metrics: dict[str, Any] = {}
    if task_id == GAZE_TASK:
        metrics["trials"] = len(scored)
        metrics.update(
            {
                "correct_target": counts["correct"],
                "wrong_target": counts["wrong_target"],
                "fallback_no_route": counts["fallback_no_route"],
                "invalid_tracking": counts["invalid_tracking"],
                "correct_target_rate": _rate(counts["correct"], len(scored)),
                "trial_time_ms_p50": _median_metric(records, "trial_time_ms"),
                "calibration_age_s_p50": _median_metric(records, "calibration_age_s"),
            }
        )
    elif task_id == HEAD_POINTER_TASK:
        durations = [
            r["movement_end_ms"] - r["movement_start_ms"]
            for r in records
            if isinstance(r.get("movement_end_ms"), (int, float))
            and isinstance(r.get("movement_start_ms"), (int, float))
        ]
        metrics["trials"] = len(scored)
        metrics.update(
            {
                "hit": counts["hit"],
                "miss": counts["miss"],
                "abandoned": counts["abandoned"],
                "tracking_lost": counts["tracking_lost"],
                "completion_rate": _rate(counts["hit"], len(scored)),
                "movement_time_ms_p50": (
                    _missing("not_measured") if not durations else _median([float(d) for d in durations])
                ),
                "miss_count_total": _sum_metric(records, "miss_count"),
                "recenter_count_total": _sum_metric(records, "recenter_count"),
                "tracking_loss_ms_total": _sum_metric(records, "tracking_loss_ms"),
                "accidental_click_count_total": _sum_metric(records, "accidental_click_count"),
            }
        )
    elif task_id == FACE_SWITCH_TASK:
        duration = scored_duration_s(task)
        false_total = _sum_metric(records, "false_activation_count")
        per_hour: Any = _missing("not_measured")
        if isinstance(false_total, (int, float)) and duration:
            per_hour = _tidy(round(float(false_total) / (duration / 3600.0), 3))
        metrics["cues"] = len(scored)
        metrics.update(
            {
                "detected": counts["detected"],
                "missed": counts["missed"],
                "false_activation": counts["false_activation"],
                "detection_rate": _rate(counts["detected"], len(scored)),
                "activation_latency_ms_p50": _median_metric(records, "activation_latency_ms"),
                "false_activation_count_total": false_total,
                "scored_duration_s": _tidy(duration) if duration is not None else _missing("not_measured"),
                "false_activations_per_hour": per_hour,
            }
        )
    else:  # pragma: no cover - `check_records` refuses an unknown task first
        raise EyeEvalRunError(f"unknown task_id {task_id!r}; expected one of {TASK_IDS}")
    return metrics


def completeness_verdict(
    task: dict[str, Any],
    records: list[dict[str, Any]],
    *,
    blocked_reason: str | None = None,
) -> str:
    """`PASS`/`PARTIAL`/`FAIL`/`BLOCKED` from how much of the protocol actually ran.

    Deliberately threshold-free. Nothing here reads a rate, so this cannot become an
    accidental promotion gate: `design/eye-control/EVALUATION.md` sets those from
    cross-person evidence, and one QA run is not that.
    """
    if blocked_reason is not None:
        return "BLOCKED"
    task_id = str(task.get("task_id"))
    scored = _scored(records)
    if not scored:
        return "FAIL"
    unusable = sum(1 for r in scored if r.get("outcome") in UNUSABLE_OUTCOMES[task_id])
    if unusable == len(scored):
        return "FAIL"
    if unusable or len(scored) != expected_scored_trials(task):
        return "PARTIAL"
    return "PASS"


# --- the document -------------------------------------------------------------------


def safe_settings(raw: dict[str, Any] | None) -> dict[str, Any]:
    """The subset of a feature's settings that is safe to publish, by *value shape*.

    `METRICS.md` asks for "a config hash plus a whitelist of relevant non-sensitive
    feature settings" and says not to dump the whole config. Filtering by shape rather
    than by a list of key names is what keeps this honest as the config grows: a number or
    a flag cannot carry a path, a name or a sentence, and a string is kept only when it
    looks like an enum member. That is what drops `model_path`, which on a real install is
    an absolute path under the user's home directory -- the one setting in these sections
    that would leak, admitted by the rule rather than remembered by a maintainer.
    """
    out: dict[str, Any] = {}
    for key, value in (raw or {}).items():
        if isinstance(value, bool) or isinstance(value, (int, float)):
            out[str(key)] = value
        elif isinstance(value, str) and re.fullmatch(r"[a-z0-9_]{1,32}", value):
            out[str(key)] = value
    return out


def build_result(
    *,
    task: dict[str, Any],
    records: list[dict[str, Any]],
    provenance: Provenance,
    study_mode: str,
    timestamp: str,
    camera_class: str,
    capture_mode: str,
    records_source: str,
    perception_backend: str = "none",
    settings: dict[str, Any] | None = None,
    protocol_id: str | None = None,
    blocked_reason: str | None = None,
    verdict: str | None = None,
) -> dict[str, Any]:
    """Assemble one result document. Pure: no clock, no host, no disk, no validation.

    `timestamp` is passed in rather than read here so a golden test has a fixed document
    to compare against; `verdict` overrides the computed one, because `EVALUATION.md` says
    the tester selects it and a tester who watched the run knows something the counts do
    not.
    """
    task_id = str(task.get("task_id"))
    computed = completeness_verdict(task, records, blocked_reason=blocked_reason)
    stated = verdict or computed
    settings_safe = safe_settings(settings)
    sections = as_sections(provenance)
    return {
        "schema_version": SCHEMA_VERSION,
        "study_mode": study_mode,
        "timestamp": timestamp,
        "software": {
            **sections["software"],
            "perception_backend": {"name": perception_backend, "asset_version": None},
            "generator": GENERATOR,
        },
        "machine": sections["machine"],
        "os_session": sections["os_session"],
        "display": sections["display"],
        "camera": {"camera_class": camera_class, "capture_mode": capture_mode},
        "feature": {"name": TASK_FEATURES.get(task_id, task_id)},
        "config": {"config_hash": fingerprint(settings_safe), "settings": settings_safe},
        "protocol": {
            "task": task_id,
            "task_version": task.get("task_version"),
            "task_seed": task.get("seed"),
            "protocol_id": protocol_id,
        },
        "run": {
            "verdict": stated,
            "completeness_verdict": computed,
            "verdict_source": "tester" if verdict else "computed",
            "verdict_definition": (
                "PASS means every scored trial the task asks for was recorded and none was "
                "invalid. It describes the protocol running to completion, not how "
                "accurately the feature performed; no rate threshold is applied anywhere."
            ),
            "records_source": records_source,
            "scored_trials_expected": expected_scored_trials(task),
            "scored_trials_recorded": len(_scored(records)),
            "blocked_reason": blocked_reason,
        },
        "metrics": tally(task, records, blocked_reason=blocked_reason),
        "privacy": {
            "data_class": DATA_CLASS_FOR_MODE.get(study_mode),
            "raw_media_retained": False,
            "contains_personal_identifiers": False,
            "aggregates_only": True,
        },
    }


# --- the privacy sweep --------------------------------------------------------------


def _walk_strings(node: Any, path: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            out.append((f"{path}{key}", str(key)))
            out += _walk_strings(value, f"{path}{key}.")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            out += _walk_strings(value, f"{path}{index}.")
    elif isinstance(node, str):
        out.append((path.rstrip("."), node))
    return out


def privacy_problems(doc: Any, identifiers: LocalIdentifiers | None = None) -> list[str]:
    """Every place a machine or person identifier reached the document, with its path.

    Two layers. The generic patterns catch a home directory or an email address wherever
    it appears, on any machine. The `identifiers` layer catches this particular host's
    name and login, which no pattern could know.

    The identifier comparison is **case-sensitive**, on purpose. A default cloud or
    container image gives the login name and the distribution the same word -- `ubuntu`,
    `fedora`, `debian` -- and `os_name` legitimately contains the capitalised form. A
    case-insensitive compare would therefore fire on every result produced on such a host,
    and a guard that fires on a correct document is one people learn to pass `--force` to
    (ADR-021). The lowercase form of the same name almost always arrives inside a path,
    which the `/home/<name>` pattern catches regardless of case handling.

    Key names are swept too -- a key *named* after the login would leak just as well as a
    value -- but the `FORBIDDEN_FIELD_TOKENS` rule is not repeated here:
    `schema.forbidden_field_problems` already owns it, and reporting one finding under two
    spellings makes a problem list harder to act on rather than more complete.
    """
    problems: list[str] = []
    ids = identifiers or LocalIdentifiers()
    needles: list[tuple[str, str]] = []
    if len(ids.hostname) >= _MIN_IDENTIFIER_LEN:
        needles.append((ids.hostname, "this machine's hostname"))
    for name in ids.usernames:
        if len(name) >= _MIN_IDENTIFIER_LEN:
            needles.append((name, "this account's login name"))
    for home in ids.home_paths:
        if len(home) >= _MIN_IDENTIFIER_LEN:
            needles.append((home, "this account's home directory"))

    for path, text in _walk_strings(doc, ""):
        for label, pattern in _LEAK_PATTERNS:
            match = pattern.search(text)
            if match:
                problems.append(
                    f"{path}: contains {label} ({match.group(0)!r}). "
                    f"`design/eye-control/DATA_SHARING.md` lists it under 'never required "
                    f"in a public issue'; remove the value, do not rename the field."
                )
        for needle, label in needles:
            if needle in text:
                problems.append(
                    f"{path}: contains {label}. A result is shared in a public issue and "
                    f"public content persists in mirrors and archives, so the value must "
                    f"not be in the file in the first place (ADR-v2-150 Rule 4)."
                )
    return problems


# --- output -------------------------------------------------------------------------


def dump_result(doc: dict[str, Any]) -> str:
    """The canonical on-disk form: 2-space JSON, ASCII, one trailing newline."""
    return json.dumps(doc, indent=2, ensure_ascii=True) + "\n"


def write_result(doc: dict[str, Any], path: Path, *, identifiers: LocalIdentifiers | None = None) -> Path:
    """Validate, then write. Raises `EyeEvalRunError` and writes nothing if anything fails.

    The order is the feature. A validator that runs after the write is a description of a
    file that already exists on disk and may already have been attached to an issue.
    """
    problems = validate_result(doc) + privacy_problems(doc, identifiers)
    if problems:
        raise EyeEvalRunError(
            f"refusing to write {len(problems)} problem(s) to {path}:\n  - "
            + "\n  - ".join(problems)
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_result(doc), encoding="utf-8")
    return path


def summarize(doc: dict[str, Any]) -> str:
    """The human-readable summary printed after a run: verdict plus the key counts."""
    run = doc.get("run", {})
    protocol = doc.get("protocol", {})
    metrics = doc.get("metrics", {})
    mode = str(doc.get("study_mode"))
    lines = [
        f"{protocol.get('task')}  (task version {protocol.get('task_version')})",
        f"  verdict      : {run.get('verdict')}"
        + (f"   [tester-stated; computed {run.get('completeness_verdict')}]"
           if run.get("verdict_source") == "tester" else "   [protocol completeness]"),
    ]
    if run.get("blocked_reason"):
        lines.append(f"  blocked      : {run['blocked_reason']}")
    lines += [
        f"  study mode   : {mode}  (data class {doc.get('privacy', {}).get('data_class')}"
        + ("; not research evidence)" if mode != "research" else ")"),
        f"  scored trials: {run.get('scored_trials_recorded')} recorded of "
        f"{run.get('scored_trials_expected')} asked for  ({run.get('records_source')})",
    ]
    counted = [f"{k}={v}" for k, v in metrics.items() if not isinstance(v, dict)]
    unmeasured = [k for k, v in metrics.items() if isinstance(v, dict)]
    if counted:
        lines.append("  counts       : " + ", ".join(counted))
    if unmeasured:
        lines.append("  not measured : " + ", ".join(unmeasured))
    lines.append(
        "  PASS means the protocol ran to completion, not that the feature was accurate."
    )
    return "\n".join(lines)


def describe_missing_reasons() -> str:
    """The `--blocked` vocabulary, for a CLI error message that names the real options."""
    return ", ".join(MISSING_REASONS)
