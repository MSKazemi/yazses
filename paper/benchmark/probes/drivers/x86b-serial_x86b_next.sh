#!/bin/bash
# Waits for serial_x86b.sh, then re-runs the beam sweep with the version of
# bench_beam.py that records per-utterance error counts. The published table is a
# grid of WERs a few hundredths of a point apart and nothing in the first artifact
# can say whether any of those gaps is real; totals cannot be paired.
# Waits by PID, not by name: pgrep cannot see a sleeping chain script, which is how
# two chains ended up running the same bench at once and inflated every RTF by 25%.
cd ~/yazses || exit 1
PY=.venv/bin/python
log() { echo "=== $* $(date -u +%FT%TZ) load:$(cut -d\  -f1 /proc/loadavg)"; }
while kill -0 570299 2>/dev/null; do sleep 60; done
log "serial_x86b finished"
$PY paper/benchmark/bench_beam.py 200 test-clean; log "beam-clean-paired rc=$?"
$PY paper/benchmark/bench_beam.py 200 test-other; log "beam-other-paired rc=$?"
echo SERIAL_X86B_NEXT_DONE
