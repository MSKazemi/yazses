"""macOS tray (menu-bar) UI built on rumps.

The tray runs as its own process and talks to the daemon over the IPC socket
rather than driving the dictation pipeline directly. Keeping these concerns in
separate processes means a tray crash doesn't kill the daemon (and vice
versa), and the headless daemon can run on its own (e.g. on a Mac without
rumps installed, or for CI smoke tests).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from yazses.platform.base import TrayModel, TrayState
from yazses.tray.about import (
    DOCS_URL,
    REPORT_BUG_URL,
    TROUBLESHOOTING_URL,
    about_lines,
    about_title,
)
from yazses.tray.menu import (
    ABOUT_LABEL,
    DOCS_LABEL,
    HELP_LABEL,
    MEETING_START_LABEL,
    MEETING_STOP_LABEL,
    REPORT_BUG_LABEL,
    SETTINGS_LABEL,
    TROUBLESHOOTING_LABEL,
    UPDATE_LABEL,
)
from yazses.tray.updates import check_and_describe

log = logging.getLogger(__name__)

# macOS-only: dictation cannot inject keystrokes without this permission, so the hint the
# old "Help & permissions" entry carried is kept — as a line in Help, not a menu entry.
_PERMISSIONS_HINT = (
    "Grant Accessibility access in System Settings → Privacy & Security → Accessibility."
)


# Unicode glyphs that read clearly in the menu bar at small sizes.
_GLYPH = {
    TrayState.LOADING: "⏳",
    TrayState.IDLE: "🎤",
    TrayState.RECORDING: "🔴",
    TrayState.TRANSCRIBING: "💭",
    TrayState.INJECTING: "✏️",
    TrayState.PAUSED: "⏸",
    TrayState.ERROR: "⚠️",
}


class MacosTray:
    """TrayBackend implementation for macOS, backed by rumps."""

    def __init__(self) -> None:
        # rumps is imported lazily, so the concrete _App type is not nameable here.
        self._app: Any = None
        self._on_quit: Callable[[], None] | None = None
        self._lock = threading.Lock()

    def run(self, on_quit: Callable[[], None]) -> None:
        try:
            import rumps  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "rumps is not installed. Install with `pip install rumps` or run "
                "the daemon without the tray."
            ) from exc

        self._on_quit = on_quit

        class _App(rumps.App):
            def __init__(self_inner) -> None:
                super().__init__("YazSes", icon=None, title=_GLYPH[TrayState.IDLE])
                # "Settings…" opens the graphical settings window — the same
                # entry the Linux tray has, so the menu means the same thing
                # on every OS (#63). Help/About/updates likewise.
                self_inner.menu = [
                    SETTINGS_LABEL,
                    None,
                    # Meeting Mode. Both entries always present: a rumps menu is built
                    # once here and cannot be re-derived per open the way the Qt tray's
                    # is, so the daemon's own refusal is what tells the user which of
                    # the two applied.
                    MEETING_START_LABEL,
                    MEETING_STOP_LABEL,
                    None,
                    "Pause hotkey",
                    [HELP_LABEL, [DOCS_LABEL, TROUBLESHOOTING_LABEL, REPORT_BUG_LABEL]],
                    ABOUT_LABEL,
                    UPDATE_LABEL,
                ]

            @rumps.clicked(SETTINGS_LABEL)
            def _on_settings(self_inner, _sender) -> None:
                # A menu click that silently does nothing is indistinguishable
                # from a frozen tray, so a failed launch says so.
                if not _launch_settings():
                    rumps.notification(
                        "YazSes", "", "Could not open Settings — is `yazses` on PATH?"
                    )

            @rumps.clicked(MEETING_START_LABEL)
            def _on_meeting_start(self_inner, _sender) -> None:
                _run_meeting("meeting_start")

            @rumps.clicked(MEETING_STOP_LABEL)
            def _on_meeting_stop(self_inner, _sender) -> None:
                _run_meeting("meeting_stop")

            @rumps.clicked("Pause hotkey")
            def _on_pause(self_inner, _sender) -> None:
                # Wired via IPC by the tray entry point; no-op here in v0.
                rumps.notification("YazSes", "Pause", "Pausing the dictation hotkey…")

            @rumps.clicked(HELP_LABEL, DOCS_LABEL)
            def _on_docs(self_inner, _sender) -> None:
                _open(DOCS_URL)

            @rumps.clicked(HELP_LABEL, TROUBLESHOOTING_LABEL)
            def _on_troubleshooting(self_inner, _sender) -> None:
                _open(TROUBLESHOOTING_URL)

            @rumps.clicked(HELP_LABEL, REPORT_BUG_LABEL)
            def _on_report_bug(self_inner, _sender) -> None:
                _open(REPORT_BUG_URL)

            @rumps.clicked(ABOUT_LABEL)
            def _on_about(self_inner, _sender) -> None:
                # An alert rather than a notification: it stays on screen long enough
                # to read a version number off, which is the point of About.
                rumps.alert(
                    title=about_title(),
                    message="\n".join([*about_lines(), "", _PERMISSIONS_HINT]),
                )

            @rumps.clicked(UPDATE_LABEL)
            def _on_check_updates(self_inner, _sender) -> None:
                # Off the UI thread: the check reaches the network and would otherwise
                # freeze the menu bar for as long as the lookup takes.
                rumps.notification("YazSes", "", "Checking for updates…")

                def _work() -> None:
                    title, body = check_and_describe()
                    rumps.notification("YazSes", title, body)

                threading.Thread(
                    target=_work, name="tray-update-check", daemon=True
                ).start()

        self._app = _App()
        log.info("Launching rumps tray (NSApp.run blocks)")
        self._app.run()
        if self._on_quit is not None:
            self._on_quit()

    def set_state(self, model: TrayModel) -> None:
        with self._lock:
            if self._app is None:
                return
            glyph = _GLYPH.get(model.state, _GLYPH[TrayState.IDLE])
            try:
                self._app.title = glyph
            except Exception:
                log.exception("Tray title update failed")

    def notify(self, title: str, body: str) -> None:
        """Show a Notification Center banner relayed from the daemon.

        macOS has no libnotify either, so the daemon's self-healing messages (mic
        auto-heal, VAD retune, silent streak) were log-only here too. They arrive
        over the `status` reply the tray already polls.
        """
        try:
            import rumps  # type: ignore[import-not-found]

            rumps.notification("YazSes", title, body)
        except Exception:
            log.debug("tray notification failed", exc_info=True)

    def stop(self) -> None:
        try:
            import rumps  # type: ignore[import-not-found]

            rumps.quit_application()
        except Exception:
            log.exception("Tray stop raised")


def _run_meeting(action: str) -> None:
    """Start or stop a meeting off the UI thread, reporting the daemon's answer.

    Module-level for the same reason as ``_launch_settings``: importable and testable
    without rumps, which cannot be imported on a Linux CI runner.

    Threaded because starting a meeting builds the recorder and may construct a
    diarizer; a menu-bar app blocked on that is a beachball.
    """
    def _work() -> None:
        from yazses.tray.meeting import run_meeting_action

        title, body = run_meeting_action(action)
        try:
            import rumps  # type: ignore[import-not-found]

            rumps.notification("YazSes", title, body)
        except Exception:
            log.debug("tray notification failed", exc_info=True)

    threading.Thread(target=_work, name="tray-meeting", daemon=True).start()


def _open(url: str) -> bool:
    """Open a Help/About link, telling the user if no browser could be reached.

    Module-level for the same reason as ``_launch_settings``: importable and testable
    without rumps, which cannot be imported on a Linux CI runner.
    """
    from yazses.system.browser import open_url

    if open_url(url):
        return True
    try:
        import rumps  # type: ignore[import-not-found]

        rumps.notification("YazSes", "", f"Could not open your browser. The link is: {url}")
    except Exception:
        log.debug("tray notification failed", exc_info=True)
    return False


def _launch_settings() -> bool:
    """Open the settings window, detached. Shared by the menu handler above.

    Kept module-level so it is importable and testable without rumps, which is
    macOS-only and cannot be imported on a Linux CI runner.
    """
    import subprocess

    from yazses.tray.launch import settings_command

    try:
        subprocess.Popen(
            # The .app bundle has no `yazses` on PATH either; `settings_command`
            # finds the CLI beside the running binary. See its docstring.
            settings_command(),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        return True
    except Exception:
        log.exception("tray settings launch failed")
        return False
