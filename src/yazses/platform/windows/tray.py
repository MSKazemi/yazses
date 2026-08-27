"""Windows system-tray UI built on pystray.

Like the macOS tray, this runs in its own process and talks to the daemon
over the named-pipe IPC. The tray's icon updates reflect daemon state pushed
by the cross-platform tray entry script (``yazses.tray.app``).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from yazses.platform.base import TrayModel
from yazses.tray.about import (
    about_title,
    balloon_body,
    fit_balloon,
    fit_balloon_title,
    help_links,
)
from yazses.tray.menu import (
    ABOUT_LABEL,
    HELP_LABEL,
    MEETING_START_LABEL,
    MEETING_STOP_LABEL,
    SETTINGS_LABEL,
    UPDATE_LABEL,
    icon_spec,
    status_from_model,
)
from yazses.tray.updates import describe_update

log = logging.getLogger(__name__)


# Matches LinuxTray's _ICON_PX. pystray hands the image to Windows through a
# temporary .ico, and Windows picks a frame for the display scaling (16 px at
# 100%, 20 at 125%, 24 at 150%, 32 at 200%) — 64 is a clean multiple of all four.
_ICON_PX = 64

# Shell_NotifyIcon's szTip is 128 wide chars including the terminator and
# truncates silently; icon_spec's richest tooltip can exceed that with a long
# device name, so it is cut here rather than mid-line by the shell.
_TOOLTIP_MAX = 127


def _make_icon(color_hex: str):
    """The YazSes mark — a rounded badge in the state colour with a white "Y".

    This used to be a bare `draw.ellipse` disc: no brand mark, and visibly
    jagged because Pillow does not anti-alias. `render_mark` supersamples, and is
    the same renderer that produces assets/yazses.ico, so the tray badge and the
    shortcut icon are the same drawing. `wave=False` keeps the mark legible at
    16 px — the sound-wave bars are sub-pixel there.
    """
    from yazses.brandmark import render_mark
    from yazses.tray.menu import glyph_for

    # The mark is not always white: on the yellow "nowhere to type" badge a
    # white glyph measures 1.71:1, unreadable at tray size. Shared with the Linux
    # painter so the two platforms stay legible in the same way.
    return render_mark(_ICON_PX, fill=color_hex, wave=False, glyph_colour=glyph_for(color_hex))


class WindowsTray:
    """TrayBackend implementation for Windows, backed by pystray."""

    def __init__(self) -> None:
        # pystray is imported lazily, so the concrete Icon type is not nameable here.
        self._icon: Any = None
        self._on_quit: Callable[[], None] | None = None
        self._lock = threading.Lock()

    def run(self, on_quit: Callable[[], None]) -> None:
        try:
            import pystray  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "pystray is not installed. Install with `pip install pystray Pillow` "
                "or run the daemon without the tray."
            ) from exc

        self._on_quit = on_quit

        def _quit_clicked(icon, _item) -> None:  # noqa: ANN001
            icon.stop()

        def _notify(icon, title: str, body: str) -> None:  # noqa: ANN001
            # `fit_balloon` here rather than at the call sites, because this is the
            # single point that reaches Shell_NotifyIcon: a body over 255 wide chars
            # overruns `NOTIFYICONDATA.szInfo` and Windows drops the balloon whole —
            # no exception, nothing to log, a menu entry that silently does nothing.
            # That has shipped twice (About, then Check for updates), so the fix
            # belongs where it cannot be forgotten by the next entry.
            try:
                icon.notify(fit_balloon(body), fit_balloon_title(title))
            except Exception:
                log.debug("tray notification failed", exc_info=True)

        def _settings_clicked(icon, _item) -> None:  # noqa: ANN001
            # A menu click with no visible effect reads as a frozen tray, so a
            # failed launch is reported rather than swallowed.
            if not launch_settings():
                _notify(icon, "YazSes", "Could not open Settings — is `yazses` on PATH?")

        def _link_clicked(url: str):
            def _handler(icon, _item) -> None:  # noqa: ANN001
                if not open_link(url):
                    _notify(icon, "YazSes", f"Could not open your browser. The link is: {url}")

            return _handler

        def _about_clicked(icon, _item) -> None:  # noqa: ANN001
            # pystray has no dialog, so About is a notification. Windows gives that
            # body a 256-wide-char buffer (`NOTIFYICONDATA.szInfo`); the full About
            # text is 347 and overran it, which is why About appeared to do nothing
            # at all. `balloon_body()` trims to fit by dropping whole lines, keeping
            # the version — the one thing About is opened for — at the top.
            _notify(icon, about_title(), balloon_body())

        def _update_clicked(icon, _item) -> None:  # noqa: ANN001
            # Off the UI thread: the check hits the network and would freeze the menu.
            _notify(icon, "YazSes", "Checking for updates…")

            def _work() -> None:
                title, body = describe_update()
                _notify(icon, title, body)

            threading.Thread(target=_work, name="tray-update-check", daemon=True).start()

        def _meeting_clicked(action: str):
            def _handler(icon, _item) -> None:  # noqa: ANN001
                # Off the UI thread: starting a meeting builds the recorder and may
                # construct a diarizer, and a pystray menu blocked on that is a frozen
                # icon. The daemon's own answer — including a refusal — comes back as
                # the notification.
                def _work() -> None:
                    from yazses.tray.meeting import run_meeting_action

                    _notify(icon, *run_meeting_action(action))

                threading.Thread(target=_work, name="tray-meeting", daemon=True).start()

            return _handler

        # The same Help/About/update entries the Linux and macOS trays have. "Help" used
        # to be a disabled placeholder here — a menu item that did nothing when clicked.
        help_menu = pystray.Menu(
            *(pystray.MenuItem(label, _link_clicked(url)) for label, url in help_links())
        )
        menu = pystray.Menu(
            pystray.MenuItem("YazSes", None, enabled=False),
            pystray.Menu.SEPARATOR,
            # The same entry the Linux and macOS trays have (#63).
            pystray.MenuItem(SETTINGS_LABEL, _settings_clicked),
            pystray.Menu.SEPARATOR,
            # Meeting Mode. Both entries are always present and always clickable: a
            # pystray menu is built once here and cannot be re-derived per open the way
            # the Qt tray's is, so the daemon's refusal ("a meeting is already running")
            # is what tells the user which of the two applied.
            pystray.MenuItem(MEETING_START_LABEL, _meeting_clicked("meeting_start")),
            pystray.MenuItem(MEETING_STOP_LABEL, _meeting_clicked("meeting_stop")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Pause hotkey", None, enabled=False),
            pystray.MenuItem(HELP_LABEL, help_menu),
            pystray.MenuItem(ABOUT_LABEL, _about_clicked),
            pystray.MenuItem(UPDATE_LABEL, _update_clicked),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", _quit_clicked),
        )

        # Seed through the same policy as every later update, so the icon the user
        # first sees is not drawn by a second, divergent code path.
        color, tooltip = icon_spec(status_from_model(TrayModel()))
        self._icon = pystray.Icon(
            "yazses",
            _make_icon(color),
            tooltip[:_TOOLTIP_MAX],
            menu,
        )
        log.info("Launching pystray tray (blocks the calling thread)")
        try:
            self._icon.run()
        finally:
            if self._on_quit is not None:
                self._on_quit()

    def set_state(self, model: TrayModel) -> None:
        # Colour and tooltip come from the shared policy in tray/menu.py, the same
        # one the Linux tray uses. This backend used to keep a private seven-entry
        # colour table, so Windows had different colours for the same daemon state,
        # no purple command mode, no yellow "nowhere to type", and five TrayState
        # members that fell through to idle blue.
        status = status_from_model(model)
        with self._lock:
            if self._icon is None:
                return
            try:
                color, tooltip = icon_spec(status)
                self._icon.icon = _make_icon(color)
                self._icon.title = tooltip[:_TOOLTIP_MAX]
            except Exception:
                log.exception("Tray icon update failed")

    def notify(self, title: str, body: str) -> None:
        """Show a balloon toast from the tray icon.

        Windows has no libnotify, so the daemon cannot toast at all — every
        self-healing event (the mic auto-heal, a VAD retune, a silent streak) was
        written only to a log file. The daemon now relays them here through the
        `status` reply the tray is already polling. pystray's balloon carries no
        buttons, so the body must already spell out the fix — which is exactly
        what `system/notify.py` builds for its no-actions fallback.
        """
        with self._lock:
            if self._icon is None:
                return
            try:
                # Fitted for the same reason as the menu's own notifier: these
                # relayed daemon messages carry a fix in prose (the mic auto-heal
                # names the device and what to do), so they are the longest bodies
                # the tray shows and the likeliest to be silently discarded.
                self._icon.notify(fit_balloon(body), fit_balloon_title(title))
            except Exception:
                log.debug("tray notification failed", exc_info=True)

    def stop(self) -> None:
        with self._lock:
            if self._icon is not None:
                try:
                    self._icon.stop()
                except Exception:
                    log.exception("Tray stop raised")


def open_link(url: str) -> bool:
    """Open a Help/About link in the browser. Never raises; returns the handoff."""
    from yazses.system.browser import open_url

    return open_url(url)


def launch_settings() -> bool:
    """Open the settings window, detached. Never blocks the tray thread."""
    import subprocess

    from yazses.tray.launch import settings_command

    try:
        subprocess.Popen(
            # Not `["yazses", "settings"]`: the installer build puts no `yazses` on
            # PATH, so that spelling made this button impossible on the one install
            # whose users have no terminal to fall back to.
            settings_command(),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return True
    except Exception:
        log.exception("tray settings launch failed")
        return False
