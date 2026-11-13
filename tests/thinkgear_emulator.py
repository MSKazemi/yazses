"""A deterministic, synthetic NeuroSky ThinkGear (TGAM) byte-stream emulator for tests.

Not collected as tests (no ``test_`` prefix). It produces the bytes a TGAM-based headset
would put on its serial port, so the *real* parser, ``ThinkGearSource``, stream guard,
pipeline and runner can be driven end to end without a headset, a serial port, pyserial
or a wall clock. Everything is seeded: the same :class:`TraceSpec` always yields the same
bytes.

## What the stream looks like, and where each choice comes from

Framing is NeuroSky's "ThinkGear Communications Protocol"
(https://developer.neurosky.com/docs/doku.php?id=thinkgear_communications_protocol), the
same document ``src/yazses/biosignal/thinkgear.py`` cites:
``[AA][AA][PLENGTH][PAYLOAD][CHKSUM]`` with ``CHKSUM = ~sum(PAYLOAD) & 0xFF``. The checksum
here is computed independently and :func:`self_check` verifies it against the production
helper and the protocol document's own worked example.

* **Raw rows, 512 Hz.** The doc: code 0x80 is a 2-byte big-endian signed value the ASIC
  "outputs ... 512 times a second". Each raw value travels in its own 8-byte packet
  ``AA AA 04 80 02 HI LO CHK``. *One value per packet is an assumption* about the
  firmware (the protocol allows several rows per packet; the parser accepts both).
* **One report per second.** The doc: POOR_SIGNAL (0x02) is "typically output every
  second". The report packet carries 0x02, the 24-byte 0x83 band-power row and the
  0x04 / 0x05 eSense attention/meditation bytes, ``PLENGTH`` 0x20. *That exact grouping
  is an assumption* (it is the commonly described TGAM layout, not quoted from the doc);
  the band-power and eSense bytes are random filler the parser must walk past.
* **Vendor blink strength.** Optional undocumented 0x16 rows near each blink, which the
  parser must ignore (thinkgear.py: "any meaning of codes not in the doc's table ... is
  never interpreted").
* **Microvolts.** ``1 count = 1.8 / 4096 / 2000 V`` (NeuroSky's conversion, the production
  ``THINKGEAR_RAW_TO_UV``), so 150 µV is about 683 counts.

## The blink artefact (assumptions, labelled)

The shape and size mirror the repository's own synthetic source rather than a recording,
because no ThinkGear recording exists in this tree:

* a raised-cosine (Hann) bump ``0.30 s`` long, peak ``150 µV`` on a frontal channel -
  ``SyntheticSource._BLINK_WIDTH_S`` ("a blink artifact as one smooth ~300 ms bump (design
  choice)") and ``SyntheticSource.schedule_blink(amp=150.0)`` in
  ``src/yazses/biosignal/sources.py``;
* its FWHM (150 ms) sits inside ``BlinkDetector``'s ``min_width_s=0.10`` /
  ``max_width_s=0.40`` window, and a pair 0.35 s apart sits inside its
  ``double_window_s=0.6`` (``src/yazses/biosignal/artifacts.py``);
* background: 4 µV rms white noise plus an 8 µV, 10 Hz alpha rhythm - the ``eeg`` preset
  and ``_ALPHA_UV`` of the same synthetic source.

Real Fp1 amplitudes through a dry TGAM electrode are **unmeasured here**; treat 150 µV
as a placeholder to replace with day-1 hardware numbers, not as evidence.

## Faults it can inject

Contact loss (POOR_SIGNAL 200 reports for an interval), any POOR_SIGNAL value, a
``0 / 200 / 0`` burst of reports that lands inside one serial read, reports that stop
(stale) or never come, corrupted checksums, garbage bytes, transport stalls (bytes held
back and delivered as one burst, or lost - whole packets, or torn mid-packet), and
arbitrary chunking of bytes per read (``EmulatedSerial``).

Manual use (POSIX): ``uv run python -m tests.thinkgear_emulator`` prints a
``thinkgear:/dev/pts/N`` spec to give ``yazses biosignal monitor --source ... --blink``;
monitor needs pyserial (the ``emg`` extra).

Pure numpy + stdlib. No I/O except in :func:`main`, which writes to a pseudo-terminal
for a manual ``yazses biosignal monitor`` run (POSIX only; no network).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np

__all__ = [
    "BLINK_AMP_UV", "BLINK_WIDTH_S", "DOC_EXAMPLE", "DOUBLE_BLINK_GAP_S", "FS", "NO_CONTACT",
    "UV_PER_COUNT", "Blink", "CorruptChecksum", "EmulatedSerial", "FakeClock", "Garbage",
    "PoorBurst", "PoorSignal", "Stall", "Trace", "TraceSpec", "checksum", "double_blink",
    "generate", "packet", "poor_signal_packet", "raw_row", "self_check",
]

FS = 512.0
SYNC = 0xAA
RAW_PACKET_LEN = 8                                  # AA AA 04 80 02 HI LO CHK
UV_PER_COUNT = 1.8 / 4096.0 / 2000.0 * 1e6          # NeuroSky's conversion, ~0.2197 µV
NO_CONTACT = 200

# The protocol document's worked example: POOR_SIGNAL 0x20, BATTERY 0x7E, ATTENTION 0x12,
# MEDITATION 0x60, checksum 0xE3.
DOC_EXAMPLE = bytes.fromhex("AAAA 08 0220 017E 0412 0560 E3")

# Blink defaults: see the module docstring for where each comes from.
BLINK_AMP_UV = 150.0
BLINK_WIDTH_S = 0.30
DOUBLE_BLINK_GAP_S = 0.35


def checksum(payload: bytes | bytearray) -> int:
    """One's complement of the low byte of the payload sum (independent of production)."""
    return (~sum(payload)) & 0xFF


