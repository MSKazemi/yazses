set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
export HF_HUB_OFFLINE=1
cd ~/yazses
# The whole point of this run is an uncontended box: wait for every diarization job.
sleep 20
echo "=== box is idle: $(uptime) ==="
echo "### PART 1 -- authoritative engine matrix, nothing else running"
date -u +"start %H:%M:%SZ"
uv run --group benchmark --extra diarization --extra parakeet --extra moonshine python - <<'PY'
import json, sys
sys.path.insert(0, "paper/benchmark")
import bench_wer
r = bench_wer.run(200, bench_wer.FULL_SPECS)
open("$HOME/wer_vm_clean.json", "w").write(json.dumps(r, indent=2))
PY
date -u +"end %H:%M:%SZ"
echo "### PART 2 -- is WER reproducible on one host? tiny.en, same 200 utterances"
for T in default default 1 4 16; do
  if [ "$T" = "default" ]; then unset OMP_NUM_THREADS; else export OMP_NUM_THREADS="$T"; fi
  uv run --group benchmark --extra diarization --extra parakeet --extra moonshine python - <<'PY'
import hashlib, json, os, sys
sys.path.insert(0, "paper/benchmark")
import bench_wer
from _common import librispeech_subset
ids = [u for u, _, _, _ in librispeech_subset(200, stratified=True)]
r = bench_wer.run(200, [("tiny.en", "faster-whisper", "tiny.en")])
m = r["models"]["tiny.en"]
print("REPRO threads=" + os.environ.get("OMP_NUM_THREADS", "default"),
      "subset=" + hashlib.sha256("\n".join(ids).encode()).hexdigest()[:16],
      json.dumps({k: m[k] for k in ("wer","substitutions","deletions","insertions","hits")}),
      flush=True)
PY
done
echo "=== done ==="
