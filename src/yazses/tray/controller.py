"""Tray action controller — turns menu clicks into daemon calls.

Sits between the Qt widget and the daemon so the widget stays dumb and this stays
testable: the IPC client and the process launcher are injected, so every action can be
asserted without a running daemon or a real subprocess.

Mic actions (pin / unpin / re-calibrate) go over IPC so they take effect *live* on the
running daemon (no restart). Restart shells out to the ``yazses`` CLI, which already
knows how to cleanly restart via systemd / detached process. Stop uses the existing
``shutdown`` IPC method.
"""
from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable

log = logging.getLogger(__name__)


class TrayController:
    """Execute tray menu actions against the daemon. All side effects injected."""

    def __init__(
        self,
        client,
        launcher: Callable[[list[str]], object] = subprocess.Popen,
    ) -> None:
        self._client = client
        self._launch = launcher

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
    def restart(self) -> None:
        """Restart the daemon via the CLI (handles systemd / detached cleanly)."""
        try:
            self._launch(["yazses", "restart"])
        except Exception:
            log.exception("tray restart failed")

    def stop_daemon(self) -> dict:
        """Ask the daemon to shut down."""
        return self._call("shutdown")

    def _call(self, method: str, **params) -> dict:
        try:
            result = self._client.call(method, **params)
            return dict(result) if isinstance(result, dict) else {"ok": True}
        except Exception as exc:
            log.warning("tray %s call failed: %s", method, exc)
            return {"ok": False, "error": str(exc)}
