set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
cd ~/yazses
echo "=== AMI 4 meetings: cluster_threshold over the range the wide sweep says matters ==="
date -u +"start %H:%M:%SZ"
uv run --group benchmark --extra diarization --extra parakeet --extra moonshine python paper/benchmark/bench_diarization.py ~/ami_corpus ~/ami_sweep2.json \
  --sweep --thresholds 0.9,1.0,1.1,1.2,1.3,1.4,1.6
date -u +"end %H:%M:%SZ"
echo "AMI_SWEEP2_DONE"
