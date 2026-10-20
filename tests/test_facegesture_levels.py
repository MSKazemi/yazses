"""Active/talk levels and the thresholds derived between them (pure) -- EYE-FACE-004.

The resting baseline cannot help when rest is already ~0: normalising by `1 - 0` changes nothing,
and the absolute `hold_threshold = 0.5` may sit above anything a given face produces. These pin
`facegesture/levels.py`: every empty and degenerate capture is defined, thresholds are derived
only when rest, active and (optionally) talk are separable by a margin, and a derived hold
threshold never falls into the speech range.

**Every number below is SYNTHETIC**, hand-written to exercise a branch. None is a measurement of
a face, and none of it is evidence that any fraction, margin or threshold is right for a person
(design/eye-control/ROADMAP.md P5.4). In particular nothing here is derived from the one live
trial that motivated the feature.
"""
from __future__ import annotations

import itertools
import json
import math

import pytest

from yazses.facegesture.calibration import Baseline, Reading
from yazses.facegesture.levels import (
    ACTIVE,
    DEFAULT_HOLD_FRACTION,
    DEFAULT_RELEASE_FRACTION,
    MAX_HOLD_FRACTION,
    MIN_HYSTERESIS,
    MIN_SPAN,
    REST_HOLD_SIGMAS,
    REST_RELEASE_SIGMAS,
    TALK,
    TALK_MARGIN,
    GestureLevels,
    LevelCapture,
    derive_thresholds,
    describe_reason,
    levels_path,
    load_levels,
    reset_levels,
    save_level,
    summarise_level,
)

NAN = float("nan")
INF = float("inf")


def frames(values, conf=0.9):
    return [Reading(v, conf) for v in values]


def rest(level=0.02, spread=0.005, gesture="jaw_open"):
    return Baseline(gesture, level, spread, 40)


def active(level=0.40, peak=0.55, gesture="jaw_open"):
    return LevelCapture(gesture, ACTIVE, level, peak, 60)


def talk(level=0.20, gesture="jaw_open"):
    return LevelCapture(gesture, TALK, level, level, 80)


# -- summarise_level: every empty / degenerate capture is defined ------------------------------


@pytest.mark.parametrize(
    ("readings", "kwargs", "reason"),
    [
        ([], {}, "no_frames"),
        ([Reading(None, None)] * 30, {}, "no_reading"),
        (frames([NAN] * 30), {}, "no_reading"),
        (frames([INF, -INF] * 15), {}, "no_reading"),
        (frames([0.4] * 30, conf=0.3), {"confidence_floor": 0.6}, "low_confidence"),
        ([Reading(0.4, None)] * 30, {"confidence_floor": 0.6}, "low_confidence"),
        (frames([0.4] * 14), {}, "too_few_samples"),
        (frames([0.4] * 29 + [NAN]), {"min_samples": 30}, "too_few_samples"),
        (frames([0.4] * 30), {"kind": "rest"}, "bad_kind"),
    ],
)
def test_every_degenerate_capture_returns_a_specific_reason_and_no_level(readings, kwargs, reason):
    kwargs = dict(kwargs)
    kind = kwargs.pop("kind", ACTIVE)
    result = summarise_level("jaw_open", kind, readings, **kwargs)
    assert result.capture is None and not result.ok
    assert result.reason == reason


def test_a_failed_capture_never_looks_like_a_zero_level():
    for readings in ([], frames([NAN] * 30), frames([0.0] * 5)):
        result = summarise_level("jaw_open", ACTIVE, readings)
        assert result.capture is None


def test_the_counts_say_what_was_dropped():
    readings = [Reading(None, None)] * 3 + frames([0.4] * 5, conf=0.1) + frames([0.5] * 20)
    result = summarise_level("jaw_open", ACTIVE, readings, confidence_floor=0.5)
    assert (result.total, result.kept) == (28, 20)
    assert (result.dropped_no_reading, result.dropped_low_confidence) == (3, 5)


