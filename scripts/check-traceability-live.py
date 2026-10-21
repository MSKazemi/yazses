#!/usr/bin/env python3
"""Scheduled, read-only audit of the live GitHub facts behind ``design/traceability.yml``.

``scripts/check-traceability.py`` is offline: it proves the manifest is coherent. It cannot
know whether issue #164 is still open or whether milestone 9 still exists. This script asks
GitHub, and nothing else. It only ever issues ``GET`` requests, never mutates an issue or a
milestone, and is repository maintenance tooling (it is not part of the product under
``src/yazses/``, so the "nothing leaves the machine" rule does not apply to it).

What it checks, per manifest entry that names issues or a milestone
-------------------------------------------------------------------
``ISSUE_MISSING``
    A referenced issue number does not exist.
``ISSUE_IS_PULL_REQUEST``
    A referenced number is a pull request, not an issue.
``NO_OPEN_TRACKER``
    The entry's delivery status is not terminal (anything except ``shipped``, ``deferred``,
    ``not-planned``) yet *every* issue it names is closed, so a closed issue is the sole
    tracker of live work.
``MILESTONE_MISSING``
    The entry declares ``tracking.milestone: N`` and GitHub has no milestone numbered N.
``MILESTONE_MISMATCH``
    The entry declares a milestone and an *open* issue it names carries a different one (or
    none). Closed issues are not compared: their milestone is history.

Advisory drift, per open GitHub issue (reported, NEVER changes the exit code)
------------------------------------------------------------------------------
The same issue listing also answers three questions about the issue tracker itself. They are
advisory because the policy that would make them binding is #480's decision, still open:

``UNMILESTONED_UNCLASSIFIED``
    An open issue has no milestone and carries none of the exempt class labels listed under
    ``issue_policy.exempt_labels`` in ``design/traceability-exceptions.yml``. That list is
    empty until #480 names the classes, so today this is simply "open issue, no milestone".
``STALE_DO_NOT_START``
    An open issue's body carries a "do not start" blockquote banner and every issue/PR the
    banner (or the issue's ``## Blocked by`` section) names is now closed. Conservative by
    construction: an unknown or still-open reference keeps the banner quiet.
``CLOSED_TRACKER_REFERENCE``
    A non-terminal manifest entry still lists a closed issue beside an open one. (When every
    tracker is closed that is the blocking ``NO_OPEN_TRACKER`` above, not this.)

Exit codes (a transient outage must never read as a traceability finding)
------------------------------------------------------------------------
``0``  every live check passed (exceptions and advisory drift are listed, never silent)
``1``  at least one real traceability violation
``2``  live state could not be obtained: network error, timeout, 5xx, 429, exhausted rate
       limit, truncated pagination or an unreadable response. Not a finding; retry later.
``3``  the audit cannot run as configured: invalid manifest or exceptions file, bad token
       or permissions (401/403), unknown repository (404), a redirect, bad arguments. Retrying
       will not help.

Cost: two paginated list requests (all issues, all milestones) regardless of how many manifest
entries there are, never one request per entry.

Exceptions
----------
The milestone policy (#480) is still being decided, so this script invents none. Instead,
``design/traceability-exceptions.yml`` is an explicit allowlist, empty by default. Each item
names a rule, an entry and (optionally) an issue, and must carry a ``reason`` and the
``tracker`` issue that justifies it; an optional ``expires`` date stops it applying. An
exception that matched nothing is reported so the file cannot quietly rot.

``--summary-file`` appends a human report (the job summary); ``--json-file`` writes the same
outcome as JSON for the workflow artifact, for every exit code.

The token is read from ``GITHUB_TOKEN``/``GH_TOKEN`` and is only ever sent to the API host; it
is never printed, logged, or echoed in an error.
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "design" / "traceability.yml"
EXCEPTIONS = ROOT / "design" / "traceability-exceptions.yml"
MANIFEST_REL = "design/traceability.yml"
EXCEPTIONS_REL = "design/traceability-exceptions.yml"

EXIT_OK = 0
EXIT_VIOLATION = 1
EXIT_UNAVAILABLE = 2
EXIT_CONFIG = 3

DEFAULT_REPO = "MSKazemi/yazses"
DEFAULT_API = "https://api.github.com"

#: Delivery states whose tracker may legitimately be closed (or absent).
TERMINAL_DELIVERY = frozenset({"shipped", "deferred", "not-planned"})

RULES = (
    "ISSUE_MISSING",
    "ISSUE_IS_PULL_REQUEST",
    "NO_OPEN_TRACKER",
    "MILESTONE_MISSING",
    "MILESTONE_MISMATCH",
)

#: Advisory rules: reported in the summary and artifact, never part of the exit code.
DRIFT_RULES = (
    "UNMILESTONED_UNCLASSIFIED",
    "STALE_DO_NOT_START",
    "CLOSED_TRACKER_REFERENCE",
)

MAX_PAGES = 100  # 10,000 items; hitting it means the listing is truncated, not "done"
MAX_ATTEMPTS = 3
MAX_WAIT_SECONDS = 60


# --------------------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------------------
class LiveStateUnavailable(Exception):
    """GitHub's state could not be read. Transient by nature: exit 2, not a finding."""


