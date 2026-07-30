"""CLI exposure for the spaced-repetition capture core (ADR-v2-112) — persistent deck."""
from __future__ import annotations

import pytest
from typer.testing import CliRunner

from yazses import cli

runner = CliRunner()


@pytest.fixture()
def deck(tmp_path, monkeypatch):
    path = tmp_path / "srscap.json"
    monkeypatch.setattr(cli, "_srs_path", lambda: path)
    return path


def test_capture_then_list(deck):
    r = runner.invoke(cli.app, ["srs", "capture", "remember that the capital of France is Paris"])
    assert r.exit_code == 0, r.output
    assert "c1::Paris" in r.output
    out = runner.invoke(cli.app, ["srs", "list"]).output
    assert "Paris" in out and "interval 0d" in out


def test_capture_no_fact_exits_nonzero(deck):
    r = runner.invoke(cli.app, ["srs", "capture", "just chatting about the weather"])
    assert r.exit_code == 1
    assert "no fact detected" in r.output.lower()


def test_review_updates_schedule(deck):
    runner.invoke(cli.app, ["srs", "capture", "remember that pi is 3.14159"])
    r = runner.invoke(cli.app, ["srs", "review", "1", "--grade", "5"])
    assert r.exit_code == 0, r.output
    assert "review again in 1 day" in r.output
    assert "interval 1d" in runner.invoke(cli.app, ["srs", "list"]).output


def test_review_bad_index(deck):
    r = runner.invoke(cli.app, ["srs", "review", "9", "--grade", "5"])
    assert r.exit_code == 1
    assert "could not review" in r.output.lower()


def test_capture_reads_stdin(deck):
    r = runner.invoke(cli.app, ["srs", "capture"],
                      input="remember that the boiling point of water is 100 degrees\n")
    assert r.exit_code == 0, r.output
    assert "100 degrees" in r.output
