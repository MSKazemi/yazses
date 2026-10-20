"""The #426 analysis of de-identified eye-control results: what it computes and what it refuses.

Every record here is SYNTHETIC and built in this file. They prove the CODE -- the
arithmetic, the refusals, the grouping -- and say nothing about how well gaze, head pointer
or face switch work. No threshold in `yazses.eyeeval.analysis` was derived from them, and
no test asserts that a particular rate is "good".

Shapes this file exists to catch, each of which has gone wrong elsewhere:

* trials counted as participants (one person, three sessions, 120 trials is ONE participant);
* a `community_qa` row quietly pooled into a research analysis;
* a rate printed from a handful of trials;
* wrong-target and fallback collapsed into one "error", or poor performance used to exclude;
* a missing count read as zero;
* latency averaged across unlike machines;
* output that depends on file order, hash seed or the clock.
"""

from __future__ import annotations

import dataclasses
import json
import os
import random
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from yazses.eyeeval import (
    FACE_SWITCH_TASK,
    GAZE_TASK,
    HEAD_POINTER_TASK,
    Provenance,
    build_result,
    dump_result,
    generate_task,
)
from yazses.eyeeval import analysis as A
from yazses.eyeeval.analysis import INSUFFICIENT, EyeAnalysisError, analyze, wilson_interval

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "analyze_eye_eval.py"

_PROV = Provenance(
    yazses_version="9.9.9", git_commit="0123456789ab", python_version="3.13.0",
    os_name="ExampleOS", os_version="1.2", kernel="0.0.0-test", arch="x86_64",
    cpu_model="Example CPU 1000", logical_cpus=8, ram_gb=16.0, session_type="headless",
    displays=({"index": 0, "x": 0, "y": 0, "width": 1920, "height": 1080,
               "scale": 1.0, "primary": True},),
    packages={"yazses": "9.9.9"},
)

_SEQ = [0]


def make_doc(
    task_id: str = GAZE_TASK,
    outcomes: dict[str, int] | None = None,
    *,
    mode: str = "research",
    cpu: str = "Example CPU 1000",
    os_name: str = "ExampleOS",
    latency: int | None = None,
    false_events: int = 0,
    blocked: str | None = None,
) -> dict[str, Any]:
    """One synthetic, schema-valid result document with the given outcome counts."""
    _SEQ[0] += 1
    task = generate_task(task_id)
    records: list[dict[str, Any]] = []
    index = 0
    for outcome, count in (outcomes or {}).items():
        for _ in range(count):
            record: dict[str, Any] = {"outcome": "correct" if outcome == "correct_target" else outcome}
            if task_id == FACE_SWITCH_TASK:
                record.update(block_id="b", block_type="x", cue_index=index)
                if latency is not None:
                    record["activation_latency_ms"] = latency
            else:
                record["trial_index"] = index
                if latency is not None and task_id == GAZE_TASK:
                    record["trial_time_ms"] = latency
                if latency is not None and task_id == HEAD_POINTER_TASK:
                    record.update(movement_start_ms=0, movement_end_ms=latency)
            records.append(record)
            index += 1
    if task_id == FACE_SWITCH_TASK:
        records.append({"block_id": "b", "block_type": "x", "false_activation_count": false_events})
    prov = dataclasses.replace(_PROV, cpu_model=cpu, os_name=os_name)
    return build_result(
        task=task, records=records, provenance=prov, study_mode=mode,
        timestamp=f"2026-10-15T00:00:{_SEQ[0] % 60:02d}+00:{_SEQ[0] // 60:02d}",
        camera_class="integrated", capture_mode="live", records_source="synthetic test",
        protocol_id="STUDY-A" if mode == "research" else None, blocked_reason=blocked,
    )


def raw(doc: dict[str, Any]) -> bytes:
    return dump_result(doc).encode("utf-8")


def links(*rows: tuple[str, str, str, bool], extra: dict[str, dict[str, Any]] | None = None) -> str:
    out = []
    for name, participant, session, pilot in rows:
        row = {"result": name, "participant_id": participant, "session_id": session, "pilot": pilot}
        row.update((extra or {}).get(name, {}))
        out.append(row)
    return json.dumps({"links_version": "1.0", "rows": out})


