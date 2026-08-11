#!/usr/bin/env python3
"""Measure the contributor funnel — read-only, GitHub-native, no tracking.

The task inventory says how much work exists. This says whether any of it is working:
how many distinct non-bot accounts have an attributed commit on the default branch, who
merged a PR but does **not** appear in the contributors API (the silent failure that
loses a contributor their credit), and how each acquisition cohort actually converted.

**Attribution is the whole point.** GitHub attributes a commit by its author *email*. A
contributor whose commit email is not connected to their account gets a grey avatar, no
profile link, and no entry in the contributor graph — they did the work and the project
shows nothing. `--attribution-gaps` is the query that finds them, and it is the reason
this script exists.

Two things it deliberately does not do:

* **No tracking.** Everything comes from the public GitHub API and local git. No pixels,
  no per-user analytics, no third-party service. A cohort is a code someone typed into a
  PR body, not a fingerprint.
* **No emails in output.** Attribution debugging needs to know an email is *unconnected*,
  never what it is. Printing a contributor's address into a log or an issue would be a
  privacy failure in a project whose entire claim is that nothing leaves the machine.

Usage:

    uv run python scripts/campaign_stats.py                       # summary
    uv run python scripts/campaign_stats.py --since 2026-08-11    # new since a date
    uv run python scripts/campaign_stats.py --cohort india-foss-01
    uv run python scripts/campaign_stats.py --attribution-gaps
    uv run python scripts/campaign_stats.py --json

Without network access it falls back to local git history and says so, rather than
printing numbers it cannot stand behind.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = os.environ.get("YAZSES_REPO", "MSKazemi/yazses")
API = "https://api.github.com"

#: `Cohort: india-foss-club-01` in a PR body. Voluntary campaign operations data that
#: lives in GitHub where the contributor can see and delete it — not hidden analytics.
#: `{0,48}` not `{1,48}` — the quantifier counts characters *after* the first, so `{1,48}`
#: silently required a two-character code and dropped any one-character cohort.
COHORT_RE = re.compile(r"^\s*cohort\s*[:=]\s*([A-Za-z0-9][A-Za-z0-9_-]{0,48})\s*$", re.I | re.M)

BOT_SUFFIXES = ("[bot]",)
#: Accounts that are automation but do not carry the `[bot]` marker.
KNOWN_BOTS = frozenset({"dependabot", "github-actions", "allcontributors"})


# ── Pure logic (unit-tested offline) ──────────────────────────────────────────

def is_bot(login: str, account_type: str = "") -> bool:
    """Is this account automation rather than a person?

    The contributors API reports `type: "Bot"` for most, but not all: an installation
    can commit as a plain User. Counting a bot as a contributor inflates the only number
    that matters, so both signals are checked.
    """
    if account_type.lower() == "bot":
        return True
    low = login.lower()
    return low.endswith(BOT_SUFFIXES) or low in KNOWN_BOTS


def human_contributors(rows: list[dict]) -> list[str]:
    """Logins from the contributors API, bots removed, stable order."""
    seen: list[str] = []
    for row in rows:
        login = row.get("login") or ""
        if not login or is_bot(login, row.get("type", "")):
            continue
        if login not in seen:
            seen.append(login)
    return seen


def cohort_of(pr_body: str | None) -> str | None:
    """The cohort code a contributor voluntarily wrote into their PR body."""
    if not pr_body:
        return None
    m = COHORT_RE.search(pr_body)
    return m.group(1).lower() if m else None


def attribution_gaps(merged_authors: list[str], contributor_logins: list[str]) -> list[str]:
    """Merged human PR authors who are absent from the contributors API.

    Each name here is a person whose work is in `main` and who the project is currently
    showing no credit for. That is a bug in the project, not in them.
    """
    known = {c.lower() for c in contributor_logins}
    out: list[str] = []
    for author in merged_authors:
        if not author or is_bot(author):
            continue
        if author.lower() not in known and author not in out:
            out.append(author)
    return out


def cohort_funnel(prs: list[dict]) -> dict[str, dict[str, int]]:
    """Per-cohort counts: PRs opened, merged, and distinct authors merged."""
    out: dict[str, dict[str, int]] = {}
    authors: dict[str, set[str]] = {}
    for pr in prs:
        cohort = cohort_of(pr.get("body")) or "(none)"
        author = (pr.get("user") or {}).get("login", "")
        if is_bot(author):
            continue
        row = out.setdefault(cohort, {"prs": 0, "merged": 0, "authors_merged": 0})
        row["prs"] += 1
        if pr.get("merged_at"):
            row["merged"] += 1
            authors.setdefault(cohort, set()).add(author)
    for cohort, names in authors.items():
        out[cohort]["authors_merged"] = len(names)
    return dict(sorted(out.items()))


def summarize(
    *,
    contributors: list[str],
    merged_authors: list[str],
    prs: list[dict],
    baseline: int = 10,
) -> dict:
    gaps = attribution_gaps(merged_authors, contributors)
    merged_humans = {a for a in merged_authors if a and not is_bot(a)}
    return {
        "repo": REPO,
        "commit_contributors": len(contributors),
        "change_from_baseline": len(contributors) - baseline,
        "merged_pr_authors": len(merged_humans),
        "attribution_gaps": gaps,
        "open_prs": sum(1 for p in prs if p.get("state") == "open"),
        "cohorts": cohort_funnel(prs),
    }


def render(summary: dict, *, degraded: bool = False) -> str:
    lines = [f"# Contributor funnel — {summary['repo']}", ""]
    if degraded:
        lines += [
            "⚠ GitHub API unavailable — these numbers come from local git history.",
            "  Commit-author counts are a lower bound and attribution cannot be checked.",
            "",
        ]
    delta = summary["change_from_baseline"]
    sign = f"+{delta}" if delta >= 0 else str(delta)
    lines += [
        f"commit contributors : {summary['commit_contributors']} ({sign} from baseline)",
        f"merged PR authors   : {summary['merged_pr_authors']}",
        f"open PRs            : {summary['open_prs']}",
    ]
    gaps = summary["attribution_gaps"]
    if gaps:
        lines += [
            "",
            f"⚠ attribution gaps  : {len(gaps)} — merged work showing no credit",
        ]
        lines += [f"    @{g}" for g in gaps]
        lines += [
            "",
            "  Each of these merged a PR and does not appear in the contributors API.",
            "  Usual cause: the commit's author email is not connected to their GitHub",
            "  account. Contact them privately; never paste an address into a public log.",
        ]
    else:
        lines += ["", "✓ no attribution gaps — everyone who merged is credited"]

    cohorts = {k: v for k, v in summary["cohorts"].items() if k != "(none)"}
    if cohorts:
        lines += ["", "## Cohorts", "", "| cohort | PRs | merged | authors |", "|---|---:|---:|---:|"]
        for name, row in cohorts.items():
            lines.append(f"| {name} | {row['prs']} | {row['merged']} | {row['authors_merged']} |")
    return "\n".join(lines) + "\n"


# ── Data access ───────────────────────────────────────────────────────────────

def _get(path: str) -> list[dict]:
    """One paginated GitHub API call. Returns [] on any failure; caller degrades."""
    out: list[dict] = []
    url = f"{API}{path}"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "yazses-campaign-stats"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    while url:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed https host
            payload = json.loads(resp.read().decode("utf-8"))
            out.extend(payload if isinstance(payload, list) else [payload])
            link = resp.headers.get("Link", "")
            nxt = re.search(r'<([^>]+)>;\s*rel="next"', link)
            url = nxt.group(1) if nxt else ""
    return out


def contributors_from_git() -> list[str]:
    """Offline fallback: distinct commit author names on the current branch.

    Deliberately names, not emails. This is a lower bound and the caller says so — git
    knows who authored a commit, not whether GitHub attributes it.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "log", "--format=%an", "HEAD"],
            capture_output=True, text=True, check=True, timeout=60,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    names: list[str] = []
    for name in out.splitlines():
        name = name.strip()
        if name and not is_bot(name) and name not in names:
            names.append(name)
    return names


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Measure the contributor funnel (read-only).")
    ap.add_argument("--since", help="ISO date; only count PRs merged on or after it")
    ap.add_argument("--cohort", help="report one cohort only")
    ap.add_argument("--attribution-gaps", action="store_true", help="only list uncredited authors")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--baseline", type=int, default=10, help="contributor count to compare against")
    args = ap.parse_args(argv)

    degraded = False
    try:
        contributors = human_contributors(_get(f"/repos/{REPO}/contributors?per_page=100&anon=0"))
        prs = _get(f"/repos/{REPO}/pulls?state=all&per_page=100")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError):
        degraded = True
        contributors = contributors_from_git()
        prs = []

    if args.since:
        prs = [p for p in prs if (p.get("merged_at") or "") >= args.since or not p.get("merged_at")]
    if args.cohort:
        want = args.cohort.lower()
        prs = [p for p in prs if cohort_of(p.get("body")) == want]

    merged_authors = [
        (p.get("user") or {}).get("login", "") for p in prs if p.get("merged_at")
    ]
    summary = summarize(
        contributors=contributors, merged_authors=merged_authors, prs=prs, baseline=args.baseline
    )

    if args.attribution_gaps:
        gaps = summary["attribution_gaps"]
        if args.json:
            print(json.dumps(gaps, indent=2))
        elif gaps:
            print("\n".join(f"@{g}" for g in gaps))
        else:
            print("no attribution gaps")
        return 1 if gaps else 0

    print(json.dumps(summary, indent=2) if args.json else render(summary, degraded=degraded), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
