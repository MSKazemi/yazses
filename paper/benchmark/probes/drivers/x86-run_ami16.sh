#!/bin/bash
# The FULL AMI test split (16 meetings), not the 4-meeting subset. Three
# configurations, run as three processes so they finish in one pass rather than three.
set -uo pipefail
PY=~/yazses/.venv/bin/python
cd ~/yazses
export HF_HUB_OFFLINE=1
date -u +"start %H:%M:%SZ"
$PY paper/benchmark/make_corpus.py ami ~/ami16/wav ~/ami16/rttm ~/ami16_corpus 600 \
  > ~/ami16_build.log 2>&1 || { echo "BUILD FAILED"; tail -20 ~/ami16_build.log; exit 1; }
$PY - <<'PY'
import json
m = json.load(open("$HOME/ami16_corpus/manifest.json"))
ids = m.get("recordings") or m.get("ids") or []
print("[ami16] recordings:", len(ids))
print("[ami16]", " ".join(sorted(ids if isinstance(ids, list) else ids.keys())))
PY

( $PY paper/benchmark/bench_diarization.py ~/ami16_corpus ~/ami16_shipped.json \
    > ~/ami16_shipped.log 2>&1; echo "AMI16_SHIPPED_DONE" ) &
( $PY paper/benchmark/bench_diarization.py ~/ami16_corpus ~/ami16_thr12.json \
    --thresholds 1.2 --sweep > ~/ami16_thr12.log 2>&1; echo "AMI16_THR12_DONE" ) &
( $PY paper/benchmark/bench_diarization.py ~/ami16_corpus ~/ami16_maxspk.json \
    --max-speakers 4 > ~/ami16_maxspk.log 2>&1; echo "AMI16_MAXSPK_DONE" ) &
wait
echo "### AMI16 ALL DONE $(date -u +%H:%M:%SZ)"
grep -h "DER" ~/ami16_shipped.log ~/ami16_thr12.log ~/ami16_maxspk.log 2>/dev/null | tail -20
