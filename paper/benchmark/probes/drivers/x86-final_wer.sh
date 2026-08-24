set -uo pipefail
PY=~/yazses/.venv/bin/python
cd ~/yazses
export HF_HUB_OFFLINE=1
# The only job on this box that measures wall-clock time, so it waits for every other
# one -- including the VoxConverse fetch, which competes for I/O.
while pgrep -f "bench_diarization|embmodel_test|make_corpus|fetch_vox2|run_vox" >/dev/null 2>&1; do sleep 60; done
sleep 20
echo "### PART 1 -- authoritative engine matrix. load: $(uptime)"
date -u +"start %H:%M:%SZ"
$PY - <<'PY'
import json, sys
sys.path.insert(0, "paper/benchmark")
import bench_wer
r = bench_wer.run(200, bench_wer.FULL_SPECS)
sys.path.insert(0, "paper/benchmark")
from _common import provenance
from datetime import datetime, timezone
stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
open("$HOME/wer_vm_clean.json", "w").write(
    json.dumps({"provenance": provenance(stamp), **r}, indent=2))
PY
date -u +"end %H:%M:%SZ"
echo "### PART 2 -- is WER reproducible on one host? tiny.en, same 200 utterances"
for T in default default 1 4 16; do
  if [ "$T" = "default" ]; then unset OMP_NUM_THREADS; else export OMP_NUM_THREADS="$T"; fi
  $PY - <<'PY'
import hashlib, json, os, sys
sys.path.insert(0, "paper/benchmark")
import bench_wer
from _common import librispeech_subset
ids = [u for u, _, _, _ in librispeech_subset(200, stratified=True)]
m = bench_wer.run(200, [("tiny.en", "faster-whisper", "tiny.en")])["models"]["tiny.en"]
print("REPRO threads=" + os.environ.get("OMP_NUM_THREADS", "default"),
      "subset=" + hashlib.sha256("\n".join(ids).encode()).hexdigest()[:16],
      json.dumps({k: m[k] for k in ("wer","substitutions","deletions","insertions","hits")}),
      flush=True)
PY
done
echo "### CLEAN_WER DONE $(date -u +%H:%M:%SZ)"
