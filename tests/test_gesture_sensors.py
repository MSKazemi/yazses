"""Shared-camera samples to chord tokens (pure) -- EYE-GESTURE-001.

Numeric fakes only: a ``PerceptionSample`` is a timestamp and some numbers. What is pinned:

* the face tokens come from the face switch's own detector (its thresholds, debounce and
  confidence floor), not a second copy;
* **a sample is acted on once** -- the runner polls faster than the camera delivers, and a
  frame-counting switch must not count one frame twice;
* **missing, stale and NaN signals yield no token**, release what was held at once, and drop
  the pointer freeze;
* an expression that has *begun* freezes the pointer before it is a token;
* with no chord bound nothing is watched at all.
"""
from __future__ import annotations

import math
from types import SimpleNamespace

from yazses.gesture.engine import ChordEngine
from yazses.gesture.headmotion import HeadMotionSettings
from yazses.gesture.sensors import FaceSwitchSettings, SensorSettings, SensorTokens
from yazses.perception.signals import FaceSignal, HeadPoseSignal, PerceptionSample

FPS = 15.0
DT = 1.0 / FPS


class Rig:
    """An engine with fake handlers, driven by hand-built samples at a fixed frame rate."""

    def __init__(self, bindings, *, face=None, head=None, freshness_s=0.5, window_s=0.4):
        self.calls: list[str] = []
        self.freeze: list[bool] = []
        handlers = {a: (lambda a=a: self.calls.append(a)) for a in set(bindings.values())}
        self.engine = ChordEngine(
            bindings, handlers, window_s=window_s, refractory_s=1.0, freeze_tail_s=0.3,
            on_freeze=self.freeze.append,
        )
        self.sensors = SensorTokens(
            self.engine,
            SensorSettings(
                freshness_s=freshness_s,
                face=face or FaceSwitchSettings(),
                head=head or HeadMotionSettings(),
            ),
        )
        self.t = 100.0

    def frame(self, *, jaw=None, pitch=0.0, yaw=0.0, roll=0.0, conf=1.0, head=True, face=True):
        """One camera frame, delivered and polled once."""
        self.t += DT
        return self.poll(self.sample(jaw=jaw, pitch=pitch, yaw=yaw, roll=roll, conf=conf,
                                     head=head, face=face))

    def sample(self, *, jaw=None, pitch=0.0, yaw=0.0, roll=0.0, conf=1.0, head=True, face=True,
               t=None):
        t = self.t if t is None else t
        return PerceptionSample(
            t,
            head_pose=HeadPoseSignal(t, yaw, pitch, roll, conf) if head else None,
            face=FaceSignal(t, conf, {"jawOpen": jaw if jaw is not None else 0.0})
            if face else None,
        )

    def poll(self, sample, now=None):
        self.sensors.update(sample, self.t if now is None else now)

    def nod(self):
        """A double nod, one frame at a time."""
        n = int(1.0 * FPS)
        for i in range(n + 1):
            self.frame(pitch=0.2 * math.sin(2 * math.pi * 2 * i / n))


# --------------------------------------------------------------------------- #
# Dormancy
# --------------------------------------------------------------------------- #
def test_with_no_chord_nothing_is_watched_and_a_tick_does_nothing():
    rig = Rig({})
    assert rig.sensors.watching == ()
    rig.frame(jaw=0.9)
    rig.nod()
    assert rig.calls == [] and rig.freeze == []


def test_only_the_tokens_a_chord_uses_are_watched():
    assert Rig({"jaw_open+nod": "recenter"}).sensors.watching == ("jaw_open", "nod")
    assert Rig({"nod": "recenter"}).sensors.watching == ("nod",)
    assert Rig({"smile": "recenter"}).sensors.watching == ("smile",)


# --------------------------------------------------------------------------- #
# A face token alone
# --------------------------------------------------------------------------- #
def test_a_held_jaw_is_a_token_after_the_face_switchs_own_debounce():
    rig = Rig({"jaw_open": "recenter"})
    rig.frame(jaw=0.9)
    rig.frame(jaw=0.9)
    assert rig.calls == []                # min_hold_frames is 3 for the face switch
    rig.frame(jaw=0.9)
    assert rig.calls == ["recenter"]


def test_a_flicker_shorter_than_the_debounce_is_nothing():
    rig = Rig({"jaw_open": "recenter"})
    for jaw in (0.9, 0.9, 0.0, 0.9, 0.9, 0.0, 0.9, 0.9, 0.0):
        rig.frame(jaw=jaw)
    assert rig.calls == []


def test_the_face_switch_thresholds_are_the_ones_given():
    rig = Rig({"jaw_open": "recenter"}, face=FaceSwitchSettings(hold_threshold=0.8,
                                                                release_threshold=0.5))
    for _ in range(6):
        rig.frame(jaw=0.7)                # would hold at the default 0.5, not at 0.8
    assert rig.calls == []
    for _ in range(3):
        rig.frame(jaw=0.9)
    assert rig.calls == ["recenter"]


def test_the_confidence_floor_is_the_face_switchs_own():
    rig = Rig({"jaw_open": "recenter"}, face=FaceSwitchSettings(confidence_floor=0.8))
    for _ in range(6):
        rig.frame(jaw=0.9, conf=0.5)
    assert rig.calls == []


# --------------------------------------------------------------------------- #
# A sample is acted on once
# --------------------------------------------------------------------------- #
def test_one_observation_polled_many_times_counts_as_one_frame():
    rig = Rig({"jaw_open": "recenter"})
    rig.t += DT
    sample = rig.sample(jaw=0.9)
    for _ in range(10):                   # a 30 Hz poll over a slower camera
        rig.poll(sample)
    assert rig.calls == []                # one frame, not ten: the debounce is not met