GAZE_40 = {"correct_target": 30, "wrong_target": 4, "fallback_no_route": 5, "invalid_tracking": 1}


def study(n_participants: int = 5, sessions: int = 1, counts: dict[str, int] | None = None, **kw: Any):
    """A research study: inputs and a links text."""
    inputs, rows = [], []
    for p in range(n_participants):
        for s in range(sessions):
            name = f"r_p{p}_s{s}.json"
            inputs.append((name, raw(make_doc(outcomes=counts or GAZE_40, **kw))))
            rows.append((name, f"P{p:02d}", f"S{s}", False))
    return inputs, links(*rows)


def stratum(report: dict[str, Any], i: int = 0) -> dict[str, Any]:
    return report["strata"][i]


# --- the interval ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("k", "n", "lo", "hi"),
    [(5, 10, 0.2366, 0.7634), (0, 10, 0.0, 0.2775), (10, 10, 0.7225, 1.0), (1, 2, 0.0945, 0.9055)],
)
def test_wilson_matches_published_values(k: int, n: int, lo: float, hi: float) -> None:
    got = wilson_interval(k, n)
    assert got[0] == pytest.approx(lo, abs=5e-4) and got[1] == pytest.approx(hi, abs=5e-4)


def test_wilson_always_contains_the_estimate_and_stays_in_unit_interval() -> None:
    for n in range(1, 41):
        for k in range(n + 1):
            lo, hi = wilson_interval(k, n)
            assert 0.0 <= lo <= k / n <= hi <= 1.0


@pytest.mark.parametrize(("k", "n"), [(1, 0), (-1, 5), (6, 5)])
def test_wilson_refuses_an_impossible_count(k: int, n: int) -> None:
    with pytest.raises(ValueError):
        wilson_interval(k, n)


# --- refusals --------------------------------------------------------------------------


def test_the_unit_is_never_assumed() -> None:
    inputs, text = study(1)
    with pytest.raises(EyeAnalysisError, match="aggregation unit is never assumed"):
        analyze(inputs, unit="trial", links_text=text)


def test_nothing_to_analyse_is_a_refusal_not_a_clean_report() -> None:
    with pytest.raises(EyeAnalysisError, match="no result files"):
        analyze([], unit="run", links_text=links(("a.json", "P01", "S0", False)))


def test_a_research_analysis_without_links_is_refused() -> None:
    inputs, _ = study(1)
    with pytest.raises(EyeAnalysisError, match="links file is required"):
        analyze(inputs, unit="run")


def test_participant_unit_without_links_is_refused_even_for_qa() -> None:
    inputs = [("a.json", raw(make_doc(mode="community_qa")))]
    with pytest.raises(EyeAnalysisError, match="links file is required"):
        analyze(inputs, unit="participant", study_mode="community_qa")


def test_an_unknown_schema_major_is_refused() -> None:
    doc = make_doc()
    doc["schema_version"] = "2.0"
    with pytest.raises(EyeAnalysisError, match="major version 2"):
        analyze([("a.json", raw(doc))], unit="run", links_text=links(("a.json", "P01", "S0", False)))


def test_a_schema_invalid_result_is_refused_with_its_problem() -> None:
    doc = make_doc()
    del doc["machine"]
    with pytest.raises(EyeAnalysisError, match="machine: missing required field"):
        analyze([("a.json", raw(doc))], unit="run", links_text=links(("a.json", "P01", "S0", False)))


def test_a_result_carrying_an_identifier_field_is_refused() -> None:
    doc = make_doc()
    doc["run"]["participant_email"] = "x"
    with pytest.raises(EyeAnalysisError, match="forbidden field"):
        analyze([("a.json", raw(doc))], unit="run", links_text=links(("a.json", "P01", "S0", False)))


def test_a_home_path_inside_a_value_is_refused() -> None:
    doc = make_doc()
    doc["run"]["records_source"] = "/home/someone/study.json"
    with pytest.raises(EyeAnalysisError, match="home directory"):
        analyze([("a.json", raw(doc))], unit="run", links_text=links(("a.json", "P01", "S0", False)))


