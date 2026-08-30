#!/usr/bin/env python3
"""Ask GitHub whether each pinned action SHA really is the version written beside it.

`tests/test_workflow_actions_are_pinned.py` proves, offline, that every `uses:` names a
commit SHA and carries a `# <version>` comment, and that the same pin is labelled the
same way everywhere. What it cannot prove is that the label is *true*: a comment that
is uniformly wrong disagrees with nothing. That is not a hypothetical — on 2026-08-30
six pins in this repository read `# v2`, `# v4` and `# release/v1` while pointing at
v4.2.2, v7 and v1.14.2, and `# v2` was `# v2` at all three of its sites.

Answering it needs one question per pin that only GitHub can answer — "what commit does
tag `v4.2.2` of `actions/attest-build-provenance` point at?" — so this is a script run
by hand (and after a Dependabot sweep), never a test. Nothing in `src/` gains an
outbound call; ADR-019's egress inventory is unaffected.

    python scripts/check-action-pins.py            # check every workflow
    python scripts/check-action-pins.py --fix      # rewrite the comments that are wrong

Exit status is 0 when every comment is accurate, 1 otherwise, so it can gate a release
step if that is ever wanted. Unauthenticated requests are rate-limited to 60/hour;
export `GITHUB_TOKEN` (or `GH_TOKEN`) to lift that.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO / ".github" / "workflows"
API = "https://api.github.com"

_USES = re.compile(r"^(?P<head>\s*(?:-\s+)?uses:\s*)(?P<ref>\S+?)(?:\s*#\s*(?P<comment>.+?))?\s*$")
_SHA = re.compile(r"^[0-9a-f]{40}$")


def _get(url: str) -> dict | None:
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def resolve_tag(action: str, tag: str) -> str | None:
    """The commit SHA that *tag* of *action* points at, or None if there is no such tag.

    Annotated tags need dereferencing: `git/ref/tags/<tag>` on an annotated tag returns
    the **tag object**, not the commit, and comparing that against a pin is how a
    correct pin gets reported as wrong. Most action publishers use lightweight tags and
    a few do not, which is exactly the mix that makes the bug intermittent.
    """
    owner_repo = "/".join(action.split("/")[:2])
    ref = _get(f"{API}/repos/{owner_repo}/git/ref/tags/{tag}")
    if ref is None:
        return None
    obj = ref["object"]
    if obj["type"] == "tag":
        return _get(f"{API}/repos/{owner_repo}/git/tags/{obj['sha']}")["object"]["sha"]
    return obj["sha"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fix", action="store_true", help="rewrite comments that are wrong")
    args = parser.parse_args()

    files = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
    if not files:
        print(f"no workflows under {WORKFLOWS}", file=sys.stderr)
        return 1

    # One network round-trip per distinct (action, tag), not per line: `actions/checkout`
    # alone is pinned in 35 places.
    claims: dict[tuple[str, str], list[str]] = defaultdict(list)
    pins: dict[tuple[str, str], str] = {}
    for path in files:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = _USES.match(line)
            if not match:
                continue
            ref, comment = match.group("ref").strip("'\""), match.group("comment")
            if ref.startswith((".", "/", "docker://")) or "@" not in ref or not comment:
                continue
            action, sha = ref.split("@", 1)
            if not _SHA.match(sha):
                continue
            tag = comment.strip().split()[0]
            claims[(action, tag)].append(f"{path.name}:{number}")
            pins[(action, tag)] = sha

    wrong: list[tuple[str, str, str, str]] = []
    unknown: list[tuple[str, str]] = []
    for (action, tag), sha in sorted(pins.items()):
        actual = resolve_tag(action, tag)
        if actual is None:
            unknown.append((action, tag))
            print(f"?  {action}@{tag}: no such tag upstream")
        elif actual != sha:
            wrong.append((action, tag, sha, actual))
            print(f"✗  {action} pinned {sha[:12]} but says {tag}, which is {actual[:12]}")
        else:
            print(f"✓  {action}@{tag}")

    if args.fix and wrong:
        # The pin is the truth and the comment is the claim, so the comment is what
        # moves. Rewriting the SHA instead would silently upgrade an action.
        for action, tag, sha, actual in wrong:
            correct = _describe(action, sha) or "unknown"
            for path in files:
                text = path.read_text(encoding="utf-8")
                new = text.replace(f"{action}@{sha} # {tag}", f"{action}@{sha} # {correct}")
                if new != text:
                    path.write_text(new, encoding="utf-8")
            print(f"→  {action}@{sha[:12]}: # {tag} → # {correct}")

    print(
        f"\n{len(pins)} distinct pins across {len(files)} workflows: "
        f"{len(pins) - len(wrong) - len(unknown)} accurate, {len(wrong)} wrong, "
        f"{len(unknown)} unresolvable"
    )
    return 1 if wrong or unknown else 0


def _describe(action: str, sha: str) -> str | None:
    """The most specific tag pointing at *sha*, preferring `v1.2.3` over `v1`."""
    owner_repo = "/".join(action.split("/")[:2])
    tags = _get(f"{API}/repos/{owner_repo}/tags?per_page=100") or []
    names = [t["name"] for t in tags if t["commit"]["sha"] == sha]
    return max(names, key=len) if names else None


if __name__ == "__main__":
    sys.exit(main())
