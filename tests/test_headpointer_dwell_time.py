"""Dwell-click is timed in real seconds, and ``freshness_ms`` is bounded like ``stale_after_ms``.

**Dwell.** The hold used to be counted in samples (``dwell_hold_frames = 20``), so it lasted
0.67 s on a 30 fps webcam and 1.33 s on a 15 fps one -- the camera's rate leaked into a
timing the user has to learn. It is now ``dwell_ms`` on the samples' own timestamps. These
tests pin the properties that matter, none of them a recommendation about what a human can
hold still for (the numbers are synthetic; ``design/eye-control/GOVERNANCE.md``):

* the same wait at 15, 30 and 60 fps;
* stillness has to be *observed* -- a stall (a gap longer than ``max_dt_s``) restarts the
  dwell rather than completing it, and a clock fault does the same;
* everything that already dropped a half-built dwell (pause, clutch, recenter, signal loss)
  still does, and dwell stays off unless asked for;
* an old ``dwell_hold_frames`` keeps meaning roughly what it did, at a nominal 30 fps.

**Freshness.** ``[headpointer] freshness_ms = 0`` was accepted by the loader and *applied
literally*: every real sample has a positive age, so every sample was stale, the state was
LOST for ever and the pointer never moved -- with ``Config`` reporting a perfectly valid 0.
A value past a minute meant "never stale" and ``10**400`` raised ``OverflowError`` while the
settings were built. Same family as ``stale_after_ms`` (commit 6983c89d), and fixed the same
way: bounds in field metadata, enforced by the loader, plus an effective-value function the
controller applies, so the two layers cannot drift into two defaults.
"""
from __future__ import annotations

import dataclasses
import math

import pytest

from tests.pointer_fake import FakePointerSink, PointerActionKind
from yazses.config import Config, HeadpointerConfig, load_config_checked
from yazses.configcheck import ConfigProblem
from yazses.headpointer.controller import (
    DEFAULT_DWELL_S,
    DEFAULT_FRESHNESS_S,
    MAX_DWELL_S,
    MAX_FRESHNESS_S,
    MIN_DWELL_S,
    HeadPointerController,
    HeadPointerSettings,
    State,
    effective_dwell_s,
    effective_freshness_s,
)
from yazses.headpointer.pointer import DEFAULT_MAX_DT_S, DwellClicker, PointerCalib
from yazses.headpointer.runtime import settings_from_config
from yazses.perception.signals import HeadPoseSignal

# A gain so large that one frame of a 0.5 rad turn crosses the dwell radius at ANY frame rate
# (>= 250 units even at 60 fps), so the dwell is armed and anchored on that one frame and the
# test measures the wait from a known instant, not from wherever a slow drift happened to stop.
JUMP = PointerCalib(
    x_gain=30000.0, y_gain=0.0, deadzone=0.02,
    max_speed_x=1e9, max_speed_y=1e9, max_speed_overall=1e9,
)


class Rig:
    """A controller on a hand-moved clock; the sink is the recording fake, never a real mouse."""

    def __init__(self, fps: float = 30.0, **settings) -> None:
        settings.setdefault("calib", JUMP)
        settings.setdefault("dwell_enabled", True)
        settings.setdefault("dwell_hold_s", 0.7)
        self.fps = fps
        self.t = 1000.0
        self.sink = FakePointerSink()
        self.ctl = HeadPointerController(self.sink, HeadPointerSettings(**settings))

    def feed(self, yaw: float = 0.0, *, dt: float | None = None):
        self.t += (1.0 / self.fps) if dt is None else dt
        return self.ctl.update(HeadPoseSignal(self.t, yaw, 0.0, 0.0, 1.0), self.t)

    @property
    def clicks(self) -> int:
        return sum(1 for a in self.sink.actions if a.kind is PointerActionKind.BUTTON_PRESS)

    @property
    def raw_progress(self) -> float:
        """The clicker's own progress, which ``status()`` hides while the detector is disarmed.

        Disarming alone also keeps a stale dwell from clicking (it needs fresh travel), so a
        status check cannot tell whether the clicker was really emptied; this can.
        """
        return self.ctl._clicker.progress  # noqa: SLF001

    def arm_dwell(self) -> float:
        """Centre, then one big turn that travels past the radius. Returns that frame's time."""
        self.feed(0.0)  # becomes the neutral pose
        self.feed(0.0)  # the settling frame already happened; nothing moves
        self.feed(0.5)  # the jump: dwell armed and anchored on this very sample
        assert self.ctl.status().dwell_armed
        return self.t

    def still_until_click(self, limit_s: float = 5.0) -> float | None:
        """Hold the head at neutral; the time of the click, or None if none came in ``limit_s``."""
        start = self.t
        while self.t - start < limit_s:
            before = self.clicks
            self.feed(0.0)
            if self.clicks > before:
                return self.t
        return None


