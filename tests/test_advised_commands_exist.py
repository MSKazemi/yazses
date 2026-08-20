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
        if not any(str(f.relative_to(REPO)).startswith(s) for s in _SPECULATIVE)
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
