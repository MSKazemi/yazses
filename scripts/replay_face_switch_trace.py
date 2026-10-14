#!/usr/bin/env python3
"""Replay face-switch traces and print the false-activation / recall / latency / chatter report.

The command-line front end for EYE-BENCH-001 (#409) and ``design/eye-control/ROADMAP.md``
P5.4. It reads checked-in numeric traces, validates them against the schema in
``src/yazses/eyeeval/switch_trace.py``, replays every one through the real
``GestureSwitch`` and ``SwitchMapper`` (``src/yazses/eyeeval/switch_replay.py``) and prints
one deterministic JSON document -- the same shape of tool as ``replay_grounding_trace.py``.

Usage::

    uv run python scripts/replay_face_switch_trace.py                      # the fixtures
    uv run python scripts/replay_face_switch_trace.py --check              # CI drift gate
    uv run python scripts/replay_face_switch_trace.py --write              # regenerate
    uv run python scripts/replay_face_switch_trace.py --trace one.json     # one file
    uv run python scripts/replay_face_switch_trace.py --sweep 0.3,0.35,0.4 # your own grid
    uv run python scripts/replay_face_switch_trace.py --use-trace-baseline # apply the trace's baseline

The report carries a ``no_threshold_notice``: the sweep shows a phantom/recall trade-off on
the traces it ran on, and on the checked-in synthetic ones it licenses no default.

Three properties are deliberate, and each is a failure this repository has shipped.

**It fails loudly on input it cannot read.** A trace that is missing, unreadable or not
valid JSON exits ``2`` and prints why; it never degrades into an empty document that then
passes every check. A trace that parses but breaks a schema rule exits ``1``.

**An empty trace set, an empty trace or an empty sweep is an error, not an empty report.**
Zero samples would make every rate ``0.0``, which in the output is indistinguishable from a
switch that never misfires.

**It is offline and clock-free.** No network, no environment lookup, no ``time`` call --
time is the sample index over each trace's ``sample_rate_hz``. Running it twice on the same
bytes gives the same bytes back, which is what lets the committed report be reviewed in a
diff.

Exit codes:

* ``0`` -- every trace is valid and, with ``--check``, the report matches;
* ``1`` -- a trace parsed but violates a rule, an argument is refused, or the report drifted;
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

from yazses.eyeeval.switch_replay import (  # noqa: E402
    SwitchConfig,
    SwitchReplayError,
    replay_traces,
)
from yazses.eyeeval.switch_trace import (  # noqa: E402
    SwitchTrace,
    SwitchTraceError,
    check_trace,
)

DEFAULT_TRACE_DIR = ROOT / "tests" / "fixtures" / "face_switch_traces"
DEFAULT_REPORT = ROOT / "tests" / "fixtures" / "face_switch_replay_report.json"

#: A grid to look at, not a set of candidates. It spans the range the synthetic fixtures
#: need to show a trade-off and recommends nothing.
DEFAULT_SWEEP = (0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.6)


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


def collect_traces(paths: list[Path]) -> tuple[list[SwitchTrace], list[str]]:
    """Validate every trace; return the good ones and every rule violation found."""
    traces: list[SwitchTrace] = []
    problems: list[str] = []
    for path in paths:
        document = read_document(path)
        try:
            traces.append(check_trace(document))
        except SwitchTraceError as exc:
            problems.append(f"{path.name}: {exc}")
    return traces, problems


def render(document: Any) -> str:
    """One canonical spelling, so a diff shows a changed number and nothing else."""
    return json.dumps(document, indent=2, sort_keys=False, ensure_ascii=False) + "\n"


def parse_sweep(text: str) -> list[float]:
    """``"0.3,0.35"`` -> ``[0.3, 0.35]``. An empty or unparseable list is refused, not ignored."""
    parts = [p.strip() for p in text.split(",")]
    if not text.strip() or any(not p for p in parts):
        raise SwitchReplayError("--sweep needs a comma-separated list of hold thresholds, e.g. 0.3,0.35,0.4")
    try:
        return [float(p) for p in parts]
    except ValueError as exc:
        raise SwitchReplayError(f"--sweep: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    defaults = SwitchConfig()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--trace", type=Path, action="append",
                        help="a single trace file; repeatable. Defaults to every *.json in --trace-dir.")
    parser.add_argument("--trace-dir", type=Path, default=DEFAULT_TRACE_DIR,
                        help="directory of trace files (default: %(default)s)")
    parser.add_argument("--check", type=Path, nargs="?", const=DEFAULT_REPORT,
                        help="compare the report against this file and exit 1 if it drifted")
    parser.add_argument("--write", type=Path, nargs="?", const=DEFAULT_REPORT,
                        help="write the report to this file instead of stdout")
    parser.add_argument("--sweep", default=",".join(str(v) for v in DEFAULT_SWEEP),
                        help="comma-separated hold thresholds to replay over the same traces "
                        "(default: %(default)s)")
    parser.add_argument("--no-sweep", action="store_true", help="report the single configuration only")
    parser.add_argument("--hold-threshold", type=float, default=defaults.hold_threshold)
    parser.add_argument("--release-threshold", type=float, default=defaults.release_threshold)
    parser.add_argument("--min-hold-frames", type=int, default=defaults.min_hold_frames)
    parser.add_argument("--min-release-frames", type=int, default=defaults.min_release_frames)
    parser.add_argument("--confidence-floor", type=float, default=defaults.confidence_floor)
    parser.add_argument("--refractory-frames", type=int, default=defaults.refractory_frames)
    parser.add_argument("--match-grace-samples", type=int, default=defaults.match_grace_samples)
    parser.add_argument("--use-trace-baseline", action="store_true",
                        help="apply the baseline level a trace declares, as a calibrated install would")
    args = parser.parse_args(argv)

    paths = sorted(args.trace) if args.trace else sorted(Path(args.trace_dir).glob("*.json"))
    if not paths:
        print(f"No trace files found under {args.trace_dir}. Refusing to report on zero traces: "
              f"every rate would be 0.0, which reads as a switch that never misfires.", file=sys.stderr)
        return 1

    try:
        traces, problems = collect_traces(paths)
    except TraceUnreadable as exc:
        print(f"Face-switch trace could not be read: {exc}", file=sys.stderr)
        return 2
    if problems:
        print("Face-switch trace problems:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    config = SwitchConfig(
        hold_threshold=args.hold_threshold,
        release_threshold=args.release_threshold,
        min_hold_frames=args.min_hold_frames,
        min_release_frames=args.min_release_frames,
        confidence_floor=args.confidence_floor,
        refractory_frames=args.refractory_frames,
        use_trace_baseline=args.use_trace_baseline,
        match_grace_samples=args.match_grace_samples,
    )
    try:
        sweep = None if args.no_sweep else parse_sweep(args.sweep)
        document = replay_traces(traces, config, sweep=sweep)
    except SwitchReplayError as exc:
        print(f"Face-switch replay refused to report: {exc}", file=sys.stderr)
        return 1

    text = render(document)
    summary = f"({document['total_traces']} traces, {len(document.get('sweep', []))} sweep rows)"

    if args.check is not None:
        try:
            current = Path(args.check).read_text(encoding="utf-8")
        except OSError as exc:
            print(f"Report could not be read: {exc}", file=sys.stderr)
            return 2
        if current != text:
            print(f"{args.check} is out of date. Regenerate it with:\n"
                  f"  uv run python scripts/replay_face_switch_trace.py --write", file=sys.stderr)
            return 1
        print(f"Face-switch replay report is current {summary}.")
        return 0

    if args.write is not None:
        Path(args.write).write_text(text, encoding="utf-8")
        print(f"Wrote {args.write} {summary}.")
        return 0

    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
