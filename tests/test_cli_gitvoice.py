"""CLI exposure for the Voice Git Choreographer core (ADR-v2-076, issue #37).

`plan.py` was already a pure, well-tested grammar with no way to reach it short of
importing the module directly. Here it is driven through the real `yazses gitvoice`
command, including the --run / --yes confirm gate for destructive commands.
"""
from __future__ import annotations

from typer.testing import CliRunner

from yazses import cli

runner = CliRunner()


def test_gitvoice_prints_argv_and_undo():
    r = runner.invoke(cli.app, ["gitvoice", "commit with message fix the parser"])
    assert r.exit_code == 0, r.output
    lines = r.output.splitlines()
    assert lines[0] == "git commit -m 'fix the parser'"
    assert lines[1] == "undo: git reset --soft HEAD~1"


def test_gitvoice_reads_stdin():
    r = runner.invoke(cli.app, ["gitvoice"], input="status\n")
    assert r.exit_code == 0, r.output
    assert r.output.splitlines()[0] == "git status"


def test_gitvoice_never_runs_without_run_flag(monkeypatch):
    import subprocess

    called = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: called.append(a))
    r = runner.invoke(cli.app, ["gitvoice", "push"])
    assert r.exit_code == 0, r.output
    assert not called


def test_gitvoice_unparseable_exits_nonzero():
    r = runner.invoke(cli.app, ["gitvoice", "make me a sandwich"])
    assert r.exit_code == 1
    assert "could not parse" in r.output.lower()


def test_gitvoice_destructive_refuses_run_without_yes(monkeypatch):
    import subprocess

    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a))
    r = runner.invoke(cli.app, ["gitvoice", "force push", "--run"])
    assert r.exit_code == 1
    assert "destructive" in r.output.lower()
    assert not calls


def test_gitvoice_destructive_runs_with_yes(monkeypatch):
    import subprocess

    calls = []

    class _Result:
        returncode = 0

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a) or _Result())
    r = runner.invoke(cli.app, ["gitvoice", "force push", "--run", "--yes"])
    assert r.exit_code == 0, r.output
    assert calls == [(["git", "push", "--force"],)]


def test_gitvoice_safe_command_runs_without_yes(monkeypatch):
    import subprocess

    calls = []

    class _Result:
        returncode = 0

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a) or _Result())
    r = runner.invoke(cli.app, ["gitvoice", "status", "--run"])
    assert r.exit_code == 0, r.output
    assert calls == [(["git", "status"],)]
