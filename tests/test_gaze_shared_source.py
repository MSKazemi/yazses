"""Glance-Type gaze leases the shared camera instead of owning one (#396).

`tests/test_gaze_glance_type_unchanged.py` pins that gaze *behaves* the same; this file
pins the part that is meant to change — who owns the camera — and the seams around it.
The claims, each a test below:

* the adapter takes its lease lazily, on the first sample, and gives it back on close;
* a second camera consumer on the same source does not open a second device;
* a stale, missing or face-less observation is "no gaze", never the last value replayed;
* the wiring shares the camera only when sharing is correct (same device, MediaPipe
  backend), and is byte-for-byte the old path otherwise.

Hermetic: a numeric fake lease, plus the real ``SharedPerceptionSource`` over fake
capture/processor objects for the one-open assertion. No camera, no model, no gaze
extra, no thread.
"""
from __future__ import annotations

import logging
import sys
import types

import numpy as np
import pytest

from tests.test_gaze_glance_type_unchanged import (
    _SCRIPT,
    _decisions,
)
from yazses.config import Config, GazeConfig, PerceptionConfig
from yazses.gaze.calibrate import CalibrationMap
from yazses.gaze.shared import (
    FIRST_SAMPLE_WAIT_S,
    MAX_SAMPLE_AGE_S,
    SharedGazeBackend,
    shared_source_for_gaze,
)
from yazses.gaze.targeter import GazeTargeter
from yazses.perception import GazeSignal, PerceptionSample, SharedPerceptionSource, SourceState

# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


class Clock:
    """A clock that only moves when told to, and a sleep that tells it to."""

    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakeLease:
    """``FacePerceptionSource`` as a consumer sees it, counting what was done to it."""

    def __init__(self, clock: Clock, samples=()):
        self._clock = clock
        self._samples = list(samples)
        self.starts = 0
        self.stops = 0
        self.reads = 0
        #: When set, the n-th ``latest()`` is the first to return a sample (warm-up).
        self.available_from_read = 1

    def start(self) -> None:
        self.starts += 1

    def stop(self) -> None:
        self.stops += 1

    def latest(self):
        self.reads += 1
        if self.reads < self.available_from_read:
            return None
        return self._samples.pop(0) if len(self._samples) > 1 else (
            self._samples[0] if self._samples else None
        )


def sample(clock: Clock, *, age=0.0, x=0.3, y=-0.1, confidence=0.9, gaze=True):
    stamp = clock.now - age
    return PerceptionSample(
        timestamp_s=stamp,
        gaze=GazeSignal(stamp, x, y, confidence) if gaze else None,
    )


def backend(lease, clock, **kwargs):
    return SharedGazeBackend(lease, clock=clock, sleep=clock.sleep, **kwargs)


# --------------------------------------------------------------------------- #
# The adapter
# --------------------------------------------------------------------------- #


def test_building_the_adapter_takes_no_lease() -> None:
    """The webcam light must not come on because gaze is *enabled* (legacy was lazy too)."""
    clock = Clock()
    lease = FakeLease(clock, [sample(clock)])
    backend(lease, clock)
    assert lease.starts == 0 and lease.reads == 0


def test_the_first_sample_takes_the_lease_once_and_later_ones_do_not() -> None:
    clock = Clock()
    lease = FakeLease(clock, [sample(clock)])
    shared = backend(lease, clock)
    shared.estimate_sample()
    shared.estimate_sample()
    shared.estimate_sample()
    assert lease.starts == 1


def test_a_fresh_observation_becomes_the_calibration_input_unchanged() -> None:
    clock = Clock()
    shared = backend(FakeLease(clock, [sample(clock, x=0.31, y=-0.17, confidence=0.83)]), clock)
    got = shared.estimate_sample()
    assert got is not None
    assert (got.x, got.y, got.confidence) == (0.31, -0.17, 0.83)
    assert got.point == (0.31, -0.17)


def test_estimate_is_the_point_of_the_sample() -> None:
    clock = Clock()
    shared = backend(FakeLease(clock, [sample(clock, x=0.2, y=0.4)]), clock)
    assert shared.estimate() == (0.2, 0.4)


