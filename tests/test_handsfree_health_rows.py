"""Every hands-free failure has to be readable off one screen — EYE-OBS-001 (#416).

The failure this covers is not a crash. A camera handed to a video call, a MediaPipe model
that never downloaded, a face switch whose signal died four seconds ago, a calibration
fitted on a monitor since unplugged: each ends as *nothing happens*, on the one input method
a hands-free user has. R-08 and R-19 in `design/eye-control/RISK_REGISTER.md` are these two,
and until something reported them there was no way to tell them apart from outside.

These are the rows, driven by fabricated facts: no camera, no daemon, no monitor. The four
properties worth more than any individual wording are held as sweeps over every row this
module can produce, because a per-case assertion cannot notice the case somebody adds next:

* nothing is reported at all on a default install;
* a row that cannot decide says **unknown**, and never something that reads as OK;
* an unknown does not move `doctor`'s verdict, or every Glance-Type user gets a permanent
  yellow warning about nothing (ADR-021: a guard is judged on how rarely it fires);
* no row is non-OK without saying why.
"""

from __future__ import annotations

import dataclasses

import pytest

from yazses.config import Config
from yazses.handsfree.observability import (
    DOCTOR_STATUS,
    PERCEPTION_RUNNING,
    PERCEPTION_STOPPED,
    HandsFreeFacts,
    Health,
    as_payload,
    doctor_rows,
    facts_from_payload,
    health_rows,
    render_status_lines,
)
from yazses.handsfree.probe import facts_from_config
from yazses.handsfree.safety import HandsFreeSafety, SafetyLimits

#: The registry answer, pinned rather than read: this file is about the rows, and a test
#: that reads `unwired_slugs()` would change meaning the day Head-Pointer is wired.
WIRED: frozenset[str] = frozenset()
UNWIRED_HEAD = frozenset({"headpointer"})


def _cfg(**features) -> Config:
    cfg = Config()
    for name, value in features.items():
        getattr(cfg, name).enabled = value
    return cfg


def _facts(cfg: Config, *, unwired: frozenset[str] = WIRED, **overrides) -> HandsFreeFacts:
    return dataclasses.replace(facts_from_config(cfg, unwired=unwired), **overrides)


def _all_row_sets() -> list[tuple[str, tuple]]:
    """One entry per interesting machine, for the sweeps. Names are for the failure text."""
    gate = HandsFreeSafety(("headpointer", "facegesture"),
                           limits=SafetyLimits(500.0), clock=lambda: 10_000.0)
    gate.sample("headpointer")
    gate.sample("facegesture")
    gate.resume()
    faulted = HandsFreeSafety(("facegesture",), limits=SafetyLimits(500.0),
                              clock=lambda: 10_000.0)
    faulted.sample("facegesture")
    faulted.resume()
    faulted.fault("facegesture", "the camera was taken by another application")
    every = _cfg(gaze=True, facegesture=True, headpointer=True)
    return [
        ("gaze only, nothing probed", health_rows(_facts(_cfg(gaze=True)))),
        ("gaze, camera blocked", health_rows(
            _facts(_cfg(gaze=True), camera_ready=False))),
        ("gaze, calibration stale", health_rows(_facts(
            _cfg(gaze=True), camera_ready=True,
            calibration_validity="stale", calibration_reason="a monitor changed"))),
        ("gaze, calibration unverified", health_rows(_facts(
            _cfg(gaze=True), camera_ready=True,
            calibration_validity="unverified", calibration_reason="layout unreadable"))),
        ("gaze, calibration missing", health_rows(_facts(
            _cfg(gaze=True), camera_ready=True, calibration_validity="missing",
            calibration_reason="nothing has been calibrated"))),
        ("head-pointer, unwired", health_rows(_facts(
            _cfg(headpointer=True), unwired=UNWIRED_HEAD, camera_ready=True))),
        ("head-pointer, wired, no signal state", health_rows(_facts(
            _cfg(headpointer=True), camera_ready=True))),
        ("face switch, camera stopped", health_rows(_facts(
            _cfg(facegesture=True), camera_ready=True,
            perception_state=PERCEPTION_STOPPED))),
        ("face switch, running, channel present", health_rows(_facts(
            _cfg(facegesture=True), camera_ready=True, perception_state=PERCEPTION_RUNNING,
            perception_channels=("face",), perception_age_ms=33.0,
            perception_consumers=1))),
        ("face switch, running, channel absent", health_rows(_facts(
            _cfg(facegesture=True), camera_ready=True, perception_state=PERCEPTION_RUNNING,
            perception_channels=()))),
        ("everything on, gate active", health_rows(_facts(
            _with_safety(every), camera_ready=True, unwired=UNWIRED_HEAD,
            safety=gate.status(at_ms=10_100.0)))),
        ("everything on, gate faulted", health_rows(_facts(
            _with_safety(every), camera_ready=True, unwired=UNWIRED_HEAD,
            safety=faulted.status(at_ms=10_100.0)))),
        ("pointer backend present", health_rows(_facts(
            _cfg(headpointer=True), camera_ready=True, pointer_backend="x11",
            pointer_relative=True, pointer_absolute=True, pointer_buttons=3))),
        ("pointer backend that cannot move", health_rows(_facts(
            _cfg(headpointer=True), camera_ready=True, pointer_backend="portal",
            pointer_relative=False, pointer_absolute=False))),
        ("safety on with no camera feature", health_rows(
            _facts(_with_safety(Config())))),
    ]


