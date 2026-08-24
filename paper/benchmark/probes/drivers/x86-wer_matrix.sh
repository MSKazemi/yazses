#!/bin/bash
# The engine matrix docs/models.md asserts but never measured: does Parakeet really
# beat whisper-large-v3? Pinned to 4 threads on 4 dedicated cores so the WER is
# reproducible; RTF from this run is CONTENDED (6 diarization jobs share the box)
# and must not be published as a clean speed figure.
#
# `set -e` deliberately: the first attempt ran against a checkout predating the
# cpu_threads argument, every _build raised TypeError, and the script sailed past it
# and reported DONE in four seconds. A benchmark that continues after its subject
# failed to load is worse than one that stops.
set -euo pipefail
PY=~/yazses/.venv/bin/python
cd ~/yazses
date -u +"start %H:%M:%SZ"
echo "### fetch phase (network on: model weights only)"
unset HF_HUB_OFFLINE || true
$PY - <<'PY'
import sys
sys.path.insert(0, "paper/benchmark")
import bench_wer
bad = []
for label, engine, model in bench_wer.FULL_SPECS:
    try:
        bench_wer._build(engine, model, 4)
        print(f"[fetch] OK   {label} ({engine})", flush=True)
    except Exception as e:
        print(f"[fetch] FAIL {label} ({engine}): {type(e).__name__}: {e}", flush=True)
        bad.append(label)
if bad:
    raise SystemExit(f"[fetch] {len(bad)} model(s) unavailable: {bad}")
PY
echo "### matrix phase. load: $(uptime)"
export OMP_NUM_THREADS=4
taskset -c 8,9,10,11 $PY - <<'PY'
import json, sys
from datetime import datetime, timezone
sys.path.insert(0, "paper/benchmark")
import bench_wer
from _common import provenance
r = bench_wer.run(200, bench_wer.FULL_SPECS, cpu_threads=4)
stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
r["config"]["rtf_is_contended"] = True
r["config"]["contention_note"] = (
    "6 concurrent single-core diarization jobs on the same 16-core VM; the decode was "
    "pinned to 4 dedicated cores. WER is unaffected by contention, RTF is not -- read "
    "RTF from an uncontended run, never from this one."
)
open("$HOME/wer_matrix.json", "w").write(
    json.dumps({"provenance": provenance(stamp), **r}, indent=2))
PY
echo "### WER_MATRIX_DONE $(date -u +%H:%M:%SZ)"
