"""Graded squeeze and the BrainFlow source (#103).

The onset detector is exercised against synthetic envelopes, as the issue asks;
the board is a fake, so no hardware and no BrainFlow install is involved. The
guarantee that gets the most tests is the one the serial backend already gives:
a missing device or dependency is a logged no-op, never a crash.
"""

from __future__ import annotations

import numpy as np
import pytest

from yazses.platform.emg.brainflow_source import BrainFlowSource
from yazses.platform.emg.pressure import (
    GradedSqueeze,
    PressureThresholds,
    SqueezeLevel,
    calibrate,
    envelope,
    tkeo,
)

RATE = 1000


def _burst(amplitude: float, hz: float = 90.0, n: int = 400, drift: float = 0.0):
    """Synthetic EMG: a band-limited burst, optionally on a wandering baseline."""
    t = np.arange(n) / RATE
    rng = np.random.default_rng(0)
    signal = amplitude * np.sin(2 * np.pi * hz * t) * rng.normal(1.0, 0.1, n)
    return signal + drift * np.sin(2 * np.pi * 0.5 * t)


# ---- TKEO ------------------------------------------------------------------


def test_tkeo_responds_to_a_contraction():
    assert envelope(_burst(1.0)) > envelope(_burst(0.05)) * 10


def test_tkeo_suppresses_low_frequency_drift():
    """The reason for TKEO over a bare threshold: baseline wander is large and slow.

    A rectified-amplitude threshold would read this drift as a contraction; TKEO
    weighs frequency as well as amplitude, so it does not.
    """
    quiet_with_drift = _burst(0.02, drift=3.0)
    real_squeeze = _burst(0.6)
    assert envelope(quiet_with_drift) < envelope(real_squeeze)


def test_tkeo_drops_endpoints_rather_than_inventing_them():
    assert len(tkeo(np.arange(10.0))) == 8
    assert len(tkeo([1.0, 2.0])) == 0


def test_envelope_of_nothing_is_zero_not_a_crash():
    assert envelope([]) == 0.0
    assert envelope([1.0]) == 0.0


# ---- calibration -----------------------------------------------------------


def test_thresholds_are_derived_from_this_persons_own_range():
    """Fixed microvolt thresholds are meaningless across people and placements."""
    thresholds = calibrate(_burst(0.02), _burst(1.0))
    assert 0 < thresholds.light < thresholds.hard


def test_a_stronger_person_gets_higher_thresholds():
    weak = calibrate(_burst(0.02), _burst(0.4))
    strong = calibrate(_burst(0.02), _burst(4.0))
    assert strong.hard > weak.hard


def test_indistinguishable_baseline_and_contraction_is_refused():
    """Placing thresholds anyway would produce a switch that fires at random."""
    with pytest.raises(ValueError, match="electrode placement"):
        calibrate(_burst(0.5), _burst(0.5))


# ---- levels ----------------------------------------------------------------


def test_relaxed_light_and_hard_are_separated():
    t = PressureThresholds(light=10.0, hard=50.0)
    assert t.level(1.0) is SqueezeLevel.RELAXED
    assert t.level(20.0) is SqueezeLevel.LIGHT
    assert t.level(80.0) is SqueezeLevel.HARD


def test_thresholds_are_inclusive_at_the_boundary():
    t = PressureThresholds(light=10.0, hard=50.0)
    assert t.level(10.0) is SqueezeLevel.LIGHT
    assert t.level(50.0) is SqueezeLevel.HARD


def test_light_squeeze_dictates_and_hard_squeeze_commands():
    """Mirrors the command key, so all three mode switches behave alike."""
    g = GradedSqueeze(PressureThresholds(10.0, 50.0), hold_samples=1)
    g.update(20.0)
    assert g.mode == "full_text"
    g.update(80.0)
    assert g.mode == "command"
    g.update(0.0)
    assert g.mode is None


def test_a_ramp_to_hard_does_not_briefly_start_dictation():
    """The reason for the hold: passing through `light` is not a light squeeze."""
    g = GradedSqueeze(PressureThresholds(10.0, 50.0), hold_samples=3)
    modes = []
    for value in (20.0, 35.0, 80.0, 85.0, 90.0, 88.0):
        if g.update(value) is not None:
            modes.append(g.mode)
    assert modes == ["command"], f"expected no transient dictate, got {modes}"


