"""The tray's Camera switch: the pure menu entry and the one IPC call behind it (#924).

A webcam is an exclusive device, so the user needs a switch at the icon that releases it
*now* -- ``yazses camera off`` in a terminal is not what you have open when a video call
asks for the camera. The daemon owns the state (``perception/switch.py``) and publishes
it in ``status["camera"]``; the tray only reads that and calls the ``camera`` IPC method.

Split like ``meeting.py``: this module is Qt-free and importable on its own, so the three
trays (Qt, rumps, pystray) share one decision about what the entry says and does.

Two rules carried over from ``meeting.py``: never raise (a menu click has no handler above
it), and never paraphrase the daemon (its failure reasons are passed through).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

CAMERA_LABEL = "Camera"
#: The IPC method, and the two actions it takes besides ``status``.
METHOD = "camera"
ON = "on"
OFF = "off"


@dataclass(frozen=True)
class CameraEntry:
    """The Camera menu toggle, derived purely from the daemon status."""

    label: str        # "Camera"
    checked: bool     # True = ON
    action: str       # what a click asks for: "on" or "off"
    indicator: str    # one line: held / released / covered / failing
    holders: tuple[str, ...] = ()
    covered: bool = False  # a camera looks covered and was released (#923)


def camera_entry(status: dict) -> CameraEntry | None:
    """The Camera toggle for *status*, or ``None`` when there is nothing to switch.

    ``None`` on an older daemon (no ``camera`` key) and when no camera feature is
    enabled (no registered consumer): a switch with nothing behind it is the greyed-out
    placeholder the tray menus have already dropped once ("Pause hotkey").
    """
    raw = status.get("camera")
    if not isinstance(raw, dict):
        return None
    holders = _names(raw.get("holders"))
    if not _names(raw.get("consumers")) and not holders:
        return None
    on = str(raw.get("state", "on")).lower() != "off"
    failures = raw.get("failures")
    failed = sorted(failures) if isinstance(failures, dict) else []
    # Indexes, so not `_names`: camera 0 is a camera.
    raw_covered = raw.get("covered")
    covered = on and isinstance(raw_covered, (list, tuple)) and len(raw_covered) > 0
    if not on:
        indicator = "Camera off: released for other applications"
    elif covered:
        indicator = "Camera covered: released until it is uncovered"
    elif holders:
        indicator = "Camera held by: " + ", ".join(holders)
    elif failed:
        indicator = "Camera could not be opened: " + ", ".join(failed)
    else:
        indicator = "Camera on: not held right now"
    return CameraEntry(
        label=CAMERA_LABEL,
        checked=on,
        action=OFF if on else ON,
        indicator=indicator,
        holders=holders,
        covered=covered,
    )


def _names(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(v) for v in value if str(v))


def call_camera(action: str, client=None) -> dict:
    """Ask the daemon to switch the camera ``on`` or ``off``. Never raises.

    An unreachable daemon comes back as ``{"ok": False, "reason": ...}``, the same shape
    as a refusal, so the caller has one thing to check.
    """
    if action not in (ON, OFF):  # pragma: no cover - caller bug
        return {"ok": False, "reason": f"{action!r} is not a camera action."}
    try:
        if client is None:
            from yazses.platform import get_platform

            platform = get_platform()
            client = platform.ipc_client_factory(platform.paths.ipc_socket)
        result = client.call(METHOD, action=action)
    except Exception as exc:
        log.warning("tray camera %s call failed: %s", action, exc)
        return {"ok": False, "reason": f"Could not reach YazSes: {exc}"}
    return dict(result) if isinstance(result, dict) else {"ok": True}


def describe(action: str, result: dict) -> tuple[str, str]:
    """The ``(title, body)`` notification for *result*. Pure."""
    if not result.get("ok"):
        return "YazSes", str(result.get("reason") or result.get("error") or "That did not work.")
    if action == OFF:
        body = "Camera off: released for other applications."
    else:
        body = "Camera on."
        failures = result.get("failures")
        if isinstance(failures, dict) and failures:
            body += "\n" + "\n".join(f"{k}: {v}" for k, v in sorted(failures.items()))
    return "YazSes", body


def run_camera_action(action: str, client=None) -> tuple[str, str]:
    """Do *action* and return the ``(title, body)`` to show. Never raises."""
    return describe(action, call_camera(action, client=client))
