"""Spoken git and spoken shell: the ref you said must be the ref in the command.

Both found by running the commands rather than reading them.

**`gitvoice`** threw away the ref on `push` alone — every other ref-taking rule
captures one. "push to main" became a bare `git push`, which pushes the **current**
branch to its upstream, so naming a branch while standing on another pushed the other
one. "force push to main" did it destructively. This is the same defect the module's
own comment already describes for `delete branch feature slash login`, in the command
where it costs the most.

**`shellpipe`** put the connective into the pattern. Its alternation listed
`search for` but not `grep for`, so the most natural phrasing — "grep for error" —
rendered `grep 'for error'`, which matches nothing. Only the stilted "grep error"
worked.
"""

from __future__ import annotations

import pytest

from yazses.gitvoice.plan import build_git_argv, reversibility, undo_hint
from yazses.shellpipe.build import parse_stages, render_pipeline


def _git(text: str) -> list[str]:
    return build_git_argv(text) or []


# ---- the ref must survive ---------------------------------------------------


def test_a_named_branch_reaches_the_command():
    """The defect. `git push` pushes the current branch, whatever was said."""
    assert _git("push to main") == ["git", "push", "origin", "main"]


def test_a_named_branch_reaches_a_force_push():
    """The same, on the one command that cannot be undone from this machine."""
    assert _git("force push to main") == ["git", "push", "--force", "origin", "main"]


def test_an_explicit_remote_is_used_rather_than_the_default():
    assert _git("push to origin main") == ["git", "push", "origin", "main"]
    assert _git("push to upstream develop") == ["git", "push", "upstream", "develop"]


def test_a_remote_alone_is_not_read_as_a_branch():
    """"push origin" names a remote, not a branch called origin."""
    assert _git("push origin") == ["git", "push", "origin"]


def test_a_bare_push_stays_bare():
    """With nothing named, the current branch and its upstream are what was meant.

    Adding a guess here would turn a correct command into a guessed one.
    """
    assert _git("push") == ["git", "push"]


def test_force_is_not_mistaken_for_a_branch_name():
    """"push force" must not push a branch called `force`.

    The force words are stripped before the ref is read, which is the only ordering
    that gets this right.
    """
    assert _git("push force") == ["git", "push", "--force"]
    assert _git("push --force") == ["git", "push", "--force"]


def test_a_spoken_slash_branch_survives_on_push_too():
    """`feature/login` is the commonest branch convention and is spoken "slash".

    The module already handles this for `delete branch`; push did not reach the
    code that does it.
    """
    assert _git("push to feature slash login") == [
        "git", "push", "origin", "feature/login",
    ]
    assert _git("force push to origin feature slash login") == [
        "git", "push", "--force", "origin", "feature/login",
    ]


def test_the_branch_keeps_its_case():
    """Git refs are case-sensitive; folding them aims at a different branch."""
    assert _git("push to Release-2.0") == ["git", "push", "origin", "Release-2.0"]


# ---- and the safety machinery still recognises it ---------------------------


def test_a_force_push_with_a_ref_is_still_classified_destructive():
    """`reversibility` matches on argv membership, so a longer argv must not slip past.

    A confirm gate that stops recognising the command once it gained a ref would be
    a worse outcome than the bug being fixed.
    """
    assert reversibility(_git("force push to main")) == "confirm"
    assert reversibility(_git("push to main")) == "safe"


def test_the_undo_hint_still_fires_for_a_force_push_with_a_ref():
    assert "remote" in undo_hint(_git("force push to main"))


# ---- shellpipe: the connective belongs to the grammar, not the pattern -----


def _pipe(text: str):
    return render_pipeline(parse_stages(text))


@pytest.mark.parametrize(
    "spoken",
    [
        "grep for error",
        "grep error",
        "search for error",
        "find lines matching error",
        "filter for error",
    ],
)
def test_every_natural_phrasing_greps_for_the_word_alone(spoken):
    assert _pipe(spoken) == "grep error"


def test_a_word_that_merely_starts_with_a_connective_is_not_truncated():
    """"grep forbidden" must not become `grep bidden`.

    The connective group is followed by a required space, so the `for` alternative
    matches the prefix, fails on the missing whitespace, and backtracks — leaving the
    word whole. This is the case that makes stripping connectives safe at all.
    """
    assert _pipe("grep forbidden") == "grep forbidden"


def test_a_multi_word_pattern_is_still_quoted():
    assert _pipe("grep for two words") == "grep 'two words'"


def test_the_fix_works_mid_pipeline():
    assert _pipe("list files then grep for error then count lines") == (
        "ls | grep error | wc -l"
    )
