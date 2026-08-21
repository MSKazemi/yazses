"""Every `yazses …` command we tell a user to run must actually exist.

The reverse of `test_cli_reference_covers_every_command.py`. That one asks whether
each shipped command is documented; this asks whether each command we *name* ships.
Both directions have failed, and this one is worse: an undocumented command is a
gap, while advice naming a command that does not exist is a dead end handed to
someone who is already stuck.

Found by running the product. The settings window's model dropdown said *"Same list
as `yazses models`"* and `docs/settings-gui.md` repeated it — but the command is
`yazses model list`. `yazses models` exits 2 with *"No such command"*. Two surfaces,
one invented name, and every test passed because nothing compared the strings we ship
against the CLI we ship.

The same shape had already appeared twice in two days: a diagnosis module linking
three how-to pages that have never existed, and a bug-report bundle reading
`yazses.log` where the file is `daemon.log`. All three are strings that are only
wrong at the moment a user acts on them.

## What counts as advice

Backticked `yazses …` in **shipped strings** (the package) and in **user
documentation** — the places a person is told what to type. Not the CHANGELOG or
design notes, which describe history and may legitimately name a command that has
since been renamed.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from tests.test_cli_reference_covers_every_command import _shipped_commands

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "yazses"
DOCS = ROOT / "docs"

#: Advice is `yazses …` **inside backticks** — optionally via `uv run`. Requiring the
#: backtick is what makes this usable rather than noise.
#:
#: The first version matched `yazses` anywhere, and drowned: `cd yazses`,
#: `pipx install yazses`, `sudo snap refresh yazses`, `brew install ... yazses`,
#: "yazses on ubuntu", and the repo's own name in a clone URL all came back as
#: invented commands. Thirty-odd false positives against one real defect is a guard
#: nobody keeps — which is its own way of not existing. A backtick is the mark that
#: says "type this", so it is the right thing to key on.
_INVOCATION = re.compile(r"`(?:uv run |\$ )?yazses((?:\s+[a-z][a-z0-9-]*)+)")

#: Words that follow a command but are not one: flags are stripped by the regex, and
#: these are the prose continuations that survive it. Each is a real sentence in the
#: tree, e.g. "run `yazses restart` to apply" -> "restart to apply".
_PROSE_TAIL = frozenset({
    "to", "and", "or", "then", "for", "with", "in", "on", "at", "from", "again",
    "first", "now", "it", "them", "this", "that", "if", "when", "after", "before",
    "will", "is", "was", "does", "did", "has", "have", "says", "prints", "shows",
    "reports", "writes", "runs", "checks", "picks", "you", "your", "the", "a", "an",
    "as", "into", "onto", "over", "under", "once", "twice", "so", "but", "not",
    "never", "always", "still", "already", "yet", "here", "there", "where", "which",
    "who", "why", "how", "what", "all", "any", "each", "every", "both", "either",
})


def _longest_real_prefix(words: list[str], shipped: set[str]) -> str | None:
    """The longest leading run of *words* that is a real command path, or None.

    Longest-first, because `model list` and `model` are both real and the specific
    one is what was meant. Returning the prefix rather than a bool is what lets the
    failure message say which part resolved and which did not.
    """
    for size in range(len(words), 0, -1):
        candidate = " ".join(words[:size])
        if candidate in shipped:
            return candidate
    return None


def _invocations(text: str) -> set[tuple[str, ...]]:
    """Every `yazses …` invocation in *text*, as word tuples with prose trimmed."""
    found = set()
    for match in _INVOCATION.finditer(text):
        words = match.group(1).split()
        while words and words[-1] in _PROSE_TAIL:
            words.pop()
        if words:
            found.add(tuple(words))
    return found


def _shipped_strings() -> list[tuple[Path, str]]:
    """Every string literal in the package — what a user can actually be shown."""
    out: list[tuple[Path, str]] = []
    for path in sorted(SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - fails loudly elsewhere
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if "yazses " in node.value:
                    out.append((path, node.value))
    return out


@pytest.fixture(scope="module")
def shipped() -> set[str]:
    return set(_shipped_commands())


def test_the_guard_can_see_the_command_tree(shipped: set[str]) -> None:
    """Fail loudly rather than vacuously if the CLI walk ever returns nothing.

    A guard that iterates an empty set passes on everything, which this repo has
    been bitten by three times in one day.
    """
    assert len(shipped) > 50, f"only {len(shipped)} commands found — the walk is broken"
    assert "model list" in shipped and "audio use" in shipped


def test_every_command_named_in_a_shipped_string_exists(shipped: set[str]) -> None:
    """The defect: `yazses models` in a tooltip, where the command is `yazses model`."""
    bad: list[str] = []
    for path, text in _shipped_strings():
        for words in _invocations(text):
            if _longest_real_prefix(list(words), shipped) is None:
                bad.append(f"{path.relative_to(ROOT)}: `yazses {' '.join(words)}`")
    assert not bad, (
        "these strings tell a user to run a command that does not exist:\n  "
        + "\n  ".join(sorted(set(bad)))
    )


def test_every_command_named_in_the_user_docs_exists(shipped: set[str]) -> None:
    bad: list[str] = []
    for path in sorted(DOCS.rglob("*.md")):
        # Two trees are excluded, each for a reason about what the page *is*.
        #
        # `docs/releases/` is history: it may name a command that has since been
        # renamed, and rewriting a published release note to match today's CLI would
        # be a lie about what that release shipped.
        #
        # `docs/research/` poses open questions, and naming something that does not
        # exist is the point — "what would a fair cross-CPU `yazses bench` look like,
        # and who runs it?" is a research question, not an instruction. Neither tree
        # tells anyone what to type now, which is what this guard is about.
        if {"releases", "research"} & set(path.parts):
            continue
        for words in _invocations(path.read_text(encoding="utf-8")):
            if _longest_real_prefix(list(words), shipped) is None:
                bad.append(f"{path.relative_to(ROOT)}: `yazses {' '.join(words)}`")
    assert not bad, (
        "these docs tell a user to run a command that does not exist:\n  "
        + "\n  ".join(sorted(set(bad)))
    )


def test_the_guard_would_notice_an_invented_command(shipped: set[str]) -> None:
    """Only worth having if it can fail — and `models` is the exact miss it was built on."""
    assert _longest_real_prefix(["models"], shipped) is None
    assert _longest_real_prefix(["model", "list"], shipped) == "model list"
    assert _longest_real_prefix(["audio", "use", "somename"], shipped) == "audio use"


def test_prose_after_a_command_is_not_read_as_a_subcommand(shipped: set[str]) -> None:
    """"run `yazses restart` to apply" must not be read as `yazses restart to apply`.

    Without this the guard would be so noisy nobody would keep it, which is its own
    way of not existing.
    """
    assert _invocations("run `yazses restart` to apply") == {("restart",)}
    assert _invocations("`yazses audio use <name>`") == {("audio", "use")}
