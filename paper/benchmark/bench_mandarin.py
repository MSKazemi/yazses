"""Mandarin ASR benchmark harness: CER under four views, S/D/I counts, licence record.

MODEL-01 of #503 (CHN-40). The instrument the Whisper ``small`` baseline (MODEL-02),
``large-v3-turbo`` (MODEL-03), ``large-v3`` (MODEL-04) and any later candidate are scored
with, so that every one of them uses the same corpus selection and the same normalization
-- the issue's first acceptance line. Modelled on `bench_persian.py`, and deliberately
sharing its manifest gate and its runtime helpers rather than restating them.

Two input modes, one output:

- ``--manifest``: a JSONL file of ``{"id", "audio", "reference"}`` rows plus its
  ``.meta.json`` sidecar, gated by `persian_manifest.load_manifest` (the gate is
  language-agnostic despite its name: licence and consent for every row, opaque
  pseudonyms, audio only from ``--audio-root``). ``--limit N --seed S`` selects a
  reproducible subset by hash. Transcription goes through the shipping
  ``stt.factory.build_engine`` with ``language="zh"`` and the production
  ``chinese_script`` conversion **off**, so the raw column is the model's own output.
  A manifest run is refused unless ``--model-license`` and ``--license-source`` say
  what licence the weights are under and where that was read (MODEL-06).
- ``--smoke``: a built-in synthetic set with hypotheses fixed in this file. No audio,
  no model, no network; it exercises every view, the S/D/I split, the validator and the
  provenance stamp, so CI can run "one command emits schema-valid result JSON".

What a result reports (see `mandarin_metrics.py` for the rules):

- ``cer_raw``: the code points as given -- what a user would receive;
- ``cer_punct``: zh-eval-v1 with punctuation kept (punctuation-aware CER);
- ``cer_normalized``: zh-eval-v1 (punctuation-stripped CER);
- ``cer_script_normalized``: the normalized view after an OpenCC fold to the reference's
  script, and ``script_delta_cer`` = normalized minus script-normalized. Only when OpenCC
  is importable; otherwise both are ``null`` and ``script_fold.applied`` is ``false``
  with the reason. A missing converter never produces a number that looks like one.

OpenCC is not a dependency of the benchmark group. It is imported lazily if present
(the ``chinese`` extra installs it); this file adds no dependency.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

from bench_persian import (
    _library_default,
    _peak_rss_mb,
    _resolve_cached_revision,
    _sha256_of,
    _yazses_commit,
    dumps_result,
)
from mandarin_metrics import (
    EVAL_NORMALIZER_VERSION,
    TOKENISATION,
    VIEWS,
    ScriptConverter,
    score,
)
from persian_manifest import ManifestError, load_manifest

RESULT_SCHEMA = "yazses.bench.mandarin/1"
RESULT_SCHEMA_VERSION = 1

#: Weight licences the project's Chinese model policy names as permissive
#: (design/adr/adr-v2-141-chinese-model-policy.md: "MIT/Apache-2.0/BSD-style"). A licence
#: outside this set is not judged here; ``in_permissive_allowlist: false`` means only
#: that a maintainer has to read it -- e.g. SenseVoiceSmall's custom FunASR licence.
PERMISSIVE_ALLOWLIST = frozenset({"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause"})

#: The two folds OpenCC's character-level configs provide, keyed by the reference script.
_OPENCC_CONFIG = {"simplified": "t2s", "traditional": "s2t"}

SMOKE_CORPUS = {
    "name": "synthetic-smoke",
    "language": "zh",
    "version": "0",
    "split": "smoke",
}

#: Each row is a trap one view exists for, so the columns are forced apart by construction.
SMOKE_PAIRS = [
    {
        # Width + punctuation: ASCII comma for a full-width one and a dropped 。.
        # raw: 1 S + 1 D; punct: 1 D (the 。); normalized: exact.
        "id": "smoke-001",
        "reference": "你好，世界。",
        "hypothesis": "你好,世界",
    },
    {
        # A real recognition error: 北京 heard as 背景. Two substitutions in every view.
        "id": "smoke-002",
        "reference": "我今天去北京",
        "hypothesis": "我今天去背景",
    },
    {
        # Right words, wrong script: 们学习汉语 written 們學習漢語 for a Simplified
        # reference. Five substitutions until the script fold, zero after it.
        "id": "smoke-003",
        "reference": "我们学习汉语",
        "hypothesis": "我們學習漢語",
    },
    {
        # An insertion (真的) and, below, a deletion (一杯): the S/D/I split must see both.
        "id": "smoke-004",
        "reference": "今天天气很好",
        "hypothesis": "今天天气真的很好",
    },
    {
        "id": "smoke-005",
        "reference": "我想喝一杯咖啡",
        "hypothesis": "我想喝咖啡",
    },
    {
        # Mandarin-English mixing: Whisper spaces around Latin and changes its case.
        # raw: 2 insertions + 1 substitution; normalized: exact.
        "id": "smoke-006",
        "reference": "我用iPhone拍照",
        "hypothesis": "我用 iphone 拍照",
    },
]


# -- pure helpers ---------------------------------------------------------------


def select_rows(rows: list[dict], seed: int, limit: int | None) -> tuple[list[dict], str]:
    """A reproducible subset of *rows* and the rule that chose it.

    With no limit every row is kept, in manifest order. With one, rows are ranked by
    ``sha256(f"{seed}:{id}")`` and the first *limit* kept -- a function of the ids and
    the seed only, so the same manifest and seed select the same utterances on any host
    -- and are then decoded in **manifest** order, because with
    ``condition_on_previous_text`` the decode order is part of the measurement.
    """
    if limit is None or limit >= len(rows):
        return list(rows), "all rows in manifest order; no subsampling"
    if limit <= 0:
        raise ValueError(f"--limit must be positive, got {limit}")

    def key(row: dict) -> str:
        return hashlib.sha256(f"{seed}:{row['id']}".encode()).hexdigest()

    chosen = {id(r) for r in sorted(rows, key=key)[:limit]}
    return (
        [r for r in rows if id(r) in chosen],
        "sha256(f'{seed}:{id}') ascending, first `limit` rows, decoded in manifest order",
    )


def license_record(
    model_id: str,
    revision: str | None,
    license_id: str | None,
    license_source: str | None,
    notes: str | None = None,
) -> dict:
    """MODEL-06's per-artifact record: which weights, which revision, under what licence.

    The licence is what the operator *read* at ``license_source``; this cannot verify it.
    ``in_permissive_allowlist`` is computed from it, never asserted, and is ``None`` when
    no licence was stated at all (the smoke set has no weights).
    """
    return {
        "model_id": model_id,
        "revision": revision,
        "license_id": license_id,
        "license_source": license_source,
        "in_permissive_allowlist": None if license_id is None else license_id in PERMISSIVE_ALLOWLIST,
        "policy": "design/adr/adr-v2-141-chinese-model-policy.md",
        "notes": notes,
    }


def load_script_converter(
    target: str | None, importer: Callable[[], object] | None = None
) -> tuple[ScriptConverter | None, dict]:
    """The OpenCC fold to *target*, or ``None`` with the reason; plus the result's record.

    *importer* returns the ``opencc`` module (injected by tests). Absent OpenCC is a
    documented no-op: the record says ``applied: false`` and why, and the script column
    is ``null``. OpenCC is never installed or required by this harness.
    """
    record: dict = {"target": target, "applied": False, "converter": None,
                    "opencc_version": None, "reason": None}
    if not target:
        record["reason"] = "no target script requested (--script none)"
        return None, record
    if target not in _OPENCC_CONFIG:
        raise ValueError(f"--script must be one of {sorted(_OPENCC_CONFIG)} or none, got {target!r}")
    try:
        if importer is not None:
            opencc = importer()
        else:
            import opencc  # noqa: PLC0415 - optional; the `chinese` extra installs it
    except ModuleNotFoundError:
        record["reason"] = "opencc is not importable; script fold not applied"
        return None, record
    config = _OPENCC_CONFIG[target]
    converter = opencc.OpenCC(config)  # type: ignore[attr-defined]
    record.update(
        applied=True,
        converter=f"opencc {config}",
        opencc_version=str(getattr(opencc, "__version__", None) or "unknown"),
    )
    return converter.convert, record


def score_pairs(
    references: list[str],
    hypotheses: list[str],
    script_converter: ScriptConverter | None = None,
) -> dict:
    """The ``metrics`` block's scored half: four CER views with their S/D/I counts."""
    s = score(references, hypotheses, script_converter=script_converter)
    v = s["views"]
    return {
        "n_pairs": s["n_pairs"],
        "n_skipped_empty": s["n_skipped_empty"],
        "cer_raw": v["raw"]["cer"],
        "cer_punct": v["punct"]["cer"],
        "cer_normalized": v["normalized"]["cer"],
        "cer_script_normalized": v["script"]["cer"] if v["script"] else None,
        "script_delta_cer": s["script_delta_cer"],
        "counts": v,
        "evaluation_normalizer": EVAL_NORMALIZER_VERSION,
        "tokenisation": TOKENISATION,
        "_per_utterance": s["per_utterance"],
    }


