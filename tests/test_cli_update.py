"""`yazses update` CLI: report, then upgrade unless --check (or refused)."""
from __future__ import annotations

from typer.testing import CliRunner

import yazses.cli as cli
from yazses.system.updater import UpdateStatus

runner = CliRunner()


def _status(available, **kw):
    base = dict(
        method="pip", current="0.4.1", latest="0.5.0" if available else "0.4.1",
        available=available, command=["pip", "install", "--upgrade", "yazses"] if available else None,
        note="",
    )
    base.update(kw)
    return UpdateStatus(**base)


def test_update_reports_when_up_to_date(monkeypatch):
    monkeypatch.setattr(cli, "check_update", lambda current: _status(False))
    ran = []
    monkeypatch.setattr(cli, "run_upgrade", lambda st: ran.append(st) or 0)
    result = runner.invoke(cli.app, ["update", "--check"])
    assert result.exit_code == 0
    assert "latest" in result.output.lower()
    assert ran == []  # nothing upgraded


def test_update_check_only_does_not_upgrade(monkeypatch):
    monkeypatch.setattr(cli, "check_update", lambda current: _status(True))
    ran = []
    monkeypatch.setattr(cli, "run_upgrade", lambda st: ran.append(st) or 0)
    result = runner.invoke(cli.app, ["update", "--check"])
    assert result.exit_code == 0
    assert "0.5.0" in result.output
    assert "available" in result.output.lower()
    assert ran == []  # --check must never run the upgrade


def test_update_yes_runs_upgrade(monkeypatch):
    monkeypatch.setattr(cli, "check_update", lambda current: _status(True))
    ran = []
    monkeypatch.setattr(cli, "run_upgrade", lambda st: ran.append(st) or 0)
    result = runner.invoke(cli.app, ["update", "--yes"])
    assert result.exit_code == 0
    assert len(ran) == 1  # upgrade was performed without prompting


def test_update_prompt_decline_skips_upgrade(monkeypatch):
    monkeypatch.setattr(cli, "check_update", lambda current: _status(True))
    ran = []
    monkeypatch.setattr(cli, "run_upgrade", lambda st: ran.append(st) or 0)
    result = runner.invoke(cli.app, ["update"], input="n\n")
    assert result.exit_code == 0
    assert ran == []  # declined at the prompt


def test_update_in_help_panel(monkeypatch):
    out = runner.invoke(cli.app, ["update", "-h"], env={"COLUMNS": "220"}).output
    assert "Usage" in out
    assert "yazses update" in out  # example present


def test_update_without_a_known_upgrade_command_explains_instead_of_crashing(monkeypatch):
    # upgrade_command() returns None for any install method it has no recipe for.
    # detect_install_method() only yields snap/uv/pipx/pip today, so this is not
    # reachable in production -- but it is one `apt` branch away from being, and
    # `" ".join(None)` would raise TypeError instead of telling the user anything.
    monkeypatch.setattr(
        cli, "check_update", lambda current: _status(True, method="apt", command=None)
    )
    ran = []
    monkeypatch.setattr(cli, "run_upgrade", lambda st: ran.append(st) or 0)
    result = runner.invoke(cli.app, ["update"])
    assert result.exit_code == 1
    assert not isinstance(result.exception, TypeError)
    assert "apt" in result.output
    assert "no automatic upgrade" in result.output.lower()
    assert ran == []  # must not attempt an upgrade it has no command for
