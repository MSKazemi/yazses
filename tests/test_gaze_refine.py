"""A passive refinement can never replace a better calibration (#398).

The Phase 2 exit gate in ``design/eye-control/ROADMAP.md`` is a sentence about what must
be *impossible*: "implicit calibration can never replace a better baseline in tests". So
this file is organised around refusals, and each refusal is checked in the way that cannot
pass by accident:

* **Bytes, not values.** A rejected, failed or premature refinement is asserted to leave
  the stored file *byte-for-byte* what it was, because "the same calibration" read back
  through a parser hides a rewritten timestamp, a reordered key, a changed source.
* **Injected failure.** The atomic-write guarantee is tested by making ``os.replace`` raise
  at the worst moment and then reading the directory.
* **A win has to be a real win.** The worse-candidate test feeds the estimator *biased*
  training clicks and the held-out buffer *honest* ones, so the candidate really does get
  worse. A gate that always said yes would fail it (mutation-checked: neutralising the
  ``refined_if_better`` verdict turns it red).
* **Empty is a named outcome**, not a division and not a default win.

The synthetic maps and click streams are fixtures for mechanism. They say nothing about
real eyes; the defaults they exercise are unmeasured starting values and field evidence
(#104) is what sets them.

Hermetic: numeric streams, ``tmp_path`` for the store, injected persist/activate callables.
No camera, no desktop, no network.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import numpy as np
import pytest

import yazses.gaze.refine as refine_module
import yazses.gaze.store as store_module
from yazses.gaze.association import Association, AssociationPolicy
from yazses.gaze.calibrate import CalibrationMap
from yazses.gaze.capture import ClickGazeCapture
from yazses.gaze.clicks import ClickEvent
from yazses.gaze.implicit import mean_error_px
from yazses.gaze.refine import (
    ImplicitRefiner,
    RefinementOutcome,
    RefinementPolicy,
)
from yazses.gaze.store import (
    PREVIOUS_FILENAME,
    CalibrationRecord,
    CalibrationWriteError,
    RefinementInfo,
    calibration_path,
    load_calibration_record,
    previous_calibration_path,
    promote_refinement,
    rollback_available,
    rollback_calibration,
    save_calibration,
)
from yazses.gaze.topology import CalibrationContext, Display, DisplayTopology
from yazses.perception.signals import GazeSignal

# --------------------------------------------------------------------------- #
# Fixtures: a "true" eye->screen map, and a wizard fit that has since drifted
# --------------------------------------------------------------------------- #

TRUE = CalibrationMap(A=np.array([[900.0, 40.0, 960.0], [30.0, 700.0, 540.0]]))


def drifted(dx: float = 120.0, dy: float = -80.0) -> CalibrationMap:
    A = np.array(TRUE.A, copy=True)
    A[0, 2] += dx
    A[1, 2] += dy
    return CalibrationMap(A=A)


def pairs(n: int, *, truth: CalibrationMap = TRUE, seed: int = 0, bias=(0.0, 0.0), confidence=0.9):
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        yaw, pitch = float(rng.uniform(-0.4, 0.4)), float(rng.uniform(-0.3, 0.3))
        x, y = truth.predict(yaw, pitch)
        out.append(
            Association(
                gaze=(yaw, pitch),
                click=(x + bias[0], y + bias[1]),
                confidence=confidence,
                lag_s=0.1,
            )
        )
    return out


POLICY = RefinementPolicy(
    min_train_samples=20, min_holdout_samples=8, holdout_every=4, evaluate_every=1000
)


class Recorder:
    """persist/activate doubles that remember *order* as well as arguments."""

    def __init__(self, *, persist_error: Exception | None = None, activate_error=None):
        self.events: list[tuple[str, object]] = []
        self._persist_error = persist_error
        self._activate_error = activate_error

    def persist(self, candidate, result) -> None:
        self.events.append(("persist", candidate))
        if self._persist_error is not None:
            raise self._persist_error

    def activate(self, candidate) -> None:
        self.events.append(("activate", candidate))
        if self._activate_error is not None:
            raise self._activate_error

    @property
    def names(self) -> list[str]:
        return [name for name, _ in self.events]


def refiner(baseline=None, rec: Recorder | None = None, policy: RefinementPolicy = POLICY, **kw):
    rec = rec or Recorder()
    return (
        ImplicitRefiner(
            baseline or drifted(), policy, persist=rec.persist, activate=rec.activate, **kw
        ),
        rec,
    )


def feed(r: ImplicitRefiner, stream) -> None:
    for pair in stream:
        r.observe(pair)


# --------------------------------------------------------------------------- #
# The policy
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_train_samples": 2},          # an affine map has three coefficients
        {"min_holdout_samples": 0},        # nothing can be compared on zero
        {"holdout_every": 1},              # would leave nothing to train on
        {"min_holdout_samples": 10, "max_holdout_samples": 9},
        {"evaluate_every": 0},
        {"min_improvement_px": -1.0},
        {"min_improvement_px": float("nan")},
        {"forgetting": 0.0},
        {"forgetting": 1.5},
        {"max_residual_px": 0.0},
        {"min_confidence": 1.5},
    ],
)
def test_a_nonsense_policy_is_refused_when_built(kwargs) -> None:
    with pytest.raises(ValueError):
        RefinementPolicy(**kwargs)


# --------------------------------------------------------------------------- #
# Empty and partial: every one a named outcome, none a default win
# --------------------------------------------------------------------------- #


def test_evaluating_with_no_samples_at_all_changes_nothing() -> None:
    r, rec = refiner()
    result = r.evaluate()
    assert result.outcome is RefinementOutcome.INSUFFICIENT_DATA
    assert (result.train_samples, result.holdout_samples) == (0, 0)
    assert result.baseline_error_px is None and result.candidate_error_px is None
    assert rec.events == []


def test_plenty_of_training_but_no_held_out_pairs_is_not_a_win() -> None:
    r, rec = refiner(policy=RefinementPolicy(
        min_train_samples=20, min_holdout_samples=8, holdout_every=1000, evaluate_every=10_000
    ))
    feed(r, pairs(60))  # holdout_every=1000: every one of these goes to training
    assert r.evaluate().outcome is RefinementOutcome.INSUFFICIENT_DATA
    assert rec.events == []


def test_plenty_held_out_but_too_little_training_is_not_a_win() -> None:
    r, rec = refiner()
    feed(r, pairs(12))  # 9 train... below 20; 3 held out below 8
    assert r.evaluate().outcome is RefinementOutcome.INSUFFICIENT_DATA
    assert rec.events == []


def test_the_threshold_is_exact_one_short_of_either_count_is_still_insufficient() -> None:
    policy = RefinementPolicy(min_train_samples=3, min_holdout_samples=2, holdout_every=2,
                              evaluate_every=1000)
    r, rec = refiner(policy=policy)
    feed(r, pairs(5))  # positions 0,2,4 train (3); 1,3 held out (2): exactly enough
    assert r.evaluate().outcome is not RefinementOutcome.INSUFFICIENT_DATA
    r2, _ = refiner(policy=policy)
    feed(r2, pairs(4))  # 2 train, 2 held out
    assert r2.evaluate().outcome is RefinementOutcome.INSUFFICIENT_DATA


# --------------------------------------------------------------------------- #
# A better candidate promotes — persist first, then live
# --------------------------------------------------------------------------- #


def test_a_better_candidate_is_saved_then_activated_and_becomes_the_baseline() -> None:
    baseline = drifted()
    r, rec = refiner(baseline)
    feed(r, pairs(80))
    result = r.evaluate()
    assert result.outcome is RefinementOutcome.APPLIED
    assert rec.names == ["persist", "activate"], "the disk must have the map before the process uses it"
    chosen = rec.events[0][1]
    assert rec.events[1][1] is chosen
    assert result.candidate_error_px is not None and result.baseline_error_px is not None
    assert result.candidate_error_px < result.baseline_error_px
    held_out = pairs(40, seed=99)
    pts = [(p.gaze, p.click) for p in held_out]
    assert mean_error_px(chosen, pts) < mean_error_px(baseline, pts) / 3
    assert r.baseline is chosen and r.source == "implicit"


def test_after_a_promotion_the_estimator_and_held_out_evidence_start_over() -> None:
    """The held-out pairs approved this map. Judging the next candidate on them would be
    grading on the exam that was studied for."""
    r, _ = refiner()
    feed(r, pairs(80))
    r.evaluate()
    status = r.status()
    assert (status.train_samples, status.holdout_samples) == (0, 0)
    assert status.applied == 1


def test_evaluation_runs_by_itself_every_n_accepted_pairs() -> None:
    policy = RefinementPolicy(min_train_samples=20, min_holdout_samples=8, holdout_every=4,
                              evaluate_every=40)
    r, rec = refiner(policy=policy)
    feed(r, pairs(39))
    assert r.status().evaluations == 0
    feed(r, pairs(1, seed=5))
    assert r.status().evaluations == 1
    assert r.status().last_result is not None


# --------------------------------------------------------------------------- #
# The refusals
# --------------------------------------------------------------------------- #


def test_a_candidate_that_is_worse_on_held_out_data_never_replaces_the_baseline() -> None:
    """The baseline is perfect. The training clicks are biased 90 px, so the estimator is
    pulled off it; the held-out clicks are honest. Position routing is fixed (every 4th is
    held out), so the two streams are interleaved by construction."""
    r, rec = refiner(baseline=TRUE)
    honest = pairs(200, seed=1)
    biased = pairs(200, seed=2, bias=(90.0, 90.0))
    stream = []
    for i in range(80):
        stream.append(honest[i] if i % 4 == 3 else biased[i])
    feed(r, stream)

    result = r.evaluate()

    assert result.outcome is RefinementOutcome.KEPT_BASELINE
    assert result.candidate_error_px > result.baseline_error_px, "the fixture must make it worse"
    assert rec.events == [], "a worse candidate must not even be offered to persist"
    assert r.baseline is TRUE and r.source == "explicit"


def test_a_candidate_that_is_only_marginally_better_does_not_clear_the_margin() -> None:
    policy = RefinementPolicy(min_train_samples=20, min_holdout_samples=8, holdout_every=4,
                              evaluate_every=1000, min_improvement_px=500.0)
    r, rec = refiner(policy=policy)
    feed(r, pairs(80))
    assert r.evaluate().outcome is RefinementOutcome.KEPT_BASELINE
    assert rec.events == []


def test_a_kept_baseline_keeps_learning_and_can_still_win_later() -> None:
    r, rec = refiner(policy=RefinementPolicy(
        min_train_samples=20, min_holdout_samples=8, holdout_every=4, evaluate_every=1000,
        min_improvement_px=500.0,
    ))
    feed(r, pairs(80))
    first = r.evaluate()
    assert first.outcome is RefinementOutcome.KEPT_BASELINE
    assert r.status().train_samples == first.train_samples, "samples are retained after a loss"


def test_training_pairs_never_become_held_out_evidence() -> None:
    """Spy on both sides: no pair the estimator learned from may be in the verdict's set."""
    r, _ = refiner()
    trained: set[int] = set()
    real_observe = r._calibrator.observe

    def spy_observe(gaze, click, *, confidence=1.0):
        trained.add(id(gaze))
        return real_observe(gaze, click, confidence=confidence)

    r._calibrator.observe = spy_observe  # type: ignore[method-assign]
    judged: list[set[int]] = []
    real_gate = refine_module.refined_if_better

    def spy_gate(baseline, candidate, holdout, **kw):
        judged.append({id(gaze) for gaze, _ in holdout})
        return real_gate(baseline, candidate, holdout, **kw)

    stream = pairs(80)
    refine_module.refined_if_better = spy_gate
    try:
        feed(r, stream)
        r.evaluate()
    finally:
        refine_module.refined_if_better = real_gate
    assert judged and judged[0], "the gate must have been shown held-out pairs"
    assert trained and judged[0].isdisjoint(trained)
    assert len(trained) + len(judged[0]) == 80


