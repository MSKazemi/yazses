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

from yazses.platform.base import TrayModel, TrayState
from yazses.tray.about import about_lines, about_title, help_links
from yazses.tray.menu import (
    ABOUT_LABEL,
    HELP_LABEL,
    SETTINGS_LABEL,
    UPDATE_LABEL,
)
from yazses.tray.updates import check_and_describe

log = logging.getLogger(__name__)


_GLYPH_COLOR = {
    TrayState.LOADING: (170, 170, 170, 255),     # light grey, "still warming up"
    TrayState.IDLE: (40, 130, 200, 255),         # blue
    TrayState.RECORDING: (220, 60, 60, 255),     # red
    TrayState.TRANSCRIBING: (255, 180, 30, 255), # amber
    TrayState.INJECTING: (60, 180, 90, 255),     # green
    TrayState.PAUSED: (140, 140, 140, 255),      # grey
    TrayState.ERROR: (200, 40, 80, 255),         # magenta
}


def _make_icon(state: TrayState):
    from PIL import Image, ImageDraw  # type: ignore[import-not-found]

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    color = _GLYPH_COLOR.get(state, _GLYPH_COLOR[TrayState.IDLE])
    # Solid filled circle. Simple, recognisable at 16×16.
    draw.ellipse((4, 4, 60, 60), fill=color)
    return img


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

        def _settings_clicked(icon, _item) -> None:  # noqa: ANN001
            # A menu click with no visible effect reads as a frozen tray, so a
            # failed launch is reported rather than swallowed.
            if not launch_settings():
                try:
                    icon.notify("Could not open Settings — is `yazses` on PATH?", "YazSes")
                except Exception:
                    log.debug("tray notification failed", exc_info=True)

        def _notify(icon, title: str, body: str) -> None:  # noqa: ANN001
            try:
                icon.notify(body, title)
            except Exception:
                log.debug("tray notification failed", exc_info=True)

        def _link_clicked(url: str):
            def _handler(icon, _item) -> None:  # noqa: ANN001
                if not open_link(url):
                    _notify(icon, "YazSes", f"Could not open your browser. The link is: {url}")

            return _handler

        def _about_clicked(icon, _item) -> None:  # noqa: ANN001
            # pystray has no dialog, so About is a notification. The version — the one
            # thing About is opened for — leads the body so it survives truncation.
            _notify(icon, about_title(), "\n".join(about_lines()))

        def _update_clicked(icon, _item) -> None:  # noqa: ANN001
            # Off the UI thread: the check hits the network and would freeze the menu.
            _notify(icon, "YazSes", "Checking for updates…")

            def _work() -> None:
                title, body = check_and_describe()
                _notify(icon, title, body)

            threading.Thread(target=_work, name="tray-update-check", daemon=True).start()

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
            pystray.MenuItem("Pause hotkey", None, enabled=False),
            pystray.MenuItem(HELP_LABEL, help_menu),
            pystray.MenuItem(ABOUT_LABEL, _about_clicked),
            pystray.MenuItem(UPDATE_LABEL, _update_clicked),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", _quit_clicked),
        )

        self._icon = pystray.Icon(
            "yazses",
            _make_icon(TrayState.IDLE),
            "YazSes",
            menu,
        )
        log.info("Launching pystray tray (blocks the calling thread)")
        try:
            self._icon.run()
        finally:
            if self._on_quit is not None:
                self._on_quit()

    def set_state(self, model: TrayModel) -> None:
        with self._lock:
            if self._icon is None:
                return
            try:
                self._icon.icon = _make_icon(model.state)
                self._icon.title = f"YazSes — {model.state.value}"
            except Exception:
                log.exception("Tray icon update failed")

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

    try:
        subprocess.Popen(
            ["yazses", "settings"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return True
    except Exception:
        log.exception("tray settings launch failed")
        return False
