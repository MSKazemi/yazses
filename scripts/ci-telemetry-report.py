#!/usr/bin/env python3
"""Fetch this repository's GitHub Actions runs and write the CI telemetry report (#536).

The thin, networked half of the report; every number is computed by the pure
`scripts/ci_telemetry.py`. This file only fetches, bounds and writes.

    GH_TOKEN=$(gh auth token) python3 scripts/ci-telemetry-report.py \\
        --repo MSKazemi/yazses --out-json ci-telemetry.json --out-md ci-telemetry.md

What it does on the network, all of it:

- **Read-only.** Every request is an HTTP `GET` to the GitHub REST API (`GITHUB_API_URL`,
  default `https://api.github.com`). It sends nothing but the token and the query.
- **Bounded.** The window is `--days` (default 14, at most 90), fetched one 24-hour slice
  at a time, because the runs API returns at most 1,000 results for a filtered query.
  A slice that reports more than that is recorded as truncated. Runs are capped by
  `--max-runs`; job lists are fetched for at most `--max-job-runs` completed runs, failed
  runs first and then newest first. Fetching stops early when the rate-limit budget
  falls to `--rate-limit-reserve`, so a shared `GITHUB_TOKEN` (1,000 requests an hour per
  repository) is never exhausted for the other workflows. Every bound that bit is written
  into the report's `coverage.notes`, so a partial report says it is partial.
- **Private by construction.** Raw records go straight into the pure module, which keeps
  an allow-list of fields; the JSON artifact is the aggregate report, never raw records.

The token is read from `GH_TOKEN` or `GITHUB_TOKEN` and never accepted on the command
line, where it would be visible in the process list. It is never printed.

Exit status: 0 when the report was written (missed SLOs included: this reports, it does
not gate), 1 when the API could not be read, 2 for a usage error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:  # scripts/ is not a package; run as a script, its directory is already on sys.path
    import ci_telemetry
except ModuleNotFoundError:  # pragma: no cover - imported from elsewhere
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import ci_telemetry

PER_PAGE = 100
#: The runs API stops at 1,000 results for a query filtered by `created`.
SEARCH_CAP = 1000
MAX_JOB_PAGES = 3
TIMEOUT_S = 30
USER_AGENT = "yazses-ci-telemetry"

#: (parsed JSON, response headers with lower-cased names)
Response = tuple[Any, Mapping[str, str]]
Transport = Callable[[str], Response]


class ApiError(RuntimeError):
    """The API could not be read. The message never contains the token."""


def http_get(token: str, *, opener: Callable[..., Any] = urllib.request.urlopen) -> Transport:
    """A GET-only transport. One retry on a 5xx or a dropped connection, nothing else."""

    def get(url: str) -> Response:
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "User-Agent": USER_AGENT,
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        for attempt in (1, 2):
            try:
                with opener(request, timeout=TIMEOUT_S) as response:
                    body = response.read().decode("utf-8")
                    headers = {k.lower(): v for k, v in response.headers.items()}
                    return json.loads(body), headers
            except urllib.error.HTTPError as exc:
                if exc.code >= 500 and attempt == 1:
                    time.sleep(2)
                    continue
                raise ApiError(f"GET {_redact(url)} failed: HTTP {exc.code}") from None
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt == 1:
                    time.sleep(2)
                    continue
                reason = getattr(exc, "reason", exc)
                raise ApiError(f"GET {_redact(url)} failed: {reason}") from None
            except json.JSONDecodeError:
                raise ApiError(f"GET {_redact(url)} returned something that is not JSON") from None
        raise ApiError(f"GET {_redact(url)} failed")  # pragma: no cover - loop always returns

    return get


def _redact(url: str) -> str:
    """The URL without its query string; a query never holds the token, but keep it short."""
    return url.split("?", 1)[0]


@dataclass
class Fetcher:
    api: str
    repo: str
    get: Transport
    reserve: int = 200
    requests: int = 0
    remaining: int | None = None
    notes: list[str] = field(default_factory=list)

    def call(self, path: str, **query: Any) -> Any:
        url = f"{self.api.rstrip('/')}/repos/{self.repo}" + (f"/{path}" if path else "")
        if query:
            url += "?" + urllib.parse.urlencode(query, safe=":.")
        data, headers = self.get(url)
        self.requests += 1
        value = headers.get("x-ratelimit-remaining")
        if value is not None and value.isdigit():
            self.remaining = int(value)
        return data

    @property
    def budget_exhausted(self) -> bool:
        return self.remaining is not None and self.remaining <= self.reserve


def _slices(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """24-hour slices covering [start, end]. The API's ranges are inclusive at both ends,
    so neighbouring slices share their boundary second; runs are de-duplicated by id."""
    out = []
    cursor = start
    while cursor < end:
        stop = min(cursor + timedelta(days=1), end)
        out.append((cursor, stop))
        cursor = stop
    return out


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_runs(f: Fetcher, start: datetime, end: datetime, *, max_runs: int) -> list[dict]:
    runs: dict[int, dict] = {}
    for lo, hi in _slices(start, end):
        page = 1
        while True:
            if len(runs) >= max_runs:
                f.notes.append(f"stopped at --max-runs {max_runs}; older runs are missing")
                return list(runs.values())
            if f.budget_exhausted:
                f.notes.append("stopped listing runs at the rate-limit reserve; the window is incomplete")
                return list(runs.values())
            data = f.call("actions/runs", created=f"{_stamp(lo)}..{_stamp(hi)}",
                          per_page=PER_PAGE, page=page)
            batch = data.get("workflow_runs", []) if isinstance(data, Mapping) else []
            total = data.get("total_count", 0) if isinstance(data, Mapping) else 0
            for raw in batch:
                if isinstance(raw, Mapping) and isinstance(raw.get("id"), int):
                    runs.setdefault(raw["id"], dict(raw))
            if page == 1 and isinstance(total, int) and total > SEARCH_CAP:
                f.notes.append(f"{_stamp(lo)[:10]}: {total} runs, API returns only {SEARCH_CAP}")
            if len(batch) < PER_PAGE or page * PER_PAGE >= min(total, SEARCH_CAP):
                break
            page += 1
    return list(runs.values())


def pick_job_runs(runs: list[Mapping[str, Any]], limit: int) -> list[int]:
    """Completed runs to fetch jobs for: failures first, then newest first."""
    completed = [r for r in runs if r.get("status") == "completed" and isinstance(r.get("id"), int)]
    # Two stable sorts: newest first, then failures ahead of everything else.
    completed.sort(key=lambda r: (str(r.get("created_at") or ""), r["id"]), reverse=True)
    completed.sort(key=lambda r: ci_telemetry.outcome_of(r.get("conclusion")) != ci_telemetry.FAILURE)
    return [r["id"] for r in completed[:limit]]


def fetch_jobs(f: Fetcher, run_ids: list[int]) -> dict[int, list[dict]]:
    jobs: dict[int, list[dict]] = {}
    for run_id in run_ids:
        if f.budget_exhausted:
            f.notes.append(
                f"job lists fetched for {len(jobs)} of {len(run_ids)} selected runs: "
                "stopped at the rate-limit reserve")
            break
        records: list[dict] = []
        for page in range(1, MAX_JOB_PAGES + 1):
            data = f.call(f"actions/runs/{run_id}/jobs", filter="latest",
                          per_page=PER_PAGE, page=page)
            batch = data.get("jobs", []) if isinstance(data, Mapping) else []
            records += [dict(j) for j in batch if isinstance(j, Mapping)]
            if len(batch) < PER_PAGE:
                break
        jobs[run_id] = records
    return jobs


def fetch_workflows(f: Fetcher) -> list[dict]:
    data = f.call("actions/workflows", per_page=PER_PAGE)
    items = data.get("workflows", []) if isinstance(data, Mapping) else []
    return [{"name": w.get("name"), "path": w.get("path"), "state": w.get("state")}
            for w in items if isinstance(w, Mapping)]


def collect(
    get: Transport,
    *,
    api: str,
    repo: str,
    days: int,
    now: datetime,
    max_runs: int,
    max_job_runs: int,
    reserve: int,
    default_branch: str | None,
) -> dict[str, Any]:
    f = Fetcher(api=api, repo=repo, get=get, reserve=reserve)
    if default_branch is None:
        meta = f.call("")
        default_branch = meta.get("default_branch", "main") if isinstance(meta, Mapping) else "main"
    end = now.replace(microsecond=0)
    start = end - timedelta(days=days)
    workflows = fetch_workflows(f)
    runs = fetch_runs(f, start, end, max_runs=max_runs)
    selected = pick_job_runs(runs, max_job_runs)
    completed = sum(1 for r in runs if r.get("status") == "completed")
    if completed > len(selected):
        f.notes.append(f"job lists limited to {len(selected)} of {completed} completed runs "
                       f"(--max-job-runs {max_job_runs}; failures first)")
    jobs = fetch_jobs(f, selected)
    report = ci_telemetry.build_report(
        runs, jobs,
        window_start=start, window_end=end, default_branch=str(default_branch),
        workflows_raw=workflows, repository=repo,
        coverage={"job_lists_fetched": len(jobs), "api_requests": f.requests,
                  "rate_limit_remaining": f.remaining, "notes": list(f.notes)},
    )
    report["generated_at"] = ci_telemetry._iso(end)
    return report


def _bounded_int(lo: int, hi: int) -> Callable[[str], int]:
    def parse(text: str) -> int:
        try:
            value = int(text)
        except ValueError:
            raise argparse.ArgumentTypeError(f"not an integer: {text!r}") from None
        if not lo <= value <= hi:
            raise argparse.ArgumentTypeError(f"must be between {lo} and {hi}, got {value}")
        return value
    return parse


def main(argv: list[str] | None = None, *, transport: Transport | None = None,
         now: datetime | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"),
                        help="OWNER/NAME (default: $GITHUB_REPOSITORY)")
    parser.add_argument("--days", type=_bounded_int(1, 90), default=14,
                        help="observation window in days (1-90, default 14)")
    parser.add_argument("--max-runs", type=_bounded_int(1, 20000), default=5000)
    parser.add_argument("--max-job-runs", type=_bounded_int(0, 5000), default=1000)
    parser.add_argument("--rate-limit-reserve", type=_bounded_int(0, 5000), default=200)
    parser.add_argument("--default-branch", default=None,
                        help="default: read from the repository")
    parser.add_argument("--top", type=_bounded_int(1, 100), default=10)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-md", type=Path, required=True)
    args = parser.parse_args(argv)

    if not args.repo or args.repo.count("/") != 1 or any(c in args.repo for c in "?#& "):
        parser.error("--repo must be OWNER/NAME")
    if transport is None:
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if not token:
            parser.error("set GH_TOKEN or GITHUB_TOKEN (read-only actions scope is enough)")
        transport = http_get(token)

    api = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    try:
        report = collect(
            transport, api=api, repo=args.repo, days=args.days,
            now=now or datetime.now(timezone.utc), max_runs=args.max_runs,
            max_job_runs=args.max_job_runs, reserve=args.rate_limit_reserve,
            default_branch=args.default_branch,
        )
    except ApiError as exc:
        print(f"ci-telemetry: {exc}", file=sys.stderr)
        return 1

    args.out_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.out_md.write_text(ci_telemetry.render_markdown(report, top=args.top), encoding="utf-8")
    cov = report["coverage"]
    print(f"ci-telemetry: {cov['runs']} runs, jobs for {cov['runs_with_jobs']}, "
          f"{cov['api_requests']} API requests; wrote {args.out_json} and {args.out_md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
