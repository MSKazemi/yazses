"""Local ThinkGear health diagnostics, and what a shareable result may hold (#831).

``check-source`` says what a run saw of the protocol, ``monitor`` says which gate holds
events, ``doctor`` says it opens nothing, and a field-test result holds counts and
durations only (TG-17). Everything runs on hand-framed fake serial bytes
(``tests/thinkgear_gate_trace.py``) and generated signals: no device, recording or network.
"""

from __future__ import annotations

import dataclasses
import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.thinkgear_gate_trace import (
    FakeClock,
    TraceSerial,
    bad_checksum_raw,
    blink_counts,
    build_trace,
    quality,
)
from yazses.biosignal import cli_impl, fieldtest
from yazses.biosignal.calibration import CalibrationProfile, default_profile_path, save_profile
from yazses.biosignal.cli_impl import (
    OK,
    calibration_spec,
    run_check_source,
    run_doctor,
    run_field_test,
    run_monitor,
)
from yazses.biosignal.sources import SyntheticSource
from yazses.biosignal.thinkgear import ThinkGearSource
from yazses.biosignal.thinkgear_health import (
    HealthReason,
    PacketReport,
    ProtocolHealth,
    ThinkGearHealth,
)
from yazses.biosignal.types import ChannelInfo, SampleBlock, SignalKind
from yazses.config import BiosignalConfig, Config

#: A port name that must never reach a health summary or a shareable result.
PORT = "/dev/rfcomm-private7"
SPEC = f"thinkgear:{PORT}"


def _cfg(source: str = SPEC, **over: Any) -> Config:
    cfg = Config()
    over.setdefault("double_blink", True)
    cfg.biosignal = dataclasses.replace(BiosignalConfig(), enabled=True, source=source, **over)
    return cfg


def _port_source(trace: Any) -> ThinkGearSource:
    clock = FakeClock()
    return ThinkGearSource(PORT, serial_factory=lambda: TraceSerial(trace, clock), clock=clock)


def _contact_trace(duration: float = 8.0) -> Any:
    """Good contact, except one "no skin contact" report at 3 s."""
    return build_trace(blink_counts((), duration),
                       contact=lambda second: 200 if second == 3 else 0)


def _gone() -> ThinkGearSource:
    def refuse() -> Any:
        raise OSError("no such port")

    return ThinkGearSource(PORT, serial_factory=refuse)


# ---------------------------------------------------------------- the tally (pure)


def _health(machine: ThinkGearHealth) -> ProtocolHealth:
    return ProtocolHealth(machine.tally)


def test_every_reason_has_a_category_and_only_trusted_has_none() -> None:
    for reason in HealthReason:
        assert bool(reason.category()) is (reason is not HealthReason.TRUSTED), reason
    assert HealthReason.UNKNOWN_CONTACT.category() == "contact unknown"
    assert HealthReason.CONTACT_STALE.category() == "contact stale"
    assert HealthReason.NO_CONTACT.category() == "contact contaminated"
    assert HealthReason.CORRUPT_PACKET.category() == "corrupt framing"
    assert HealthReason.TRANSPORT_STALLED.category() == "stream integrity failure"


def test_tally_counts_reports_in_three_bins_and_holds_the_read() -> None:
    machine = ThinkGearHealth()
    machine.observe_batch(
        1.0, [PacketReport(0, 0), PacketReport(0, 26), PacketReport(0, 200)], 0, 0)
    t = machine.tally
    assert (t.zero_reports, t.contaminated_reports, t.no_contact_reports) == (1, 1, 1)
    assert (t.reads, t.trusted_reads) == (1, 0)
    assert t.held_reads == {"no_contact": 1} and t.trust_breaks == {"no_contact": 1}
    assert _health(machine).result == "never_trusted"


def test_a_stream_without_contact_reports_is_unqualified() -> None:
    machine = ThinkGearHealth()
    for i in range(5):
        machine.observe_batch(float(i), [PacketReport(512, None)], 0, 0)
    health = _health(machine)
    assert health.result == "no_contact_report"
    assert health.tally.longest_report_gap_s == pytest.approx(4.0)
    text = "\n".join(health.lines())
    assert "none seen" in text and "UNQUALIFIED" in text


