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


# ── The other direction: what the contract calls PUBLIC must be committable ──
#
# `design/README.md` carries the visibility table and says in the same breath that
# three mechanisms enforce it and "changing one without the others is a bug". The
# table declared `paper/results/` public from the day the harness was published.
# The hook's allow-list still read `^paper/benchmark/[^/]+\.(py|md)$`, so the
# entire results archive — the artifacts behind every number on a public page —
# was uncommittable, and the block message read like a considered policy decision
# rather than a list that had not caught up. Nothing failed until someone tried.
#
# The tests above prove the hook does not under-block. These prove it does not
# over-block, and they take the set of public trees from the contract itself,
# because a literal list here would be a fourth place to forget.

TABLE_ROW = re.compile(r"^\|\s*(`[^|]+`)\s*\|\s*\*\*(Public|Private)\*\*\s*\|", re.M)


def _contract_trees(visibility: str) -> tuple[str, ...]:
    """Directories the visibility table in design/README.md gives `visibility`.

    A row may name more than one directory (`paper/benchmark/`, `paper/results/`),
    so each cell is split on the comma and every backticked path is returned.
    """
    text = (ROOT / "design" / "README.md").read_text(encoding="utf-8")
    trees: list[str] = []
    for cell, kind in TABLE_ROW.findall(text):
        if kind != visibility:
            continue
        trees.extend(re.findall(r"`([^`]+)`", cell))
    return tuple(trees)


def _allowed_re(text: str) -> str:
    m = re.search(r"allowed_re='([^']+)'", text)
    assert m, "cannot find allowed_re in the hook — its shape changed"
    return m.group(1)


def _committable(hook: str, path: str) -> bool:
    """What the hook actually decides for one staged path: blocked unless the
    narrow allow-list rescues it. Mirrors the two greps in section 2."""
    if not re.search(_blocked_re(hook), path):
        return True
    return bool(re.search(_allowed_re(hook), path))


def test_the_contract_table_is_parseable() -> None:
    """Guard the guard, again: an unparseable table must not read as agreement."""
    public = _contract_trees("Public")
    private = _contract_trees("Private")
    assert len(public) >= 3, f"only {public} parsed as public out of design/README.md"
    assert len(private) >= 3, f"only {private} parsed as private out of design/README.md"
    assert not set(public) & set(private), "a directory is listed as both"


@pytest.mark.parametrize(
    ("tree", "name"),
    [
        ("design/", "adr/adr-001.md"),
        ("docs/", "benchmarks.md"),
        ("paper/benchmark/", "bench_wer.py"),
        ("paper/benchmark/", "probes/largev3_repeat.py"),
        ("paper/benchmark/", "probes/drivers/x86-bootstrap.sh"),
        ("paper/results/", "wer.json"),
        ("paper/results/", "README.md"),
        ("paper/results/", "probes/logs/x86b-serial_chain.log"),
    ],
)
def test_every_tree_called_public_can_actually_be_committed(tree: str, name: str) -> None:
    """The property that was violated, in the direction nothing was checking.

    The `tree` is asserted to be public *by the contract* rather than assumed, so
    quietly reclassifying one fails here instead of silently retiring a case.
    """
    assert tree in _contract_trees("Public"), (
        f"{tree!r} is no longer listed as public in design/README.md's visibility "
        f"table. If that is deliberate, this case and the hook must change together."
    )
    path = f"{tree}{name}"
    assert _committable(_hook_text(), path), (
        f"design/README.md calls {tree} public, but .git/hooks/pre-commit refuses to "
        f"commit {path}. The contract says all three enforcement points must agree; "
        f"this is the one that does not."
    )


# Two of these probes are split across a tuple rather than written as one string,
# and the seam is the point. Section 3 of the hook forbids a *public* file from
# containing a path into a private tree, and this file is public. Written whole,
# an agent-artifact path would trip that check on the way in — correctly, since
# the rule cannot tell a test fixture from a live link, and the exception that
# would let it through is exactly the exception that leaks a filename later.
@pytest.mark.parametrize(
    ("prefix", "rest"),
    [
        ("paper/", "main.tex"),                     # the manuscript
        ("paper/", "corpus/ami/ES2004a.wav"),       # licensed audio
        ("paper/", "references/whisper.pdf"),       # a third-party paper
        ("paper/benchmark/", "corpus/train.wav"),   # audio smuggled under the harness
        ("paper/results/", "corpus/ES2004a.flac"),  # audio smuggled under the archive
        ("strategy", "/launch.md"),
        (".claude", "/plans/today.md"),
    ],
)
def test_widening_the_allow_list_did_not_let_the_private_half_through(
    prefix: str, rest: str
) -> None:
    """The allow-list is anchored on extension, not on depth, precisely so that a
    subdirectory under a published tree cannot carry audio or a manuscript out.
    `paper/` is private *except* for code and small artifacts, and that exception
    has to stay an exception."""
    path = prefix + rest
    assert not _committable(_hook_text(), path), (
        f"{path} would be committable to a public repository. The paper/ exception "
        f"is for harness code (.py/.md/.sh) and result artifacts (.json/.md/.log) "
        f"only — no audio, no transcripts, no manuscript."
    )
