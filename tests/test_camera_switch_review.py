"""Review fixes for the runtime camera switch (#927). Fakes only: no camera, no daemon."""
from __future__ import annotations

import sys
import threading
import types
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from yazses import cli
from yazses.config import FacegestureConfig
from yazses.facegesture.backend import FaceGestureBackend
from yazses.ipc.client import IpcCallError, IpcTimeoutError
from yazses.ipc.protocol import RpcError
from yazses.perception.devices import CameraDevice, resolve_camera
from yazses.perception.switch import CameraConsumer, CameraSwitch

runner = CliRunner()


def _wait_for(pred, timeout=3.0):
    done = threading.Event()
    for _ in range(int(timeout / 0.01)):
        if pred():
            return True
        done.wait(0.01)
    return pred()


# ---------------------------------------------------------------- 1. first open fails


class _Cap:
    def __init__(self):
        self.released = False

    def release(self):
        self.released = True

    def read(self):
        return False, None


def _fake_mediapipe():
    mp = types.ModuleType("mediapipe")
    mp.Image = lambda **kw: object()
    mp.ImageFormat = SimpleNamespace(SRGB=1)
    return mp


def test_face_backend_waits_after_a_failed_first_open_and_reopens_on_resume(monkeypatch):
    monkeypatch.setitem(sys.modules, "mediapipe", _fake_mediapipe())
    backend = FaceGestureBackend(FacegestureConfig(enabled=True, fps=60))
    closed: list[int] = []
    backend._build_landmarker = lambda: SimpleNamespace(
        detect=lambda image: SimpleNamespace(face_blendshapes=[]),
        close=lambda: closed.append(1),
    )
    opens: list[int] = []

    def open_camera():
        opens.append(1)
        if len(opens) == 1:
            backend._camera_failure = "camera 0 is in use or permission was denied"
            return None, None
        backend._camera_failure = ""
        backend._camera_open = True
        backend._idle.clear()
        return _Cap(), SimpleNamespace(cvtColor=lambda f, c: f, COLOR_BGR2RGB=0)

    backend._open_camera = open_camera
    t = threading.Thread(target=backend.run, daemon=True)
    t.start()
    try:
        assert _wait_for(lambda: len(opens) == 1)
        assert _wait_for(lambda: "in use" in backend.camera_failure)
        assert t.is_alive(), "run() must wait, not return, after a failed first open"
        backend.pause_camera()
        backend.resume_camera()  # camera off, then on
        assert _wait_for(lambda: backend.camera_held), "camera on must reopen the device"
        assert backend.camera_failure == ""
    finally:
        backend.stop()
        t.join(3.0)
    assert not t.is_alive()
    assert closed == [1]  # the landmarker is closed once, on stop


# ---------------------------------------------------------------- 2. CLI honesty


class _Daemon:
    def __init__(self, error=None, reply=None):
        self.error, self.reply, self.calls = error, reply, []

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


def test_cli_timeout_is_not_reported_as_daemon_not_running(daemon):
    daemon.error = IpcTimeoutError("sock")
    result = runner.invoke(cli.app, ["camera", "off"])
    assert result.exit_code == 1
    assert "not running" not in result.output
    assert "still switching" in result.output


@pytest.mark.parametrize("word", ["on", "off"])
def test_cli_switching_waits_longer_than_the_default(daemon, word):
    daemon.reply = {"ok": True, "state": word, "holders": [], "consumers": [], "failures": {}}
    runner.invoke(cli.app, ["camera", word])
    assert daemon.calls[0][1]["wait_s"] >= 10


def test_cli_use_waits_longer_than_the_default(daemon):
    daemon.reply = {"ok": True, "state": "on", "holders": [], "consumers": [], "failures": {}}
    runner.invoke(cli.app, ["camera", "use", "0"])
    assert daemon.calls[0][1]["wait_s"] >= 10


