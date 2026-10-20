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

Exit codes (a transient outage must never read as a traceability finding)
------------------------------------------------------------------------
``0``  every live check passed (exceptions are listed, never silent)
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
        out[number] = IssueFact(
            number=number,
            state=state,
            is_pull_request="pull_request" in raw,
            milestone=ms_number,
            title=str(raw.get("title") or ""),
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


@dataclass
class AuditResult:
    findings: list[Finding] = field(default_factory=list)
    suppressed: list[tuple[Finding, AllowedException]] = field(default_factory=list)
    expired: list[AllowedException] = field(default_factory=list)
    unused: list[AllowedException] = field(default_factory=list)
    entries_checked: int = 0
    issues_referenced: int = 0


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
) -> AuditResult:
    """Run every live check and apply the explicit exception allowlist."""
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
    return "\n".join(out) + "\n"


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
) -> tuple[dict[str, Any], str, list[AllowedException]]:
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
    if exceptions_path.exists():
        try:
            exceptions = parse_exceptions(yaml.safe_load(exceptions_path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            raise AuditConfigError(f"cannot read {EXCEPTIONS_REL}: {exc}") from exc
    return manifest, text, exceptions


def _write_summary(path: str, body: str, title: str) -> None:
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"### {title}\n\n```\n{body}```\n")
    except OSError:
        pass  # a missing summary file must not change the verdict


def run(
    argv: list[str] | None = None,
    client_factory: Callable[[str, str | None, str], GitHubClient] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPO)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--exceptions", type=Path, default=EXCEPTIONS)
    parser.add_argument("--summary-file", help="append the report here (GITHUB_STEP_SUMMARY)")
    args = parser.parse_args(argv)

    def finish(code: int, body: str, title: str) -> int:
        stream = sys.stdout if code == EXIT_OK else sys.stderr
        stream.write(body)
        if args.summary_file:
            _write_summary(args.summary_file, body, title)
        return code

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    api_url = os.environ.get("GITHUB_API_URL") or DEFAULT_API
    try:
        manifest, text, exceptions = load_inputs(args.manifest, args.exceptions)
        factory = client_factory or (lambda repo, tok, api: GitHubClient(repo, tok, api))
        client = factory(args.repo, token, api_url)
        issues = client.issues()
        milestones = client.milestones()
    except AuditConfigError as exc:
        return finish(EXIT_CONFIG, render_config_error(str(exc)), "Traceability: cannot run")
    except LiveStateUnavailable as exc:
        return finish(EXIT_UNAVAILABLE, render_unavailable(str(exc)), "Traceability: not checked")

    result = audit(manifest, issues, milestones, exceptions)
    code = exit_code_for(result)
    body = render_report(result, locate_entries(text), args.repo)
    title = "Traceability: violations" if code else "Traceability: OK"
    return finish(code, body, title)


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
