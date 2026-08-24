set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
# One serial queue. Two reasons it must be serial rather than four background jobs:
#  * `uv run --extra X` re-syncs the SHARED .venv, so a job with different extras
#    uninstalls the module a concurrently running job already needs (this killed the
#    first 4-meeting sweep with ModuleNotFoundError: sherpa_onnx);
#  * the last job measures wall-clock RTF and is worthless on a contended box.
# Every invocation therefore uses one superset environment, and nothing overlaps.
# Wait for whatever is still running from before the queue existed.
while pgrep -f "bench_diarization|embmodel_test" >/dev/null 2>&1; do sleep 30; done
sleep 10
echo "### queue start $(date -u +%H:%M:%SZ)  load: $(uptime)"
for s in run_ami2 run_maxspk run_embtest2 run_synth_wide clean_wer; do
  echo "### >>> $s  $(date -u +%H:%M:%SZ)"
  bash ~/$s.sh 2>&1 | tee ~/$s.log
  echo "### <<< $s exit=${PIPESTATUS[0]} $(date -u +%H:%M:%SZ)"
done
echo "### QUEUE DONE $(date -u +%H:%M:%SZ)"