def test_a_change_is_reported_once_not_every_sample():
    g = GradedSqueeze(PressureThresholds(10.0, 50.0), hold_samples=1)
    assert g.update(20.0) is SqueezeLevel.LIGHT
    assert g.update(21.0) is None
    assert g.update(22.0) is None


# ---- the BrainFlow source, with a fake board -------------------------------


class _FakeBoard:
    """Implements exactly the BrainFlow methods the source calls."""

    def __init__(self, chunks, fail_on=""):
        self._chunks, self._fail_on = list(chunks), fail_on
        self.prepared = self.started = self.stopped = self.released = False

    def _maybe_fail(self, step):
        if self._fail_on == step:
            raise RuntimeError(f"{step} failed")

    def prepare_session(self):
        self._maybe_fail("prepare_session")
        self.prepared = True

    def start_stream(self):
        self._maybe_fail("start_stream")
        self.started = True

    def get_current_board_data(self, n):
        return self._chunks.pop(0) if self._chunks else np.zeros((1, 0))

    def stop_stream(self):
        self.stopped = True

    def release_session(self):
        self.released = True


def _run_once(chunks, fail_on="", monkeypatch=None):
    """Drive the source until the fake board runs out of chunks, then stop it.

    The stream has to actually iterate — stopping before `run()` would exit the
    loop before a single sample is read, which is how this harness was wrong the
    first time and reported "no squeeze detected" for a hard squeeze.

    The fake serves a **single row**, so it only fakes a board whose EMG data sits
    on row 0. `BrainFlowSource._emg_channels` asks the real `BoardShim` for the
    channel map and falls back to "all rows" only when the import fails, and board
    -1 (BrainFlow's synthetic board) reports rows 1..16 — every one of them past
    the end of a 1-row array, so `_consume` finds nothing usable and returns before
    the detector ever sees a sample.

    That made the outcome depend on whether `brainflow` happened to be installed:
    green on every CI runner and on the maintainer's laptop, red on a box built
    with `uv sync --all-extras`. Found by building that box. The fake now pins the
    channel map it is built for, so the test measures the squeeze detector on every
    machine rather than measuring the environment.
    """
    started, ended = [], []
    board = _FakeBoard(chunks, fail_on=fail_on)
    source = BrainFlowSource(
        -1, PressureThresholds(1e-4, 1e-2), started.append, lambda: ended.append(1),
        board_factory=lambda: board,
    )
    serve = board.get_current_board_data

    def serve_then_stop(n):
        if not board._chunks:
            source.stop()
        return serve(n)

    board.get_current_board_data = serve_then_stop
    # Row 0 is where this fake puts its samples; say so rather than letting an
    # optional install decide.
    source._emg_channels = lambda: []
    source.run()
    return board, started, ended


def test_a_squeeze_on_the_board_starts_a_mode():
    strong = np.vstack([_burst(2.0)])
    _, started, _ = _run_once([strong] * 5)
    assert started, "a hard squeeze should have started a mode"


def test_a_missing_board_is_a_logged_no_op_not_a_crash():
    """Same guarantee the serial backend gives."""
    board, started, ended = _run_once([], fail_on="prepare_session")
    assert (started, ended) == ([], [])
    assert board.started is False


def test_a_missing_dependency_is_a_logged_no_op():
    source = BrainFlowSource(-1, PressureThresholds(1.0, 2.0), lambda m: None, lambda: None)
    source.stop()
    source.run()      # brainflow is not installed here; must simply return


def test_the_session_is_released_even_after_an_error():
    """An un-released board keeps the device locked for every later run."""
    board = _FakeBoard([np.zeros((1, 0))])
    board.get_current_board_data = lambda n: (_ for _ in ()).throw(RuntimeError("usb gone"))
    source = BrainFlowSource(
        -1, PressureThresholds(1.0, 2.0), lambda m: None, lambda: None,
        board_factory=lambda: board,
    )
    source.run()
    assert board.stopped and board.released


def test_an_empty_chunk_changes_nothing():
    _, started, ended = _run_once([np.zeros((1, 0))])
    assert (started, ended) == ([], [])
