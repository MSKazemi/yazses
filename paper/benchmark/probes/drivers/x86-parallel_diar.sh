set -uo pipefail
PY=~/yazses/.venv/bin/python
cd ~/yazses
# DER is deterministic, so these may share the box; the venv is pre-synced and every
# job calls the interpreter directly, so no two `uv run` invocations can race on it.
nohup $PY ~/embmodel_test2.py > ~/embtest2.log 2>&1 &
echo "embtest2 pid $!"
nohup $PY paper/benchmark/bench_diarization.py ~/meeting_corpus ~/synth_sweep_wide.json \
  --sweep --thresholds 0.5,0.7,0.9,1.0,1.1,1.2,1.3,1.4,1.6 > ~/synth_wide.log 2>&1 &
echo "synth_wide pid $!"
nohup $PY paper/benchmark/bench_diarization.py ~/ami_corpus ~/ami_maxspk4.json \
  --max-speakers 4 > ~/maxspk.log 2>&1 &
echo "maxspk pid $!"
