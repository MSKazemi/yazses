#!/bin/bash
cd ~/yazses
echo "start $(date -u +%H:%M:%SZ)"
for t in 0.9 1.0 1.1 1.2 1.3; do
  .venv/bin/python paper/benchmark/bench_diarization.py ~/ami_one ~/guard_$t.json \
      --thresholds $t --sweep --dump-rttm ~/guard_hyp_$t 2>&1 | grep -E "^\[sweep\]|^\[der\]"
  echo "  dumped: $(ls ~/guard_hyp_$t/ 2>/dev/null | tr '\n' ' ')"
done
echo "GUARD_SWEEP_DONE $(date -u +%H:%M:%SZ)"
