"""Covered camera in the camera lifecycle (#923): switch, watch, daemon and surfaces.

Fakes and generated frames only: no camera, no OpenCV, no daemon process. The watch is
driven by hand (`tick`) with a fake clock, except where a thread is the point.
"""
from __future__ import annotations

import dataclasses
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from yazses.config import Config, FacegestureConfig, load_config
from yazses.core.daemon import Daemon
from yazses.facegesture.backend import FaceGestureBackend
from yazses.handsfree.observability import (
    PERCEPTION_COVERED,
    HandsFreeFacts,
    Health,
    health_rows,
)
from yazses.ipc.protocol import Request
from yazses.perception.cover import PROBE_BLANK, PROBE_CLEAR, PROBE_DELAY_S, PROBE_UNKNOWN
from yazses.perception.coverwatch import CoverWatch
from yazses.perception.source import SharedPerceptionSource, SourceState
from yazses.perception.switch import CameraConsumer, CameraSwitch
from yazses.platform import get_platform
from yazses.system.doctor import _camera_cover_check
from yazses.tray import camera as tray_camera

DARK = np.zeros((48, 64, 3), dtype=np.uint8)
BRIGHT = np.full((48, 64, 3), 120, dtype=np.uint8)


class _Owner:
    """A camera owner that holds a device until paused."""

    def __init__(self, switch, name="facegesture", index=0):
        self.index = index
        self.held = True
        self.log: list[str] = []
        switch.register(CameraConsumer(
            name, self._pause, self._resume,
            holders=lambda: (name,) if self.held else (),
            camera_index=lambda: self.index,
        ))

    def _pause(self):
        self.log.append("pause")
        self.held = False

    def _resume(self):
        self.log.append("resume")
        self.held = True


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _rig(*, signal=None, verdicts=()):
    switch = CameraSwitch()
    owner = _Owner(switch)
    clock = _Clock()
    probes: list[int] = []
    queue = list(verdicts)

    def probe(index, cancelled):
        probes.append(index)
        return queue.pop(0) if queue else PROBE_BLANK

    watch = CoverWatch(switch, probe=probe, signal=signal, clock=clock)
    return switch, owner, watch, clock, probes


def _feed(watch, clock, frame, seconds, index=0, step=0.25):
    for _ in range(int(seconds / step) + 1):
        watch.observe(index, frame)
        clock.now += step


# ---------------------------------------------------------------- the switch


def test_cover_releases_only_the_owners_of_that_camera():
    switch = CameraSwitch()
    near, far = _Owner(switch, "facegesture", 0), _Owner(switch, "gaze", 1)
    assert switch.cover(0) is True
    assert not near.held and far.held
    assert switch.is_on and switch.covered == (0,)
    assert switch.status().as_payload()["covered"] == [0]
    assert switch.cover(0) is False  # already covered
    assert switch.uncover(0) is True
    assert near.held and switch.covered == () and far.log == []


def test_cover_is_refused_when_off_unowned_or_stale():
    switch = CameraSwitch()
    _Owner(switch)
    assert switch.cover(7) is False
    stale = switch.generation
    switch.set(True)  # any user transition
    assert switch.cover(0, stale) is False
    switch.set(False)
    assert switch.cover(0) is False and switch.covered == ()


def test_camera_on_takes_a_covered_camera_back():
    switch = CameraSwitch()
    owner = _Owner(switch)
    switch.cover(0)
    assert switch.set(True) is False  # it was never switched off
    assert owner.held and switch.covered == ()


def test_off_forgets_the_cover_and_uncover_cannot_undo_off():
    switch = CameraSwitch()
    owner = _Owner(switch)
    switch.cover(0)
    switch.set(False)
    assert switch.covered == ()
    assert switch.uncover(0) is False and not owner.held


def test_choosing_another_camera_forgets_the_cover():
    switch = CameraSwitch()
    owner = _Owner(switch)
    switch.cover(0)
    switch.use_camera(2, "other")
    assert switch.covered == () and owner.held


def test_an_owner_registered_on_a_covered_camera_is_paused():
    switch = CameraSwitch()
    _Owner(switch)
    switch.cover(0)
    late = _Owner(switch, "gaze", 0)
    assert not late.held


