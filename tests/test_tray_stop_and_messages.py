"""The tray's Stop daemon stays stopped, and every menu action reports what happened.

Three defects, one file:

1. "Stop daemon" sent only `shutdown`. The tray relaunched the daemon five seconds later
   because nothing had left the stop note (`system/stop_request.py`), so the stop was
   undone. The controller now leaves the note before it sends `shutdown`.
2. The Linux handlers announced success ("Pinned to ...", "Stopping the daemon...")
   whatever the daemon answered, and dropped its own words on failure.
3. `meeting.describe` read only `reason`, so a dead-IPC `error` showed as "That did not
   work." The Linux re-calibrate handler had the same mismatch.

Nothing here starts or signals a daemon: the IPC client and the data directory are fakes
and every path is under `tmp_path`.
"""

from __future__ import annotations

import time

import pytest

from yazses.platform.linux.tray import LinuxTray
from yazses.system.stop_request import FILENAME, stop_requested_since
from yazses.tray.controller import TrayController
from yazses.tray.meeting import START, describe


class _FakeClient:
    def __init__(self, reply=None):
        self.calls = []
        self._reply = reply or {"ok": True}

    def call(self, method, **params):
        self.calls.append((method, params))
        return self._reply


class _NoteWatchingClient:
    """Records whether the stop note existed at the moment `shutdown` was sent."""

    def __init__(self, data_dir, raises=None):
        self._data_dir = data_dir
        self._raises = raises
        self.note_at_shutdown = None

    def call(self, method, **params):
        if method == "shutdown":
            self.note_at_shutdown = (self._data_dir / FILENAME).exists()
            if self._raises is not None:
                raise self._raises
        return {"ok": True}


# ---- 1. Stop daemon leaves the stop note ------------------------------------


def test_stop_daemon_leaves_the_note_before_shutdown_is_sent(tmp_path):
    client = _NoteWatchingClient(tmp_path)
    before = time.time()

    TrayController(client, data_dir=tmp_path).stop_daemon()

    assert client.note_at_shutdown is True
    assert stop_requested_since(tmp_path, before - 1)


def test_stop_daemon_still_sends_shutdown_when_the_note_cannot_be_written(tmp_path):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x", encoding="utf-8")
    client = _FakeClient()

    result = TrayController(client, data_dir=blocker / "data").stop_daemon()

    assert client.calls == [("shutdown", {})]
    assert result == {"ok": True}


def test_stop_daemon_still_sends_shutdown_when_writing_the_note_raises_anything(
    tmp_path, monkeypatch
):
    def boom(_data_dir):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr("yazses.tray.controller.request_stop", boom)
    client = _FakeClient()

    TrayController(client, data_dir=tmp_path).stop_daemon()

    assert client.calls == [("shutdown", {})]


def test_a_refused_shutdown_takes_its_note_back(tmp_path):
    """A stop that did not happen must not leave a note: a wedged daemon would then be
    waited for forever instead of reported as not responding."""
    client = _NoteWatchingClient(tmp_path, raises=RuntimeError("connection refused"))

    result = TrayController(client, data_dir=tmp_path).stop_daemon()

    assert client.note_at_shutdown is True
    assert not (tmp_path / FILENAME).exists()
    assert result["ok"] is False
    assert "connection refused" in result["error"]


def test_restart_writes_no_stop_note(tmp_path):
    """`yazses restart` must keep the tray: it is not a stop."""
    ctrl = TrayController(_FakeClient(), launcher=lambda argv: None, data_dir=tmp_path)

    assert ctrl.restart() is True
    assert not (tmp_path / FILENAME).exists()


# ---- 2 and 3. The outcome is reported, and the daemon's words are kept ------


class _OutcomeController:
    def __init__(self, *, pin=None, stop=None, recalibrate=None):
        self._replies = {"pin": pin, "stop": stop, "recalibrate": recalibrate}

    def pin(self, device):
        return self._replies["pin"]

    def stop_daemon(self):
        return self._replies["stop"]

    def recalibrate(self):
        return self._replies["recalibrate"]


@pytest.fixture
def notes(monkeypatch):
    shown: list[tuple[str, str]] = []

    def make(controller):
        tray = LinuxTray()
        tray._controller = controller
        monkeypatch.setattr(tray, "_notify", lambda title, body: shown.append((title, body)))
        return tray

    make.shown = shown
    return make


def test_stop_daemon_says_stopping_when_the_daemon_accepted_it(notes):
    tray = notes(_OutcomeController(stop={"ok": True}))

    tray._on_stop_daemon()

    assert notes.shown == [("YazSes", "Stopping the daemon…")]


def test_stop_daemon_failure_says_so_and_names_the_error(notes):
    tray = notes(_OutcomeController(stop={"ok": False, "error": "connection refused"}))

    tray._on_stop_daemon()

    (_, body), = notes.shown
    assert "connection refused" in body
    assert "Stopping the daemon" not in body


def test_stop_daemon_failure_names_the_daemons_reason(notes):
    tray = notes(_OutcomeController(stop={"ok": False, "reason": "already stopping"}))

    tray._on_stop_daemon()

    (_, body), = notes.shown
    assert "already stopping" in body
    assert "Stopping the daemon" not in body


def test_pin_failure_is_not_reported_as_pinned(notes):
    tray = notes(_OutcomeController(pin={"ok": False, "error": "no such device"}))

    tray._on_pick_device("USB")

    (_, body), = notes.shown
    assert "no such device" in body
    assert "Pinned" not in body


def test_pin_success_still_says_pinned(notes):
    tray = notes(_OutcomeController(pin={"ok": True, "device": "USB"}))

    tray._on_pick_device("USB")

    assert notes.shown == [("YazSes microphone", "Pinned to 'USB'.")]


def test_recalibrate_failure_shows_the_daemons_error(notes):
    tray = notes(_OutcomeController(recalibrate={"ok": False, "error": "socket gone"}))

    tray._on_recalibrate()

    (_, body), = notes.shown
    assert "socket gone" in body


def test_meeting_describe_shows_an_error_when_no_reason_is_present():
    assert describe(START, {"ok": False, "error": "connection refused"}) == (
        "YazSes",
        "connection refused",
    )


def test_meeting_describe_shows_a_reason_when_no_error_is_present():
    assert describe(START, {"ok": False, "reason": "meeting mode is off"}) == (
        "YazSes",
        "meeting mode is off",
    )
