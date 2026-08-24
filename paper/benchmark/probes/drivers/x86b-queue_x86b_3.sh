#!/bin/bash
cd ~/yazses || exit 1
while pgrep -f "queue_x86b_2" >/dev/null; do sleep 60; done
echo "=== queue2 done $(date -u +%FT%TZ) ==="
# Re-run with per-utterance outcomes so the 4-in-200 differences can be tested
# pairwise (McNemar) instead of eyeballed.
.venv/bin/python paper/benchmark/bench_onset.py 200 2
echo "=== onset-paired rc=$? $(date -u +%FT%TZ) ==="
echo QUEUE_X86B3_DONE
