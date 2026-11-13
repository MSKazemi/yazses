"""A synthetic ThinkGear headset, end to end through the real blink switch.

``tests/thinkgear_emulator.py`` renders a seeded, protocol-faithful TGAM byte stream (512 Hz
raw packets, a POOR_SIGNAL/eSense report each second, scripted blink artefacts and
transport faults); ``EmulatedSerial`` plays it against a fake clock. This file drives that
stream through the three places a headset's blocks reach a detector, each exactly as the
product composes it - since #830 all three through ``source_gates``:

* **daemon** - ``runner.build_runner_from_config`` -> ``BiosignalRunner.run``: ``open_source``
  -> ``IntegrityGuard`` (arrival-rate check on) -> ``SourceHealthGate(IntegrityGate)`` ->
  ``BiosignalPipeline``;
* **monitor** - ``cli_impl.run_monitor``: the same guard and gates, its own pipeline;
* **field-test** - ``cli_impl.run_field_test``: the same guard and gates, no runner.

Only these are replaced, none of them policy: the serial port (``_open_serial`` returns
the emulated port), the clocks of the source's health state, the guard and the runner (the
fake clock), and the runner's idle sleep (0, so a test does not wait for wall time).
Detector thresholds, gates and the pipeline are untouched. Spies record what each layer
did: the source's health verdict per block, the reason the pipeline logs for every refused
event, and the pipeline/detector resets.

## What is asserted

ADR-v2-155's safety properties, as plain tests: no activation from an untrusted read, on
every path, with the layer that stopped it and the same reasons on all three paths. Two
things are pinned as measured rather than as properties: the reconnect false negative
(a pair made while the source rearms is held) and one KNOWN LIMIT (whole-packet loss
compresses time; no layer can see it).

Everything is synthetic and offline: no device, no network, no recording of a person.
"""

from __future__ import annotations

import collections
import dataclasses
import json
import logging
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
from yazses.biosignal.artifacts import BlinkDetector
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


def test_a_0_200_0_burst_inside_one_read_taints_that_read() -> None:
    """``poor_signal`` still shows only the latest value (0), but the read's health verdict
    counts the 200 in wire order and is untrusted (#828): a final zero does not rescue it."""
    trace = em.generate(em.TraceSpec(seconds=3.0, poor_bursts=(em.PoorBurst(1.6),)))
    clock = em.FakeClock()
    port = em.EmulatedSerial(trace, clock, poll_s=0.5)
    src = ThinkGearSource(SPEC, serial_factory=lambda: port, clock=clock)
    src.start()
    seen = []
    for _ in range(8):
        block = src.read()
        verdict = src.health_for(block) if block is not None else None
        seen.append((src.poor_signal, verdict))
    assert trace.poor_values_between(1.5, 1.7) == (0, 0, 200, 0)
    assert 200 not in [poor for poor, _ in seen]         # the attribute never shows it ...
    tainted = [v for _, v in seen if v is not None and v.nonzero_quality_reports]
    assert len(tainted) == 1                             # ... the verdict of its read does
    assert not tainted[0].trusted and tainted[0].reason.value == "no_contact"


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
    refused: dict[str, int]                # pipeline gate refusals by category (quality/stream)
    refusal_reasons: list[str]             # the gate's own reason for each refused event
    violations: dict[str, int]             # stream-integrity violations
    health: dict[str, int]                 # source-health reason -> blocks judged with it
    first_trusted_t: float | None          # stream t0 of the first block the source trusted
    runner_resets: int                     # pipeline.reset() calls (the runner's gap reset)
    source_resets: int                     # detector resets asked by source health: a new
                                           # fault epoch, or trust returning (e5ad4b6a)
    lost_packets: int
    skipped_bytes: int
    labels: list[str]                      # daemon intents
    report: dict[str, Any] | None          # field-test payload

    @property
    def activations(self) -> list[float]:
        return [t for kind, t in self.accepted if kind == "double_blink"]

    def refused_by(self, prefix: str) -> int:
        return sum(1 for r in self.refusal_reasons if r.startswith(prefix))


class _RefusalLog(logging.Handler):
    """Collects the reason the pipeline logs for each event a gate refused."""

    _PREFIX = "Biosignal event "

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.reasons: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        msg = record.getMessage()
        if msg.startswith(self._PREFIX) and " dropped: " in msg:
            self.reasons.append(msg.split(" dropped: ", 1)[1])


