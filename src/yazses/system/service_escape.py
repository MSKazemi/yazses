"""Run a command outside the daemon's systemd unit.

The daemon starts the tray, the tray starts Settings, and Settings runs `yazses restart`.
All of them live in the `yazses.service` cgroup, and `systemctl --user stop yazses` kills the
whole cgroup (the default `KillMode=control-group`) -- `setsid` does not help, a session is
not a cgroup. So a restart launched from the tray or Settings died between its "stop" and
its "start", and the daemon stayed down, because `Restart=on-failure` does not revive a
clean exit. The Settings window died with it, so it could never confirm the outcome.

`systemd-run --scope` moves the command into a scope of its own, which a stop of
`yazses.service` leaves alone. A scope, unlike a transient service, keeps the caller's
environment (DISPLAY, WAYLAND_DISPLAY, the XDG_* overrides), stdio and exit code, so a GUI
or a CLI behaves exactly as it did, only no longer inside the unit.

The decisions are pure; the two side effects (reading the cgroup, running a process) are
injectable, so none of this needs a systemd to test.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

UNIT = "yazses.service"
_CGROUP_FILE = Path("/proc/self/cgroup")


def inside_unit_cgroup(cgroup_text: str, unit: str = UNIT) -> bool:
    """True when a `/proc/<pid>/cgroup` listing places the process in *unit*.

    Matches a whole path component, so `yazses.service.d` or `not-yazses.service` do not
    count. cgroup v2 has one `0::<path>` line; v1 has one line per hierarchy and the
    `name=systemd` one is the unit's, so every line's path is checked the same way.
    """
    for line in cgroup_text.splitlines():
        _hierarchy, sep, rest = line.partition(":")
        if not sep:
            continue
        _controllers, sep, path = rest.partition(":")
        if sep and unit in path.split("/"):
            return True
    return False


def current_process_inside_unit(
    read: Callable[[], str] | None = None, unit: str = UNIT
) -> bool:
    """Is *this* process inside *unit*? False off Linux or when the cgroup is unreadable."""
    if sys.platform != "linux":
        return False
    try:
        text = read() if read is not None else _CGROUP_FILE.read_text(encoding="utf-8")
    except OSError:
        return False
    return inside_unit_cgroup(text, unit)


def scope_argv(argv: Sequence[str]) -> list[str]:
    """`systemd-run --scope` wrapped around *argv*: same process, its own cgroup."""
    # --collect: no failed-scope litter; --quiet: no "Running scope as unit" banner on stderr.
    return ["systemd-run", "--user", "--scope", "--collect", "--quiet", *argv]


def detached_argv(
    argv: Sequence[str], *, inside: Callable[[], bool] | None = None
) -> list[str]:
    """*argv* ready to launch from a process that may be inside the unit.

    Returns it untouched unless this process is inside `yazses.service` and `systemd-run`
    exists, so every other install (snap, macOS, a terminal, no systemd) is unaffected.
    """
    inside = current_process_inside_unit if inside is None else inside
    if inside() and shutil.which("systemd-run") is not None:
        return scope_argv(argv)
    return list(argv)


def run_outside_service(argv: Sequence[str]) -> int | None:
    """Run *argv* in a scope outside the unit and return its exit code.

    None means "could not hand off" (no `systemd-run`, or it would not launch), and the
    caller carries on in-process exactly as it did before this existed.
    """
    if shutil.which("systemd-run") is None:
        return None
    try:
        return subprocess.run(scope_argv(argv), check=False).returncode
    except OSError:
        return None