# ---------------------------------------------------------------- the watch


def test_dark_frames_release_the_camera_only_after_the_window():
    switch, owner, watch, clock, probes = _rig()
    _feed(watch, clock, DARK, 3.0)
    watch.tick()
    assert owner.held
    _feed(watch, clock, DARK, 3.0)
    watch.tick()
    assert not owner.held and switch.covered == (0,) and probes == []


def test_a_picture_never_covers():
    switch, owner, watch, clock, _ = _rig()
    _feed(watch, clock, BRIGHT, 30.0)
    watch.tick()
    assert owner.held and switch.covered == ()


def test_probes_are_slow_back_off_and_resume_on_a_picture():
    switch, owner, watch, clock, probes = _rig(
        verdicts=[PROBE_BLANK, PROBE_UNKNOWN, PROBE_CLEAR]
    )
    _feed(watch, clock, DARK, 6.0)
    watch.tick()
    watch.tick()
    assert probes == []  # not in a tight loop
    for wait, count in ((PROBE_DELAY_S, 1), (2 * PROBE_DELAY_S, 2), (4 * PROBE_DELAY_S, 3)):
        clock.now += wait - 0.5
        watch.tick()
        assert len(probes) == count - 1
        clock.now += 0.6
        watch.tick()
        assert len(probes) == count
    assert owner.held and switch.covered == ()


def test_after_resuming_a_new_full_run_is_needed():
    switch, owner, watch, clock, _ = _rig(verdicts=[PROBE_CLEAR])
    _feed(watch, clock, DARK, 6.0)
    watch.tick()
    clock.now += PROBE_DELAY_S
    watch.tick()
    assert owner.held
    _feed(watch, clock, DARK, 1.0)
    watch.tick()
    assert owner.held


def test_switched_off_nothing_is_measured_or_probed():
    switch, owner, watch, clock, probes = _rig()
    _feed(watch, clock, DARK, 6.0)
    watch.tick()
    switch.set(False)
    clock.now += 100.0
    watch.tick()
    assert probes == [] and not owner.held


def test_camera_on_restarts_the_run():
    switch, owner, watch, clock, probes = _rig()
    _feed(watch, clock, DARK, 6.0)
    watch.tick()
    switch.set(True)
    assert owner.held
    _feed(watch, clock, DARK, 1.0)
    watch.tick()
    assert owner.held and probes == []


def test_a_hardware_signal_covers_at_once_and_uncovers_without_a_probe():
    state: dict[str, bool | None] = {"closed": True}
    switch, owner, watch, clock, probes = _rig(signal=lambda index: state["closed"])
    watch.tick()
    assert not owner.held
    clock.now += 100.0
    watch.tick()
    assert probes == []  # the hardware says closed: no reason to open the camera
    state["closed"] = False
    watch.tick()
    assert owner.held and switch.covered == () and probes == []


def test_a_signal_that_says_open_does_not_override_dark_frames():
    switch, owner, watch, clock, probes = _rig(signal=lambda index: False)
    _feed(watch, clock, DARK, 6.0)
    watch.tick()
    assert not owner.held
    watch.tick()
    assert not owner.held  # "open" from the hardware does not uncover a frame verdict
    clock.now += PROBE_DELAY_S
    watch.tick()
    assert probes == [0]


def test_a_signal_that_disappears_falls_back_to_probing():
    state: dict[str, bool | None] = {"closed": True}
    switch, owner, watch, clock, probes = _rig(
        signal=lambda index: state["closed"], verdicts=[PROBE_CLEAR]
    )
    watch.tick()
    state["closed"] = None
    clock.now += PROBE_DELAY_S
    watch.tick()
    assert probes == [0] and owner.held


def test_a_failing_signal_or_probe_is_contained():
    def boom(*_args):
        raise OSError("nope")

    switch = CameraSwitch()
    owner = _Owner(switch)
    clock = _Clock()
    watch = CoverWatch(switch, probe=boom, signal=boom, clock=clock)
    _feed(watch, clock, DARK, 6.0)
    watch.tick()
    clock.now += PROBE_DELAY_S
    watch.tick()
    assert not owner.held and switch.covered == (0,)


