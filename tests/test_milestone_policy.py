"""The milestone policy (#480) classifies every open issue and reports every violation.

Offline throughout: the inputs are synthetic fixtures under
``tests/fixtures/milestone_policy/`` or issues built inline, never a live GitHub snapshot.
"""
from __future__ import annotations

import importlib.util
import itertools
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "milestone_policy.py"
CHECKER = ROOT / "scripts" / "check-traceability.py"
POLICY_DOC = ROOT / "design" / "milestone-policy.md"
FIXTURES = ROOT / "tests" / "fixtures" / "milestone_policy"


def _load():
    name = "milestone_policy_under_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


mp = _load()


def _issue(number, labels=(), milestone=None, parent=None):
    return mp.Issue(
        number=number,
        title=f"synthetic {number}",
        labels=frozenset(labels),
        milestone=milestone,
        parent=parent,
    )


def _rules(report, number=None):
    return sorted(v.rule for v in report.violations if number is None or v.issue == number)


def _fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- classification


def test_an_unlabelled_issue_is_delivery_and_owes_a_milestone():
    report = mp.evaluate([_issue(1)])
    assert report.classes[1] == mp.DELIVERY
    assert _rules(report) == ["DELIVERY_WITHOUT_MILESTONE"]
    assert mp.evaluate([_issue(1, milestone=4)]).violations == []


@pytest.mark.parametrize("topic", ["research", "measurement-wanted", "documentation", "question"])
def test_a_topic_label_never_exempts_an_issue(topic):
    # Exemption is structured metadata (an evergreen:* label), never a topical label: adding
    # `research` to a bug must not quietly take it out of a milestone.
    report = mp.evaluate([_issue(1, labels=[topic])])
    assert report.classes[1] == mp.DELIVERY
    assert _rules(report) == ["DELIVERY_WITHOUT_MILESTONE"]


@pytest.mark.parametrize("cls", sorted(mp.EVERGREEN_CLASSES))
def test_each_evergreen_class_carries_no_milestone(cls):
    label = f"evergreen:{cls}"
    assert mp.evaluate([_issue(1, labels=[label])]).violations == []
    report = mp.evaluate([_issue(1, labels=[label], milestone=9)])
    assert report.classes[1] == label
    assert _rules(report) == ["EVERGREEN_WITH_MILESTONE"]


def test_an_unknown_evergreen_class_is_a_violation_not_an_exemption():
    report = mp.evaluate([_issue(1, labels=["evergreen:someday"])])
    assert report.classes[1] == mp.INVALID
    assert _rules(report) == ["UNKNOWN_EVERGREEN_CLASS"]


@pytest.mark.parametrize(
    "labels",
    [["epic", "evergreen:research"], ["evergreen:research", "evergreen:community"]],
)
def test_two_class_labels_conflict(labels):
    report = mp.evaluate([_issue(1, labels=labels)])
    assert report.classes[1] == mp.INVALID
    assert _rules(report) == ["CONFLICTING_CLASSES"]


def test_no_issue_can_fall_through_both_categories():
    """#480 acceptance 4, exhaustively over a small label universe.

    Every combination of class and topic labels, with and without a milestone, lands in
    exactly one class, and is either compliant or reported. A delivery issue with no
    milestone is always reported, and an exempt one is exempt only by a class label.
    """
    universe = ["epic", "research", "bug", *(f"evergreen:{c}" for c in mp.EVERGREEN_CLASSES)]
    universe.append("evergreen:bogus")
    allowed = {mp.DELIVERY, mp.EPIC, mp.INVALID} | {
        f"evergreen:{c}" for c in mp.EVERGREEN_CLASSES
    }
    for size in range(len(universe) + 1):
        for labels in itertools.combinations(universe, size):
            for milestone in (None, 1):
                report = mp.evaluate([_issue(1, labels=labels, milestone=milestone)])
                cls = report.classes[1]
                assert cls in allowed, (labels, milestone)
                exempt = cls == mp.EPIC or cls.startswith("evergreen:")
                if milestone is None and not exempt:
                    assert report.violations, (labels, milestone)
                if cls.startswith("evergreen:") and milestone is not None:
                    assert "EVERGREEN_WITH_MILESTONE" in _rules(report)
                if exempt:
                    assert set(labels) & ({"epic"} | {f"evergreen:{c}" for c in mp.EVERGREEN_CLASSES})


