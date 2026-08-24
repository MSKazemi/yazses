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
LEADS_MS = [0, 100, 300, 600, 1000]

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
print(f"[lead] {len(raw)} clips; leading silence trimmed: "
      f"median {np.median(dropped)/SR*1000:.0f} ms, max {max(dropped)/SR*1000:.0f} ms",
      flush=True)
# If nothing was trimmed the two arms are the same experiment and every row will agree.
assert np.median(dropped) > 0, "no clip had leading silence to trim; the probe is inert"

engine = build_engine(SttConfig(model="base.en", language="en", compute_type="int8"))

results = {"config": {"n": len(raw), "model": "base.en", "leads_ms": LEADS_MS,
                      "trim_threshold": 0.01,
                      "median_trimmed_ms": float(np.median(dropped) / SR * 1000)},
           "rows": []}


def first_token(text: str) -> str:
    parts = text.split()
    return parts[0] if parts else ""


for arm, clips in (("trimmed", trimmed), ("untrimmed", raw)):
    for lead_ms in LEADS_MS:
        lead = np.zeros(int(lead_ms * SR / 1000), dtype=np.float32)
        refs, hyps, decode_s = [], [], 0.0
        for _utt, audio, ref in clips:
            a = np.concatenate([lead, audio]) if lead.size else audio
            t0 = time.monotonic()
            hyp = engine.transcribe(a)
            decode_s += time.monotonic() - t0
            refs.append(_normalize(ref))
            hyps.append(_normalize(hyp))
        pairs = [(r, h) for r, h in zip(refs, hyps) if r]
        wer = jiwer.wer([r for r, _ in pairs], [h for _, h in pairs]) * 100
        first_ok = sum(1 for r, h in pairs if first_token(r) == first_token(h))
        empty = sum(1 for _, h in pairs if not h.strip())
        row = {"arm": arm, "lead_ms": lead_ms, "wer": round(wer, 2),
               "first_word_ok": first_ok, "n": len(pairs), "empty_hyps": empty,
               "decode_seconds": round(decode_s, 1)}
        results["rows"].append(row)
        print(f"[lead] {arm:9s} lead={lead_ms:4d}ms  WER {row['wer']:5.2f}%  "
              f"first word {first_ok}/{len(pairs)}  empty {empty}", flush=True)
        OUT.write_text(json.dumps(results, indent=2))

print("LEADIN_PROBE_DONE", flush=True)