def test_a_community_qa_row_never_enters_a_research_analysis() -> None:
    inputs, text = study(2)
    inputs.append(("qa.json", raw(make_doc(mode="community_qa"))))
    text = text.replace("]}", ',{"result":"qa.json","participant_id":"P99","session_id":"S0","pilot":false}]}')
    with pytest.raises(EyeAnalysisError, match="community_qa row is never pooled"):
        analyze(inputs, unit="participant", links_text=text)


def test_a_qa_only_input_cannot_pass_as_research() -> None:
    inputs = [("qa.json", raw(make_doc(mode="community_qa")))]
    with pytest.raises(EyeAnalysisError, match="do not match the requested analysis mode"):
        analyze(inputs, unit="run", links_text=links(("qa.json", "P01", "S0", False)))


def test_a_qa_analysis_is_allowed_when_asked_for_and_needs_no_links() -> None:
    inputs = [("qa.json", raw(make_doc(mode="community_qa")))]
    report = analyze(inputs, unit="run", study_mode="community_qa")
    assert report["study_mode"] == "community_qa"
    assert report["counts"]["analysed"]["participants"].startswith("not available")


def test_the_same_bytes_twice_are_not_two_runs() -> None:
    data = raw(make_doc())
    with pytest.raises(EyeAnalysisError, match="a repeated file is not another run"):
        analyze([("a.json", data), ("b.json", data)], unit="run",
                links_text=links(("a.json", "P01", "S0", False), ("b.json", "P02", "S0", False)))


def test_counts_that_do_not_add_up_are_refused_not_repaired() -> None:
    doc = make_doc(outcomes=GAZE_40)
    doc["metrics"]["trials"] = 41
    with pytest.raises(EyeAnalysisError, match="do not add up"):
        analyze([("a.json", raw(doc))], unit="run", links_text=links(("a.json", "P01", "S0", False)))


def test_a_fractional_count_is_refused() -> None:
    doc = make_doc(outcomes=GAZE_40)
    doc["metrics"]["wrong_target"] = 4.5
    with pytest.raises(EyeAnalysisError, match="whole, non-negative count"):
        analyze([("a.json", raw(doc))], unit="run", links_text=links(("a.json", "P01", "S0", False)))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["rows"][0].update(name="Ada"),
        lambda d: d["rows"][0].update(participant_id="ada@example.org"),
        lambda d: d["rows"][0].update(pilot="no"),
        lambda d: d["rows"][0].update(github_user="x"),
        lambda d: d["rows"][0].update(exclusion={"category": "poor", "reason": "x", "predefined": True}),
        lambda d: d.update(links_version="9.0"),
    ],
    ids=["name", "email-id", "pilot-string", "github", "bad-category", "version"],
)
def test_the_links_file_is_a_closed_shape(mutate: Any) -> None:
    inputs, text = study(1)
    doc = json.loads(text)
    mutate(doc)
    with pytest.raises(EyeAnalysisError):
        analyze(inputs, unit="run", links_text=json.dumps(doc))


def test_a_result_missing_from_the_links_file_is_refused() -> None:
    inputs, text = study(2)
    inputs.append(("extra.json", raw(make_doc())))
    with pytest.raises(EyeAnalysisError, match="not listed in the links file"):
        analyze(inputs, unit="run", links_text=text)


def test_a_link_to_a_file_that_was_not_given_is_refused() -> None:
    inputs, text = study(2)
    with pytest.raises(EyeAnalysisError, match="matches no result file"):
        analyze(inputs[:1], unit="run", links_text=text)


# --- the independent unit ---------------------------------------------------------------


def test_forty_trials_times_three_sessions_is_still_one_participant() -> None:
    inputs, text = study(1, sessions=3)
    report = analyze(inputs, unit="participant", links_text=text)
    counts = report["counts"]["analysed"]
    assert (counts["participants"], counts["sessions"], counts["runs"]) == (1, 3, 3)
    assert counts["trials_by_task"] == {GAZE_TASK: 120}
    assert stratum(report)["across_units"]["units_total"] == 1
    # One participant is far below the unit floor: the across-unit summary must refuse.
    assert stratum(report)["across_units"]["correct_target"]["summary"] == INSUFFICIENT


