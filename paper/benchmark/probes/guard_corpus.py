"""Per-label speech totals for every recording in a corpus, at one threshold."""
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, "paper/benchmark")
import bench_diarization as bd  # noqa: E402

from yazses.config import RecimportConfig  # noqa: E402
from yazses.recimport.diarizer import SherpaDiarizer  # noqa: E402

corpus = Path(sys.argv[1])
thr = float(sys.argv[2])
manifest = bd._read_manifest(corpus)
diar = SherpaDiarizer(replace(RecimportConfig(), cluster_threshold=thr))
out = {}
for meta in manifest["meetings"]:
    mid = meta["id"]
    audio = bd._load_wav(corpus / f"{mid}.wav")
    totals = {}
    for t in diar.diarize(audio, 16000):
        if t.end > t.start:
            totals[t.speaker] = totals.get(t.speaker, 0.0) + (t.end - t.start)
    out[mid] = {"true_speakers": meta["n_speakers"], "totals": totals}
    print(f"[gc] {mid}: {len(totals)} labels (true {meta['n_speakers']})", flush=True)
Path(sys.argv[3]).write_text(json.dumps(out, indent=1))
print("GUARD_CORPUS_DONE", flush=True)
