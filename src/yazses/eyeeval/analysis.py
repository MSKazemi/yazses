"""Reproducible, descriptive analysis of de-identified eye-control evaluation results (#426).

Reads result documents that already pass `yazses.eyeeval.schema` (the one evaluation format;
this module adds none) and computes the summaries `design/eye-control/PAPER_EVIDENCE.md`
asks for: outcome shares with Wilson intervals, false activations per hour of exposure,
per-participant / per-session grouping, a within-participant session spread (test-retest),
and per-host latency. Pure and stdlib-only: bytes in, a plain dict (or Markdown) out, no
clock, no network, no camera, nothing written. `scripts/analyze_eye_eval.py` is the door.

## What this is not

**Fixtures prove the code, not the product.** The synthetic records in the tests show that
the arithmetic, the refusals and the grouping behave; they say nothing about how well gaze,
head pointer or face switch work, and no threshold or default here was derived from them or
from any single person's data. Every reporting minimum below is a *provisional reporting
floor* (like the 20-attempt floor in `gaze_field`): it stops one-trial "rates" reading as a
finding and is not a power calculation. Every output is labelled `provisional` and carries n.

**No inferential test.** #426 says to build the plumbing first and #425 freezes the analysis
plan. So there is no p-value, no comparison and no model. The Wilson interval is a
*description of one unit's trials* (it treats them as independent Bernoulli draws); it is
never presented as an interval for a population of participants. Across units the report
gives only the count of units and the min / median / max of their rates.

## Rules this holds

* **Refuse, do not repair.** A document that fails `validate_result`, carries a forbidden
  identifier field or a home path / email value, repeats another file's bytes, mixes study
  modes, or has counts that do not add up stops the whole analysis. Nothing is guessed.
* **One study mode per analysis**, `research` by default (ADR-v2-150 Rule 6): a
  `community_qa` row is refused, never silently dropped or pooled.
* **The aggregation unit is explicit** (`run`, `session` or `participant`). The result
  envelope has no participant or session field and must not grow one here, so participant /
  session grouping comes from a separate *links* file (`parse_links`) that maps a result
  file to pseudonymous IDs. A research analysis requires it, because without it pilot rows
  cannot be told from confirmatory ones.
* **Repeated trials are never participants.** `n` always names its unit; the participant
  count, session count, run count, trial count and distinct-host count are reported
  separately. Distinct hosts come from the links file's `host_id` when given; otherwise from
  a fingerprint of the machine / display / camera fields, which is a *lower bound* (two
  identical laptops collide).
* **Wrong target, fallback and lost tracking stay three different things.** No combined
  "error" is ever computed. Technical invalidation (a missing-data reason, `invalid_tracking`,
  `tracking_lost`) is reported as itself, and poor performance is never an exclusion reason.
* **A rate needs its denominator.** Below the minimum n (or minimum exposure) the output is
  the words `insufficient data`, not a number. False activations are events over scored
  exposure hours; no interval is given for them because that needs a model of how events
  cluster, which belongs to #425.
* **Missing is never zero.** A metric marker with a reason is counted under that reason.
* **Latency is never pooled across hosts or configs.** It is listed per stratum, per run.
* **Exclusions are reported with category, reason and whether the rule was predefined.**
  Pilot rows are excluded by default.
* **Deterministic.** Sorted everywhere, no timestamps, file identity is name plus content
  hash, so the same inputs give byte-identical output on every machine.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from dataclasses import dataclass, field
from typing import Any

from yazses.eyeeval.runner import privacy_problems
from yazses.eyeeval.schema import (
    STUDY_MODES,
    _reject_repeated_keys,
    compatibility_note,
    forbidden_field_problems,
    validate_result_text,
)
from yazses.eyeeval.tasks import FACE_SWITCH_TASK, GAZE_TASK, HEAD_POINTER_TASK

ANALYSIS_VERSION = "1.0"
LINKS_VERSION = "1.0"
UNITS = ("run", "session", "participant")

#: Provisional reporting floors -- see the module docstring. Overridable, always printed.
DEFAULT_MIN_TRIALS = 20  # same order as gaze_field's provisional 20-attempt floor
DEFAULT_MIN_UNITS = 5
DEFAULT_MIN_EXPOSURE_S = 600

#: Two-sided 95% standard-normal quantile (constant: no scipy).
Z_95 = 1.959963984540054
INSUFFICIENT = "insufficient data"

#: Per task: where its counts live and which outcome shares are reported. `report` shares
#: share the denominator `denominator` -- all scored trials, or for face switch only the
#: intended cues that were answered (a `false_activation` record answers no cue).
_TASKS: dict[str, dict[str, Any]] = {
    GAZE_TASK: {
        "total": "trials",
        "cats": ("correct_target", "wrong_target", "fallback_no_route", "invalid_tracking"),
        "report": ("correct_target", "wrong_target", "fallback_no_route", "invalid_tracking"),
        "primary": "correct_target",
        "latency": "trial_time_ms_p50",
    },
    HEAD_POINTER_TASK: {
        "total": "trials",
        "cats": ("hit", "miss", "abandoned", "tracking_lost"),
        "report": ("hit", "miss", "abandoned", "tracking_lost"),
        "primary": "hit",
        "latency": "movement_time_ms_p50",
    },
    FACE_SWITCH_TASK: {
        "total": "cues",
        "cats": ("detected", "missed", "false_activation"),
        "report": ("detected", "missed"),
        "primary": "detected",
        "latency": "activation_latency_ms_p50",
        "exposure": ("false_activation_count_total", "scored_duration_s"),
    },
}

#: Missing-data reason -> exclusion category (`METRICS.md` "Exclusions").
_REASON_CATEGORY = {
    "technical_invalidation": "technical",
    "tracking_unavailable": "technical",
    "permission_denied": "technical",
    "not_supported": "technical",
    "participant_stopped": "withdrawal",
    "not_measured": "protocol",
}
EXCLUSION_CATEGORIES = ("technical", "protocol", "withdrawal")

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}")
_CODE = re.compile(r"[a-z0-9_]{1,48}")
_FILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_ROW_KEYS = {"result", "participant_id", "session_id", "pilot", "host_id", "exclusion"}


class EyeAnalysisError(ValueError):
    """The analysis was refused; the message lists every reason, one per line."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__(
            f"{len(problems)} reason(s) the analysis was refused:\n  - " + "\n  - ".join(problems)
        )