def test_participants_sessions_runs_and_hosts_are_reported_separately() -> None:
    inputs, text = study(3, sessions=2, cpu="Same CPU")
    inputs.append(("other.json", raw(make_doc(outcomes=GAZE_40, cpu="Other CPU"))))
    text = text.replace("]}", ',{"result":"other.json","participant_id":"P00","session_id":"S9","pilot":false}]}')
    c = analyze(inputs, unit="session", links_text=text)["counts"]["analysed"]
    assert (c["participants"], c["sessions"], c["runs"], c["distinct_hosts"]) == (3, 7, 7, 2)
    assert "lower bound" in c["host_identity"][0]


def test_a_declared_host_id_overrides_the_fingerprint() -> None:
    inputs, text = study(2)
    extra = {n: {"host_id": "H1"} for n, _ in inputs}
    rows = [(n, f"P{i:02d}", "S0", False) for i, (n, _) in enumerate(inputs)]
    c = analyze(inputs, unit="run", links_text=links(*rows, extra=extra))["counts"]["analysed"]
    assert c["distinct_hosts"] == 1 and c["host_identity"] == ["links host_id"]


def test_session_unit_pools_runs_of_one_session_and_keeps_sessions_apart() -> None:
    a, b, c = (raw(make_doc(outcomes=GAZE_40)) for _ in range(3))
    text = links(("a.json", "P00", "S0", False), ("b.json", "P00", "S0", False), ("c.json", "P00", "S1", False))
    units = stratum(analyze([("a.json", a), ("b.json", b), ("c.json", c)], unit="session", links_text=text))["units"]
    assert {u["unit"]: u["outcomes"]["correct_target"]["n"] for u in units} == {"P00/S0": 80, "P00/S1": 40}


# --- rates, denominators and the difference between failure kinds --------------------------


def test_a_rate_below_the_minimum_n_prints_insufficient_data_not_a_number() -> None:
    doc = make_doc(outcomes={"correct_target": 9, "wrong_target": 1})
    entry = stratum(analyze([("a.json", raw(doc))], unit="run", links_text=links(("a.json", "P0", "S0", False))))[
        "units"][0]["outcomes"]["correct_target"]
    assert entry["rate"] == INSUFFICIENT and entry["n"] == 10 and "k" not in entry and "ci95_wilson" not in entry
    assert entry["provisional"] is True


def test_the_minimum_is_inclusive_and_overridable() -> None:
    doc = make_doc(outcomes={"correct_target": 8, "wrong_target": 2})
    one = [("a.json", raw(doc))]
    lk = links(("a.json", "P0", "S0", False))
    at = analyze(one, unit="run", links_text=lk, min_trials=10)
    below = analyze(one, unit="run", links_text=lk, min_trials=11)
    assert stratum(at)["units"][0]["outcomes"]["correct_target"]["rate"] == 0.8
    assert stratum(below)["units"][0]["outcomes"]["correct_target"]["rate"] == INSUFFICIENT


def test_wrong_target_fallback_and_lost_tracking_stay_three_numbers() -> None:
    inputs, text = study(1)
    out = stratum(analyze(inputs, unit="run", links_text=text))["units"][0]["outcomes"]
    assert set(out) == {"correct_target", "wrong_target", "fallback_no_route", "invalid_tracking"}
    assert (out["wrong_target"]["k"], out["fallback_no_route"]["k"], out["invalid_tracking"]["k"]) == (4, 5, 1)
    assert all("n" in v and v["n"] == 40 for v in out.values())
    flat = json.dumps(analyze(inputs, unit="run", links_text=text))
    assert '"error' not in flat, "no combined error rate may exist"


def test_poor_performance_is_never_an_exclusion() -> None:
    bad = {"correct_target": 0, "wrong_target": 40}
    inputs = [("a.json", raw(make_doc(outcomes=bad)))]
    report = analyze(inputs, unit="run", links_text=links(("a.json", "P0", "S0", False)))
    assert report["exclusions"] == []
    assert stratum(report)["units"][0]["outcomes"]["wrong_target"]["rate"] == 1.0


