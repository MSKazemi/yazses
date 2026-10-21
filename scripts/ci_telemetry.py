#!/usr/bin/env python3
"""Aggregate GitHub Actions run and job records into a CI telemetry report (#536).

This module is **pure**: it takes the JSON that the GitHub REST API returns for workflow
runs (`GET /repos/{owner}/{repo}/actions/runs`) and their jobs
(`GET .../actions/runs/{id}/jobs`), and returns a report. It opens no connection, reads
no file and looks at no clock — the observation window is an argument — so the same
input gives the same report on a laptop, on a runner and in a test.
`scripts/ci-telemetry-report.py` is the thin fetcher that feeds it.

What it answers is the question in `.github/CI_POLICY.md` §12: *what is consuming CI,
and where are contributors waiting?*

Definitions (also written up in CI_POLICY.md §12.1):

- **Queue latency** is per job: `started_at - created_at`. A job with `needs:` is created
  when its dependencies finish, so this is time spent waiting for a runner, not for
  upstream jobs. Skipped jobs never queue and are excluded.
- **Run duration** is per run attempt: the last job's `completed_at` minus
  `run_started_at`, for completed runs whose jobs were fetched. `updated_at` is *not*
  used for it, because GitHub rewrites it on finished runs (see `Run.duration_s`). Where
  a run's jobs were not fetched, its end falls back to `updated_at`, for the
  superseded-run overlap test only.
- **Job duration** is `completed_at - started_at`, for jobs that ran.
- **Percentiles** are nearest-rank: p95 of 20 values is the 19th smallest. No
  interpolation, so every reported value is one that was actually observed.
- **Outcome classes**: `success`; `failure` (failure, timed_out, startup_failure);
  `cancelled`; `other` (skipped, neutral, action_required, stale). Runs that have not
  completed are counted separately and excluded from the percentages.
- **Superseded run**: a `pull_request` / `pull_request_target` run for which a newer run
  of the *same workflow* for the *same pull request* was created before it completed.
  The concurrency policy (§2) should cancel every one of them. The report gives the share
  that was cancelled, the cancellation delay (`updated_at` of the cancelled run minus
  `created_at` of its successor) and the workflows whose superseded runs ran to the end.
- **Repeated failure**: the same (workflow, job, first failed step) failing in two or
  more runs in the window.
- **Red on the default branch**: the newest completed non-PR run of a workflow on the
  default branch failed. "Red since" is the oldest failure in the unbroken streak of
  failures ending there (cancelled and skipped runs neither break nor extend the streak).

Privacy (§12, last paragraph): every raw record is projected onto an explicit allow-list
of fields the moment it enters (`project_run`, `project_job`). Pull-request titles and
bodies, commit messages, author names and emails, actor logins, branch names, fork names
and log text never reach the report. A pull request is identified only by an opaque key
used for grouping and never written out. The only free text that remains is workflow,
job and step names, which come from workflow files and are escaped before they are
rendered as Markdown. Numeric run ids are kept so a reader can open the failing run.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any

SCHEMA = "yazses-ci-telemetry/1"

PR_EVENTS = frozenset({"pull_request", "pull_request_target"})

SUCCESS = "success"
FAILURE = "failure"
CANCELLED = "cancelled"
OTHER = "other"
OUTCOMES = (SUCCESS, FAILURE, CANCELLED, OTHER)

_FAILURE_CONCLUSIONS = frozenset({"failure", "timed_out", "startup_failure"})

#: The targets in CI_POLICY.md §12, in seconds. The report compares facts with these;
#: it never changes a gate and never fails because one is missed.
SLO_PR_QUEUE_P95_S = 5 * 60
SLO_FAST_GATE_P95_S = 10 * 60
SLO_SUPERSEDED_CANCEL_P95_S = 2 * 60
SLO_MAIN_RED_S = 24 * 3600
SLO_SCHEDULED_RED_S = 7 * 24 * 3600

#: Names longer than this are cut when rendered; a job name is not a place for prose.
MAX_NAME = 120

NO_FAILED_STEP = "(no failed step recorded)"


# ---------------------------------------------------------------------------- records


@dataclass(frozen=True)
class Step:
    name: str
    conclusion: str | None


@dataclass(frozen=True)
class Job:
    run_id: int
    name: str
    status: str
    conclusion: str | None
    created_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    steps: tuple[Step, ...] = ()

    @property
    def ran(self) -> bool:
        return self.conclusion != "skipped" and self.started_at is not None

    @property
    def queue_s(self) -> float | None:
        if not self.ran or self.created_at is None or self.started_at is None:
            return None
        return max(0.0, (self.started_at - self.created_at).total_seconds())

    @property
    def duration_s(self) -> float | None:
        if not self.ran or self.status != "completed" or self.completed_at is None:
            return None
        assert self.started_at is not None
        return max(0.0, (self.completed_at - self.started_at).total_seconds())

    @property
    def failed_step(self) -> str:
        for step in self.steps:
            if step.conclusion in _FAILURE_CONCLUSIONS:
                return step.name
        return NO_FAILED_STEP


@dataclass(frozen=True)
class Run:
    id: int
    workflow: str
    path: str
    event: str
    status: str
    conclusion: str | None
    created_at: datetime
    run_started_at: datetime | None
    updated_at: datetime | None
    run_attempt: int
    on_default_branch: bool
    pr_key: str | None = field(default=None, repr=False)
    #: When the run finished: the last job's `completed_at` once jobs are attached
    #: (`timed_by_jobs`), else `updated_at`. See `with_jobs`.
    ended_at: datetime | None = None
    timed_by_jobs: bool = False

    @property
    def key(self) -> str:
        """Workflows are grouped by file path; two workflows may share a display name."""
        return self.path or self.workflow

    @property
    def completed(self) -> bool:
        return self.status == "completed"

    @property
    def outcome(self) -> str | None:
        if not self.completed:
            return None
        return outcome_of(self.conclusion)

    @property
    def duration_s(self) -> float | None:
        """Wall-clock time of the latest attempt, only when its jobs are known.

        `updated_at` alone is not a completion time: GitHub touches finished runs again
        later (on 2026-10-16 it moved a dozen failed PR runs' `updated_at` to the same
        second, up to 22 hours after they ended), so a duration built on it reports
        hours for a run that took minutes.
        """
        if not self.timed_by_jobs or self.run_started_at is None or self.ended_at is None:
            return None
        return max(0.0, (self.ended_at - self.run_started_at).total_seconds())

    def with_jobs(self, jobs: Sequence[Job]) -> Run:
        """This run with its end taken from its fetched jobs.

        A completed run whose job list came back *empty* never ran anything (a workflow
        file error, or every job filtered out), so it ended when it started — its
        `updated_at` can be days later. It gets no duration, because nothing executed.
        """
        if not self.completed:
            return self
        ends = [job.completed_at for job in jobs if job.completed_at is not None]
        if not ends:
            return replace(self, ended_at=self.run_started_at or self.created_at)
        return replace(self, ended_at=max(ends), timed_by_jobs=True)


def outcome_of(conclusion: str | None) -> str:
    if conclusion == "success":
        return SUCCESS
    if conclusion in _FAILURE_CONCLUSIONS:
        return FAILURE
    if conclusion == "cancelled":
        return CANCELLED
    return OTHER


def parse_time(value: Any) -> datetime | None:
    """GitHub's `2026-10-20T21:51:14Z`, as an aware UTC datetime; None for anything else."""
    if not isinstance(value, str) or not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _str(value: Any, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _opaque(text: str) -> str:
    return "h:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _pr_key(raw: Mapping[str, Any]) -> str | None:
    """An opaque grouping key for the pull request a run belongs to.

    `pull_requests` is empty for a pull request from a fork, so the fallback is the head
    repository plus branch — hashed, because both can name a person.
    """
    prs = raw.get("pull_requests")
    if isinstance(prs, list) and prs and isinstance(prs[0], Mapping):
        number = prs[0].get("number")
        if isinstance(number, int):
            return f"pr:{number}"
    head_repo = raw.get("head_repository")
    repo_name = _str(head_repo.get("full_name")) if isinstance(head_repo, Mapping) else ""
    branch = _str(raw.get("head_branch"))
    if not (repo_name or branch):
        return None
    return _opaque(f"{repo_name}\0{branch}")


def project_run(raw: Mapping[str, Any], *, default_branch: str) -> Run | None:
    """The allow-listed fields of one run, or None when the record is unusable."""
    run_id = raw.get("id")
    created = parse_time(raw.get("created_at"))
    if not isinstance(run_id, int) or created is None:
        return None
    event = _str(raw.get("event"), "unknown")
    path = _str(raw.get("path"))
    attempt = raw.get("run_attempt")
    return Run(
        id=run_id,
        # Dependabot and other `dynamic/` workflows put a per-update title in `name`
        # ("uv in /. for Pillow - Update #1640658397"); the path is the stable name.
        workflow=(path if path.startswith("dynamic/") else _str(raw.get("name")))
        or path or "(unnamed)",
        path=path,
        event=event,
        status=_str(raw.get("status"), "unknown"),
        conclusion=raw.get("conclusion") if isinstance(raw.get("conclusion"), str) else None,
        created_at=created,
        run_started_at=parse_time(raw.get("run_started_at")),
        updated_at=parse_time(raw.get("updated_at")),
        run_attempt=attempt if isinstance(attempt, int) and attempt > 0 else 1,
        on_default_branch=(
            event not in PR_EVENTS and _str(raw.get("head_branch")) == default_branch
        ),
        pr_key=_pr_key(raw) if event in PR_EVENTS else None,
        ended_at=parse_time(raw.get("updated_at")) if raw.get("status") == "completed" else None,
    )


def project_job(raw: Mapping[str, Any], *, run_id: int) -> Job:
    steps_raw = raw.get("steps")
    steps = tuple(
        Step(name=_str(s.get("name"), "(unnamed step)"),
             conclusion=s.get("conclusion") if isinstance(s.get("conclusion"), str) else None)
        for s in (steps_raw if isinstance(steps_raw, list) else [])
        if isinstance(s, Mapping)
    )
    return Job(
        run_id=run_id,
        name=_str(raw.get("name"), "(unnamed job)"),
        status=_str(raw.get("status"), "unknown"),
        conclusion=raw.get("conclusion") if isinstance(raw.get("conclusion"), str) else None,
        created_at=parse_time(raw.get("created_at")),
        started_at=parse_time(raw.get("started_at")),
        completed_at=parse_time(raw.get("completed_at")),
        steps=steps,
    )


# ----------------------------------------------------------------------------- maths


def percentile(values: Iterable[float], q: float) -> float | None:
    """Nearest-rank percentile; None for no values. `q` is in [0, 100]."""
    ordered = sorted(values)
    if not ordered:
        return None
    if not 0 <= q <= 100:
        raise ValueError(f"percentile must be in [0, 100], got {q}")
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return ordered[rank - 1]


def _stats(values: Sequence[float]) -> dict[str, Any]:
    return {
        "n": len(values),
        "p50_s": _round(percentile(values, 50)),
        "p95_s": _round(percentile(values, 95)),
        "max_s": _round(max(values)) if values else None,
    }


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


def _pct(part: int, whole: int) -> float | None:
    return None if whole == 0 else round(100.0 * part / whole, 1)


def _outcomes(runs: Iterable[Run]) -> dict[str, Any]:
    counts = Counter(run.outcome for run in runs if run.completed)
    completed = sum(counts.values())
    return {
        "completed": completed,
        "counts": {o: counts.get(o, 0) for o in OUTCOMES},
        "percent": {o: _pct(counts.get(o, 0), completed) for o in OUTCOMES},
    }


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------- metrics


def superseded_runs(runs: Sequence[Run]) -> list[tuple[Run, Run]]:
    """(older run, its successor) for every overlapping same-PR, same-workflow pair.

    The successor is the earliest newer run of the same workflow for the same pull
    request created while the older one's latest attempt was running. A run still in
    progress at the end of the window counts as overlapping anything created after it.
    A re-run is judged by its latest attempt, the only one the runs API reports: a newer
    run created *before* the re-run started did not supersede it. Runs that ended
    `action_required` (waiting for a maintainer to approve a first-time contributor's or
    a bot's run) never started, so they neither supersede nor are superseded.
    """
    groups: dict[tuple[str, str], list[Run]] = defaultdict(list)
    for run in runs:
        if run.conclusion == "action_required":
            continue
        if run.event in PR_EVENTS and run.pr_key is not None:
            groups[(run.key, run.pr_key)].append(run)
    pairs: list[tuple[Run, Run]] = []
    for group in groups.values():
        group.sort(key=lambda r: (r.created_at, r.id))
        for index, older in enumerate(group):
            started = older.run_started_at or older.created_at
            ended = older.ended_at if older.completed else None
            for newer in group[index + 1:]:
                if newer.created_at < started:
                    continue  # created before this run's latest attempt began
                if ended is None or newer.created_at < ended:
                    pairs.append((older, newer))
                break
    return pairs


def _superseded_report(runs: Sequence[Run]) -> dict[str, Any]:
    pr_runs = [r for r in runs if r.event in PR_EVENTS]
    pairs = [(o, n) for o, n in superseded_runs(runs) if o.completed]
    cancelled = [(o, n) for o, n in pairs if o.conclusion == "cancelled"]
    delays = [
        max(0.0, (o.ended_at - n.created_at).total_seconds())
        for o, n in cancelled
        if o.ended_at is not None
    ]
    ran_on: Counter[str] = Counter(o.workflow for o, n in pairs if o.conclusion != "cancelled")
    return {
        "pr_runs": len(pr_runs),
        "superseded": len(pairs),
        "superseded_cancelled": len(cancelled),
        "cancellation_rate_percent": _pct(len(cancelled), len(pairs)),
        "share_of_pr_runs_percent": _pct(len(pairs), len(pr_runs)),
        "cancel_delay": _stats(delays),
        "ran_to_completion_by_workflow": [
            {"workflow": wf, "runs": n} for wf, n in sorted(ran_on.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
    }


def _red_on_default_branch(runs: Sequence[Run], window_end: datetime) -> list[dict[str, Any]]:
    by_workflow: dict[str, list[Run]] = defaultdict(list)
    for run in runs:
        if run.on_default_branch and run.completed:
            by_workflow[run.key].append(run)
    red: list[dict[str, Any]] = []
    for group in by_workflow.values():
        decisive = [r for r in group if r.outcome in (SUCCESS, FAILURE)]
        decisive.sort(key=lambda r: (r.created_at, r.id))
        if not decisive or decisive[-1].outcome != FAILURE:
            continue
        streak: list[Run] = []
        for run in reversed(decisive):
            if run.outcome != FAILURE:
                break
            streak.append(run)
        first, last = streak[-1], streak[0]
        scheduled_only = all(r.event == "schedule" for r in streak)
        limit = SLO_SCHEDULED_RED_S if scheduled_only else SLO_MAIN_RED_S
        red_for = max(0.0, (window_end - first.created_at).total_seconds())
        red.append({
            "workflow": last.workflow,
            "path": last.path,
            "events": sorted({r.event for r in streak}),
            "failed_runs_in_streak": len(streak),
            "red_since": _iso(first.created_at),
            "red_for_s": _round(red_for),
            "slo_limit_s": limit,
            "over_slo": red_for > limit,
            "latest_run_id": last.id,
        })
    red.sort(key=lambda row: (-row["red_for_s"], row["workflow"]))
    return red


def build_report(
    runs_raw: Iterable[Mapping[str, Any]],
    jobs_raw: Mapping[int, Iterable[Mapping[str, Any]]],
    *,
    window_start: datetime,
    window_end: datetime,
    default_branch: str = "main",
    workflows_raw: Iterable[Mapping[str, Any]] | None = None,
    repository: str = "",
    coverage: Mapping[str, Any] | None = None,
    top: int = 10,
) -> dict[str, Any]:
    """The whole report as a JSON-serialisable dict.

    `jobs_raw` maps a run id to that run's raw job records; runs absent from it simply
    contribute no job-level numbers, and `coverage` (from the fetcher) says how many
    were fetched. `workflows_raw` is the repository's workflow list, used only to name
    active workflows that did not run at all in the window.
    """
    runs: list[Run] = []
    seen: set[int] = set()
    for raw in runs_raw:
        run = project_run(raw, default_branch=default_branch)
        if run is None or run.id in seen:
            continue
        if not window_start <= run.created_at <= window_end:
            continue
        seen.add(run.id)
        runs.append(run)
    runs.sort(key=lambda r: (r.created_at, r.id))
    known = {run.id for run in runs}

    jobs_by_run: dict[int, list[Job]] = {}
    for run_id, records in jobs_raw.items():
        if int(run_id) in known:
            jobs_by_run[int(run_id)] = [
                project_job(raw, run_id=int(run_id)) for raw in records if isinstance(raw, Mapping)
            ]
    runs = [run.with_jobs(jobs_by_run[run.id]) if run.id in jobs_by_run else run for run in runs]
    jobs: list[tuple[Run, Job]] = [
        (run, job) for run in runs for job in jobs_by_run.get(run.id, [])
    ]

    # --- volume and outcomes
    by_wf: dict[str, list[Run]] = defaultdict(list)
    by_wf_event: dict[tuple[str, str], list[Run]] = defaultdict(list)
    for run in runs:
        by_wf[run.key].append(run)
        by_wf_event[(run.key, run.event)].append(run)

    queue_by_wf: dict[str, list[float]] = defaultdict(list)
    minutes_by_wf: dict[str, float] = defaultdict(float)
    for run, job in jobs:
        if job.queue_s is not None:
            queue_by_wf[run.key].append(job.queue_s)
        if job.duration_s is not None:
            minutes_by_wf[run.key] += job.duration_s / 60

    workflows = []
    for key, group in by_wf.items():
        outcome = _outcomes(group)
        workflows.append({
            "workflow": group[-1].workflow,
            "path": group[0].path,
            "runs": len(group),
            "incomplete": sum(1 for r in group if not r.completed),
            **{f"{o}_percent": outcome["percent"][o] for o in OUTCOMES},
            "outcomes": outcome["counts"],
            "run_duration": _stats([d for r in group if (d := r.duration_s) is not None]),
            "job_queue": _stats(queue_by_wf.get(key, [])),
            "job_minutes": round(minutes_by_wf.get(key, 0.0), 1),
        })
    workflows.sort(key=lambda row: (-row["job_minutes"], -row["runs"], row["workflow"]))

    by_event = [
        {"workflow": group[-1].workflow, "path": group[-1].path, "event": ev,
         "runs": len(group), **_outcomes(group)["counts"]}
        for (_, ev), group in by_wf_event.items()
    ]
    by_event.sort(key=lambda row: (-row["runs"], row["workflow"], row["event"]))

    # --- longest jobs, by p95 over every execution of the same (workflow, job)
    durations: dict[tuple[str, str], list[float]] = defaultdict(list)
    names = {run.key: run.workflow for run in runs}
    for run, job in jobs:
        if job.duration_s is not None:
            durations[(run.key, job.name)].append(job.duration_s)
    longest = [
        {"workflow": names[key], "job": name, **_stats(values),
         "total_minutes": round(sum(values) / 60, 1)}
        for (key, name), values in durations.items()
    ]
    longest.sort(key=lambda row: (-(row["p95_s"] or 0), row["workflow"], row["job"]))

    # --- no success in the window, and no run at all
    no_success = []
    for group in by_wf.values():
        outcome = _outcomes(group)
        if outcome["completed"] and outcome["counts"][SUCCESS] == 0:
            no_success.append({"workflow": group[-1].workflow, "path": group[0].path,
                               **outcome["counts"]})
    no_success.sort(key=lambda row: row["workflow"])

    ran_paths = {run.path for run in runs if run.path}
    no_runs = []
    for wf in workflows_raw or ():
        if not isinstance(wf, Mapping) or wf.get("state") != "active":
            continue
        path = _str(wf.get("path"))
        if path and path not in ran_paths and path.startswith(".github/workflows/"):
            no_runs.append({"workflow": _str(wf.get("name")) or path, "path": path})
    no_runs.sort(key=lambda row: row["path"])

    # --- repeated failures by (workflow, job, first failed step)
    failures: dict[tuple[str, str, str], list[Run]] = defaultdict(list)
    for run, job in jobs:
        if run.completed and job.conclusion in _FAILURE_CONCLUSIONS:
            failures[(run.key, job.name, job.failed_step)].append(run)
    repeated = []
    for (key, job_name, step), failed in failures.items():
        distinct = {r.id: r for r in failed}
        if len(distinct) < 2:
            continue
        newest = max(distinct.values(), key=lambda r: (r.created_at, r.id))
        repeated.append({
            "workflow": names[key], "job": job_name, "step": step, "runs": len(distinct),
            "events": sorted({r.event for r in distinct.values()}),
            "last_seen": _iso(newest.created_at), "last_run_id": newest.id,
        })
    repeated.sort(key=lambda row: (-row["runs"], row["workflow"], row["job"], row["step"]))

    # --- SLO facts (CI_POLICY.md §12)
    pr_queue = [job.queue_s for run, job in jobs if run.event in PR_EVENTS and job.queue_s is not None]
    superseded = _superseded_report(runs)
    red = _red_on_default_branch(runs, window_end)
    slo = [
        _slo_row("PR job queue delay p95 (all PR workflows; fast lane not yet split, #535)",
                 percentile(pr_queue, 95), SLO_PR_QUEUE_P95_S, len(pr_queue)),
        {"name": "Fast PR gate execution p95", "target_s": SLO_FAST_GATE_P95_S,
         "value_s": None, "n": 0, "status": "n/a",
         "note": "no fast lane exists yet to measure (#535)"},
        _slo_row("Superseded PR run cancellation delay p95",
                 superseded["cancel_delay"]["p95_s"], SLO_SUPERSEDED_CANCEL_P95_S,
                 superseded["cancel_delay"]["n"]),
        _red_slo_row("Default-branch workflows red > 24 h (excluding schedule-only)",
                     [r for r in red if r["slo_limit_s"] == SLO_MAIN_RED_S], SLO_MAIN_RED_S),
        _red_slo_row("Scheduled workflows red > 7 days",
                     [r for r in red if r["slo_limit_s"] == SLO_SCHEDULED_RED_S],
                     SLO_SCHEDULED_RED_S),
    ]

    all_queue = [job.queue_s for _, job in jobs if job.queue_s is not None]
    jobs_ran = sum(1 for _, job in jobs if job.ran)
    return {
        "schema": SCHEMA,
        "repository": repository,
        "window": {
            "start": _iso(window_start),
            "end": _iso(window_end),
            "days": round((window_end - window_start).total_seconds() / 86400, 2),
            "default_branch": default_branch,
        },
        "coverage": {
            "runs": len(runs),
            "runs_with_jobs": len({run.id for run, _ in jobs}),
            "jobs": len(jobs),
            "jobs_ran": jobs_ran,
            **dict(coverage or {}),
        },
        "totals": {
            "runs": len(runs),
            "incomplete": sum(1 for r in runs if not r.completed),
            **_outcomes(runs),
            "run_duration": _stats([d for r in runs if (d := r.duration_s) is not None]),
            "job_queue": _stats(all_queue),
            "job_minutes": round(sum(minutes_by_wf.values()), 1),
        },
        "workflows": workflows,
        "by_workflow_event": by_event,
        "superseded": superseded,
        "longest_jobs": longest[:top],
        "no_success": no_success,
        "no_runs": no_runs,
        "repeated_failures": repeated,
        "red_on_default_branch": red,
        "slo": slo,
    }


def _slo_row(name: str, value: float | None, target: float, n: int) -> dict[str, Any]:
    if value is None:
        status = "no data"
    else:
        status = "met" if value < target else "missed"
    return {"name": name, "target_s": target, "value_s": _round(value), "n": n, "status": status}


def _red_slo_row(name: str, rows: Sequence[Mapping[str, Any]], limit: float) -> dict[str, Any]:
    over = [r for r in rows if r["over_slo"]]
    return {
        "name": name, "target_s": limit, "value_s": None, "n": len(over),
        "status": "missed" if over else "met",
        "note": (f"{len(over)} workflow(s) over the limit; the report cannot see whether a "
                 "linked issue exists") if over else "",
    }


# --------------------------------------------------------------------------- markdown


def md_escape(text: Any) -> str:
    """A Markdown table cell that cannot break the table or inject HTML."""
    value = " ".join(str(text).split())
    if len(value) > MAX_NAME:
        value = value[: MAX_NAME - 1] + "…"
    for char, repl in (("\\", "\\\\"), ("|", "\\|"), ("`", "'"), ("<", "&lt;"),
                       (">", "&gt;"), ("[", "\\["), ("]", "\\]"), ("*", "\\*"), ("_", "\\_")):
        value = value.replace(char, repl)
    return value


def fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "–"
    total = int(round(seconds))
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m {secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    if hours < 48:
        return f"{hours}h {minutes:02d}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours:02d}h"


def _fmt_pct(value: float | None) -> str:
    return "–" if value is None else f"{value:.1f}%"


def _table(header: Sequence[str], rows: Iterable[Sequence[Any]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return lines


def render_markdown(report: Mapping[str, Any], *, top: int = 10) -> str:
    """The report as a GitHub job-summary page."""
    window, totals, cov = report["window"], report["totals"], report["coverage"]
    repo = md_escape(report.get("repository") or "this repository")
    out: list[str] = [
        f"# CI telemetry — {repo}",
        "",
        f"Window: **{window['start']} → {window['end']}** ({window['days']} days). "
        f"{totals['runs']} runs, {totals['completed']} completed, "
        f"{totals['incomplete']} still running or queued.",
        "",
        f"Job-level numbers cover **{cov['runs_with_jobs']} of {cov['runs']} runs** "
        f"({cov['jobs_ran']} jobs that ran)."
        + (f" Job lists were fetched for {cov['job_lists_fetched']} runs; the rest of those "
           "had no jobs (a workflow-file error, or every job filtered out)."
           if "job_lists_fetched" in cov else ""),
    ]
    for note in cov.get("notes", []) or []:
        out.append(f"- ⚠ {md_escape(note)}")
    pct = totals["percent"]
    out += [
        "",
        f"Outcomes: success {_fmt_pct(pct[SUCCESS])} · failure {_fmt_pct(pct[FAILURE])} · "
        f"cancelled {_fmt_pct(pct[CANCELLED])} · other {_fmt_pct(pct[OTHER])}. "
        f"Job queue p50/p95 {fmt_duration(totals['job_queue']['p50_s'])} / "
        f"{fmt_duration(totals['job_queue']['p95_s'])}. "
        f"Runner time {totals['job_minutes']:.0f} job-minutes.",
        "",
        "## SLO facts (targets from CI_POLICY.md §12; nothing here changes a gate)",
        "",
    ]
    out += _table(
        ["Objective", "Target", "Observed", "n", "Status"],
        [
            (md_escape(row["name"]), fmt_duration(row["target_s"]),
             fmt_duration(row["value_s"]) if row["value_s"] is not None else
             md_escape(row.get("note") or "–"),
             row["n"], row["status"])
            for row in report["slo"]
        ],
    )

    out += ["", "## What is consuming CI (by job-minutes)", ""]
    out += _table(
        ["Workflow", "Runs", "Success", "Failure", "Cancelled", "Run p50 / p95",
         "Job queue p50 / p95", "Job-minutes"],
        [
            (md_escape(w["workflow"]), w["runs"], _fmt_pct(w["success_percent"]),
             _fmt_pct(w["failure_percent"]), _fmt_pct(w["cancelled_percent"]),
             f"{fmt_duration(w['run_duration']['p50_s'])} / {fmt_duration(w['run_duration']['p95_s'])}",
             f"{fmt_duration(w['job_queue']['p50_s'])} / {fmt_duration(w['job_queue']['p95_s'])}",
             f"{w['job_minutes']:.0f}")
            for w in report["workflows"]
        ],
    )

    out += ["", "## Runs by workflow and event", ""]
    out += _table(
        ["Workflow", "Event", "Runs", "Success", "Failure", "Cancelled", "Other"],
        [(md_escape(r["workflow"]), md_escape(r["event"]), r["runs"], r[SUCCESS], r[FAILURE],
          r[CANCELLED], r[OTHER]) for r in report["by_workflow_event"]],
    )

    sup = report["superseded"]
    out += [
        "",
        "## Superseded pull-request runs",
        "",
        f"{sup['superseded']} of {sup['pr_runs']} PR runs were superseded by a newer run of "
        f"the same workflow for the same PR ({_fmt_pct(sup['share_of_pr_runs_percent'])}). "
        f"Cancelled: {sup['superseded_cancelled']} "
        f"({_fmt_pct(sup['cancellation_rate_percent'])}); cancellation delay p50/p95 "
        f"{fmt_duration(sup['cancel_delay']['p50_s'])} / {fmt_duration(sup['cancel_delay']['p95_s'])}.",
    ]
    if sup["ran_to_completion_by_workflow"]:
        out += ["", "Superseded runs that ran to completion (a concurrency gap, CI_POLICY §2):", ""]
        out += _table(["Workflow", "Runs"],
                      [(md_escape(r["workflow"]), r["runs"]) for r in sup["ran_to_completion_by_workflow"]])

    out += ["", f"## Longest jobs (top {top} by p95)", ""]
    out += _table(
        ["Workflow", "Job", "n", "p50", "p95", "Max", "Job-minutes"],
        [(md_escape(j["workflow"]), md_escape(j["job"]), j["n"], fmt_duration(j["p50_s"]),
          fmt_duration(j["p95_s"]), fmt_duration(j["max_s"]), f"{j['total_minutes']:.0f}")
         for j in report["longest_jobs"]],
    )

    out += ["", "## Red on the default branch", ""]
    if report["red_on_default_branch"]:
        out += _table(
            ["Workflow", "Events", "Failed runs", "Red since", "Red for", "Over SLO", "Latest run"],
            [(md_escape(r["workflow"]), md_escape(", ".join(r["events"])),
              r["failed_runs_in_streak"], r["red_since"], fmt_duration(r["red_for_s"]),
              "yes" if r["over_slo"] else "no", r["latest_run_id"])
             for r in report["red_on_default_branch"]],
        )
    else:
        out.append("None: the newest decisive default-branch run of every workflow succeeded.")

    out += ["", "## Workflows with no successful run in the window", ""]
    if report["no_success"]:
        out += _table(
            ["Workflow", "Success", "Failure", "Cancelled", "Other"],
            [(md_escape(r["workflow"]), r[SUCCESS], r[FAILURE], r[CANCELLED], r[OTHER])
             for r in report["no_success"]],
        )
    else:
        out.append("None.")
    if report["no_runs"]:
        out += ["", "Active workflows that did not run at all in the window (not necessarily "
                "wrong — release workflows run on tags):", ""]
        out += [f"- {md_escape(r['workflow'])} (`{md_escape(r['path'])}`)" for r in report["no_runs"]]

    out += ["", "## Repeated failures (same workflow, job and first failed step, 2+ runs)", ""]
    if report["repeated_failures"]:
        out += _table(
            ["Workflow", "Job", "Step", "Runs", "Events", "Last seen", "Last run"],
            [(md_escape(r["workflow"]), md_escape(r["job"]), md_escape(r["step"]), r["runs"],
              md_escape(", ".join(r["events"])), r["last_seen"], r["last_run_id"])
             for r in report["repeated_failures"][: top * 2]],
        )
    else:
        out.append("None.")

    out += [
        "",
        "---",
        "Definitions, bounds and privacy rules: `.github/CI_POLICY.md` §12.1. "
        "This report contains workflow, job and step names, events, timings, conclusions "
        "and run ids only.",
        "",
    ]
    return "\n".join(out)
