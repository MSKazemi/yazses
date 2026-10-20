#!/usr/bin/env python3
"""Read-only preflight for a future upstream Google Jules issue trigger.

The literal jules label can start external work once the GitHub App is
connected. This command therefore runs before that label is applied. It
validates a trusted, structured issue contract and never mutates GitHub state.

Usage:
    uv run python scripts/check-jules-issue.py 392

Exit 0 means only "eligible for a maintainer to consider triggering".
It is not an execution action and never authorizes merge.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

REPO = os.environ.get("YAZSES_REPO", "MSKazemi/yazses")
API = "https://api.github.com"
TRUSTED_CONTRACT_AUTHORS = frozenset({"mskazemi"})

CLOUD_READY = (
    "Cloud-ready — implementation and all required evidence can be completed in a clean VM"
)
REQUIRED_SECTIONS = (
    "One-sentence goal",
    "Explicitly out of scope",
    "Where this plugs in",
    "Acceptance criteria (Given / When / Then)",
    "Required tests",
    "Definition-of-done command",
)
REMOTE_SECTION = "Remote-agent execution class"
SUITABILITY_SECTION = "Suitable for"
BLOCKERS_SECTION = "Blocked by (issue numbers)"

NO_RESPONSE = frozenset(
    {"", "_no response_", "no response", "none", "n/a", "na", "not applicable"}
)
ISSUE_REF = re.compile(r"#(?P<number>[1-9][0-9]*)\b")
SECTION = re.compile(
    r"^###\s+(?P<label>.+?)\s*$\n(?P<body>.*?)(?=^###\s+|\Z)",
    re.MULTILINE | re.DOTALL,
)


@dataclass(frozen=True)
class IssueSnapshot:
    number: int
    state: str
    author: str
    labels: frozenset[str]
    body: str
    is_pull_request: bool = False


@dataclass(frozen=True)
class EligibilityReport:
    failures: tuple[str, ...]
    blockers: tuple[int, ...]

    @property
    def eligible(self) -> bool:
        return not self.failures


def api_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "yazses-jules-preflight",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def parse_sections(body: str) -> dict[str, str]:
    """Return rendered Issue Form sections without reading comments."""
    return {
        match.group("label").strip(): match.group("body").strip()
        for match in SECTION.finditer(body or "")
    }


def is_blank_form_value(value: str | None) -> bool:
    return (value or "").strip().lower() in NO_RESPONSE


def selected_checkboxes(value: str) -> set[str]:
    """Checked labels from one rendered Issue Form checkbox section."""
    selected: set[str] = set()
    for line in value.splitlines():
        match = re.match(r"^\s*-\s*\[[xX]\]\s*(.+?)\s*$", line)
        if match:
            selected.add(match.group(1))
    return selected


def parse_blockers(value: str | None) -> tuple[tuple[int, ...], str | None]:
    """Parse only the explicit blocker field; fail closed on prose-only lines."""
    if is_blank_form_value(value):
        return (), None

    refs: list[int] = []
    assert value is not None
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        found = [int(match.group("number")) for match in ISSUE_REF.finditer(line)]
        if not found:
            return (), f"ambiguous blocker line: {line!r}"
        refs.extend(found)

    if not refs:
        return (), "blocker field is not empty but contains no issue reference"
    return tuple(dict.fromkeys(refs)), None


def snapshot_from_api(data: dict[str, Any]) -> IssueSnapshot:
    user = data.get("user") or {}
    labels = {
        str(label.get("name", "")).strip().lower()
        for label in data.get("labels") or []
        if isinstance(label, dict)
    }
    return IssueSnapshot(
        number=int(data.get("number") or 0),
        state=str(data.get("state") or ""),
        author=str(user.get("login") or ""),
        labels=frozenset(label for label in labels if label),
        body=str(data.get("body") or ""),
        is_pull_request="pull_request" in data,
    )


def evaluate(
    issue: IssueSnapshot,
    *,
    blocker_states: dict[int, str] | None = None,
) -> EligibilityReport:
    """Pure eligibility policy. No network, filesystem, labels, or writes."""
    failures: list[str] = []
    sections = parse_sections(issue.body)

    if issue.is_pull_request:
        failures.append("target is a pull request, not an issue")
    if issue.state.lower() != "open":
        failures.append("issue is not open")
    if issue.author.lower() not in TRUSTED_CONTRACT_AUTHORS:
        failures.append(
            f"issue author @{issue.author or '(missing)'} is not in the trusted "
            "execution-contract author set"
        )
    if "agent-ready" not in issue.labels:
        failures.append("missing required label: agent-ready")
    if "jules" in issue.labels:
        failures.append("jules label is already present; preflight is too late")

    for label in REQUIRED_SECTIONS:
        if is_blank_form_value(sections.get(label)):
            failures.append(f"missing or empty structured section: {label}")

    remote = sections.get(REMOTE_SECTION, "")
    if is_blank_form_value(remote):
        failures.append(f"missing or empty structured section: {REMOTE_SECTION}")
    elif remote.strip() != CLOUD_READY:
        failures.append("remote-agent execution class is not Cloud-ready")

    suitability = selected_checkboxes(sections.get(SUITABILITY_SECTION, ""))
    if "Needs real hardware to verify (cannot be done in a container)" in suitability:
        failures.append("real-hardware evidence is required")
    if "Needs a native-language/domain reviewer before merge" in suitability:
        failures.append("native-language/domain evidence is required before merge")

    if "hardware-required" in issue.labels:
        failures.append(
            "hardware-required label is incompatible with central cloud execution"
        )
    if "research" in issue.labels:
        failures.append(
            "research evidence issues are not eligible for the initial central deployment"
        )

    blockers, blocker_error = parse_blockers(sections.get(BLOCKERS_SECTION))
    if blocker_error:
        failures.append(blocker_error)

    states = blocker_states or {}
    for blocker in blockers:
        state = states.get(blocker)
        if state is None:
            failures.append(f"blocker #{blocker} was not resolved by the preflight")
        elif state.lower() != "closed":
            failures.append(f"blocker #{blocker} is still {state}")

    return EligibilityReport(tuple(failures), blockers)


def github_get(path: str) -> dict[str, Any]:
    """One read-only GitHub GET. This module intentionally defines no write helper."""
    req = urllib.request.Request(f"{API}{path}", headers=api_headers(), method="GET")
    with urllib.request.urlopen(req, timeout=30) as response:
        data = json.load(response)
    if not isinstance(data, dict):
        raise ValueError("GitHub API returned a non-object response")
    return data


def fetch_issue(number: int) -> IssueSnapshot:
    return snapshot_from_api(github_get(f"/repos/{REPO}/issues/{number}"))


def fetch_blocker_states(numbers: tuple[int, ...]) -> dict[int, str]:
    states: dict[int, str] = {}
    for number in numbers:
        data = github_get(f"/repos/{REPO}/issues/{number}")
        if "pull_request" in data:
            states[number] = "pull-request"
        else:
            states[number] = str(data.get("state") or "unknown")
    return states


def preflight(number: int) -> EligibilityReport:
    issue = fetch_issue(number)
    sections = parse_sections(issue.body)
    blockers, blocker_error = parse_blockers(sections.get(BLOCKERS_SECTION))
    states = {} if blocker_error else fetch_blocker_states(blockers)
    return evaluate(issue, blocker_states=states)


def render(number: int, report: EligibilityReport) -> str:
    lines = [f"# Jules issue preflight — #{number}", ""]
    if report.eligible:
        lines.extend(
            [
                "ELIGIBLE",
                "",
                "All machine-checkable pre-trigger conditions passed.",
                "This does not start Jules and is not authorization to merge.",
                "A maintainer must still decide whether to apply the jules execution label.",
            ]
        )
    else:
        lines.extend(["INELIGIBLE", "", "Failed preconditions:"])
        lines.extend(f"- {failure}" for failure in report.failures)
        lines.extend(
            [
                "",
                "Do not apply the jules execution label while any failure remains.",
            ]
        )
    if report.blockers:
        lines.extend(
            ["", "Declared blockers: " + ", ".join(f"#{n}" for n in report.blockers)]
        )
    return "\n".join(lines)


def positive_issue_number(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("issue number must be an integer") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("issue number must be greater than zero")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("issue_number", type=positive_issue_number)
    args = parser.parse_args(argv)

    try:
        report = preflight(args.issue_number)
    except urllib.error.HTTPError as exc:
        print(f"GitHub API error: HTTP {exc.code}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"GitHub preflight could not run: {exc}", file=sys.stderr)
        return 2

    print(render(args.issue_number, report))
    return 0 if report.eligible else 1


if __name__ == "__main__":
    raise SystemExit(main())
