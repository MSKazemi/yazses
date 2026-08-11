#!/usr/bin/env python3
"""Check one campaign task locally, before you push.

    uv run python scripts/check-task.py APP-014

Runs the same three checks CI will run — your changes are inside the task's allowed
paths, nothing personal reached the diff, and the task's own validation command passes —
and prints what a human reviewer will then look for.

**Why this exists separately from the CI preflight.** Finding out your diff was out of
scope *after* pushing, from a red check on your first pull request, is a bad way to learn
it. This is the same logic run against your working tree, so the answer arrives while the
work is still in front of you. `make check` remains the full gate; this is the narrow one
the task actually needs.

Exit code is 0 when everything passed, 1 otherwise, so it can gate a pre-push hook.
"""
from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from campaign_preflight import check_paths, scan_diff  # noqa: E402

from campaign import load_tasks, validation_command_problem  # noqa: E402


def changed_files(base: str) -> list[str]:
    """Files changed in the working tree versus `base`, staged or not."""
    cmds = [
        ["git", "-C", str(ROOT), "diff", "--name-only", base],
        ["git", "-C", str(ROOT), "diff", "--name-only", "--cached"],
        ["git", "-C", str(ROOT), "ls-files", "--others", "--exclude-standard"],
    ]
    out: list[str] = []
    for cmd in cmds:
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            continue
        for line in res.stdout.splitlines():
            if line.strip() and line.strip() not in out:
                out.append(line.strip())
    return out


def working_diff(base: str) -> str:
    """The unified diff of everything not yet on `base`, staged and unstaged."""
    parts: list[str] = []
    for cmd in (
        ["git", "-C", str(ROOT), "diff", base],
        ["git", "-C", str(ROOT), "diff", "--cached"],
    ):
        try:
            parts.append(subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout)
        except (OSError, subprocess.SubprocessError):
            pass
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("task_id", nargs="?", help="e.g. APP-014. Omit to list open tasks.")
    ap.add_argument("--base", default="origin/main", help="compare against this ref")
    ap.add_argument("--no-run", action="store_true", help="check scope only; do not run validation")
    args = ap.parse_args(argv)

    tasks = {t["id"]: t for t in load_tasks()}

    if not args.task_id:
        openable = sorted(t for t, v in tasks.items() if v["state"] == "open")
        print(f"{len(openable)} open tasks. Pick one:\n")
        for tid in openable[:40]:
            print(f"  {tid:<28} {tasks[tid]['title'][:60]}")
        if len(openable) > 40:
            print(f"  …and {len(openable) - 40} more — see campaign/generated/open-tasks.md")
        return 0

    task_id = args.task_id.upper()
    task = tasks.get(task_id)
    if task is None:
        print(f"✗ No task {task_id!r}. See campaign/generated/open-tasks.md", file=sys.stderr)
        return 1

    print(f"Task {task_id} — {task['title']}")
    print(f"  risk {task['risk']} · about {task['minutes']} min")
    print(f"  may touch: {', '.join(task['allowed_paths'])}\n")

    ok = True
    changed = changed_files(args.base)
    if not changed:
        print(f"· No changes yet versus {args.base}. Nothing to check.")
    else:
        outside = check_paths(changed, task["allowed_paths"])
        if outside:
            ok = False
            print(f"✗ {len(outside)} file(s) outside this task's scope:")
            for p in outside:
                print(f"    {p}")
            print("  If the change genuinely needs them, say why in the PR — the task may")
            print("  simply be scoped wrong, and that is ours to fix, not yours.\n")
        else:
            print(f"✓ all {len(changed)} changed file(s) inside the task's scope\n")

        findings = scan_diff(working_diff(args.base))
        if findings:
            ok = False
            print("✗ possible personal data in the diff:")
            seen = set()
            for path, label, snippet, hint in findings:
                if (path, snippet) in seen:
                    continue
                seen.add((path, snippet))
                print(f"    {path} — {label}: {snippet} — {hint}")
            print()
        else:
            print("✓ no obvious home path, email or token in the diff\n")

    if args.no_run:
        print("· skipping validation (--no-run)")
    else:
        for cmd in task["validation"]:
            # tasks.json is a code-execution surface: this runs on the contributor's own
            # machine. Re-checked here rather than trusting that the file was validated,
            # and run without a shell so metacharacters cannot chain a second command.
            problem = validation_command_problem(cmd)
            if problem:
                print(f"✗ refusing to run — {problem}")
                ok = False
                continue
            print(f"▶  {cmd}")
            try:
                res = subprocess.run(shlex.split(cmd), cwd=ROOT, timeout=1800)
            except (OSError, subprocess.SubprocessError) as exc:
                print(f"✗ could not run it: {exc}")
                ok = False
                continue
            if res.returncode != 0:
                ok = False
                print(f"✗ failed (exit {res.returncode})\n")
            else:
                print("✓ passed\n")

    if task.get("evidence"):
        print("A human reviewer will look for:")
        for e in task["evidence"]:
            print(f"  - {e}")
        print()

    print("✓ ready to push" if ok else "✗ not ready yet — see above")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
