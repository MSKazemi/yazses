#!/bin/bash
cd ~/yazses
while pgrep -f "bench_plausibility.py $HOME/ami16_corpus" >/dev/null; do sleep 30; done
.venv/bin/python paper/benchmark/bench_plausibility.py ~/vox_corpus 0.9 plausibility-voxconverse-0.9 >> ~/guard_vox_bench.log 2>&1
.venv/bin/python paper/benchmark/bench_plausibility.py ~/vox_corpus 1.0 plausibility-voxconverse-1.0 >> ~/guard_vox_bench.log 2>&1
echo CHAIN_DONE >> ~/guard_vox_bench.log
