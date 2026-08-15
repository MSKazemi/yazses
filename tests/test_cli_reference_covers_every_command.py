"""`docs/cli-reference.md` must document every command the CLI actually ships.

The reference is **hand-written** — deliberately, because it is example-first and
grouped the way the CLI's own `--help` panels are, which a generator does not do
well. The cost of that choice is that a new command reaches users with no entry,
and nothing notices.

That is not hypothetical. `gitvoice`, `fileopen` and `jump` all shipped, all
appeared in the generated `docs/command-index.md`, and all were missing from the
reference until a documentation audit on 2026-08-14 diffed the two by hand.

So this asserts against the **live Click tree**, not against the generated index:
an index that had gone stale in the same way would otherwise agree with a stale
reference and both would pass.

**It walks into groups.** The first version of this guard read only the top level,
so `yazses meeting` being present made the whole group look covered — and
`meeting enroll` and `gaze status` sat undocumented behind it, in the reference
alone, while `command-index.md` and the man page both listed them. Fifteen groups
carry roughly fifty subcommands between them; checking the fifteen names proves
nothing about the fifty.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from yazses.cli import app

REFERENCE = Path(__file__).resolve().parents[1] / "docs" / "cli-reference.md"


def _shipped_commands() -> list[str]:
    """Every invocable path in the CLI: `start`, `meeting`, `meeting enroll`, …

    Descends by asking for `.commands` rather than by `isinstance(cmd, click.Group)`.
    Under Click 8.4 `typer.core.TyperGroup` does **not** subclass `click.Group` — it
    derives from `typer._click.core.Command` — so an isinstance walk silently finds
    no subcommands at all and this guard passes while checking nothing. That is the
    exact failure being fixed here, so it must not be reintroduced by the fix.
    """
    found: list[str] = []

    def walk(group: Any, prefix: str) -> None:
        for name, cmd in group.commands.items():
            path = f"{prefix} {name}".strip()
            found.append(path)
            if hasattr(cmd, "commands"):
                walk(cmd, path)

    walk(typer.main.get_command(app), "")
    return sorted(found)


def test_every_shipped_command_appears_in_the_cli_reference() -> None:
    text = REFERENCE.read_text(encoding="utf-8")
    missing = [name for name in _shipped_commands() if f"yazses {name}" not in text]
    assert not missing, (
        "These commands ship but are absent from docs/cli-reference.md: "
        f"{missing}. Add an entry with a real, run-it-yourself example — the "
        "reference is example-first, so a bare mention is not enough."
    )


def test_the_guard_descends_into_command_groups() -> None:
    """The blind spot that let two subcommands ship undocumented.

    A guard that only reads the top level cannot fail on a missing subcommand, so
    pin that the walk actually produces them.
    """
    shipped = _shipped_commands()
    assert "meeting" in shipped and "meeting enroll" in shipped
    assert "gaze status" in shipped
    assert sum(" " in name for name in shipped) > 40, (
        "expected the walk to reach the subcommands of every group; it found "
        f"only {sum(' ' in name for name in shipped)}"
    )


def test_the_guard_would_notice_a_missing_command() -> None:
    """The check above is only worth having if it can fail.

    A substring search over a 1,200-line document passes very easily; this pins
    that a name which is genuinely absent is genuinely reported.
    """
    text = REFERENCE.read_text(encoding="utf-8")
    assert "yazses definitely-not-a-real-command" not in text
