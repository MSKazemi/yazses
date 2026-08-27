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

from collections.abc import Callable, Mapping
from pathlib import Path

from yazses.config import Config


def should_launch_tray(
    config: Config, env: Mapping[str, str], *, platform: str | None = None
) -> bool:
    """Whether the daemon should auto-spawn the tray icon.

    Only when enabled in ``[tray]`` AND a graphical session is present. The second
    half used to be a bare ``DISPLAY``/``WAYLAND_DISPLAY`` test, which is an
    X11/Wayland question rather than a desktop one, so the daemon never auto-spawned
    the tray on Windows or macOS -- see
    :mod:`yazses.system.graphical`. Headless servers and the test suite still never
    spawn it.
    """
    from yazses.system.graphical import has_graphical_session

    if not config.tray.enabled:
        return False
    return has_graphical_session(env, platform=platform)


def settings_command(
    subcommand: str = "settings",
    *,
    frozen: bool | None = None,
    executable: Path | None = None,
    which: Callable[[str], str | None] | None = None,
    windows: bool | None = None,
    exists: Callable[[Path], bool] | None = None,
) -> list[str]:
    """The argv that runs ``yazses <subcommand>`` on *this* install.

    A frozen bundle is asked through its own mode flag; otherwise a console script
    beside the running interpreter wins, then one on PATH, then ``-m``. The full
    reasoning for that order lives with the implementation.

    Every input is injectable so the decision is testable without a bundle, a
    Windows box, or a real PATH.

    Kept as the tray's name for the operation, but the decision now lives in
    ``system/relaunch.py`` — the same question was being answered independently in
    six other places, and one of those answers has to be the one that is maintained.
    Delegating also fixed a real bug here: this named a ``yazses-cli`` sibling on any
    frozen non-Windows build, and the macOS ``.app`` ships exactly one executable, so
    the Settings button pointed at a file that does not exist. The sibling is now
    tested for rather than assumed from the platform.
    """
    from yazses.system.relaunch import Mode, command_for

    mode = Mode.SETTINGS if subcommand == "settings" else Mode.CLI
    extra = () if subcommand == "settings" else (subcommand,)
    return command_for(
        mode, *extra, frozen=frozen, executable=executable, which=which,
        windows=windows, exists=exists,
    )


def tray_dependency_available() -> bool:
    """Whether PySide6 is importable (base dep, but stays optional on old distros)."""
    import importlib.util

    return importlib.util.find_spec("PySide6") is not None
