#!/usr/bin/env python3
"""Generate the eye/camera validation coverage dashboard from the slot registry.

`design/eye-control/VALIDATION_OPERATIONS.md` asks the project to be able to answer,
without reading every issue by hand, which validation cells exist, which are runnable,
what blocks the rest and where the programme has no cell at all. This script answers
exactly that, from one committed input -- `design/eye-control/validation-slots.json` --
and writes `design/eye-control/generated/validation-coverage.md`.

Run it, and commit the result:

    uv run python scripts/gen-eye-validation-dashboard.py

Five properties are deliberate.

**It consumes the registry; it does not re-parse the prose matrix.** The registry and its
validator are the machine-readable form of the A/B tables, so `load_registry` and
`validate_registry` are imported from `scripts/check_eye_validation_slots.py` rather than
reimplemented. A registry that fails validation produces no page at all: a dashboard
generated from a registry nobody validated would look authoritative and be wrong.

**It is offline and clock-free.** No GitHub call, no network, no timestamp, no version
stamp, no environment lookup. The same registry bytes therefore render byte-identical
output on any machine, which is what makes the committed page reviewable in a diff and
enforceable by a drift test. Issue numbers are recorded facts about which cell an issue
represents; they are not live issue state, and this page never claims to be.

**It reports the registry's recorded plan, not live GitHub readiness.** `design/eye-control/README.md`
rejected a hand-written `STATUS.md` because a file cannot track state that lives on GitHub.
This page is not that file: every value on it is a function of the committed registry, and
the page says so about itself. Live readiness, labels and claims are still read from the
issues.

**Absence of a report is never rendered as a failure, and a failure is never rendered as
absence.** A FAIL or BLOCKED outcome is a valid completed contribution
(VALIDATION_OPERATIONS.md), so a cell carrying one is counted as *reported*, never as
awaiting evidence; and a cell with no report is counted as awaiting a first report, never
as a failure.

**Independent hosts and repeated sessions are counted separately, always.** The matrix's
first rule is that ten sessions by one person on one laptop are not ten independent
computers, so the two numbers travel in different fields and are rendered in different
words. Nothing in this file adds one to the other.

Reported outcomes are an optional second input. No outcome file is committed today, so the
committed page reports every cell as awaiting its first report. When one exists, pass it
with `--outcomes PATH`; the shape is documented in `validate_outcomes` below and is the only
place a later format has to be adapted. It is deliberately *not* the per-session result
envelope in `src/yazses/eyeeval/schema.py`: that document describes one run, carries a
timestamp and names no validation cell, so turning a directory of runs into one outcome per
cell is a separate aggregation step -- and a timestamped input could not produce a
byte-stable committed page anyway.

Exit codes:

* ``0`` -- the page was written (or, with ``--check``, is already current);
* ``1`` -- an input parsed but violates a rule, or ``--check`` found drift;
* ``2`` -- an input could not be read or parsed at all.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_eye_validation_slots import (  # noqa: E402  (sibling script, not a package)
    ENVIRONMENTS,
    PACKS,
    RegistryError,
    _scan_identity,
    load_registry,
    validate_registry,
)

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "design" / "eye-control" / "validation-slots.json"
OUTPUT = ROOT / "design" / "eye-control" / "generated" / "validation-coverage.md"

GENERATOR = "scripts/gen-eye-validation-dashboard.py"
REGISTRY_REL = "design/eye-control/validation-slots.json"
OUTPUT_REL = "design/eye-control/generated/validation-coverage.md"
ISSUE_URL = "https://github.com/MSKazemi/yazses/issues"

#: Reading order for the grid columns: the three desktop platforms, the two Linux session
#: types, the topology bucket, then the platform-agnostic bucket. It matches the order
#: VALIDATION_MATRIX.md lists them in, and it is written down so the table cannot reorder
#: itself between runs.
ENVIRONMENT_ORDER = ("WIN", "MAC", "GNOME", "KDE", "X11", "HIDPI", "ANY")
PACK_ORDER = tuple(f"T{n}" for n in range(8))
SLOT_ORDER = ("A", "B", "repeat")

#: The reported outcome classes, in the order VALIDATION_OPERATIONS.md lists them. PASS and
#: PARTIAL are successes, FAIL and BLOCKED are *recorded evidence* -- not missing evidence.
OUTCOME_ORDER = ("pass", "partial", "fail", "blocked")

_OUTCOME_KEYS = {"outcome", "independent_hosts", "repeat_sessions"}


class DashboardError(Exception):
    """An input parsed but violates a rule. Rendered as exit 1, never as an empty page."""


# --------------------------------------------------------------------------- #
# Pure logic: registry (+ optional outcomes) -> a coverage model
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Cell:
    """One validation cell, ready to render. Every field is derived from the registry."""

    id: str
    pack: str
    environment: str
    session: str
    slot: str
    state: str
    issue: int | None
    blocked_by: tuple[int, ...]
    additional_blockers: str
    sessions_planned: int
    beginner_safe: bool
    outcome: str | None
    independent_hosts: int
    repeat_sessions: int

    @property
    def testable_now(self) -> bool:
        """Whether a contributor could run this cell today.

        Derived from the registry state and nothing else. VALIDATION_OPERATIONS.md makes
        READY mean the runtime is reachable, the fixture exists and the blockers are named,
        so READY is the only honest "yes" available offline -- this file does not inspect
        the source tree and guess whether a feature is implemented.
        """
        return self.state == "ready"

    @property
    def reported(self) -> bool:
        """Whether a report exists. A FAIL or BLOCKED report counts; it is evidence."""
        return self.outcome is not None


@dataclass(frozen=True)
class Coverage:
    """The whole model the page renders. Built once, rendered without further lookups."""

    schema_version: int
    cells: tuple[Cell, ...]

    def grid(self) -> dict[tuple[str, str], tuple[Cell, ...]]:
        """Registered cells keyed by (pack, environment), in slot order."""
        out: dict[tuple[str, str], list[Cell]] = {}
        for cell in self.cells:
            out.setdefault((cell.pack, cell.environment), []).append(cell)
        return {
            key: tuple(sorted(group, key=lambda c: _slot_rank(c.slot)))
            for key, group in out.items()
        }

    def gaps(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        """Per pack, the environments in the registry's own vocabulary with no cell.

        A gap means the programme has not committed a cell for that combination -- not
        that a test is overdue. VALIDATION_MATRIX.md is explicit that a row must not be
        asked of contributors before the capability is reachable on their platform.
        """
        registered = {(cell.pack, cell.environment) for cell in self.cells}
        out: list[tuple[str, tuple[str, ...]]] = []
        for pack in _ordered(PACKS, PACK_ORDER):
            missing = tuple(
                env
                for env in _ordered(ENVIRONMENTS, ENVIRONMENT_ORDER)
                if (pack, env) not in registered
            )
            if missing:
                out.append((pack, missing))
        return tuple(out)

    def blocking_issues(self) -> tuple[tuple[int, tuple[str, ...]], ...]:
        """Prerequisite issue -> the cells it blocks, both in deterministic order."""
        out: dict[int, list[str]] = {}
        for cell in self.cells:
            for issue in cell.blocked_by:
                out.setdefault(issue, []).append(cell.id)
        return tuple((issue, tuple(out[issue])) for issue in sorted(out))

    def counts(self) -> dict[str, int]:
        """Every number the summary table prints, so the table cannot compute its own."""
        cells = self.cells
        return {
            "cells": len(cells),
            "planned": sum(1 for c in cells if c.state == "planned"),
            "ready": sum(1 for c in cells if c.state == "ready"),
            "testable_now": sum(1 for c in cells if c.testable_now),
            "reported": sum(1 for c in cells if c.reported),
            # Deliberately *not* "cells with no evidence": a FAIL or BLOCKED cell has
            # evidence, and lumping it in here is the misreading the issue forbids.
            "awaiting_first_report": sum(1 for c in cells if not c.reported),
            **{
                f"outcome_{name}": sum(1 for c in cells if c.outcome == name)
                for name in OUTCOME_ORDER
            },
            # Two different units. Independent hosts answer "how many computers?";
            # repeat sessions answer "how many separated runs on the same one?".
            "independent_hosts": sum(c.independent_hosts for c in cells),
            "repeat_sessions": sum(c.repeat_sessions for c in cells),
            "sessions_planned": sum(c.sessions_planned for c in cells),
            "packs_with_a_cell": len({c.pack for c in cells}),
            "packs_total": len(PACKS),
            "environments_with_a_cell": len({c.environment for c in cells}),
            "environments_total": len(ENVIRONMENTS),
            "beginner_safe": sum(1 for c in cells if c.beginner_safe),
        }


def _slot_rank(slot: str) -> tuple[int, str]:
    return (SLOT_ORDER.index(slot) if slot in SLOT_ORDER else len(SLOT_ORDER), slot)


def _ordered(values: set[str], preferred: tuple[str, ...]) -> tuple[str, ...]:
    """``preferred`` first, then anything the vocabulary gained since, alphabetically.

    The vocabulary lives in the validator. Hard-coding the order here and *deriving* the
    membership means a value added to the validator still appears on this page -- a
    hand-written set of the things to show is the defect this avoids.
    """
    known = [v for v in preferred if v in values]
    return tuple(known + sorted(values - set(preferred)))


def _cell_rank(cell: Cell) -> tuple[int, int, tuple[int, str], str]:
    pack_order = _ordered(PACKS, PACK_ORDER)
    env_order = _ordered(ENVIRONMENTS, ENVIRONMENT_ORDER)
    return (
        pack_order.index(cell.pack) if cell.pack in pack_order else len(pack_order),
        env_order.index(cell.environment) if cell.environment in env_order else len(env_order),
        _slot_rank(cell.slot),
        cell.id,
    )


def validate_outcomes(data: dict[str, Any], known_ids: set[str]) -> list[str]:
    """Return every rule violation in a reported-outcome document.

    Shape -- deliberately minimal, and the only thing a later result format must adapt:

    .. code-block:: json

        {"schema_version": 1,
         "cells": {"T0-WIN-A": {"outcome": "fail",
                                "independent_hosts": 1,
                                "repeat_sessions": 0}}}

    ``independent_hosts`` counts distinct physical computers; ``repeat_sessions`` counts
    separated runs on the same computer by the same person. They are separate fields
    because the matrix's first rule is that one is not the other. Participant identity and
    contact data are rejected outright, for the same reason the registry rejects them.
    """
    errors: list[str] = []
    unknown = set(data) - {"schema_version", "description", "cells"}
    if unknown:
        errors.append(f"unknown top-level keys {sorted(unknown)}")
    if data.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    _scan_identity(data, "", errors)

    cells = data.get("cells")
    if not isinstance(cells, dict):
        errors.append("cells must be a mapping of cell id -> reported outcome")
        return errors
    if not cells:
        # An outcome file with nothing in it is a mistake, not "no outcomes": the caller
        # asked for a file, and a guard that only iterates is green on an empty mapping.
        errors.append("cells is empty -- omit --outcomes rather than passing an empty file")
        return errors

    for cell_id in sorted(cells):
        record = cells[cell_id]
        if cell_id not in known_ids:
            errors.append(f"{cell_id}: no such cell in the registry")
        if not isinstance(record, dict):
            errors.append(f"{cell_id}: reported outcome must be a mapping")
            continue
        extra = set(record) - _OUTCOME_KEYS
        if extra:
            errors.append(f"{cell_id}: unknown outcome keys {sorted(extra)}")
        outcome = record.get("outcome")
        if outcome not in OUTCOME_ORDER:
            errors.append(f"{cell_id}: outcome must be one of {list(OUTCOME_ORDER)}, got {outcome!r}")
        for field in ("independent_hosts", "repeat_sessions"):
            value = record.get(field, 0)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                errors.append(f"{cell_id}: {field} must be a non-negative integer")
    return errors


def build_coverage(
    registry: dict[str, Any], outcomes: dict[str, Any] | None = None
) -> Coverage:
    """Turn a validated registry (+ optional outcomes) into the renderable model.

    Pure: no filesystem, no clock, no network. Raises :class:`DashboardError` rather than
    returning a short model, because a coverage page missing cells reads as coverage.
    """
    slots = registry.get("slots")
    if not isinstance(slots, list) or not slots:
        raise DashboardError(
            "registry has no slots -- an empty coverage page would read as full coverage"
        )
    reported = dict(outcomes or {})

    cells: list[Cell] = []
    for slot in slots:
        if not isinstance(slot, dict):
            raise DashboardError(f"registry slot is not a mapping: {slot!r}")
        slot_id = slot.get("id")
        if not isinstance(slot_id, str) or not slot_id:
            raise DashboardError(f"registry slot has no usable id: {slot!r}")
        record = reported.get(slot_id) or {}
        blockers = slot.get("additional_blockers") or ""
        cells.append(
            Cell(
                id=slot_id,
                pack=str(slot.get("pack")),
                environment=str(slot.get("environment")),
                session=str(slot.get("session")),
                slot=str(slot.get("slot")),
                state=str(slot.get("state")),
                issue=slot.get("issue"),
                blocked_by=tuple(slot.get("blocked_by") or ()),
                additional_blockers=str(blockers),
                sessions_planned=int(slot.get("sessions") or 1),
                beginner_safe=bool(slot.get("beginner_safe")),
                outcome=record.get("outcome"),
                independent_hosts=int(record.get("independent_hosts") or 0),
                repeat_sessions=int(record.get("repeat_sessions") or 0),
            )
        )

    ids = {cell.id for cell in cells}
    if len(ids) != len(cells):
        raise DashboardError("registry contains duplicate cell ids")
    unknown = sorted(set(reported) - ids)
    if unknown:
        raise DashboardError(f"reported outcomes name cells that are not registered: {unknown}")

    version = registry.get("schema_version")
    return Coverage(
        schema_version=version if isinstance(version, int) else 0,
        cells=tuple(sorted(cells, key=_cell_rank)),
    )


def missing_cells(page: str, registry: dict[str, Any]) -> list[str]:
    """Registry cell ids that do not appear in ``page``.

    This is the check a regenerate-and-compare drift test cannot make. That test compares
    the file to its generator, so a generator which silently drops a cell agrees with its
    own output and the test stays green. Completeness has to be asserted against the
    *registry*, by id, which is what this does.
    """
    slots = registry.get("slots")
    if not isinstance(slots, list):
        raise DashboardError("registry has no slots list to check completeness against")
    return [
        slot["id"]
        for slot in slots
        if isinstance(slot, dict) and isinstance(slot.get("id"), str) and slot["id"] not in page
    ]


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def _issue_link(issue: int | None) -> str:
    return f"[#{issue}]({ISSUE_URL}/{issue})" if issue else "none yet"


def _state_label(cell: Cell) -> str:
    return cell.state.upper()


def _evidence(cell: Cell) -> str:
    """One cell's reported evidence, with hosts and repeat sessions kept apart."""
    if cell.outcome is None:
        return "awaiting first report"
    parts = [cell.outcome.upper()]
    parts.append(
        f"{cell.independent_hosts} independent host"
        f"{'' if cell.independent_hosts == 1 else 's'}"
    )
    parts.append(
        f"{cell.repeat_sessions} repeat session"
        f"{'' if cell.repeat_sessions == 1 else 's'}"
    )
    return " · ".join(parts)


