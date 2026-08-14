"""Tray action controller — turns menu clicks into daemon calls.

Sits between the Qt widget and the daemon so the widget stays dumb and this stays
testable: the IPC client and the process launcher are injected, so every action can be
asserted without a running daemon or a real subprocess.

Mic actions (pin / unpin / re-calibrate) go over IPC so they take effect *live* on the
running daemon (no restart). Restart shells out to the ``yazses`` CLI, which already
knows how to cleanly restart via systemd / detached process. Stop uses the existing
``shutdown`` IPC method. Launching the settings window shells out the same way, as a
detached ``yazses settings`` process — the tray never blocks waiting on it.

Help/About open a URL through an injected opener. The update check is the one action that
*blocks* (it reaches PyPI, or shells ``snap info``), so it is exposed as a plain call the
caller is expected to run on a worker thread — the Qt tray marshals the result back.
"""
from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable

from yazses.system.browser import open_url

log = logging.getLogger(__name__)


class TrayController:
    """Execute tray menu actions against the daemon. All side effects injected."""

    def __init__(
        self,
        client,
        launcher: Callable[[list[str]], object] = subprocess.Popen,
        opener: Callable[[str], bool] = open_url,
    ) -> None:
        self._client = client
        self._launch = launcher
        self._open = opener

    # ---- reads ----
    def status(self) -> dict:
        """Current daemon status, or ``{}`` when unreachable."""
        try:
            return dict(self._client.call("status"))
        except Exception as exc:
            log.debug("tray status call failed: %s", exc)
            return {}

    def list_devices(self):
        """Local input-device list (no daemon needed)."""
        from yazses.audio.devices import list_input_devices

        try:
            return list_input_devices()
        except Exception as exc:  # pragma: no cover - hardware/backend dependent
            log.debug("tray device list failed: %s", exc)
            return []

    # ---- mic actions (live, over IPC) ----
    def pin(self, device: str) -> dict:
        """Pin capture to ``device`` (a name substring). Empty string = OS default."""
        return self._call("pin_mic", device=device)

    def unpin(self) -> dict:
        """Follow the OS default input device again."""
        return self.pin("")

    def recalibrate(self) -> dict:
        """Re-measure the active mic and write a fitting vad_threshold."""
        return self._call("recalibrate_mic")

    # ---- daemon control ----
    def restart(self) -> bool:
        """Restart the daemon via the CLI (handles systemd / detached cleanly).

        Returns whether the launch was handed off, so the caller can tell the user
        rather than reporting a restart that never began.
        """
        try:
            self._launch(["yazses", "restart"])
            return True
        except Exception:
            log.exception("tray restart failed")
            return False

    def launch_settings(self) -> bool:
        """Open the graphical settings window, detached (never blocks the tray).

        Returns whether the launch was handed off. A menu click that silently does
        nothing is indistinguishable from a frozen tray, so the caller reports it.
        """
        try:
            self._launch(["yazses", "settings"])
            return True
        except Exception:
            log.exception("tray settings launch failed")
            return False

    def stop_daemon(self) -> dict:
        """Ask the daemon to shut down."""
        return self._call("shutdown")

    # ---- help / about / updates -------------------------------------------
    def open_url(self, url: str) -> bool:
        """Open a docs/issues URL in the browser. Returns whether it was handed off."""
        try:
            return bool(self._open(url))
        except Exception:
            log.exception("tray url launch failed: %s", url)
            return False

    def check_updates(self):
        """Look up whether a newer YazSes is published, for the running install method.

        Blocking: this reaches PyPI (or shells ``snap info``), so callers must run it off
        the GUI thread. A failure comes back as a ``latest=None`` status rather than an
        exception, so the tray always has something to show. Shared with the macOS and
        Windows trays, which have no controller of their own.
        """
        from yazses.tray.updates import check_updates

        return check_updates()

    def install_update(self, status) -> int:
        """Run the upgrade command for ``status``; return its exit code (blocking)."""
        from yazses.system.updater import run_upgrade

        try:
            return run_upgrade(status)
        except Exception:
            log.exception("tray update install failed")
            return 1

    def _call(self, method: str, **params) -> dict:
        try:
            result = self._client.call(method, **params)
            return dict(result) if isinstance(result, dict) else {"ok": True}
        except Exception as exc:
            log.warning("tray %s call failed: %s", method, exc)
            return {"ok": False, "error": str(exc)}
