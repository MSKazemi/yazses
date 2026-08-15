"""Run the full YazSes benchmark suite and write results + provenance to paper/results/.

Usage:
    uv run python paper/benchmark/run_all.py [--wer-n N] [--lat-n N] [--vad-n N] [--coverage]

Every experiment is reproducible from the pinned `benchmark` dependency group and the
LibriSpeech test-clean download. Results land as JSON in paper/results/, each carrying
a shared provenance block (CPU/OS/versions/date).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import subprocess
import time

import bench_commands
import bench_latency
import bench_meta
import bench_streaming
import bench_vad
import bench_wer
from _common import RESULTS_DIR, provenance, write_result


def _now_iso() -> str:
    # new Date() is unavailable in workflow scripts, but this is a plain CLI run.
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _coverage() -> dict:
    """Run the full test suite under coverage; capture the TOTAL percentage."""
    print("[coverage] running full pytest suite under coverage (slow) ...", flush=True)
    t0 = time.monotonic()
    proc = subprocess.run(
        [
            "uv", "run", "python", "-m", "pytest", "tests",
            "--cov=yazses", "--cov-report=term", "-q",
        ],
        capture_output=True,
        text=True,
        cwd=str(RESULTS_DIR.parents[1]),
    )
    dur = time.monotonic() - t0
    total_pct = None
    passed = None
    for line in proc.stdout.splitlines():
        if line.startswith("TOTAL"):
            for tok in line.split():
                if tok.endswith("%"):
                    total_pct = tok
        if " passed" in line:
            passed = line.strip()
    return {
        "coverage_total": total_pct,
        "pytest_summary": passed,
        "duration_s": round(dur, 1),
        "returncode": proc.returncode,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wer-n", type=int, default=200)
    ap.add_argument("--lat-n", type=int, default=30)
    ap.add_argument("--vad-n", type=int, default=200)
    # Streaming feeds audio at real time by design, so it is the slowest bench per
    # utterance (>= the audio duration each). Smaller default sample for that reason.
    ap.add_argument("--stream-n", type=int, default=15)
    ap.add_argument("--coverage", action="store_true")
    ap.add_argument(
        "--skip",
        nargs="*",
        default=[],
        help="benches to skip: wer latency streaming commands vad meta",
    )
    args = ap.parse_args()

    ts = _now_iso()
    prov = provenance(ts)
    print(f"[run_all] provenance: {json.dumps(prov)}", flush=True)

    index: dict = {"provenance": prov, "results": {}}

    if "commands" not in args.skip:
        index["results"]["commands"] = bench_commands.run()
        write_result("commands", {"provenance": prov, **index["results"]["commands"]})
    if "vad" not in args.skip:
        index["results"]["vad"] = bench_vad.run(args.vad_n)
        write_result("vad", {"provenance": prov, **index["results"]["vad"]})
    if "wer" not in args.skip:
        index["results"]["wer"] = bench_wer.run(args.wer_n)
        write_result("wer", {"provenance": prov, **index["results"]["wer"]})
    if "latency" not in args.skip:
        index["results"]["latency"] = bench_latency.run(args.lat_n)
        write_result("latency", {"provenance": prov, **index["results"]["latency"]})
    if "streaming" not in args.skip:
        index["results"]["streaming"] = bench_streaming.run(args.stream_n)
        write_result("streaming", {"provenance": prov, **index["results"]["streaming"]})
    if "meta" not in args.skip:
        index["results"]["meta"] = bench_meta.run()
        write_result("meta", {"provenance": prov, **index["results"]["meta"]})
    if args.coverage:
        index["results"]["coverage"] = _coverage()
        write_result("coverage", {"provenance": prov, **index["results"]["coverage"]})

    write_result("index", index)
    print("[run_all] done. results in paper/results/", flush=True)


if __name__ == "__main__":
    main()
