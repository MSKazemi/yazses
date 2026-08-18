"""Spoken git intent → argv + reversibility + undo (pure) — ADR-v2-076.

Build a git argv from a spoken command (message as a single quoted arg, never shell-interpolated),
classify its reversibility, and give the exact undo. Pure and deterministic; execution is a plain
``git`` subprocess elsewhere.
"""
from __future__ import annotations

import re

# argv tuples (without the leading "git") that require a spoken confirm before running.
_DESTRUCTIVE = (
    ("push", "--force"), ("reset", "--hard"), ("branch", "-D"),
    ("clean", "-fd"), ("checkout", "--"),
)


#: Remotes whose name, if spoken, is unmistakably a remote rather than a branch.
#: Anything else in that position is read as a branch — "push to main" names a branch,
#: and rendering it as `git push main` would make git look for a REMOTE called main.
_KNOWN_REMOTES = ("origin", "upstream", "fork")

#: The default remote when the user names only a branch. See the note at the call site
#: for why assuming one is safer than dropping the ref.
_DEFAULT_REMOTE = "origin"


def ref_src_for_push(raw: str) -> str:
    """The push utterance with the force words removed, refs de-spoken.

    "force" must go before the ref is read, or "push force" yields a branch called
    ``force``. ``slash`` becomes ``/`` for the same reason it does further down:
    ``feature/login`` is the commonest branch convention and it is spoken that way.
    """
    text = re.sub(r"\s+slash\s+", "/", raw)
    # `-{0,2}\bforce\b` rather than `\b--?force\b`: there is no word boundary before
    # a leading dash, so the latter stripped only the word and left `--` behind — which
    # `[\w./-]+` happily accepted as a branch name, rendering `git push --force origin --`.
    # Caught by the test for "push --force", not by reading.
    text = re.sub(r"-{0,2}\bforce\b", " ", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def _push_target(cleaned: str) -> list[str]:
    """The ``[remote, ref]`` (or ``[]``) trailing a push utterance. Pure.

    Bare "push" keeps its bare `git push`: with nothing named, the current branch and
    its upstream are exactly what the user meant, and adding a guess there would change
    a correct command into a guessed one.
    """
    m = re.search(r"\bpush\b(?:\s+to)?\s*(?P<rest>.*)$", cleaned, re.IGNORECASE)
    if not m:
        return []
    # `\w` is required somewhere in the token: a leftover `--` or `-` is punctuation,
    # not a ref, and passing it through would aim the push at a name git cannot resolve.
    tokens = [
        tok for tok in m.group("rest").split()
        if re.fullmatch(r"[\w./-]+", tok) and re.search(r"\w", tok)
    ]
    if not tokens:
        return []
    if len(tokens) >= 2 and tokens[0].lower() in _KNOWN_REMOTES:
        return [tokens[0], tokens[1]]
    if tokens[0].lower() in _KNOWN_REMOTES:
        return [tokens[0]]
    return [_DEFAULT_REMOTE, tokens[0]]


def build_git_argv(text: str):
    """Parse a spoken git command into a full argv list, or ``None`` if unrecognized. Pure.

    Keywords are matched case-insensitively, but anything *captured* — a branch name, a
    merge target, a pathspec — is taken from the utterance as spoken. Git refs and paths
    are case-sensitive, so folding them would aim the command at the wrong thing: on a
    case-sensitive filesystem ``discard changes in Server.py`` must not become
    ``git checkout -- server.py``.
    """
    raw = (text or "").strip()
    t = raw.lower()

    m = re.search(r"commit\s+(?:all\s+)?(?:with\s+)?(?:message|saying)\s+(.+)$", raw,
                  re.IGNORECASE)
    if m:
        msg = m.group(1).strip().strip("\"'")
        argv = ["git", "commit"]
        if re.search(r"\bcommit\s+all\b", t):
            argv.append("-a")
        return argv + ["-m", msg]

    # Push is the one command whose ref was thrown away, and it is the worst one to
    # throw it away on. "push to main" became a bare `git push`, which pushes the
    # CURRENT branch to its upstream — so saying a branch name while standing on a
    # different branch pushed the other one, and "force push to main" did it
    # destructively. Every other ref-taking rule below already captures its ref; this
    # is the same defect the `delete branch feature slash login` comment describes,
    # in the command where it costs the most.
    #
    # An unnamed remote becomes `origin`, and that is deliberately an assumption that
    # fails LOUDLY: on a repo whose remote is called something else, `git push origin
    # main` stops with "'origin' does not appear to be a git repository" and nothing
    # happens. Dropping the ref failed silently and pushed the wrong branch. A visible
    # wrong guess beats an invisible right-looking one.
    forced = bool(re.search(r"\b(force\s+push|push\s+force|push\s+--?force)\b", t))
    if forced or re.search(r"^push\b", t) or re.fullmatch(r"push", t):
        argv = ["git", "push"] + (["--force"] if forced else [])
        return argv + _push_target(ref_src_for_push(raw))
    if re.search(r"^pull\b", t):
        return ["git", "pull"]
    if re.search(r"\bstatus\b", t):
        return ["git", "status"]
    if re.search(r"\b(stage|add)\s+(all|everything)\b", t):
        return ["git", "add", "-A"]
    if re.search(r"\breset\s+hard\b", t):
        return ["git", "reset", "--hard"]
    if re.search(r"\bstash\s+pop\b", t):
        return ["git", "stash", "pop"]
    if re.search(r"\bstash\b", t):
        return ["git", "stash"]

    # Below, the utterance is matched as spoken (IGNORECASE) so the captured ref/path
    # keeps its case — see the docstring.
    #
    # "feature slash login" is how `feature/login` is spoken, and `feature/…` is the
    # most common branch convention there is. The capture class stops at the space, so
    # the name was silently truncated to its first segment and a DESTRUCTIVE command
    # was emitted against a different ref than the one named:
    #
    #   "delete branch feature slash login"  ->  git branch -D feature
    #
    # Applied only here, after the commit-message branch has already returned, so a
    # message containing the word is untouched.
    ref_src = re.sub(r"\s+slash\s+", "/", raw)

    m = re.search(r"\b(?:create|new)\s+branch\s+([\w./-]+)\s*$", ref_src, re.IGNORECASE)
    if m:
        return ["git", "checkout", "-b", m.group(1)]
    m = re.search(r"\bdelete\s+branch\s+([\w./-]+)\s*$", ref_src, re.IGNORECASE)
    if m:
        return ["git", "branch", "-D", m.group(1)]
    m = re.search(r"\bdiscard\s+(?:changes|edits)\s+(?:in|to|on)\s+([\w./-]+)\s*$",
                  ref_src, re.IGNORECASE)
    if m:
        return ["git", "checkout", "--", m.group(1)]
    m = re.search(r"\b(?:checkout|switch\s+to|switch)\s+(?:branch\s+)?([\w./-]+)\s*$",
                  ref_src, re.IGNORECASE)
    if m:
        return ["git", "checkout", m.group(1)]
    m = re.search(r"\bmerge\s+([\w./-]+)\s*$", ref_src, re.IGNORECASE)
    if m:
        return ["git", "merge", m.group(1)]
    return None


def reversibility(argv) -> str:
    """Classify a git argv as ``safe`` or ``confirm`` (destructive). Pure."""
    tail = tuple(a for a in (argv or []) if a != "git")
    for pat in _DESTRUCTIVE:
        if all(p in tail for p in pat):
            return "confirm"
    return "safe"


def undo_hint(argv) -> str:
    """The exact command to undo a git argv (or an advisory for irreversible ops). Pure."""
    tail = [a for a in (argv or []) if a != "git"]
    if not tail:
        return ""
    sub = tail[0]
    if sub == "commit":
        return "git reset --soft HEAD~1"
    if sub == "checkout" and "-b" in tail:
        return f"git branch -d {tail[-1]}"
    if sub == "checkout" and "--" in tail:
        return "recover via: git reflog / your editor's local history (uncommitted changes are gone unless stashed first)"
    if sub == "merge":
        return "git merge --abort"
    if sub == "add":
        return "git reset"
    if sub == "stash" and "pop" not in tail:
        return "git stash pop"
    if sub == "reset" and "--hard" in tail:
        return "recover via: git reflog (no clean undo)"
    if sub == "branch" and "-D" in tail:
        return f"recover via: git reflog, then git branch {tail[-1]} <sha>"
    if sub == "push" and "--force" in tail:
        return "restore the remote ref from its prior sha (git reflog on the remote clone)"
    return ""
