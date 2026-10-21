"""`yazses stop` stops YazSes, tray included, instead of being undone by it.

The tray restarts a daemon that disappears (on Windows nothing else does), and it could
not tell a crash from a user's `yazses stop`. So `stop` printed "YazSes stopped" and the
tray had a new daemon up within seconds: a new PID inside 10 s, measured on Windows 11.

`stop` now leaves a note first (`system/stop_request.py`). A tray that finds the daemon
gone and a note newer than itself closes. A crash leaves no note, so recovery is
unchanged; `restart` writes none, so it keeps the tray.
"""

from __future__ import annotations

import time

import pytest
from typer.testing import CliRunner

from yazses import cli
from yazses.platform.base import TrayState
from yazses.system.stop_request import (
    FILENAME,
    clear_stop_request,
    request_stop,
    stop_requested_since,
)
from yazses.tray.app import _RECONNECT_GRACE_S, unreachable_decision

_PAST_GRACE = _RECONNECT_GRACE_S + 1


# ---- the note ---------------------------------------------------------------


def test_no_note_means_no_stop(tmp_path):
    assert not stop_requested_since(tmp_path, 0.0)


def test_a_note_left_after_the_tray_started_counts(tmp_path):
    tray_started = time.time() - 60
    request_stop(tmp_path)
    assert stop_requested_since(tmp_path, tray_started)


def test_a_note_older_than_the_tray_is_ignored(tmp_path):
    """A tray launched after a stop must not close because of that old stop."""
    request_stop(tmp_path)
    assert not stop_requested_since(tmp_path, time.time() + 60)


def test_an_unreadable_note_is_no_note(tmp_path):
    (tmp_path / FILENAME).write_text("not a time", encoding="utf-8")
    assert not stop_requested_since(tmp_path, 0.0)


def test_clearing_removes_the_note_and_tolerates_none(tmp_path):
    request_stop(tmp_path)
    clear_stop_request(tmp_path)
    clear_stop_request(tmp_path)
    assert not (tmp_path / FILENAME).exists()


# ---- the tray's decision ----------------------------------------------------


class TestTrayDecision:
    def test_a_requested_stop_closes_the_tray_instead_of_restarting(self) -> None:
        d = unreachable_decision(True, _PAST_GRACE, daemon_running=False, stop_requested=True)
        assert d.close_tray is True
        assert d.relaunch is False

    def test_it_closes_without_waiting_out_the_restart_grace(self) -> None:
        d = unreachable_decision(True, 0.5, daemon_running=False, stop_requested=True)
        assert d.close_tray is True

    def test_a_daemon_still_shutting_down_is_waited_for(self) -> None:
        d = unreachable_decision(True, _PAST_GRACE, daemon_running=True, stop_requested=True)
        assert not d.close_tray and not d.relaunch and not d.give_up
        assert d.state is TrayState.IDLE  # stopping on request is not an error

    def test_a_crash_still_restarts_the_daemon(self) -> None:
        """The reason the tray restarts daemons at all must survive this change."""
        d = unreachable_decision(True, _PAST_GRACE, daemon_running=False)
        assert d.relaunch is True and not d.close_tray


# ---- the commands -----------------------------------------------------------


@pytest.fixture
def platform(monkeypatch, tmp_path):
    seen: dict[str, bool] = {}

    class _Lifecycle:
        def read_pid(self):
            return 4242

        def is_running(self):
            return True

        def stop_daemon(self, _pid):
            # The note must already be there when the daemon goes, or the tray
            # can poll in between and restart it.
            seen["note_before_stop"] = (tmp_path / FILENAME).exists()

    class _Paths:
        data_dir = tmp_path
        ipc_socket = str(tmp_path / "none.sock")

    class _Platform:
        name = "linux"
        lifecycle = _Lifecycle()
        paths = _Paths()

        @staticmethod
        def ipc_client_factory(_socket):
            class _C:
                def is_reachable(self):
                    return False

                def call(self, *_a, **_k):
                    return {}

            return _C()

    p = _Platform()
    monkeypatch.setattr(cli, "get_platform", lambda: p)
    return p, seen


def test_stop_leaves_the_note_before_stopping_the_daemon(platform, tmp_path):
    _, seen = platform
    r = CliRunner().invoke(cli.app, ["stop"])
    assert r.exit_code == 0, r.output
    assert seen["note_before_stop"] is True
    assert stop_requested_since(tmp_path, time.time() - 60)


def test_stop_still_stops_when_the_note_cannot_be_written(platform, monkeypatch):
    _, seen = platform

    def refuse(_data_dir):
        raise PermissionError("read-only profile")

    monkeypatch.setattr("yazses.system.stop_request.request_stop", refuse)
    r = CliRunner().invoke(cli.app, ["stop"])
    assert r.exit_code == 0, r.output
    assert "note_before_stop" in seen  # the daemon was stopped regardless
    assert "quit the tray" in r.output


def test_start_forgets_an_earlier_stop(platform, tmp_path):
    p, _ = platform
    request_stop(tmp_path)
    cli._clear_stop_request(p)
    assert not (tmp_path / FILENAME).exists()


def test_start_with_a_platform_that_has_no_paths_is_left_alone():
    class _Bare:
        pass

    cli._clear_stop_request(_Bare())  # must not raise