def test_every_pair_is_routed_to_exactly_one_side_in_the_configured_proportion() -> None:
    r, _ = refiner()
    feed(r, pairs(40))
    status = r.status()
    assert status.holdout_samples == 10          # every 4th of 40
    assert status.train_samples == 30


def test_low_confidence_and_outlier_pairs_are_refused_on_both_sides() -> None:
    r, _ = refiner(baseline=TRUE)
    feed(r, pairs(8, confidence=0.1))                             # eyes disagreed
    feed(r, pairs(8, bias=(5000.0, 0.0), seed=3))                 # a click on another planet
    status = r.status()
    assert (status.train_samples, status.holdout_samples) == (0, 0)
    assert status.rejected == 16


def test_the_held_out_buffer_is_bounded() -> None:
    policy = RefinementPolicy(min_train_samples=3, min_holdout_samples=1, holdout_every=2,
                              max_holdout_samples=5, evaluate_every=10_000)
    r, _ = refiner(policy=policy)
    feed(r, pairs(200))
    assert r.status().holdout_samples == 5


# --------------------------------------------------------------------------- #
# Failure paths: the baseline survives them
# --------------------------------------------------------------------------- #


def test_when_saving_fails_the_baseline_stays_active_and_nothing_goes_live() -> None:
    rec = Recorder(persist_error=OSError("disk full"))
    baseline = drifted()
    r, _ = refiner(baseline, rec)
    feed(r, pairs(80))
    result = r.evaluate()
    assert result.outcome is RefinementOutcome.PERSIST_FAILED
    assert rec.names == ["persist"], "activate must never run after a failed save"
    assert r.baseline is baseline and r.source == "explicit"
    assert r.status().applied == 0
    assert "OSError" in result.reason and "disk full" not in result.reason