def test_the_backend_keeps_the_name_users_and_docs_know() -> None:
    assert backend(FakeLease(Clock()), Clock()).name == "mediapipe"


@pytest.mark.parametrize(
    ("age", "expected_none"),
    [
        (0.0, False),
        (MAX_SAMPLE_AGE_S, False),            # the bound itself is still fresh
        (MAX_SAMPLE_AGE_S + 0.001, True),     # one millisecond past it is history
        (30.0, True),
    ],
)
def test_an_observation_older_than_the_bound_is_no_gaze(age: float, expected_none: bool) -> None:
    """A stale sample is the face that left the frame, replayed. Routing on it is the
    wrong-window error the whole feature is built to avoid."""
    clock = Clock()
    shared = backend(FakeLease(clock, [sample(clock, age=age)]), clock)
    assert (shared.estimate_sample() is None) is expected_none


def test_a_sample_with_no_gaze_channel_is_no_gaze() -> None:
    """Head pose or blendshapes may arrive without an iris reading (ADR-v2-145 inv. 6)."""
    clock = Clock()
    shared = backend(FakeLease(clock, [sample(clock, gaze=False)]), clock)
    assert shared.estimate_sample() is None


def test_no_observation_at_all_is_no_gaze_and_waits_a_bounded_time_once() -> None:
    clock = Clock()
    lease = FakeLease(clock, [])  # a camera that never produces a face
    shared = backend(lease, clock)
    before = clock.now
    assert shared.estimate_sample() is None
    waited = clock.now - before
    assert 0 < waited <= FIRST_SAMPLE_WAIT_S + 0.05, "the warm-up wait must be bounded"

    before = clock.now
    assert shared.estimate_sample() is None
    assert clock.now == before, "only the call that opened the lease may wait"


def test_the_first_call_waits_for_the_camera_to_warm_up_instead_of_reporting_no_face() -> None:
    clock = Clock()

    class WarmingUp(FakeLease):
        def latest(self):
            self.reads += 1
            return None if self.reads <= 5 else sample(clock)

    lease = WarmingUp(clock)
    got = backend(lease, clock).estimate_sample()
    assert got is not None
    assert lease.starts == 1 and lease.reads == 6


def test_a_failed_source_gives_up_the_wait_at_once_and_says_why_exactly_once(caplog) -> None:
    clock = Clock()
    lease = FakeLease(clock, [])
    shared = backend(lease, clock, failure_reason=lambda: "the camera could not be opened (OSError)")
    with caplog.at_level(logging.WARNING, logger="yazses.gaze.shared"):
        before = clock.now
        assert shared.estimate_sample() is None
        assert clock.now - before < 0.05, "a source that already failed must not be waited on"
        assert shared.estimate_sample() is None
        assert shared.estimate_sample() is None
    reasons = [r for r in caplog.records if "shared camera is not running" in r.getMessage()]
    assert len(reasons) == 1
    assert "OSError" in reasons[0].getMessage()


def test_close_gives_the_lease_back_and_a_later_sample_takes_it_again() -> None:
    clock = Clock()
    lease = FakeLease(clock, [sample(clock)])
    shared = backend(lease, clock)
    shared.estimate_sample()
    shared.close()
    shared.close()  # idempotent at this layer: the lease itself ignores a duplicate
    assert lease.stops == 2  # forwarded; FacePerceptionSource.stop() is idempotent per lease
    shared.estimate_sample()
    assert lease.starts == 2


# --------------------------------------------------------------------------- #
# Same decisions as the old backend, through the real targeter
# --------------------------------------------------------------------------- #


def _lease_playing(clock: Clock, script):
    """A lease whose n-th ``latest()`` is the n-th scripted observation, stamped 'now'."""

    class Playing(FakeLease):
        def latest(self):
            self.reads += 1
            if not script:
                return None
            item = script.pop(0)
            if item is None:
                return None
            x, y, confidence = item
            return sample(clock, x=x, y=y, confidence=confidence)

    return Playing(clock)


