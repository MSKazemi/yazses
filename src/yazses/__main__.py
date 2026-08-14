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
ships two: a windowed ``YazSesApp.exe`` (tray/daemon, no console) and a console
``yazses-cli.exe`` behind a ``yazses`` shim. A GUI-subsystem binary has no
stdout to write to, so the CLI has to be reachable through the console one or
``yazses doctor`` prints nothing at all.

Whenever this entry point routes to the CLI it first calls
``wincon.ensure_streams()``. That is the safety net for a CLI command that
reaches the windowed binary despite the shim — it borrows the launching
terminal's console if there is one, and otherwise guarantees the std streams are
at least not ``None``. Without it, ``sys.stdout.isatty()`` anywhere downstream
raises ``AttributeError`` and Windows renders it as an "Unhandled exception in
script" dialog rather than an error message.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Executables whose bare invocation means "run the CLI" rather than "run the
# tray". Matched on the argv[0] stem, so YazSesApp.exe and yazses-cli.exe stay
# distinguishable on a case-insensitive filesystem.
_CLI_SUFFIX = "-cli"


def _run_cli(args: list[str]) -> None:
    """Dispatch to the Typer CLI, with printable streams guaranteed first."""
    from yazses.system.wincon import ensure_streams

    ensure_streams()

    from yazses.cli import app

    sys.argv = [sys.argv[0]] + args
    app()


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
        _run_cli(args[1:])
    else:
        # No mode flag → default to CLI (matches the pip-installed `yazses` script).
        # `YazSesApp.exe doctor` lands here too, which is why _run_cli fixes up
        # the std streams before Typer touches them.
        _run_cli(args)


if __name__ == "__main__":
    main()
