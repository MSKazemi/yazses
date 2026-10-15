"""The gaze field report against what real backends and real sessions do (#399 audit).

``test_gaze_field_report.py`` pins the schema; ``test_cli_gaze_measure.py`` pins the command.
Both drive a backend that is a fake written for this feature, so both share its blind spots.
Four things a fake hid:

* **A real backend without ``estimate_sample``.** The L2CS backend implements only the
  ``GazeBackend`` protocol's ``estimate()``; ``collect_validation`` called ``estimate_sample``
  unconditionally, so ``[gaze] backend = "l2cs"`` ended every session with an
  ``AttributeError`` after the tester had looked at every target.
* **A frame that is not a number.** One NaN coordinate or an out-of-range confidence raised
  out of the pass and lost the session (or, via NaN error, would have reached the report).
* **A session too small to mean anything** travelled as a report with plausible-looking
  numbers. The document now says so itself, in its own words.
* **A desktop that changes mid-session.** A pass can take minutes; reading the layout only
  at the start reports ``valid`` for numbers measured on two desktops.

The numeric streams are mechanism fixtures; they say nothing about how well anyone's eyes
track, and the sufficiency floors under test are provisional reporting floors, not results.
"""
from __future__ import annotations

import json
import math
import types
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

import yazses.cli as cli
from yazses.config import Config
from yazses.eyeeval import LocalIdentifiers, Provenance, privacy_problems
from yazses.eyeeval.gaze_field import (
    MIN_CONFIDENCE_SAMPLES,
    MIN_ROUTING_ATTEMPTS,
    MIN_VALIDATION_POINTS,
    CalibrationFacts,
    MeasurementSession,
    PointError,
    RoutingCounts,
    build_report,
    collect_validation,
    render_markdown,
    report_problems,
)
from yazses.gaze.calibrate import CalibrationMap
from yazses.gaze.store import save_calibration
from yazses.gaze.topology import CalibrationContext, Display, DisplayTopology

FAKE_MACHINE = Provenance(
    yazses_version="9.9.9", python_version="3.12.0", os_name="Ubuntu", os_version="24.04",
    kernel="6.8.0", arch="x86_64", cpu_model="Example CPU", logical_cpus=8, ram_gb=16.0,
    session_type="x11", displays=({"width_px": 1920, "height_px": 1080, "scale": 1.0},),
)
FAKE_IDS = LocalIdentifiers(hostname="thinkpad-of-someone", usernames=("evelyn",),
                            home_paths=("/home/evelyn",))
NOW = "2026-10-15T09:00:00+00:00"


class Identity:
    def predict(self, x, y):
        return x, y


class ProtocolOnlyBackend:
    """Exactly the surface ``GazeBackend`` promises and ``L2csGazeBackend`` implements."""

    name = "l2cs"

    def __init__(self, point=(100.0, 100.0)):
        self.point = point
        self.closed = False

    def estimate(self):
        return self.point

    def close(self):
        self.closed = True


class Sample:
    def __init__(self, x, y, confidence):
        self.x, self.y, self.confidence = x, y, confidence


class Scripted:
    def __init__(self, samples):
        self._samples = list(samples)

    def estimate_sample(self):
        return self._samples.pop(0) if self._samples else None


def report(session, routing=None, block_s=300.0):
    return build_report(
        provenance=FAKE_MACHINE, timestamp=NOW, session=session,
        calibration=CalibrationFacts(), routing=routing, block_s=block_s,
    )


# --------------------------------------------------------------------------- #
# A backend that has only estimate()
# --------------------------------------------------------------------------- #


