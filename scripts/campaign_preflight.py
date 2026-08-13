#!/usr/bin/env python3
"""Automated preflight for a campaign pull request.

Answers the cheap questions before a human spends review minutes: does the PR name a
task that exists, did it stay inside that task's allowed paths, and did it accidentally
commit a home path, hostname or email. It produces **one actionable summary**, not a wall
of logs — a newcomer who has to read raw workflow output has already been failed.

What it deliberately does **not** do: approve anything. It cannot judge whether a
translation reads naturally, whether hardware behaved as claimed, or whether an
architectural change is right. Those are human checks and stay human checks.

Security notes, because this reads contributor-controlled text:

* Nothing here is ever passed to a shell. The caller supplies file lists and text; this
  module only does string and regex work.
* The workflow runs on `pull_request`, not `pull_request_target`, so it has a read-only
  token and never sees repository secrets. It needs no write permission because it
  reports through the job summary rather than by posting a comment.

Usage:

    uv run python scripts/campaign_preflight.py --task-id APP-001 --changed-files a.md b.md
    uv run python scripts/campaign_preflight.py --pr-body-file body.txt --changed-files-from files.txt
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from campaign import load_tasks  # noqa: E402

#: `Task ID: APP-001`, `task-id: APP-001`, or a bare mention of a known id.
TASK_ID_RE = re.compile(r"task[ _-]?id\s*[:=]\s*([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)", re.I)
BARE_ID_RE = re.compile(r"\b([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)\b")

#: Patterns that mean a contributor pasted something from their own machine.
#: Each is (label, regex, hint). Kept deliberately narrow — a false positive on a first
#: PR costs more trust than a missed hint costs privacy, and a human still reviews.
PERSONAL_DATA = (
    (
        "a Linux home path",
        re.compile(r"/home/(?!user\b|runner\b|youruser\b)[a-z_][a-z0-9_-]{2,}/"),
        "replace with ~/ or /home/user/",
    ),
    (
        "a macOS home path",
        re.compile(r"/Users/(?!user\b|runner\b)[A-Za-z][A-Za-z0-9._-]{2,}/"),
        "replace with ~/ or /Users/user/",
    ),
    (
        "a Windows user path",
        re.compile(r"[Cc]:\\\\?Users\\\\?(?!user\b|Public\b)[A-Za-z][A-Za-z0-9._-]{2,}"),
        r"replace with C:\\Users\\user",
    ),
    (
        "an email address",
        re.compile(r"\b[\w.+-]+@(?!example\.(?:com|org)\b|users\.noreply\.github\.com\b)[\w-]+\.[\w.]{2,}\b"),
        "remove it, or use you@example.com",
    ),
    (
        "what looks like a token or key",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{16,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})\b"),
        "revoke it immediately, then remove it from the diff",
    ),
)


def find_task_id(text: str, known_ids: set[str] | None = None) -> str | None:
    """Pull a task id out of a PR title or body.

    Prefers an explicit `Task ID:` line. Falls back to any bare token that is a *known*
    id, which is what catches the common case of someone writing the id into the title
    and nothing else.
    """
    m = TASK_ID_RE.search(text)
    if m:
        return m.group(1).upper()
    if known_ids:
        for candidate in BARE_ID_RE.findall(text):
            if candidate.upper() in known_ids:
                return candidate.upper()
    return None


def path_allowed(path: str, allowed: list[str]) -> bool:
    """Is one changed file inside a task's allowed paths?

    `src/yazses/**` is written the way a human writes it and is expected to match
    `src/yazses/a/b.py`. `fnmatch` alone does not do that, so `**` is expanded to also
    match the zero-directory case.
    """
    for pattern in allowed:
        if fnmatch.fnmatch(path, pattern):
            return True
        # `a/**` should match `a/b` as well as `a/b/c`.
        if pattern.endswith("/**") and fnmatch.fnmatch(path, pattern[:-3]):
            return True
        if "**" in pattern and fnmatch.fnmatch(path, pattern.replace("/**", "*")):
            return True
    return False


def check_paths(changed: list[str], allowed: list[str]) -> list[str]:
    """Changed files that fall outside the task's declared scope."""
    return [p for p in changed if not path_allowed(p, allowed)]