def test_an_active_level_is_the_upper_quartile_not_the_mean_and_not_a_spike():
    ramp = [0.0, 0.1, 0.2] + [0.40] * 24 + [0.2, 0.1, 0.0]    # a hold with ramps at both ends
    spike = ramp + [1.0]
    base = summarise_level("jaw_open", ACTIVE, frames(ramp)).capture
    spiked = summarise_level("jaw_open", ACTIVE, frames(spike)).capture
    assert base is not None and spiked is not None
    assert base.level == pytest.approx(0.40)
    assert spiked.level == pytest.approx(0.40), "one spiked frame must not move the level"
    assert spiked.peak == 1.0 and spiked.samples == len(spike)


def test_a_talk_level_is_the_maximum_so_a_cough_makes_the_guard_stricter_not_looser():
    speech = [0.05, 0.12, 0.2] * 8
    clean = summarise_level("jaw_open", TALK, frames(speech)).capture
    coughed = summarise_level("jaw_open", TALK, frames([*speech, 0.45])).capture
    assert clean is not None and coughed is not None
    assert clean.level == pytest.approx(0.2)
    assert coughed.level == pytest.approx(0.45) and coughed.level >= clean.level


def test_scores_outside_the_unit_range_are_clamped_not_trusted():
    capture = summarise_level("jaw_open", ACTIVE, frames([1.4] * 20 + [-0.3] * 2)).capture
    assert capture is not None
    assert 0.0 <= capture.level <= capture.peak <= 1.0


def test_the_confidence_floor_applies_to_level_captures_like_it_does_at_run_time():
    mixed = frames([0.6] * 20, conf=0.9) + frames([0.0] * 40, conf=0.1)
    capture = summarise_level("jaw_open", ACTIVE, mixed, confidence_floor=0.5).capture
    assert capture is not None and capture.level == pytest.approx(0.6) and capture.samples == 20


# -- derive_thresholds: the happy path ------------------------------------------------------------


def test_thresholds_sit_between_rest_and_active_at_the_configured_fractions():
    d = derive_thresholds(rest(0.02), active(0.42))
    span = 0.40
    assert d.ok and d.reason == ""
    assert d.hold == pytest.approx(0.02 + DEFAULT_HOLD_FRACTION * span)
    assert d.release == pytest.approx(0.02 + DEFAULT_RELEASE_FRACTION * span)
    assert 0.02 < d.release < d.hold < 0.42


def test_the_fractions_are_honoured():
    d = derive_thresholds(rest(0.0, 0.0), active(0.50), hold_fraction=0.6, release_fraction=0.3)
    assert d.ok
    assert d.hold == pytest.approx(0.30) and d.release == pytest.approx(0.15)


def test_a_talk_level_below_the_midpoint_changes_nothing():
    plain = derive_thresholds(rest(), active())
    guarded = derive_thresholds(rest(), active(), talk(0.10))
    assert (guarded.hold, guarded.release) == (plain.hold, plain.release)
    assert guarded.raised_for_talk is False


def test_a_talk_level_above_the_midpoint_lifts_hold_to_clear_it():
    d = derive_thresholds(rest(), active(0.60), talk(0.35))
    assert d.ok and d.raised_for_talk
    assert d.hold == pytest.approx(0.35 + TALK_MARGIN)
    assert d.release < d.hold - MIN_HYSTERESIS + 1e-9


def test_a_derived_hold_never_falls_into_the_speech_range():
    """Sweep talk levels: whenever a derivation succeeds, hold clears speech by the margin."""
    ok_seen = refused_seen = 0
    for t in [i / 100 for i in range(0, 61, 2)]:
        d = derive_thresholds(rest(), active(0.45), talk(t))
        if d.ok:
            ok_seen += 1
            assert d.hold >= t + TALK_MARGIN - 1e-9, f"talk={t}"
        else:
            refused_seen += 1
            assert d.reason == "talk_reaches_active", f"talk={t} refused for {d.reason}"
    assert ok_seen and refused_seen, "the sweep must cross the boundary to prove anything"


