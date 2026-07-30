"""CLI exposure for the find/replace (ADR-v2-068) and key-chord (ADR-v2-085) cores.

Built + tested pure cores with no runtime entry point; here they are driven through the
real `yazses findreplace` / `yazses chords` commands.
"""
from __future__ import annotations

from typer.testing import CliRunner

from yazses import cli

runner = CliRunner()


# ---- yazses findreplace -----------------------------------------------------

def test_findreplace_applies_to_in_option():
    r = runner.invoke(cli.app, ["findreplace", "replace every cat with dog", "--in", "the cat sat"])
    assert r.exit_code == 0, r.output
    assert r.output.strip() == "the dog sat"


def test_findreplace_first_only():
    r = runner.invoke(cli.app, ["findreplace", "replace first foo with bar"], input="foo foo foo\n")
    assert r.exit_code == 0, r.output
    assert r.output.strip() == "bar foo foo"


def test_findreplace_unparseable_exits_nonzero():
    r = runner.invoke(cli.app, ["findreplace", "hello world", "--in", "x"])
    assert r.exit_code == 1
    assert "could not parse" in r.output.lower()


# ---- yazses chords ----------------------------------------------------------

def test_chords_modifier_combo():
    r = runner.invoke(cli.app, ["chords", "press control shift P"])
    assert r.exit_code == 0, r.output
    assert r.output.strip() == "ctrl+shift+p"


def test_chords_repeat_one_per_line():
    r = runner.invoke(cli.app, ["chords", "escape twice"])
    assert r.exit_code == 0, r.output
    assert [ln for ln in r.output.splitlines() if ln.strip()] == ["Escape", "Escape"]


def test_chords_reads_stdin():
    r = runner.invoke(cli.app, ["chords"], input="hit F5\n")
    assert r.exit_code == 0, r.output
    assert r.output.strip() == "F5"


def test_chords_unparseable_exits_nonzero():
    r = runner.invoke(cli.app, ["chords", "just some words here"])
    assert r.exit_code == 1
    assert "could not parse" in r.output.lower()
