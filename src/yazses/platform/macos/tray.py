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
    STATUS_LINE_SLOTS,
    TROUBLESHOOTING_LABEL,
    UPDATE_LABEL,
    status_from_model,
    status_lines,
)
from yazses.tray.updates import describe_update

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

# The status lines at the top of the menu: engine, speech-model memory, the top warning
# (`tray/menu.py::status_lines`). A rumps menu is built once, so the slots exist from the
# start and each tick retitles them, hiding the ones with nothing to say. rumps keys a
# MenuItem by its title *when it is added*, so each slot starts under a distinct
# placeholder key; the title shown is set before the menu is ever opened.
_STATUS_SLOT_KEYS: tuple[str, ...] = tuple(
    f"yazses-status-{i}" for i in range(STATUS_LINE_SLOTS)
)


class MacosTray:
    """TrayBackend implementation for macOS, backed by rumps."""

    #: What this tray imports: rumps, a darwin base dependency (`tray/launch.py`).
    RUNTIME_MODULES: tuple[str, ...] = ("rumps",)

    def __init__(self) -> None:
        # rumps is imported lazily, so the concrete _App type is not nameable here.
        self._app: Any = None
        self._on_quit: Callable[[], None] | None = None
        self._lock = threading.Lock()
        # The disabled status MenuItems (see `_STATUS_SLOT_KEYS`), and the lines they
        # last showed, so an unchanged tick does not queue work on the main thread.
        self._status_items: list[Any] = []
        self._shown_lines: list[str] | None = None

    def run(self, on_quit: Callable[[], None]) -> None:
        try:
            import rumps  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "rumps is not installed. Install with `pip install rumps` or run "
                "the daemon without the tray."
            ) from exc

        self._on_quit = on_quit
        tray = self

        class _App(rumps.App):
            def __init__(self_inner) -> None:
                super().__init__("YazSes", icon=None, title=_GLYPH[TrayState.IDLE])
                # Status lines first: the glyph is all a Mac user saw, so the engine,
                # whether the speech model is in memory, and any warning were invisible
                # here while Linux showed them in its menu and Windows in its tooltip.
                # No callback, so rumps greys them out: they inform, they do not act.
                # Retitled only after they are in the menu (below), because rumps keys
                # an item by its title at the moment it is added.
                status_items = [rumps.MenuItem(key) for key in _STATUS_SLOT_KEYS]
                # "Settings…" opens the graphical settings window — the same
                # entry the Linux tray has, so the menu means the same thing
                # on every OS (#63). Help/About/updates likewise.
                self_inner.menu = [
                    *status_items,
                    None,
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
                # "loading" until the first poll retitles them. Still on the main
                # thread here, before the run loop starts, so no dispatch is needed.
                _apply_status_lines(
                    status_items, status_lines({"state": TrayState.LOADING.value})
                )
                tray._status_items = status_items

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
                    # `describe_update`, not `check_and_describe`: a .app install has
                    # no upgrade command — the upgrade is a downloaded .dmg — so the
                    # describing variant ends at a URL inside a notification, where it
                    # is not clickable. This opens the download page, which is the
                    # smallest thing that makes the click mean something.
                    title, body = describe_update()
                    rumps.notification("YazSes", title, body)

                threading.Thread(
                    target=_work, name="tray-update-check", daemon=True
                ).start()

        # rumps' own "Quit" item calls NSApplication.terminate:, which ends the process
        # from inside the event loop -- `self._app.run()` below never returns, so the
        # statement after it never ran and the daemon was never told to stop. It stayed
        # up (launchd restarts only a crash), still holding the permission it read when
        # its keyboard tap was created, and opening the app again exited as a duplicate
        # (#578). `before_quit` fires from applicationWillTerminate: on that path.
        # The call after run() stays for a loop that does return, and the guard keeps
        # the daemon from being asked twice.
        sent = threading.Event()

        def _tell_daemon_once() -> None:
            if sent.is_set():
                return
            sent.set()
            if self._on_quit is not None:
                self._on_quit()

        from rumps import events as rumps_events  # type: ignore[import-not-found]

        rumps_events.before_quit.register(_tell_daemon_once)

        self._app = _App()
        log.info("Launching rumps tray (NSApp.run blocks)")
        self._app.run()
        _tell_daemon_once()

    def set_state(self, model: TrayModel) -> None:
        with self._lock:
            if self._app is None:
                return
            glyph = _GLYPH.get(model.state, _GLYPH[TrayState.IDLE])
            try:
                self._app.title = glyph
            except Exception:
                log.exception("Tray title update failed")
            # The status lines, on the same tick as the glyph. Worked out here, on the
            # poller thread, from the shared helpers; only the AppKit mutation itself
            # goes to the main thread, and only when a line actually changed.
            items = list(self._status_items)
            if not items:
                return
            lines = status_lines(status_from_model(model))
            if lines == self._shown_lines:
                return
            if _on_main_thread(_apply_status_lines, items, lines):
                self._shown_lines = lines

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


def _apply_status_lines(items: list[Any], lines: list[str]) -> None:
    """Show *lines* in the status slots, in order, and hide the slots left over.

    Must run on the main thread: these are AppKit menu items. Module-level, like
    ``_launch_settings``, so it is testable without rumps on a Linux runner. A hidden
    slot keeps its old title (``hidden`` needs rumps 0.4.0, the declared floor); one
    failing item must not leave the others stale, so each is guarded on its own.
    """
    for index, item in enumerate(items):
        text = lines[index] if index < len(lines) else None
        try:
            if text is None:
                item.hidden = True
            else:
                item.title = text
                item.hidden = False
        except Exception:
            log.debug("tray status line update failed", exc_info=True)


def _on_main_thread(func: Callable[..., None], *args: Any) -> bool:
    """Queue ``func(*args)`` on the Cocoa main thread; ``False`` if it could not be queued.

    The status poll calls ``set_state`` from its own thread, and AppKit objects may only
    be mutated on the main one. `PyObjCTools.AppHelper.callAfter` (pyobjc-framework-Cocoa,
    which rumps depends on) posts the call to the main run loop: no timer of our own, and
    the poll stays the one clock. When it is unavailable the update is skipped rather
    than made from the wrong thread, and the next tick tries again (``set_state`` records
    the lines as shown only when they were queued).
    """
    try:
        from PyObjCTools import AppHelper  # type: ignore[import-not-found]

        AppHelper.callAfter(func, *args)
    except Exception:
        log.debug("could not queue a tray update on the main thread", exc_info=True)
        return False
    return True


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