def test_a_duplicate_head_sample_does_not_complete_a_nod():
    rig = Rig({"nod": "recenter"})
    rig.nod()
    assert rig.calls == ["recenter"]
    rig.calls.clear()
    last = rig.sample(pitch=0.0, t=rig.t)
    for _ in range(5):
        rig.poll(last)
    assert rig.calls == []


# --------------------------------------------------------------------------- #
# Head and face together
# --------------------------------------------------------------------------- #
def test_jaw_open_and_a_nod_together_fire_the_chord_once():
    rig = Rig({"jaw_open+nod": "recenter"})
    for _ in range(4):
        rig.frame(jaw=0.9)                # jaw held...
    n = int(1.0 * FPS)
    for i in range(n + 1):                # ...while nodding
        rig.frame(jaw=0.9, pitch=0.2 * math.sin(2 * math.pi * 2 * i / n))
    rig.engine.tick(rig.t + 1.0)
    assert rig.calls == ["recenter"]


def test_a_nod_without_the_jaw_is_not_that_chord():
    rig = Rig({"jaw_open+nod": "recenter"})
    rig.nod()
    rig.engine.tick(rig.t + 1.0)
    assert rig.calls == []


def test_a_held_tilt_is_a_token():
    rig = Rig({"tilt": "recenter"})
    for _ in range(int(1.0 * FPS)):
        rig.frame(roll=0.5)
    assert rig.calls == ["recenter"]


# --------------------------------------------------------------------------- #
# Doubt is silence
# --------------------------------------------------------------------------- #
def test_no_sample_at_all_yields_no_token():
    rig = Rig({"jaw_open": "recenter", "nod": "pause_pointer"})
    for _ in range(20):
        rig.t += DT
        rig.poll(None)
    assert rig.calls == []


def test_a_stale_sample_is_no_signal_not_a_held_gesture():
    rig = Rig({"jaw_open": "recenter"}, freshness_s=0.5)
    rig.t += DT
    stale = rig.sample(jaw=0.9, t=rig.t - 5.0)       # 5 s old
    for _ in range(10):
        rig.poll(stale)
    assert rig.calls == []


def test_losing_the_camera_releases_a_held_face_token_and_drops_the_freeze():
    rig = Rig({"jaw_open+nod": "recenter"})
    for _ in range(4):
        rig.frame(jaw=0.9)
    assert rig.freeze[-1] is True
    rig.t += DT
    rig.poll(None)
    assert rig.freeze[-1] is False        # at once, not after a debounce
    assert not rig.engine.freeze_pointer


def test_the_last_value_is_not_replayed_when_the_camera_returns():
    rig = Rig({"jaw_open": "recenter"})
    for _ in range(3):
        rig.frame(jaw=0.9)
    assert rig.calls == ["recenter"]
    rig.calls.clear()
    rig.t += DT
    rig.poll(None)                        # the camera dies mid-hold
    rig.t += 2.0
    rig.frame(jaw=0.0)                    # and returns with a relaxed face
    rig.engine.tick(rig.t + 3.0)
    assert rig.calls == []


def test_a_nan_pose_is_no_token_and_does_not_raise():
    rig = Rig({"nod": "recenter"})
    bad = SimpleNamespace(
        timestamp_s=rig.t, face=None,
        head_pose=SimpleNamespace(timestamp_s=rig.t, yaw=float("nan"), pitch=0.0, roll=0.0,
                                  confidence=1.0),
    )
    rig.poll(bad)                         # type: ignore[arg-type]
    assert rig.calls == []


def test_a_nan_clock_resets_and_does_not_raise():
    rig = Rig({"nod": "recenter"})
    rig.sensors.update(rig.sample(), float("nan"))
    assert rig.calls == []


def test_the_head_channel_failing_does_not_take_the_face_channel_with_it():
    rig = Rig({"jaw_open": "recenter"})
    for _ in range(3):
        rig.frame(jaw=0.9, head=False)    # a missing facial transform: no head pose
    assert rig.calls == ["recenter"]


# --------------------------------------------------------------------------- #
# The pointer onset
# --------------------------------------------------------------------------- #
def test_an_expression_that_has_begun_freezes_the_pointer_before_it_is_a_token():
    rig = Rig({"jaw_open+nod": "recenter"})
    rig.frame(jaw=0.4)                    # between release (0.35) and hold (0.5)
    assert rig.engine.freeze_pointer and rig.calls == []
    rig.frame(jaw=0.0)
    rig.engine.tick(rig.t + 1.0)
    assert not rig.engine.freeze_pointer


def test_a_relaxed_face_never_freezes_the_pointer():
    rig = Rig({"jaw_open+nod": "recenter"})
    for _ in range(30):
        rig.frame(jaw=0.05)
    assert rig.freeze == []


def test_reset_releases_everything():
    rig = Rig({"jaw_open+nod": "recenter"})
    for _ in range(4):
        rig.frame(jaw=0.9)
    rig.sensors.reset(rig.t)
    assert not rig.engine.freeze_pointer
    rig.sensors.reset(rig.t)              # idempotent


def test_the_freeze_names_the_camera_frame_that_showed_the_expression():
    rig = Rig({"jaw_open+nod": "recenter"})
    rig.frame(jaw=0.05)
    assert rig.engine.freeze_started_s is None
    rig.frame(jaw=0.9)                    # first frame at or above the release threshold
    assert rig.engine.freeze_pointer
    assert rig.engine.freeze_started_s == rig.t
