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

log = logging.getLogger(__name__)


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
                self_inner.menu = ["Pause hotkey", "Help & permissions"]

            @rumps.clicked("Pause hotkey")
            def _on_pause(self_inner, _sender) -> None:
                # Wired via IPC by the tray entry point; no-op here in v0.
                rumps.notification("YazSes", "Pause", "Pausing the dictation hotkey…")

            @rumps.clicked("Help & permissions")
            def _on_help(self_inner, _sender) -> None:
                rumps.notification(
                    "YazSes",
                    "Help",
                    "Grant Accessibility access in System Settings → Privacy & Security → Accessibility.",
                )

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

    def stop(self) -> None:
        try:
            import rumps  # type: ignore[import-not-found]

            rumps.quit_application()
        except Exception:
            log.exception("Tray stop raised")
