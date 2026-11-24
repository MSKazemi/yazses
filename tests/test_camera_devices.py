"""Camera listing and selection by name or path (#924): the pure resolver, the sysfs
enumerator on a fake tree, the switch's index swap, and the IPC / CLI wiring.

No camera, no OpenCV, no /sys. Nothing here starts a thread.
"""
from __future__ import annotations

import types

import pytest
from typer.testing import CliRunner

from yazses import cli
from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.ipc.client import IpcUnreachableError
from yazses.ipc.protocol import Request
from yazses.perception.devices import (
    CameraDevice,
    default_enumerator,
    enumerate_by_probe,
    enumerate_v4l,
    format_devices,
    resolve_camera,
)
from yazses.perception.factory import build_perception_source
from yazses.perception.switch import CameraConsumer, CameraSwitch
from yazses.platform import get_platform

runner = CliRunner()

C920 = CameraDevice(0, "Logitech C920", ("/dev/v4l/by-id/usb-Logitech_C920-video-index0",
                                        "/dev/video0"))
INTEGRATED = CameraDevice(2, "Integrated Camera", ("/dev/video2",))
DEVICES = [C920, INTEGRATED]


# ------------------------------------------------------------------ resolver


@pytest.mark.parametrize("query, index", [
    ("Logitech C920", 0),
    ("logitech c920", 0),
    ("integrated", 2),
    ("2", 2),
    ("0", 0),
    ("/dev/video2", 2),
    ("/dev/v4l/by-id/usb-Logitech_C920-video-index0", 0),
    ("/dev//video2", 2),
    ("  C920  ", 0),
])
def test_resolve_finds_one_device(query, index):
    found = resolve_camera(DEVICES, query)
    assert found.ok and found.device is not None and found.device.index == index
    assert found.message() == ""


def test_resolve_missing_lists_every_camera():
    found = resolve_camera(DEVICES, "Razer")
    assert not found.ok and found.problem == "missing"
    assert found.candidates == tuple(DEVICES)
    text = found.message()
    assert "'Razer'" in text and "Logitech C920" in text and "Integrated Camera" in text


@pytest.mark.parametrize("query", ["7", "/dev/video9"])
def test_resolve_unlisted_index_or_path_is_missing(query):
    assert resolve_camera(DEVICES, query).problem == "missing"


def test_resolve_ambiguous_fragment_names_only_the_matches():
    twins = [CameraDevice(0, "USB Camera", ("/dev/video0",)),
             CameraDevice(2, "USB Camera", ("/dev/video2",)),
             CameraDevice(4, "Integrated Camera", ("/dev/video4",))]
    found = resolve_camera(twins, "usb camera")
    assert found.problem == "ambiguous" and [d.index for d in found.candidates] == [0, 2]
    assert "more specific" in found.message()
    # An index or a path still picks one of the twins.
    assert resolve_camera(twins, "2").device == twins[1]
    assert resolve_camera(twins, "/dev/video0").device == twins[0]
    # "camera" matches all three as a fragment.
    assert resolve_camera(twins, "camera").problem == "ambiguous"


def test_resolve_exact_name_beats_a_longer_name_containing_it():
    devices = [CameraDevice(0, "Cam", ()), CameraDevice(1, "Cam Pro", ())]
    assert resolve_camera(devices, "cam").device == devices[0]


def test_resolve_empty_query_and_no_devices():
    assert resolve_camera(DEVICES, "  ").problem == "empty"
    none = resolve_camera([], "C920")
    assert none.problem == "missing" and "No cameras were found." in none.message()


def test_format_devices():
    assert format_devices([]) == "No cameras found."
    out = format_devices(DEVICES)
    assert "0: Logitech C920" in out and "/dev/v4l/by-id/usb-Logitech_C920-video-index0" in out
    assert "2: Integrated Camera" in out


# ------------------------------------------------------------------ enumerators


def _v4l_tree(tmp_path):
    sys_root = tmp_path / "sys"
    by_id = tmp_path / "by-id"
    dev = tmp_path / "dev"
    for node, name, idx in [("video0", "Logitech C920", "0"), ("video1", "Logitech C920", "1"),
                            ("video2", "Integrated Camera", "0")]:
        (sys_root / node).mkdir(parents=True)
        (sys_root / node / "name").write_text(name + "\n", encoding="utf-8")
        (sys_root / node / "index").write_text(idx + "\n", encoding="utf-8")
        (dev / node).parent.mkdir(exist_ok=True)
        (dev / node).write_text("", encoding="utf-8")
    by_id.mkdir()
    (by_id / "usb-Logitech_C920-video-index0").symlink_to(dev / "video0")
    (by_id / "usb-Logitech_C920-video-index1").symlink_to(dev / "video1")
    (sys_root / "not-a-video-node").mkdir()
    return sys_root, by_id


