"""How YazSes starts another part of itself.

Every component that spawns another one -- the daemon launching the tray and the
overlay, the tray opening Settings, the Settings window restarting the daemon, the
lifecycle backends starting the daemon -- has to answer the same question: *what is
the command that runs `<this component>` on **this** install?*

Six call sites answered it independently with ``[sys.executable, "-m", "yazses.x"]``,
and in the shipped macOS/Windows bundles that answer is wrong in a way that produces
no error at all.

**Why it fails silently.** In a PyInstaller bundle ``sys.executable`` is the *app*,
not an interpreter. The bundle is one multi-call binary that dispatches on argv
(``__main__.py``: ``--daemon`` / ``--tray`` / ``--settings`` / ``--cli``), and an
unrecognised first argument falls through to the CLI. So ``YazSesApp.exe -m
yazses.tray.app`` reaches Typer as the flag ``-m``, which exits 2 -- and the windowed
binary has no console to print that to. The tray never appears, the overlay never
appears, Apply→Restart never restarts, and nothing anywhere reports a problem.

That is the same defect already fixed once in ``tray/launch.py`` for the Settings
button. This module is that fix generalised, so the next component to spawn a sibling
inherits the right answer instead of re-deriving the wrong one. The codebase knew
this in one file and got it wrong in six others; a shared seam is the only thing that
stops the seventh.

**The order of preference, and why.**

1. **A frozen bundle** -> the bundle itself, with its mode flag. Windows ships a
   separate console ``yazses-cli.exe`` beside the windowed binary, and CLI work is
   routed through it when it is there, because a GUI-subsystem binary has no stdout.
   Its presence is *tested*, not assumed from the platform: the macOS ``.app`` ships
   exactly one executable, so naming a sibling there points at a file that does not
   exist. PATH is deliberately not consulted first -- a machine can carry both the
   installer's app and a stray old ``pip install``, and picking the stray one runs a
   different version against this one's config.
2. **A console script beside the running interpreter** -- the same install, by
   construction. This machine routinely carries a pipx copy, a ``uv tool`` copy and a
   checkout's venv at once, and PATH answers with whichever came first, so a daemon
   from one install could launch a tray from another. ``linux/autostart.py`` already
   resolves ``yazses-daemon`` this way.
3. **A console script on PATH** -- what pipx, uv and a normal pip install provide
   when the interpreter is somewhere else.
4. **None of those** -> ``[sys.executable, "-m", "<module>"]``. Any interpreter that
   can import the package can run its entry points, which covers a venv whose
   ``bin/`` was never exported.

Every input is injectable, so each decision is testable without a bundle, a Windows
box, a macOS box, or a real PATH -- which matters because none of those are available
where this is written, and the frozen path is exactly the one that cannot be
exercised here.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

__all__ = ["Mode", "MODES", "command_for"]


class Mode:
    """The parts of YazSes that can be launched as their own process."""

    CLI = "cli"
    DAEMON = "daemon"
    TRAY = "tray"
    SETTINGS = "settings"
    OVERLAY = "overlay"


#: mode -> (bundle argv flag, console script name, importable module)
#:
#: Each component has its own script, including `yazses-settings` -- a **gui-script**,
#: so on Windows it is launched by `pythonw.exe` and opens no console behind the
#: window. Going through `yazses settings` would have worked and flashed one.
#:
#: The three columns are the three worlds this has to work in, and they are listed
#: together so a new component cannot be added to one and forgotten in the others.
#: `overlay` needs `__main__.py` to carry an `--overlay` branch; it did not, which
#: meant the voice-activity overlay was unreachable from a bundle by construction.
MODES: dict[str, tuple[str, str, str]] = {
    Mode.CLI: ("--cli", "yazses", "yazses.cli"),
    Mode.DAEMON: ("--daemon", "yazses-daemon", "yazses.main"),
    Mode.TRAY: ("--tray", "yazses-tray", "yazses.tray.app"),
    Mode.SETTINGS: ("--settings", "yazses-settings", "yazses.settingsui.app"),
    Mode.OVERLAY: ("--overlay", "yazses-overlay", "yazses.overlay.app"),
}


def command_for(
    mode: str,
    *args: str,
    frozen: bool | None = None,
    executable: Path | None = None,
    which: Callable[[str], str | None] | None = None,
    windows: bool | None = None,
    exists: Callable[[Path], bool] | None = None,
) -> list[str]:
    """The argv that runs *mode* on this install, with *args* passed through.

    ``command_for(Mode.CLI, "restart")`` is "run ``yazses restart`` however this
    install can", and the caller never has to know which of the three worlds it is in.
    """
    import shutil

    if mode not in MODES:
        raise ValueError(f"unknown launch mode {mode!r}; expected one of {sorted(MODES)}")
    flag, script, module = MODES[mode]

    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    executable = Path(sys.executable) if executable is None else executable
    which = shutil.which if which is None else which
    windows = sys.platform.startswith("win") if windows is None else windows
    exists = Path.exists if exists is None else exists

    if frozen:
        # Console work goes through the console binary where one exists, because a
        # windowed binary cannot print. `settings` is a GUI, so it stays on the
        # windowed one even on Windows.
        if mode in (Mode.CLI, Mode.DAEMON):
            sibling = executable.with_name("yazses-cli.exe" if windows else "yazses-cli")
            if exists(sibling):
                # `yazses-cli` already defaults to CLI mode from its own name, so
                # the flag would be redundant there and is only needed to send it
                # somewhere else.
                lead = [] if mode == Mode.CLI else [flag]
                return [str(sibling), *lead, *args]
        return [str(executable), flag, *args]

    # A console script **beside the running interpreter** comes before PATH, which
    # is the idiom `platform/linux/autostart.py` already uses to resolve
    # `yazses-daemon`. On a machine carrying more than one install -- a pipx copy, a
    # `uv tool` copy and a checkout's venv is an ordinary state here -- PATH answers
    # with whichever came first, so a daemon from one install could launch the tray
    # from another and the two would disagree about config, version and socket.
    # Siblings cannot: they are the install that is already running.
    sibling = executable.with_name(script + ".exe" if windows else script)
    if exists(sibling):
        return [str(sibling), *args]

    found = which(script)
    if found:
        return [found, *args]

    # Every module in the table carries an `if __name__ == "__main__"` block, which is
    # what makes this branch real rather than decorative. `-m yazses.cli --version`
    # printed nothing and exited 0 until one was added -- and this is precisely the
    # path taken by the installs least able to report a problem.
    return [str(executable), "-m", module, *args]
