"""`yazses update` CLI: report, then upgrade unless --check (or refused)."""
from __future__ import annotations

from typer.testing import CliRunner

import yazses.cli as cli
from yazses.system.updater import UpdateStatus, UpgradeOutcome

runner = CliRunner()


def _fake_upgrade(ran, after=None):
    """Stand in for a real upgrade that actually moved the installed version."""

    def _run(status):
        ran.append(status)
        return UpgradeOutcome(
            code=0,
            before=status.current,
            after=after if after is not None else (status.latest or status.current),
            expected=status.latest,
            method=status.method,
            command=status.command,
        )

    return _run


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
    monkeypatch.setattr(cli, "run_upgrade_checked", _fake_upgrade(ran))
    result = runner.invoke(cli.app, ["update", "--check"])
    assert result.exit_code == 0
    assert "latest" in result.output.lower()
    assert ran == []  # nothing upgraded


def test_update_check_only_does_not_upgrade(monkeypatch):
    monkeypatch.setattr(cli, "check_update", lambda current: _status(True))
    ran = []
    monkeypatch.setattr(cli, "run_upgrade_checked", _fake_upgrade(ran))
    result = runner.invoke(cli.app, ["update", "--check"])
    assert result.exit_code == 0
    assert "0.5.0" in result.output
    assert "available" in result.output.lower()
    assert ran == []  # --check must never run the upgrade


def test_update_yes_runs_upgrade(monkeypatch):
    monkeypatch.setattr(cli, "check_update", lambda current: _status(True))
    ran = []
    monkeypatch.setattr(cli, "run_upgrade_checked", _fake_upgrade(ran))
    result = runner.invoke(cli.app, ["update", "--yes"])
    assert result.exit_code == 0
    assert len(ran) == 1  # upgrade was performed without prompting


def test_update_prompt_decline_skips_upgrade(monkeypatch):
    monkeypatch.setattr(cli, "check_update", lambda current: _status(True))
    ran = []
    monkeypatch.setattr(cli, "run_upgrade_checked", _fake_upgrade(ran))
    result = runner.invoke(cli.app, ["update"], input="n\n")
    assert result.exit_code == 0
    assert ran == []  # declined at the prompt


def test_update_in_help_panel(monkeypatch):
    out = runner.invoke(cli.app, ["update", "-h"], env={"COLUMNS": "220"}).output
    assert "Usage" in out
    assert "yazses update" in out  # example present


def test_a_blocked_check_explains_how_to_update_by_hand(monkeypatch):
    # The firewall case. `yazses update` used to print "Could not determine the
    # latest version" and stop, which tells someone behind a corporate proxy
    # nothing they can act on -- and implies YazSes itself is broken, when
    # dictation is entirely local and completely unaffected.
    from yazses.system.updater import offline_steps

    monkeypatch.setattr(
        cli, "check_update",
        lambda current: _status(
            False, latest=None, note="could not reach PyPI — offline, or a firewall",
            steps=offline_steps("pip"),
        ),
    )
    result = runner.invoke(cli.app, ["update"])
    assert result.exit_code == 1  # the check genuinely failed
    assert "keeps working" in result.output  # ...but YazSes did not
    assert "pip install --upgrade yazses" in result.output


def test_a_windows_installer_install_prints_steps_and_succeeds(monkeypatch):
    # There is no command to run -- the upgrade is a downloaded .exe. Printing the
    # exact steps is doing the job, so it is not an error.
    from yazses.system.updater import manual_update_steps

    monkeypatch.setattr(
        cli, "check_update",
        lambda current: _status(
            True, method="windows-installer", command=None,
            steps=manual_update_steps("windows-installer"),
        ),
    )
    # Patches `run_upgrade_checked`, not `run_upgrade`: this test was written
    # against the older API and the two landed independently — the verified-upgrade
    # rework on main, the Windows channels on a branch. The assertion is unchanged
    # and is the one that matters, that nothing is shelled out to at all.
    ran = []
    monkeypatch.setattr(cli, "run_upgrade_checked", _fake_upgrade(ran))
    result = runner.invoke(cli.app, ["update"])
    assert result.exit_code == 0
    assert "releases" in result.output
    assert "winget upgrade" in result.output
    assert ran == []  # nothing to shell out to; it must not try


def test_update_without_a_known_upgrade_command_explains_instead_of_crashing(monkeypatch):
    # upgrade_command() returns None for any install method it has no recipe for.
    # detect_install_method() only yields snap/uv/pipx/pip today, so this is not
    # reachable in production -- but it is one `apt` branch away from being, and
    # `" ".join(None)` would raise TypeError instead of telling the user anything.
    monkeypatch.setattr(
        cli, "check_update", lambda current: _status(True, method="apt", command=None)
    )
    ran = []
    monkeypatch.setattr(cli, "run_upgrade_checked", _fake_upgrade(ran))
    result = runner.invoke(cli.app, ["update"])
    assert result.exit_code == 1
    assert not isinstance(result.exception, TypeError)
    assert "apt" in result.output
    assert "no automatic upgrade" in result.output.lower()
    assert ran == []  # must not attempt an upgrade it has no command for


def test_update_does_not_claim_success_when_the_version_did_not_move(monkeypatch):
    """`uv tool upgrade` exits 0 and does nothing when the install is version-pinned.

    Reported from a real machine: the tray said the update was installed, the daemon
    was restarted, and it came back on the same version — with the package manager's
    own "Nothing to upgrade" scrolled off above. Exit status is not evidence.
    """
    monkeypatch.setattr(
        cli, "check_update", lambda current: _status(True, method="uv",
                                                     command=["uv", "tool", "upgrade", "yazses"])
    )
    ran = []
    # Exit 0, but the installed version is exactly what it was.
    monkeypatch.setattr(cli, "run_upgrade_checked", _fake_upgrade(ran, after="0.4.1"))

    result = runner.invoke(cli.app, ["update", "--yes"])

    assert len(ran) == 1
    assert result.exit_code == 1, "a no-op upgrade must not exit 0"
    assert "still 0.4.1" in result.output
    assert "Updated to" not in result.output
    assert "uv tool install" in result.output  # the way out of the pin


def test_update_says_so_when_the_new_version_cannot_be_confirmed(monkeypatch):
    monkeypatch.setattr(cli, "check_update", lambda current: _status(True))
    ran = []
    monkeypatch.setattr(cli, "run_upgrade_checked", _fake_upgrade(ran, after=""))

    def _unreadable(status):
        ran.append(status)
        return UpgradeOutcome(code=0, before=status.current, after=None,
                              expected=status.latest, method=status.method,
                              command=status.command)

    monkeypatch.setattr(cli, "run_upgrade_checked", _unreadable)
    result = runner.invoke(cli.app, ["update", "--yes"])

    assert result.exit_code == 1
    assert "could not be read" in result.output
    assert "Updated to" not in result.output
