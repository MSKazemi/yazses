"""Where a clipboard tool finds the Wayland socket inside a strict snap. Pure.

snapd gives a snap a private ``XDG_RUNTIME_DIR`` (``/run/user/<uid>/snap.<name>``)
and passes ``WAYLAND_DISPLAY=wayland-0`` through unchanged, so ``wl-copy`` and
``wl-paste`` look for the socket in a directory that never holds it and fail with
"Failed to connect to a Wayland server". The socket is one level up, and libwayland
accepts an absolute path.

The path is handed to the clipboard commands only, never written into
``os.environ``: the tray and the other Qt processes inherit the daemon's
environment, and a ``WAYLAND_DISPLAY`` that suddenly resolved would move them to a
different Qt platform plugin.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any


def wayland_tool_env(env: Mapping[str, str] | None = None) -> dict[str, str] | None:
    """The environment for a ``wl-*`` command, or None to inherit it unchanged."""
    env = os.environ if env is None else env
    display = env.get("WAYLAND_DISPLAY", "")
    runtime = env.get("XDG_RUNTIME_DIR", "").rstrip("/")
    if not env.get("SNAP") or not display or not runtime or os.path.isabs(display):
        return None
    # ``SNAP`` alone is inherited by anything started from a snapped terminal; the
    # private runtime directory is what says this process is the confined one.
    if not os.path.basename(runtime).startswith("snap."):
        return None
    if os.path.exists(os.path.join(runtime, display)):
        return None
    host = os.path.join(os.path.dirname(runtime), display)
    if not os.path.exists(host):
        return None
    return {**env, "WAYLAND_DISPLAY": host}


def wayland_run_kwargs() -> dict[str, Any]:
    """``subprocess.run`` keywords for a ``wl-*`` command; empty outside a snap."""
    env = wayland_tool_env()
    return {} if env is None else {"env": env}