class AuditConfigError(Exception):
    """The audit cannot run as configured. Retrying will not help: exit 3."""


# --------------------------------------------------------------------------------------
# Pure logic: parsing
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class IssueFact:
    number: int
    state: str  # "open" | "closed"
    is_pull_request: bool
    milestone: int | None
    title: str
    labels: tuple[str, ...] = ()
    body: str = ""
    merged: bool = False  # pull requests only: closed by a merge, not abandoned


@dataclass(frozen=True)
class MilestoneFact:
    number: int
    title: str
    state: str


def _require(cond: bool, what: str) -> None:
    if not cond:
        raise LiveStateUnavailable(f"unreadable GitHub response: {what}")


def parse_issues(items: Iterable[Any]) -> dict[int, IssueFact]:
    """Index the ``GET /repos/{r}/issues`` payload. Pull requests are listed there too."""
    out: dict[int, IssueFact] = {}
    for raw in items:
        _require(isinstance(raw, dict), "issue item is not an object")
        number, state = raw.get("number"), raw.get("state")
        _require(isinstance(number, int) and not isinstance(number, bool), "issue.number")
        _require(state in ("open", "closed"), f"issue #{number} has state {state!r}")
        milestone = raw.get("milestone")
        _require(
            milestone is None or isinstance(milestone, dict), f"issue #{number}.milestone"
        )
        ms_number = None if milestone is None else milestone.get("number")
        _require(
            ms_number is None or isinstance(ms_number, int), f"issue #{number}.milestone.number"
        )
        raw_labels = raw.get("labels") or []
        _require(isinstance(raw_labels, list), f"issue #{number}.labels")
        labels: list[str] = []
        for label in raw_labels:
            name = label.get("name") if isinstance(label, dict) else label
            if not isinstance(name, str):
                raise LiveStateUnavailable(f"unreadable GitHub response: issue #{number} label")
            labels.append(name)
        body = raw.get("body")
        _require(body is None or isinstance(body, str), f"issue #{number}.body")
        pull = raw.get("pull_request")
        out[number] = IssueFact(
            number=number,
            state=state,
            is_pull_request="pull_request" in raw,
            milestone=ms_number,
            title=str(raw.get("title") or ""),
            labels=tuple(labels),
            body=body or "",
            merged=isinstance(pull, dict) and bool(pull.get("merged_at")),
        )
    return out


def parse_milestones(items: Iterable[Any]) -> dict[int, MilestoneFact]:
    out: dict[int, MilestoneFact] = {}
    for raw in items:
        _require(isinstance(raw, dict), "milestone item is not an object")
        number, state = raw.get("number"), raw.get("state")
        _require(isinstance(number, int) and not isinstance(number, bool), "milestone.number")
        _require(state in ("open", "closed"), f"milestone {number} has state {state!r}")
        out[number] = MilestoneFact(number, str(raw.get("title") or ""), state)
    return out


_LINK_NEXT = re.compile(r'<([^>]+)>\s*;\s*rel="next"')


def parse_link_next(header: str | None) -> str | None:
    """The ``rel="next"`` target of an RFC 8288 ``Link`` header, or ``None`` on the last page."""
    if not header:
        return None
    match = _LINK_NEXT.search(header)
    return match.group(1) if match else None


def locate_entries(manifest_text: str) -> dict[str, int]:
    """Map each manifest entry id to its 1-based line, so findings can point at the file."""
    found: dict[str, int] = {}
    for number, line in enumerate(manifest_text.splitlines(), start=1):
        match = re.match(r"""\s*-\s+id:\s*["']?([^"'\s#]+)["']?""", line)
        if match:
            found.setdefault(match.group(1), number)
    return found


# --------------------------------------------------------------------------------------
# Pure logic: exceptions
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class AllowedException:
    rule: str
    entry: str
    issue: int | None
    reason: str
    tracker: int
    expires: dt.date | None


