#!/usr/bin/env python3
"""Validate the machine-readable eye/camera validation slot registry.

The registry (``design/eye-control/validation-slots.json``) is the machine-readable
form of ``design/eye-control/VALIDATION_MATRIX.md``: one entry per validation cell
(test pack x environment/session x A/B/repeat). This script answers structural and
policy questions about it and nothing else.

Three properties are deliberate.

**It is offline.** No GitHub call, no network, no clock, no environment lookup. Issue
numbers are recorded facts about which slot an issue represents, not live state; live
issue state belongs to a separate network-backed audit. Running this twice on the same
bytes gives the same answer on any machine.

**It is dependency-free.** Only the standard library. The repository stores design
manifests as both YAML (``design/traceability.yml``) and JSON (``campaign/tasks.json``,
``contract/vectors/*.json``); JSON was chosen here precisely because ``json`` is in the
standard library, so the validator -- and the coverage dashboard that will read the same
file -- needs no import beyond CPython itself.

**It fails loudly on input it cannot read.** A registry that is missing, unreadable or
not valid JSON raises :class:`RegistryError` and exits ``2``; it never degrades into an
empty document that then passes every per-slot check. For the same reason an empty
``slots`` list is an error, not a vacuous pass: a guard that only iterates is green on a
collection with nothing in it, which is the failure mode this file is written against.

Exit codes:

* ``0`` -- registry is structurally and policy valid;
* ``1`` -- registry parsed but violates one or more rules;
* ``2`` -- registry could not be read or parsed at all.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "design" / "eye-control" / "validation-slots.json"

SCHEMA_VERSION = 1

TOP_LEVEL_KEYS = {"schema_version", "description", "generated_from", "slots"}
TOP_LEVEL_REQUIRED = {"schema_version", "generated_from", "slots"}

SLOT_KEYS = {
    "id",
    "pack",
    "environment",
    "session",
    "slot",
    "state",
    "issue",
    "blocked_by",
    "additional_blockers",
    "sessions",
    "time_estimate_minutes",
    "hardware_required",
    "beginner_safe",
    "cloud_agent_ready",
    "public",
    "evidence_mode",
    "requirement",
}
#: Fields every slot must carry, whatever its state.
SLOT_REQUIRED = {
    "id",
    "pack",
    "environment",
    "session",
    "slot",
    "state",
    "hardware_required",
    "beginner_safe",
    "requirement",
}
#: Fields that must additionally be *resolved* before a slot may say READY.
#: VALIDATION_OPERATIONS.md: a slot becomes READY only once the runtime is reachable,
#: the fixture/evaluator exists and the issue body names the version and blockers -- so
#: a READY slot with an open prerequisite or a missing estimate is a contradiction.
READY_REQUIRED = ("issue", "time_estimate_minutes")

PACKS = {"T0", "T1", "T2", "T3", "T4", "T5", "T6", "T7"}
ENVIRONMENTS = {"WIN", "MAC", "GNOME", "KDE", "X11", "HIDPI", "ANY"}
SLOTS = {"A", "B", "repeat"}
STATES = {"planned", "ready"}

#: ADR-v2-150's evidence classes, minus ``research``. Research participant data is
#: collected under a named protocol on a private path and never appears in a public
#: registry, so the value is rejected outright rather than merely discouraged.
EVIDENCE_MODES = {"community_qa", "ci", "synthetic"}
FORBIDDEN_EVIDENCE_MODES = {"research"}
PUBLIC_EVIDENCE_MODE = "community_qa"

#: Defence in depth for the privacy rule. The slot schema is closed -- an unknown key is
#: already an error -- so these patterns exist to catch identity that slips into a value
#: of a legitimate free-text field, and to keep firing if the schema is ever widened.
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}")
_HANDLE = re.compile(r"(?<![\w.+-])@[A-Za-z0-9][A-Za-z0-9-]{0,38}")
_PHONE = re.compile(r"\+\d[\d\s().-]{7,}\d")
_IDENTITY_KEY_TOKENS = {
    "email",
    "mail",
    "phone",
    "tel",
    "contact",
    "participant",
    "participants",
    "username",
    "handle",
    "address",
    "hostname",
    "serial",
    "consent",
    "tester",
    "testers",
    "claimant",
    "assignee",
}


class RegistryError(Exception):
    """The registry could not be read or parsed.

    Raised rather than returning an empty document: a check that cannot parse its
    input must fail, because an empty result is indistinguishable from compliance.
    """


def load_registry(path: Path = REGISTRY) -> dict[str, Any]:
    """Read and parse the registry, or raise :class:`RegistryError`."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RegistryError(f"cannot read registry {path}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RegistryError(f"registry {path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise RegistryError(
            f"registry {path} must be a JSON object, got {type(data).__name__}"
        )
    return data


