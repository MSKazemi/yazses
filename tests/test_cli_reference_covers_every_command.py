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
"""

from __future__ import annotations

from pathlib import Path

import typer

from yazses.cli import app

REFERENCE = Path(__file__).resolve().parents[1] / "docs" / "cli-reference.md"


def _shipped_commands() -> list[str]:
    return sorted(typer.main.get_command(app).commands.keys())


def test_every_shipped_command_appears_in_the_cli_reference() -> None:
    text = REFERENCE.read_text(encoding="utf-8")
    missing = [name for name in _shipped_commands() if f"yazses {name}" not in text]
    assert not missing, (
        "These commands ship but are absent from docs/cli-reference.md: "
        f"{missing}. Add an entry with a real, run-it-yourself example — the "
        "reference is example-first, so a bare mention is not enough."
    )


def test_the_guard_would_notice_a_missing_command() -> None:
    """The check above is only worth having if it can fail.

    A substring search over a 1,200-line document passes very easily; this pins
    that a name which is genuinely absent is genuinely reported.
    """
    text = REFERENCE.read_text(encoding="utf-8")
    assert "yazses definitely-not-a-real-command" not in text
