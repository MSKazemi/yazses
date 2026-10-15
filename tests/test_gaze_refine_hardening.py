"""Real-world orderings that the first #398 tests could not see (audit, 2026-10-15).

``test_gaze_refine.py`` proves the policy with injected doubles whose answers are always
instantaneous and always consistent with the disk. Four things differ on a real desktop, and
each of them is one test here:

* **The display guard is rate-limited.** ``SessionTopologyGuard.suspended()`` answers
  ``False`` for up to five seconds after its last poll whatever happened to the monitors, so
  a layout change followed by a refinement win inside that window was *promoted into the
  stored calibration*. The refiner now asks an unthrottled confirmation immediately before
  it writes.
* **The file can change under a running daemon.** ``yazses gaze rollback`` (or a
  recalibration) edits the disk while the daemon holds the old map in memory; a candidate
  that beat the in-memory map must not overwrite the file the user just restored.
* **A tie is not a win, and NaN is not a win.** ``new > base - margin`` is ``False`` for NaN
  and, at margin 0, for an exact tie.
* **A crash between the two writes.** The rollback copy is written first, then the live
  file; dying between them must leave a live file that is the old one.

The synthetic maps and click streams exercise mechanism only; they say nothing about real
eyes, and no default here is a measurement.
"""
from __future__ import annotations

import dataclasses
import os
from pathlib import Path

import numpy as np
import pytest

import yazses.gaze.store as store_module
from yazses.config import Config
from yazses.gaze.association import Association
from yazses.gaze.calibrate import CalibrationMap
from yazses.gaze.implicit import mean_error_px, refined_if_better
from yazses.gaze.refine import ImplicitRefiner, RefinementOutcome, RefinementPolicy
from yazses.gaze.refine_runtime import GuardedContext
from yazses.gaze.store import (
    CalibrationWriteError,
    RefinementInfo,
    calibration_path,
    load_calibration_record,
    previous_calibration_path,
    promote_refinement,
    rollback_calibration,
    save_calibration,
)
from yazses.gaze.topology import (
    CalibrationContext,
    Display,
    DisplayTopology,
    SessionTopologyGuard,
)

TRUE = CalibrationMap(A=np.array([[900.0, 40.0, 960.0], [30.0, 700.0, 540.0]]))


def drifted(dx: float = 120.0, dy: float = -80.0) -> CalibrationMap:
    A = np.array(TRUE.A, copy=True)
    A[0, 2] += dx
    A[1, 2] += dy
    return CalibrationMap(A=A)


def pairs(n: int, seed: int = 0) -> list[Association]:
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        yaw, pitch = float(rng.uniform(-0.4, 0.4)), float(rng.uniform(-0.3, 0.3))
        x, y = TRUE.predict(yaw, pitch)
        out.append(Association(gaze=(yaw, pitch), click=(x, y), confidence=0.9, lag_s=0.1))
    return out


def holdout(n: int = 30, seed: int = 3):
    return [(p.gaze, p.click) for p in pairs(n, seed)]


POLICY = RefinementPolicy(
    min_train_samples=20, min_holdout_samples=8, holdout_every=4, evaluate_every=1000
)


def layout(width: int = 1920, extra: bool = False) -> CalibrationContext:
    displays = [Display("eDP-1", 0, 0, width, 1080, 1.0, True)]
    if extra:
        displays.append(Display("HDMI-1", width, 0, 2560, 1440, 1.0, False))
    return CalibrationContext(
        topology=DisplayTopology(displays=tuple(displays)),
        camera_id="0", camera_width=640, camera_height=480,
    )


# --------------------------------------------------------------------------- #
# 1. A tie, a NaN and a zero margin never promote
# --------------------------------------------------------------------------- #


def test_an_exact_tie_is_not_a_win_even_with_no_margin() -> None:
    twin = CalibrationMap(A=np.array(TRUE.A, copy=True))
    samples = holdout()
    assert mean_error_px(twin, samples) == mean_error_px(TRUE, samples)
    chosen, _, _ = refined_if_better(TRUE, twin, samples, min_improvement_px=0.0)
    assert chosen is TRUE


