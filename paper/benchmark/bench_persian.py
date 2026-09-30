"""Persian ASR benchmark harness: score a manifest, emit schema-valid result JSON.

Part of FA-04 / #513, slice 1. Implements the result schema and the metrics of
`design/specs/persian-benchmark-and-validation.md` so that model-selection work
(FA-05) has an instrument to run against before any corpus is downloaded.

Two input modes, one output:

- ``--manifest``: a JSONL file of ``{"id", "audio", "reference"}`` rows (Corpus A/B
  adapters in slice 2 write this). Transcription goes through the shipping
  ``stt.factory.build_engine`` so the numbers describe YazSes' real decode path,
  exactly as ``bench_wer.py`` already does for English.
- ``--smoke``: a tiny built-in synthetic set with a mock engine that echoes the
  reference with one controlled edit. It exercises every code path — manifest
  parsing, both normalizers, raw and normalized metrics, the Persian quality
  block, the provenance stamp — with no audio, no model and no network, so CI can
  run the schema check the spec's acceptance criteria demand ("one command emits
  schema-valid result JSON").

The scoring core (``score_pairs``) is engine-agnostic and unit-tested directly;
``run()`` is only plumbing around it. Nothing in this file re-implements WER/CER —
that stays with jiwer, and the evaluation normalizer stays in ``persian_metrics``,
separate from the production normalizer per spec §6.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import jiwer
from persian_metrics import (
    EVAL_NORMALIZER_VERSION,
    compute_persian_quality,
    normalize_fa_eval_v1,
)

RESULT_SCHEMA_VERSION = 1

#: The corpus block for the synthetic smoke set. Not a real corpus; named plainly
#: so a smoke result can never be mistaken for a corpus measurement downstream.
SMOKE_CORPUS = {
    "name": "synthetic-smoke",
    "language": "fa",
    "version": "0",
    "split": "smoke",
}
#: Deliberately mixed raw/normalized traps: Arabic Yeh (raw differs, normalizes
#: equal), a real word error (survives both), a ZWNJ deletion (survives both).
SMOKE_PAIRS = [
    {
        "id": "smoke-001",
        "reference": "\u0633\u0644\u0627\u0645 \u062f\u0646\u06cc\u0627",
        # Arabic Yeh U+064A instead of Persian U+06CC: raw mismatch, normalized hit.
        "hypothesis": "\u0633\u0644\u0627\u0645 \u062f\u0646\u064a\u0627",
    },
    {
        "id": "smoke-002",
        "reference": "\u0627\u06cc\u0646 \u06a9\u062a\u0627\u0628 \u0631\u0627 \u062e\u0648\u0627\u0646\u062f\u0645",
        # A substitution: wrong word, wrong under both scorers.
        "hypothesis": "\u0627\u06cc\u0646 \u06a9\u062a\u0627\u0628 \u0631\u0627 \u062e\u0648\u062f\u062f\u0645",
    },
    {
        "id": "smoke-003",
        "reference": "\u0645\u06cc\u200c\u062e\u0648\u0627\u0647\u0645 \u0622\u0645\u062f\u0647 \u0627\u0633\u062a",
        # ZWNJ dropped in the hypothesis: real error under both scorers.
        "hypothesis": "\u0645\u06cc\u062e\u0648\u0627\u0647\u0645 \u0622\u0645\u062f\u0647 \u0627\u0633\u062a",
    },
]


def score_pairs(
    references: list[str], hypotheses: list[str], sample_ids: list[str]
) -> dict:
    """Score paired texts per spec §5: raw + normalized WER/CER, exact match, quality.

    Pure function of its inputs — no audio, no engine, no I/O — so every number in
    the result block is unit-testable in isolation. Empty references are skipped
    from WER/CER the same way ``bench_wer.py`` skips them: jiwer scores an empty
    reference as 100% insertions, which is a property of the scorer, not of the
    model.
    """
    if not (len(references) == len(hypotheses) == len(sample_ids)):
        raise ValueError(
            f"references/hypotheses/sample_ids must align: "
            f"{len(references)}/{len(hypotheses)}/{len(sample_ids)}"
        )
    if not references:
        raise ValueError("nothing to score: empty manifest")

    raw_pairs = [
        (r, h)
        for r, h in zip(references, hypotheses)
        if r.strip() and h.strip()
    ]
    norm_refs = [normalize_fa_eval_v1(r) for r, _ in raw_pairs]
    norm_hyps = [normalize_fa_eval_v1(h) for _, h in raw_pairs]

    def _wer(refs: list[str], hyps: list[str]) -> float | None:
        pairs = [(r, h) for r, h in zip(refs, hyps) if r.strip()]
        if not pairs:
            return None
        return round(
            jiwer.wer([r for r, _ in pairs], [h for _, h in pairs]) * 100, 2
        )

    def _cer(refs: list[str], hyps: list[str]) -> float | None:
        pairs = [(r, h) for r, h in zip(refs, hyps) if r.strip()]
        if not pairs:
            return None
        return round(
            jiwer.cer([r for r, _ in pairs], [h for _, h in pairs]) * 100, 2
        )

    exact_raw = sum(1 for r, h in raw_pairs if r == h)
    exact_norm = sum(
        1 for r, h in zip(norm_refs, norm_hyps) if r == h
    )
    n = len(raw_pairs)

    quality = compute_persian_quality(
        [r for r, _ in raw_pairs], [h for _, h in raw_pairs]
    )

    return {
        "n_pairs": n,
        "n_skipped_empty": len(references) - n,
        "wer_raw": _wer([r for r, _ in raw_pairs], [h for _, h in raw_pairs]),
        "wer_normalized": _wer(norm_refs, norm_hyps),
        "cer_raw": _cer([r for r, _ in raw_pairs], [h for _, h in raw_pairs]),
        "cer_normalized": _cer(norm_refs, norm_hyps),
        "exact_match_raw": round(exact_raw / n, 4),
        "exact_match_normalized": round(exact_norm / n, 4),
        "persian_quality": {
            "arabic_yeh_count": quality.arabic_yeh_count,
            "arabic_kaf_count": quality.arabic_kaf_count,
            "zwnj": quality.zwnj_metrics._asdict(),
        },
        "evaluation_normalizer": EVAL_NORMALIZER_VERSION,
    }


def _sha256_of(rows: list[dict]) -> str:
    """Content hash of the manifest rows — the selection's identity in the result."""
    blob = json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(blob).hexdigest()


