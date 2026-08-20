"""Windows backend bundle.

pywin32 / pystray imports happen lazily inside the modules that need them so
importing :mod:`yazses.platform.windows` on a non-Windows box (e.g. a Linux
dev machine) does not fail just from the package import.
"""

from __future__ import annotations

from yazses.platform.base import WINDOWS_PLATFORM_NAME, Platform
from yazses.platform.windows.paths import build_paths


def build_platform() -> Platform:
    from yazses.platform.windows.hotkey import WindowsHotkey
    from yazses.platform.windows.injector import WindowsInjector
    from yazses.platform.windows.ipc import (
        NamedPipeIpcClient,
        NamedPipeIpcServer,
    )
    from yazses.platform.windows.lifecycle import WindowsLifecycle
    from yazses.platform.windows.permissions import WindowsPermissions
    from yazses.platform.windows.tray import WindowsTray

    paths = build_paths()
    return Platform(
        name=WINDOWS_PLATFORM_NAME,
        default_hotkey="right_ctrl",
        paths=paths,
        permissions=WindowsPermissions(),
        lifecycle=WindowsLifecycle(paths=paths),
        hotkey_factory=lambda key_id, threshold_ms, on_start, on_end: WindowsHotkey(
            key_id=key_id,
            threshold_ms=threshold_ms,
            on_hold_start=on_start,
            on_hold_end=on_end,
        ),
        injector_factory=WindowsInjector,
        ipc_server_factory=lambda socket_path: NamedPipeIpcServer(socket_path),
        ipc_client_factory=lambda socket_path: NamedPipeIpcClient(socket_path),
        tray_factory=WindowsTray,
        tray_default_enabled=True,
    )


__all__ = ["build_platform"]
