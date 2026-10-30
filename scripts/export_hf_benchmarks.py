#!/usr/bin/env python3
"""Export the archived benchmark results as a curated Hugging Face evaluation dataset.

``paper/results/`` holds one JSON per experiment, written by the harness in
``paper/benchmark/``.  This script turns an explicit **allowlist** of those files into
flat CSV tables under ``huggingface/benchmarks/data/`` -- tables of numbers, never audio,
transcripts or corpora -- plus ``export-metadata.json`` (what went in, what was left out and
why, row counts) and ``SHA256SUMS``.

Design rules, each of which exists because the archive's own README learned it the hard way:

* **Allowlist, not glob.**  A file reaches the dataset only if it is named in ``ALLOWLIST``.
  Every other file under ``paper/results/`` is listed in the metadata with a reason, so a new
  archive file cannot slip in -- or silently vanish -- without ``--check`` failing.
* **One table per experiment family.**  WER grids, beam sweeps, latency, streaming, Persian,
  diarization and the command grammar measure different things in different units; they are
  never merged into one ranking.  A ``*-significance`` file is an *analysis* of a measurement
  (it decodes nothing), so it lives in its own ``significance_*`` tables, labelled
  ``record_kind = significance_analysis``.
* **Copy, never recompute.**  Values are copied from the JSON text.  Floats are parsed as
  ``Decimal`` so ``4.30`` stays ``4.30`` and ``1.0`` stays ``1.0``; no metric is recomputed and
  no normalisation changed.  A missing value is the empty string -- never ``0``, never inferred.
* **Byte-reproducible.**  Stable row order, ``\\n`` newlines, no generation timestamp in any
  output.  ``--check`` regenerates in memory and compares bytes.
* **Nothing sensitive.**  Every string in every source record, and every output cell, is scanned
  for home-directory paths, e-mail addresses, access tokens and private-tree paths.  A hit
  aborts the export naming the file and the field.
* **Writes are fenced.**  The only directory this script writes to is
  ``huggingface/benchmarks/data``; it refuses any other target (``paper/results`` above all).

Usage::

    uv run python scripts/export_hf_benchmarks.py --list
    uv run python scripts/export_hf_benchmarks.py --write
    uv run python scripts/export_hf_benchmarks.py --check      # exit 1 on drift, never writes
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_REL = "paper/results"
OUT_REL = "huggingface/benchmarks/data"
SCHEMA_VERSION = "1"
SOURCE_REPOSITORY = "https://github.com/MSKazemi/yazses"
GENERATOR = "scripts/export_hf_benchmarks.py"

RECORD_KINDS = ("measurement", "significance_analysis", "superseded", "withdrawn")
METADATA_NAME = "export-metadata.json"
SUMS_NAME = "SHA256SUMS"


class ExportError(Exception):
    """A source record is malformed, sensitive, or the requested write is not allowed."""


# --------------------------------------------------------------------------------------
# Sensitivity scan
# --------------------------------------------------------------------------------------

#: Private trees (``design/README.md`` tiers; mirrors ``tests/test_private_tiers_stay_private``).
_PRIVATE_TREES = r"(?:strategy|design/vision|design/marketing|design/seo|\.claude|\.git-private|\.dualgit)"

SENSITIVE_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("home-directory path", re.compile(r"(?<![\w$])/(?:home|Users|root)/[A-Za-z0-9_.-]+")),
    ("home-directory path", re.compile(r"[A-Za-z]:\\+Users\\+[A-Za-z0-9_.-]+")),
    ("e-mail address", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")),
    ("Hugging Face token", re.compile(r"\bhf_[A-Za-z0-9]{12,}")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{12,}")),
    ("GitHub token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{12,}")),
    ("API key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}")),
    ("cloud access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("chat token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("bearer credential", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{20,}")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    (
        "private-tree path",
        re.compile(rf"(?<![A-Za-z0-9_.-]){_PRIVATE_TREES}(?:/|$)"),
    ),
)


def scan_text(text: str) -> list[str]:
    """Names of the sensitivity rules *text* trips (never the matched text itself)."""
    return sorted({name for name, pat in SENSITIVE_RULES if pat.search(text)})


def _walk_strings(value: Any, path: str = "$") -> Iterable[tuple[str, str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, Mapping):
        for k, v in value.items():
            yield f"{path}.<key {k!r}>", str(k)
            yield from _walk_strings(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _walk_strings(v, f"{path}[{i}]")


def scan_document(doc: Any, where: str) -> None:
    """Raise :class:`ExportError` if any string inside *doc* looks sensitive."""
    for path, text in _walk_strings(doc):
        hits = scan_text(text)
        if hits:
            raise ExportError(
                f"{where}: sensitive content at {path} ({', '.join(hits)}); "
                "refusing to export. Fix the source artifact or leave the file out of the allowlist."
            )


# --------------------------------------------------------------------------------------
# Allowlist
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Source:
    """One allowlisted archive file and how to read it."""

    path: str  # relative to paper/results, posix
    table: str
    parser: str
    kind: str = "measurement"
    experiment: str = ""
    note: str = ""  # curation note shown in the ``curation_note`` column (not from the source)

    def __post_init__(self) -> None:
        if self.kind not in RECORD_KINDS:
            raise ValueError(f"{self.path}: unknown record kind {self.kind!r}")


def _beam(path: str, experiment: str) -> Source:
    return Source(path, "beam_sweep", "beam", experiment=experiment)


def _beam_sig(path: str, experiment: str) -> Source:
    return Source(
        path, "significance_beam", "beam_significance",
        kind="significance_analysis", experiment=experiment,
    )


_PERSIAN_NOTES = {
    "persian-fleurs-test871-small-idle.json": (
        "idle-host re-measure of persian-fleurs-test871-small.json; both are kept because the "
        "difference between them is itself a finding about host load"
    ),
    "persian-fleurs-test50-small-repeat.json": (
        "run-to-run repeat of persian-fleurs-test50-small.json on the same host"
    ),
    "persian-fleurs-test871-steja-small.json": (
        "fine-tuned checkpoint (CT2 int8 conversion), not the stock model"
    ),
    "persian-cvfa-test10559-steja-small.json": (
        "fine-tuned checkpoint (CT2 int8 conversion), not the stock model"
    ),
}

_PERSIAN_FILES = (
    "persian-cvfa-test10559-small.json",
    "persian-cvfa-test10559-steja-small.json",
    "persian-fleurs-test50-base.json",
    "persian-fleurs-test50-medium.json",
    "persian-fleurs-test50-small-repeat.json",
    "persian-fleurs-test50-small.json",
    "persian-fleurs-test871-base.json",
    "persian-fleurs-test871-large-v3-turbo.json",
    "persian-fleurs-test871-small-idle.json",
    "persian-fleurs-test871-small.json",
    "persian-fleurs-test871-steja-small.json",
)

ALLOWLIST: tuple[Source, ...] = (
    # --- ASR accuracy on LibriSpeech (WER + RTF per engine/checkpoint) -----------------
    Source("wer.json", "asr_librispeech_wer", "wer"),
    Source("wer-test-other.json", "asr_librispeech_wer", "wer"),
    # --- [stt] beam_size sweeps ---------------------------------------------------------
    _beam("beam-test-clean.json", "beam-test"),
    _beam("beam-test-other.json", "beam-test"),
    _beam("beam-governor-test-clean.json", "beam-governor"),
    _beam("beam-governor-test-other.json", "beam-governor"),
    # --- silence lead-in ---------------------------------------------------------------
    Source("onset.json", "onset_first_word", "onset"),
    # --- latency, pipeline stages, streaming -------------------------------------------
    Source("latency.json", "latency_decode", "latency_decode"),
    Source("latency.json", "latency_pipeline_stages", "latency_stages"),
    Source("streaming.json", "streaming_latency", "streaming"),
    # --- gates -------------------------------------------------------------------------
    Source("vad.json", "vad_gate", "vad"),
    Source("commands.json", "command_grammar", "commands"),
    # --- Persian -----------------------------------------------------------------------
    *(
        Source(p, "persian_asr", "persian", note=_PERSIAN_NOTES.get(p, ""))
        for p in _PERSIAN_FILES
    ),
    # --- diarization -------------------------------------------------------------------
    Source("diarization-ami16_corpus-der.json", "diarization_recordings", "diar_recordings"),
    Source("diarization-ami16_corpus-der.json", "diarization_corpus_summary", "diar_summary"),
    Source(
        "diarization-ami16_corpus-maxspk4.json", "diarization_recordings", "diar_recordings",
        note="speaker count pinned to four (--max-speakers 4); cluster_threshold is inert under a pinned count",
    ),
    Source(
        "diarization-ami16_corpus-maxspk4.json", "diarization_corpus_summary", "diar_summary",
        note="speaker count pinned to four (--max-speakers 4); cluster_threshold is inert under a pinned count",
    ),
    # --- significance analyses (decode nothing; read a measurement above) ---------------
    _beam_sig("beam-test-clean-significance.json", "beam-test"),
    _beam_sig("beam-test-clean-significance-vs-beam2.json", "beam-test"),
    _beam_sig("beam-test-other-significance.json", "beam-test"),
    _beam_sig("beam-test-other-significance-vs-beam2.json", "beam-test"),
    _beam_sig("beam-governor-test-clean-significance.json", "beam-governor"),
    _beam_sig("beam-governor-test-clean-significance-vs-beam2.json", "beam-governor"),
    _beam_sig("beam-governor-test-other-significance.json", "beam-governor"),
    _beam_sig("beam-governor-test-other-significance-vs-beam2.json", "beam-governor"),
    Source("onset-significance.json", "significance_onset", "onset_significance",
           kind="significance_analysis"),
    Source("diarization-ami16_corpus-maxspk4-vs-der-significance.json",
           "significance_diarization", "diar_significance", kind="significance_analysis"),
)

#: Fields deliberately left out of the tables, per source family (stated in the metadata).
FIELDS_NOT_EXPORTED: dict[str, list[str]] = {
    "beam_sweep": ["rows[].per_utt_errors", "rows[].per_utt_ref_words (per-utterance arrays)"],
    "onset_first_word": ["rows[].first_word_hits (per-utterance 0/1 string)"],
    "significance_onset": ["distinct[] (per-run consistency summary)"],
    "all_tables": [
        "provenance.kernel", "provenance.python", "provenance.numpy",
        "(machine columns keep cpu_model, logical_cpus, ram_gb and os only)",
    ],
}

#: Exclusion rules for everything under paper/results/ that is not allowlisted. First match wins.
#: Each is (predicate on the posix relative path, reason).
_EXCLUSION_RULES: tuple[tuple[Callable[[str], bool], str], ...] = (
    (lambda p: p.endswith(".md"),
     "documentation about the archive, not a result"),
    (lambda p: p == "index.json",
     "superseded roll-up snapshot written by run_all.py (2.12.0.dev4); its wer block "
     "duplicates wer.json, so exporting both would count the same decode twice"),
    (lambda p: p == "meta.json",
     "mixes three unrelated families (dysfluency-gate evaluation, model disk footprint, "
     "repository size statistics); not normalised in schema version 1"),
    (lambda p: p == "platform-resolution.json",
     "install-target resolution per OS and instruction set; not an accuracy, latency or "
     "diarization evaluation"),
    (lambda p: p == "plausibility-ami16-1.2.json",
     "argv records a path inside a private working tree, which the sensitivity scan rejects; "
     "also a different family (attribution-warning firing rate), not normalised in schema version 1"),
    (lambda p: p.startswith("plausibility-"),
     "attribution-warning firing-rate study with nested per-recording label-second maps; "
     "different family, not normalised in schema version 1"),
    (lambda p: p.startswith("centroid-merge-"),
     "per-cluster embedding centroids and every cluster-pair cosine; bulky derived embedding "
     "data rather than a summary table"),
    (lambda p: p.startswith("history/"),
     "dated copy kept for the archive's own history (a probe run or an earlier "
     "platform-resolution snapshot); not a current result"),
    (lambda p: p.startswith("platforms/"),
     "one-off CI-runner smoke run (60 utterances, shared hardware of unknown neighbours, "
     "load average noted); its README says it is not the published table, so it is not "
     "mixed with the dedicated-host 200-utterance runs"),
    (lambda p: p.startswith("probes/logs/") or not p.endswith(".json"),
     "raw run log or non-JSON file; may carry host paths and has no structured schema"),
    (lambda p: p.startswith("probes/"),
     "exploratory probe made while a question was being scoped, not a harness result; "
     "its README marks some as superseded by a committed harness script"),
)
_DEFAULT_EXCLUSION = (
    "not reviewed for export: add it to ALLOWLIST (with a parser) or to an exclusion rule"
)


def exclusion_reason(rel: str) -> str:
    for pred, reason in _EXCLUSION_RULES:
        if pred(rel):
            return reason
    return _DEFAULT_EXCLUSION


# --------------------------------------------------------------------------------------
# Reading and value helpers
# --------------------------------------------------------------------------------------


def _no_constant(name: str) -> Any:
    raise ValueError(f"non-finite number {name} is not valid in an archived result")


def parse_json_text(text: str, where: str) -> Any:
    """Parse JSON keeping every float's written form (``Decimal``) and refusing NaN/Infinity."""
    try:
        return json.loads(text, parse_float=Decimal, parse_constant=_no_constant)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ExportError(f"{where}: not valid JSON ({exc})") from exc


