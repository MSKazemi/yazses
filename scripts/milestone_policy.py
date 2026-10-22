#!/usr/bin/env python3
"""Classify open issues under the milestone policy (#480) and report every violation.

The policy itself is written down in ``design/milestone-policy.md``; this module is its
executable form. It is **pure and offline**: it reads an issue snapshot that somebody else
fetched (``gh issue list --state open --json number,title,labels,milestone``, or the raw
REST ``GET /repos/{owner}/{repo}/issues`` payload) and never touches the network.

Every open issue lands in exactly one class, decided only by structured metadata (labels),
never by title prose:

``delivery``
    The default. Must carry exactly one milestone, and that milestone must be open.
``epic``
    Labelled ``epic``. Its milestone is *derived* from its open sub-issues: it carries one
    exactly when all of its open delivery children share it, and none when they span
    several outcomes.
``evergreen:<class>``
    Labelled with one of :data:`EVERGREEN_CLASSES`. Must carry **no** milestone: an issue
    that no release can finish would hold an outcome's progress below 100% forever.

There is no fourth outcome, so nothing can fall through both categories.

Usage::

    gh issue list --state open --limit 1000 --json number,title,labels,milestone > issues.json
    gh api repos/MSKazemi/yazses/milestones -X GET -f state=all --paginate > milestones.json
    python scripts/milestone_policy.py issues.json --milestones milestones.json

Exit codes: ``0`` no violation, ``1`` at least one violation, ``2`` an input could not be
read or does not have the expected shape (never reported as "no violations").
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

EPIC_LABEL = "epic"
EVERGREEN_PREFIX = "evergreen:"

#: The closed set of evergreen classes. ``design/milestone-policy.md`` documents each one,
#: and a test fails if the document and this mapping disagree.
EVERGREEN_CLASSES: dict[str, str] = {
    "research": "An open research question with no delivery outcome of its own.",
    "field-report": (
        "An open-ended call for compatibility or measurement reports from many people."
    ),
    "translation": "A translation or native-speaker review queue that stays open for volunteers.",
    "community": "A contributor hub, stewardship invitation, or outreach call.",
}

DELIVERY = "delivery"
EPIC = "epic"
INVALID = "invalid"

RULES: dict[str, str] = {
    "DELIVERY_WITHOUT_MILESTONE": "a delivery issue must carry exactly one milestone",
    "EVERGREEN_WITH_MILESTONE": "an evergreen issue must not carry a milestone",
    "UNKNOWN_EVERGREEN_CLASS": "an evergreen:* label must name a class the policy defines",
    "CONFLICTING_CLASSES": "an issue may carry at most one class label (epic or evergreen:*)",
    "MILESTONE_UNKNOWN": "the issue's milestone is not in the milestone listing",
    "MILESTONE_CLOSED": "an open issue must not sit in a closed milestone",
    "EPIC_SPANS_MILESTONES": (
        "an epic carries a milestone only when every open delivery child shares it"
    ),
    "EPIC_MILESTONE_MISSING": (
        "an epic whose open delivery children all share one milestone must carry it"
    ),
}


class SnapshotError(Exception):
    """An input could not be read or has the wrong shape. Never treated as 'no violations'."""


@dataclass(frozen=True)
class Issue:
    number: int
    title: str
    labels: frozenset[str]
    milestone: int | None
    milestone_title: str | None = None
    parent: int | None = None


@dataclass(frozen=True)
class Milestone:
    number: int
    title: str
    state: str  # "open" | "closed"


@dataclass(frozen=True)
class Violation:
    rule: str
    issue: int
    message: str


@dataclass
class PolicyReport:
    classes: dict[int, str] = field(default_factory=dict)
    violations: list[Violation] = field(default_factory=list)
    #: Epics whose milestone could not be derived because the snapshot names no child.
    unverified_epics: list[int] = field(default_factory=list)
    has_parent_links: bool = False
    milestones_checked: bool = False

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for cls in self.classes.values():
            out[cls] = out.get(cls, 0) + 1
        return dict(sorted(out.items()))


# --------------------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------------------
def _number(value: Any, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SnapshotError(f"{what} must be a positive integer, got {value!r}")
    return value


def _milestone_ref(raw: Any, where: str) -> tuple[int | None, str | None]:
    if raw is None:
        return None, None
    if not isinstance(raw, Mapping):
        raise SnapshotError(f"{where}.milestone must be an object or null")
    return _number(raw.get("number"), f"{where}.milestone.number"), str(raw.get("title") or "")


def _parent_ref(raw: Any, where: str) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, Mapping):
        return _number(raw.get("number"), f"{where}.parent.number")
    return _number(raw, f"{where}.parent")


def _labels(raw: Any, where: str) -> frozenset[str]:
    if raw is None:
        return frozenset()
    if not isinstance(raw, list):
        raise SnapshotError(f"{where}.labels must be a list")
    names: set[str] = set()
    for label in raw:
        name = label.get("name") if isinstance(label, Mapping) else label
        if not isinstance(name, str) or not name:
            raise SnapshotError(f"{where}.labels has an entry without a name: {label!r}")
        names.add(name)
    return frozenset(names)


def parse_issues(data: Any) -> list[Issue]:
    """Accept ``gh issue list --json`` output or the REST issues payload.

    Pull requests (REST lists them among issues) and closed issues are skipped: the policy
    is about what is open now. A ``state`` field is optional because ``gh issue list
    --state open`` omits it unless asked.
    """
    if not isinstance(data, list):
        raise SnapshotError("issue snapshot must be a JSON array of issues")
    issues: list[Issue] = []
    seen: set[int] = set()
    for index, raw in enumerate(data):
        where = f"issues[{index}]"
        if not isinstance(raw, Mapping):
            raise SnapshotError(f"{where} must be an object")
        number = _number(raw.get("number"), f"{where}.number")
        where = f"issue #{number}"
        if "pull_request" in raw:
            continue
        state = raw.get("state", "open")
        if not isinstance(state, str):
            raise SnapshotError(f"{where}.state must be a string")
        if state.lower() != "open":
            continue
        if number in seen:
            raise SnapshotError(f"{where} appears twice in the snapshot")
        seen.add(number)
        milestone, milestone_title = _milestone_ref(raw.get("milestone"), where)
        issues.append(
            Issue(
                number=number,
                title=str(raw.get("title") or ""),
                labels=_labels(raw.get("labels"), where),
                milestone=milestone,
                milestone_title=milestone_title,
                parent=_parent_ref(raw.get("parent"), where),
            )
        )
    if not issues:
        # A policy check over nothing proves nothing; an empty snapshot is far likelier to
        # be a failed fetch than a repository with no open issues.
        raise SnapshotError("issue snapshot contains no open issues; refusing to report OK")
    return issues


def parse_milestones(data: Any) -> dict[int, Milestone]:
    if not isinstance(data, list):
        raise SnapshotError("milestone listing must be a JSON array")
    out: dict[int, Milestone] = {}
    for index, raw in enumerate(data):
        where = f"milestones[{index}]"
        if not isinstance(raw, Mapping):
            raise SnapshotError(f"{where} must be an object")
        number = _number(raw.get("number"), f"{where}.number")
        state = raw.get("state")
        if not isinstance(state, str) or state.lower() not in ("open", "closed"):
            raise SnapshotError(f"milestone {number} has state {state!r}")
        out[number] = Milestone(number, str(raw.get("title") or ""), state.lower())
    return out


# --------------------------------------------------------------------------------------
# Classification and evaluation
# --------------------------------------------------------------------------------------
def classify(issue: Issue) -> tuple[str, list[Violation]]:
    """Return the issue's single class, plus any violation that makes the class invalid."""
    evergreen = sorted(label for label in issue.labels if label.startswith(EVERGREEN_PREFIX))
    class_labels = evergreen + ([EPIC_LABEL] if EPIC_LABEL in issue.labels else [])
    problems: list[Violation] = []
    for label in evergreen:
        if label.removeprefix(EVERGREEN_PREFIX) not in EVERGREEN_CLASSES:
            known = ", ".join(EVERGREEN_PREFIX + name for name in EVERGREEN_CLASSES)
            problems.append(
                Violation(
                    "UNKNOWN_EVERGREEN_CLASS",
                    issue.number,
                    f"label {label!r} is not a defined class (known: {known})",
                )
            )
    if len(class_labels) > 1:
        problems.append(
            Violation(
                "CONFLICTING_CLASSES",
                issue.number,
                f"carries {len(class_labels)} class labels ({', '.join(class_labels)}); "
                "keep exactly one",
            )
        )
    if problems:
        return INVALID, problems
    if evergreen:
        return evergreen[0], []
    if EPIC_LABEL in issue.labels:
        return EPIC, []
    return DELIVERY, []