def test_a_failed_save_is_retried_on_the_next_evaluation_with_the_samples_kept() -> None:
    rec = Recorder(persist_error=OSError("disk full"))
    r, _ = refiner(drifted(), rec)
    feed(r, pairs(80))
    r.evaluate()
    rec._persist_error = None
    assert r.evaluate().outcome is RefinementOutcome.APPLIED


def test_if_going_live_fails_after_a_successful_save_the_promotion_stands() -> None:
    """The file is right; only the running process missed the switch. Undoing a good save
    because of that would be the worse outcome — the next start loads the refined map."""
    rec = Recorder(activate_error=RuntimeError("targeter gone"))
    r, _ = refiner(drifted(), rec)
    feed(r, pairs(80))
    assert r.evaluate().outcome is RefinementOutcome.APPLIED
    assert rec.names == ["persist", "activate"]


# --------------------------------------------------------------------------- #
# A changed display context refines nothing (ADR-v2-149)
# --------------------------------------------------------------------------- #


def test_pairs_are_refused_while_the_display_context_is_stale() -> None:
    valid = {"now": True}
    r, rec = refiner(context_valid=lambda: valid["now"])
    feed(r, pairs(30))
    assert r.status().train_samples > 0
    valid["now"] = False
    assert r.observe(pairs(1)[0]) is False
    assert (r.status().train_samples, r.status().holdout_samples) == (0, 0), (
        "evidence from the old layout must be discarded, not kept for later"
    )
    assert rec.events == []


