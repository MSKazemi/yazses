"""Whether/how to auto-launch the system tray (mirrors the overlay's launch gate).

Also owns **how the tray starts a YazSes command**, which is not the trivial
question it looks like. Every backend used to spawn `["yazses", "settings"]`, and
on the Windows installer build there is no `yazses` on PATH — the bundle ships
`YazSesApp.exe` and `yazses-cli.exe` beside each other and adds neither. Clicking
**Settings…** therefore produced a toast saying *"Could not open Settings — is
`yazses` on PATH?"* and nothing else, on the one build whose users are least
likely to own a terminal. Reported from a live install, 2026-08-15.
"""
from __future__ import annotations

import sys
from collections.abc import Callable, Mapping
from pathlib import Path

from yazses.config import Config


def should_launch_tray(config: Config, env: Mapping[str, str]) -> bool:
    """Whether the daemon should auto-spawn the tray icon.

    Only when enabled in ``[tray]`` AND a graphical session is present (``DISPLAY``
    for X11 or ``WAYLAND_DISPLAY``). Headless servers and the test suite never spawn it.
    """
    if not config.tray.enabled:
        return False
    return bool(env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"))


def settings_command(
    subcommand: str = "settings",
    *,
    frozen: bool | None = None,
    executable: Path | None = None,
    which: Callable[[str], str | None] | None = None,
    windows: bool | None = None,
) -> list[str]:
    """The argv that runs ``yazses <subcommand>`` on *this* install.

    Three cases, tried in this order, because each later one is a weaker
    assumption than the last:

    1. **A frozen bundle** — use the `yazses-cli` executable sitting beside the
       running one. `sys.executable` is the *app* here, so ``-m yazses.cli`` would
       hand a module flag to a windowed binary that ignores it and opens the GUI
       again. PATH is deliberately **not** consulted first: a machine can carry
       both the installer's app and an old `pip install`, and picking the stray
       one silently opens another version's settings.
    2. **A console script on PATH** — what pipx, uv and a normal pip install give.
    3. **Neither** — ``[sys.executable, "-m", "yazses.cli", …]``. Any interpreter
       that can import the package can run its CLI, which covers a venv whose
       `bin/` was never exported. This is the same fallback
       `settingsui/app.py::_run_restart` already relies on.

    Every input is injectable so the decision is testable without a bundle, a
    Windows box, or a real PATH.
    """
    import shutil

    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    executable = Path(sys.executable) if executable is None else executable
    which = shutil.which if which is None else which
    windows = sys.platform.startswith("win") if windows is None else windows

    if frozen:
        sibling = executable.with_name("yazses-cli.exe" if windows else "yazses-cli")
        return [str(sibling), subcommand]

    found = which("yazses")
    if found:
        return [found, subcommand]

    return [str(executable), "-m", "yazses.cli", subcommand]


def tray_dependency_available() -> bool:
    """Whether PySide6 is importable (base dep, but stays optional on old distros)."""
    import importlib.util

    return importlib.util.find_spec("PySide6") is not None