def parse_exceptions(data: Any) -> list[AllowedException]:
    """Validate the allowlist. Anything malformed raises :class:`AuditConfigError`."""
    if data is None:
        return []
    if not isinstance(data, dict) or data.get("version") != 1:
        raise AuditConfigError(f"{EXCEPTIONS_REL}: must be a mapping with `version: 1`")
    items = data.get("exceptions", [])
    if items is None:
        items = []
    if not isinstance(items, list):
        raise AuditConfigError(f"{EXCEPTIONS_REL}: `exceptions` must be a list")
    parsed: list[AllowedException] = []
    for index, item in enumerate(items):
        where = f"{EXCEPTIONS_REL}: exceptions[{index}]"
        if not isinstance(item, dict):
            raise AuditConfigError(f"{where} must be a mapping")
        rule, entry, issue = item.get("rule"), item.get("entry"), item.get("issue")
        reason, tracker, expires = item.get("reason"), item.get("tracker"), item.get("expires")
        if rule not in RULES:
            raise AuditConfigError(f"{where}.rule must be one of {', '.join(RULES)}")
        if not isinstance(entry, str) or not entry:
            raise AuditConfigError(f"{where}.entry must be a manifest entry id")
        if issue is not None and (not isinstance(issue, int) or issue <= 0):
            raise AuditConfigError(f"{where}.issue must be null or a positive integer")
        if not isinstance(reason, str) or not reason.strip():
            raise AuditConfigError(f"{where}.reason is required: say why this is allowed")
        if not isinstance(tracker, int) or isinstance(tracker, bool) or tracker <= 0:
            raise AuditConfigError(f"{where}.tracker must be the issue that justifies it")
        if expires is not None and not isinstance(expires, dt.date):
            raise AuditConfigError(f"{where}.expires must be a YYYY-MM-DD date or null")
        if isinstance(expires, dt.datetime):
            raise AuditConfigError(f"{where}.expires must be a date, not a timestamp")
        parsed.append(AllowedException(rule, entry, issue, reason.strip(), tracker, expires))
    return parsed


@dataclass(frozen=True)
class IssuePolicy:
    """Which open issues may lack a milestone. #480 decides; this only encodes the decision."""

    exempt_labels: frozenset[str] = frozenset()


def parse_issue_policy(data: Any) -> IssuePolicy:
    """Read ``issue_policy`` from the exceptions file. Absent means no exemption class."""
    if not isinstance(data, dict) or data.get("issue_policy") is None:
        return IssuePolicy()
    raw = data["issue_policy"]
    where = f"{EXCEPTIONS_REL}: issue_policy"
    if not isinstance(raw, dict):
        raise AuditConfigError(f"{where} must be a mapping")
    unknown = set(raw) - {"exempt_labels"}
    if unknown:
        raise AuditConfigError(f"{where} has unknown key(s): {', '.join(sorted(unknown))}")
    labels = raw.get("exempt_labels") or []
    if not isinstance(labels, list) or not all(
        isinstance(name, str) and name.strip() for name in labels
    ):
        raise AuditConfigError(f"{where}.exempt_labels must be a list of label names")
    return IssuePolicy(frozenset(name.strip() for name in labels))