def test_speech_that_overlaps_the_gesture_is_refused_with_that_reason_and_the_numbers():
    d = derive_thresholds(rest(), active(0.40), talk(0.38))
    assert not d.ok and (d.hold, d.release) == (None, None)
    assert d.reason == "talk_reaches_active"
    assert "overlaps your talking" in d.detail and "0.38" in d.detail


# -- derive_thresholds: refusals are specific -------------------------------------------------------


@pytest.mark.parametrize(
    ("args", "reason"),
    [
        ((None, active()), "no_rest"),
        ((rest(), None), "no_active"),
        ((rest(gesture="smile"), active()), "gesture_mismatch"),
        ((rest(), active(), talk(gesture="smile")), "gesture_mismatch"),
        ((rest(0.4), active(0.30)), "active_not_above_rest"),
        ((rest(0.3), active(0.30)), "active_not_above_rest"),
        ((rest(0.30), active(0.30 + MIN_SPAN - 0.01, 0.5)), "span_too_small"),
        ((rest(NAN), active()), "invalid_levels"),
        ((rest(0.1, INF), active()), "invalid_levels"),
        ((rest(1.5), active()), "invalid_levels"),
        ((rest(), LevelCapture("jaw_open", TALK, 0.4, 0.5, 9)), "invalid_levels"),
        ((rest(), active(), active()), "invalid_levels"),
    ],
)
def test_each_unseparable_or_malformed_input_is_refused_with_its_own_reason(args, reason):
    d = derive_thresholds(*args)
    assert not d.ok and (d.hold, d.release) == (None, None)
    assert d.reason == reason
    assert d.detail, "a refusal must say why in words"


@pytest.mark.parametrize(
    ("hold", "release"),
    [(0.3, 0.3), (0.2, 0.3), (0.0, 0.0), (0.5, 0.0), (0.5, -0.1), (NAN, 0.2), (0.5, NAN),
     (INF, 0.2), (MAX_HOLD_FRACTION + 0.05, 0.2), (1.0, 0.5)],
)
def test_nonsense_fractions_are_refused_rather_than_clamped(hold, release):
    d = derive_thresholds(rest(), active(), hold_fraction=hold, release_fraction=release)
    assert d.reason == "bad_fractions" and not d.ok


def test_a_noisy_resting_face_that_reaches_the_gesture_is_refused():
    # 3 sigma of rest noise lands above 0.8 of a small span: nowhere clear of rest to hold.
    d = derive_thresholds(rest(0.0, 0.05), active(0.18, 0.3))
    assert d.reason == "rest_noise_reaches_hold" and not d.ok


def test_the_resting_noise_lifts_hold_and_release_clear_of_rest():
    d = derive_thresholds(rest(0.0, 0.03), active(0.50))
    assert d.ok
    assert d.hold >= REST_HOLD_SIGMAS * 0.03 - 1e-9
    assert d.release >= REST_RELEASE_SIGMAS * 0.03 - 1e-9, "a relaxed face must fall below release"


def test_no_room_for_hysteresis_is_refused():
    d = derive_thresholds(rest(0.0, 0.018), active(0.10, 0.2))
    assert d.reason == "no_hysteresis_room"


def test_every_refusal_code_has_a_sentence():
    for reason in ("bad_fractions", "no_rest", "no_active", "gesture_mismatch", "invalid_levels",
                   "active_not_above_rest", "span_too_small", "rest_noise_reaches_hold",
                   "talk_reaches_active", "no_hysteresis_room"):
        assert describe_reason(reason) != reason
    assert describe_reason("something_new") == "something_new"


