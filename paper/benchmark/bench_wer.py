"""WER + real-time factor on a LibriSpeech test-clean subset, across model sizes.

Uses the shipping STT wrapper (yazses.stt.faster_whisper.FasterWhisperEngine) so the
numbers reflect YazSes' actual decode path, not a bespoke faster-whisper call. WER is
computed with the standard Whisper EnglishTextNormalizer applied to both reference and
hypothesis, so the numbers are comparable to published Whisper results.
"""
from __future__ import annotations

import time

import jiwer
from whisper_normalizer.english import EnglishTextNormalizer

from _common import load_audio, librispeech_subset, percentile

MODELS = ["tiny.en", "base.en", "small.en"]
_normalize = EnglishTextNormalizer()


def run(n: int) -> dict:
    from yazses.stt.faster_whisper import FasterWhisperEngine

    subset = librispeech_subset(n, stratified=True)
    total_audio_s = sum(dur for _, _, _, dur in subset)
    n_speakers = len({utt_id.split("-")[0] for utt_id, _, _, _ in subset})
    results: dict = {
        "config": {
            "dataset": "LibriSpeech test-clean",
            "dataset_source": "https://www.openslr.org/resources/12/test-clean.tar.gz",
            "citation": "Panayotov et al., ICASSP 2015",
            "n_utterances": len(subset),
            "n_speakers": n_speakers,
            "total_audio_seconds": round(total_audio_s, 1),
            "normalizer": "whisper_normalizer.english.EnglishTextNormalizer",
            "selection": "deterministic speaker-stratified round-robin across all test-clean speakers",
        },
        "models": {},
    }

    for model_name in MODELS:
        print(f"[wer] loading {model_name} ...", flush=True)
        t_load = time.monotonic()
        engine = FasterWhisperEngine(model_name=model_name)
        load_s = time.monotonic() - t_load

        refs: list[str] = []
        hyps: list[str] = []
        rtfs: list[float] = []
        decode_s_total = 0.0
        for i, (utt_id, flac, ref, dur) in enumerate(subset):
            audio = load_audio(flac)
            t0 = time.monotonic()
            hyp = engine.transcribe(audio)
            dt = time.monotonic() - t0
            decode_s_total += dt
            rtfs.append(dt / dur if dur > 0 else 0.0)
            refs.append(_normalize(ref))
            hyps.append(_normalize(hyp))
            if (i + 1) % 25 == 0:
                print(f"  {model_name}: {i + 1}/{len(subset)}", flush=True)

        # jiwer expects non-empty strings; drop pairs where the reference is empty.
        pairs = [(r, h) for r, h in zip(refs, hyps) if r.strip()]
        ref_list = [r for r, _ in pairs]
        hyp_list = [h for _, h in pairs]
        measures = jiwer.process_words(ref_list, hyp_list)
        results["models"][model_name] = {
            "wer": round(measures.wer * 100, 2),  # percent
            "mer": round(measures.mer * 100, 2),
            "substitutions": measures.substitutions,
            "deletions": measures.deletions,
            "insertions": measures.insertions,
            "hits": measures.hits,
            "load_seconds": round(load_s, 2),
            "rtf_median": round(percentile(rtfs, 50), 3),
            "rtf_p95": round(percentile(rtfs, 95), 3),
            "rtf_mean": round(sum(rtfs) / len(rtfs), 3) if rtfs else 0.0,
            "decode_seconds_total": round(decode_s_total, 1),
            "realtime_speedup_median": round(1.0 / percentile(rtfs, 50), 1)
            if percentile(rtfs, 50) > 0
            else 0.0,
        }
        m = results["models"][model_name]
        print(
            f"[wer] {model_name}: WER={m['wer']}%  RTF median={m['rtf_median']} "
            f"(~{m['realtime_speedup_median']}x realtime)  load={m['load_seconds']}s",
            flush=True,
        )
    return results


if __name__ == "__main__":
    import sys

    from _common import write_result

    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    write_result("wer", run(n))