def test_cli_older_daemon_without_the_camera_method_has_no_traceback(daemon):
    daemon.error = IpcCallError(RpcError(code=-32601, message="Method not found: camera"))
    result = runner.invoke(cli.app, ["camera", "status"])
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "Traceback" not in result.output
    assert "older" in result.output


def test_linux_tray_camera_click_does_not_block_the_ui_thread():
    from yazses.platform.linux.tray import LinuxTray

    release = threading.Event()
    entered = threading.Event()
    sent: list[object] = []

    class Ctl:
        def set_camera(self, on):
            entered.set()
            release.wait(5.0)
            return {"ok": True, "state": "on" if on else "off", "holders": []}

    tray = LinuxTray.__new__(LinuxTray)
    tray._controller = Ctl()
    tray._bridge = SimpleNamespace(notified=SimpleNamespace(emit=sent.append))
    tray._notify = lambda *a: sent.append(a)
    done = threading.Event()
    threading.Thread(target=lambda: (tray._on_camera("off"), done.set()), daemon=True).start()
    try:
        assert done.wait(1.0), "_on_camera blocked the calling (UI) thread"
        assert entered.wait(1.0)
    finally:
        release.set()
    assert _wait_for(lambda: bool(sent))


# ---------------------------------------------------------------- 3. transitions


def test_concurrent_off_then_on_cannot_leave_switch_on_with_camera_released():
    state = {"held": True}
    entered, gate = threading.Event(), threading.Event()

    def pause():
        entered.set()
        gate.wait(0.4)
        state["held"] = False

    def resume():
        state["held"] = True

    s = CameraSwitch()
    s.register(CameraConsumer("c", pause, resume, holders=lambda: ("c",) if state["held"] else ()))
    a = threading.Thread(target=lambda: s.set(False), daemon=True)
    a.start()
    assert entered.wait(2.0)
    b = threading.Thread(target=lambda: s.set(True), daemon=True)
    b.start()
    b.join(0.05)
    gate.set()
    a.join(3.0)
    b.join(3.0)
    assert not a.is_alive() and not b.is_alive()
    assert state["held"] == s.is_on


def test_use_camera_is_one_transition_against_a_concurrent_off():
    state = {"held": True}
    entered, gate = threading.Event(), threading.Event()
    seen: list[int] = []

    def pause():
        entered.set()
        gate.wait(0.4)
        state["held"] = False

    def resume():
        state["held"] = True

    s = CameraSwitch()
    s.register(CameraConsumer("c", pause, resume, set_index=seen.append,
                              holders=lambda: ("c",) if state["held"] else ()))
    a = threading.Thread(target=lambda: s.use_camera(2, "cam"), daemon=True)
    a.start()
    assert entered.wait(2.0)
    b = threading.Thread(target=lambda: s.set(False), daemon=True)
    b.start()
    b.join(0.05)
    gate.set()
    a.join(3.0)
    b.join(3.0)
    assert not a.is_alive() and not b.is_alive()
    assert state["held"] == s.is_on
    assert not s.is_on  # the off that arrived mid-switch is applied after it, not lost


def test_observers_run_outside_the_transition_lock():
    s = CameraSwitch()
    s.register(CameraConsumer("c", lambda: None, lambda: None))
    result: list[bool] = []

    def observer(on):
        if on:
            return
        t = threading.Thread(target=lambda: result.append(s.set(True)), daemon=True)
        t.start()
        t.join(2.0)  # would deadlock if the transition lock were still held here
        assert not t.is_alive()

    s.subscribe(observer)
    s.set(False)
    assert result == [True]


def test_concurrent_flips_leave_the_consumer_matching_the_switch():
    state = {"held": True}
    s = CameraSwitch()
    s.register(CameraConsumer(
        "c", lambda: state.update(held=False), lambda: state.update(held=True),
        holders=lambda: ("c",) if state["held"] else (),
    ))
    threads = [threading.Thread(target=lambda: [s.toggle() for _ in range(300)], daemon=True)
               for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5.0)
    assert not any(t.is_alive() for t in threads)
    assert state["held"] == s.is_on


