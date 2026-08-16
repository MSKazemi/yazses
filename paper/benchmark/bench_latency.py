"""Latency, memory, and pipeline-stage timing.

Three things:
1. Cold-start model load time per model.
2. Decode latency distribution (P50/P95) on a fixed short-utterance subset.
3. The non-decode pipeline overhead: VAD gate, text cleanup, disfluency filter, and
   command-grammar classification — the pure fast transforms wrapped around the
   Whisper decode. Shows the pipeline adds negligible latency on top of the model.
4. Resident-set memory (RSS) baseline and per model.
"""
from __future__ import annotations

import time

import numpy as np

from _common import librispeech_subset, load_audio, percentile

MODELS = ["tiny.en", "base.en", "small.en"]
_REPS = 2000  # per pure-stage timing


def _rss_mb() -> float:
    import psutil

    return psutil.Process().memory_info().rss / 1e6


def _time_stage(fn, reps: int = _REPS) -> dict:
    # warmup
    for _ in range(50):
        fn()
    samples = []
    for _ in range(reps):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000.0)  # ms
    return {
        "median_ms": round(percentile(samples, 50), 4),
        "p95_ms": round(percentile(samples, 95), 4),
        "mean_ms": round(sum(samples) / len(samples), 4),
    }


def _pipeline_stage_timings() -> dict:
    from yazses.audio.vad_calibrated import is_silent_calibrated
    from yazses.commands.grammar import classify
    from yazses.config import AccessibilityConfig, DisfluencyConfig
    from yazses.postprocess.cleaner import clean_text
    from yazses.stt.filters.disfluency import filter_transcript

    acc = AccessibilityConfig()
    dis = DisfluencyConfig()
    # A representative 1 s speech buffer and a representative transcript.
    audio = (np.random.default_rng(0).standard_normal(16000) * 0.05).astype(np.float32)
    transcript = "the quick brown fox jumps over the lazy dog and then runs away"
    command = "go to line 42"

    return {
        "vad_gate": _time_stage(lambda: is_silent_calibrated(audio, acc)),
        "clean_text": _time_stage(lambda: clean_text(transcript + " [BLANK_AUDIO]")),
        "disfluency_filter": _time_stage(lambda: filter_transcript(transcript, dis)),
        "grammar_classify_dictation": _time_stage(lambda: classify(transcript)),
        "grammar_classify_command": _time_stage(lambda: classify(command)),
    }


def run(n_latency: int) -> dict:
    from yazses.stt.faster_whisper import FasterWhisperEngine

    baseline_rss = _rss_mb()
    subset = librispeech_subset(n_latency)
    durations = [d for _, _, _, d in subset]

    out: dict = {
        "config": {
            "n_latency_utterances": len(subset),
            "audio_duration_median_s": round(percentile(durations, 50), 2),
            "audio_duration_p95_s": round(percentile(durations, 95), 2),
            "pure_stage_reps": _REPS,
        },
        "memory": {"baseline_rss_mb": round(baseline_rss, 1)},
        "models": {},
    }

    for model_name in MODELS:
        print(f"[latency] {model_name}: cold-start load ...", flush=True)
        t0 = time.monotonic()
        engine = FasterWhisperEngine(model_name=model_name)
        load_s = time.monotonic() - t0
        rss_after_load = _rss_mb()

        decode_ms: list[float] = []
        for i, (_, flac, _, _) in enumerate(subset):
            audio = load_audio(flac)
            t = time.monotonic()
            engine.transcribe(audio)
            decode_ms.append((time.monotonic() - t) * 1000.0)
            if (i + 1) % 10 == 0:
                print(f"  {model_name}: {i + 1}/{len(subset)}", flush=True)
        rss_peak = _rss_mb()

        out["models"][model_name] = {
            "cold_start_load_s": round(load_s, 2),
            "decode_median_ms": round(percentile(decode_ms, 50), 1),
            "decode_p95_ms": round(percentile(decode_ms, 95), 1),
            "rss_after_load_mb": round(rss_after_load, 1),
            "rss_peak_mb": round(rss_peak, 1),
            "model_rss_delta_mb": round(rss_after_load - baseline_rss, 1),
        }
        print(f"[latency] {model_name}: {out['models'][model_name]}", flush=True)
        del engine

    print("[latency] pure pipeline-stage timings ...", flush=True)
    out["pipeline_stages"] = _pipeline_stage_timings()
    # Total non-decode overhead per utterance (median of the always-run stages).
    st = out["pipeline_stages"]
    out["non_decode_overhead_median_ms"] = round(
        st["vad_gate"]["median_ms"]
        + st["clean_text"]["median_ms"]
        + st["disfluency_filter"]["median_ms"]
        + st["grammar_classify_dictation"]["median_ms"],
        4,
    )
    print(
        f"[latency] non-decode pipeline overhead (median): "
        f"{out['non_decode_overhead_median_ms']} ms",
        flush=True,
    )
    return out


if __name__ == "__main__":
    import sys

    from _common import write_result

    n = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    write_result("latency", run(n))