def fmt(value: Any) -> str:
    """Render one cell: empty for missing, source text for numbers, JSON for containers."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return value
    return _compact_json(value)


def _compact_json(value: Any) -> str:
    """Canonical JSON for container cells, keeping every number as the source wrote it."""
    if isinstance(value, dict):
        items = ",".join(
            f"{json.dumps(str(k), ensure_ascii=False)}:{_compact_json(v)}"
            for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
        )
        return "{" + items + "}"
    if isinstance(value, list):
        return "[" + ",".join(_compact_json(v) for v in value) + "]"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, Decimal)):
        return fmt(value)
    return json.dumps(value, ensure_ascii=False)


def _obj(value: Any, where: str, what: str = "object") -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ExportError(f"{where}: expected {what} (JSON object), got {type(value).__name__}")
    return value


def _list(value: Any, where: str) -> list[Any]:
    if not isinstance(value, list):
        raise ExportError(f"{where}: expected a JSON array, got {type(value).__name__}")
    return value


def get(d: Mapping[str, Any], key: str, where: str, *, required: bool = False,
        numeric: bool = False) -> Any:
    """``d[key]`` or ``None`` -- never a default.  *required* raises, *numeric* type-checks."""
    value = d.get(key)
    if value is None:
        if required:
            raise ExportError(f"{where}: missing required field {key!r}")
        return None
    if numeric and (isinstance(value, bool) or not isinstance(value, (int, Decimal))):
        raise ExportError(f"{where}: field {key!r} must be a number, got {value!r}")
    return value


def interval(d: Mapping[str, Any], key: str, where: str) -> tuple[Any, Any]:
    """Split a ``[low, high]`` pair; a missing pair is two empties, a malformed one an error."""
    value = d.get(key)
    if value is None:
        return None, None
    if not (isinstance(value, list) and len(value) == 2
            and all(isinstance(x, (int, Decimal)) and not isinstance(x, bool) for x in value)):
        raise ExportError(f"{where}: field {key!r} must be a [low, high] pair of numbers")
    return value[0], value[1]


# --------------------------------------------------------------------------------------
# Common provenance columns
# --------------------------------------------------------------------------------------

COMMON_HEAD = ("record_kind", "source_file", "source_pointer")
COMMON_TAIL = (
    "source_sha256", "source_git_commit", "timestamp_utc",
    "machine", "machine_cpu_model", "machine_logical_cpus", "machine_ram_gb", "machine_os",
    "yazses_version", "faster_whisper_version", "ctranslate2_version",
    "compute_type", "device", "omp_num_threads", "load_average_1m",
    "corpus_name", "corpus_split", "corpus_n", "corpus_sha256_16", "corpus_stratified",
    "corpus_version", "corpus_description",
    "argv", "curation_note",
)
#: Provenance fields every archived result must carry (``tests/test_benchmark_results_are_archived``).
REQUIRED_PROVENANCE = ("timestamp", "cpu_model", "logical_cpus", "os", "yazses")
_CORPUS_KEYS = (
    "corpus_name", "corpus_split", "corpus_n", "corpus_sha256_16", "corpus_stratified",
    "corpus_version", "corpus_description",
)


def provenance_columns(doc: Mapping[str, Any], where: str) -> dict[str, Any]:
    """Validated machine / version / corpus / argv columns for one source document."""
    prov = get(doc, "provenance", where, required=True)
    prov = _obj(prov, f"{where}: provenance")
    for key in REQUIRED_PROVENANCE:
        if get(prov, key, f"{where}: provenance") in (None, ""):
            raise ExportError(f"{where}: provenance is missing required field {key!r}")
    cpu = prov["cpu_model"]
    n_cpu = prov["logical_cpus"]
    ram = prov.get("ram_gb")
    os_name = prov["os"]
    machine = " / ".join(
        [str(cpu), f"{fmt(n_cpu)} logical CPUs", f"{fmt(ram)} GB" if ram is not None else "", str(os_name)]
    )
    cols: dict[str, Any] = {
        "timestamp_utc": prov["timestamp"],
        "machine": machine,
        "machine_cpu_model": cpu,
        "machine_logical_cpus": n_cpu,
        "machine_ram_gb": ram,
        "machine_os": os_name,
        "yazses_version": prov["yazses"],
        "faster_whisper_version": prov.get("faster_whisper"),
        "ctranslate2_version": prov.get("ctranslate2"),
        "compute_type": prov.get("compute_type"),
        "device": prov.get("device"),
        "omp_num_threads": prov.get("omp_num_threads"),
        "load_average_1m": prov.get("load_average_1m"),
        "argv": prov.get("argv") or "",
    }
    cols.update(dict.fromkeys(_CORPUS_KEYS))
    corpus = prov.get("corpus")
    top = doc.get("corpus")
    if corpus is not None:
        corpus = _obj(corpus, f"{where}: provenance.corpus")
        for key in ("n", "sha256_16"):
            if corpus.get(key) in (None, ""):
                raise ExportError(f"{where}: provenance.corpus is missing required field {key!r}")
        cols.update(
            corpus_name=corpus.get("dataset"), corpus_split=corpus.get("split"),
            corpus_n=corpus["n"], corpus_sha256_16=corpus["sha256_16"],
            corpus_stratified=corpus.get("stratified"),
        )
    elif top is not None:  # the Persian manifest-mode layout
        top = _obj(top, f"{where}: corpus")
        for key in ("name", "split", "samples"):
            if top.get(key) in (None, ""):
                raise ExportError(f"{where}: corpus block is missing required field {key!r}")
        cols.update(
            corpus_name=top["name"], corpus_split=top["split"], corpus_n=top["samples"],
            corpus_version=top.get("version"),
        )
        sel = doc.get("selection")
        if isinstance(sel, dict):
            cols["corpus_description"] = sel.get("rule")
    return cols


# --------------------------------------------------------------------------------------
# Tables (specific columns; the common head/tail wrap every one of them)
# --------------------------------------------------------------------------------------

TABLES: dict[str, tuple[str, ...]] = {
    "asr_librispeech_wer": (
        "model_key", "model", "engine", "engine_class", "n_scored_utterances",
        "wer_pct", "wer_ci95_low_pct", "wer_ci95_high_pct", "mer_pct",
        "hits", "substitutions", "deletions", "insertions",
        "total_audio_seconds", "decode_seconds_total", "load_seconds",
        "rtf_mean", "rtf_median", "rtf_p95", "realtime_speedup_median",
        "normalizer", "failure",
    ),
    "beam_sweep": (
        "experiment", "model", "beam_size", "wer_pct", "wer_ci95_low_pct", "wer_ci95_high_pct",
        "substitutions", "deletions", "insertions", "total_audio_seconds",
        "decode_seconds", "rtf",
    ),
    "onset_first_word": (
        "model", "run", "arm", "cut_ms", "lead_ms", "wer_pct", "first_word_ok", "n_utterances",
        "empty_hyps", "decode_seconds", "trim_peak", "median_trimmed_ms", "max_trimmed_ms",
    ),
    "latency_decode": (
        "model", "cold_start_load_s", "decode_median_ms", "decode_p95_ms",
        "model_rss_delta_mb", "rss_after_load_mb", "rss_peak_mb", "baseline_rss_mb",
        "n_latency_utterances", "audio_duration_median_s", "audio_duration_p95_s",
        "non_decode_overhead_median_ms",
    ),
    "latency_pipeline_stages": ("stage", "mean_ms", "median_ms", "p95_ms", "pure_stage_reps"),
    "streaming_latency": (
        "model", "n_utterances", "chunk_ms", "partial_interval_ms", "feed",
        "utterances_with_no_partial_before_release",
        *(f"{m}_{s}" for m in (
            "batch_speech_end_to_text_s", "streaming_speech_end_to_final_s",
            "streaming_time_to_first_text_s", "streaming_visible_at_release_pct",
        ) for s in ("n", "mean", "median", "p95")),
    ),
    "vad_gate": (
        "vad_threshold", "n_speech_clips", "n_silence_clips", "negatives",
        "speech_detection_rate_pct", "silence_rejection_rate_pct", "balanced_accuracy_pct",
        "speech_rms_median", "speech_rms_p05", "speech_rms_to_threshold_margin_x",
    ),
    "command_grammar": (
        "n_command_phrases", "n_dictation_lines", "command_fixture", "dictation_fixture",
        "action_hits", "action_accuracy_pct", "classified_as_command_pct", "misfire_count",
        "false_positive_count", "false_positive_rate_pct",
        "runtime_n_calls", "per_call_median_ms", "per_call_p95_ms",
    ),
    "persian_asr": (
        "model_name", "model_engine", "model_compute_type", "model_revision",
        "decoder_beam_size", "decoder_condition_on_previous_text", "decoder_language",
        "wer_raw_pct", "wer_normalized_pct", "cer_raw_pct", "cer_normalized_pct",
        "exact_match_raw_fraction", "exact_match_normalized_fraction", "evaluation_normalizer",
        "rtf", "latency_p50_ms", "latency_p95_ms",
        "zwnj_reference_count", "zwnj_hypothesis_count", "zwnj_matched_count",
        "zwnj_precision", "zwnj_recall", "zwnj_f1", "arabic_yeh_count", "arabic_kaf_count",
        "model_load_s", "peak_rss_mb", "rss_before_load_mb", "rows_sha256",
        "yazses_commit_recorded",
    ),
    "diarization_recordings": (
        "recording_id", "duration_s", "true_speakers", "profile", "cluster_threshold",
        "max_speakers",
        "strict_der_pct", "strict_missed_pct", "strict_false_alarm_pct", "strict_confusion_pct",
        "strict_n_ref_speakers", "strict_n_hyp_speakers", "strict_speaker_count_error",
        "strict_scored_seconds", "strict_collar_s",
        "collar250ms_der_pct", "collar250ms_missed_pct", "collar250ms_false_alarm_pct",
        "collar250ms_confusion_pct", "collar250ms_n_ref_speakers", "collar250ms_n_hyp_speakers",
        "collar250ms_speaker_count_error", "collar250ms_scored_seconds", "collar250ms_collar_s",
    ),
    "diarization_corpus_summary": (
        "profile", "backend", "scoring", "frame_s", "cluster_threshold", "max_speakers",
        "n_meetings",
        "strict_der_mean_pct", "strict_der_time_weighted_pct",
        "collar250ms_der_mean_pct", "collar250ms_der_time_weighted_pct",
        "strict_missed_pct", "strict_false_alarm_pct", "strict_confusion_pct",
        "mean_speaker_count_error", "scored_seconds_total", "derived_after_run_fields",
    ),
    "significance_beam": (
        "experiment", "analysis_of", "baseline_beam", "comparison_a", "comparison_b",
        "a_wer_pct", "b_wer_pct", "diff_a_minus_b_pct", "diff_ci95_low_pct", "diff_ci95_high_pct",
        "p_value", "alpha", "method", "file_n_comparisons", "file_n_significant",
    ),
    "significance_onset": (
        "analysis_of", "comparison_a", "comparison_b", "a_first_word_ok", "b_first_word_ok",
        "discordant", "only_a", "only_b", "p_value", "alpha", "bonferroni_alpha",
        "file_n_comparisons", "file_n_significant",
    ),
    "significance_diarization": (
        "analysis_a_file", "analysis_b_file", "collar", "n_recordings",
        "b_better_on", "b_worse_on", "unchanged_on",
        "mean_delta_b_minus_a_pct", "mean_delta_ci95_low_pct", "mean_delta_ci95_high_pct",
        "time_weighted_delta_b_minus_a_pct", "time_weighted_delta_ci95_low_pct",
        "time_weighted_delta_ci95_high_pct", "delta_min_pct", "delta_max_pct",
        "sign_test_p", "verdict", "seed", "n_bootstrap", "per_meeting_delta_json",
    ),
}

#: Which tables carry which record kind -- enforced, so a significance row cannot land in a
#: measurement table (or the reverse).
TABLE_KIND: dict[str, str] = {
    **dict.fromkeys(TABLES, "measurement"),
    "significance_beam": "significance_analysis",
    "significance_onset": "significance_analysis",
    "significance_diarization": "significance_analysis",
}

Row = dict[str, Any]
Parsed = list[Row]


def _prefixed(src: Mapping[str, Any], prefix: str, fields: Sequence[tuple[str, str]],
              where: str) -> Row:
    return {f"{prefix}_{out}": get(src, key, where) for key, out in fields}


# --- parsers: (document, source, where) -> rows ---------------------------------------


def parse_wer(doc: Row, src: Source, where: str) -> Parsed:
    cfg = _obj(get(doc, "config", where, required=True), f"{where}: config")
    models = _obj(get(doc, "models", where, required=True), f"{where}: models")
    failed = doc.get("failed") or {}
    failed = _obj(failed, f"{where}: failed")
    common = {
        "corpus_name": cfg.get("dataset"),
        "corpus_n": cfg.get("n_utterances"),
        "corpus_description": cfg.get("selection"),
        "total_audio_seconds": cfg.get("total_audio_seconds"),
        "normalizer": cfg.get("normalizer"),
    }
    rows: Parsed = []
    for key in sorted(set(models) | set(failed)):
        ptr = f"{where}: models.{key}"
        if key in failed:
            rows.append({**common, "source_pointer": f"failed.{key}", "model_key": key,
                         "failure": failed[key] if isinstance(failed[key], str) else fmt(failed[key])})
            continue
        m = _obj(models[key], ptr)
        get(m, "wer", ptr, required=True, numeric=True)
        lo, hi = interval(m, "wer_ci95", ptr)
        rows.append({
            **common, "source_pointer": f"models.{key}", "model_key": key,
            "model": m.get("model"), "engine": m.get("engine"),
            "engine_class": m.get("engine_class"),
            "n_scored_utterances": m.get("n_scored_utterances"),
            "wer_pct": m["wer"], "wer_ci95_low_pct": lo, "wer_ci95_high_pct": hi,
            "mer_pct": m.get("mer"), "hits": m.get("hits"),
            "substitutions": m.get("substitutions"), "deletions": m.get("deletions"),
            "insertions": m.get("insertions"),
            "decode_seconds_total": m.get("decode_seconds_total"),
            "load_seconds": m.get("load_seconds"),
            "rtf_mean": m.get("rtf_mean"), "rtf_median": m.get("rtf_median"),
            "rtf_p95": m.get("rtf_p95"),
            "realtime_speedup_median": m.get("realtime_speedup_median"),
        })
    return rows


def parse_beam(doc: Row, src: Source, where: str) -> Parsed:
    cfg = _obj(get(doc, "config", where, required=True), f"{where}: config")
    rows_in = _list(get(doc, "rows", where, required=True), f"{where}: rows")
    if "comparisons" in doc:
        raise ExportError(f"{where}: carries 'comparisons' -- that is an analysis, not a measurement")
    out: Parsed = []
    for i, r in enumerate(rows_in):
        ptr = f"{where}: rows[{i}]"
        r = _obj(r, ptr)
        for key in ("model", "beam_size", "wer_pct"):
            get(r, key, ptr, required=True)
        lo, hi = interval(r, "wer_ci95", ptr)
        out.append({
            "source_pointer": f"rows[{i}]", "experiment": src.experiment,
            "model": r["model"], "beam_size": r["beam_size"],
            "corpus_split": r.get("split") or cfg.get("split"),
            "corpus_n": cfg.get("n_utterances"),
            "total_audio_seconds": cfg.get("total_audio_seconds"),
            "wer_pct": r["wer_pct"], "wer_ci95_low_pct": lo, "wer_ci95_high_pct": hi,
            "substitutions": r.get("substitutions"), "deletions": r.get("deletions"),
            "insertions": r.get("insertions"), "decode_seconds": r.get("decode_seconds"),
            "rtf": r.get("rtf"),
        })
    return out


def parse_onset(doc: Row, src: Source, where: str) -> Parsed:
    cfg = _obj(get(doc, "config", where, required=True), f"{where}: config")
    rows_in = _list(get(doc, "rows", where, required=True), f"{where}: rows")
    out: Parsed = []
    for i, r in enumerate(rows_in):
        ptr = f"{where}: rows[{i}]"
        r = _obj(r, ptr)
        for key in ("arm", "lead_ms", "wer_pct"):
            get(r, key, ptr, required=True)
        out.append({
            "source_pointer": f"rows[{i}]", "model": cfg.get("model"),
            "run": r.get("run"), "arm": r["arm"], "cut_ms": r.get("cut_ms"),
            "lead_ms": r["lead_ms"], "wer_pct": r["wer_pct"],
            "first_word_ok": r.get("first_word_ok"), "n_utterances": r.get("n"),
            "empty_hyps": r.get("empty_hyps"), "decode_seconds": r.get("decode_seconds"),
            "trim_peak": cfg.get("trim_peak"),
            "median_trimmed_ms": cfg.get("median_trimmed_ms"),
            "max_trimmed_ms": cfg.get("max_trimmed_ms"),
            "corpus_n": cfg.get("n"),
        })
    return out


def parse_latency_decode(doc: Row, src: Source, where: str) -> Parsed:
    cfg = _obj(get(doc, "config", where, required=True), f"{where}: config")
    models = _obj(get(doc, "models", where, required=True), f"{where}: models")
    memory = doc.get("memory") or {}
    out: Parsed = []
    for key in sorted(models):
        ptr = f"{where}: models.{key}"
        m = _obj(models[key], ptr)
        get(m, "decode_median_ms", ptr, required=True, numeric=True)
        out.append({
            "source_pointer": f"models.{key}", "model": key,
            "cold_start_load_s": m.get("cold_start_load_s"),
            "decode_median_ms": m["decode_median_ms"], "decode_p95_ms": m.get("decode_p95_ms"),
            "model_rss_delta_mb": m.get("model_rss_delta_mb"),
            "rss_after_load_mb": m.get("rss_after_load_mb"),
            "rss_peak_mb": m.get("rss_peak_mb"),
            "baseline_rss_mb": memory.get("baseline_rss_mb"),
            "n_latency_utterances": cfg.get("n_latency_utterances"),
            "audio_duration_median_s": cfg.get("audio_duration_median_s"),
            "audio_duration_p95_s": cfg.get("audio_duration_p95_s"),
            "non_decode_overhead_median_ms": doc.get("non_decode_overhead_median_ms"),
            "corpus_n": cfg.get("n_latency_utterances"),
        })
    return out


def parse_latency_stages(doc: Row, src: Source, where: str) -> Parsed:
    cfg = _obj(get(doc, "config", where, required=True), f"{where}: config")
    stages = _obj(get(doc, "pipeline_stages", where, required=True), f"{where}: pipeline_stages")
    out: Parsed = []
    for key in sorted(stages):
        ptr = f"{where}: pipeline_stages.{key}"
        s = _obj(stages[key], ptr)
        get(s, "median_ms", ptr, required=True, numeric=True)
        out.append({
            "source_pointer": f"pipeline_stages.{key}", "stage": key,
            "mean_ms": s.get("mean_ms"), "median_ms": s["median_ms"], "p95_ms": s.get("p95_ms"),
            "pure_stage_reps": cfg.get("pure_stage_reps"),
        })
    return out


_STREAM_METRICS = (
    "batch_speech_end_to_text_s", "streaming_speech_end_to_final_s",
    "streaming_time_to_first_text_s", "streaming_visible_at_release_pct",
)


def parse_streaming(doc: Row, src: Source, where: str) -> Parsed:
    cfg = _obj(get(doc, "config", where, required=True), f"{where}: config")
    models = _obj(get(doc, "models", where, required=True), f"{where}: models")
    out: Parsed = []
    for key in sorted(models):
        ptr = f"{where}: models.{key}"
        m = _obj(models[key], ptr)
        row: Row = {
            "source_pointer": f"models.{key}", "model": key,
            "n_utterances": cfg.get("n_utterances"), "chunk_ms": cfg.get("chunk_ms"),
            "partial_interval_ms": cfg.get("partial_interval_ms"), "feed": cfg.get("feed"),
            "utterances_with_no_partial_before_release":
                m.get("utterances_with_no_partial_before_release"),
            "corpus_n": cfg.get("n_utterances"),
        }
        for metric in _STREAM_METRICS:
            stats = m.get(metric)
            if stats is None:
                continue
            stats = _obj(stats, f"{ptr}.{metric}")
            for s in ("n", "mean", "median", "p95"):
                row[f"{metric}_{s}"] = stats.get(s)
        out.append(row)
    return out


def parse_vad(doc: Row, src: Source, where: str) -> Parsed:
    cfg = _obj(get(doc, "config", where, required=True), f"{where}: config")
    res = _obj(get(doc, "results", where, required=True), f"{where}: results")
    get(res, "balanced_accuracy_pct", where + ": results", required=True, numeric=True)
    return [{
        "source_pointer": "results", "vad_threshold": cfg.get("vad_threshold"),
        "n_speech_clips": cfg.get("n_speech_clips"), "n_silence_clips": cfg.get("n_silence_clips"),
        "negatives": cfg.get("negatives"),
        "speech_detection_rate_pct": res.get("speech_detection_rate_pct"),
        "silence_rejection_rate_pct": res.get("silence_rejection_rate_pct"),
        "balanced_accuracy_pct": res["balanced_accuracy_pct"],
        "speech_rms_median": res.get("speech_rms_median"),
        "speech_rms_p05": res.get("speech_rms_p05"),
        "speech_rms_to_threshold_margin_x": res.get("speech_rms_to_threshold_margin_x"),
        "corpus_name": cfg.get("dataset_positives"), "corpus_n": cfg.get("n_speech_clips"),
    }]


def parse_commands(doc: Row, src: Source, where: str) -> Parsed:
    cfg = _obj(get(doc, "config", where, required=True), f"{where}: config")
    prec = _obj(get(doc, "precision", where, required=True), f"{where}: precision")
    fpos = _obj(get(doc, "false_positive", where, required=True), f"{where}: false_positive")
    run = _obj(doc.get("runtime") or {}, f"{where}: runtime")
    get(prec, "action_accuracy_pct", f"{where}: precision", required=True, numeric=True)
    misfires = prec.get("misfires")
    fps = fpos.get("false_positives")
    return [{
        "source_pointer": "$", "n_command_phrases": cfg.get("n_command_phrases"),
        "n_dictation_lines": cfg.get("n_dictation_lines"),
        "command_fixture": cfg.get("command_fixture"),
        "dictation_fixture": cfg.get("dictation_fixture"),
        "action_hits": prec.get("action_hits"), "action_accuracy_pct": prec["action_accuracy_pct"],
        "classified_as_command_pct": prec.get("classified_as_command_pct"),
        "misfire_count": len(misfires) if isinstance(misfires, list) else None,
        "false_positive_count": len(fps) if isinstance(fps, list) else None,
        "false_positive_rate_pct": fpos.get("false_positive_rate_pct"),
        "runtime_n_calls": run.get("n_calls"), "per_call_median_ms": run.get("per_call_median_ms"),
        "per_call_p95_ms": run.get("per_call_p95_ms"),
    }]


def parse_persian(doc: Row, src: Source, where: str) -> Parsed:
    metrics = _obj(get(doc, "metrics", where, required=True), f"{where}: metrics")
    model = _obj(get(doc, "model", where, required=True), f"{where}: model")
    dec = _obj(doc.get("decoder") or {}, f"{where}: decoder")
    run = _obj(doc.get("runtime") or {}, f"{where}: runtime")
    sel = _obj(doc.get("selection") or {}, f"{where}: selection")
    qual = _obj(metrics.get("persian_quality") or {}, f"{where}: metrics.persian_quality")
    zw = _obj(qual.get("zwnj") or {}, f"{where}: metrics.persian_quality.zwnj")
    for key in ("wer_raw", "wer_normalized", "cer_normalized"):
        get(metrics, key, f"{where}: metrics", required=True, numeric=True)
    get(model, "name", f"{where}: model", required=True)
    return [{
        "source_pointer": "$",
        "model_name": model["name"], "model_engine": model.get("engine"),
        "model_compute_type": model.get("compute_type"), "model_revision": model.get("revision"),
        "decoder_beam_size": dec.get("beam_size"),
        "decoder_condition_on_previous_text": dec.get("condition_on_previous_text"),
        "decoder_language": dec.get("language"),
        "wer_raw_pct": metrics.get("wer_raw"), "wer_normalized_pct": metrics["wer_normalized"],
        "cer_raw_pct": metrics.get("cer_raw"), "cer_normalized_pct": metrics["cer_normalized"],
        "exact_match_raw_fraction": metrics.get("exact_match_raw"),
        "exact_match_normalized_fraction": metrics.get("exact_match_normalized"),
        "evaluation_normalizer": metrics.get("evaluation_normalizer"),
        "rtf": metrics.get("rtf"), "latency_p50_ms": metrics.get("latency_p50_ms"),
        "latency_p95_ms": metrics.get("latency_p95_ms"),
        "zwnj_reference_count": zw.get("reference_count"),
        "zwnj_hypothesis_count": zw.get("hypothesis_count"),
        "zwnj_matched_count": zw.get("matched_count"),
        "zwnj_precision": zw.get("precision"), "zwnj_recall": zw.get("recall"),
        "zwnj_f1": zw.get("f1"),
        "arabic_yeh_count": qual.get("arabic_yeh_count"),
        "arabic_kaf_count": qual.get("arabic_kaf_count"),
        "model_load_s": run.get("model_load_s"), "peak_rss_mb": run.get("peak_rss_mb"),
        "rss_before_load_mb": run.get("rss_before_load_mb"),
        "rows_sha256": sel.get("rows_sha256"),
        "yazses_commit_recorded": doc.get("yazses_commit"),
    }]


_DER_FIELDS = (
    ("der", "der_pct"), ("missed_pct", "missed_pct"), ("false_alarm_pct", "false_alarm_pct"),
    ("confusion_pct", "confusion_pct"), ("n_ref_speakers", "n_ref_speakers"),
    ("n_hyp_speakers", "n_hyp_speakers"), ("speaker_count_error", "speaker_count_error"),
    ("scored_seconds", "scored_seconds"), ("collar_s", "collar_s"),
)


def _diar_corpus(cfg: Mapping[str, Any]) -> Row:
    return {
        "corpus_name": cfg.get("corpus"), "corpus_n": cfg.get("n_meetings"),
        "corpus_description": cfg.get("corpus_kind"),
    }


def parse_diar_recordings(doc: Row, src: Source, where: str) -> Parsed:
    cfg = _obj(get(doc, "config", where, required=True), f"{where}: config")
    meetings = _list(get(doc, "meetings", where, required=True), f"{where}: meetings")
    out: Parsed = []
    for i, m in enumerate(meetings):
        ptr = f"{where}: meetings[{i}]"
        m = _obj(m, ptr)
        get(m, "id", ptr, required=True)
        strict = _obj(get(m, "strict", ptr, required=True), f"{ptr}.strict")
        get(strict, "der", f"{ptr}.strict", required=True, numeric=True)
        collar = _obj(m.get("collar250ms") or {}, f"{ptr}.collar250ms")
        row: Row = {
            "source_pointer": f"meetings[{i}]", "recording_id": m["id"],
            "duration_s": m.get("duration_s"), "true_speakers": m.get("true_speakers"),
            "profile": cfg.get("profile"), "cluster_threshold": cfg.get("cluster_threshold"),
            "max_speakers": cfg.get("max_speakers"), **_diar_corpus(cfg),
        }
        row.update(_prefixed(strict, "strict", _DER_FIELDS, f"{ptr}.strict"))
        row.update(_prefixed(collar, "collar250ms", _DER_FIELDS, f"{ptr}.collar250ms"))
        out.append(row)
    return out


_POST_HOC = ("der_strict_time_weighted", "der_collar250ms_time_weighted", "scored_seconds_total")


def parse_diar_summary(doc: Row, src: Source, where: str) -> Parsed:
    cfg = _obj(get(doc, "config", where, required=True), f"{where}: config")
    summ = _obj(get(doc, "summary", where, required=True), f"{where}: summary")
    get(summ, "der_strict", f"{where}: summary", required=True, numeric=True)
    note = doc.get("derived_after_the_run") or doc.get("summary_rederived")
    derived = ""
    if note is not None:
        if not isinstance(note, str) or not all(name in note for name in _POST_HOC):
            raise ExportError(
                f"{where}: the post-hoc derivation note no longer names the fields "
                f"{_POST_HOC}; review how derived_after_run_fields is exported"
            )
        derived = ";".join(_POST_HOC)
    return [{
        "source_pointer": "summary", "profile": cfg.get("profile"), "backend": cfg.get("backend"),
        "scoring": cfg.get("scoring"), "frame_s": cfg.get("frame_s"),
        "cluster_threshold": cfg.get("cluster_threshold"), "max_speakers": cfg.get("max_speakers"),
        "n_meetings": cfg.get("n_meetings"),
        "strict_der_mean_pct": summ["der_strict"],
        "strict_der_time_weighted_pct": summ.get("der_strict_time_weighted"),
        "collar250ms_der_mean_pct": summ.get("der_collar250ms"),
        "collar250ms_der_time_weighted_pct": summ.get("der_collar250ms_time_weighted"),
        "strict_missed_pct": summ.get("missed_pct"),
        "strict_false_alarm_pct": summ.get("false_alarm_pct"),
        "strict_confusion_pct": summ.get("confusion_pct"),
        "mean_speaker_count_error": summ.get("mean_speaker_count_error"),
        "scored_seconds_total": summ.get("scored_seconds_total"),
        "derived_after_run_fields": derived, **_diar_corpus(cfg),
    }]


def parse_beam_significance(doc: Row, src: Source, where: str) -> Parsed:
    comps = _list(get(doc, "comparisons", where, required=True), f"{where}: comparisons")
    if "rows" in doc:
        raise ExportError(f"{where}: carries 'rows' -- that is a measurement, not an analysis")
    source = get(doc, "source", where, required=True)
    out: Parsed = []
    for i, c in enumerate(comps):
        ptr = f"{where}: comparisons[{i}]"
        c = _obj(c, ptr)
        for key in ("a", "b", "p"):
            get(c, key, ptr, required=True)
        lo, hi = interval(c, "diff_ci95", ptr)
        out.append({
            "source_pointer": f"comparisons[{i}]", "experiment": src.experiment,
            "analysis_of": source, "baseline_beam": doc.get("baseline_beam"),
            "comparison_a": c["a"], "comparison_b": c["b"],
            "a_wer_pct": c.get("a_wer"), "b_wer_pct": c.get("b_wer"),
            "diff_a_minus_b_pct": c.get("diff"), "diff_ci95_low_pct": lo, "diff_ci95_high_pct": hi,
            "p_value": c["p"], "alpha": doc.get("alpha"), "method": doc.get("method"),
            "file_n_comparisons": doc.get("n_comparisons"),
            "file_n_significant": doc.get("n_significant"),
            "corpus_split": c.get("split"), "corpus_n": c.get("n_utterances"),
        })
    return out


def parse_onset_significance(doc: Row, src: Source, where: str) -> Parsed:
    comps = _list(get(doc, "comparisons", where, required=True), f"{where}: comparisons")
    source = get(doc, "source", where, required=True)
    out: Parsed = []
    for i, c in enumerate(comps):
        ptr = f"{where}: comparisons[{i}]"
        c = _obj(c, ptr)
        for key in ("a", "b", "p"):
            get(c, key, ptr, required=True)
        out.append({
            "source_pointer": f"comparisons[{i}]", "analysis_of": source,
            "comparison_a": c["a"], "comparison_b": c["b"],
            "a_first_word_ok": c.get("a_ok"), "b_first_word_ok": c.get("b_ok"),
            "discordant": c.get("discordant"), "only_a": c.get("only_a"),
            "only_b": c.get("only_b"), "p_value": c["p"], "alpha": doc.get("alpha"),
            "bonferroni_alpha": doc.get("bonferroni_alpha"),
            "file_n_comparisons": doc.get("n_comparisons"),
            "file_n_significant": doc.get("n_significant"), "corpus_n": c.get("n"),
        })
    return out


def parse_diar_significance(doc: Row, src: Source, where: str) -> Parsed:
    result = _obj(get(doc, "result", where, required=True), f"{where}: result")
    out: Parsed = []
    for key in sorted(result):
        ptr = f"{where}: result.{key}"
        r = _obj(result[key], ptr)
        a = _obj(get(r, "a", ptr, required=True), f"{ptr}.a")
        b = _obj(get(r, "b", ptr, required=True), f"{ptr}.b")
        get(r, "sign_test_p", ptr, required=True, numeric=True)
        mlo, mhi = interval(r, "mean_delta_ci95", ptr)
        tlo, thi = interval(r, "time_weighted_delta_ci95", ptr)
        out.append({
            "source_pointer": f"result.{key}", "analysis_a_file": a.get("path"),
            "analysis_b_file": b.get("path"), "collar": r.get("collar") or key,
            "n_recordings": r.get("n_recordings"), "b_better_on": r.get("b_better_on"),
            "b_worse_on": r.get("b_worse_on"), "unchanged_on": r.get("unchanged_on"),
            "mean_delta_b_minus_a_pct": r.get("mean_delta"),
            "mean_delta_ci95_low_pct": mlo, "mean_delta_ci95_high_pct": mhi,
            "time_weighted_delta_b_minus_a_pct": r.get("time_weighted_delta"),
            "time_weighted_delta_ci95_low_pct": tlo, "time_weighted_delta_ci95_high_pct": thi,
            "delta_min_pct": r.get("delta_min"), "delta_max_pct": r.get("delta_max"),
            "sign_test_p": r["sign_test_p"], "verdict": r.get("verdict"), "seed": r.get("seed"),
            "n_bootstrap": r.get("n_bootstrap"), "per_meeting_delta_json": r.get("per_meeting_delta"),
            "corpus_n": r.get("n_recordings"),
        })
    return out


PARSERS: dict[str, Callable[[Row, Source, str], Parsed]] = {
    "wer": parse_wer, "beam": parse_beam, "onset": parse_onset,
    "latency_decode": parse_latency_decode, "latency_stages": parse_latency_stages,
    "streaming": parse_streaming, "vad": parse_vad, "commands": parse_commands,
    "persian": parse_persian, "diar_recordings": parse_diar_recordings,
    "diar_summary": parse_diar_summary, "beam_significance": parse_beam_significance,
    "onset_significance": parse_onset_significance, "diar_significance": parse_diar_significance,
}


# --------------------------------------------------------------------------------------
# Git provenance
# --------------------------------------------------------------------------------------


class GitInfo:
    """Source commits via ``git log -1 -- <file>``; empty when not derivable.

    Not derivable means: not a git checkout, a shallow clone (the answer would be the
    shallow boundary, not the real last-touching commit), or a source file that is
    untracked or modified in the working tree (its content is not what that commit holds).
    In those cases *fallback* -- the values recorded in the committed metadata -- is used,
    so ``--check`` does not report drift merely because CI cloned shallowly.
    """

    def __init__(self, root: Path, fallback: Mapping[str, str] | None = None,
                 fallback_revision: str = "") -> None:
        self.root = root
        self.fallback = dict(fallback or {})
        self.fallback_revision = fallback_revision
        self.available = self._probe()
        self._memo: dict[str, str] = {}

    def _git(self, *args: str) -> str | None:
        try:
            done = subprocess.run(
                ["git", "-C", str(self.root), *args], capture_output=True, text=True,
                check=False, timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return done.stdout.strip() if done.returncode == 0 else None

    def _probe(self) -> bool:
        if self._git("rev-parse", "--is-inside-work-tree") != "true":
            return False
        return self._git("rev-parse", "--is-shallow-repository") == "false"

    def commit(self, rel: str) -> str:
        if rel not in self._memo:
            if not self.available:
                self._memo[rel] = self.fallback.get(rel, "")
            elif self._git("status", "--porcelain", "--", rel):
                self._memo[rel] = ""
            else:
                self._memo[rel] = self._git("log", "-1", "--format=%H", "--", rel) or ""
        return self._memo[rel]

    def revision(self, rels: Sequence[str]) -> str:
        if not self.available:
            return self.fallback_revision
        if any(self._git("status", "--porcelain", "--", r) for r in rels):
            return ""
        return self._git("log", "-1", "--format=%H", "--", *rels) or ""


def load_recorded(out_dir: Path) -> tuple[dict[str, str], str]:
    """Commits recorded in a previously committed metadata file (for the shallow fallback)."""
    path = out_dir / METADATA_NAME
    if not path.is_file():
        return {}, ""
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
        commits = {s["path"]: s.get("git_commit", "") for s in meta.get("sources", [])}
        return commits, meta.get("source_revision", "")
    except (ValueError, KeyError, TypeError):
        return {}, ""


# --------------------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------------------


@dataclass
class Export:
    """The complete, in-memory result of one export run (name -> bytes)."""

    files: dict[str, bytes]
    metadata: dict[str, Any]


def render_csv(columns: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> bytes:
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([fmt(row.get(c)) for c in columns])
    return buf.getvalue().encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def list_archive(results_dir: Path) -> list[str]:
    """Every file under *results_dir*, posix-relative and sorted (nothing is globbed by name)."""
    if not results_dir.is_dir():
        raise ExportError(f"{results_dir}: results directory not found")
    return sorted(p.relative_to(results_dir).as_posix() for p in results_dir.rglob("*") if p.is_file())


def _safe_source_path(results_dir: Path, rel: str) -> Path:
    path = (results_dir / rel).resolve()
    try:
        path.relative_to(results_dir.resolve())
    except ValueError as exc:
        raise ExportError(f"{rel}: allowlisted path escapes {RESULTS_REL}") from exc
    return path


def build_export(
    root: Path = REPO_ROOT,
    sources: Sequence[Source] = ALLOWLIST,
    git: Any | None = None,
) -> Export:
    """Read every allowlisted source, validate, scan, and render all outputs in memory."""
    results_dir = root / RESULTS_REL
    out_dir = root / OUT_REL
    archive = list_archive(results_dir)
    if git is None:
        commits, revision = load_recorded(out_dir)
        git = GitInfo(root, commits, revision)

    for table in {s.table for s in sources}:
        if table not in TABLES:
            raise ExportError(f"allowlist names unknown table {table!r}")
    for s in sources:
        if s.parser not in PARSERS:
            raise ExportError(f"{s.path}: unknown parser {s.parser!r}")
        if s.kind != TABLE_KIND[s.table]:
            raise ExportError(
                f"{s.path}: record kind {s.kind!r} cannot go in table {s.table!r} "
                f"(which holds {TABLE_KIND[s.table]!r} records)"
            )
        if s.path not in archive:
            raise ExportError(f"{s.path}: allowlisted but not present under {RESULTS_REL}/")

    ordered = sorted(sources, key=lambda s: (s.table, s.path, s.parser))
    table_rows: dict[str, list[Row]] = {t: [] for t in TABLES}
    included: dict[str, dict[str, Any]] = {}
    docs: dict[str, tuple[Any, str]] = {}
    for src in ordered:
        if src.path not in docs:
            raw = _safe_source_path(results_dir, src.path).read_bytes()
            doc = parse_json_text(raw.decode("utf-8"), src.path)
            _obj(doc, src.path, "top-level object")
            scan_document(doc, src.path)
            docs[src.path] = (doc, sha256_bytes(raw))
        doc, sha = docs[src.path]
        where = src.path
        rows = PARSERS[src.parser](doc, src, where)
        if not rows:
            raise ExportError(f"{where}: parser {src.parser!r} produced no rows")
        prov = provenance_columns(doc, where)
        allowed = set(TABLES[src.table]) | set(COMMON_TAIL) | {"source_pointer"}
        for row in rows:
            unknown = set(row) - allowed
            if unknown:
                raise ExportError(f"{where}: parser emitted unknown column(s) {sorted(unknown)}")
            merged: Row = dict(prov)
            # The provenance block is authoritative where it states a value (an explicit
            # ``provenance.corpus`` beats a config-derived hint); the parser fills the gaps.
            # A parser's ``None`` never blanks anything.
            for k, v in row.items():
                if v is not None and merged.get(k) in (None, ""):
                    merged[k] = v
            merged.update(
                record_kind=src.kind, source_file=f"{RESULTS_REL}/{src.path}",
                source_sha256=sha, source_git_commit=git.commit(f"{RESULTS_REL}/{src.path}"),
                curation_note=src.note,
            )
            table_rows[src.table].append(merged)
        entry = included.setdefault(src.path, {
            "path": f"{RESULTS_REL}/{src.path}",
            "sha256": sha, "git_commit": git.commit(f"{RESULTS_REL}/{src.path}"),
            "record_kind": src.kind, "tables": {},
        })
        entry["tables"][src.table] = entry["tables"].get(src.table, 0) + len(rows)

    files: dict[str, bytes] = {}
    table_meta: dict[str, Any] = {}
    for table in sorted(TABLES):
        columns = (*COMMON_HEAD, *TABLES[table], *COMMON_TAIL)
        if len(set(columns)) != len(columns):
            raise ExportError(f"table {table!r} declares a duplicate column")
        rows = table_rows[table]
        if not rows:
            continue
        data = render_csv(columns, rows)
        text = data.decode("utf-8")
        # Final guard: nothing sensitive may appear in any rendered cell.
        hits = scan_text(text)
        if hits:
            raise ExportError(f"{table}.csv: sensitive content in output ({', '.join(hits)})")
        files[f"{table}.csv"] = data
        table_meta[table] = {
            "file": f"{table}.csv", "rows": len(rows), "columns": list(columns),
            "record_kind": TABLE_KIND[table],
            "sources": sorted({r["source_file"] for r in rows}),
            "sha256": sha256_bytes(data),
        }

    included_paths = sorted(included)
    excluded = []
    for rel in archive:
        if rel in included:
            continue
        raw = (results_dir / rel).read_bytes()
        excluded.append({"path": f"{RESULTS_REL}/{rel}", "sha256": sha256_bytes(raw), "reason": exclusion_reason(rel)})

    metadata = {
        "schema_version": SCHEMA_VERSION,
        "generator": GENERATOR,
        "source_repository": SOURCE_REPOSITORY,
        "source_revision": git.revision([f"{RESULTS_REL}/{p}" for p in included_paths]),
        "record_kinds": list(RECORD_KINDS),
        "tables": table_meta,
        "sources": [included[p] for p in included_paths],
        "excluded": excluded,
        "fields_not_exported": FIELDS_NOT_EXPORTED,
        "sensitivity_scan": {
            "rules": sorted({name for name, _ in SENSITIVE_RULES}), "findings": 0,
        },
        "row_counts": {t: m["rows"] for t, m in table_meta.items()},
    }
    meta_bytes = (json.dumps(metadata, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    files[METADATA_NAME] = meta_bytes
    sums = "".join(f"{sha256_bytes(files[n])}  {n}\n" for n in sorted(files))
    files[SUMS_NAME] = sums.encode("utf-8")
    return Export(files=files, metadata=metadata)


# --------------------------------------------------------------------------------------
# Writing and checking
# --------------------------------------------------------------------------------------


def _fenced_out_dir(root: Path, out_dir: Path) -> Path:
    expected = (root / OUT_REL).resolve()
    actual = out_dir.resolve()
    if actual != expected:
        raise ExportError(
            f"refusing to write to {out_dir}: the only permitted target is {OUT_REL}/ "
            f"(and never anything under {RESULTS_REL}/)"
        )
    results = (root / RESULTS_REL).resolve()
    if actual == results or results in actual.parents:
        raise ExportError(f"refusing to write inside {RESULTS_REL}/")
    return actual


def write_export(export: Export, root: Path = REPO_ROOT, out_dir: Path | None = None) -> list[str]:
    """Write *export* into ``huggingface/benchmarks/data``; return the names written."""
    target = _fenced_out_dir(root, out_dir if out_dir is not None else root / OUT_REL)
    target.mkdir(parents=True, exist_ok=True)
    owned = set(export.files)
    for stale in sorted(target.iterdir()):
        if stale.is_file() and stale.name not in owned and (
            stale.suffix == ".csv" or stale.name in (METADATA_NAME, SUMS_NAME)
        ):
            stale.unlink()
    for name, data in sorted(export.files.items()):
        (target / name).write_bytes(data)
    return sorted(export.files)


def diff_export(export: Export, root: Path = REPO_ROOT) -> list[str]:
    """Differences between *export* and what is committed; empty means in sync.  Reads only."""
    target = root / OUT_REL
    problems: list[str] = []
    for name, data in sorted(export.files.items()):
        path = target / name
        if not path.is_file():
            problems.append(f"missing: {OUT_REL}/{name}")
        elif path.read_bytes() != data:
            problems.append(f"changed: {OUT_REL}/{name}")
    if target.is_dir():
        for path in sorted(target.iterdir()):
            if path.is_file() and path.name not in export.files:
                problems.append(f"unexpected: {OUT_REL}/{path.name}")
    return problems


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


def format_listing(root: Path, sources: Sequence[Source] = ALLOWLIST) -> str:
    archive = list_archive(root / RESULTS_REL)
    lines = ["INCLUDED (allowlist):"]
    for s in sorted(sources, key=lambda s: (s.table, s.path)):
        lines.append(f"  {s.table:28s} {s.kind:22s} {s.path}")
    included = {s.path for s in sources}
    lines.append("")
    lines.append("EXCLUDED (reason):")
    for rel in archive:
        if rel not in included:
            lines.append(f"  {rel}\n      {exclusion_reason(rel)}")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None, *, root: Path | None = None,
         out=None, err=None) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    parser = argparse.ArgumentParser(
        description="Export paper/results/ to a curated Hugging Face evaluation dataset "
        f"under {OUT_REL}/ (tables only: no audio, no transcripts, no corpora).",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true",
                      help="regenerate in memory and compare with the committed output; "
                      "exit 1 on drift; never writes")
    mode.add_argument("--write", action="store_true", help=f"write {OUT_REL}/")
    mode.add_argument("--list", action="store_true",
                      help="list allowlisted sources and every excluded file with its reason")
    parser.add_argument("--root", type=Path, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    base = (args.root or root or REPO_ROOT).resolve()
    try:
        if args.list:
            out.write(format_listing(base))
            return 0
        export = build_export(base)
        if args.check:
            problems = diff_export(export, base)
            if problems:
                err.write("drift between paper/results and the committed Hugging Face export:\n")
                for p in problems:
                    err.write(f"  {p}\n")
                err.write("run: uv run python scripts/export_hf_benchmarks.py --write\n")
                return 1
            out.write(f"in sync: {len(export.files)} files, "
                      f"{sum(export.metadata['row_counts'].values())} rows\n")
            return 0
        written = write_export(export, base)
        out.write(f"wrote {len(written)} files to {OUT_REL}/ "
                  f"({sum(export.metadata['row_counts'].values())} rows)\n")
        return 0
    except ExportError as exc:
        err.write(f"error: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
