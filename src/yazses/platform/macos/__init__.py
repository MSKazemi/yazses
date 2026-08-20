"""macOS backend bundle.

The PyObjC frameworks used by hotkey/injector/permissions/tray are only
required at runtime on darwin. They're imported lazily by the modules that
use them so importing :mod:`yazses.platform.macos` on a non-Mac box (e.g.
a Linux dev machine) doesn't fail just from the package import.
"""

from __future__ import annotations

from yazses.platform.base import MACOS_PLATFORM_NAME, Platform
from yazses.platform.macos.paths import build_paths


def build_platform() -> Platform:
    from yazses.platform.macos.hotkey import MacosHotkey
    from yazses.platform.macos.injector import MacosInjector
    from yazses.platform.macos.ipc import UnixSocketIpcClient, UnixSocketIpcServer
    from yazses.platform.macos.lifecycle import MacosLifecycle
    from yazses.platform.macos.permissions import MacosPermissions
    from yazses.platform.macos.tray import MacosTray

    paths = build_paths()
    return Platform(
        name=MACOS_PLATFORM_NAME,
        default_hotkey="right_option",
        paths=paths,
        permissions=MacosPermissions(),
        lifecycle=MacosLifecycle(paths=paths),
        hotkey_factory=lambda key_id, threshold_ms, on_start, on_end: MacosHotkey(
            key_id=key_id,
            threshold_ms=threshold_ms,
            on_hold_start=on_start,
            on_hold_end=on_end,
        ),
        injector_factory=MacosInjector,
        ipc_server_factory=lambda socket_path: UnixSocketIpcServer(socket_path),
        ipc_client_factory=lambda socket_path: UnixSocketIpcClient(socket_path),
        tray_factory=MacosTray,
        tray_default_enabled=True,
    )


__all__ = ["build_platform"]
