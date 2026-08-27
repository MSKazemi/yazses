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
- ``--overlay`` → run the voice-activity overlay (the daemon launches it)

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


def interpreter_reentry(args: list[str]) -> str | None:
    """Return the ``-c`` program CPython is asking this binary to run, else None.

    Pure, so the parsing is testable without freezing anything.

    **Why a frozen app has to answer this at all.** In a PyInstaller bundle
    ``sys.executable`` is the bundle, not a Python interpreter — and parts of the
    standard library relaunch ``sys.executable`` on the assumption that it *is*
    one. ``multiprocessing.resource_tracker`` builds exactly this::

        [sys.executable, *util._args_from_interpreter_flags(), "-c",
         "from multiprocessing.resource_tracker import main;main(<fd>)"]

    PyInstaller's bootloader sets ``dont_write_bytecode``, so the flags are
    ``["-B"]`` and the child re-enters :func:`main` with
    ``["-B", "-c", "from multiprocessing..."]``. With no branch for it that falls
    through to the Typer CLI, which reports *"No such option: -B"*, exits, and
    takes the resource tracker with it — after which Python prints
    *"resource_tracker: process died unexpectedly … Some resources might leak"*
    and relaunches it, and the whole thing repeats for every tracked resource.

    Observed on the first successful end-to-end macOS run
    ([#182](https://github.com/MSKazemi/yazses/issues/182)): the dictation chain
    itself was green — captured, heard, cleaned — and every command was framed by
    that error, which reads as a broken CLI rather than a leaked semaphore.

    Only the interpreter's own leading short flags are skipped. Anything that is
    not a flag, and any ``--long`` option, means this is a real YazSes invocation
    and is left alone — ``yazses transcribe -v file.wav`` must not be mistaken for
    an interpreter re-entry.
    """
    for i, arg in enumerate(args):
        if arg == "-c":
            return args[i + 1] if i + 1 < len(args) else None
        # `_args_from_interpreter_flags` emits only single-token short flags
        # (`-B`, `-E`, `-s`, `-Wignore`, `-Xdev`); none takes a separate value.
        if arg.startswith("-") and not arg.startswith("--") and len(arg) > 1:
            continue
        return None
    return None


def _handle_interpreter_reentry() -> bool:
    """Serve a stdlib relaunch of this binary, and say whether one was served.

    Gated on ``sys.frozen``. A pip-installed ``yazses`` is launched through a
    console script and never receives these argv shapes, so outside a bundle the
    same input should stay what it has always been: a CLI usage error. Executing
    it there would turn a typo into arbitrary code.

    ``freeze_support()`` covers the *other* relaunch shape,
    ``--multiprocessing-fork`` (a spawned child process). It is a no-op except in
    that exact case, so calling it unconditionally-when-frozen is safe.
    """
    if not getattr(sys, "frozen", False):
        return False

    import multiprocessing

    multiprocessing.freeze_support()

    code = interpreter_reentry(sys.argv[1:])
    if code is None:
        return False
    # Match `python -c`: argv[0] is "-c" and the program runs as __main__.
    sys.argv = ["-c"]
    exec(compile(code, "<multiprocessing>", "exec"), {"__name__": "__main__"})
    return True


def _run_cli(args: list[str]) -> None:
    """Dispatch to the Typer CLI exactly the way the console script does.

    Through ``cli.main`` and **not** ``cli.app``. The two are not the same entry:
    ``main`` is what ``pyproject.toml`` binds ``yazses`` to, and everything it does
    before handing over to Typer was silently absent from every bundled ``.exe`` and
    ``.app`` while this called ``app()`` directly --

    * ``ensure_printable_streams()`` -- a redirected stdout on Windows is cp1252,
      which cannot encode the arrow, the warning sign or the box rule this CLI prints
      everywhere. `yazses doctor` from the Scoop-installed v2.32.0 binary died with
      ``UnicodeEncodeError: 'charmap' codec can't encode character '\u2717'`` after
      printing most of its report;
    * ``escape_help_sections(app)`` -- Rich reads ``[meeting]`` in a help string as a
      style tag and drops it, so twelve commands named a config key without its
      section;
    * the ``UnsupportedPlatformError`` handler, which turns "no backend for this OS"
      into a sentence instead of a traceback.

    ``ensure_streams()`` still runs first and separately: it answers "is there a
    stream at all", which the windowed binary can fail before anything is printable.
    """
    from yazses.system.wincon import ensure_streams

    ensure_streams()

    from yazses.cli import main as run_cli

    sys.argv = [sys.argv[0]] + args
    run_cli()


def default_mode(argv0: str) -> str:
    """The mode to use when no explicit ``--daemon/--tray/--cli`` flag is given."""
    stem = Path(argv0).stem.lower()
    return "--cli" if stem.endswith(_CLI_SUFFIX) else "--tray"


def main() -> None:
    # Before anything reads argv as a YazSes command: the stdlib relaunches
    # `sys.executable`, which in a bundle is this binary. See
    # `interpreter_reentry`.
    if _handle_interpreter_reentry():
        return

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
    elif mode == "--overlay":
        # The daemon launches the voice-activity overlay as its own process. Without
        # a branch here there was no argv the bundle would accept for it at all, so
        # the overlay was unreachable from a .app or .exe by construction -- the
        # daemon's launch fell through to the CLI, exited 2, and had no console to
        # say so.
        from yazses.overlay.app import run as run_overlay

        sys.argv = [sys.argv[0]] + args[1:]
        run_overlay()
    elif mode == "--cli":
        _run_cli(args[1:])
    else:
        # No mode flag → default to CLI (matches the pip-installed `yazses` script).
        # `YazSesApp.exe doctor` lands here too, which is why _run_cli fixes up
        # the std streams before Typer touches them.
        _run_cli(args)


if __name__ == "__main__":
    main()
