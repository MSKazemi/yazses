"""A synthetic ThinkGear headset, end to end through the real blink switch.

``tests/thinkgear_emulator.py`` renders a seeded, protocol-faithful TGAM byte stream (512 Hz
raw packets, a POOR_SIGNAL/eSense report each second, scripted blink artefacts and
transport faults); ``EmulatedSerial`` plays it against a fake clock. This file drives that
stream through the three places a headset's blocks reach a detector, each exactly as the
product composes it:

* **daemon** - ``runner.build_runner_from_config`` -> ``BiosignalRunner.run``: ``open_source``
  -> ``IntegrityGuard`` (arrival-rate check on) -> ``IntegrityGate`` -> ``BiosignalPipeline``;
* **monitor** - ``cli_impl.run_monitor``: the same guard and gate, its own pipeline;
* **field-test** - ``cli_impl.run_field_test``: the bare source, no guard (as shipped).

Only three things are replaced, none of them policy: the serial port (``_open_serial``
returns the emulated port), the guard's and runner's clocks (the fake clock), and the
runner's idle sleep (0, so a test does not wait for wall time). Detector thresholds, gates
and the pipeline are untouched.

## Characterization, not a fix

Maintainer review of ADR-v2-155 (#827) is pending, so nothing under ``src/`` changes here.
Where the current code admits an activation the ADR says it must not, the test states the
*safe* property and is marked ``xfail(strict=True, raises=AssertionError)`` naming the
issue that owns the fix: #828 (per-read source health), #829 (compose it with the gates),
#830 (field-test/monitor parity). ``xfail_strict`` is on, so the day one of those lands
the marker must come off - an xfail cannot outlive the bug it describes. Behaviour that is
neither clearly safe nor unsafe is pinned as it is, with a comment.

Everything is synthetic and offline: no device, no network, no recording of a person.
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests import thinkgear_emulator as em
from yazses.biosignal import cli_impl
from yazses.biosignal import integrity as integrity_mod
from yazses.biosignal import runner as runner_mod
from yazses.biosignal import sources as sources_mod
from yazses.biosignal import thinkgear as thinkgear_mod
from yazses.biosignal.pipeline import BiosignalPipeline
from yazses.biosignal.runner import RunnerCallbacks, build_runner_from_config
from yazses.biosignal.thinkgear import (
    THINKGEAR_RAW_TO_UV,
    ThinkGearParser,
    ThinkGearSource,
    thinkgear_checksum,
)
from yazses.config import BiosignalConfig, Config

SPEC = "thinkgear:/dev/emulated-tgam"
PATHS = ("daemon", "monitor", "field_test")
# The caller's polling period: 1/32 s is ~129 bytes (~16 raw samples) per read.
POLL_S = 1.0 / 32.0
# The double blink of most scenarios: onsets 5.00 and 5.35 s, peaks 5.15 and 5.50 s.
PAIR_AT = 5.0
SECONDS = 12.0


# ====================================================================================
# 1. the emulator itself: framing, cadence, determinism, faults
# ====================================================================================


def test_framing_matches_the_production_checksum_and_the_protocol_example() -> None:
    em.self_check()
    assert thinkgear_checksum(em.DOC_EXAMPLE[3:-1]) == em.DOC_EXAMPLE[-1] == 0xE3
    assert em.UV_PER_COUNT == pytest.approx(THINKGEAR_RAW_TO_UV)


def test_cadence_is_512_raw_packets_and_one_report_per_second() -> None:
    trace = em.generate(em.TraceSpec(seconds=10.0, seed=1))
    parser = ThinkGearParser()
    packets = parser.feed(trace.data)
    raw = [v for p in packets for v in p.raw]
    reports = [p.poor_signal for p in packets if p.poor_signal is not None]
    assert len(raw) == 5120 and raw == trace.counts.tolist()
    assert reports == [0] * 10
    assert parser.stats.rejected_packets == 0 and parser.stats.skipped_bytes == 0
    # 8 B per raw packet + one 36 B report a second fits a 57600-baud 8N1 link (5760 B/s).
    assert len(trace.data) / 10.0 == pytest.approx(512 * 8 + 36)
    assert len(trace.data) / 10.0 < 57600 / 10


def test_esense_and_vendor_blink_rows_are_on_the_wire_but_never_surface() -> None:
    trace = em.generate(em.TraceSpec(seconds=3.0, blinks=(em.Blink(1.0),)))
    data = trace.data
    # report: PLENGTH 0x20, POOR_SIGNAL 0, band powers (0x83, 24 B), attention 0x04, meditation 0x05
    assert data.count(b"\xaa\xaa\x20\x02\x00\x83\x18") == 3
    assert b"\xaa\xaa\x02\x16" in data                   # the undocumented blink-strength row
    packets = ThinkGearParser().feed(trace.data)
    assert {f.name for f in dataclasses.fields(packets[0])} == {"raw", "poor_signal"}
    assert sum(len(p.raw) for p in packets) == trace.counts.size


def test_generation_is_deterministic_and_seeded() -> None:
    spec = em.TraceSpec(seconds=4.0, seed=7, blinks=em.double_blink(1.0),
                        garbage=(em.Garbage(2.0, 40),))
    assert em.generate(spec).data == em.generate(spec).data
    assert em.generate(dataclasses.replace(spec, seed=8)).data != em.generate(spec).data


def test_blink_shape_is_the_documented_assumption() -> None:
    trace = em.generate(em.TraceSpec(seconds=3.0, noise_uv=0.0, alpha_uv=0.0,
                                     blinks=(em.Blink(1.0),)))
    uv = trace.counts * em.UV_PER_COUNT
    assert uv.max() == pytest.approx(em.BLINK_AMP_UV, abs=em.UV_PER_COUNT)
    above_half = np.flatnonzero(uv >= em.BLINK_AMP_UV / 2) / em.FS
    fwhm = above_half[-1] - above_half[0]
    assert 0.10 <= fwhm <= 0.40                          # BlinkDetector's width window
    assert fwhm == pytest.approx(em.BLINK_WIDTH_S / 2, abs=2 / em.FS)


def test_faults_are_rendered_as_specified() -> None:
    spec = em.TraceSpec(
        seconds=10.0,
        corrupt=(em.CorruptChecksum(2.0, count=3),),
        garbage=(em.Garbage(3.0, 50),),
        poor_bursts=(em.PoorBurst(6.0),),
        stalls=(em.Stall(7.0, 0.5, drop=True),),
    )
    trace = em.generate(spec)
    parser = ThinkGearParser()
    packets = parser.feed(trace.data)
    assert parser.stats.bad_checksum == trace.corrupted_packets == 3
    # each rejected packet costs its 6 bytes after the sync pair, plus the garbage
    assert parser.stats.skipped_bytes == 3 * 6 + 50
    assert sum(len(p.raw) for p in packets) == 5120 - 3 - trace.dropped_packets
    assert trace.dropped_packets == 256
    assert [p.poor_signal for p in packets if p.poor_signal is not None].count(200) == 1
    torn = em.generate(em.TraceSpec(seconds=4.0, stalls=(em.Stall(2.0, 0.2, drop=True,
                                                                   tear=True),)))
    tparser = ThinkGearParser()
    tparser.feed(torn.data)
    assert tparser.stats.bad_checksum == 1                # the cut is visible to the parser


def test_stale_and_absent_reports() -> None:
    stale = em.generate(em.TraceSpec(seconds=8.0, report_until_s=3.0))
    assert stale.report_times == (0.5, 1.5, 2.5)
    never = em.generate(em.TraceSpec(seconds=4.0, report_period_s=None))
    assert never.report_values == () and never.poor_at(3.0) is None


# ====================================================================================
# 2. the transports
# ====================================================================================


def _drain(source: ThinkGearSource, port: em.EmulatedSerial) -> list[Any]:
    """Read until every byte has been delivered (bounded, so a bug cannot spin forever)."""
    blocks = []
    for _ in range(100_000):
        if port.pos >= len(port.trace.data):
            break
        b = source.read()
        if b is not None:
            blocks.append(b)
    return blocks


@pytest.mark.parametrize("chunk_sizes", [None, (1, 1), (1, 17), (3, 700)],
                         ids=["whole", "byte-at-a-time", "1-17", "3-700"])
def test_emulated_port_any_chunking_delivers_every_sample_once(chunk_sizes) -> None:
    trace = em.generate(em.TraceSpec(seconds=2.0, seed=3, blinks=(em.Blink(1.0),)))
    clock = em.FakeClock()
    port = em.EmulatedSerial(trace, clock, poll_s=POLL_S, chunk_sizes=chunk_sizes, seed=5)
    src = ThinkGearSource(SPEC, serial_factory=lambda: port)
    src.start()
    blocks = _drain(src, port)
    assert port.pos == len(trace.data)
    got = np.concatenate([b.data[0] for b in blocks])
    np.testing.assert_allclose(got, trace.counts * THINKGEAR_RAW_TO_UV)
    # t0 counts delivered samples: contiguous whatever the chunking
    assert [b.t0 for b in blocks] == pytest.approx(
        list(np.cumsum([0] + [b.n_samples for b in blocks[:-1]]) / em.FS))
    assert src.poor_signal == 0 and src.lost_packets == 0


def test_emulated_port_follows_the_injected_clock_through_a_stall() -> None:
    trace = em.generate(em.TraceSpec(seconds=4.0, stalls=(em.Stall(1.0, 2.0),)))
    clock = em.FakeClock()
    port = em.EmulatedSerial(trace, clock, poll_s=0.25)
    assert port.read(10**6) == b""                     # t = 0: nothing has arrived yet
    sizes = [len(port.read(10**6)) for _ in range(16)]  # t = 0.25 .. 4.0
    # 0.25 s of data per read (128 raw packets = 1024 B, plus a 36 B report once a second)
    assert sizes[:4] == [1024, 1060, 1024, 1024]       # t = 0.25 .. 1.0
    assert sizes[4:11] == [0] * 7                        # t = 1.25 .. 2.75: stalled
    assert sizes[11] == 8 * 1024 + 2 * 36                # t = 3.0: the 2 s held back, at once
    assert port.pos == len(trace.data)


def test_source_reports_only_the_last_poor_signal_of_a_read() -> None:
    """Characterization (#828): a 0/200/0 burst inside one read leaves ``poor_signal == 0``.

    The 200 was on the wire and parsed, but ``ThinkGearSource`` keeps only the final value,
    so nothing downstream can know contact was lost inside that read. ADR-v2-155 asks for
    the whole read to be untrusted instead.
    """
    trace = em.generate(em.TraceSpec(seconds=3.0, poor_bursts=(em.PoorBurst(1.6),)))
    clock = em.FakeClock()
    port = em.EmulatedSerial(trace, clock, poll_s=0.5)
    src = ThinkGearSource(SPEC, serial_factory=lambda: port)
    src.start()
    seen = []
    for _ in range(8):
        src.read()
        seen.append(src.poor_signal)
    assert trace.poor_values_between(1.5, 1.7) == (0, 0, 200, 0)
    assert 200 not in seen                               # the 200 never became visible
    assert set(seen) <= {None, 0}


@pytest.mark.skipif(sys.platform == "win32", reason="pseudo-terminals need Linux or macOS")
@pytest.mark.timeout(60)
def test_thinkgear_source_opens_a_real_tty_through_pyserial() -> None:
    """The real ``_open_serial`` (pyserial, ``timeout=0``) on a pty fed by the emulator.

    Proves the production open path reads a byte-exact stream from an actual tty path - the
    shape of ``/dev/rfcomm0`` - before any hardware exists. Skips without the ``emg`` extra.
    """
    pytest.importorskip("serial", reason="pyserial ships with the 'emg' extra")
    import pty
    import tty

    trace = em.generate(em.TraceSpec(seconds=3.0, seed=11, blinks=em.double_blink(1.0)))
    controller, follower = pty.openpty()
    tty.setraw(follower)                                 # no CR/LF translation, no echo
    path = os.ttyname(follower)
    stop = threading.Event()

    def writer() -> None:
        view = memoryview(trace.data)
        for i in range(0, len(view), 512):
            if stop.is_set():
                return
            os.write(controller, view[i:i + 512])
            time.sleep(0.002)

    src = ThinkGearSource(path)
    thread = threading.Thread(target=writer, daemon=True)
    try:
        src.start()
        assert src.available, src.last_error
        thread.start()
        got: list[np.ndarray] = []
        deadline = time.monotonic() + 30.0
        while sum(g.size for g in got) < trace.counts.size and time.monotonic() < deadline:
            block = src.read()
            if block is None:
                time.sleep(0.005)
            else:
                got.append(block.data[0])
    finally:
        stop.set()
        thread.join(timeout=5.0)
        src.stop()
        os.close(controller)
        os.close(follower)
    np.testing.assert_allclose(np.concatenate(got), trace.counts * THINKGEAR_RAW_TO_UV)
    assert src.lost_packets == 0 and src.poor_signal == 0


@pytest.mark.skipif(sys.platform == "win32", reason="pseudo-terminals need Linux or macOS")
@pytest.mark.timeout(60)
def test_manual_pty_tool_streams_and_exits(capsys: pytest.CaptureFixture[str]) -> None:
    """``python -m tests.thinkgear_emulator`` prints a ``thinkgear:`` spec and returns 0.
    0.1 s is ~410 bytes, under the smallest tty input buffer, so with nobody reading the
    follower the write can never block."""
    assert em.main(["--seconds", "0.1", "--double-blink-every", "0"]) == 0
    assert capsys.readouterr().out.startswith("thinkgear:/dev/")


# ====================================================================================
# 3. end to end: emulator -> ThinkGearSource -> guard/gate -> pipeline, on three paths
# ====================================================================================


@dataclasses.dataclass
class Outcome:
    path: str
    accepted: list[tuple[str, float]]      # (kind, stream t) of every event a pipeline accepted
    refused: dict[str, int]                # pipeline gate refusals by reason
    violations: dict[str, int]             # stream-integrity violations (guarded paths only)
    lost_packets: int
    skipped_bytes: int
    labels: list[str]                      # daemon intents
    report: dict[str, Any] | None          # field-test payload

    @property
    def activations(self) -> list[float]:
        return [t for kind, t in self.accepted if kind == "double_blink"]


def _cfg() -> Config:
    cfg = Config()
    cfg.biosignal = dataclasses.replace(BiosignalConfig(), enabled=True, source=SPEC,
                                        double_blink=True, jaw_clench=False, emg=False)
    return cfg


@pytest.fixture
def drive(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Callable[..., Outcome]]:
    """``drive(path, spec, *, poll_s, chunk_sizes)`` -> :class:`Outcome` for one run."""
    counter = iter(range(10**6))

    def run(path: str, spec: em.TraceSpec, *, poll_s: float = POLL_S,
            chunk_sizes: tuple[int, int] | None = None) -> Outcome:
        trace = em.generate(spec)
        clock = em.FakeClock()
        stop_hook: list[Callable[[], None]] = []
        port = em.EmulatedSerial(trace, clock, poll_s=poll_s, chunk_sizes=chunk_sizes,
                                 seed=spec.seed, tail_s=0.5,
                                 on_exhausted=lambda: stop_hook[0]())
        opened: list[Any] = []
        guards: list[Any] = []
        pipelines: list[BiosignalPipeline] = []
        accepted: list[tuple[str, float]] = []

        real_open = sources_mod.open_source

        def open_source(text: str, **kw: Any) -> Any:
            src = real_open(text, **kw)
            opened.append(src)
            return src

        class ClockedGuard(integrity_mod.IntegrityGuard):
            def __init__(self, source: Any, **kw: Any) -> None:
                kw["clock"] = clock
                super().__init__(source, **kw)
                guards.append(self)

        class ClockedRunner(runner_mod.BiosignalRunner):
            def __init__(self, *a: Any, **kw: Any) -> None:
                kw["clock"] = clock
                kw["poll_seconds"] = 0.0
                super().__init__(*a, **kw)

        real_process = BiosignalPipeline.process

        def process(self: BiosignalPipeline, block: Any) -> Any:
            if not any(p is self for p in pipelines):
                pipelines.append(self)
            result = real_process(self, block)
            accepted.extend((e.kind.value, round(float(e.t), 3)) for e in result.events)
            return result

        with monkeypatch.context() as m:
            m.setattr(thinkgear_mod, "_open_serial", lambda port_name, baud: port)
            m.setattr(sources_mod, "open_source", open_source)
            m.setattr(integrity_mod, "IntegrityGuard", ClockedGuard)
            m.setattr(runner_mod, "BiosignalRunner", ClockedRunner)
            m.setattr(BiosignalPipeline, "process", process)
            labels: list[str] = []
            report: dict[str, Any] | None = None
            if path == "daemon":
                runner = build_runner_from_config(
                    _cfg(), RunnerCallbacks(on_intent=lambda i: labels.append(i.label)),
                    ledger_path="")
                assert runner is not None
                stop_hook.append(runner.stop)
                runner.run()
                assert runner.status()["last_error"] == ""
            else:
                def interrupt() -> None:
                    raise KeyboardInterrupt  # what Ctrl-C does to both CLI loops

                stop_hook.append(interrupt)
                data_dir = tmp_path / f"run{next(counter)}"
                data_dir.mkdir()
                if path == "monitor":
                    rc = cli_impl.run_monitor(_cfg(), data_dir, blink=True, emg=False,
                                              clench=False)
                else:
                    payloads: list[dict[str, Any]] = []
                    from yazses.biosignal import fieldtest

                    real_dict = fieldtest.report_to_dict

                    def keep(rep: Any) -> dict[str, Any]:
                        payloads.append(real_dict(rep))
                        return payloads[-1]

                    m.setattr(fieldtest, "report_to_dict", keep)
                    rc = cli_impl.run_field_test(_cfg(), data_dir, as_json=True)
                    report = payloads[0]
                assert rc == 0, path
        assert port.pos == len(trace.data), "the run ended before the trace did"
        assert len(opened) == 1 and len(pipelines) == 1
        src = opened[0]
        refused = dict(pipelines[0].status.dropped_by_reason)
        violations = dict(guards[0].report.as_dict()["violations"]) if guards else {}
        assert bool(guards) == (path != "field_test")
        return Outcome(path, accepted, refused, violations, src.lost_packets,
                       src.parser.stats.skipped_bytes, labels, report)

    yield run


def _spec(**kw: Any) -> em.TraceSpec:
    base: dict[str, Any] = {"seconds": SECONDS, "seed": 0, "blinks": em.double_blink(PAIR_AT)}
    base.update(kw)
    return em.TraceSpec(**base)


# ---------------------------------------------------------------- (a) / (b) clean signal


@pytest.mark.parametrize("path", PATHS)
def test_clean_double_blink_is_exactly_one_activation(drive, path) -> None:
    out = drive(path, _spec())
    # stamped at the second blink's peak (5.50 s) plus the detector chain's filter delay
    assert len(out.activations) == 1
    assert PAIR_AT + 0.35 + em.BLINK_WIDTH_S / 2 <= out.activations[0] <= PAIR_AT + 0.8
    assert out.violations == {} and out.lost_packets == 0
    if path == "daemon":
        assert out.labels == ["undo"]                    # the default intent, once
    if path == "field_test":
        assert out.report is not None
        rest = next(p for p in out.report["phases"] if p["name"] == "rest")
        assert rest["phantom_activations"] == 1          # a no-intent phase: it is a phantom


@pytest.mark.parametrize("path", PATHS)
def test_single_blink_is_no_activation(drive, path) -> None:
    out = drive(path, _spec(blinks=(em.Blink(PAIR_AT),)))
    assert out.accepted == []


@pytest.mark.parametrize("seed", range(4))
@pytest.mark.parametrize("chunk_sizes", [(1, 40), (64, 2048)], ids=["tiny-reads", "bursty"])
def test_arbitrary_chunking_does_not_change_the_outcome(drive, seed, chunk_sizes) -> None:
    # Small chunks under-read the port: it falls behind and catches up as bursts, which the
    # guard must not mistake for a rate problem within a 12 s trace.
    out = drive("daemon", _spec(seed=seed), chunk_sizes=chunk_sizes,
                poll_s=POLL_S if chunk_sizes[0] > 1 else 1 / 256)
    assert len(out.activations) == 1 and out.labels == ["undo"]


@pytest.mark.timeout(240)
def test_ten_minutes_of_clean_noise_has_no_false_activation(drive) -> None:
    """(c) 10 min, 307,200 raw samples of background EEG only, through the daemon path.

    Observed: 0 accepted events, 0 integrity violations (seed 0). Zero in 10 min bounds the
    rate only to ~18/h (rule of three); it shows the plumbing does not invent gestures, not
    that a real forehead is quiet.
    """
    out = drive("daemon", em.TraceSpec(seconds=600.0, seed=0), poll_s=0.1)
    assert out.accepted == []
    assert out.violations == {} and out.lost_packets == 0 and out.skipped_bytes == 0


@pytest.mark.timeout(240)
def test_ten_minutes_of_spontaneous_single_blinks_has_no_false_activation(drive) -> None:
    """10 min with a single blink every 2-6 s (uniform; ~15/min, the resting blink rate
    ``config.py`` quotes) and never two within 1.5 s. A pair the detector reads into that
    would be a false activation. Observed: 0."""
    rng = np.random.default_rng(42)
    t, blinks = 3.0, []
    while t < 598.0:
        blinks.append(em.Blink(float(t)))
        t += float(rng.uniform(2.0, 6.0))
    out = drive("daemon", em.TraceSpec(seconds=600.0, seed=1, blinks=tuple(blinks)), poll_s=0.1)
    assert len(blinks) > 140
    assert out.activations == []


# ---------------------------------------------------------------- (d) contact and transport


# Scenario -> (spec, the ADR-v2-155 rule it breaks, the issue that owns the fix)
UNSAFE: dict[str, tuple[em.TraceSpec, str]] = {
    # Electrode off the skin (POOR_SIGNAL 200 on every report) while the raw waveform still
    # carries a double blink - e.g. a lifted electrode picking up movement.
    "no_contact_200": (_spec(poor=(em.PoorSignal(2.0, SECONDS, 200),)),
                       "#829: POOR_SIGNAL is read by nothing outside thinkgear.py"),
    # "any nonzero value indicates that some sort of noise contamination is detected"
    "contaminated_26": (_spec(poor=(em.PoorSignal(2.0, SECONDS, 26),)),
                        "#829: a nonzero POOR_SIGNAL does not veto"),
    # 0, 200, 0 inside one read, between the two blinks of the pair
    "burst_0_200_0": (_spec(poor_bursts=(em.PoorBurst(PAIR_AT + 0.2),)),
                      "#828: only the last POOR_SIGNAL of a read survives"),
    # A checksum failure just before the pair: the packet is dropped, t0 stays contiguous
    "bad_checksum": (_spec(corrupt=(em.CorruptChecksum(PAIR_AT - 0.05, count=3),)),
                     "#828: a rejected packet does not taint its read"),
    # A loss in the middle of a packet between the blinks (visible: one bad checksum)
    "torn_packet": (_spec(stalls=(em.Stall(PAIR_AT + 0.25, 0.02, drop=True, tear=True),)),
                    "#828: a gesture spanning an uncertainty boundary is admitted"),
    # The headset never sends POOR_SIGNAL: contact is unknown for the whole session
    "contact_never_reported": (_spec(report_period_s=None),
                               "#829: unknown contact is treated as healthy"),
    # Reports stop at 1.5 s; the pair at 5 s is > 3 s after the last one
    "contact_report_stale": (_spec(report_until_s=1.5),
                             "#829: a stale contact report is treated as healthy"),
}


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("scenario", sorted(UNSAFE))
def test_unsafe_admission_is_reproduced_on_every_path(drive, scenario, path) -> None:
    """Characterization: on every path, current code admits the pair in each UNSAFE case.

    These are the numbers the report quotes. The safe property is stated separately below
    as a strict xfail, so this test and that one flip together when the fix lands.
    """
    spec, _why = UNSAFE[scenario]
    out = drive(path, spec)
    assert len(out.activations) == 1
    assert out.violations == {}                          # the stream guard saw nothing wrong
    trace = em.generate(spec)
    if scenario == "no_contact_200":
        # ground truth: the electrode really was off at the moment the event was admitted
        assert [trace.poor_at(t) for t in out.activations] == [200]
    elif scenario == "contaminated_26":
        assert [trace.poor_at(t) for t in out.activations] == [26]
    elif scenario == "contact_never_reported":
        assert [trace.poor_at(t) for t in out.activations] == [None]
    elif scenario in ("bad_checksum", "torn_packet"):
        assert out.lost_packets >= 1                     # counted, yet no gate consulted it


def _xfail_param(scenario: str) -> Any:
    return pytest.param(scenario, marks=pytest.mark.xfail(
        strict=True, raises=AssertionError, reason=UNSAFE[scenario][1]))


@pytest.mark.parametrize("scenario", [_xfail_param(s) for s in sorted(UNSAFE)])
def test_safe_property_no_activation_while_health_is_untrusted(drive, scenario) -> None:
    """ADR-v2-155 decision 2-4: an untrusted read, nonzero/unknown/stale contact or a
    rejected frame suppresses events. Strict xfail until #828/#829 land."""
    spec, _why = UNSAFE[scenario]
    assert drive("daemon", spec).activations == []


def test_garbage_bytes_inside_the_pair_are_skipped_and_the_pair_admitted(drive) -> None:
    """Pinned as-is: 120 non-sync bytes between the blinks are skipped (counted in
    ``skipped_bytes``, not in ``lost_packets``) and the pair is admitted. ADR-v2-155 leaves
    whether "a lone extraneous framing byte" vetoes the batch to the implementation, so this
    is neither marked safe nor unsafe."""
    out = drive("daemon", _spec(garbage=(em.Garbage(PAIR_AT + 0.25, 120),)))
    assert out.skipped_bytes == 120 and out.lost_packets == 0
    assert len(out.activations) == 1


def test_whole_packet_loss_compresses_time_into_a_false_double_blink(drive) -> None:
    """Two blinks 0.9 s apart are *not* a double blink (window 0.6 s) - control: no event.
    Lose 0.4 s of whole packets between them and ``t0`` (delivered samples / 512) closes the
    gap to 0.5 s: the pair is admitted, and no layer can see why - no checksum fails, the
    0.4 s silence is below the 1.5 s stall limit, and 4 % missing samples is inside the 10 %
    arrival-rate tolerance. ADR-v2-155 "Context": ``t0`` is an index, not proof that no
    sample was lost. Pinned as current behaviour; the torn-packet variant, which the parser
    *can* see, is in UNSAFE."""
    apart = (em.Blink(PAIR_AT), em.Blink(PAIR_AT + 0.9))
    control = drive("daemon", _spec(blinks=apart))
    assert control.activations == []
    lossy = drive("daemon", _spec(blinks=apart, stalls=(em.Stall(PAIR_AT + 0.35, 0.4,
                                                                   drop=True),)))
    assert lossy.lost_packets == 0 and lossy.violations == {}
    assert len(lossy.activations) == 1


@pytest.mark.parametrize(("loss", "violations", "activations"), [
    (0.05, set(), 1),
    (0.125, {"arrival_drift"}, 0),
], ids=["5pct", "12.5pct"])
def test_sustained_checksum_loss_is_seen_only_by_the_arrival_rate_check(
        drive, loss, violations, activations) -> None:
    """One raw packet in 20 (or in 8) fails its checksum for 28 s; a pair at 20 s.

    Pinned as-is. 5 %: 717 packets lost, no layer reacts and the pair is admitted (the
    ``bad_checksum`` row of UNSAFE is the strict-xfail statement of why that is wrong).
    12.5 %: the arrival rate falls outside the guard's 10 % tolerance and it flags
    ``arrival_drift``; the pair is not detected at all in this trace (nothing is refused),
    so the 0 is the detector's, not the gate's."""
    step = 1.0 / (loss * em.FS)
    spec = em.TraceSpec(seconds=30.0, seed=4, blinks=em.double_blink(20.0),
                        corrupt=tuple(em.CorruptChecksum(float(t))
                                      for t in np.arange(1.0, 29.0, step)))
    out = drive("daemon", spec)
    assert out.lost_packets == round(28.0 / step)
    assert set(out.violations) == violations
    assert len(out.activations) == activations and out.refused == {}


# ---------------------------------------------------------------- stall: where the paths differ


STALL_BURST = _spec(stalls=(em.Stall(PAIR_AT - 0.5, 2.0),))   # pair held back, then a burst


@pytest.mark.parametrize(("path", "expected"), [("daemon", 0), ("monitor", 0),
                                                ("field_test", 1)])
def test_a_bluetooth_stall_burst_is_refused_only_where_the_guard_runs(drive, path,
                                                                      expected) -> None:
    """2 s of silence, then the held-back bytes (the pair among them) in one burst.

    The guarded paths flag a ``stall``; field-test, which reads the bare source, accepts
    the pair - the parity gap the spec describes (#830). The two guarded paths refuse it by
    *different* mechanisms: the daemon's runner sees a block gap above its 1.5 s watchdog
    and resets the detectors, so the pair is never detected (nothing is refused); monitor
    has no runner, detects the pair and the stream gate refuses it (``stream``)."""
    out = drive(path, STALL_BURST)
    assert len(out.activations) == expected
    if path == "daemon":
        assert out.violations.get("stall", 0) >= 1 and out.refused == {}
    elif path == "monitor":
        assert out.violations.get("stall", 0) >= 1 and out.refused.get("stream", 0) >= 1
    else:
        assert out.violations == {}


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="#830: run_field_test reads the bare source, without IntegrityGuard")
def test_field_test_admits_what_the_daemon_admits(drive) -> None:
    assert (len(drive("field_test", STALL_BURST).activations)
            == len(drive("daemon", STALL_BURST).activations))


def test_contact_loss_without_a_blink_never_activates(drive) -> None:
    """Control for the UNSAFE cases: contact loss, a 0/200/0 burst, corruption and garbage
    with no blink in the waveform produce nothing on any path - the unsafe admissions above
    come from the waveform, not from the faults themselves."""
    spec = em.TraceSpec(seconds=SECONDS, seed=2,
                        poor=(em.PoorSignal(3.0, 6.0, 200),),
                        poor_bursts=(em.PoorBurst(7.0),),
                        corrupt=(em.CorruptChecksum(8.0, count=20),),
                        garbage=(em.Garbage(9.0, 300),))
    for path in PATHS:
        assert drive(path, spec).accepted == [], path


def test_field_test_report_holds_counts_only(drive) -> None:
    out = drive("field_test", _spec())
    text = json.dumps(out.report)
    assert "/dev/" not in text and "thinkgear" not in text.lower()
    assert "amplitude" not in text and "z_score" not in text