# --------------------------------------------------------------------------------------
# Pure logic: "do not start" banners in issue bodies
# --------------------------------------------------------------------------------------
_DO_NOT_START = re.compile(r"\b(?:do\s+not|don['’]t)\s+start\b", re.IGNORECASE)
# `#123`, but not `owner/repo#123`, `&#123;` or an anchor such as `page#123`.
_ISSUE_REF = re.compile(r"(?<![\w/&])#(\d+)\b")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^\s{0,3}(```|~~~)")


def _prose_lines(body: str) -> list[str]:
    """The body's lines with fenced code blanked, so a quoted snippet is not read as prose."""
    out: list[str] = []
    fenced = False
    for line in body.splitlines():
        if _FENCE.match(line):
            fenced = not fenced
            out.append("")
            continue
        out.append("" if fenced else line)
    return out


def banner_blockers(body: str, own_number: int | None = None) -> list[int] | None:
    """Issue numbers a "do not start" banner waits on, or ``None`` when there is no banner.

    The banner is a Markdown blockquote block that says "do not start". Its blockers are the
    ``#N`` references in that block plus those in a ``## Blocked by`` section, if the issue
    has one. Taking the union is the conservative direction: a stray extra reference that is
    still open can only keep a banner from being reported stale, never make one fire.
    """
    lines = _prose_lines(body)
    banner: list[str] | None = None
    block: list[str] = []
    for line in [*lines, ""]:
        if line.lstrip().startswith(">"):
            block.append(line)
            continue
        if block and _DO_NOT_START.search(" ".join(block)):
            banner = (banner or []) + block
        block = []
    if banner is None:
        return None
    text = list(banner)
    in_blocked = False
    for line in lines:
        heading = _HEADING.match(line)
        if heading:
            in_blocked = heading.group(1).strip().lower().rstrip(":") == "blocked by"
            continue
        if in_blocked:
            text.append(line)
    refs: list[int] = []
    for match in _ISSUE_REF.finditer("\n".join(text)):
        number = int(match.group(1))
        if number != own_number and number not in refs:
            refs.append(number)
    return refs


# --------------------------------------------------------------------------------------
# Pure logic: the decision
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Finding:
    rule: str
    entry: str
    message: str
    issue: int | None = None
    milestone: int | None = None


@dataclass(frozen=True)
class Drift:
    """An advisory observation about the live tracker. Never part of the exit code."""

    rule: str
    issue: int
    message: str
    entry: str | None = None


@dataclass
class AuditResult:
    findings: list[Finding] = field(default_factory=list)
    suppressed: list[tuple[Finding, AllowedException]] = field(default_factory=list)
    expired: list[AllowedException] = field(default_factory=list)
    unused: list[AllowedException] = field(default_factory=list)
    entries_checked: int = 0
    issues_referenced: int = 0
    drift: list[Drift] = field(default_factory=list)
    open_issues: int = 0
    unused_exempt_labels: list[str] = field(default_factory=list)


def _ms_label(number: int, milestones: dict[int, MilestoneFact]) -> str:
    fact = milestones.get(number)
    return f"milestone {number} ({fact.title!r})" if fact else f"milestone {number}"


def evaluate_entry(
    entry: dict[str, Any],
    issues: dict[int, IssueFact],
    milestones: dict[int, MilestoneFact],
) -> list[Finding]:
    """Compare one manifest entry with the live facts. Pure: no I/O, no clock."""
    entry_id = str(entry["id"])
    tracking = entry.get("tracking") or {}
    delivery = entry.get("delivery_status")
    declared = tracking.get("milestone")
    referenced = [n for n in tracking.get("issues") or [] if isinstance(n, int)]
    findings: list[Finding] = []

    existing: list[IssueFact] = []
    for number in referenced:
        fact = issues.get(number)
        if fact is None:
            findings.append(
                Finding(
                    "ISSUE_MISSING",
                    entry_id,
                    f"issue #{number} does not exist on GitHub",
                    issue=number,
                )
            )
        elif fact.is_pull_request:
            findings.append(
                Finding(
                    "ISSUE_IS_PULL_REQUEST",
                    entry_id,
                    f"#{number} is a pull request, not an issue",
                    issue=number,
                )
            )
        else:
            existing.append(fact)

    if (
        delivery not in TERMINAL_DELIVERY
        and existing
        and not any(fact.state == "open" for fact in existing)
    ):
        names = ", ".join(f"#{fact.number}" for fact in existing)
        findings.append(
            Finding(
                "NO_OPEN_TRACKER",
                entry_id,
                f"delivery_status={delivery} but every tracking issue is closed ({names}); "
                "a closed issue is the sole tracker of live work",
                issue=existing[0].number if len(existing) == 1 else None,
            )
        )

    if declared is not None:
        if declared not in milestones:
            findings.append(
                Finding(
                    "MILESTONE_MISSING",
                    entry_id,
                    f"manifest declares milestone {declared}, which does not exist on GitHub",
                    milestone=declared,
                )
            )
        else:
            for fact in existing:
                if fact.state != "open" or fact.milestone == declared:
                    continue
                actual = (
                    "no milestone"
                    if fact.milestone is None
                    else _ms_label(fact.milestone, milestones)
                )
                findings.append(
                    Finding(
                        "MILESTONE_MISMATCH",
                        entry_id,
                        f"open issue #{fact.number} has {actual}; manifest declares "
                        f"{_ms_label(declared, milestones)}",
                        issue=fact.number,
                        milestone=declared,
                    )
                )
    return findings


def _safe_title(title: str, limit: int = 80) -> str:
    """An issue title is contributor text: keep it from breaking out of the summary's fence."""
    flat = re.sub(r"[\x00-\x1f\x7f`]+", " ", title).strip()
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _describe(fact: IssueFact) -> str:
    if not fact.is_pull_request:
        return f"#{fact.number} (closed)"
    return f"#{fact.number} (PR merged)" if fact.merged else f"#{fact.number} (PR closed unmerged)"


