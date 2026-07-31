"""Linux backend bundle."""

from __future__ import annotations

import logging
import os

from yazses.platform.base import Platform
from yazses.platform.linux.paths import build_paths

log = logging.getLogger(__name__)


def _make_hotkey(key_id: str, threshold_ms: int, on_start, on_end):
    in_snap = "SNAP" in os.environ
    has_x11 = bool(os.environ.get("DISPLAY"))

    if in_snap and has_x11:
        try:
            from yazses.platform.linux.hotkey_xgrab import X11GrabHotkey
            return X11GrabHotkey(
                key_id=key_id,
                threshold_ms=threshold_ms,
                on_hold_start=on_start,
                on_hold_end=on_end,
            )
        except Exception as exc:
            log.warning("X11GrabHotkey unavailable (%s), falling back to evdev", exc)

    from yazses.platform.linux.hotkey import LinuxHotkey
    return LinuxHotkey(
        key_id=key_id,
        threshold_ms=threshold_ms,
        on_hold_start=on_start,
        on_hold_end=on_end,
    )


def _make_tray():
    """Build the Linux tray backend (PySide6 QSystemTrayIcon)."""
    from yazses.platform.linux.tray import LinuxTray

    return LinuxTray()


def build_platform() -> Platform:
    from yazses.platform.linux.injector import LinuxInjector
    from yazses.platform.linux.ipc import UnixSocketIpcClient, UnixSocketIpcServer
    from yazses.platform.linux.lifecycle import LinuxLifecycle
    from yazses.platform.linux.permissions import LinuxPermissions

    paths = build_paths()
    return Platform(
        name="linux",
        default_hotkey="right_alt",
        paths=paths,
        permissions=LinuxPermissions(),
        lifecycle=LinuxLifecycle(paths=paths),
        hotkey_factory=_make_hotkey,
        injector_factory=LinuxInjector,
        ipc_server_factory=lambda socket_path: UnixSocketIpcServer(socket_path),
        ipc_client_factory=lambda socket_path: UnixSocketIpcClient(socket_path),
        tray_factory=_make_tray,
        tray_default_enabled=True,
    )


__all__ = ["build_platform"]