def test_the_targeter_reaches_the_same_decisions_on_the_shared_adapter() -> None:
    clock = Clock()
    lease = _lease_playing(clock, list(_SCRIPT))
    shared_decisions, shared_activated = _decisions(backend(lease, clock))

    from tests.test_gaze_glance_type_unchanged import _ScriptedSamples

    legacy_decisions, legacy_activated = _decisions(_ScriptedSamples(_SCRIPT))
    assert shared_decisions == legacy_decisions
    assert shared_activated == legacy_activated == ["browser", "browser"]


def test_missing_gaze_still_falls_back_to_the_focused_window() -> None:
    clock = Clock()
    lease = FakeLease(clock, [sample(clock, gaze=False)])
    desktop = types.SimpleNamespace(
        focused_window=lambda: "editor", list_windows=lambda: [], activate=lambda w: None
    )
    decision = GazeTargeter(
        backend(lease, clock), CalibrationMap(A=np.eye(2, 3)), desktop
    ).retarget()
    assert (decision.used_gaze, decision.target) == (False, "editor")


def test_the_burst_snapshot_deixis_reads_is_the_decision_of_the_last_retarget() -> None:
    clock = Clock()
    lease = _lease_playing(clock, [(700.0, 500.0, 0.9)])
    desktop = types.SimpleNamespace(
        focused_window=lambda: "editor",
        list_windows=lambda: [("editor", 0, 0, 500, 1000), ("browser", 500, 0, 500, 1000)],
        activate=lambda w: None,
    )
    targeter = GazeTargeter(
        backend(lease, clock), CalibrationMap(A=np.eye(2, 3)), desktop
    )
    assert targeter.last_decision is None
    decision = targeter.retarget(activate=False)
    assert targeter.last_decision is decision
    assert decision.target == "browser" and decision.used_gaze


def test_closing_the_targeter_releases_the_lease() -> None:
    clock = Clock()
    lease = FakeLease(clock, [sample(clock)])
    shared = backend(lease, clock)
    shared.estimate_sample()
    GazeTargeter(shared, CalibrationMap(A=np.eye(2, 3)), types.SimpleNamespace()).close()
    assert lease.stops == 1


# --------------------------------------------------------------------------- #
# The point of the change: one physical camera for two consumers
# --------------------------------------------------------------------------- #


class _Capture:
    def __init__(self):
        self.opens = self.closes = 0

    def open(self):
        self.opens += 1

    def read(self):
        return object()

    def close(self):
        self.closes += 1


class _Processor:
    name = "fake"

    def __init__(self, clock):
        self._clock = clock
        self.closes = 0

    def process(self, frame, timestamp_s):
        return PerceptionSample(
            timestamp_s=timestamp_s, gaze=GazeSignal(timestamp_s, 0.1, 0.2, 0.9)
        )

    def close(self):
        self.closes += 1


class _NoThread:
    """A driver that never runs the loop; the test pumps ``observe()`` itself."""

    def __init__(self, body, name):
        pass

    def join(self, timeout=None):
        pass

    def is_alive(self):
        return False


def _real_source(clock):
    captures: list[_Capture] = []

    def capture_factory():
        captures.append(_Capture())
        return captures[-1]

    source = SharedPerceptionSource(
        capture_factory,
        lambda: _Processor(clock),
        clock=clock,
        spawn=lambda body, name: _NoThread(body, name),
    )
    return source, captures


def test_gaze_and_another_camera_consumer_open_one_physical_camera() -> None:
    clock = Clock()
    source, captures = _real_source(clock)
    shared = SharedGazeBackend(
        source.consumer("gaze"), clock=clock, sleep=clock.sleep,
        failure_reason=lambda: source.status().failure_reason,
    )
    head = source.consumer("head-pointer")

    assert source.status().opens == 0, "nothing opens until gaze asks"
    head.start()
    assert source.observe()
    assert shared.estimate_sample() is not None
    assert source.status().opens == 1
    assert len(captures) == 1
    assert source.status().consumers == ("gaze", "head-pointer")

    shared.close()
    assert captures[0].closes == 0, "the other consumer still holds the camera"
    head.stop()
    assert captures[0].closes == 1, "the last one out closes the device"
    assert source.status().state is SourceState.DORMANT


