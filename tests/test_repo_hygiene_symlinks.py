"""No tracked file may be a symlink that points outside the repository.

A merge landed `.venv` in git as a symlink to the absolute path
`/home/mohsen/scratch/repos/yazses/.venv`, and it reached `origin/main`. It looks
harmless on the machine that created it, because there the target exists. Every
other clone gets a dangling link — and worse, a link that points *outside the
working tree*, so a `uv sync` or `python -m venv .venv` in a fresh clone follows
it and writes somewhere the user did not choose.

`.gitignore` already listed `.venv`, which is exactly why this was invisible:
ignore rules do not apply to a path that is added explicitly or with `-f`, and
nothing else looked. `git status` shows a symlink as an ordinary file, so it does
not stand out in a review either.

This is the check that was missing. It reads the index, so it covers both "about
to be committed" locally and "what is in this commit" in CI.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from tests.gitprobe import require_git

ROOT = Path(__file__).resolve().parent.parent

# git's mode for a symlink. Regular files are 100644/100755.
SYMLINK_MODE = "120000"

# Directories that must never be tracked at all, whatever their type. A build or
# environment directory in git is always a mistake, and tracking it as a symlink
# is how it slips past a `.gitignore` that names the directory.
NEVER_TRACKED = {".venv", "venv", "node_modules", "site", "dist", "build", "__pycache__"}


def _tracked_entries() -> list[tuple[str, str, str]]:
    """(mode, object, path) for everything in the index."""
    require_git()
    out = subprocess.run(
        ["git", "ls-files", "-s"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    entries = []
    for line in out.splitlines():
        meta, _, path = line.partition("\t")
        mode, obj, _stage = meta.split()
        entries.append((mode, obj, path))
    return entries


def _symlink_target(obj: str) -> str:
    """A symlink's blob content IS its target path."""
    return subprocess.run(
        ["git", "cat-file", "blob", obj], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def test_no_tracked_symlink_points_outside_the_repository() -> None:
    """The defect this exists for. An absolute target is never right in a repo —
    it encodes one machine's filesystem and breaks or escapes on every other."""
    offenders = []
    for mode, obj, path in _tracked_entries():
        if mode != SYMLINK_MODE:
            continue
        target = _symlink_target(obj)
        if target.startswith("/"):
            offenders.append(f"{path} -> {target}  (absolute)")
            continue
        # Relative links are fine as long as they stay inside the tree.
        resolved = (ROOT / Path(path).parent / target).resolve()
        try:
            resolved.relative_to(ROOT.resolve())
        except ValueError:
            offenders.append(f"{path} -> {target}  (escapes the repo)")
    assert not offenders, (
        "tracked symlinks point outside the repository — every clone gets a "
        "dangling or escaping link:\n  " + "\n  ".join(offenders)
    )


def test_environment_and_build_directories_are_not_tracked() -> None:
    """`.gitignore` naming a directory does not protect it: an explicit or forced
    `git add` bypasses ignore rules entirely, which is how `.venv` got in."""
    tracked = {path for _mode, _obj, path in _tracked_entries()}
    offenders = sorted(
        p for p in tracked
        if p in NEVER_TRACKED or any(p.startswith(f"{d}/") for d in NEVER_TRACKED)
    )
    assert not offenders, (
        f"these must never be tracked: {offenders}. Remove with "
        f"`git rm --cached <path>` — .gitignore alone will not undo an explicit add."
    )


def test_gitignore_covers_the_venv_both_ways() -> None:
    """`.venv/` (with the slash) matches a directory but NOT a symlink named
    `.venv`. Both spellings must be present or the symlink form slips through."""
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    lines = {ln.strip() for ln in text.splitlines()}
    assert ".venv" in lines, ".gitignore needs a bare `.venv` to cover the symlink form"
    assert ".venv/" in lines, ".gitignore needs `.venv/` to cover the directory form"
