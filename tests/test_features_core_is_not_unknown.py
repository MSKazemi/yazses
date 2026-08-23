"""`yazses features enable dictation` said the feature does not exist. It does.

Found by sweeping `features enable` across all 147 catalog entries against a scratch config.
67 were refused, and 66 of those refusals were correct and well-worded — experimental ones
name the `--force` escape, unwired ones explain that enabling would change nothing. One was
not:

    $ yazses features enable dictation
    Unknown feature 'dictation'. Toggle names: commands, voice-punctuation, … (147 names)

`dictation` is the **core** capability. `yazses features` lists it, `yazses features info
dictation` describes it, and `feature_status()` returns it. Only `enable` and `disable`
claimed it did not exist — and answered with a dump of every other name, which is no help to
someone who typed a real one.

The cause is one condition doing two jobs:

    if feat is None or not feat.toggleable:
        typer.echo(f"Unknown feature {name!r}. …")

"Does not exist" and "exists but is not a switch" are different facts with different
remedies, and the second is the one a user can act on: there is nothing to fix, the
capability is already on.

## Why one instance was still worth splitting

Exactly one feature is non-toggleable today, so this is a single wrong sentence. It is
worth fixing because the condition is what is wrong, not the wording: any future
always-on capability inherits the same false answer, and the fix costs four lines.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from yazses.cli import app
from yazses.config import Config
from yazses.system.features import feature_status, find_feature


@pytest.fixture
def scratch(sandbox_paths):
    """A config directory these tests may write to — see `sandbox_paths` in conftest.

    This fixture used to build the sandbox itself out of environment variables, and
    two successive attempts at that were both wrong. `XDG_CONFIG_HOME` alone is a
    Linux answer: platformdirs reads `%LOCALAPPDATA%` on Windows and
    `~/Library/Application Support` on macOS, so on the Windows runner it sandboxed
    nothing and `features enable` wrote into the runner's own config, which only the
    host-state guard in conftest noticed, at teardown, as an error rather than a
    failure.

    Adding `APPDATA`/`LOCALAPPDATA`/`HOME`/`USERPROFILE` looked like the fix and was
    not, and the reason it survived review is that it was never executed on Windows.
    Run there, it stops the write and then fails its own sandbox assertion for every
    test in this file: platformdirs asks the OS for the Windows folders, so no
    environment variable can move them. The working sandbox replaces `build_paths()`
    instead, which is a seam rather than a hint.
    """
    yield sandbox_paths.config_dir


def _core_slugs() -> list[str]:
    return [f.slug for f in feature_status(Config()) if not f.toggleable]


def test_there_is_a_non_toggleable_feature_to_test() -> None:
    """Guard the guard: if none exists, every assertion below is vacuous."""
    assert _core_slugs(), "no non-toggleable feature — this file has nothing to check"


@pytest.mark.parametrize("action", ["enable", "disable"])
def test_a_core_feature_is_not_reported_as_unknown(action: str, scratch) -> None:
    slug = _core_slugs()[0]
    result = CliRunner().invoke(app, ["features", action, slug])
    assert result.exit_code != 0, "a core capability must not be toggled"
    assert "Unknown feature" not in result.output, (
        f"`features {action} {slug}` claims the capability does not exist; it is listed "
        f"by `yazses features` and described by `features info`"
    )
    assert "cannot be toggled" in result.output


@pytest.mark.parametrize("action", ["enable", "disable"])
def test_the_refusal_points_somewhere_useful(action: str, scratch) -> None:
    """A refusal that dumps 147 other names is not a remedy."""
    slug = _core_slugs()[0]
    result = CliRunner().invoke(app, ["features", action, slug])
    assert f"features info {slug}" in result.output


@pytest.mark.parametrize("action", ["enable", "disable"])
def test_a_genuinely_unknown_name_still_says_unknown(action: str, scratch) -> None:
    """The opposite failure: softening both branches would lose a real error."""
    result = CliRunner().invoke(app, ["features", action, "definitely-not-a-feature"])
    assert result.exit_code != 0
    assert "Unknown feature" in result.output


def test_the_core_feature_really_is_listed_and_describable(scratch) -> None:
    """The premise of the whole file: `enable` was the only surface that disagreed."""
    slug = _core_slugs()[0]
    assert find_feature(Config(), slug) is not None

    runner = CliRunner()
    assert runner.invoke(app, ["features", "info", slug]).exit_code == 0
    listing = runner.invoke(app, ["features"])
    assert listing.exit_code == 0
    assert find_feature(Config(), slug).name in listing.output


def test_an_ordinary_feature_still_toggles(scratch) -> None:
    """A refusal branch that caught too much would break every real toggle."""
    result = CliRunner().invoke(app, ["features", "enable", "timeline", "--no-install"])
    assert result.exit_code == 0, result.output
    assert "Unknown feature" not in result.output
