"""A limitation the code knows about must be visible where a user looks for it.

`audio/devices.py::is_routing_alias` exists solely to describe one, and its docstring
says what to do with it:

    "This is why the device-change watcher cannot see a switch on a typical Linux
    desktop: it detects a change by comparing this name over time, and against an
    alias it compares `default` with `default` for ever... so the limitation is
    named where a user looks instead of being silently absent."

`docs/reliability.md` is that place — its whole subject is which failures recover by
themselves and which do not. It listed *"OS default input changed → capture heals back
to the last-good device"* in a table of working signals, with no caveat, and its
*"What does not heal itself"* section did not mention it. On PipeWire or PulseAudio
that trigger never fires.

Nothing was broken in the code. The streak-based half of the guard catches the same
failure by counting outcomes rather than names, which is why this was invisible: the
microphone does get healed, just later and for a different reason than the page said.

This test ties the two together. While the limitation exists, the page must name it;
if someone ever reads through the alias properly and removes the limitation, this test
fails and prompts the page to be updated in the same commit.
"""

from __future__ import annotations

from pathlib import Path

from yazses.audio import devices

PAGE = Path(__file__).resolve().parents[1] / "docs" / "reliability.md"


def test_the_limitation_still_exists() -> None:
    """The premise. If this ever goes away, the warning below should go with it."""
    assert hasattr(devices, "is_routing_alias"), (
        "is_routing_alias is gone — if the watcher can now read through the alias, "
        "delete the warning in docs/reliability.md in the same commit"
    )
    assert devices.is_routing_alias("default") is True
    assert devices.is_routing_alias("Raptor Lake-P/U/H cAVS Digital Microphone") is False


def test_the_reliability_page_names_it() -> None:
    """The page a user reads to learn what heals must not overstate what heals."""
    page = PAGE.read_text(encoding="utf-8").lower()
    assert "alias" in page, (
        "docs/reliability.md presents the OS-default-changed trigger without saying it "
        "cannot fire on PipeWire/PulseAudio, where the default is a routing alias whose "
        "name never changes. is_routing_alias's docstring asks for this to be 'named "
        "where a user looks'."
    )
    # The compensating behaviour matters as much as the limitation: without it the
    # warning reads as "your microphone is not protected", which is false.
    assert "silent streak" in page or "counts *outcomes*" in page or "outcomes" in page


def test_the_page_still_tells_the_user_what_to_do_about_it() -> None:
    """A limitation with no remedy is an apology. Pinning removes the problem."""
    page = PAGE.read_text(encoding="utf-8")
    assert "yazses audio use" in page
