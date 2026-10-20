"""Baseline and confidence reach the running switch, and the CLI that captures them (#406).

`tests/test_facegesture_calibration.py` proves the arithmetic; this proves the plumbing — config
-> backend -> detector, daemon -> stored baseline, and the `yazses facegesture` commands — all
with fakes. No camera is opened and no model is loaded.

The default-off direction is pinned too: an install that sets none of the new keys must behave
exactly as before, and a baseline file lying around must not change a switch that did not ask
for it.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

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
from yazses.platform import get_platform

runner = CliRunner()


class _Cat:
    def __init__(self, name, score):
        self.category_name, self.score = name, score


class _Cv2:
    COLOR_BGR2RGB = 0

    def cvtColor(self, frame, code):
        return frame


class _Mp:
    ImageFormat = type("F", (), {"SRGB": 0})

    def Image(self, image_format, data):
        return data


def _loop_events(cfg, scores, **backend_kwargs):
    """Run the real capture loop over ``scores`` of jawOpen and return the hold events."""
    frames = list(scores)
    current = [frames[0]]

    class _Landmarker:
        def detect(self, image):
            return type("R", (), {"face_blendshapes": [[_Cat("jawOpen", current[0])]]})

    events: list[str] = []
    backend = FaceGestureBackend(
        replace(cfg, fps=60), lambda n: events.append("start"), lambda: events.append("end"),
        **backend_kwargs,
    )

    class _Cap:
        def read(self):
            current[0] = frames.pop(0)
            if not frames:
                backend.stop()
            return True, object()

    backend._loop(_Landmarker(), _Cap(), _Cv2(), _Mp())
    return events


# -- defaults: an existing install is unchanged ------------------------------


def test_the_new_keys_are_dormant_by_default():
    cfg = FacegestureConfig()
    assert (cfg.use_baseline, cfg.confidence_floor, cfg.refractory_frames) == (False, 0.0, 0)


def test_a_stored_baseline_does_not_change_a_switch_that_did_not_ask_for_it():
    resting = [0.5, 0.52, 0.51, 0.5, 0.53, 0.5, 0.5, 0.5]
    baselines = {"jaw_open": Baseline("jaw_open", 0.5, 0.01, 30)}
    off = FacegestureConfig(enabled=True)
    assert _loop_events(off, resting, baselines=baselines) == _loop_events(off, resting)
    assert _loop_events(off, resting) == ["start"], "premise: absolute thresholds fire here"


def test_use_baseline_normalises_in_the_running_loop():
    resting = [0.5, 0.52, 0.51, 0.5, 0.53, 0.5, 0.5, 0.5]
    on = FacegestureConfig(enabled=True, use_baseline=True)
    baselines = {"jaw_open": Baseline("jaw_open", 0.5, 0.01, 30)}
    assert _loop_events(on, resting, baselines=baselines) == []
    assert _loop_events(on, resting + [0.97] * 4, baselines=baselines) == ["start"]


def test_use_baseline_without_a_stored_baseline_falls_back_and_says_so(caplog):
    on = FacegestureConfig(enabled=True, use_baseline=True)
    with caplog.at_level(logging.WARNING):
        backend = FaceGestureBackend(on, baselines={})
    assert backend._baseline is None
    assert "yazses facegesture calibrate" in caplog.text
    assert _loop_events(on, [0.9] * 4) == ["start"]


def test_a_baseline_for_another_gesture_is_not_applied():
    on = FacegestureConfig(enabled=True, use_baseline=True)
    assert FaceGestureBackend(on, baselines={"smile": Baseline("smile", 0.3, 0.0, 20)})._baseline is None


def test_an_unusable_stored_baseline_fails_closed_and_says_so(caplog):
    """A hand-edited level of 0.95 cannot be normalised; firing on it would hold the mic."""
    on = FacegestureConfig(enabled=True, use_baseline=True)
    with caplog.at_level(logging.WARNING):
        backend = FaceGestureBackend(on, baselines={"jaw_open": Baseline("jaw_open", 0.95, 0, 20)})
    assert "too little headroom" in caplog.text
    assert backend._switch.baseline_usable is False
    assert _loop_events(on, [1.0] * 6, baselines={"jaw_open": Baseline("jaw_open", 0.95, 0, 20)}) == []


def test_a_noisy_baseline_warns_that_the_resting_face_can_reach_the_threshold(caplog):
    on = FacegestureConfig(enabled=True, use_baseline=True)
    noisy = Baseline("jaw_open", 0.2, 0.2, 30)
    with caplog.at_level(logging.WARNING):
        FaceGestureBackend(on, baselines={"jaw_open": noisy})
    assert "too noisy" in caplog.text


# -- confidence on the capture path -----------------------------------------


def test_a_frame_with_a_face_reports_the_presence_bound_as_its_confidence():
    class _Landmarker:
        def detect(self, image):
            return type("R", (), {"face_blendshapes": [[_Cat("jawOpen", 0.7)]]})

    class _Cap:
        def read(self):
            return True, object()

    backend = FaceGestureBackend(FacegestureConfig())
    reading = backend._reading(_Landmarker(), _Cap(), _Cv2(), _Mp())
    assert reading == Reading(0.7, 0.5)


@pytest.mark.parametrize("shapes", [[], [[_Cat("browInnerUp", 0.9)]]])
def test_no_face_or_no_matching_category_is_a_reading_of_nothing(shapes):
    class _Landmarker:
        def detect(self, image):
            return type("R", (), {"face_blendshapes": shapes})

    class _Cap:
        def read(self):
            return True, object()

    reading = FaceGestureBackend(FacegestureConfig())._reading(_Landmarker(), _Cap(), _Cv2(), _Mp())
    assert reading == Reading(None, None)


def test_a_floor_this_camera_path_can_never_satisfy_is_called_out(caplog):
    with caplog.at_level(logging.WARNING):
        backend = FaceGestureBackend(FacegestureConfig(confidence_floor=0.8))
    assert "never fire" in caplog.text
    assert _loop_events(FacegestureConfig(confidence_floor=0.8), [0.9] * 6) == []
    assert backend._switch.thresholds  # constructed, not crashed


def test_a_floor_at_or_below_the_presence_bound_leaves_the_switch_working():
    assert _loop_events(FacegestureConfig(confidence_floor=0.5), [0.9] * 4) == ["start"]


def test_refractory_frames_reach_the_loop():
    bounce = [0.9] * 3 + [0.1] * 2 + [0.9] * 3
    assert _loop_events(FacegestureConfig(), bounce) == ["start", "end", "start"]
    assert _loop_events(FacegestureConfig(refractory_frames=4), bounce) == ["start", "end"]


# -- config validation -------------------------------------------------------


def test_configcheck_keeps_valid_values_and_repairs_a_negative_refractory():
    problems: list = []
    ok = build_section(
        FacegestureConfig,
        {"use_baseline": True, "confidence_floor": 0.4, "refractory_frames": 5},
        "facegesture", problems,
    )
    assert (ok.use_baseline, ok.confidence_floor, ok.refractory_frames) == (True, 0.4, 5)
    assert problems == []

    problems = []
    bad = build_section(FacegestureConfig, {"refractory_frames": -3}, "facegesture", problems)
    assert bad.refractory_frames == 0 and problems


# -- calibration capture ------------------------------------------------------


def test_collect_readings_samples_for_the_requested_time_and_survives_a_bad_frame():
    calls = []

    class _Landmarker:
        def detect(self, image):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("bad frame")
            return type("R", (), {"face_blendshapes": [[_Cat("jawOpen", 0.3)]]})

    class _Cap:
        def read(self):
            return True, object()

    slept: list[float] = []
    backend = FaceGestureBackend(replace(FacegestureConfig(), fps=10))
    got = backend.collect_readings(_Landmarker(), _Cap(), _Cv2(), _Mp(), 1.0, sleep=slept.append)
    assert len(got) == 10 and len(slept) == 10
    assert got[1] == Reading(None, None)
    assert got[0] == Reading(0.3, 0.5)


# -- the daemon loads a stored baseline only when asked ------------------------


def _daemon(tmp_path, **face):
    cfg = replace(Config(), facegesture=replace(FacegestureConfig(enabled=True), **face))
    d = Daemon(config=cfg, platform=get_platform())
    d._platform = SimpleNamespace(paths=SimpleNamespace(data_dir=tmp_path))
    return d


def test_the_daemon_hands_the_stored_baseline_to_the_backend_when_opted_in(tmp_path):
    save_baseline(baseline_path(tmp_path), Baseline("jaw_open", 0.4, 0.01, 30))
    d = _daemon(tmp_path, use_baseline=True)
    source = d._build_face_gesture_source(d._config)[0]
    assert source._baseline is not None and source._baseline.level == 0.4


def test_the_daemon_reads_no_baseline_file_when_not_opted_in(tmp_path, monkeypatch):
    save_baseline(baseline_path(tmp_path), Baseline("jaw_open", 0.4, 0.01, 30))
    import yazses.facegesture.calibration as cal

    def _boom(*a, **k):
        raise AssertionError("an install that did not opt in must not read the baseline file")

    monkeypatch.setattr(cal, "load_baselines", _boom)
    d = _daemon(tmp_path)
    assert d._build_face_gesture_source(d._config)[0]._baseline is None


# -- the CLI ------------------------------------------------------------------


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """A platform whose data and config dirs are tmp, so no command touches the host."""
    paths = SimpleNamespace(data_dir=tmp_path / "data", config_file=tmp_path / "config.toml")
    monkeypatch.setattr(cli, "get_platform", lambda: SimpleNamespace(paths=paths))
    return paths


def _fake_capture(monkeypatch, readings, *, landmarker=True, camera=True):
    closed = []

    class _Cap:
        def release(self):
            closed.append("cap")

    class _Lm:
        def close(self):
            closed.append("lm")

    monkeypatch.setattr(FaceGestureBackend, "_build_landmarker", lambda self: _Lm() if landmarker else None)
    monkeypatch.setattr(
        FaceGestureBackend, "_open_camera", lambda self: (_Cap(), object()) if camera else (None, None)
    )
    monkeypatch.setattr(FaceGestureBackend, "collect_readings", lambda self, *a, **k: list(readings))
    return closed


_REST = [Reading(s, 0.9) for s in [0.4, 0.42, 0.41, 0.4, 0.39] * 4]


def test_calibrate_stores_the_baseline_and_releases_the_camera(sandbox, monkeypatch):
    closed = _fake_capture(monkeypatch, _REST)
    r = runner.invoke(cli.app, ["facegesture", "calibrate", "--yes"])
    assert r.exit_code == 0, r.output
    stored = load_baselines(baseline_path(sandbox.data_dir))
    assert stored["jaw_open"].level == pytest.approx(0.4, abs=0.01)
    assert sorted(closed) == ["cap", "lm"]
    assert "use_baseline" in r.output


def test_calibrate_fails_and_stores_nothing_when_too_few_frames_had_a_face(sandbox, monkeypatch):
    _fake_capture(monkeypatch, [Reading(None, None)] * 30)
    r = runner.invoke(cli.app, ["facegesture", "calibrate", "--yes"])
    assert r.exit_code == 1
    assert "failed" in r.output.lower()
    assert load_baselines(baseline_path(sandbox.data_dir)) == {}


def test_calibrate_refuses_a_face_with_no_headroom(sandbox, monkeypatch):
    _fake_capture(monkeypatch, [Reading(0.9, 0.9)] * 30)
    r = runner.invoke(cli.app, ["facegesture", "calibrate", "--yes"])
    assert r.exit_code == 1
    assert "top of the range" in r.output
    assert load_baselines(baseline_path(sandbox.data_dir)) == {}


def test_calibrate_reports_a_missing_model_and_a_missing_camera(sandbox, monkeypatch):
    _fake_capture(monkeypatch, _REST, landmarker=False)
    assert runner.invoke(cli.app, ["facegesture", "calibrate", "--yes"]).exit_code == 1
    closed = _fake_capture(monkeypatch, _REST, camera=False)
    r = runner.invoke(cli.app, ["facegesture", "calibrate", "--yes"])
    assert r.exit_code == 1 and "camera" in r.output.lower()
    assert closed == ["lm"], "the model must be closed when the camera cannot be opened"


def test_calibrate_rejects_an_unknown_gesture_before_touching_the_camera(sandbox, monkeypatch):
    _fake_capture(monkeypatch, _REST)
    r = runner.invoke(cli.app, ["facegesture", "calibrate", "--gesture", "wink", "--yes"])
    assert r.exit_code == 1 and "Unknown gesture" in r.output


def test_calibrate_can_target_another_gesture(sandbox, monkeypatch):
    _fake_capture(monkeypatch, _REST)
    r = runner.invoke(cli.app, ["facegesture", "calibrate", "--gesture", "Brow_Raise", "--yes"])
    assert r.exit_code == 0, r.output
    assert set(load_baselines(baseline_path(sandbox.data_dir))) == {"brow_raise"}


def test_reset_forgets_the_baseline(sandbox, monkeypatch):
    _fake_capture(monkeypatch, _REST)
    runner.invoke(cli.app, ["facegesture", "calibrate", "--yes"])
    r = runner.invoke(cli.app, ["facegesture", "reset"])
    assert r.exit_code == 0 and "forgotten" in r.output
    assert load_baselines(baseline_path(sandbox.data_dir)) == {}
    assert "No stored baseline" in runner.invoke(cli.app, ["facegesture", "reset"]).output
