"""No test may read or write the developer's real portal restore token."""

from __future__ import annotations

from pathlib import Path

from platformdirs import PlatformDirs

from yazses.inject import portal


def test_the_suite_never_resolves_the_token_into_the_real_data_directory() -> None:
    real = Path(PlatformDirs("yazses", "yazses").user_data_dir).resolve()
    here = portal.token_path().resolve()
    assert real not in here.parents and here.parent != real, here


def test_writing_a_token_in_a_test_leaves_the_real_directory_untouched() -> None:
    real = Path(PlatformDirs("yazses", "yazses").user_data_dir) / portal.TOKEN_FILENAME
    before = real.read_bytes() if real.exists() else None
    portal.write_token("fake-token-for-the-guard-test")
    assert portal.read_token() == "fake-token-for-the-guard-test"
    after = real.read_bytes() if real.exists() else None
    assert after == before