@pytest.mark.parametrize(
    "which",
    [pytest.param("candidate", id="nan-candidate"), pytest.param("baseline", id="nan-baseline")],
)
def test_a_nan_map_never_wins(which: str) -> None:
    broken = CalibrationMap(A=np.full((2, 3), np.nan))
    baseline, candidate = (TRUE, broken) if which == "candidate" else (broken, TRUE)
    chosen, _, _ = refined_if_better(baseline, candidate, holdout(), min_improvement_px=0.5)
    assert chosen is baseline


def test_a_policy_that_would_promote_a_tie_is_refused_when_built() -> None:
    with pytest.raises(ValueError, match="min_improvement_px"):
        RefinementPolicy(min_improvement_px=0.0)


# --------------------------------------------------------------------------- #
# 2. The rate-limited display guard cannot be the last word before a write
# --------------------------------------------------------------------------- #


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class World:
    """A desktop whose layout the test changes, read through the real guard."""

    def __init__(self) -> None:
        self.live = layout()
        self.reads = 0
        self.fail = False
        self.clock = Clock()
        self.guard = SessionTopologyGuard(
            layout(), self._read, min_interval=5.0, clock=self.clock
        )

    def _read(self) -> CalibrationContext:
        self.reads += 1
        if self.fail:
            raise OSError("xrandr hung")
        return self.live


class Recorder:
    def __init__(self) -> None:
        self.persisted: list = []

    def persist(self, candidate, result) -> None:
        self.persisted.append(candidate)


def guarded_refiner(world: World, rec: Recorder) -> ImplicitRefiner:
    return ImplicitRefiner(
        drifted(), POLICY, persist=rec.persist, context_valid=GuardedContext(world.guard)
    )


def test_a_layout_change_inside_the_guards_rate_limit_window_is_not_promoted() -> None:
    world, rec = World(), Recorder()
    r = guarded_refiner(world, rec)
    for pair in pairs(60)[:30]:
        r.observe(pair)               # first poll: unchanged, now inside the 5 s window
    world.live = layout(extra=True)   # a monitor is plugged in
    world.clock.now += 2.0            # two seconds later: the guard will not look again
    for pair in pairs(60, seed=1):
        r.observe(pair)
    assert world.guard.suspended() is False, "premise: the cheap check cannot see it yet"

    result = r.evaluate()

    assert result.outcome is RefinementOutcome.STALE_CONTEXT
    assert rec.persisted == [], "a calibration was written for a layout that had just changed"
    assert r.status().train_samples == 0, "evidence straddling the change must be discarded"


def test_the_same_win_is_promoted_when_the_layout_really_is_unchanged() -> None:
    """The confirmation must not be a veto that can never be passed."""
    world, rec = World(), Recorder()
    r = guarded_refiner(world, rec)
    for pair in pairs(80):
        r.observe(pair)
    assert r.evaluate().outcome is RefinementOutcome.APPLIED
    assert len(rec.persisted) == 1


def test_a_layout_that_cannot_be_read_at_write_time_is_not_promoted_and_keeps_its_evidence() -> None:
    world, rec = World(), Recorder()
    r = guarded_refiner(world, rec)
    for pair in pairs(80):
        r.observe(pair)
    world.fail = True
    result = r.evaluate()
    assert result.outcome is RefinementOutcome.STALE_CONTEXT
    assert rec.persisted == []
    assert r.status().train_samples > 0, "an unreadable display is not a changed one"
    world.fail = False
    assert r.evaluate().outcome is RefinementOutcome.APPLIED


def test_a_confirmation_that_raises_is_a_no() -> None:
    class Context:
        def __call__(self) -> bool:
            return True

        def confirm(self) -> bool:
            raise RuntimeError("boom")

    rec = Recorder()
    r = ImplicitRefiner(drifted(), POLICY, persist=rec.persist, context_valid=Context())
    for pair in pairs(80):
        r.observe(pair)
    assert r.evaluate().outcome is RefinementOutcome.STALE_CONTEXT
    assert rec.persisted == []


def test_verify_now_ignores_the_rate_limit_and_is_sticky_once_stale() -> None:
    world = World()
    assert world.guard.suspended() is False          # polls once
    world.live = layout(extra=True)
    assert world.guard.suspended() is False          # inside the window: blind
    assert world.guard.verify_now().stale is True    # unthrottled: sees it
    world.live = layout()                            # put it back
    assert world.guard.verify_now().stale is True    # ...and it stays stale
    assert world.guard.suspended() is True


