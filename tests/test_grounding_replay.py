"""The replay harness reports what actually happened, and refuses to report on nothing.

`src/yazses/grounding/replay.py` and `src/yazses/grounding/trace.py` are phase P4 of
ADR-v2-151: replay privacy-safe target/candidate/intent traces and report grounded
coverage, wrong target, ambiguity and abstention. The properties below are the ones an
evaluation harness gets wrong in ways that read as success, and this repository has
shipped each shape at least once:

1. **A guard that iterates is green on an empty collection.** A wrong-target rate of
   `0.0` over zero trials is character-identical to a flawless run, so a trace with no
   cases is a rule violation and `replay` refuses an empty case list outright. Tested
   from both ends.
2. **A check that cannot parse its input must fail loudly.** Unreadable or non-JSON input
   exits `2`; input that parses but breaks a rule exits `1`; only a clean run exits `0`.
   It never degrades into an empty report that reads as compliance.
3. **An "is it in sync?" test on a generated artifact cannot notice an omission.** The
   committed report is checked against its generator *and* for completeness by count and
   by case id, and `test_dropping_a_fixture_is_caught_by_count_and_by_id` drops a fixture
   and proves the completeness check — not the sync check — is what catches it.
4. **A characterization test freezes whatever the code does today.** Every expectation in
   `EXPECTED` below was derived from the resolver's documented rules and the fixture
   geometry before it was run, and the fixture guards in section 0 fail if a fixture stops
   being the case it claims to be.

Nothing here measures a product threshold, and nothing may: the fixtures are invented.
RQ-G4 in `design/eye-control/GROUNDED_INTERACTION_RESEARCH.md` measures the real curve.
"""

from __future__ import annotations

import ast
import importlib.util
import itertools
import json
from pathlib import Path
from typing import Any

import pytest

from yazses.grounding import (
    CoordinateSpace,
    GroundingEvidence,
    GroundingOutcome,
    Point,
    SemanticSourceKind,
    TargetSnapshot,
    TargetSource,
    UnresolvedReason,
)
from yazses.grounding.replay import (
    NO_THRESHOLD_NOTICE,
    REPORT_VERSION,
    ZERO_DENOMINATOR_RULE,
    Classification,
    GroundingReplayError,
    Strategy,
    replay,
    replay_case,
)
from yazses.grounding.resolver import ResolutionPolicy, TargetResolver
from yazses.grounding.trace import (
    TRACE_SCHEMA_VERSION,
    GroundingTraceError,
    TraceCase,
    check_trace,
    validate_trace,
)

ROOT = Path(__file__).resolve().parent.parent
TRACE_DIR = ROOT / "tests" / "fixtures" / "grounding_traces"
REPORT_PATH = ROOT / "tests" / "fixtures" / "grounding_replay_report.json"
SCRIPT = ROOT / "scripts" / "replay_grounding_trace.py"

#: The five shapes the issue requires a golden fixture for, and the file each lives in.
REQUIRED_SHAPES = {
    "one target": "one-target.json",
    "repeated labels": "repeated-labels.json",
    "ambiguous overlap": "ambiguous-overlap.json",
    "no candidate": "no-candidate.json",
    "off-region label match": "off-region-label-match.json",
}

#: Every case the fixtures declare. Written out rather than derived from the fixtures, so
#: that deleting a fixture file changes the report and *not* this list — which is the
#: whole point of a completeness check (see the module docstring, item 3).
EXPECTED_CASE_IDS = frozenset(
    {
        "ambiguous-overlap/point-in-the-overlap",
        "no-candidate/empty-tree",
        "no-candidate/low-confidence-target",
        "no-candidate/other-coordinate-space",
        "no-candidate/stale-target",
        "off-region-label-match/hint-cannot-reach-across-the-screen",
        "off-region-label-match/the-same-hint-inside-the-region-grounds",
        "one-target/coarse-region",
        "one-target/precise-point",
        "repeated-labels/hint-cannot-separate-identical-rows",
        "repeated-labels/region-over-two-rows",
    }
)

