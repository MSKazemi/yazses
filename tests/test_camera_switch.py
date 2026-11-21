"""The camera on/off switch (#922, #924): state, owners, IPC and CLI.

Everything is fakes: no camera, no OpenCV, no daemon process. Every thread a test starts
waits on a stop event and is stopped and joined in a ``finally``.
"""
from __future__ import annotations

import sys
import threading
import types
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from yazses import cli
from yazses.config import Config, FacegestureConfig
from yazses.core.daemon import Daemon
from yazses.facegesture.backend import FaceGestureBackend
from yazses.ipc.client import IpcUnreachableError
from yazses.ipc.protocol import Request
from yazses.perception.source import SharedPerceptionSource, SourceState
from yazses.perception.switch import CameraConsumer, CameraSwitch
from yazses.platform import get_platform

runner = CliRunner()


# ------------------------------------------------------------------ pure switch


def _consumer(name, log, *, held=None, fail_pause=False, fail_resume=False):
    state = {"held": True if held is None else held}

    def pause():
        log.append(f"pause:{name}")
        if fail_pause:
            raise RuntimeError("boom")
        state["held"] = False

    def resume():
        log.append(f"resume:{name}")
        if fail_resume:
            raise RuntimeError("boom")
        state["held"] = True

    return CameraConsumer(
        name, pause, resume,
        holders=lambda: (name,) if state["held"] else (),
    )


def test_switch_starts_on_and_set_reports_change():
    s = CameraSwitch()
    assert s.is_on
    assert s.set(True) is False
    assert s.set(False) is True and not s.is_on
    assert s.toggle() is True


def test_off_pauses_every_consumer_and_on_resumes_them():
    log: list[str] = []
    s = CameraSwitch()
    s.register(_consumer("a", log))
    s.register(_consumer("b", log))
    assert s.holders() == ("a", "b")
    s.set(False)
    assert log == ["pause:b", "pause:a"]
    assert s.holders() == ()
    s.set(True)
    assert log[2:] == ["resume:a", "resume:b"]
    assert s.holders() == ("a", "b")


def test_a_failing_consumer_does_not_stop_the_others_or_raise():
    log: list[str] = []
    s = CameraSwitch()
    s.register(_consumer("a", log))
    s.register(_consumer("b", log, fail_pause=True))
    s.set(False)
    assert "pause:a" in log


def test_observers_are_called_on_change_only_and_can_unsubscribe():
    seen: list[bool] = []
    s = CameraSwitch()
    off = s.subscribe(seen.append)
    s.set(True)
    s.set(False)
    s.set(True)
    off()
    s.set(False)
    assert seen == [False, True]


def test_observer_exception_is_contained():
    s = CameraSwitch()
    s.subscribe(lambda on: 1 / 0)
    assert s.set(False) is True


def test_a_consumer_registered_while_off_is_paused_at_once():
    log: list[str] = []
    s = CameraSwitch(on=False)
    s.register(_consumer("late", log))
    assert log == ["pause:late"]


def test_status_reports_failures_only_while_on():
    c = CameraConsumer("x", lambda: None, lambda: None, failure=lambda: "camera 0 is busy")
    s = CameraSwitch()
    s.register(c)
    assert s.status().as_payload()["failures"] == {"x": "camera 0 is busy"}
    s.set(False)
    assert s.status().failures == {}


def test_holder_changes_are_logged_once(caplog):
    log: list[str] = []
    s = CameraSwitch()
    s.register(_consumer("facegesture", log))
    with caplog.at_level("INFO", logger="yazses.perception.switch"):
        s.note_holders()
        s.note_holders()
        s.set(False)
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert text.count("held by: facegesture") == 1
    assert "not held by YazSes" in text


