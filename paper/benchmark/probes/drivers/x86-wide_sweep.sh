set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
cd ~/yazses
echo "=== IS1009a only: does ANY threshold recover 4 speakers? ==="
uv run python paper/benchmark/bench_diarization.py ~/ami_one ~/ami_one_sweep.json --sweep \
  --thresholds 0.5,0.7,0.9,1.0,1.1,1.2,1.3,1.5,1.7,2.0
echo "WIDE_DONE"
