#!/usr/bin/env python3
"""Decide the one stable `ci-gate` status from the results of `test.yml`'s jobs (#535).

`test.yml` skips its full cross-platform lane when the change classifier says a pull
request does not need it. A skipped job reports `skipped`, and GitHub treats a skipped
required check as passing — so requiring the individual jobs would let a broken
classifier wave a PR through. Instead the `ci-gate` job depends on every blocking job and
runs this script, and that one status is what a branch ruleset requires (#462).

The rules:

- a job in the fast lane or the Linux baseline must have succeeded, always;
- a full-lane job must have succeeded when the full lane was selected, and must have been
  skipped (or succeeded) when it was not;
- `failure`, `cancelled`, or any result this script does not know, fails the gate;
- so does a `full` decision that is neither `true` nor `false`: a classifier that
  crashed or printed nothing must not read as "the fast lane was enough".

Inputs arrive as environment variables, never interpolated into shell code:

    NEEDS='${{ toJSON(needs) }}' FULL='${{ needs.changes.outputs.full }}' \\
        python3 scripts/ci_gate.py
"""

from __future__ import annotations

import json
import os
import sys

#: Jobs that only run when the change needs the full lane. `tests/test_ci_lanes.py`
#: fails if this drifts from the jobs `test.yml` actually gates on the decision.
FULL_LANE_JOBS = frozenset({"test", "gui", "extras", "benchmark-harness"})


def verdict(needs: dict[str, dict], full: str) -> list[str]:
    """Return one problem per job that makes the gate fail; an empty list means green."""
    problems = []
    if full not in ("true", "false"):
        problems.append(f"the lane decision is {full!r}, not 'true' or 'false'")
    for job, info in sorted(needs.items()):
        result = info.get("result") if isinstance(info, dict) else None
        if result == "success":
            continue
        if result == "skipped" and job in FULL_LANE_JOBS and full == "false":
            continue
        problems.append(f"{job}: {result}")
    return problems


def main() -> int:
    try:
        needs = json.loads(os.environ.get("NEEDS", ""))
    except json.JSONDecodeError:
        print("::error::ci-gate could not read the job results")
        return 1
    if not isinstance(needs, dict) or not needs:
        print("::error::ci-gate was given no job results")
        return 1
    full = os.environ.get("FULL", "")
    problems = verdict(needs, full)
    for problem in problems:
        print(f"::error::{problem}")
    if problems:
        return 1
    lane = "full" if full == "true" else "fast + Linux baseline"
    print(f"ci-gate: every blocking job selected for this change passed ({lane}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
