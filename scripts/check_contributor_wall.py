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

It also checks the reverse direction — wall entries whose GitHub account no longer
resolves, which happens when someone deletes or renames their account and leaves a 404
behind on the README. That one is reported but **never fatal**: the work still shipped, so
the entry must stay and the link gets repaired. Skip it with `--no-check-profiles`.

Exit status is 0 when every contributor with commits is on the wall, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
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


def probe_profile(login: str) -> int | None:
    """HTTP status for a GitHub account, or None when the request itself failed."""
    req = urllib.request.Request(
        f"https://api.github.com/users/{login}", headers={"Accept": "application/vnd.github+json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception:
        return None


def dead_wall_profiles(logins: set[str], probe=probe_profile) -> set[str]:
    """Wall entries whose GitHub account no longer resolves.

    The check above runs one direction only — *everyone with commits is on the wall* — and
    that is blind to the opposite failure: a wall entry pointing at an account that has since
    been deleted or renamed. Worse, it is blind *quietly*. When an account goes, GitHub stops
    listing it in `/contributors`, so `have` simply shrinks and the run still exits 0. The
    guard gets weaker at the same moment the problem appears.

    Anything other than a definite 404 is treated as "no opinion" and aborts the whole
    sub-check: a rate limit (403) or a transient error must never be reported as "this person
    does not exist". A false accusation here is far worse than silence.
    """
    dead: set[str] = set()
    for login in sorted(logins):
        status = probe(login)
        if status == 404:
            dead.add(login)
        elif status != 200:
            return set()  # rate-limited or offline — say nothing rather than something wrong
    return dead


def redact_email(entry: str) -> str:
    """`Ada Lovelace <ada@example.com>` -> `Ada Lovelace <a…@example.com>`.

    Enough for a maintainer to recognise the person and follow up privately; not enough to
    harvest. A contributor's address must never be printed into a public log, and workflow
    logs on a public repository are public — the same rule `campaign_stats.py` follows.
    """
    if "<" not in entry or "@" not in entry:
        return entry
    name, _, addr = entry.partition("<")
    addr = addr.rstrip(">")
    local, _, domain = addr.partition("@")
    masked = (local[0] + "\u2026") if local else "\u2026"
    return f"{name}<{masked}@{domain}>"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="use git history instead of the GitHub API")
    ap.add_argument(
        "--no-check-profiles",
        action="store_true",
        help="skip the reverse check (wall entries whose GitHub account no longer resolves)",
    )
    ap.add_argument(
        "--redact-emails",
        action="store_true",
        help="mask author addresses in the output — required when running in CI, because "
             "workflow logs on a public repository are public",
    )
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
            print(f"  ? {redact_email(who) if args.redact_emails else who}")

    # Reverse check. Deliberately NON-FATAL: a contributor whose account has gone must stay
    # on the wall — the work shipped — so failing CI here would only pressure someone into
    # "fixing" it by deleting the person, which is the outcome this whole script exists to
    # prevent. Report it, repair the link, keep the credit.
    if source == "GitHub API" and not args.no_check_profiles:
        dead = dead_wall_profiles(wall)
        if dead:
            print("\non the wall but the GitHub account no longer resolves:")
            for login in sorted(dead):
                print(f"  ! {login}  (https://github.com/{login} -> 404)")
            print(
                "\nDo NOT remove them — their commits are still in the history and in every\n"
                "release. Repoint the profile link (the `?author=` commits URL still works)\n"
                "and leave the credit in place."
            )

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
