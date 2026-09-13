"""Snap-confinement awareness.

Advice that cannot work is worse than no advice. Inside a strictly confined
snap the barrier to ``/dev/input/event*`` is snapd, not the ``input`` group, so
telling the user to run ``usermod -aG input`` sends them round a loop that can
never succeed — they join the group, log out, log back in, and get the same
``denied`` (issue #44). The only thing that can grant it is the ``raw-input``
interface, or installing unconfined.

Pure and import-light on purpose: this is consulted from ``yazses doctor``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Iterable, Mapping

# snapd reports the confinement the snap is actually running under. Only these
# two give the sandbox escape that makes raw keyboard reads work by default.
_UNCONFINED = frozenset({"classic", "devmode"})


def in_snap(env: Mapping[str, str] | None = None) -> bool:
    """True when this process is running from inside a snap."""
    environ = os.environ if env is None else env
    return bool(environ.get("SNAP_NAME") or environ.get("SNAP"))


def in_strict_snap(env: Mapping[str, str] | None = None) -> bool:
    """True when running inside a *strictly confined* snap.

    ``SNAP_CONFINEMENT`` is set by snapd. When it is missing we assume strict:
    that is what this project publishes, and it is the failure mode that needs
    explaining. Guessing "unconfined" here would restore the bad advice.
    """
    environ = os.environ if env is None else env
    if not in_snap(environ):
        return False
    return environ.get("SNAP_CONFINEMENT", "strict").strip().lower() not in _UNCONFINED


def dependency_install_advice(
    packages: Iterable[str], env: Mapping[str, str] | None = None
) -> str:
    """The truth about installing optional libraries inside a snap: you cannot.

    A snap's payload is a read-only squashfs, and the Python we stage is
    Debian's, which ships a PEP 668 ``EXTERNALLY-MANAGED`` marker. So pip stops
    with *Debian's* advice — "apt install python3-xyz", "create a virtualenv",
    "use pipx" — none of which means anything inside confinement, and the last
    of which is the very thing the user chose not to do. Better to refuse with
    the one instruction that works than to hand them apt's.
    """
    environ = os.environ if env is None else env
    name = environ.get("SNAP_INSTANCE_NAME") or environ.get("SNAP_NAME") or "yazses"
    wanted = " ".join(packages)
    return (
        "this is a snap, and a snap's own files are read-only, so extra Python "
        "libraries can never be installed into it — pip refuses whatever flags "
        f"it is given.\nThis capability needs: {wanted}\n"
        "The snap bundles the libraries for every capability that fits inside "
        "it; this one does not (too large, or no wheel for this architecture).\n"
        "To use it, install unconfined instead — same app, every capability:\n"
        f"    sudo snap remove {name}\n"
        "    pipx install yazses\n"
        "(Config and models do not carry over: the snap keeps them under "
        f"~/snap/{name}/, an unconfined install under ~/.config/yazses.)"
    )


# The two interfaces without which the snap cannot dictate, and what each one
# costs the user when it is missing. Both are manual-connect: snapd will not
# auto-connect them for a snap that has no store declaration, and **a snap
# cannot connect its own interfaces**.
REQUIRED_INTERFACES: tuple[tuple[str, str], ...] = (
    ("audio-record", "the microphone — without it YazSes records silence"),
    ("raw-input", "the hold-to-talk key — without it nothing ever starts recording"),
)


def interface_connected(plug: str, env: Mapping[str, str] | None = None) -> bool | None:
    """Whether ``plug`` is connected. ``None`` means *could not determine*.

    The three-valued answer is the point. A connected/not-connected boolean
    would have to invent an answer when ``snapctl`` is absent or fails, and
    inventing "connected" hides the very failure this exists to surface while
    inventing "not connected" sends an unconfined user chasing a command that
    does not apply to them. ``None`` lets the caller say "could not check".
    """
    if not in_snap(env):
        return None
    if not shutil.which("snapctl"):
        return None
    try:
        proc = subprocess.run(
            ["snapctl", "is-connected", plug],
            capture_output=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return None
    # snapctl is-connected exits 0 when connected and 1 when not. Anything else
    # (unknown plug, snapd too old for the subcommand) is not an answer.
    if proc.returncode == 0:
        return True
    if proc.returncode == 1:
        return False
    return None


def missing_interfaces(
    env: Mapping[str, str] | None = None,
) -> list[tuple[str, str]]:
    """The required interfaces that are known to be disconnected.

    Only definitively-disconnected ones: an interface whose state could not be
    determined is left out, so this never manufactures a problem.
    """
    return [
        (plug, why)
        for plug, why in REQUIRED_INTERFACES
        if interface_connected(plug, env) is False
    ]


def connection_advice(
    missing: Iterable[tuple[str, str]], env: Mapping[str, str] | None = None
) -> str:
    """The exact commands that fix a disconnected install.

    Written as a copy-pasteable block because this is the message a first-time
    snap user sees at the moment nothing works, and the state it describes --
    a daemon that started cleanly, reports healthy, and silently never hears a
    word -- is indistinguishable from the app simply being broken.
    """
    environ = os.environ if env is None else env
    name = environ.get("SNAP_INSTANCE_NAME") or environ.get("SNAP_NAME") or "yazses"
    items = list(missing)
    if not items:
        return ""
    lines = [
        "This snap is installed but not permitted to do its job. A snap cannot "
        "connect its own interfaces, so these have to be run once, by you:",
        "",
    ]
    lines += [f"    sudo snap connect {name}:{plug}" for plug, _ in items]
    lines += ["    yazses restart", ""]
    lines += [f"  {plug} grants {why}." for plug, why in items]
    return "\n".join(lines)


def keyboard_capture_advice(env: Mapping[str, str] | None = None) -> str:
    """The only advice that can actually restore keyboard capture in a snap."""
    environ = os.environ if env is None else env
    name = environ.get("SNAP_INSTANCE_NAME") or environ.get("SNAP_NAME") or "yazses"
    return (
        "this is a strictly confined snap, so reading the keyboard needs the "
        "`raw-input` interface — joining the `input` group cannot grant it. Run:\n"
        f"    sudo snap connect {name}:raw-input\n"
        "    yazses restart\n"
        "If your snapd does not offer that interface, install unconfined instead:\n"
        f"    sudo snap remove {name} && pipx install yazses"
    )


__all__ = [
    "REQUIRED_INTERFACES",
    "connection_advice",
    "dependency_install_advice",
    "in_snap",
    "in_strict_snap",
    "interface_connected",
    "keyboard_capture_advice",
    "missing_interfaces",
]
