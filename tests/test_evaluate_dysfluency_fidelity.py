"""Synthetic-only and privacy-safe evaluation runner regression tests (issue #255)."""

from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path

import pytest

import runpy

# This executable is a research script, not an installed distribution. Load it
# from its checked-in path rather than declaring a fictional "scripts" package.
_RUNNER = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts" / "evaluate_dysfluency_fidelity.py"),
    run_name="dysfluency_fidelity_test_runner",
)
EvaluationInputError = _RUNNER["EvaluationInputError"]
_word_errors = _RUNNER["_word_errors"]
_write_aggregate_report = _RUNNER["_write_aggregate_report"]
evaluate_synthetic = _RUNNER["evaluate_synthetic"]
main = _RUNNER["main"]

_FIXTURE = Path(__file__).parent / "fixtures" / "disfluency" / "fidelity_synthetic.json"
_DIGEST = "0" * 64


def item(**overrides):
    case = {
        "id": "SYN-TEST-001",
        "stratum": "interjection",
        "asr_text": "um hello",
        "verbatim_reference": "um hello",
        "semantic_reference": "hello",
        "expected_on": "hello",
        "oracle_label": "safe-cleanup",
        "oracle_status": "confirmed",
    }
    case.update(overrides)
    return case


def payload(*cases):
    return {"schema_version": 1, "fixture_scope": "synthetic", "cases": list(cases)}


def test_paired_conditions_use_identical_input():
    calls = []

    def off(text):
        calls.append(("off", text))
        return text

    def on(text):
        calls.append(("on", text))
        return "hello"

    result = evaluate_synthetic(payload(item()), filter_off=off, filter_on=on,
                                manifest_sha256=_DIGEST)
    assert calls == [("off", "um hello"), ("on", "um hello")]
    assert result["decision"] == "PASS_SYNTHETIC"
    assert result["changed_cases"] == 1
    assert result["confirmed_new_destructive_cases"] == 0


def test_independent_verbatim_and_semantic_wer_reveal_tradeoff():
    report = evaluate_synthetic(payload(item()), filter_off=lambda s: s,
                                filter_on=lambda s: "hello", manifest_sha256=_DIGEST)
    errors = report["word_error_counts"]
    assert errors["verbatim_off"]["micro_wer"] == 0.0
    assert errors["verbatim_on"]["micro_wer"] == 0.5
    assert errors["semantic_off"]["micro_wer"] == 1.0
    assert errors["semantic_on"]["micro_wer"] == 0.0
    assert errors["verbatim_off"]["reference_words"] == 2
    assert errors["semantic_off"]["reference_words"] == 1


def test_word_distance_reports_insertions_deletions_and_substitutions():
    assert _word_errors("one two three", "one three") == (1, 3)
    assert _word_errors("one two", "one new two") == (1, 2)
    assert _word_errors("one two", "one too") == (1, 2)
    assert _word_errors("ONE  two", "one two") == (0, 2)
    assert _word_errors("", "added") == (1, 0)


def test_empty_references_do_not_create_a_division_by_zero():
    case = item(verbatim_reference="", semantic_reference="")
    report = evaluate_synthetic(payload(case), filter_off=lambda s: s,
                                filter_on=lambda s: "hello", manifest_sha256=_DIGEST)
    assert report["word_error_counts"]["verbatim_on"]["micro_wer"] is None
    assert report["word_error_counts"]["semantic_on"]["cases_scored"] == 0


def test_confirmed_destructive_change_is_not_averaged_away():
    safe = item()
    destructive = item(id="SYN-TEST-002", asr_text="the dose is not high",
                       verbatim_reference="the dose is not high",
                       semantic_reference="the dose is not high",
                       expected_on="the dose is high",
                       oracle_label="destructive-content")

    def clean(s):
        return "hello" if s == "um hello" else "the dose is high"

    report = evaluate_synthetic(payload(safe, destructive), filter_off=lambda s: s,
                                filter_on=clean, manifest_sha256=_DIGEST)
    assert report["confirmed_new_destructive_cases"] == 1
    assert report["decision"] == "FAIL_SYNTHETIC"
    assert report["safe_cleanup_yield_nonfluent"]["numerator"] == 1


def test_disputed_candidate_does_not_count_as_a_pass():
    suspect = item(oracle_status="disputed")
    report = evaluate_synthetic(payload(suspect), filter_off=lambda s: s,
                                filter_on=lambda s: "hello", manifest_sha256=_DIGEST)
    assert report["decision"] == "INCONCLUSIVE_SYNTHETIC"
    assert report["unresolved_oracle_cases"] == 1


def test_one_confirmed_destructive_takes_precedence_over_one_disputed():
    destructive = item(oracle_label="destructive-structure", expected_on="hello",
                       oracle_status="confirmed")
    disputed = item(id="SYN-TEST-002", oracle_status="pending")
    result = evaluate_synthetic(payload(destructive, disputed), filter_off=lambda s: s,
                                filter_on=lambda s: "hello", manifest_sha256=_DIGEST)
    assert result["decision"] == "FAIL_SYNTHETIC"
    assert result["unresolved_oracle_cases"] == 1


def test_oracle_mismatch_is_inconclusive_not_a_false_success():
    result = evaluate_synthetic(payload(item(expected_on="something else")),
                                filter_off=lambda s: s, filter_on=lambda s: "hello",
                                manifest_sha256=_DIGEST)
    assert result["decision"] == "INCONCLUSIVE_SYNTHETIC"
    assert result["fixture_output_or_label_mismatches"] == 1
    assert result["safe_cleanup_yield_nonfluent"]["numerator"] == 0


