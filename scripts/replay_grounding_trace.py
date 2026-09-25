#!/usr/bin/env python3
"""Replay grounding traces and print the wrong-target / ambiguity / abstention report.

The command-line front end for phase P4 of ``design/specs/eye-grounded-targets.md``
(ADR-v2-151). It reads checked-in trace files, validates them against the schema in
``src/yazses/grounding/trace.py``, replays every case through the real resolver under
each strategy, and prints one deterministic JSON document.

Usage::

    uv run python scripts/replay_grounding_trace.py                       # the fixtures
    uv run python scripts/replay_grounding_trace.py --check <report.json> # CI drift gate
    uv run python scripts/replay_grounding_trace.py --write <report.json> # regenerate
    uv run python scripts/replay_grounding_trace.py --trace <one.json>    # one file

Three properties are deliberate, and each is a failure this repository has shipped.

**It fails loudly on input it cannot read.** A trace that is missing, unreadable or not
valid JSON exits ``2`` and prints why; it never degrades into an empty document that then
passes every per-case check. A trace that parses but breaks a schema rule exits ``1``. The
same three-way contract as ``scripts/check_eye_validation_slots.py``.

**An empty trace set is an error, not an empty report.** Zero cases would make every rate
``0.0``, which in the output is indistinguishable from a run with no wrong targets. So a
trace with no cases is a rule violation, and a run that finds no trace files at all is
too.

**It is offline and clock-free.** No network, no environment lookup, no ``time`` call —
``now_s`` is a recorded field of each case. Running it twice on the same bytes gives the
same bytes back, which is what lets the committed report be reviewed in a diff.

Exit codes:

* ``0`` -- every trace is valid and, with ``--check``, the report matches;
* ``1`` -- a trace parsed but violates a rule, or the report drifted;
* ``2`` -- a trace could not be read or parsed at all.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from yazses.grounding.replay import (  # noqa: E402
    GroundingReplayError,
    ReplayReport,
    replay,
)
from yazses.grounding.trace import (  # noqa: E402
    GroundingTraceError,
    TraceCase,
    check_trace,
)

DEFAULT_TRACE_DIR = ROOT / "tests" / "fixtures" / "grounding_traces"
DEFAULT_REPORT = ROOT / "tests" / "fixtures" / "grounding_replay_report.json"


class TraceUnreadable(Exception):
    """The bytes could not become a document. Exit 2, never an empty result."""


def read_document(path: Path) -> Any:
    """Parse one trace file, or raise :class:`TraceUnreadable`."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise TraceUnreadable(f"{path}: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise TraceUnreadable(f"{path}: not valid JSON -- {exc}") from exc


def collect_cases(paths: list[Path]) -> tuple[list[TraceCase], list[str]]:
    """Validate every trace and return its cases, plus every rule violation found.

    Raises :class:`TraceUnreadable` on the first file that is not a document at all; a
    rule violation is collected so one bad trace does not hide the next one's problems.
    """
    cases: list[TraceCase] = []
    problems: list[str] = []
    for path in paths:
        document = read_document(path)
        try:
            trace = check_trace(document)
        except GroundingTraceError as exc:
            problems.append(f"{path.name}: {exc}")
            continue
        cases.extend(trace.cases)
    return cases, problems


def build_report(cases: list[TraceCase]) -> ReplayReport:
    return replay(cases)


def render(document: Any) -> str:
    """One canonical spelling, so a diff shows a changed number and nothing else."""
    return json.dumps(document, indent=2, sort_keys=False, ensure_ascii=False) + "\n"


def trace_paths(args: argparse.Namespace) -> list[Path]:
    if args.trace:
        return sorted(args.trace)
    return sorted(Path(args.trace_dir).glob("*.json"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--trace",
        type=Path,
        action="append",
        help="a single trace file; repeatable. Defaults to every *.json in --trace-dir.",
    )
    parser.add_argument(
        "--trace-dir",
        type=Path,
        default=DEFAULT_TRACE_DIR,
        help="directory of trace files (default: %(default)s)",
    )
    parser.add_argument(
        "--check",
        type=Path,
        nargs="?",
        const=DEFAULT_REPORT,
        help="compare the report against this file and exit 1 if it drifted",
    )
    parser.add_argument(
        "--write",
        type=Path,
        nargs="?",
        const=DEFAULT_REPORT,
        help="write the report to this file instead of stdout",
    )
    args = parser.parse_args(argv)

    paths = trace_paths(args)
    if not paths:
        print(
            f"No trace files found under {args.trace_dir}. Refusing to report on zero "
            f"trials: every rate would be 0.0, which reads as a perfect run.",
            file=sys.stderr,
        )
        return 1

    try:
        cases, problems = collect_cases(paths)
    except TraceUnreadable as exc:
        print(f"Grounding trace could not be read: {exc}", file=sys.stderr)
        return 2

    if problems:
        print("Grounding trace problems:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    try:
        document = build_report(cases).to_document()
    except GroundingReplayError as exc:
        print(f"Grounding replay refused to report: {exc}", file=sys.stderr)
        return 1

    text = render(document)

    if args.check is not None:
        try:
            current = Path(args.check).read_text(encoding="utf-8")
        except OSError as exc:
            print(f"Report could not be read: {exc}", file=sys.stderr)
            return 2
        if current != text:
            print(
                f"{args.check} is out of date. Regenerate it with:\n"
                f"  uv run python scripts/replay_grounding_trace.py --write",
                file=sys.stderr,
            )
            return 1
        print(
            f"Grounding replay report is current "
            f"({document['total_trials']} trials from {len(paths)} traces)."
        )
        return 0

    if args.write is not None:
        Path(args.write).write_text(text, encoding="utf-8")
        print(
            f"Wrote {args.write} "
            f"({document['total_trials']} trials from {len(paths)} traces)."
        )
        return 0

    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