def test_enumerate_v4l_lists_capture_nodes_with_by_id_paths(tmp_path):
    sys_root, by_id = _v4l_tree(tmp_path)
    devices = enumerate_v4l(sys_root, by_id)
    assert [(d.index, d.name) for d in devices] == [(0, "Logitech C920"),
                                                    (2, "Integrated Camera")]
    assert devices[0].paths[0] == str(by_id / "usb-Logitech_C920-video-index0")
    assert devices[0].paths[-1] == "/dev/video0"
    assert devices[1].paths == ("/dev/video2",)
    # The by-id link of the metadata node (video1) is not offered.
    assert not any("index1" in p for d in devices for p in d.paths)
    assert resolve_camera(devices, devices[0].paths[0]).device == devices[0]


def test_enumerate_v4l_with_no_sysfs_or_no_by_id_dir(tmp_path):
    assert enumerate_v4l(tmp_path / "missing", tmp_path / "missing2") == []
    sys_root, _ = _v4l_tree(tmp_path)
    devices = enumerate_v4l(sys_root, tmp_path / "no-by-id")
    assert [d.index for d in devices] == [0, 2]


def test_enumerate_by_probe_names_and_contains_probe_errors():
    def probe(i):
        if i == 3:
            raise RuntimeError("driver crash")
        return i in (0, 1)

    devices = enumerate_by_probe(probe, limit=5)
    assert [(d.index, d.name) for d in devices] == [(0, "Camera 0"), (1, "Camera 1")]
    assert resolve_camera(devices, "1").device == devices[1]
    assert enumerate_by_probe(lambda i: True, limit=0) == []


def test_default_enumerator_uses_sysfs_when_present_else_the_probe(tmp_path):
    sys_root, _ = _v4l_tree(tmp_path)
    assert [d.index for d in default_enumerator(lambda i: False, sys_root)()] == [0, 2]
    probed = default_enumerator(lambda i: i == 1, tmp_path / "absent")()
    assert [d.index for d in probed] == [1]


# ------------------------------------------------------------------ the switch


def _owner(name, log, on_log=None):
    state = {"held": True}

    def pause():
        log.append(f"pause:{name}")
        state["held"] = False

    def resume():
        log.append(f"resume:{name}")
        state["held"] = True

    return CameraConsumer(
        name, pause, resume, holders=lambda: (name,) if state["held"] else (),
        set_index=lambda i: log.append(f"index:{name}:{i}"),
    )


def test_use_camera_releases_swaps_then_reopens_when_on():
    log: list[str] = []
    s = CameraSwitch()
    s.register(_owner("a", log))
    s.register(_owner("b", log))
    assert s.use_camera(2, "Integrated Camera") is True
    assert log == ["pause:b", "pause:a", "index:a:2", "index:b:2", "resume:a", "resume:b"]
    assert s.status().as_payload()["active"] == {"index": 2, "name": "Integrated Camera"}
    assert s.holders() == ("a", "b")


def test_use_camera_while_off_stays_off_and_applies_at_the_next_on():
    log: list[str] = []
    s = CameraSwitch()
    s.register(_owner("a", log))
    s.set(False)
    log.clear()
    assert s.use_camera(1, "X") is False
    assert log == ["index:a:1"] and not s.is_on and s.holders() == ()
    s.set(True)
    assert log[-1] == "resume:a"


def test_use_camera_survives_an_owner_that_cannot_switch():
    log: list[str] = []

    def boom(_i):
        raise RuntimeError("no")

    s = CameraSwitch()
    s.register(CameraConsumer("bad", lambda: None, lambda: None, set_index=boom))
    s.register(CameraConsumer("noindex", lambda: None, lambda: None))
    s.register(_owner("ok", log))
    assert s.use_camera(3) is True
    assert "index:ok:3" in log and s.is_on


def test_status_has_no_active_camera_until_one_is_chosen():
    assert CameraSwitch().status().as_payload()["active"] is None


def test_shared_source_reopens_on_the_chosen_index():
    opened: list[int] = []

    class Cap:
        def open(self):
            pass

        def read(self):
            return None

        def close(self):
            pass

    cfg = types.SimpleNamespace(enabled=True, camera_index=0, fps=15)
    src = build_perception_source(
        cfg,
        capture_factory=lambda i: (opened.append(i), Cap())[1],
        processor_factory=lambda: types.SimpleNamespace(
            name="p", process=lambda f, t: None, close=lambda: None),
    )
    assert src is not None
    src.set_camera_index(5)
    # Opening is the first consumer's business; here only the index slot is checked.
    src._capture_factory()
    assert opened == [5]


# ------------------------------------------------------------------ IPC


def _daemon(devices):
    d = Daemon(config=Config(), platform=get_platform())
    d._camera_enumerator = lambda: list(devices)
    return d


def test_ipc_list_returns_the_devices():
    d = _daemon(DEVICES)
    reply = d._handle_camera(Request("camera", {"action": "list"}))
    assert reply["ok"] and [r["index"] for r in reply["devices"]] == [0, 2]
    assert reply["devices"][0]["name"] == "Logitech C920"


