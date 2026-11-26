"""Daemon, ``biosignal monitor`` and ``biosignal field-test`` judge a stream alike (#830).

ADR-v2-155 decision 6 and spec §4: the three live consumers build the *same* guarded
source and event gate through one constructor (``biosignal.source_gates``), so the same
packet trace gets the same admissions, refusals and reasons in each (TG-14), and the field
test leaves untrusted stream out of its usable exposure and voids the cues that overlap it
(TG-16). The report stays aggregate-only (TG-17 is #831's; the shape is pinned here only
as far as this change could have touched it).

Every source is a ``ThinkGearSource`` over a hand-framed fake serial trace
(``tests/thinkgear_gate_trace.py``); nothing reads a device, a recording or the network.
"""

from __future__ import annotations

import dataclasses
import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from tests.thinkgear_gate_trace import (
    bad_checksum_raw,
    blink_counts,
    build_trace,
    quality,
    trace_source,
)
from yazses.biosignal import cli_impl, fieldtest, source_gates
from yazses.biosignal import sources as sources_mod
from yazses.biosignal.cli_impl import run_field_test, run_monitor
from yazses.biosignal.integrity import IntegrityGate, IntegrityGuard
from yazses.biosignal.pipeline import BiosignalPipeline
from yazses.biosignal.runner import build_runner_from_config
from yazses.biosignal.source_gates import SourceHealthGate
from yazses.biosignal.sources import SyntheticSource
from yazses.biosignal.types import EventKind
from yazses.config import BiosignalConfig, Config

SPEC = "thinkgear:/dev/fake-thinkgear"
DURATION_S = 14.0
EARLY_PAIR = (4.3, 4.6)      # straddled by a 0/200/0 read at 4.45 s: refused
LATE_PAIR = (11.5, 11.8)     # after the corrupt frame at 6.5 s and a full rearm: admitted

# The shared trace of spec §5 / TG-14: ordered bytes and arrival clock come from
# build_trace; the expected source health below is written down from the G0 policy by
# hand, not computed by the code under test. Windows are (start_s, end_s, trusted).
CONTACT_EVENTS = ((4.45, quality(0)), (4.45, quality(200)), (4.45, quality(0)),
                  (6.5, bad_checksum_raw()))
EXPECTED_HEALTH = (
    (0.0, 1.0, False),      # unknown contact, then rearming (reports at 0 s and 1 s)
    (1.1, 4.4, True),
    (4.5, 6.0, False),      # 0/200/0 taints its read; rearm needs the 5 s and 6 s reports
    (6.1, 6.4, True),
    (6.5, 8.0, False),      # a corrupt frame; rearm needs the 7 s and 8 s reports
    (8.1, DURATION_S, True),
)
EXPECTED_EVENTS = [EventKind.DOUBLE_BLINK]       # the late pair only


def _cfg(spec: str = SPEC) -> Config:
    cfg = Config()
    cfg.biosignal = dataclasses.replace(BiosignalConfig(), enabled=True, source=spec,
                                        double_blink=True)
    return cfg


def _trace():
    return build_trace(blink_counts(EARLY_PAIR + LATE_PAIR, DURATION_S), inject=CONTACT_EVENTS)


def _expected_trusted(t0: float, t1: float) -> bool | None:
    """The hand-written verdict for a block spanning [t0, t1), or None for a block that is
    not wholly inside one window (it straddles a transition)."""
    for start, end, trusted in EXPECTED_HEALTH:
        if start - 1e-9 <= t0 and t1 <= end + 1e-9:
            return trusted
    return None


@pytest.fixture
def record(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, ...]]:
    """Every pipeline.process call, by any consumer: block span, events, gate verdict."""
    rows: list[tuple[Any, ...]] = []
    original = BiosignalPipeline.process

    def process(self: BiosignalPipeline, block: Any) -> Any:
        result = original(self, block)
        report_health = None
        guard = getattr(self._parts.quality, "guard", None)
        if guard is not None:
            health = guard.health_for(block)
            report_health = None if health is None else health.trusted
        rows.append((round(float(block.t0), 6), block.n_samples,
                     tuple(e.kind for e in result.events), result.status.quality,
                     result.status.reason, result.status.dropped, report_health,
                     type(self._parts.quality).__name__))
        return result

    monkeypatch.setattr(BiosignalPipeline, "process", process)
    return rows