#: `case_id -> (window_only classification, semantic_grounding classification)`.
#:
#: Derived from the resolver's documented rules and the fixture geometry, not from a run.
#: For each: window-only sees the `window`-source candidate alone and no hint, semantic
#: grounding sees everything. A `null` ground truth means abstention is correct, so any
#: grounding under it is a wrong target.
EXPECTED: dict[str, tuple[str, str]] = {
    # The button outranks the window on source reliability; window-only has only the
    # window, which is not the control the user meant.
    "one-target/precise-point": ("grounded_wrong", "grounded_correct"),
    "one-target/coarse-region": ("grounded_wrong", "grounded_correct"),
    # Two identical rows intersect the region; nothing separates them, with or without
    # the user's own words.
    "repeated-labels/region-over-two-rows": ("grounded_wrong", "ambiguous"),
    "repeated-labels/hint-cannot-separate-identical-rows": ("grounded_wrong", "ambiguous"),
    # Same area, same distance, same source: abstention is the right answer, so the
    # window-only ground counts as a wrong target under the stated rule.
    "ambiguous-overlap/point-in-the-overlap": ("grounded_wrong", "ambiguous"),
    # Nothing to ground onto, four different ways.
    "no-candidate/empty-tree": ("unresolved", "unresolved"),
    "no-candidate/stale-target": ("unresolved", "unresolved"),
    "no-candidate/low-confidence-target": ("unresolved", "unresolved"),
    "no-candidate/other-coordinate-space": ("unresolved", "unresolved"),
    # The criterion the layer exists for: a hint may not reach across the screen.
    "off-region-label-match/hint-cannot-reach-across-the-screen": (
        "grounded_wrong",
        "unresolved",
    ),
    "off-region-label-match/the-same-hint-inside-the-region-grounds": (
        "grounded_wrong",
        "grounded_correct",
    ),
}

SPACE = CoordinateSpace("screen", 1)
T0 = 1000.0


