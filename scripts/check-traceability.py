#!/usr/bin/env python3
"""Validate the offline planning traceability manifest.

This script intentionally does not call GitHub. Local/CI validation answers structural
questions only: is the manifest internally coherent, do referenced repo paths exist, and
are delivery states compatible with their tracking metadata? Live issue/milestone state
belongs in a separate network-backed audit.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "design" / "traceability.yml"

KINDS = {"capability", "programme", "research", "decision"}
DECISION_STATUSES = {"proposed", "accepted", "superseded", "rejected"}
DELIVERY_STATUSES = {
    "research",
    "designed",
    "scheduled",
    "in-progress",
    "partially-shipped",
    "shipped",
    "blocked",
    "deferred",
    "not-planned",
}
TRACKING_KINDS = {"issue", "campaign", "research", "none"}
TRACKED_DELIVERY = {"scheduled", "in-progress"}
NO_MILESTONE_DELIVERY = {"deferred", "not-planned"}


def load_manifest(path: Path = MANIFEST) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def validate_manifest(data: dict[str, Any], root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    if data.get("version") != 1:
        errors.append("top-level version must be 1")

    entries = data.get("entries")
    if not isinstance(entries, list):
        return errors + ["top-level entries must be a list"]

    seen: set[str] = set()
    for index, entry in enumerate(entries):
        where = f"entries[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{where} must be a mapping")
            continue

        entry_id = entry.get("id")
        if not isinstance(entry_id, str) or not entry_id:
            errors.append(f"{where}.id must be a non-empty string")
            continue
        where = entry_id
        if entry_id in seen:
            errors.append(f"{where}: duplicate id")
        seen.add(entry_id)

        kind = entry.get("kind")
        if kind not in KINDS:
            errors.append(f"{where}: invalid kind {kind!r}")

        title = entry.get("title")
        if not isinstance(title, str) or not title.strip():
            errors.append(f"{where}: title must be a non-empty string")

        source = entry.get("source")
        if not isinstance(source, str) or not source:
            errors.append(f"{where}: source must be a repo-relative path")
        elif not (root / source).exists():
            errors.append(f"{where}: source path does not exist: {source}")

        decision_status = entry.get("decision_status")
        if kind == "research":
            if decision_status is not None:
                errors.append(f"{where}: research entries must not invent a decision_status")
        elif decision_status not in DECISION_STATUSES:
            errors.append(f"{where}: invalid decision_status {decision_status!r}")

        delivery_status = entry.get("delivery_status")
        if delivery_status not in DELIVERY_STATUSES:
            errors.append(f"{where}: invalid delivery_status {delivery_status!r}")

        tracking = entry.get("tracking")
        if not isinstance(tracking, dict):
            errors.append(f"{where}: tracking must be a mapping")
            continue

        tracking_kind = tracking.get("kind")
        if tracking_kind not in TRACKING_KINDS:
            errors.append(f"{where}: invalid tracking.kind {tracking_kind!r}")

        issues = tracking.get("issues")
        if not isinstance(issues, list) or any(
            not isinstance(issue, int) or issue <= 0 for issue in issues
        ):
            errors.append(f"{where}: tracking.issues must be a list of positive integers")
            issues = []

        task = tracking.get("task")
        if task is not None and (not isinstance(task, str) or not task):
            errors.append(f"{where}: tracking.task must be null or a non-empty string")

        milestone = tracking.get("milestone")
        if milestone is not None and (not isinstance(milestone, int) or milestone <= 0):
            errors.append(f"{where}: tracking.milestone must be null or a positive integer")

        if tracking_kind == "none" and (issues or task is not None or milestone is not None):
            errors.append(f"{where}: tracking.kind=none cannot carry issues/task/milestone")
        if tracking_kind in {"issue", "research"} and not issues:
            errors.append(f"{where}: tracking.kind={tracking_kind} requires an issue")
        if tracking_kind == "campaign" and (not issues or task is None):
            errors.append(f"{where}: campaign tracking requires umbrella issue(s) and task")
        if delivery_status in TRACKED_DELIVERY and tracking_kind == "none":
            errors.append(f"{where}: {delivery_status} work requires a tracking surface")
        if delivery_status in NO_MILESTONE_DELIVERY and milestone is not None:
            errors.append(f"{where}: {delivery_status} work cannot carry a milestone")
        if delivery_status == "partially-shipped" and not entry.get("remaining"):
            errors.append(f"{where}: partially-shipped work must say what remains")

    return errors


def main() -> int:
    errors = validate_manifest(load_manifest())
    if errors:
        print("Planning traceability errors:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("Planning traceability manifest is structurally valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
