"""Phase R0 of the streaming replay protocol: the pure oracle over the v1 fixtures.

Synthetic traces only. These tests give no evidence about any editor, display
server, injector or ASR model; they check the *policy oracle* is internally
consistent and that each rule is load-bearing.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

import pytest

from yazses.stt.streaming_replay import (
    ReplayFormatError,
    Rules,
    load_traces,
    parse_trace,
    reduce_trace,
)

FIXTURE = Path(__file__).resolve().parents[1] / "design/research/fixtures/streaming-replay-v1.jsonl"
FIXTURE_SHA256 = "b32f48d2268edd0bfe425cf684739f73e63ff765927742d77bef3f52d1361397"
KNOWN_DEFECT_IDS = {"SR-002", "SR-003", "SR-004", "SR-006", "SR-011", "SR-014", "SR-015"}

LINES = FIXTURE.read_text(encoding="utf-8").splitlines()
TRACES = load_traces(LINES)
BY_ID = {t.id: t for t in TRACES}


def _want(trace):
    return {k: v for k, v in trace.expect.items() if k != "known_defect"}


def _mismatching(rules: Rules) -> set[str]:
    return {t.id for t in TRACES if reduce_trace(t, rules).as_expect() != _want(t)}


def test_fixture_is_the_reviewed_file():
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == FIXTURE_SHA256


def test_all_sixteen_fixtures_load_with_unique_ids():
    assert [t.id for t in TRACES] == [f"SR-{i:03d}" for i in range(1, 17)]


@pytest.mark.parametrize("trace", TRACES, ids=lambda t: t.id)
def test_fixture_expect_block(trace):
    assert reduce_trace(trace).as_expect() == _want(trace)


def test_known_defect_fixtures_are_explicit_and_still_checked():
    marked = {t.id for t in TRACES if "known_defect" in t.expect}
    assert marked == KNOWN_DEFECT_IDS
    # marking never loosens the oracle: every marked fixture also matches in full
    assert _mismatching(Rules()) == set()


def test_sr008_is_indeterminate_not_retried():
    r = reduce_trace(BY_ID["SR-008"])
    assert r.indeterminate and r.target_writes == ()


def test_sr013_commit_failure_keeps_buffer_for_retry():
    r = reduce_trace(BY_ID["SR-013"])
    assert r.staged_chunks == ("recoverable",) and not r.indeterminate
    assert r.phase == "staged_pending"


# ------------------------------------------------ rules not covered by fixtures


def _mk(events, *, activation="hold", staged=False, streaming=True):
    return parse_trace(
        {
            "id": "X",
            "description": "d",
            "mode": {"activation": activation, "staged": staged, "streaming": streaming},
            "events": events,
            "expect": {
                "target_writes": [],
                "staged_chunks": [],
                "finalizations": 0,
                "no_pre_release_writes": True,
                "no_forbidden_deletions": True,
            },
        }
    )


START = {"t_ms": 0, "kind": "hold_start"}


def test_final_before_release_is_never_counted():
    r = reduce_trace(_mk([START, {"t_ms": 5, "kind": "final_decode", "text": "early"}]))
    assert r.finalizations == 0 and r.target_writes == ()


def test_handsfree_stop_cannot_end_a_physical_hold_and_vice_versa():
    stop = {"t_ms": 5, "kind": "handsfree_stop"}
    rel = {"t_ms": 5, "kind": "hold_release"}
    fin = {"t_ms": 6, "kind": "final_decode", "text": "x"}
    assert reduce_trace(_mk([START, stop, fin])).finalizations == 0
    assert reduce_trace(_mk([START, rel, fin], activation="handsfree")).finalizations == 0


def test_duplicate_hold_start_is_rejected_without_state_change():
    def tgt(t, f):
        return {"t_ms": t, "kind": "target", "focus_id": f, "caret_version": 1, "editable": True}

    t = _mk(
        [
            tgt(0, "a"),
            {"t_ms": 1, "kind": "hold_start"},
            tgt(2, "b"),
            {"t_ms": 3, "kind": "hold_start"},  # must not re-snapshot the target
            {"t_ms": 4, "kind": "hold_release"},
            {"t_ms": 5, "kind": "final_decode", "text": "x"},
        ]
    )
    assert reduce_trace(t).target_writes == ()


def test_stage_discard_drops_buffer_without_writing():
    t = _mk(
        [
            START,
            {"t_ms": 1, "kind": "hold_release"},
            {"t_ms": 2, "kind": "final_decode", "text": "x"},
            {"t_ms": 3, "kind": "stage_discard"},
        ],
        staged=True,
    )
    r = reduce_trace(t)
    assert r.staged_chunks == () and r.target_writes == () and r.phase == "sealed"


def test_indeterminate_commit_is_not_silently_replayed():
    t = _mk(
        [
            START,
            {"t_ms": 1, "kind": "hold_release"},
            {"t_ms": 2, "kind": "final_decode", "text": "x"},
            {"t_ms": 3, "kind": "stage_commit"},
            {"t_ms": 4, "kind": "failure", "category": "inject_after_partial_effect"},
            {"t_ms": 5, "kind": "stage_commit"},
        ],
        staged=True,
    )
    r = reduce_trace(t)
    assert r.indeterminate and r.target_writes == ()


# ------------------------------------------------------------ mutation tests

# Each rule, flipped, must break at least these fixtures.
MUTATIONS = {
    "hypothesis_never_writes": {"SR-001"},
    "finalize_once": {"SR-009"},
    "gate_on_target": {"SR-006", "SR-015"},
    "late_partial_dropped": {"SR-005"},
    "staged_defers_write": {"SR-003", "SR-004", "SR-010"},
    "empty_final_writes_nothing": {"SR-007"},
    "failure_revokes_write": {"SR-008", "SR-013", "SR-014"},
    "never_delete": {"SR-003"},
}


def test_mutations_cover_every_rule():
    assert set(MUTATIONS) == {f.name for f in dataclasses.fields(Rules)}


@pytest.mark.parametrize("rule", sorted(MUTATIONS))
def test_flipping_a_rule_breaks_a_fixture(rule):
    broken = _mismatching(Rules(**{rule: False}))
    assert MUTATIONS[rule] <= broken, f"flipping {rule} did not break {MUTATIONS[rule]}: {broken}"


# ------------------------------------------------------- schema negatives

GOOD = json.loads(LINES[0])


def _bad(mutate):
    rec = json.loads(json.dumps(GOOD))
    mutate(rec)
    return rec


NEGATIVES = {
    "missing_id": lambda r: r.pop("id"),
    "missing_events": lambda r: r.pop("events"),
    "bad_activation": lambda r: r["mode"].update(activation="toggle"),
    "staged_not_bool": lambda r: r["mode"].update(staged=1),
    "empty_events": lambda r: r.update(events=[]),
    "unknown_kind": lambda r: r["events"][0].update(kind="teleport"),
    "float_time": lambda r: r["events"][0].update(t_ms=1.5),
    "bool_time": lambda r: r["events"][0].update(t_ms=True),
    "negative_time": lambda r: r["events"][0].update(t_ms=-1),
    "non_monotonic": lambda r: r["events"][1].update(t_ms=r["events"][2]["t_ms"] + 1),
    "hypothesis_without_text": lambda r: r["events"][1].pop("text"),
    "pause_without_duration": lambda r: r["events"][2].pop("duration_ms"),
    "failure_bad_category": lambda r: r["events"].append(
        {"t_ms": 99999, "kind": "failure", "category": "meltdown"}
    ),
    "target_missing_editable": lambda r: r["events"].insert(
        0, {"t_ms": 0, "kind": "target", "focus_id": "a", "caret_version": 1}
    ),
    "expect_missing_key": lambda r: r["expect"].pop("finalizations"),
    "expect_unknown_key": lambda r: r["expect"].update(surprise=1),
    "expect_writes_not_list": lambda r: r["expect"].update(target_writes="x"),
    "expect_flag_not_bool": lambda r: r["expect"].update(no_pre_release_writes="yes"),
    "known_defect_empty": lambda r: r["expect"].update(known_defect=""),
}


@pytest.mark.parametrize("name", sorted(NEGATIVES))
def test_malformed_record_is_rejected(name):
    with pytest.raises(ReplayFormatError):
        parse_trace(_bad(NEGATIVES[name]))


def test_good_record_parses():
    assert parse_trace(GOOD).id == "SR-001"


def test_non_object_bad_json_and_duplicate_ids_rejected():
    with pytest.raises(ReplayFormatError):
        parse_trace([1, 2])
    with pytest.raises(ReplayFormatError):
        load_traces(["{not json"])
    with pytest.raises(ReplayFormatError, match="duplicate"):
        load_traces([LINES[0], "", LINES[0]])
