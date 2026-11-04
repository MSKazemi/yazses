"""Offline, synthetic-only paired transcript-filter evaluation for research #255.

This is NOT a speech/participant benchmark. It compares one fixed input string
with filtering off and on, using manually authored synthetic oracle labels.
Reports contain aggregates, never input strings or per-case transcript hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Callable

SCHEMA_VERSION = 1
MAX_INPUT_BYTES = 1_000_000
MAX_CASES = 1_000
MAX_TEXT_LENGTH = 2_500
STRATA = frozenset({
    "fluent", "word_repetition", "sound_repetition", "prolongation", "block", "interjection",
})
ORACLE_LABELS = frozenset({
    "destructive-content", "destructive-correction", "destructive-structure",
    "benign-retention", "safe-cleanup", "no-material-edit", "unassessable-disputed",
})
STATUSES = frozenset({"confirmed", "disputed", "pending"})
_CASE_KEYS = frozenset({
    "id", "stratum", "asr_text", "verbatim_reference", "semantic_reference",
    "expected_on", "oracle_label", "oracle_status",
})
_ID_PATTERN = re.compile(r"SYN-[A-Z0-9_-]{1,48}\Z")


class EvaluationInputError(ValueError):
    """Safe validation error; messages never include transcript contents."""


def _string(value: object, *, ordinal: int, field: str) -> str:
    if not isinstance(value, str) or len(value) > MAX_TEXT_LENGTH:
        raise EvaluationInputError(f"case {ordinal}: {field} must be a bounded string")
    return value


def _validated_cases(payload: object) -> list[dict[str, str]]:
    if not isinstance(payload, dict):
        raise EvaluationInputError("root must be an object")
    if set(payload) != {"schema_version", "fixture_scope", "cases"}:
        raise EvaluationInputError("root keys must be schema_version, fixture_scope, cases")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != SCHEMA_VERSION:
        raise EvaluationInputError("unsupported schema_version")
    if payload["fixture_scope"] != "synthetic":
        raise EvaluationInputError("synthetic fixtures only; real speech is not accepted")
    cases = payload["cases"]
    if not isinstance(cases, list) or not 1 <= len(cases) <= MAX_CASES:
        raise EvaluationInputError("cases must be a nonempty bounded array")
    checked: list[dict[str, str]] = []
    ids: set[str] = set()
    for ordinal, case in enumerate(cases, start=1):
        if not isinstance(case, dict) or set(case) != _CASE_KEYS:
            raise EvaluationInputError(f"case {ordinal}: incorrect keys")
        fields = {k: _string(case[k], ordinal=ordinal, field=k) for k in _CASE_KEYS}
        case_id = fields["id"]
        if not _ID_PATTERN.fullmatch(case_id) or case_id in ids:
            raise EvaluationInputError(f"case {ordinal}: invalid or duplicate synthetic id")
        ids.add(case_id)
        if fields["stratum"] not in STRATA:
            raise EvaluationInputError(f"case {ordinal}: invalid stratum")
        if fields["oracle_label"] not in ORACLE_LABELS:
            raise EvaluationInputError(f"case {ordinal}: invalid oracle_label")
        if fields["oracle_status"] not in STATUSES:
            raise EvaluationInputError(f"case {ordinal}: invalid oracle_status")
        checked.append(fields)
    return checked


def _word_errors(reference: str, actual: str) -> tuple[int, int]:
    """Word edit distance and reference-token count; whitespace/casefold only.

    No punctuation stripping or other cleanup: the numerator must not conceal
    changes the filter made. Not an established externally comparable WER policy.
    """
    ref = reference.casefold().split()
    hyp = actual.casefold().split()
    previous = list(range(len(hyp) + 1))
    for index, word in enumerate(ref, start=1):
        current = [index]
        for j, hypothesis in enumerate(hyp, start=1):
            current.append(min(
                current[-1] + 1, previous[j] + 1,
                previous[j - 1] + (word != hypothesis),
            ))
        previous = current
    return previous[-1], len(ref)


def evaluate_synthetic(
    payload: object,
    *,
    filter_off: Callable[[str], str],
    filter_on: Callable[[str], str],
    manifest_sha256: str,
) -> dict[str, object]:
    """Evaluate paired *synthetic* cases and report aggregate counts only.

    Oracle labels are authored with the fixtures; this code cannot infer human
    intent. A mismatch between expected and actual output makes the experiment
    inconclusive, never an artificial success. A confirmed destructive edit
    takes precedence over an unresolved item (FAIL rather than INCONCLUSIVE).
    """
    cases = _validated_cases(payload)
    if not re.fullmatch(r"[0-9a-f]{64}", manifest_sha256):
        raise EvaluationInputError("manifest_sha256 must be a hex SHA-256 digest")
    labels: Counter[str] = Counter()
    strata: Counter[str] = Counter()
    fluent_changes = 0
    dysfluent_count = 0
    safe_cleanups = 0
    destructive = 0
    unresolved = 0
    oracle_mismatches = 0
    changed = 0
    # [edit_distance, reference_token_count, cases_with_nonempty_reference]
    word_totals = {"verbatim_off": [0, 0, 0], "verbatim_on": [0, 0, 0],
                   "semantic_off": [0, 0, 0], "semantic_on": [0, 0, 0]}

    for case in cases:
        source = case["asr_text"]
        off = filter_off(source)
        on = filter_on(source)
        if not isinstance(off, str) or not isinstance(on, str):
            raise EvaluationInputError("filter must return strings")
        if off != source:
            raise EvaluationInputError("filter-off changed the fixed source hypothesis")
        was_changed = off != on
        changed += int(was_changed)
        stratum = case["stratum"]
        strata[stratum] += 1
        if stratum == "fluent":
            fluent_changes += int(was_changed)
        else:
            dysfluent_count += 1
        status = case["oracle_status"]
        label = case["oracle_label"]
        labels[label] += 1
        mismatch = (on != case["expected_on"] or
                    (label == "safe-cleanup" and not was_changed) or
                    (label in {"no-material-edit", "benign-retention"} and was_changed) or
                    (label.startswith("destructive-") and not was_changed))
        if mismatch:
            oracle_mismatches += 1
        if status != "confirmed" or label == "unassessable-disputed":
            unresolved += 1
        elif not mismatch and label.startswith("destructive-"):
            destructive += 1
        elif not mismatch and label == "safe-cleanup" and stratum != "fluent":
            safe_cleanups += 1

        for key, reference in (("verbatim", case["verbatim_reference"]),
                               ("semantic", case["semantic_reference"])):
            for condition, hypothesis in (("off", off), ("on", on)):
                errors, words = _word_errors(reference, hypothesis)
                if words:
                    cell = word_totals[f"{key}_{condition}"]
                    cell[0] += errors
                    cell[1] += words
                    cell[2] += 1

    if destructive:
        decision = "FAIL_SYNTHETIC"
    elif unresolved or oracle_mismatches:
        decision = "INCONCLUSIVE_SYNTHETIC"
    else:
        decision = "PASS_SYNTHETIC"

    scores = {
        key: {"errors": value[0], "reference_words": value[1],
              "cases_scored": value[2],
              "micro_wer": (value[0] / value[1] if value[1] else None)}
        for key, value in word_totals.items()
    }
    fluent_total = strata["fluent"]
    return {
        "schema_version": SCHEMA_VERSION,
        "scope": "synthetic-only; not a real-speech or participant efficacy result",
        "manifest_sha256": manifest_sha256,
        "case_count": len(cases),
        "strata_counts": dict(sorted(strata.items())),
        "oracle_label_counts": dict(sorted(labels.items())),
        "changed_cases": changed,
        "confirmed_new_destructive_cases": destructive,
        "unresolved_oracle_cases": unresolved,
        "fixture_output_or_label_mismatches": oracle_mismatches,
        "fluent_changes": {
            "numerator": fluent_changes,
            "denominator": fluent_total,
            "rate": fluent_changes / fluent_total if fluent_total else None,
        },
        "safe_cleanup_yield_nonfluent": {
            "numerator": safe_cleanups,
            "denominator": dysfluent_count,
            "rate": safe_cleanups / dysfluent_count if dysfluent_count else None,
        },
        "word_error_counts": scores,
        "decision": decision,
        "limitations": [
            "Synthetic authored cases have no speaker or acoustic validity.",
            "Labels are fixture oracles, not blinded human adjudications.",
            "WER uses casefolded whitespace tokens; no published benchmark equivalence is claimed.",
        ],
    }


def _write_aggregate_report(path: Path, report: dict[str, object]) -> None:
    """Create an aggregate-only report, never overwrite an existing file."""
    data = (json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as target:
        target.write(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path, help="Local JSON containing only synthetic cases")
    parser.add_argument("--output", type=Path, help="New file for aggregate-only JSON; never overwritten")
    args = parser.parse_args(argv)
    try:
        if args.fixture.stat().st_size > MAX_INPUT_BYTES:
            raise EvaluationInputError("fixture exceeds maximum size")
        raw = args.fixture.read_bytes()
        if len(raw) > MAX_INPUT_BYTES:
            raise EvaluationInputError("fixture exceeds maximum size")
        payload = json.loads(raw.decode("utf-8"))
        _validated_cases(payload)  # Reject real-speech scope before invoking YazSes.
        from yazses.config import DisfluencyConfig
        from yazses.stt.filters.disfluency import filter_transcript

        off_cfg = DisfluencyConfig(enabled=False)
        on_cfg = DisfluencyConfig(
            enabled=True, collapse_repetitions=True, collapse_prolongations=True,
        )
        report = evaluate_synthetic(
            payload,
            filter_off=lambda text: filter_transcript(text, off_cfg).text,
            filter_on=lambda text: filter_transcript(text, on_cfg).text,
            manifest_sha256=hashlib.sha256(raw).hexdigest(),
        )
        if args.output is not None:
            _write_aggregate_report(args.output, report)
    except (OSError, UnicodeError, json.JSONDecodeError, EvaluationInputError) as exc:
        # No transcript contents or paths are reflected in a validation error.
        if isinstance(exc, EvaluationInputError):
            parser.error(str(exc))
        parser.error("could not load fixture or create aggregate report")
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["decision"] == "PASS_SYNTHETIC" else 1


if __name__ == "__main__":
    raise SystemExit(main())
