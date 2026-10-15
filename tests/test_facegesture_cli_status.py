"""`yazses facegesture status`: why a bound select / confirm / cancel did or did not act.

The daemon is a stub returning a canned reply; what is asserted is the request sent and what a
person is told, including "daemon not running", "face switch off" and "nothing bound".
"""
from __future__ import annotations

import types

import pytest
from typer.testing import CliRunner

from yazses import cli
from yazses.ipc.client import IpcUnreachableError

runner = CliRunner()


class Daemon:
    def __init__(self, reply=None, error=None):
        self.calls = []
        self.reply = reply
        self.error = error

    def call(self, method, **params):
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


def test_status_asks_the_daemon_and_prints_each_actions_last_outcome(daemon):
    daemon.reply = {
        "ok": True, "active": True,
        "actions": [
            {"action": "select", "result": "refused", "reason": "the Head-Pointer is paused",
             "age_s": 3.0, "done": 1, "refused": 2, "noop": 0},
            {"action": "confirm", "result": "unused", "reason": "", "age_s": None,
             "done": 0, "refused": 0, "noop": 0},
        ],
    }
    result = runner.invoke(cli.app, ["facegesture", "status"])
    assert result.exit_code == 0, result.output
    assert daemon.calls == [("facegesture", {"action": "status"})]
    assert "select: last refused (the Head-Pointer is paused)" in result.output
    assert "done 1, refused 2" in result.output
    assert "confirm: bound, not used yet" in result.output


def test_nothing_bound_says_how_to_bind(daemon):
    daemon.reply = {"ok": True, "active": True, "actions": []}
    result = runner.invoke(cli.app, ["facegesture", "status"])
    assert result.exit_code == 0
    assert "No select, confirm or cancel gesture is bound" in result.output


def test_face_switch_off_is_said_with_its_reason(daemon):
    daemon.reply = {"ok": True, "active": False, "reason": "the face switch is not running"}
    result = runner.invoke(cli.app, ["facegesture", "status"])
    assert result.exit_code == 0
    assert "not running" in result.output


def test_no_daemon_is_said_plainly_and_exits_nonzero(daemon):
    daemon.error = IpcUnreachableError("nope")
    result = runner.invoke(cli.app, ["facegesture", "status"])
    assert result.exit_code == 1
    assert "not running" in result.output


def test_an_older_daemon_without_the_method_fails_with_a_reason(daemon):
    daemon.reply = {"ok": False, "reason": "unknown method"}
    result = runner.invoke(cli.app, ["facegesture", "status"])
    assert result.exit_code == 1
    assert "unknown method" in result.output