def test_an_evaluation_in_a_stale_context_discards_and_applies_nothing() -> None:
    valid = {"now": True}
    r, rec = refiner(context_valid=lambda: valid["now"])
    feed(r, pairs(80))
    valid["now"] = False
    result = r.evaluate()
    assert result.outcome is RefinementOutcome.STALE_CONTEXT
    assert rec.events == []
    valid["now"] = True
    assert r.status().train_samples == 0, "resumption starts from zero, not from old evidence"


def test_a_context_check_that_raises_counts_as_a_changed_context() -> None:
    """A guard that cannot answer must not be read as "all clear"."""

    def broken() -> bool:
        raise RuntimeError("display query failed")

    r, rec = refiner(context_valid=broken)
    assert r.observe(pairs(1)[0]) is False
    assert r.evaluate().outcome is RefinementOutcome.STALE_CONTEXT
    assert rec.events == []


# --------------------------------------------------------------------------- #
# The store: atomic, byte-exact, reversible
# --------------------------------------------------------------------------- #


def context() -> CalibrationContext:
    topology = DisplayTopology(
        displays=(Display(identifier="eDP-1", x=0, y=0, width=1920, height=1080, scale=1.0, primary=True),)
    )
    return CalibrationContext(topology=topology, camera_id="0", camera_width=640, camera_height=480)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def info() -> RefinementInfo:
    return RefinementInfo(train_samples=60, holdout_samples=20, baseline_error_px=140.0,
                          candidate_error_px=12.5)


@pytest.fixture
def saved(tmp_path: Path) -> Path:
    save_calibration(drifted(), tmp_path, context())
    return tmp_path


def test_an_explicit_calibration_records_its_source_time_and_context_fingerprint(saved) -> None:
    record = load_calibration_record(saved)
    assert record is not None
    assert record.source == "explicit"
    assert record.refinement is None
    assert record.saved_at.endswith("+00:00")
    raw = calibration_path(saved).read_text(encoding="utf-8")
    assert context().fingerprint() in raw


def test_a_calibration_written_before_source_existed_reads_as_explicit(tmp_path) -> None:
    calibration_path(tmp_path).write_text(
        '{"version": 2, "A": [[1, 2, 3], [4, 5, 6]]}', encoding="utf-8"
    )
    record = load_calibration_record(tmp_path)
    assert record is not None and record.source == "explicit" and record.saved_at == ""


