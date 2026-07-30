"""CLI exposure for the outline core (ADR-v2-124) — persistent incremental builder."""
from __future__ import annotations

import pytest
from typer.testing import CliRunner

from yazses import cli

runner = CliRunner()


@pytest.fixture()
def outline(tmp_path, monkeypatch):
    path = tmp_path / "outline.json"
    monkeypatch.setattr(cli, "_outline_path", lambda: path)
    return path


def test_build_nested_outline_across_calls(outline):
    runner.invoke(cli.app, ["outline", "add", "Chapter 1"])
    runner.invoke(cli.app, ["outline", "add", "Section A"])
    runner.invoke(cli.app, ["outline", "indent"])
    r = runner.invoke(cli.app, ["outline", "render"])
    assert r.exit_code == 0, r.output
    assert r.output.rstrip() == "- Chapter 1\n  - Section A"


def test_promote_and_opml(outline):
    runner.invoke(cli.app, ["outline", "add", "A"])
    runner.invoke(cli.app, ["outline", "add", "B"])
    runner.invoke(cli.app, ["outline", "indent"])
    runner.invoke(cli.app, ["outline", "promote"])  # B back to level 0
    r = runner.invoke(cli.app, ["outline", "render", "--format", "opml"])
    assert r.exit_code == 0, r.output
    assert '<outline text="A">' in r.output and '<outline text="B">' in r.output


def test_clear(outline):
    runner.invoke(cli.app, ["outline", "add", "Something"])
    runner.invoke(cli.app, ["outline", "clear"])
    r = runner.invoke(cli.app, ["outline", "render"])
    assert "(empty outline)" in r.output


def test_add_echoes_current_outline(outline):
    r = runner.invoke(cli.app, ["outline", "add", "Top"])
    assert r.exit_code == 0, r.output
    assert "- Top" in r.output
