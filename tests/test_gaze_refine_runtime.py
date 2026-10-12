"""Implicit refinement is assembled only when it can honestly run, and says why when not (#398).

`src/yazses/gaze/refine_runtime.py` is the one place the click observer, the shared camera,
the association policy, the refinement gate and the store are wired together. Its contract
is mostly about *not* starting: enabled-but-dormant is the symptomless failure this project
keeps paying for ("it says it is on, nothing happens, nothing says why"), so every
precondition has a test that names the reason it returns.

Hermetic: a fake observer, a fake perception source whose leases count, a fake targeter, a
tmp_path data directory, an injected spawn so no thread runs unless a test asks.
"""
from __future__ import annotations

import threading
import types

import numpy as np
import pytest

from yazses.config import Config, GazeRefineConfig
from yazses.gaze.calibrate import CalibrationMap
from yazses.gaze.clicks import ClickEvent, ClickObserverError
from yazses.gaze.refine_runtime import (
    RefinementRuntime,
    build_refinement_runtime,
    policies_from_config,
)
from yazses.gaze.store import (
    calibration_path,
    load_calibration_record,
    rollback_calibration,
    save_calibration,
)
from yazses.perception.signals import GazeSignal, PerceptionSample

TRUE = CalibrationMap(A=np.array([[900.0, 40.0, 960.0], [30.0, 700.0, 540.0]]))


def drifted() -> CalibrationMap:
    A = np.array(TRUE.A, copy=True)
    A[0, 2] += 120.0
    A[1, 2] -= 80.0
    return CalibrationMap(A=A)


class FakeObserver:
    def __init__(self, fail: Exception | None = None):
        self.callback = None
        self.starts = self.stops = 0
        self.fail = fail

    def start(self, on_click):
        self.starts += 1
        if self.fail is not None:
            raise self.fail
        self.callback = on_click

    def stop(self):
        self.stops += 1
        self.callback = None


class FakeLease:
    def __init__(self):
        self.starts = self.stops = 0
        self.sample = None

    def start(self):
        self.starts += 1

    def stop(self):
        self.stops += 1

    def latest(self):
        return self.sample


class FakePerception:
    def __init__(self):
        self.lease = FakeLease()
        self.names: list[str] = []

    def consumer(self, name):
        self.names.append(name)
        return self.lease


class FakeTargeter:
    def __init__(self, calibration):
        self.calibration = calibration
        self.swapped: list[CalibrationMap] = []

    def set_calibration(self, calibration):
        self.swapped.append(calibration)
        self.calibration = calibration


def section(**overrides) -> GazeRefineConfig:
    base = dict(enabled=True, min_train_samples=20, min_holdout_samples=8, evaluate_every=10_000)
    return GazeRefineConfig(**{**base, **overrides})


def build(tmp_path, **kwargs):
    observer = kwargs.pop("observer", FakeObserver())
    perception = kwargs.pop("perception", FakePerception())
    spawned: list = []
    args = dict(
        section=section(),
        targeter=FakeTargeter(drifted()),
        perception=perception,
        gaze_on_shared_source=True,
        observer_factory=lambda: observer,
        data_dir=tmp_path,
        calibration_verified=True,
        spawn=lambda body: spawned.append(body) or types.SimpleNamespace(join=lambda timeout=None: None),
    )
    args.update(kwargs)
    runtime, reason = build_refinement_runtime(args.pop("section"), **args)
    return runtime, reason, observer, perception, spawned


# --------------------------------------------------------------------------- #
# Dormancy: each precondition names itself
# --------------------------------------------------------------------------- #


def test_the_shipped_default_is_off_and_silent(tmp_path) -> None:
    runtime, reason, observer, perception, spawned = build(tmp_path, section=GazeRefineConfig())
    assert runtime is None and reason == ""
    assert (observer.starts, perception.lease.starts, spawned) == (0, 0, [])


@pytest.mark.parametrize(
    ("override", "needle"),
    [
        ({"targeter": None}, "no calibration to refine"),
        ({"perception": None}, "shared camera"),
        ({"gaze_on_shared_source": False}, "shared camera"),
        ({"observer_factory": None}, "no click observer"),
        ({"calibration_verified": False}, "could not be verified"),
    ],
)
def test_each_missing_precondition_returns_no_runtime_and_a_reason(tmp_path, override, needle) -> None:
    runtime, reason, observer, perception, spawned = build(tmp_path, **override)
    assert runtime is None
    assert needle in reason
    assert (observer.starts, spawned) == (0, [])
    if override.get("perception", perception) is not None:
        assert perception.lease.starts == 0, (
            "nothing may be opened or started until every precondition has passed"
        )


def test_a_nonsense_config_value_is_a_reason_not_a_daemon_that_will_not_start(tmp_path) -> None:
    runtime, reason, *_ = build(tmp_path, section=section(holdout_every=1))
    assert runtime is None and "unusable value" in reason