# ---------------------------------------------------------------- epics


def test_an_epic_whose_children_span_outcomes_carries_no_milestone():
    # The Android shape: sub-issues in several milestones.
    children = [_issue(n, milestone=m, parent=100) for n, m in [(1, 1), (2, 2), (3, 3)]]
    assert mp.evaluate([_issue(100, labels=["epic"]), *children]).violations == []

    report = mp.evaluate([_issue(100, labels=["epic"], milestone=1), *children])
    assert _rules(report) == ["EPIC_SPANS_MILESTONES"]
    message = report.violations[0].message
    assert "#2" in message and "#3" in message and "#1 " not in message


def test_an_epic_whose_children_share_one_outcome_carries_it():
    children = [_issue(n, milestone=9, parent=100) for n in (1, 2)]
    assert mp.evaluate([_issue(100, labels=["epic"], milestone=9), *children]).violations == []
    report = mp.evaluate([_issue(100, labels=["epic"]), *children])
    assert _rules(report) == ["EPIC_MILESTONE_MISSING"]


def test_evergreen_children_do_not_decide_an_epics_milestone():
    kids = [
        _issue(1, milestone=9, parent=100),
        _issue(2, labels=["evergreen:field-report"], parent=100),
    ]
    assert mp.evaluate([_issue(100, labels=["epic"], milestone=9), *kids]).violations == []


def test_an_unmilestoned_delivery_child_is_reported_once_not_twice():
    kids = [_issue(1, milestone=9, parent=100), _issue(2, parent=100)]
    report = mp.evaluate([_issue(100, labels=["epic"], milestone=9), *kids])
    assert [(v.rule, v.issue) for v in report.violations] == [("DELIVERY_WITHOUT_MILESTONE", 2)]


def test_an_epic_without_known_children_is_unverified_never_passed():
    report = mp.evaluate([_issue(100, labels=["epic"]), _issue(1, milestone=2)])
    assert report.violations == []
    assert report.unverified_epics == [100]
    assert not report.has_parent_links
    text = mp.render(report)
    assert "unverified epic(s) #100" in text
    assert "no parent links" in text


def test_a_parent_outside_the_snapshot_is_ignored():
    # A closed parent is absent from an open-issue snapshot; the child is judged on its own.
    assert mp.evaluate([_issue(1, milestone=3, parent=999)]).violations == []


# ---------------------------------------------------------------- milestone listing


def test_closed_and_unknown_milestones_are_reported_only_with_a_listing():
    issues = [_issue(1, milestone=3), _issue(2, milestone=99)]
    assert mp.evaluate(issues).violations == []
    listing = mp.parse_milestones(_fixture("milestones.json"))
    report = mp.evaluate(issues, listing)
    assert [(v.rule, v.issue) for v in report.violations] == [
        ("MILESTONE_CLOSED", 1),
        ("MILESTONE_UNKNOWN", 2),
    ]
    assert "not checked" in mp.render(mp.evaluate(issues))


# ---------------------------------------------------------------- fixtures


def test_the_compliant_fixture_has_no_violation():
    report = mp.evaluate(
        mp.parse_issues(_fixture("compliant_issues.json")),
        mp.parse_milestones(_fixture("milestones.json")),
    )
    assert report.violations == []
    assert report.unverified_epics == []
    assert report.counts() == {
        "delivery": 4,
        "epic": 2,
        "evergreen:community": 1,
        "evergreen:field-report": 1,
        "evergreen:research": 1,
        "evergreen:translation": 1,
    }


def test_the_violating_fixture_reports_every_rule():
    report = mp.evaluate(
        mp.parse_issues(_fixture("violating_issues.json")),
        mp.parse_milestones(_fixture("milestones.json")),
    )
    assert [(v.issue, v.rule) for v in report.violations] == [
        (11, "DELIVERY_WITHOUT_MILESTONE"),
        (12, "EVERGREEN_WITH_MILESTONE"),
        (13, "UNKNOWN_EVERGREEN_CLASS"),
        (14, "CONFLICTING_CLASSES"),
        (15, "EPIC_SPANS_MILESTONES"),
        (18, "EPIC_MILESTONE_MISSING"),
        (20, "MILESTONE_CLOSED"),
        (21, "MILESTONE_UNKNOWN"),
    ]
    assert {v.rule for v in report.violations} == set(mp.RULES)


