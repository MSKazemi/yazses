"""WER + real-time factor on a LibriSpeech test-clean subset, across engines and models.

Uses the shipping engine factory (`yazses.stt.factory.build_engine`) so the numbers
reflect YazSes' actual decode path for **every** pluggable engine, not a bespoke
faster-whisper call. WER is computed with the standard Whisper EnglishTextNormalizer
applied to both reference and hypothesis, so the numbers are comparable to published
Whisper results.

Why the factory rather than `FasterWhisperEngine` directly: this bench used to
hardcode three Whisper checkpoints, so `docs/models.md`'s claim that Parakeet beats
whisper-large-v3 was carried on the vendor's word with no local measurement behind
it. Routing through `build_engine` is what makes the claim checkable.

**The factory's kindness is this bench's hazard.** `build_engine` deliberately never
lets a bad `[stt] engine` brick dictation: a missing optional dependency falls back
to faster-whisper with a logged warning. That is right for a daemon and fatal for a
benchmark, which would then publish Whisper's numbers under Parakeet's name. So every
built engine is checked against the engine that was asked for, and a mismatch raises
instead of measuring. A benchmark may fail to run; it may not quietly measure the
wrong thing.
"""
from __future__ import annotations

import time

import jiwer
from whisper_normalizer.english import EnglishTextNormalizer

from _common import librispeech_subset, load_audio, percentile

# (label, engine, model). The label is the key in the results JSON and must appear
# verbatim in docs/benchmarks.md -- tests/test_benchmarks_match_results.py asserts
# that every measured model reaches the page, so a model cannot be measured and
# quietly left unpublished. Whisper checkpoints keep their bare names so the
# existing published table and its guard stay valid.
WHISPER_MODELS = ["tiny.en", "base.en", "small.en"]
DEFAULT_SPECS: list[tuple[str, str, str]] = [
    (m, "faster-whisper", m) for m in WHISPER_MODELS
]
# The comparison the docs assert but never measured: the two non-Whisper engines,
# plus the Whisper checkpoints they are claimed to beat.
FULL_SPECS: list[tuple[str, str, str]] = [
    *DEFAULT_SPECS,
    ("medium.en", "faster-whisper", "medium.en"),
    ("large-v3", "faster-whisper", "large-v3"),
    ("parakeet-tdt-0.6b-v2", "parakeet", "nemo-parakeet-tdt-0.6b-v2"),
    ("moonshine/tiny", "moonshine", "moonshine/tiny"),
    ("moonshine/base", "moonshine", "moonshine/base"),
]

# The class the factory must have returned for each engine name. Guards against the
# silent fallback documented in the module docstring.
_EXPECTED_CLASS = {
    "faster-whisper": "FasterWhisperEngine",
    "parakeet": "ParakeetEngine",
    "moonshine": "MoonshineEngine",
}

_normalize = EnglishTextNormalizer()

# Resamples for the bootstrap interval. 1000 is the usual floor for a stable 95%
# percentile interval and costs milliseconds here -- the decode already happened.
_BOOTSTRAP_N = 1000
_BOOTSTRAP_SEED = 20260823


def _bootstrap_wer_ci(per_utt: list[tuple[int, int]]) -> tuple[float, float]:
    """95% CI for corpus WER, resampling *utterances* (not words) with replacement.

    `per_utt` is (errors, reference_words) per utterance.

    Why this exists: these runs score a 200-utterance subset, and a bare percentage
    invites a comparison the sample cannot support. Measured here, `small.en` came out
    ahead of `medium.en` -- the reverse of the published full-test-clean ordering --
    and without an interval there is no way for a reader to tell whether that is a
    finding or the subset. Resampling is at the utterance level because that is the
    unit that was sampled; resampling words would treat one 30-word utterance as 30
    independent draws and report an interval several times too narrow.
    """
    import random

    if not per_utt:
        return (0.0, 0.0)
    rng = random.Random(_BOOTSTRAP_SEED)
    n = len(per_utt)
    draws = []
    for _ in range(_BOOTSTRAP_N):
        sample = [per_utt[rng.randrange(n)] for _ in range(n)]
        words = sum(w for _, w in sample)
        draws.append(sum(e for e, _ in sample) / words * 100 if words else 0.0)
    draws.sort()
    return (round(draws[int(0.025 * _BOOTSTRAP_N)], 2),
            round(draws[int(0.975 * _BOOTSTRAP_N)], 2))


