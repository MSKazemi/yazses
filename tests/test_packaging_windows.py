"""Contract tests for the Windows bundle.

The Windows installer is assembled from three files that have to agree with each
other and with the Python entry point, and nothing in the normal test run
touches them — they are only exercised when a tag build runs on a Windows
runner. Every mismatch below has already shipped at least once:

- the bundle spawned the daemon with argv the bundle itself rejects,
- the CLI was built into a windowed binary that cannot print,
- the installer's autostart string diverged from the one the app writes.

These assert the contract on Linux CI, where the whole suite actually runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yazses.__main__ import default_mode
from yazses.platform.windows.lifecycle import resolve_tray_command

_PKG = Path(__file__).resolve().parents[1] / "packaging" / "windows"
_SPEC = _PKG / "yazses.spec"
_ISS = _PKG / "installer.iss"
_CMD = _PKG / "yazses.cmd"


# ---- Entry-point dispatch ----------------------------------------------


@pytest.mark.parametrize(
    "argv0",
    [
        r"C:\Program Files\YazSes\yazses-cli.exe",
        "yazses-cli.exe",
        "/usr/local/bin/yazses-cli",
    ],
)
def test_cli_binary_defaults_to_the_cli(argv0):
    assert default_mode(argv0) == "--cli"


@pytest.mark.parametrize(
    "argv0",
    [
        r"C:\Program Files\YazSes\YazSes.exe",
        "YazSes.exe",
        "yazses.exe",  # case-insensitive filesystems fold this onto YazSes.exe
    ],
)
def test_windowed_binary_defaults_to_the_tray(argv0):
    assert default_mode(argv0) == "--tray"


def test_the_two_bundle_binaries_do_not_share_a_default_mode():
    """They differ only in case and suffix; if both defaulted the same way, one
    of the two shipped binaries would be unreachable."""
    assert default_mode("YazSes.exe") != default_mode("yazses-cli.exe")


# ---- Bundle contents ---------------------------------------------------


def test_spec_builds_both_a_windowed_and_a_console_binary():
    spec = _SPEC.read_text(encoding="utf-8")
    assert "console=False" in spec, "windowed tray/daemon binary is missing"
    assert "console=True" in spec, (
        "no console binary: a GUI-subsystem exe has no stdout, so every "
        "diagnostic command would print nothing"
    )
    assert 'name="yazses-cli"' in spec


def test_both_binaries_are_collected_into_the_bundle():
    spec = _SPEC.read_text(encoding="utf-8")
    collect = spec[spec.index("COLLECT(") :]
    assert "exe," in collect and "cli_exe," in collect, (
        "a binary was built but not COLLECTed, so it never reaches the installer"
    )


def test_shim_forwards_to_the_cli_binary_relative_to_itself():
    cmd = _CMD.read_text(encoding="utf-8")
    assert "yazses-cli.exe" in cmd
    assert "%~dp0" in cmd, "an absolute path would break for non-default install dirs"
    assert "%*" in cmd, "arguments must be forwarded"


def test_installer_ships_the_shim():
    iss = _ISS.read_text(encoding="utf-8")
    assert "yazses.cmd" in iss


# ---- Installer / app agreement -----------------------------------------


def test_installer_autostart_matches_what_the_app_writes():
    """installer.iss and WindowsLifecycle manage the same HKCU\\Run value. If
    they disagree, toggling autostart in-app silently rewrites the installer's
    entry into something else."""
    iss = _ISS.read_text(encoding="utf-8")
    assert '""{app}\\{#MyAppExeName}"" --tray' in iss

    app_side = resolve_tray_command(r"C:\X\YazSes.exe", frozen=True, tray_script=None)
    assert app_side == r'"C:\X\YazSes.exe" --tray'


def test_installer_does_not_delete_the_whole_user_path_on_uninstall():
    """`uninsdeletevalue` on the Path value would wipe the user's entire PATH.
    Removal must go through the surgical RemovePath procedure instead."""
    iss = _ISS.read_text(encoding="utf-8")
    path_entry = next(
        line for line in iss.splitlines() if 'ValueName: "Path"' in line
    )
    assert "uninsdeletevalue" not in path_entry
    assert "procedure RemovePath" in iss
    assert "CurUninstallStepChanged" in iss


def test_installer_guards_against_duplicate_path_entries():
    iss = _ISS.read_text(encoding="utf-8")
    assert "NeedsAddPath" in iss
    assert "ChangesEnvironment=yes" in iss, (
        "without this, open shells never see the new PATH"
    )


def test_uninstall_stops_the_daemon_through_the_console_binary():
    iss = _ISS.read_text(encoding="utf-8")
    assert "yazses-cli.exe" in iss
