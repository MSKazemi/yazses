#!/bin/bash
# Fills the gap the published beam grid leaves: `latency/governor.py` hardcodes
# beam_size=5 for its normal policy and 1 for its high-load policy, and the grid
# measured base.en at 1,2,3,5,8 but small.en only at 1 and 5 and tiny.en not at all.
# beam=2 turned out to be a dead heat with beam=5 on base.en while costing ~8% less
# decode, so whether that holds for the two models the governor actually selects is
# the question that decides whether the constant should move.
# Waits by PID: pgrep cannot see a sleeping chain script.
cd ~/yazses || exit 1
PY=.venv/bin/python
log() { echo "=== $* $(date -u +%FT%TZ) load:$(cut -d\  -f1 /proc/loadavg)"; }
while kill -0 980247 2>/dev/null; do sleep 60; done
log "largev3 chain finished"
$PY paper/benchmark/bench_beam.py 200 test-other --grid="tiny.en:1,2,5;small.en:2" --name=beam-governor-test-other; log "gov-other rc=$?"
$PY paper/benchmark/bench_beam.py 200 test-clean --grid="tiny.en:1,2,5;small.en:2" --name=beam-governor-test-clean; log "gov-clean rc=$?"
echo SERIAL_X86B_GOV_DONE