def run_smoke() -> dict:
    """The CI path: score the built-in set, stamp provenance, no I/O beyond that."""
    return _assemble(
        corpus=SMOKE_CORPUS,
        model={
            "engine": "synthetic-echo",
            "name": "echo-with-one-edit",
            "revision": "0",
            "compute_type": "n/a",
        },
        decoder={
            "language": "fa",
            "beam_size": None,
            "condition_on_previous_text": None,
        },
        rows=SMOKE_PAIRS,
        references=[p["reference"] for p in SMOKE_PAIRS],
        hypotheses=[p["hypothesis"] for p in SMOKE_PAIRS],
        rtf=None,
        latency_p50_ms=None,
        latency_p95_ms=None,
    )


def run_manifest(manifest: Path, model_spec: str, cpu_threads: int = 0) -> dict:
    """Transcribe a JSONL manifest through the shipping engine and score it."""
    rows: list[dict] = []
    with manifest.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            for key in ("id", "audio", "reference"):
                if key not in row:
                    raise SystemExit(f"manifest row missing {key!r}: {row}")
            rows.append(row)
    if not rows:
        raise SystemExit(f"manifest has no rows: {manifest}")

    engine_name, _, model_name = model_spec.partition(":")
    if not model_name:
        model_name = engine_name
        engine_name = "faster-whisper"

    from _common import load_audio  # noqa: PLC0415 — optional heavy dep at call time

    engine = _build_checked(engine_name, model_name, cpu_threads)
    references: list[str] = []
    hypotheses: list[str] = []
    decode_times: list[float] = []
    durations: list[float] = []
    for row in rows:
        audio = load_audio(Path(row["audio"]))
        duration = len(audio) / 16000
        t0 = time.monotonic()
        hyp = engine.transcribe(audio)
        decode_times.append(time.monotonic() - t0)
        durations.append(duration)
        references.append(row["reference"])
        hypotheses.append(hyp)

    rtfs = [dt / dur if dur > 0 else 0.0 for dt, dur in zip(decode_times, durations)]
    sorted_rtfs = sorted(decode_times)
    p50 = sorted_rtfs[len(sorted_rtfs) // 2] * 1000
    p95 = sorted_rtfs[min(len(sorted_rtfs) - 1, int(len(sorted_rtfs) * 0.95))] * 1000

    return _assemble(
        corpus={
            "name": manifest.stem,
            "language": "fa",
            # The manifest's own identity: same content in, same version stamped
            # out. An mtime would move the "version" on every checkout, which is
            # the opposite of what §2 pins.
            "version": hashlib.sha256(manifest.read_bytes()).hexdigest()[:16],
            "split": "test",
        },
        model={
            "engine": engine_name,
            "name": model_name,
            "revision": None,
            "compute_type": None,
        },
        decoder={
            "language": "fa",
            "beam_size": getattr(engine, "beam_size", None),
            "condition_on_previous_text": None,
        },
        rows=rows,
        references=references,
        hypotheses=hypotheses,
        rtf=round(sorted(rtfs)[len(rtfs) // 2], 3),
        latency_p50_ms=round(p50, 1),
        latency_p95_ms=round(p95, 1),
    )


def _build_checked(engine_name: str, model_name: str, cpu_threads: int):
    """Build through the shipping factory, refusing the fallback it is kind enough to do.

    The exact hazard ``bench_wer.py`` documents: the factory degrades a missing
    extra to faster-whisper with a warning, which is right for dictation and fatal
    for a benchmark that would publish Whisper's numbers under another engine's
    name. So the class is checked against what was asked for.
    """
    from yazses.stt.factory import build_engine  # noqa: PLC0415

    expected = {
        "faster-whisper": "FasterWhisperEngine",
        "parakeet": "ParakeetEngine",
        "moonshine": "MoonshineEngine",
    }
    engine = build_engine(engine_name, model=model_name, cpu_threads=cpu_threads)
    want = expected.get(engine_name)
    if want and type(engine).__name__ != want:
        raise SystemExit(
            f"asked for {engine_name!r} but build_engine returned "
            f"{type(engine).__name__!r}; refusing to publish a mislabeled result"
        )
    return engine


def _assemble(
    *,
    corpus: dict,
    model: dict,
    decoder: dict,
    rows: list[dict],
    references: list[str],
    hypotheses: list[str],
    rtf: float | None,
    latency_p50_ms: float | None,
    latency_p95_ms: float | None,
) -> dict:
    """Build the §7 result document: schema, corpus, model, decoder, machine, metrics."""
    from _common import provenance  # noqa: PLC0415 — psutil is a benchmark-group dep

    metrics = score_pairs(
        references,
        hypotheses,
        [str(r.get("id", i)) for i, r in enumerate(rows)],
    )
    from datetime import UTC, datetime

    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    prov = provenance(timestamp)

    doc = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "yazses_commit": _yazses_commit(),
        "timestamp_utc": timestamp,
        "corpus": {**corpus, "samples": len(rows)},
        "selection": {
            "rows_sha256": _sha256_of(rows),
            "rule": "all rows in manifest order; no subsampling" if rows else "",
        },
        "model": model,
        "decoder": decoder,
        "machine": {
            "os": prov.get("os", "unknown"),
            "cpu": prov.get("cpu_model", "unknown"),
            "ram_gb": prov.get("ram_gb", 0),
        },
        "metrics": {
            "wer_raw": metrics["wer_raw"],
            "cer_raw": metrics["cer_raw"],
            "wer_normalized": metrics["wer_normalized"],
            "cer_normalized": metrics["cer_normalized"],
            "exact_match_raw": metrics["exact_match_raw"],
            "exact_match_normalized": metrics["exact_match_normalized"],
            "rtf": rtf,
            "latency_p50_ms": latency_p50_ms,
            "latency_p95_ms": latency_p95_ms,
            "persian_quality": metrics["persian_quality"],
            "evaluation_normalizer": metrics["evaluation_normalizer"],
        },
        "provenance": prov,
    }
    problems = validate_result(doc)
    if problems:
        raise SystemExit(
            "assembled result does not match the schema:\n  " + "\n  ".join(problems)
        )
    return doc


def _yazses_commit() -> str:
    import subprocess  # noqa: PLC0415

    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        return out.stdout.strip() or "unknown"
    except OSError:
        return "unknown"


def validate_result(doc: dict) -> list[str]:
    """Return a list of schema violations (empty = valid) for the §7 result document.

    Deliberately hand-written rather than jsonschema: the benchmark group is a
    build-only dependency set and adding one for a fifteen-field document would
    cost more than the validator. Every field the spec names is checked for
    presence and, where the spec fixes a type, for type.
    """
    problems: list[str] = []

    def _need(container: dict, key: str, container_name: str, types: tuple) -> None:
        if key not in container:
            problems.append(f"{container_name}.{key} missing")
        elif container[key] is not None and not isinstance(container[key], types):
            problems.append(
                f"{container_name}.{key} has type {type(container[key]).__name__}, "
                f"expected {types}"
            )

    for key in (
        "schema_version",
        "yazses_commit",
        "timestamp_utc",
        "corpus",
        "model",
        "decoder",
        "machine",
        "metrics",
    ):
        if key not in doc:
            problems.append(f"top-level {key} missing")
    if problems:
        return problems

    if doc["schema_version"] != RESULT_SCHEMA_VERSION:
        problems.append(
            f"schema_version {doc['schema_version']} != {RESULT_SCHEMA_VERSION}"
        )

    for key, types in (
        ("name", (str,)),
        ("language", (str,)),
        ("version", (str,)),
        ("split", (str,)),
        ("samples", (int,)),
    ):
        _need(doc["corpus"], key, "corpus", types)

    for key, types in (
        ("engine", (str,)),
        ("name", (str,)),
        ("revision", (str, type(None))),
        ("compute_type", (str, type(None))),
    ):
        _need(doc["model"], key, "model", types)

    _need(doc["decoder"], "language", "decoder", (str,))

    for key, types in (("os", (str,)), ("cpu", (str,)), ("ram_gb", (int, float))):
        _need(doc["machine"], key, "machine", types)

    for key in (
        "wer_raw",
        "cer_raw",
        "wer_normalized",
        "cer_normalized",
        "rtf",
        "latency_p50_ms",
        "latency_p95_ms",
    ):
        _need(doc["metrics"], key, "metrics", (int, float, type(None)))

    if "persian_quality" not in doc["metrics"]:
        problems.append("metrics.persian_quality missing")
    if doc["metrics"].get("evaluation_normalizer") != EVAL_NORMALIZER_VERSION:
        problems.append(
            "metrics.evaluation_normalizer missing or not "
            f"{EVAL_NORMALIZER_VERSION!r}"
        )
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--manifest", type=Path, help="JSONL manifest of a real corpus")
    src.add_argument(
        "--smoke",
        action="store_true",
        help="synthetic CI set; needs no audio, model or network",
    )
    parser.add_argument("--model", default="small", help="engine:model for --manifest")
    parser.add_argument("--out", type=Path, help="write result JSON here")
    parser.add_argument("--threads", type=int, default=0)
    args = parser.parse_args()

    if args.smoke:
        doc = run_smoke()
    else:
        doc = run_manifest(args.manifest, args.model, args.threads)

    blob = json.dumps(doc, indent=2, ensure_ascii=False)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(blob + "\n", encoding="utf-8")
        print(f"wrote {args.out} ({doc['metrics']['wer_raw']}% wer_raw)")
    else:
        print(blob)


if __name__ == "__main__":
    main()
