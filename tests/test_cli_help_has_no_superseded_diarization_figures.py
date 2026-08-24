"""No shipped `--help` text may quote a DER the current defaults do not produce.

`yazses meeting start --help` told every user that speaker labelling scores **84 % DER**
by default and 29 % if they pass `--speakers`. Both figures were measured against
`cluster_threshold = 0.5` on a four-meeting subset; ADR-v2-133 raised the default to
`1.2`, at which the full AMI test split scores 26.71 %. The help text was quoting a
configuration the product had stopped shipping — overstating its own error rate
threefold and pushing users toward a flag on evidence that no longer described it.

`tests/test_speaker_count_advice.py` already forbade those figures, and did not catch
this: it checks the string `speaker_count_advice()` returns, and this was a different
surface saying the same wrong thing. One guard per surface is the defect; the set of
surfaces is what has to be derived.

So this walks the **Typer app itself** — every command, every option — rather than a
list of files someone remembered to add. A new command that copies the old sentence
fails on the day it lands.

Docstrings and comments in the source may still discuss `84.09 %`, and several do: it
is the measurement the default change was made *on*, and deleting the history would
make the reasoning unfollowable. What may not survive is a figure presented to a user
as what their installation does.
"""
from __future__ import annotations

from typing import Any

import pytest
import typer

from yazses.cli import app

#: Figures from the pre-ADR-v2-133 configuration. Any of these in a help string is a
#: claim about a threshold the product no longer ships.
SUPERSEDED = ("84%", "84 %", "84.09", "28.55", "257 speakers")


def _help_texts() -> list[tuple[str, str]]:
    """(where, text) for every command help and every option help in the app.

    Descends by asking for `.commands` rather than `isinstance(cmd, click.Group)`:
    under Click 8.4 `typer.core.TyperGroup` does not subclass `click.Group`, so an
    isinstance walk finds no subcommands and a guard built on it passes while reading
    nothing. That failure has already happened once in this repo.
    """
    out: list[tuple[str, str]] = []

    def walk(group: Any, prefix: str) -> None:
        for name, cmd in group.commands.items():
            path = f"{prefix} {name}".strip()
            for attr in ("help", "short_help"):
                if text := getattr(cmd, attr, None):
                    out.append((f"{path} ({attr})", str(text)))
            for param in getattr(cmd, "params", ()):
                if text := getattr(param, "help", None):
                    opts = "/".join(getattr(param, "opts", []) or [param.name])
                    out.append((f"{path} {opts}", str(text)))
            if hasattr(cmd, "commands"):
                walk(cmd, path)

    walk(typer.main.get_command(app), "")
    return out


def test_the_walk_actually_reaches_the_nested_commands() -> None:
    """Guard the guard. Every check below iterates this list; an empty or shallow
    walk passes them all while reading nothing -- which is how the Typer traversal
    failed the last time it was written."""
    found = _help_texts()
    assert len(found) > 100, f"only walked {len(found)} help strings"
    where = {w.split(" (")[0].rsplit(" ", 1)[0] for w, _ in found}
    assert any(w.startswith("meeting ") for w in where), (
        f"the walk never descended into the `meeting` sub-app: {sorted(where)[:20]}"
    )


@pytest.mark.parametrize("figure", SUPERSEDED)
def test_no_help_text_quotes_a_superseded_diarization_figure(figure: str) -> None:
    hits = [where for where, text in _help_texts() if figure in text]
    assert not hits, (
        f"{hits} quote `{figure}`, measured at the pre-ADR-v2-133 "
        f"`cluster_threshold = 0.5`. The shipped default is 1.2 and scores 26.71% on "
        "the full AMI test split. Quote what this build does, or no number at all."
    )


def test_the_speakers_flag_still_warns_that_the_count_is_exact() -> None:
    """Removing the stale figures must not remove the part that prevents a bug.
    `max_speakers` is an exact cluster count on the shipped sherpa backend, so a
    cautious over-estimate invents people who were never in the room."""
    texts = [t for w, t in _help_texts() if "--speakers" in w]
    assert texts, "no --speakers option found in the app"
    assert any("exact count" in t and "not a maximum" in t for t in texts), (
        f"none of the --speakers help strings say the count is exact: {texts}"
    )
