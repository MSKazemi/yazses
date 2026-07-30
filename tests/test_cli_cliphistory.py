"""CLI exposure for the clipboard-history core (ADR-v2-060) — persistent store."""
from __future__ import annotations

import pytest
from typer.testing import CliRunner

from yazses import cli

runner = CliRunner()


@pytest.fixture()
def hist(tmp_path, monkeypatch):
    path = tmp_path / "cliphistory.json"
    monkeypatch.setattr(cli, "_cliphistory_path", lambda: path)
    return path


def test_add_list(hist):
    runner.invoke(cli.app, ["cliphistory", "add", "alpha"])
    runner.invoke(cli.app, ["cliphistory", "add", "beta"])
    out = runner.invoke(cli.app, ["cliphistory", "list"]).output
    # newest first
    assert out.index("beta") < out.index("alpha")


def test_recall_url_and_ordinal(hist):
    runner.invoke(cli.app, ["cliphistory", "add", "just some text"])
    runner.invoke(cli.app, ["cliphistory", "add", "https://example.com"])
    assert runner.invoke(cli.app, ["cliphistory", "recall", "the last url"]).output.strip() == "https://example.com"
    assert runner.invoke(cli.app, ["cliphistory", "recall", "the second one"]).output.strip() == "just some text"


def test_recall_no_match_exits_nonzero(hist):
    r = runner.invoke(cli.app, ["cliphistory", "recall", "anything"])
    assert r.exit_code == 1
    assert "no matching" in r.output.lower()


def test_add_empty_exits_nonzero(hist):
    r = runner.invoke(cli.app, ["cliphistory", "add"], input="\n")
    assert r.exit_code == 1


def test_add_reads_stdin(hist):
    runner.invoke(cli.app, ["cliphistory", "add"], input="piped value\n")
    assert runner.invoke(cli.app, ["cliphistory", "list"]).output.strip().endswith("piped value")
