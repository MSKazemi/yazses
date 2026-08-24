#!/bin/bash
# Two independent 4-repeat runs of large-v3, one per split, on an idle box.
# The published test-other table rests on a model that moved 2.83 points between two
# runs while six of its eight neighbours were bit-identical; this measures the spread
# directly, and on both splits, so "the instability is all in the insertions" stops
# being an inference from one run plus a mechanism.
# Each split writes its own artifact: one filename for both would have the second run
# silently displace the first, which is the failure that made this probe necessary.
cd ~/yazses || exit 1
PY=.venv/bin/python
log() { echo "=== $* $(date -u +%FT%TZ) load:$(cut -d\  -f1 /proc/loadavg)"; }
log start
$PY paper/benchmark/probes/largev3_repeat.py 4 test-other 200; log "lv3-other rc=$?"
$PY paper/benchmark/probes/largev3_repeat.py 4 test-clean 200; log "lv3-clean rc=$?"
echo SERIAL_X86B_LV3_DONE