def _ms(issue: Issue) -> str:
    if issue.milestone is None:
        return "no milestone"
    title = f" {issue.milestone_title!r}" if issue.milestone_title else ""
    return f"milestone {issue.milestone}{title}"


def evaluate(
    issues: Iterable[Issue], milestones: Mapping[int, Milestone] | None = None
) -> PolicyReport:
    """Classify every issue and collect every violation. Pure: no I/O, no clock."""
    issues = list(issues)
    report = PolicyReport(
        has_parent_links=any(issue.parent is not None for issue in issues),
        milestones_checked=milestones is not None,
    )
    by_number = {issue.number: issue for issue in issues}

    for issue in issues:
        cls, problems = classify(issue)
        report.classes[issue.number] = cls
        report.violations.extend(problems)
        if cls == DELIVERY and issue.milestone is None:
            report.violations.append(
                Violation(
                    "DELIVERY_WITHOUT_MILESTONE",
                    issue.number,
                    "delivery issue has no milestone; assign its outcome, or label it "
                    "epic / evergreen:<class> if it is not delivery work",
                )
            )
        if cls.startswith(EVERGREEN_PREFIX) and issue.milestone is not None:
            report.violations.append(
                Violation(
                    "EVERGREEN_WITH_MILESTONE",
                    issue.number,
                    f"{cls} issue carries {_ms(issue)}; evergreen work carries none",
                )
            )
        if milestones is not None and issue.milestone is not None:
            known = milestones.get(issue.milestone)
            if known is None:
                report.violations.append(
                    Violation(
                        "MILESTONE_UNKNOWN",
                        issue.number,
                        f"{_ms(issue)} is not in the milestone listing",
                    )
                )
            elif known.state != "open":
                report.violations.append(
                    Violation(
                        "MILESTONE_CLOSED",
                        issue.number,
                        f"open issue sits in closed milestone {known.number} {known.title!r}",
                    )
                )

    children: dict[int, list[Issue]] = {}
    for issue in issues:
        if issue.parent is not None and issue.parent in by_number:
            children.setdefault(issue.parent, []).append(issue)

    for issue in issues:
        if report.classes[issue.number] != EPIC:
            continue
        kids = [
            kid
            for kid in children.get(issue.number, [])
            if report.classes[kid.number] in (DELIVERY, EPIC)
        ]
        if not kids:
            report.unverified_epics.append(issue.number)
            continue
        outcomes = sorted({kid.milestone for kid in kids if kid.milestone is not None})
        if issue.milestone is not None:
            stray = [kid for kid in kids if kid.milestone not in (None, issue.milestone)]
            if stray:
                names = ", ".join(f"#{kid.number} ({_ms(kid)})" for kid in stray)
                report.violations.append(
                    Violation(
                        "EPIC_SPANS_MILESTONES",
                        issue.number,
                        f"epic carries {_ms(issue)} but open children sit elsewhere: {names}; "
                        "an epic spanning outcomes carries no milestone",
                    )
                )
        elif len(outcomes) == 1 and all(kid.milestone is not None for kid in kids):
            report.violations.append(
                Violation(
                    "EPIC_MILESTONE_MISSING",
                    issue.number,
                    f"every open delivery child is in milestone {outcomes[0]}; "
                    "the epic carries it too",
                )
            )

    report.violations.sort(key=lambda v: (v.issue, v.rule))
    return report