# -- the two modes --------------------------------------------------------------


def run_smoke(
    script: str | None = "simplified",
    *,
    importer: Callable[[], object] | None = None,
    timestamp: str | None = None,
) -> dict:
    """The CI path: score the built-in set, stamp provenance, no audio and no engine."""
    converter, fold = load_script_converter(script, importer)
    doc, _ = _assemble(
        corpus=SMOKE_CORPUS,
        model={"engine": "synthetic-echo", "name": "fixed-hypotheses",
               "revision": "0", "compute_type": "n/a"},
        model_license=license_record("synthetic-echo", "0", None, None,
                                     "synthetic smoke set: no model weights exist"),
        decoder={"language": "zh", "beam_size": None, "condition_on_previous_text": None,
                 "production_chinese_script": ""},
        script_fold=fold,
        converter=converter,
        rows=SMOKE_PAIRS,
        selection={"rule": "all rows in manifest order; no subsampling",
                   "seed": None, "limit": None, "n_manifest_rows": len(SMOKE_PAIRS)},
        references=[p["reference"] for p in SMOKE_PAIRS],
        hypotheses=[p["hypothesis"] for p in SMOKE_PAIRS],
        timing={"rtf": None, "latency_p50_ms": None, "latency_p95_ms": None},
        timestamp=timestamp,
    )
    return doc


