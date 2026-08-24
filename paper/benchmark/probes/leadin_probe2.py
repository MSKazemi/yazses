"""Does `[accessibility] pre_speech_padding_ms` recover the opening word?

The daemon prepends literal zeros before the STT decode "so faster-whisper doesn't drop
the opening word on an abrupt onset" (core/daemon.py). 300 ms has never been measured.

The case the setting exists for is an abrupt onset, which LibriSpeech does not have --
its clips open with a beat of room tone. So each clip's leading silence is trimmed first,
putting speech at sample 0, and the untrimmed clips are carried as a control: if the
lead-in matters, it must matter more on the trimmed set than on the untrimmed one.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path.home() / "yazses" / "paper" / "benchmark"))

import jiwer
import numpy as np
from whisper_normalizer.english import EnglishTextNormalizer

from _common import librispeech_subset, load_audio

from yazses.config import SttConfig
from yazses.stt.factory import build_engine

_normalize = EnglishTextNormalizer()
SR = 16000
LEADS_MS = [0, 300, 600]

N = int(sys.argv[1]) if len(sys.argv) > 1 else 200
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path.home() / "leadin_probe.json"


def trim_leading_silence(audio: np.ndarray, frame: int = 160, thresh: float = 0.01) -> np.ndarray:
    """Drop everything before the first 10 ms frame whose peak clears `thresh`."""
    n_frames = len(audio) // frame
    for i in range(n_frames):
        if np.max(np.abs(audio[i * frame:(i + 1) * frame])) >= thresh:
            return audio[i * frame:]
    return audio


subset = librispeech_subset(N, stratified=True, split="test-clean")
raw = [(utt, load_audio(wav), ref) for utt, wav, ref, _ in subset]
trimmed = [(utt, trim_leading_silence(a), ref) for utt, a, ref in raw]
dropped = [len(a) - len(t) for (_, a, _), (_, t, _) in zip(raw, trimmed)]
assert np.median(dropped) > 0, "no clip had leading silence to trim; the probe is inert"

# The case the setting exists for: the key goes down AFTER the voice has started, so
# the opening phoneme is gone from the capture. Prepending silence cannot invent it --
# the question is whether a clean onset boundary lets the decoder recover the word
# anyway. `clip_ms` of SPEECH is removed, not silence.
CLIPS_MS = [40, 120, 240]
print(f"[clip] {len(raw)} clips; base trim median {np.median(dropped)/SR*1000:.0f} ms",
      flush=True)

engine = build_engine(SttConfig(model="base.en", language="en", compute_type="int8"))
results = {"config": {"n": len(raw), "model": "base.en", "leads_ms": LEADS_MS,
                      "clips_ms": CLIPS_MS}, "rows": []}


def first_token(text: str) -> str:
    parts = text.split()
    return parts[0] if parts else ""


for clip_ms in CLIPS_MS:
    cut = int(clip_ms * SR / 1000)
    arm = [(u, a[cut:], r) for u, a, r in trimmed]
    # A clip shorter than the cut would become empty and score as a false null.
    assert all(len(a) > SR for _, a, _ in arm), "a clip was shorter than the cut"
    for lead_ms in LEADS_MS:
        lead = np.zeros(int(lead_ms * SR / 1000), dtype=np.float32)
        refs, hyps = [], []
        for _u, audio, ref in arm:
            a = np.concatenate([lead, audio]) if lead.size else audio
            refs.append(_normalize(ref))
            hyps.append(_normalize(engine.transcribe(a)))
        pairs = [(r, h) for r, h in zip(refs, hyps) if r]
        wer = jiwer.wer([r for r, _ in pairs], [h for _, h in pairs]) * 100
        first_ok = sum(1 for r, h in pairs if first_token(r) == first_token(h))
        row = {"clip_ms": clip_ms, "lead_ms": lead_ms, "wer": round(wer, 2),
               "first_word_ok": first_ok, "n": len(pairs),
               "empty_hyps": sum(1 for _, h in pairs if not h.strip())}
        results["rows"].append(row)
        print(f"[clip] cut={clip_ms:4d}ms lead={lead_ms:4d}ms  WER {row['wer']:5.2f}%  "
              f"first word {first_ok}/{len(pairs)}", flush=True)
        OUT.write_text(json.dumps(results, indent=2))

print("CLIP_PROBE_DONE", flush=True)
