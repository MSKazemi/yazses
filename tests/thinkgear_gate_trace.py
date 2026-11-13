"""Synthetic ThinkGear wire traces for the source-health gate tests (#829, #830).

A trace is a list of serial reads (bytes) paced at the nominal 512 Hz, plus a fake
monotonic clock that advances by each read's sample time. The bytes are framed by hand
from NeuroSky's protocol document (``packet`` / ``raw_row`` in ``test_biosignal_thinkgear``)
and the waveform is the deterministic synthetic EEG of ``SyntheticSource`` re-encoded as
raw counts, so nothing here comes from a recording or from the parser under test.

Contact reports (POOR_SIGNAL, 0x02) arrive once per second of samples, as on a TGAM.
``contact`` decides their value per second; ``inject`` puts extra packets (a corrupt
frame, a lone ``POOR_SIGNAL=200``) at a stream time, in wire order.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np

from tests.test_biosignal_thinkgear import FakeSerial, packet, raw_row
from yazses.biosignal.sources import SyntheticSource
from yazses.biosignal.thinkgear import THINKGEAR_FS, THINKGEAR_RAW_TO_UV, ThinkGearSource

READ_SAMPLES = 51                  # ~0.1 s per serial read at 512 Hz


def quality(value: int) -> bytes:
    return packet(bytes([0x02, value]))


def bad_checksum_raw(value: int = 9) -> bytes:
    bad = bytearray(packet(raw_row(value)))
    bad[-1] ^= 0x01
    return bytes(bad)


def blink_counts(blinks: Sequence[float], duration: float, *, seed: int = 2) -> np.ndarray:
    """Synthetic Fp1 (no mains hum) with blinks at ``blinks`` s, as int16 raw counts."""
    src = SyntheticSource("eeg", fs=THINKGEAR_FS, seed=seed, duration=duration, mains_uv=0.0)
    for t in blinks:
        src.schedule_blink(t)
    src.start()
    rows = []
    while True:
        try:
            block = src.read()
        except EOFError:
            break
        if block is not None:
            rows.append(block.data[0])
    uv = np.concatenate(rows)
    return np.clip(np.round(uv / THINKGEAR_RAW_TO_UV), -32768, 32767).astype(int)


@dataclass
class Trace:
    reads: list[bytes]
    dt: list[float]                 # clock advance before each read
    duration: float
    notes: dict[str, float] = field(default_factory=dict)


def build_trace(
    counts: np.ndarray, *,
    contact: Callable[[int], int | None] = lambda second: 0,
    inject: Sequence[tuple[float, bytes]] = (),
    read_samples: int = READ_SAMPLES,
) -> Trace:
    """Serial reads for ``counts``: one raw packet per sample, a contact report at every
    whole second (``contact(second)``; None = no report), ``inject`` packets at their
    stream times. Each read covers ``read_samples`` samples and arrives that much later."""
    fs = int(THINKGEAR_FS)
    extra: dict[int, list[bytes]] = {}
    for t, wire in inject:
        extra.setdefault(int(round(t * fs)), []).append(wire)
    reads: list[bytes] = []
    dts: list[float] = []
    n = len(counts)
    for start in range(0, n, read_samples):
        chunk = bytearray()
        for i in range(start, min(start + read_samples, n)):
            if i % fs == 0:
                value = contact(i // fs)
                if value is not None:
                    chunk += quality(value)
            for wire in extra.get(i, ()):
                chunk += wire
            chunk += packet(raw_row(int(counts[i])))
        reads.append(bytes(chunk))
        dts.append(min(read_samples, n - start) / THINKGEAR_FS)
    return Trace(reads=reads, dt=dts, duration=n / THINKGEAR_FS)


class TraceSerial(FakeSerial):
    """A fake port that hands out one trace read per ``read()`` and advances the clock;
    once the trace is spent it fails like an unplugged port (so loops end)."""

    def __init__(self, trace: Trace, clock: FakeClock) -> None:
        super().__init__(list(trace.reads))
        self._dts = list(trace.dt)
        self._clock = clock

    def read(self, size: int) -> bytes:
        if not self.chunks:
            raise OSError("trace finished")
        if self._dts:
            self._clock.t += self._dts.pop(0)
        return super().read(size)


class FakeClock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def trace_source(trace: Trace, clock: FakeClock | None = None) -> ThinkGearSource:
    """An unstarted ThinkGear source over ``trace`` with its own fake clock."""
    clk = clock or FakeClock()
    return ThinkGearSource("/dev/fake-thinkgear", serial_factory=lambda: TraceSerial(trace, clk),
                           clock=clk)