def test_safe_cleanup_label_cannot_claim_credit_for_unchanged_text():
    result = evaluate_synthetic(payload(item()), filter_off=lambda s: s,
                                filter_on=lambda s: s, manifest_sha256=_DIGEST)
    assert result["decision"] == "INCONCLUSIVE_SYNTHETIC"


def test_filter_off_must_be_byte_identical():
    with pytest.raises(EvaluationInputError, match="filter-off changed"):
        evaluate_synthetic(payload(item()), filter_off=lambda s: s.upper(),
                           filter_on=lambda s: "hello", manifest_sha256=_DIGEST)


def test_fluent_false_change_reports_both_numerator_and_denominator():
    fluent = item(stratum="fluent", oracle_label="destructive-content",
                  asr_text="she is sort of stable", expected_on="she is stable",
                  verbatim_reference="she is sort of stable",
                  semantic_reference="she is sort of stable")
    other = item(id="SYN-TEST-002", stratum="fluent", oracle_label="no-material-edit",
                 asr_text="a normal sentence", expected_on="a normal sentence",
                 verbatim_reference="a normal sentence", semantic_reference="a normal sentence")
    result = evaluate_synthetic(payload(fluent, other), filter_off=lambda s: s,
                                filter_on=lambda s: s.replace("sort of ", ""),
                                manifest_sha256=_DIGEST)
    assert result["fluent_changes"] == {"numerator": 1, "denominator": 2, "rate": 0.5}
    assert result["safe_cleanup_yield_nonfluent"]["rate"] is None


def test_fluent_safe_change_does_not_count_as_nonfluent_cleanup():
    fluent = item(stratum="fluent")
    report = evaluate_synthetic(payload(fluent), filter_off=lambda s: s,
                                filter_on=lambda s: "hello", manifest_sha256=_DIGEST)
    assert report["safe_cleanup_yield_nonfluent"] == {
        "numerator": 0, "denominator": 0, "rate": None,
    }
    assert report["fluent_changes"]["numerator"] == 1


def test_synthetic_only_enforced_and_no_real_input_metadata_needed():
    bad = payload(item())
    bad["fixture_scope"] = "real-audio"
    with pytest.raises(EvaluationInputError, match="synthetic fixtures only"):
        evaluate_synthetic(bad, filter_off=lambda s: s,
                           filter_on=lambda s: s, manifest_sha256=_DIGEST)


@pytest.mark.parametrize("change", [
    {"schema_version": True},
    {"schema_version": 999},
    {"extra": "do not accept unknown data fields"},
    {"cases": []},
    {"cases": [item(id="participant-007")]},
    {"cases": [item(oracle_label="definitely-safe")]},
    {"cases": [item(stratum="unknown")]},
    {"cases": [item(asr_text="x" * 2501)]},
    {"cases": [item(), item()]},
])
def test_invalid_schema_rejected_without_reflecting_text(change):
    original = payload(item())
    original.update(change)
    with pytest.raises(EvaluationInputError) as exc:
        evaluate_synthetic(original, filter_off=lambda s: s,
                           filter_on=lambda s: s, manifest_sha256=_DIGEST)
    assert "um hello" not in str(exc.value)


def test_report_contains_aggregates_not_transcripts_or_case_ids():
    secret = "TEST_ONLY_SENSITIVE_STRING_NEVER_IN_REPORT"
    case = item(asr_text="um " + secret, expected_on=secret,
                verbatim_reference="um " + secret, semantic_reference=secret)
    report = evaluate_synthetic(payload(case), filter_off=lambda s: s,
                                filter_on=lambda s: secret, manifest_sha256=_DIGEST)
    encoded = json.dumps(report)
    assert secret not in encoded
    assert case["id"] not in encoded
    assert "cases" not in report
    assert report["scope"].startswith("synthetic-only")


def test_report_writer_is_exclusive_and_aggregate_only(tmp_path):
    target = tmp_path / "result.json"
    data = {"decision": "PASS_SYNTHETIC", "case_count": 1}
    _write_aggregate_report(target, data)
    assert json.loads(target.read_text(encoding="utf-8")) == data
    if os.name == "posix":
        assert target.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        _write_aggregate_report(target, {"decision": "FAIL_SYNTHETIC"})
    assert json.loads(target.read_text(encoding="utf-8")) == data


def test_cli_rejects_non_synthetic_before_loading_yazses(tmp_path, capsys):
    source = tmp_path / "not-synthetic.json"
    invalid = deepcopy(payload(item()))
    invalid["fixture_scope"] = "private-recordings"
    source.write_text(json.dumps(invalid), encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        main([str(source)])
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert "synthetic fixtures only" in captured.err
    assert "um hello" not in captured.err


def test_real_filter_matches_committed_synthetic_oracles(capsys):
    pytest.importorskip("yazses.config")
    expected_digest = hashlib.sha256(_FIXTURE.read_bytes()).hexdigest()
    assert main([str(_FIXTURE)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["manifest_sha256"] == expected_digest
    assert report["case_count"] == 9
    assert report["decision"] == "PASS_SYNTHETIC"
    assert report["fixture_output_or_label_mismatches"] == 0
    assert report["confirmed_new_destructive_cases"] == 0
    assert report["fluent_changes"]["numerator"] == 0
    assert report["word_error_counts"]["semantic_on"]["micro_wer"] == 0.0
