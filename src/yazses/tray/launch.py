"""Whether/how to auto-launch the system tray (mirrors the overlay's launch gate)."""
from __future__ import annotations

from collections.abc import Mapping

from yazses.config import Config


def should_launch_tray(config: Config, env: Mapping[str, str]) -> bool:
    """Whether the daemon should auto-spawn the tray icon.

    Only when enabled in ``[tray]`` AND a graphical session is present (``DISPLAY``
    for X11 or ``WAYLAND_DISPLAY``). Headless servers and the test suite never spawn it.
    """
    if not config.tray.enabled:
        return False
    return bool(env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"))


def tray_dependency_available() -> bool:
    """Whether PySide6 is importable (base dep, but stays optional on old distros)."""
    import importlib.util

    return importlib.util.find_spec("PySide6") is not None