# --------------------------------------------------------------------------- #
# The pure clicker
# --------------------------------------------------------------------------- #


def _click_time(fps: float, hold_s: float) -> float:
    clicker = DwellClicker(radius=5.0, hold_s=hold_s)
    t = 50.0
    start = t
    clicker.update(10.0, 10.0, t)
    while t - start < 10.0:
        t += 1.0 / fps
        if clicker.update(10.0, 10.0, t):
            return t - start
    raise AssertionError("never clicked")


@pytest.mark.parametrize("fps", [10, 15, 26, 30, 60, 120])
def test_the_hold_lasts_the_same_time_at_every_frame_rate(fps):
    waited = _click_time(fps, 0.7)
    # The click lands on the first sample at or after the hold: late by less than one frame,
    # never early. (1e-9: the sum of many float gaps.)
    assert 0.7 - 1e-9 <= waited < 0.7 + 1.0 / fps + 1e-9, (fps, waited)


def test_a_frame_counted_clicker_would_have_failed_this():
    """The control: 15 fps must not take twice as long as 30 fps."""
    assert abs(_click_time(15, 0.7) - _click_time(30, 0.7)) < 1.0 / 15 + 1e-9


def test_a_stall_cannot_complete_a_dwell_by_itself():
    clicker = DwellClicker(radius=5.0, hold_s=0.7)
    clicker.update(10.0, 10.0, 0.0)
    clicker.update(10.0, 10.0, 0.1)
    # The camera stalls for two seconds and comes back with the pointer where it was. Nobody
    # watched it for those two seconds: that is not 2 s of stillness.
    assert clicker.update(10.0, 10.0, 2.1) is False
    assert clicker.progress == 0.0  # restarted, not credited
    assert DEFAULT_MAX_DT_S < 0.7  # so a clamp alone could never finish it either


def test_a_gap_just_over_the_limit_restarts_and_just_under_it_counts():
    clicker = DwellClicker(radius=5.0, hold_s=0.5, max_dt_s=0.25)
    clicker.update(0.0, 0.0, 0.0)
    clicker.update(0.0, 0.0, 0.25)  # exactly the limit: counted
    assert clicker.progress == pytest.approx(0.5)
    clicker.update(0.0, 0.0, 0.51)  # 0.26 s: a stall
    assert clicker.progress == 0.0


@pytest.mark.parametrize("bad", [0.0, -0.1, math.nan, math.inf, -math.inf])
def test_a_clock_fault_restarts_the_dwell_and_never_clicks(bad):
    clicker = DwellClicker(radius=5.0, hold_s=0.3)
    clicker.update(0.0, 0.0, 10.0)
    clicker.update(0.0, 0.0, 10.1)
    ts = 10.1 + bad if bad in (0.0, -0.1) else bad
    assert clicker.update(0.0, 0.0, ts) is False
    assert clicker.progress == 0.0


def test_moving_outside_the_radius_restarts_the_hold():
    clicker = DwellClicker(radius=5.0, hold_s=0.3)
    clicker.update(0.0, 0.0, 0.0)
    clicker.update(0.0, 0.0, 0.2)
    assert clicker.update(50.0, 0.0, 0.3) is False  # moved: new anchor, new clock
    assert clicker.update(50.0, 0.0, 0.5) is False  # only 0.2 s at the new spot
    assert clicker.update(50.0, 0.0, 0.6) is True


def test_progress_rises_with_time_not_with_samples():
    fast, slow = DwellClicker(5.0, 1.0), DwellClicker(5.0, 1.0)
    for t in (0.0, 0.05, 0.10, 0.15, 0.20):
        fast.update(0.0, 0.0, t)
    for t in (0.0, 0.2):
        slow.update(0.0, 0.0, t)
    assert fast.progress == pytest.approx(slow.progress) == pytest.approx(0.2)