def evaluate_drift(
    manifest: dict[str, Any],
    issues: dict[int, IssueFact],
    policy: IssuePolicy | None = None,
) -> tuple[list[Drift], int, list[str]]:
    """Advisory drift over every open issue. Pure: no I/O, no clock.

    Returns the observations, how many open issues were looked at, and which exempt labels
    matched no open issue (so the #480 class list cannot quietly rot either).
    """
    policy = policy or IssuePolicy()
    drift: list[Drift] = []
    open_issues = sorted(
        (f for f in issues.values() if f.state == "open" and not f.is_pull_request),
        key=lambda f: f.number,
    )
    used_labels: set[str] = set()
    for fact in open_issues:
        exempt = policy.exempt_labels.intersection(fact.labels)
        used_labels.update(exempt)
        if fact.milestone is None and not exempt:
            drift.append(
                Drift(
                    "UNMILESTONED_UNCLASSIFIED",
                    fact.number,
                    f"open issue #{fact.number} has no milestone and no exempt class label "
                    f"({_safe_title(fact.title)})",
                )
            )
        blockers = banner_blockers(fact.body, fact.number)
        if blockers:
            known = [issues.get(n) for n in blockers]
            if all(b is not None and b.state == "closed" for b in known):
                closed = ", ".join(_describe(b) for b in known if b is not None)
                drift.append(
                    Drift(
                        "STALE_DO_NOT_START",
                        fact.number,
                        f'open issue #{fact.number} still says "do not start" but every '
                        f"blocker it references by number is closed: {closed}; re-check any "
                        "prose condition, then lift or update the banner",
                    )
                )

    for entry in manifest.get("entries", []):
        if entry.get("delivery_status") in TERMINAL_DELIVERY:
            continue
        tracking = entry.get("tracking") or {}
        facts = [
            issues[n]
            for n in tracking.get("issues") or []
            if isinstance(n, int) and n in issues and not issues[n].is_pull_request
        ]
        if not any(f.state == "open" for f in facts):
            continue  # all closed is NO_OPEN_TRACKER, a blocking finding, not drift
        for fact in facts:
            if fact.state == "closed":
                drift.append(
                    Drift(
                        "CLOSED_TRACKER_REFERENCE",
                        fact.number,
                        f"entry {entry['id']!r} (delivery_status="
                        f"{entry.get('delivery_status')}) still lists closed issue "
                        f"#{fact.number} beside an open tracker",
                        entry=str(entry["id"]),
                    )
                )
    unused = sorted(policy.exempt_labels - used_labels)
    return drift, len(open_issues), unused


def _matches(finding: Finding, exc: AllowedException) -> bool:
    return (
        finding.rule == exc.rule
        and finding.entry == exc.entry
        and (exc.issue is None or exc.issue == finding.issue)
    )


def audit(
    manifest: dict[str, Any],
    issues: dict[int, IssueFact],
    milestones: dict[int, MilestoneFact],
    exceptions: list[AllowedException] | None = None,
    today: dt.date | None = None,
    policy: IssuePolicy | None = None,
) -> AuditResult:
    """Run every live check, apply the explicit exception allowlist, and collect drift."""
    today = today or dt.datetime.now(dt.timezone.utc).date()
    exceptions = exceptions or []
    result = AuditResult()
    live = [e for e in exceptions if e.expires is None or e.expires >= today]
    result.expired = [e for e in exceptions if e not in live]
    used: set[AllowedException] = set()

    referenced: set[int] = set()
    for entry in manifest.get("entries", []):
        tracking = entry.get("tracking") or {}
        issue_numbers = [n for n in tracking.get("issues") or [] if isinstance(n, int)]
        if not issue_numbers and tracking.get("milestone") is None:
            continue  # nothing live to verify (e.g. a deferred decision with no tracker)
        result.entries_checked += 1
        referenced.update(issue_numbers)
        for finding in evaluate_entry(entry, issues, milestones):
            allowed = next((e for e in live if _matches(finding, e)), None)
            if allowed is None:
                result.findings.append(finding)
            else:
                used.add(allowed)
                result.suppressed.append((finding, allowed))
    result.issues_referenced = len(referenced)
    result.unused = [e for e in live if e not in used]
    result.drift, result.open_issues, result.unused_exempt_labels = evaluate_drift(
        manifest, issues, policy
    )
    return result


def exit_code_for(result: AuditResult) -> int:
    return EXIT_VIOLATION if result.findings else EXIT_OK