def test_a_backend_with_only_estimate_completes_the_pass_with_points_and_no_confidence() -> None:
    session = MeasurementSession()
    backend = ProtocolOnlyBackend((100.0, 100.0))
    assert not hasattr(backend, "estimate_sample"), "premise: this is the L2CS shape"

    produced = collect_validation(
        backend, Identity(), [("a", (103, 104)), ("b", (100, 100))], lambda *_: None, session,
        lambda: 1.0, per_point=3,
    )

    assert produced == 2
    assert [round(p.error_px, 6) for p in session.points] == [5.0, 0.0]
    doc = report(session)
    assert report_problems(doc) == []
    confidence = doc["metrics"]["confidence"]
    assert confidence["samples"] == 0
    assert confidence["mean"] == {"value": None, "reason": "not_supported"}, (
        "no confidence was reported: that is 'not supported', not a mean of zero or one"
    )
    assert "no per-sample confidence" in " ".join(doc["metrics"]["sufficiency"]["statements"])


def test_a_backend_that_sees_no_face_through_estimate_makes_no_point() -> None:
    session = MeasurementSession()
    backend = ProtocolOnlyBackend(point=None)  # type: ignore[arg-type]
    assert collect_validation(
        backend, Identity(), [("a", (1, 1))], lambda *_: None, session, lambda: 0.0
    ) == 0
    assert session.points == ()


# --------------------------------------------------------------------------- #
# A frame that is not a number
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param(Sample(float("nan"), 100.0, 0.9), id="nan-x"),
        pytest.param(Sample(100.0, float("inf"), 0.9), id="inf-y"),
        pytest.param(Sample(100.0, 100.0, float("nan")), id="nan-confidence"),
        pytest.param(Sample(100.0, 100.0, 1.5), id="confidence-above-one"),
        pytest.param(Sample(100.0, 100.0, -0.1), id="confidence-below-zero"),
        pytest.param(Sample("x", 100.0, 0.9), id="not-a-number"),
    ],
)
def test_one_unusable_frame_is_skipped_and_the_pass_carries_on(bad) -> None:
    session = MeasurementSession()
    backend = Scripted([bad, Sample(100.0, 100.0, 0.8), Sample(100.0, 100.0, 0.6)])

    produced = collect_validation(
        backend, Identity(), [("a", (100, 100))], lambda *_: None, session, lambda: 0.0,
        per_point=3,
    )

    assert produced == 1
    assert session.points[0].error_px == 0.0
    assert session.confidence_samples == 2, "the bad frame's confidence must not be counted"
    assert report_problems(report(session)) == []


def test_a_calibration_that_predicts_nan_makes_no_point_instead_of_crashing() -> None:
    class Broken:
        def predict(self, x, y):
            return float("nan"), float("nan")

    session = MeasurementSession()
    produced = collect_validation(
        Scripted([Sample(1.0, 1.0, 0.9)]), Broken(), [("a", (1, 1))], lambda *_: None, session,
        lambda: 0.0, per_point=1,
    )
    assert produced == 0 and session.points == ()


# --------------------------------------------------------------------------- #
# Too little data says so, in the document
# --------------------------------------------------------------------------- #


def big_session() -> MeasurementSession:
    session = MeasurementSession()
    for i in range(MIN_CONFIDENCE_SAMPLES):
        session.record_confidence(0.5 + (i % 5) / 10)
    for i in range(MIN_VALIDATION_POINTS):
        session.record_point(PointError(t_s=10.0 * i, error_px=30.0 + i))
    session.record_point(PointError(t_s=700.0, error_px=45.0))
    return session


def test_an_empty_session_states_every_shortfall_and_none_of_it_as_a_zero() -> None:
    suff = report(MeasurementSession())["metrics"]["sufficiency"]
    assert suff["provisional"] is True
    assert suff["validation_points"] == {"n": 0, "minimum": MIN_VALIDATION_POINTS, "enough": False}
    assert suff["routing_attempts"]["n"] == {"value": None, "reason": "not_measured"}
    assert suff["routing_attempts"]["enough"] is False
    assert len(suff["statements"]) == 4
    assert all(isinstance(s, str) and s for s in suff["statements"])