def _with_safety(cfg: Config) -> Config:
    cfg.handsfree_safety.enabled = True
    return cfg


# --- the contract that matters most: silence on an ordinary install -------------------


def test_a_default_install_reports_nothing_at_all() -> None:
    """The first acceptance criterion, and the reason this is not noise.

    Every camera capability ships off, so a hands-free block on a default install would be
    a paragraph about nothing on every `doctor` run ever printed — and a signal that fires
    when nothing is wrong is one people learn to skip past (ADR-v2-021).
    """
    facts = facts_from_config(Config(), unwired=WIRED)
    assert facts.features_requested == ()
    assert health_rows(facts) == ()
    assert doctor_rows(facts) == ()
    assert as_payload(facts) is None
    assert render_status_lines(as_payload(facts)) == []


def test_a_broken_config_reports_nothing_rather_than_crashing() -> None:
    """`doctor` runs with ``cfg = None`` when the config file will not parse."""
    facts = facts_from_config(None, unwired=WIRED)
    assert health_rows(facts) == ()


def test_the_row_set_is_not_empty_for_a_user_who_asked() -> None:
    """A guard over an empty collection passes on everything (see the memory hazard)."""
    for name, rows in _all_row_sets():
        assert rows, f"{name} produced no rows at all"


# --- unknown must be unknown ---------------------------------------------------------


def test_every_undecided_row_says_the_word_unknown() -> None:
    """A probe that cannot determine a state must not print a default that reads as OK."""
    for name, rows in _all_row_sets():
        for row in rows:
            if row.health is Health.UNKNOWN:
                assert "unknown" in row.reason.lower(), (
                    f"{name}: {row.label!r} is undecided and does not say so: {row.reason}"
                )


def test_an_unknown_row_does_not_turn_doctors_verdict_yellow() -> None:
    """The other half, and the one a well-meaning fix would break.

    `doctor`'s verdict counts WARN rows. Mapping "we could not tell" to WARN would put a
    permanent optional-warning line in front of every user who merely enabled Glance-Type
    and has nothing wrong with it, which is exactly the guard-that-always-fires failure
    ADR-021 rules out. SKIP is visible, is not green, and does not move the verdict.
    """
    assert DOCTOR_STATUS[Health.UNKNOWN] == "SKIP"
    assert DOCTOR_STATUS[Health.OK] == "OK"
    assert DOCTOR_STATUS[Health.DEGRADED] == "WARN"
    assert DOCTOR_STATUS[Health.FAULT] == "FAIL"
    rows = doctor_rows(_facts(_cfg(gaze=True), camera_ready=True,
                              calibration_validity="valid", calibration_reason="unchanged"))
    assert [status for _, status, _ in rows if status == "WARN"] == [], rows


def test_no_row_is_a_problem_without_saying_why() -> None:
    for name, rows in _all_row_sets():
        for row in rows:
            if row.health is Health.OK:
                continue
            assert row.reason.strip(), f"{name}: {row.label!r} is {row.health} with no reason"


def test_every_row_label_is_unique_within_one_report() -> None:
    """`doctor`'s output is what people paste into issues; two rows with one name make a
    report unanswerable (`tests/test_doctor_labels_are_unique.py` is the same defect)."""
    for name, rows in _all_row_sets():
        labels = [row.label for row in rows]
        assert len(labels) == len(set(labels)), f"{name} repeats a label: {labels}"


