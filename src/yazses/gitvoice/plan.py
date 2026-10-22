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


#: How a branch name's punctuation is spoken. `feature/login` and `fix-tray-crash` are
#: both ordinary conventions and neither can be *dictated*: no speech model produces a
#: bare "/" or "-" from silence between words, so the user says the separator. Only
#: "slash" was understood, which left the hyphenated half of real branch names
#: unreachable by voice -- in a voice-first product.
#:
#: No entry is currently a prefix of another, so the order does not decide anything
#: today. It is written longest-first anyway because adding one that is (say "score"
#: beside "underscore") would otherwise change the meaning of existing utterances
#: depending on where it landed in the tuple.
_SPOKEN_SEPARATORS = (
    ("underscore", "_"),
    ("hyphen", "-"),
    ("slash", "/"),
    ("dash", "-"),
    ("dot", "."),
)


#: Words that are never a ref. An utterance is not a branch name just because a word
#: sits where a branch name would: "push the frobnicator please" rendered
#: ``git push origin the`` and exited 0, because the first word after "push" was taken
#: as the branch whatever it was. Articles, determiners, pronouns, prepositions and
#: politeness are what fill that slot in ordinary speech, and none of them is a
#: plausible branch name -- so a ref that is one of these is refused, not guessed.
#:
#: Only function words belong here. A content word ("changes", "fix") can be a real
#: branch, and refusing it would make a real branch unreachable by voice.
_NOT_A_REF = frozenset({
    "a", "an", "the", "this", "that", "these", "those", "some", "all", "every",
    "it", "its", "my", "our", "your", "their", "his", "her", "me", "us", "them",
    "to", "up", "for", "of", "on", "in", "into", "onto", "with", "and", "or", "from",
    "please", "now", "thanks", "thank", "you",
})

#: Courtesy a speaker appends to a command: "push to main please", "push now".
#: Stripped from the END of a ref-reading utterance only, so it can neither become the
#: ref nor push the ref out of the position the grammar reads it from.
_TRAILING_COURTESY = re.compile(r"[\s,]+(?:please|now|thanks|thank\s+you)$", re.IGNORECASE)

#: Sentence punctuation a speech model appends ("Push to main."). Only when it follows
#: a word character: a lone "." is a real pathspec (`discard changes in .`).
_TRAILING_PUNCT = re.compile(r"(?<=\w)[.,!?;:]+$")


def strip_courtesy(raw: str) -> str:
    """Drop trailing sentence punctuation and politeness from a ref utterance. Pure.

    Never applied to a commit message -- "commit with message fix it now" must keep
    its last word -- only where a ref or pathspec is read.
    """
    text = (raw or "").strip()
    prev = None
    while prev != text:
        prev = text
        text = _TRAILING_PUNCT.sub("", text).rstrip()
        text = _TRAILING_COURTESY.sub("", text).rstrip()
    return text


def is_clean_ref(token: str) -> bool:
    """Whether *token* can be read as a git ref without guessing. Pure.

    Refused: a function word (:data:`_NOT_A_REF`); anything outside ``[\\w./-]``; and
    the shapes ``git check-ref-format`` rejects that the character class lets through
    -- a leading ``.`` or ``/``, a trailing ``.`` or ``/``, ``..``, ``//`` and a
    ``.lock`` suffix. A leading ``-`` is refused above all: in a ref position it is an
    OPTION, so "push -f" rendered ``git push origin -f`` -- a force push that
    :func:`reversibility` classified ``safe``.
    """
    if not re.fullmatch(r"\w[\w./-]*", token or ""):
        return False
    if token.lower() in _NOT_A_REF:
        return False
    if token.endswith((".", "/", ".lock")) or ".." in token or "//" in token:
        return False
    return True


def despeak_ref(raw: str) -> str:
    """Turn spoken separators into the punctuation they name. Pure.

    Applied only where a *ref* is read, never to a commit message -- "commit with message
    fix the dash in the title" must keep its word. Both ref-reading paths go through this
    one function rather than each carrying its own substitution, which is how they came
    to disagree: the push path and the branch path had separate copies and only ever
    handled "slash".
    """
    text = raw
    for word, symbol in _SPOKEN_SEPARATORS:
        text = re.sub(rf"\s+{word}\s+", symbol, text, flags=re.IGNORECASE)
    return text


