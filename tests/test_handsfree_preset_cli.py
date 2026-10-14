"""`yazses handsfree enable | disable | explain` -- the preset's command line (#410).

The contract these pin: `enable` writes **one** key and nothing else (the preset expands when the
config is loaded, not when it is switched on); `explain` prints the resolved per-feature config
and applies nothing; `disable` stops what is moving *now* and says what a restart releases.
Every case injects a platform with a temporary config and a fake IPC client. No camera, no
daemon, no pointer.
"""
from __future__ import annotations

import types

import pytest
from typer.testing import CliRunner

from yazses import cli
from yazses.cli import app
from yazses.ipc.client import IpcUnreachableError

runner = CliRunner()


class _Client:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def call(self, method, **params):
        self.calls.append((method, params))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


@pytest.fixture
def rig(tmp_path, monkeypatch):
    config = tmp_path / "config.toml"

    class Platform:
        name = "linux"

        def __init__(self, client):
            self._client = client
            self.paths = types.SimpleNamespace(
                ipc_socket=str(tmp_path / "sock"), data_dir=str(tmp_path), config_file=config,
            )

        def ipc_client_factory(self, _path):
            return self._client

    def install(reply=None, text: str | None = None):
        client = _Client(reply if reply is not None else IpcUnreachableError("no daemon"))
        monkeypatch.setattr(cli, "get_platform", lambda: Platform(client))
        monkeypatch.setattr(cli, "_feature_deps_blocked", lambda _f: None)
        if text is not None:
            config.write_text(text, encoding="utf-8")
        return client, config

    return install


def test_the_commands_are_listed():
    out = runner.invoke(app, ["handsfree", "--help"]).output
    for word in ("enable", "disable", "explain", "pause", "resume", "status"):
        assert word in out


# --------------------------------------------------------------------------- explain


def test_explain_prints_the_resolved_config_and_writes_nothing(rig):
    _, config = rig()
    result = runner.invoke(app, ["handsfree", "explain"])
    assert result.exit_code == 0, result.output
    for line in ("[handsfree_safety] enabled = true", "[headpointer] enabled = true",
                 "[gaze] refuse_destructive_fallback = true", "[gesture] chords = "):
        assert line in result.output
    assert "PROVISIONAL" in result.output and "OFF in your config" in result.output
    assert not config.exists(), "explain must not create or change the config"


def test_explain_says_which_values_are_yours(rig):
    rig(text="[headpointer]\ndwell_enabled = false\n")
    result = runner.invoke(app, ["handsfree", "explain"])
    assert "YOURS (preset would set true)" in result.output


def test_explain_reports_a_refusal_with_the_key(rig):
    rig(text="[handsfree_safety]\nenabled = false\n")
    result = runner.invoke(app, ["handsfree", "explain"])
    assert result.exit_code == 0
    assert "REFUSED" in result.output and "[handsfree_safety] enabled = false" in result.output


def test_explain_survives_an_unparseable_config(rig):
    rig(text="this is [not toml")
    assert runner.invoke(app, ["handsfree", "explain"]).exit_code == 0


# --------------------------------------------------------------------------- enable


def test_enable_refuses_experimental_features_without_force_and_writes_nothing(rig):
    _, config = rig()
    result = runner.invoke(app, ["handsfree", "enable", "--no-install"])
    assert result.exit_code == 1
    assert "--force" in result.output and "experimental" in result.output
    assert not config.exists()


def test_enable_writes_exactly_one_key(rig):
    _, config = rig(text="[stt]\nmodel = 'tiny'\n")
    result = runner.invoke(app, ["handsfree", "enable", "--force", "--no-install"])
    assert result.exit_code == 0, result.output
    text = config.read_text(encoding="utf-8")
    assert "[handsfree]" in text and "enabled = true" in text
    for section in ("headpointer", "gaze", "facegesture", "gesture", "perception", "handsfree_safety"):
        assert f"[{section}]" not in text, "the per-feature settings are derived, not written"
    assert "yazses restart" in result.output and "yazses handsfree explain" in result.output
    assert "yazses handsfree pause" in result.output, "the stop path is named at the moment of enabling"


def test_enable_is_refused_when_the_safety_floor_would_be_weakened(rig):
    _, config = rig(text="[cmdsafety]\nenabled = false\n")
    before = config.read_text(encoding="utf-8")
    result = runner.invoke(app, ["handsfree", "enable", "--force", "--no-install"])
    assert result.exit_code == 1
    assert "[cmdsafety] enabled = false" in result.output
    assert config.read_text(encoding="utf-8") == before


def test_enable_refuses_when_a_dependency_can_never_arrive(rig, monkeypatch):
    _, config = rig()
    monkeypatch.setattr(cli, "_feature_deps_blocked", lambda _f: "this snap cannot install it")
    result = runner.invoke(app, ["handsfree", "enable", "--force", "--no-install"])
    assert result.exit_code == 1 and "this snap cannot install it" in result.output
    assert not config.exists()


def test_the_enabled_config_then_resolves_to_the_preset(rig):
    _, config = rig()
    runner.invoke(app, ["handsfree", "enable", "--force", "--no-install"])
    from yazses.config import load_config

    cfg = load_config(config)
    assert cfg.handsfree.enabled and cfg.headpointer.enabled and cfg.handsfree_safety.enabled


# --------------------------------------------------------------------------- disable


def test_disable_writes_false_stops_what_is_moving_and_says_what_a_restart_does(rig):
    client, config = rig(
        reply={"ok": True, "scope": ["all hands-free input"]}, text="[handsfree]\nenabled = true\n"
    )
    result = runner.invoke(app, ["handsfree", "disable"])
    assert result.exit_code == 0, result.output
    assert "enabled = false" in config.read_text(encoding="utf-8")
    assert client.calls == [("handsfree", {"action": "pause"})]
    assert "Paused now: all hands-free input." in result.output
    assert "yazses restart" in result.output and "camera" in result.output


def test_disable_with_no_daemon_still_disables(rig):
    _, config = rig(text="[handsfree]\nenabled = true\n")
    result = runner.invoke(app, ["handsfree", "disable"])
    assert result.exit_code == 0, result.output
    assert "enabled = false" in config.read_text(encoding="utf-8")
    assert "Paused now" not in result.output


def test_disable_keeps_the_users_own_settings_and_calibration_keys(rig):
    _, config = rig(text="[handsfree]\nenabled = true\n[headpointer]\nx_gain = -300.0\n")
    runner.invoke(app, ["handsfree", "disable"])
    assert "x_gain = -300.0" in config.read_text(encoding="utf-8")
