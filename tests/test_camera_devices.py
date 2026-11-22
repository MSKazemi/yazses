"""Pure camera-choice logic, the Linux enumerator, and the shared-camera config rule (#924)."""
from pathlib import Path

from yazses.camera.devices import (
    CameraDevice,
    effective_camera_index,
    list_cameras,
    resolve_camera,
)
from yazses.config import Config, load_config
from yazses.platform.linux.camera import LinuxCameraEnumerator
from yazses.platform.macos.camera import parse_system_profiler
from yazses.platform.windows.camera import parse_pnp_json

BRIO = CameraDevice("Logitech BRIO", "/dev/video0", 0, "usb-Logitech_BRIO_ABC-video-index0")
LAPTOP = CameraDevice("Integrated Camera", "/dev/video2", 2, "usb-Chicony_Integrated-video-index0")
TWIN_A = CameraDevice("USB Camera", "/dev/video4", 4, "usb-Acme_USB_Camera_111-video-index0")
TWIN_B = CameraDevice("USB Camera", "/dev/video6", 6, "usb-Acme_USB_Camera_222-video-index0")


class _Fake:
    def __init__(self, devices):
        self._d = devices

    def list_cameras(self):
        return self._d


def test_list_cameras_sorts_by_index():
    assert [d.index for d in list_cameras(_Fake([LAPTOP, BRIO]))] == [0, 2]


def test_stable_id_prefers_by_id_then_name():
    assert BRIO.stable_id.startswith("usb-Logitech")
    assert CameraDevice("Cam", "x", 0).stable_id == "Cam"


def test_resolve_unique_substring_case_insensitive():
    r = resolve_camera("brio", [BRIO, LAPTOP])
    assert r.device == BRIO and not r.ambiguous


def test_resolve_ambiguous_is_refused_not_guessed():
    r = resolve_camera("usb camera", [TWIN_A, TWIN_B])
    assert r.device is None and r.ambiguous
    assert set(r.candidates) == {TWIN_A, TWIN_B}


def test_exact_stable_id_disambiguates_identical_names():
    r = resolve_camera(TWIN_B.stable_id, [TWIN_A, TWIN_B])
    assert r.device == TWIN_B


def test_resolve_no_match_and_empty_query():
    assert resolve_camera("nope", [BRIO]).device is None
    assert not resolve_camera("nope", [BRIO]).ambiguous
    assert resolve_camera("  ", [BRIO]).candidates == ()


def test_effective_index_shared_wins_only_when_chosen():
    assert effective_camera_index(-1, 3) == 3
    assert effective_camera_index(0, 3) == 0
    assert effective_camera_index(2, 0) == 2


def test_linux_enumerator_reads_sysfs_skips_metadata_and_adds_by_id(tmp_path: Path):
    sysfs, dev, by_id = tmp_path / "sys", tmp_path / "dev", tmp_path / "by-id"
    for n, name, idx in [(0, "Logitech BRIO", "0"), (1, "Logitech BRIO", "1"), (2, "Integrated", "0")]:
        d = sysfs / f"video{n}"
        d.mkdir(parents=True)
        (d / "name").write_text(name + "\n", encoding="utf-8")
        (d / "index").write_text(idx + "\n", encoding="utf-8")
        (dev).mkdir(exist_ok=True)
        (dev / f"video{n}").write_text("", encoding="utf-8")
    by_id.mkdir()
    (by_id / "usb-Logitech_BRIO-video-index0").symlink_to(dev / "video0")
    (by_id / "usb-Logitech_BRIO-video-index1").symlink_to(dev / "video1")
    cams = LinuxCameraEnumerator(sysfs, dev, by_id).list_cameras()
    assert [(c.index, c.name) for c in cams] == [(0, "Logitech BRIO"), (2, "Integrated")]
    assert cams[0].by_id == "usb-Logitech_BRIO-video-index0"
    assert cams[1].by_id == ""
    assert cams[1].stable_id == "Integrated"


def test_linux_enumerator_without_v4l_reports_nothing(tmp_path: Path):
    assert LinuxCameraEnumerator(tmp_path / "missing", tmp_path, tmp_path).list_cameras() == []


def test_macos_parser():
    text = '{"SPCameraDataType":[{"_name":"FaceTime HD Camera","spcamera_unique-id":"u1"},{"_name":"Brio"}]}'
    cams = parse_system_profiler(text)
    assert [(c.name, c.index) for c in cams] == [("FaceTime HD Camera", 0), ("Brio", 1)]
    assert parse_system_profiler("garbage") == []


def test_windows_parser_single_object_and_list():
    one = parse_pnp_json('{"FriendlyName":"Cam","InstanceId":"USB\\\\X"}')
    assert [c.name for c in one] == ["Cam"]
    two = parse_pnp_json('[{"FriendlyName":"A"},{"FriendlyName":"B"}]')
    assert [c.index for c in two] == [0, 1]
    assert parse_pnp_json("") == []


def test_camera_section_is_dormant_by_default():
    cfg = Config()
    assert cfg.camera.device == "" and cfg.camera.index == -1
    assert cfg.gaze.camera_index == cfg.facegesture.camera_index == cfg.perception.camera_index == 0


def test_unset_camera_leaves_legacy_indexes_alone(tmp_path: Path):
    p = tmp_path / "config.toml"
    p.write_text("[gaze]\ncamera_index = 3\n[perception]\ncamera_index = 3\n", encoding="utf-8")
    cfg = load_config(p)
    assert (cfg.gaze.camera_index, cfg.perception.camera_index, cfg.facegesture.camera_index) == (3, 3, 0)


def test_chosen_camera_overrides_all_three_legacy_keys(tmp_path: Path):
    p = tmp_path / "config.toml"
    p.write_text('[camera]\ndevice = "usb-x"\nindex = 2\n[gaze]\ncamera_index = 5\n', encoding="utf-8")
    cfg = load_config(p)
    assert (cfg.gaze.camera_index, cfg.facegesture.camera_index, cfg.perception.camera_index) == (2, 2, 2)