def ref_src_for_push(raw: str) -> str:
    """The push utterance with courtesy and force words removed, refs de-spoken.

    "force" must go before the ref is read, or "push force" yields a branch called
    ``force``. Spoken separators are resolved by :func:`despeak_ref` for the same reason
    they are further down: `feature/login` and `fix-tray-crash` are how branches are
    named, and both are spoken rather than typed.
    """
    text = despeak_ref(strip_courtesy(raw))
    # `-{0,2}\bforce\b` rather than `\b--?force\b`: there is no word boundary before
    # a leading dash, so the latter stripped only the word and left `--` behind — which
    # `[\w./-]+` happily accepted as a branch name, rendering `git push --force origin --`.
    # Caught by the test for "push --force", not by reading.
    text = re.sub(r"-{0,2}\bforce\b", " ", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def _push_target(cleaned: str) -> list[str] | None:
    """The ``[remote, ref]`` (or ``[]``) trailing a push utterance, or ``None``. Pure.

    Bare "push" keeps its bare `git push`: with nothing named, the current branch and
    its upstream are exactly what the user meant, and adding a guess there would change
    a correct command into a guessed one.

    ``None`` means a target was spoken but cannot be read cleanly, and the whole command
    is refused. The grammar is ``push [to] [remote] [ref]`` and every word after "push"
    must be accounted for by it. Taking the first word and silently dropping the rest
    is how "push the frobnicator please" became ``git push origin the`` -- a command
    built from a word nobody meant as a branch, which exited 0.
    """
    m = re.search(r"\bpush\b(?:\s+to)?\s*(?P<rest>.*)$", cleaned, re.IGNORECASE)
    if not m:
        return []
    # `\w` is required somewhere in the token: a leftover `--` or `-` is punctuation,
    # not a word the user said, so it is dropped rather than read. Every other token
    # must be read by the grammar below, or the command is refused.
    tokens = [tok for tok in m.group("rest").split() if re.search(r"\w", tok)]
    if not tokens:
        return []
    if tokens[0].lower() in _KNOWN_REMOTES:
        remote, refs = tokens[0], tokens[1:]
    else:
        remote, refs = _DEFAULT_REMOTE, tokens
    if not refs:
        return [remote]
    if len(refs) > 1 or not is_clean_ref(refs[0]):
        return None
    return [remote, refs[0]]


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
        target = _push_target(ref_src_for_push(raw))
        if target is None:
            return None
        argv = ["git", "push"] + (["--force"] if forced else [])
        return argv + target
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
    #
    # Trailing courtesy and sentence punctuation go first, for the reason push needs it:
    # "delete branch old please" must not delete a branch called `please`.
    ref_src = despeak_ref(strip_courtesy(raw))

    m = re.search(r"\b(?:create|new)\s+branch\s+([\w./-]+)\s*$", ref_src, re.IGNORECASE)
    if m:
        return _with_ref(["git", "checkout", "-b"], m.group(1))
    m = re.search(r"\bdelete\s+branch\s+([\w./-]+)\s*$", ref_src, re.IGNORECASE)
    if m:
        return _with_ref(["git", "branch", "-D"], m.group(1))
    # A pathspec, not a ref: `.` is a legitimate answer here and it sits after `--`, so
    # a leading dash cannot become an option. The ref checks do not apply.
    m = re.search(r"\bdiscard\s+(?:changes|edits)\s+(?:in|to|on)\s+([\w./-]+)\s*$",
                  ref_src, re.IGNORECASE)
    if m:
        return ["git", "checkout", "--", m.group(1)]
    m = re.search(r"\b(?:checkout|switch\s+to|switch)\s+(?:branch\s+)?([\w./-]+)\s*$",
                  ref_src, re.IGNORECASE)
    if m:
        return _with_ref(["git", "checkout"], m.group(1))
    m = re.search(r"\bmerge\s+([\w./-]+)\s*$", ref_src, re.IGNORECASE)
    if m:
        return _with_ref(["git", "merge"], m.group(1))
    return None


def _with_ref(prefix: list[str], ref: str) -> list[str] | None:
    """*prefix* + *ref*, or ``None`` when *ref* cannot be read cleanly. Pure.

    Refusing is the point: "switch to the" rendered ``git checkout the``, and
    "checkout -f" rendered ``git checkout -f`` -- which throws away local changes while
    :func:`reversibility` called it ``safe``.
    """
    return [*prefix, ref] if is_clean_ref(ref) else None


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
