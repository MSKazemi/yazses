"""Active/talk levels reach the running switch, and the CLI that captures them (EYE-FACE-004).

`tests/test_facegesture_levels.py` proves the arithmetic; this proves the plumbing -- config ->
backend -> detector, daemon -> stored levels, and `yazses facegesture calibrate --active/--talk` --
all with fakes. No camera is opened and no model is loaded.

The default-off direction is pinned: an install that does not set `use_active_levels` must behave
exactly as before, and levels lying around on disk must not change a switch that did not ask.

**Every number is SYNTHETIC** and exercises a branch; none is a measurement of a face and none is
evidence for a threshold (design/eye-control/ROADMAP.md P5.4).
"""
from __future__ import annotations

import logging
from dataclasses import replace
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from tests.test_facegesture_baseline_wiring import _loop_events
from yazses import cli
from yazses.config import Config, FacegestureConfig
from yazses.configcheck import build_section
from yazses.core.daemon import Daemon
from yazses.facegesture.backend import FaceGestureBackend
from yazses.facegesture.calibration import (
    Baseline,
    Reading,
    baseline_path,
    load_baselines,
    save_baseline,
)
from yazses.facegesture.levels import (
    ACTIVE,
    DEFAULT_HOLD_FRACTION,
    DEFAULT_RELEASE_FRACTION,
    TALK,
    GestureLevels,
    LevelCapture,
    levels_path,
    load_levels,
    save_level,
)
from yazses.platform import get_platform

runner = CliRunner()

# Synthetic: a person whose resting jaw is ~0 and whose deliberate hold tops out far below the
# shipped 0.5 hold threshold -- the situation the feature exists for, not a measurement of anyone.
REST = Baseline("jaw_open", 0.01, 0.004, 40)
ACT = LevelCapture("jaw_open", ACTIVE, 0.34, 0.40, 60)
TALK_LOW = LevelCapture("jaw_open", TALK, 0.12, 0.12, 80)
DEFAULT = FacegestureConfig(enabled=True)
ON = FacegestureConfig(enabled=True, use_active_levels=True)

OPEN_HOLD = [0.0, 0.3, 0.3, 0.3, 0.3, 0.3, 0.0, 0.0, 0.0]     # a deliberate open
SPEECH = [0.0, 0.1, 0.12, 0.05, 0.11, 0.08] * 4                 # speech under the talk peak


def levels(active=ACT, talk=None):
    return {"jaw_open": GestureLevels(active=active, talk=talk)}


# -- defaults: an existing install is unchanged ----------------------------------------------------------


def test_the_new_keys_are_dormant_by_default():
    cfg = FacegestureConfig()
    assert cfg.use_active_levels is False
    # The fractions are the parameter-free choices, and the config copy must not drift from them.
    assert (cfg.active_hold_fraction, cfg.active_release_fraction) == (
        DEFAULT_HOLD_FRACTION, DEFAULT_RELEASE_FRACTION)


def test_the_shipped_threshold_never_fires_on_the_low_gesture_premise():
    assert _loop_events(DEFAULT, OPEN_HOLD) == [], "premise: absolute 0.5 cannot see this gesture"


def test_levels_on_disk_do_not_change_a_switch_that_did_not_opt_in():
    kwargs = {"baselines": {"jaw_open": REST}, "levels": levels(talk=TALK_LOW)}
    assert _loop_events(DEFAULT, OPEN_HOLD, **kwargs) == _loop_events(DEFAULT, OPEN_HOLD)
    backend = FaceGestureBackend(DEFAULT, **kwargs)
    assert backend._switch.thresholds == (0.5, 0.35) and backend._derived == {}


# -- opted in: thresholds sit between the user's own levels ---------------------------------------------


def test_opted_in_the_derived_thresholds_replace_the_configured_ones():
    backend = FaceGestureBackend(ON, baselines={"jaw_open": REST}, levels=levels())
    hold, release = backend._switch.thresholds
    assert hold == pytest.approx(0.01 + DEFAULT_HOLD_FRACTION * (0.34 - 0.01))
    assert release == pytest.approx(0.01 + DEFAULT_RELEASE_FRACTION * (0.34 - 0.01))
    assert backend._derived["jaw_open"].ok
    assert backend._baseline is None, "the thresholds already sit between the user's own levels"