def _load_script() -> Any:
    spec = importlib.util.spec_from_file_location("replay_grounding_trace", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = _load_script()


def _trace_files() -> list[Path]:
    files = sorted(TRACE_DIR.glob("*.json"))
    assert len(files) == len(REQUIRED_SHAPES), (
        f"expected {len(REQUIRED_SHAPES)} trace fixtures in {TRACE_DIR}, found "
        f"{[path.name for path in files]} -- a guard that globs an empty directory is "
        f"green for the wrong reason"
    )
    return files


def _documents() -> dict[str, Any]:
    return {
        path.name: json.loads(path.read_text(encoding="utf-8")) for path in _trace_files()
    }


def _all_cases() -> list[TraceCase]:
    cases: list[TraceCase] = []
    for document in _documents().values():
        cases.extend(check_trace(document).cases)
    return cases


def _golden() -> Any:
    return json.loads(REPORT_PATH.read_text(encoding="utf-8"))


def _omissions(document: Any, expected_ids: frozenset[str]) -> list[str]:
    """Every fixture case the report fails to account for, by count and by id.

    Separate from the sync check on purpose. A sync check compares a file to its
    generator and is perfectly happy when both lose the same case; only a list of the ids
    that *should* be there notices an omission.
    """
    problems: list[str] = []
    rows = document.get("cases", [])
    seen = {row["case_id"] for row in rows}
    if document.get("total_trials") != len(expected_ids):
        problems.append(
            f"total_trials is {document.get('total_trials')}, expected {len(expected_ids)}"
        )
    if len(rows) != len(expected_ids):
        problems.append(f"{len(rows)} case rows, expected {len(expected_ids)}")
    for strategy, body in sorted(document.get("strategies", {}).items()):
        if body["counts"]["total_trials"] != len(expected_ids):
            problems.append(
                f"{strategy}: counted {body['counts']['total_trials']} trials, "
                f"expected {len(expected_ids)}"
            )
    problems += [f"missing case {case_id}" for case_id in sorted(expected_ids - seen)]
    problems += [f"unexpected case {case_id}" for case_id in sorted(seen - expected_ids)]
    return problems


# --------------------------------------------------------------------------- #
# 0. Guard the fixtures. A fixture that stopped being the case it claims makes
#    every expectation below pass for the wrong reason.
# --------------------------------------------------------------------------- #
def test_every_required_fixture_shape_exists() -> None:
    names = {path.name for path in _trace_files()}
    assert names == set(REQUIRED_SHAPES.values()), names


def test_the_fixtures_declare_exactly_the_expected_cases() -> None:
    ids = {case.case_id for case in _all_cases()}
    assert ids == EXPECTED_CASE_IDS
    assert set(EXPECTED) == EXPECTED_CASE_IDS


def test_the_one_target_fixture_really_holds_one_reachable_control() -> None:
    cases = {case.case_id: case for case in _all_cases()}
    case = cases["one-target/precise-point"]
    leaves = [c for c in case.candidates if c.source is not SemanticSourceKind.WINDOW]
    assert len(leaves) == 1
    assert leaves[0].bounds is not None and case.target.point is not None
    assert leaves[0].bounds.contains(case.target.point), "the point misses the control"


def test_the_repeated_label_fixture_really_repeats_a_label() -> None:
    cases = {case.case_id: case for case in _all_cases()}
    for case_id in (
        "repeated-labels/region-over-two-rows",
        "repeated-labels/hint-cannot-separate-identical-rows",
    ):
        case = cases[case_id]
        labels = [c.label for c in case.candidates if c.role == "listitem"]
        assert len(labels) == 4 and len(set(labels)) == 1, labels
        target = case.target.bounds
        assert target is not None
        touching = [
            c
            for c in case.candidates
            if c.role == "listitem" and c.bounds is not None and c.bounds.intersects(target)
        ]
        assert len(touching) == 2, "the region must reach exactly two identical rows"


def test_the_overlap_fixture_really_overlaps_and_the_pair_is_indistinguishable() -> None:
    case = next(
        c for c in _all_cases() if c.case_id == "ambiguous-overlap/point-in-the-overlap"
    )
    buttons = [c for c in case.candidates if c.role == "button"]
    assert len(buttons) == 2
    first, second = (c.bounds for c in buttons)
    assert first is not None and second is not None
    assert first.intersects(second), "the two buttons do not overlap"
    assert first.width * first.height == second.width * second.height
    assert case.target.point is not None
    assert first.contains(case.target.point) and second.contains(case.target.point)
    # Different confidences, deliberately: the resolver may not separate them on one.
    assert len({c.confidence for c in buttons}) == 2
    assert case.expected_entity_id is None


def test_the_no_candidate_fixture_really_has_an_empty_tree() -> None:
    case = next(c for c in _all_cases() if c.case_id == "no-candidate/empty-tree")
    assert case.candidates == ()
    assert all(
        c.expected_entity_id is None
        for c in _all_cases()
        if c.trace_id == "no-candidate"
    )


def test_the_off_region_fixture_puts_the_named_label_outside_the_envelope() -> None:
    case = next(
        c
        for c in _all_cases()
        if c.case_id == "off-region-label-match/hint-cannot-reach-across-the-screen"
    )
    assert case.hint is not None and case.hint.label_tokens == ("save",)
    named = case.candidate_by_id("save-button")
    assert named is not None and named.bounds is not None
    assert case.target.point is not None
    assert not named.bounds.contains(case.target.point), "the Save is under the target"
    # And something else *is* under the target, so the case is about reach, not emptiness.
    under = [
        c
        for c in case.candidates
        if c.bounds is not None and c.bounds.contains(case.target.point)
    ]
    assert len(under) == 2, [c.entity_id for c in under]


# --------------------------------------------------------------------------- #
# 1. The classifications, derived rather than recorded
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("case_id", sorted(EXPECTED))
def test_each_case_classifies_as_the_rules_say_it_must(case_id: str) -> None:
    report = replay(_all_cases())
    document = report.to_document()
    row = next(item for item in document["cases"] if item["case_id"] == case_id)
    window_only, semantic = EXPECTED[case_id]
    assert row["window_only"]["classification"] == window_only, row["window_only"]
    assert row["semantic_grounding"]["classification"] == semantic, (
        row["semantic_grounding"]
    )


def test_semantic_grounding_never_grounds_the_wrong_element_on_these_fixtures() -> None:
    """The number worth having, and the one the ADR says abstention buys.

    It describes five invented layouts and licences no threshold.
    """
    semantic = replay(_all_cases()).strategy(Strategy.SEMANTIC_GROUNDING).to_document()
    assert semantic["counts"]["grounded_wrong"] == 0, semantic["counts"]
    assert semantic["rates"]["wrong_target_rate"] == 0.0


def test_the_two_strategies_differ_in_the_direction_the_layer_claims() -> None:
    report = replay(_all_cases())
    window_only = report.strategy(Strategy.WINDOW_ONLY).to_document()
    semantic = report.strategy(Strategy.SEMANTIC_GROUNDING).to_document()

    assert window_only["counts"]["grounded_correct"] == 0
    assert semantic["counts"]["grounded_correct"] == 3
    # Window-only's wrongs are all coarse window grounds, not misclicks on a sibling
    # control -- which is the distinction that makes the comparison readable.
    assert window_only["counts"]["grounded_wrong_by_source"] == {"window": 7}
    assert semantic["counts"]["grounded_wrong_by_source"] == {}
    # And it never abstains where semantics does: it has nothing to be unsure between.
    assert window_only["counts"]["ambiguous"] == 0
    assert semantic["counts"]["ambiguous"] == 3


def test_the_abstention_split_names_who_owns_each_failure() -> None:
    """P4 reports target-source failure and semantic-source failure separately: one is a
    sensor/calibration problem and the other is platform coverage (#444)."""
    semantic = replay(_all_cases()).strategy(Strategy.SEMANTIC_GROUNDING).to_document()
    sources = semantic["abstention_sources"]
    assert sources["target_source_failure"] == 2
    assert sources["semantic_source_failure"] == 3
    assert sources["target_source_failure"] + sources["semantic_source_failure"] == (
        semantic["counts"]["unresolved"]
    )
    assert sources["by_reason"] == {
        "semantic_no_candidates": 1,
        "semantic_no_plausible_candidate": 1,
        "semantic_space_mismatch": 1,
        "target_confidence_below_floor": 1,
        "target_stale": 1,
    }


def test_the_candidate_count_distribution_reports_before_and_after_the_hint() -> None:
    report = replay(_all_cases())
    semantic = report.strategy(Strategy.SEMANTIC_GROUNDING).to_document()
    counts = semantic["candidate_counts"]
    assert counts["cases_with_hint"] == 3
    assert counts["before_hint"] == {"0": 4, "2": 4, "3": 3}
    assert sum(counts["before_hint"].values()) == semantic["counts"]["total_trials"]
    # The hint only ever removes: three hinted cases go 3->2, 2->0 and 2->1.
    assert counts["after_hint"] == {"0": 1, "1": 1, "2": 1}

    window_only = report.strategy(Strategy.WINDOW_ONLY).to_document()
    assert window_only["candidate_counts"]["after_hint"] == {
        "value": None,
        "reason": "not_supported",
    }


# --------------------------------------------------------------------------- #
# 2. Anti-trap: an empty collection is not a clean run
# --------------------------------------------------------------------------- #
def test_replaying_zero_cases_raises_rather_than_reporting_a_perfect_run() -> None:
    with pytest.raises(GroundingReplayError) as excinfo:
        replay([])
    assert "zero trials" in str(excinfo.value)


def test_a_trace_with_no_cases_is_a_rule_violation() -> None:
    problems = validate_trace(
        {
            "schema_version": TRACE_SCHEMA_VERSION,
            "trace_id": "empty",
            "study_mode": "synthetic",
            "space": {"name": "screen", "version": 1},
            "cases": [],
        }
    )
    assert any("at least one case" in problem for problem in problems), problems


def test_the_cli_exits_one_on_a_trace_with_no_cases(tmp_path: Path) -> None:
    path = tmp_path / "empty.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": TRACE_SCHEMA_VERSION,
                "trace_id": "empty",
                "study_mode": "synthetic",
                "space": {"name": "screen", "version": 1},
                "cases": [],
            }
        ),
        encoding="utf-8",
    )
    assert script.main(["--trace", str(path)]) == 1


