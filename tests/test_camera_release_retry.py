"""Getting the camera back after another application had it, and saying so (#922).

A call app holds the webcam; `camera on` fails; the call ends; `camera on` must now work,
and each reply must describe what really happened. Fakes only: no camera, no OpenCV, no
daemon process. Every thread a test starts is stopped and joined in a ``finally``.
"""
from __future__ import annotations

import logging
import sys
import threading
import types
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from yazses import cli
from yazses.config import Config, FacegestureConfig
from yazses.core.daemon import Daemon
from yazses.facegesture.backend import FaceGestureBackend
from yazses.ipc.protocol import Request
from yazses.perception.camera import camera_held_message
from yazses.perception.source import SharedPerceptionSource, SourceState
from yazses.platform import get_platform

runner = CliRunner()

BUSY = "camera 0 is in use or permission was denied"


def _wait_for(pred, timeout=3.0):
    done = threading.Event()
    for _ in range(int(timeout / 0.01)):
        if pred():
            return True
        done.wait(0.01)
    return pred()


# ------------------------------------------------------------------ shared source


class _Device:
    """One webcam another application can take."""

    def __init__(self, busy=False):
        self.busy = busy
        self.broken = False
        self.opens = self.closes = 0

    def open(self):
        if self.busy:
            raise OSError(BUSY)
        self.opens += 1

    def read(self):
        if self.broken:
            raise OSError("camera 0 disconnected")
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


def _source(device):
    return SharedPerceptionSource(lambda: device, _Proc, interval_s=0.0, spawn=_Worker)


def test_camera_on_retries_a_shared_camera_that_another_app_was_holding():
    device = _Device(busy=True)
    source = _source(device)
    daemon = Daemon(config=Config(), platform=get_platform())
    daemon._perception = source
    daemon._extra_activations = []
    daemon._gaze_targeter = None
    source.consumer("headpointer").start()  # the call already has the camera
    daemon._register_camera_consumers()
    assert source.status().state is SourceState.FAILED

    still_busy = daemon._handle_camera(Request("camera", {"action": "on"}))
    assert BUSY in still_busy["failures"]["shared camera"]
    assert still_busy["holders"] == []

    device.busy = False  # the call ended
    reply = daemon._handle_camera(Request("camera", {"action": "on"}))
    assert reply["failures"] == {}
    assert reply["holders"] == ["headpointer"]
    assert device.opens == 1


def test_off_on_during_a_call_then_on_again_after_it():
    device = _Device()
    source = _source(device)
    source.consumer("gaze").start()
    source.suspend()
    device.busy = True
    source.resume()
    assert source.status().state is SourceState.FAILED
    device.busy = False
    source.resume()
    assert source.status().state is SourceState.RUNNING
    assert source.status().failure_reason == ""
    assert device.opens == 2


def test_resume_reopens_a_source_whose_camera_went_away():
    device = _Device()
    source = _source(device)
    source.consumer("gaze").start()
    device.broken = True
    assert source.observe() is False
    assert source.status().state is SourceState.FAILED
    assert device.closes == 1
    device.broken = False
    source.resume()
    assert source.status().state is SourceState.RUNNING
    assert device.opens == 2 and device.closes == 1


def test_resume_leaves_a_running_source_alone_and_a_new_consumer_never_retries():
    device = _Device()
    source = _source(device)
    source.consumer("gaze").start()
    source.resume()
    assert device.opens == 1

    busy = _Device(busy=True)
    failed = _source(busy)
    failed.consumer("gaze").start()
    busy.busy = False
    failed.consumer("headpointer").start()
    assert busy.opens == 0 and failed.status().state is SourceState.FAILED


def test_resume_after_the_last_lease_left_a_failed_source_opens_nothing():
    device = _Device(busy=True)
    source = _source(device)
    lease = source.consumer("gaze")
    lease.start()
    lease.stop()
    device.busy = False
    source.resume()
    assert device.opens == 0 and source.status().state is SourceState.DORMANT


# ------------------------------------------------------------------ face switch


class _Cap:
    def __init__(self):
        self.released = False

    def read(self):
        return True, object()

    def release(self):
        self.released = True


@contextmanager
def _face(monkeypatch, open_camera):
    """A face switch over fakes; *open_camera(backend)* stands in for ``_open_camera``."""
    mp = types.ModuleType("mediapipe")
    mp.Image = lambda **kw: object()
    mp.ImageFormat = SimpleNamespace(SRGB=1)
    monkeypatch.setitem(sys.modules, "mediapipe", mp)
    backend = FaceGestureBackend(FacegestureConfig(enabled=True, fps=60))
    backend._build_landmarker = lambda: SimpleNamespace(
        detect=lambda image: SimpleNamespace(face_blendshapes=[]), close=lambda: None
    )
    backend._open_camera = lambda: open_camera(backend)
    thread = threading.Thread(target=backend.run, daemon=True)
    try:
        yield backend, thread
    finally:
        backend.stop()
        if thread.ident is not None:
            thread.join(3.0)
            assert not thread.is_alive()


def _opened(backend, cap):
    backend._camera_failure = ""
    backend._camera_open = True
    backend._idle.clear()
    return cap, SimpleNamespace(cvtColor=lambda f, c: f, COLOR_BGR2RGB=0)