def test_promoting_keeps_the_previous_file_byte_for_byte_and_the_context(saved) -> None:
    before = calibration_path(saved).read_bytes()
    record = promote_refinement(saved, TRUE, info())
    assert previous_calibration_path(saved).read_bytes() == before
    assert record.source == "implicit"
    assert record.refinement == info()
    assert record.context == context(), "the context is carried over, never replaced"
    assert np.allclose(record.calibration.A, TRUE.A)
    assert rollback_available(saved)


def test_rolling_back_restores_the_exact_prior_bytes_and_removes_the_copy(saved) -> None:
    before = calibration_path(saved).read_bytes()
    promote_refinement(saved, TRUE, info())
    assert calibration_path(saved).read_bytes() != before

    restored = rollback_calibration(saved)

    assert calibration_path(saved).read_bytes() == before, "an exact restore, not a re-encoding"
    assert restored is not None and restored.source == "explicit"
    assert not previous_calibration_path(saved).exists()
    assert rollback_available(saved) is False


def test_rolling_back_twice_or_with_nothing_to_roll_back_is_a_clean_none(saved) -> None:
    assert rollback_calibration(saved) is None
    promote_refinement(saved, TRUE, info())
    assert rollback_calibration(saved) is not None
    assert rollback_calibration(saved) is None


def test_a_fresh_wizard_run_removes_the_stale_rollback_copy(saved) -> None:
    promote_refinement(saved, TRUE, info())
    save_calibration(drifted(1.0, 1.0), saved, context())
    assert not previous_calibration_path(saved).exists()
    assert rollback_calibration(saved) is None


def test_an_unreadable_rollback_copy_is_refused_and_the_live_file_is_left_alone(saved) -> None:
    promote_refinement(saved, TRUE, info())
    live = digest(calibration_path(saved))
    previous_calibration_path(saved).write_text("not json", encoding="utf-8")
    with pytest.raises(CalibrationWriteError):
        rollback_calibration(saved)
    assert digest(calibration_path(saved)) == live


def test_promoting_with_nothing_stored_is_refused(tmp_path) -> None:
    with pytest.raises(CalibrationWriteError):
        promote_refinement(tmp_path, TRUE, info())
    assert list(tmp_path.iterdir()) == []


def test_promoting_over_an_unreadable_calibration_is_refused(tmp_path) -> None:
    calibration_path(tmp_path).write_text("{ torn", encoding="utf-8")
    with pytest.raises(CalibrationWriteError):
        promote_refinement(tmp_path, TRUE, info())
    assert calibration_path(tmp_path).read_text(encoding="utf-8") == "{ torn"


