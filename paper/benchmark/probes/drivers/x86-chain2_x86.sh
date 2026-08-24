#!/bin/bash
cd ~/yazses
while pgrep -f "bench_plausibility.py $HOME/" >/dev/null; do sleep 60; done
.venv/bin/python paper/benchmark/bench_diarization.py ~/ami16_corpus >> ~/chain2_x86.log 2>&1
echo CHAIN2_DONE >> ~/chain2_x86.log