def packet(payload: bytes) -> bytes:
    if len(payload) > 169:
        raise ValueError("PLENGTH must be <= 169")
    return b"\xaa\xaa" + bytes([len(payload)]) + payload + bytes([checksum(payload)])


def raw_row(count: int) -> bytes:
    return b"\x80\x02" + int(count).to_bytes(2, "big", signed=True)


def poor_signal_packet(value: int) -> bytes:
    return packet(bytes([0x02, value & 0xFF]))


def self_check() -> None:
    """Raise AssertionError unless this module frames packets exactly as production parses them."""
    from yazses.biosignal.thinkgear import ThinkGearParser, thinkgear_checksum

    assert checksum(DOC_EXAMPLE[3:-1]) == thinkgear_checksum(DOC_EXAMPLE[3:-1]) == 0xE3
    assert packet(DOC_EXAMPLE[3:-1]) == DOC_EXAMPLE
    for value in (0, 1, -1, 683, -683, 32767, -32768):
        p = packet(raw_row(value))
        assert len(p) == RAW_PACKET_LEN
        assert ThinkGearParser().feed(p)[0].raw == (value,)


# ====================================================================================
# trace description
# ====================================================================================


@dataclass(frozen=True)
class Blink:
    """One blink artefact starting at ``t`` (s): a Hann bump ``width_s`` long, ``amp_uv`` peak."""

    t: float
    amp_uv: float = BLINK_AMP_UV
    width_s: float = BLINK_WIDTH_S


def double_blink(t: float, gap_s: float = DOUBLE_BLINK_GAP_S, **kw: float) -> tuple[Blink, Blink]:
    """Two blinks whose onsets (and so peaks) are ``gap_s`` apart."""
    return Blink(t, **kw), Blink(t + gap_s, **kw)


@dataclass(frozen=True)
class PoorSignal:
    """Every 1 Hz report in ``[start, end)`` carries ``value`` (200 = no skin contact)."""

    start: float
    end: float
    value: int = NO_CONTACT


