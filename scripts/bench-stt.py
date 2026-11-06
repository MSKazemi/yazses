"""STT Benchmark Harness.

Measures WER (Word Error Rate), RTF (Real Time Factor), warmed decode p50/p95, cold
model-load time, and the process's peak RSS.
Usage:
    uv run python scripts/bench-stt.py data/librispeech-sample --engine faster-whisper --model base.en
    uv run python scripts/bench-stt.py DATA --engine parakeet --json-out run.json

Integrity rules (support for the *proposed* evaluation protocol of ADR-033, which is not
accepted; nothing here depends on it being accepted -- they are protocol-agnostic):

* The engine that actually loaded is checked against the one requested. The factory
  falls back to faster-whisper when a requested engine cannot load, and a row scored on
  the fallback must never be published under the requested engine's name. A fallback
  exits 2 unless ``--allow-fallback`` is given, and then the row says FALLBACK.
* Every file is accounted for. A missing reference, an undecodable file or a failed
  decode is counted, not silently dropped from the denominator. Coverage below 100 %
  exits 3 (after printing the results) unless ``--allow-partial`` is given, and the row
  always carries the coverage when it is partial.
"""
import argparse
import json
import os
import platform
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# Ensure yazses is in pythonpath
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

try:
    import jiwer
except ImportError:
    print("Error: jiwer is not installed. Run: uv pip install jiwer")
    sys.exit(1)


def _build_normalizer():
    """Return (normalize_fn, name) -- Whisper's normaliser when it is installed.

    This harness scored with a bare `.lower()`, which counts punctuation as part of
    the word it is glued to. On the corpus this repo ships, `base.en` returns the
    reference text *exactly* apart from two commas, and `.lower()` scored that
    flawless transcription at 9.09 % WER while the standard normaliser scores it
    0.00 %. So the community table was reporting recognition errors that were not
    recognition errors, on the page that invites contributors to publish numbers.

    It also made these numbers incomparable with `benchmark/bench_wer.py`,
    which has always used `EnglishTextNormalizer` -- two harnesses in one project
    producing two different WERs for the same audio and the same model.

    Falls back to `.lower()` rather than exiting, because this script's job is to be
    runnable on a contributor's machine; but it says which one it used, and the
    printed table row is labelled, so a lenient number can never be quietly pasted
    into the table next to a strict one.
    """
    try:
        from whisper_normalizer.english import EnglishTextNormalizer
    except ImportError:
        return (lambda t: t.lower().strip()), "lower"
    normalizer = EnglishTextNormalizer()
    return (lambda t: normalizer(t)), "whisper"

def get_peak_rss_mb() -> float:
    try:
        import psutil
        process = psutil.Process(os.getpid())
        if hasattr(process.memory_info(), 'peak_wset'):
            return process.memory_info().peak_wset / (1024 * 1024)
        return process.memory_info().rss / (1024 * 1024)
    except ImportError:
        try:
            import resource
            # ru_maxrss is kilobytes on Linux and *bytes* on macOS/BSD. This number
            # goes into a published comparison table, so getting the unit wrong would
            # not look like a bug — it would look like a Mac using 1/1024th the memory.
            divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
            return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / divisor
        except ImportError:
            return 0.0

