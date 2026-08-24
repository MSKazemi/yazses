#!/bin/bash
cd ~/yazses
while pgrep -f "bench_onset.py 200 2" >/dev/null; do sleep 60; done
.venv/bin/python paper/benchmark/bench_beam.py 200 test-clean  >> ~/chain_x86b.log 2>&1
.venv/bin/python paper/benchmark/bench_beam.py 200 test-other  >> ~/chain_x86b.log 2>&1
.venv/bin/python paper/benchmark/bench_wer.py 200 full --split test-other >> ~/chain_x86b.log 2>&1
echo CHAIN_X86B_DONE >> ~/chain_x86b.log