# ---------------------------------------------------------------- 6. retry when ON


def test_camera_on_when_already_on_retries_a_consumer_that_failed_to_reopen():
    state = {"fail": "camera 0 is busy", "resumes": 0}

    def resume():
        state["resumes"] += 1
        state["fail"] = ""

    healthy = {"resumes": 0}
    s = CameraSwitch()
    s.register(CameraConsumer("gaze", lambda: None, resume, failure=lambda: state["fail"]))
    s.register(CameraConsumer("ok", lambda: None,
                              lambda: healthy.update(resumes=healthy["resumes"] + 1)))
    s.set(True)
    assert state["resumes"] == 1
    assert state["fail"] == ""
    assert healthy["resumes"] == 0  # a healthy consumer is not touched
    s.set(True)
    assert state["resumes"] == 1  # nothing failing: a true no-op again


# ---------------------------------------------------------------- 4/5. gaze backends


class _GCap:
    def __init__(self, ok=True, gate=None, entered=None):
        self.ok, self.gate, self.entered, self.released = ok, gate, entered, False

    def isOpened(self):
        return self.ok

    def read(self):
        if self.entered:
            self.entered.set()
        if self.gate:
            self.gate.wait(3.0)
        return True, object()

    def release(self):
        self.released = True


def _stub(which, cap_factory):
    if which == "mp":
        from yazses.gaze.mediapipe_backend import MediapipeGazeBackend as cls
    else:
        from yazses.gaze.l2cs import L2csGazeBackend as cls
    obj = cls.__new__(cls)
    caps: list[_GCap] = []
    obj._cv2 = SimpleNamespace(
        VideoCapture=lambda i: caps.append(cap_factory()) or caps[-1],
        cvtColor=lambda f, c: f, COLOR_BGR2RGB=0,
    )
    obj._mp = SimpleNamespace(Image=lambda **kw: object(),
                              ImageFormat=SimpleNamespace(SRGB=1))
    obj._landmarker = SimpleNamespace(detect=lambda image: SimpleNamespace(face_landmarks=[]))
    obj._pipeline = SimpleNamespace(step=lambda frame: None)
    obj._camera_index = 0
    obj._cap = None
    obj._camera_off = False
    obj._camera_failure = ""
    obj._camera_lock = threading.RLock()
    return obj, caps


@pytest.mark.parametrize("which", ["mp", "l2cs"])
def test_pause_waits_for_an_in_flight_read(which):
    gate, entered = threading.Event(), threading.Event()
    b, caps = _stub(which, lambda: _GCap(gate=gate, entered=entered))
    reader = threading.Thread(target=b.estimate, daemon=True)
    reader.start()
    assert entered.wait(2.0)
    pauser = threading.Thread(target=b.pause_camera, daemon=True)
    pauser.start()
    pauser.join(0.2)
    try:
        assert not caps[0].released, "released the device under a read in progress"
    finally:
        gate.set()
    reader.join(3.0)
    pauser.join(3.0)
    assert caps[0].released and not b.camera_held


@pytest.mark.parametrize("which", ["mp", "l2cs"])
def test_a_camera_that_will_not_open_is_not_retried_on_every_estimate(which):
    b, caps = _stub(which, lambda: _GCap(ok=False))
    for _ in range(5):
        b.estimate()
    assert len(caps) == 1
    b.resume_camera()  # an explicit camera on retries at once
    assert len(caps) == 2
    b.estimate()
    assert len(caps) == 2
    b._open_retry_at = 0.0  # the backoff has run out
    b.estimate()
    assert len(caps) == 3


# ---------------------------------------------------------------- 7. path matching


def test_resolve_matches_a_windows_style_path():
    win = r"C:\cams\video0"
    dev = CameraDevice(0, "Cam", (win,))
    assert resolve_camera([dev], win).device == dev
