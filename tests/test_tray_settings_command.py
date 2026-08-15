"""How the tray opens the settings window, on an install that has no `yazses`.

Reported from a live Windows install (2026-08-15, v2.21.0 era): clicking
**Settings…** in the tray produced a toast reading

    YazSes
    Could not open Settings — is `yazses` on PATH?

and nothing opened. Every tray backend — Linux, macOS and Windows — launched the
window with the literal argv ``["yazses", "settings"]``, which assumes a console
script on PATH. The PyInstaller bundle has no such thing: it ships `YazSesApp.exe`
and `yazses-cli.exe` side by side and puts neither on PATH, so the one build most
likely to be used by someone who has never seen a terminal was the one build where
the button could not work.

The codebase already knew the answer in another file: `settingsui/app.py::_run_restart`
runs `[sys.executable, "-m", "yazses.cli", …]` precisely so it does not depend on
PATH. This resolver is that knowledge, in one place, for the three backends that
were each getting it wrong separately.

Order matters and is asserted below:

1. **Frozen** → the sibling `yazses-cli` executable inside the bundle. `sys.executable`
   is the app itself there, so `-m` is meaningless: passing `-m yazses.cli` to
   `YazSesApp.exe` re-launches the GUI rather than running a command.
2. **`yazses` on PATH** → use it. Cheapest, and it is what a pipx/uv install gives.
3. **Otherwise** → `[sys.executable, "-m", "yazses.cli", "settings"]`, which works for
   any interpreter that can import the package, including a venv whose `bin/` was
   never added to PATH.
"""
from __future__ import annotations

import sys
from pathlib import Path

from yazses.tray.launch import settings_command


def test_a_frozen_bundle_uses_its_sibling_cli_not_dash_m() -> None:
    """`sys.executable` in a bundle is the app; `-m` would re-open the GUI."""
    exe = Path("C:/Program Files/YazSes/YazSesApp.exe")
    cmd = settings_command(frozen=True, executable=exe, which=lambda _: None, windows=True)
    assert cmd == [str(exe.with_name("yazses-cli.exe")), "settings"]


def test_the_frozen_sibling_is_extensionless_off_windows() -> None:
    """macOS ships the same layout without `.exe`; a hardcoded suffix misses it."""
    exe = Path("/Applications/YazSes.app/Contents/MacOS/YazSesApp")
    cmd = settings_command(frozen=True, executable=exe, which=lambda _: None, windows=False)
    assert cmd == ["/Applications/YazSes.app/Contents/MacOS/yazses-cli", "settings"]


def test_a_normal_install_prefers_the_console_script() -> None:
    cmd = settings_command(
        frozen=False, executable=Path(sys.executable), which=lambda n: f"/usr/bin/{n}"
    )
    assert cmd == ["/usr/bin/yazses", "settings"]


def test_without_a_console_script_it_falls_back_to_dash_m() -> None:
    """A venv whose bin/ is not on PATH still has an interpreter that can import us."""
    cmd = settings_command(frozen=False, executable=Path("/venv/bin/python"), which=lambda _: None)
    assert cmd == ["/venv/bin/python", "-m", "yazses.cli", "settings"]


def test_path_is_not_consulted_when_frozen() -> None:
    """A *different* yazses on PATH must not win over the bundle's own CLI.

    A machine can easily have both — the installer's app and an old pip install.
    Launching the wrong one silently opens a settings window for another version.
    """
    exe = Path("C:/Program Files/YazSes/YazSesApp.exe")
    cmd = settings_command(
        frozen=True, executable=exe, which=lambda n: "C:/Python311/Scripts/yazses.exe",
        windows=True,
    )
    assert cmd[0].endswith("yazses-cli.exe")


def test_the_subcommand_is_configurable() -> None:
    """`restart` needs the same resolution; only the verb differs."""
    cmd = settings_command(
        "restart", frozen=False, executable=Path("/venv/bin/python"), which=lambda _: None
    )
    assert cmd == ["/venv/bin/python", "-m", "yazses.cli", "restart"]


def test_the_real_call_returns_something_runnable() -> None:
    """No arguments: it must read the live process and still produce a command."""
    cmd = settings_command()
    assert cmd and all(isinstance(part, str) for part in cmd)
    assert cmd[-1] == "settings"