# --- statistics ----------------------------------------------------------------------


def wilson_interval(k: int, n: int) -> tuple[float, float]:
    """Two-sided 95% Wilson score interval for k successes in n Bernoulli trials.

    Chosen over Clopper-Pearson because it needs no beta quantile (stdlib only) and has
    better coverage at the small n these studies start with; it is wider-than-nothing at
    k = 0 and k = n, where the normal interval collapses. Descriptive of the n trials given.
    """
    if n <= 0 or k < 0 or k > n:
        raise ValueError(f"wilson_interval needs 0 <= k <= n and n > 0 (got k={k}, n={n}).")
    z2 = Z_95 * Z_95
    p = k / n
    denom = 1.0 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    half = Z_95 * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    # At k = 0 the lower bound is exactly 0 and at k = n the upper exactly 1; floating point
    # leaves a 1e-17 residue that would put the estimate outside its own interval.
    lo = 0.0 if k == 0 else max(0.0, centre - half)
    hi = 1.0 if k == n else min(1.0, centre + half)
    return lo, hi


def _share(k: int, n: int, min_n: int) -> dict[str, Any]:
    base: dict[str, Any] = {"n": n, "provisional": True}
    if n < max(min_n, 1):
        return {**base, "rate": INSUFFICIENT, "minimum_n": min_n}
    lo, hi = wilson_interval(k, n)
    return {**base, "k": k, "rate": round(k / n, 4), "ci95_wilson": [round(lo, 4), round(hi, 4)]}


def _per_hour(events: int, exposure_s: float, min_exposure_s: float) -> dict[str, Any]:
    base: dict[str, Any] = {"exposure_s": _tidy(exposure_s), "provisional": True}
    if exposure_s < max(min_exposure_s, 1e-9):
        return {**base, "per_hour": INSUFFICIENT, "minimum_exposure_s": min_exposure_s}
    return {**base, "events": events, "per_hour": round(events / (exposure_s / 3600.0), 3)}


def _tidy(value: float) -> float | int:
    return int(value) if float(value).is_integer() else round(float(value), 3)