def _load_adapters():
    """Import the sibling adapters module by path.

    This file is `bench-stt.py` — a hyphen, so it is a script and not importable, and it
    cannot use a normal relative import to reach `bench_adapters`.
    """
    import importlib.util

    path = Path(__file__).with_name("bench_adapters.py")
    spec = importlib.util.spec_from_file_location("bench_adapters", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # @dataclass looks its own module up in sys.modules; a by-path import that skips this
    # blows up inside the class body rather than at the call site.
    sys.modules["bench_adapters"] = mod
    spec.loader.exec_module(mod)
    return mod


@dataclass
class MockConfig:
    engine: str
    model: str
    language: str
    device: str
    compute_type: str


# Exit codes beyond 1 (usage / nothing to score). Distinct so a wrapper script can tell
# "this number is about a different engine" from "this number is about fewer files".
EXIT_FALLBACK = 2
EXIT_PARTIAL = 3

# Same floor as the live latency summary (src/yazses/stt/latency.py): below it a "p95" is
# one of the two or three slowest files wearing a statistical name. Kept as a literal so
# this script's pure helpers import without `yazses`; a test pins it to the source.
MIN_SAMPLES_FOR_P95 = 20

PROTOCOL_LABEL = "ADR-033 evaluation protocol v1 -- PROPOSED, not accepted"


def _build_engine(stt_config):
    """Seam for tests: the real factory, imported lazily so `--tool` runs need no engine."""
    from yazses.stt.factory import build_engine

    return build_engine(stt_config)


def _load_audio(path: Path, rate: int):
    """Seam for tests: the project's decoder (PyAV with an ffmpeg fallback)."""
    from yazses.recimport.audio_io import load_audio

    return load_audio(path, rate)


def _describe_engine(engine) -> dict | None:
    """The engine's own account of what it is, via the factory's describer when available."""
    try:
        from yazses.stt.factory import describe_active_engine
    except Exception:  # noqa: BLE001 -- a by-path run without src/ on the path
        describe_active_engine = None
    if describe_active_engine is not None:
        return describe_active_engine(engine)
    name = getattr(engine, "engine_name", None)
    if not isinstance(name, str) or not name:
        return None
    return {
        "engine": name,
        "model": str(getattr(engine, "model_name", "") or ""),
        "fallback_from": str(getattr(engine, "fallback_from", "") or ""),
        "fallback_reason": str(getattr(engine, "fallback_reason", "") or ""),
    }


@dataclass
class EngineCheck:
    """Whether the engine that loaded is the engine that was asked for."""

    requested_engine: str
    requested_model: str
    resolved_engine: str = ""          # "" when the engine does not identify itself
    resolved_model: str = ""
    fallback_from: str = ""
    fallback_reason: str = ""
    problems: list[str] = field(default_factory=list)   # fatal unless --allow-fallback
    warnings: list[str] = field(default_factory=list)   # reported, never fatal

    @property
    def verified(self) -> bool:
        return bool(self.resolved_engine)

    @property
    def is_fallback(self) -> bool:
        return bool(self.problems)

    def as_dict(self) -> dict:
        return {
            "requested_engine": self.requested_engine,
            "requested_model": self.requested_model,
            "resolved_engine": self.resolved_engine or None,
            "resolved_model": self.resolved_model or None,
            "verified": self.verified,
            "fallback": self.is_fallback,
            "fallback_from": self.fallback_from or None,
            "fallback_reason": self.fallback_reason or None,
            "problems": list(self.problems),
            "warnings": list(self.warnings),
        }


def check_engine(requested_engine: str, requested_model: str, identity: dict | None) -> EngineCheck:
    """Compare the requested engine with *identity* (from :func:`_describe_engine`).

    A recorded factory fallback, or a resolved engine name that differs from the request,
    is a problem: the numbers describe a different decoder. A model name that differs is
    only a warning, because engines legitimately canonicalise names (Moonshine prefixes
    ``moonshine/``) -- but it is recorded so a reader can judge.
    """
    check = EngineCheck(requested_engine=requested_engine, requested_model=requested_model)
    if identity is None:
        check.warnings.append(
            "the engine does not identify itself; the resolved engine is UNVERIFIED")
        return check
    check.resolved_engine = identity.get("engine", "") or ""
    check.resolved_model = identity.get("model", "") or ""
    check.fallback_from = identity.get("fallback_from", "") or ""
    check.fallback_reason = identity.get("fallback_reason", "") or ""
    if check.fallback_from:
        check.problems.append(
            f"the factory fell back from {check.fallback_from!r} to {check.resolved_engine!r}"
            + (f" because {check.fallback_reason}" if check.fallback_reason else ""))
    elif check.resolved_engine != requested_engine:
        check.problems.append(
            f"requested engine {requested_engine!r} but {check.resolved_engine!r} loaded")
    if requested_model and check.resolved_model and check.resolved_model != requested_model:
        check.warnings.append(
            f"requested model {requested_model!r}, engine reports {check.resolved_model!r}")
    return check


@dataclass
class Coverage:
    """Every file in the corpus, and what happened to it."""

    n_total: int = 0
    scored: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)   # (file, reason)

    @property
    def n_scored(self) -> int:
        return len(self.scored)

    @property
    def n_failed(self) -> int:
        return len(self.failed)

    @property
    def complete(self) -> bool:
        return self.n_total > 0 and self.n_scored == self.n_total

    def fail(self, name: str, reason: str) -> None:
        print(f"Warning: {name}: {reason} -- counted as FAILED, not skipped.")
        self.failed.append((name, reason))

    def describe(self) -> str:
        pct = 100.0 * self.n_scored / self.n_total if self.n_total else 0.0
        return f"{self.n_scored}/{self.n_total} scored ({pct:.1f} %), {self.n_failed} failed"

    def as_dict(self) -> dict:
        return {
            "n_total": self.n_total,
            "n_scored": self.n_scored,
            "n_failed": self.n_failed,
            "failed": [{"file": f, "reason": r} for f, r in self.failed],
        }


