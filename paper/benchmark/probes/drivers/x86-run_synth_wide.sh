set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
cd ~/yazses
echo "=== synthetic corpus, swept over the range AMI says matters ==="
echo "The published sweep stopped at 0.9. If the synthetic minimum also sits above 1.0,"
echo "the corpus was never the problem -- the range was."
uv run --group benchmark --extra diarization --extra parakeet --extra moonshine python paper/benchmark/bench_diarization.py ~/meeting_corpus ~/synth_sweep_wide.json \
  --sweep --thresholds 0.5,0.7,0.9,1.0,1.1,1.2,1.3,1.4,1.6
echo "SYNTH_WIDE_DONE"