# --------------------------------------------------------------------------------------
# Pure logic: rendering
# --------------------------------------------------------------------------------------
def render_report(
    result: AuditResult, lines: dict[str, int] | None = None, repo: str = DEFAULT_REPO
) -> str:
    lines = lines or {}

    def where(entry: str) -> str:
        line = lines.get(entry)
        return f"{MANIFEST_REL}:{line}" if line else MANIFEST_REL

    out: list[str] = []
    if result.findings:
        out.append(
            f"Live traceability audit: {len(result.findings)} violation(s) "
            f"in {MANIFEST_REL} ({repo})"
        )
        for f in result.findings:
            out.append(f"  - [{f.rule}] entry {f.entry!r} ({where(f.entry)}): {f.message}")
        out.append("")
        out.append(
            f"Fix the entry in {MANIFEST_REL} or the issue/milestone on GitHub. A deliberate, "
            f"reasoned exception goes in {EXCEPTIONS_REL} (policy: #480)."
        )
    else:
        out.append(
            f"Live traceability audit: OK. {result.entries_checked} manifest entries, "
            f"{result.issues_referenced} issues checked against {repo}."
        )
    for f, exc in result.suppressed:
        out.append(
            f"  allowed [{f.rule}] entry {f.entry!r}: {f.message} "
            f"(exception tracked in #{exc.tracker}: {exc.reason})"
        )
    for exc in result.expired:
        out.append(
            f"  expired exception [{exc.rule}] entry {exc.entry!r} "
            f"(expired {exc.expires}, #{exc.tracker}): no longer applied"
        )
    for exc in result.unused:
        out.append(
            f"  unused exception [{exc.rule}] entry {exc.entry!r} (#{exc.tracker}): "
            f"matched nothing; remove it from {EXCEPTIONS_REL}"
        )
    out.extend(render_drift(result))
    return "\n".join(out) + "\n"


def render_drift(result: AuditResult) -> list[str]:
    """The advisory section. It says plainly that it does not change the verdict."""
    out = [
        "",
        f"Advisory drift: {len(result.drift)} observation(s) across {result.open_issues} open "
        "issue(s). Advisory only: this never changes the exit code (milestone policy: #480).",
    ]
    for rule in DRIFT_RULES:
        items = [d for d in result.drift if d.rule == rule]
        if items:
            out.append(f"  {rule} ({len(items)}):")
            out.extend(f"    - {d.message}" for d in items)
    for label in result.unused_exempt_labels:
        out.append(
            f"  unused exempt label {label!r}: no open issue carries it; check "
            f"issue_policy in {EXCEPTIONS_REL}"
        )
    return out


_STATUS = {
    EXIT_OK: "ok",
    EXIT_VIOLATION: "violations",
    EXIT_UNAVAILABLE: "not-checked",
    EXIT_CONFIG: "cannot-run",
}


def render_json(
    result: AuditResult | None,
    code: int,
    lines: dict[str, int] | None = None,
    repo: str = DEFAULT_REPO,
    reason: str | None = None,
) -> str:
    """The machine-readable outcome for the workflow artifact, written for every exit code."""
    lines = lines or {}
    doc: dict[str, Any] = {
        "schema": 1,
        "repo": repo,
        "manifest": MANIFEST_REL,
        "exceptions": EXCEPTIONS_REL,
        "exit_code": code,
        "status": _STATUS[code],
        "reason": reason,
        "violations": [],
        "drift": [],
    }
    if result is not None:

        def where(entry: str) -> str:
            line = lines.get(entry)
            return f"{MANIFEST_REL}:{line}" if line else MANIFEST_REL

        doc["entries_checked"] = result.entries_checked
        doc["issues_referenced"] = result.issues_referenced
        doc["open_issues"] = result.open_issues
        doc["violations"] = [
            {"rule": f.rule, "entry": f.entry, "location": where(f.entry), "issue": f.issue,
             "milestone": f.milestone, "message": f.message}
            for f in result.findings
        ]
        doc["suppressed"] = [
            {"rule": f.rule, "entry": f.entry, "issue": f.issue, "tracker": e.tracker,
             "reason": e.reason}
            for f, e in result.suppressed
        ]
        doc["drift"] = [
            {"rule": d.rule, "issue": d.issue, "entry": d.entry, "message": d.message}
            for d in result.drift
        ]
        doc["unused_exempt_labels"] = list(result.unused_exempt_labels)
    return json.dumps(doc, indent=2, sort_keys=True) + "\n"


def render_unavailable(reason: str) -> str:
    return (
        "Live traceability audit: NOT CHECKED. GitHub's state could not be read "
        f"({reason}).\nThis is NOT a traceability violation; nothing was verified either way. "
        "Re-run later.\n"
    )