# ---------------------------------------------------------------- parsing


def test_rest_payload_shape_skips_pull_requests_and_closed_issues():
    rest = [
        {"number": 1, "state": "open", "title": "a", "labels": [{"name": "bug"}],
         "milestone": {"number": 2, "title": "B", "state": "open"}},
        {"number": 2, "state": "open", "title": "a PR", "labels": [], "milestone": None,
         "pull_request": {"url": "x"}},
        {"number": 3, "state": "closed", "title": "done", "labels": [], "milestone": None},
        {"number": 4, "state": "OPEN", "title": "gh casing", "labels": ["epic"], "milestone": None},
    ]
    issues = mp.parse_issues(rest)
    assert [i.number for i in issues] == [1, 4]
    assert issues[0].labels == frozenset({"bug"}) and issues[0].milestone == 2
    assert issues[1].labels == frozenset({"epic"})


@pytest.mark.parametrize(
    "data",
    [
        {},
        [],
        [{"number": 1, "state": "closed"}],
        ["not an object"],
        [{"number": "1"}],
        [{"number": 1, "labels": "bug"}],
        [{"number": 1, "labels": [{"color": "red"}]}],
        [{"number": 1, "milestone": 3}],
        [{"number": 1, "parent": "two"}],
        [{"number": 1}, {"number": 1}],
    ],
    ids=["mapping", "empty", "only-closed", "string-item", "string-number", "labels-string",
         "label-without-name", "milestone-int", "parent-string", "duplicate"],
)
def test_a_snapshot_it_cannot_read_raises_instead_of_reporting_ok(data):
    with pytest.raises(mp.SnapshotError):
        mp.parse_issues(data)


@pytest.mark.parametrize(
    "data", [{}, [{"number": 1, "state": "archived"}], [{"number": 0, "state": "open"}]]
)
def test_a_milestone_listing_it_cannot_read_raises(data):
    with pytest.raises(mp.SnapshotError):
        mp.parse_milestones(data)


# ---------------------------------------------------------------- the written policy


def test_the_policy_document_names_every_class_and_every_rule():
    text = POLICY_DOC.read_text(encoding="utf-8")
    documented = set(re.findall(r"`evergreen:([a-z-]+)`", text))
    assert documented == set(mp.EVERGREEN_CLASSES)
    for rule in mp.RULES:
        assert f"`{rule}`" in text, rule
    assert f"`{mp.EPIC_LABEL}`" in text


def test_the_roadmaps_no_longer_claim_every_open_issue_has_a_milestone():
    for rel in ("docs/roadmap.md", "ROADMAP.md"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "Every open issue is filed under one" not in text, rel
        assert "Every open issue belongs to exactly one milestone" not in text, rel
        assert "milestone-policy.md" in text, rel


# ---------------------------------------------------------------- command lines


def _run(*args):
    done = subprocess.run(
        [sys.executable, *map(str, args)], capture_output=True, text=True, timeout=60
    )
    return done.returncode, done.stdout + done.stderr


def test_cli_exit_codes():
    milestones = FIXTURES / "milestones.json"
    code, out = _run(SCRIPT, FIXTURES / "compliant_issues.json", "--milestones", milestones)
    assert code == 0, out
    assert "No violations." in out
    code, out = _run(SCRIPT, FIXTURES / "violating_issues.json", "--milestones", milestones)
    assert code == 1, out
    assert "[EPIC_SPANS_MILESTONES] #15" in out
    code, out = _run(SCRIPT, FIXTURES / "does-not-exist.json")
    assert code == 2, out
    assert "CANNOT CHECK" in out


def test_the_offline_traceability_checker_runs_the_policy_on_request(tmp_path):
    code, out = _run(CHECKER)
    assert code == 0, out
    assert "Milestone policy" not in out

    milestones = FIXTURES / "milestones.json"
    code, out = _run(CHECKER, "--issues", FIXTURES / "compliant_issues.json",
                     "--milestones", milestones)
    assert code == 0, out
    assert "structurally valid" in out and "No violations." in out

    code, out = _run(CHECKER, "--issues", FIXTURES / "violating_issues.json")
    assert code == 1, out
    assert "DELIVERY_WITHOUT_MILESTONE" in out

    empty = tmp_path / "empty.json"
    empty.write_text("[]", encoding="utf-8")
    code, out = _run(CHECKER, "--issues", empty)
    assert code == 2, out
