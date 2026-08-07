#!/usr/bin/env python3
"""Fail when a tracked file is large enough to burden every clone, forever.

Git keeps history. A big file committed once is downloaded by every future clone even
after it is deleted, so the cost is permanent and the only cheap moment to catch it is
before the commit lands. This exists because that already happened here: a 35 MB screen
recording was swept into a commit by a broad `git add -A docs/`, unreferenced and
unnoticed, and removing it now would need a history rewrite and a force-push.

Screenshots and short demo GIFs are legitimate and small. The limit is set well above
them and well below anything that would make cloning noticeably slower.

    uv run python scripts/check_repo_size.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# A README demo GIF should come in under 5 MB (scripts/record-demo.py targets that and
# warns when it misses). 8 MB leaves headroom for a legitimately rich asset while still
# catching a full-screen recording, which is the failure that actually occurred.
MAX_BYTES = 8 * 1024 * 1024

# Paths allowed to exceed it, with the reason. Keep this list short and justified —
# an entry here is a permanent cost to everyone who clones the repo.
ALLOWED: dict[str, str] = {}


def tracked_files(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, capture_output=True, text=True, check=True
    ).stdout
    return [p for p in out.split("\0") if p]


def oversized(root: Path) -> list[tuple[str, int]]:
    found = []
    for rel in tracked_files(root):
        if rel in ALLOWED:
            continue
        path = root / rel
        try:
            size = path.stat().st_size
        except OSError:
            continue  # deleted in the working tree; not our problem here
        if size > MAX_BYTES:
            found.append((rel, size))
    return sorted(found, key=lambda t: -t[1])


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    big = oversized(root)
    if not big:
        print(f"No tracked file exceeds {MAX_BYTES // 1024 // 1024} MB.")
        return 0

    print(f"Tracked files over {MAX_BYTES // 1024 // 1024} MB:\n", file=sys.stderr)
    for rel, size in big:
        print(f"  {size / 1e6:8.1f} MB  {rel}", file=sys.stderr)
    print(
        "\nGit keeps history, so committing one of these makes every future clone pay "
        "for it permanently — deleting it later does not undo that.\n"
        "Shrink it, keep it out of the repo, or add it to ALLOWED in this script with a "
        "reason.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
