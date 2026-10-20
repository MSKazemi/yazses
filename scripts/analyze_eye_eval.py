#!/usr/bin/env python3
"""Reproducible, provisional analysis of de-identified eye-control evaluation results (#426).

    uv run python scripts/analyze_eye_eval.py --unit participant --links links.json results/
    uv run python scripts/analyze_eye_eval.py --unit run --study-mode ci --format json ci/*.json

Reads result files that pass the versioned schema (`scripts/check_eye_eval_result.py`) and
prints outcome shares with Wilson intervals, false activations per hour of exposure,
per-unit grouping, within-participant session spread and per-host latency -- descriptively,
with no inferential test (the analysis plan is frozen in #425). All the logic is in
`yazses.eyeeval.analysis`; read its docstring for the rules (refusals, minimums, the
participant / session / pilot *links file*, what a number is allowed to mean).

It refuses, rather than repairs: a schema-invalid or identifier-carrying result, a mix of
study modes (a `community_qa` row never enters a `research` analysis), a repeated file, or
counts that do not add up. Rates below the provisional minimum print `insufficient data`.
Output is deterministic and labelled provisional; nothing is written unless --out is given.
Real participant data stays out of the repository: point this at files outside the tree.

Exit codes: 0 report produced; 1 analysis refused; 2 usage error.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from yazses.eyeeval.analysis import (  # noqa: E402
    DEFAULT_MIN_EXPOSURE_S,
    DEFAULT_MIN_TRIALS,
    DEFAULT_MIN_UNITS,
    UNITS,
    EyeAnalysisError,
    analyze,
    dump_report,
    render_markdown,
)
from yazses.eyeeval.schema import STUDY_MODES  # noqa: E402


def _gather(paths: Sequence[Path]) -> list[tuple[str, bytes]]:
    files: list[Path] = []
    for path in paths:
        files += sorted(path.glob("*.json")) if path.is_dir() else [path]
    return [(p.name, p.read_bytes()) for p in files]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("results", nargs="*", type=Path, help="result JSON files, or directories of *.json")
    parser.add_argument("--unit", required=True, choices=UNITS, help="aggregation unit (never assumed)")
    parser.add_argument("--links", type=Path, help="links file: result -> participant / session / pilot")
    parser.add_argument("--study-mode", default="research", choices=STUDY_MODES)
    parser.add_argument("--include-pilot", action="store_true", help="analyse pilot rows (exploratory)")
    parser.add_argument("--min-trials", type=int, default=DEFAULT_MIN_TRIALS, help="provisional floor")
    parser.add_argument("--min-units", type=int, default=DEFAULT_MIN_UNITS, help="provisional floor")
    parser.add_argument("--min-exposure-s", type=float, default=DEFAULT_MIN_EXPOSURE_S, help="provisional floor")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--out", type=Path, help="write the report here instead of stdout")
    args = parser.parse_args(argv)
    if not args.results:
        print("No result file named; nothing was analysed.", file=sys.stderr)
        return 2
    try:
        inputs = _gather(args.results)
        links_text = args.links.read_bytes().decode("utf-8-sig") if args.links else None
    except (OSError, UnicodeDecodeError) as exc:
        print(f"REFUSED: cannot read an input ({exc}).", file=sys.stderr)
        return 1
    try:
        report = analyze(
            inputs, unit=args.unit, links_text=links_text, study_mode=args.study_mode,
            include_pilot=args.include_pilot, min_trials=args.min_trials,
            min_units=args.min_units, min_exposure_s=args.min_exposure_s,
        )
    except EyeAnalysisError as exc:
        print("REFUSED:", file=sys.stderr)
        print("  - " + "\n  - ".join(exc.problems), file=sys.stderr)
        return 1
    text = dump_report(report) if args.format == "json" else render_markdown(report)
    if args.out:
        args.out.write_bytes(text.encode("utf-8"))  # bytes: the same file on every OS
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