def test_head_pointer_shares_and_face_switch_recall_use_their_own_denominators() -> None:
    head = make_doc(HEAD_POINTER_TASK, {"hit": 18, "miss": 4, "abandoned": 2, "tracking_lost": 1})
    face = make_doc(FACE_SWITCH_TASK, {"detected": 18, "missed": 2, "false_activation": 3}, false_events=3)
    report = analyze([("h.json", raw(head)), ("f.json", raw(face))], unit="run",
                     links_text=links(("h.json", "P0", "S0", False), ("f.json", "P0", "S0", False)))
    by_task = {s["stratum"]["task"]: s for s in report["strata"]}
    hit = by_task[HEAD_POINTER_TASK]["units"][0]["outcomes"]
    assert hit["hit"]["n"] == 25 and hit["tracking_lost"]["k"] == 1
    det = by_task[FACE_SWITCH_TASK]["units"][0]["outcomes"]
    assert det["detected"]["n"] == 20, "a false-activation record answers no cue"
    assert det["detected"]["rate"] == 0.9


def test_false_activations_are_events_over_exposure_hours() -> None:
    face = make_doc(FACE_SWITCH_TASK, {"detected": 20}, false_events=3)
    seconds = face["metrics"]["scored_duration_s"]
    assert isinstance(seconds, int)
    entry = stratum(analyze([("f.json", raw(face))], unit="run", links_text=links(("f.json", "P0", "S0", False)))
                    )["units"][0]["false_activations"]
    assert entry["events"] == 3 and entry["exposure_s"] == seconds
    assert entry["per_hour"] == round(3 / (seconds / 3600), 3)
    assert "ci95_wilson" not in entry, "no interval for a rate that needs a clustering model"


def test_short_exposure_prints_insufficient_data_for_the_hourly_rate() -> None:
    face = make_doc(FACE_SWITCH_TASK, {"detected": 20}, false_events=0)
    lk = links(("f.json", "P0", "S0", False))
    entry = stratum(analyze([("f.json", raw(face))], unit="run", links_text=lk, min_exposure_s=10**6)
                    )["units"][0]["false_activations"]
    assert entry["per_hour"] == INSUFFICIENT and "events" not in entry


def test_a_missing_exposure_is_a_reason_not_zero_false_activations() -> None:
    face = make_doc(FACE_SWITCH_TASK, {"detected": 20}, false_events=0)
    face["metrics"]["false_activation_count_total"] = {"value": None, "reason": "not_measured"}
    report = analyze([("f.json", raw(face))], unit="run", links_text=links(("f.json", "P0", "S0", False)))
    assert "false_activations" not in stratum(report)["units"][0]
    assert any(m["family"] == "exposure" and m["reason"] == "not_measured" for m in report["missing_data"])


# --- exclusions ----------------------------------------------------------------------------


def test_pilot_rows_are_excluded_by_default_and_reported() -> None:
    inputs, text = study(2)
    doc = json.loads(text)
    doc["rows"][0]["pilot"] = True
    report = analyze(inputs, unit="run", links_text=json.dumps(doc))
    assert [e["reason"] for e in report["exclusions"]] == ["pilot"]
    assert report["counts"]["loaded"]["runs"] == 2 and report["counts"]["analysed"]["runs"] == 1
    again = analyze(inputs, unit="run", links_text=json.dumps(doc), include_pilot=True)
    assert again["exclusions"] == [] and "exploratory" in again["pilot_rows"]


def test_a_blocked_run_is_a_technical_exclusion_with_its_reason() -> None:
    blocked = make_doc(blocked="technical_invalidation")
    stopped = make_doc(blocked="participant_stopped")
    good = make_doc(outcomes=GAZE_40)
    report = analyze(
        [("b.json", raw(blocked)), ("s.json", raw(stopped)), ("g.json", raw(good))], unit="run",
        links_text=links(("b.json", "P0", "S0", False), ("s.json", "P1", "S0", False), ("g.json", "P2", "S0", False)))
    got = {e["run"].split("@")[0]: (e["category"], e["reason"], e["predefined"]) for e in report["exclusions"]}
    assert got == {"b.json": ("technical", "technical_invalidation", True),
                   "s.json": ("withdrawal", "participant_stopped", True)}