def test_gaze_reads_no_face_after_the_source_is_closed_not_the_last_one_seen() -> None:
    clock = Clock()
    source, _ = _real_source(clock)
    shared = SharedGazeBackend(
        source.consumer("gaze"), clock=clock, sleep=clock.sleep, first_sample_wait_s=0.0
    )
    shared.estimate_sample()          # takes the lease; the loop has not run yet
    source.observe()
    assert shared.estimate_sample() is not None
    source.close()                     # process shutdown, whatever the leases say
    assert shared.estimate_sample() is None
    assert source.status().opens == 1, "a closed source must not be reopened by a read"


def test_a_source_that_fails_to_open_leaves_gaze_silent_not_crashing(caplog) -> None:
    clock = Clock()

    class Broken(_Capture):
        def open(self):
            raise OSError("camera 0 could not be opened")

    source = SharedPerceptionSource(
        Broken, lambda: _Processor(clock), clock=clock, spawn=lambda b, n: _NoThread(b, n)
    )
    shared = SharedGazeBackend(
        source.consumer("gaze"), clock=clock, sleep=clock.sleep,
        failure_reason=lambda: source.status().failure_reason,
    )
    with caplog.at_level(logging.WARNING, logger="yazses.gaze.shared"):
        assert shared.estimate_sample() is None
    assert source.status().state is SourceState.FAILED
    assert any("could not be opened" in r.getMessage() for r in caplog.records)


# --------------------------------------------------------------------------- #
# Deciding whether gaze may share (pure)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("backend_name", "gaze_index", "perception_index", "source", "shares"),
    [
        ("mediapipe", 0, 0, object(), True),
        ("mediapipe", 2, 2, object(), True),
        ("mediapipe", 0, 0, None, False),       # [perception] off / no backend wired
        ("l2cs", 0, 0, object(), False),        # L2CS owns its pipeline (ADR allows it)
        ("mediapipe", 0, 1, object(), False),   # a different physical camera
        ("none", 0, 0, object(), False),
    ],
)
def test_gaze_shares_only_when_sharing_is_correct(
    backend_name, gaze_index, perception_index, source, shares
) -> None:
    choice = shared_source_for_gaze(
        GazeConfig(backend=backend_name, camera_index=gaze_index),
        PerceptionConfig(camera_index=perception_index),
        source,
    )
    assert (choice.source is not None) is shares
    if shares:
        assert choice.source is source
    assert choice.reason


def test_a_camera_index_mismatch_names_both_indexes() -> None:
    choice = shared_source_for_gaze(
        GazeConfig(camera_index=0), PerceptionConfig(camera_index=1), object()
    )
    assert "0" in choice.reason and "1" in choice.reason and "different cameras" in choice.reason


# --------------------------------------------------------------------------- #
# build_gaze
# --------------------------------------------------------------------------- #


def test_build_gaze_returns_the_old_backend_unless_a_source_is_supplied(monkeypatch) -> None:
    built = {}
    fake_mod = types.ModuleType("yazses.gaze.mediapipe_backend")
    fake_mod.MediapipeGazeBackend = lambda cfg: built.setdefault("legacy", "LEGACY")
    monkeypatch.setitem(sys.modules, "yazses.gaze.mediapipe_backend", fake_mod)
    monkeypatch.setitem(sys.modules, "mediapipe", types.ModuleType("mediapipe"))
    from yazses.gaze.factory import build_gaze

    assert build_gaze(GazeConfig(enabled=True)) == "LEGACY"
    assert build_gaze(GazeConfig(enabled=True), perception=None) == "LEGACY"


