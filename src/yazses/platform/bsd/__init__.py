"""BSD backend bundle — FreeBSD, OpenBSD, NetBSD, DragonFly.

Deliberately a thin composition over the Linux backend rather than a parallel
implementation, because on a BSD desktop almost every piece is genuinely the
same code path, not merely a similar one:

* **Paths** — `linux/paths.py` is `platformdirs`, which already returns the XDG
  locations BSDs use (`~/.config/yazses`, `~/.local/share/yazses`). Nothing in
  it is Linux-specific; the module name is historical.
* **Hotkey** — FreeBSD ships `evdev` (`/dev/input/event*`) when the kernel has
  `EVDEV_SUPPORT`, on by default since FreeBSD 12, and the X11 grab fallback is
  the same X server.
* **Injection** — `xdotool`, `ydotool`, `wtype`, `wl-clipboard`, `xclip` are all
  in ports/pkgsrc, and `inject/auto.py` probes for whichever exists rather than
  assuming one.
* **IPC** — a Unix domain socket is a Unix domain socket.
* **Lifecycle** — PID file, detached spawn and stop are plain POSIX. Only
  *autostart* is Linux-only (systemd `--user`), and `LinuxLifecycle` already
  raises a clear "systemctl not found" rather than silently doing nothing, which
  is the correct behaviour here: see `BsdLifecycle` below, which says so in BSD
  terms instead.

**Support status: experimental.** Every component is exercised by the test suite
against a simulated BSD `sys.platform`, but nobody has run YazSes on real BSD
hardware. It is wired up so that it *can* work and so a BSD user gets a working
`doctor` and a truthful report, not because it is known to work end to end. See
`docs/platform-support.md`; report results on
https://github.com/MSKazemi/yazses/issues.
"""

from __future__ import annotations

import logging
import os
import sys

from yazses.platform.base import Paths, Platform
from yazses.platform.linux import _make_tray
from yazses.platform.linux.lifecycle import LinuxLifecycle
from yazses.platform.linux.paths import build_paths

log = logging.getLogger(__name__)

# sys.platform on a BSD carries the major version ("freebsd14", "openbsd7"), so
# every check has to be a prefix match — an equality test against "freebsd"
# silently never fires. This tuple is the single source of that truth.
BSD_PREFIXES = ("freebsd", "openbsd", "netbsd", "dragonfly")


def is_bsd(platform_name: str | None = None) -> bool:
    """True when the given (or running) `sys.platform` is a BSD."""
    return (platform_name if platform_name is not None else sys.platform).startswith(BSD_PREFIXES)


def _make_hotkey(key_id: str, threshold_ms: int, on_start, on_end):
    """Hotkey backend for BSD — X11 grab first, evdev only as a long shot.

    The reverse of the Linux order, and for a concrete reason: `evdev` is a C
    extension compiled against `<linux/input.h>` and does not build on FreeBSD,
    so `pyproject.toml` deliberately leaves it Linux-only. FreeBSD *does* expose
    `/dev/input/event*` when the kernel has `EVDEV_SUPPORT`, so the evdev path is
    still attempted last in case a user has a working build from ports — but
    python-xlib is pure Python, installs everywhere X11 does, and is the backend
    a BSD desktop will actually get.
    """
    if os.environ.get("DISPLAY"):
        try:
            from yazses.platform.linux.hotkey_xgrab import X11GrabHotkey

            return X11GrabHotkey(
                key_id=key_id,
                threshold_ms=threshold_ms,
                on_hold_start=on_start,
                on_hold_end=on_end,
            )
        except Exception as exc:
            log.warning("X11GrabHotkey unavailable on %s (%s); trying evdev", sys.platform, exc)

    from yazses.platform.linux.hotkey import LinuxHotkey

    return LinuxHotkey(
        key_id=key_id,
        threshold_ms=threshold_ms,
        on_hold_start=on_start,
        on_hold_end=on_end,
    )


class BsdLifecycle(LinuxLifecycle):
    """Linux lifecycle minus the systemd assumption.

    The PID file, the detached spawn and the stop path are POSIX and inherited
    unchanged. Autostart is not: BSDs use `rc.d`, not systemd `--user`, and there
    is no per-user equivalent to install into. Rather than write a `.service`
    file into `~/.config/systemd/user/` that nothing on the system will ever
    read — which would report success and produce no autostart at all — this
    refuses with the actual instructions.
    """

    def install_autostart(self) -> None:
        raise RuntimeError(
            "Autostart on BSD is not managed by YazSes: there is no systemd --user "
            "here. Start it from your desktop session's autostart, or add an rc.d "
            "script that runs `yazses-daemon` as your user. `yazses start` works "
            "normally in the meantime."
        )

    def uninstall_autostart(self) -> None:
        # Nothing was ever installed, so removal is a no-op rather than an error —
        # `yazses autostart disable` should not fail on a machine that never had it.
        return None


def build_platform(paths: Paths | None = None) -> Platform:
    """Assemble the BSD bundle. `paths` is injectable for tests."""
    from yazses.platform.linux.injector import LinuxInjector
    from yazses.platform.linux.ipc import UnixSocketIpcClient, UnixSocketIpcServer
    from yazses.platform.linux.permissions import LinuxPermissions

    resolved = paths if paths is not None else build_paths()
    return Platform(
        # The real sys.platform ("freebsd14"), not a generic "bsd": `doctor` and
        # bug reports should name the actual system.
        name=sys.platform,
        default_hotkey="right_alt",
        paths=resolved,
        permissions=LinuxPermissions(),
        lifecycle=BsdLifecycle(paths=resolved),
        hotkey_factory=_make_hotkey,
        injector_factory=LinuxInjector,
        ipc_server_factory=lambda socket_path: UnixSocketIpcServer(socket_path),
        ipc_client_factory=lambda socket_path: UnixSocketIpcClient(socket_path),
        tray_factory=_make_tray,
        tray_default_enabled=True,
        extras={"experimental": True, "family": "bsd"},
    )


__all__ = ["BSD_PREFIXES", "BsdLifecycle", "_make_hotkey", "build_platform", "is_bsd"]