def test_the_cli_exits_one_when_it_finds_no_trace_files_at_all(tmp_path: Path) -> None:
    """A directory that lost its fixtures is the state a rename produces, and it is
    exactly when the harness is most needed."""
    assert script.main(["--trace-dir", str(tmp_path)]) == 1


def test_duplicate_case_ids_across_traces_are_refused() -> None:
    """Two cases with one id silently replace each other in the per-case rows, which
    would make the completeness check pass while a trial went missing."""
    cases = _all_cases()
    with pytest.raises(GroundingReplayError) as excinfo:
        replay([*cases, cases[0]])
    assert "unique" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# 3. Anti-trap: input it cannot parse must fail loudly, never return {}
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "payload",
    ["", "not json at all", "{", '{"schema_version": "1.0",}', "\x00\x01"],
)
def test_the_cli_exits_two_on_input_it_cannot_parse(tmp_path: Path, payload: str) -> None:
    path = tmp_path / "broken.json"
    path.write_text(payload, encoding="utf-8")
    assert script.main(["--trace", str(path)]) == 2


def test_the_cli_exits_two_when_the_trace_file_is_absent(tmp_path: Path) -> None:
    assert script.main(["--trace", str(tmp_path / "absent.json")]) == 2


@pytest.mark.parametrize(
    "mutate,needle",
    [
        ({"schema_version": "9.0"}, "major version 9"),
        ({"schema_version": "one"}, "malformed"),
        ({"study_mode": "research"}, "not one of"),
        ({"space": None}, "missing required field"),
        ({"trace_id": ""}, "non-empty string"),
    ],
)
def test_a_trace_that_parses_but_breaks_a_rule_exits_one(
    tmp_path: Path, mutate: dict[str, Any], needle: str
) -> None:
    document = _documents()["one-target.json"]
    document.update(mutate)
    if mutate.get("space", "keep") is None:
        document.pop("space")
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert script.main(["--trace", str(path)]) == 1
    assert any(needle in problem for problem in validate_trace(document))