def test_a_declared_exclusion_keeps_its_category_reason_and_whether_it_was_predefined() -> None:
    inputs, text = study(2)
    doc = json.loads(text)
    doc["rows"][1]["exclusion"] = {"category": "protocol", "reason": "script_deviation", "predefined": False}
    report = analyze(inputs, unit="run", links_text=json.dumps(doc))
    (ex,) = report["exclusions"]
    assert (ex["category"], ex["reason"], ex["predefined"]) == ("protocol", "script_deviation", False)
    assert report["counts"]["analysed"]["runs"] == 1


def test_an_unsupported_task_is_excluded_loudly_not_dropped() -> None:
    doc = make_doc()
    doc["protocol"]["task"] = "some_future_task"
    report = analyze([("a.json", raw(doc))], unit="run", links_text=links(("a.json", "P0", "S0", False)))
    assert report["exclusions"][0]["reason"] == "unsupported_task" and report["strata"] == []


# --- stratification, latency and test-retest ----------------------------------------------


def test_latency_is_listed_per_host_never_pooled() -> None:
    fast = raw(make_doc(outcomes=GAZE_40, latency=100, cpu="CPU A"))
    slow = raw(make_doc(outcomes=GAZE_40, latency=900, cpu="CPU B"))
    report = analyze([("a.json", fast), ("b.json", slow)], unit="run",
                     links_text=links(("a.json", "P0", "S0", False), ("b.json", "P1", "S0", False)))
    assert len(report["strata"]) == 2
    assert sorted(s["latency"]["per_run_p50"][0] for s in report["strata"]) == [100, 900]
    assert all(len(s["latency"]["per_run_p50"]) == 1 for s in report["strata"])
    assert "pooled" not in json.dumps(report).replace("never pooled", "")


def test_a_different_os_is_a_different_stratum() -> None:
    a = raw(make_doc(os_name="OS-A"))
    b = raw(make_doc(os_name="OS-B"))
    report = analyze([("a.json", a), ("b.json", b)], unit="run",
                     links_text=links(("a.json", "P0", "S0", False), ("b.json", "P1", "S0", False)))
    assert len({s["stratum_id"] for s in report["strata"]}) == 2


def test_missing_latency_keeps_its_reason() -> None:
    inputs, text = study(1)
    s = stratum(analyze(inputs, unit="run", links_text=text))
    assert s["latency"]["runs_with_value"] == 0 and s["latency"]["missing_by_reason"] == {"not_measured": 1}


def test_test_retest_reports_each_participants_session_spread() -> None:
    inputs, rows = [], []
    for p in range(5):
        for s, correct in enumerate((30, 24)):
            name = f"p{p}s{s}.json"
            inputs.append((name, raw(make_doc(outcomes={"correct_target": correct, "wrong_target": 40 - correct}))))
            rows.append((name, f"P{p}", f"S{s}", False))
    rt = stratum(analyze(inputs, unit="participant", links_text=links(*rows)))["session_retest"]
    assert rt["participants_with_two_or_more_sessions"] == 5
    assert rt["rows"][0]["spread"] == 0.15 and rt["summary"]["median"] == 0.15


def test_test_retest_needs_enough_participants_and_a_links_file() -> None:
    inputs, text = study(2, sessions=2)
    rt = stratum(analyze(inputs, unit="participant", links_text=text))["session_retest"]
    assert rt["summary"] == INSUFFICIENT and len(rt["rows"]) == 2
    qa = analyze([("q.json", raw(make_doc(mode="community_qa")))], unit="run", study_mode="community_qa")
    assert stratum(qa)["session_retest"]["status"].startswith("not available")


def test_across_unit_summary_appears_only_with_enough_units() -> None:
    inputs, text = study(5)
    s = stratum(analyze(inputs, unit="participant", links_text=text))["across_units"]["correct_target"]
    assert s["min"] == s["median"] == s["max"] == 0.75 and s["units_with_enough_data"] == 5
    inputs4, text4 = study(4)
    s4 = stratum(analyze(inputs4, unit="participant", links_text=text4))["across_units"]["correct_target"]
    assert s4["summary"] == INSUFFICIENT


# --- provenance of every number ------------------------------------------------------------