def _nearest_rank(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile, the same definition as `yazses.stt.latency.percentile`."""
    import math

    ordered = sorted(values)
    rank = math.ceil(round(fraction * len(ordered), 9))
    rank = min(max(rank, 1), len(ordered))
    return float(ordered[rank - 1])


def decode_percentiles(decode_seconds: list[float]) -> dict:
    """Warmed per-file decode p50/p95 in ms; p95 is None below :data:`MIN_SAMPLES_FOR_P95`."""
    n = len(decode_seconds)
    if n == 0:
        return {"n": 0, "p50_ms": None, "p95_ms": None, "p95_min_n": MIN_SAMPLES_FOR_P95}
    ms = [s * 1000.0 for s in decode_seconds]
    return {
        "n": n,
        "p50_ms": round(_nearest_rank(ms, 0.50), 1),
        "p95_ms": round(_nearest_rank(ms, 0.95), 1) if n >= MIN_SAMPLES_FOR_P95 else None,
        "p95_min_n": MIN_SAMPLES_FOR_P95,
    }


def word_ops(reference: str, hypothesis: str) -> dict:
    """Word-level hits/substitutions/deletions/insertions of normalised texts (jiwer)."""
    out = jiwer.process_words(reference, hypothesis)
    return {
        "hits": out.hits,
        "substitutions": out.substitutions,
        "deletions": out.deletions,
        "insertions": out.insertions,
    }


def _versions() -> dict:
    from importlib import metadata

    found: dict[str, str | None] = {"python": platform.python_version()}
    for dist in ("yazses", "numpy", "jiwer", "faster-whisper", "ctranslate2",
                 "onnxruntime", "whisper-normalizer", "av"):
        try:
            found[dist] = metadata.version(dist)
        except metadata.PackageNotFoundError:
            found[dist] = None
    return found


def _git_commit() -> str | None:
    """The checkout's commit -- a local `git` call, no network."""
    import subprocess

    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parent,
            capture_output=True, text=True, encoding="utf-8", timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def run_header(*, subject: str, model: str, normalizer: str, engine_check: EngineCheck | None,
               load_s: float | None, warmup_s: float | None) -> dict:
    return {
        "schema": "yazses-bench-stt/1",
        "protocol": PROTOCOL_LABEL,
        "commit": _git_commit(),
        "subject": subject,
        "model": model or None,
        "engine": engine_check.as_dict() if engine_check is not None else None,
        "normalizer": normalizer,
        "versions": _versions(),
        "cpu": {"machine": platform.machine(), "processor": platform.processor() or None,
                "logical_cores": os.cpu_count()},
        "os": platform.platform(),
        "cold_load_s": None if load_s is None else round(load_s, 3),
        "warmup_s": None if warmup_s is None else round(warmup_s, 3),
        "rss_note": "peak RSS of the whole benchmark process (includes harness + corpus)",
    }


def table_row(*, label: str, model: str, wer: float, normalizer: str, rtf: float,
              rss_str: str, coverage: Coverage, engine_check: EngineCheck | None) -> str:
    """The markdown row. Everything that changes what the number means rides on it."""
    notes = [f"norm: {normalizer}"]
    if normalizer != "whisper":
        notes.append("lower-fold")
    if engine_check is not None:
        if engine_check.is_fallback:
            notes.append(f"FALLBACK: {engine_check.resolved_engine or '?'} ran, "
                         f"not {engine_check.requested_engine}")
        elif not engine_check.verified:
            notes.append("engine unverified")
    if not coverage.complete:
        notes.append(f"PARTIAL coverage {coverage.n_scored}/{coverage.n_total}")
    shown = label
    if engine_check is not None and engine_check.is_fallback and engine_check.resolved_engine:
        shown = f"{engine_check.resolved_engine} (requested {label})"
    if rss_str != "N/A" and not rss_str.startswith("n/a"):
        rss_str = f"{rss_str} (process peak)"
    return (f"| CPU/GPU | `{shown}` (`{model or 'default'}`) | {wer * 100:.1f}% "
            f"({'; '.join(notes)}) | {rtf:.2f}x | {rss_str} |")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run STT Benchmark on a directory of WAV and TXT files.")
    parser.add_argument("dataset", type=Path, help="Directory containing .wav and .txt reference files")
    parser.add_argument("--engine", type=str, default="faster-whisper", help="Engine to use (faster-whisper, parakeet)")
    parser.add_argument(
        "--tool",
        type=str,
        default="",
        help="Benchmark an EXTERNAL tool instead of a YazSes engine "
             "(whisper-cpp, openai-whisper, vosk). Same corpus, same machine — this is "
             "what makes the results a comparison rather than a self-report.",
    )
    parser.add_argument("--model", type=str, default="base.en", help="Model name (e.g., base.en, tiny.en)")
    parser.add_argument("--device", type=str, default="cpu", help="Device (cpu, cuda, auto)")
    parser.add_argument("--compute-type", type=str, default="int8", help="Compute type (int8, float16)")
    parser.add_argument("--allow-fallback", action="store_true",
                        help="Score the run even if the factory fell back to another engine; "
                             "the row is then labelled FALLBACK. Default: exit 2.")
    parser.add_argument("--allow-partial", action="store_true",
                        help="Exit 0 even when some files could not be scored; the row still "
                             "states the coverage. Default: exit 3 below 100%% coverage.")
    parser.add_argument("--json-out", type=Path, default=None,
                        help="Write a header (commit, engine, versions, CPU, OS, normaliser) "
                             "and one row per file to this JSON file.")
    args = parser.parse_args(argv)

    if not args.dataset.exists() or not args.dataset.is_dir():
        print(f"Error: Dataset directory {args.dataset} not found.")
        return 1

    # `--tool` measures somebody else's software; `--engine` measures ours. The external
    # path deliberately skips build_engine and the warm-up: a subprocess starts cold every
    # file, and pretending otherwise would flatter us against tools that cannot be warmed.
    external = None
    engine = None
    engine_check: EngineCheck | None = None
    load_s: float | None = None
    warmup_s: float | None = None
    if args.tool:
        external = _load_adapters()
        if args.tool not in external.ADAPTERS:
            print(f"Error: unknown --tool {args.tool!r}; known: "
                  f"{', '.join(sorted(external.ADAPTERS))}")
            return 1
        if not external.ADAPTERS[args.tool].available():
            print(f"Error: {external.ADAPTERS[args.tool].binary!r} is not on PATH. "
                  f"Install it, or drop --tool from this run.")
            return 1
        print(f"Benchmarking external tool: {external.describe(args.tool)}")
    else:
        print(f"Loading engine: {args.engine} (model: {args.model})...")
        stt_config = MockConfig(
            engine=args.engine,
            model=args.model,
            language="en",
            device=args.device,
            compute_type=args.compute_type
        )
        # Cold load is reported on its own and never folded into decode time.
        t0 = time.perf_counter()
        engine = _build_engine(stt_config)
        load_s = time.perf_counter() - t0

        engine_check = check_engine(args.engine, args.model, _describe_engine(engine))
        for warning in engine_check.warnings:
            print(f"Warning: {warning}")
        if engine_check.is_fallback:
            for problem in engine_check.problems:
                print(f"{'Warning' if args.allow_fallback else 'Error'}: {problem}")
            if not args.allow_fallback:
                print("Refusing to score a different engine under the requested name. "
                      "Fix the engine install, or pass --allow-fallback to label the row.")
                return EXIT_FALLBACK
        else:
            print(f"Resolved engine: {engine_check.resolved_engine or 'UNVERIFIED'} "
                  f"(model: {engine_check.resolved_model or 'unreported'})")

        print("Warming up engine...")
        dummy_audio = np.zeros(16000, dtype=np.float32)
        t0 = time.perf_counter()
        engine.transcribe(dummy_audio, 16000)
        warmup_s = time.perf_counter() - t0

    wav_files = sorted(args.dataset.glob("*.wav"))
    if not wav_files:
        print(f"No .wav files found in {args.dataset}")
        return 1

    normalize, normalizer_name = _build_normalizer()
    if normalizer_name == "lower":
        print(
            "Warning: whisper-normalizer is not installed, so WER is scored with a bare "
            "lower-case fold. That counts punctuation as part of a word and inflates the "
            "score -- a perfect transcription can read as ~9 % WER. Install it for a "
            "comparable number: uv sync --group benchmark"
        )
    print(f"Found {len(wav_files)} files. Starting benchmark...")

    coverage = Coverage(n_total=len(wav_files))
    total_audio_duration = 0.0
    total_decode_time = 0.0
    decode_times: list[float] = []
    references: list[str] = []
    hypotheses: list[str] = []
    samples: list[dict] = []

    for wav_path in wav_files:
        txt_path = wav_path.with_suffix(".txt")
        if not txt_path.exists():
            coverage.fail(wav_path.name, "missing reference text")
            continue

        with open(txt_path, "r", encoding="utf-8") as f:
            reference = f.read().strip()

        # The project already has a decoder that returns mono float32 at a requested
        # rate, via PyAV with an ffmpeg fallback and no dependency beyond the base
        # install (`recimport/audio_io.py`). Reading with `soundfile` instead would add
        # an install step for a dev script and, because it does not resample, made the
        # harness silently *skip* every dataset that is not already 16 kHz — which is
        # most of them, LibriSpeech included.
        try:
            audio, sr = _load_audio(wav_path, 16000)
        except (RuntimeError, FileNotFoundError) as exc:
            coverage.fail(wav_path.name, f"could not decode audio: {exc}")
            continue

        duration = len(audio) / sr
        if duration <= 0:
            coverage.fail(wav_path.name, "decoded to no audio")
            continue

        start_time = time.perf_counter()
        try:
            if external is not None:
                hypothesis = external.transcribe(args.tool, wav_path, args.model)
            else:
                hypothesis = engine.transcribe(audio, 16000)
        except RuntimeError as exc:
            # One bad file must not silently shrink the corpus a rival is scored on.
            coverage.fail(wav_path.name, f"transcription failed: {exc}")
            continue
        decode_time = time.perf_counter() - start_time

        total_audio_duration += duration
        total_decode_time += decode_time
        decode_times.append(decode_time)
        ref_n, hyp_n = normalize(reference), normalize(hypothesis)
        references.append(ref_n)
        hypotheses.append(hyp_n)
        coverage.scored.append(wav_path.name)
        samples.append({
            "file": wav_path.name,
            "duration_s": round(duration, 3),
            "decode_s": round(decode_time, 4),
            "ref": ref_n,
            "hyp": hyp_n,
            **word_ops(ref_n, hyp_n),
        })

        print(f"[{wav_path.name}] duration={duration:.2f}s decode={decode_time:.2f}s RTF={decode_time/duration:.3f}")

    print(f"Coverage     : {coverage.describe()}")
    if not references:
        print("No valid file pairs found.")
        return 1

    wer = jiwer.wer(references, hypotheses)
    rtf = total_decode_time / total_audio_duration
    peak_rss = get_peak_rss_mb()
    pct = decode_percentiles(decode_times)

    subject = external.describe(args.tool) if external is not None else args.engine
    print("\n--- Benchmark Results ---")
    print(f"Protocol     : {PROTOCOL_LABEL}")
    print(f"Dataset Size : {len(references)} files ({total_audio_duration:.2f}s total audio)")
    print(f"Coverage     : {coverage.describe()}")
    print(f"Subject      : {subject}")
    if engine_check is not None:
        resolved = engine_check.resolved_engine or "UNVERIFIED"
        tag = "  ** FALLBACK **" if engine_check.is_fallback else ""
        print(f"Resolved     : {resolved} / {engine_check.resolved_model or 'unreported'}{tag}")
    print(f"Model        : {args.model or '(tool default)'}")
    print(f"WER          : {wer * 100:.2f}%  (normalizer: {normalizer_name})")
    print(f"Overall RTF  : {rtf:.3f}x")
    p95 = (f"{pct['p95_ms']:.0f} ms" if pct["p95_ms"] is not None
           else f"withheld (n={pct['n']} < {MIN_SAMPLES_FOR_P95})")
    print(f"Decode p50   : {pct['p50_ms']:.0f} ms (warmed, per file)")
    print(f"Decode p95   : {p95}")
    if load_s is not None:
        print(f"Cold load    : {load_s:.2f}s (model build, excluded from decode); "
              f"warm-up {warmup_s or 0.0:.2f}s")
    if peak_rss > 0:
        print(f"Peak RSS     : {peak_rss:.1f} MB (whole-process peak)")
    else:
        print("Peak RSS     : N/A (psutil or resource not available)")

    print("\nMarkdown Table Row:")
    rss_str = f"{peak_rss:.1f} MB" if peak_rss > 0 else "N/A"
    label = args.tool if external is not None else args.engine
    # Peak RSS of *this* process is meaningless for a subprocess-based tool; reporting our
    # own footprint as theirs would be a fabricated number, so it is omitted explicitly.
    if external is not None:
        rss_str = "n/a (subprocess)"
    # The normaliser is part of the number, and so are a fallback and partial coverage:
    # all of them label the row so it cannot be pasted beside rows that differ.
    print(table_row(label=label, model=args.model, wer=wer, normalizer=normalizer_name,
                    rtf=rtf, rss_str=rss_str, coverage=coverage, engine_check=engine_check))

    if args.json_out is not None:
        doc = {
            "header": run_header(subject=subject, model=args.model, normalizer=normalizer_name,
                                 engine_check=engine_check, load_s=load_s, warmup_s=warmup_s),
            "summary": {
                "wer": wer,
                "rtf": rtf,
                "audio_s": round(total_audio_duration, 3),
                "decode": pct,
                "peak_rss_mb": round(peak_rss, 1) if peak_rss > 0 and external is None else None,
                "coverage": coverage.as_dict(),
            },
            "samples": samples,
        }
        args.json_out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                                 encoding="utf-8")
        print(f"\nPer-file JSON written to {args.json_out}")

    if not coverage.complete and not args.allow_partial:
        print(f"\nError: coverage is {coverage.describe()}. The WER above covers only the "
              "scored files. Pass --allow-partial to accept that explicitly.")
        return EXIT_PARTIAL
    return 0


if __name__ == "__main__":
    sys.exit(main())
