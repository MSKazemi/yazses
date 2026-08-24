#!/bin/bash
cd ~/yazses || exit 1
PY=.venv/bin/python
while pgrep -f "bench_onset.py" >/dev/null; do sleep 60; done
echo "=== onset done $(date -u +%FT%TZ) ==="
$PY paper/benchmark/bench_beam.py 200 test-clean
echo "=== beam-clean rc=$? $(date -u +%FT%TZ) ==="
$PY paper/benchmark/bench_beam.py 200 test-other
echo "=== beam-other rc=$? $(date -u +%FT%TZ) ==="
echo QUEUE_X86B_DONE