def render_config_error(reason: str) -> str:
    return (
        f"Live traceability audit: CANNOT RUN ({reason}).\n"
        "This is a configuration problem, not a traceability violation, and retrying will not "
        "fix it.\n"
    )


# --------------------------------------------------------------------------------------
# HTTP layer (the only part that touches the network)
# --------------------------------------------------------------------------------------
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: urllib would forward the Authorization header with it."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def default_opener() -> Callable[..., Any]:
    return urllib.request.build_opener(_NoRedirect).open


def classify_failure(status: int, headers: Any) -> str:
    """Decide what an HTTP error status means: ``"transient"`` or ``"fatal"``.

    Pure so the policy is testable without a socket. Rate limiting arrives as 429, or as 403
    carrying ``Retry-After`` or ``X-RateLimit-Remaining: 0``; a bare 403 is a permission
    problem and retrying it is pointless.
    """
    get = headers.get if headers is not None else (lambda _k, _d=None: None)
    if status in (429, 500, 502, 503, 504):
        return "transient"
    if status == 403 and (get("Retry-After") or get("X-RateLimit-Remaining") == "0"):
        return "transient"
    return "fatal"


def retry_delay(attempt: int, headers: Any) -> float | None:
    """Seconds to wait before retry ``attempt`` (1-based), or ``None`` if too long to wait."""
    get = headers.get if headers is not None else (lambda _k, _d=None: None)
    retry_after = get("Retry-After")
    if retry_after and str(retry_after).isdigit():
        wait = float(retry_after)
    elif get("X-RateLimit-Remaining") == "0" and str(get("X-RateLimit-Reset") or "").isdigit():
        wait = float(get("X-RateLimit-Reset")) - time.time() + 1
    else:
        wait = float(2**attempt)
    return None if wait > MAX_WAIT_SECONDS else max(wait, 0.0)


class GitHubClient:
    """Minimal read-only GitHub REST client: GET only, bounded retries, no redirects."""

    def __init__(
        self,
        repo: str,
        token: str | None,
        api_url: str = DEFAULT_API,
        opener: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        timeout: float = 30.0,
    ) -> None:
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
            raise AuditConfigError(f"repository must look like owner/name, got {repo!r}")
        api_url = api_url.rstrip("/")
        if not api_url.startswith("https://"):
            raise AuditConfigError("the GitHub API URL must be https://")
        self.repo = repo
        self.api_url = api_url
        self._token = token
        self._opener = opener or default_opener()
        self._sleep = sleep
        self._timeout = timeout

    def _request(self, url: str) -> tuple[Any, Any]:
        # The token only ever goes to the API host: refuse any other target outright.
        if not (url == self.api_url or url.startswith(self.api_url + "/")):
            raise LiveStateUnavailable("refusing to follow a pagination link off the API host")
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "yazses-traceability-live-audit",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        last = "no attempt made"
        for attempt in range(1, MAX_ATTEMPTS + 1):
            delay: float | None = float(2**attempt)
            try:
                request = urllib.request.Request(url, headers=headers, method="GET")
                with self._opener(request, timeout=self._timeout) as response:
                    return json.loads(response.read().decode("utf-8")), response.headers
            except urllib.error.HTTPError as exc:
                kind = classify_failure(exc.code, exc.headers)
                if kind == "fatal":
                    raise AuditConfigError(_fatal_message(exc.code, self.repo)) from None
                last = f"HTTP {exc.code}"
                delay = retry_delay(attempt, exc.headers)
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
                last = f"network error ({type(exc).__name__})"
            except (ValueError, UnicodeDecodeError):
                last = "response body was not valid JSON"
            if attempt == MAX_ATTEMPTS or delay is None:
                break
            self._sleep(delay)
        raise LiveStateUnavailable(f"{last} after {attempt} attempt(s)")

    def paginate(self, path: str, params: dict[str, str]) -> list[Any]:
        """Collect every item of a list endpoint by following ``Link: rel="next"``."""
        query = urllib.parse.urlencode({**params, "per_page": "100"})
        url: str | None = f"{self.api_url}/repos/{self.repo}/{path}?{query}"
        items: list[Any] = []
        for _ in range(MAX_PAGES):
            if url is None:
                return items
            body, headers = self._request(url)
            _require(isinstance(body, list), f"{path} did not return a list")
            items.extend(body)
            url = parse_link_next(headers.get("Link") if headers is not None else None)
        raise LiveStateUnavailable(f"{path} listing exceeded {MAX_PAGES} pages (truncated)")

    def issues(self) -> dict[int, IssueFact]:
        # Ascending creation order: a new issue appends at the end instead of shifting every
        # later page, which would otherwise be able to hide a real one from the scan.
        return parse_issues(
            self.paginate("issues", {"state": "all", "sort": "created", "direction": "asc"})
        )

    def milestones(self) -> dict[int, MilestoneFact]:
        return parse_milestones(self.paginate("milestones", {"state": "all"}))


