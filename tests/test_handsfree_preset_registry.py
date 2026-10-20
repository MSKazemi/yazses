"""The hands-free preset is a `features` registry row, and every way on goes through its gate (#410).

ADR-v2-148: turning the preset on must go through the ordinary capability registry and the
safety floor. Before this, `yazses features enable handsfree` answered "Unknown feature" and the
settings window could not show the switch at all, so the only way on was `yazses handsfree
enable`. These pin:

* the row exists, is experimental, off by default, and writes exactly ``[handsfree] enabled``;
* `yazses features enable handsfree` is `yazses handsfree enable` (same tier gate, same
  safety-floor refusal, same one key) and `features disable handsfree` pauses what is moving;
* the settings window refuses the same files with the same words, and refuses when it cannot
  read the file at all (a gate that cannot see the file must not wave the preset through);
* a file that asks for the preset while the loader refused it reads as on-but-inactive, not on;
* end to end on fakes: switched on through the registry, the loaded config is the preset's, and
  switched off again, the daemon builds no camera consumer.

No camera, no pointer, no daemon, no network.
"""
from __future__ import annotations

import types

import pytest
from typer.testing import CliRunner

from yazses import cli
from yazses.cli import app
from yazses.config import Config, load_config
from yazses.handsfree.preset import enable_refusal as preset_refusal
from yazses.handsfree.preset import expand, floor_unmet
from yazses.ipc.client import IpcUnreachableError
from yazses.settingsui.controller import SettingsController
from yazses.system import features as F

runner = CliRunner()

WEAKENED = "[cmdsafety]\nenabled = false\n"


class _Client:
    def __init__(self, reply):
        self.reply = reply
        self.calls: list = []

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


# --------------------------------------------------------------------------- the row


def _row():
    feat = F.find_feature(Config(), F.PRESET_SLUG)
    assert feat is not None, "the preset is not a features registry row"
    return feat


def test_the_preset_is_an_experimental_registry_row_that_is_off_by_default():
    feat = _row()
    assert feat.tier == F.EXPERIMENTAL
    assert feat.on is False and feat.wired is True and feat.toggleable is True
    assert feat.category == F.CAT_ACCESS
    assert feat.example and feat.use_case
    assert F.default_state()[F.PRESET_SLUG] is False
    assert F.PRESET_SLUG not in F.default_enabled_slugs()


def test_the_row_writes_only_the_presets_own_key():
    feat = _row()
    assert feat.on_writes == (("handsfree", "enabled", "true", False),)
    assert feat.off_writes == (("handsfree", "enabled", "false", False),)


def test_the_row_needs_exactly_the_packages_of_the_camera_features_it_composes():
    feat = _row()
    for slug in ("gaze", "headpointer", "facegesture"):
        other = F.find_feature(Config(), slug)
        assert other is not None
        assert feat.pip_packages == other.pip_packages
        assert feat.check_modules == other.check_modules


# --------------------------------------------------------------------------- the gate


@pytest.mark.parametrize("text", [
    {},
    {"cmdsafety": {"enabled": False}},
    {"handsfree_safety": {"enabled": False}},
    {"gaze": {"refuse_destructive_fallback": False}},
    {"handsfree": {"gaze": False}, "gaze": {"refuse_destructive_fallback": False}},
])
def test_the_registry_gate_is_the_presets_own_refusal(text):
    assert F.enable_refusal(F.PRESET_SLUG, text) == expand(text, assume_enabled=True).refusal
    assert F.enable_refusal(F.PRESET_SLUG, text) == preset_refusal(text)


def test_the_gate_has_teeth_and_is_silent_for_every_other_feature():
    assert F.enable_refusal(F.PRESET_SLUG, {"cmdsafety": {"enabled": False}})
    assert F.enable_refusal(F.PRESET_SLUG, {}) == ""
    assert F.enable_refusal("gaze", {"cmdsafety": {"enabled": False}}) == ""
    assert F.enable_refusal("gaze", None) == ""


def test_a_gate_that_cannot_read_the_file_refuses_the_preset():
    assert "could not be read" in F.enable_refusal(F.PRESET_SLUG, None)


