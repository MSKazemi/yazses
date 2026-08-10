#!/usr/bin/env python3
"""Fail when someone with merged work is missing from the contributors wall.

`tests/test_contributors_wall.py` checks the three credit surfaces against *each other*
— `.all-contributorsrc`, the README wall + badge, and `CONTRIBUTORS.md`. It cannot check
them against reality, and says so: deciding whether "someone with merged work is missing
from all three" needs to know who actually has merged work, which the test suite has no
business fetching. So all three can agree perfectly and still omit a real contributor.

That is the gap this closes, and it is the failure mode that matters most as the project
takes many small contributions: being forgotten is the one thing a contributor never
reports. They just do not come back.

    uv run python scripts/check_contributor_wall.py            # GitHub API (authoritative)
    uv run python scripts/check_contributor_wall.py --offline  # git history only, no network

The offline mode needs no token and no network. It recovers logins from GitHub noreply
addresses (`145488564+octocat@users.noreply.github.com` -> `octocat`), which is what the
web UI and `gh` produce by default, and reports any other author it could not map rather
than silently passing them.

Exit status is 0 when every contributor with commits is on the wall, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RC = ROOT / ".all-contributorsrc"

REPO = "MSKazemi/yazses"

# Automation accounts. A bot on the wall would be noise, and its absence is not a bug.
BOTS = {"dependabot[bot]", "github-actions[bot]", "allcontributors[bot]", "snyk-bot"}

NOREPLY = re.compile(r"^(?:\d+\+)?(?P<login>[A-Za-z0-9-]+)@users\.noreply\.github\.com$")


def wall_logins() -> set[str]:
    data = json.loads(RC.read_text(encoding="utf-8"))
    return {c["login"] for c in data["contributors"]}


def logins_from_api() -> set[str]:
    """Every account GitHub credits with commits. Public endpoint; no token needed."""
    logins: set[str] = set()
    url = f"https://api.github.com/repos/{REPO}/contributors?per_page=100&anon=0"
    while url:
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            logins |= {c["login"] for c in json.load(resp)}
            link = resp.headers.get("Link", "")
        nxt = re.search(r'<([^>]+)>;\s*rel="next"', link)
        url = nxt.group(1) if nxt else ""
    return logins


def logins_from_git() -> tuple[set[str], set[str]]:
    """(logins recovered from noreply addresses, author emails that could not be mapped)."""
    out = subprocess.run(
        ["git", "log", "--format=%aN\t%aE"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    logins: set[str] = set()
    unmapped: set[str] = set()
    for line in out.splitlines():
        name, _, email = line.partition("\t")
        email = email.strip()
        # A bot's noreply address contains `[` and `]`, which the login pattern excludes,
        # so it would otherwise land in `unmapped` and read as something to chase.
        if name in BOTS or name.endswith("[bot]"):
            continue
        m = NOREPLY.match(email)
        if m:
            logins.add(m.group("login"))
        elif email:
            unmapped.add(f"{name} <{email}>")
    return logins, unmapped


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="use git history instead of the GitHub API")
    args = ap.parse_args()

    wall = wall_logins()
    unmapped: set[str] = set()
    if args.offline:
        have, unmapped = logins_from_git()
        source = "git history"
    else:
        try:
            have = logins_from_api()
        except Exception as exc:  # network, rate limit, offline CI — degrade, don't crash
            print(f"GitHub API unavailable ({exc}); falling back to git history.", file=sys.stderr)
            have, unmapped = logins_from_git()
            source = "git history (API unavailable)"
        else:
            source = "GitHub API"

    lower = {w.lower() for w in wall}
    missing = sorted(login for login in have - BOTS if login.lower() not in lower)

    print(f"source: {source}")
    print(f"on the wall: {len(wall)}   with commits: {len(have - BOTS)}")

    if unmapped:
        print("\ncould not map to a GitHub login (check these by hand):")
        for who in sorted(unmapped):
            print(f"  ? {who}")

    if missing:
        print("\nhas merged commits but is NOT on the contributors wall:")
        for login in missing:
            print(f"  - {login}")
        print(
            "\nAdd each one, then re-run:\n"
            "  npx all-contributors-cli add <login> code\n"
            "and update CONTRIBUTORS.md plus the README badge count "
            "(tests/test_contributors_wall.py enforces all three agree)."
        )
        return 1

    print("\nEveryone with merged commits is on the wall.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
