"""Every command YazSes tells a user to run must be a command YazSes has.

`doctor`, the notification toasts, `--help` epilogs, error messages and the guides all
end in the same sentence shape: *"fix it with `yazses <something>`"*. There are 115
commands and subcommands, and the advice strings that name them are scattered across
`src/` and 200 documentation pages with nothing tying the two together -- so renaming or
removing a command breaks an unknown number of instructions, silently, in the exact place
a user has already hit a problem and is least able to absorb another one.

The region is derived rather than listed: the command tree comes from Typer, and the
references come from walking the trees. A new command, a renamed one, or a new advice
string is covered the day it is written.

⚠ The tree walk deliberately duck-types on `.commands` instead of `isinstance(c,
click.Group)`. `TyperGroup` does **not** subclass `click.Group` -- it subclasses
`typer._click.core.Command` from a vendored click -- so the isinstance form silently
enumerates **zero** commands and every assertion here passes vacuously. That is not a
hypothetical: it is how this suite was first written, it reported 126 false failures, and
it is the same blind spot that once disabled the CLI-reference guard.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest
import typer

from yazses.cli import app

REPO = pathlib.Path(__file__).resolve().parents[1]

#: `yazses <cmd>` or `yazses <group> <sub>`, inside backticks so prose is not scanned.
_REF = re.compile(r"`yazses ([a-z][a-z0-9-]*(?: [a-z][a-z0-9-]*)?)")

#: `docs/research/` poses open questions about commands that do not exist yet -- e.g.
#: "what would a fair cross-CPU `yazses bench` look like, and who runs it?". That is a
#: research prompt, not an instruction, and the whole tree is speculative by design.
_SPECULATIVE = ("docs/research/",)


def _command_tree() -> tuple[set[tuple[str, ...]], set[str]]:
    root = typer.main.get_command(app)

    def walk(node, prefix=()):
        found = set()
        for name, sub in (getattr(node, "commands", None) or {}).items():
            found.add(prefix + (name,))
            found |= walk(sub, prefix + (name,))
        return found

    every = walk(root)
    groups = {
        p[0]
        for p in every
        if len(p) == 1 and getattr(root.commands[p[0]], "commands", None)
    }
    return every, groups


REAL, GROUPS = _command_tree()


def unresolved(text: str) -> list[tuple[str, ...]]:
    """Command paths named in *text* that the CLI cannot dispatch."""
    bad = []
    for match in _REF.finditer(text):
        parts = tuple(match.group(1).split())
        if parts in REAL:
            continue
        if len(parts) == 2 and parts[0] not in GROUPS:
            # `yazses transcribe file.wav` -- the second word is an argument.
            if parts[:1] in REAL:
                continue
            bad.append(parts[:1])
            continue
        bad.append(parts)
    return bad


def _sources() -> list[pathlib.Path]:
    files = sorted((REPO / "src" / "yazses").rglob("*.py"))
    files += [
        f
        for f in sorted((REPO / "docs").rglob("*.md"))
        if not any(f.relative_to(REPO).as_posix().startswith(s) for s in _SPECULATIVE)
    ]
    return files


def test_the_command_tree_is_not_empty():
    """The vacuity guard, and the specific way this suite has already failed once.

    An `isinstance(c, click.Group)` walk returns an empty set against Typer, and every
    reference then resolves against nothing. Assert the tree is real and deep.
    """
    assert len(REAL) > 100, f"only found {len(REAL)} commands -- the walk is broken"
    assert max(len(p) for p in REAL) == 2, "command depth changed; the regex assumes 2"
    assert ("audio", "devices") in REAL, sorted(REAL)[:20]


def test_the_scan_covers_both_trees():
    """A guard that iterates is green on an empty collection."""
    files = _sources()
    assert sum(1 for f in files if f.suffix == ".py") > 200, "source tree not scanned"
    assert sum(1 for f in files if f.suffix == ".md") > 150, "docs tree not scanned"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("run `yazses nosuchcmd` now", [("nosuchcmd",)]),
        ("run `yazses audio nosuchsub` now", [("audio", "nosuchsub")]),
        ("run `yazses audio devices` now", []),
        ("run `yazses transcribe talk.wav` now", []),
        ("yazses nosuchcmd without backticks", []),
    ],
)
def test_the_detector_can_actually_fail(text, expected):
    """A sweep that reports nothing is worthless until it is shown able to report."""
    assert unresolved(text) == expected


@pytest.mark.parametrize("path", _sources(), ids=lambda p: str(p.relative_to(REPO)))
def test_every_advised_command_exists(path):
    text = path.read_text(encoding="utf-8")
    missing = {}
    for lineno, line in enumerate(text.splitlines(), 1):
        for parts in unresolved(line):
            missing.setdefault(" ".join(parts), []).append(lineno)
    assert not missing, (
        f"{path.relative_to(REPO)} tells the user to run commands that do not exist: "
        + "; ".join(f"`yazses {c}` (line{'s' if len(l) > 1 else ''} "
                    f"{', '.join(map(str, l))})" for c, l in sorted(missing.items()))
    )


# --- the same question one level deeper: the flags on those commands ----------
#
# A command name that resolves is not the whole promise. `yazses mic-level --set`
# is one string: if the flag is renamed the command still dispatches, Typer exits 2
# with "No such option", and the user meets that at the exact moment they had
# already hit a problem and were following instructions to get out of it. The
# sweep above cannot see it -- it stops at the second word.
#
# Currently zero across 229 advice strings that carry a flag -- 83 of them string
# literals in `src/` that the backtick rule above cannot see at all -- which is why
# it is worth pinning now rather than after the first rename.

#: A whole invocation, so the flags after the command name are visible. Deliberately
#: NOT anchored on backticks. The command sweep above requires them so that prose in
#: 200 markdown pages is not parsed as a command line -- but in `src/` the advice a
#: user actually reads is a `typer.echo` string, and 337 of those carry no backticks
#: at all, including four of the five places that print `yazses mic-level --set`.
#: Requiring a backtick here would have left the most user-facing half of the advice
#: unchecked while reporting green.
#:
#: Prose cannot false-positive on this the way it can on a bare command name, because
#: a flag is only ever checked once a *real* command path has already resolved in
#: front of it -- "yazses is still running" resolves to no command and is skipped.
_INVOCATION = re.compile(r"\b(yazses [a-z][^\n]*)")

#: Advice is quoted, parenthesised and punctuated in the wild: ``yazses tune
#: --apply``)``, ``--set` later)``, ``--set'.``. Strip what a shell would not see.
_TRAILING = "`'\".,;:)]}!?*"

#: `--help` (and `-h`) are added by click at parse time and are not in
#: `Command.params`, so a table built from `params` alone reports `yazses
#: transcribe --help` as a flag that command does not accept. Every command has it.
_ALWAYS = {"--help"}


def _flags_by_command() -> dict[tuple[str, ...], set[str]]:
    """Every option string each dispatchable command accepts, keyed by path."""
    root = typer.main.get_command(app)

    def walk(node, prefix=()):
        out: dict[tuple[str, ...], set[str]] = {}
        subs = getattr(node, "commands", None) or {}
        for name, sub in subs.items():
            out.update(walk(sub, prefix + (name,)))
        if not subs:
            opts: set[str] = set()
            for param in getattr(node, "params", []):
                opts |= set(getattr(param, "opts", ()) or ())
                opts |= set(getattr(param, "secondary_opts", ()) or ())
            out[prefix] = {o for o in opts if o.startswith("-")}
        return out

    return walk(root)


FLAGS = _flags_by_command()


def advised_flags(text: str) -> list[tuple[str, str]]:
    """`(invocation, flag)` for every long flag named on a command that lacks it.

    Only long flags are checked. A bare `-s` in prose is far more often a typo'd
    word fragment than an option, and the false positives would be paid by whoever
    edits the docs next.
    """
    bad: list[tuple[str, str]] = []
    for match in _INVOCATION.finditer(text):
        tokens = [t.rstrip(_TRAILING) for t in match.group(1).split()[1:]]
        path = next((tuple(tokens[:n]) for n in (2, 1) if tuple(tokens[:n]) in FLAGS), None)
        if path is None:
            continue  # not a dispatchable command; the sweep above owns that case
        raw_tokens = match.group(1).split()[1:]
        if any("`" in t for t in raw_tokens[:len(path)]):
            # The span closed on the command itself -- ``\`yazses meeting status\` to
            # report it done, or re-run with --force`` names no flag *of that command*;
            # the --force belongs to the sentence, not the invocation.
            continue
        for raw, token in zip(raw_tokens[len(path):], tokens[len(path):]):
            # An invocation ends where its line stops being one. The regex runs to the
            # end of the line on purpose (a `typer.echo` string is not delimited), so
            # the scan has to stop itself: at a backtick, which in this codebase always
            # opens or closes a *different* code span, and at a token that ends a
            # sentence. Without this, `` `yazses test` and `yazses verify --type` ``
            # charges --type to `test`, and prose like "Needs Neovim started with
            # `nvim --listen`" is charged to whatever command the sentence opened with.
            if raw == "/":
                # `/` separates alternatives, not arguments: "yazses about / --version
                # / --help" lists three things to try, and --version belongs to the
                # root command rather than to `about`.
                break
            flag = token.split("=", 1)[0]
            if flag.startswith("--") and len(flag) > 2 and flag not in FLAGS[path] | _ALWAYS:
                bad.append((match.group(1), flag))
            if "`" in raw:
                # The token is checked *before* this break, not after. A backtick most
                # often closes the span it is in -- ``\`yazses mic-level --set\``` puts
                # it on the final flag -- so breaking first would skip the last flag of
                # every backticked invocation, which is nearly all of them in the docs.
                # A backtick that *opens* a new span is harmless here: the token it is
                # attached to is a word, not a flag, so the check above is a no-op and
                # the break still stops the scan before the next command's flags.
                break
            if raw.endswith((".", ";", ":")) and not flag.startswith("-"):
                break
    return bad


def _advice_strings(path: pathlib.Path) -> list[str]:
    """The text of *path* that is addressed to a user.

    For a Python source that means every string literal -- messages, `--help` text,
    docstrings -- read with `ast` rather than by regex over the file, so a command
    line in code (a `subprocess` argv, a test fixture) is not mistaken for advice.
    For markdown it means the whole page.
    """
    if path.suffix != ".py":
        return [path.read_text(encoding="utf-8")]
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:  # pragma: no cover - the tree parses or the build is broken
        return []
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def test_the_flag_table_is_real():
    """Vacuity, twice over: a broken walk yields no commands, and a command whose
    params were not read yields no flags -- both make every assertion below pass."""
    assert len(FLAGS) > 80, f"only {len(FLAGS)} dispatchable commands found"
    # Named membership rather than a count: a threshold picked by hand is a number
    # this file asserts about itself, and mutating the code can never falsify it.
    assert FLAGS[("mic-level",)] >= {"--set", "--seconds"}, FLAGS[("mic-level",)]
    assert FLAGS[("doctor",)] >= {"--mic"}, FLAGS[("doctor",)]
    assert sum(1 for v in FLAGS.values() if v) > 30, "params were not read"


def test_the_advice_actually_carries_flags_to_check():
    """If no advice string named a flag, the sweep would be green and meaningless."""
    carrying = sum(
        1
        for f in _sources()
        for text in _advice_strings(f)
        for m in _INVOCATION.finditer(text)
        if any(t.startswith("--") and len(t) > 2 for t in m.group(1).split()[1:])
    )
    assert carrying > 50, f"only {carrying} advice strings name a flag"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("try `yazses mic-level --set` now", []),
        # The reported span runs to the end of the line -- the invocation is not
        # delimited in a `typer.echo` string, so there is nothing to close it on.
        ("try `yazses mic-level --st` now", [("yazses mic-level --st` now", "--st")]),
        ("try `yazses doctor --mic` now", []),
        ("try `yazses transcribe talk.wav --names A,B` now", []),
        ("try `yazses nosuchcmd --whatever` now", []),  # owned by the other sweep
        # No backticks needed any more: in `src/` the advice a user reads is a plain
        # `typer.echo` string, and requiring them left 337 of those unchecked.
        ("yazses mic-level --nope without backticks", [("yazses mic-level --nope without backticks", "--nope")]),
    ],
)
def test_the_flag_detector_can_actually_fail(text, expected):
    assert advised_flags(text) == expected


@pytest.mark.parametrize("path", _sources(), ids=lambda p: str(p.relative_to(REPO)))
def test_every_advised_flag_exists(path):
    bad = [b for text in _advice_strings(path) for b in advised_flags(text)]
    assert not bad, (
        f"{path.relative_to(REPO)} tells the user to run a flag the command does not "
        f"accept: " + "; ".join(f"`{inv}` has no {flag}" for inv, flag in bad)
    )
