"""Does `[stt] beam_size` earn its latency?

config.py says beam 1 is "measurably faster and measurably worse". Neither half had
ever been measured. This scores the shipped default model (base.en) and the next one
up (small.en) across beam widths on the same 200-utterance LibriSpeech test-clean
subset the published table uses, through the shipping engine factory.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path.home() / "yazses" / "paper" / "benchmark"))

import jiwer
from whisper_normalizer.english import EnglishTextNormalizer

from _common import librispeech_subset, load_audio

from yazses.config import SttConfig
from yazses.stt.factory import build_engine

_normalize = EnglishTextNormalizer()

N = int(sys.argv[1]) if len(sys.argv) > 1 else 200
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path.home() / "beam_probe.json"
GRID = [("base.en", b) for b in (1, 2, 5)] + [("small.en", b) for b in (1, 5)]

subset = librispeech_subset(N, stratified=True, split="test-other")
total_audio_s = sum(dur for _, _, _, dur in subset)
print(f"[beam] {len(subset)} utts, {total_audio_s/60:.1f} min of audio", flush=True)

# A beam width that never reaches the decoder would make every row identical and the
# finding would be "beam does not matter" — which is exactly the wrong conclusion to
# reach from a broken probe. Prove the knob is live before measuring with it.
probe_engine = build_engine(SttConfig(model="base.en", language="en",
                                      compute_type="int8", beam_size=3))
assert probe_engine._decode_kwargs(None).get("beam_size") == 3, (
    "beam_size does not reach the decoder; fix the probe before trusting a row"
)
del probe_engine

results = {"config": {"n_utterances": len(subset),
                      "total_audio_seconds": round(total_audio_s, 1),
                      "split": "test-other"},
           "rows": []}

for model, beam in GRID:
    print(f"[beam] {model} beam={beam} loading ...", flush=True)
    engine = build_engine(SttConfig(model=model, language="en",
                                    compute_type="int8", beam_size=beam))
    refs, hyps, decode_s = [], [], 0.0
    for utt_id, wav, ref, _dur in subset:
        audio = load_audio(wav)
        t0 = time.monotonic()
        hyp = engine.transcribe(audio)
        decode_s += time.monotonic() - t0
        refs.append(_normalize(ref))
        hyps.append(_normalize(hyp))
    pairs = [(r, h) for r, h in zip(refs, hyps) if r]
    wer = jiwer.wer([r for r, _ in pairs], [h for _, h in pairs]) * 100
    out = jiwer.process_words([r for r, _ in pairs], [h for _, h in pairs])
    row = {"model": model, "beam_size": beam, "wer": round(wer, 2),
           "sub": out.substitutions, "del": out.deletions, "ins": out.insertions,
           "decode_seconds": round(decode_s, 1),
           "rtf": round(decode_s / total_audio_s, 4)}
    results["rows"].append(row)
    print(f"[beam] {model} beam={beam}: WER {row['wer']}%  RTF {row['rtf']}  "
          f"({row['decode_seconds']}s)", flush=True)
    OUT.write_text(json.dumps(results, indent=2))
    del engine

print("BEAM_PROBE_DONE", flush=True)
