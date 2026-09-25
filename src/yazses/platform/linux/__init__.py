"""Linux backend bundle."""

from __future__ import annotations

import logging
import os

from yazses.platform.base import LINUX_PLATFORM_NAME, Platform
from yazses.platform.linux.paths import build_paths
from yazses.pointer.base import PointerSink

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


def build_pointer_sink() -> PointerSink:
    """Open this Linux session's pointer output (ADR-v2-146), or say why there is none.

    Separate from :func:`build_platform` on purpose. `Platform` is built once at start-up
    for every user, and a pointer sink must be opened only when a pointer consumer is
    actually enabled — ADR-v2-146 rule 7, which matters most on Wayland where opening one
    means asking the user for consent. Folding it into the bundle would take a display
    connection for everybody who only ever dictates.

    X11 only, for now, and that is a narrower claim than "Linux": XTEST is an X-server
    extension, so this reaches a real X session, and on a Wayland session it reaches
    whatever XWayland exposes — which is not the native Wayland pointer. A session with no
    X server at all gets ``PointerUnsupportedError`` rather than something that accepts
    every request and moves nothing. The Wayland path is to extend the RemoteDesktop
    portal session in `src/yazses/inject/portal.py`, which is a separate backend; until it
    exists this function is the only pointer output Linux has, and the choice between them
    is not made here.
    """
    from yazses.platform.linux.pointer_x11 import build_x11_pointer_sink

    return build_x11_pointer_sink()


def build_platform() -> Platform:
    from yazses.platform.linux.injector import LinuxInjector
    from yazses.platform.linux.ipc import UnixSocketIpcClient, UnixSocketIpcServer
    from yazses.platform.linux.lifecycle import LinuxLifecycle
    from yazses.platform.linux.permissions import LinuxPermissions

    paths = build_paths()
    return Platform(
        name=LINUX_PLATFORM_NAME,
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


__all__ = ["build_platform", "build_pointer_sink"]
