#!/bin/bash
# The gate answered the yes/no question (1.2 does NOT transfer: 42.13% on VoxConverse
# against 27.07% on AMI). This locates VoxConverse's own optimum so the ADR can say
# where each domain's cut height sits rather than only that they differ. 0.7 already
# beats the shipped 0.5 by 17 pp here, so 0.5 is not optimal on any corpus measured.
set -euo pipefail
PY=~/yazses/.venv/bin/python
cd ~/yazses
export HF_HUB_OFFLINE=1
date -u +"start %H:%M:%SZ"
$PY paper/benchmark/bench_diarization.py ~/vox_corpus ~/vox_optimum.json --sweep --thresholds 0.6,0.8,0.9
echo "VOX_OPTIMUM_DONE $(date -u +%H:%M:%SZ)"