def test_a_valid_trace_exits_zero(tmp_path: Path) -> None:
    """The permissive direction. A validator nothing can satisfy reads as a policy
    decision, and only the failing direction is usually tested."""
    assert script.main([]) == 0


def test_an_expected_entity_that_names_no_candidate_is_refused() -> None:
    document = _documents()["one-target.json"]
    document["cases"][0]["expected_entity_id"] = "not-in-this-case"
    problems = validate_trace(document)
    assert any("names no candidate" in problem for problem in problems), problems


def test_a_missing_ground_truth_key_is_refused_rather_than_read_as_null() -> None:
    document = _documents()["one-target.json"]
    document["cases"][0].pop("expected_entity_id")
    problems = validate_trace(document)
    assert any("expected_entity_id" in problem for problem in problems), problems


def test_a_malformed_value_becomes_a_problem_not_a_traceback() -> None:
    """The contracts raise on a confidence outside [0, 1]. A harness that let that
    escape would exit on a traceback, which is not one of the three documented codes."""
    document = _documents()["one-target.json"]
    document["cases"][0]["target"]["confidence"] = 4.2
    problems = validate_trace(document)
    assert problems and any("0.0, 1.0" in problem for problem in problems), problems
    with pytest.raises(GroundingTraceError):
        check_trace(document)


