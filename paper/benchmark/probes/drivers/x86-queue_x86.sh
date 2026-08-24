#!/bin/bash
# Run the remaining archive jobs one after another. Each writes into
# ~/yazses/paper/results/ via write_result(), so provenance is stamped.
cd ~/yazses || exit 1
PY=.venv/bin/python
while pgrep -f "bench_plausibility.py $HOME/ami16_corpus" >/dev/null; do sleep 60; done
echo "=== ami done $(date -u +%FT%TZ) ==="
$PY paper/benchmark/bench_plausibility.py ~/vox_corpus 0.9 plausibility-voxconverse-0.9
echo "=== vox09 rc=$? $(date -u +%FT%TZ) ==="
$PY paper/benchmark/bench_plausibility.py ~/vox_corpus 1.0 plausibility-voxconverse-1.0
echo "=== vox10 rc=$? $(date -u +%FT%TZ) ==="
$PY paper/benchmark/bench_diarization.py ~/ami16_corpus
echo "=== der rc=$? $(date -u +%FT%TZ) ==="
echo QUEUE_X86_DONE