def _cfg() -> Config:
    cfg = Config()
    cfg.biosignal = dataclasses.replace(BiosignalConfig(), enabled=True, source=SPEC,
                                        double_blink=True, jaw_clench=False, emg=False)
    return cfg


def _run_path(path: str, m: pytest.MonkeyPatch, stop_hook: list[Callable[[], None]],
              data_dir: Path) -> tuple[list[str], dict[str, Any] | None]:
    """Run one of the three product paths to the end of the trace; (daemon intents, report)."""
    labels: list[str] = []
    if path == "daemon":
        runner = build_runner_from_config(
            _cfg(), RunnerCallbacks(on_intent=lambda i: labels.append(i.label)), ledger_path="")
        assert runner is not None
        stop_hook.append(runner.stop)
        runner.run()
        assert runner.status()["last_error"] == ""
        return labels, None

    def interrupt() -> None:
        raise KeyboardInterrupt              # what Ctrl-C does to both CLI loops

    stop_hook.append(interrupt)
    data_dir.mkdir()
    if path == "monitor":
        assert cli_impl.run_monitor(_cfg(), data_dir, blink=True, emg=False, clench=False) == 0
        return labels, None
    from yazses.biosignal import fieldtest

    payloads: list[dict[str, Any]] = []
    real_dict = fieldtest.report_to_dict

    def keep(rep: Any) -> dict[str, Any]:
        payloads.append(real_dict(rep))
        return payloads[-1]

    m.setattr(fieldtest, "report_to_dict", keep)
    assert cli_impl.run_field_test(_cfg(), data_dir, as_json=True) == 0
    return labels, payloads[0]


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
            # The source's own health clock (contact TTL, stall while rearming) is the fake
            # one too: on the wall clock a 12 s trace replays in ~0.3 s and nothing ages.
            src = real_open(text, **{"clock": clock, **kw})
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
        real_reset = BiosignalPipeline.reset
        health: collections.Counter[str] = collections.Counter()
        first_trusted: list[float] = []
        resets: list[str] = []

        def process(self: BiosignalPipeline, block: Any) -> Any:
            if not any(p is self for p in pipelines):
                pipelines.append(self)
            verdict = guards[0].health_for(block) if guards else None
            if verdict is not None:
                health[verdict.reason.value] += 1
                if verdict.trusted and not first_trusted:
                    first_trusted.append(float(block.t0))
            result = real_process(self, block)
            accepted.extend((e.kind.value, round(float(e.t), 3)) for e in result.events)
            return result

        def reset(self: BiosignalPipeline, *a: Any, **kw: Any) -> Any:
            resets.append("reset")             # the runner's stream-gap / backlog reset
            return real_reset(self, *a, **kw)

        real_det_reset = BlinkDetector.reset
        detector_resets: list[str] = []

        def det_reset(self: BlinkDetector) -> None:
            # By the runner (inside pipeline.reset) or by a new source-health fault epoch.
            detector_resets.append("reset")
            real_det_reset(self)

        refusals = _RefusalLog()
        pipeline_log = logging.getLogger("yazses.biosignal.pipeline")

        with monkeypatch.context() as m:
            m.setattr(thinkgear_mod, "_open_serial", lambda port_name, baud: port)
            m.setattr(sources_mod, "open_source", open_source)
            m.setattr(integrity_mod, "IntegrityGuard", ClockedGuard)
            m.setattr(runner_mod, "BiosignalRunner", ClockedRunner)
            m.setattr(BiosignalPipeline, "process", process)
            m.setattr(BiosignalPipeline, "reset", reset)
            m.setattr(BlinkDetector, "reset", det_reset)
            # Every refusal is logged (DEBUG) with the gate's own reason, which names the
            # layer that refused it ("source health: ...", "stream integrity: ...").
            old_level = pipeline_log.level
            pipeline_log.setLevel(logging.DEBUG)
            pipeline_log.addHandler(refusals)
            try:
                labels, report = _run_path(path, m, stop_hook, tmp_path / f"run{next(counter)}")
            finally:
                pipeline_log.removeHandler(refusals)
                pipeline_log.setLevel(old_level)
        assert port.pos == len(trace.data), "the run ended before the trace did"
        assert len(opened) == 1 and len(pipelines) == 1
        assert len(guards) == 1                          # one guard on every path (#830)
        src = opened[0]
        return Outcome(
            path=path, accepted=accepted,
            refused=dict(pipelines[0].status.dropped_by_reason),
            refusal_reasons=refusals.reasons,
            violations=dict(guards[0].report.as_dict()["violations"]),
            health=dict(health), first_trusted_t=first_trusted[0] if first_trusted else None,
            runner_resets=len(resets),
            source_resets=len(detector_resets) - len(resets), lost_packets=src.lost_packets,
            skipped_bytes=src.parser.stats.skipped_bytes, labels=labels, report=report)

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
    # The rearm rule (two zero reports + 1 s clean) trusts the stream from the read after
    # the 1.5 s report; nothing was refused. The one source reset is at that first trusted
    # block: nothing seen before it may feed an event.
    assert out.first_trusted_t == pytest.approx(1.5, abs=POLL_S)
    assert set(out.health) == {"unknown_contact", "rearming", "trusted"}
    assert out.refusal_reasons == [] and out.runner_resets == 0 and out.source_resets == 1
    if path == "daemon":
        assert out.labels == ["undo"]                    # the default intent, once
    if path == "field_test":
        assert out.report is not None
        rest = next(p for p in out.report["phases"] if p["name"] == "rest")
        assert rest["phantom_activations"] == 1          # a no-intent phase: it is a phantom