def test_ipc_use_applies_live_and_status_reports_the_active_camera():
    d = _daemon(DEVICES)
    log: list[str] = []
    d._camera_switch.register(_owner("facegesture", log))
    reply = d._handle_camera(Request("camera", {"action": "use", "target": "integrated"}))
    assert reply["ok"] and reply["state"] == "on"
    assert reply["active"] == {"index": 2, "name": "Integrated Camera"}
    assert log == ["pause:facegesture", "index:facegesture:2", "resume:facegesture"]
    status = d._handle_camera(Request("camera", {"action": "status"}))
    assert status["active"]["index"] == 2


def test_ipc_use_by_by_id_path():
    d = _daemon(DEVICES)
    reply = d._handle_camera(Request("camera", {
        "action": "use", "target": "/dev/v4l/by-id/usb-Logitech_C920-video-index0"}))
    assert reply["ok"] and reply["active"]["index"] == 0


def test_ipc_use_missing_changes_nothing_and_lists_the_cameras():
    d = _daemon(DEVICES)
    log: list[str] = []
    d._camera_switch.register(_owner("facegesture", log))
    reply = d._handle_camera(Request("camera", {"action": "use", "target": "Razer"}))
    assert reply["ok"] is False and reply["problem"] == "missing"
    assert "Logitech C920" in reply["reason"] and len(reply["devices"]) == 2
    assert log == [] and d._camera_switch.active is None and d._camera_switch.is_on


def test_ipc_use_ambiguous_is_refused():
    twins = [CameraDevice(0, "USB Camera"), CameraDevice(2, "USB Camera")]
    d = _daemon(twins)
    reply = d._handle_camera(Request("camera", {"action": "use", "target": "USB Camera"}))
    assert reply["ok"] is False and reply["problem"] == "ambiguous"


def test_ipc_use_with_no_target_and_a_broken_enumerator():
    d = _daemon(DEVICES)
    assert d._handle_camera(Request("camera", {"action": "use"}))["problem"] == "empty"

    def boom():
        raise OSError("sysfs gone")

    d._camera_enumerator = boom
    reply = d._handle_camera(Request("camera", {"action": "list"}))
    assert reply["ok"] is False and "OSError" in reply["reason"]


# ------------------------------------------------------------------ CLI


class _Daemon:
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
    stub = _Daemon()
    platform = types.SimpleNamespace(
        paths=types.SimpleNamespace(ipc_socket=tmp_path / "sock"),
        ipc_client_factory=lambda _sock: stub,
    )
    monkeypatch.setattr(cli, "get_platform", lambda: platform)
    return stub


def test_cli_list_prints_the_daemons_cameras(daemon):
    daemon.reply = {"ok": True, "active": {"index": 2, "name": "Integrated Camera"},
                    "devices": [d.as_payload() for d in DEVICES]}
    result = runner.invoke(cli.app, ["camera", "list"])
    assert result.exit_code == 0, result.output
    assert daemon.calls == [("camera", {"action": "list"})]
    assert "Logitech C920" in result.output and "by-id" in result.output
    assert "Using: Integrated Camera (index 2)" in result.output
    assert "yazses camera use" in result.output


def test_cli_list_falls_back_to_a_local_listing_without_a_daemon(daemon, monkeypatch):
    daemon.error = IpcUnreachableError("no socket")
    monkeypatch.setattr("yazses.perception.devices.default_enumerator",
                        lambda *a, **k: lambda: list(DEVICES))
    result = runner.invoke(cli.app, ["camera", "list"])
    assert result.exit_code == 0 and "Integrated Camera" in result.output


def test_cli_use_sends_the_target_and_reports_the_camera(daemon):
    daemon.reply = {"ok": True, "state": "on", "holders": ["facegesture"],
                    "consumers": ["facegesture"], "failures": {},
                    "active": {"index": 2, "name": "Integrated Camera"}}
    result = runner.invoke(cli.app, ["camera", "use", "integrated"])
    assert result.exit_code == 0, result.output
    assert daemon.calls == [("camera", {"action": "use", "target": "integrated",
                                        "wait_s": cli._CAMERA_SWITCH_WAIT_S})]
    assert "Using: Integrated Camera (index 2)" in result.output
    assert "not saved" in result.output


def test_cli_use_missing_prints_the_fallback_listing(daemon):
    daemon.reply = {"ok": False, "problem": "missing",
                    "reason": "No camera matches 'Razer'.\n  0: Logitech C920"}
    result = runner.invoke(cli.app, ["camera", "use", "Razer"])
    assert result.exit_code == 1
    assert "No camera matches" in result.output and "Logitech C920" in result.output


def test_cli_use_ambiguous_suggests_index_or_path(daemon):
    daemon.reply = {"ok": False, "problem": "ambiguous", "reason": "More than one camera"}
    result = runner.invoke(cli.app, ["camera", "use", "USB"])
    assert result.exit_code == 1 and "by-id" in result.output


def test_cli_use_without_a_daemon(daemon):
    daemon.error = IpcUnreachableError("no socket")
    result = runner.invoke(cli.app, ["camera", "use", "x"])
    assert result.exit_code == 1 and "Daemon is not running" in result.output
