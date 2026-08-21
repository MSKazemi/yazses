"""Enrolling a name twice destroys the first voiceprint; it must say so.

`enroll_participant` writes to a path derived from the display name and calls
`save_voiceprint` with no existence check. So:

    yazses meeting enroll <a> speaker_0 --name Alice
    yazses meeting enroll <b> speaker_1 --name Alice

replaces the first Alice's biometric voiceprint, and reports the same success message
either way.

Replacing is legitimate — a longer or cleaner recording gives a better embedding — so this
is not blocked. What is wrong is doing it silently: from inside YazSes a *second person
named Alice* and a *re-enrollment of the same Alice* are indistinguishable, and only one of
those is what the user meant. The data is biometric and was enrolled deliberately, under an
explicit-consent policy (ADR-011/012), which is exactly the kind of data not to overwrite
without a word.

`existing_participant` answers the question, and `yazses meeting enroll` now says
"Replaced the existing voiceprint for …" when it applies.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from yazses.meeting.participants import existing_participant, participant_path


class _Cfg:
    def __init__(self, root: Path):
        self.participants_dir = str(root)


@pytest.fixture
def cfg(tmp_path) -> _Cfg:
    return _Cfg(tmp_path)


def test_nothing_enrolled_means_nothing_replaced(cfg) -> None:
    assert existing_participant("Alice", cfg) is None


def test_an_enrolled_name_is_reported_as_a_replacement(cfg) -> None:
    path = participant_path("Alice", cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"an encrypted voiceprint")

    found = existing_participant("Alice", cfg)
    assert found is not None and found == path


def test_a_different_name_is_not_a_replacement(cfg) -> None:
    """A guard that reported every enrollment as a replacement would be noise."""
    p = participant_path("Alice", cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
    assert existing_participant("Bob", cfg) is None


def test_the_path_is_the_one_enrollment_writes_to(cfg) -> None:
    """The check is worthless if it looks somewhere else.

    `enroll_participant` must use `participant_path`, or the two could disagree and the
    warning would be decorative.
    """
    source = inspect.getsource(
        __import__("yazses.meeting.participants", fromlist=["x"]).enroll_participant
    )
    assert "participant_path(" in source, (
        "enroll_participant computes its own path again — the replacement check can drift"
    )


@pytest.mark.parametrize(
    "name,other",
    [("Alice", "alice"), ("Anne Marie", "Anne  Marie"), ("Bob", "Bobby")],
)
def test_distinct_names_do_not_collide(cfg, name: str, other: str) -> None:
    """Only a real collision may be called a replacement."""
    p = participant_path(name, cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
    assert (existing_participant(other, cfg) is not None) == (
        participant_path(other, cfg) == p
    )


def test_the_cli_says_which_happened() -> None:
    """Read from the source: driving it needs an embedder, a cipher and a real meeting."""
    from yazses import cli

    source = inspect.getsource(cli)
    assert "existing_participant" in source, "the CLI never checks for a replacement"
    assert "Replaced the existing voiceprint" in source, (
        "the CLI checks and then reports the same message either way"
    )