def test_the_switch_is_thread_safe_under_concurrent_flips():
    log: list[str] = []
    s = CameraSwitch()
    s.register(_consumer("a", log))
    stop = threading.Event()

    def flip():
        while not stop.is_set():
            s.toggle()

    threads = [threading.Thread(target=flip, daemon=True) for _ in range(3)]
    for t in threads:
        t.start()
    try:
        stop.wait(0.05)
    finally:
        stop.set()
        for t in threads:
            t.join(2.0)
    assert not any(t.is_alive() for t in threads)
    assert s.status().on in (True, False)


# ------------------------------------------------------------------ shared source


class _Cap:
    def __init__(self):
        self.opens = self.closes = 0

    def open(self):
        self.opens += 1

    def read(self):
        return None

    def close(self):
        self.closes += 1


class _Proc:
    name = "fake"

    def process(self, frame, ts):
        return None

    def close(self):
        pass


class _Worker:
    def __init__(self, target, name):
        pass

    def join(self, timeout=None):
        pass

    def is_alive(self):
        return False


def _source():
    cap = _Cap()
    src = SharedPerceptionSource(lambda: cap, _Proc, interval_s=0.0, spawn=_Worker)
    return src, cap


def test_suspend_closes_the_device_but_keeps_the_lease_and_resume_reopens():
    src, cap = _source()
    lease = src.consumer("gaze")
    lease.start()
    assert cap.opens == 1 and src.status().state is SourceState.RUNNING
    src.suspend()
    assert cap.closes == 1 and src.suspended
    assert src.status().state is SourceState.DORMANT
    assert lease.active  # the consumer still wants it
    assert lease.latest() is None
    src.resume()
    assert cap.opens == 2 and src.status().state is SourceState.RUNNING


def test_a_lease_taken_while_suspended_opens_nothing_until_resume():
    src, cap = _source()
    src.suspend()
    src.consumer("gaze").start()
    assert cap.opens == 0
    src.resume()
    assert cap.opens == 1


def test_resume_with_no_leases_opens_nothing_and_suspend_is_idempotent():
    src, cap = _source()
    src.suspend()
    src.suspend()
    src.resume()
    assert cap.opens == 0


# ------------------------------------------------------------------ face switch backend


class _Cv2:
    COLOR_BGR2RGB = 0

    def cvtColor(self, frame, code):
        return frame


def _fake_mediapipe():
    return SimpleNamespace(
        ImageFormat=type("F", (), {"SRGB": 0}),
        Image=lambda image_format, data: data,
    )


class _OwnCap:
    def __init__(self, log):
        self.log = log

    def read(self):
        return True, object()

    def release(self):
        self.log.append("cap.release")


def _own_backend(monkeypatch, opens, *, fail_reopen=False):
    monkeypatch.setitem(sys.modules, "mediapipe", _fake_mediapipe())
    log: list[str] = []
    backend = FaceGestureBackend(FacegestureConfig(enabled=True, fps=60))
    backend._build_landmarker = lambda: SimpleNamespace(
        detect=lambda image: SimpleNamespace(face_blendshapes=[]),
        close=lambda: log.append("lm.close"),
    )

    def open_camera():
        opens.append(1)
        if fail_reopen and len(opens) > 1:
            backend._camera_failure = "camera 0 is in use or permission was denied"
            return None, None
        backend._camera_failure = ""
        backend._camera_open = True
        backend._idle.clear()
        return _OwnCap(log), _Cv2()

    backend._open_camera = open_camera
    return backend, log


def _run_in_thread(backend):
    t = threading.Thread(target=backend.run, daemon=True)
    t.start()
    return t


def _wait_for(pred, timeout=3.0):
    done = threading.Event()
    for _ in range(int(timeout / 0.01)):
        if pred():
            return True
        done.wait(0.01)
    return pred()


def test_face_backend_releases_the_camera_on_pause_and_reopens_on_resume(monkeypatch):
    opens: list[int] = []
    backend, log = _own_backend(monkeypatch, opens)
    t = _run_in_thread(backend)
    try:
        assert _wait_for(lambda: backend.camera_held)
        backend.pause_camera()
        assert not backend.camera_held  # pause waits for the release
        assert "cap.release" in log
        assert "lm.close" not in log  # the model stays loaded
        backend.resume_camera()
        assert _wait_for(lambda: backend.camera_held)
        assert len(opens) == 2
        assert backend.camera_failure == ""
    finally:
        backend.stop()
        t.join(3.0)
    assert not t.is_alive()
    assert log.count("cap.release") == 2 and log[-1] == "lm.close"