def test_camera_off_waits_for_a_probe_to_let_the_camera_go():
    switch = CameraSwitch()
    _Owner(switch)
    clock = _Clock()
    probing, released = threading.Event(), threading.Event()

    def probe(index, cancelled):
        probing.set()
        pause = threading.Event()
        for _ in range(500):
            if cancelled():
                break
            pause.wait(0.01)
        released.set()
        return PROBE_BLANK

    watch = CoverWatch(switch, probe=probe, clock=clock)
    _feed(watch, clock, DARK, 6.0)
    watch.tick()
    clock.now += PROBE_DELAY_S
    thread = threading.Thread(target=watch.tick, daemon=True)
    thread.start()
    try:
        assert probing.wait(3.0)
        switch.set(False)
        assert released.is_set(), "`camera off` returned while the probe held the camera"
    finally:
        watch.stop()
        thread.join(3.0)


def test_start_and_stop_are_idempotent_and_the_thread_ends():
    switch = CameraSwitch()
    watch = CoverWatch(switch, probe=lambda i, c: PROBE_BLANK, tick_s=0.01)
    watch.start()
    watch.start()
    watch.stop()
    watch.stop()
    assert not [t for t in threading.enumerate() if t.name == "yazses-camera-cover"]


# ---------------------------------------------------------------- the frame taps


class _Capture:
    opens = 0
    closes = 0

    def open(self):
        self.opens += 1

    def read(self):
        return DARK

    def close(self):
        self.closes += 1


class _Processor:
    name = "fake"

    def process(self, frame, timestamp_s):
        return None

    def close(self):
        pass


class _IdleWorker:
    def join(self, timeout=None):
        pass

    def is_alive(self):
        return False


def _source():
    capture = _Capture()
    source = SharedPerceptionSource(
        lambda: capture, _Processor, spawn=lambda body, name: _IdleWorker()
    )
    return source, capture


def test_the_shared_source_shows_each_frame_to_the_observer():
    source, _ = _source()
    seen: list[object] = []
    source.set_frame_observer(seen.append)
    source.consumer("x").start()
    source.observe()
    assert len(seen) == 1 and seen[0] is DARK


def test_a_failing_frame_observer_does_not_stop_the_source():
    source, _ = _source()
    source.set_frame_observer(lambda frame: 1 / 0)
    source.consumer("x").start()
    source.observe()
    assert source.status().state is SourceState.RUNNING


def test_the_face_switch_shows_its_own_frames_with_the_camera_index():
    backend = FaceGestureBackend(FacegestureConfig(enabled=True, camera_index=3))
    assert backend.camera_index == 3
    backend.set_camera_index(5)
    assert backend.camera_index == 5
    backend._open_index = 5
    seen: list[tuple[int, object]] = []
    backend.set_frame_observer(lambda index, frame: seen.append((index, frame)))
    backend._blendshapes(
        SimpleNamespace(detect=lambda image: SimpleNamespace(face_blendshapes=[])),
        SimpleNamespace(read=lambda: (True, DARK)),
        SimpleNamespace(cvtColor=lambda f, c: f, COLOR_BGR2RGB=0),
        SimpleNamespace(Image=lambda **kw: object(), ImageFormat=SimpleNamespace(SRGB=1)),
    )
    assert len(seen) == 1 and seen[0][0] == 5 and seen[0][1] is DARK


# ---------------------------------------------------------------- the daemon


def _daemon(cfg):
    platform = dataclasses.replace(get_platform(), camera_cover_factory=None)
    return Daemon(config=cfg, platform=platform)


def test_detection_is_off_by_default_and_from_the_config_file(tmp_path):
    assert Config().camera.cover_detection is False
    path = tmp_path / "config.toml"
    path.write_text("[camera]\ncover_detection = true\n", encoding="utf-8")
    assert load_config(path).camera.cover_detection is True


def test_with_detection_off_the_daemon_builds_no_watch():
    daemon = _daemon(Config())
    source, _ = _source()
    daemon._perception = source
    daemon._register_camera_consumers()
    assert daemon._cover_watch is None
    assert source._frame_observer is None