@dataclass(frozen=True)
class PoorBurst:
    """Extra POOR_SIGNAL packets, back to back, inserted at ``t`` (e.g. 0, 200, 0).

    They are adjacent on the wire, so unless the transport splits them they arrive in one
    serial read - the case where only the *last* value survives in ``source.poor_signal``.
    """

    t: float
    values: tuple[int, ...] = (0, NO_CONTACT, 0)


@dataclass(frozen=True)
class CorruptChecksum:
    """Flip one bit of the checksum of ``count`` consecutive raw packets from ``t`` on."""

    t: float
    count: int = 1


@dataclass(frozen=True)
class Garbage:
    """``nbytes`` random bytes inserted at ``t``. 0xAA is excluded unless ``allow_sync``,
    so the garbage cannot by chance frame a packet the test did not ask for."""

    t: float
    nbytes: int
    allow_sync: bool = False


@dataclass(frozen=True)
class Stall:
    """Nothing arrives in ``[t, t + dur)``. ``drop=False``: those bytes are held back and
    delivered as one burst at ``t + dur`` (Bluetooth buffering). ``drop=True``: they are
    lost in transport and never delivered. ``tear=True`` (with ``drop``): the first lost
    raw packet is cut after 5 bytes instead of vanishing whole, so the parser sees one
    broken frame at the cut - a loss in the middle of a packet."""

    t: float
    dur: float
    drop: bool = False
    tear: bool = False


@dataclass(frozen=True)
class TraceSpec:
    seconds: float
    seed: int = 0
    noise_uv: float = 4.0
    alpha_uv: float = 8.0
    alpha_hz: float = 10.0
    mains_uv: float = 0.0
    mains_hz: float = 50.0
    blinks: tuple[Blink, ...] = ()
    poor: tuple[PoorSignal, ...] = ()
    poor_bursts: tuple[PoorBurst, ...] = ()
    corrupt: tuple[CorruptChecksum, ...] = ()
    garbage: tuple[Garbage, ...] = ()
    stalls: tuple[Stall, ...] = ()
    # Value of every report outside a PoorSignal interval.
    baseline_poor: int = 0
    # First report at ``report_phase_s``, then every ``report_period_s``. ``None``
    # period: the headset never reports POOR_SIGNAL at all.
    report_period_s: float | None = 1.0
    report_phase_s: float = 0.5
    # No report at or after this time (stale contact metadata); None = reports throughout.
    report_until_s: float | None = None
    esense: bool = True
    vendor_blink_rows: bool = True


# ====================================================================================
# the generated trace
# ====================================================================================


@dataclass(frozen=True)
class Trace:
    """The bytes, when each byte becomes available, and the ground truth behind them."""

    spec: TraceSpec
    data: bytes
    frame_end: np.ndarray            # cumulative byte offset at the end of each frame
    frame_time: np.ndarray           # arrival time of each frame (non-decreasing)
    counts: np.ndarray               # the intended raw values (int16), before any fault
    report_times: tuple[float, ...]  # wire time of each delivered POOR_SIGNAL value ...
    report_values: tuple[int, ...]   # ... and the value, in wire order (bursts included)
    corrupted_packets: int           # checksum-flipped raw packets, as rendered
    dropped_packets: int             # raw packets a ``Stall(drop=True)`` never delivers

    @property
    def end_time(self) -> float:
        return float(self.frame_time[-1]) if self.frame_time.size else 0.0

    def available_at(self, t: float) -> int:
        """Bytes that have arrived by time ``t``."""
        k = int(np.searchsorted(self.frame_time, t, side="right"))
        return int(self.frame_end[k - 1]) if k else 0

    def poor_at(self, t: float) -> int | None:
        """The latest POOR_SIGNAL value on the wire at or before time ``t`` (``None``
        before the first report): ground truth for "contact at that moment". Wire time
        equals the source's stream time only while no packet has been lost."""
        k = int(np.searchsorted(np.asarray(self.report_times), t, side="right"))
        return self.report_values[k - 1] if k else None

    def poor_values_between(self, t0: float, t1: float) -> tuple[int, ...]:
        """Every POOR_SIGNAL value on the wire in ``[t0, t1]``."""
        return tuple(v for t, v in zip(self.report_times, self.report_values) if t0 <= t <= t1)


