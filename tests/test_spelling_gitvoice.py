"""Phonetic Spelling Mode (ADR-v2-075) + Voice Git Choreographer (ADR-v2-076) — pure cores."""
from __future__ import annotations

from yazses.gitvoice.plan import build_git_argv, reversibility, undo_hint
from yazses.spelling.nato import spell_parse

# ---- phonetic spelling -----------------------------------------------------

def test_spell_basic_and_case():
    assert spell_parse("alpha bravo charlie") == "abc"
    assert spell_parse("capital alpha bravo") == "Ab"
    assert spell_parse("capital alpha capital bravo") == "AB"


def test_spell_repeat_digits_symbols():
    assert spell_parse("capital alpha bravo double lima") == "Abll"
    assert spell_parse("seven three dash one") == "73-1"
    assert spell_parse("delta oscar tango") == "dot"    # spells the word, letter by letter


def test_spell_ignores_unknown_and_empty():
    assert spell_parse("alpha banana bravo") == "ab"     # 'banana' skipped
    assert spell_parse("") == ""


def test_spell_lowercase_modifier():
    assert spell_parse("capital alpha lowercase bravo") == "Ab"


# ---- git choreographer -----------------------------------------------------

def test_build_commit():
    assert build_git_argv("commit with message initial import") == ["git", "commit", "-m", "initial import"]
    assert build_git_argv("commit all with message wip") == ["git", "commit", "-a", "-m", "wip"]


def test_build_branch_ops():
    assert build_git_argv("create branch feature/x") == ["git", "checkout", "-b", "feature/x"]
    assert build_git_argv("switch to main") == ["git", "checkout", "main"]
    assert build_git_argv("merge develop") == ["git", "merge", "develop"]
    assert build_git_argv("delete branch old") == ["git", "branch", "-D", "old"]


def test_build_discard():
    assert build_git_argv("discard changes in server.py") == ["git", "checkout", "--", "server.py"]
    assert build_git_argv("discard edits to src/app.py") == ["git", "checkout", "--", "src/app.py"]


def test_captured_refs_and_paths_keep_their_case():
    # Git refs and paths are case-sensitive. Folding them aims the command at something
    # else — and for the destructive ones that means discarding the wrong file, or
    # failing to discard the one the user named.
    assert build_git_argv("discard changes in Server.py") == [
        "git", "checkout", "--", "Server.py",
    ]
    assert build_git_argv("create branch FixLogin") == ["git", "checkout", "-b", "FixLogin"]
    assert build_git_argv("delete branch Old-Feature") == ["git", "branch", "-D", "Old-Feature"]
    assert build_git_argv("switch to Release-2.0") == ["git", "checkout", "Release-2.0"]
    assert build_git_argv("merge Develop") == ["git", "merge", "Develop"]
    # …while the keywords themselves stay case-insensitive.
    assert build_git_argv("Create Branch feature/JIRA-123") == [
        "git", "checkout", "-b", "feature/JIRA-123",
    ]


def test_build_plumbing_and_none():
    assert build_git_argv("push") == ["git", "push"]
    assert build_git_argv("force push") == ["git", "push", "--force"]
    assert build_git_argv("stage all") == ["git", "add", "-A"]
    assert build_git_argv("status") == ["git", "status"]
    assert build_git_argv("pull") == ["git", "pull"]
    assert build_git_argv("reset hard") == ["git", "reset", "--hard"]
    assert build_git_argv("stash") == ["git", "stash"]
    assert build_git_argv("stash pop") == ["git", "stash", "pop"]
    assert build_git_argv("make me a sandwich") is None


def test_reversibility():
    assert reversibility(["git", "commit", "-m", "x"]) == "safe"
    assert reversibility(["git", "push", "--force"]) == "confirm"
    assert reversibility(["git", "reset", "--hard"]) == "confirm"
    assert reversibility(["git", "branch", "-D", "old"]) == "confirm"
    assert reversibility(["git", "checkout", "--", "server.py"]) == "confirm"


def test_undo_hint():
    assert undo_hint(["git", "commit", "-m", "x"]) == "git reset --soft HEAD~1"
    assert undo_hint(["git", "checkout", "-b", "feat"]) == "git branch -d feat"
    assert undo_hint(["git", "merge", "dev"]) == "git merge --abort"
    assert undo_hint(["git", "add", "-A"]) == "git reset"
    assert "reflog" in undo_hint(["git", "reset", "--hard"])
    assert undo_hint(["git", "stash"]) == "git stash pop"
    assert "reflog" in undo_hint(["git", "branch", "-D", "old"])
    assert "prior sha" in undo_hint(["git", "push", "--force"])
    assert "reflog" in undo_hint(["git", "checkout", "--", "server.py"])
    assert undo_hint([]) == ""
    assert undo_hint(["git", "status"]) == ""


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "spelling" in slugs and "gitvoice" in slugs
    assert Config().spelling.enabled is False and Config().gitvoice.enabled is False


def test_a_spoken_slash_makes_the_branch_name_it_sounds_like():
    """`feature/login` spoken is "feature slash login", and it lost everything after.

    The ref patterns capture `[\\w./-]+`, which stops at the space, and `re.search`
    is unanchored, so the rest of the name was silently discarded:

        "delete branch feature slash login"      -> git branch -D feature
        "delete branch my slash deep slash name" -> git branch -D my

    A destructive command aimed at a *different branch than the one named*, with
    nothing to show that anything was dropped. `feature/…` is the most common
    branch convention there is.
    """
    from yazses.gitvoice.plan import build_git_argv

    assert build_git_argv("delete branch feature slash login") == [
        "git", "branch", "-D", "feature/login"]
    assert build_git_argv("create branch feature slash login") == [
        "git", "checkout", "-b", "feature/login"]
    assert build_git_argv("delete branch my slash deep slash name") == [
        "git", "branch", "-D", "my/deep/name"]
    # Spelled with a real slash, unchanged.
    assert build_git_argv("delete branch feature/login") == [
        "git", "branch", "-D", "feature/login"]


def test_words_after_the_ref_refuse_rather_than_truncate_it():
    """Anchored at both ends, which is this project's rule for spoken grammars.

    CLAUDE.md: "Spoken-command grammars are anchored at both ends (`^...$`) …  a
    suffix match swallows 'click undo' instead of typing it." These were anchored
    at one end, so anything the grammar did not model was dropped and a command
    was emitted anyway. Refusing prints the hint listing what it does understand;
    emitting `git branch -D` against the wrong ref does not.
    """
    from yazses.gitvoice.plan import build_git_argv

    assert build_git_argv("delete branch feature login") is None
    assert build_git_argv("create branch some name here") is None
    # Case preserved, per the module's own docstring about case-sensitive refs.
    assert build_git_argv("delete branch Feature slash Login") == [
        "git", "branch", "-D", "Feature/Login"]