def test_every_reported_row_has_a_claim_manifest_entry_naming_real_source_runs() -> None:
    inputs, text = study(3, sessions=2)
    report = analyze(inputs, unit="participant", links_text=text)
    run_ids = {f"{n}@" for n, _ in inputs}
    claims = {c["claim_id"]: c for c in report["claim_manifest"]}
    for s in report["strata"]:
        for u in s["units"]:
            claim = claims[f"{s['stratum_id']}/outcomes/{u['unit']}"]
            assert claim["source_runs"] == u["source_runs"] and len(u["source_runs"]) == 2
            assert all(r.split("@")[0] + "@" in run_ids for r in claim["source_runs"])


def test_every_output_is_labelled_provisional_with_its_n() -> None:
    inputs, text = study(5)
    report = analyze(inputs, unit="participant", links_text=text)
    assert report["provisional"] is True and report["minimums"]["status"] == "provisional"
    md = A.render_markdown(report)
    assert "PROVISIONAL" in md and "(n=40)" in md and "provisional" in md.lower()
    for entry in stratum(report)["units"][0]["outcomes"].values():
        assert entry["provisional"] is True and entry["n"] == 40


# --- determinism -----------------------------------------------------------------------------


def test_the_report_does_not_depend_on_file_order() -> None:
    inputs, text = study(5, sessions=2)
    shuffled = list(inputs)
    random.Random(7).shuffle(shuffled)
    a = analyze(inputs, unit="participant", links_text=text)
    b = analyze(shuffled, unit="participant", links_text=text)
    assert A.dump_report(a) == A.dump_report(b) and A.render_markdown(a) == A.render_markdown(b)


# --- the script ----------------------------------------------------------------------------


def _run(args: list[str], seed: str = "0") -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONHASHSEED": seed}
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=env, check=False)


def _write(tmp_path: Path, n: int = 5) -> tuple[Path, Path]:
    inputs, text = study(n, sessions=2)
    results = tmp_path / "results"
    results.mkdir()
    for name, data in inputs:
        (results / name).write_bytes(data)
    lk = tmp_path / "links.json"
    lk.write_text(text, encoding="utf-8")
    return results, lk


def test_script_prints_the_same_bytes_across_processes_and_hash_seeds(tmp_path: Path) -> None:
    results, lk = _write(tmp_path)
    args = ["--unit", "participant", "--links", str(lk), "--format", "json", str(results)]
    first, second = _run(args, "1"), _run(args, "12345")
    assert first.returncode == 0 == second.returncode, first.stderr
    assert first.stdout == second.stdout and json.loads(first.stdout)["provisional"] is True


def test_script_exit_codes(tmp_path: Path) -> None:
    results, lk = _write(tmp_path)
    assert _run(["--unit", "run"]).returncode == 2
    assert _run(["--unit", "participant", str(results)]).returncode == 1  # no links file
    (results / "bad.json").write_text("{}", encoding="utf-8")
    refused = _run(["--unit", "participant", "--links", str(lk), str(results)])
    assert refused.returncode == 1 and "REFUSED" in refused.stderr and refused.stdout == ""
    ok = _run(["--unit", "participant", "--links", str(lk), str(results / "r_p0_s0.json"),
               str(results / "r_p0_s1.json")])
    assert ok.returncode == 1, "the links file names results that were not given"


def test_script_writes_markdown_to_out(tmp_path: Path) -> None:
    results, lk = _write(tmp_path)
    out = tmp_path / "report.md"
    done = _run(["--unit", "participant", "--links", str(lk), "--out", str(out), str(results)])
    assert done.returncode == 0 and done.stdout == ""
    assert out.read_text(encoding="utf-8").startswith("# Eye-control evaluation analysis")


def test_the_module_says_fixtures_prove_the_code_not_the_product() -> None:
    assert "Fixtures prove the code, not the product" in (A.__doc__ or "")
    assert "prove the CODE" in (__doc__ or "")


def test_the_module_is_stdlib_only() -> None:
    src = (ROOT / "src" / "yazses" / "eyeeval" / "analysis.py").read_text(encoding="utf-8")
    for heavy in ("numpy", "scipy", "pandas", "matplotlib", "statsmodels"):
        assert f"import {heavy}" not in src and f"from {heavy}" not in src