def _build(engine_name: str, model: str):
    """Build *model* on *engine_name*, refusing a silent fallback to another engine."""
    from yazses.config import SttConfig
    from yazses.stt.factory import build_engine

    # language="en": every model here is English or English-only, and an explicit
    # code avoids Whisper's extra auto-detect pass skewing the RTF measurement.
    engine = build_engine(
        SttConfig(engine=engine_name, model=model, language="en", compute_type="int8")
    )
    actual = type(engine).__name__
    expected = _EXPECTED_CLASS[engine_name]
    if actual != expected:
        raise RuntimeError(
            f"asked for engine {engine_name!r} ({expected}) and the factory returned "
            f"{actual}. build_engine falls back to faster-whisper when an optional "
            f"dependency is missing, so this run would have published one engine's "
            f"numbers under another's name. Install the extra and re-run: "
            f"uv sync --extra {'parakeet' if engine_name == 'parakeet' else 'moonshine'}"
        )
    return engine


def _engine_versions(specs) -> dict:
    """Record the version of every decoder actually exercised, not just Whisper."""
    from _common import _pkg_version

    wanted = {e for _, e, _ in specs}
    out = {}
    if "parakeet" in wanted:
        out["onnx_asr"] = _pkg_version("onnx-asr")
    if "moonshine" in wanted:
        out["useful_moonshine_onnx"] = _pkg_version("useful-moonshine-onnx")
    return out


def run(n: int, specs: list[tuple[str, str, str]] | None = None) -> dict:
    specs = specs or DEFAULT_SPECS
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
            "engines": sorted({e for _, e, _ in specs}),
            "engine_versions": _engine_versions(specs),
        },
        "models": {},
    }

    for label, engine_name, model_name in specs:
        print(f"[wer] loading {label} (engine={engine_name}) ...", flush=True)
        t_load = time.monotonic()
        engine = _build(engine_name, model_name)
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
                print(f"  {label}: {i + 1}/{len(subset)}", flush=True)

        # jiwer expects non-empty strings; drop pairs where the reference is empty.
        pairs = [(r, h) for r, h in zip(refs, hyps) if r.strip()]
        ref_list = [r for r, _ in pairs]
        hyp_list = [h for _, h in pairs]
        measures = jiwer.process_words(ref_list, hyp_list)
        # Per-utterance error counts, for the bootstrap interval below. Scored one
        # at a time deliberately: jiwer's corpus call returns only totals, and the
        # interval needs to know which utterance each error came from.
        per_utt = []
        for r, h in pairs:
            m1 = jiwer.process_words([r], [h])
            per_utt.append((m1.substitutions + m1.deletions + m1.insertions,
                            m1.substitutions + m1.deletions + m1.hits))
        ci_low, ci_high = _bootstrap_wer_ci(per_utt)
        results["models"][label] = {
            "engine": engine_name,
            "engine_class": type(engine).__name__,
            "model": model_name,
            "wer": round(measures.wer * 100, 2),  # percent
            "wer_ci95": [ci_low, ci_high],
            "n_scored_utterances": len(per_utt),
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
        m = results["models"][label]
        print(
            f"[wer] {label}: WER={m['wer']}% "
            f"(95% CI {m['wer_ci95'][0]}-{m['wer_ci95'][1]})  "
            f"RTF median={m['rtf_median']} "
            f"(~{m['realtime_speedup_median']}x realtime)  load={m['load_seconds']}s",
            flush=True,
        )
    return results


def _parse_specs(arg: str) -> list[tuple[str, str, str]]:
    """`default` | `full` | a comma-separated list of `engine:model` pairs."""
    if arg in ("", "default"):
        return DEFAULT_SPECS
    if arg == "full":
        return FULL_SPECS
    specs = []
    for item in arg.split(","):
        item = item.strip()
        if not item:
            continue
        engine, _, model = item.partition(":")
        if not model:
            engine, model = "faster-whisper", engine
        if engine not in _EXPECTED_CLASS:
            raise SystemExit(
                f"unknown engine {engine!r}; valid: {sorted(_EXPECTED_CLASS)}"
            )
        specs.append((model, engine, model))
    return specs


if __name__ == "__main__":
    import sys

    from _common import write_result

    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    specs = _parse_specs(sys.argv[2] if len(sys.argv) > 2 else "default")
    write_result("wer", run(n, specs))
