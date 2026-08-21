"""The tray's Meeting Mode actions — the shared half of Start/Stop meeting.

Meeting Mode is the one capability with no key to hold. It runs hands-free for up to an
hour, so the only way to begin or end one was ``yazses meeting start`` in a terminal —
which is exactly what nobody has open during a meeting. The tray icon is the surface
that is already on screen, so the two actions belong there.

Split the same way ``updates.py`` is, and for the same reason: the macOS and Windows
trays build static menus and never construct a ``TrayController``, so the I/O half has to
be importable on its own. ``TrayController.start_meeting``/``stop_meeting`` remain the
right entry point where a controller *does* exist (Linux), because there the IPC client
is already open and injected — ``call_meeting`` opens its own.

Two rules, both learned from the rest of the tray:

* **Never raise.** A menu click has no exception handler above it; on pystray it takes
  the icon down. Every failure comes back as a ``(title, body)`` the caller can show.
* **Never paraphrase the daemon.** Its refusals name the thing to do next ("meeting mode
  is off; run `yazses features enable meeting`") and its start warning is the only place
  a user is told a transcript will come back with no speaker names. Both are passed
  through verbatim.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# The IPC methods, so a caller cannot invent a third spelling.
START = "meeting_start"
STOP = "meeting_stop"


def call_meeting(action: str, client=None) -> dict:
    """Invoke *action* on the daemon and return its reply. Never raises.

    ``client`` is injected by tests and by any caller that already holds one; otherwise
    a client is built from the platform's IPC socket for this one call.

    An unreachable daemon comes back as ``{"ok": False, "reason": ...}`` — the same shape
    a refusal has — so the caller has exactly one thing to check.
    """
    if action not in (START, STOP):  # pragma: no cover - caller bug
        return {"ok": False, "reason": f"{action!r} is not a meeting action."}
    try:
        if client is None:
            from yazses.platform import get_platform

            platform = get_platform()
            client = platform.ipc_client_factory(platform.paths.ipc_socket)
        result = client.call(action)
    except Exception as exc:
        log.warning("tray %s call failed: %s", action, exc)
        return {"ok": False, "reason": f"Could not reach YazSes: {exc}"}
    return dict(result) if isinstance(result, dict) else {"ok": True}


def describe(action: str, result: dict) -> tuple[str, str]:
    """The ``(title, body)`` notification for *result*. Pure.

    Shared by all three trays so that starting a meeting reads the same on every OS —
    the drift this whole module layout exists to prevent (#63).
    """
    if not result.get("ok"):
        return "YazSes", str(result.get("reason") or "That did not work.")
    if action == START:
        meeting_id = str(result.get("meeting_id") or "").strip()
        body = f"Recording meeting {meeting_id}" if meeting_id else "Recording the meeting"
        warning = result.get("warning")
        if warning:
            # Speaker labels were asked for and the models are missing. Dropping this
            # would hand back an unattributed transcript with nothing having said why.
            body = f"{body}\n⚠ {warning}"
        return "YazSes", body
    return "YazSes", "Meeting stopped — transcribing and writing it up…"


def run_meeting_action(action: str, client=None) -> tuple[str, str]:
    """Do *action* and return the ``(title, body)`` to show. Never raises."""
    return describe(action, call_meeting(action, client=client))
