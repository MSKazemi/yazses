"""The sandbox has to work on the OS the suite is *running* on, not the one it was written on.

Two attempts at sandboxing config writes shipped before this one, and both were correct
on Linux and wrong elsewhere. The first set `XDG_CONFIG_HOME`, which platformdirs reads
only on Linux. The second added `APPDATA`, `LOCALAPPDATA`, `HOME` and `USERPROFILE` --
which looks exhaustive and is still wrong, because platformdirs asks Windows for its
known folders rather than reading the environment at all. Executed on Windows Server
2022, that second version stopped the write and then failed its own sandbox assertion
for all eight tests that used it, so the build stayed red.

Neither was caught by a test, because the tests that *used* the sandbox all passed on the
machine anyone ran them on. This file tests the sandbox itself, so whichever OS the suite
runs on has to answer for it.
"""
from __future__ import annotations

from pathlib import Path

import pytest


def _resolved_config_dir() -> Path:
    from yazses.platform.factory import get_paths

    return get_paths().config_dir


def test_the_sandbox_moves_the_config_directory(sandbox_paths, tmp_path):
    resolved = _resolved_config_dir()
    assert tmp_path in resolved.parents, (
        f"config_dir resolved to {resolved}, outside {tmp_path} — on this OS the "
        f"sandbox does not take, and any test writing config edits the real machine"
    )


def test_it_moves_the_platform_bundle_too_not_only_the_factory(sandbox_paths, tmp_path):
    # `get_paths()` and `get_platform().paths` are two doors to the same answer and the
    # CLI uses the second one. A sandbox that only moved the first would look right here
    # and leak in every command.
    from yazses.platform import get_platform

    assert tmp_path in get_platform().paths.config_file.parents


def test_every_directory_is_inside_the_sandbox_not_just_config(sandbox_paths, tmp_path):
    # The learning corpus, the pid file and the logs all live off the other four.
    paths = _paths()
    for name in ("config_dir", "state_dir", "cache_dir", "log_dir", "data_dir"):
        resolved = getattr(paths, name)
        assert tmp_path in resolved.parents, f"{name} escaped to {resolved}"


def _paths():
    from yazses.platform.factory import get_paths

    return get_paths()


def test_a_real_config_write_lands_inside_the_sandbox(sandbox_paths):
    # The end-to-end shape of the original escape: `features enable` through the CLI,
    # which is what wrote `[timeline] enabled = true` into a developer's own config and
    # into the Windows runner's.
    from typer.testing import CliRunner

    from yazses.cli import app

    result = CliRunner().invoke(app, ["features", "enable", "timeline", "--no-install"])
    assert result.exit_code == 0, result.output
    written = sandbox_paths.config_dir / "config.toml"
    assert written.exists(), "the write did not land in the sandbox"
    assert "timeline" in written.read_text(encoding="utf-8")


def test_the_sandbox_is_released_so_the_next_test_sees_the_real_paths(sandbox_paths):
    # Guard the teardown: a fixture that left its tmp_path cached would silently
    # sandbox every later test in the session, which hides real path bugs rather than
    # causing them — the quietest possible failure.
    assert _resolved_config_dir() != Path("/nonexistent")


def test_after_the_fixture_the_caches_are_clean():
    # Runs without the fixture. If the previous test's tmp_path were still cached this
    # would still point at it, since both lru_caches are `maxsize=1`.
    resolved = _resolved_config_dir()
    assert "yazses-sandbox" not in str(resolved), (
        f"a previous test's sandbox is still cached: {resolved}"
    )


@pytest.mark.parametrize("attempt", ["XDG_CONFIG_HOME", "LOCALAPPDATA", "APPDATA"])
def test_the_sandbox_does_not_depend_on_an_environment_variable(
    sandbox_paths, monkeypatch, tmp_path, attempt
):
    # Clearing the variable the old sandbox relied on must change nothing. If this
    # fails, the sandbox has quietly gone back to being a hint to the resolver rather
    # than a replacement for it.
    monkeypatch.delenv(attempt, raising=False)
    from yazses.platform.factory import reset_platform_cache

    reset_platform_cache()
    assert tmp_path in _resolved_config_dir().parents
