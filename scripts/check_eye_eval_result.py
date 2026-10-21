#!/usr/bin/env python3
"""Check eye-control evaluation result files against the versioned schema.

    uv run python scripts/check_eye_eval_result.py result.json [more.json ...]

`yazses.eyeeval.schema` is the contract (`design/eye-control/METRICS.md`); this is its
command-line door, for a result someone *else* produced -- an attachment on a public issue, a
file from another machine -- where the producer's own pre-write validation cannot be trusted
to have run. It is offline and stdlib-plus-yazses only.

It fails loudly on input it cannot read. A file that is missing, a directory, empty, not
UTF-8, not JSON, nested absurdly deep, carrying a repeated key or a `NaN` is a *reported
problem*, never an empty document that then passes every per-field check. Naming no file at
all is a usage error rather than a vacuous pass, because a guard that iterates is green on
an empty collection.

Two layers, as in `yazses eye-eval` itself: the schema (`validate_result_text`), then the
value sweep for a home directory or an email address (`privacy_problems`). The sweep here
knows no machine-specific name -- it is checking someone else's file -- so it catches the
patterns, not this host's login. A gaze field report (`yazses gaze measure`, attached to
issue #104) gets a third: its own schema, which refuses any list or object it does not define
and any field named for raw gaze, so per-sample coordinates cannot ride along.

A later minor version of the same major is accepted and a note is printed (stdout, not an
error): fields added since this reader's version were not checked.

Exit codes:

* ``0`` -- every file is valid;
* ``1`` -- at least one file is invalid or unreadable;
* ``2`` -- usage error (no file named).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from yazses.eyeeval import compatibility_note, privacy_problems, validate_result_file  # noqa: E402
from yazses.eyeeval.gaze_field import TASK as GAZE_FIELD_TASK  # noqa: E402
from yazses.eyeeval.gaze_field import report_problems as gaze_field_problems  # noqa: E402


def check_file(path: Path) -> tuple[list[str], str | None]:
    """``(problems, note)`` for one file. Never raises for bad content.

    A gaze field report (``protocol.task == "gaze_field_measurement"``, the #104 attachment)
    is also held to its own schema, which refuses any per-sample series or raw-gaze field
    the envelope alone would let through (`yazses.eyeeval.gaze_field.report_problems`).
    """
    problems = validate_result_file(path)
    if problems:
        return problems, None
    # The file already parsed cleanly above, so this read cannot be the unreadable case.
    doc = json.loads(path.read_bytes().decode("utf-8-sig"))
    protocol = doc.get("protocol") if isinstance(doc, dict) else None
    if isinstance(protocol, dict) and protocol.get("task") == GAZE_FIELD_TASK:
        return gaze_field_problems(doc), compatibility_note(doc)
    return privacy_problems(doc), compatibility_note(doc)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("files", nargs="*", type=Path, help="result JSON file(s) to check")
    args = parser.parse_args(argv)
    if not args.files:
        print("No result file named; nothing was checked.", file=sys.stderr)
        return 2

    failed = 0
    for path in args.files:
        problems, note = check_file(path)
        if problems:
            failed += 1
            print(f"INVALID {path}", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            continue
        print(f"OK      {path}")
        if note:
            print(f"  note: {note}")
    if failed:
        print(f"{failed} of {len(args.files)} file(s) invalid.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