def test_trusted_reads_are_counted_and_the_result_stays_protocol_only() -> None:
    machine = ThinkGearHealth()
    machine.observe_batch(0.0, [PacketReport(0, 0), PacketReport(512, None)], 0, 0)
    machine.observe_batch(1.0, [PacketReport(0, 0), PacketReport(512, None)], 0, 0)
    assert machine.observe_batch(2.0, [PacketReport(512, 0)], 0, 0).trusted
    health = _health(machine)
    assert health.result == "trusted_reads_seen"
    assert (health.tally.reads, health.tally.trusted_reads) == (3, 1)
    text = "\n".join(health.lines())
    assert "latest verdict: trusted" in text and "covers the protocol only" in text
    assert "not evidence of a usable waveform" in text


def test_a_report_going_stale_on_an_idle_read_is_recorded() -> None:
    machine = ThinkGearHealth()
    machine.observe_batch(0.0, [PacketReport(1, 0)], 0, 0)
    machine.observe_idle(4.0)
    assert machine.tally.trust_breaks == {"contact_stale": 1}
    assert machine.tally.last_reason == "contact_stale" and not machine.tally.last_trusted
    assert machine.tally.longest_report_gap_s == pytest.approx(4.0)
    assert machine.tally.reads == 1                      # an empty read is not a read


def test_a_clock_that_goes_back_or_is_not_finite_adds_no_gap() -> None:
    machine = ThinkGearHealth()
    machine.observe_batch(10.0, [PacketReport(1, 0)], 0, 0)
    machine.observe_batch(2.0, [PacketReport(1, 0)], 0, 0)
    machine.observe_idle(float("nan"))
    assert machine.tally.longest_report_gap_s == 0.0


def test_rejected_packets_make_the_lost_sample_count_unknown() -> None:
    machine = ThinkGearHealth()
    assert ProtocolHealth(machine.tally).as_dict()["lost_samples"] == "none detected"
    machine.observe_batch(0.0, [], 2, 5)
    health = ProtocolHealth(machine.tally, bad_checksum=2)
    out = health.as_dict()
    assert (out["rejected_packets"], out["skipped_bytes"]) == (2, 5)
    assert out["lost_samples"] == "unknown"
    assert "lost samples: unknown" in "\n".join(health.lines())


def test_stop_keeps_the_tally_and_a_new_session_clears_it() -> None:
    machine = ThinkGearHealth()
    machine.observe_batch(0.0, [PacketReport(1, 0)], 0, 0)
    machine.invalidate()
    assert machine.tally.reads == 1
    machine.reset()
    assert machine.tally.reads == 0
    assert ProtocolHealth(machine.tally).result == "not_observed"


def test_the_summary_has_a_fixed_schema_of_counts_and_codes() -> None:
    assert set(ProtocolHealth(ThinkGearHealth().tally).as_dict()) == {
        "reads", "trusted_reads", "raw_samples", "zero_reports", "contaminated_reports",
        "no_contact_reports", "rejected_packets", "skipped_bytes", "longest_report_gap_s",
        "held_reads", "trust_breaks", "last_trusted", "last_reason", "packets_ok",
        "bad_checksum", "bad_length", "malformed", "lost_samples", "result",
    }


def test_a_sources_summary_is_a_snapshot_without_its_port() -> None:
    src = _port_source(_contact_trace(3.0))
    src.start()
    src.read()
    snapshot = src.protocol_health()
    while src.available:
        src.read()
    src.stop()
    assert snapshot.tally.reads == 1
    assert src.protocol_health().tally.reads > 1
    final = src.protocol_health()
    text = json.dumps(final.as_dict()) + "\n".join(final.lines())
    assert "private7" not in text and "/dev/" not in text


# ---------------------------------------------------------------- check-source


def _check(monkeypatch: pytest.MonkeyPatch, source: Any, **kw: Any) -> int:
    monkeypatch.setattr(cli_impl, "_open", lambda spec, realtime=False: source)
    return run_check_source(_cfg(), source=SPEC, **kw)


