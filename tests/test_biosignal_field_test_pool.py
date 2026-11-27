"""The first-device reporting gaps of #889: ``field-test --cues``, the squeeze that cannot
fire, ``field-test-pool`` with the exact Poisson bound, and what ``monitor`` counts.

Everything runs on synthetic signal, hand-framed ThinkGear traces or hand-written result
files. Nothing opens hardware or the real data directory.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import typer.main
from typer.testing import CliRunner

import yazses.cli as cli
from tests.thinkgear_gate_trace import blink_counts, build_trace, trace_source
from yazses.biosignal import cli_impl, fieldtest
from yazses.biosignal.calibration import CalibrationProfile, default_profile_path, save_profile
from yazses.biosignal.cli_impl import (
    OK,
    UNUSABLE,
    ProtocolTooShort,
    Switches,
    run_field_test,
    run_field_test_pool,
    run_monitor,
)
from yazses.biosignal.sources import SyntheticSource
from yazses.biosignal.types import EventKind
from yazses.config import BiosignalConfig, Config

runner = CliRunner()
THINKGEAR = "thinkgear:/dev/fake-thinkgear"
BLINK_ONLY = Switches(emg=False, double_blink=True, jaw_clench=False)
EVERY = Switches(emg=True, double_blink=True, jaw_clench=True)


def _cfg(source: str, *, emg: bool = True, blink: bool = True, jaw: bool = False) -> Config:
    cfg = Config()
    cfg.biosignal = dataclasses.replace(BiosignalConfig(), enabled=True, source=source,
                                        emg=emg, double_blink=blink, jaw_clench=jaw)
    return cfg


# ---------------------------------------------------------------------------
# what the live ledger counts


def test_a_lone_blink_is_neither_an_event_nor_a_ledger_activation(tmp_path: Path) -> None:
    """#889 item 1: the double-blink switch never emits a single blink, so ``monitor``'s
    ``Measured:`` rate cannot include one."""
    src = SyntheticSource("eog", seed=3, duration=30.0, mains_uv=0.0)
    src.schedule_blink(16.0)                                   # on its own
    src.schedule_blink(22.0).schedule_blink(22.5)              # the deliberate pair
    pipeline, _parts, ledger = cli_impl._build_pipeline(
        Config().biosignal, src, BLINK_ONLY, tmp_path)
    kinds: list[EventKind] = []
    cli_impl._pump(src, pipeline, lambda _b, r: kinds.extend(e.kind for e in r.events))
    assert kinds == [EventKind.DOUBLE_BLINK]
    assert ledger.counts_by_kind() == {EventKind.DOUBLE_BLINK: (1, 0)}


# ---------------------------------------------------------------------------
# --cues


def test_cues_sets_the_count_and_lengthens_the_gesture_phase() -> None:
    (phase,) = [p for p in fieldtest.default_protocol(("double_blink",), cues=16)
                if p.expects_intent]
    assert phase.cues == 16 and len(phase.cue_offsets()) == 16
    assert phase.duration_s == pytest.approx(85.0)


def test_the_cli_option_matches_the_module_limits() -> None:
    group = typer.main.get_command(cli.app).commands["biosignal"]  # type: ignore[attr-defined]
    option = next(p for p in group.commands["field-test"].params if p.name == "cues")
    assert option.default == fieldtest.DEFAULT_CUES
    assert (option.type.min, option.type.max) == (fieldtest.MIN_CUES, fieldtest.MAX_CUES)


@pytest.mark.parametrize("switches", [BLINK_ONLY, EVERY], ids=["blink", "every"])
@pytest.mark.parametrize("cues", range(fieldtest.MIN_CUES, fieldtest.MAX_CUES + 1))
def test_every_cue_count_gives_a_session_at_the_default_and_the_named_minimum(
        cues: int, switches: Switches) -> None:
    """The shortest ``--minutes`` the refusal names must be one the session accepts."""
    with pytest.raises(ProtocolTooShort) as info:
        cli_impl._scaled_protocol(fieldtest, 0.01, switches, cues)
    minimum = info.value.minimum
    for minutes in (0.0, minimum):
        phases, _total, note = cli_impl._scaled_protocol(fieldtest, minutes, switches, cues)
        assert note == ""
        assert all(p.cues == cues for p in phases if p.expects_intent)
        fieldtest.FieldTestSession(None, lambda: None, protocol=phases)
    with pytest.raises(ProtocolTooShort):
        cli_impl._scaled_protocol(fieldtest, minimum - 0.01, switches, cues)


@pytest.mark.parametrize("cues", [0, 4, 101])
def test_run_field_test_refuses_cues_out_of_range_before_opening(
        cues: int, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    def _open(spec: str, realtime: bool = False) -> Any:
        raise AssertionError("the source must not be opened")

    monkeypatch.setattr(cli_impl, "_open", _open)
    assert run_field_test(_cfg("synthetic:eog"), tmp_path, cues=cues) == UNUSABLE
    assert "--cues must be between 5 and 100" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# the squeeze that cannot fire


def _capture_protocol(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Stop at the session constructor, keeping the protocol it was handed."""
    seen: list[Any] = []

    class Session:
        def __init__(self, source: Any, factory: Any, **kw: Any) -> None:
            seen.append(kw["protocol"])
            raise ValueError("stop here")

    monkeypatch.setattr(fieldtest, "FieldTestSession", Session)
    return seen