def test_face_backend_reports_why_a_reopen_failed_and_keeps_running(monkeypatch):
    opens: list[int] = []
    backend, _log = _own_backend(monkeypatch, opens, fail_reopen=True)
    t = _run_in_thread(backend)
    try:
        assert _wait_for(lambda: backend.camera_held)
        backend.pause_camera()
        backend.resume_camera()
        assert _wait_for(lambda: len(opens) == 2)
        assert _wait_for(lambda: "in use" in backend.camera_failure)
        assert not backend.camera_held
        assert t.is_alive()  # the daemon thread is not taken down
        backend.resume_camera()  # a later retry is allowed
        assert _wait_for(lambda: len(opens) == 3)
    finally:
        backend.stop()
        t.join(3.0)
    assert not t.is_alive()


def test_face_backend_stop_while_paused_exits(monkeypatch):
    opens: list[int] = []
    backend, _ = _own_backend(monkeypatch, opens)
    t = _run_in_thread(backend)
    try:
        assert _wait_for(lambda: backend.camera_held)
        backend.pause_camera()
    finally:
        backend.stop()
        t.join(3.0)
    assert not t.is_alive()


# ------------------------------------------------------------------ gaze backends


class _GCap:
    def __init__(self, ok=True):
        self.ok = ok
        self.released = False

    def isOpened(self):
        return self.ok

    def read(self):
        return True, object()

    def release(self):
        self.released = True


def _gaze_stub(cls_name):
    """A backend instance built without its heavy deps, using the real methods."""
    if cls_name == "mp":
        from yazses.gaze.mediapipe_backend import MediapipeGazeBackend as cls
    else:
        from yazses.gaze.l2cs import L2csGazeBackend as cls
    obj = cls.__new__(cls)
    caps: list[_GCap] = []
    obj._cv2 = SimpleNamespace(VideoCapture=lambda i: caps.append(_GCap()) or caps[-1])
    obj._camera_index = 0
    obj._cap = None
    obj._camera_off = False
    obj._camera_failure = ""
    obj._camera_lock = threading.RLock()
    return obj, caps


@pytest.mark.parametrize("which", ["mp", "l2cs"])
def test_gaze_backend_pause_releases_and_keeps_off_until_resume(which):
    b, caps = _gaze_stub(which)
    assert b._ensure_camera() is caps[0] and b.camera_held
    b.pause_camera()
    assert caps[0].released and not b.camera_held
    assert b._ensure_camera() is None and len(caps) == 1  # nothing reopens while off
    b.resume_camera()
    # resume reopens at once: no estimate has been asked for yet
    assert len(caps) == 2 and b.camera_held
    assert b._ensure_camera() is caps[1]


@pytest.mark.parametrize("which", ["mp", "l2cs"])
def test_gaze_backend_resume_reports_a_busy_camera_without_raising(which):
    b, caps = _gaze_stub(which)
    b.pause_camera()
    b._cv2 = SimpleNamespace(VideoCapture=lambda i: caps.append(_GCap(ok=False)) or caps[-1])
    b.resume_camera()
    assert not b.camera_held and "in use" in b.camera_failure

    def boom(_i):
        raise RuntimeError("driver exploded")

    b._cv2 = SimpleNamespace(VideoCapture=boom)
    b.resume_camera()
    assert not b.camera_held and "driver exploded" in b.camera_failure


@pytest.mark.parametrize("which", ["mp", "l2cs"])
def test_gaze_backend_reports_a_camera_that_will_not_open(which):
    b, caps = _gaze_stub(which)
    b._cv2 = SimpleNamespace(VideoCapture=lambda i: caps.append(_GCap(ok=False)) or caps[-1])
    assert b._ensure_camera() is None
    assert "in use" in b.camera_failure and caps[0].released


