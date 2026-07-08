"""Author + contact branding is surfaced in the running app.

The `about` command, the top-level help epilog, and `yazses doctor` must all
point people at the author and where to report issues / request features. This
locks that contract so it can't silently regress across distribution channels.
"""
from __future__ import annotations

from typer.testing import CliRunner

import yazses.cli as cli
from yazses import branding

runner = CliRunner()
WIDE = {"COLUMNS": "220", "TERM": "dumb"}


def test_about_shows_author_email_and_links():
    r = runner.invoke(cli.app, ["about"], env=WIDE)
    assert r.exit_code == 0
    assert branding.AUTHOR in r.output
    assert branding.EMAIL in r.output
    assert branding.ISSUES in r.output
    assert branding.version() in r.output


def test_top_level_help_advertises_contact():
    r = runner.invoke(cli.app, ["-h"], env=WIDE)
    assert r.exit_code == 0
    assert "about" in r.output
    assert branding.AUTHOR in r.output


def test_contact_lines_are_well_formed():
    lines = branding.contact_lines()
    joined = "\n".join(lines)
    assert branding.AUTHOR in joined
    assert branding.EMAIL in joined
    assert branding.ISSUES in joined
    # Every line is a `label: value` pair.
    assert all(":" in line for line in lines)