def test_opted_in_the_gesture_that_the_absolute_threshold_missed_now_fires():
    kwargs = {"baselines": {"jaw_open": REST}, "levels": levels()}
    assert _loop_events(ON, OPEN_HOLD, **kwargs) == ["start", "end"]


def test_speech_under_the_talk_level_does_not_fire_with_the_derived_thresholds():
    kwargs = {"baselines": {"jaw_open": REST}, "levels": levels(talk=TALK_LOW)}
    assert _loop_events(ON, SPEECH, **kwargs) == []
    assert _loop_events(ON, SPEECH + OPEN_HOLD, **kwargs) == ["start", "end"]


def test_the_talk_level_lifts_hold_above_speech_that_would_otherwise_have_started_it():
    loud = LevelCapture("jaw_open", TALK, 0.25, 0.25, 80)       # speech reaching 0.25
    speech_peak = [0.0, 0.24, 0.24, 0.24, 0.24, 0.0, 0.0]
    without = {"baselines": {"jaw_open": REST}, "levels": levels()}
    with_talk = {"baselines": {"jaw_open": REST}, "levels": levels(talk=loud)}
    assert _loop_events(ON, speech_peak, **without) == ["start", "end"], "premise: speech fires"
    assert _loop_events(ON, speech_peak, **with_talk) == [], "the talk guard keeps hold above it"


def test_use_active_levels_takes_precedence_over_use_baseline_for_that_gesture():
    both = replace(ON, use_baseline=True)
    backend = FaceGestureBackend(both, baselines={"jaw_open": REST}, levels=levels())
    assert backend._baseline is None and backend._derived


def test_each_watched_gesture_is_derived_from_its_own_levels():
    smile = LevelCapture("smile", ACTIVE, 0.70, 0.8, 50)
    cfg = replace(ON, switches=[{"gesture": "smile", "intent": "hold_to_command"}])
    backend = FaceGestureBackend(
        cfg,
        baselines={"jaw_open": REST, "smile": Baseline("smile", 0.05, 0.01, 40)},
        levels={"jaw_open": GestureLevels(active=ACT), "smile": GestureLevels(active=smile)},
        actions={"hold_to_command": SimpleNamespace(press=lambda: None, release=lambda: None)},
    )
    jaw = backend._switches["jaw_open"].thresholds
    smi = backend._switches["smile"].thresholds
    assert jaw != smi and smi[0] > jaw[0]


def test_the_configured_fractions_reach_the_derivation():
    cfg = replace(ON, active_hold_fraction=0.6, active_release_fraction=0.3)
    hold, release = FaceGestureBackend(cfg, baselines={"jaw_open": REST}, levels=levels())._switch.thresholds
    assert hold == pytest.approx(0.01 + 0.6 * 0.33) and release == pytest.approx(0.01 + 0.3 * 0.33)


# -- opted in but refused: configured thresholds stand, and the reason is logged ----------------------


@pytest.mark.parametrize(
    ("baselines", "lv", "reason"),
    [
        ({}, levels(), "no_rest"),
        ({"jaw_open": REST}, {}, "no_active"),
        ({"jaw_open": REST}, levels(LevelCapture("jaw_open", ACTIVE, 0.03, 0.05, 40)), "span_too_small"),
        ({"jaw_open": Baseline("jaw_open", 0.4, 0.01, 30)}, levels(), "active_not_above_rest"),
        ({"jaw_open": REST}, levels(talk=LevelCapture("jaw_open", TALK, 0.33, 0.4, 80)),
         "talk_reaches_active"),
    ],
)
def test_a_refused_derivation_falls_back_to_the_configured_thresholds_and_says_why(
    caplog, baselines, lv, reason
):
    with caplog.at_level(logging.WARNING):
        backend = FaceGestureBackend(ON, baselines=baselines, levels=lv)
    assert backend._switch.thresholds == (0.5, 0.35)
    assert backend._derived == {}
    assert reason in caplog.text and "calibrate --active" in caplog.text