def test_targeter_forwards_pause_and_tolerates_a_backend_without_it():
    from yazses.gaze.targeter import GazeTargeter

    t = GazeTargeter.__new__(GazeTargeter)
    t._backend = object()  # a shared-source backend has no pause_camera
    t.pause_camera()
    t.resume_camera()
    assert t.camera_held is False and t.camera_failure == ""
    b, caps = _gaze_stub("mp")
    t._backend = b
    b._ensure_camera()
    assert t.camera_held
    t.pause_camera()
    assert not t.camera_held


# ------------------------------------------------------------------ IPC handler


def _daemon():
    return Daemon(config=Config(), platform=get_platform())


def test_ipc_camera_is_registered():
    import inspect

    assert 'server.register("camera", self._handle_camera)' in inspect.getsource(
        Daemon._start_ipc_server
    )


def test_ipc_camera_status_off_on_and_unknown():
    d = _daemon()
    log: list[str] = []
    d._camera_switch.register(_consumer("facegesture", log))
    reply = d._handle_camera(Request("camera", {}))
    assert reply["ok"] and reply["state"] == "on" and reply["holders"] == ["facegesture"]
    reply = d._handle_camera(Request("camera", {"action": "off"}))
    assert reply["state"] == "off" and reply["holders"] == []
    reply = d._handle_camera(Request("camera", {"action": "on"}))
    assert reply["state"] == "on" and reply["holders"] == ["facegesture"]
    assert d._handle_camera(Request("camera", {"action": "zoom"}))["ok"] is False


def test_daemon_with_no_camera_feature_switches_cleanly():
    d = _daemon()
    assert d._handle_camera(Request("camera", {"action": "off"}))["consumers"] == []
    assert d._camera_switch.is_on is False


def test_register_camera_consumers_wires_shared_source_face_and_gaze():
    d = _daemon()
    src, cap = _source()
    d._perception = src
    src.consumer("headpointer").start()
    face_log: list[str] = []
    face = SimpleNamespace(
        pause_camera=lambda: face_log.append("p"),
        resume_camera=lambda: face_log.append("r"),
        camera_held=True,
        camera_failure="",
    )
    d._extra_activations = [face]
    d._gaze_targeter = SimpleNamespace(
        pause_camera=lambda: face_log.append("gp"),
        resume_camera=lambda: face_log.append("gr"),
        camera_held=False,
        camera_failure="",
    )
    d._register_camera_consumers()
    assert d._camera_switch.holders() == ("facegesture", "headpointer")
    d._camera_switch.set(False)
    assert cap.closes == 1 and src.suspended
    assert face_log == ["gp", "p"]
    d._camera_switch.set(True)
    assert cap.opens == 2 and face_log[2:] == ["r", "gr"]


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
        paths=types.SimpleNamespace(ipc_socket=tmp_path / "sock", config_file=tmp_path / "c.toml"),
        ipc_client_factory=lambda _sock: stub,
    )
    monkeypatch.setattr(cli, "get_platform", lambda: platform)
    return stub


@pytest.mark.parametrize("word", ["status", "on", "off"])
def test_cli_sends_the_action(daemon, word):
    daemon.reply = {"ok": True, "state": "on", "holders": [], "consumers": [], "failures": {}}
    result = runner.invoke(cli.app, ["camera", word])
    assert result.exit_code == 0, result.output
    assert daemon.calls == [("camera", {"action": word})]


def test_cli_status_names_the_holders_and_the_workaround(daemon):
    daemon.reply = {"ok": True, "state": "on", "holders": ["facegesture"],
                    "consumers": ["facegesture"], "failures": {}}
    out = runner.invoke(cli.app, ["camera", "status"]).output
    assert "Camera: ON" in out and "Held by: facegesture" in out
    assert "yazses camera off" in out


