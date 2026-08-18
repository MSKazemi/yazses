"""A branch name you cannot dictate is a branch name voice control cannot reach.

`feature/login` and `fix-tray-crash` are both ordinary conventions, and **neither can be
spoken**: no speech model produces a bare "/" or "-" from the silence between two words,
so the user says the separator. Only "slash" was understood:

    create branch feature slash login   ->  git checkout -b feature/login   ✓
    create branch feature dash login    ->  Could not parse a git command.  ✗

That put the hyphenated half of real branch names out of reach in a voice-first product,
and the failure was a flat refusal — the error even advertises `'create branch …'`, the
form that had just been rejected.

## Why one shared function

The substitution existed **twice** — once in `ref_src_for_push`, once beside the branch
verbs — and both copies handled only "slash". Two copies of a rule that must agree is how
they come to disagree, so both now call `despeak_ref`. The parametrised tests below run
every separator against every ref-reading verb for the same reason: adding a separator
that only one path honours should fail here, not in someone's terminal.

## The negative that matters most

`despeak_ref` is applied **only where a ref is read**, never to a commit message. The
existing code is careful to run it after the commit-message branch has returned, and
`test_a_commit_message_keeps_its_words` pins that: "commit with message fix the dash in
the title" must keep the word "dash", not grow a hyphen. A separator list applied one
line earlier would silently corrupt commit messages — a far worse bug than the one being
fixed here.
"""

from __future__ import annotations

import pytest

from yazses.gitvoice.plan import _SPOKEN_SEPARATORS, build_git_argv, despeak_ref

#: Every ref-reading verb, and the command each should produce for `feature<sep>login`.
VERBS = [
    ("create branch", ["git", "checkout", "-b"]),
    ("new branch", ["git", "checkout", "-b"]),
    ("delete branch", ["git", "branch", "-D"]),
]


def test_the_separators_cover_both_real_conventions() -> None:
    """The premise: slashes and hyphens are how branches are actually named."""
    symbols = {symbol for _word, symbol in _SPOKEN_SEPARATORS}
    assert "/" in symbols, "feature/login unreachable"
    assert "-" in symbols, "fix-tray-crash unreachable — the original defect"


@pytest.mark.parametrize("word,symbol", list(_SPOKEN_SEPARATORS))
@pytest.mark.parametrize("phrase,expected", VERBS)
def test_every_separator_works_on_every_ref_verb(
    word: str, symbol: str, phrase: str, expected: list[str]
) -> None:
    """The rule lived in two copies that had drifted; this crosses them."""
    got = build_git_argv(f"{phrase} feature {word} login")
    assert got == [*expected, f"feature{symbol}login"], (
        f"{phrase!r} does not honour the spoken separator {word!r}"
    )


@pytest.mark.parametrize("word,symbol", list(_SPOKEN_SEPARATORS))
def test_push_honours_the_same_separators(word: str, symbol: str) -> None:
    """The second copy of the rule. It handled only "slash"."""
    assert build_git_argv(f"push to feature {word} login") == [
        "git", "push", "origin", f"feature{symbol}login",
    ]


def test_a_realistic_multi_separator_name() -> None:
    """What a person actually says for a fix branch."""
    assert build_git_argv("create branch fix dash tray dash crash") == [
        "git", "checkout", "-b", "fix-tray-crash",
    ]


def test_a_commit_message_keeps_its_words() -> None:
    """The load-bearing negative: separators must not reach a commit message.

    Running the substitution one line earlier would rewrite prose into punctuation —
    a quieter and much worse bug than the one this file fixes.
    """
    assert build_git_argv("commit with message fix the dash in the title") == [
        "git", "commit", "-m", "fix the dash in the title",
    ]
    assert build_git_argv("commit with message use a slash here") == [
        "git", "commit", "-m", "use a slash here",
    ]


def test_despeak_leaves_ordinary_text_alone() -> None:
    """Only a *separating* occurrence counts — spaces on both sides."""
    assert despeak_ref("dashboard metrics") == "dashboard metrics"
    assert despeak_ref("slashdot") == "slashdot"


def test_the_single_word_case_still_works() -> None:
    """It always did; a regression here would be the fix eating the common case."""
    assert build_git_argv("create branch login") == ["git", "checkout", "-b", "login"]