def _data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _via_runner(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(sources_mod, "open_source", lambda _spec, **_kw: trace_source(_trace()))
    runner = build_runner_from_config(_cfg(), ledger_path="", data_dir=_data_dir(tmp_path))
    assert runner is not None
    # The runner's own run() loop, untouched, on a thread; a live source never ends, so it
    # is stopped once the trace's port has failed (the source then reads None for ever).
    thread = threading.Thread(target=runner.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 60.0
    while time.monotonic() < deadline:
        src = runner._source
        if src is not None and getattr(src, "available", True) is False:
            break
        time.sleep(0.001)
    runner.stop()
    thread.join(timeout=10.0)
    assert not thread.is_alive()


def _via_monitor(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cli_impl, "_open", lambda spec, realtime=False: trace_source(_trace()))
    run_monitor(_cfg(), _data_dir(tmp_path), source=SPEC, seconds=0.0, interval=60.0)


def _via_field_test(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cli_impl, "_open", lambda spec, realtime=False: trace_source(_trace()))
    run_field_test(_cfg(), _data_dir(tmp_path), source=SPEC, as_json=True)


CONSUMERS = {"daemon": _via_runner, "monitor": _via_monitor, "field-test": _via_field_test}


def _run(consumer: str, monkeypatch, tmp_path, record) -> list[tuple[Any, ...]]:
    record.clear()
    with monkeypatch.context() as m:
        CONSUMERS[consumer](m, tmp_path / consumer)
    return list(record)


# ---------------------------------------------------------------- TG-14


@pytest.mark.parametrize("consumer", list(CONSUMERS))
def test_tg14_each_consumer_matches_the_hand_written_health_and_events(
        consumer, monkeypatch, tmp_path, record, capsys) -> None:
    rows = _run(consumer, monkeypatch, tmp_path, record)
    assert rows, "the consumer never processed a block"
    assert {r[-1] for r in rows} == {"SourceHealthGate"}
    checked = 0
    for t0, n, _events, quality_, _reason, _dropped, trusted, _gate in rows:
        expected = _expected_trusted(t0, t0 + n / 512.0)
        if expected is None:
            continue
        checked += 1
        assert trusted is expected, (consumer, t0)
        if not trusted:
            assert quality_.lower() == "bad", (consumer, t0)
    assert checked > 100
    events = [k for r in rows for k in r[2]]
    assert events == EXPECTED_EVENTS, consumer
    reasons = {r[4] for r in rows if r[4]}
    assert any(r.startswith("source health: no_contact") for r in reasons), reasons
    assert any(r.startswith("stream integrity: source corrupt_packet") for r in reasons)


def test_tg14_daemon_monitor_and_field_test_agree_block_for_block(
        monkeypatch, tmp_path, record, capsys) -> None:
    runs = {c: _run(c, monkeypatch, tmp_path, record) for c in CONSUMERS}
    # (t0, samples, accepted kinds, quality, gate reason, refusals so far, source verdict)
    shape = {c: [r[:7] for r in rows] for c, rows in runs.items()}
    assert shape["daemon"] == shape["monitor"] == shape["field-test"]


@pytest.mark.parametrize("consumer", list(CONSUMERS))
def test_all_three_consumers_build_through_the_one_constructor(
        consumer, monkeypatch, tmp_path, record, capsys) -> None:
    calls: list[str] = []
    real_guard, real_gate = source_gates.guard_source, source_gates.compose_quality_gate

    def guard(source, spec, **kw):
        calls.append("guard")
        return real_guard(source, spec, **kw)

    def gate(g, q, spec=""):
        calls.append("gate")
        return real_gate(g, q, spec)

    monkeypatch.setattr(source_gates, "guard_source", guard)
    monkeypatch.setattr(source_gates, "compose_quality_gate", gate)
    _run(consumer, monkeypatch, tmp_path, record)
    assert calls.count("guard") == 1 and calls.count("gate") == 1, calls


# ---------------------------------------------------------------- other sources


def _synthetic(*_a, **_k):
    src = SyntheticSource("eog", seed=3, duration=6.0, mains_uv=0.0)
    src.schedule_blink(3.0)
    src.schedule_blink(3.3)
    return src


@pytest.mark.parametrize("consumer", ["monitor", "field-test"])
def test_a_synthetic_source_keeps_the_plain_integrity_gate(consumer, monkeypatch, tmp_path,
                                                           record, capsys) -> None:
    monkeypatch.setattr(cli_impl, "_open", _synthetic)
    data = _data_dir(tmp_path)
    if consumer == "monitor":
        run_monitor(_cfg("synthetic:eog"), data, source="synthetic:eog", seconds=0.0)
    else:
        run_field_test(_cfg("synthetic:eog"), data, source="synthetic:eog", as_json=True)
    assert record and {r[-1] for r in record} == {"IntegrityGate"}
    assert {r[6] for r in record} == {None}            # no source verdict, none needed


def test_field_test_on_a_clean_synthetic_source_reports_what_it_did_before(
        monkeypatch, tmp_path, capsys) -> None:
    """Field test now has the integrity guard; on a correct source it never fires, so the
    report equals the one the old, unguarded wiring produced."""
    monkeypatch.setattr(cli_impl, "_open", _synthetic)
    data = _data_dir(tmp_path)
    run_field_test(_cfg("synthetic:eog"), data, source="synthetic:eog", as_json=True)
    guarded = json.loads(capsys.readouterr().out)
    with monkeypatch.context() as m:
        m.setattr(source_gates, "guard_source", lambda source, spec, **kw: source)
        m.setattr(source_gates, "compose_quality_gate", lambda g, q, spec="": q)
        run_field_test(_cfg("synthetic:eog"), data, source="synthetic:eog", as_json=True)
    unguarded = json.loads(capsys.readouterr().out)
    assert guarded == unguarded


# ---------------------------------------------------------------- TG-16


def _phases() -> tuple[fieldtest.Phase, ...]:
    return (
        fieldtest.Phase("rest", "Sit still", "Sit still.", 5.0, False),
        fieldtest.Phase("gesture_double_blink", "Blink twice", "Blink twice.", 6.5, True,
                        expected=(EventKind.DOUBLE_BLINK,), cues=2, response_window_s=1.0,
                        lead_in_s=0.5),
    )


def _session_over(trace, monkeypatch) -> fieldtest.FieldTestReport:
    """A field-test session over ``trace`` built exactly as ``run_field_test`` builds it."""
    src = trace_source(trace)
    guard = source_gates.guard_source(src, SPEC)
    guard.start()
    sw = cli_impl.switches_from(_cfg().biosignal)

    def make_pipeline() -> Any:
        pipeline, parts, _ = cli_impl._build_pipeline(_cfg().biosignal, guard, sw, Path("."))
        parts.quality = source_gates.compose_quality_gate(guard, parts.quality, SPEC)
        return pipeline

    session = fieldtest.FieldTestSession(None, make_pipeline, protocol=_phases(),
                                         min_phase_s=1.0, settle_s=0.0)
    while not session.finished:
        block = guard.read()
        if block is None:
            if not guard.available:
                break
            continue
        session.feed(block)
    guard.stop()
    return session.result()


def test_tg16_untrusted_seconds_are_excluded_and_overlapping_cues_voided(monkeypatch) -> None:
    clean = _session_over(build_trace(blink_counts((), 18.0)), monkeypatch)
    # Rest ends at about 7 s of stream (5 s usable after ~2 s unknown/rearm). Contact is
    # then reported lost at 9, 10 and 11 s, inside the gesture phase and over its cues;
    # the rearm needs the 12 s and 13 s reports.
    faulty_trace = build_trace(blink_counts((), 18.0),
                               contact=lambda s: 200 if 9 <= s <= 11 else 0)
    faulty = _session_over(faulty_trace, monkeypatch)

    c_rest, f_rest = clean.phase("rest"), faulty.phase("rest")
    c_g, f_g = clean.phase("gesture_double_blink"), faulty.phase("gesture_double_blink")
    assert None not in (c_rest, f_rest, c_g, f_g)
    assert (f_rest.usable_s, f_rest.excluded_s) == (c_rest.usable_s, c_rest.excluded_s)
    # Exposure is usable signal only: the untrusted stretch (no contact, then the rearm) is
    # excluded, not counted toward the phase.
    assert c_g.excluded_s == 0
    assert f_g.excluded_s >= 3
    assert f_g.usable_s <= f_g.signal_s - f_g.excluded_s
    # A cue overlapping it is voided, not scored as a miss.
    assert c_g.cues_voided == 0 and c_g.cues_scored == c_g.cues_total
    assert f_g.cues_voided >= 1
    assert f_g.cues_scored + f_g.cues_voided <= f_g.cues_total
    assert f_g.hits == 0 and f_g.extra_activations == 0


def test_tg16_rearm_exposure_is_excluded_too(monkeypatch) -> None:
    """The first second (unknown contact, then rearming) is not usable exposure."""
    report = _session_over(build_trace(blink_counts((), 13.0)), monkeypatch)
    rest = report.phase("rest")
    assert rest is not None and rest.excluded_s >= 1


def test_tg16_the_report_stays_aggregate_only(monkeypatch) -> None:
    payload = fieldtest.report_to_dict(_session_over(build_trace(blink_counts((), 13.0)),
                                                     monkeypatch))
    text = json.dumps(payload)
    for forbidden in ("/dev/", "fake-thinkgear", "rfcomm", "poor_signal", "consecutive_good",
                      "continuous_good", "source health", "health"):
        assert forbidden not in text, forbidden


# ---------------------------------------------------------------- lifecycle


@pytest.mark.parametrize("spec", [SPEC, "synthetic:eog"])
def test_field_test_session_is_handed_the_guarded_source_never_the_bare_one(
        monkeypatch, tmp_path, capsys, spec) -> None:
    """``FieldTestSession.run()`` reads whatever source it was given. ``run_field_test``
    drives ``feed()`` itself today, but a session holding the bare source would be one
    ``run()`` call away from scoring unguarded, ungated blocks."""
    bare = trace_source(_trace()) if spec == SPEC else _synthetic()
    monkeypatch.setattr(cli_impl, "_open", lambda _spec, realtime=False: bare)
    seen: list[Any] = []
    real_session = fieldtest.FieldTestSession

    def session(source_or_blocks: Any = None, *a: Any, **kw: Any) -> Any:
        seen.append(source_or_blocks)
        return real_session(source_or_blocks, *a, **kw)

    monkeypatch.setattr(fieldtest, "FieldTestSession", session)
    run_field_test(_cfg(spec), _data_dir(tmp_path), source=spec, as_json=True)
    assert len(seen) == 1
    assert seen[0] is not bare
    assert isinstance(seen[0], IntegrityGuard) and seen[0].inner is bare


def test_field_test_starts_the_source_once_and_always_stops_it(monkeypatch, tmp_path,
                                                               capsys) -> None:
    starts: list[int] = []
    stops: list[int] = []
    src = trace_source(_trace())
    real_start, real_stop = src.start, src.stop
    monkeypatch.setattr(src, "start", lambda: (starts.append(1), real_start())[1])
    monkeypatch.setattr(src, "stop", lambda: (stops.append(1), real_stop())[1])
    monkeypatch.setattr(cli_impl, "_open", lambda spec, realtime=False: src)
    run_field_test(_cfg(), _data_dir(tmp_path), source=SPEC, as_json=True)
    assert starts == [1] and stops == [1]


def test_field_test_ctrl_c_stops_the_source(monkeypatch, tmp_path, capsys) -> None:
    src = trace_source(_trace())
    stopped: list[int] = []
    real_stop = src.stop
    reads = {"n": 0}
    real_read = src.read

    def read():
        reads["n"] += 1
        if reads["n"] > 20:
            raise KeyboardInterrupt
        return real_read()

    monkeypatch.setattr(src, "read", read)
    monkeypatch.setattr(src, "stop", lambda: (stopped.append(1), real_stop())[1])
    monkeypatch.setattr(cli_impl, "_open", lambda spec, realtime=False: src)
    run_field_test(_cfg(), _data_dir(tmp_path), source=SPEC, as_json=True)
    assert stopped == [1]


def test_field_test_on_an_unavailable_port_is_unusable_not_a_crash(monkeypatch, tmp_path,
                                                                   capsys) -> None:
    from yazses.biosignal.thinkgear import ThinkGearSource

    def boom():
        raise OSError("no such port")

    monkeypatch.setattr(cli_impl, "_open", lambda spec, realtime=False: ThinkGearSource(
        "/dev/none", serial_factory=boom))
    assert run_field_test(_cfg(), _data_dir(tmp_path), source=SPEC) == cli_impl.UNUSABLE


def test_monitor_prints_the_source_health_reason_without_signal_values(
        monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(cli_impl, "_open", lambda spec, realtime=False: trace_source(_trace()))
    run_monitor(_cfg(), _data_dir(tmp_path), source=SPEC, seconds=0.0, interval=60.0)
    out = capsys.readouterr().out
    assert "Source health: events HELD (no_contact" in out
    assert "Source health: events HELD (corrupt_packet" in out
    assert "Source health: trusted" in out


def test_guard_types_are_the_existing_ones(monkeypatch, tmp_path) -> None:
    guard = source_gates.guard_source(trace_source(_trace()), SPEC)
    assert type(guard) is IntegrityGuard
    gate = source_gates.compose_quality_gate(guard, None, SPEC)
    assert isinstance(gate, SourceHealthGate) and type(gate.inner) is IntegrityGate
