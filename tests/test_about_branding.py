"""The `yazses about` banner: ASCII wordmark on a TTY, plain fallback otherwise."""
from __future__ import annotations

from typer.testing import CliRunner

from yazses import branding
from yazses.cli import app

runner = CliRunner()


def test_banner_art_contains_name_and_version() -> None:
    out = branding.banner(force=True)
    assert branding.APP_NAME in out
    assert branding.version() in out
    assert branding.TAGLINE in out
    # the ASCII art block is present
    assert branding.BANNER_ART.splitlines()[-1] in out


def test_banner_plain_fallback_has_no_art() -> None:
    out = branding.banner(force=False)
    assert branding.APP_NAME in out
    assert branding.version() in out
    # no multi-line ASCII art in the plain form
    assert branding.BANNER_ART not in out
    assert out.count("\n") == 0


def test_no_color_env_disables_art(monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    assert branding._supports_banner() is False


def test_about_command_shows_branding_and_contact() -> None:
    result = runner.invoke(app, ["about"])
    assert result.exit_code == 0
    assert branding.APP_NAME in result.stdout
    assert branding.AUTHOR in result.stdout
    assert branding.ISSUES in result.stdout
