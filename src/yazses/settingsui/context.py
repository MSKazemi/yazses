"""What an app page may ask of the window around it. Every effect is injectable."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from yazses.config import Config
from yazses.settingsui.overview import UNRESPONSIVE


@dataclass
class PageContext:
    load_config: Callable[[], Config]
    #: ``client_call(method, **params)`` → the daemon's reply, or ``None``. Blocking.
    #: ``wait_s=`` lengthens the wait for a call the daemon answers slowly.
    client_call: Callable[..., Any]
    #: Whether the daemon process is alive, which tells "slow" from "absent". Blocking.
    daemon_running: Callable[[], bool]
    #: ``run(key, fn, done)``: *fn* off the GUI thread, *done* back on it.
    run: Callable[[str, Callable[[], Any], Callable[[Any], None]], bool]
    #: Both return ``(ok, message)``. Blocking.
    start_daemon: Callable[[], tuple[bool, str]]
    restart_daemon: Callable[[], tuple[bool, str]]
    goto: Callable[[str], None]
    open_path: Callable[[str], None]
    switches: Any
    window: Any
    #: Opens the first-run setup guide again; ``None`` where there is none to open.
    open_setup: Callable[[], Any] | None = None

    def status(self) -> Any:
        """One ``status`` reply that leaves the daemon's notifications for the tray."""
        return self.ask("status", consume_notifications=False)

    def ask(self, method: str, **params: Any) -> Any:
        """``client_call``, but a live daemon that did not answer reads as unresponsive."""
        reply = self.client_call(method, **params)
        if reply is None and self.daemon_running():
            return dict(UNRESPONSIVE)
        return reply