# --------------------------------------------------------------------------- #
# 4. Anti-trap: a sync check cannot notice an omission
# --------------------------------------------------------------------------- #
def test_the_committed_report_matches_its_generator() -> None:
    assert script.main(["--check", str(REPORT_PATH)]) == 0


def test_the_committed_report_accounts_for_every_fixture_case() -> None:
    assert _omissions(_golden(), EXPECTED_CASE_IDS) == []


def test_dropping_a_fixture_is_caught_by_count_and_by_id() -> None:
    """The proof that the completeness check earns its place.

    Regenerating from four of the five fixtures produces a report that is perfectly in
    sync with its generator -- `--check` against it would pass -- and is missing two
    trials. Only the id list notices.
    """
    kept = [
        path for path in _trace_files() if path.name != REQUIRED_SHAPES["repeated labels"]
    ]
    assert len(kept) == 4
    cases: list[TraceCase] = []
    for path in kept:
        cases.extend(check_trace(json.loads(path.read_text(encoding="utf-8"))).cases)
    shrunk = replay(cases).to_document()

    # The report is internally consistent: every count agrees with every other.
    assert shrunk["total_trials"] == len(shrunk["cases"]) == 9
    for body in shrunk["strategies"].values():
        assert body["counts"]["total_trials"] == 9

    problems = _omissions(shrunk, EXPECTED_CASE_IDS)
    assert problems == [
        "total_trials is 9, expected 11",
        "9 case rows, expected 11",
        "semantic_grounding: counted 9 trials, expected 11",
        "window_only: counted 9 trials, expected 11",
        "missing case repeated-labels/hint-cannot-separate-identical-rows",
        "missing case repeated-labels/region-over-two-rows",
    ], problems


def test_an_added_case_is_caught_too() -> None:
    document = _golden()
    document["cases"].append({"case_id": "invented/case"})
    assert "unexpected case invented/case" in _omissions(document, EXPECTED_CASE_IDS)


# --------------------------------------------------------------------------- #
# 5. Zero denominators: missing is never zero
# --------------------------------------------------------------------------- #
def _lone_case(**kw: Any) -> TraceCase:
    base: dict[str, Any] = dict(
        case_id="synthetic/one",
        trace_id="synthetic",
        now_s=T0,
        target=TargetSnapshot(
            source=TargetSource.MOUSE,
            timestamp_s=T0,
            confidence=0.9,
            space=SPACE,
            point=Point(10.0, 10.0),
        ),
        candidates=(),
        hint=None,
        expected_entity_id=None,
    )
    base.update(kw)
    return TraceCase(**base)


def test_a_rate_with_a_zero_denominator_is_missing_not_zero() -> None:
    """`grounded_correct_share_of_grounded` has no meaning when nothing grounded. A
    `0.0` there would read as "everything it grounded was wrong"."""
    report = replay([_lone_case()]).strategy(Strategy.SEMANTIC_GROUNDING).to_document()
    assert report["counts"]["total_trials"] == 1
    assert report["rates"]["grounded_correct_share_of_grounded"] == {
        "value": None,
        "reason": "not_measured",
    }
    # The two rates the issue names are always real numbers, because total_trials >= 1.
    assert report["rates"]["wrong_target_rate"] == 0.0
    assert report["rates"]["abstention_rate"] == 1.0


def test_an_unhinted_trace_reports_the_after_hint_distribution_as_missing() -> None:
    report = replay([_lone_case()]).strategy(Strategy.SEMANTIC_GROUNDING).to_document()
    assert report["candidate_counts"]["cases_with_hint"] == 0
    assert report["candidate_counts"]["after_hint"] == {
        "value": None,
        "reason": "not_measured",
    }