# --------------------------------------------------------------------------- the CLI


def test_features_enable_without_force_refuses_and_writes_nothing(rig):
    _, config = rig()
    result = runner.invoke(app, ["features", "enable", "handsfree", "--no-install"])
    assert result.exit_code == 1
    assert "--force" in result.output and "experimental" in result.output
    assert not config.exists()


def test_features_enable_writes_the_one_key_and_names_the_stop_path(rig):
    _, config = rig(text="[stt]\nmodel = 'tiny'\n")
    result = runner.invoke(app, ["features", "enable", "handsfree", "--force", "--no-install"])
    assert result.exit_code == 0, result.output
    text = config.read_text(encoding="utf-8")
    assert "[handsfree]" in text and "enabled = true" in text
    for section in ("headpointer", "gaze", "facegesture", "gesture", "perception", "handsfree_safety"):
        assert f"[{section}]" not in text, "the per-feature settings are derived, not written"
    assert "yazses handsfree pause" in result.output


def test_both_spellings_refuse_a_weakened_floor_with_the_same_words(rig):
    _, config = rig(text=WEAKENED)
    via_features = runner.invoke(app, ["features", "enable", "handsfree", "--force", "--no-install"])
    via_handsfree = runner.invoke(app, ["handsfree", "enable", "--force", "--no-install"])
    assert via_features.exit_code == via_handsfree.exit_code == 1
    assert via_features.output == via_handsfree.output
    assert "[cmdsafety] enabled = false" in via_features.output
    assert config.read_text(encoding="utf-8") == WEAKENED


def test_features_disable_pauses_what_is_moving_now(rig):
    client, config = rig(
        reply={"ok": True, "scope": ["all hands-free input"]}, text="[handsfree]\nenabled = true\n"
    )
    result = runner.invoke(app, ["features", "disable", "handsfree"])
    assert result.exit_code == 0, result.output
    assert "enabled = false" in config.read_text(encoding="utf-8")
    assert client.calls == [("handsfree", {"action": "pause"})]
    assert "yazses restart" in result.output


def test_the_features_listing_shows_the_preset(rig):
    rig()
    result = runner.invoke(app, ["features", "info", "handsfree"])
    assert result.exit_code == 0, result.output
    assert "Hands-Free Preset" in result.output


# --------------------------------------------------------------------------- the settings window


def _controller(tmp_path, text: str | None, *, raw_loader="file"):
    config = tmp_path / "config.toml"
    if text is not None:
        config.write_text(text, encoding="utf-8")
    writes: list = []

    def _raw():
        from yazses import tomlio

        return tomlio.read(config) if config.exists() else {}

    ctrl = SettingsController(
        load_config=lambda: load_config(config),
        writer=lambda *a: writes.append(a),
        deps_probe=lambda _mods: [],
        blocked_probe=lambda _pkgs: None,
        raw_config_loader=_raw if raw_loader == "file" else raw_loader,
    )
    return ctrl, writes


def test_the_window_asks_for_the_experimental_confirmation_first(tmp_path):
    ctrl, writes = _controller(tmp_path, None)
    result = ctrl.set_enabled(F.PRESET_SLUG, True)
    assert result.needs_confirmation and not writes


def test_the_window_writes_the_one_key_when_confirmed(tmp_path):
    ctrl, writes = _controller(tmp_path, None)
    result = ctrl.set_enabled(F.PRESET_SLUG, True, confirmed=True)
    assert result.ok, result.error
    assert writes == [("handsfree", "enabled", "true", False)]


def test_the_window_refuses_a_weakened_floor_with_the_clis_words_and_writes_nothing(tmp_path):
    ctrl, writes = _controller(tmp_path, WEAKENED)
    result = ctrl.set_enabled(F.PRESET_SLUG, True, confirmed=True)
    assert not result.ok and writes == []
    assert preset_refusal({"cmdsafety": {"enabled": False}}) in (result.error or "")