# --- links (participant / session / pilot / exclusion) ------------------------------


def parse_links(text: str) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """``(rows keyed by result file name, problems)`` for a links document.

    The links file is the only place participant and session IDs enter. It is a closed
    shape: any key outside the allowlist is refused, which is also what keeps a name, e-mail
    or GitHub handle from riding along. IDs are short pseudonymous tokens.
    """
    try:
        doc = json.loads(text, object_pairs_hook=_reject_repeated_keys)
    except RecursionError:
        return {}, ["links: nested too deeply."]
    except ValueError as exc:
        return {}, [f"links: not a readable JSON document ({exc})."]
    if not isinstance(doc, dict) or set(doc) != {"links_version", "rows"}:
        return {}, ['links: expected an object with exactly "links_version" and "rows".']
    problems = [f"links.{p}" for p in forbidden_field_problems(doc)]
    problems += [f"links.{p}" for p in privacy_problems(doc)]
    if doc["links_version"] != LINKS_VERSION:
        problems.append(f"links.links_version: expected {LINKS_VERSION!r}, got {doc['links_version']!r}.")
    rows = doc["rows"]
    if not isinstance(rows, list) or not rows:
        return {}, problems + ["links.rows: expected a non-empty list."]
    out: dict[str, dict[str, Any]] = {}
    for i, row in enumerate(rows):
        where = f"links.rows.{i}"
        if not isinstance(row, dict):
            problems.append(f"{where}: expected an object.")
            continue
        for key in sorted(set(row) - _ROW_KEYS):
            problems.append(f"{where}.{key}: not an allowed field (allowed: {sorted(_ROW_KEYS)}).")
        for key in ("result", "participant_id", "session_id", "pilot"):
            if key not in row:
                problems.append(f"{where}.{key}: missing required field.")
        name, pilot = row.get("result"), row.get("pilot")
        if not isinstance(name, str) or not _FILE.fullmatch(name):
            problems.append(f"{where}.result: expected a plain file name.")
        elif name in out:
            problems.append(f"{where}.result: {name!r} is linked twice.")
        for key in ("participant_id", "session_id", "host_id"):
            if key in row and (not isinstance(row[key], str) or not _ID.fullmatch(row[key])):
                problems.append(f"{where}.{key}: expected a short pseudonymous ID ({_ID.pattern}).")
        if "pilot" in row and not isinstance(pilot, bool):
            problems.append(f"{where}.pilot: expected true or false; pilot status is never inferred.")
        excl = row.get("exclusion")
        if excl is not None:
            ok = (
                isinstance(excl, dict)
                and set(excl) == {"category", "reason", "predefined"}
                and excl["category"] in EXCLUSION_CATEGORIES
                and isinstance(excl["reason"], str)
                and _CODE.fullmatch(excl["reason"]) is not None
                and isinstance(excl["predefined"], bool)
            )
            if not ok:
                problems.append(
                    f'{where}.exclusion: expected {{"category": one of {EXCLUSION_CATEGORIES}, '
                    f'"reason": a [a-z0-9_] code, "predefined": true|false}}.'
                )
        if isinstance(name, str):
            out[name] = row
    return out, problems


# --- loading and validation ----------------------------------------------------------


@dataclass
class _Run:
    id: str
    name: str
    doc: dict[str, Any]
    participant: str | None
    session: str | None
    pilot: bool
    link_exclusion: dict[str, Any] | None
    host: str
    host_basis: str
    task: str = ""
    stratum: dict[str, Any] = field(default_factory=dict)
    stratum_id: str = ""
    counts: dict[str, int] | None = None
    total: int = 0
    outcome_missing: str | None = None
    events: int | None = None
    exposure_s: float | None = None
    exposure_missing: str | None = None
    latency: float | None = None
    latency_missing: str | None = None


def _read(metrics: dict[str, Any], key: str) -> tuple[str, Any]:
    """``("ok", number)``, ``("missing", reason)`` or ``("absent", None)`` for one metric."""
    value = metrics.get(key)
    if isinstance(value, dict) and ("value" in value or "reason" in value):
        if value.get("value") is None:
            return "missing", value.get("reason")
        value = value["value"]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "ok", value
    return "absent", None