@pytest.mark.parametrize(("onset", "activations", "refusals"), [
    (1.5, 0, []),                       # before trust: never detected
    (2.5, 0, []),                       # inside the detector's warm-up, restarted at 1.5 s
    (3.2, 0, []),
    (3.4, 1, []),                       # the earliest accepted onset on a 0.2 s grid
])
def test_how_soon_after_start_a_clean_double_blink_can_activate(drive, onset, activations,
                                                                 refusals) -> None:
    """Pinned as measured (daemon path). Source health trusts the stream from 1.5 s (the
    second zero report). The pipeline resets its detectors and filters at that first
    trusted block (e5ad4b6a: nothing seen before trust may feed an event), so the
    detector's 2 s warm-up runs from 1.5 s and limits the first activation. Before that
    fix the earliest accepted onset was 2.5 s; it is now 3.4 s."""
    out = drive("daemon", _spec(blinks=em.double_blink(onset)))
    assert out.first_trusted_t == pytest.approx(1.5, abs=POLL_S)
    assert len(out.activations) == activations
    assert sorted(set(out.refusal_reasons)) == refusals


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

# Which layer stops a pair, as these tests name it:
#   VETO   - the pair is detected and the source-health gate refuses it, with its reason;
#   RESET  - the fault starts a new source-health epoch, which resets the detector
#            (ADR-v2-155 decision 3: no pairing across a fault), so the pair is never
#            detected - nothing is refused, because nothing was emitted;
#   STALL  - the stream-integrity guard refuses it ("stream integrity: stall ...");
#   RUNNER - the daemon runner sees a block gap above its watchdog and resets the pipeline.
VETO, RESET = "veto", "reset"


@dataclasses.dataclass(frozen=True)
class Untrusted:
    spec: em.TraceSpec
    layer: str             # VETO or RESET
    health: str            # the source-health reason the fault produces
    issue: str             # the issue that made it safe