def _build_checked(engine_name: str, model_name: str, cpu_threads: int):
    """Build through the shipping factory and refuse its fallback, as `bench_persian` does.

    ``language="zh"`` is explicit (an auto-detect pass would skew RTF), and
    ``chinese_script`` is left at its default (off): the production conversion would
    otherwise rewrite the raw column this harness exists to report.
    """
    from yazses.config import SttConfig  # noqa: PLC0415
    from yazses.stt.factory import build_engine  # noqa: PLC0415

    expected = {
        "faster-whisper": "FasterWhisperEngine",
        "parakeet": "ParakeetEngine",
        "moonshine": "MoonshineEngine",
    }
    engine = build_engine(
        SttConfig(
            engine=engine_name,
            model=model_name,
            language="zh",
            compute_type="int8",
            cpu_threads=cpu_threads,
        )
    )
    want = expected.get(engine_name)
    if want and type(engine).__name__ != want:
        raise RuntimeError(
            f"asked for engine {engine_name!r} ({want}) and the factory returned "
            f"{type(engine).__name__}. build_engine falls back to faster-whisper when an "
            "optional dependency is missing, so this run would have published one "
            "engine's numbers under another's name. Install the extra and re-run."
        )
    return engine


def _decode_settings(engine_name: str, model_name: str, engine) -> tuple[dict, dict]:
    """The ``model`` and ``decoder`` blocks read off the live engine (cf. `bench_persian`)."""
    model = {"engine": engine_name, "name": model_name, "revision": None, "compute_type": None}
    decoder = {"language": "zh", "beam_size": None, "condition_on_previous_text": None,
               "production_chinese_script": ""}
    fw_model = getattr(engine, "_model", None)
    if fw_model is None:
        return model, decoder
    model["compute_type"] = getattr(getattr(fw_model, "model", None), "compute_type", None)
    model["revision"] = _resolve_cached_revision(model_name)
    passed = int(getattr(engine, "_beam_size", 0) or 0)
    decoder["beam_size"] = passed if passed > 0 else _library_default(type(fw_model), "transcribe", "beam_size")
    decoder["condition_on_previous_text"] = bool(getattr(engine, "_condition_on_previous_text", True))
    decoder["language"] = getattr(engine, "_language", "zh") or "zh"
    return model, decoder