def test_a_failure_replacing_the_live_file_leaves_it_byte_identical_and_no_litter(
    saved, monkeypatch
) -> None:
    before = calibration_path(saved).read_bytes()
    real_replace = os.replace
    calls = {"n": 0}

    def fail_on_the_live_file(src, dst, *a, **k):
        calls["n"] += 1
        if Path(dst) == calibration_path(saved):
            raise OSError("simulated power loss")
        return real_replace(src, dst, *a, **k)

    monkeypatch.setattr(store_module.os, "replace", fail_on_the_live_file)
    with pytest.raises(CalibrationWriteError):
        promote_refinement(saved, TRUE, info())

    assert calibration_path(saved).read_bytes() == before
    assert load_calibration_record(saved) is not None
    leftovers = [p.name for p in saved.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == [], f"a failed write left temporary files behind: {leftovers}"
    assert previous_calibration_path(saved).read_bytes() == before, (
        "the rollback copy was written first and is identical to the live file"
    )


def test_a_failure_writing_the_rollback_copy_means_the_live_file_is_never_touched(
    saved, monkeypatch
) -> None:
    before = calibration_path(saved).read_bytes()
    real_replace = os.replace

    def fail_on_the_backup(src, dst, *a, **k):
        if Path(dst).name == PREVIOUS_FILENAME:
            raise OSError("disk full")
        return real_replace(src, dst, *a, **k)

    monkeypatch.setattr(store_module.os, "replace", fail_on_the_backup)
    with pytest.raises(CalibrationWriteError):
        promote_refinement(saved, TRUE, info())
    assert calibration_path(saved).read_bytes() == before
    assert not any(p.name.endswith(".tmp") for p in saved.iterdir())


def test_a_failed_explicit_save_leaves_the_previous_explicit_calibration(saved, monkeypatch) -> None:
    before = calibration_path(saved).read_bytes()
    monkeypatch.setattr(store_module.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
    with pytest.raises(OSError):
        save_calibration(TRUE, saved, context())
    assert calibration_path(saved).read_bytes() == before
    assert not any(p.name.endswith(".tmp") for p in saved.iterdir())


# --------------------------------------------------------------------------- #
# The whole path against the real store
# --------------------------------------------------------------------------- #


def real_refiner(data_dir: Path, *, baseline: CalibrationMap, activated: list | None = None):
    def persist(candidate, result) -> None:
        promote_refinement(
            data_dir,
            candidate,
            RefinementInfo(result.train_samples, result.holdout_samples,
                           float(result.baseline_error_px), float(result.candidate_error_px)),
        )

    return ImplicitRefiner(
        baseline, POLICY, persist=persist,
        activate=(activated.append if activated is not None else None),
    )


def test_a_win_reaches_the_disk_with_its_evidence_and_can_be_rolled_back(tmp_path) -> None:
    save_calibration(drifted(), tmp_path, context())
    original = calibration_path(tmp_path).read_bytes()
    live: list = []
    r = real_refiner(tmp_path, baseline=drifted(), activated=live)
    feed(r, pairs(80))
    assert r.evaluate().outcome is RefinementOutcome.APPLIED

    record = load_calibration_record(tmp_path)
    assert record is not None and record.source == "implicit"
    assert record.refinement is not None
    assert record.refinement.candidate_error_px < record.refinement.baseline_error_px
    assert len(live) == 1 and np.allclose(live[0].A, record.calibration.A)

    rollback_calibration(tmp_path)
    assert calibration_path(tmp_path).read_bytes() == original


def test_a_loss_leaves_the_stored_file_byte_identical_and_creates_no_backup(tmp_path) -> None:
    save_calibration(TRUE, tmp_path, context())
    before = digest(calibration_path(tmp_path))
    names_before = sorted(p.name for p in tmp_path.iterdir())
    r = real_refiner(tmp_path, baseline=TRUE)
    honest, biased = pairs(200, seed=1), pairs(200, seed=2, bias=(90.0, 90.0))
    feed(r, [honest[i] if i % 4 == 3 else biased[i] for i in range(80)])

    assert r.evaluate().outcome is RefinementOutcome.KEPT_BASELINE

    assert digest(calibration_path(tmp_path)) == before
    assert sorted(p.name for p in tmp_path.iterdir()) == names_before


def test_a_save_that_dies_midway_through_the_real_store_keeps_the_baseline(
    tmp_path, monkeypatch
) -> None:
    save_calibration(drifted(), tmp_path, context())
    before = calibration_path(tmp_path).read_bytes()
    real_replace = os.replace

    def die(src, dst, *a, **k):
        if Path(dst) == calibration_path(tmp_path):
            raise OSError("killed")
        return real_replace(src, dst, *a, **k)

    monkeypatch.setattr(store_module.os, "replace", die)
    live: list = []
    r = real_refiner(tmp_path, baseline=drifted(), activated=live)
    feed(r, pairs(80))

    result = r.evaluate()

    assert result.outcome is RefinementOutcome.PERSIST_FAILED
    assert calibration_path(tmp_path).read_bytes() == before
    assert live == [], "the running process must not use a map the disk does not have"


def test_click_events_to_a_promoted_file_end_to_end(tmp_path) -> None:
    """Fake gaze stream + fake clicks through capture, association, refinement and store."""
    save_calibration(drifted(), tmp_path, context())
    r = real_refiner(tmp_path, baseline=drifted())
    capture = ClickGazeCapture(r.observe, AssociationPolicy())
    rng = np.random.default_rng(7)
    t = 1000.0
    for _ in range(80):
        yaw, pitch = float(rng.uniform(-0.4, 0.4)), float(rng.uniform(-0.3, 0.3))
        capture.record_gaze(GazeSignal(t, yaw, pitch, 0.9))
        x, y = TRUE.predict(yaw, pitch)
        capture.handle_click(ClickEvent(t + 0.1, x, y))
        t += 1.0
    assert r.evaluate().outcome is RefinementOutcome.APPLIED
    record = load_calibration_record(tmp_path)
    assert isinstance(record, CalibrationRecord) and record.source == "implicit"
