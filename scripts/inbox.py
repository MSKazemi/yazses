#!/usr/bin/env python3
"""Every open thread that is waiting on the maintainer, and nothing else.

GitHub's notification inbox is the wrong instrument for this. It is dominated by CI
activity from every repo you own — a real design review sat unanswered for a day here
because 49 of 50 unread notifications were workflow failures from elsewhere — and it is
*read state*, not *reply state*: opening a thread clears it whether or not you answered.

This asks the only question that matters: **on which open threads is the last word
somebody else's?** Issues, pull requests, PR review threads and discussions. It is
stateless, so it cannot drift out of sync, and marking something read cannot hide it.

    make inbox              # threads waiting on you
    make inbox ARGS=--all   # include bot threads (dependabot & friends)

Requires the `gh` CLI, authenticated. Everything else is stdlib.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

BOT_SUFFIX = "[bot]"
BOT_LOGINS = {"dependabot", "github-actions", "codecov", "renovate"}


@dataclass(frozen=True)
class Thread:
    """One open thread whose last word belongs to somebody else."""

    kind: str          # issue | pr | review | discussion
    number: int
    title: str
    who: str           # who spoke last
    when: str          # ISO-8601 timestamp of the last word
    note: str = ""     # why it is here, when that is not obvious

    @property
    def url_path(self) -> str:
        return "discussions" if self.kind == "discussion" else (
            "pull" if self.kind in {"pr", "review"} else "issues"
        )


def is_bot(login: str) -> bool:
    return login.endswith(BOT_SUFFIX) or login.lower() in BOT_LOGINS


def age_days(iso: str, now: datetime | None = None) -> float:
    """Days since `iso`. Tolerates the trailing Z that the REST API emits."""
    stamp = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return ((now or datetime.now(timezone.utc)) - stamp).total_seconds() / 86400


def waiting(thread_author: str, last_speaker: str | None, me: str) -> bool:
    """Is this thread waiting on me?

    Two ways to be waiting, and the second is the one a comment-count filter misses:
    somebody else spoke last, OR nobody has spoken at all on something they opened.
    A brand-new issue from a stranger has zero comments and is the most urgent kind.
    """
    speaker = last_speaker if last_speaker is not None else thread_author
    return speaker != me


def rank(threads: list[Thread]) -> list[Thread]:
    """Oldest silence first — the thread most at risk of being abandoned."""
    return sorted(threads, key=lambda t: t.when)


def gh_text(*args: str) -> str:
    out = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or f"gh {' '.join(args)} failed")
    return out.stdout.strip()


def gh(*args: str) -> object:
    """A `gh` call whose output is JSON. Use gh_text for --jq scalars, which are bare."""
    raw = gh_text(*args)
    return json.loads(raw) if raw else None


def me_and_repo() -> tuple[str, str]:
    return (
        gh_text("api", "user", "--jq", ".login"),
        gh_text("repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"),
    )


def collect_issues_and_prs(repo: str, me: str, include_bots: bool) -> list[Thread]:
    found: list[Thread] = []
    items = gh("api", f"repos/{repo}/issues?state=open&per_page=100", "--paginate") or []
    for item in items:
        author = item["user"]["login"]
        if not include_bots and is_bot(author):
            continue
        kind = "pr" if item.get("pull_request") else "issue"
        last_who, last_when, note = author, item["created_at"], "never answered"
        if item["comments"]:
            comments = gh(
                "api", f"repos/{repo}/issues/{item['number']}/comments?per_page=100",
                "--paginate",
            ) or []
            visible = [c for c in comments if include_bots or not is_bot(c["user"]["login"])]
            if visible:
                last_who = visible[-1]["user"]["login"]
                last_when = visible[-1]["created_at"]
                note = ""
        if waiting(author, last_who, me):
            found.append(Thread(kind, item["number"], item["title"], last_who, last_when, note))
    return found


def collect_pr_reviews(repo: str, me: str, include_bots: bool) -> list[Thread]:
    """Inline review threads. These never appear in the issue-comment timeline."""
    found: list[Thread] = []
    prs = gh("api", f"repos/{repo}/pulls?state=open&per_page=100", "--paginate") or []
    for pr in prs:
        if not include_bots and is_bot(pr["user"]["login"]):
            continue
        comments = gh(
            "api", f"repos/{repo}/pulls/{pr['number']}/comments?per_page=100", "--paginate",
        ) or []
        visible = [c for c in comments if include_bots or not is_bot(c["user"]["login"])]
        if visible and waiting(pr["user"]["login"], visible[-1]["user"]["login"], me):
            found.append(Thread(
                "review", pr["number"], pr["title"],
                visible[-1]["user"]["login"], visible[-1]["created_at"],
                f"{len(visible)} inline review comment(s)",
            ))
    return found


DISCUSSION_QUERY = """
{ repository(owner: "%s", name: "%s") {
    discussions(first: 100, states: OPEN) { nodes {
      number title author { login }
      comments(last: 20) { nodes {
        author { login } createdAt
        replies(last: 20) { nodes { author { login } createdAt } } } } } } } }
"""


def collect_discussions(repo: str, me: str, include_bots: bool) -> list[Thread]:
    owner, name = repo.split("/", 1)
    try:
        data = gh("api", "graphql", "-f", "query=" + DISCUSSION_QUERY % (owner, name))
    except RuntimeError:
        return []  # discussions may be disabled; that is not an error worth failing on
    nodes = data["data"]["repository"]["discussions"]["nodes"] if data else []
    found: list[Thread] = []
    for d in nodes:
        said: list[tuple[str, str]] = []
        for c in d["comments"]["nodes"]:
            said.append((c["author"]["login"], c["createdAt"]))
            said.extend((r["author"]["login"], r["createdAt"]) for r in c["replies"]["nodes"])
        said = [(w, t) for w, t in said if include_bots or not is_bot(w)]
        if not said:
            continue  # an unanswered discussion you opened yourself is not a task
        said.sort(key=lambda p: p[1])
        who, when = said[-1]
        if waiting(d["author"]["login"], who, me):
            found.append(Thread("discussion", d["number"], d["title"], who, when))
    return found


ICON = {"issue": "◆", "pr": "⬢", "review": "⌇", "discussion": "💬"}


def render(threads: list[Thread], repo: str) -> str:
    if not threads:
        return "\n  ✓  Nothing is waiting on you. Every open thread ends with your reply.\n"
    lines = [f"\n  {len(threads)} thread(s) waiting on you — oldest silence first\n"]
    for t in rank(threads):
        days = age_days(t.when)
        flag = "🔴" if days > 3 else ("🟡" if days > 1 else "  ")
        detail = f" — {t.note}" if t.note else ""
        lines.append(f"  {flag} {ICON[t.kind]} #{t.number:<4} {t.title[:58]}")
        lines.append(f"        @{t.who} · {days:.1f}d ago{detail}")
        lines.append(f"        https://github.com/{repo}/{t.url_path}/{t.number}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--all", action="store_true", help="include bot threads")
    args = parser.parse_args()

    try:
        me, repo = me_and_repo()
    except (RuntimeError, FileNotFoundError) as exc:
        print(f"  ✗  Needs an authenticated `gh` CLI: {exc}", file=sys.stderr)
        return 2

    threads = (
        collect_issues_and_prs(repo, me, args.all)
        + collect_pr_reviews(repo, me, args.all)
        + collect_discussions(repo, me, args.all)
    )
    print(render(threads, repo))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
