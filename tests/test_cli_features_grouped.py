"""`yazses features` clusters capabilities into categories and supports filters."""
from __future__ import annotations

from typer.testing import CliRunner

from yazses.cli import app
from yazses.config import Config
from yazses.system.features import feature_status

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


def test_the_catalogue_prices_what_it_offers() -> None:
    """A 3 GB feature must say so where it is chosen, not where it is paid for.

    Before this, the only place a size appeared was `features enable`, at the
    moment the download began.
    """
    result = runner.invoke(app, ["features"])
    assert result.exit_code == 0
    assert "DOWNLOAD" in result.stdout
    # cocktail resolves to speechbrain -> torch -> the CUDA stack.
    row = next(ln for ln in result.stdout.splitlines() if " cocktail " in ln)
    assert "GB" in row, row


def test_a_pure_logic_feature_is_not_priced() -> None:
    """`reflow` downloads nothing; a size against it would be a lie."""
    result = runner.invoke(app, ["features"])
    row = next(ln for ln in result.stdout.splitlines() if " reflow " in ln)
    assert "MB" not in row and "GB" not in row, row


def test_the_size_column_width_matches_what_labels_are_sized_against() -> None:
    """Two constants, two files: drift shifts every ADVICE cell right."""
    from yazses import cli
    from yazses.system import depsize

    assert cli._SIZE_W == depsize.SIZE_COLUMN_WIDTH