# Each case was admitted on every path before #828-#830 (see the commit's before/after).
UNTRUSTED: dict[str, Untrusted] = {
    # Electrode off the skin (POOR_SIGNAL 200 on every report) while the raw waveform still
    # carries a double blink - e.g. a lifted electrode picking up movement.
    "no_contact_200": Untrusted(_spec(poor=(em.PoorSignal(2.0, SECONDS, 200),)),
                                VETO, "no_contact", "#829"),
    # "any nonzero value indicates that some sort of noise contamination is detected"
    "contaminated_26": Untrusted(_spec(poor=(em.PoorSignal(2.0, SECONDS, 26),)),
                                 VETO, "contact_contaminated", "#829"),
    # The headset never sends POOR_SIGNAL: contact is unknown for the whole session.
    "contact_never_reported": Untrusted(_spec(report_period_s=None),
                                        VETO, "unknown_contact", "#829"),
    # 0, 200, 0 inside one read, between the two blinks of the pair.
    "burst_0_200_0": Untrusted(_spec(poor_bursts=(em.PoorBurst(PAIR_AT + 0.2),)),
                               RESET, "no_contact", "#828"),
    # A checksum failure just before the pair: the packet is dropped, t0 stays contiguous.
    "bad_checksum": Untrusted(_spec(corrupt=(em.CorruptChecksum(PAIR_AT - 0.05, count=3),)),
                              RESET, "corrupt_packet", "#828"),
    # A loss in the middle of a packet between the blinks (visible: one bad checksum).
    "torn_packet": Untrusted(
        _spec(stalls=(em.Stall(PAIR_AT + 0.25, 0.02, drop=True, tear=True),)),
        RESET, "corrupt_packet", "#828"),
    # 120 non-sync bytes between the blinks: skipped framing bytes taint the read.
    "garbage_120B": Untrusted(_spec(garbage=(em.Garbage(PAIR_AT + 0.25, 120),)),
                              RESET, "corrupt_packet", "#828"),
    # Reports at 0.5 and 1.5 s (enough to trust the stream), then none: stale after 4.5 s,
    # before the pair. (The first version of this case stopped at 1.5 s, which left one
    # zero report - the stream never became trusted, so it tested rearming, not staleness.)
    "contact_report_stale": Untrusted(_spec(report_until_s=2.0),
                                      RESET, "contact_stale", "#829"),
}


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("scenario", sorted(UNTRUSTED))
def test_no_activation_while_source_health_is_untrusted(drive, scenario, path) -> None:
    """ADR-v2-155 decisions 2-4, on every path: an untrusted read, nonzero, unknown or stale
    contact, or a rejected frame never yields an activation, and the layer that stops it
    is the source-health gate - not the stream guard (which sees nothing wrong here), not
    the runner."""
    case = UNTRUSTED[scenario]
    out = drive(path, case.spec)
    assert out.activations == []
    assert out.health.get(case.health, 0) >= 1
    assert out.violations == {} and out.runner_resets == 0
    if case.layer == VETO:
        assert out.refusal_reasons and all(
            r.startswith(f"source health: {case.health}") for r in out.refusal_reasons)
        assert out.refused == {"quality": len(out.refusal_reasons)}
    else:
        assert out.refusal_reasons == [] and out.source_resets >= 1
    if scenario == "contact_never_reported":
        assert out.first_trusted_t is None               # no zero report, no trust, ever


@pytest.mark.parametrize("scenario", sorted(UNTRUSTED))
def test_the_three_paths_give_the_same_verdict_and_reasons(drive, scenario) -> None:
    """ADR-v2-155 acceptance: field-test, monitor and daemon apply the same health gate and
    report comparable reasons for the same packet sequence (#830)."""
    seen = {p: drive(p, UNTRUSTED[scenario].spec) for p in PATHS}
    keys = {p: (o.activations, o.refusal_reasons, o.health, o.source_resets)
            for p, o in seen.items()}
    assert keys["monitor"] == keys["daemon"] == keys["field_test"]


@pytest.mark.parametrize("scenario", ["no_contact_200", "contact_never_reported"])
def test_field_test_excludes_untrusted_time_from_exposure(drive, scenario) -> None:
    """Untrusted seconds are not usable exposure (ADR-v2-155 decision 5): the rest phase
    has 12 s of signal, 9 s past its 3 s settle, and all 9 are excluded."""
    rest = next(p for p in drive("field_test", UNTRUSTED[scenario].spec).report["phases"]
                if p["name"] == "rest")
    assert (rest["usable_s"], rest["excluded_s"], rest["phantom_activations"]) == (0, 9, 0)


@pytest.mark.parametrize("path", PATHS)
def test_reconnect_holds_a_pair_made_while_rearming(drive, path) -> None:
    """Documented current behaviour (a false negative by design, ADR-v2-155 "may be overly
    strict"). Contact is lost from 3 s to 5 s (POOR_SIGNAL 200 at 3.5 and 4.5 s); the zero
    reports at 5.5 and 6.5 s rearm it, and the stream is trusted from 6.5 s.

    - A pair begun at 5.5 s, wholly inside the rearm, is detected and refused as rearming.
    - A pair begun at 6.2 s has its whole first blink (6.20-6.50 s) in rearming reads. It
      must not be admitted, and it is never even detected: the pipeline resets its
      detectors and filters at the first trusted block (e5ad4b6a), so nothing seen while
      rearming feeds an event. Before that fix this pair was admitted, because the
      detector placed the first blink at 6.51 s (filter delay plus peak search, ~0.17 s
      after its samples), just after the last vetoed block.
    - The detector's 2 s warm-up restarts at that reset. Measured on seed 0, 0.1 s grid:
      onsets up to 8.3 s produce nothing, from 8.4 s accepted. One at 9.0 s is accepted.
    """
    def run(onset: float) -> Outcome:
        return drive(path, em.TraceSpec(seconds=16.0, seed=0,
                                        poor=(em.PoorSignal(3.0, 5.0, 200),),
                                        blinks=em.double_blink(onset)))

    early, straddle, late = run(5.5), run(6.2), run(9.0)
    assert early.activations == []
    assert early.refusal_reasons and all(r.startswith("source health: rearming")
                                         for r in early.refusal_reasons)
    assert straddle.activations == [] and straddle.refusal_reasons == []
    assert len(late.activations) == 1 and late.refusal_reasons == []