def _grid_token(cell: Cell) -> str:
    slot = f"repeat×{cell.sessions_planned}" if cell.slot == "repeat" else cell.slot
    if cell.outcome is None:
        return f"{slot} ({_state_label(cell)})"
    return f"{slot} ({_state_label(cell)}, {cell.outcome.upper()})"


def _summary_rows(counts: dict[str, int]) -> list[tuple[str, str]]:
    outcomes = " / ".join(str(counts[f"outcome_{name}"]) for name in OUTCOME_ORDER)
    return [
        ("Registered validation cells", str(counts["cells"])),
        ("PLANNED — runtime or harness not available yet", str(counts["planned"])),
        ("READY — a contributor could run it today", str(counts["ready"])),
        ("Cells with a report of any outcome", str(counts["reported"])),
        ("— PASS / PARTIAL / FAIL / BLOCKED", outcomes),
        ("Cells awaiting a first report", str(counts["awaiting_first_report"])),
        ("Independent physical hosts represented", str(counts["independent_hosts"])),
        ("Repeat sessions recorded (same person, same host)", str(counts["repeat_sessions"])),
        ("Sessions the registry plans in total", str(counts["sessions_planned"])),
        (
            "Test packs with at least one registered cell",
            f"{counts['packs_with_a_cell']} of {counts['packs_total']}",
        ),
        (
            "Environments with at least one registered cell",
            f"{counts['environments_with_a_cell']} of {counts['environments_total']}",
        ),
        (
            "Cells whose task is intrinsically beginner-safe (not a live label)",
            str(counts["beginner_safe"]),
        ),
    ]