def test_the_daemon_hands_the_refiner_a_context_that_can_confirm(monkeypatch, tmp_path) -> None:
    """The real wiring in ``Daemon._build_gaze_targeter``, with only the OS faked."""
    import types

    from yazses.core.daemon import Daemon
    from yazses.platform.factory import get_platform

    world = World()
    start = layout()
    save_calibration(drifted(), tmp_path, start)

    monkeypatch.setattr("yazses.gaze.desktop.build_desktop", lambda: object())
    monkeypatch.setattr("yazses.gaze.display.build_topology_provider", lambda: object())
    monkeypatch.setattr(
        "yazses.gaze.display.current_context", lambda camera_id="0", provider=None: world.live
    )
    monkeypatch.setattr("yazses.gaze.factory.build_gaze", lambda cfg, perception=None: object())
    monkeypatch.setattr(
        "yazses.gaze.shared.shared_source_for_gaze",
        lambda *a, **k: types.SimpleNamespace(source=None, reason="test"),
    )
    cfg = Config()
    cfg.gaze.enabled = True
    cfg.gaze.route_dictation = True
    platform = get_platform()
    platform = dataclasses.replace(
        platform, paths=dataclasses.replace(platform.paths, data_dir=tmp_path)
    )
    daemon = Daemon(config=cfg, platform=platform)

    assert daemon._build_gaze_targeter(cfg) is not None
    verified, source, context = daemon._gaze_calibration_facts
    assert verified is True and source == "explicit" and context is not None
    assert context() is True          # first poll: unchanged
    world.live = layout(extra=True)
    assert context() is True, "premise: the daemon's guard is rate-limited"
    confirm = getattr(context, "confirm", None)
    assert confirm is not None and confirm() is False


# --------------------------------------------------------------------------- #
# 3. The file changed under a running daemon
# --------------------------------------------------------------------------- #


def info() -> RefinementInfo:
    return RefinementInfo(train_samples=60, holdout_samples=20, baseline_error_px=140.0,
                          candidate_error_px=12.5)


def test_a_refinement_measured_against_another_map_does_not_overwrite_the_file(tmp_path) -> None:
    save_calibration(drifted(), tmp_path, layout())
    on_disk = calibration_path(tmp_path).read_bytes()
    in_memory = drifted(dx=300.0)         # what the running daemon thinks the baseline is
    with pytest.raises(CalibrationWriteError, match="no longer the map"):
        promote_refinement(tmp_path, TRUE, info(), expected_baseline=in_memory)
    assert calibration_path(tmp_path).read_bytes() == on_disk
    assert not previous_calibration_path(tmp_path).exists()


def test_the_matching_baseline_promotes_and_survives_the_json_round_trip(tmp_path) -> None:
    awkward = CalibrationMap(A=np.array([[900.123456789012, 40.1, 960.7], [30.3, 700.9, 540.01]]))
    save_calibration(awkward, tmp_path, layout())
    record = promote_refinement(tmp_path, TRUE, info(), expected_baseline=awkward)
    assert record.source == "implicit"


def test_a_rollback_run_while_the_daemon_is_up_is_not_silently_undone(tmp_path) -> None:
    """The ordering the doubles hide: win, user rolls back from another shell, next win."""
    save_calibration(drifted(), tmp_path, layout())
    original = calibration_path(tmp_path).read_bytes()
    world = World()

    def persist(candidate, result) -> None:
        promote_refinement(
            tmp_path, candidate,
            RefinementInfo(result.train_samples, result.holdout_samples,
                           float(result.baseline_error_px), float(result.candidate_error_px)),
            expected_baseline=r.baseline,
        )

    r = ImplicitRefiner(
        drifted(), POLICY, persist=persist, context_valid=GuardedContext(world.guard)
    )
    for pair in pairs(80):
        r.observe(pair)
    assert r.evaluate().outcome is RefinementOutcome.APPLIED

    assert rollback_calibration(tmp_path) is not None        # `yazses gaze rollback`
    assert calibration_path(tmp_path).read_bytes() == original

    # The daemon never restarted: its baseline is still the refined map, and it keeps learning
    # from a *different* truth so a second candidate genuinely beats it.
    moved = CalibrationMap(A=TRUE.A + np.array([[0.0, 0.0, 60.0], [0.0, 0.0, 0.0]]))
    rng = np.random.default_rng(9)
    for _ in range(80):
        yaw, pitch = float(rng.uniform(-0.4, 0.4)), float(rng.uniform(-0.3, 0.3))
        x, y = moved.predict(yaw, pitch)
        r.observe(Association(gaze=(yaw, pitch), click=(x, y), confidence=0.9, lag_s=0.1))
    result = r.evaluate()

    assert result.outcome is RefinementOutcome.PERSIST_FAILED
    assert calibration_path(tmp_path).read_bytes() == original, "the rollback was undone"


