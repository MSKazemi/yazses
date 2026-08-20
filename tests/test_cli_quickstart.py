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


def _patch(monkeypatch, plat, *, model="base.en", downloaded=True):
    monkeypatch.setattr(cli, "get_platform", lambda: plat)
    monkeypatch.setattr(cli, "_resolved_hotkey", lambda p: "right_ctrl")
    # Pinned, not left to the machine. Both are real reads -- the config file and the
    # Hugging Face cache -- so without this the page takes a different branch on a
    # developer's laptop than in CI, and whichever branch the host happens to have is
    # the only one the suite ever sees.
    monkeypatch.setattr(cli, "_configured_model", lambda p: model)
    monkeypatch.setattr(cli, "_model_is_downloaded", lambda m: downloaded)


# ---- quickstart ------------------------------------------------------------


# ---- the speech model, which the docstring always promised and never read ----
#
# `quickstart`'s own docstring says it looks at "prerequisites, whether the daemon is
# running, the speech model, your hotkey". Three of those four were read. The model was
# not: step 2 printed "first run can take 10-30s" whatever the state of the disk, which
# is the *load* time for a checkpoint that is already there and no description at all of
# the case that goes wrong.
#
# That case is #310 -- the first bug from a real user -- where a firewall blocked the
# automatic fetch and `yazses start` simply sat there.


def test_quickstart_confirms_the_model_when_it_is_already_downloaded(monkeypatch):
    _patch(monkeypatch, _Platform(running=False), model="base.en", downloaded=True)
    out = runner.invoke(cli.app, ["quickstart"]).output
    assert "base.en" in out and "already downloaded" in out
    assert "model download" not in out, "nothing to download — do not send them anywhere"


def test_quickstart_sends_you_to_fetch_the_model_before_start_when_it_is_missing(
    monkeypatch,
):
    _patch(monkeypatch, _Platform(running=False), model="small.en", downloaded=False)
    result = runner.invoke(cli.app, ["quickstart"])
    assert result.exit_code == 0
    out = result.output
    assert "yazses model download small.en" in out, (
        "the one step that needs the network has to be named as a command the user runs, "
        "so a blocked network fails somewhere it can be reported"
    )
    assert out.index("yazses model download") < out.index("Then: yazses start"), (
        "the download has to come before the start, or it is not a step"
    )
    assert "already downloaded" not in out


def test_quickstart_says_nothing_about_the_model_once_the_daemon_is_running(monkeypatch):
    """A running daemon has already loaded it; re-litigating that is noise."""
    _patch(monkeypatch, _Platform(running=True), model="base.en", downloaded=False)
    out = runner.invoke(cli.app, ["quickstart"]).output
    assert "model download" not in out
    assert "already running" in out


def test_quickstart_is_silent_rather_than_wrong_when_the_model_cannot_be_read(
    monkeypatch,
):
    """A cosmetic check must never invent a scary claim on a machine it cannot read.

    Drives the real failure -- config loading blowing up, and the cache lookup blowing
    up -- rather than replacing the helpers, so their own guards are what is tested.
    """
    import yazses.config as config
    import yazses.stt.download as dl

    def _boom(*a, **k):
        raise RuntimeError("unreadable")

    monkeypatch.setattr(config, "load_config", _boom)
    monkeypatch.setattr(dl, "is_cached", _boom)
    monkeypatch.setattr(cli, "get_platform", lambda: _Platform(running=False))
    monkeypatch.setattr(cli, "_resolved_hotkey", lambda p: "right_ctrl")

    assert cli._configured_model(_Platform(running=False)) == ""
    assert cli._model_is_downloaded("base.en") is True  # never cry wolf

    result = runner.invoke(cli.app, ["quickstart"])
    assert result.exit_code == 0, result.output
    assert "not downloaded" not in result.output


def test_quickstart_and_doctor_never_disagree_about_the_model(monkeypatch):
    """Two screens answering "is the model here?" from two predicates is two answers.

    They both go through `stt.download.is_cached`, so this drives that one function and
    asserts the pair moves together: doctor WARNs exactly when quickstart sends the user
    to download.
    """
    from pathlib import Path as _Path

    import yazses.stt.download as dl
    from yazses.system import doctor

    for cached in (True, False):
        monkeypatch.setattr(dl, "is_cached", lambda name, cache_dir=None: cached)
        quickstart_says_ready = cli._model_is_downloaded("base.en")
        doctor_status = doctor._model_check("base.en", _Path("/nonexistent-cache"))[1]
        assert quickstart_says_ready is cached
        assert (doctor_status == "WARN") is (not quickstart_says_ready), (
            f"cached={cached}: doctor says {doctor_status} while quickstart says "
            f"ready={quickstart_says_ready}"
        )


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