def test_build_gaze_with_a_source_leases_it_and_never_builds_a_camera(monkeypatch) -> None:
    exploding = types.ModuleType("yazses.gaze.mediapipe_backend")

    def boom(cfg):
        raise AssertionError("the own-camera backend must not be built when sharing")

    exploding.MediapipeGazeBackend = boom
    monkeypatch.setitem(sys.modules, "yazses.gaze.mediapipe_backend", exploding)
    monkeypatch.setitem(sys.modules, "mediapipe", types.ModuleType("mediapipe"))
    from yazses.gaze.factory import build_gaze

    clock = Clock()
    source, captures = _real_source(clock)
    got = build_gaze(GazeConfig(enabled=True), perception=source)
    assert isinstance(got, SharedGazeBackend)
    assert captures == [] and source.status().opens == 0


def test_build_gaze_still_names_a_missing_dependency_before_sharing(monkeypatch, caplog) -> None:
    """Sharing the camera must not hide "the mediapipe extra is not installed"."""
    import yazses.gaze.factory as factory_mod
    from yazses.system.backends import probe_backend as real_probe

    def probe_without_mediapipe(backend, **kwargs):
        kwargs["missing"] = lambda names: [n for n in names if n == "mediapipe"]
        return real_probe(backend, **kwargs)

    monkeypatch.setattr(factory_mod, "probe_backend", probe_without_mediapipe)
    from yazses.gaze.factory import build_gaze

    clock = Clock()
    source, _ = _real_source(clock)
    with caplog.at_level(logging.WARNING, logger="yazses.gaze.factory"):
        assert build_gaze(GazeConfig(enabled=True), perception=source) is None
    assert any("dormant" in r.getMessage() for r in caplog.records)


# --------------------------------------------------------------------------- #
# The daemon
# --------------------------------------------------------------------------- #


def _daemon(cfg):
    from yazses.core.daemon import Daemon
    from yazses.platform import get_platform

    return Daemon(config=cfg, platform=get_platform())


def test_an_enabled_perception_section_builds_a_dormant_source_without_importing_cv2(
    monkeypatch,
) -> None:
    monkeypatch.setitem(sys.modules, "cv2", None)         # importing it would raise
    monkeypatch.setitem(sys.modules, "mediapipe", None)
    cfg = Config()
    cfg.perception.enabled = True
    source = _daemon(Config())._build_perception_source(cfg)
    assert source is not None
    assert source.status().state is SourceState.DORMANT
    assert source.status().opens == 0


def _wire_a_gaze_daemon(monkeypatch, cfg):
    """Everything `_build_gaze_targeter` needs except a camera, a desktop and a display."""
    import yazses.gaze.desktop as desktop_mod
    import yazses.gaze.display as display_mod
    import yazses.gaze.factory as factory_mod
    import yazses.gaze.store as store_mod
    from yazses.gaze.topology import ContextCheck, Validity

    monkeypatch.setattr(desktop_mod, "build_desktop", lambda: object())
    monkeypatch.setattr(display_mod, "build_topology_provider", lambda: None)
    monkeypatch.setattr(display_mod, "current_context", lambda **kw: None)
    monkeypatch.setattr(
        store_mod,
        "calibration_state",
        lambda data_dir, ctx: (CalibrationMap(A=np.eye(2, 3)), ContextCheck(Validity.VALID, "ok")),
    )
    monkeypatch.setattr(
        factory_mod,
        "probe_backend",
        lambda *a, **k: types.SimpleNamespace(available=True, message=""),
    )
    monkeypatch.setitem(sys.modules, "mediapipe", types.ModuleType("mediapipe"))
    return _daemon(cfg)


def test_with_perception_on_the_daemon_wires_gaze_to_a_lease_and_opens_nothing(monkeypatch) -> None:
    cfg = Config()
    cfg.gaze.enabled = True
    cfg.gaze.route_dictation = True
    cfg.perception.enabled = True
    daemon = _wire_a_gaze_daemon(monkeypatch, cfg)
    daemon._perception = daemon._build_perception_source(cfg)

    targeter = daemon._build_gaze_targeter(cfg)

    assert targeter is not None
    assert isinstance(targeter._backend, SharedGazeBackend)
    assert daemon._gaze_on_shared_source is True
    assert daemon._perception.status().opens == 0, "wiring must not open the camera"
    targeter.close()


