"""Every `--flag` the docs show must exist on the command they show it with.

`test_cli_reference_covers_every_command.py` guards the other direction — that no
shipped command is missing from the reference. Nothing checked the flags, so a
renamed or removed option could sit in the docs indefinitely, and a reader would
find out by having the command reject it.

That is not hypothetical for this project: `--min-speakers` spent this cycle
documented as a lower bound it never applied, and `[remote] default_host` was
documented as a default for an argument that cannot be omitted. Both were about the
*meaning* of an option rather than its existence — this file closes the cheaper half,
where the option is simply not there.

**The result today is zero**, which is the point of pinning it: the invariant already
holds and this keeps it holding.

## Two traps this file is written around

**`TyperGroup` is not a `click.Group` under Click 8.4.** An `isinstance` walk finds no
subcommands, returns one path, and passes — a guard that checks nothing. The walk is
duck-typed on `.commands` instead, and `test_the_walk_actually_descends` fails if it
ever collapses again.

**A scanner that matches nothing passes too.** `test_the_scanner_finds_a_planted_flag`
plants an invented option and requires it to be caught, so an over-tight regex cannot
masquerade as a clean bill of health.
"""
from __future__ import annotations

import re
from pathlib import Path

import typer.main

from yazses.cli import app

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

#: Release notes record what a version shipped with and are not corrected in place.
SKIP_DIRS = {"releases"}

#: Matches `yazses <up to 3 command words> --flag [--flag …]` in prose or a code block.
INVOCATION = re.compile(r"yazses ((?:[a-z][\w-]*\s+){1,3})((?:--[\w-]+\s*)+)")


def _flag_table() -> dict[tuple[str, ...], set[str]]:
    """Every command path in the app mapped to the long options it accepts."""

    def walk(command, path: tuple[str, ...] = ()) -> dict[tuple[str, ...], set[str]]:
        out: dict[tuple[str, ...], set[str]] = {}
        # Duck-typed on purpose — see the module docstring.
        for name, sub in (getattr(command, "commands", {}) or {}).items():
            out.update(walk(sub, path + (name,)))
        opts = {
            opt
            for param in getattr(command, "params", [])
            for opt in list(getattr(param, "opts", []))
            + list(getattr(param, "secondary_opts", []))
            if opt.startswith("--")
        }
        out[path] = opts
        return out

    return walk(typer.main.get_command(app))


def _pages() -> list[Path]:
    return [p for p in DOCS.rglob("*.md") if not SKIP_DIRS & set(p.relative_to(DOCS).parts)]


def _unknown_flags(extra_line: str = "") -> list[str]:
    table = _flag_table()
    root = table.get((), set())

    def resolve(tokens: list[str]):
        for n in (3, 2, 1):
            path = tuple(tokens[:n])
            if path in table:
                return path, table[path]
        return None, None

    def scan(text: str, where: str) -> list[str]:
        found = []
        for num, line in enumerate(text.splitlines(), 1):
            for match in INVOCATION.finditer(line):
                path, flags = resolve(match.group(1).split())
                if path is None:
                    continue  # not a command we ship; nothing to say about its flags
                for flag in re.findall(r"--[\w-]+", match.group(2)):
                    if flag in flags or flag in root or flag == "--help":
                        continue
                    found.append(f"{where}:{num} — `yazses {' '.join(path)} {flag}`")
        return found

    out: list[str] = []
    for page in _pages():
        out += scan(page.read_text(encoding="utf-8"), str(page.relative_to(ROOT)))
    if extra_line:
        out += scan(extra_line, "<planted>")
    return sorted(set(out))


def test_no_page_documents_a_flag_the_command_does_not_have():
    bad = _unknown_flags()
    assert not bad, (
        "these docs show an option the command does not accept — rename it, remove "
        "it, or add the option:\n  " + "\n  ".join(bad)
    )


def test_the_walk_actually_descends_into_subcommands():
    """Guards the guard: an isinstance walk collapses to one path and passes."""
    table = _flag_table()
    assert len(table) > 50, f"only {len(table)} command paths — the walk collapsed"
    assert "--diarize" in table[("transcribe",)]
    assert "--json" in table[("status",)]


def test_the_scanner_finds_a_planted_flag():
    """A regex that matches nothing would otherwise report a clean bill of health."""
    planted = _unknown_flags("yazses status --totally-invented-flag\n")
    assert any("--totally-invented-flag" in line for line in planted), planted
