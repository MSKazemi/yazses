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
        # Handles for children we started and deliberately do not wait on. Kept so
        # they can be reaped; see `reap`.
        self._children: list = []

    def _spawn(self, argv: list[str]) -> None:
        """Start a detached child and remember it so it can be reaped later."""
        handle = self._launch(argv)
        if hasattr(handle, "poll"):
            self._children.append(handle)

    def reap(self) -> int:
        """Collect finished children. Returns how many were reaped. Never raises.

        The tray must not block on the settings window -- that would freeze the icon
        for as long as the window is open -- but not waiting at all leaves a zombie.
        Observed on a live machine: `yazses-settings` sat defunct under the tray for
        **67 minutes**, because `subprocess` only reaps opportunistically when the
        next `Popen` is created. Open Settings once and close it and the PID leaks
        until the tray happens to spawn something else; open it repeatedly and they
        accumulate.

        Called from the tray's existing per-tick update, so it costs one `poll()` per
        live child per tick and nothing when there are none.
        """
        alive, reaped = [], 0
        for handle in self._children:
            try:
                if handle.poll() is None:
                    alive.append(handle)
                else:
                    reaped += 1
            except Exception:  # pragma: no cover - a handle that cannot be polled
                log.debug("could not poll a spawned child", exc_info=True)
        self._children = alive
        return reaped

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
            from yazses.tray.launch import settings_command

            self._spawn(settings_command("restart"))
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
            from yazses.tray.launch import settings_command

            self._spawn(settings_command())
            return True
        except Exception:
            log.exception("tray settings launch failed")
            return False

    def stop_daemon(self) -> dict:
        """Ask the daemon to shut down."""
        return self._call("shutdown")

    # ---- Meeting Mode (live, over IPC) ------------------------------------
    def start_meeting(self) -> dict:
        """Begin a hands-free meeting recording.

        Returns the daemon's own answer, including its ``reason`` when it refuses and
        its ``warning`` when speaker labels are requested but the diarization models are
        missing. Both are passed through untouched: the tray guesses at what is possible
        so it can grey out a doomed click, but only the daemon knows, and paraphrasing
        its refusal here is how the two come to disagree.
        """
        return self._call("meeting_start")

    def stop_meeting(self) -> dict:
        """End the running meeting and kick off its transcription post-pass.

        Returns as soon as capture has stopped — the diarization and note-writing run on
        a daemon thread afterwards, which is why ``meeting_finalizing`` exists and why
        the menu stays greyed out for a while after this returns ok.
        """
        return self._call("meeting_stop")

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

    def install_update(self, status):
        """Run the upgrade for ``status`` and verify it (blocking).

        Returns an ``UpgradeOutcome``, not an exit code: the package managers exit 0
        without doing anything when the install is pinned, so only a re-read of the
        installed version can tell the user the truth.
        """
        from yazses.system.updater import UpgradeOutcome, run_upgrade_checked

        try:
            return run_upgrade_checked(status)
        except Exception:
            log.exception("tray update install failed")
            return UpgradeOutcome(
                code=1,
                before=getattr(status, "current", ""),
                after=None,
                expected=getattr(status, "latest", None),
                method=getattr(status, "method", ""),
                command=getattr(status, "command", None),
            )

    def _call(self, method: str, **params) -> dict:
        try:
            result = self._client.call(method, **params)
            return dict(result) if isinstance(result, dict) else {"ok": True}
        except Exception as exc:
            log.warning("tray %s call failed: %s", method, exc)
            return {"ok": False, "error": str(exc)}
