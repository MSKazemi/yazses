#!/usr/bin/env python3
"""The nightly runtime budget (ADR-029 section 4): peak RSS per residency unit against a ceiling.

The nightly job measures each residency unit's peak RSS in its own subprocess and writes
``{unit: peak_rss_mb}``. This script is the verdict on that file:

* exit 0 -- every budgeted unit was measured and sits within its ceiling;
* exit 1 -- a breach, a budgeted unit the run did not measure, or an empty measurement
  (an empty run has not passed, it has not run);
* exit 2 -- an unreadable or malformed budget or measurement file.

    uv run python scripts/check_runtime_budget.py --emit-template > measured.json
    uv run python scripts/check_runtime_budget.py --measured measured.json

The ceilings live in ``scripts/runtime_budget.json``. They are the ADR's stated figures
where it states one, and labelled proposals where it does not; the nightly measurements
are what replace them. Stdlib plus the installed ``yazses`` package only: no network,
no model, no audio.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from yazses.system.residency import DEFAULT_POLICY, RuntimeBudget, check_rss, unmeasured

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BUDGET = Path(__file__).with_name("runtime_budget.json")

# ADR-029 section 4 names the verdict's tolerance: a single runner's peak is noisy, and a
# ceiling that fails on noise gets deleted.
TOLERANCE = 1.2


class InputError(Exception):
    """An input file that cannot be read or does not have the expected shape."""


def _load_json(path: Path, what: str) -> object:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InputError(f"cannot read {what} {path}: {exc.strerror or exc}") from None
    except UnicodeDecodeError as exc:
        raise InputError(f"{what} {path} is not UTF-8 text: {exc.reason}") from None
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise InputError(f"{what} {path} is not valid JSON: {exc}") from None


def load_budget(path: Path) -> dict[str, float | None]:
    """Each policy unit's ceiling in MB, or ``None`` where the ADR states no figure yet.

    Every unit of :data:`DEFAULT_POLICY` must have a row: a unit the budget forgets is a
    unit nobody checks, which is the failure this gate exists to prevent.
    """
    raw = _load_json(path, "budget")
    if not isinstance(raw, dict):
        raise InputError(f"budget {path} must be a JSON object keyed by residency unit")
    rows = {k: v for k, v in raw.items() if not k.startswith("_")}

    known = DEFAULT_POLICY.units()
    unknown = sorted(set(rows) - known)
    if unknown:
        raise InputError(f"budget {path} names unknown unit(s): {', '.join(unknown)}")
    missing = sorted(known - set(rows))
    if missing:
        raise InputError(f"budget {path} has no row for unit(s): {', '.join(missing)}")

    ceilings: dict[str, float | None] = {}
    for unit, row in rows.items():
        if not isinstance(row, dict) or "peak_rss_mb" not in row:
            raise InputError(f"budget row {unit!r} must be an object with 'peak_rss_mb'")
        value = row["peak_rss_mb"]
        if value is not None and not _is_number(value):
            raise InputError(f"budget row {unit!r}: peak_rss_mb must be a number or null")
        try:
            # The same finite, non-negative rule the residency policy applies everywhere.
            if value is not None:
                RuntimeBudget(feature=unit, peak_rss_mb=float(value))
        except (TypeError, ValueError) as exc:
            raise InputError(f"budget row {unit!r}: {exc}") from None
        ceilings[unit] = None if value is None else float(value)
    return ceilings


def load_measured(path: Path, units: frozenset[str] | set[str]) -> dict[str, float]:
    """The figures the run produced. A ``null`` is a unit the run did not measure, so the
    ``--emit-template`` skeleton is a valid input that simply reports everything unmeasured.
    """
    raw = _load_json(path, "measurement")
    if not isinstance(raw, dict):
        raise InputError(f"measurement {path} must be a JSON object of {{unit: peak_rss_mb}}")
    measured: dict[str, float] = {}
    for unit, value in raw.items():
        if unit not in units:
            raise InputError(
                f"measurement {path} names unit {unit!r}, which is not a budgeted unit"
            )
        if value is None:
            continue
        if not _is_number(value):
            raise InputError(f"measurement for {unit!r} must be a number or null, got {value!r}")
        if not math.isfinite(value) or value < 0:
            raise InputError(
                f"measurement for {unit!r} must be finite and non-negative, got {value!r}"
            )
        measured[unit] = float(value)
    return measured


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def emit_template(budget_units: list[str]) -> str:
    """A measured-file skeleton: every budgeted unit, null until the probe fills it."""
    return json.dumps({unit: None for unit in budget_units}, indent=2) + "\n"


def verdict(ceilings: dict[str, float | None], measured: dict[str, float]) -> int:
    """Print one line per breach and per unmeasured unit; return the exit code."""
    if not measured:
        print(
            "FAIL: the run measured nothing; an empty measurement is a failure, not a pass.",
            file=sys.stderr,
        )
        for unit in unmeasured({u: 0.0 for u in ceilings}, measured):
            print(f"UNMEASURED {unit}")
        return 1

    budget_mb = {unit: ceiling for unit, ceiling in ceilings.items() if ceiling is not None}
    breaches = check_rss(measured, budget_mb, tolerance=TOLERANCE)
    missing = unmeasured({u: 0.0 for u in ceilings}, measured)

    for breach in breaches:
        print(f"BREACH {breach.describe()}")
    for unit in missing:
        print(f"UNMEASURED {unit}: no peak RSS figure in this run")
    for unit in sorted(set(measured) - set(budget_mb)):
        print(f"NOTE {unit}: measured {measured[unit]:.0f} MB, but it has no ceiling yet")

    if breaches or missing:
        return 1
    print(f"OK: {len(budget_mb)} budgeted unit(s) within their ceilings (tolerance {TOLERANCE}).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--budget", type=Path, default=DEFAULT_BUDGET,
        help="the committed ceilings (default: scripts/runtime_budget.json)",
    )
    parser.add_argument(
        "--measured", type=Path,
        help='the nightly run\'s peaks, JSON {"unit": peak_rss_mb}; null means not measured',
    )
    parser.add_argument(
        "--emit-template", action="store_true",
        help="print a measured-file skeleton with null for every budgeted unit, and exit 0",
    )
    args = parser.parse_args(argv)

    try:
        ceilings = load_budget(args.budget)
        if args.emit_template:
            print(emit_template(sorted(ceilings)), end="")
            return 0
        if args.measured is None:
            parser.error("--measured is required unless --emit-template is given")
        measured = load_measured(args.measured, frozenset(ceilings))
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return verdict(ceilings, measured)


if __name__ == "__main__":
    sys.exit(main())