def test_a_refused_derivation_still_honours_use_baseline_as_before():
    cfg = replace(ON, use_baseline=True)
    backend = FaceGestureBackend(cfg, baselines={"jaw_open": REST}, levels={})
    assert backend._baseline == REST, "falls back to exactly the baseline-normalised switch"


# -- config validation ---------------------------------------------------------------------------------------


def test_configcheck_keeps_valid_values():
    problems: list = []
    section = build_section(
        FacegestureConfig,
        {"use_active_levels": True, "active_hold_fraction": 0.6, "active_release_fraction": 0.2},
        "facegesture", problems,
    )
    assert (section.use_active_levels, section.active_hold_fraction, section.active_release_fraction) == (
        True, 0.6, 0.2)
    assert problems == []


# -- the daemon loads stored levels only when asked -------------------------------------------------------------


def _daemon(tmp_path, **face):
    cfg = replace(Config(), facegesture=replace(FacegestureConfig(enabled=True), **face))
    d = Daemon(config=cfg, platform=get_platform())
    d._platform = SimpleNamespace(paths=SimpleNamespace(data_dir=tmp_path))
    return d


def test_the_daemon_hands_stored_baseline_and_levels_to_the_backend_when_opted_in(tmp_path):
    save_baseline(baseline_path(tmp_path), REST)
    save_level(levels_path(tmp_path), ACT)
    d = _daemon(tmp_path, use_active_levels=True)
    source = d._build_face_gesture_source(d._config)[0]
    assert source._derived["jaw_open"].ok


def test_the_daemon_reads_no_levels_file_when_not_opted_in(tmp_path, monkeypatch):
    save_baseline(baseline_path(tmp_path), REST)
    save_level(levels_path(tmp_path), ACT)
    import yazses.facegesture.levels as lv

    def _boom(*a, **k):
        raise AssertionError("an install that did not opt in must not read the levels file")

    monkeypatch.setattr(lv, "load_levels", _boom)
    d = _daemon(tmp_path)
    assert d._build_face_gesture_source(d._config)[0]._derived == {}


# -- the CLI -----------------------------------------------------------------------------------------------------


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    paths = SimpleNamespace(data_dir=tmp_path / "data", config_file=tmp_path / "config.toml")
    monkeypatch.setattr(cli, "get_platform", lambda: SimpleNamespace(paths=paths))
    return paths


def _fake(monkeypatch, *, rest=None, lead=None, hold=None, talk=None, landmarker=True):
    """Fake the camera; ``collect_readings`` answers by the number of seconds asked for."""
    closed: list[str] = []
    asked: list[float] = []

    class _Cap:
        def release(self):
            closed.append("cap")

    class _Lm:
        def close(self):
            closed.append("lm")

    by_seconds = {
        4.0: rest, 1.0: lead if lead is not None else [Reading(0.1, 0.9)] * 10,
        2.0: hold, 8.0: talk,
    }

    def collect(self, landmarker_, cap, cv2, mp, seconds, sleep=None):
        asked.append(seconds)
        return list(by_seconds[seconds] or [])

    monkeypatch.setattr(FaceGestureBackend, "_build_landmarker", lambda self: _Lm() if landmarker else None)
    monkeypatch.setattr(FaceGestureBackend, "_open_camera", lambda self: (_Cap(), object()))
    monkeypatch.setattr(FaceGestureBackend, "collect_readings", collect)
    return closed, asked


_REST = [Reading(s, 0.9) for s in [0.01, 0.02, 0.01, 0.0, 0.01] * 6]
_HOLD = [Reading(s, 0.9) for s in [0.2, 0.34, 0.35, 0.34, 0.33] * 6]          # synthetic deliberate hold
_SPEECH = [Reading(s, 0.9) for s in [0.02, 0.1, 0.12, 0.08, 0.05] * 6]
_LOUD_SPEECH = [Reading(s, 0.9) for s in [0.02, 0.3, 0.33, 0.2, 0.05] * 6]