def test_known_limit_whole_packet_loss_compresses_time_into_a_false_double_blink(drive) -> None:
    """KNOWN LIMIT - not fixed by #828-#830, and no layer can see it.

    Two blinks 0.9 s apart are *not* a double blink (window 0.6 s) - control: no event.
    Lose 0.4 s of *whole* packets between them and ``t0`` (delivered samples / 512) closes
    the gap to 0.5 s: the pair is admitted. Nothing is visible to any check: no checksum
    fails and no byte is skipped (so source health stays trusted), the 0.4 s silence is
    below the 1.5 s stall limit, and 4 % missing samples is inside the 10 % arrival-rate
    tolerance. ADR-v2-155 "Context": ``t0`` is an index, not proof that no sample was lost.
    A loss that tears a packet *is* visible and is refused (``torn_packet`` above). If this
    test starts failing because the pair is refused, the limit was fixed: update it."""
    apart = (em.Blink(PAIR_AT), em.Blink(PAIR_AT + 0.9))
    for path in PATHS:
        control = drive(path, _spec(blinks=apart))
        assert control.activations == [], path
        lossy = drive(path, _spec(blinks=apart, stalls=(em.Stall(PAIR_AT + 0.35, 0.4,
                                                                    drop=True),)))
        assert lossy.lost_packets == 0 and lossy.violations == {}, path
        assert set(lossy.health) == {"unknown_contact", "rearming", "trusted"}, path
        assert len(lossy.activations) == 1, path


@pytest.mark.parametrize(("loss", "violations"), [(0.05, set()), (0.125, {"arrival_drift"})],
                         ids=["5pct", "12.5pct"])
def test_sustained_checksum_loss_never_activates(drive, loss, violations) -> None:
    """One raw packet in 20 (or in 8) fails its checksum for 28 s; a pair at 20 s (daemon).

    5 %: before #828 no layer reacted and the pair was admitted; now every read carries a
    reject, the source never trusts the stream and the pair is not admitted - with no help
    from the stream guard. 12.5 %: the guard's arrival-rate check also fires."""
    step = 1.0 / (loss * em.FS)
    spec = em.TraceSpec(seconds=30.0, seed=4, blinks=em.double_blink(20.0),
                        corrupt=tuple(em.CorruptChecksum(float(t))
                                      for t in np.arange(1.0, 29.0, step)))
    out = drive("daemon", spec)
    assert out.lost_packets == round(28.0 / step)
    assert set(out.violations) == violations
    assert out.activations == [] and out.first_trusted_t is None
    assert max(out.health, key=out.health.__getitem__) == "corrupt_packet"


# ---------------------------------------------------------------- stall: same count, different layer


STALL_BURST = _spec(stalls=(em.Stall(PAIR_AT - 0.5, 2.0),))   # pair held back, then a burst


@pytest.mark.parametrize("path", PATHS)
def test_a_bluetooth_stall_burst_never_activates_and_each_path_says_why(drive, path) -> None:
    """2 s of silence, then the held-back bytes (the pair among them) in one burst.

    No path admits it (before #830 field-test did). The layer differs, by construction:
    the daemon's runner sees a block gap above its 1.5 s watchdog and resets the pipeline,
    so the pair is never detected and nothing is refused; monitor and field-test have no
    runner, detect the pair, and the stream guard refuses it as a stall. Source health is
    not involved: no byte was lost, only delayed."""
    out = drive(path, STALL_BURST)
    assert out.activations == []
    assert out.violations == {"stall": 1}
    assert "corrupt_packet" not in out.health and out.source_resets == 1   # first trust
    if path == "daemon":
        assert out.runner_resets == 1 and out.refusal_reasons == []
    else:
        assert out.runner_resets == 0
        assert out.refusal_reasons == ["stream integrity: stall (no block for 1.53 s)"]
        assert out.refused == {"stream": 1}


def test_contact_loss_without_a_blink_never_activates(drive) -> None:
    """Control: contact loss, a 0/200/0 burst, corruption and garbage with no blink in the
    waveform produce nothing on any path."""
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
