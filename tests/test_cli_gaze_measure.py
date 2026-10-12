"""`yazses gaze measure`: a local session in, a validated privacy-safe report out (#399).

The report content is pinned in `test_gaze_field_report.py`; this file pins the command around
it — what it refuses before touching the camera, that it writes nothing when it must not, and
that the whole run is offline. The webcam, the desktop and the calibration prompts are faked the
way the neighbouring gaze CLI tests fake them, so the suite needs no camera, no X11 and no
network, and never touches the host's own calibration or data directory.
"""
from __future__ import annotations

import json
import socket
import types
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

import yazses.cli as cli
from yazses.config import Config
from yazses.eyeeval import LocalIdentifiers, Provenance, validate_result
from yazses.eyeeval.gaze_field import report_problems
from yazses.gaze.calibrate import CalibrationMap
from yazses.gaze.store import calibration_path, promote_refinement, save_calibration
from yazses.gaze.topology import CalibrationContext, Display, DisplayTopology

runner = CliRunner()

FAKE_MACHINE = Provenance(
    yazses_version="9.9.9", python_version="3.12.0", os_name="Ubuntu", os_version="24.04",
    kernel="6.8.0", arch="x86_64", cpu_model="Example CPU", logical_cpus=8, ram_gb=16.0,
    session_type="x11", displays=({"width_px": 1920, "height_px": 1080, "scale": 1.0},),
)
FAKE_IDS = LocalIdentifiers(hostname="thinkpad-of-someone", usernames=("evelyn",),
                            home_paths=("/home/evelyn",))


class Sample:
    def __init__(self, x, y, confidence):
        self.x, self.y, self.confidence = x, y, confidence


class FakeBackend:
    name = "mediapipe"

    def __init__(self, sample=None):
        self.sample = sample if sample is not None else Sample(960.0, 540.0, 0.9)
        self.closed = False

    def estimate_sample(self):
        return self.sample

    def close(self):
        self.closed = True


class FakeDesktop:
    def screen_size(self):
        return (1920, 1080)


def _config(*, enabled=True) -> Config:
    cfg = Config()
    cfg.gaze.enabled = enabled
    return cfg


def _context(width: int = 1920) -> CalibrationContext:
    topology = DisplayTopology(
        displays=(Display(identifier="eDP-1", x=0, y=0, width=width, height=1080, primary=True),)
    )
    return CalibrationContext(topology=topology, camera_id="0")


def _wire(monkeypatch, tmp_path: Path, *, enabled=True, desktop=True, backend="ok",
          current_width: int = 1920, calibrated: bool = True, ctx_saved: bool = True):
    monkeypatch.setattr(
        cli, "get_platform",
        lambda: types.SimpleNamespace(
            paths=types.SimpleNamespace(config_file=tmp_path / "config.toml", data_dir=tmp_path)
        ),
    )
    monkeypatch.setattr("yazses.config.load_config", lambda _p: _config(enabled=enabled))
    monkeypatch.setattr("yazses.gaze.desktop.build_desktop", lambda: FakeDesktop() if desktop else None)
    fake = FakeBackend()
    monkeypatch.setattr("yazses.gaze.factory.build_gaze", lambda _c: fake if backend == "ok" else None)
    monkeypatch.setattr(
        "yazses.gaze.display.current_context", lambda **_k: _context(current_width)
    )
    monkeypatch.setattr("yazses.eyeeval.collect_provenance", lambda: FAKE_MACHINE)
    monkeypatch.setattr("yazses.eyeeval.local_identifiers", lambda: FAKE_IDS)
    if calibrated:
        save_calibration(CalibrationMap(A=np.eye(2, 3)), tmp_path, _context() if ctx_saved else None)
    return fake


def _invoke(*args: str, out: Path):
    return runner.invoke(
        cli.app, ["gaze", "measure", "--camera-class", "integrated", "-o", str(out), *args],
        input="\n" * 200,
    )


def test_a_session_writes_a_valid_report_and_prints_a_summary(monkeypatch, tmp_path) -> None:
    backend = _wire(monkeypatch, tmp_path)
    out = tmp_path / "report.json"

    result = _invoke("--glasses", "glasses", "--lighting", "normal", "--camera-label", "Integrated 720p",
                     "--routing-attempts", "20", "--routing-fallbacks", "3", "--wrong-target", "2",
                     out=out)

    assert result.exit_code == 0, result.output
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert report_problems(doc) == []
    assert validate_result(doc) == []
    assert doc["metrics"]["calibration"]["validation_points"] == 9
    assert doc["metrics"]["routing"]["wrong_target_rate"] == pytest.approx(0.1)
    assert doc["metrics"]["environment"]["glasses"] == "glasses"
    assert "Gaze field measurement" in result.output
    assert "read it before you share it" in result.output
    assert backend.closed is True, "the camera must be released even on the happy path"


def test_nothing_in_the_file_or_the_screen_names_this_machine_or_person(monkeypatch, tmp_path) -> None:
    _wire(monkeypatch, tmp_path)
    out = tmp_path / "report.json"
    result = _invoke(out=out)
    assert result.exit_code == 0, result.output
    for text in (out.read_text(encoding="utf-8"), result.output):
        for needle in ("thinkpad-of-someone", "evelyn", "/home/"):
            assert needle not in text, f"{needle!r} leaked"


