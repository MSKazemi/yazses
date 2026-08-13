"""Mode-dispatched entry point for a single PyInstaller binary.

Bundled binaries on macOS / Windows ship as a single executable so the .app /
.exe can run as the tray (default), the daemon, or the CLI depending on argv.
Pip-installed users keep using the dedicated console scripts (``yazses``,
``yazses-daemon``, ``yazses-tray``).

Modes:
- ``--daemon``  → run the dictation daemon
- ``--tray``    → run the tray application (also the default if no args)
- ``--cli``     → run the Typer CLI; remaining args pass through to it
- ``--settings``→ open the graphical settings window (the Start-menu
  shortcut and the tray's "Settings…" entry both use this)

The default mode depends on which executable was launched. The Windows bundle
ships two: a windowed ``YazSes.exe`` (tray/daemon, no console) and a console
``yazses-cli.exe`` behind a ``yazses`` shim. A GUI-subsystem binary has no
stdout to write to, so the CLI has to be reachable through the console one or
``yazses doctor`` prints nothing at all.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Executables whose bare invocation means "run the CLI" rather than "run the
# tray". Matched on the argv[0] stem, so YazSes.exe and yazses-cli.exe stay
# distinguishable on a case-insensitive filesystem.
_CLI_SUFFIX = "-cli"


def default_mode(argv0: str) -> str:
    """The mode to use when no explicit ``--daemon/--tray/--cli`` flag is given."""
    stem = Path(argv0).stem.lower()
    return "--cli" if stem.endswith(_CLI_SUFFIX) else "--tray"


def main() -> None:
    args = sys.argv[1:]
    mode = args[0] if args else default_mode(sys.argv[0])

    if mode == "--daemon":
        from yazses.main import run as run_daemon

        sys.argv = [sys.argv[0]] + args[1:]
        run_daemon()
    elif mode == "--tray":
        from yazses.tray.app import run as run_tray

        sys.argv = [sys.argv[0]] + args[1:]
        run_tray()
    elif mode == "--settings":
        # The Start-menu shortcut and the tray's "Settings…" both launch the
        # bundle with this flag. Without a branch here the windowed binary would
        # fall through to the CLI, exit 2 on an unknown argument, and — having no
        # console to print to — look like a shortcut that does nothing at all.
        from yazses.settingsui.app import run as run_settings

        sys.argv = [sys.argv[0]] + args[1:]
        run_settings()
    elif mode == "--cli":
        from yazses.cli import app

        sys.argv = [sys.argv[0]] + args[1:]
        app()
    else:
        # No mode flag → default to CLI (matches the pip-installed `yazses` script).
        from yazses.cli import app

        app()


if __name__ == "__main__":
    main()
