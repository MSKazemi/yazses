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


#: What a tray backend that declares nothing is assumed to need: the Qt tray (Linux, BSD).
_DEFAULT_TRAY_MODULES: tuple[str, ...] = ("PySide6",)


def tray_runtime_modules(platform=None) -> tuple[str, ...]:  # noqa: ANN001
    """The modules this platform's tray backend imports.

    Each backend declares ``RUNTIME_MODULES``; one that does not (the Qt tray, built
    through a factory function) is assumed to be the Qt tray. The answer used to be
    PySide6 everywhere, which is wrong for the two trays that never touch Qt: Windows
    (pystray + Pillow) and macOS (rumps), both base dependencies on their platforms.
    """
    if platform is None:
        try:
            from yazses.platform import get_platform

            platform = get_platform()
        except Exception:  # noqa: BLE001 - an unknown platform keeps the old answer
            return _DEFAULT_TRAY_MODULES
    factory = getattr(platform, "tray_factory", None)
    return tuple(getattr(factory, "RUNTIME_MODULES", _DEFAULT_TRAY_MODULES))


def missing_tray_modules(platform=None) -> list[str]:  # noqa: ANN001
    """The tray backend's modules that are not importable here; empty when it can run."""
    import importlib.util

    return [m for m in tray_runtime_modules(platform) if importlib.util.find_spec(m) is None]


def tray_dependency_available(platform=None) -> bool:  # noqa: ANN001
    """Whether this platform's tray backend has what it imports.

    On Windows that decides more than whether an icon appears. The tray is what
    restarts a crashed daemon there (the ``HKCU\\Run`` autostart fires once, at
    sign-in), so when this said "PySide6 is missing" on a pip, pipx or uv install,
    which ships pystray but not Qt, the daemon skipped the tray and a crash meant no
    dictation until the next sign-in.
    """
    return not missing_tray_modules(platform)
