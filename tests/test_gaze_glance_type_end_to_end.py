"""Glance-Type gaze, old path against new path, through the real components (#396).

`tests/test_gaze_glance_type_unchanged.py` compares the *arithmetic* of the two paths and
the *targeter* over a scripted backend; `tests/test_gaze_shared_source.py` runs the targeter
over a numeric fake lease. Neither runs the same landmarks down both whole paths, so a bug
that only exists in the seams between them (the processor that wraps ``derive_gaze``, the
source that stamps and publishes, the adapter that ages and converts) would pass all three.

Here one fake FaceLandmarker feeds:

* the legacy path -- ``MediapipeGazeBackend`` reading a fake ``cv2`` camera; and
* the new path -- the real ``MediapipeFaceProcessor`` inside the real
  ``SharedPerceptionSource`` behind the real ``SharedGazeBackend``;

each into its own real ``GazeTargeter``, and the routing decisions must be identical for
every pair of eye offsets in a grid that crosses the confidence threshold, off-screen
landmarks, and the no-face case. The camera and model are fakes; nothing opens a device.

One difference is deliberate, documented in ``gaze/shared.py`` and pinned separately below:
a face that has just left the frame keeps routing for up to ``MAX_SAMPLE_AGE_S`` on the new
path because the source does not clear a sample when a frame has no face. It is a bounded
grace period, not a replayed answer.
"""
from __future__ import annotations

import itertools

import numpy as np
import pytest

from tests.test_gaze_glance_type_unchanged import _Desktop
from tests.test_gaze_mediapipe import _FakeResult, _landmarks, mp_backend
from yazses.gaze.calibrate import CalibrationMap
from yazses.gaze.shared import MAX_SAMPLE_AGE_S, SharedGazeBackend
from yazses.gaze.targeter import GazeTargeter
from yazses.perception import SharedPerceptionSource, SourceState

__all__ = ["mp_backend"]  # re-exported so pytest finds the fixture in this module

# Offsets 0.0 -> screen x 500 (the pane boundary); +/-0.2 -> 700 / 300; 2.0 -> off screen.
_SCALE = CalibrationMap(A=np.array([[1000.0, 0.0, 500.0], [0.0, 1000.0, 500.0]]))
_PANES = [("editor", 0, 0, 500, 1000), ("browser", 500, 0, 500, 1000)]
_OFFSETS = [(-0.2, 0.0), (0.2, 0.0), (0.05, 0.1), (2.0, 0.0)]


class _Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class _Camera:
    """The shared source's capture half: opens once, yields a frame token, counts."""

    def __init__(self) -> None:
        self.opens = 0
        self.closes = 0

    def open(self) -> None:
        self.opens += 1

    def read(self):
        return object()

    def close(self) -> None:
        self.closes += 1


class _NoThread:
    def join(self, timeout=None) -> None:
        pass

    def is_alive(self) -> bool:
        return False


class _World:
    """Both paths over one landmarker, advanced one 'frame' at a time."""

    def __init__(self, mp_backend, confidence_min: float) -> None:
        from yazses.perception.mediapipe_backend import MediapipeFaceProcessor

        self.legacy_backend, _, self.landmarker = mp_backend
        self.clock = _Clock()
        self.camera = _Camera()
        self.source = SharedPerceptionSource(
            lambda: self.camera,
            lambda: MediapipeFaceProcessor(model_path="/models/face_landmarker.task"),
            clock=self.clock,
            spawn=lambda body, name: _NoThread(),
        )
        self.lease = self.source.consumer("gaze")
        self.shared_backend = SharedGazeBackend(
            self.lease, clock=self.clock, sleep=self.clock.sleep
        )
        # A real source runs its own loop from the moment a lease opens it; this one is pumped
        # by hand, so open it now (the backend's own start is then a no-op on the same lease).
        self.lease.start()
        self.legacy_desktop = _Desktop("editor", _PANES)
        self.shared_desktop = _Desktop("editor", _PANES)
        self.legacy = GazeTargeter(
            self.legacy_backend, _SCALE, self.legacy_desktop, confidence_min
        )
        self.shared = GazeTargeter(
            self.shared_backend, _SCALE, self.shared_desktop, confidence_min
        )

    def frame(self, landmarks, *, advance: float = 1.0 / 15.0) -> None:
        """One camera frame: the landmarker answers, the source observes, time passes."""
        self.landmarker.result = _FakeResult(landmarks)
        self.clock.now += advance
        self.source.observe()

    def decisions(self):
        """Both paths' decisions for the frame just observed."""
        old = self.legacy.retarget()
        new = self.shared.retarget()
        return (old.used_gaze, old.target), (new.used_gaze, new.target)