def _signal_uv(spec: TraceSpec, n: int, rng: np.random.Generator) -> np.ndarray:
    t = np.arange(n) / FS
    x = rng.normal(0.0, spec.noise_uv, n) if spec.noise_uv > 0 else np.zeros(n)
    if spec.alpha_uv > 0:
        x += spec.alpha_uv * np.sin(2 * np.pi * spec.alpha_hz * t + rng.uniform(0, 2 * np.pi))
    if spec.mains_uv > 0:
        x += spec.mains_uv * np.sin(2 * np.pi * spec.mains_hz * t + rng.uniform(0, 2 * np.pi))
    for b in spec.blinks:
        u = (t - b.t) / b.width_s
        x += b.amp_uv * np.where((u >= 0) & (u <= 1), 0.5 - 0.5 * np.cos(2 * np.pi * u), 0.0)
    return x


def _raw_packets(counts: np.ndarray) -> np.ndarray:
    """(n, 8) uint8: one ``AA AA 04 80 02 HI LO CHK`` packet per raw value."""
    u = counts.astype(np.int16).view(np.uint16)
    hi = (u >> 8).astype(np.uint8)
    lo = (u & 0xFF).astype(np.uint8)
    p = np.empty((counts.size, RAW_PACKET_LEN), dtype=np.uint8)
    p[:, 0] = SYNC
    p[:, 1] = SYNC
    p[:, 2] = 0x04
    p[:, 3] = 0x80
    p[:, 4] = 0x02
    p[:, 5] = hi
    p[:, 6] = lo
    p[:, 7] = (~(0x82 + hi.astype(np.int64) + lo.astype(np.int64))) & 0xFF
    return p


def _report_payload(poor: int, spec: TraceSpec, rng: np.random.Generator) -> bytes:
    if not spec.esense:
        return bytes([0x02, poor & 0xFF])
    bands = rng.integers(0, 256, 24, dtype=np.uint8).tobytes()
    attention, meditation = (int(v) for v in rng.integers(0, 101, 2))
    return bytes([0x02, poor & 0xFF, 0x83, 0x18]) + bands + bytes([0x04, attention,
                                                                    0x05, meditation])


def _poor_value(spec: TraceSpec, t: float) -> int:
    value = spec.baseline_poor
    for p in spec.poor:
        if p.start <= t < p.end:
            value = p.value
    return value