def test_derivation_is_total_and_its_successes_are_well_ordered():
    """A grid including NaN/inf/out-of-range: never raises; success implies 0 <= release < hold <= 1,
    release clear of rest noise, hold at least the hysteresis gap above release."""
    values = [0.0, 0.05, 0.3, 0.9, 1.0, NAN, INF, -0.2, 1.7]
    spreads = [0.0, 0.01, 0.05, NAN, -0.1]
    known = {"bad_fractions", "no_rest", "no_active", "gesture_mismatch", "invalid_levels",
             "active_not_above_rest", "span_too_small", "rest_noise_reaches_hold",
             "talk_reaches_active", "no_hysteresis_room"}
    ok = 0
    for r, sp, a, t in itertools.product(values, spreads, values, [None, *values]):
        base = Baseline("jaw_open", r, sp, 10)
        act = LevelCapture("jaw_open", ACTIVE, a, a, 10)
        tk = None if t is None else LevelCapture("jaw_open", TALK, t, t, 10)
        d = derive_thresholds(base, act, tk)
        if d.ok:
            ok += 1
            assert d.hold is not None and d.release is not None
            assert all(math.isfinite(x) for x in (d.hold, d.release))
            assert 0.0 <= d.release <= d.hold - MIN_HYSTERESIS + 1e-9 and d.hold <= 1.0
            assert d.release >= r + REST_RELEASE_SIGMAS * sp - 1e-9
            if t is not None:
                assert d.hold >= t + TALK_MARGIN - 1e-9
        else:
            assert d.reason in known, d.reason
    assert ok > 0


# -- persistence --------------------------------------------------------------------------------------


def test_levels_round_trip_and_keep_their_neighbours(tmp_path):
    path = levels_path(tmp_path)
    save_level(path, active(0.4, 0.5))
    save_level(path, talk(0.2))
    save_level(path, LevelCapture("smile", ACTIVE, 0.6, 0.7, 30))
    got = load_levels(path)
    assert set(got) == {"jaw_open", "smile"}
    assert got["jaw_open"] == GestureLevels(active=active(0.4, 0.5), talk=talk(0.2))
    assert got["smile"].talk is None


def test_saving_replaces_the_same_gesture_and_kind_only(tmp_path):
    path = levels_path(tmp_path)
    save_level(path, active(0.4, 0.5))
    save_level(path, talk(0.2))
    save_level(path, active(0.5, 0.6))
    got = load_levels(path)["jaw_open"]
    assert got.active.level == 0.5 and got.talk.level == 0.2


def test_only_derived_numbers_are_persisted(tmp_path):
    path = levels_path(tmp_path)
    save_level(path, active())
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert set(raw) == {"version", "levels"}
    assert set(raw["levels"][0]) == {"gesture", "kind", "level", "peak", "samples"}
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("content", ["", "not json", "[]", "{}", '{"levels": 3}', '{"levels": [1, "x"]}',
                                     '{"levels": [{"gesture": "jaw_open"}]}', "\x00\x01"])
def test_an_unreadable_levels_file_is_no_levels_never_an_exception(tmp_path, content):
    path = levels_path(tmp_path)
    path.write_text(content, encoding="utf-8")
    assert load_levels(path) == {}
    assert load_levels(tmp_path / "missing.json") == {}


def test_a_malformed_entry_does_not_discard_its_well_formed_neighbour(tmp_path):
    path = levels_path(tmp_path)
    good = active().to_dict()
    bad = {**active().to_dict(), "level": NAN}
    path.write_text(json.dumps({"version": 1, "levels": [bad, good, {"kind": "active"}]}), encoding="utf-8")
    assert load_levels(path)["jaw_open"].active == active()


@pytest.mark.parametrize(
    "mutate",
    [
        {"level": True}, {"level": "0.4"}, {"level": -0.1}, {"level": 1.2}, {"peak": 0.1},
        {"samples": 0}, {"samples": 2.5}, {"samples": True}, {"kind": "rest"}, {"gesture": ""},
        {"level": INF},
    ],
)
def test_from_dict_rejects_every_ill_formed_level(mutate):
    assert LevelCapture.from_dict({**active().to_dict(), **mutate}) is None


def test_reset_forgets_one_gesture_or_everything(tmp_path):
    path = levels_path(tmp_path)
    save_level(path, active())
    save_level(path, LevelCapture("smile", ACTIVE, 0.6, 0.7, 30))
    assert reset_levels(path, "smile") is True
    assert set(load_levels(path)) == {"jaw_open"}
    assert reset_levels(path, "smile") is False
    assert reset_levels(path, "jaw_open") is True and not path.exists()
    save_level(path, active())
    assert reset_levels(path) is True and not path.exists()
    assert reset_levels(path) is False