@pytest.mark.parametrize("confidence_min", [0.0, 0.5, 0.9], ids=["floor0", "default", "strict"])
def test_every_eye_pair_routes_identically_down_both_whole_paths(mp_backend, confidence_min):
    world = _World(mp_backend, confidence_min)
    # The first shared call opens the lease and waits for a first observation; the source is
    # pumped by hand, so give it one frame before anything is compared.
    world.frame(_landmarks((0.2, 0.0), (0.2, 0.0)))
    world.shared_backend.estimate_sample()

    compared = 0
    for left, right in itertools.product(_OFFSETS, repeat=2):
        world.frame(_landmarks(left, right))
        old, new = world.decisions()
        assert old == new, f"paths disagree for left={left} right={right}: {old} vs {new}"
        compared += 1
    assert compared == len(_OFFSETS) ** 2
    # The grid must actually exercise both outcomes, or the comparison proves nothing.
    outcomes = set()
    for left, right in itertools.product(_OFFSETS, repeat=2):
        world.frame(_landmarks(left, right))
        outcomes.add(world.decisions()[0])
    assert (True, "browser") in outcomes and (False, "editor") in outcomes


def test_no_face_for_longer_than_the_age_bound_routes_to_the_focused_window_on_both(mp_backend):
    world = _World(mp_backend, 0.5)
    world.frame(_landmarks((0.2, 0.0), (0.2, 0.0)))
    assert world.decisions() == ((True, "browser"), (True, "browser"))

    world.frame(None, advance=MAX_SAMPLE_AGE_S + 0.1)
    assert world.decisions() == ((False, "editor"), (False, "editor"))


def test_a_face_that_just_left_is_routed_on_for_the_age_bound_and_not_a_moment_longer(
    mp_backend,
):
    """The one deliberate difference: bounded, not replayed. Legacy answers 'no gaze' at once."""
    world = _World(mp_backend, 0.5)
    world.frame(_landmarks((0.2, 0.0), (0.2, 0.0)))
    world.decisions()

    world.frame(None, advance=0.2)                      # inside the bound
    old, new = world.decisions()
    assert old == (False, "editor")
    assert new == (True, "browser"), "the documented grace period no longer applies"

    world.frame(None, advance=MAX_SAMPLE_AGE_S)         # now past it
    old, new = world.decisions()
    assert old == new == (False, "editor")


def test_a_low_confidence_face_never_routes_on_either_path_whatever_its_position(mp_backend):
    world = _World(mp_backend, 0.5)
    world.frame(_landmarks((0.2, 0.0), (0.2, 0.0)))
    world.shared_backend.estimate_sample()
    world.frame(_landmarks((0.4, 0.0), (-0.4, 0.0)))    # eyes disagree by 0.8 > scale
    old, new = world.decisions()
    assert old == new == (False, "editor")
    assert world.legacy_desktop.activated == world.shared_desktop.activated == []


def test_burst_snapshot_for_deixis_is_the_same_decision_on_both(mp_backend):
    world = _World(mp_backend, 0.5)
    world.frame(_landmarks((0.2, 0.0), (0.2, 0.0)))
    world.decisions()
    assert world.legacy.last_decision is not None
    assert world.shared.last_decision is not None
    assert (world.legacy.last_decision.used_gaze, world.legacy.last_decision.target) == (
        world.shared.last_decision.used_gaze,
        world.shared.last_decision.target,
    )


def test_gaze_and_two_other_camera_consumers_open_one_camera_in_any_release_order(mp_backend):
    world = _World(mp_backend, 0.5)
    face = world.source.consumer("facegesture")
    head = world.source.consumer("headpointer")
    world.shared_backend.estimate_sample()              # gaze leases the camera
    face.start()
    head.start()
    assert world.camera.opens == 1
    assert world.source.status().consumers == ("facegesture", "gaze", "headpointer")

    world.frame(_landmarks((0.2, 0.0), (0.2, 0.0)))
    face.stop()
    head.stop()
    assert world.camera.closes == 0, "gaze still holds the camera"
    assert world.shared_backend.estimate_sample() is not None

    world.shared_backend.close()
    assert world.camera.closes == 1
    assert world.source.status().state is SourceState.DORMANT
    assert world.source.latest() is None, "a face seen before the camera closed outlived it"
