"""`yazses camera devices / use / status` CLI group (#924)."""
from typer.testing import CliRunner

from yazses import cli
from yazses.camera.devices import CameraDevice

runner = CliRunner()
_ENV = {"COLUMNS": "220", "TERM": "dumb"}

BRIO = CameraDevice("Logitech BRIO", "/dev/video0", 0, "usb-Logitech_BRIO_ABC-video-index0")
LAPTOP = CameraDevice("Integrated Camera", "/dev/video2", 2)
TWIN_A = CameraDevice("USB Camera", "/dev/video4", 4, "usb-Acme_111-video-index0")
TWIN_B = CameraDevice("USB Camera", "/dev/video6", 6, "usb-Acme_222-video-index0")


class _Fake:
    def __init__(self, devices):
        self._d = devices

    def list_cameras(self):
        return list(self._d)


def _cams(mocker, devices):
    mocker.patch("yazses.platform.factory.get_camera_enumerator", return_value=_Fake(devices))


def _patch_cfg(mocker, tmp_path):
    cfg = tmp_path / "config.toml"
    plat = mocker.Mock()
    plat.paths.config_file = cfg
    mocker.patch.object(cli, "get_platform", return_value=plat)
    return cfg


def test_devices_lists_cameras(mocker, tmp_path):
    _patch_cfg(mocker, tmp_path)
    _cams(mocker, [BRIO, LAPTOP])
    r = runner.invoke(cli.app, ["camera", "devices"], env=_ENV)
    assert r.exit_code == 0
    assert "Logitech BRIO" in r.output and "Integrated Camera" in r.output
    assert "None chosen" in r.output


def test_devices_none_found(mocker, tmp_path):
    _patch_cfg(mocker, tmp_path)
    _cams(mocker, [])
    r = runner.invoke(cli.app, ["camera", "devices"], env=_ENV)
    assert r.exit_code == 0 and "No cameras found" in r.output


def test_use_writes_shared_and_all_three_legacy_keys_atomically(mocker, tmp_path):
    cfg = _patch_cfg(mocker, tmp_path)
    _cams(mocker, [BRIO, LAPTOP])
    r = runner.invoke(cli.app, ["camera", "use", "integrated"], env=_ENV)
    assert r.exit_code == 0, r.output
    from yazses.config import load_config

    loaded = load_config(cfg)
    assert loaded.camera.device == "Integrated Camera" and loaded.camera.index == 2
    assert loaded.gaze.camera_index == loaded.facegesture.camera_index == 2
    assert loaded.perception.camera_index == 2
    text = cfg.read_text(encoding="utf-8")
    for section in ("camera", "gaze", "facegesture", "perception"):
        assert f"[{section}]" in text
    assert "restart" in r.output.lower()


def test_use_refuses_ambiguous_name_and_writes_nothing(mocker, tmp_path):
    cfg = _patch_cfg(mocker, tmp_path)
    _cams(mocker, [TWIN_A, TWIN_B])
    r = runner.invoke(cli.app, ["camera", "use", "usb camera"], env=_ENV)
    assert r.exit_code == 2
    assert "usb-Acme_111-video-index0" in r.output and "usb-Acme_222-video-index0" in r.output
    assert not cfg.exists()


def test_use_exact_stable_id_picks_one_twin(mocker, tmp_path):
    cfg = _patch_cfg(mocker, tmp_path)
    _cams(mocker, [TWIN_A, TWIN_B])
    r = runner.invoke(cli.app, ["camera", "use", "usb-Acme_222-video-index0"], env=_ENV)
    assert r.exit_code == 0
    from yazses.config import load_config

    assert load_config(cfg).camera.index == 6


def test_use_unknown_camera_writes_nothing(mocker, tmp_path):
    cfg = _patch_cfg(mocker, tmp_path)
    _cams(mocker, [BRIO])
    r = runner.invoke(cli.app, ["camera", "use", "nonesuch"], env=_ENV)
    assert r.exit_code == 1 and "No camera matches" in r.output
    assert not cfg.exists()


def test_use_requires_name(mocker, tmp_path):
    cfg = _patch_cfg(mocker, tmp_path)
    r = runner.invoke(cli.app, ["camera", "use"], env=_ENV)
    assert r.exit_code == 2 and not cfg.exists()


def test_use_clear_resets_choice_and_legacy_keys(mocker, tmp_path):
    cfg = _patch_cfg(mocker, tmp_path)
    _cams(mocker, [BRIO, LAPTOP])
    runner.invoke(cli.app, ["camera", "use", "integrated"], env=_ENV)
    r = runner.invoke(cli.app, ["camera", "use", "--clear"], env=_ENV)
    assert r.exit_code == 0
    from yazses.config import load_config

    loaded = load_config(cfg)
    assert loaded.camera.index == -1 and loaded.camera.device == ""
    assert loaded.gaze.camera_index == 0


def test_status_unchosen(mocker, tmp_path):
    _patch_cfg(mocker, tmp_path)
    r = runner.invoke(cli.app, ["camera", "status"], env=_ENV)
    assert r.exit_code == 0 and "none" in r.output.lower()
    assert "gaze=0" in r.output


def test_status_reports_replug_renumbering_and_absence(mocker, tmp_path):
    _patch_cfg(mocker, tmp_path)
    _cams(mocker, [BRIO])
    runner.invoke(cli.app, ["camera", "use", "brio"], env=_ENV)
    _cams(mocker, [CameraDevice(BRIO.name, "/dev/video4", 4, BRIO.by_id)])
    moved = runner.invoke(cli.app, ["camera", "status"], env=_ENV)
    assert "now at index 4" in moved.output
    _cams(mocker, [])
    gone = runner.invoke(cli.app, ["camera", "status"], env=_ENV)
    assert "not in the OS list" in gone.output