def test_rounds_multiply_the_validation_points_and_make_drift_blocks(monkeypatch, tmp_path) -> None:
    _wire(monkeypatch, tmp_path)
    out = tmp_path / "report.json"
    result = _invoke("--rounds", "2", "--interval-s", "0", "--block-s", "1", out=out)
    assert result.exit_code == 0, result.output
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["metrics"]["calibration"]["validation_points"] == 18
    assert doc["metrics"]["session"]["drift_blocks"], "the drift buckets must be reported"


def test_degrees_appear_only_when_the_geometry_was_supplied(monkeypatch, tmp_path) -> None:
    _wire(monkeypatch, tmp_path)
    plain, withgeo = tmp_path / "a.json", tmp_path / "b.json"
    _invoke(out=plain)
    _invoke("--screen-diagonal-in", "15.6", "--viewing-distance-cm", "60", out=withgeo)
    assert json.loads(plain.read_text(encoding="utf-8"))["metrics"]["calibration"]["error_deg_mean"]["value"] is None
    assert isinstance(json.loads(withgeo.read_text(encoding="utf-8"))["metrics"]["calibration"]["error_deg_mean"], float)


def test_a_session_where_no_face_was_ever_seen_is_still_a_valid_honest_report(monkeypatch, tmp_path) -> None:
    backend = _wire(monkeypatch, tmp_path)
    backend.sample = None
    out = tmp_path / "report.json"
    result = _invoke(out=out)
    assert result.exit_code == 0, result.output
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert report_problems(doc) == []
    assert doc["metrics"]["calibration"]["validation_points"] == 0
    assert doc["metrics"]["calibration"]["error_px_mean"]["reason"] == "not_measured"


# --------------------------------------------------------------------------- #
# Refusals: before the camera, and writing nothing
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("wire", "args", "needle"),
    [
        ({"enabled": False}, (), "features enable gaze"),
        ({"desktop": False}, (), "X11"),
        ({"calibrated": False}, (), "gaze calibrate"),
        ({"current_width": 2560}, (), "no longer matches this desktop"),
        ({"backend": "none"}, (), "deps are unavailable"),
        ({}, ("--study-mode", "research"), "--protocol-id"),
        ({}, ("--study-mode", "synthetic"), "community_qa or research"),
        ({}, ("--glasses", "monocle"), "glasses must be one of"),
        ({}, ("--camera-label", "me@example.com"), "camera_label"),
        ({}, ("--screen-diagonal-in", "15.6"), "--viewing-distance-cm"),
        ({}, ("--routing-attempts", "3", "--wrong-target", "9"), "cannot exceed attempts"),
    ],
)
def test_the_command_refuses_before_measuring_and_writes_no_file(
    monkeypatch, tmp_path, wire, args, needle
) -> None:
    backend = _wire(monkeypatch, tmp_path, **wire)
    out = tmp_path / "report.json"
    result = _invoke(*args, out=out)
    assert result.exit_code != 0
    assert needle in (result.output + (result.stderr if hasattr(result, "stderr") else "")), result.output
    assert not out.exists()
    assert backend.closed is False, "no camera was opened for a refusal"


def test_the_camera_class_is_required_and_never_guessed(monkeypatch, tmp_path) -> None:
    _wire(monkeypatch, tmp_path)
    result = runner.invoke(cli.app, ["gaze", "measure", "-o", str(tmp_path / "r.json")])
    assert result.exit_code == 2
    assert not (tmp_path / "r.json").exists()


def test_a_refinement_the_user_has_live_is_reported_as_the_calibration_source(monkeypatch, tmp_path) -> None:
    from yazses.gaze.store import RefinementInfo

    _wire(monkeypatch, tmp_path)
    promote_refinement(tmp_path, CalibrationMap(A=np.eye(2, 3)), RefinementInfo(60, 20, 140.0, 12.5))
    out = tmp_path / "report.json"
    assert _invoke(out=out).exit_code == 0
    cal = json.loads(out.read_text(encoding="utf-8"))["metrics"]["calibration"]
    assert cal["source"] == "implicit"
    assert cal["implicit_candidate_delta_px"] == pytest.approx(127.5)


def test_the_command_opens_no_network_socket(monkeypatch, tmp_path) -> None:
    def no_network(*_a, **_k):
        raise AssertionError("a network socket was opened by `gaze measure`")

    _wire(monkeypatch, tmp_path)
    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    assert _invoke(out=tmp_path / "r.json").exit_code == 0


def test_the_measured_calibration_file_is_never_modified(monkeypatch, tmp_path) -> None:
    """Measuring is read-only: nothing is re-fitted and nothing is saved."""
    _wire(monkeypatch, tmp_path)
    before = calibration_path(tmp_path).read_bytes()
    assert _invoke(out=tmp_path / "r.json").exit_code == 0
    assert calibration_path(tmp_path).read_bytes() == before