def _count(metrics: dict[str, Any], key: str, where: str, problems: list[str]) -> tuple[str, Any]:
    state, value = _read(metrics, key)
    if state == "ok" and (float(value) < 0 or not float(value).is_integer()):
        problems.append(f"{where}: metrics.{key} = {value!r} is not a whole, non-negative count.")
        return "absent", None
    return state, int(value) if state == "ok" else value


def _extract(run: _Run, problems: list[str]) -> None:
    """Fill the run's counts, exposure and latency from its metrics, or add problems."""
    spec = _TASKS.get(run.task)
    metrics = run.doc.get("metrics", {})
    if spec is None:
        return
    where = run.id
    keys = (spec["total"], *spec["cats"])
    got = {k: _count(metrics, k, where, problems) for k in keys}
    states = {state for state, _ in got.values()}
    if states == {"ok"}:
        counts = {k: int(got[k][1]) for k in spec["cats"]}
        total = int(got[spec["total"]][1])
        if sum(counts.values()) != total:
            problems.append(
                f"{where}: {spec['total']}={total} but its outcome counts sum to "
                f"{sum(counts.values())}; counts that do not add up are refused, not repaired."
            )
        run.counts, run.total = counts, total
    else:
        reasons = sorted({str(v) for s, v in got.values() if s == "missing"})
        run.outcome_missing = reasons[0] if reasons else "not_measured"
    if "exposure" in spec:
        ev = _count(metrics, spec["exposure"][0], where, problems)
        dv = _read(metrics, spec["exposure"][1])
        if ev[0] == "ok" and dv[0] == "ok" and float(dv[1]) > 0:
            run.events, run.exposure_s = int(ev[1]), float(dv[1])
        else:
            bad = next((s for s in (ev, dv) if s[0] == "missing"), None)
            run.exposure_missing = str(bad[1]) if bad else "not_measured"
    state, value = _read(metrics, spec["latency"])
    if state == "ok":
        run.latency = float(value)
    else:
        run.latency_missing = str(value) if state == "missing" else "not_measured"


def _fingerprint(parts: list[Any] | dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:10]


def _load(
    inputs: list[tuple[str, bytes]],
    links: dict[str, dict[str, Any]] | None,
    study_mode: str,
    problems: list[str],
) -> list[_Run]:
    runs: list[_Run] = []
    seen: dict[str, str] = {}
    modes: dict[str, int] = {}
    for name, raw in sorted(inputs, key=lambda item: (item[0], hashlib.sha256(item[1]).hexdigest())):
        digest = hashlib.sha256(raw).hexdigest()
        run_id = f"{name}@{digest[:12]}"
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            problems.append(f"{run_id}: not UTF-8 text.")
            continue
        found = validate_result_text(text)
        doc: Any = None
        if not found:
            doc = json.loads(text)
            found = privacy_problems(doc)
        if found:
            problems += [f"{run_id}: {p}" for p in found]
            continue
        if digest in seen:
            problems.append(f"{run_id}: identical bytes to {seen[digest]}; a repeated file is not another run.")
            continue
        seen[digest] = run_id
        mode = doc["study_mode"]
        modes[mode] = modes.get(mode, 0) + 1
        link = (links or {}).get(name)
        if links is not None and link is None:
            problems.append(f"{run_id}: not listed in the links file, so its participant and pilot status are unknown.")
            continue
        machine, display, camera = doc["machine"], doc["display"], doc["camera"]
        if link and link.get("host_id"):
            host, basis = str(link["host_id"]), "links host_id"
        else:
            host = "fp-" + _fingerprint([
                machine["arch"], machine["cpu_model"], machine["logical_cpus"], machine["ram_gb"],
                display["topology_fingerprint"], camera["camera_class"],
            ])
            basis = "derived fingerprint (lower bound)"
        run = _Run(
            id=run_id, name=name, doc=doc,
            participant=link["participant_id"] if link else None,
            session=link["session_id"] if link else None,
            pilot=bool(link["pilot"]) if link else False,
            link_exclusion=link.get("exclusion") if link else None,
            host=host, host_basis=basis, task=str(doc["protocol"]["task"]),
        )
        run.stratum = {
            "task": run.task, "task_version": doc["protocol"].get("task_version"),
            "protocol_id": doc["protocol"].get("protocol_id"),
            "os_name": machine["os_name"], "os_version": machine["os_version"],
            "session_type": doc["os_session"]["session_type"],
            "camera_class": camera["camera_class"], "config_hash": doc["config"]["config_hash"],
            "host": host,
        }
        run.stratum_id = _fingerprint(run.stratum)
        _extract(run, problems)
        runs.append(run)
    if len(modes) > 1 or (modes and study_mode not in modes):
        listing = ", ".join(f"{m}={c}" for m, c in sorted(modes.items()))
        extra = " A community_qa row is never pooled into a research analysis (ADR-v2-150 Rule 6)." if "community_qa" in modes else ""
        problems.append(
            f"study modes in the input ({listing}) do not match the requested analysis mode "
            f"{study_mode!r}; one analysis covers one study mode and mixing is refused.{extra}"
        )
    return runs