def _scan_identity(node: Any, where: str, errors: list[str]) -> None:
    """Reject anything that looks like participant identity or contact data."""
    if isinstance(node, dict):
        for key, value in node.items():
            path = f"{where}.{key}" if where else str(key)
            if isinstance(key, str):
                tokens = {token for token in re.split(r"[^a-z0-9]+", key.lower()) if token}
                hit = tokens & _IDENTITY_KEY_TOKENS
                if hit:
                    errors.append(
                        f"{path}: identity/contact field {sorted(hit)[0]!r} "
                        "must never appear in this registry"
                    )
            _scan_identity(value, path, errors)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _scan_identity(value, f"{where}[{index}]", errors)
    elif isinstance(node, str):
        for label, pattern in (("email address", _EMAIL), ("phone number", _PHONE)):
            if pattern.search(node):
                errors.append(f"{where}: value looks like a {label}; identity data is forbidden")
        # `@handle` only reads as identity in prose, and an email already matched above.
        if _HANDLE.search(node) and not _EMAIL.search(node):
            errors.append(f"{where}: value looks like an @handle; identity data is forbidden")


def _check_time_estimate(value: Any, where: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{where}: time_estimate_minutes must be a mapping with min and max")
        return
    unknown = set(value) - {"min", "max"}
    if unknown:
        errors.append(f"{where}: unknown time_estimate_minutes keys {sorted(unknown)}")
    low, high = value.get("min"), value.get("max")
    for name, bound in (("min", low), ("max", high)):
        if not isinstance(bound, int) or isinstance(bound, bool) or bound <= 0:
            errors.append(f"{where}: time_estimate_minutes.{name} must be a positive integer")
            return
    if isinstance(low, int) and isinstance(high, int) and low > high:
        errors.append(f"{where}: time_estimate_minutes.min must not exceed max")


def _check_slot(slot: Any, where: str, errors: list[str]) -> str | None:
    """Validate one slot; return its id when the id itself is usable."""
    if not isinstance(slot, dict):
        errors.append(f"{where}: slot must be a mapping")
        return None

    unknown = set(slot) - SLOT_KEYS
    if unknown:
        errors.append(f"{where}: unknown slot keys {sorted(unknown)}")

    slot_id = slot.get("id")
    if not isinstance(slot_id, str) or not slot_id.strip():
        errors.append(f"{where}: id must be a non-empty string")
        slot_id = None
    else:
        where = slot_id

    missing = sorted(field for field in SLOT_REQUIRED if slot.get(field) is None)
    if missing:
        errors.append(f"{where}: missing required field(s) {missing}")

    pack = slot.get("pack")
    if pack not in PACKS:
        errors.append(f"{where}: pack must be one of {sorted(PACKS)}, got {pack!r}")
    environment = slot.get("environment")
    if environment not in ENVIRONMENTS:
        errors.append(
            f"{where}: environment must be one of {sorted(ENVIRONMENTS)}, got {environment!r}"
        )
    ab = slot.get("slot")
    if ab not in SLOTS:
        errors.append(f"{where}: slot must be one of {sorted(SLOTS)}, got {ab!r}")

    if isinstance(slot_id, str) and pack in PACKS and environment in ENVIRONMENTS and ab in SLOTS:
        expected = f"{pack}-{environment}-{ab.upper()}"
        if slot_id != expected:
            errors.append(f"{where}: id should be {expected!r} for this pack/environment/slot")

    session = slot.get("session")
    if not isinstance(session, str) or not session.strip():
        errors.append(f"{where}: session must be a non-empty string")

    requirement = slot.get("requirement")
    if not isinstance(requirement, str) or not requirement.strip():
        errors.append(f"{where}: requirement must be a non-empty string")

    state = slot.get("state")
    if state not in STATES:
        errors.append(f"{where}: state must be one of {sorted(STATES)}, got {state!r}")

    for flag in ("hardware_required", "beginner_safe", "cloud_agent_ready", "public"):
        value = slot.get(flag)
        if value is not None and not isinstance(value, bool):
            errors.append(f"{where}: {flag} must be a boolean")

    issue = slot.get("issue")
    if issue is not None and (not isinstance(issue, int) or isinstance(issue, bool) or issue <= 0):
        errors.append(f"{where}: issue must be null or a positive integer")

    blocked_by = slot.get("blocked_by", [])
    if not isinstance(blocked_by, list) or any(
        not isinstance(n, int) or isinstance(n, bool) or n <= 0 for n in blocked_by
    ):
        errors.append(f"{where}: blocked_by must be a list of positive integers")
        blocked_by = []

    extra_blockers = slot.get("additional_blockers")
    if extra_blockers is not None and not isinstance(extra_blockers, str):
        errors.append(f"{where}: additional_blockers must be null or a string")

    sessions = slot.get("sessions", 1)
    if not isinstance(sessions, int) or isinstance(sessions, bool) or sessions <= 0:
        errors.append(f"{where}: sessions must be a positive integer")
    elif ab == "repeat" and sessions < 2:
        errors.append(f"{where}: a repeat slot must record more than one session")

    estimate = slot.get("time_estimate_minutes")
    if estimate is not None:
        _check_time_estimate(estimate, where, errors)

    # Evidence class. ADR-v2-150: a public report is community_qa, and `research` is
    # collected under a protocol on a private path -- never from this registry.
    evidence = slot.get("evidence_mode", PUBLIC_EVIDENCE_MODE)
    public = slot.get("public", True)
    if evidence in FORBIDDEN_EVIDENCE_MODES:
        errors.append(
            f"{where}: evidence_mode {evidence!r} is forbidden -- research participant data "
            "is collected under its own protocol, never through this registry"
        )
    elif evidence not in EVIDENCE_MODES:
        errors.append(f"{where}: evidence_mode must be one of {sorted(EVIDENCE_MODES)}")
    elif public is not False and evidence != PUBLIC_EVIDENCE_MODE:
        errors.append(
            f"{where}: a public slot must be {PUBLIC_EVIDENCE_MODE!r}, not {evidence!r}"
        )

    # A human hardware slot can never be cloud-agent-ready. VALIDATION_OPERATIONS.md:
    # "A machine can prepare the harness; a human must observe the real hardware result."
    if slot.get("cloud_agent_ready") is True:
        if slot.get("hardware_required") is not False:
            errors.append(
                f"{where}: a hardware slot can never be cloud_agent_ready -- a human must "
                "observe the real hardware result"
            )
        if evidence == PUBLIC_EVIDENCE_MODE:
            errors.append(
                f"{where}: community_qa evidence is human-operated and can never be "
                "cloud_agent_ready"
            )

    if state == "ready":
        for field in READY_REQUIRED:
            if slot.get(field) is None:
                errors.append(f"{where}: READY slot is missing required field {field!r}")
        if blocked_by:
            errors.append(
                f"{where}: READY slot still has unresolved prerequisite issue(s) {blocked_by}"
            )
        if isinstance(extra_blockers, str) and extra_blockers.strip():
            errors.append(
                f"{where}: READY slot still names an unresolved blocker: {extra_blockers!r}"
            )

    return slot_id if isinstance(slot_id, str) else None


def validate_registry(data: dict[str, Any], root: Path = ROOT) -> list[str]:
    """Return every rule violation in ``data``; an empty list means valid."""
    errors: list[str] = []

    unknown = set(data) - TOP_LEVEL_KEYS
    if unknown:
        errors.append(f"unknown top-level keys {sorted(unknown)}")
    missing = sorted(TOP_LEVEL_REQUIRED - set(data))
    if missing:
        errors.append(f"missing top-level key(s) {missing}")

    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")

    sources = data.get("generated_from")
    if not isinstance(sources, list) or not sources:
        errors.append("generated_from must be a non-empty list of repo-relative paths")
    else:
        for index, source in enumerate(sources):
            if not isinstance(source, str) or not source:
                errors.append(f"generated_from[{index}] must be a repo-relative path")
            elif not (root / source).exists():
                errors.append(f"generated_from[{index}]: path does not exist: {source}")

    _scan_identity(data, "", errors)

    slots = data.get("slots")
    if not isinstance(slots, list):
        errors.append("slots must be a list")
        return errors
    if not slots:
        # An empty registry is a failure, not a vacuous pass: every per-slot rule below
        # iterates, and iteration over nothing proves nothing.
        errors.append("slots is empty -- an empty registry proves nothing and is not valid")
        return errors

    seen_ids: set[str] = set()
    seen_issues: dict[int, str] = {}
    for index, slot in enumerate(slots):
        slot_id = _check_slot(slot, f"slots[{index}]", errors)
        if slot_id is not None:
            if slot_id in seen_ids:
                errors.append(f"{slot_id}: duplicate slot id")
            seen_ids.add(slot_id)
        if isinstance(slot, dict):
            issue = slot.get("issue")
            if isinstance(issue, int) and not isinstance(issue, bool) and issue > 0:
                owner = seen_issues.get(issue)
                if owner is not None:
                    errors.append(
                        f"{slot_id or f'slots[{index}]'}: issue #{issue} is already "
                        f"represented by {owner}"
                    )
                else:
                    seen_issues[issue] = slot_id or f"slots[{index}]"

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--registry",
        type=Path,
        default=REGISTRY,
        help="path to the validation slot registry (default: %(default)s)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="print the errors as a JSON array instead of a human-readable list",
    )
    args = parser.parse_args(argv)

    try:
        data = load_registry(args.registry)
    except RegistryError as exc:
        if args.as_json:
            print(json.dumps({"ok": False, "unreadable": True, "errors": [str(exc)]}))
        else:
            print(f"Eye validation registry could not be read: {exc}", file=sys.stderr)
        return 2

    errors = validate_registry(data)
    if args.as_json:
        print(json.dumps({"ok": not errors, "unreadable": False, "errors": errors}))
        return 1 if errors else 0
    if errors:
        print("Eye validation slot registry errors:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print(f"Eye validation slot registry is valid ({len(data['slots'])} slots).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