def test_a_small_session_says_how_small_and_what_would_be_enough() -> None:
    session = MeasurementSession()
    session.record_point(PointError(t_s=1.0, error_px=12.0))
    session.record_confidence(0.9)
    text = " ".join(
        report(session, RoutingCounts(attempts=3))["metrics"]["sufficiency"]["statements"]
    )
    assert f"Only 1 validation point(s) (at least {MIN_VALIDATION_POINTS} wanted)" in text
    assert f"Only 1 confidence sample(s) (at least {MIN_CONFIDENCE_SAMPLES} wanted)" in text
    assert f"Only 3 routing attempt(s) (at least {MIN_ROUTING_ATTEMPTS} wanted)" in text
    assert "drift cannot be assessed" in text


def test_a_session_above_every_floor_has_no_shortfall_statement() -> None:
    doc = report(big_session(), RoutingCounts(attempts=MIN_ROUTING_ATTEMPTS))
    suff = doc["metrics"]["sufficiency"]
    assert suff["statements"] == []
    assert all(suff[k]["enough"] for k in
               ("validation_points", "confidence_samples", "routing_attempts", "drift_blocks"))
    assert report_problems(doc) == []


def test_the_floors_are_exact_one_below_is_not_enough_and_the_floor_is() -> None:
    def enough(points: int) -> bool:
        session = MeasurementSession()
        for i in range(points):
            session.record_point(PointError(t_s=float(i), error_px=1.0))
        return bool(report(session)["metrics"]["sufficiency"]["validation_points"]["enough"])

    assert (enough(MIN_VALIDATION_POINTS - 1), enough(MIN_VALIDATION_POINTS)) == (False, True)


def test_the_markdown_a_tester_pastes_carries_the_shortfall_in_plain_words() -> None:
    session = MeasurementSession()
    session.record_point(PointError(t_s=1.0, error_px=12.0))
    text = render_markdown(report(session))
    assert "Not enough data for a finding" in text
    assert "Only 1 validation point(s)" in text
    ok = render_markdown(report(big_session(), RoutingCounts(attempts=MIN_ROUTING_ATTEMPTS)))
    assert "Not enough data" not in ok and "above the provisional reporting floors" in ok


def test_a_report_that_claims_enough_while_its_numbers_say_otherwise_is_refused() -> None:
    doc = report(MeasurementSession())
    doc["metrics"]["sufficiency"]["validation_points"]["enough"] = True
    assert any("contradicts n and minimum" in p for p in report_problems(doc))


def test_a_sufficiency_n_that_disagrees_with_the_figure_it_summarises_is_refused() -> None:
    doc = report(big_session(), RoutingCounts(attempts=MIN_ROUTING_ATTEMPTS))
    doc["metrics"]["sufficiency"]["validation_points"]["n"] = 999
    assert any("does not match the figure" in p for p in report_problems(doc))


def test_a_report_without_the_sufficiency_group_is_refused_as_missing_fields() -> None:
    doc = report(MeasurementSession())
    del doc["metrics"]["sufficiency"]
    assert any("metrics.sufficiency" in p for p in report_problems(doc))


def test_the_sufficiency_sentences_carry_no_identifier_and_pass_the_privacy_sweep() -> None:
    doc = report(MeasurementSession(), RoutingCounts(attempts=1))
    assert privacy_problems(doc, FAKE_IDS) == []
    assert not math.isnan(sum(len(s) for s in doc["metrics"]["sufficiency"]["statements"]))


# --------------------------------------------------------------------------- #
# The command: an L2CS-shaped backend, and a desktop that changes mid-session
# --------------------------------------------------------------------------- #

runner = CliRunner()


class FakeDesktop:
    def screen_size(self):
        return (1920, 1080)


def _context(width: int = 1920) -> CalibrationContext:
    topology = DisplayTopology(
        displays=(Display(identifier="eDP-1", x=0, y=0, width=width, height=1080, primary=True),)
    )
    return CalibrationContext(topology=topology, camera_id="0", camera_width=640, camera_height=480)


