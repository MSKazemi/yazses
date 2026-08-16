"""No shipped source file may be invisible to git.

`.gitignore` carried the snap build artifacts as `stage/`, `prime/`, `parts/`,
`overlay/`. An unanchored directory pattern matches that name at **any** depth, so
`overlay/` was also matching `src/yazses/overlay/` — the shipped voice-activity
overlay package.

Nothing looked wrong, because files already tracked are unaffected by `.gitignore`.
The failure was reserved for the next person: a new file added to that package
never appears in `git status` at all. No error, no warning, no diff — the work is
simply not in the commit, and it is found later by someone wondering why the
feature is missing from a release.

This checks the property rather than the four patterns, so a future rule that
swallows `src/yazses/tts/` or `src/yazses/gaze/` fails here on the day it is
written rather than the first time somebody loses an afternoon.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "yazses"


def _ignored(paths: list[str]) -> list[str]:
    """Which of *paths* git would ignore. Batched — one call, not one per file."""
    # --no-index is load-bearing. Without it `git check-ignore` skips paths that
    # are already tracked, so this would only ever notice a file nobody had
    # committed yet — and the whole point is that the *tracked* package is sitting
    # under a pattern that will swallow the next file added to it. The first
    # version of this omitted the flag and caught nothing.
    proc = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin"],
        cwd=ROOT, input="\n".join(paths), capture_output=True, text=True,
    )
    # exit 0 = some ignored, 1 = none ignored, 128 = not a git repo
    if proc.returncode == 128:
        pytest.skip("not a git checkout")
    return [line for line in proc.stdout.splitlines() if line.strip()]


def test_the_source_tree_is_there_to_check() -> None:
    """Guard the guard: an empty list would make the assertion below vacuous."""
    assert len(list(SRC.rglob("*.py"))) > 100


def test_no_python_source_file_is_ignored() -> None:
    files = [str(p.relative_to(ROOT)) for p in SRC.rglob("*.py")]
    ignored = _ignored(files)
    assert not ignored, (
        "these shipped source files are invisible to git — a new file beside them "
        "would never appear in `git status`:\n  " + "\n  ".join(sorted(ignored)[:20])
    )


def test_no_source_package_directory_is_ignored() -> None:
    """The directory matters as much as the files: the trap is what happens to the
    *next* file added there, not to the ones already tracked."""
    packages = [
        str(p.relative_to(ROOT))
        for p in SRC.rglob("*")
        if p.is_dir() and p.name != "__pycache__"
    ]
    assert packages, "no packages found — this guard is checking nothing"
    ignored = _ignored(packages)
    assert not ignored, (
        "these source packages are ignored, so anything added to them is silently "
        "dropped:\n  " + "\n  ".join(sorted(ignored))
    )


def test_the_snap_artefact_rules_are_anchored() -> None:
    """The specific cause, pinned. `overlay/` unanchored matched at any depth;
    `/overlay/` matches only the build directory it was written for."""
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for name in ("stage", "prime", "parts", "overlay"):
        assert f"\n/{name}/" in text, (
            f"the snap artefact rule for {name}/ is not anchored to the repository "
            f"root — unanchored, it matches a directory of that name anywhere, "
            f"including under src/"
        )


def test_the_tests_directory_is_not_ignored() -> None:
    """Same failure, equally silent: a new test that never runs in CI."""
    ignored = _ignored([str(p.relative_to(ROOT)) for p in (ROOT / "tests").glob("*.py")])
    assert not ignored, f"ignored test files: {sorted(ignored)[:10]}"
