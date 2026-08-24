#!/bin/bash
# Prove the Moonshine fix against the REAL model, not a double. The unit tests cannot
# reach this: they mock the package, and the package is what rejected the shape.
set -euo pipefail
PY=~/yazses/.venv/bin/python
cd ~/yazses
date -u +"start %H:%M:%SZ"
export OMP_NUM_THREADS=2
taskset -c 14,15 $PY - <<'PY'
import sys
sys.path.insert(0, "paper/benchmark")
import bench_wer
specs = [(l, e, m) for (l, e, m) in bench_wer.FULL_SPECS if e == "moonshine"]
print("specs:", specs, flush=True)
r = bench_wer.run(25, specs, cpu_threads=2)
for name, d in r["models"].items():
    print(f"[moon] {name}: WER={d['wer']}%  ins={d['insertions']} sub={d['substitutions']} del={d['deletions']}", flush=True)
PY
echo "MOON_DONE $(date -u +%H:%M:%SZ)"