def test_with_perception_off_the_daemon_keeps_the_own_camera_backend(monkeypatch) -> None:
    cfg = Config()
    cfg.gaze.enabled = True
    cfg.gaze.route_dictation = True
    daemon = _wire_a_gaze_daemon(monkeypatch, cfg)
    assert daemon._perception is None
    seen = {}
    import yazses.gaze.factory as factory_mod

    def spy(config, perception=None):
        seen["perception"] = perception
        return types.SimpleNamespace(name="legacy", close=lambda: None)

    monkeypatch.setattr(factory_mod, "build_gaze", spy)
    assert daemon._build_gaze_targeter(cfg) is not None
    assert seen == {"perception": None}
    assert daemon._gaze_on_shared_source is False


def test_a_different_gaze_camera_keeps_its_own_backend_even_with_perception_on(monkeypatch) -> None:
    cfg = Config()
    cfg.gaze.enabled = True
    cfg.gaze.route_dictation = True
    cfg.gaze.camera_index = 1
    cfg.perception.enabled = True
    cfg.perception.camera_index = 0
    daemon = _wire_a_gaze_daemon(monkeypatch, cfg)
    daemon._perception = daemon._build_perception_source(cfg)
    seen = {}
    import yazses.gaze.factory as factory_mod

    def spy(config, perception=None):
        seen["perception"] = perception
        return types.SimpleNamespace(name="legacy", close=lambda: None)

    monkeypatch.setattr(factory_mod, "build_gaze", spy)
    assert daemon._build_gaze_targeter(cfg) is not None
    assert seen == {"perception": None}
    assert daemon._gaze_on_shared_source is False


# --------------------------------------------------------------------------- #
# Status: shared state is reported only for a consumer that really shares
# --------------------------------------------------------------------------- #


def _status_daemon(cfg, *, source, on_shared):
    return types.SimpleNamespace(
        _config=cfg,
        _gaze_targeter=object(),
        _extra_activations=[],
        _perception=source,
        _gaze_on_shared_source=on_shared,
    )


def test_status_reports_nothing_per_channel_before_the_first_sample() -> None:
    """A lazy source that nobody has opened is dormant, not 'no face in view'."""
    from yazses.core.daemon import Daemon

    clock = Clock()
    source, _ = _real_source(clock)
    cfg = Config()
    cfg.gaze.enabled = True
    payload = Daemon._handsfree_payload(_status_daemon(cfg, source=source, on_shared=True))
    assert payload is not None
    assert payload["perception_state"] == "running"        # a gaze consumer was built
    assert payload["perception_channels"] is None           # not () == "no face"
    assert payload["perception_age_ms"] is None
    assert "shared camera source dormant" in str(payload["perception_reason"])


def test_status_reports_channels_and_age_once_the_shared_source_is_running() -> None:
    from yazses.core.daemon import Daemon

    clock = Clock()
    source, _ = _real_source(clock)
    lease = source.consumer("gaze")
    lease.start()
    source.observe()
    clock.now += 0.25
    cfg = Config()
    cfg.gaze.enabled = True
    payload = Daemon._handsfree_payload(_status_daemon(cfg, source=source, on_shared=True))
    assert payload is not None
    assert payload["perception_channels"] == ["gaze"] or payload["perception_channels"] == ("gaze",)
    assert payload["perception_age_ms"] == pytest.approx(250.0)
    lease.stop()


def test_status_does_not_claim_shared_state_for_a_gaze_that_owns_its_camera() -> None:
    from yazses.core.daemon import Daemon

    clock = Clock()
    source, _ = _real_source(clock)
    cfg = Config()
    cfg.gaze.enabled = True
    payload = Daemon._handsfree_payload(_status_daemon(cfg, source=source, on_shared=False))
    assert payload is not None
    assert payload["perception_channels"] is None
    assert "opens its own capture" in str(payload["perception_reason"])