def run_manifest(
    manifest: Path,
    model_spec: str,
    *,
    license_id: str | None,
    license_source: str | None,
    model_revision: str | None = None,
    license_notes: str | None = None,
    cpu_threads: int = 0,
    seed: int = 0,
    limit: int | None = None,
    script: str | None = "simplified",
    hyps_out: Path | None = None,
    audio_root: Path | None = None,
    transcriber: Callable | None = None,
    audio_loader: Callable | None = None,
    importer: Callable[[], object] | None = None,
    timestamp: str | None = None,
) -> dict:
    """Transcribe a JSONL manifest through the shipping engine and score it.

    Refused before any model is built when the manifest gate fails or when the weight
    licence is not stated. ``transcriber`` (``audio -> str``), ``audio_loader``
    (``Path -> ndarray``), ``importer`` and ``timestamp`` are injection points so tests
    need no model, no audio decoder, no OpenCC and no clock.
    """
    if not (license_id and license_id.strip()) or not (license_source and license_source.strip()):
        raise SystemExit(
            "refusing to run: state the weight licence and where it was read "
            "(--model-license SPDX-ID --license-source URL). MODEL-06 of #503 needs it "
            "recorded for every tested artifact; a result without it cannot be promoted."
        )
    try:
        loaded = load_manifest(manifest, audio_root)
    except ManifestError as exc:
        raise SystemExit(str(exc)) from exc
    all_rows = list(loaded.rows)
    rows, rule = select_rows(all_rows, seed, limit)
    keep = {r["id"] for r in rows}
    entries = [e for e in loaded.entries if e.id in keep]
    converter, fold = load_script_converter(script, importer)

    engine_name, _, model_name = model_spec.partition(":")
    if not model_name:
        model_name, engine_name = engine_name, "faster-whisper"

    import psutil  # noqa: PLC0415 - benchmark-group dependency
    from cost_meter import os_cpu_times  # noqa: PLC0415

    if audio_loader is None:
        from _common import load_audio as audio_loader  # noqa: PLC0415

    proc = psutil.Process()
    rss_before_mb = proc.memory_info().rss / 1e6
    load_t0 = time.monotonic()
    engine = (_build_checked(engine_name, model_name, cpu_threads) if transcriber is None
              else SimpleNamespace(transcribe=transcriber))
    model_load_s = time.monotonic() - load_t0

    references: list[str] = []
    hypotheses: list[str] = []
    decode_s: list[float] = []
    audio_s: list[float] = []
    cpu0 = sum(os_cpu_times())
    for entry in entries:
        audio = audio_loader(entry.audio)
        audio_s.append(len(audio) / 16000)
        t0 = time.monotonic()
        hyp = engine.transcribe(audio)
        decode_s.append(time.monotonic() - t0)
        references.append(entry.reference)
        hypotheses.append(hyp)
    decode_core_s = sum(os_cpu_times()) - cpu0

    model_block, decoder_block = _decode_settings(engine_name, model_name, engine)
    if model_revision:
        model_block["revision"] = model_revision
    peak_mb, peak_source = _peak_rss_mb(proc)
    rtfs = sorted(dt / dur if dur > 0 else 0.0 for dt, dur in zip(decode_s, audio_s))
    lat = sorted(decode_s)
    meta = loaded.meta
    pins = {k: meta[k] for k in ("dataset", "revision", "config", "audio_archive_sha256",
                                 "audio_archive_verified") if k in meta}
    doc, per_utterance = _assemble(
        corpus={
            "name": manifest.stem,
            "language": "zh",
            "version": loaded.sha256[:16],
            "split": meta["split"] if isinstance(meta.get("split"), str) else "test",
            "licenses": sorted({e.license for e in entries}),
            "consents": sorted({e.consent for e in entries}),
        },
        model=model_block,
        model_license=license_record(
            model_name, model_block["revision"], license_id.strip(), license_source.strip(),
            license_notes,
        ),
        decoder=decoder_block,
        script_fold=fold,
        converter=converter,
        rows=rows,
        selection={"rule": rule, "seed": seed if limit is not None else None,
                   "limit": limit, "n_manifest_rows": len(all_rows)},
        references=references,
        hypotheses=hypotheses,
        timing={
            "rtf": round(rtfs[len(rtfs) // 2], 3),
            "latency_p50_ms": round(lat[len(lat) // 2] * 1000, 1),
            "latency_p95_ms": round(lat[min(len(lat) - 1, int(len(lat) * 0.95))] * 1000, 1),
        },
        runtime={
            "model_load_s": round(model_load_s, 2),
            "rss_before_load_mb": round(rss_before_mb, 1),
            "peak_rss_mb": peak_mb,
            "peak_rss_source": peak_source,
            "decode_core_s": round(decode_core_s, 3),
            "audio_s": round(sum(audio_s), 2),
        },
        manifest={"sha256": loaded.sha256, "pins": pins},
        timestamp=timestamp,
    )
    if hyps_out is not None:
        hyps_out.parent.mkdir(parents=True, exist_ok=True)
        with hyps_out.open("w", encoding="utf-8") as fh:
            for entry, ref, hyp, counts in zip(entries, references, hypotheses, per_utterance):
                fh.write(json.dumps({"id": entry.id, "reference": ref, "hypothesis": hyp,
                                     "counts": counts}, ensure_ascii=False) + "\n")
    return doc


def _assemble(
    *,
    corpus: dict,
    model: dict,
    model_license: dict,
    decoder: dict,
    script_fold: dict,
    converter: ScriptConverter | None,
    rows: list[dict],
    selection: dict,
    references: list[str],
    hypotheses: list[str],
    timing: dict,
    runtime: dict | None = None,
    manifest: dict | None = None,
    timestamp: str | None = None,
) -> tuple[dict, list[dict | None]]:
    """Build and validate the result document; also return the per-utterance counts.

    The per-utterance list (``None`` for a skipped empty reference) is kept out of the
    document, which stays a corpus-level summary, and written by ``--hyps-out``.
    """
    from datetime import UTC, datetime  # noqa: PLC0415

    from _common import provenance  # noqa: PLC0415 - psutil is a benchmark-group dep

    metrics = score_pairs(references, hypotheses, converter)
    per_utterance = metrics.pop("_per_utterance")
    timestamp = timestamp or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    prov = provenance(timestamp)
    doc: dict = {
        "schema": RESULT_SCHEMA,
        "schema_version": RESULT_SCHEMA_VERSION,
        "yazses_commit": _yazses_commit(),
        "timestamp_utc": timestamp,
        "corpus": {**corpus, "samples": len(rows)},
        "selection": {"rows_sha256": _sha256_of(rows), **selection},
        "model": model,
        "model_license": model_license,
        "decoder": decoder,
        "script_fold": script_fold,
        "machine": {
            "os": prov.get("os", "unknown"),
            "cpu": prov.get("cpu_model", "unknown"),
            "ram_gb": prov.get("ram_gb", 0),
        },
        "metrics": {**metrics, **timing},
        "provenance": prov,
    }
    if runtime is not None:
        doc["runtime"] = runtime
    if manifest is not None:
        doc["manifest"] = manifest
    problems = validate_result(doc)
    if problems:
        raise SystemExit("assembled result does not match the schema:\n  " + "\n  ".join(problems))
    return doc, per_utterance


# -- the schema -----------------------------------------------------------------

_NUM = (int, float, type(None))
_STR_OR_NONE = (str, type(None))


def validate_result(doc: dict) -> list[str]:
    """Return every schema violation in *doc* (empty = valid).

    Hand-written, as in `bench_persian.py`, so the benchmark group gains no dependency.
    Beyond presence and type it checks the document against itself: each view's CER must
    be its own edit counts over its own reference length, the script column must be
    ``null`` exactly when the fold was not applied, and the allowlist verdict must follow
    from the stated licence. A hand-edited number fails here.
    """
    problems: list[str] = []
    if not isinstance(doc, dict):
        return [f"document has type {type(doc).__name__}, expected dict"]

    def need(container: object, key: str, where: str, types: tuple) -> None:
        if not isinstance(container, dict):
            problems.append(f"{where} missing or not an object")
        elif key not in container:
            problems.append(f"{where}.{key} missing")
        elif container[key] is not None and not isinstance(container[key], types):
            problems.append(f"{where}.{key} has type {type(container[key]).__name__}")

    top = ("schema", "schema_version", "yazses_commit", "timestamp_utc", "corpus",
           "selection", "model", "model_license", "decoder", "script_fold", "machine",
           "metrics", "provenance")
    missing = [k for k in top if k not in doc]
    if missing:
        return [f"top-level {k} missing" for k in missing]
    if doc["schema"] != RESULT_SCHEMA:
        problems.append(f"schema {doc['schema']!r} != {RESULT_SCHEMA!r}")
    if doc["schema_version"] != RESULT_SCHEMA_VERSION:
        problems.append(f"schema_version {doc['schema_version']} != {RESULT_SCHEMA_VERSION}")

    for key, types in (("name", (str,)), ("language", (str,)), ("version", (str,)),
                       ("split", (str,)), ("samples", (int,))):
        need(doc["corpus"], key, "corpus", types)
    need(doc["selection"], "rows_sha256", "selection", (str,))
    need(doc["selection"], "rule", "selection", (str,))
    for key in ("seed", "limit", "n_manifest_rows"):
        need(doc["selection"], key, "selection", (int, type(None)))
    for key in ("engine", "name"):
        need(doc["model"], key, "model", (str,))
    for key in ("revision", "compute_type"):
        need(doc["model"], key, "model", _STR_OR_NONE)
    lic = doc["model_license"]
    for key in ("model_id", "revision", "license_id", "license_source", "policy", "notes"):
        need(lic, key, "model_license", _STR_OR_NONE)
    need(lic, "in_permissive_allowlist", "model_license", (bool, type(None)))
    if isinstance(lic, dict) and "license_id" in lic:
        expect = None if lic["license_id"] is None else lic["license_id"] in PERMISSIVE_ALLOWLIST
        if lic.get("in_permissive_allowlist") != expect:
            problems.append("model_license.in_permissive_allowlist does not follow from license_id")
    need(doc["decoder"], "language", "decoder", (str,))
    fold = doc["script_fold"]
    need(fold, "applied", "script_fold", (bool,))
    for key in ("target", "converter", "opencc_version", "reason"):
        need(fold, key, "script_fold", _STR_OR_NONE)
    for key, types in (("os", (str,)), ("cpu", (str,)), ("ram_gb", (int, float))):
        need(doc["machine"], key, "machine", types)
    for key in ("timestamp", "cpu_model", "os", "python", "yazses"):
        need(doc["provenance"], key, "provenance", (str,))

    m = doc["metrics"]
    for key in ("cer_raw", "cer_punct", "cer_normalized", "cer_script_normalized",
                "script_delta_cer", "rtf", "latency_p50_ms", "latency_p95_ms"):
        need(m, key, "metrics", _NUM)
    for key in ("n_pairs", "n_skipped_empty"):
        need(m, key, "metrics", (int,))
    if isinstance(m, dict) and m.get("evaluation_normalizer") != EVAL_NORMALIZER_VERSION:
        problems.append(f"metrics.evaluation_normalizer missing or not {EVAL_NORMALIZER_VERSION!r}")
    if isinstance(m, dict) and not isinstance(m.get("tokenisation"), str):
        problems.append("metrics.tokenisation must be a string")
    counts = m.get("counts") if isinstance(m, dict) else None
    if not isinstance(counts, dict) or set(counts) != set(VIEWS):
        problems.append(f"metrics.counts must hold exactly the views {list(VIEWS)}")
        return problems

    applied = isinstance(fold, dict) and fold.get("applied") is True
    column = {"raw": "cer_raw", "punct": "cer_punct", "normalized": "cer_normalized",
              "script": "cer_script_normalized"}
    for view in VIEWS:
        block = counts[view]
        if view == "script" and not applied:
            if block is not None or m.get("cer_script_normalized") is not None \
                    or m.get("script_delta_cer") is not None:
                problems.append("script view reported although script_fold.applied is false")
            continue
        if not isinstance(block, dict):
            problems.append(f"metrics.counts.{view} missing")
            continue
        fields = ("substitutions", "deletions", "insertions", "hits", "ref_chars")
        if any(not isinstance(block.get(k), int) or block[k] < 0 for k in fields):
            problems.append(f"metrics.counts.{view} needs non-negative integer {fields}")
            continue
        if block["hits"] + block["substitutions"] + block["deletions"] != block["ref_chars"]:
            problems.append(f"metrics.counts.{view}: hits + S + D != ref_chars")
        errors = block["substitutions"] + block["deletions"] + block["insertions"]
        want = round(errors / block["ref_chars"] * 100, 2) if block["ref_chars"] else None
        if block.get("cer") != want or m.get(column[view]) != want:
            problems.append(f"metrics.{column[view]} is not its own counts' CER ({want})")

    if "runtime" in doc:
        rt = doc["runtime"]
        for key in ("model_load_s", "rss_before_load_mb", "peak_rss_mb", "decode_core_s", "audio_s"):
            need(rt, key, "runtime", (int, float))
        if isinstance(rt, dict) and rt.get("peak_rss_source") not in ("VmHWM", "rss"):
            problems.append("runtime.peak_rss_source must be 'VmHWM' or 'rss'")
    if "manifest" in doc:
        need(doc["manifest"], "sha256", "manifest", (str,))
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--manifest", type=Path, help="JSONL manifest of a real corpus")
    src.add_argument("--smoke", action="store_true",
                     help="synthetic CI set; needs no audio, model or network")
    parser.add_argument("--model", default="small", help="engine:model for --manifest")
    parser.add_argument("--model-revision", help="weight revision/hash, when the HF cache cannot say")
    parser.add_argument("--model-license", help="SPDX id of the weight licence (required with --manifest)")
    parser.add_argument("--license-source", help="where that licence was read (required with --manifest)")
    parser.add_argument("--license-notes", help="redistribution obligations or caveats, free text")
    parser.add_argument("--script", default="simplified",
                        choices=["simplified", "traditional", "none"],
                        help="script of the references; the script view folds both texts to it")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--limit", type=int, help="score a hash-selected subset of N rows")
    parser.add_argument("--threads", type=int, default=0)
    parser.add_argument("--audio-root", type=Path,
                        help="the only directory --manifest audio may be read from")
    parser.add_argument("--hyps-out", type=Path,
                        help="also write per-utterance transcripts and S/D/I counts (JSONL)")
    parser.add_argument("--out", type=Path, help="write result JSON here")
    args = parser.parse_args()
    if args.smoke and (args.hyps_out or args.audio_root or args.limit is not None):
        parser.error("--hyps-out, --audio-root and --limit need --manifest")
    script = None if args.script == "none" else args.script

    if args.smoke:
        doc = run_smoke(script)
    else:
        doc = run_manifest(
            args.manifest, args.model,
            license_id=args.model_license, license_source=args.license_source,
            model_revision=args.model_revision, license_notes=args.license_notes,
            cpu_threads=args.threads, seed=args.seed, limit=args.limit, script=script,
            hyps_out=args.hyps_out, audio_root=args.audio_root,
        )

    blob = dumps_result(doc)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(blob + "\n", encoding="utf-8")
        print(f"wrote {args.out} ({doc['metrics']['cer_normalized']}% cer_normalized)")
    else:
        print(blob)


if __name__ == "__main__":
    main()
