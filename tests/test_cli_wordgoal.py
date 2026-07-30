"""CLI exposure for the word-goal tracker (ADR-v2-092) — persistent store."""
from __future__ import annotations

import pytest
from typer.testing import CliRunner

from yazses import cli

runner = CliRunner()


@pytest.fixture()
def state(tmp_path, monkeypatch):
    path = tmp_path / "wordgoal.json"
    monkeypatch.setattr(cli, "_wordgoal_path", lambda: path)
    return path


def test_add_accumulates_across_calls(state):
    runner.invoke(cli.app, ["wordgoal", "goal", "10"])
    runner.invoke(cli.app, ["wordgoal", "add", "one two three"])
    r = runner.invoke(cli.app, ["wordgoal", "add", "four five"])
    assert r.exit_code == 0, r.output
    assert "5 of 10 words — 5 to go." in r.output


def test_status_and_reset(state):
    runner.invoke(cli.app, ["wordgoal", "add", "a b c"])
    assert "3 words so far." in runner.invoke(cli.app, ["wordgoal", "status"]).output
    runner.invoke(cli.app, ["wordgoal", "reset"])
    assert "0 words so far." in runner.invoke(cli.app, ["wordgoal", "status"]).output


def test_goal_zero_clears(state):
    runner.invoke(cli.app, ["wordgoal", "add", "a b"])
    runner.invoke(cli.app, ["wordgoal", "goal", "0"])
    assert "2 words so far." in runner.invoke(cli.app, ["wordgoal", "status"]).output


def test_add_reads_stdin(state):
    r = runner.invoke(cli.app, ["wordgoal", "add"], input="alpha beta gamma delta\n")
    assert r.exit_code == 0, r.output
    assert "4 words so far." in r.output
