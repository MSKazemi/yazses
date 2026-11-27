"""The tray's one-click fix for a daemon that has a problem: start, restart, recalibrate.

*Whether* to offer one, and which, is decided in ``tray/menu.py::fix_entry``, which asks
the same function as the window's Overview page (``settingsui/overview.py::health``). This
module only carries the click out, the way that page does.

Split like ``meeting.py`` and ``camera.py``: Qt-free and importable on its own, so the
three trays (Qt, rumps, pystray) share it. Never raise (a menu click has no handler above
it), and pass the daemon's refusal through in its own words.
"""
from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable

log = logging.getLogger(__name__)

# `overview.Health.action` values.
START = "start"
RESTART = "restart"
RECALIBRATE = "recalibrate"

_COMMANDS: dict[str, tuple[str, ...]] = {
    # `--no-autostart`: a button that says "Start" must not also add a login item.
    START: ("start", "--no-autostart"),
    RESTART: ("restart",),
}


def command(action: str) -> list[str]:
    """The argv for *action* (``start`` or ``restart``) on this install."""
    from yazses.system.relaunch import Mode, command_for
    from yazses.system.service_escape import detached_argv

    # Outside the daemon's systemd unit: the tray lives in it, and stopping the unit
    # would kill the command part way through.
    return detached_argv(command_for(Mode.CLI, *_COMMANDS[action]))


def _launch(argv: list[str], **kwargs: object) -> object:
    """Start *argv* in its own session, with no terminal and no console window."""
    options: dict = {
        "start_new_session": True,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        # No console flashing up on Windows; 0 is the only value accepted elsewhere.
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
    }
    options.update(kwargs)
    return subprocess.Popen(argv, **options)


def _daemon_running() -> bool:
    from yazses.platform import get_platform

    return bool(get_platform().lifecycle.is_running())


def start_daemon(
    launcher: Callable[..., object] | None = None,
    running: Callable[[], bool] | None = None,
) -> dict:
    """Start YazSes unless it is already running. Never raises.

    ``yazses start`` *restarts* a daemon that is already running, without the guard
    ``restart`` has for a meeting still being written, so a live one is left alone, and
    nothing is started when that cannot be checked.
    """
    try:
        if (running or _daemon_running)():
            return {"ok": True, "already_running": True}
        # No terminal to answer a question on: a prompt would hang the start.
        (launcher or _launch)(command(START), stdin=subprocess.DEVNULL)
        return {"ok": True}
    except Exception as exc:
        log.warning("tray could not start the daemon", exc_info=True)
        return {"ok": False, "reason": f"Could not start YazSes: {exc}"}


def restart_daemon(launcher: Callable[..., object] | None = None) -> dict:
    """Hand off ``yazses restart``. Never raises."""
    try:
        (launcher or _launch)(command(RESTART))
        return {"ok": True}
    except Exception as exc:
        log.warning("tray could not restart the daemon", exc_info=True)
        return {"ok": False, "reason": f"Could not restart YazSes: {exc}"}


def call_recalibrate(client=None) -> dict:
    """Ask the daemon to recalibrate the microphone. Never raises."""
    try:
        if client is None:
            from yazses.platform import get_platform

            platform = get_platform()
            client = platform.ipc_client_factory(platform.paths.ipc_socket)
        result = client.call("recalibrate_mic")
    except Exception as exc:
        log.warning("tray recalibrate call failed: %s", exc)
        return {"ok": False, "reason": f"Could not reach YazSes: {exc}"}
    return dict(result) if isinstance(result, dict) else {"ok": False}


def describe(action: str, result: dict) -> tuple[str, str]:
    """The ``(title, body)`` notification for *result*. Pure."""
    if not result.get("ok"):
        reason = result.get("reason") or result.get("error") or "That did not work."
        return "YazSes", str(reason)
    if action == RECALIBRATE:
        # The daemon measures the room first and the voice second (`_recalibrate_mic`).
        body = "Re-calibrating: stay quiet first, then speak when asked."
    elif action == RESTART:
        body = "Restarting YazSes…"
    elif result.get("already_running"):
        body = "YazSes is already running."
    else:
        body = "Starting YazSes…"
    return "YazSes", body


def run_fix_action(
    action: str,
    *,
    client=None,
    launcher: Callable[..., object] | None = None,
    running: Callable[[], bool] | None = None,
) -> tuple[str, str]:
    """Do *action* and return the ``(title, body)`` to show. Never raises."""
    if action == START:
        result = start_daemon(launcher, running)
    elif action == RESTART:
        result = restart_daemon(launcher)
    elif action == RECALIBRATE:
        result = call_recalibrate(client)
    else:  # pragma: no cover - caller bug
        result = {"ok": False, "reason": f"{action!r} is not a fix."}
    return describe(action, result)
