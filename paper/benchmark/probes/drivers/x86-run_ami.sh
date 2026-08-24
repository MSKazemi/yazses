set -euo pipefail
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
cd ~/yazses
echo "=== AMI: shipped default (cluster_threshold=0.5) ==="
date -u +"start %H:%M:%SZ"
uv run python paper/benchmark/bench_diarization.py ~/ami_corpus ~/ami_der.json
date -u +"done %H:%M:%SZ"
echo "=== AMI: cluster_threshold sweep ==="
uv run python paper/benchmark/bench_diarization.py ~/ami_corpus ~/ami_sweep.json --sweep
date -u +"sweep done %H:%M:%SZ"
echo "AMI_ALL_DONE"
