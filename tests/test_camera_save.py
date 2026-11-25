"""``yazses camera use --save`` (#924): remember the chosen camera in the config file.

Main's ``camera use`` switches the running daemon and is not saved. ``--save`` also writes
``[camera] device``/``index`` and keeps the three legacy ``camera_index`` keys equal to it, so
the choice survives a restart. A camera that is not listed, or that two cameras share a name
with, writes nothing. No camera, no daemon, no OpenCV.
"""
from __future__ import annotations

import types

import pytest
import typer
from typer.testing import CliRunner

from yazses import cli
from yazses.config import load_config
from yazses.perception.devices import CameraDevice, effective_camera_index

BRIO = CameraDevice(2, "Logitech Brio", ("/dev/v4l/by-id/usb-Logitech_Brio-video-index0",))
TWIN_A = CameraDevice(0, "USB Webcam", ("/dev/v4l/by-id/usb-A-video-index0",))
TWIN_B = CameraDevice(1, "USB Webcam", ("/dev/v4l/by-id/usb-B-video-index0",))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    cfg.write_text("", encoding="utf-8")
    monkeypatch.setattr(cli, "get_platform", lambda: types.SimpleNamespace(
        paths=types.SimpleNamespace(config_file=cfg, ipc_socket=tmp_path / "s")))
    calls: list[tuple] = []

    def fake_call(action, **params):
        calls.append((action, params))
        return {"ok": True, "state": "on", "holders": [], "consumers": []}

    monkeypatch.setattr(cli, "_camera_call", fake_call)

    def devices(listing):
        monkeypatch.setattr("yazses.perception.devices.default_enumerator",
                            lambda *a, **k: (lambda: list(listing)))

    return types.SimpleNamespace(cfg=cfg, calls=calls, devices=devices)


def _use(*args):
    return CliRunner().invoke(cli.app, ["camera", "use", *args])


def test_without_save_nothing_is_written(env):
    env.devices([BRIO])
    result = _use("Brio")
    assert result.exit_code == 0
    assert env.cfg.read_text(encoding="utf-8") == ""
    assert env.calls == [("use", {"target": "Brio"})]


def test_save_writes_the_choice_and_the_legacy_keys(env):
    env.devices([BRIO])
    result = _use("Brio", "--save")
    assert result.exit_code == 0, result.output
    cfg = load_config(env.cfg)
    assert cfg.camera.index == 2
    assert cfg.camera.device == BRIO.paths[0]
    # the shared choice overrides every feature's own camera_index at load time
    assert (cfg.gaze.camera_index, cfg.facegesture.camera_index, cfg.perception.camera_index) == (2, 2, 2)
    assert env.calls == [("use", {"target": "Brio"})]  # and the running daemon is switched too


def test_save_still_saves_when_no_daemon_is_running(env, monkeypatch):
    env.devices([BRIO])

    def unreachable(action, **params):
        raise typer.Exit(1)

    monkeypatch.setattr(cli, "_camera_call", unreachable)
    result = _use("Brio", "--save")
    assert result.exit_code == 0
    assert "Saved" in result.output
    assert load_config(env.cfg).camera.index == 2


def test_save_refuses_a_camera_that_is_not_listed(env):
    env.devices([BRIO])
    result = _use("Nope", "--save")
    assert result.exit_code == 1
    assert env.cfg.read_text(encoding="utf-8") == ""


def test_save_refuses_an_ambiguous_name(env):
    env.devices([TWIN_A, TWIN_B])
    result = _use("USB Webcam", "--save")
    assert result.exit_code == 1
    assert env.cfg.read_text(encoding="utf-8") == ""
    # the by-id path is unambiguous and is accepted
    assert _use(TWIN_B.paths[0], "--save").exit_code == 0
    assert load_config(env.cfg).camera.index == 1


def test_an_unchosen_camera_leaves_every_features_own_index_alone():
    assert effective_camera_index(-1, 3) == 3
    assert effective_camera_index(0, 3) == 0
    assert effective_camera_index("x", 3) == 3  # type: ignore[arg-type]


def test_clear_forgets_the_saved_choice(env):
    env.devices([BRIO])
    assert _use("Brio", "--save").exit_code == 0
    assert load_config(env.cfg).camera.index == 2
    result = _use("--clear")
    assert result.exit_code == 0, result.output
    cfg = load_config(env.cfg)
    assert (cfg.camera.device, cfg.camera.index) == ("", -1)
    assert (cfg.gaze.camera_index, cfg.facegesture.camera_index, cfg.perception.camera_index) == (0, 0, 0)


def test_no_target_and_no_clear_is_a_usage_error(env):
    result = _use()
    assert result.exit_code == 2
    assert env.calls == []