def _wire(monkeypatch, tmp_path: Path, backend, contexts):
    """*contexts* is consumed one per ``current_context`` call; the last one repeats."""
    cfg = Config()
    cfg.gaze.enabled = True
    monkeypatch.setattr(
        cli, "get_platform",
        lambda: types.SimpleNamespace(
            paths=types.SimpleNamespace(config_file=tmp_path / "config.toml", data_dir=tmp_path)
        ),
    )
    monkeypatch.setattr("yazses.config.load_config", lambda _p: cfg)
    monkeypatch.setattr("yazses.gaze.desktop.build_desktop", lambda: FakeDesktop())
    monkeypatch.setattr("yazses.gaze.desktop.unavailable_reason", lambda: "pinned for the test")
    monkeypatch.setattr("yazses.gaze.factory.build_gaze", lambda _c: backend)
    queue = list(contexts)

    def read(**_k):
        return queue.pop(0) if len(queue) > 1 else queue[0]

    monkeypatch.setattr("yazses.gaze.display.current_context", read)
    monkeypatch.setattr("yazses.eyeeval.collect_provenance", lambda: FAKE_MACHINE)
    monkeypatch.setattr("yazses.eyeeval.local_identifiers", lambda: FAKE_IDS)
    save_calibration(CalibrationMap(A=np.eye(2, 3)), tmp_path, _context())


def _invoke(out: Path):
    return runner.invoke(
        cli.app, ["gaze", "measure", "--camera-class", "integrated", "-o", str(out)],
        input="\n" * 200,
    )


def test_the_command_runs_end_to_end_on_a_backend_with_only_estimate(monkeypatch, tmp_path) -> None:
    backend = ProtocolOnlyBackend((960.0, 540.0))
    _wire(monkeypatch, tmp_path, backend, [_context()])
    out = tmp_path / "report.json"

    result = _invoke(out)

    assert result.exit_code == 0, result.output
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert report_problems(doc) == []
    assert doc["metrics"]["calibration"]["validation_points"] == 9
    assert doc["metrics"]["confidence"]["mean"]["reason"] == "not_supported"
    assert backend.closed is True


def test_a_monitor_plugged_in_during_the_pass_writes_no_report(monkeypatch, tmp_path) -> None:
    # one read at the start, one after the pass: the second sees a different panel.
    backend = ProtocolOnlyBackend((960.0, 540.0))
    _wire(monkeypatch, tmp_path, backend, [_context(1920), _context(2560)])
    out = tmp_path / "report.json"

    result = _invoke(out)

    assert result.exit_code == 1
    assert "layout changed while you were measuring" in result.output
    assert not out.exists(), "numbers from two desktops must not be written as one report"
    assert backend.closed is True


def test_a_layout_that_cannot_be_read_at_the_end_is_reported_unverified_not_valid(
    monkeypatch, tmp_path
) -> None:
    unreadable = CalibrationContext(topology=DisplayTopology(), camera_id="0")
    backend = ProtocolOnlyBackend((960.0, 540.0))
    _wire(monkeypatch, tmp_path, backend, [_context(1920), unreadable])
    out = tmp_path / "report.json"

    assert _invoke(out).exit_code == 0

    cal = json.loads(out.read_text(encoding="utf-8"))["metrics"]["calibration"]
    assert cal["topology_validity"] == "unverified"


def test_an_unchanged_layout_throughout_is_reported_valid(monkeypatch, tmp_path) -> None:
    backend = ProtocolOnlyBackend((960.0, 540.0))
    _wire(monkeypatch, tmp_path, backend, [_context()])
    out = tmp_path / "report.json"
    assert _invoke(out).exit_code == 0
    cal = json.loads(out.read_text(encoding="utf-8"))["metrics"]["calibration"]
    assert cal["topology_validity"] == "valid"
