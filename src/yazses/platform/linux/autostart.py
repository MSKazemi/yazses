"""The systemd --user unit for YazSes, and how to find the binary it should run.

Kept pure and import-light on purpose: no systemd, no subprocess, no Linux-only imports,
so the unit text and the executable resolution can be unit-tested on any platform and
reused by every installer instead of being retyped in each one.

Why this exists at all: ``install_autostart()`` used to *refuse* unless a unit file had
already been written by ``install.sh``. Anyone who installed the ordinary Python way —
``pipx install yazses``, ``uv tool install yazses``, ``pip install --user`` — therefore had
no autostart whatsoever and had to run ``yazses start`` by hand after every reboot, with
nothing anywhere saying so. A daemon you must remember to launch is not a daemon.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

SERVICE_NAME = "yazses.service"


def service_path() -> Path:
    """Where the user unit lives (systemd --user reads this directory)."""
    return Path.home() / ".config" / "systemd" / "user" / SERVICE_NAME


def resolve_daemon_command() -> str:
    """The ExecStart command for however YazSes happens to be installed here.

    Order matters. The console script *next to the running interpreter* is checked first
    because it is the one belonging to this install — a `yazses-daemon` earlier on PATH
    from some other environment would otherwise silently become what starts at login,
    which is the sort of thing that "works" until an upgrade moves it.
    """
    sibling = Path(sys.executable).resolve().parent / "yazses-daemon"
    if sibling.exists():
        return str(sibling)
    found = shutil.which("yazses-daemon")
    if found:
        return str(Path(found).resolve())
    # No console script (running from a source checkout, or a broken install): drive the
    # module through this exact interpreter, which is always correct if less pretty.
    return f"{Path(sys.executable).resolve()} -m yazses.main"


def unit_text(exec_start: str) -> str:
    """The unit YazSes installs. Single source of truth — installers should use this.

    ``Restart=on-failure`` rather than ``always``: a clean exit is what ``yazses stop``
    produces, and restarting after the user asked it to stop would be a bug, not
    resilience. The StartLimit pair bounds the crash loop, so a persistently broken
    machine (no audio stack, unreadable config) stops retrying and leaves a diagnosable
    state instead of spinning forever.
    """
    return f"""[Unit]
Description=YazSes voice dictation daemon
Documentation=https://github.com/MSKazemi/yazses
After=graphical-session.target sound.target
Wants=graphical-session.target
# Self-healing with a crash-loop bound: restart on failure, but if it fails 5 times
# within 60s (a persistent bad config, a missing audio stack) stop retrying so it does
# not spin forever. `yazses doctor` then explains why.
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
ExecStart={exec_start}
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
# X11 injection (xdotool/xclip) needs the session's display. GNOME/GDM export these to
# the systemd user manager automatically; PassEnvironment picks them up when they do.
PassEnvironment=DISPLAY XAUTHORITY

[Install]
WantedBy=graphical-session.target
"""


def needs_rewrite(existing: str | None, wanted: str) -> bool:
    """True when the installed unit is missing or no longer matches what we would write.

    Catches the upgrade case that silently breaks autostart: the unit still exists and is
    still enabled, so everything *looks* configured, but its ExecStart points at a binary
    that moved when the tool was reinstalled into a new environment.
    """
    if existing is None:
        return True
    return existing.strip() != wanted.strip()
