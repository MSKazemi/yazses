"""Windows backend bundle.

pywin32 / pystray imports happen lazily inside the modules that need them so
importing :mod:`yazses.platform.windows` on a non-Windows box (e.g. a Linux
dev machine) does not fail just from the package import.
"""

from __future__ import annotations

import logging
import os

from yazses.platform.base import WINDOWS_PLATFORM_NAME, Platform
from yazses.platform.windows.paths import build_paths

log = logging.getLogger(__name__)

#: Values of ``[injection] backend`` that mean "paste, don't type" on Windows.
#: `inject/registry.py` owns the Linux ladder; Windows has exactly two ways of
#: getting characters into a window, so the choice is a literal here rather than
#: a second ladder that could drift from the first.
_CLIPBOARD_NAMES = frozenset({"clipboard", "paste"})

#: The Windows default: SendInput + KEYEVENTF_UNICODE.
_TYPE_NAMES = frozenset({"auto", "", "type", "sendinput", "unicode", "windows"})


def build_injector():
    """Honour ``[injection] backend`` on Windows.

    Until now this file named `WindowsInjector` unconditionally, so the setting
    was read, validated, bridged into ``YAZSES_INJECTOR`` by
    `inject.auto.apply_injection_config` -- and then ignored on the one platform
    where the alternative is the documented remedy for the problem it exists to
    solve. A user whose note application renders every dictated character as
    ``?`` had a config key that said it could fix it and did nothing.

    Typing stays the default. `WindowsClipboardInjector` overwrites the
    clipboard and is a no-op in terminals, so it is chosen only when asked for.
    """
    requested = (os.environ.get("YAZSES_INJECTOR", "") or "").strip().lower()
    if requested in _CLIPBOARD_NAMES:
        from yazses.platform.windows.clipboard import WindowsClipboardInjector

        return WindowsClipboardInjector()
    if requested not in _TYPE_NAMES:
        # A Linux-only name (ydotool, wtype, xdotool, portal) in a shared config.
        # Substituting in silence is what `inject/registry.py`'s docstring calls
        # out as the failure to avoid, so say which one is actually running.
        log.warning(
            "[injection] backend = %r has no meaning on Windows; typing with "
            "SendInput instead. Windows supports 'auto' (type) or 'clipboard'.",
            requested,
        )
    from yazses.platform.windows.injector import WindowsInjector

    return WindowsInjector()


def build_platform() -> Platform:
    from yazses.platform.windows.hotkey import WindowsHotkey
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
        injector_factory=build_injector,
        ipc_server_factory=lambda socket_path: NamedPipeIpcServer(socket_path),
        ipc_client_factory=lambda socket_path: NamedPipeIpcClient(socket_path),
        tray_factory=WindowsTray,
        tray_default_enabled=True,
    )


__all__ = ["build_injector", "build_platform"]
