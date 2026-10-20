"""`yazses headpointer ...`: the escape hatch has to be a command you can actually type (#405).

A continuous pointer needs a way out that does not depend on steering the pointer, so each
subcommand here takes no coordinate and no precision and is one IPC call to the daemon. The
daemon is a stub that records the call; what is asserted is the request each command sends and
what a person is told, including when the answer is "not running" or "refused".
"""
from __future__ import annotations

import types

import pytest
from typer.testing import CliRunner

from yazses import cli
from yazses.ipc.client import IpcUnreachableError

runner = CliRunner()


class Daemon:
    def __init__(self, reply=None, error: Exception | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.reply = reply if reply is not None else {"ok": True}
        self.error = error

    def call(self, method: str, **params):
        self.calls.append((method, params))
        if self.error:
            raise self.error
        return self.reply


@pytest.fixture
def daemon(monkeypatch, tmp_path):
    stub = Daemon()
    platform = types.SimpleNamespace(
        paths=types.SimpleNamespace(ipc_socket=tmp_path / "sock"),
        ipc_client_factory=lambda _sock: stub,
    )
    monkeypatch.setattr(cli, "get_platform", lambda: platform)
    return stub


@pytest.mark.parametrize(
    ("args", "action", "extra"),
    [
        (["recenter"], "recenter", {}),
        (["pause"], "pause", {}),
        (["resume"], "resume", {}),
        (["clutch"], "clutch", {"source": "cli", "active": True}),
        (["clutch", "--off"], "clutch", {"source": "cli", "active": False}),
        (["dwell", "on"], "dwell", {"enabled": True}),
        (["dwell", "OFF"], "dwell", {"enabled": False}),
    ],
)
def test_each_subcommand_sends_one_headpointer_request(daemon, args, action, extra):
    result = runner.invoke(cli.app, ["headpointer", *args])
    assert result.exit_code == 0, result.output
    assert daemon.calls == [("headpointer", {"action": action, **extra})]


def test_a_refusal_is_reported_with_its_reason_and_a_nonzero_exit(daemon):
    daemon.reply = {"ok": False, "reason": "headpointer: no signal yet"}
    result = runner.invoke(cli.app, ["headpointer", "resume"])
    assert result.exit_code == 1
    assert "no signal yet" in result.output


def test_no_daemon_is_said_plainly(daemon):
    daemon.error = IpcUnreachableError("nope")
    result = runner.invoke(cli.app, ["headpointer", "pause"])
    assert result.exit_code == 1
    assert "not running" in result.output


def test_dwell_rejects_anything_but_on_or_off(daemon):
    result = runner.invoke(cli.app, ["headpointer", "dwell", "maybe"])
    assert result.exit_code == 2
    assert daemon.calls == []


def test_status_of_a_dormant_pointer_says_why(daemon):
    daemon.reply = {"ok": True, "active": False, "reason": "no shared camera source"}
    result = runner.invoke(cli.app, ["headpointer", "status"])
    assert result.exit_code == 0
    assert "not running" in result.output and "no shared camera source" in result.output


def test_status_of_a_running_pointer_shows_state_flags_and_dwell_progress(daemon):
    daemon.reply = {
        "ok": True, "active": True, "state": "tracking", "reason": "", "backend": "x11",
        "calibrated": True, "paused": False, "clutched": False,
        "dwell_enabled": True, "dwell_progress": 0.4, "fault": "",
    }
    result = runner.invoke(cli.app, ["headpointer", "status"])
    assert result.exit_code == 0
    for text in ("tracking", "x11", "40% to a click", "released"):
        assert text in result.output


def test_status_says_dwell_is_off_and_that_it_will_never_click(daemon):
    daemon.reply = {"ok": True, "active": True, "state": "tracking", "dwell_enabled": False}
    result = runner.invoke(cli.app, ["headpointer", "status"])
    assert "never click" in result.output


def test_status_points_at_the_command_that_clears_a_fault(daemon):
    daemon.reply = {"ok": True, "active": True, "state": "faulted", "fault": "backend died"}
    result = runner.invoke(cli.app, ["headpointer", "status"])
    assert "backend died" in result.output and "yazses headpointer resume" in result.output


def test_status_says_the_pointer_is_waiting_for_the_users_permission(daemon):
    daemon.reply = {
        "ok": True, "active": True, "state": "pending_consent",
        "reason": "waiting for you to answer the desktop's Remote Desktop permission dialog",
        "backend": "portal", "consent": "pending_consent", "fault": "",
    }
    result = runner.invoke(cli.app, ["headpointer", "status"])
    assert result.exit_code == 0
    assert "state:    pending_consent" in result.output
    assert "consent:  PENDING" in result.output
    assert "starts by itself" in result.output
    # It is not a fault, so it must not send the user to the command that clears one.
    assert "headpointer resume" not in result.output


def test_status_says_a_refusal_is_denied_and_how_to_be_asked_again(daemon):
    daemon.reply = {
        "ok": True, "active": True, "state": "denied", "backend": "portal",
        "consent": "denied", "fault": "",
    }
    result = runner.invoke(cli.app, ["headpointer", "status"])
    assert "consent:  DENIED" in result.output
    assert "yazses restart" in result.output


@pytest.mark.parametrize(
    ("consent", "needle"),
    [
        ("granted", "granted for this session"),
        ("not_required", "not needed on this backend"),
        ("unavailable", "offers no pointer"),
    ],
)
def test_status_words_each_other_consent_state(daemon, consent, needle):
    daemon.reply = {"ok": True, "active": True, "state": "tracking", "backend": "x", "consent": consent}
    result = runner.invoke(cli.app, ["headpointer", "status"])
    assert needle in result.output


def test_status_of_a_backend_with_no_consent_concept_prints_no_consent_line(daemon):
    daemon.reply = {"ok": True, "active": True, "state": "tracking", "backend": "x11", "consent": ""}
    result = runner.invoke(cli.app, ["headpointer", "status"])
    assert "consent:" not in result.output