def _fatal_message(status: int, repo: str) -> str:
    if status in (401, 403):
        return f"GitHub rejected the credentials/permissions (HTTP {status}; needs issues: read)"
    if status == 404:
        return f"GitHub returned 404 for {repo}: unknown repository or no access"
    if 300 <= status < 400:
        return f"GitHub redirected the request (HTTP {status}); the repository was likely renamed"
    return f"GitHub refused the request (HTTP {status})"


# --------------------------------------------------------------------------------------
# Wiring
# --------------------------------------------------------------------------------------
def _load_offline_checker() -> Any:
    path = ROOT / "scripts" / "check-traceability.py"
    spec = importlib.util.spec_from_file_location("check_traceability_offline", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_inputs(
    manifest_path: Path, exceptions_path: Path
) -> tuple[dict[str, Any], str, list[AllowedException], IssuePolicy]:
    """Read and validate both local files. Raises :class:`AuditConfigError` on any problem."""
    import yaml

    offline = _load_offline_checker()
    try:
        manifest = offline.load_manifest(manifest_path)
    except offline.ManifestError as exc:
        raise AuditConfigError(str(exc)) from exc
    errors = offline.validate_manifest(manifest)
    if errors:
        raise AuditConfigError(
            f"{MANIFEST_REL} fails the offline check (run scripts/check-traceability.py): "
            + "; ".join(errors[:3])
        )
    text = manifest_path.read_text(encoding="utf-8")
    exceptions: list[AllowedException] = []
    policy = IssuePolicy()
    if exceptions_path.exists():
        try:
            data = yaml.safe_load(exceptions_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            raise AuditConfigError(f"cannot read {EXCEPTIONS_REL}: {exc}") from exc
        exceptions = parse_exceptions(data)
        policy = parse_issue_policy(data)
    return manifest, text, exceptions, policy


def _write_summary(path: str, body: str, title: str) -> None:
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"### {title}\n\n```\n{body}```\n")
    except OSError:
        pass  # a missing summary file must not change the verdict


def _write_json(path: str, text: str) -> None:
    try:
        Path(path).write_text(text, encoding="utf-8")
    except OSError:
        pass  # an unwritable artifact path must not change the verdict either


def run(
    argv: list[str] | None = None,
    client_factory: Callable[[str, str | None, str], GitHubClient] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPO)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--exceptions", type=Path, default=EXCEPTIONS)
    parser.add_argument("--summary-file", help="append the report here (GITHUB_STEP_SUMMARY)")
    parser.add_argument("--json-file", help="write the outcome as JSON here (workflow artifact)")
    args = parser.parse_args(argv)

    def finish(code: int, body: str, title: str, payload: str) -> int:
        stream = sys.stdout if code == EXIT_OK else sys.stderr
        stream.write(body)
        if args.summary_file:
            _write_summary(args.summary_file, body, title)
        if args.json_file:
            _write_json(args.json_file, payload)
        return code

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    api_url = os.environ.get("GITHUB_API_URL") or DEFAULT_API
    try:
        manifest, text, exceptions, policy = load_inputs(args.manifest, args.exceptions)
        factory = client_factory or (lambda repo, tok, api: GitHubClient(repo, tok, api))
        client = factory(args.repo, token, api_url)
        issues = client.issues()
        milestones = client.milestones()
    except AuditConfigError as exc:
        return finish(
            EXIT_CONFIG,
            render_config_error(str(exc)),
            "Traceability: cannot run",
            render_json(None, EXIT_CONFIG, repo=args.repo, reason=str(exc)),
        )
    except LiveStateUnavailable as exc:
        return finish(
            EXIT_UNAVAILABLE,
            render_unavailable(str(exc)),
            "Traceability: not checked",
            render_json(None, EXIT_UNAVAILABLE, repo=args.repo, reason=str(exc)),
        )

    result = audit(manifest, issues, milestones, exceptions, policy=policy)
    code = exit_code_for(result)
    lines = locate_entries(text)
    body = render_report(result, lines, args.repo)
    title = "Traceability: violations" if code else "Traceability: OK"
    return finish(code, body, title, render_json(result, code, lines, args.repo))


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
