"""FA-04 slice 1: the Persian harness scores honestly and emits schema-valid JSON.

`design/specs/persian-benchmark-and-validation.md` demands "one command emits
schema-valid result JSON" and "raw and normalized metrics both reported". A harness
that can emit a schema-invalid document, or one whose smoke path needs audio or a
model, cannot satisfy either acceptance line on CI — so both are pinned here, with
the normalizer's contract checked against the exact traps it exists to handle.

The normalizer is also checked for the property that makes the whole design work:
it does NOT import the production `postprocess.persian_text`. §6 requires the
evaluation normalizer to be separately versioned, because production bug fixes
must never silently move historical benchmark numbers.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.benchmark_deps import load

BENCH = Path(__file__).resolve().parents[1] / "paper" / "benchmark"


@pytest.fixture(scope="module")
def persian_metrics():
    return load("persian_metrics", "persian_metrics.py")


@pytest.fixture(scope="module")
def bench_persian():
    return load("bench_persian", "bench_persian.py")


# ── the evaluation normalizer (fa-eval-v1) ────────────────────────────────────


def test_normalizer_canonicalizes_arabic_yeh_and_kaf(persian_metrics):
    n = persian_metrics.normalize_fa_eval_v1
    assert n("\u064a\u0643") == "\u06cc\u06a9"


def test_normalizer_is_idempotent(persian_metrics):
    n = persian_metrics.normalize_fa_eval_v1
    once = n("\u0645\u06cc\u200c\u062e\u0648\u0627\u0647\u0645  \u0622\u0645\u062f\u0647\u064a")
    assert n(once) == once


def test_normalizer_preserves_zwnj(persian_metrics):
    n = persian_metrics.normalize_fa_eval_v1
    # The ZWNJ in می‌خواهم is meaningful; whitespace collapsing must not eat it.
    assert persian_metrics.ZWNJ in n("\u0645\u06cc\u200c\u062e\u0648\u0627\u0647\u0645")


def test_normalizer_collapses_whitespace_runs(persian_metrics):
    n = persian_metrics.normalize_fa_eval_v1
    assert n("a \t b\nc ") == "a b c"


def test_normalizer_leaves_digits_and_punctuation_alone(persian_metrics):
    n = persian_metrics.normalize_fa_eval_v1
    text = "۱۲۳ \u066a"
    assert n(text) == text


def test_evaluation_normalizer_does_not_import_production_normalization(
    persian_metrics,
):
    """§6: evaluation and production normalization drift independently."""
    import ast

    tree = ast.parse((BENCH / "persian_metrics.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    offenders = [m for m in imported if "yazses" in m or "persian_text" in m]
    assert not offenders, (
        f"the evaluation normalizer imports {offenders} — §6 versions evaluation "
        "and production normalization separately so a production fix cannot "
        "silently move historical benchmark numbers"
    )
    # And the version is pinned, so results can name what scored them.
    assert persian_metrics.EVAL_NORMALIZER_VERSION == "fa-eval-v1"


# ── the quality metrics (§5) ─────────────────────────────────────────────────


def test_zwnj_metrics_are_computed_from_both_sides(persian_metrics):
    m = persian_metrics.compute_zwnj_metrics
    # ref 2 ZWNJ, hyp 1: matched 1, precision 1.0, recall 0.5.
    r = m(["a\u200cb\u200cc"], ["a\u200cbc"])
    assert (r.reference_count, r.hypothesis_count, r.matched_count) == (2, 1, 1)
    assert r.precision == 1.0 and r.recall == 0.5


def test_zwnj_metrics_vacuous_case_is_not_a_zero(persian_metrics):
    # No ZWNJ anywhere: perfect by absence, not 0.0 by division guard.
    m = persian_metrics.compute_zwnj_metrics(["abc"], ["abc"])
    assert m.precision == 1.0 and m.recall == 1.0 and m.f1 == 1.0


def test_arabic_variant_counts_see_the_noncanonical_letters(persian_metrics):
    yeh, kaf = persian_metrics.count_arabic_variants("\u064a\u06a9\u0643")
    assert (yeh, kaf) == (1, 1)


# ── the scoring core ─────────────────────────────────────────────────────────


def test_score_pairs_reports_raw_and_normalized_separately(bench_persian):
    # Arabic Yeh: mismatch raw, hit normalized — the exact case both numbers exist for.
    out = bench_persian.score_pairs(
        ["\u062f\u0646\u06cc\u0627"], ["\u062f\u0646\u064a\u0627"], ["s1"]
    )
    assert out["wer_raw"] == 100.0
    assert out["wer_normalized"] == 0.0
    assert out["n_pairs"] == 1


def test_score_pairs_counts_a_real_error_under_both(bench_persian):
    out = bench_persian.score_pairs(["\u0627\u0644\u0641"], ["\u0628"], ["s1"])
    assert out["wer_raw"] == 100.0 and out["wer_normalized"] == 100.0


def test_score_pairs_skips_empty_references_and_says_so(bench_persian):
    out = bench_persian.score_pairs(
        ["abc", "  ", "def"], ["abc", "x", "def"], ["1", "2", "3"]
    )
    assert out["n_pairs"] == 2 and out["n_skipped_empty"] == 1


def test_score_pairs_refuses_misaligned_inputs(bench_persian):
    with pytest.raises(ValueError, match="align"):
        bench_persian.score_pairs(["a"], ["a", "b"], ["1"])
    with pytest.raises(ValueError, match="empty manifest"):
        bench_persian.score_pairs([], [], [])


# ── the §7 schema validator ──────────────────────────────────────────────────


def test_validator_accepts_the_smoke_document(bench_persian):
    doc = bench_persian.run_smoke()
    assert bench_persian.validate_result(doc) == []


def test_validator_rejects_broken_documents(bench_persian):
    v = bench_persian.validate_result
    assert v({}) , "an empty document must not validate"
    doc = bench_persian.run_smoke()
    del doc["metrics"]["wer_raw"]
    assert any("wer_raw" in p for p in v(doc))
    doc = bench_persian.run_smoke()
    doc["schema_version"] = 99
    assert any("schema_version" in p for p in v(doc))


def test_smoke_run_needs_no_audio_or_model(bench_persian):
    """The acceptance line 'CI can run a small smoke benchmark' — proven structurally:
    the smoke path never calls the engine factory."""
    src = (BENCH / "bench_persian.py").read_text(encoding="utf-8")
    smoke_fn = src.split("def run_smoke(")[1].split("\ndef ")[0]
    assert "build_engine" not in smoke_fn and "load_audio" not in smoke_fn


# ── the CLI contract ─────────────────────────────────────────────────────────


def test_one_command_emits_schema_valid_json(bench_persian):
    """The literal acceptance criterion, executed as a subprocess."""
    r = subprocess.run(
        [sys.executable, str(BENCH / "bench_persian.py"), "--smoke"],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(BENCH),
    )
    assert r.returncode == 0, r.stderr
    doc = json.loads(r.stdout)
    assert bench_persian.validate_result(doc) == []
    # Raw and normalized both present and distinct where they should be.
    m = doc["metrics"]
    assert m["wer_raw"] > m["wer_normalized"], (
        "the smoke set contains an Arabic-Yeh trap: normalized WER must be "
        "strictly lower than raw, or the two scorers are not doing different work"
    )
    assert m["evaluation_normalizer"] == "fa-eval-v1"