# --------------------------------------------------------------------------- #
# The controller
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("fps", [15, 30, 60])
def test_the_controller_clicks_after_the_same_wait_at_every_frame_rate(fps):
    rig = Rig(fps)
    anchor = rig.arm_dwell()
    clicked_at = rig.still_until_click()
    assert clicked_at is not None
    waited = clicked_at - anchor
    assert 0.7 - 1e-9 <= waited < 0.7 + 1.0 / fps + 1e-9, (fps, waited)
    assert rig.clicks == 1


def test_dwell_is_off_unless_asked_for():
    assert HeadPointerSettings().dwell_enabled is False
    assert Config().headpointer.dwell_enabled is False
    rig = Rig(dwell_enabled=False)
    rig.feed(0.0)
    rig.feed(0.0)
    rig.feed(0.5)
    assert rig.still_until_click(3.0) is None
    assert rig.clicks == 0


def test_a_stall_mid_dwell_does_not_click_even_though_the_pointer_is_back_where_it_was():
    rig = Rig(30)
    rig.arm_dwell()
    for _ in range(10):  # 0.33 s of stillness, then...
        rig.feed(0.0)
    # ...a 0.4 s camera hiccup: still inside the 0.5 s freshness window, so the sample is
    # *valid*, but longer than max_dt_s. The dwell must not be credited with the gap.
    step = rig.feed(0.0, dt=0.4)
    assert step.state is State.TRACKING
    assert not step.clicked and rig.clicks == 0
    assert rig.ctl.status().dwell_progress == 0.0
    # And it then needs a full hold again, not the remainder.
    start = rig.t
    clicked_at = rig.still_until_click()
    assert clicked_at is not None and clicked_at - start >= 0.7 - 1e-9


def test_a_stall_longer_than_the_hold_is_not_a_click_either():
    rig = Rig(30, dwell_hold_s=0.5)
    rig.arm_dwell()
    rig.feed(0.0)
    # 0.45 s late: valid (< freshness), longer than max_dt_s, and longer than the whole hold.
    rig.feed(0.0, dt=0.45)
    assert rig.clicks == 0


def test_pause_drops_a_half_built_dwell_and_it_restarts_from_nothing():
    rig = Rig(30)
    rig.arm_dwell()
    for _ in range(15):  # 0.5 s of a 0.7 s hold
        rig.feed(0.0)
    assert rig.ctl.status().dwell_progress > 0.5 and rig.raw_progress > 0.5
    rig.ctl.pause()
    assert rig.ctl.status().dwell_progress == 0.0
    assert rig.raw_progress == 0.0
    for _ in range(30):
        rig.feed(0.0)
    rig.ctl.resume()
    for _ in range(60):  # resting after a resume never clicks: it must travel to re-arm
        rig.feed(0.0)
    assert rig.clicks == 0


def test_a_held_clutch_drops_the_dwell():
    rig = Rig(30)
    rig.arm_dwell()
    for _ in range(15):
        rig.feed(0.0)
    rig.ctl.set_clutch("test", True)
    assert rig.ctl.status().dwell_progress == 0.0
    assert rig.raw_progress == 0.0
    for _ in range(60):
        rig.feed(0.0)
    rig.ctl.set_clutch("test", False)
    for _ in range(60):
        rig.feed(0.0)
    assert rig.clicks == 0


def test_recenter_drops_the_dwell():
    rig = Rig(30)
    rig.arm_dwell()
    for _ in range(15):
        rig.feed(0.0)
    rig.ctl.recenter()
    assert rig.ctl.status().dwell_progress == 0.0
    assert rig.raw_progress == 0.0
    for _ in range(60):
        rig.feed(0.0)
    assert rig.clicks == 0


def test_losing_the_signal_drops_the_dwell():
    rig = Rig(30)
    rig.arm_dwell()
    for _ in range(15):
        rig.feed(0.0)
    rig.t += 1.0
    assert rig.ctl.update(None, rig.t).state is State.LOST
    assert rig.ctl.status().dwell_progress == 0.0
    assert rig.raw_progress == 0.0
    for _ in range(90):
        rig.feed(0.0)
    assert rig.clicks == 0


def test_sitting_still_after_start_up_never_clicks_however_long_it_lasts():
    rig = Rig(30)
    for _ in range(300):  # 10 s of perfect stillness
        rig.feed(0.0)
    assert rig.clicks == 0


# --------------------------------------------------------------------------- #
# Legacy ``dwell_hold_frames`` and the effective value
# --------------------------------------------------------------------------- #


