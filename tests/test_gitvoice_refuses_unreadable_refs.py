"""A word in the ref position is not a ref. Refuse rather than guess.

Found by a docs audit (2026-10-21) running the command rather than reading it:

    yazses gitvoice "push the frobnicator please"   ->  git push origin the   (exit 0)

`_push_target` took the first token after "push" as the branch, whatever it was, and
silently dropped everything after it. The article became a branch name, the actual
noun was thrown away, and the command looked perfectly well-formed.

The fix is a grammar that must account for every word: ``push [to] [remote] [ref]``.
Trailing courtesy and sentence punctuation are stripped first (a speech model writes
"Push to main." and people say "please"), function words are never a ref, and anything
left over refuses the whole command -- `yazses gitvoice` then exits 1 with "Could not
parse", which is what an unreadable utterance deserves.

The same reading covers the other ref verbs, and one case was worse than a bogus name:
a token starting with `-` sat in the ref slot as an OPTION. "push -f" rendered
``git push origin -f`` -- a force push that `reversibility` classified ``safe``, so
`--run` would have run it without `--yes`.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from yazses import cli
from yazses.gitvoice.plan import build_git_argv, is_clean_ref, strip_courtesy

runner = CliRunner()


# ---- the reported case ------------------------------------------------------


def test_the_audited_utterance_is_refused():
    """The defect: an article was pushed as a branch and the command exited 0."""
    assert build_git_argv("push the frobnicator please") is None


def test_the_audited_utterance_makes_the_cli_exit_nonzero():
    r = runner.invoke(cli.app, ["gitvoice", "push the frobnicator please"])
    assert r.exit_code == 1
    assert "could not parse" in r.output.lower()
    assert "origin the" not in r.output


@pytest.mark.parametrize(
    "spoken",
    [
        "push the",
        "push it",
        "push my changes",
        "push to the main branch",
        "push to origin the",
        "push main develop",           # two refs: which one? -- refused, not the first
        "push to origin main develop",
        "force push the",
    ],
)
def test_a_target_that_cannot_be_read_cleanly_is_refused(spoken):
    assert build_git_argv(spoken) is None, spoken


# ---- courtesy is not a ref, and does not block the real one -----------------


@pytest.mark.parametrize(
    "spoken",
    [
        "push to main please",
        "push to main now",
        "push to main, please.",
        "Push to main.",
        "push to main thank you",
        "push to main now please",
    ],
)
def test_trailing_courtesy_and_punctuation_leave_the_ref_intact(spoken):
    assert build_git_argv(spoken) == ["git", "push", "origin", "main"]


def test_courtesy_alone_after_push_is_a_bare_push():
    """"push please" names nothing, so it means what bare "push" means."""
    assert build_git_argv("push please") == ["git", "push"]
    assert build_git_argv("push now") == ["git", "push"]


def test_courtesy_does_not_hide_a_force_push():
    assert build_git_argv("force push to main please") == [
        "git", "push", "--force", "origin", "main",
    ]


# ---- an option is not a ref ------------------------------------------------


@pytest.mark.parametrize("spoken", ["push -f", "push to -f", "push origin -f"])
def test_a_dash_token_is_not_smuggled_into_push_as_an_option(spoken):
    """`git push origin -f` is a force push; it was classified `safe`."""
    assert build_git_argv(spoken) is None, spoken


def test_a_dash_token_is_refused_on_every_ref_verb():
    """`git checkout -f` discards local changes; it was classified `safe` too."""
    assert build_git_argv("checkout -f") is None
    assert build_git_argv("merge --abort") is None
    assert build_git_argv("create branch -x") is None
    assert build_git_argv("delete branch -r") is None


# ---- the other ref verbs get the same reading -------------------------------


@pytest.mark.parametrize(
    "spoken",
    ["switch to the", "checkout please", "merge the", "create branch the", "delete branch it"],
)
def test_a_function_word_is_never_a_ref_on_any_verb(spoken):
    assert build_git_argv(spoken) is None, spoken


def test_courtesy_on_a_branch_verb_does_not_become_the_branch():
    """"delete branch old please" must not delete a branch called `please`."""
    assert build_git_argv("delete branch old please") == ["git", "branch", "-D", "old"]
    assert build_git_argv("switch to main please") == ["git", "checkout", "main"]
    assert build_git_argv("merge develop.") == ["git", "merge", "develop"]


# ---- what must keep working -------------------------------------------------


def test_a_commit_message_keeps_its_courtesy_and_punctuation():
    """The message is prose, not a ref; nothing here may touch it."""
    assert build_git_argv("commit with message fix it now please.") == [
        "git", "commit", "-m", "fix it now please.",
    ]


def test_a_lone_dot_is_still_a_pathspec():
    """`discard changes in .` is a real request; the punctuation strip must spare it."""
    assert build_git_argv("discard changes in .") == ["git", "checkout", "--", "."]


@pytest.mark.parametrize(
    "spoken,expected",
    [
        ("push", ["git", "push"]),
        ("push origin", ["git", "push", "origin"]),
        ("push to main", ["git", "push", "origin", "main"]),
        ("push to upstream develop", ["git", "push", "upstream", "develop"]),
        ("push to feature slash login", ["git", "push", "origin", "feature/login"]),
        ("push to Release-2.0", ["git", "push", "origin", "Release-2.0"]),
        ("force push to main", ["git", "push", "--force", "origin", "main"]),
        ("push --force", ["git", "push", "--force"]),
        ("push to changes", ["git", "push", "origin", "changes"]),  # content word: a real ref
    ],
)
def test_every_readable_push_still_reads(spoken, expected):
    assert build_git_argv(spoken) == expected


# ---- the two helpers, directly ----------------------------------------------


@pytest.mark.parametrize(
    "token", ["main", "feature/login", "fix-tray-crash", "Release-2.0", "v2.1", "JIRA_123"]
)
def test_real_ref_shapes_are_clean(token):
    assert is_clean_ref(token)


@pytest.mark.parametrize(
    "token",
    ["the", "The", "please", "it", "-f", "--force", ".hidden", "main.", "feature/",
     "a..b", "a//b", "main.lock", "", "ma:in", "/main"],
)
def test_unreadable_ref_shapes_are_not_clean(token):
    assert not is_clean_ref(token)


def test_strip_courtesy_only_touches_the_end():
    assert strip_courtesy("please push to main") == "please push to main"
    assert strip_courtesy("push to main, please!") == "push to main"
    assert strip_courtesy("discard changes in .") == "discard changes in ."