@pytest.mark.parametrize("loader", [None, lambda: None, lambda: (_ for _ in ()).throw(OSError("no"))])
def test_the_window_refuses_the_preset_when_it_cannot_read_the_file(tmp_path, loader):
    ctrl, writes = _controller(tmp_path, None, raw_loader=loader)
    result = ctrl.set_enabled(F.PRESET_SLUG, True, confirmed=True)
    assert not result.ok and writes == []
    assert "could not be read" in (result.error or "")


def test_an_unreadable_file_does_not_block_any_other_feature(tmp_path):
    ctrl, writes = _controller(tmp_path, None, raw_loader=None)
    result = ctrl.set_enabled("headpointer", True, confirmed=True)
    assert result.ok, result.error
    assert writes == [("headpointer", "enabled", "true", False)]


def test_the_window_can_always_turn_the_preset_off(tmp_path):
    ctrl, writes = _controller(tmp_path, "[handsfree]\nenabled = true\n" + WEAKENED, raw_loader=None)
    result = ctrl.set_enabled(F.PRESET_SLUG, False)
    assert result.ok, result.error
    assert writes == [("handsfree", "enabled", "false", False)]


# --------------------------------------------------------------------------- honest status


def test_a_refused_preset_reads_as_inactive_not_as_working(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[handsfree]\nenabled = true\n" + WEAKENED, encoding="utf-8")
    cfg = load_config(path)
    assert _row_for(cfg).on is True, "the file does ask for it"
    reason = F.inactive_reason(F.PRESET_SLUG, cfg)
    assert "[cmdsafety] enabled" in reason and "not applied" in reason
    assert cfg.headpointer.enabled is False, "a refused preset applies nothing"


def test_an_applied_preset_has_no_inactive_reason(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[handsfree]\nenabled = true\n", encoding="utf-8")
    cfg = load_config(path)
    assert _row_for(cfg).on is True
    assert F.inactive_reason(F.PRESET_SLUG, cfg) == ""


@pytest.mark.parametrize("text", ["", "[handsfree]\nenabled = false\n" + WEAKENED])
def test_floor_unmet_is_empty_whenever_the_preset_is_off(tmp_path, text):
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    cfg = load_config(path)
    from yazses.config import handsfree_preset

    assert floor_unmet(handsfree_preset(cfg), cfg) == ()


def _row_for(cfg):
    feat = F.find_feature(cfg, F.PRESET_SLUG)
    assert feat is not None
    return feat


# --------------------------------------------------------------------------- end to end on fakes


class _Camera:
    """A shared camera that refuses to be opened: building must not need one."""

    def consumer(self, name):
        class Lease:
            def start(self):
                raise AssertionError("building must not lease the camera")

            def stop(self):
                pass

            def latest(self):
                return None

        return Lease()

    def status(self):
        return types.SimpleNamespace(failure_reason=None)


def _camera_consumers(config_path):
    from yazses.core.daemon import Daemon
    from yazses.platform import get_platform

    cfg = load_config(config_path)
    daemon = Daemon(config=cfg, platform=get_platform())
    daemon._perception = _Camera()
    daemon._handsfree_safety = daemon._build_handsfree_safety(cfg)
    headpointer = daemon._build_headpointer(cfg)
    face = daemon._build_face_gesture_source(cfg)
    return {
        "gate": daemon._handsfree_safety is not None,
        "headpointer": bool(getattr(headpointer, "active", False)) or cfg.headpointer.enabled,
        "face": [type(s).__name__ for s in face],
        "perception": cfg.perception.enabled,
    }


def test_on_through_the_registry_then_off_again_leaves_no_camera_consumer(rig):
    _, config = rig(text="[stt]\nmodel = 'tiny'\n")
    on = runner.invoke(app, ["features", "enable", "handsfree", "--force", "--no-install"])
    assert on.exit_code == 0, on.output
    enabled = _camera_consumers(config)
    assert enabled == {"gate": True, "headpointer": True, "face": ["FaceGestureBackend"],
                       "perception": True}

    off = runner.invoke(app, ["features", "disable", "handsfree"])
    assert off.exit_code == 0, off.output
    assert _camera_consumers(config) == {"gate": False, "headpointer": False, "face": [],
                                         "perception": False}
    assert "model = 'tiny'" in config.read_text(encoding="utf-8"), "the rest of the file is kept"
