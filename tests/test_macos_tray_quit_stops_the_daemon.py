"""Choosing "Quit" in the macOS menu bar must tell the daemon to shut down (#578).

rumps' Quit item calls `NSApplication.terminate:`, which ends the process from inside
the event loop. `App.run()` therefore never returns, and the line after it -- the only
place the tray sent the IPC `shutdown` -- never ran. The daemon outlived "Quit" for
days (launchd restarts only a crash), kept the permission it read when its keyboard tap
was created, and the next launch exited as a duplicate.

The rumps API is faked here, as elsewhere in the macOS tests ("rumps is tested manually
on a Mac"): what matters is the one property of the real library the bug turns on --
that Quit does not return from `run()`.
"""

from __future__ import annotations

import sys
import types

import pytest

from yazses.platform.macos.tray import MacosTray


class _Emitter:
    def __init__(self) -> None:
        self.callbacks: list = []

    def register(self, func):
        self.callbacks.append(func)
        return func

    def emit(self) -> None:
        for cb in list(self.callbacks):
            cb()


def _install_fake_rumps(monkeypatch, *, quit_returns: bool):
    events = types.ModuleType("rumps.events")
    events.before_quit = _Emitter()

    class App:
        def __init__(self, *a, **k):
            self.menu = None
            self.title = ""

        def run(self):
            # Quit: Cocoa posts applicationWillTerminate (-> before_quit) and then
            # exits the process; control only comes back if the loop is stopped.
            events.before_quit.emit()
            if not quit_returns:
                raise SystemExit(0)

    rumps = types.ModuleType("rumps")
    rumps.App = App
    rumps.events = events
    rumps.clicked = lambda *a, **k: (lambda f: f)
    monkeypatch.setitem(sys.modules, "rumps", rumps)
    monkeypatch.setitem(sys.modules, "rumps.events", events)


def test_quit_that_exits_the_process_still_tells_the_daemon(monkeypatch):
    _install_fake_rumps(monkeypatch, quit_returns=False)
    told: list[str] = []

    with pytest.raises(SystemExit):
        MacosTray().run(lambda: told.append("shutdown"))

    assert told == ["shutdown"]


def test_a_loop_that_returns_tells_the_daemon_exactly_once(monkeypatch):
    _install_fake_rumps(monkeypatch, quit_returns=True)
    told: list[str] = []

    MacosTray().run(lambda: told.append("shutdown"))

    assert told == ["shutdown"]
