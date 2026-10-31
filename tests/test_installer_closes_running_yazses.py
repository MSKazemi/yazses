"""The Windows installer closes a running YazSes itself, in the right order.

``CloseApplications=yes`` alone does not work for YazSes: it is a tray process plus a
windowless ``--daemon`` child, the Restart Manager has no main window to ask, and Setup
stops with "unable to automatically close all applications" (run silently: exit code 5,
nothing installed). Reproduced on Windows 11 by upgrading over a running tray with the
switches the in-app updater uses. Only the one-click update was spared, because it waits
for YazSes to exit before starting the installer; a manual run, `winget upgrade`,
`choco upgrade`, `scoop update`, and anyone updating *from* a release older than the
one-click update all hit it.

The behaviour lives in Pascal that only a Windows runner compiles, so these pin the parts
of the script that matter and that a tidy-up could quietly undo.
"""

from __future__ import annotations

import re
from pathlib import Path

ISS = (Path(__file__).resolve().parents[1] / "packaging" / "windows" / "installer.iss").read_text(
    encoding="utf-8"
)
CODE = ISS.split("[Code]", 1)[1]


def _block(name: str) -> str:
    """The body of one top-level routine in [Code], up to the next top-level one."""
    start = re.search(rf"^(?:function|procedure) {name}\b", CODE, flags=re.M)
    assert start, f"{name} is gone from installer.iss"
    rest = CODE[start.end():]
    end = re.search(r"^(?:function|procedure) \w+", rest, flags=re.M)
    return rest[: end.start()] if end else rest


def test_setup_stops_yazses_before_it_looks_for_files_in_use() -> None:
    body = _block("PrepareToInstall")
    assert "StopRunningYazSes" in body
    # Never blocks the install: the Restart Manager stays the backstop, and a refusal to
    # install belongs to it (a daemon that will not stop), not to our best-effort step.
    assert "Result := ''" in body


def test_the_tray_goes_first_and_the_daemon_is_asked_not_killed() -> None:
    body = _block("StopRunningYazSes")
    tray = body.index("Stop-Process")
    daemon = body.index("'stop'")
    # A live tray relaunches the daemon the moment it disappears, so it must be gone first.
    assert tray < daemon
    # The daemon is stopped through its own shutdown, which saves a meeting in progress.
    assert "yazses-cli.exe" in body[daemon - 80:daemon + 20]
    # Nothing here is a blanket kill of the daemon.
    assert "taskkill" not in body.lower()
    assert body.count("Stop-Process") == 1


def test_only_this_installs_own_processes_are_touched() -> None:
    body = _block("StopRunningYazSes")
    assert "ExpandConstant('{app}')" in body
    assert "StartsWith($d" in body and "OrdinalIgnoreCase" in body
    assert "--tray" in body


def test_the_powershell_text_survives_being_one_quoted_argument() -> None:
    """The script travels inside ``-Command "..."``; a double quote in it would end that
    argument early and silently turn the whole step into a no-op."""
    script = _block("StopRunningYazSes").split("Script :=", 1)[1].split("if Exec(", 1)[0]
    assert '"' not in script
    # A path with an apostrophe (a user called O'Brien) must not break the single quotes.
    assert "''''" in _block("PsQuote") and "StringChangeEx" in _block("PsQuote")


def test_a_silent_upgrade_brings_back_only_a_tray_it_closed() -> None:
    body = _block("CurStepChanged")
    # The in-app update passes /NORESTARTAPPLICATIONS and relaunches itself: a second
    # launch here would be two trays.
    assert "/NORESTARTAPPLICATIONS" in _block("RestartApplicationsRefused")
    for needle in ("TrayWasRunning", "WizardSilent", "not RestartApplicationsRefused"):
        assert needle in body
    # Never as the elevated user of an all-users install: ADR-027 keeps the tray unelevated.
    assert "ExecAsOriginalUser" in body
    assert "ssDone" in body


def test_nothing_force_closes() -> None:
    """Force-closing is the one thing the update path deliberately never does: it could
    destroy the work of a daemon still saving a meeting."""
    assert "CloseApplications=force" not in ISS
    assert "/FORCECLOSEAPPLICATIONS" not in ISS


def test_a_refused_stop_brings_the_tray_back_before_the_install_fails() -> None:
    """`yazses stop` refuses while a meeting is being written up. The Restart Manager then
    fails the install, so CurStepChanged never reaches ssDone: without this, the tray
    closed a moment earlier would stay closed and the user keeps a daemon with no tray."""
    after = _block("StopRunningYazSes").split("'stop'", 1)[1]
    assert "--daemon" in after
    assert "ExecAsOriginalUser" in after and "'--tray'" in after
    # Brought back here, so CurStepChanged must not start a second one.
    assert "Result := False" in after
    survivors = after.split("Survivors :=", 1)[1].split("if Exec(", 1)[0]
    assert '"' not in survivors