def _gestures(phases: Any) -> list[str]:
    return [p.name for p in phases if p.expects_intent]


def _thinkgear(_spec: str, realtime: bool = False) -> Any:
    return trace_source(build_trace(blink_counts((), 4.0)))


def _synthetic(spec: str, realtime: bool = False) -> Any:
    return SyntheticSource(spec.partition(":")[2], seed=3, duration=4.0, mains_uv=0.0)


@pytest.mark.parametrize(("spec", "opener", "why"), [
    (THINKGEAR, _thinkgear, "no muscle channel"),
    ("synthetic:eog", _synthetic, "no muscle channel"),
    ("synthetic:mixed", _synthetic, "without a usable calibration"),
])
def test_a_squeeze_that_cannot_fire_is_not_cued_and_says_why(
        spec: str, opener: Any, why: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    """``emg = true`` is the shipped default; its cues used to be guaranteed misses."""
    monkeypatch.setattr(cli_impl, "_open", opener)
    seen = _capture_protocol(monkeypatch)
    run_field_test(_cfg(spec), tmp_path, cues=16, as_json=True)
    assert len(seen) == 1
    assert _gestures(seen[0]) == ["gesture_double_blink"]
    assert [p.cues for p in seen[0] if p.expects_intent] == [16]
    err = capsys.readouterr().err
    assert "Muscle squeeze: not cued" in err and why in err


def test_a_calibrated_squeeze_is_still_cued(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    spec = "synthetic:emg"
    src = _synthetic(spec)
    save_profile(CalibrationProfile(
        created_at=datetime.now(UTC).isoformat(), board_id="synthetic",
        channels=tuple(c.name for c in src.channels),
        channel_kinds=tuple(c.kind.value for c in src.channels), fs=float(src.fs),
        baseline_rms=10.0, noise_floor=5.0, mvc_rms=400.0, light_rms=80.0,
        phases=("relax", "squeeze_hard")), default_profile_path(tmp_path))
    monkeypatch.setattr(cli_impl, "_open", _synthetic)
    seen = _capture_protocol(monkeypatch)
    run_field_test(_cfg(spec, blink=False), tmp_path, as_json=True)
    assert len(seen) == 1 and _gestures(seen[0]) == ["gesture_squeeze"]
    assert "not cued" not in capsys.readouterr().err


@pytest.mark.parametrize(("spec", "opener"), [
    (THINKGEAR, _thinkgear), ("synthetic:emg", _synthetic)])
def test_nothing_to_test_is_refused_rather_than_scored(
        spec: str, opener: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    """With no switch able to fire, zero phantoms would read as a quiet switch."""
    monkeypatch.setattr(cli_impl, "_open", opener)
    seen = _capture_protocol(monkeypatch)
    assert run_field_test(_cfg(spec, blink=False), tmp_path) == UNUSABLE
    assert seen == []
    assert "nothing to test" in capsys.readouterr().err


def test_monitor_does_not_ask_a_thinkgear_user_to_calibrate_a_squeeze(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli_impl, "_open", _thinkgear)
    run_monitor(_cfg(THINKGEAR), tmp_path)
    out = capsys.readouterr().out
    assert "Muscle squeeze: not available on this source" in out
    assert "off until you calibrate" not in out


# ---------------------------------------------------------------------------
# field-test-pool


def _result(*, phantoms: int = 0, usable_s: int = 120, hits: int = 8, scored: int = 8,
            trigger: str = "double_blink") -> dict[str, Any]:
    """A saved field-test result: one quiet phase and one gesture phase."""
    def phase(name: str, intent: bool, **kw: Any) -> dict[str, Any]:
        return {"name": name, "label": name, "expects_intent": intent, "planned_s": usable_s,
                "signal_s": usable_s, "usable_s": usable_s, "phantom_activations": 0, **kw}

    return {
        "schema": 1, "budget_per_hour": 6.0, "min_phase_s": 30.0, "trigger_kinds": [trigger],
        "phases": [
            phase("rest", False, phantom_activations=phantoms, workday_weight=1.0),
            phase("gesture_double_blink", True, cues_total=scored, cues_scored=scored,
                  hits=hits),
        ],
    }


def _write(path: Path, data: Any) -> str:
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return str(path)


def _phase(payload: dict[str, Any], name: str) -> dict[str, Any]:
    return next(p for p in payload["phases"] if p["name"] == name)


def test_one_result_shows_the_exact_bound_beside_the_approximation(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The numbers from #889: no phantom in 120 s is 89.9 per hour exactly, not 89.1."""
    assert run_field_test_pool([_write(tmp_path / "a.json", _result())], as_json=True) == OK
    rest = _phase(json.loads(capsys.readouterr().out), "rest")
    assert rest["phantom_exact_upper_per_hour"] == pytest.approx(89.87, abs=0.01)
    assert rest["phantom_upper_per_hour"] == pytest.approx(89.06, abs=0.01)


def test_two_results_add_up_and_the_bounds_are_recomputed(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    files = [_write(tmp_path / "a.json", _result()),
             _write(tmp_path / "b.json", _result(phantoms=1))]
    assert run_field_test_pool(files, as_json=True) == OK
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["sessions"] == 2
    rest = _phase(payload, "rest")
    assert (rest["usable_s"], rest["phantom_activations"]) == (240, 1)
    # one event: exact upper limit 4.744 events, over 240 s
    assert rest["phantom_exact_upper_per_hour"] == pytest.approx(4.7439 * 15.0, abs=0.01)
    gesture = _phase(payload, "gesture_double_blink")
    assert (gesture["hits"], gesture["cues_scored"]) == (16, 16)
    assert gesture["hit_ci"][0] >= 0.80                       # needs both sessions
    assert gesture["phantom_exact_upper_per_hour"] is None
    assert captured.err == ""


def test_the_pooled_output_is_itself_a_readable_result(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_field_test_pool([_write(tmp_path / "a.json", _result())], as_json=True) == OK
    payload = json.loads(capsys.readouterr().out)
    assert fieldtest.report_to_dict(fieldtest.report_from_dict(payload)) == payload


def test_the_text_output_names_the_exact_column_and_the_one_configuration_rule(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_field_test_pool([_write(tmp_path / "a.json", _result())]) == OK
    out = capsys.readouterr().out
    assert "exact 95% /h" in out and "89.9" in out
    assert "one configuration" in out


def test_the_same_file_twice_is_refused(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    name = _write(tmp_path / "a.json", _result())
    assert run_field_test_pool([name, str(tmp_path / "." / "a.json")]) == UNUSABLE
    captured = capsys.readouterr()
    assert "named twice" in captured.err and captured.out == ""


def test_identical_contents_are_pooled_with_a_warning(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    files = [_write(tmp_path / n, _result()) for n in ("a.json", "copy.json")]
    assert run_field_test_pool(files, as_json=True) == OK
    captured = capsys.readouterr()
    assert "identical contents" in captured.err
    assert json.loads(captured.out)["sessions"] == 2


def test_results_counting_different_triggers_are_not_pooled(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    files = [_write(tmp_path / "a.json", _result()),
             _write(tmp_path / "b.json", _result(trigger="jaw_clench"))]
    assert run_field_test_pool(files) == UNUSABLE
    assert "cannot be pooled" in capsys.readouterr().err


@pytest.mark.parametrize("content", [
    "not json",
    "[1, 2]",
    {"schema": 99},
    {"schema": 1},
    _result(phantoms=-1),
    _result(usable_s=-5),
    _result(hits=9, scored=8),
    json.dumps(_result()).replace('"usable_s": 120', '"usable_s": Infinity'),
    json.dumps(_result()).replace('"budget_per_hour": 6.0', '"budget_per_hour": NaN'),
], ids=["text", "list", "schema", "empty", "negative-count", "negative-time", "more-hits",
        "infinity", "nan-budget"])
def test_an_unusable_file_is_named_not_a_traceback(
        content: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    name = _write(tmp_path / "bad.json", content)
    assert run_field_test_pool([name]) == UNUSABLE
    assert "Cannot read" in capsys.readouterr().err


def test_a_missing_file_is_unusable(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_field_test_pool([str(tmp_path / "none.json")]) == UNUSABLE
    assert "Cannot read" in capsys.readouterr().err


def test_a_phase_with_no_exposure_never_gets_a_rate(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``min_phase_s = 0`` in a file used to divide by zero hours."""
    data = _result()
    data["min_phase_s"] = 0
    data["phases"][0]["usable_s"] = 0
    assert run_field_test_pool([_write(tmp_path / "a.json", data)], as_json=True) == OK
    assert _phase(json.loads(capsys.readouterr().out), "rest")["status"] == "inconclusive"


def test_pool_command_parses_its_arguments(tmp_path: Path) -> None:
    name = _write(tmp_path / "a.json", _result())
    result = runner.invoke(cli.app, ["biosignal", "field-test-pool", name, "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["sessions"] == 1
    assert runner.invoke(cli.app, ["biosignal", "field-test-pool"]).exit_code == 2
