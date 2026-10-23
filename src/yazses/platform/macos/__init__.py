"""macOS backend bundle.

The PyObjC frameworks used by hotkey/injector/permissions/tray are only
required at runtime on darwin. They're imported lazily by the modules that
use them so importing :mod:`yazses.platform.macos` on a non-Mac box (e.g.
a Linux dev machine) doesn't fail just from the package import.
"""

from __future__ import annotations

from yazses.platform.base import MACOS_PLATFORM_NAME, PRIMARY_MODIFIER_CMD, Platform
from yazses.platform.macos.paths import build_paths


def build_platform() -> Platform:
    from yazses.platform.macos.click_observer import MacClickObserver
    from yazses.platform.macos.focused_app import build_macos_focused_app
    from yazses.platform.macos.hotkey import MacosHotkey
    from yazses.platform.macos.injector import MacosInjector
    from yazses.platform.macos.ipc import UnixSocketIpcClient, UnixSocketIpcServer
    from yazses.platform.macos.lifecycle import MacosLifecycle
    from yazses.platform.macos.permissions import MacosPermissions
    from yazses.platform.macos.pointer import build_macos_pointer_sink
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
        # The factory, not the bare class: it refuses at open time when Quartz is
        # missing or post-event access is denied, so the Head-Pointer can say why.
        pointer_factory=build_macos_pointer_sink,
        # The constructor, unstarted: it imports Quartz and creates its listen-only tap
        # only on start(), which the refiner calls solely under `[gaze_refine] enabled`.
        # A NULL tap (no Input Monitoring / Accessibility) raises there with the reason.
        click_observer_factory=MacClickObserver,
        # The frontmost app's bundle id ("com.microsoft.VSCode"), for editor command
        # profiles under `[commands] profile = "auto"`. AppKit is imported only when the
        # daemon builds it, and its absence raises with the reason the daemon logs.
        focused_app_factory=build_macos_focused_app,
        # Undo, copy, paste, save, select all are Cmd chords here, not Ctrl ones;
        # `commands/dispatch.py` sends its macOS keymap because of this one field.
        primary_modifier=PRIMARY_MODIFIER_CMD,
    )


__all__ = ["build_platform"]
