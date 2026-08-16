"""The privacy hook's two lists must agree about what is private.

`.git/hooks/pre-commit` carries two regexes:

* **`blocked_re`** — paths that may not be committed at all;
* a **link-leak** pattern — private trees a *public* file may not even mention,
  because the link would dangle for every reader.

They listed different sets. `design/vision/`, `design/marketing/` and `design/seo/`
appeared in the link-leak pattern and in `hooks/design_tier.py`'s private-prefix list,
and **were absent from `blocked_re`**. So the docs site excluded them, a public file
could not link to them, and `git add -A` would have committed the files themselves to
a public repository. Three mechanisms agreed a tree was private and the one that
mattered did not.

That is the repository's recurring shape — a guard that looks like protection and is
not — and the reason this test compares the lists to each other rather than to a
literal set of its own. A hardcoded list here would be a fourth place to forget.

The hook is machine-local (`.git/hooks/` is not tracked), so this skips where it is
absent rather than failing a clone that never installed it. On a machine that has it —
this one, and any where the guard is meant to be doing its job — it runs.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / ".git" / "hooks" / "pre-commit"


def _hook_text() -> str:
    if not HOOK.is_file():
        pytest.skip("no .git/hooks/pre-commit on this checkout")
    return HOOK.read_text(encoding="utf-8", errors="ignore")


def _blocked_re(text: str) -> str:
    m = re.search(r"blocked_re='([^']+)'", text)
    assert m, "cannot find blocked_re in the hook — its shape changed"
    return m.group(1)


def _link_private_trees(text: str) -> tuple[str, ...]:
    """The trees the link-leak check calls private. Parsed exactly the way
    `hooks/design_tier.py` parses them, so all three agree by construction."""
    m = re.search(r"\(\^\|\[\^a-zA-Z0-9_/-\]\)\(([^)]+)\)/", text)
    assert m, "cannot find the link-leak pattern in the hook — its shape changed"
    return tuple(p.replace("\\", "") for p in m.group(1).split("|"))


def test_the_hook_is_parseable() -> None:
    """Guard the guard: a parse failure must not read as agreement."""
    text = _hook_text()
    assert _blocked_re(text)
    trees = _link_private_trees(text)
    assert len(trees) >= 3, f"only {trees} parsed out of the link-leak pattern"


@pytest.mark.parametrize(
    "tree",
    ["strategy", "design/vision", "design/marketing", "design/seo", ".claude"],
)
def test_every_tree_called_private_cannot_be_committed(tree: str) -> None:
    """The property that was violated.

    Parameterised over the known trees rather than only over what the hook happens
    to say, so deleting a tree from *both* lists still fails here — silently
    narrowing what counts as private is the same defect wearing a different hat.
    """
    text = _hook_text()
    pattern = _blocked_re(text)
    probe = f"{tree}/some-file.md"
    assert re.search(pattern, probe), (
        f"{probe} is not matched by the hook's blocked_re, so `git add -A` would "
        f"commit it to a public repository — even though {tree!r} is treated as "
        f"private elsewhere in the same hook and in hooks/design_tier.py."
    )


def test_the_two_lists_do_not_disagree() -> None:
    """Anything the link-leak check calls private must also be blocked outright.

    A file that may not even be *mentioned* by public content certainly may not be
    *committed* as public content.
    """
    text = _hook_text()
    pattern = _blocked_re(text)
    unguarded = [
        tree
        for tree in _link_private_trees(text)
        if not re.search(pattern, f"{tree}/some-file.md")
    ]
    assert not unguarded, (
        f"the hook forbids public files from linking to {unguarded}, but does not "
        f"stop those files being committed. The weaker list is the one that decides."
    )


def test_the_public_part_of_design_is_still_committable() -> None:
    """The other direction: over-blocking would make the engineering tier
    uncommittable, and `design/` being public is a deliberate decision (the ADRs,
    the architecture and the threat model are the prestige surface)."""
    pattern = _blocked_re(_hook_text())
    for path in ("design/adr/adr-001.md", "design/architecture.md", "design/README.md"):
        assert not re.search(pattern, path), f"{path} is public and must stay committable"