# --- the analysis --------------------------------------------------------------------


def _decide(run: _Run, include_pilot: bool) -> dict[str, Any] | None:
    """The exclusion that applies to *run*, or None when it is analysed."""
    base = {"run": run.id}
    if run.link_exclusion:
        e = run.link_exclusion
        return {**base, "category": e["category"], "reason": e["reason"],
                "predefined": e["predefined"], "rule": "declared in links file"}
    if run.pilot and not include_pilot:
        return {**base, "category": "pilot", "reason": "pilot", "predefined": True,
                "rule": "PAPER_EVIDENCE.md: pilot rows are excluded from confirmatory output by default"}
    if run.task not in _TASKS:
        return {**base, "category": "protocol", "reason": "unsupported_task", "predefined": True,
                "rule": f"analysis {ANALYSIS_VERSION} summarises {sorted(_TASKS)} only"}
    if run.counts is None and run.events is None:
        reason = run.outcome_missing or "not_measured"
        return {**base, "category": _REASON_CATEGORY.get(reason, "protocol"), "reason": reason,
                "predefined": True, "rule": f"analysis {ANALYSIS_VERSION}: no outcome count was measured"}
    return None


def _group_key(run: _Run, unit: str) -> str:
    if unit == "run":
        return run.id
    if unit == "session":
        return f"{run.participant}/{run.session}"
    return str(run.participant)


def _counts_block(runs: list[_Run]) -> dict[str, Any]:
    trials: dict[str, int] = {}
    for r in runs:
        if r.counts is not None:
            trials[r.task] = trials.get(r.task, 0) + r.total
    linked = [r for r in runs if r.participant is not None]
    return {
        "runs": len(runs),
        "participants": len({r.participant for r in linked}) if linked else "not available (no links file)",
        "sessions": len({(r.participant, r.session) for r in linked}) if linked else "not available (no links file)",
        "trials_by_task": dict(sorted(trials.items())),
        "distinct_hosts": len({r.host for r in runs}),
        "host_identity": sorted({r.host_basis for r in runs}),
    }


