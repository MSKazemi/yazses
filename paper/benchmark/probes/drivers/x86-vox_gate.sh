#!/bin/bash
# The ADR-v2-133 gate, jumped to the front of the queue: does the AMI optimum of 1.2
# survive a different domain? The full sweep reaches 1.2 sixth, four hours from now,
# and the decision only needs this one point.
set -uo pipefail
PY=~/yazses/.venv/bin/python
cd ~/yazses
export HF_HUB_OFFLINE=1
date -u +"start %H:%M:%SZ"
$PY paper/benchmark/bench_diarization.py ~/vox_corpus ~/vox_gate.json --sweep --thresholds 1.2
echo "VOX_GATE_DONE $(date -u +%H:%M:%SZ)"