def test_the_missing_marker_is_distinguishable_from_a_real_zero() -> None:
    """Guard the guard above: a real zero must not be written as a marker."""
    full = replay(_all_cases()).strategy(Strategy.SEMANTIC_GROUNDING).to_document()
    assert full["rates"]["wrong_target_rate"] == 0.0
    assert not isinstance(full["rates"]["wrong_target_rate"], dict)
    assert full["rates"]["grounded_correct_share_of_grounded"] == 1.0


# --------------------------------------------------------------------------- #
# 6. Determinism, and order-independence of the trace itself
# --------------------------------------------------------------------------- #
def test_the_report_is_byte_identical_across_runs() -> None:
    first = script.render(replay(_all_cases()).to_document())
    second = script.render(replay(_all_cases()).to_document())
    assert first == second


def test_trace_file_order_does_not_change_any_aggregate() -> None:
    cases = _all_cases()
    baseline = replay(cases).to_document()
    for order in itertools.islice(itertools.permutations(range(len(cases))), 6):
        shuffled = replay([cases[index] for index in order]).to_document()
        assert shuffled == baseline


def test_candidate_order_inside_a_case_does_not_change_a_classification() -> None:
    case = next(
        c for c in _all_cases() if c.case_id == "one-target/precise-point"
    )
    resolver = TargetResolver()
    baseline = replay_case(
        case, strategy=Strategy.SEMANTIC_GROUNDING, resolver=resolver
    )
    for order in itertools.permutations(case.candidates):
        variant = replay_case(
            TraceCase(
                case_id=case.case_id,
                trace_id=case.trace_id,
                now_s=case.now_s,
                target=case.target,
                candidates=order,
                hint=case.hint,
                expected_entity_id=case.expected_entity_id,
            ),
            strategy=Strategy.SEMANTIC_GROUNDING,
            resolver=resolver,
        )
        assert variant.to_document() == baseline.to_document()


def test_the_policy_travels_with_the_numbers() -> None:
    """Every threshold that produced the report is in the report, so a policy change
    shows up as a diff rather than as an unexplained number moving."""
    document = _golden()
    assert document["policy"] == {
        "envelope_expansion_px": 0.0,
        "max_candidate_skew_s": 0.5,
        "max_target_age_s": 0.5,
        "min_candidate_confidence": 0.0,
        "min_target_confidence": 0.5,
        "tie_area_ratio": 0.8,
        "tie_distance_px": 4.0,
    }
    assert document["policy"] == {
        item: getattr(ResolutionPolicy(), item) for item in document["policy"]
    }


def test_a_different_policy_produces_a_different_report() -> None:
    """Otherwise the policy block would be decoration: it must actually be in force."""
    strict = ResolutionPolicy(min_target_confidence=0.95)
    baseline = replay(_all_cases()).to_document()
    changed = replay(_all_cases(), policy=strict).to_document()
    assert changed != baseline
    assert changed["strategies"]["semantic_grounding"]["abstention_sources"][
        "target_source_failure"
    ] > baseline["strategies"]["semantic_grounding"]["abstention_sources"][
        "target_source_failure"
    ]


# --------------------------------------------------------------------------- #
# 7. Privacy: a report cannot carry what the user could see on screen
# --------------------------------------------------------------------------- #
def _strings(node: Any) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [item for value in node.values() for item in _strings(value)]
    if isinstance(node, list):
        return [item for value in node for item in _strings(value)]
    return []


def test_no_visible_label_reaches_the_report() -> None:
    labels = {
        candidate.label
        for case in _all_cases()
        for candidate in case.candidates
        if candidate.label
    }
    assert len(labels) >= 8, labels
    text = REPORT_PATH.read_text(encoding="utf-8")
    for label in labels:
        assert label not in text, f"the visible label {label!r} leaked into the report"


