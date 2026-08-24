set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
cd ~/yazses
echo "=== benchmark group ==="
uv sync --group benchmark --extra parakeet --extra moonshine 2>&1 | tail -3
echo "=== librispeech test-clean ==="
mkdir -p paper/data && cd paper/data
if [ ! -d LibriSpeech/test-clean ]; then
  curl -fsSL -O https://www.openslr.org/resources/12/test-clean.tar.gz
  tar -xzf test-clean.tar.gz
fi
du -sh LibriSpeech 2>/dev/null
cd ~/yazses
echo "=== full engine matrix, idle host ==="
date -u +"start %H:%M:%SZ"
uv run python - <<'PY'
import datetime as dt, json, sys
sys.path.insert(0, "paper/benchmark")
import bench_wer
from _common import provenance
ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
res = {"provenance": provenance(ts), **bench_wer.run(200, bench_wer.FULL_SPECS)}
with open("$HOME/wer_vm.json", "w", encoding="utf-8") as fh:
    json.dump(res, fh, indent=2)
print("WROTE $HOME/wer_vm.json")
PY
date -u +"done %H:%M:%SZ"
echo "WER_VM_DONE"