def render(coverage: Coverage) -> str:
    """Render the whole page. Deterministic: same model in, same bytes out."""
    out: list[str] = []
    w = out.append

    w(f"<!-- GENERATED by {GENERATOR} — do not edit by hand. -->")
    w(f"<!-- Source of truth: {REGISTRY_REL} — edit that, then regenerate: -->")
    w(f"<!--   uv run python {GENERATOR} -->")
    w("")
    w("# Eye / camera validation coverage")
    w("")
    w(
        "Generated from [`validation-slots.json`](../validation-slots.json) "
        f"(schema version {coverage.schema_version}). Do not hand-edit this file: edit the "
        f"registry and run `uv run python {GENERATOR}`."
    )
    w("")
    w("## How to read this page")
    w("")
    w(
        "- **It reports the committed registry, not GitHub.** Every value below is a function "
        "of the registry file. Live issue readiness, labels and claims are read from the "
        "issues under [#102](https://github.com/MSKazemi/yazses/issues/102), never from here — "
        "see the note in [README.md](../README.md) about why this directory carries no status "
        "snapshot."
    )
    w(
        "- **PLANNED and READY are lifecycle states, not results.** "
        "[VALIDATION_OPERATIONS.md](../VALIDATION_OPERATIONS.md) defines them: PLANNED means the "
        "runtime or harness is not available yet, READY means a contributor could run the cell "
        "today."
    )
    w(
        "- **A FAIL or BLOCKED report is evidence, not missing evidence.** Such a cell counts as "
        "reported, is a valid completed contribution, and never appears in *awaiting a first "
        "report*."
    )
    w(
        "- **Independent hosts and repeat sessions are different units.** Three separated "
        "sessions by one person on one computer are three repeat sessions and *one* host; they "
        "are never added together or shown as three people."
    )
    w(
        "- **Beginner-safety is intrinsic difficulty, not a live label.** It records whether a "
        "cell would carry `good first issue` once READY. Readiness labels are deliberately "
        "withheld while a cell is PLANNED ([GOVERNANCE.md](../GOVERNANCE.md))."
    )
    w(
        "- **A combination with no registered cell is not an overdue test.** The programme opens "
        "a cell when the capability is reachable on that platform, so a gap below means no cell "
        "has been committed yet."
    )
    w("")

    counts = coverage.counts()
    w("## Summary")
    w("")
    w("| Measure | Count |")
    w("|---|---:|")
    for label, value in _summary_rows(counts):
        w(f"| {label} | {value} |")
    w("")

    w("## Registered cells by test pack and environment")
    w("")
    w(
        "Rows are the test packs and columns the environments in the registry's own "
        "vocabulary, so a pack or environment added to the registry appears here without "
        "editing this table. `—` means no cell is registered for that combination."
    )
    w("")
    env_order = _ordered(ENVIRONMENTS, ENVIRONMENT_ORDER)
    w("| Pack | " + " | ".join(env_order) + " |")
    w("|---|" + "---|" * len(env_order))
    grid = coverage.grid()
    for pack in _ordered(PACKS, PACK_ORDER):
        row = [pack]
        for env in env_order:
            group = grid.get((pack, env), ())
            row.append(", ".join(_grid_token(cell) for cell in group) if group else "—")
        w("| " + " | ".join(row) + " |")
    w("")

    w("## Every registered cell")
    w("")
    w(
        "One row per registered cell, in pack then environment then slot order. The issue link "
        "is derived from the registry, so it cannot disagree with the cell it represents."
    )
    w("")
    w(
        "| Cell | Session | Slot | State | Runnable today? | Issue | Reported evidence | "
        "Sessions planned | Blocked by |"
    )
    w("|---|---|---|---|---|---|---|---:|---|")
    for cell in coverage.cells:
        blocked = ", ".join(_issue_link(n) for n in cell.blocked_by) or "—"
        if cell.additional_blockers:
            blocked += " + a condition below"
        w(
            f"| `{cell.id}` | {cell.session} | {cell.slot} | {_state_label(cell)} | "
            f"{'yes' if cell.testable_now else 'no'} | {_issue_link(cell.issue)} | "
            f"{_evidence(cell)} | {cell.sessions_planned} | {blocked} |"
        )
    w("")

    w("## Unmet blockers")
    w("")
    blocking = coverage.blocking_issues()
    if blocking:
        w("| Prerequisite | Cells blocked | Cells |")
        w("|---|---:|---|")
        for issue, ids in blocking:
            w(f"| {_issue_link(issue)} | {len(ids)} | {', '.join(f'`{i}`' for i in ids)} |")
    else:
        w("No registered cell names a prerequisite issue.")
    w("")
    conditions = [cell for cell in coverage.cells if cell.additional_blockers]
    w("### Conditions beyond a prerequisite issue")
    w("")
    if conditions:
        w("| Cell | Condition that must hold first |")
        w("|---|---|")
        for cell in conditions:
            w(f"| `{cell.id}` | {cell.additional_blockers} |")
    else:
        w("No registered cell names a condition beyond its prerequisite issues.")
    w("")

    w("## Combinations with no registered cell")
    w("")
    w(
        "These are pack/environment combinations the registry vocabulary allows and for which "
        "no cell has been committed. They are gaps in the plan, not overdue work: "
        "[VALIDATION_MATRIX.md](../VALIDATION_MATRIX.md) is explicit that a row must not be asked "
        "of a contributor before that capability is reachable on their platform."
    )
    w("")
    gaps = coverage.gaps()
    if gaps:
        w("| Pack | Environments with no registered cell |")
        w("|---|---|")
        for pack, missing in gaps:
            w(f"| {pack} | {', '.join(missing)} |")
    else:
        w("Every pack/environment combination in the vocabulary has a registered cell.")
    w("")

    # One trailing newline exactly: the sections each end with a blank line, and a file
    # whose last byte pair is "\n\n" is what a POSIX tool, an editor and this generator
    # would each silently disagree about.
    return "\n".join(out).rstrip("\n") + "\n"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def generate(registry_path: Path, outcomes_path: Path | None = None) -> str:
    """Load, validate and render. Raises :class:`RegistryError` or :class:`DashboardError`."""
    registry = load_registry(registry_path)
    errors = validate_registry(registry)
    if errors:
        raise DashboardError(
            "registry is invalid, so no coverage page was generated:\n  - "
            + "\n  - ".join(errors)
        )

    outcomes: dict[str, Any] | None = None
    if outcomes_path is not None:
        try:
            # Same loud-on-unparseable contract as the registry, renamed so the message
            # says which of the two inputs could not be read.
            document = load_registry(outcomes_path)
        except RegistryError as exc:
            raise RegistryError(f"reported-outcome document: {exc}") from exc
        known = {
            slot["id"]
            for slot in registry["slots"]
            if isinstance(slot, dict) and isinstance(slot.get("id"), str)
        }
        outcome_errors = validate_outcomes(document, known)
        if outcome_errors:
            raise DashboardError(
                "reported outcomes are invalid, so no coverage page was generated:\n  - "
                + "\n  - ".join(outcome_errors)
            )
        outcomes = document["cells"]

    page = render(build_coverage(registry, outcomes))
    dropped = missing_cells(page, registry)
    if dropped:
        # Belt and braces for the failure a drift test cannot see: if rendering ever loses
        # a cell, refuse to write the page rather than emit a plausible short one.
        raise DashboardError(f"rendered page is missing registered cell(s): {dropped}")
    return page


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--registry",
        type=Path,
        default=REGISTRY,
        help="path to the validation slot registry (default: %(default)s)",
    )
    parser.add_argument(
        "--outcomes",
        type=Path,
        default=None,
        help="optional reported-outcome document; omitted means no report exists yet",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT,
        help="path to write the dashboard to (default: %(default)s)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; exit 1 if the committed page differs from the generator",
    )
    args = parser.parse_args(argv)

    try:
        page = generate(args.registry, args.outcomes)
    except RegistryError as exc:
        print(f"Eye validation input could not be read: {exc}", file=sys.stderr)
        return 2
    except DashboardError as exc:
        print(f"Eye validation coverage dashboard not generated: {exc}", file=sys.stderr)
        return 1

    if args.check:
        try:
            current = args.output.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"{args.output} could not be read: {exc}", file=sys.stderr)
            return 1
        if current != page:
            print(
                f"{OUTPUT_REL} is stale — run `uv run python {GENERATOR}` and commit.",
                file=sys.stderr,
            )
            return 1
        print(f"{OUTPUT_REL} is current.")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(page, encoding="utf-8")
    print(f"wrote {OUTPUT_REL}  ({page.count(chr(10))} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
