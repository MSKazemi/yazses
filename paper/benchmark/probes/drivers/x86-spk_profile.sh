#!/bin/bash
# Per-speaker total speech time under each setting, so a "does this attribution look
# like people?" heuristic can be validated against real output instead of reasoned about.
set -uo pipefail
cd ~/yazses
export HF_HUB_OFFLINE=1
~/yazses/.venv/bin/python - <<'PY'
import json, sys
sys.path.insert(0, "paper/benchmark")
from types import SimpleNamespace
from _common import load_audio  # noqa
import soundfile as sf
from yazses.recimport.diarizer import SherpaDiarizer

CASES = [
    ("shipped-0.5",  dict(cluster_threshold=0.5, max_speakers=0)),
    ("thr-1.2",      dict(cluster_threshold=1.2, max_speakers=0)),
    ("maxspk-4",     dict(cluster_threshold=0.5, max_speakers=4)),
]
MEETINGS = ["IS1009a", "TS3003a"]
out = {}
for mid in MEETINGS:
    audio, sr = sf.read(f"$HOME/ami16_corpus/{mid}.wav", dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    total = len(audio) / sr
    out[mid] = {"duration_s": round(total, 1)}
    for name, kw in CASES:
        cfg = SimpleNamespace(model_dir="", **kw)
        turns = SherpaDiarizer(cfg).diarize(audio, sr)
        per = {}
        for t in turns:
            per[t.speaker] = per.get(t.speaker, 0.0) + (t.end - t.start)
        secs = sorted(per.values(), reverse=True)
        out[mid][name] = {
            "n_speakers": len(secs),
            "n_turns": len(turns),
            "speech_s": round(sum(secs), 1),
            "per_speaker_s": [round(s, 2) for s in secs],
        }
        print(f"[{mid}] {name}: {len(secs)} speakers, {len(turns)} turns, "
              f"top5={[round(s,1) for s in secs[:5]]} "
              f"min={round(secs[-1],2) if secs else 0}", flush=True)
json.dump(out, open("$HOME/spk_profile.json", "w"), indent=2)
print("SPK_PROFILE_DONE", flush=True)
PY