def test_the_default_invocation_is_unchanged_and_writes_no_levels(sandbox, monkeypatch):
    closed, asked = _fake(monkeypatch, rest=_REST)
    r = runner.invoke(cli.app, ["facegesture", "calibrate", "--yes"])
    assert r.exit_code == 0, r.output
    assert asked == [4.0], "only the resting capture"
    assert not levels_path(sandbox.data_dir).exists()
    assert "use_baseline" in r.output and "use_active_levels" not in r.output
    assert sorted(closed) == ["cap", "lm"]


def test_active_captures_the_deliberate_holds_after_the_resting_face(sandbox, monkeypatch):
    closed, asked = _fake(monkeypatch, rest=_REST, hold=_HOLD)
    r = runner.invoke(cli.app, ["facegesture", "calibrate", "--active", "--yes"])
    assert r.exit_code == 0, r.output
    assert asked == [4.0, 1.0, 2.0, 1.0, 2.0, 1.0, 2.0], "rest, then 3 x (lead-in, hold)"
    assert load_baselines(baseline_path(sandbox.data_dir))["jaw_open"].level == pytest.approx(0.01, abs=0.01)
    stored = load_levels(levels_path(sandbox.data_dir))["jaw_open"]
    assert stored.active is not None and stored.active.level == pytest.approx(0.34, abs=0.02)
    assert stored.talk is None
    assert "use_active_levels" in r.output and "Derived: hold" in r.output
    assert sorted(closed) == ["cap", "lm"]


def test_the_lead_in_frames_are_discarded_not_measured(sandbox, monkeypatch):
    _fake(monkeypatch, rest=_REST, hold=_HOLD, lead=[Reading(0.95, 0.9)] * 30)
    r = runner.invoke(cli.app, ["facegesture", "calibrate", "--active", "--yes"])
    assert r.exit_code == 0, r.output
    assert load_levels(levels_path(sandbox.data_dir))["jaw_open"].active.peak < 0.5


def test_holds_and_seconds_are_options(sandbox, monkeypatch):
    _, asked = _fake(monkeypatch, rest=_REST, hold=_HOLD)
    r = runner.invoke(cli.app, ["facegesture", "calibrate", "--active", "--holds", "2", "--yes"])
    assert r.exit_code == 0, r.output
    assert asked.count(2.0) == 2


def test_talk_adds_a_speech_level_and_the_derivation_stays_above_it(sandbox, monkeypatch):
    _fake(monkeypatch, rest=_REST, hold=_HOLD, talk=_SPEECH)
    r = runner.invoke(cli.app, ["facegesture", "calibrate", "--active", "--talk", "--yes"])
    assert r.exit_code == 0, r.output
    stored = load_levels(levels_path(sandbox.data_dir))["jaw_open"]
    assert stored.talk is not None and stored.talk.level == pytest.approx(0.12)
    assert "speech peak" in r.output


def test_an_active_gesture_that_does_not_clear_rest_is_refused_and_no_levels_are_saved(sandbox, monkeypatch):
    weak = [Reading(s, 0.9) for s in [0.02, 0.03, 0.04, 0.03, 0.02] * 6]
    _fake(monkeypatch, rest=_REST, hold=weak)
    r = runner.invoke(cli.app, ["facegesture", "calibrate", "--active", "--yes"])
    assert r.exit_code == 1
    assert "Cannot derive thresholds" in r.output and "jitter" in r.output
    assert not levels_path(sandbox.data_dir).exists()
    assert "jaw_open" in load_baselines(baseline_path(sandbox.data_dir)), "the resting baseline is kept"


def test_speech_that_overlaps_the_gesture_is_refused_and_says_so(sandbox, monkeypatch):
    _fake(monkeypatch, rest=_REST, hold=_HOLD, talk=_LOUD_SPEECH)
    r = runner.invoke(cli.app, ["facegesture", "calibrate", "--active", "--talk", "--yes"])
    assert r.exit_code == 1
    assert "overlaps your talking" in r.output
    assert not levels_path(sandbox.data_dir).exists()


