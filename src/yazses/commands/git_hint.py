"""Project name and git branch as recognition hints (pure; ADR-v2-004, ``[context] use_git``).

When dictating into a terminal or editor that sits inside a git repository, the
project's name and its branch ("fix-tray-crash" → "tray", "crash") are the words the
user is most likely to say. This module finds them from a directory **by reading
files**: it walks up to ``.git``, follows a ``gitdir:`` pointer when ``.git`` is a file
(a linked worktree or a submodule), and reads ``HEAD``. No subprocess, no ``git``
binary, no network, and nothing is written.

Which directory to start from is platform-specific (the focused window's working
directory, ``platform/base.py`` :class:`FocusedCwdProvider`); this module only takes a
path. Like the rest of ``[context]``, what it reads is used for one decode and NEVER
stored or logged -- not the path, not the repo name, not the branch. Every function
here returns ``None``/``[]`` rather than raising.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from yazses.gitvoice.plan import split_ref_words

#: How far up from the start directory to look for ``.git``. Deep enough for any real
#: checkout, and a bound so a pathological path can never make the hot path walk forever.
_MAX_WALK_UP = 64

#: ``HEAD``, ``commondir`` and a ``.git`` pointer file are one line each. Reading more than
#: this means the file is not what it claims to be, and it is ignored.
_MAX_POINTER_BYTES = 4096

_REF_PREFIX = "ref:"
_HEADS = "refs/heads/"
_GITDIR_PREFIX = "gitdir:"
#: A branch word must carry at least one letter: "123" in "issue-123" biases nothing.
_HAS_LETTER = re.compile(r"[A-Za-z]")


@dataclass(frozen=True)
class GitHint:
    """What a repository says about itself, for one decode. Never stored."""

    repo_name: str
    branch: str | None  # None on a detached HEAD (or a HEAD that names no branch)


def _read_small(path: Path) -> str | None:
    """A one-line git metadata file's text, or None when absent, unreadable or too big."""
    try:
        with path.open("rb") as fh:
            data = fh.read(_MAX_POINTER_BYTES + 1)
    except OSError:
        return None
    if len(data) > _MAX_POINTER_BYTES:
        return None
    try:
        return data.decode("utf-8").strip()
    except UnicodeDecodeError:
        return None


def _resolve_git_dir(dot_git: Path) -> Path | None:
    """The real git directory behind *dot_git*: itself, or what its ``gitdir:`` names.

    A linked worktree's ``.git`` is a file reading ``gitdir: <main>/.git/worktrees/<n>``;
    a submodule's reads ``gitdir: ../.git/modules/<n>``. A relative pointer is relative to
    the directory holding the ``.git`` file, as git itself reads it.
    """
    if dot_git.is_dir():
        return dot_git
    text = _read_small(dot_git)
    if not text or not text.startswith(_GITDIR_PREFIX):
        return None
    target = Path(text[len(_GITDIR_PREFIX):].strip())
    if not target.is_absolute():
        target = dot_git.parent / target
    return target if target.is_dir() else None


def find_git(start: Path) -> tuple[Path, Path] | None:
    """``(work_tree_root, git_dir)`` for the repository containing *start*, or None.

    Walks *start* and its parents (bounded by :data:`_MAX_WALK_UP`) for a ``.git`` entry,
    directory or pointer file. The nearest one wins, so a nested repository or a
    submodule answers for itself rather than for the repository around it.
    """
    try:
        here = Path(start)
        if not here.is_absolute():
            return None
        if not here.is_dir():
            here = here.parent
    except (OSError, ValueError):
        return None
    for _ in range(_MAX_WALK_UP):
        dot_git = here / ".git"
        try:
            if dot_git.exists():
                git_dir = _resolve_git_dir(dot_git)
                return (here, git_dir) if git_dir is not None else None
        except OSError:
            return None
        if here.parent == here:
            return None
        here = here.parent
    return None


def read_branch(git_dir: Path) -> str | None:
    """The checked-out branch named by ``git_dir/HEAD``, or None when HEAD is detached.

    ``ref: refs/heads/feature/login`` → ``feature/login``. A bare commit id (detached
    HEAD), a symbolic ref outside ``refs/heads/`` and an unreadable file all give None.
    """
    text = _read_small(git_dir / "HEAD")
    if not text or not text.startswith(_REF_PREFIX):
        return None
    ref = text[len(_REF_PREFIX):].strip()
    if not ref.startswith(_HEADS):
        return None
    return ref[len(_HEADS):] or None


def _repo_name(work_tree: Path, git_dir: Path) -> str:
    """The project's name: the main checkout's directory, not a linked worktree's.

    A linked worktree's git directory carries ``commondir`` pointing at the shared
    repository (``<main>/.git``); the project is the directory holding that. Without one
    (an ordinary checkout, a submodule) the work tree's own directory is the name.
    """
    common = _read_small(git_dir / "commondir")
    if common:
        common_dir = Path(common)
        if not common_dir.is_absolute():
            common_dir = git_dir / common_dir
        try:
            common_dir = common_dir.resolve()
        except (OSError, RuntimeError):
            return work_tree.name
        if common_dir.name == ".git":
            return common_dir.parent.name
        return common_dir.name.removesuffix(".git") or work_tree.name
    return work_tree.name


def git_hint(start: Path | None) -> GitHint | None:
    """The repository name and branch for *start*, or None when it is in no repository."""
    if start is None:
        return None
    found = find_git(start)
    if found is None:
        return None
    work_tree, git_dir = found
    try:
        return GitHint(repo_name=_repo_name(work_tree, git_dir), branch=read_branch(git_dir))
    except (OSError, ValueError):
        return None


def hint_terms(hint: GitHint | None, max_terms: int = 48) -> list[str]:
    """Prompt terms from a :class:`GitHint`: name, branch, then the branch's words.

    ``GitHint("yazses", "fix-tray-crash")`` → ``["yazses", "fix-tray-crash", "fix",
    "tray", "crash"]``. The branch is split with the spoken-separator table in
    ``gitvoice/plan.py`` (:func:`split_ref_words`), so a branch is heard as the words a
    user says for it. De-duplicated case-insensitively; capped at *max_terms*.
    """
    if hint is None or max_terms <= 0:
        return []
    terms: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        key = term.lower()
        if term and key not in seen:
            seen.add(key)
            terms.append(term)

    add(hint.repo_name)
    if hint.branch:
        add(hint.branch)
        for word in split_ref_words(hint.branch):
            if len(word) > 1 and _HAS_LETTER.search(word):
                add(word)
    return terms[:max_terms]


__all__ = ["GitHint", "find_git", "git_hint", "hint_terms", "read_branch"]
