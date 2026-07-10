"""`yazses features` clusters capabilities into categories and supports filters."""
from __future__ import annotations

from typer.testing import CliRunner

from yazses.cli import app
from yazses.system.features import CATEGORY_ORDER, feature_status
from yazses.config import Config

runner = CliRunner()


def test_features_lists_category_headers() -> None:
    result = runner.invoke(app, ["features"])
    assert result.exit_code == 0
    # at least the core groups appear as headers
    for cat in ("Core dictation", "Accuracy & correction", "Multilingual"):
        assert cat in result.stdout


def test_features_shows_all_toggle_names() -> None:
    result = runner.invoke(app, ["features"])
    assert result.exit_code == 0
    for f in feature_status(Config()):
        if f.toggleable:
            assert f.slug in result.stdout, f"{f.slug} missing from grouped output"


def test_tier_filter_narrows_and_validates() -> None:
    ok = runner.invoke(app, ["features", "--tier", "rec"])
    assert ok.exit_code == 0
    assert "recommended" in ok.stdout

    bad = runner.invoke(app, ["features", "--tier", "nope"])
    assert bad.exit_code == 1


def test_category_filter_selects_one_group() -> None:
    result = runner.invoke(app, ["features", "--category", "multiling"])
    assert result.exit_code == 0
    assert "Multilingual" in result.stdout
    # a category from another group should not appear as a header
    assert "Accuracy & correction" not in result.stdout


def test_on_filter_shows_only_enabled() -> None:
    result = runner.invoke(app, ["features", "--on"])
    assert result.exit_code == 0
    assert "○ off" not in result.stdout
