"""The Homebrew cask must name BOTH macOS permissions, not just Accessibility.

A `CGEventTap` needs **Input Monitoring** as well as Accessibility (macOS 10.15+),
and either one being off produces the identical symptom: the dictation key is dead
everywhere while the Accessibility toggle sits there enabled. `7b039fb` taught the
app to request Input Monitoring, and `docs/macos-install.md` and
`platform/macos/permissions.py` were both updated to say so.

The cask was not. Its caveats still told users to grant Accessibility and nothing
else -- and the caveats are the *only* instructions a `brew install --cask` user
ever sees, since they never open the docs site. Six version-bump refreshes touched
that file afterwards and none noticed, because a refresh rewrites `version` and
`sha256` and reads nothing else.

That is the surface the project's macOS bug reports keep arriving through, so this
guards it by content rather than trusting the next refresh to remember.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CASK = ROOT / "packaging" / "homebrew" / "yazses.rb"


@pytest.fixture(scope="module")
def caveats() -> str:
    text = CASK.read_text(encoding="utf-8")
    m = re.search(r"caveats <<~EOS\n(.*?)\n\s*EOS", text, re.S)
    assert m, "the cask has no caveats block"
    # Collapse the wrapping. These caveats are hard-wrapped prose, so "Input
    # Monitoring" is routinely split across a line break -- a phrase search
    # against the raw text fails on formatting rather than on content, which is
    # a test that reports the wrong thing.
    return re.sub(r"\s+", " ", m.group(1))


def test_the_caveats_name_input_monitoring(caveats: str) -> None:
    """Without it, the instructions describe a build that does not work."""
    assert re.search(r"input monitoring", caveats, re.I), (
        "the cask tells users to grant Accessibility and stops there. Accessibility "
        "alone leaves the dictation key dead in every application."
    )


def test_the_caveats_still_name_accessibility(caveats: str) -> None:
    """Both are required; naming only the new one would be the same bug mirrored."""
    assert re.search(r"accessibility", caveats, re.I)


def test_the_caveats_explain_the_empty_list(caveats: str) -> None:
    """'Enable it in Settings' is unfollowable while the app is absent from the pane.

    An app appears in Input Monitoring only once it has asked, and the `+` button
    cannot add it beforehand -- so a user told to enable it, finding nothing to
    enable, concludes the install failed.
    """
    assert re.search(r"only appears|once it has asked|cannot add it", caveats, re.I), (
        "the caveats do not say what to do when YazSes is not in the list"
    )


def test_the_regrant_note_covers_both_permissions(caveats: str) -> None:
    """The bundle is unsigned, so an upgrade drops BOTH grants, not just one."""
    m = re.search(r"re-grant([^.]*)\.", caveats, re.I | re.S)
    assert m, "the cask no longer explains that an upgrade drops the grants"
    assert re.search(r"input monitoring", m.group(1), re.I), (
        f"the re-grant note names only: {m.group(1)!r}"
    )


def test_the_cask_does_not_promise_a_microphone_prompt_that_cannot_arrive(
    caveats: str,
) -> None:
    """The microphone prompt is downstream of the key working.

    YazSes records only while the key is held, so a key dead for want of Input
    Monitoring never records, never prompts, and never reaches the Microphone
    pane. Presenting the mic prompt as unconditional is what made three symptoms
    of one cause read as three separate bugs.
    """
    assert re.search(r"hold", caveats, re.I), (
        "the caveats do not tie the microphone prompt to holding the key"
    )
