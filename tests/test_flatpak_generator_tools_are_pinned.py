"""The program that writes the pins must not itself be unpinned.

`packaging/flatpak/python3-yazses.json` is the artefact Flathub builds YazSes from:
45 wheels, each with a URL and a SHA-256. Its entire value is that it pins.

It is *generated*, by `uv pip compile` and `req2flatpak`, in the `generate` job of
`.github/workflows/flatpak.yml`. Those two programs were installed with

    python3 -m pip install --quiet --upgrade uv req2flatpak

-- unpinned, and `--upgrade` to be sure of taking whatever PyPI served that minute.
So the thing deciding what the pins *are* was the one thing with no pin at all.

That inversion matters more than an ordinary unpinned CI tool because of what the
output looks like. A compromised `req2flatpak` writes attacker URLs with matching
hashes into a JSON file that a human then reviews and commits, and hashes are
exactly the field a reviewer cannot check by reading. The pin would be perfect and
would pin the wrong thing.

The tools are now hash-pinned in `packaging/flatpak/tools-requirements.txt` and
installed with `--require-hashes`, which makes pip refuse an artifact whose digest
does not match. This module holds that arrangement together: the file must stay
hash-complete, and the workflow must keep using it that way.

Deliberately scoped to this one workflow. The other `pip install` lines in
`.github/workflows/` install test dependencies into a throwaway runner and produce
nothing that is shipped or committed; requiring hashes there would buy little and
would make the FreeBSD leg, which installs by name on purpose, much harder to keep
working. The distinction is not "CI" versus "release" -- it is whether the command
*produces a pinned artefact somebody later trusts*.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = REPO / ".github" / "workflows" / "flatpak.yml"
TOOLS = REPO / "packaging" / "flatpak" / "tools-requirements.txt"

#: `name==version \` at the start of a line -- one per pinned distribution.
_PIN = re.compile(r"^(?P<name>[A-Za-z0-9._-]+)==(?P<version>[^\s\\]+)", re.MULTILINE)


def _tools_text() -> str:
    assert TOOLS.is_file(), (
        f"{TOOLS.relative_to(REPO)} is gone. It is what makes the Flatpak "
        "dependency generator reproducible; if the generator was removed, remove "
        "this module too rather than leaving it to pass on a missing file."
    )
    return TOOLS.read_text(encoding="utf-8")


def test_the_workflow_installs_the_generator_tools_with_required_hashes() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "--require-hashes" in text, (
        "the Flatpak generate job no longer installs its tools with "
        "`--require-hashes`. Without it pip treats the hashes as advisory and a "
        "substituted artifact installs silently -- which is the whole failure this "
        "file exists to prevent, because the tools go on to WRITE the pins in "
        "packaging/flatpak/python3-yazses.json."
    )
    assert "packaging/flatpak/tools-requirements.txt" in text, (
        "the generate job no longer reads the hash-pinned requirements file."
    )
    assert "--upgrade uv req2flatpak" not in text, (
        "the unpinned `pip install --upgrade uv req2flatpak` is back."
    )


def test_every_pinned_tool_carries_at_least_one_hash() -> None:
    """`--require-hashes` fails the whole file if any one requirement lacks a hash,
    so a hashless line does not weaken the pin -- it breaks the job. Caught here
    instead, where the message says which line and why."""
    text = _tools_text()
    blocks = re.split(r"\n(?=[A-Za-z0-9._-]+==)", text)
    pinned = [b for b in blocks if _PIN.match(b)]
    assert pinned, (
        f"{TOOLS.relative_to(REPO)} pins nothing. An empty requirements file "
        "installs nothing and `--require-hashes` is satisfied vacuously, so the "
        "generate job would fail later and for the wrong stated reason."
    )
    missing = [_PIN.match(b).group("name") for b in pinned if "--hash=sha256:" not in b]
    assert not missing, (
        f"these pins carry no hash: {missing}. `pip install --require-hashes` "
        "refuses a file where any requirement is unhashed, so this would fail the "
        "Flatpak generate job outright."
    )


def test_the_two_tools_the_job_actually_runs_are_the_ones_pinned() -> None:
    """A requirements file can be perfectly hash-pinned and pin the wrong programs.

    The job invokes `uv pip compile` and `req2flatpak` by name; if either stops
    being listed here it is installed from somewhere else, or not at all, and the
    hash pinning describes packages nobody runs.
    """
    names = {m.group("name").lower().replace("_", "-") for m in _PIN.finditer(_tools_text())}
    workflow = WORKFLOW.read_text(encoding="utf-8")
    for tool in ("uv", "req2flatpak"):
        assert tool in names, (
            f"`{tool}` is run by the Flatpak generate job but is not pinned in "
            f"{TOOLS.relative_to(REPO)}."
        )
        assert tool in workflow, (
            f"`{tool}` is pinned but the workflow no longer runs it -- either the "
            "job changed and this pin is dead weight, or the pin is now describing "
            "the wrong toolchain."
        )


def test_the_regeneration_recipe_is_written_down() -> None:
    """A generated file with no recorded command is a file nobody dares update.

    These pins will go stale, and the person updating them will not be the person
    who wrote them. Without the exact `uv pip compile` invocation, the likely next
    move is to delete the hashes rather than to regenerate them.
    """
    text = _tools_text()
    assert "uv pip compile" in text and "--generate-hashes" in text, (
        f"{TOOLS.relative_to(REPO)} no longer records how to regenerate itself."
    )