def test_the_daemon_releases_and_resumes_the_shared_camera(monkeypatch):
    monkeypatch.setattr(CoverWatch, "start", lambda self: None)  # ticked by hand
    cfg = Config()
    cfg.camera.cover_detection = True
    daemon = _daemon(cfg)
    source, capture = _source()
    daemon._perception = source
    daemon._register_camera_consumers()
    watch = daemon._cover_watch
    assert watch is not None
    clock = _Clock()
    watch._clock = clock
    watch._probe = lambda index, cancelled: PROBE_CLEAR
    source.consumer("headpointer").start()
    for _ in range(30):
        source.observe()
        clock.now += 0.25
    watch.tick()
    assert source.suspended and capture.closes == 1
    reply = daemon._handle_camera(Request("camera", {}))
    assert reply["state"] == "on" and reply["covered"] == [0] and reply["holders"] == []
    clock.now += PROBE_DELAY_S
    watch.tick()
    assert not source.suspended and capture.opens == 2
    assert daemon._handle_camera(Request("camera", {}))["covered"] == []


def test_status_health_says_the_camera_is_covered():
    cfg = Config()
    cfg.facegesture.enabled = True
    daemon = _daemon(cfg)
    daemon._extra_activations = [FaceGestureBackend(cfg.facegesture)]
    _Owner(daemon._camera_switch)
    daemon._camera_switch.cover(0)
    payload = daemon._handsfree_payload()
    assert payload is not None and payload["perception_state"] == PERCEPTION_COVERED


# ---------------------------------------------------------------- the surfaces


def test_the_perception_row_names_the_cover_and_the_way_out():
    facts = HandsFreeFacts(
        features_requested=("facegesture",), perception_state=PERCEPTION_COVERED
    )
    row = next(r for r in health_rows(facts) if r.label == "Hands-free perception")
    assert row.health is Health.DEGRADED
    assert "covered" in row.reason and "yazses camera on" in row.remedy


@pytest.mark.parametrize("index", [0, 2])
def test_the_tray_says_covered_including_for_camera_zero(index):
    entry = tray_camera.camera_entry({"camera": {
        "state": "on", "holders": [], "consumers": ["facegesture"], "covered": [index],
    }})
    assert entry is not None and entry.covered and entry.checked
    assert entry.indicator.startswith("Camera covered")


def test_the_tray_prefers_off_over_covered_and_ignores_an_older_daemon():
    base = {"holders": [], "consumers": ["facegesture"]}
    off = tray_camera.camera_entry({"camera": {**base, "state": "off", "covered": [0]}})
    assert off is not None and not off.covered and "off" in off.indicator
    old = tray_camera.camera_entry({"camera": {**base, "state": "on"}})
    assert old is not None and not old.covered


def test_camera_status_prints_the_covered_camera(capsys):
    from yazses import cli

    cli._echo_camera({
        "state": "on", "holders": [], "consumers": ["facegesture"], "covered": [0],
    })
    out = capsys.readouterr().out
    assert "Camera 0 looks covered" in out
    assert "not holding" not in out


def _cover_row(*, detection=True, covered=(), reading=None, camera_row=("Camera", "OK", "")):
    cfg = Config()
    cfg.facegesture.enabled = True
    cfg.camera.cover_detection = detection
    return _camera_cover_check(
        cfg, SimpleNamespace(camera_cover_factory=None), camera_row,
        daemon_covered=list(covered), signal=lambda index: reading,
    )


def test_doctor_is_silent_unless_detection_and_a_camera_feature_are_on():
    assert _cover_row(detection=False) is None
    assert _cover_row(camera_row=None) is None


def test_doctor_warns_when_the_daemon_released_a_covered_camera():
    row = _cover_row(covered=[0])
    assert row is not None and row[1] == "WARN" and "camera 0" in row[2]


@pytest.mark.parametrize(
    "reading,status,word",
    [(True, "WARN", "closed"), (False, "OK", "reports open"), (None, "OK", "black frames")],
)
def test_doctor_reports_the_hardware_signal(reading, status, word):
    row = _cover_row(reading=reading)
    assert row is not None and row[1] == status and word in row[2]
