"""The CI telemetry report computes the right numbers and leaks nothing (#536).

`scripts/ci_telemetry.py` turns GitHub Actions run and job records into the report a
maintainer reads to answer "what is consuming CI, and where are contributors waiting?"
(`.github/CI_POLICY.md` §12.1). A wrong number there is worse than none: it sends the
owner after the wrong workflow. So each metric is pinned against a hand-computed value
on a synthetic fixture, `tests/fixtures/ci_telemetry/`, built so that every rule in the
module's docstring has one case that exercises it — a rewritten `updated_at`, a fork PR
with an empty `pull_requests`, an approval-gated successor, a cancelled run inside a red
streak, a duplicate record, a run outside the window.

The fixture's runs also carry the fields the real API sends and the report must never
repeat: commit author emails, commit messages, PR titles, actor logins, fork owners,
branch names, runner names. Two privacy guards check the output for those values, and
for any JSON key outside a reviewed allow-list.

`scripts/ci-telemetry-report.py`, the fetcher, is tested through a fake transport: no
test opens a connection. The workflow's contract (triggers, permissions, retention, not
a gate) is pinned at the end.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
FIXTURES = ROOT / "tests" / "fixtures" / "ci_telemetry"
WORKFLOW = ROOT / ".github" / "workflows" / "ci-telemetry.yml"


def _load(name: str, filename: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


ct = _load("ci_telemetry", "ci_telemetry.py")
rep = _load("ci_telemetry_report", "ci-telemetry-report.py")

START = datetime(2026, 10, 1, tzinfo=timezone.utc)
END = datetime(2026, 10, 15, tzinfo=timezone.utc)

#: Values present in the fixture that must never reach the report.
PERSONAL = (
    "synthetic.author@example.invalid",
    "Synthetic Author",
    "SYNTHETIC-COMMIT-MESSAGE",
    "SYNTHETIC-PR-TITLE",
    "Synthetic run title",
    "synthetic-actor",
    "synthetic-fork-owner",
    "SYNTHETIC-FORK-BRANCH",
    "SYNTHETIC-RUNNER",
    "feature-a",
    "@",
)


def _fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def report() -> dict[str, Any]:
    return ct.build_report(
        _fixture("runs.json"), {int(k): v for k, v in _fixture("jobs.json").items()},
        window_start=START, window_end=END, default_branch="main",
        workflows_raw=_fixture("workflows.json"), repository="example/yazses",
    )


def _row(rows: list[dict], **match: Any) -> dict:
    found = [r for r in rows if all(r.get(k) == v for k, v in match.items())]
    assert len(found) == 1, f"expected one row matching {match}, got {found}"
    return found[0]


# ------------------------------------------------------------------------- the maths


@pytest.mark.parametrize(("values", "q", "expected"), [
    (list(range(1, 21)), 95, 19),   # nearest rank: ceil(0.95 * 20) = 19th smallest
    (list(range(1, 21)), 50, 10),
    (list(range(1, 21)), 100, 20),
    ([7.0], 95, 7.0),
    ([3, 1, 2], 50, 2),             # input order does not matter
    ([], 95, None),
])
def test_percentile_is_nearest_rank(values: list[float], q: float, expected: float | None) -> None:
    assert ct.percentile(values, q) == expected


def test_percentile_rejects_an_out_of_range_rank() -> None:
    with pytest.raises(ValueError):
        ct.percentile([1, 2], 101)


@pytest.mark.parametrize(("conclusion", "outcome"), [
    ("success", "success"), ("failure", "failure"), ("timed_out", "failure"),
    ("startup_failure", "failure"), ("cancelled", "cancelled"), ("skipped", "other"),
    ("action_required", "other"), ("neutral", "other"), (None, "other"),
])
def test_outcome_classes(conclusion: str | None, outcome: str) -> None:
    assert ct.outcome_of(conclusion) == outcome


# ------------------------------------------------------------------- volume, outcomes


def test_window_and_duplicates(report: dict) -> None:
    # 19 records: run 999 is outside the window and run 101 appears twice.
    assert report["totals"]["runs"] == 17
    assert report["totals"]["completed"] == 16
    assert report["totals"]["incomplete"] == 1
    assert report["window"] == {"start": "2026-10-01T00:00:00Z", "end": "2026-10-15T00:00:00Z",
                                "days": 14.0, "default_branch": "main"}


def test_outcome_percentages(report: dict) -> None:
    totals = report["totals"]
    assert totals["counts"] == {"success": 6, "failure": 6, "cancelled": 3, "other": 1}
    assert totals["percent"] == {"success": 37.5, "failure": 37.5, "cancelled": 18.8, "other": 6.2}


def test_run_count_by_workflow_and_event(report: dict) -> None:
    counts = {(r["workflow"], r["event"]): r["runs"] for r in report["by_workflow_event"]}
    assert counts == {
        ("Tests", "push"): 2, ("Tests", "pull_request"): 9,
        ("Nightly", "schedule"): 4, ("Docs", "pull_request"): 1, ("Docs", "push"): 1,
    }


def test_job_queue_latency_excludes_skipped_jobs(report: dict) -> None:
    tests = _row(report["workflows"], workflow="Tests")
    # 10 jobs ran (the skipped `macos` job never queued):
    # 5, 10, 10, 20, 30, 60, 60, 60, 120, 120 seconds
    assert tests["job_queue"] == {"n": 10, "p50_s": 30.0, "p95_s": 120.0, "max_s": 120.0}


def test_run_duration_comes_from_jobs_not_from_a_rewritten_updated_at() -> None:
    runs = [r for r in _fixture("runs.json") if r["id"] == 102]
    jobs = {102: _fixture("jobs.json")["102"]}
    out = ct.build_report(runs, jobs, window_start=START, window_end=END)
    # updated_at says 2 days 9 hours; the last job finished 15 minutes after the start.
    assert out["totals"]["run_duration"]["p95_s"] == 900.0


def test_a_run_whose_jobs_were_not_fetched_has_no_duration() -> None:
    runs = [r for r in _fixture("runs.json") if r["id"] == 102]
    out = ct.build_report(runs, {}, window_start=START, window_end=END)
    assert out["totals"]["run_duration"]["n"] == 0


def test_dynamic_workflows_are_named_by_path() -> None:
    raw = {"id": 1, "name": "uv in /. for Pillow - Update #1640658397",
           "path": "dynamic/dependabot/dependabot-updates", "event": "dynamic",
           "status": "completed", "conclusion": "success",
           "created_at": "2026-10-02T00:00:00Z"}
    run = ct.project_run(raw, default_branch="main")
    assert run is not None and run.workflow == "dynamic/dependabot/dependabot-updates"


@pytest.mark.parametrize("raw", [{}, {"id": "7", "created_at": "2026-10-02T00:00:00Z"},
                                 {"id": 7, "created_at": "yesterday"}])
def test_an_unusable_run_record_is_dropped(raw: dict) -> None:
    assert ct.project_run(raw, default_branch="main") is None


# ------------------------------------------------------------- superseded PR runs


def test_superseded_runs(report: dict) -> None:
    sup = report["superseded"]
    # 103 -> 104 (cancelled 30 s later), 105 -> 106 (ran on), 107 -> 108 (fork PR,
    # cancelled 30 s later, end from updated_at because its jobs were not fetched).
    # 109 -> 110 is not one: 110 waited for approval and never started.
    assert sup["pr_runs"] == 10
    assert sup["superseded"] == 3
    assert sup["superseded_cancelled"] == 2
    assert sup["cancellation_rate_percent"] == 66.7
    assert sup["share_of_pr_runs_percent"] == 30.0
    assert sup["cancel_delay"] == {"n": 2, "p50_s": 30.0, "p95_s": 30.0, "max_s": 30.0}
    assert sup["ran_to_completion_by_workflow"] == [{"workflow": "Tests", "runs": 1}]


def test_supersession_needs_the_same_pull_request() -> None:
    base = {"name": "Tests", "path": ".github/workflows/test.yml", "event": "pull_request",
            "status": "completed", "conclusion": "success"}
    runs = [
        {**base, "id": 1, "created_at": "2026-10-02T10:00:00Z", "updated_at": "2026-10-02T10:30:00Z",
         "pull_requests": [{"number": 1}]},
        {**base, "id": 2, "created_at": "2026-10-02T10:05:00Z", "updated_at": "2026-10-02T10:35:00Z",
         "pull_requests": [{"number": 2}]},
    ]
    projected = [ct.project_run(r, default_branch="main") for r in runs]
    assert ct.superseded_runs([r for r in projected if r]) == []


def test_a_rerun_is_not_superseded_by_a_run_created_before_it_started() -> None:
    base = {"name": "Tests", "path": ".github/workflows/test.yml", "event": "pull_request",
            "status": "completed", "conclusion": "success", "pull_requests": [{"number": 1}]}
    runs = [
        # first created at 10:00, re-run (attempt 2) at 12:00
        {**base, "id": 1, "created_at": "2026-10-02T10:00:00Z", "run_attempt": 2,
         "run_started_at": "2026-10-02T12:00:00Z", "updated_at": "2026-10-02T12:30:00Z"},
        {**base, "id": 2, "created_at": "2026-10-02T11:00:00Z",
         "updated_at": "2026-10-02T11:20:00Z"},
    ]
    projected = [ct.project_run(r, default_branch="main") for r in runs]
    assert ct.superseded_runs([r for r in projected if r]) == []


# ---------------------------------------------------------- jobs, failures, red state


def test_longest_jobs_by_p95(report: dict) -> None:
    first = report["longest_jobs"][0]
    assert (first["workflow"], first["job"]) == ("Tests", "build")
    assert first["n"] == 9
    assert first["p95_s"] == 3540.0  # run 111's build timed out after 59 minutes
    assert [(j["workflow"], j["job"]) for j in report["longest_jobs"]] == [
        ("Tests", "build"), ("Nightly", "fuzz"), ("Tests", "ci-gate"),
    ]


def test_workflows_with_no_success_and_no_runs(report: dict) -> None:
    assert [r["workflow"] for r in report["no_success"]] == ["Docs"]
    assert _row(report["no_success"], workflow="Docs")["failure"] == 1
    # Release never ran; the disabled workflow is not reported.
    assert report["no_runs"] == [{"workflow": "Release", "path": ".github/workflows/release.yml"}]


def test_repeated_failures_by_workflow_job_and_step(report: dict) -> None:
    rows = [(r["workflow"], r["job"], r["step"], r["runs"]) for r in report["repeated_failures"]]
    # The timed-out build (no failed step) failed once, so it is not "repeated";
    # run 999's identical failure is outside the window.
    assert rows == [("Nightly", "fuzz", "Fuzz the parser", 2), ("Tests", "build", "Run tests", 2)]
    tests = _row(report["repeated_failures"], workflow="Tests")
    assert tests["last_run_id"] == 104 and tests["events"] == ["pull_request"]


def test_a_failed_job_without_a_failed_step_is_named_so() -> None:
    job = ct.project_job({"name": "build", "conclusion": "timed_out", "steps": [
        {"name": "Run tests", "conclusion": "success"}]}, run_id=1)
    assert job.failed_step == ct.NO_FAILED_STEP


def test_red_on_the_default_branch(report: dict) -> None:
    red = report["red_on_default_branch"]
    assert [r["workflow"] for r in red] == ["Nightly", "Tests"]
    nightly, tests = red
    # The cancelled run on 10-12 neither breaks nor extends the streak.
    assert nightly["red_since"] == "2026-10-11T03:00:00Z"
    assert nightly["failed_runs_in_streak"] == 2
    assert nightly["slo_limit_s"] == ct.SLO_SCHEDULED_RED_S
    assert nightly["over_slo"] is False
    assert tests["red_since"] == "2026-10-13T00:00:00Z"
    assert tests["red_for_s"] == 48 * 3600
    assert tests["over_slo"] is True


def test_slo_rows_report_facts_and_never_raise(report: dict) -> None:
    status = {row["name"].split(" (")[0]: row["status"] for row in report["slo"]}
    assert status == {
        "PR job queue delay p95": "met",                 # 120 s < 5 min
        "Fast PR gate execution p95": "n/a",             # no fast lane yet (#535)
        "Superseded PR run cancellation delay p95": "met",  # 30 s < 2 min
        "Default-branch workflows red > 24 h": "missed",  # Tests, 48 h
        "Scheduled workflows red > 7 days": "met",       # Nightly, under 4 days
    }
    empty = ct.build_report([], {}, window_start=START, window_end=END)
    assert {row["status"] for row in empty["slo"]} <= {"no data", "n/a", "met"}


# ------------------------------------------------------------------------- privacy


def test_no_personal_value_reaches_the_report(report: dict) -> None:
    text = json.dumps(report) + ct.render_markdown(report)
    leaked = [value for value in PERSONAL if value in text]
    assert not leaked, f"the report carries data it must not: {leaked}"


#: Every JSON key the report may contain. A new key is a new published field, so adding
#: one here is a reviewed privacy decision, not a formality.
ALLOWED_KEYS = {
    "schema", "repository", "window", "start", "end", "days", "default_branch",
    "coverage", "runs", "runs_with_jobs", "jobs", "jobs_ran", "api_requests",
    "rate_limit_remaining", "job_lists_fetched", "notes", "totals", "incomplete", "completed", "counts",
    "percent", "success", "failure", "cancelled", "other", "run_duration", "job_queue",
    "job_minutes", "n", "p50_s", "p95_s", "max_s", "workflows", "workflow", "path",
    "success_percent", "failure_percent", "cancelled_percent", "other_percent", "outcomes",
    "by_workflow_event", "event", "superseded", "pr_runs", "superseded_cancelled",
    "cancellation_rate_percent", "share_of_pr_runs_percent", "cancel_delay",
    "ran_to_completion_by_workflow", "longest_jobs", "job", "total_minutes", "no_success",
    "no_runs", "repeated_failures", "step", "events", "last_seen", "last_run_id",
    "red_on_default_branch", "failed_runs_in_streak", "red_since", "red_for_s",
    "slo_limit_s", "over_slo", "latest_run_id", "slo", "name", "target_s", "value_s",
    "status", "note", "generated_at",
}


def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


def test_the_report_has_only_reviewed_keys(report: dict) -> None:
    unexpected = _keys(report) - ALLOWED_KEYS
    assert not unexpected, f"new report fields need a privacy review: {sorted(unexpected)}"


def test_a_projected_run_keeps_no_personal_field() -> None:
    raw = next(r for r in _fixture("runs.json") if r["id"] == 107)
    run = ct.project_run(raw, default_branch="main")
    assert run is not None
    assert run.pr_key is not None and run.pr_key.startswith("h:")  # hashed, fork PR
    leaked = [value for value in PERSONAL if value in repr(run) + str(run.pr_key)]
    assert not leaked


@pytest.mark.parametrize("hostile", [
    "evil | column", "line\nbreak", "<img src=x onerror=alert(1)>", "[click](http://x)",
    "`code`", "x" * 500,
])
def test_names_cannot_break_the_markdown(hostile: str) -> None:
    cell = ct.md_escape(hostile)
    assert "\n" not in cell and "<" not in cell and "`" not in cell
    assert "|" not in cell.replace("\\|", "")
    assert "](" not in cell.replace("\\]", "")  # an escaped bracket cannot open a link
    assert len(cell) <= ct.MAX_NAME + 20


def test_a_hostile_job_name_is_escaped_in_the_rendered_report() -> None:
    runs = [r for r in _fixture("runs.json") if r["id"] in (102, 104)]
    jobs = _fixture("jobs.json")
    evil = "<script>alert(1)</script> | x"
    hostile = {rid: [{**j, "name": evil} for j in jobs[str(rid)]] for rid in (102, 104)}
    page = ct.render_markdown(ct.build_report(runs, hostile, window_start=START, window_end=END))
    assert "<script>" not in page
    assert "&lt;script&gt;" in page


@pytest.mark.parametrize(("seconds", "text"), [
    (None, "–"), (4, "4s"), (65, "1m 05s"), (3600, "1h 00m"), (49 * 3600, "2d 01h"),
])
def test_fmt_duration(seconds: float | None, text: str) -> None:
    assert ct.fmt_duration(seconds) == text


def test_render_markdown_has_every_section(report: dict) -> None:
    page = ct.render_markdown(report)
    for heading in ("## SLO facts", "## What is consuming CI", "## Runs by workflow and event",
                    "## Superseded pull-request runs", "## Longest jobs",
                    "## Red on the default branch", "## Workflows with no successful run",
                    "## Repeated failures"):
        assert heading in page


# ------------------------------------------------------------------------- the fetcher


class FakeApi:
    """A recorded GitHub API: answers by path, counts calls, never opens a socket."""

    def __init__(self, *, runs: list[dict], jobs: dict[str, list[dict]],
                 remaining: int = 4000, totals: dict[int, int] | None = None) -> None:
        self.runs, self.jobs, self.remaining = runs, jobs, remaining
        self.totals = totals or {}
        self.urls: list[str] = []

    def __call__(self, url: str) -> tuple[Any, dict[str, str]]:
        self.urls.append(url)
        self.remaining -= 1
        headers = {"x-ratelimit-remaining": str(self.remaining)}
        parsed = urllib.parse.urlparse(url)
        query = dict(urllib.parse.parse_qsl(parsed.query))
        path = parsed.path.removeprefix("/repos/example/yazses")
        if path == "":
            return {"default_branch": "main"}, headers
        if path == "/actions/workflows":
            return {"workflows": _fixture("workflows.json")}, headers
        if path == "/actions/runs":
            lo, hi = query["created"].split("..")
            hits = [r for r in self.runs if lo <= r["created_at"] <= hi]
            page, per = int(query["page"]), int(query["per_page"])
            total = self.totals.get(len(self.urls), len(hits))
            return {"total_count": total, "workflow_runs": hits[(page - 1) * per: page * per]}, headers
        if path.startswith("/actions/runs/") and path.endswith("/jobs"):
            run_id = path.split("/")[3]
            return {"jobs": self.jobs.get(run_id, [])}, headers
        raise AssertionError(f"unexpected request {url}")


def _collect(api: FakeApi, **overrides: Any) -> dict:
    kwargs: dict[str, Any] = {
        "api": "https://api.github.com", "repo": "example/yazses", "days": 14, "now": END,
        "max_runs": 5000, "max_job_runs": 1000, "reserve": 200, "default_branch": None,
    }
    kwargs.update(overrides)
    return rep.collect(api, **kwargs)


def test_collect_fetches_the_window_in_daily_slices() -> None:
    api = FakeApi(runs=_fixture("runs.json"), jobs=_fixture("jobs.json"))
    out = _collect(api)
    slices = [u for u in api.urls if "/actions/runs?" in u]
    assert len(slices) == 14
    assert all("per_page=100" in u for u in slices)
    assert out["totals"]["runs"] == 17
    assert out["coverage"]["notes"] == []
    assert out["generated_at"] == "2026-10-15T00:00:00Z"


def test_every_request_is_inside_the_repository() -> None:
    api = FakeApi(runs=_fixture("runs.json"), jobs=_fixture("jobs.json"))
    _collect(api)
    assert api.urls and all(u.startswith("https://api.github.com/repos/example/yazses") for u in api.urls)
    assert not any("/logs" in u for u in api.urls), "the report must never download logs"


def test_runs_are_paginated_and_capped_at_the_search_limit() -> None:
    runs = [{"id": i, "status": "completed", "conclusion": "success", "name": "Tests",
             "path": ".github/workflows/test.yml", "event": "push", "head_branch": "main",
             "created_at": "2026-10-14T12:00:00Z"} for i in range(1, 1201)]
    api = FakeApi(runs=runs, jobs={})
    out = _collect(api, days=1, max_job_runs=0)
    pages = [u for u in api.urls if "/actions/runs?" in u]
    assert len(pages) == 10  # 1,000 results is the API's ceiling for a filtered query
    assert out["totals"]["runs"] == 1000
    assert any("API returns only 1000" in note for note in out["coverage"]["notes"])


def test_max_runs_bounds_the_listing() -> None:
    api = FakeApi(runs=_fixture("runs.json"), jobs=_fixture("jobs.json"))
    out = _collect(api, max_runs=3)
    assert any("--max-runs 3" in note for note in out["coverage"]["notes"])


def test_job_fetching_stops_at_the_rate_limit_reserve() -> None:
    api = FakeApi(runs=_fixture("runs.json"), jobs=_fixture("jobs.json"), remaining=220)
    out = _collect(api)
    assert any("rate-limit reserve" in note for note in out["coverage"]["notes"])
    assert api.remaining >= 200 - 1  # stopped at the reserve, did not run the budget dry
    assert out["coverage"]["runs_with_jobs"] < 16


def test_job_lists_are_bounded_and_failures_come_first() -> None:
    runs = [
        {"id": 1, "status": "completed", "conclusion": "success", "created_at": "2026-10-03T00:00:00Z"},
        {"id": 2, "status": "completed", "conclusion": "failure", "created_at": "2026-10-01T00:00:00Z"},
        {"id": 3, "status": "completed", "conclusion": "success", "created_at": "2026-10-05T00:00:00Z"},
        {"id": 4, "status": "in_progress", "conclusion": None, "created_at": "2026-10-06T00:00:00Z"},
        {"id": 5, "status": "completed", "conclusion": "timed_out", "created_at": "2026-10-02T00:00:00Z"},
    ]
    assert rep.pick_job_runs(runs, 10) == [5, 2, 3, 1]
    assert rep.pick_job_runs(runs, 3) == [5, 2, 3]


def test_slices_cover_the_window() -> None:
    slices = rep._slices(START, END)
    assert len(slices) == 14
    assert slices[0][0] == START and slices[-1][1] == END
    assert all(a[1] == b[0] for a, b in zip(slices, slices[1:]))


# ------------------------------------------------------------------- http and CLI


class _Response(io.BytesIO):
    def __init__(self, body: Any, headers: dict[str, str]) -> None:
        super().__init__(json.dumps(body).encode("utf-8"))
        self.headers = headers

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def test_http_get_is_read_only_and_authenticated(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Any] = []

    def opener(request: Any, timeout: float) -> _Response:
        seen.append(request)
        return _Response({"ok": True}, {"X-RateLimit-Remaining": "42"})

    data, headers = rep.http_get("tok-SECRET", opener=opener)("https://api.github.com/repos/a/b")
    assert data == {"ok": True} and headers["x-ratelimit-remaining"] == "42"
    (request,) = seen
    assert request.get_method() == "GET"
    assert request.data is None
    assert request.get_header("Authorization") == "Bearer tok-SECRET"


def test_http_get_retries_one_server_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rep.time, "sleep", lambda s: None)
    calls = []

    def opener(request: Any, timeout: float) -> _Response:
        calls.append(1)
        if len(calls) == 1:
            raise urllib.error.HTTPError(request.full_url, 503, "busy", {}, None)  # type: ignore[arg-type]
        return _Response([], {})

    rep.http_get("tok", opener=opener)("https://api.github.com/x")
    assert len(calls) == 2


def test_an_api_error_never_carries_the_token(monkeypatch: pytest.MonkeyPatch) -> None:
    def opener(request: Any, timeout: float) -> _Response:
        raise urllib.error.HTTPError(request.full_url, 404, "nope", {}, None)  # type: ignore[arg-type]

    with pytest.raises(rep.ApiError) as excinfo:
        rep.http_get("tok-SECRET", opener=opener)("https://api.github.com/x?page=1")
    assert "tok-SECRET" not in str(excinfo.value) and "404" in str(excinfo.value)
    assert excinfo.value.__cause__ is None and excinfo.value.__suppress_context__


def test_main_writes_both_outputs(tmp_path: Path) -> None:
    api = FakeApi(runs=_fixture("runs.json"), jobs=_fixture("jobs.json"))
    out_json, out_md = tmp_path / "r.json", tmp_path / "r.md"
    code = rep.main(["--repo", "example/yazses", "--out-json", str(out_json),
                     "--out-md", str(out_md)], transport=api, now=END)
    assert code == 0
    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert data["schema"] == ct.SCHEMA and data["totals"]["runs"] == 17
    page = out_md.read_text(encoding="utf-8")
    assert page.startswith("# CI telemetry")
    leaked = [v for v in PERSONAL if v in page or v in out_json.read_text(encoding="utf-8")]
    assert not leaked


def test_main_reports_an_unreadable_api_as_exit_1(tmp_path: Path) -> None:
    def broken(url: str) -> tuple[Any, dict[str, str]]:
        raise rep.ApiError("GET https://api.github.com/repos/example/yazses failed: HTTP 403")

    code = rep.main(["--repo", "example/yazses", "--out-json", str(tmp_path / "a"),
                     "--out-md", str(tmp_path / "b")], transport=broken, now=END)
    assert code == 1
    assert not (tmp_path / "a").exists()


@pytest.mark.parametrize("argv", [
    ["--days", "0"], ["--days", "91"], ["--days", "two"], ["--repo", "no-slash"],
    ["--repo", "a/b?x=1"],
])
def test_main_rejects_bad_arguments(argv: list[str], tmp_path: Path) -> None:
    base = ["--repo", "example/yazses", "--out-json", str(tmp_path / "a"), "--out-md", str(tmp_path / "b")]
    with pytest.raises(SystemExit) as excinfo:
        rep.main(base + argv, transport=FakeApi(runs=[], jobs={}), now=END)
    assert excinfo.value.code == 2


def test_main_needs_a_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(SystemExit) as excinfo:
        rep.main(["--repo", "example/yazses", "--out-json", str(tmp_path / "a"),
                  "--out-md", str(tmp_path / "b")])
    assert excinfo.value.code == 2


def test_the_token_is_never_a_command_line_option() -> None:
    source = (SCRIPTS / "ci-telemetry-report.py").read_text(encoding="utf-8")
    assert "--token" not in source


# ------------------------------------------------------------------------ the workflow


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_workflow_runs_on_a_schedule_and_by_hand_only(workflow: dict) -> None:
    triggers = workflow.get("on", workflow.get(True))  # PyYAML reads a bare `on` as True
    assert set(triggers) == {"schedule", "workflow_dispatch"}


def test_workflow_token_is_read_only(workflow: dict) -> None:
    assert workflow["permissions"] == {"actions": "read", "contents": "read"}
    for name, job in workflow["jobs"].items():
        assert "permissions" not in job, f"job {name} must not widen the token"


def test_workflow_keeps_its_artifact_briefly_and_has_a_timeout(workflow: dict) -> None:
    (job,) = workflow["jobs"].values()
    assert 0 < job["timeout-minutes"] <= 30
    uploads = [s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/upload-artifact@")]
    assert len(uploads) == 1
    assert 1 <= int(uploads[0]["with"]["retention-days"]) <= 14
    checkout = next(s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/checkout@"))
    assert checkout["with"]["persist-credentials"] is False


def test_workflow_input_reaches_the_script_as_data(workflow: dict) -> None:
    (job,) = workflow["jobs"].values()
    for step in job["steps"]:
        assert "${{" not in step.get("run", ""), "expressions go through env:, not into shell"


def test_telemetry_is_not_a_gate() -> None:
    test_yml = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    assert "ci-telemetry" not in test_yml and "ci_telemetry" not in test_yml
