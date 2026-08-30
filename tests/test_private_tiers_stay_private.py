"""Nothing from a private tier may be tracked in this repository.

`design/README.md` defines three tiers, and the pre-commit hook enforces one half of
the rule: a public file must not *reference* a path inside a private tree, because the
link dangles and the filename itself leaks what is being held back.

Nothing enforced the other half — that a private path is not **committed** in the first
place. That gap is not hypothetical: writing the problem-space document for this backlog, I
created it inside the private vision tree, committed it, and linked it from the public
docs site. The hook stopped the *link*. The file had already been public for two commits.

(This very docstring had to be rewritten to name the tree without naming a file inside
it — the hook blocked the first draft. That is the rule working, on the file that
enforces it.)

A reference is a broken link. A committed file is a disclosure, and it is the worse of
the two — so it deserves the stronger check.

The prefixes below are read from the hook itself rather than restated, so the two cannot
drift apart. If the hook's list changes, this test follows it.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from tests.gitprobe import require_git

ROOT = Path(__file__).resolve().parent.parent


def _hook_path() -> Path | None:
    """The pre-commit hook, resolving the worktree indirection.

    In a linked worktree `.git` is a file pointing at the real git dir, and hooks live
    in the *common* dir shared with the main checkout — so `git rev-parse --git-dir` is
    the wrong one to ask.
    """
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):  # pragma: no cover
        return None
    hook = (ROOT / common / "hooks" / "pre-commit").resolve()
    return hook if hook.is_file() else None


def _private_prefixes() -> list[str]:
    """The private trees, read out of the hook's own regex.

    Restating them here would create exactly the drift this file exists to prevent.
    Falls back to the documented set when the hook is absent (a fresh clone has no
    hooks until `core.hooksPath` or `git init` templating installs them).
    """
    documented = ["strategy", "design/vision", "design/marketing", "design/seo", ".claude"]
    hook = _hook_path()
    if hook is None:
        return documented
    text = hook.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r"\(\^\|\[\^a-zA-Z0-9_/-\]\)\(([^)]+)\)/", text)
    if not match:
        return documented
    return [p.replace("\\", "") for p in match.group(1).split("|")]


def _tracked_files() -> list[str]:
    require_git()
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [line for line in out.splitlines() if line]


def test_the_hook_is_readable_and_names_private_trees():
    """Guard the guard: silently falling back to a stale list would defeat the point."""
    prefixes = _private_prefixes()
    assert prefixes, "no private prefixes found in the hook or the fallback"
    assert "design/vision" in prefixes, (
        f"expected design/vision among the private trees, got {prefixes} — if the tiers "
        f"changed, update design/README.md and this expectation together"
    )


@pytest.mark.parametrize("prefix", _private_prefixes())
def test_no_private_path_is_tracked(prefix: str):
    """A committed private file is a disclosure, not a broken link."""
    leaked = sorted(f for f in _tracked_files() if f == prefix or f.startswith(f"{prefix}/"))
    assert not leaked, (
        f"these files are tracked but live in the private tier {prefix!r}: {leaked}\n\n"
        f"Move them to a public tier (design/ for engineering and science, docs/ for "
        f"user-facing material) or remove them from the index. See design/README.md."
    )


def test_the_public_engineering_tier_is_actually_populated():
    """The counterpart check: if everything ended up private, the tiers are misconfigured
    rather than merely tidy."""
    tracked = _tracked_files()
    public_design = [f for f in tracked if f.startswith("design/") and "/vision/" not in f]
    assert len(public_design) > 10, (
        f"only {len(public_design)} files in the public design tier — that is a sign "
        f"material has been misfiled as private, not that there is nothing to publish"
    )
