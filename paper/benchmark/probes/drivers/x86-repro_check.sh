set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
cd ~/yazses
export HF_HUB_OFFLINE=1
while pgrep -f "run_wer_vm" >/dev/null 2>&1; do sleep 30; done
echo "=== WER reproducibility on one idle host: tiny.en, same 200 utterances ==="
for T in default default 1 4 16; do
  echo "--- intra_threads=$T ---"
  if [ "$T" = "default" ]; then unset OMP_NUM_THREADS; else export OMP_NUM_THREADS="$T"; fi
  uv run --group benchmark --extra parakeet --extra moonshine python - <<'PY'
import hashlib, json, os, sys
sys.path.insert(0, "paper/benchmark")
import bench_wer
from _common import librispeech_subset
ids = [u for u, _, _, _ in librispeech_subset(200, stratified=True)]
print("SUBSET", len(ids), hashlib.sha256("\n".join(ids).encode()).hexdigest()[:16])
r = bench_wer.run(200, [("tiny.en", "faster-whisper", "tiny.en")])
m = r["models"]["tiny.en"]
print("REPRO", os.environ.get("OMP_NUM_THREADS", "default"), json.dumps(
    {k: m[k] for k in ("wer","substitutions","deletions","insertions","hits","n_scored_utterances")}))
PY
done
echo "=== done ==="