def scan_personal_data(text: str) -> list[tuple[str, str, str]]:
    """Return (label, matched snippet, hint) for anything that looks personal."""
    out: list[tuple[str, str, str]] = []
    for label, pattern, hint in PERSONAL_DATA:
        for m in pattern.finditer(text):
            snippet = m.group(0)
            if len(snippet) > 60:
                snippet = snippet[:57] + "..."
            out.append((label, snippet, hint))
    return out


DIFF_FILE_RE = re.compile(r"^\+\+\+ b/(.+)$")


def split_added_lines_by_file(diff_text: str) -> dict[str, str]:
    """Group a unified diff's *added* lines by the file they were added to.

    Without this the scanner reports "an email address" with no idea where, which is not
    something a contributor can act on — and it makes a deliberate test fixture
    indistinguishable from a real leak.
    """
    by_file: dict[str, list[str]] = {}
    current: str | None = None
    for line in diff_text.splitlines():
        header = DIFF_FILE_RE.match(line)
        if header:
            current = header.group(1)
            by_file.setdefault(current, [])
            continue
        if line.startswith("+++") or line.startswith("+++ /dev/null"):
            continue
        if line.startswith("+") and current is not None:
            by_file[current].append(line)
    return {path: "\n".join(lines) for path, lines in by_file.items() if lines}


def scan_diff(diff_text: str) -> list[tuple[str, str, str, str]]:
    """Scan a unified diff, returning (path, label, snippet, hint).

    Falls back to scanning the whole blob under the path ``"the diff"`` when the input
    has no ``+++ b/`` headers — a caller may legitimately pass only added lines.
    """
    by_file = split_added_lines_by_file(diff_text)
    if not by_file:
        return [(("the diff"), *f) for f in scan_personal_data(diff_text)]
    out: list[tuple[str, str, str, str]] = []
    for path, added in sorted(by_file.items()):
        for label, snippet, hint in scan_personal_data(added):
            out.append((path, label, snippet, hint))
    return out


def environment_key(requires: dict | None) -> str:
    """The identity of a compatibility record: OS + session + install channel.

    Two reports of the same environment are a duplicate; two reports of the same OS on
    different desktop sessions are not, because X11 and Wayland behave differently enough
    to be separate evidence.
    """
    if not requires:
        return ""
    parts = [str(requires.get(k, "")).strip().lower() for k in ("os", "desktop", "channel")]
    return " | ".join(p for p in parts if p)


def duplicate_environment(task: dict, existing_text: str) -> str | None:
    """Has this exact environment already been reported?

    Finding out *after* spending an evening on it is the single most demoralising way to
    lose a first-time contributor, so this runs before a human reads the PR. It is
    advisory by design — an independent verification of a surprising result is genuinely
    useful, and the message says so rather than rejecting the work.
    """
    if task.get("family") != "compatibility":
        return None
    key = environment_key(task.get("requires"))
    if not key:
        return None
    haystack = existing_text.lower()
    if all(part.strip() in haystack for part in key.split("|")):
        return (
            f"an entry for this environment ({key}) already appears in SHOWCASE.md. "
            "That is not necessarily a problem — an independent confirmation, or a "
            "contradicting result, is worth having. Say in the PR which it is."
        )
    return None