def analyze(
    inputs: list[tuple[str, bytes]],
    *,
    unit: str,
    links_text: str | None = None,
    study_mode: str = "research",
    include_pilot: bool = False,
    min_trials: int = DEFAULT_MIN_TRIALS,
    min_units: int = DEFAULT_MIN_UNITS,
    min_exposure_s: float = DEFAULT_MIN_EXPOSURE_S,
) -> dict[str, Any]:
    """The provisional descriptive report for *inputs* (``(file name, bytes)`` pairs).

    Raises `EyeAnalysisError` listing every reason when anything must be refused.
    """
    problems: list[str] = []
    if unit not in UNITS:
        problems.append(f"unit: expected one of {UNITS}; the aggregation unit is never assumed.")
    if study_mode not in STUDY_MODES:
        problems.append(f"study_mode: expected one of {STUDY_MODES}.")
    if not inputs:
        problems.append("no result files were given; an empty analysis would look like a clean one.")
    links: dict[str, dict[str, Any]] | None = None
    if links_text is not None:
        links, found = parse_links(links_text)
        problems += found
    elif unit != "run" or study_mode == "research":
        problems.append(
            "a links file is required for unit 'session' / 'participant' and for any research "
            "analysis: the result envelope carries no participant, session or pilot status, and "
            "guessing them is how trials get counted as participants."
        )
    if problems:
        raise EyeAnalysisError(problems)

    runs = _load(inputs, links, study_mode, problems)
    if links is not None:
        names = {n for n, _ in inputs}
        problems += [f"links: row for {n!r} matches no result file." for n in sorted(set(links) - names)]
    if problems:
        raise EyeAnalysisError(problems)

    exclusions: list[dict[str, Any]] = []
    kept: list[_Run] = []
    for run in runs:
        found_ex = _decide(run, include_pilot)
        (exclusions.append(found_ex) if found_ex else kept.append(run))
    exclusions.sort(key=lambda e: e["run"])

    missing: list[dict[str, str]] = []
    claims: list[dict[str, Any]] = []
    strata: dict[str, list[_Run]] = {}
    for run in kept:
        strata.setdefault(run.stratum_id, []).append(run)
        for family, reason in (("outcomes", run.outcome_missing), ("exposure", run.exposure_missing),
                               ("latency", run.latency_missing)):
            if reason and not (family == "exposure" and "exposure" not in _TASKS[run.task]):
                missing.append({"run": run.id, "family": family, "reason": reason})
    missing.sort(key=lambda m: (m["run"], m["family"]))

    out_strata = [
        _stratum_report(sid, group, unit, min_trials, min_units, min_exposure_s, claims)
        for sid, group in sorted(strata.items())
    ]
    return {
        "analysis_version": ANALYSIS_VERSION,
        "provisional": True,
        "label": (
            "PROVISIONAL, descriptive only: no inferential test (the analysis plan is frozen in "
            "#425); minimums are reporting floors, not power calculations; synthetic fixtures "
            "prove the code, not the product."
        ),
        "study_mode": study_mode,
        "aggregation_unit": unit,
        "pilot_rows": "included (exploratory)" if include_pilot else "excluded",
        "minimums": {"trials": min_trials, "units": min_units, "exposure_s": min_exposure_s,
                     "status": "provisional"},
        "interval": (
            "95% Wilson score interval; describes the unit's own trials as independent "
            "Bernoulli draws, not a population interval. Across units only min / median / max."
        ),
        "schema_notes": sorted({n for r in runs if (n := compatibility_note(r.doc))}),
        "counts": {"loaded": _counts_block(runs), "analysed": _counts_block(kept)},
        "exclusions": exclusions,
        "missing_data": missing,
        "strata": out_strata,
        "claim_manifest": sorted(claims, key=lambda c: c["claim_id"]),
    }


def _stratum_report(
    sid: str, group: list[_Run], unit: str, min_trials: int, min_units: int,
    min_exposure_s: float, claims: list[dict[str, Any]],
) -> dict[str, Any]:
    first = group[0]
    spec = _TASKS[first.task]
    by_unit: dict[str, list[_Run]] = {}
    for run in group:
        by_unit.setdefault(_group_key(run, unit), []).append(run)

    def claim(kind: str, key: str, runs: list[_Run]) -> list[str]:
        ids = sorted(r.id for r in runs)
        claims.append({"claim_id": f"{sid}/{kind}/{key}", "stratum_id": sid, "table": kind,
                       "row": key, "source_runs": ids})
        return ids

    units: list[dict[str, Any]] = []
    for key, members in sorted(by_unit.items()):
        row: dict[str, Any] = {"unit": key, "runs": len(members)}
        measured = [r for r in members if r.counts is not None]
        if measured:
            cats = {c: sum(r.counts[c] for r in measured if r.counts) for c in spec["cats"]}
            denom = sum(cats[c] for c in spec["report"]) if spec["total"] == "cues" else sum(r.total for r in measured)
            row["outcomes"] = {c: _share(cats[c], denom, min_trials) for c in spec["report"]}
            row["source_runs"] = claim("outcomes", key, measured)
        exposed = [r for r in members if r.events is not None and r.exposure_s is not None]
        if "exposure" in spec and exposed:
            row["false_activations"] = _per_hour(
                sum(r.events or 0 for r in exposed), sum(r.exposure_s or 0 for r in exposed), min_exposure_s)
            claim("false_activations", key, exposed)
        units.append(row)

    def spread(values: list[float]) -> dict[str, Any]:
        base: dict[str, Any] = {"units_with_enough_data": len(values), "minimum_units": min_units,
                                "provisional": True}
        if len(values) < max(min_units, 1):
            return {**base, "summary": INSUFFICIENT}
        return {**base, "min": round(min(values), 4), "median": round(statistics.median(values), 4),
                "max": round(max(values), 4)}

    summary: dict[str, Any] = {"units_total": len(units)}
    for cat in spec["report"]:
        vals = [u["outcomes"][cat]["rate"] for u in units
                if "outcomes" in u and isinstance(u["outcomes"][cat]["rate"], float)]
        summary[cat] = spread(vals)
    if "exposure" in spec:
        vals = [u["false_activations"]["per_hour"] for u in units
                if "false_activations" in u and isinstance(u["false_activations"]["per_hour"], float)]
        summary["false_activations_per_hour"] = spread(vals)

    latency_values = sorted(r.latency for r in group if r.latency is not None)
    reasons: dict[str, int] = {}
    for r in group:
        if r.latency_missing:
            reasons[r.latency_missing] = reasons.get(r.latency_missing, 0) + 1
    latency = {
        "metric": spec["latency"], "runs_with_value": len(latency_values),
        "per_run_p50": [_tidy(v) for v in latency_values],
        "missing_by_reason": dict(sorted(reasons.items())),
        "pooling": "never pooled: this list is one host and config only",
    }
    claim("latency", spec["latency"], [r for r in group if r.latency is not None])

    return {
        "stratum_id": sid, "stratum": first.stratum, "unit": unit,
        "primary_outcome": spec["primary"], "units": units, "across_units": summary,
        "latency": latency, "test_retest": _retest(group, spec, min_trials, min_units, claim),
    }