def test_an_old_hold_in_frames_is_read_at_a_nominal_30_fps():
    assert effective_dwell_s(0.7, 20) == pytest.approx(20 / 30)
    assert effective_dwell_s(0.7, 0) == 0.7  # unset: dwell_hold_s rules


def test_a_legacy_value_is_no_longer_stretched_by_a_slow_camera():
    """20 frames used to be 1.33 s at 15 fps. Now it is 0.67 s on any camera."""
    for fps in (15, 30, 60):
        rig = Rig(fps, dwell_hold_s=0.7, dwell_hold_frames=20)
        anchor = rig.arm_dwell()
        waited = rig.still_until_click() - anchor
        assert 20 / 30 - 1e-9 <= waited < 20 / 30 + 1.0 / fps + 1e-9, (fps, waited)


@pytest.mark.parametrize(
    "value", [0.0, -1.0, math.nan, math.inf, 0.049, 10.001, 10**400, "0.7", None, True]
)
def test_a_nonsense_dwell_is_repaired_to_the_default(value):
    assert effective_dwell_s(value) == DEFAULT_DWELL_S


def test_the_dwell_bounds_are_inclusive_and_pass_through():
    assert effective_dwell_s(MIN_DWELL_S) == MIN_DWELL_S
    assert effective_dwell_s(MAX_DWELL_S) == MAX_DWELL_S
    assert effective_dwell_s(1.5) == 1.5


def test_a_nonsense_legacy_value_is_repaired_not_obeyed():
    assert effective_dwell_s(0.7, 10**400) == DEFAULT_DWELL_S
    assert effective_dwell_s(0.7, 1) == DEFAULT_DWELL_S  # 33 ms is under the floor
    assert effective_dwell_s(0.7, True) == 0.7  # a bool is not a frame count


def test_the_controller_applies_the_effective_dwell():
    ctl = HeadPointerController(FakePointerSink(), HeadPointerSettings(dwell_hold_s=0.0))
    assert ctl._hold_s == DEFAULT_DWELL_S  # noqa: SLF001 - the one number under test


# --------------------------------------------------------------------------- #
# ``dwell_ms`` in the config
# --------------------------------------------------------------------------- #


def _load(tmp_path, key: str, literal: str):
    path = tmp_path / "config.toml"
    path.write_text(f"[headpointer]\nenabled = true\n{key} = {literal}\n", encoding="utf-8")
    return load_config_checked(path)


def test_the_shipped_dwell_is_the_controllers_default_and_inside_its_bounds():
    meta = {f.name: f for f in dataclasses.fields(HeadpointerConfig)}["dwell_ms"].metadata
    assert meta["min"] <= HeadpointerConfig().dwell_ms <= meta["max"]
    assert HeadpointerConfig().dwell_ms / 1000.0 == DEFAULT_DWELL_S
    assert meta["min"] / 1000.0 == MIN_DWELL_S and meta["max"] / 1000.0 == MAX_DWELL_S


@pytest.mark.parametrize("literal", ["0", "-5", "49", "10001", str(10**400), '"abc"', "true"])
def test_a_hostile_dwell_ms_is_repaired_to_the_default_and_reported(tmp_path, literal):
    loaded = _load(tmp_path, "dwell_ms", literal)
    reported = loaded.config.headpointer.dwell_ms
    assert reported == HeadpointerConfig().dwell_ms, (literal, reported)
    assert settings_from_config(loaded.config.headpointer).dwell_hold_s == DEFAULT_DWELL_S
    assert any(isinstance(p, ConfigProblem) and p.key == "dwell_ms" for p in loaded.problems)


@pytest.mark.parametrize("literal", ["50", "300", "700", "2500", "10000"])
def test_a_sensible_dwell_ms_passes_through_and_is_what_runs(tmp_path, literal):
    loaded = _load(tmp_path, "dwell_ms", literal)
    assert loaded.config.headpointer.dwell_ms == int(literal)
    assert settings_from_config(loaded.config.headpointer).dwell_hold_s == int(literal) / 1000.0
    assert not [p for p in loaded.problems if p.key == "dwell_ms"]


def test_an_old_config_with_dwell_hold_frames_still_loads_and_means_frames_at_30_fps(tmp_path):
    loaded = _load(tmp_path, "dwell_hold_frames", "20")
    assert not [p for p in loaded.problems if p.key == "dwell_hold_frames"]
    settings = settings_from_config(loaded.config.headpointer)
    assert effective_dwell_s(settings.dwell_hold_s, settings.dwell_hold_frames) == pytest.approx(20 / 30)