def generate(spec: TraceSpec) -> Trace:
    """Render ``spec`` into bytes. Deterministic for a given spec."""
    if spec.seconds <= 0:
        raise ValueError("seconds must be > 0")
    rng = np.random.default_rng(spec.seed)
    filler = np.random.default_rng([spec.seed, 1])       # eSense/garbage bytes: own stream
    n = int(round(spec.seconds * FS))
    counts = np.clip(np.round(_signal_uv(spec, n, rng) / UV_PER_COUNT), -32768, 32767)
    counts = counts.astype(np.int16)
    raw = _raw_packets(counts)

    corrupted = 0
    for c in spec.corrupt:
        j = int(round(c.t * FS))
        hit = raw[j:j + c.count]
        hit[:, 7] ^= 0x01
        corrupted += hit.shape[0]

    # Inserted frames: (sample index they precede, order, bytes, label, value)
    inserts: list[tuple[int, int, bytes, str, int]] = []
    order = 0
    if spec.report_period_s is not None:
        t = spec.report_phase_s
        stop = spec.seconds if spec.report_until_s is None else min(spec.seconds,
                                                                     spec.report_until_s)
        while t < stop:
            value = _poor_value(spec, t)
            inserts.append((int(round(t * FS)), order, packet(_report_payload(value, spec, filler)),
                            "poor", value))
            order += 1
            t += spec.report_period_s
    for burst in spec.poor_bursts:
        for v in burst.values:
            inserts.append((int(round(burst.t * FS)), order, poor_signal_packet(v), "poor", v))
            order += 1
    if spec.vendor_blink_rows:
        for blink in spec.blinks:
            strength = int(min(255, max(1, blink.amp_uv)))
            inserts.append((int(round((blink.t + blink.width_s) * FS)), order,
                            packet(bytes([0x16, strength])), "vendor", strength))
            order += 1
    for g in spec.garbage:
        pool = np.arange(256, dtype=np.uint8)
        if not g.allow_sync:
            pool = pool[pool != SYNC]
        junk = filler.choice(pool, g.nbytes).astype(np.uint8).tobytes()
        inserts.append((int(round(g.t * FS)), order, junk, "garbage", 0))
        order += 1
    for stall in spec.stalls:
        if stall.drop and stall.tear:
            j = int(round(stall.t * FS))
            if j < n:
                inserts.append((j, order, raw[j].tobytes()[:5], "torn", 0))
                order += 1
    inserts.sort(key=lambda r: (r[0], r[1]))

    def arrival(t: float) -> float | None:
        """When something on the wire at ``t`` arrives (None: lost in transport)."""
        for stall in spec.stalls:
            if stall.t <= t < stall.t + stall.dur:
                return None if stall.drop else stall.t + stall.dur
        return t

    chunks: list[bytes] = []
    ends: list[np.ndarray] = []
    times: list[np.ndarray] = []
    offset = 0
    dropped = 0
    report_times: list[float] = []
    report_values: list[int] = []

    def emit_raw(lo: int, hi: int) -> None:
        nonlocal offset, dropped
        if hi <= lo:
            return
        idx = np.arange(lo, hi)
        t_wire = idx / FS
        t_arr = (idx + 1) / FS                        # a packet is complete after its sample
        keep = np.ones(idx.size, dtype=bool)
        for stall in spec.stalls:
            hit = (t_wire >= stall.t) & (t_wire < stall.t + stall.dur)
            if stall.drop:
                keep &= ~hit
            else:
                t_arr = np.where(hit, stall.t + stall.dur, t_arr)
        dropped += int((~keep).sum())
        block = raw[lo:hi][keep]
        if block.shape[0] == 0:
            return
        chunks.append(block.tobytes())
        ends.append(offset + RAW_PACKET_LEN * np.arange(1, block.shape[0] + 1, dtype=np.int64))
        times.append(t_arr[keep].astype(np.float64))
        offset += block.size

    prev = 0
    for idx, _, frame, label, value in inserts:
        idx = min(max(idx, 0), n)
        emit_raw(prev, idx)
        prev = idx
        t_wire = idx / FS
        when = t_wire if label == "torn" else arrival(t_wire)
        if when is None:
            continue
        if label == "poor":
            report_times.append(t_wire)
            report_values.append(value)
        chunks.append(frame)
        offset += len(frame)
        ends.append(np.array([offset], dtype=np.int64))
        times.append(np.array([max(when, t_wire)], dtype=np.float64))
    emit_raw(prev, n)

    frame_end = np.concatenate(ends) if ends else np.empty(0, dtype=np.int64)
    frame_time = np.maximum.accumulate(np.concatenate(times)) if times else np.empty(0)
    return Trace(spec=spec, data=b"".join(chunks), frame_end=frame_end, frame_time=frame_time,
                 counts=counts, report_times=tuple(report_times),
                 report_values=tuple(report_values), corrupted_packets=corrupted,
                 dropped_packets=dropped)


# ====================================================================================
# transport
# ====================================================================================


class FakeClock:
    """A monotonic clock the test owns. Thread-safe enough for a float read."""

    def __init__(self, t: float = 1000.0) -> None:
        self.t = float(t)

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        if not dt >= 0:
            raise ValueError("a monotonic clock does not go back")
        self.t += dt