def test_check_source_json_adds_the_health_summary_and_keeps_the_verdict(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    code = _check(monkeypatch, _port_source(_contact_trace()), seconds=5.0, as_json=True)
    out = json.loads(capsys.readouterr().out)
    assert code == (OK if out["passed"] else cli_impl.FAILED)
    health = out["source_health"]
    assert health["result"] == "trusted_reads_seen"
    assert health["no_contact_reports"] == 1 and health["zero_reports"] >= 4
    assert health["trust_breaks"] == {"no_contact": 1}
    assert 0 < health["trusted_reads"] < health["reads"]
    assert health["packets_ok"] > health["raw_samples"] > 0
    assert "private7" not in json.dumps(health)


def test_check_source_text_labels_it_as_protocol_health_only(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _check(monkeypatch, _port_source(_contact_trace()), seconds=5.0)
    out = capsys.readouterr().out
    block = out[out.index("ThinkGear protocol health"):]
    assert "no skin contact 1" in block
    assert "not evidence of a usable waveform" in block
    assert "rate_arrival is" in block
    assert "private7" not in block


def test_check_source_on_an_absent_port_says_nothing_was_observed(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _check(monkeypatch, _gone(), seconds=0.2)
    assert "NOT OBSERVED" in capsys.readouterr().out


def test_check_source_on_another_source_has_no_health_block(
        capsys: pytest.CaptureFixture[str]) -> None:
    run_check_source(_cfg("synthetic:eog"), seconds=0.3, as_json=True)
    assert "source_health" not in json.loads(capsys.readouterr().out)


# ---------------------------------------------------------------- monitor and doctor


def test_monitor_names_the_kind_of_problem_and_calls_the_rate_declared(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    trace = build_trace(blink_counts((), 12.0),
                        inject=((4.45, quality(200)), (7.5, bad_checksum_raw())))
    monkeypatch.setattr(cli_impl, "_open", lambda spec, realtime=False: _port_source(trace))
    run_monitor(_cfg(), tmp_path, seconds=0.0, interval=60.0)
    out = capsys.readouterr().out
    assert "declared fs 512 Hz, not a measurement" in out
    assert "reports no skin contact) [contact contaminated]" in out
    assert "is unknown) [corrupt framing]" in out
    assert "[rearm in progress]" in out


class _Flat:
    """A finite two-channel stream with a correct clock and a dead-flat waveform."""

    fs = 250.0
    channels = (ChannelInfo("ch1", SignalKind.EMG), ChannelInfo("ch2", SignalKind.EMG))
    available = True
    last_error = ""

    def __init__(self) -> None:
        self.k = 0

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def read(self) -> SampleBlock:
        if self.k >= 40:
            raise EOFError
        t0 = 0.2 * self.k
        self.k += 1
        return SampleBlock(np.zeros((2, 50)), self.fs, self.channels, t0)


def test_monitor_says_when_the_waveform_itself_holds_events(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli_impl, "_open", lambda spec, realtime=False: _Flat())
    run_monitor(_cfg("fakeflat:"), tmp_path, seconds=0.0, interval=60.0)
    out = capsys.readouterr().out
    assert "Events HELD: waveform quality failure" in out
    assert "stream-integrity gate is closed" not in out


def test_doctor_says_it_does_not_open_the_source_and_does_not(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    def never(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("doctor must not open the configured source")

    monkeypatch.setattr(cli_impl, "_brainflow_state", lambda: (False, ""))
    monkeypatch.setattr(cli_impl, "_serial_ports", lambda: [])
    monkeypatch.setattr(cli_impl, "_open", never)
    monkeypatch.setattr("yazses.biosignal.thinkgear._open_serial", never)
    assert run_doctor(_cfg(), tmp_path) == OK
    out = capsys.readouterr().out
    assert "your source is not opened" in out
    assert "this check does not open the device" in out


# ---------------------------------------------------------------- TG-17

_TOP = {"schema", "verdict", "reasons", "budget_per_hour", "min_phase_s", "trigger_kinds",
        "aborted", "sessions", "workday", "phases", "caveat"}
_WORKDAY = {"phases_used", "phases_unmeasured", "weights", "usable_s", "activations",
            "per_hour", "lower_per_hour", "upper_per_hour", "raw_per_hour",
            "raw_upper_per_hour", "extra_hours_needed", "weights_note"}
_PHASE = {"name", "label", "expects_intent", "status", "planned_s", "signal_s", "usable_s",
          "degraded_s", "excluded_s", "quality_fraction", "counts", "refused_events",
          "phantom_activations", "phantom_per_hour", "phantom_lower_per_hour",
          "phantom_upper_per_hour", "phantom_exact_upper_per_hour", "cues_total",
          "cues_scored", "cues_voided", "hits", "hit_rate", "hit_ci", "hit_grade",
          "median_latency_s", "latencies_s", "extra_activations", "workday_weight"}


def test_tg17_the_shareable_result_is_exactly_counts_and_durations(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    """An exact allowlist: a new field has to be looked at here before it can be shared."""
    trace = _contact_trace(14.0)
    monkeypatch.setattr(cli_impl, "_open", lambda spec, realtime=False: _port_source(trace))
    out_file = tmp_path / "ft.json"
    run_field_test(_cfg(), tmp_path / "private-data", as_json=True, out=str(out_file))
    printed = json.loads(capsys.readouterr().out)
    saved = json.loads(out_file.read_text(encoding="utf-8"))
    assert saved == printed
    assert set(saved) == _TOP
    assert set(saved["workday"]) == _WORKDAY
    assert saved["phases"]
    for phase in saved["phases"]:
        assert set(phase) == _PHASE, phase["name"]
        # One number per scored hit, measured from its cue: never a clock time per event.
        assert len(phase["latencies_s"]) <= phase["hits"]
        for key in ("planned_s", "signal_s", "usable_s", "degraded_s", "excluded_s"):
            assert isinstance(phase[key], int), key
    text = json.dumps(saved)
    for forbidden in ("/dev/", "private7", "private-data", "thinkgear:", "Fp1", "poor_signal",
                      "source_health", "calibration_file", tmp_path.name):
        assert forbidden not in text, forbidden
    if os.name == "posix":
        assert stat.S_IMODE(out_file.stat().st_mode) == 0o600


# ---------------------------------------------------------------- --source and calibration


@pytest.mark.parametrize(("configured", "spec", "expected"), [
    ("brainflow:38", "", "brainflow:38"),
    ("brainflow:38", "brainflow:0:/dev/ttyUSB0", "brainflow:0:/dev/ttyUSB0"),
    ("brainflow:38", "myo:AA", "myo:AA"),
    ("brainflow:38", "synthetic:emg", "synthetic:emg"),
    ("brainflow:38", "file:session.csv", "brainflow:38"),
    ("", "file:session.csv", ""),
    ("", SPEC, SPEC),
])
def test_calibration_follows_the_source_being_read(configured: str, spec: str,
                                                   expected: str) -> None:
    assert calibration_spec(_cfg(configured).biosignal, spec) == expected


def _emg(_spec: str = "", realtime: bool = False) -> SyntheticSource:
    return SyntheticSource("emg", seed=3, duration=2.0, mains_uv=0.0)


def _save_synthetic_profile(data_dir: Path) -> None:
    src = _emg()
    save_profile(CalibrationProfile(
        created_at=datetime.now(UTC).isoformat(), board_id="synthetic",
        channels=tuple(c.name for c in src.channels),
        channel_kinds=tuple(c.kind.value for c in src.channels), fs=float(src.fs),
        baseline_rms=10.0, noise_floor=5.0, mvc_rms=400.0, light_rms=80.0,
        phases=("relax", "squeeze_hard")), default_profile_path(data_dir))


@pytest.mark.parametrize(("configured", "override", "usable"), [
    # The profile is for the source being read, which is not the configured one.
    ("brainflow:38", "synthetic:emg", True),
    # The profile fits the configured source, and another board is being read.
    ("synthetic:emg", "bitalino:/dev/fake", False),
])
@pytest.mark.parametrize("command", ["monitor", "field-test"])
def test_source_override_is_judged_against_its_own_calibration(
        command: str, configured: str, override: str, usable: bool,
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    _save_synthetic_profile(tmp_path)
    monkeypatch.setattr(cli_impl, "_open", _emg)

    class Stop:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            raise ValueError("stop before the session runs")

    monkeypatch.setattr(fieldtest, "FieldTestSession", Stop)
    cfg = _cfg(configured, double_blink=False)
    if command == "monitor":
        run_monitor(cfg, tmp_path, source=override, seconds=0.0, interval=60.0)
        assert ("off until you calibrate" not in capsys.readouterr().out) is usable
    else:
        run_field_test(cfg, tmp_path, source=override, as_json=True)   # narration on stderr
        assert ("not cued" not in capsys.readouterr().err) is usable