# --------------------------------------------------------------------------------------
# Rendering and CLI
# --------------------------------------------------------------------------------------
def render(report: PolicyReport) -> str:
    counts = ", ".join(f"{cls}={n}" for cls, n in report.counts().items())
    out = [
        f"Milestone policy (#480): {len(report.classes)} open issues classified ({counts})."
    ]
    if report.violations:
        out.append(f"{len(report.violations)} violation(s):")
        for v in report.violations:
            out.append(f"  - [{v.rule}] #{v.issue}: {v.message}")
    else:
        out.append("No violations.")
    if not report.milestones_checked:
        out.append(
            "  note: no milestone listing given; MILESTONE_UNKNOWN / MILESTONE_CLOSED not checked"
        )
    if not report.has_parent_links:
        out.append(
            "  note: snapshot carries no parent links; epic milestones were not derived"
        )
    if report.unverified_epics:
        names = ", ".join(f"#{n}" for n in report.unverified_epics)
        out.append(
            f"  unverified epic(s) {names}: no open child in the snapshot, so the epic's "
            "milestone cannot be derived; link children as GitHub sub-issues"
        )
    return "\n".join(out) + "\n"


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise SnapshotError(f"cannot read {path}: {exc}") from exc


def check_files(issues_path: Path, milestones_path: Path | None = None) -> PolicyReport:
    issues = parse_issues(load_json(issues_path))
    milestones = parse_milestones(load_json(milestones_path)) if milestones_path else None
    return evaluate(issues, milestones)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("issues", type=Path, help="open-issue snapshot (JSON array)")
    parser.add_argument("--milestones", type=Path, help="milestone listing (JSON array)")
    args = parser.parse_args(argv)
    try:
        report = check_files(args.issues, args.milestones)
    except SnapshotError as exc:
        print(f"Milestone policy: CANNOT CHECK ({exc}).", file=sys.stderr)
        return 2
    body = render(report)
    if report.violations:
        sys.stderr.write(body)
        return 1
    sys.stdout.write(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