# --------------------------------------------------------------------------- #
# 4. Dying between the two writes
# --------------------------------------------------------------------------- #


def test_dying_after_the_rollback_copy_but_before_the_live_write_leaves_the_old_live_file(
    tmp_path, monkeypatch
) -> None:
    save_calibration(drifted(), tmp_path, layout())
    before = calibration_path(tmp_path).read_bytes()
    real_replace = os.replace
    calls: list[str] = []

    def die_on_live(src, dst, *a, **k):
        calls.append(Path(dst).name)
        if Path(dst) == calibration_path(tmp_path):
            raise KeyboardInterrupt  # not an Exception: the harshest "crash" a test can raise
        return real_replace(src, dst, *a, **k)

    monkeypatch.setattr(store_module.os, "replace", die_on_live)
    with pytest.raises(KeyboardInterrupt):
        promote_refinement(tmp_path, TRUE, info())

    assert calls == [previous_calibration_path(tmp_path).name, calibration_path(tmp_path).name], (
        "the rollback point must be recorded before the live file is touched"
    )
    assert calibration_path(tmp_path).read_bytes() == before
    assert previous_calibration_path(tmp_path).read_bytes() == before
    assert load_calibration_record(tmp_path) is not None
    litter = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert litter == [], "an interrupted write left a temporary file beside the calibration"


def test_a_missing_or_corrupt_store_refuses_the_promotion_and_creates_nothing(tmp_path) -> None:
    with pytest.raises(CalibrationWriteError):
        promote_refinement(tmp_path, TRUE, info(), expected_baseline=drifted())
    calibration_path(tmp_path).write_bytes(b"{not json")
    with pytest.raises(CalibrationWriteError):
        promote_refinement(tmp_path, TRUE, info(), expected_baseline=drifted())
    assert calibration_path(tmp_path).read_bytes() == b"{not json"
    assert not previous_calibration_path(tmp_path).exists()


# --------------------------------------------------------------------------- #
# 5. Held-out discipline
# --------------------------------------------------------------------------- #


def test_the_split_is_deterministic_and_does_not_depend_on_the_pair_values() -> None:
    """Chosen by position *before* a pair is seen, so no value can steer itself into the
    held-out set (or out of it), and two runs over the same stream agree."""
    stream = pairs(100, seed=4)
    shuffled_values = pairs(100, seed=5)

    def counts(s):
        r = ImplicitRefiner(drifted(), POLICY, persist=lambda c, res: None)
        for pair in s:
            r.observe(pair)
        st = r.status()
        return st.train_samples, st.holdout_samples

    assert counts(stream) == counts(stream) == counts(shuffled_values)


def test_one_wild_held_out_click_cannot_manufacture_a_win_or_a_loss() -> None:
    """A mis-click far from the baseline is refused at intake, so it cannot be the evidence."""
    rec = Recorder()
    r = ImplicitRefiner(drifted(), POLICY, persist=rec.persist)
    for index, pair in enumerate(pairs(80)):
        if index % 4 == 3 and index == 39:  # the held-out slot of the 10th group
            pair = dataclasses.replace(pair, click=(pair.click[0] + 5000.0, pair.click[1]))
        r.observe(pair)
    assert r.status().rejected >= 1
    assert r.evaluate().outcome is RefinementOutcome.APPLIED
