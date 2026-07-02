"""CLI: `yazses features info <name>` shows description + usage example for every capability."""
from __future__ import annotations

from typer.testing import CliRunner

import yazses.cli as cli
from yazses.config import Config
from yazses.system.features import feature_status

runner = CliRunner()
WIDE = {"COLUMNS": "220", "TERM": "dumb"}


def test_info_shows_example_for_a_toggleable_feature():
    r = runner.invoke(cli.app, ["features", "info", "reflow"], env=WIDE)
    assert r.exit_code == 0
    assert "Example:" in r.output
    assert "yazses features enable reflow" in r.output


def test_info_handles_core_feature():
    r = runner.invoke(cli.app, ["features", "info", "dictation"], env=WIDE)
    assert r.exit_code == 0
    assert "Example:" in r.output
    assert "not toggleable" in r.output.lower()


def test_info_unknown_feature_errors():
    r = runner.invoke(cli.app, ["features", "info", "does-not-exist"], env=WIDE)
    assert r.exit_code == 1
    assert "Unknown feature" in r.output


def test_info_works_for_every_registered_feature():
    # every slug must resolve and print an example (no crashes, full coverage)
    for f in feature_status(Config()):
        r = runner.invoke(cli.app, ["features", "info", f.slug], env=WIDE)
        assert r.exit_code == 0, f"features info {f.slug} failed: {r.output}"
        assert "Example:" in r.output, f"no example shown for {f.slug}"


def test_info_no_arg_lists_every_capability():
    # `yazses features info` with no name is the one place that shows ALL features,
    # each with its name and example.
    r = runner.invoke(cli.app, ["features", "info"], env=WIDE)
    assert r.exit_code == 0
    feats = feature_status(Config())
    assert f"{len(feats)} total" in r.output
    for f in feats:
        assert f.name in r.output, f"catalog omitted {f.name!r}"