def test_every_string_in_the_report_comes_from_a_closed_vocabulary() -> None:
    """Stronger than a leak search: nothing may appear that is not an enum member, an id
    the trace already declared synthetic, or one of the two fixed notices."""
    cases = _all_cases()
    permitted = (
        {member.value for member in Classification}
        | {member.value for member in GroundingOutcome}
        | {member.value for member in SemanticSourceKind}
        | {member.value for member in UnresolvedReason}
        | {member.value for member in GroundingEvidence}
        | {case.case_id for case in cases}
        | {case.trace_id for case in cases}
        | {c.entity_id for case in cases for c in case.candidates}
        | {"not_measured", "not_supported", REPORT_VERSION}
        | {NO_THRESHOLD_NOTICE, ZERO_DENOMINATOR_RULE}
    )
    unexpected = sorted(set(_strings(_golden())) - permitted)
    assert unexpected == [], unexpected


def test_a_trace_that_invents_a_forbidden_field_is_refused() -> None:
    for key in ("screenshot", "raw_frame", "window_title", "transcript"):
        document = _documents()["one-target.json"]
        document["cases"][0][key] = "anything"
        problems = validate_trace(document)
        assert any("forbidden field" in problem for problem in problems), (key, problems)


def test_the_forbidden_field_scan_reaches_every_depth() -> None:
    """Guard the guard: a scan that only looked at the top level would pass the test
    above by accident, because the key is one level down."""
    document = _documents()["one-target.json"]
    document["cases"][0]["target"]["face_image"] = {"nested": {"screenshot": 1}}
    problems = [p for p in validate_trace(document) if "forbidden field" in p]
    assert len(problems) == 2, problems


# --------------------------------------------------------------------------- #
# 8. Purity. Both new modules are ones CI can fully exercise; keep it that way.
# --------------------------------------------------------------------------- #
MODULES = (
    ROOT / "src" / "yazses" / "grounding" / "replay.py",
    ROOT / "src" / "yazses" / "grounding" / "trace.py",
)

#: Names that would make a replay non-reproducible or reach off the machine.
FORBIDDEN_NAMES = {
    "time", "monotonic", "perf_counter", "random", "urlopen", "requests", "socket",
    "subprocess", "open", "datetime",
}


def test_the_purity_scan_reads_both_modules() -> None:
    for path in MODULES:
        assert path.exists() and path.read_text(encoding="utf-8").strip()
    assert len(MODULES) == 2


def test_neither_module_names_a_clock_a_file_or_a_network_call() -> None:
    for path in MODULES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {
            node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
        } | {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        assert not (names & FORBIDDEN_NAMES), (path.name, sorted(names & FORBIDDEN_NAMES))


def test_the_purity_scan_would_notice_a_clock() -> None:
    """The scan above is green on any module that does not call one, including a module
    that does nothing. Prove it fires."""
    tree = ast.parse("import time\ndef f():\n    return time.monotonic()\n")
    names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)} | {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    }
    assert names & FORBIDDEN_NAMES == {"time", "monotonic"}


def test_the_harness_imports_only_stdlib_and_this_package() -> None:
    for path in MODULES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                roots.add(node.module.split(".")[0])
        assert roots <= {
            "collections", "dataclasses", "enum", "math", "typing", "yazses", "__future__"
        }, (path.name, sorted(roots))


def test_the_daemon_facing_package_does_not_import_the_harness() -> None:
    """`yazses.grounding` is on the runtime path once #443 wires it. The harness pulls in
    `yazses.eyeeval` for the one forbidden-field list it refuses to copy, so it stays out
    of the package's own imports and is reached by module path instead."""
    source = (ROOT / "src" / "yazses" / "grounding" / "__init__.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    } - {"__future__"}
    assert "yazses.grounding.replay" not in imported
    assert "yazses.grounding.trace" not in imported
    assert imported == {"yazses.grounding.contracts", "yazses.grounding.resolver"}


def test_the_resolver_is_the_only_thing_that_decides_an_outcome() -> None:
    """The harness must not re-implement ranking. It may filter what a strategy sees; it
    may not compute a winner, so no comparison operator may touch a candidate score."""
    source = (ROOT / "src" / "yazses" / "grounding" / "replay.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert {"resolve", "score"} <= called
    assert "preference" not in source and "separable_tier" not in source
