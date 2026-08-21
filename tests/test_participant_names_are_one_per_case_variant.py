"""A participant name is one identity regardless of case, on every filesystem.

`load_participants` recovers the display name from the *filename stem* — the name is
stored nowhere else — so the file is the identity. On a case-insensitive filesystem
(macOS APFS, NTFS) `Alice.vp` and `alice.vp` are therefore one participant whatever the
code intends, and on Linux they were two. Which behaviour a user got was a property of
their filesystem.

That is not a cosmetic split. The data is biometric and enrolled under an explicit-consent
policy (ADR-011/012): on macOS, enrolling "alice" destroyed the voiceprint belonging to
"Alice", and `existing_participant` said so truthfully while `participant_path` reported a
different path for each — the warning and the write disagreed. CI caught it as
`test_distinct_names_do_not_collide[Alice-alice]`, failing on macOS and passing on Linux.

`participant_path` now resolves against what is already enrolled, so the identity is the
same everywhere and the case that was enrolled first is the one kept.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yazses.meeting.participants import (
    existing_participant,
    participant_path,
    participant_stem,
)


class _Cfg:
    def __init__(self, root: Path):
        self.participants_dir = str(root)


@pytest.fixture
def cfg(tmp_path) -> _Cfg:
    return _Cfg(tmp_path)


def _enroll(cfg: _Cfg, name: str) -> Path:
    p = participant_path(name, cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"an encrypted voiceprint")
    return p


def test_a_case_variant_resolves_to_the_enrolled_profile(cfg) -> None:
    alice = _enroll(cfg, "Alice")
    assert participant_path("alice", cfg) == alice
    assert participant_path("ALICE", cfg) == alice


def test_the_warning_and_the_write_agree(cfg) -> None:
    """The invariant that failed on macOS, asserted here without depending on the host.

    `existing_participant` may report a replacement if and only if the enrollment would
    actually land on that file. Deriving the path from the name alone satisfied this on a
    case-sensitive filesystem and broke it on every other one.
    """
    alice = _enroll(cfg, "Alice")
    found = existing_participant("alice", cfg)
    assert found is not None
    assert found == alice == participant_path("alice", cfg)


def test_the_enrolled_case_is_the_one_kept(cfg) -> None:
    """The display name comes from the stem, so resolving must not rewrite it."""
    _enroll(cfg, "Alice")
    assert participant_path("alice", cfg).stem == "Alice"


def test_an_unenrolled_name_keeps_its_own_case(cfg) -> None:
    """Resolution must not reach for an unrelated profile."""
    _enroll(cfg, "Alice")
    assert participant_path("bob", cfg).stem == "bob"
    assert existing_participant("bob", cfg) is None


def test_names_that_merely_look_similar_stay_separate(cfg) -> None:
    """Only case may fold. A prefix or a different spacing is a different person."""
    _enroll(cfg, "Anne Marie")
    assert participant_path("Anne  Marie", cfg) != participant_path("Anne Marie", cfg)
    _enroll(cfg, "Bob")
    assert participant_path("Bobby", cfg) != participant_path("Bob", cfg)
    assert existing_participant("Bobby", cfg) is None


def test_an_exact_match_still_wins_over_a_case_variant(tmp_path) -> None:
    """A machine that already holds both variants must keep returning each for its name.

    Only reachable on a case-sensitive filesystem — on macOS or Windows the second write
    lands on the first file, which is the whole reason this module folds case at all.
    """
    cfg = _Cfg(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "Alice.vp").write_bytes(b"x")
    (tmp_path / "alice.vp").write_bytes(b"y")
    if len(list(tmp_path.glob("*.vp"))) < 2:
        pytest.skip("case-insensitive filesystem: two case-variants cannot coexist")
    assert participant_path("Alice", cfg).stem == "Alice"
    assert participant_path("alice", cfg).stem == "alice"


def test_the_pure_half_is_still_available(cfg) -> None:
    """`participant_path` now reads the directory; the pure stem must remain separable."""
    assert participant_stem("  Alice ") == "Alice"
    assert participant_stem("a/b\\c") == "abc"
    assert participant_stem("   ") == "participant"
