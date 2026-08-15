#!/usr/bin/env python3
"""Fail if anything private reached the *built* site.

Why this exists when `tests/test_private_tiers_stay_private.py` and
`tests/test_design_tier_hook.py` already guard the private trees: both test the
**hook's logic**. They prove the exclusion rule is right and reads its list from
the one source of truth. Neither looks at what was actually published.

Those are different claims, and the gap between them is where a leak lives. A
correct hook that does not run publishes everything. A file can also reach the
site by a route the hook never sees — an entry added to the nav by hand, a copied
asset, a `!!! include`. The build artifact is the thing users can download, so it
is the thing worth checking.

Deliberately run against `site/` after `mkdocs build` rather than as a pytest:
building the site takes the better part of a minute, and a test that silently
skips when `site/` is absent would be a guard that passes by checking nothing —
the failure mode this repository has already been bitten by more than once.

Usage:
    python3 scripts/check-site-privacy.py [site-dir]

Exit 1 and prints every offending file. stdlib only, so a docs job with no project
dependencies installed can still run it.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Used only when the hook is unreadable (a fresh clone has no hooks until
#: `core.hooksPath` or git templating installs them). Kept identical to the list
#: in tests/test_private_tiers_stay_private.py.
DOCUMENTED = ["strategy", "design/vision", "design/marketing", "design/seo", ".claude"]

#: Files that legitimately mention a private path without containing its content:
#: the design tier's own generated indexes explain what is *excluded*, and saying
#: so requires naming it.
ALLOWED = {"404.html", "sitemap.xml", "sitemap.xml.gz", "search/search_index.json"}


def private_prefixes(hook_text: str | None) -> list[str]:
    """The private trees, read out of the pre-commit hook's own regex.

    Restating them would recreate the drift the hook exists to prevent — the same
    reasoning, and the same regex, as the test module.
    """
    if not hook_text:
        return list(DOCUMENTED)
    match = re.search(r"\(\^\|\[\^a-zA-Z0-9_/-\]\)\(([^)]+)\)/", hook_text)
    if not match:
        return list(DOCUMENTED)
    return [p.replace("\\", "") for p in match.group(1).split("|")]


def offending_paths(paths: list[str], prefixes: list[str]) -> list[str]:
    """Published paths that sit inside a private tree.

    Matched on path segments, not substrings: a page named `strategy-and-scope.md`
    is not in `strategy/`, and flagging it would train someone to ignore this
    check — which is worse than not having it.
    """
    bad: list[str] = []
    for path in paths:
        parts = path.split("/")
        for prefix in prefixes:
            wanted = prefix.split("/")
            if any(parts[i:i + len(wanted)] == wanted for i in range(len(parts))):
                bad.append(path)
                break
    return bad


def _hook_text() -> str | None:
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    hook = (ROOT / common / "hooks" / "pre-commit").resolve()
    return hook.read_text(encoding="utf-8", errors="ignore") if hook.is_file() else None


def main(argv: list[str]) -> int:
    site = Path(argv[1]) if len(argv) > 1 else ROOT / "site"
    if not site.is_dir():
        print(f"no built site at {site} — run `mkdocs build` first", file=sys.stderr)
        return 2

    prefixes = private_prefixes(_hook_text())
    published = [
        str(p.relative_to(site)) for p in site.rglob("*") if p.is_file()
    ]
    if not published:
        print(f"{site} contains no files — refusing to report a clean site", file=sys.stderr)
        return 2

    bad = [p for p in offending_paths(published, prefixes) if p not in ALLOWED]
    if bad:
        print(f"private content reached the built site ({len(bad)} file(s)):", file=sys.stderr)
        for path in sorted(bad)[:40]:
            print(f"  {path}", file=sys.stderr)
        print(f"\nprivate trees: {', '.join(prefixes)}", file=sys.stderr)
        return 1

    print(f"site is clean — {len(published)} files, none inside {', '.join(prefixes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