def _retest(group: list[_Run], spec: dict[str, Any], min_trials: int, min_units: int, claim: Any) -> dict[str, Any]:
    """Within-participant spread of the primary outcome rate across sessions (descriptive)."""
    if any(r.participant is None for r in group):
        return {"status": "not available: no links file ties sessions to participants"}
    primary = spec["primary"]
    people: dict[str, dict[str, list[_Run]]] = {}
    for run in group:
        if run.counts is not None:
            people.setdefault(str(run.participant), {}).setdefault(str(run.session), []).append(run)
    rows: list[dict[str, Any]] = []
    for pid, sessions in sorted(people.items()):
        rates: list[dict[str, Any]] = []
        for sid, members in sorted(sessions.items()):
            cats = {c: sum(r.counts[c] for r in members if r.counts) for c in spec["cats"]}
            denom = sum(cats[c] for c in spec["report"]) if spec["total"] == "cues" else sum(r.total for r in members)
            if denom >= max(min_trials, 1):
                rates.append({"session": sid, "n": denom, "rate": round(cats[primary] / denom, 4)})
        if len(rates) >= 2:
            values = [x["rate"] for x in rates]
            rows.append({"participant": pid, "sessions": rates, "spread": round(max(values) - min(values), 4)})
            claim("test_retest", pid, [r for s in sessions.values() for r in s])
    result: dict[str, Any] = {
        "outcome": primary, "provisional": True, "participants_with_two_or_more_sessions": len(rows),
        "minimum_units": min_units, "rows": rows,
        "note": "descriptive spread (max - min) only; no reliability coefficient (a model choice for #425)",
    }
    if len(rows) < max(min_units, 1):
        result["summary"] = INSUFFICIENT
    else:
        spreads = [r["spread"] for r in rows]
        result["summary"] = {"min": min(spreads), "median": round(statistics.median(spreads), 4), "max": max(spreads)}
    return result


# --- rendering -----------------------------------------------------------------------


def dump_report(report: dict[str, Any]) -> str:
    """Canonical JSON: sorted keys, 2-space indent, ASCII, one trailing newline."""
    return json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n"


def _cell(entry: Any) -> str:
    if not isinstance(entry, dict) or "rate" not in entry:
        return "-"
    if entry["rate"] == INSUFFICIENT:
        return f"{INSUFFICIENT} (n={entry['n']}, min {entry['minimum_n']})"
    lo, hi = entry["ci95_wilson"]
    return f"{entry['rate']:.4f} [{lo:.4f}, {hi:.4f}] (n={entry['n']})"


