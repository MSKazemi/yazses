#!/bin/bash
# ONE chain. Two overlapping chains ran bench_beam twice at once and inflated every
# RTF by ~25%; a timing run owns the box or it is not a timing run.
cd ~/yazses || exit 1
PY=.venv/bin/python
log() { echo "=== $* $(date -u +%FT%TZ) load:$(cut -d\  -f1 /proc/loadavg)"; }
log START
$PY paper/benchmark/bench_beam.py 200 test-clean;  log "beam-clean rc=$?"
$PY paper/benchmark/bench_beam.py 200 test-other;  log "beam-other rc=$?"
$PY paper/benchmark/bench_wer.py 200 full --split test-other; log "wer-other rc=$?"
$PY paper/benchmark/bench_onset.py 200 2;          log "onset-paired rc=$?"
echo SERIAL_X86B_DONE
