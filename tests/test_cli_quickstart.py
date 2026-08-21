"""`yazses quickstart` onboarding + actionable status/stop messages."""
from __future__ import annotations

import types

from typer.testing import CliRunner

import yazses.cli as cli

runner = CliRunner()


class _Lifecycle:
    def __init__(self, running):
        self._running = running

    def is_running(self):
        return self._running

    def read_pid(self):
        return 4321 if self._running else None

    def stop_daemon(self, pid):
        pass


class _Paths:
    config_file = "/tmp/yazses-qs-config.toml"
    ipc_socket = "/tmp/yazses-qs.sock"


class _Platform:
    default_hotkey = "right_ctrl"
    name = "linux"

    def __init__(self, running=False):
        self.lifecycle = _Lifecycle(running)
        self.paths = _Paths()


def _patch(monkeypatch, plat):
    monkeypatch.setattr(cli, "get_platform", lambda: plat)
    monkeypatch.setattr(cli, "_resolved_hotkey", lambda p: "right_ctrl")


# ---- quickstart ------------------------------------------------------------


def test_quickstart_shows_three_steps_and_hotkey(monkeypatch):
    plat = _Platform(running=False)
    _patch(monkeypatch, plat)
    result = runner.invoke(cli.app, ["quickstart"])
    assert result.exit_code == 0
    out = result.output
    assert "1." in out and "2." in out and "3." in out
    assert "yazses start" in out
    assert "right_ctrl" in out  # the resolved hotkey to hold
    assert "offline" in out.lower()  # reassures it's local/private


def test_quickstart_adapts_when_already_running(monkeypatch):
    plat = _Platform(running=True)
    _patch(monkeypatch, plat)
    # No prerequisites work needed on a machine that's already provisioned.
    monkeypatch.setattr(
        "yazses.system.setup.build_plan",
        lambda: types.SimpleNamespace(is_noop=True),
    )
    result = runner.invoke(cli.app, ["quickstart"])
    assert result.exit_code == 0
    assert "already running" in result.output.lower()


def test_quickstart_on_unprovisioned_machine_points_at_setup(monkeypatch):
    # The most important onboarding path: a fresh machine that still needs setup.
    plat = _Platform(running=False)
    _patch(monkeypatch, plat)
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr(
        "yazses.system.setup.build_plan",
        lambda: types.SimpleNamespace(is_noop=False),
    )
    result = runner.invoke(cli.app, ["quickstart"])
    assert result.exit_code == 0
    assert "yazses setup" in result.output
    assert "input" in result.output.lower()  # mentions the input-group step


def test_quickstart_changes_nothing(monkeypatch):
    # Guard: quickstart must be read-only (no start/stop side effects).
    plat = _Platform(running=False)
    _patch(monkeypatch, plat)
    started = []
    monkeypatch.setattr(plat.lifecycle, "stop_daemon", lambda pid: started.append("stop"))
    result = runner.invoke(cli.app, ["quickstart"])
    assert result.exit_code == 0
    assert started == []


def test_quickstart_asks_for_a_star_with_a_usable_link(monkeypatch):
    # A project nobody has heard of is found by word of mouth or not at all, and
    # nothing else in the CLI or README ever asks. The repo URL must be present
    # and correct, or the ask is worse than useless.
    plat = _Platform(running=False)
    _patch(monkeypatch, plat)
    result = runner.invoke(cli.app, ["quickstart"])
    assert result.exit_code == 0
    assert "https://github.com/MSKazemi/yazses" in result.output
    assert "star" in result.output.lower()


def test_quickstart_star_ask_does_not_nag_or_block(monkeypatch):
    # Guard against this turning into a nag: it appears once per invocation of an
    # explicitly-requested, read-only command, and never prompts for input.
    plat = _Platform(running=False)
    _patch(monkeypatch, plat)
    result = runner.invoke(cli.app, ["quickstart"], input="")
    assert result.exit_code == 0
    assert result.output.lower().count("a star is how") == 1


# ---- actionable status / stop ---------------------------------------------


def test_status_not_running_is_actionable(monkeypatch):
    plat = _Platform(running=False)
    _patch(monkeypatch, plat)
    result = runner.invoke(cli.app, ["status"])
    assert result.exit_code == 0
    assert "yazses start" in result.output
    assert "quickstart" in result.output  # points a new user at onboarding


def test_status_json_not_running(monkeypatch):
    import json
    plat = _Platform(running=False)
    _patch(monkeypatch, plat)
    result = runner.invoke(cli.app, ["status", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["running"] is False
    assert data["state"] == "stopped"
    assert data["pid"] is None
    assert data["ready"] is False


def test_status_json_running(monkeypatch):
    import json
    plat = _Platform(running=True)
    _patch(monkeypatch, plat)
    mock_status = {
        "state": "idle",
        "ready": True,
        "model": "base.en",
        "hotkey": "right_ctrl",
        "injection_backend": "uinput",
        "uptime_s": 42.0,
    }

    class _MockClient:
        def call(self, method):
            if method == "status":
                return mock_status
            raise RuntimeError(f"Unexpected method: {method}")

    plat.ipc_client_factory = lambda _sock: _MockClient()
    result = runner.invoke(cli.app, ["status", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["running"] is True
    assert data["pid"] == 4321
    assert data["state"] == "idle"
    assert data["ready"] is True
    assert data["model"] == "base.en"
    assert data["hotkey"] == "right_ctrl"


def test_status_json_starting_ipc_unreachable(monkeypatch):
    import json
    plat = _Platform(running=True)
    _patch(monkeypatch, plat)

    class _MockClientUnreachable:
        def call(self, method):
            raise cli.IpcUnreachableError("Socket unreachable")

    plat.ipc_client_factory = lambda _sock: _MockClientUnreachable()
    result = runner.invoke(cli.app, ["status", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["running"] is True
    assert data["state"] == "starting"
    assert data["pid"] == 4321
    assert data["ready"] is False


def test_stop_not_running_says_nothing_to_stop(monkeypatch):
    plat = _Platform(running=False)
    _patch(monkeypatch, plat)
    result = runner.invoke(cli.app, ["stop"])
    assert result.exit_code == 1
    assert "nothing to stop" in result.output.lower()


def test_every_command_quickstart_recommends_actually_exists(monkeypatch):
    """Quickstart is the first thing a newcomer reads, so a name that has moved
    breaks their very first action — and nothing here was checking.

    The existing tests pin the *shape* of the page (three steps, the hotkey, the
    star link) and none of them opens the command tree, so renaming or removing a
    recommended command would leave the suite green and the onboarding broken.

    Resolution goes through `typer.main.get_command`, deliberately not an
    `isinstance(..., click.Group)` walk: under Click 8.4 a `TyperGroup` is not a
    `click.Group`, so such a walk finds nothing and passes — the exact way the CLI
    reference guard was blind to ~50 subcommands.
    """
    import re

    import click
    import typer.main

    for running in (False, True):
        _patch(monkeypatch, _Platform(running=running))
        out = runner.invoke(cli.app, ["quickstart"]).output

        # `yazses <cmd>` as recommended, ignoring the bare program name and flags.
        named = {m for m in re.findall(r"\byazses ([a-z][a-z-]+)", out)}
        assert named, "no `yazses <cmd>` recommendations found — this guard is blind"

        root = typer.main.get_command(cli.app)
        ctx = click.Context(root)
        missing = sorted(n for n in named if root.get_command(ctx, n) is None)
        assert not missing, (
            f"quickstart (running={running}) tells a first-time user to run "
            f"{missing}, which no longer exist"
        )