def test_an_observer_factory_that_raises_is_contained(tmp_path) -> None:
    def boom():
        raise RuntimeError("no display")

    runtime, reason, _, perception, _ = build(tmp_path, observer_factory=boom)
    assert runtime is None and "could not be built" in reason
    assert perception.lease.starts == 0


def test_an_observer_that_cannot_start_gives_the_camera_back_and_says_why(tmp_path) -> None:
    observer = FakeObserver(fail=ClickObserverError("input monitoring was not granted"))
    runtime, reason, _, perception, spawned = build(tmp_path, observer=observer)
    assert runtime is None
    assert "input monitoring was not granted" in reason
    assert perception.lease.starts == 1 and perception.lease.stops == 1
    assert spawned == []


# --------------------------------------------------------------------------- #
# Running
# --------------------------------------------------------------------------- #


def test_a_runnable_configuration_takes_the_lease_and_the_hook_and_spawns_one_loop(tmp_path) -> None:
    runtime, reason, observer, perception, spawned = build(tmp_path)
    assert isinstance(runtime, RefinementRuntime) and reason == ""
    assert perception.names == ["gaze-refine"], "the lease is named so status can show who holds it"
    assert (perception.lease.starts, observer.starts) == (1, 1)
    assert len(spawned) == 1


def test_stopping_releases_everything_and_is_idempotent(tmp_path) -> None:
    runtime, _, observer, perception, _ = build(tmp_path)
    assert runtime is not None
    runtime.stop()
    runtime.stop()
    assert runtime.stop_event.is_set()
    assert (observer.stops, perception.lease.stops) == (1, 1)


def test_a_loop_that_cannot_be_spawned_releases_the_hook_and_the_camera(tmp_path) -> None:
    def refuse(body):
        raise RuntimeError("no threads")

    runtime, reason, observer, perception, _ = build(tmp_path, spawn=refuse)
    assert runtime is None and "could not start" in reason
    assert (observer.stops, perception.lease.stops) == (1, 1)


def test_the_real_default_loop_runs_polls_and_is_gone_after_stop(tmp_path) -> None:
    runtime, _, _, perception, _ = build(tmp_path, spawn=None)
    assert runtime is not None and runtime.worker is not None
    runtime.stop()
    runtime.worker.join(timeout=5)  # type: ignore[attr-defined]
    assert not runtime.worker.is_alive()  # type: ignore[attr-defined]
    assert threading.active_count() >= 1


def test_the_policies_are_read_from_the_section_in_the_right_units() -> None:
    association, refinement = policies_from_config(
        GazeRefineConfig(click_latency_ms=150, lookback_ms=700, min_confidence=0.6,
                         holdout_every=5, min_improvement_px=2.5)
    )
    assert association.latency_s == pytest.approx(0.15)
    assert association.lookback_s == pytest.approx(0.7)
    assert association.min_confidence == pytest.approx(0.6)
    assert refinement.holdout_every == 5 and refinement.min_improvement_px == 2.5
    assert refinement.min_confidence == pytest.approx(0.6)


def test_the_shipped_defaults_are_a_valid_pair_of_policies() -> None:
    policies_from_config(Config().gaze_refine)


def test_the_section_ships_off(tmp_path) -> None:
    assert Config().gaze_refine.enabled is False


# --------------------------------------------------------------------------- #
# The whole thing: fake clicks in, a promoted file and a live swap out
# --------------------------------------------------------------------------- #


def test_clicks_through_the_runtime_promote_persist_swap_live_and_can_roll_back(tmp_path) -> None:
    save_calibration(drifted(), tmp_path)
    original = calibration_path(tmp_path).read_bytes()
    targeter = FakeTargeter(drifted())
    runtime, _, observer, perception, _ = build(tmp_path, targeter=targeter)
    assert runtime is not None
    rng = np.random.default_rng(3)
    t = 500.0
    for _ in range(80):
        yaw, pitch = float(rng.uniform(-0.4, 0.4)), float(rng.uniform(-0.3, 0.3))
        perception.lease.sample = PerceptionSample(t, gaze=GazeSignal(t, yaw, pitch, 0.9))
        runtime.service.poll()
        x, y = TRUE.predict(yaw, pitch)
        observer.callback(ClickEvent(t + 0.1, x, y))
        t += 1.0

    result = runtime.refiner.evaluate()

    assert result.outcome.value == "applied"
    assert len(targeter.swapped) == 1, "the running targeter must be switched exactly once"
    record = load_calibration_record(tmp_path)
    assert record is not None and np.allclose(record.calibration.A, targeter.swapped[0].A)
    assert record is not None and record.source == "implicit"
    rolled = rollback_calibration(tmp_path)
    assert rolled is not None
    assert calibration_path(tmp_path).read_bytes() == original
    runtime.stop()
