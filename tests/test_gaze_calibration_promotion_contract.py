"""The promotion decision is a pure function, and the stored artifact is versioned (#398).

``tests/test_gaze_refine.py`` and ``tests/test_gaze_refine_hardening.py`` test the refiner
and the store as a running system. This file pins the three contracts underneath them that
a later edit could erode without any of those behaviours visibly changing:

* **The verdict is pure.** :func:`yazses.gaze.refine.decide_promotion` decides
  insufficient / kept / apply from its arguments alone: no I/O, no clock, no state, and it
  does not modify the maps or the held-out pairs it is given. The gate it states is checked
  at its exact float boundary, so "at least the margin" cannot drift to "more than" (or the
  reverse) unnoticed.
* **The split is a pure function of position**
  (:func:`yazses.gaze.refine.routes_to_holdout`), so it is deterministic by construction.
* **The schema version is read, not just written.** A damaged version is a damaged file
  (#415); a file from a newer build still routes but is never re-encoded by a promotion.
* **The artifact holds derived numbers only.** A golden key set for the promoted file and
  its evidence: a raw click, gaze sample or screen coordinate cannot be added without this
  failing.

Hermetic: synthetic maps, ``tmp_path``, no camera, no desktop, no network.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from collections import deque
from pathlib import Path

import numpy as np
import pytest

from yazses.gaze.association import Association
from yazses.gaze.calibrate import CalibrationMap
from yazses.gaze.refine import (
    ImplicitRefiner,
    RefinementOutcome,
    RefinementPolicy,
    decide_promotion,
    routes_to_holdout,
)
from yazses.gaze.store import (
    SCHEMA_VERSION,
    CalibrationWriteError,
    RefinementInfo,
    calibration_path,
    calibration_state,
    load_calibration_record,
    previous_calibration_path,
    promote_refinement,
    rollback_calibration,
    save_calibration,
)
from yazses.gaze.topology import CalibrationContext, Display, DisplayTopology, Validity

IDENTITY = CalibrationMap(A=np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]))


def shifted(dx: float) -> CalibrationMap:
    return CalibrationMap(A=np.array([[1.0, 0.0, dx], [0.0, 1.0, 0.0]]))


#: Every held-out click is 4 px right of where the identity map puts the gaze, so the
#: baseline's mean error is exactly 4.0 and a map shifted by +3 has an error of exactly 1.0.
#: Small integers keep every error exact in float64, which is what lets the boundary tests
#: below test the boundary and not rounding.
HOLDOUT = [((float(i), float(-i)), (float(i) + 4.0, float(-i))) for i in range(10)]

POLICY = RefinementPolicy(min_train_samples=20, min_holdout_samples=8, min_improvement_px=1.0)


def context() -> CalibrationContext:
    topology = DisplayTopology(
        displays=(
            Display(identifier="eDP-1", x=0, y=0, width=1920, height=1080, scale=1.0, primary=True),
        )
    )
    return CalibrationContext(topology=topology, camera_id="0", camera_width=640, camera_height=480)


def info() -> RefinementInfo:
    return RefinementInfo(
        train_samples=60, holdout_samples=20, baseline_error_px=140.0, candidate_error_px=12.5
    )


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------- #
# The verdict is a pure function
# --------------------------------------------------------------------------- #


def test_the_verdict_depends_on_its_arguments_alone_and_modifies_none_of_them() -> None:
    baseline, candidate = IDENTITY, shifted(3.0)
    holdout = copy.deepcopy(HOLDOUT)
    a_base, a_cand = baseline.A.copy(), candidate.A.copy()

    first = decide_promotion(baseline, candidate, holdout, train_samples=30, policy=POLICY)
    second = decide_promotion(baseline, candidate, holdout, train_samples=30, policy=POLICY)

    assert first == second
    assert first.outcome is RefinementOutcome.APPLIED
    assert (first.baseline_error_px, first.candidate_error_px) == (4.0, 1.0)
    assert holdout == HOLDOUT, "the held-out pairs are evidence, not scratch space"
    assert np.array_equal(baseline.A, a_base) and np.array_equal(candidate.A, a_cand)


def test_any_sequence_of_held_out_pairs_gives_the_same_verdict() -> None:
    """The refiner keeps a bounded deque; the verdict must not depend on the container."""
    as_list = decide_promotion(IDENTITY, shifted(3.0), HOLDOUT, train_samples=30, policy=POLICY)
    as_tuple = decide_promotion(
        IDENTITY, shifted(3.0), tuple(HOLDOUT), train_samples=30, policy=POLICY
    )
    as_deque = decide_promotion(
        IDENTITY, shifted(3.0), deque(HOLDOUT, maxlen=50), train_samples=30, policy=POLICY
    )
    assert as_list == as_tuple == as_deque


@pytest.mark.parametrize(
    ("train", "held"),
    [(19, 10), (30, 7), (0, 0)],
    ids=["one-short-of-training", "one-short-of-held-out", "nothing"],
)
def test_too_little_evidence_is_named_and_carries_no_error_figures(train: int, held: int) -> None:
    result = decide_promotion(
        IDENTITY, shifted(3.0), HOLDOUT[:held], train_samples=train, policy=POLICY
    )
    assert result.outcome is RefinementOutcome.INSUFFICIENT_DATA
    # No figure rather than a made-up one: an error of 0.0 would read as a perfect map.
    assert result.baseline_error_px is None and result.candidate_error_px is None
    assert (result.train_samples, result.holdout_samples) == (train, held)


def test_an_improvement_of_exactly_the_margin_is_accepted() -> None:
    policy = RefinementPolicy(min_train_samples=20, min_holdout_samples=8, min_improvement_px=3.0)
    result = decide_promotion(IDENTITY, shifted(3.0), HOLDOUT, train_samples=30, policy=policy)
    assert result.baseline_error_px - result.candidate_error_px == 3.0
    assert result.outcome is RefinementOutcome.APPLIED


def test_an_improvement_one_ulp_short_of_the_margin_is_refused() -> None:
    margin = math.nextafter(3.0, math.inf)
    policy = RefinementPolicy(
        min_train_samples=20, min_holdout_samples=8, min_improvement_px=margin
    )
    result = decide_promotion(IDENTITY, shifted(3.0), HOLDOUT, train_samples=30, policy=policy)
    assert result.outcome is RefinementOutcome.KEPT_BASELINE
    assert (result.baseline_error_px, result.candidate_error_px) == (4.0, 1.0)


@pytest.mark.parametrize(
    "candidate",
    [
        IDENTITY,  # the very same object: the gate returns the baseline, which `is` it
        CalibrationMap(A=IDENTITY.A.copy()),  # the same numbers in a different object
        shifted(-2.0),  # worse: error 6 against 4
        shifted(8.0),  # worse the other way: error 4 -> 4, a tie at a distance
        CalibrationMap(A=np.array([[np.nan, 0.0, 0.0], [0.0, 1.0, 0.0]])),
        CalibrationMap(A=np.array([[np.inf, 0.0, 0.0], [0.0, 1.0, 0.0]])),
    ],
    ids=["same-object", "same-values", "worse", "tie-at-distance", "nan", "inf"],
)
def test_a_candidate_that_is_not_strictly_better_never_wins(candidate: CalibrationMap) -> None:
    result = decide_promotion(IDENTITY, candidate, HOLDOUT, train_samples=30, policy=POLICY)
    assert result.outcome is RefinementOutcome.KEPT_BASELINE


def test_a_nan_baseline_never_hands_the_candidate_a_win() -> None:
    broken = CalibrationMap(A=np.array([[np.nan, 0.0, 0.0], [0.0, 1.0, 0.0]]))
    result = decide_promotion(broken, shifted(3.0), HOLDOUT, train_samples=30, policy=POLICY)
    assert result.outcome is RefinementOutcome.KEPT_BASELINE


def test_the_refiner_reaches_the_verdict_the_pure_function_states() -> None:
    """The refiner adds side effects (confirm, persist, activate) and no second opinion.

    Two refiners fed the same stream must agree with each other, and a win must carry
    exactly the error figures of a pure verdict on the same baseline.
    """
    truth = shifted(40.0)
    stream = [
        Association(
            gaze=(float(i % 7) * 10.0, float(i % 5) * 10.0),
            click=truth.predict(float(i % 7) * 10.0, float(i % 5) * 10.0),
            confidence=0.9,
            lag_s=0.1,
        )
        for i in range(80)
    ]
    policy = RefinementPolicy(
        min_train_samples=20, min_holdout_samples=8, holdout_every=4, evaluate_every=1000
    )
    results = []
    for _ in range(2):
        saved: list = []
        r = ImplicitRefiner(IDENTITY, policy, persist=lambda c, res, s=saved: s.append(c))
        for pair in stream:
            r.observe(pair)
        results.append((r.evaluate(), saved))
    (first, saved_first), (second, _saved_second) = results
    assert first == second
    assert first.outcome is RefinementOutcome.APPLIED
    held = [(p.gaze, p.click) for i, p in enumerate(stream) if routes_to_holdout(i, 4)]
    pure = decide_promotion(
        IDENTITY, saved_first[0], held, train_samples=first.train_samples, policy=policy
    )
    assert pure == first


# --------------------------------------------------------------------------- #
# The split is a pure function of position
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("every", [2, 3, 4, 7])
def test_the_split_holds_out_exactly_one_in_n_by_position(every: int) -> None:
    flags = [routes_to_holdout(i, every) for i in range(every * 25)]
    assert sum(flags) == 25
    assert flags == [routes_to_holdout(i, every) for i in range(every * 25)]
    assert [i for i, f in enumerate(flags) if f][:3] == [every - 1, 2 * every - 1, 3 * every - 1]


@pytest.mark.parametrize(("index", "every"), [(0, 1), (0, 0), (-1, 4)])
def test_a_split_that_cannot_be_honest_is_refused(index: int, every: int) -> None:
    with pytest.raises(ValueError):
        routes_to_holdout(index, every)


# --------------------------------------------------------------------------- #
# The schema version is read, not just written
# --------------------------------------------------------------------------- #


def _rewrite(tmp_path: Path, **changes) -> dict:
    raw = json.loads(calibration_path(tmp_path).read_text(encoding="utf-8"))
    raw.update(changes)
    calibration_path(tmp_path).write_text(json.dumps(raw, indent=2), encoding="utf-8")
    return raw


def test_every_write_records_the_current_schema_version(tmp_path: Path) -> None:
    save_calibration(IDENTITY, tmp_path, context())
    record = load_calibration_record(tmp_path)
    assert record is not None and record.version == SCHEMA_VERSION
    promoted = promote_refinement(tmp_path, shifted(3.0), info())
    assert promoted.version == SCHEMA_VERSION


def test_a_file_without_a_version_reads_as_schema_1(tmp_path: Path) -> None:
    calibration_path(tmp_path).write_text(json.dumps({"A": IDENTITY.A.tolist()}), encoding="utf-8")
    record = load_calibration_record(tmp_path)
    assert record is not None and record.version == 1


@pytest.mark.parametrize("version", ["3", True, 0, -1, 2.5, 3.0, None, [3]])
def test_a_damaged_version_is_a_damaged_file_not_a_valid_one(tmp_path: Path, version) -> None:
    save_calibration(IDENTITY, tmp_path, context())
    _rewrite(tmp_path, version=version)
    assert load_calibration_record(tmp_path) is None
    cal, check = calibration_state(tmp_path, context())
    # #415: present and unreadable is STALE with a reason, never "never calibrated".
    assert cal is None and check.validity is Validity.STALE and "damaged" in check.reason


def test_a_file_from_a_newer_build_still_routes_but_is_never_rewritten(tmp_path: Path) -> None:
    save_calibration(IDENTITY, tmp_path, context())
    _rewrite(tmp_path, version=SCHEMA_VERSION + 1, field_from_the_future={"keep": "me"})
    before = sha(calibration_path(tmp_path))
    names = sorted(p.name for p in tmp_path.iterdir())

    cal, check = calibration_state(tmp_path, context())
    assert cal is not None and check.validity is Validity.VALID, check.reason

    with pytest.raises(CalibrationWriteError, match="newer YazSes"):
        promote_refinement(tmp_path, shifted(3.0), info())
    assert sha(calibration_path(tmp_path)) == before
    assert sorted(p.name for p in tmp_path.iterdir()) == names, "no rollback copy, no litter"


def test_rolling_back_to_a_newer_schema_copy_restores_its_bytes_exactly(tmp_path: Path) -> None:
    """Rollback copies bytes, so nothing a newer build wrote can be lost by it."""
    save_calibration(IDENTITY, tmp_path, context())
    promote_refinement(tmp_path, shifted(3.0), info())
    newer = json.loads(previous_calibration_path(tmp_path).read_text(encoding="utf-8"))
    newer["version"] = SCHEMA_VERSION + 1
    newer["field_from_the_future"] = 1
    previous_calibration_path(tmp_path).write_text(json.dumps(newer), encoding="utf-8")
    copy_bytes = previous_calibration_path(tmp_path).read_bytes()

    restored = rollback_calibration(tmp_path)

    assert restored is not None and restored.version == SCHEMA_VERSION + 1
    assert calibration_path(tmp_path).read_bytes() == copy_bytes


# --------------------------------------------------------------------------- #
# Derived numbers only: the golden schema
# --------------------------------------------------------------------------- #

#: The complete top-level key set of a stored calibration. Adding a key is a schema change:
#: bump SCHEMA_VERSION, check it against the privacy rule in
#: design/specs/eye-implicit-calibration.md (no raw samples, clicks, frames or screen
#: content), and update this set in the same change.
EXPLICIT_KEYS = {"version", "space", "source", "saved_at", "A", "context", "context_fingerprint"}
IMPLICIT_KEYS = EXPLICIT_KEYS | {"refinement"}
EVIDENCE_KEYS = {"train_samples", "holdout_samples", "baseline_error_px", "candidate_error_px"}


def test_the_promoted_artifact_holds_the_golden_keys_and_scalar_evidence_only(
    tmp_path: Path,
) -> None:
    save_calibration(IDENTITY, tmp_path, context())
    promote_refinement(tmp_path, shifted(3.0), info())

    live = json.loads(calibration_path(tmp_path).read_text(encoding="utf-8"))
    previous = json.loads(previous_calibration_path(tmp_path).read_text(encoding="utf-8"))

    assert set(live) == IMPLICIT_KEYS
    assert set(previous) == EXPLICIT_KEYS
    assert set(live["refinement"]) == EVIDENCE_KEYS
    for key, value in live["refinement"].items():
        # A list here would be a sample log; a string could be anything. Counts and errors.
        assert isinstance(value, (int, float)) and not isinstance(value, bool), key
    assert np.array(live["A"]).shape == (2, 3), "the map is six coefficients, nothing more"
    # The context is the screen layout and camera *geometry* -- no screen content.
    assert set(live["context"]) == set(context().as_dict())


def test_the_rollback_directory_never_holds_more_than_the_two_calibration_files(
    tmp_path: Path,
) -> None:
    save_calibration(IDENTITY, tmp_path, context())
    promote_refinement(tmp_path, shifted(3.0), info())
    promote_refinement(tmp_path, shifted(2.0), info())
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        [calibration_path(tmp_path).name, previous_calibration_path(tmp_path).name]
    ), "one level of history: no growing archive of past maps"