def test_a_config_that_never_mentions_the_legacy_key_is_not_in_legacy_mode():
    assert Config().headpointer.dwell_hold_frames == 0


# --------------------------------------------------------------------------- #
# freshness_ms: reported is applied
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "literal",
    ["0", "0.0", '"0"', "-1", "nan", "inf", "1e999", "60001", "99999999999999999999", str(10**400),
     '"abc"', "true"],
)
def test_a_hostile_freshness_is_repaired_to_the_default_and_reported_as_it(tmp_path, literal):
    loaded = _load(tmp_path, "freshness_ms", literal)
    reported = loaded.config.headpointer.freshness_ms
    assert reported == HeadpointerConfig().freshness_ms == 500, (literal, reported)
    assert settings_from_config(loaded.config.headpointer).freshness_s == DEFAULT_FRESHNESS_S
    assert any(p.key == "freshness_ms" for p in loaded.problems), "a repair must be reported"


def test_zero_is_named_as_zero_not_as_a_type_error(tmp_path):
    message = " ".join(str(p) for p in _load(tmp_path, "freshness_ms", "0").problems)
    assert "freshness_ms" in message and "greater than 0" in message, message


@pytest.mark.parametrize("literal", ["1", "250", "500", "2000", "60000"])
def test_a_sensible_freshness_passes_through_unchanged_and_unreported(tmp_path, literal):
    loaded = _load(tmp_path, "freshness_ms", literal)
    assert loaded.config.headpointer.freshness_ms == int(literal)
    assert settings_from_config(loaded.config.headpointer).freshness_s == int(literal) / 1000.0
    assert not [p for p in loaded.problems if p.key == "freshness_ms"]


def test_the_shipped_freshness_is_inside_its_own_bounds():
    meta = {f.name: f for f in dataclasses.fields(HeadpointerConfig)}["freshness_ms"].metadata
    assert meta["min_exclusive"] < HeadpointerConfig().freshness_ms <= meta["max"]
    assert meta["max"] / 1000.0 == MAX_FRESHNESS_S
    assert HeadpointerConfig().freshness_ms / 1000.0 == DEFAULT_FRESHNESS_S


def test_the_loader_and_the_controller_agree_on_what_nonsense_is():
    for bad in (0, 0.0, -1, math.nan, math.inf, MAX_FRESHNESS_S + 1, 10**400, "x", None, True):
        assert effective_freshness_s(bad) == DEFAULT_FRESHNESS_S, bad
    assert effective_freshness_s(0.25) == 0.25
    assert effective_freshness_s(MAX_FRESHNESS_S) == MAX_FRESHNESS_S


def test_settings_from_config_survives_an_int_too_big_for_a_float():
    """The loader now repairs it; this is the second line of defence (a hand-built config)."""
    cfg = Config().headpointer
    cfg.freshness_ms = 10**400
    assert settings_from_config(cfg).freshness_s == DEFAULT_FRESHNESS_S


def test_a_zero_freshness_no_longer_leaves_the_pointer_dead():
    """The behaviour the bug produced: with 0 applied literally every sample was LOST."""
    rig = Rig(30, freshness_s=0.0, dwell_enabled=False)
    rig.feed(0.0)
    rig.feed(0.0)
    step = rig.feed(0.5)
    assert step.state is State.TRACKING, step
    assert any(a.kind is PointerActionKind.MOVE_RELATIVE for a in rig.sink.actions)


def test_a_huge_freshness_no_longer_means_never_stale():
    rig = Rig(30, freshness_s=1e9, dwell_enabled=False)
    sample = HeadPoseSignal(rig.t, 0.0, 0.0, 0.0, 1.0)
    rig.ctl.update(sample, rig.t)
    assert rig.ctl.update(sample, rig.t + 5.0).state is State.LOST  # 5 s old > the 0.5 s default


def test_the_default_freshness_still_rejects_a_stale_pose_and_accepts_a_fresh_one():
    rig = Rig(30, dwell_enabled=False)
    rig.feed(0.0)
    sample = HeadPoseSignal(rig.t, 0.0, 0.0, 0.0, 1.0)
    assert rig.ctl.update(sample, rig.t + 0.4).state is not State.LOST
    assert rig.ctl.update(sample, rig.t + 0.6).state is State.LOST