# --- the states the acceptance criteria name have to stay apart ------------------------


def test_a_blocked_camera_does_not_produce_a_second_camera_failure() -> None:
    """One cause, one failure. `doctor`'s Camera row already carries reason and fix."""
    rows = {r.label: r for r in health_rows(_facts(_cfg(gaze=True), camera_ready=False))}
    perception = rows["Hands-free perception"]
    assert perception.health is Health.DORMANT
    assert "camera is unavailable" in perception.reason
    assert "Camera row" in perception.remedy


def test_stale_tracking_is_not_confused_with_a_permission_failure() -> None:
    """The acceptance criterion in one assertion: the two words differ, and so do the fixes."""
    gate = HandsFreeSafety(("facegesture",), limits=SafetyLimits(500.0),
                           clock=lambda: 10_000.0)
    gate.sample("facegesture")
    gate.resume()
    stale = {r.label: r for r in health_rows(_facts(
        _with_safety(_cfg(facegesture=True)), camera_ready=True,
        safety=gate.status(at_ms=12_000.0)))}
    blocked = {r.label: r for r in health_rows(_facts(
        _with_safety(_cfg(facegesture=True)), camera_ready=False))}
    assert "stale" in stale["Face switch"].reason
    assert "2000 ms" in stale["Face switch"].reason, stale["Face switch"].reason
    assert "stale" not in blocked["Face switch"].reason
    assert "camera is unavailable" in blocked["Face switch"].reason


def test_a_faulted_source_names_the_fault_and_refuses_to_self_clear() -> None:
    gate = HandsFreeSafety(("facegesture",), limits=SafetyLimits(500.0),
                           clock=lambda: 10_000.0)
    gate.sample("facegesture")
    gate.resume()
    gate.fault("facegesture", "the camera was taken by another application")
    rows = {r.label: r for r in health_rows(_facts(
        _with_safety(_cfg(facegesture=True)), camera_ready=True,
        safety=gate.status(at_ms=10_050.0)))}
    assert rows["Face switch"].health is Health.FAULT
    assert "taken by another application" in rows["Face switch"].reason
    assert "re-arm" in rows["Face switch"].remedy
    assert rows["Hands-free safety"].health is Health.FAULT


def test_a_wired_and_an_unwired_consumer_read_differently() -> None:
    """`[headpointer] enabled = true` on a build that drives nothing must say so.

    The alternative is the failure the project's own feature registry calls the worst of
    the three: a capability reported as on, with no runtime path, and silence.
    """
    unwired = {r.label: r for r in health_rows(_facts(
        _cfg(headpointer=True), unwired=UNWIRED_HEAD, camera_ready=True))}
    wired = {r.label: r for r in health_rows(_facts(
        _cfg(headpointer=True), unwired=WIRED, camera_ready=True))}
    assert "no runtime path in this build drives it" in unwired["Head tracking"].reason
    assert unwired["Head tracking"].health is Health.DEGRADED
    assert "no runtime path" not in wired["Head tracking"].reason


def test_the_global_stop_is_reported_missing_only_for_a_continuous_consumer() -> None:
    """Glance-Type routes a dictation the user started; it moves nothing on its own, so a
    global-stop warning there would fire on somebody with nothing to stop."""
    gaze_only = {r.label for r in health_rows(_facts(_cfg(gaze=True), camera_ready=True))}
    assert "Hands-free safety" not in gaze_only
    with_pointer = {r.label: r for r in health_rows(_facts(
        _cfg(headpointer=True), unwired=UNWIRED_HEAD, camera_ready=True))}
    assert with_pointer["Hands-free safety"].health is Health.DEGRADED
    assert "handsfree_safety" in with_pointer["Hands-free safety"].remedy


def test_a_configured_watchdog_with_no_running_gate_is_unknown_not_fine() -> None:
    rows = {r.label: r for r in health_rows(_facts(_with_safety(_cfg(facegesture=True)),
                                                   camera_ready=True))}
    row = rows["Hands-free safety"]
    assert row.health is Health.UNKNOWN
    assert "500 ms" in row.reason, row.reason
    assert "yazses status" in row.remedy


