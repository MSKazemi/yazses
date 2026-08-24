#!/bin/bash
# ONE chain on this box, rebuilt 2026-08-24 after the first diarization run was found
# to be measuring `RecimportConfig`'s 1.0 (and, on a stale checkout, 0.5) against AMI,
# which is the Meeting Mode corpus and ships 1.2. Every run below now names the
# profile whose shipped default it is testing.
cd ~/yazses || exit 1
PY=.venv/bin/python
log() { echo "=== $* $(date -u +%FT%TZ) load:$(cut -d\  -f1 /proc/loadavg)"; }
log "start"
$PY paper/benchmark/bench_diarization.py ~/ami16_corpus --profile meeting; log "der-ami rc=$?"
$PY paper/benchmark/bench_plausibility.py ~/vox_corpus 0.9 plausibility-voxconverse-0.9; log "vox09 rc=$?"
$PY paper/benchmark/bench_plausibility.py ~/vox_corpus 1.0 plausibility-voxconverse-1.0; log "vox10 rc=$?"
$PY paper/benchmark/probes/largev3_repeat.py 4 test-other 200; log "largev3 rc=$?"
echo SERIAL_X86_DONE