@pytest.mark.parametrize("readings", [[], [Reading(None, None)] * 60, [Reading(0.3, 0.9)] * 4])
def test_an_active_capture_with_no_usable_frames_fails_with_the_reason(sandbox, monkeypatch, readings):
    _fake(monkeypatch, rest=_REST, hold=readings)
    r = runner.invoke(cli.app, ["facegesture", "calibrate", "--active", "--yes"])
    assert r.exit_code == 1 and "Active capture failed" in r.output
    assert not levels_path(sandbox.data_dir).exists()


def test_skip_rest_reuses_the_stored_baseline_and_captures_only_the_rest(sandbox, monkeypatch):
    save_baseline(baseline_path(sandbox.data_dir), REST)
    _, asked = _fake(monkeypatch, hold=_HOLD)
    r = runner.invoke(cli.app, ["facegesture", "calibrate", "--skip-rest", "--active", "--yes"])
    assert r.exit_code == 0, r.output
    assert 4.0 not in asked


def test_talk_alone_extends_the_stored_active_level(sandbox, monkeypatch):
    save_baseline(baseline_path(sandbox.data_dir), REST)
    save_level(levels_path(sandbox.data_dir), ACT)
    _fake(monkeypatch, talk=_SPEECH)
    r = runner.invoke(cli.app, ["facegesture", "calibrate", "--skip-rest", "--talk", "--yes"])
    assert r.exit_code == 0, r.output
    stored = load_levels(levels_path(sandbox.data_dir))["jaw_open"]
    assert stored.active == ACT and stored.talk is not None


@pytest.mark.parametrize(
    ("args", "seed", "needle"),
    [
        (["--skip-rest", "--yes"], {}, "nothing else to capture"),
        (["--skip-rest", "--active", "--yes"], {}, "stored resting baseline"),
        (["--talk", "--yes"], {}, "needs an active level"),
    ],
)
def test_impossible_flag_combinations_fail_before_the_camera_is_touched(
    sandbox, monkeypatch, args, seed, needle
):
    def _boom(self):
        raise AssertionError("the camera must not be opened for a request that cannot succeed")

    monkeypatch.setattr(FaceGestureBackend, "_build_landmarker", _boom)
    r = runner.invoke(cli.app, ["facegesture", "calibrate", *args])
    assert r.exit_code == 1 and needle in r.output


def test_reset_forgets_the_levels_too(sandbox, monkeypatch):
    _fake(monkeypatch, rest=_REST, hold=_HOLD)
    runner.invoke(cli.app, ["facegesture", "calibrate", "--active", "--yes"])
    assert levels_path(sandbox.data_dir).exists()
    r = runner.invoke(cli.app, ["facegesture", "reset"])
    assert r.exit_code == 0 and "forgotten" in r.output
    assert not levels_path(sandbox.data_dir).exists()
    assert load_baselines(baseline_path(sandbox.data_dir)) == {}


def test_reset_of_one_gesture_leaves_the_others_levels(sandbox):
    save_level(levels_path(sandbox.data_dir), ACT)
    save_level(levels_path(sandbox.data_dir), LevelCapture("smile", ACTIVE, 0.6, 0.7, 30))
    r = runner.invoke(cli.app, ["facegesture", "reset", "--gesture", "smile"])
    assert r.exit_code == 0 and "Active/talk levels forgotten" in r.output
    assert set(load_levels(levels_path(sandbox.data_dir))) == {"jaw_open"}


def test_the_help_documents_the_guided_steps():
    # Help is rendered with colour and a width taken from the terminal. On the FreeBSD CI leg the
    # option names arrived wrapped in escape codes, so a bare substring check failed there while
    # passing on Linux: ask for plain, wide output and normalise what is left.
    import re

    result = runner.invoke(
        cli.app,
        ["facegesture", "calibrate", "--help"],
        env={"NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "200"},
    )
    out = " ".join(re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", result.output).split())
    for needle in ("--active", "--talk", "--skip-rest", "--holds", "use_active_levels"):
        assert needle in out, (needle, out[:300])