def test_channels_not_tracked_is_not_reported_as_no_face_detected() -> None:
    """``None`` and ``()`` are different facts, and collapsing them accuses the user's face.

    A build that does not track per-channel state must not tell somebody their face is not
    being detected — that sends them to fix the lighting in a room that is fine.
    """
    untracked = {r.label: r for r in health_rows(_facts(
        _cfg(facegesture=True), camera_ready=True, perception_state=PERCEPTION_RUNNING,
        perception_channels=None))}
    none_derived = {r.label: r for r in health_rows(_facts(
        _cfg(facegesture=True), camera_ready=True, perception_state=PERCEPTION_RUNNING,
        perception_channels=()))}
    assert untracked["Face switch"].health is Health.UNKNOWN
    assert "no face" not in untracked["Hands-free perception"].reason
    assert none_derived["Face switch"].health is Health.DEGRADED
    assert "no face in view" in none_derived["Hands-free perception"].reason


def test_the_pointer_backend_is_named_when_known_and_unknown_when_not() -> None:
    unknown = {r.label: r for r in health_rows(_facts(
        _cfg(headpointer=True), camera_ready=True))}
    assert unknown["Pointer output"].health is Health.UNKNOWN
    named = {r.label: r for r in health_rows(_facts(
        _cfg(headpointer=True), camera_ready=True, pointer_backend="x11",
        pointer_relative=True, pointer_absolute=True, pointer_buttons=3))}
    assert named["Pointer output"].health is Health.OK
    assert "x11" in named["Pointer output"].reason
    assert "3 button(s)" in named["Pointer output"].reason


def test_a_pointer_backend_that_cannot_move_is_not_reported_as_working() -> None:
    rows = {r.label: r for r in health_rows(_facts(
        _cfg(headpointer=True), camera_ready=True, pointer_backend="portal",
        pointer_relative=False, pointer_absolute=False))}
    assert rows["Pointer output"].health is Health.DEGRADED


def test_the_calibration_row_only_appears_for_gaze_and_only_when_checked() -> None:
    assert "Gaze calibration" not in {
        r.label for r in health_rows(_facts(_cfg(gaze=True), camera_ready=True))
    }
    assert "Gaze calibration" not in {
        r.label for r in health_rows(_facts(_cfg(facegesture=True), camera_ready=True,
                                            calibration_validity="valid"))
    }


# --- the wire ------------------------------------------------------------------------


def test_the_payload_round_trips_through_json() -> None:
    import json

    gate = HandsFreeSafety(("facegesture",), limits=SafetyLimits(500.0),
                           clock=lambda: 10_000.0)
    gate.sample("facegesture")
    gate.resume()
    facts = _facts(_with_safety(_cfg(gaze=True, facegesture=True)), camera_ready=True,
                   perception_state=PERCEPTION_RUNNING, perception_channels=("gaze", "face"),
                   perception_age_ms=41.0, perception_consumers=2,
                   safety=gate.status(at_ms=10_030.0))
    payload = as_payload(facts)
    assert payload is not None
    restored = facts_from_payload(json.loads(json.dumps(payload)))
    assert restored == facts


def test_an_older_daemon_payload_degrades_to_not_determined() -> None:
    """Absent keys must read as "we do not know", never as good news."""
    restored = facts_from_payload({"features_requested": ["gaze"]})
    assert restored is not None
    assert restored.camera_ready is None
    assert restored.perception_channels is None
    assert restored.safety is None
    rows = {r.label: r for r in health_rows(restored)}
    assert rows["Hands-free perception"].health is Health.UNKNOWN


@pytest.mark.parametrize("junk", [
    {"features_requested": ["gaze"], "safety": "not a mapping"},
    {"features_requested": ["gaze"], "safety": {"state": "exploded"}},
    {"features_requested": ["gaze"], "perception_age_ms": "soon"},
    {"features_requested": ["gaze"], "perception_consumers": None},
    {"features_requested": ["gaze"], "perception_channels": "face"},
    {"features_requested": "gaze"},
])
def test_a_malformed_payload_never_raises(junk) -> None:
    """A `status` that tracebacks against a running daemon is worse than a missing line."""
    facts = facts_from_payload(junk)
    assert facts is not None
    assert render_status_lines(junk) is not None


def test_a_status_line_never_says_the_same_word_twice() -> None:
    """It did: the health value was prefixed onto a reason that already opened with it,
    and `unknown — unknown — ...` reads as a bug in the tool, not a fact about the box."""
    lines = render_status_lines(as_payload(_facts(_cfg(gaze=True), camera_ready=True)))
    assert lines
    for line in lines:
        assert "unknown — unknown" not in line, line
