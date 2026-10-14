"""`yazses handsfree status | pause | resume` (#420).

The same actions the settings panel offers, spelled for a terminal, a voice command, a switch
or a script — each takes no pointer position. The CLI talks to the daemon only through the
IPC client, so every case here injects one.
"""
from __future__ import annotations

import types

import pytest
from typer.testing import CliRunner

from yazses import cli
from yazses.cli import app
from yazses.config import Config
from yazses.ipc.client import IpcUnreachableError

runner = CliRunner()


class _Client:
    def __init__(self, replies):
        self.replies = replies
        self.calls = []

    def is_reachable(self):
        return True

    def call(self, method, **params):
        self.calls.append((method, params))
        reply = self.replies.get(method)
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.fixture
def client(monkeypatch):
    def install(replies):
        c = _Client(replies)
        monkeypatch.setattr(cli, "get_platform", lambda: _P(c))
        return c

    return install


class _P:
    """A platform that is only a socket path, a config path and an IPC client."""

    name = "linux"

    def __init__(self, client):
        self._client = client
        self.paths = types.SimpleNamespace(
            ipc_socket="/tmp/nope.sock", data_dir="/tmp/yazses-test-nope",
            config_file="/tmp/yazses-test-nope/config.toml",
        )
        self.permissions = types.SimpleNamespace()

    def ipc_client_factory(self, _path):
        return self._client


def test_pause_sends_one_parameter_and_reports_the_scope(client):
    c = client({"handsfree": {"ok": True, "scope": ["all hands-free input"]}})
    result = runner.invoke(app, ["handsfree", "pause"])
    assert result.exit_code == 0, result.output
    assert c.calls == [("handsfree", {"action": "pause"})]
    assert "Paused: all hands-free input." in result.output


def test_resume_reports_what_was_rearmed(client):
    client({"handsfree": {"ok": True, "scope": ["headpointer"]}})
    result = runner.invoke(app, ["handsfree", "resume"])
    assert result.exit_code == 0 and "Resumed: headpointer." in result.output


def test_a_refused_resume_exits_nonzero_with_the_reason(client):
    client({"handsfree": {"ok": False, "scope": ["headpointer"],
                          "reason": "not ready to re-arm: facegesture"}})
    result = runner.invoke(app, ["handsfree", "resume"])
    assert result.exit_code == 1
    assert "not ready to re-arm: facegesture" in result.output
    assert "Re-armed so far: headpointer." in result.output


def test_a_dead_daemon_is_a_sentence_and_exit_1(client):
    client({"handsfree": IpcUnreachableError("no socket")})
    result = runner.invoke(app, ["handsfree", "pause"])
    assert result.exit_code == 1 and "Daemon is not running" in result.output


def test_an_older_daemon_without_the_method_says_to_restart(client):
    client({"handsfree": RuntimeError("method not found")})
    result = runner.invoke(app, ["handsfree", "pause"])
    assert result.exit_code == 1 and "yazses restart" in result.output


def test_status_prints_the_panel_and_never_the_camera(client, monkeypatch):
    client({"status": {"state": "idle"}})
    monkeypatch.setattr("yazses.config.load_config", lambda _p: Config())
    result = runner.invoke(app, ["handsfree", "status"])
    assert result.exit_code == 0, result.output
    assert "Hands-free camera controls are off." in result.output
    assert "yazses handsfree pause" in result.output


def test_every_command_the_panel_names_exists():
    """The panel prints a CLI spelling for each action; each must be a real command."""
    from yazses.handsfree.panel import PanelInputs, build_panel

    model = build_panel(PanelInputs())
    for spec in (*model.actions, *model.dwell):
        parts = spec.cli.split()[1:]  # drop "yazses"
        result = runner.invoke(app, [*parts[:2], "--help"])
        assert result.exit_code == 0, (spec.cli, result.output)