def test_cli_off_says_dictation_is_unaffected(daemon):
    daemon.reply = {"ok": True, "state": "off", "holders": [],
                    "consumers": ["facegesture"], "failures": {}}
    out = runner.invoke(cli.app, ["camera", "off"]).output
    assert "Camera: OFF" in out and "not holding the camera" in out
    assert "dictation is unaffected" in out


def test_cli_shows_a_reopen_failure_reason(daemon):
    daemon.reply = {"ok": True, "state": "on", "holders": [], "consumers": ["gaze"],
                    "failures": {"gaze": "camera 0 is in use or permission was denied"}}
    out = runner.invoke(cli.app, ["camera", "on"]).output
    assert "gaze: could not reopen the camera" in out and "in use" in out


def test_cli_with_no_camera_feature_says_so(daemon):
    daemon.reply = {"ok": True, "state": "on", "holders": [], "consumers": [], "failures": {}}
    out = runner.invoke(cli.app, ["camera", "status"]).output
    assert "No camera feature is running" in out


def test_cli_when_the_daemon_is_not_running(daemon):
    daemon.error = IpcUnreachableError("no socket")
    result = runner.invoke(cli.app, ["camera", "off"])
    assert result.exit_code == 1
    assert "Daemon is not running" in result.output


def test_cli_surfaces_a_refusal(daemon):
    daemon.reply = {"ok": False, "reason": "unknown action 'zoom'"}
    result = runner.invoke(cli.app, ["camera", "status"])
    assert result.exit_code == 1 and "unknown action" in result.output


# ------------------------------------------------- calibrate commands vs. a daemon

def test_camera_guard_refuses_while_the_daemon_holds_the_camera(daemon, capsys):
    daemon.reply = {"ok": True, "state": "on", "holders": ["gaze"],
                    "consumers": ["gaze"], "failures": {}}
    with pytest.raises(cli.typer.Exit):
        cli._camera_guard("gaze calibrate")
    err = capsys.readouterr().err
    assert "holds the camera (gaze)" in err
    assert "yazses camera off" in err and "yazses camera on" in err
    assert daemon.calls == [("camera", {"action": "status"})]


def test_camera_guard_notes_a_switched_off_camera_and_continues(daemon, capsys):
    daemon.reply = {"ok": True, "state": "off", "holders": [], "consumers": ["gaze"],
                    "failures": {}}
    cli._camera_guard("gaze calibrate")
    assert "switched OFF" in capsys.readouterr().err


@pytest.mark.parametrize("reply,error", [
    ({"ok": True, "state": "on", "holders": [], "consumers": [], "failures": {}}, None),
    ({"ok": False, "reason": "unknown method"}, None),
    (None, IpcUnreachableError("no socket")),
])
def test_camera_guard_is_silent_when_nothing_holds_the_camera(daemon, capsys, reply, error):
    daemon.reply, daemon.error = reply, error
    cli._camera_guard("gaze calibrate")
    assert capsys.readouterr().err == ""


def test_gaze_calibrate_stops_at_the_guard_before_installing_anything(daemon, monkeypatch):
    daemon.reply = {"ok": True, "state": "on", "holders": ["gaze"],
                    "consumers": ["gaze"], "failures": {}}
    monkeypatch.setattr("yazses.gaze.calibrate.calibration_blocker", lambda **_k: None)
    monkeypatch.setattr("yazses.gaze.desktop.build_desktop", lambda: object())
    monkeypatch.setattr("yazses.config.load_config", lambda *_a, **_k: Config())
    installed: list[object] = []
    monkeypatch.setattr(cli, "_install_feature_deps", lambda *a, **k: installed.append(a))
    result = runner.invoke(cli.app, ["gaze", "calibrate"])
    assert result.exit_code == 1
    assert "yazses camera off" in result.output and not installed


def test_open_failure_message_points_at_the_switch():
    msg = cli._camera_open_failed("facegesture calibrate")
    assert "yazses camera off" in msg and "yazses camera on" in msg
