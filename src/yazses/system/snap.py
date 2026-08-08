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
    "dependency_install_advice",
    "in_snap",
    "in_strict_snap",
    "keyboard_capture_advice",
]