def _in_thread(fn):
    thread = threading.Thread(target=fn, daemon=True)
    thread.start()
    return thread


def test_face_camera_on_returns_only_after_the_attempt_so_the_failure_is_in_the_reply(
    monkeypatch,
):
    attempts: list[int] = []
    entered, gate = threading.Event(), threading.Event()

    def open_camera(backend):
        attempts.append(1)
        if len(attempts) == 1:
            return _opened(backend, _Cap())
        entered.set()
        gate.wait(3.0)
        backend._camera_failure = BUSY
        return None, None

    with _face(monkeypatch, open_camera) as (backend, thread):
        thread.start()
        assert _wait_for(lambda: backend.camera_held)
        backend.pause_camera()
        resumer = _in_thread(backend.resume_camera)
        try:
            assert entered.wait(2.0)
            resumer.join(0.2)
            assert resumer.is_alive(), "camera on replied before the device was tried"
        finally:
            gate.set()
        resumer.join(3.0)
        assert not resumer.is_alive()
        assert backend.camera_failure == BUSY and not backend.camera_held


def test_face_camera_on_has_the_device_when_it_returns(monkeypatch):
    with _face(monkeypatch, lambda b: _opened(b, _Cap())) as (backend, thread):
        thread.start()
        assert _wait_for(lambda: backend.camera_held)
        for _ in range(20):
            backend.pause_camera()
            assert not backend.camera_held
            backend.resume_camera()
            assert backend.camera_held


def test_face_camera_off_waits_for_an_open_in_progress(monkeypatch):
    entered, gate = threading.Event(), threading.Event()
    caps: list[_Cap] = []

    def open_camera(backend):
        entered.set()
        gate.wait(3.0)
        caps.append(_Cap())
        return _opened(backend, caps[-1])

    with _face(monkeypatch, open_camera) as (backend, thread):
        thread.start()
        assert entered.wait(2.0)
        pauser = _in_thread(backend.pause_camera)
        try:
            pauser.join(0.2)
            assert pauser.is_alive(), "camera off replied while the device was being taken"
        finally:
            gate.set()
        pauser.join(3.0)
        assert not pauser.is_alive()
        assert caps[0].released and not backend.camera_held


def test_face_switch_does_not_open_a_camera_switched_off_before_it_started(monkeypatch):
    opens: list[int] = []

    def open_camera(backend):
        opens.append(1)
        return _opened(backend, _Cap())

    with _face(monkeypatch, open_camera) as (backend, thread):
        backend.pause_camera()
        thread.start()
        assert _wait_for(lambda: backend._watching)
        assert opens == []
        backend.resume_camera()
        assert backend.camera_held and opens == [1]


def test_face_camera_on_does_not_wait_when_no_loop_is_there_to_answer(monkeypatch):
    with _face(monkeypatch, lambda b: (None, None)) as (backend, _thread):
        resumer = _in_thread(backend.resume_camera)  # never started: nothing will attempt
        resumer.join(2.0)
        assert not resumer.is_alive()


# ------------------------------------------------------------------ logs and CLI


@pytest.mark.parametrize("which", ["mp", "l2cs"])
def test_gaze_on_its_own_camera_logs_when_it_takes_and_releases_it(which, caplog):
    if which == "mp":
        from yazses.gaze.mediapipe_backend import MediapipeGazeBackend as cls
    else:
        from yazses.gaze.l2cs import L2csGazeBackend as cls
    backend = cls.__new__(cls)
    backend._cv2 = SimpleNamespace(
        VideoCapture=lambda i: SimpleNamespace(isOpened=lambda: True, release=lambda: None)
    )
    backend._camera_index = 2
    backend._cap = None
    backend._camera_off = False
    backend._camera_failure = ""
    backend._camera_lock = threading.RLock()
    with caplog.at_level(logging.INFO, logger=cls.__module__):
        backend._ensure_camera()
        backend._ensure_camera()
        backend.pause_camera()
        backend.close()
    messages = [r.getMessage() for r in caplog.records if r.name == cls.__module__]
    assert messages == [camera_held_message(2), camera_held_message(2, released=True)]


@pytest.mark.parametrize(
    ("state", "failures", "hinted"),
    [("on", {"shared camera": BUSY}, True), ("on", {}, False), ("off", {}, False)],
)
def test_cli_says_how_to_retry_a_camera_that_could_not_be_reopened(
    monkeypatch, tmp_path, state, failures, hinted
):
    reply = {"ok": True, "state": state, "holders": [], "consumers": ["shared camera"],
             "failures": failures}
    platform = SimpleNamespace(
        paths=SimpleNamespace(ipc_socket=tmp_path / "sock", config_file=tmp_path / "c.toml"),
        ipc_client_factory=lambda _sock: SimpleNamespace(call=lambda method, **p: reply),
    )
    monkeypatch.setattr(cli, "get_platform", lambda: platform)
    result = runner.invoke(cli.app, ["camera", "on"])
    assert result.exit_code == 0, result.output
    assert ("then retry: yazses camera on" in result.output) is hinted