@dataclass
class EmulatedSerial:
    """A pyserial-shaped port that plays a :class:`Trace` against an injected clock.

    Each ``read()`` first advances ``clock`` by ``poll_s`` - the caller's polling period -
    then returns the bytes that have arrived by then and not yet been read, at most
    ``size`` and, when ``chunk_sizes`` is set, at most a seeded random chunk size drawn
    from that inclusive range, so packets are split at arbitrary byte positions across
    reads. Stream time 0 is the clock value at the first read.

    Once every byte has been read and ``tail_s`` more seconds have passed, each further
    read calls ``on_exhausted`` (if given): a test uses it to stop a runner, or raises
    ``KeyboardInterrupt`` to end a CLI loop the way Ctrl-C does.
    """

    trace: Trace
    clock: FakeClock
    poll_s: float = 1.0 / 32.0
    chunk_sizes: tuple[int, int] | None = None
    seed: int = 0
    tail_s: float = 0.0
    on_exhausted: Callable[[], None] | None = None
    pos: int = 0
    reads: int = 0
    closed: bool = False
    _t0: float | None = field(default=None, repr=False)
    _rng: np.random.Generator = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._rng = np.random.default_rng([self.seed, 7])

    @property
    def stream_time(self) -> float:
        return 0.0 if self._t0 is None else self.clock() - self._t0

    @property
    def in_waiting(self) -> int:
        if self._t0 is None:
            return 0
        return max(0, self.trace.available_at(self.stream_time) - self.pos)

    def read(self, size: int = 1) -> bytes:
        if self.closed:
            raise OSError("port closed")
        if self._t0 is None:
            self._t0 = self.clock()
        else:
            self.clock.advance(self.poll_s)
        self.reads += 1
        now = self.stream_time
        avail = self.trace.available_at(now) - self.pos
        n = min(avail, int(size))
        if self.chunk_sizes is not None and n > 0:
            lo, hi = self.chunk_sizes
            n = min(n, int(self._rng.integers(lo, hi + 1)))
        out = self.trace.data[self.pos:self.pos + n]
        self.pos += len(out)
        if (self.pos >= len(self.trace.data) and now >= self.trace.end_time + self.tail_s
                and self.on_exhausted is not None):
            self.on_exhausted()
        return out

    def close(self) -> None:
        self.closed = True


# ====================================================================================
# manual use: a pseudo-terminal a human can point `yazses biosignal monitor` at
# ====================================================================================


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m tests.thinkgear_emulator`` - stream a synthetic trace on a pty (POSIX).

    Prints the pty path; run ``yazses biosignal monitor --source thinkgear:<path> --blink``
    in another terminal. Synthetic bytes only, paced in real time; no network.
    """
    import argparse
    import os
    import sys
    import time

    ap = argparse.ArgumentParser(description=main.__doc__)
    ap.add_argument("--seconds", type=float, default=120.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--double-blink-every", type=float, default=8.0,
                    help="seconds between scripted double blinks (0 = none)")
    ap.add_argument("--contact-loss", type=float, nargs=2, metavar=("START", "END"),
                    help="report POOR_SIGNAL 200 between these stream seconds")
    args = ap.parse_args(argv)
    if sys.platform == "win32":
        print("A pseudo-terminal needs Linux or macOS.", file=sys.stderr)
        return 2
    import pty
    import tty

    blinks: list[Blink] = []
    if args.double_blink_every > 0:
        t = 4.0
        while t + 1.0 < args.seconds:
            blinks.extend(double_blink(t))
            t += args.double_blink_every
    poor = (PoorSignal(*args.contact_loss),) if args.contact_loss else ()
    trace = generate(TraceSpec(seconds=args.seconds, seed=args.seed, blinks=tuple(blinks),
                               poor=poor))
    controller, follower = pty.openpty()
    tty.setraw(follower)
    print(f"thinkgear:{os.ttyname(follower)}", flush=True)
    started = time.monotonic()
    pos = 0
    try:
        while pos < len(trace.data):
            time.sleep(1.0 / 64.0)
            end = trace.available_at(time.monotonic() - started)
            if end > pos:
                os.write(controller, trace.data[pos:end])
                pos = end
    except KeyboardInterrupt:
        pass
    finally:
        os.close(controller)
        os.close(follower)
    return 0


if __name__ == "__main__":  # pragma: no cover - manual tool
    raise SystemExit(main())