def render_markdown(report: dict[str, Any]) -> str:
    """The same report as Markdown tables. Deterministic; every table says provisional and n."""
    lines = [
        f"# Eye-control evaluation analysis {report['analysis_version']} (PROVISIONAL)", "",
        report["label"], "",
        f"- study mode: `{report['study_mode']}`; aggregation unit: `{report['aggregation_unit']}`; "
        f"pilot rows: {report['pilot_rows']}",
        "- minimums (provisional): " + ", ".join(f"{k}={v}" for k, v in report["minimums"].items()),
        f"- interval: {report['interval']}",
    ]
    lines += [f"- schema note: {n}" for n in report["schema_notes"]]
    for label in ("loaded", "analysed"):
        c = report["counts"][label]
        lines.append(
            f"- {label}: runs={c['runs']}, participants={c['participants']}, sessions={c['sessions']}, "
            f"trials={json.dumps(c['trials_by_task'], sort_keys=True)}, distinct hosts={c['distinct_hosts']} "
            f"({'; '.join(c['host_identity'])})"
        )
    lines += ["", "## Exclusions", ""]
    if report["exclusions"]:
        lines += ["| run | category | reason | predefined | rule |", "|---|---|---|---|---|"]
        lines += [f"| {e['run']} | {e['category']} | {e['reason']} | {e['predefined']} | {e['rule']} |"
                  for e in report["exclusions"]]
    else:
        lines.append("None.")
    lines += ["", "## Missing data (kept with reasons, never zero)", ""]
    lines += ([f"- {m['run']}: {m['family']} -- {m['reason']}" for m in report["missing_data"]]
              or ["None."])
    for s in report["strata"]:
        st = s["stratum"]
        lines += ["", f"## Stratum {s['stratum_id']} -- {st['task']} (provisional)", "",
                  "`" + json.dumps(st, sort_keys=True) + "`", "",
                  f"Per {s['unit']}; a rate below the minimum n prints `{INSUFFICIENT}`.", ""]
        cats = sorted({c for u in s["units"] for c in u.get("outcomes", {})})
        has_fa = any("false_activations" in u for u in s["units"])
        head = ["unit", "runs", *cats, *(["false activations/h"] if has_fa else [])]
        lines += ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
        for u in s["units"]:
            cells = [u["unit"], str(u["runs"]), *[_cell(u.get("outcomes", {}).get(c)) for c in cats]]
            if has_fa:
                fa = u.get("false_activations")
                cells.append("-" if fa is None else (
                    f"{INSUFFICIENT} (exposure {fa['exposure_s']} s, min {fa['minimum_exposure_s']})"
                    if fa["per_hour"] == INSUFFICIENT
                    else f"{fa['per_hour']} ({fa['events']} events / {fa['exposure_s']} s)"))
            lines.append("| " + " | ".join(cells) + " |")
        lines += ["", "Across units (min / median / max of unit rates):", ""]
        for key, val in sorted(s["across_units"].items()):
            if isinstance(val, dict):
                body = (INSUFFICIENT if val.get("summary") == INSUFFICIENT
                        else f"{val['min']} / {val['median']} / {val['max']}")
                lines.append(f"- {key}: {body} (units with enough data n={val['units_with_enough_data']}, "
                             f"minimum {val['minimum_units']})")
        lat = s["latency"]
        lines += ["", f"Latency `{lat['metric']}` (per-run p50 ms, runs n={lat['runs_with_value']}; {lat['pooling']}): "
                      f"{lat['per_run_p50'] or INSUFFICIENT}"]
        rt = s["test_retest"]
        if "status" in rt:
            lines.append(f"Test-retest: {rt['status']}.")
        else:
            lines.append(f"Test-retest `{rt['outcome']}` (provisional): participants with >=2 sessions n="
                         f"{rt['participants_with_two_or_more_sessions']}; spread summary: "
                         f"{rt['summary'] if rt['summary'] == INSUFFICIENT else json.dumps(rt['summary'], sort_keys=True)}")
    lines += ["", "## Claim-to-source manifest", "", "| claim | source runs |", "|---|---|"]
    lines += [f"| {c['claim_id']} | {', '.join(c['source_runs'])} |" for c in report["claim_manifest"]]
    return "\n".join(lines) + "\n"