def render_report(
    *,
    task_id: str | None,
    task: dict | None,
    changed: list[str],
    outside: list[str],
    findings: list[tuple[str, str, str, str]],
    duplicate: str | None = None,
) -> tuple[bool, str]:
    """Build the single summary a contributor reads. Returns (ok, markdown)."""
    lines = ["## Campaign preflight", ""]
    ok = True

    if task_id is None:
        lines += [
            "ℹ️ **No task ID found — nothing to check.**",
            "",
            "This PR does not reference a campaign task, so preflight has nothing to say "
            "and does not block you. If you are working on one, add `Task ID: <ID>` to the "
            "PR body. Everything else in CI still applies.",
        ]
        return True, "\n".join(lines) + "\n"

    if task is None:
        lines += [
            f"❌ **Task `{task_id}` is not in the inventory.**",
            "",
            "Check the ID against [`campaign/generated/open-tasks.md`]"
            "(../blob/main/campaign/generated/open-tasks.md). If the task was real and has "
            "been removed, say so in the PR and a maintainer will sort it out — this is not "
            "something you need to fix alone.",
        ]
        return False, "\n".join(lines) + "\n"

    lines += [f"**Task `{task_id}`** — {task['title']}", ""]
    lines.append(f"- ✅ Task exists · risk **{task['risk']}** · about {task['minutes']} min")

    if outside:
        ok = False
        lines += [
            f"- ❌ **{len(outside)} file(s) outside this task's scope:**",
            "",
        ]
        for p in outside[:20]:
            lines.append(f"  - `{p}`")
        if len(outside) > 20:
            lines.append(f"  - …and {len(outside) - 20} more")
        lines += [
            "",
            f"  This task may touch: {', '.join(f'`{p}`' for p in task['allowed_paths'])}.",
            "  If your change genuinely needs a file outside that list, say why in the PR —",
            "  the task may simply be scoped wrong, and that is ours to fix, not yours.",
        ]
    else:
        lines.append(f"- ✅ All {len(changed)} changed file(s) inside the task's scope")

    if findings:
        ok = False
        lines += ["- ❌ **Possible personal data in the diff:**", ""]
        seen: set[tuple[str, str, str]] = set()
        for path, label, snippet, hint in findings:
            if (path, label, snippet) in seen:
                continue
            seen.add((path, label, snippet))
            lines.append(f"  - `{path}` — {label}: `{snippet}` — {hint}")
        lines += [
            "",
            "  These are guesses from a regex, so a false positive is possible — if it is one,",
            "  say so and a maintainer will wave it through.",
        ]
    else:
        lines.append("- ✅ No obvious home path, email or token in the diff")

    if duplicate:
        # Advisory, never a failure: duplicate evidence still has value and the
        # scheduling mistake is ours.
        lines += ["- ⚠️ " + duplicate]

    lines += ["", "**Validate your work with:**", "", "```sh"]
    lines += list(task["validation"])
    lines.append("```")
    if task.get("evidence"):
        lines += ["", "**A human reviewer will look for:**", ""]
        lines += [f"- {e}" for e in task["evidence"]]
    return ok, "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Preflight a campaign PR.")
    ap.add_argument("--task-id")
    ap.add_argument("--pr-body-file", type=Path, help="file containing the PR title+body")
    ap.add_argument("--changed-files", nargs="*", default=[])
    ap.add_argument("--changed-files-from", type=Path, help="file with one path per line")
    ap.add_argument(
        "--diff-file",
        type=Path,
        help="unified diff (preferred, gives per-file attribution) or just its added lines",
    )
    args = ap.parse_args(argv)

    tasks = load_tasks()
    by_id = {t["id"]: t for t in tasks}

    task_id = args.task_id
    if not task_id and args.pr_body_file and args.pr_body_file.exists():
        task_id = find_task_id(
            args.pr_body_file.read_text(encoding="utf-8", errors="replace"), set(by_id)
        )

    changed = list(args.changed_files)
    if args.changed_files_from and args.changed_files_from.exists():
        changed += [
            ln.strip()
            for ln in args.changed_files_from.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]

    task = by_id.get(task_id) if task_id else None

    # A PR that edits the task inventory is *maintaining* a task, not claiming one.
    #
    # `find_task_id` falls back to any bare known id in the PR text, which is what
    # catches a contributor who writes the id in the title and nothing else. But it
    # cannot tell that apart from a maintainer PR that merely *discusses* the task it
    # is repairing -- and then enforces that task's `allowed_paths` against the very
    # file the task is defined in. The result is a PR fixing a wrongly scoped task,
    # blocked by the wrong scope it is fixing, with no way out but to avoid writing
    # the id in the description.
    #
    # An explicit `Task ID:` line still means what it says; only the guess is dropped.
    inventory_touched = any(
        p.strip() == "campaign/tasks.json" or p.strip().startswith("campaign/generated/")
        for p in changed
    )
    guessed = task_id is not None and not args.task_id
    if task and guessed and inventory_touched:
        task = None
        task_id = None

    outside = check_paths(changed, task["allowed_paths"]) if task else []
    findings = []
    if args.diff_file and args.diff_file.exists():
        findings = scan_diff(args.diff_file.read_text(encoding="utf-8", errors="replace"))

    duplicate = None
    if task:
        showcase = ROOT / "SHOWCASE.md"
        if showcase.exists():
            duplicate = duplicate_environment(task, showcase.read_text(encoding="utf-8"))

    ok, report = render_report(
        task_id=task_id, task=task, changed=changed, outside=outside,
        findings=findings, duplicate=duplicate,
    )
    print(report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(report)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
