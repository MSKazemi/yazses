"""Stream integrity: is this source keeping the *transport* contract of a ``BlockSource``?

:mod:`yazses.biosignal.quality` judges the **signal**: is this electrode flat, railed,
hum-swamped, drifting, noisy, lifted? This module judges the **stream** that carries it,
and nothing else: the promises :class:`~yazses.biosignal.types.SampleBlock` and
:class:`~yazses.biosignal.types.BlockSource` make about shape, layout, time base and rate.
A new device driver (LSL, EDF/BDF/XDF replay, a serial headband, a BLE armband) can get
every one of those wrong while producing a perfectly plausible-looking signal, and the
quality monitor would not notice, because a swapped channel order, a sampling rate that is
2 % off, or a block delivered twice all *look* like clean biosignal.

## What is checked

============== =======================================================================
structure      ``data`` is a 2-D real-numeric ndarray of ``(n_channels, n_samples)``;
               ``fs`` finite and > 0; channels non-empty, typed and uniquely named;
               ``t0`` finite. A block failing any of these is **dropped** (it cannot be
               handed to the pipeline safely) and counted.
layout         the channel set, order and kinds and ``fs`` stay what the first block
               said. A change is a violation (the detectors, filters and calibration
               were built for the old layout); the new layout is then adopted.
declared       (guard only) a block agrees with the ``fs`` / ``channels`` the source
               declares — the pipeline is *built* from the declared values.
non-finite     NaN / inf samples. Replaced by 0.0 (the package's existing convention:
               a non-finite sample is a dropout) so they cannot poison IIR filter
               state, and the block is flagged.
t0             finite and strictly increasing; contiguous with the previous block to
               within a tolerance: a jump forward is a **gap** (lost packets), a jump
               back an **overlap** (a re-sent or duplicated buffer).
rate           the sample rate *observed from t0* over a window against the nominal
               ``fs`` (a device that stamps its real clock but declares the wrong rate),
               and, opt-in for live sources, the *arrival* rate on an injectable clock.
stall          (guard only) no block for ``stall_s`` (``startup_grace_s`` before the
               first one), by an injectable clock.
============== =======================================================================

What it deliberately does **not** do: score a channel, look at amplitudes, spectra,
kurtosis or contact. :mod:`quality` already does, and doing it twice would make two
monitors disagree. Note that :mod:`quality` also tracks ``t0`` gaps and NaN — but as a
*graded* share of its window that lowers a score. Here the same facts are a binary
contract breach with a hold-off, and overlaps, rate errors and layout changes (which the
monitor ignores or silently re-learns from) are caught too.

## Policy: fail closed, recover only on clean stream

Every violation closes the gate. It reopens only after ``recover_s`` seconds of
*consecutive clean blocks* (stream time, so it does not depend on block size or on how
fast a replay runs). A source that keeps breaking the contract — a duplicated ``t0`` on
every block, a rate that is permanently off — therefore keeps the gate shut for as long
as it does. That is the point: such a stream cannot be trusted to place an event in
time, and ADR-v2-152 says a bad signal never produces an event.

Each check fires only on a *specific, checkable* breach of the written contract, never on
a heuristic about what biosignal should look like (AGENTS.md rule 9: a guard is judged on
how rarely it fires). On a correct source — :class:`~yazses.biosignal.sources.SyntheticSource`,
:class:`~yazses.biosignal.sources.FileReplaySource`, a BrainFlow board with its jitter
snapping — none of them fires.

## How the pipeline consumes it

:class:`IntegrityGuard` wraps any source and is itself a ``BlockSource``; its
:attr:`IntegrityGuard.report` is a typed :class:`IntegrityReport` (counters, the last
violation, whether the gate is closed) for ``status`` / ``doctor``. :class:`IntegrityGate`
is a drop-in for ``PipelineParts.quality``: it wraps the real quality monitor and reports
``BAD`` whenever the guard's gate was closed for the block being processed, so
``BiosignalPipeline._quality_gate`` closes — and releases a held squeeze — with **no change
to the pipeline**. A block the gate has never seen (unknown provenance) counts as closed.

## Honesty about the thresholds

Every numeric default below is an engineering choice with its reasoning next to it. None
has been tuned on recordings from a real device; they are meant to be tuned once the new
drivers meet real hardware.

Pure: numpy + stdlib only, no I/O, no threads.
"""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from yazses.biosignal.types import BlockSource, ChannelInfo, SampleBlock, SignalKind

log = logging.getLogger(__name__)

__all__ = [
    "ARRIVAL_DRIFT_TOLERANCE",
    "ARRIVAL_WINDOW_S",
    "GAP_TOLERANCE_S",
    "GAP_TOLERANCE_SAMPLES",
    "MIN_DOWNSAMPLE_RATIO",
    "RATE_DRIFT_TOLERANCE",
    "RATE_WINDOW_S",
    "RECOVER_S",
    "STALL_S",
    "STARTUP_GRACE_S",
    "BlockVerdict",
    "GatedQualityReport",
    "IntegrityGate",
    "IntegrityGuard",
    "IntegrityReport",
    "IntegrityThresholds",
    "IntegrityViolation",
    "LinearResampler",
    "StreamIntegrityChecker",
    "Violation",
    "structural_problem",
]

# ---- thresholds: design choices, UNTUNED on real devices ----------------------------

# A block whose t0 is off its predecessor's end by more than this is a gap / overlap. The
# larger of a time and a sample count, so a 1000 Hz EMG stream is not held to a
# sub-sample tolerance and a 128 Hz headset is not allowed to lose 20 ms silently. 20 ms is
# below BrainFlow's own 50 ms jitter-snap (sources._TS_TOLERANCE_S), so a BrainFlow block
# never trips it except across a real resync; 1.5 samples matches the recorder's
# "not contiguous" warning in sources._CsvWriter.
GAP_TOLERANCE_S = 0.02
GAP_TOLERANCE_SAMPLES = 1.5

# The t0-observed sample rate is measured over this much contiguous stream and may differ
# from the declared fs by at most this fraction. 10 s keeps a 50 ms timestamp jitter below
# 0.5 % of the span; 2 % is far above any crystal error (tens of ppm) and far below the
# error of a driver that declares 256 Hz for a 250 Hz board (2.4 %).
RATE_WINDOW_S = 10.0
RATE_DRIFT_TOLERANCE = 0.02

# Arrival rate (samples per second of the injected clock), opt-in for live sources only:
# a replay delivers faster than real time by design. Looser than the t0 check because USB
# and BLE deliver in bursts of tens to hundreds of ms.
ARRIVAL_WINDOW_S = 10.0
ARRIVAL_DRIFT_TOLERANCE = 0.10

# No block for this long is a stall. Matched to the runner's DEFAULT_WATCHDOG_SECONDS (not
# imported: this module stays free of the runner). Before the first block a board may
# still be opening its session, so a longer grace applies.
STALL_S = 1.5
STARTUP_GRACE_S = 5.0

# Consecutive clean stream time needed before a closed gate reopens. One second: several
# blocks at any rate in the tree, short enough not to make a single dropped packet cost
# the user a noticeable pause.
RECOVER_S = 1.0

# LinearResampler has no anti-alias filter, so it refuses to shrink the rate below this
# fraction of the input. Meant for small corrections (256 -> 250 Hz), not decimation.
MIN_DOWNSAMPLE_RATIO = 0.75

# Float slack when comparing accumulated stream time (not a tunable).
_TIME_EPS_S = 1e-9

# How many emitted blocks IntegrityGate can look up by identity. The runner hands each
# block to the pipeline right after reading it, so one would do; a few is slack.
_PROVENANCE_DEPTH = 8


class Violation:
    """Violation codes (plain strings, stable for status output and tests)."""

    NOT_A_BLOCK = "not_a_block"
    BAD_SHAPE = "bad_shape"
    BAD_DTYPE = "bad_dtype"
    BAD_FS = "bad_fs"
    BAD_CHANNELS = "bad_channels"
    T0_INVALID = "t0_invalid"
    LAYOUT_CHANGED = "layout_changed"
    FS_CHANGED = "fs_changed"
    DECLARED_MISMATCH = "declared_mismatch"
    NON_FINITE = "non_finite"
    T0_BACKWARDS = "t0_backwards"
    GAP = "gap"
    OVERLAP = "overlap"
    RATE_DRIFT = "rate_drift"
    ARRIVAL_DRIFT = "arrival_drift"
    STALL = "stall"

    # A block with one of these cannot be handed downstream at all: it is dropped.
    UNUSABLE = frozenset({NOT_A_BLOCK, BAD_SHAPE, BAD_DTYPE, BAD_FS, BAD_CHANNELS, T0_INVALID})


@dataclass(frozen=True)
class IntegrityThresholds:
    """Every tunable of the checker in one place. Defaults are the module constants."""

    gap_tolerance_s: float = GAP_TOLERANCE_S
    gap_tolerance_samples: float = GAP_TOLERANCE_SAMPLES
    rate_window_s: float = RATE_WINDOW_S
    rate_drift_tolerance: float = RATE_DRIFT_TOLERANCE
    arrival_window_s: float = ARRIVAL_WINDOW_S
    arrival_drift_tolerance: float = ARRIVAL_DRIFT_TOLERANCE
    stall_s: float = STALL_S
    startup_grace_s: float = STARTUP_GRACE_S
    recover_s: float = RECOVER_S
    # True (fail closed): a source whose t0 never moves breaks the contract on every block.
    # False: a source whose t0 has stayed exactly 0.0 is treated as clockless and its
    # gap / overlap / rate checks are skipped (what quality.py does).
    require_clock: bool = True
    # True: NaN/inf are replaced by 0.0 and the block is passed on (flagged). False: such
    # a block is dropped instead.
    sanitize_non_finite: bool = True

    def gap_tolerance(self, fs: float) -> float:
        return max(self.gap_tolerance_s, self.gap_tolerance_samples / fs)


@dataclass(frozen=True)
class IntegrityViolation:
    """One breach of the stream contract."""

    code: str
    detail: str
    t: float | None = None          # stream time (source clock) where it was seen, if known
    block: int = 0                  # 1-based index of the block it was seen on (0: none)


@dataclass(frozen=True)
class BlockVerdict:
    """What :meth:`StreamIntegrityChecker.check` decided about one block.

    ``block`` is what to hand downstream: the input, a sanitized copy, or ``None`` when the
    block is unusable and was dropped. ``gate_closed`` is the gate *for this block*.
    """

    block: SampleBlock | None
    violations: tuple[IntegrityViolation, ...] = ()
    gate_closed: bool = False

    @property
    def ok(self) -> bool:
        return not self.violations


@dataclass(frozen=True)
class IntegrityReport:
    """Snapshot of a stream's integrity, for status / doctor / the pipeline hook."""

    blocks: int = 0                 # blocks inspected (including dropped ones)
    samples: int = 0                # samples passed downstream
    dropped_blocks: int = 0         # unusable blocks that were not passed on
    counts: dict[str, int] = field(default_factory=dict)   # violation code -> occurrences
    last_violation: IntegrityViolation | None = None
    gate_closed: bool = False
    clean_s: float = 0.0            # consecutive clean stream time since the last violation
    lost_s: float = 0.0             # stream time missing in gaps
    overlap_s: float = 0.0          # stream time delivered twice
    nominal_fs: float = 0.0
    observed_fs: float | None = None   # from t0, once a full rate window has been seen
    arrival_fs: float | None = None    # from the clock (guard, opt-in), once measured
    stalled: bool = False

    @property
    def ok(self) -> bool:
        """True when no violation has ever been seen."""
        return not self.counts

    @property
    def violations(self) -> int:
        return sum(self.counts.values())

    def reason(self) -> str:
        """One plain-language line: why the gate is closed, or ``""``."""
        if not self.gate_closed or self.last_violation is None:
            return ""
        return f"stream integrity: {self.last_violation.code} ({self.last_violation.detail})"

    def as_dict(self) -> dict[str, Any]:
        last = self.last_violation
        return {
            "gate_closed": self.gate_closed,
            "blocks": self.blocks,
            "samples": self.samples,
            "dropped_blocks": self.dropped_blocks,
            "violations": dict(self.counts),
            "last_violation": (None if last is None else
                               {"code": last.code, "detail": last.detail, "t": last.t,
                                "block": last.block}),
            "clean_s": round(self.clean_s, 3),
            "lost_s": round(self.lost_s, 3),
            "overlap_s": round(self.overlap_s, 3),
            "nominal_fs": self.nominal_fs,
            "observed_fs": None if self.observed_fs is None else round(self.observed_fs, 3),
            "arrival_fs": None if self.arrival_fs is None else round(self.arrival_fs, 3),
            "stalled": self.stalled,
        }

    def format(self) -> str:
        """Human-readable multi-line summary."""
        state = "CLOSED" if self.gate_closed else "open"
        lines = [f"Stream integrity: gate {state}; {self.blocks} block(s), "
                 f"{self.samples} sample(s), {self.dropped_blocks} dropped"]
        rate = f"  rate: nominal {self.nominal_fs:g} Hz"
        if self.observed_fs is not None:
            rate += f", observed {self.observed_fs:.2f} Hz (t0)"
        if self.arrival_fs is not None:
            rate += f", arriving {self.arrival_fs:.2f} Hz (clock)"
        lines.append(rate)
        if self.lost_s or self.overlap_s:
            lines.append(f"  lost {self.lost_s:.3f} s in gaps, {self.overlap_s:.3f} s overlapped")
        if self.counts:
            lines.append("  violations: " + ", ".join(
                f"{code} x{n}" for code, n in sorted(self.counts.items())))
        if self.last_violation is not None:
            v = self.last_violation
            where = f" at t={v.t:.3f} s" if v.t is not None else ""
            lines.append(f"  last: {v.code}{where} (block {v.block}): {v.detail}")
        if self.stalled:
            lines.append("  the stream is stalled now")
        return "\n".join(lines)


def _layout(channels: tuple[ChannelInfo, ...]) -> tuple[tuple[str, SignalKind], ...]:
    return tuple((c.name, c.kind) for c in channels)


def _describe_layout_change(
    old: tuple[tuple[str, SignalKind], ...], new: tuple[tuple[str, SignalKind], ...],
) -> str:
    old_names, new_names = [n for n, _ in old], [n for n, _ in new]
    if sorted(old_names) == sorted(new_names) and old_names != new_names:
        return f"channel order changed: {','.join(old_names)} -> {','.join(new_names)}"
    if old_names == new_names:
        kinds = [f"{n}:{a.value}->{b.value}" for (n, a), (_, b) in zip(old, new) if a != b]
        return "channel kind changed: " + ", ".join(kinds)
    gone = sorted(set(old_names) - set(new_names))
    added = sorted(set(new_names) - set(old_names))
    return f"channel set changed (removed {gone or '[]'}, added {added or '[]'})"


def structural_problem(block: Any) -> tuple[str, str] | None:
    """``(code, detail)`` if ``block`` cannot be handed downstream at all, else None.

    Pure and stateless; shared by the checker and the conformance kit.
    """
    if not isinstance(block, SampleBlock):
        return Violation.NOT_A_BLOCK, f"read() returned {type(block).__name__}, not a SampleBlock"
    data = block.data
    if not isinstance(data, np.ndarray):
        return Violation.BAD_SHAPE, f"data is {type(data).__name__}, not a numpy array"
    if data.dtype.kind not in "iuf":
        return Violation.BAD_DTYPE, f"data dtype {data.dtype} is not real numeric"
    channels = block.channels
    if (not isinstance(channels, tuple) or not channels
            or not all(isinstance(c, ChannelInfo) and isinstance(c.kind, SignalKind)
                       and isinstance(c.name, str) and c.name.strip() for c in channels)):
        return Violation.BAD_CHANNELS, "channels must be a non-empty tuple of named ChannelInfo"
    names = [c.name for c in channels]
    if len(set(names)) != len(names):
        dupes = sorted({n for n in names if names.count(n) > 1})
        return Violation.BAD_CHANNELS, f"duplicate channel name(s) {dupes}"
    if data.ndim != 2 or data.shape[0] != len(channels):
        return (Violation.BAD_SHAPE,
                f"data shape {data.shape} is not (n_channels={len(channels)}, n_samples)")
    try:
        fs = float(block.fs)
    except (TypeError, ValueError):
        return Violation.BAD_FS, f"fs {block.fs!r} is not a number"
    if not math.isfinite(fs) or fs <= 0:
        return Violation.BAD_FS, f"fs {fs!r} must be finite and > 0"
    try:
        t0 = float(block.t0)
    except (TypeError, ValueError):
        return Violation.T0_INVALID, f"t0 {block.t0!r} is not a number"
    if not math.isfinite(t0):
        return Violation.T0_INVALID, f"t0 {t0!r} is not finite"
    return None


# ====================================================================================
# 1. the pure checker
# ====================================================================================


class StreamIntegrityChecker:
    """Block-sequence contract checker. Feed blocks in order with :meth:`check`.

    Stateful but pure: no clock, no I/O. Clock-dependent findings (a stall, an arrival
    rate) come from a wrapper through :meth:`flag`. Not thread-safe.
    """

    def __init__(self, thresholds: IntegrityThresholds | None = None) -> None:
        self.thresholds = thresholds or IntegrityThresholds()
        self.reset()

    def reset(self) -> None:
        """Forget the stream: counters, layout, time base, hold-off."""
        self._layout: tuple[tuple[str, SignalKind], ...] | None = None
        self._fs = 0.0
        self._prev_t0: float | None = None
        self._expected_t: float | None = None
        self._clockless = True              # t0 has been exactly 0.0 on every block so far
        self._rate: deque[tuple[float, int]] = deque()
        self._rate_n = 0
        self._observed_fs: float | None = None
        self._blocks = 0
        self._samples = 0
        self._dropped = 0
        self._counts: dict[str, int] = {}
        self._last: IntegrityViolation | None = None
        self._violated = False
        self._clean_s = 0.0
        self._lost_s = 0.0
        self._overlap_s = 0.0
        self._pending: list[IntegrityViolation] = []
        self._logged: set[str] = set()
        self.arrival_fs: float | None = None   # written by the guard
        self.stalled = False                    # written by the guard

    # ---- public -----------------------------------------------------------

    @property
    def gate_closed(self) -> bool:
        # The epsilon absorbs float summation of block durations (10 x 0.1 s < 1.0 s).
        return self._violated and self._clean_s < self.thresholds.recover_s - _TIME_EPS_S

    @property
    def report(self) -> IntegrityReport:
        return IntegrityReport(
            blocks=self._blocks, samples=self._samples, dropped_blocks=self._dropped,
            counts=dict(self._counts), last_violation=self._last,
            gate_closed=self.gate_closed, clean_s=self._clean_s, lost_s=self._lost_s,
            overlap_s=self._overlap_s, nominal_fs=self._fs, observed_fs=self._observed_fs,
            arrival_fs=self.arrival_fs, stalled=self.stalled,
        )

    def flag(self, code: str, detail: str, t: float | None = None) -> IntegrityViolation:
        """Record a violation found outside :meth:`check` (stall, arrival rate, declared
        layout). It closes the gate at once and is attached to the next checked block."""
        violation = IntegrityViolation(code, detail, t, self._blocks)
        self._record(violation)
        self._pending.append(violation)
        return violation

    def check(self, block: Any) -> BlockVerdict:
        """Judge one block (in stream order) and return what to pass downstream."""
        self._blocks += 1
        found: list[IntegrityViolation] = self._pending
        self._pending = []

        problem = structural_problem(block)
        if problem is not None:
            found.append(self._new(problem[0], problem[1], None))
            self._dropped += 1
            return self._verdict(None, found)

        fs = float(block.fs)
        t0 = float(block.t0)
        n = block.n_samples
        if n == 0:
            # Nothing to judge or to lose; the contract prefers None, but it is harmless.
            return self._verdict(block, found, duration=0.0)

        self._check_layout(block, fs, t0, found)
        block = self._check_finite(block, t0, found)
        if block is None:
            self._dropped += 1
            return self._verdict(None, found)
        self._check_time(t0, n, fs, found)
        self._samples += n
        return self._verdict(block, found, duration=n / fs)

    # ---- the checks ---------------------------------------------------------

    def _check_layout(self, block: SampleBlock, fs: float, t0: float,
                      found: list[IntegrityViolation]) -> None:
        layout = _layout(block.channels)
        if self._layout is None:
            self._layout, self._fs = layout, fs
            return
        if layout != self._layout:
            found.append(self._new(Violation.LAYOUT_CHANGED,
                                   _describe_layout_change(self._layout, layout), t0))
            self._layout = layout
            self._reset_rate()
        if fs != self._fs:
            found.append(self._new(Violation.FS_CHANGED, f"fs {self._fs:g} -> {fs:g} Hz", t0))
            self._fs = fs
            self._reset_rate()

    def _check_finite(self, block: SampleBlock, t0: float,
                      found: list[IntegrityViolation]) -> SampleBlock | None:
        data = block.data
        if data.dtype.kind != "f":
            return block                    # integers cannot hold NaN / inf
        finite = np.isfinite(data)
        if finite.all():
            return block
        bad = int(data.size - np.count_nonzero(finite))
        found.append(self._new(Violation.NON_FINITE,
                               f"{bad} non-finite sample(s) of {data.size}", t0))
        if not self.thresholds.sanitize_non_finite:
            return None
        clean = np.where(finite, data, 0.0).astype(np.float64, copy=False)
        return SampleBlock(data=clean, fs=block.fs, channels=block.channels, t0=block.t0)

    def _check_time(self, t0: float, n: int, fs: float,
                    found: list[IntegrityViolation]) -> None:
        thr = self.thresholds
        if self._clockless and t0 == 0.0 and not thr.require_clock:
            self._prev_t0, self._expected_t = t0, t0 + n / fs
            return
        if t0 != 0.0:
            self._clockless = False
        prev, expected = self._prev_t0, self._expected_t
        self._prev_t0, self._expected_t = t0, t0 + n / fs
        if prev is None or expected is None:
            self._rate_push(t0, n, fs, found)
            return
        if t0 <= prev:
            what = "repeated" if t0 == prev else f"went back {prev - t0:.4f} s"
            found.append(self._new(Violation.T0_BACKWARDS,
                                   f"t0 {what} (previous block started at {prev:.4f} s)", t0))
            self._overlap_s += max(0.0, expected - t0)
            self._reset_rate()
        else:
            gap = t0 - expected
            tol = thr.gap_tolerance(fs)
            if gap > tol:
                found.append(self._new(
                    Violation.GAP, f"{gap:.4f} s (~{round(gap * fs)} sample(s)) missing", t0))
                self._lost_s += gap
                self._reset_rate()
            elif gap < -tol:
                found.append(self._new(
                    Violation.OVERLAP, f"block starts {-gap:.4f} s before the previous one "
                    "ended", t0))
                self._overlap_s += -gap
                self._reset_rate()
        self._rate_push(t0, n, fs, found)

    def _rate_push(self, t0: float, n: int, fs: float, found: list[IntegrityViolation]) -> None:
        thr = self.thresholds
        self._rate.append((t0, n))
        self._rate_n += n
        while len(self._rate) > 2 and t0 - self._rate[1][0] >= thr.rate_window_s:
            self._rate_n -= self._rate.popleft()[1]
        span = t0 - self._rate[0][0]
        if span < thr.rate_window_s:
            return
        observed = (self._rate_n - n) / span    # samples before the last block / their span
        self._observed_fs = observed
        drift = observed / fs - 1.0
        if abs(drift) > thr.rate_drift_tolerance:
            found.append(self._new(
                Violation.RATE_DRIFT,
                f"t0 says {observed:.2f} Hz, the block says {fs:g} Hz ({drift:+.1%})", t0))

    def _reset_rate(self) -> None:
        self._rate.clear()
        self._rate_n = 0

    # ---- bookkeeping --------------------------------------------------------

    def _new(self, code: str, detail: str, t: float | None) -> IntegrityViolation:
        violation = IntegrityViolation(code, detail, t, self._blocks)
        self._record(violation)
        return violation

    def _record(self, violation: IntegrityViolation) -> None:
        self._counts[violation.code] = self._counts.get(violation.code, 0) + 1
        self._last = violation
        self._violated = True
        self._clean_s = 0.0
        if violation.code not in self._logged:
            self._logged.add(violation.code)
            log.warning("Biosignal stream integrity: %s (%s); events are held until the "
                        "stream has been clean for %.1f s.", violation.code, violation.detail,
                        self.thresholds.recover_s)
        else:
            log.debug("Biosignal stream integrity: %s (%s)", violation.code, violation.detail)

    def _verdict(self, block: SampleBlock | None, found: list[IntegrityViolation],
                 duration: float = 0.0) -> BlockVerdict:
        if not found and block is not None:
            self._clean_s += duration
        return BlockVerdict(block, tuple(found), bool(found) or self.gate_closed)


# ====================================================================================
# 2. the guard: a BlockSource around any BlockSource
# ====================================================================================


class IntegrityGuard:
    """Wrap any :class:`BlockSource` and enforce the stream contract on what it yields.

    ``read()`` returns the inner block (or a sanitized copy), or ``None`` when the inner
    source had nothing *or* produced an unusable block (counted in the report). An
    ``EOFError`` and any other exception of the inner source pass through unchanged: the
    guard judges data, it does not hide failures.

    ``clock`` (injectable) times stalls and, with ``check_arrival_rate=True``, the arrival
    rate. Leave that off for replay sources, which deliver faster than real time by design.

    ``fs`` / ``channels`` mirror the inner source after ``start()``; any other attribute
    (``available``, ``last_error``, ``peek``, ``ground_truth`` ...) is forwarded to it.
    ``start()`` begins a fresh judgement of a fresh stream.
    """

    def __init__(
        self,
        source: BlockSource,
        *,
        thresholds: IntegrityThresholds | None = None,
        clock: Callable[[], float] = time.monotonic,
        check_arrival_rate: bool = False,
    ) -> None:
        self._inner = source
        self._clock = clock
        self._arrival = bool(check_arrival_rate)
        self.checker = StreamIntegrityChecker(thresholds)
        self.fs: float = float(getattr(source, "fs", 0.0) or 0.0)
        self.channels: tuple[ChannelInfo, ...] = tuple(getattr(source, "channels", ()) or ())
        self._started_at: float | None = None
        self._last_arrival: float | None = None
        self._arrivals: deque[tuple[float, int]] = deque()
        self._arrival_n = 0
        self._emitted: deque[tuple[SampleBlock, bool]] = deque(maxlen=_PROVENANCE_DEPTH)

    # ---- BlockSource --------------------------------------------------------

    def start(self) -> None:
        self._inner.start()
        self._refresh_declared()
        self.checker.reset()
        self._started_at = self._clock()
        self._last_arrival = None
        self._arrivals.clear()
        self._arrival_n = 0
        self._emitted.clear()

    def read(self) -> SampleBlock | None:
        raw = self._inner.read()            # EOFError and real failures propagate
        now = self._clock()
        if self._started_at is None:        # read() before start(): judge from here on
            self._started_at = now
        if raw is None:
            self._check_stall(now)
            return None
        self._check_resume(now)
        self._refresh_declared()
        if isinstance(raw, SampleBlock):
            self._check_declared(raw)
        verdict = self.checker.check(raw)
        if verdict.block is not None:
            self._check_arrival(now, verdict.block)
            # An arrival violation found on this block closes the gate for it, too.
            closed = verdict.gate_closed or self.checker.gate_closed
            self._emitted.append((verdict.block, closed))
        return verdict.block

    def stop(self) -> None:
        self._inner.stop()

    # ---- the hook surface ---------------------------------------------------

    @property
    def inner(self) -> BlockSource:
        return self._inner

    @property
    def report(self) -> IntegrityReport:
        return self.checker.report

    @property
    def gate_closed(self) -> bool:
        return self.checker.gate_closed

    @property
    def last_violation(self) -> IntegrityViolation | None:
        return self.checker.report.last_violation

    def gate_closed_for(self, block: SampleBlock) -> bool:
        """The gate as it stood for ``block`` (by identity). A block this guard did not
        emit recently has unknown provenance and counts as closed: fail closed."""
        for emitted, closed in reversed(self._emitted):
            if emitted is block:
                return closed
        return True

    def __getattr__(self, name: str) -> Any:
        # Only reached for attributes the guard does not have itself.
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._inner, name)

    # ---- internals ----------------------------------------------------------

    def _refresh_declared(self) -> None:
        self.fs = float(getattr(self._inner, "fs", 0.0) or 0.0)
        self.channels = tuple(getattr(self._inner, "channels", ()) or ())

    def _check_declared(self, block: SampleBlock) -> None:
        problems = []
        if self.fs > 0 and block.fs != self.fs:
            problems.append(f"block fs {block.fs!r} != declared {self.fs:g} Hz")
        if self.channels and block.channels != self.channels:
            problems.append("block channels differ from the declared channels")
        if problems:
            t0 = block.t0 if isinstance(block.t0, (int, float)) else None
            self.checker.flag(Violation.DECLARED_MISMATCH, "; ".join(problems), t0)

    def _check_stall(self, now: float) -> None:
        if self.checker.stalled or self._started_at is None:
            return
        thr = self.checker.thresholds
        if self._last_arrival is None:
            silent, limit = now - self._started_at, thr.startup_grace_s
        else:
            silent, limit = now - self._last_arrival, thr.stall_s
        if silent > limit:
            self.checker.stalled = True
            self.checker.flag(Violation.STALL, f"no block for {silent:.2f} s")
            self._reset_arrival()

    def _check_resume(self, now: float) -> None:
        thr = self.checker.thresholds
        if not self.checker.stalled and self._started_at is not None:
            if self._last_arrival is None:
                silent, limit = now - self._started_at, thr.startup_grace_s
            else:
                silent, limit = now - self._last_arrival, thr.stall_s
            if silent > limit:
                # The silence ended before anyone polled during it: still a stall.
                self.checker.flag(Violation.STALL, f"no block for {silent:.2f} s")
                self._reset_arrival()
        self.checker.stalled = False
        self._last_arrival = now

    def _check_arrival(self, now: float, block: SampleBlock) -> None:
        if not self._arrival or block.n_samples == 0:
            return
        thr = self.checker.thresholds
        n = block.n_samples
        self._arrivals.append((now, n))
        self._arrival_n += n
        while len(self._arrivals) > 2 and now - self._arrivals[1][0] >= thr.arrival_window_s:
            self._arrival_n -= self._arrivals.popleft()[1]
        span = now - self._arrivals[0][0]
        if span < thr.arrival_window_s:
            return
        arriving = (self._arrival_n - self._arrivals[0][1]) / span
        self.checker.arrival_fs = arriving
        drift = arriving / float(block.fs) - 1.0
        if abs(drift) > thr.arrival_drift_tolerance:
            self.checker.flag(
                Violation.ARRIVAL_DRIFT,
                f"{arriving:.2f} samples/s arriving for a declared {float(block.fs):g} Hz "
                f"({drift:+.1%})", float(block.t0))

    def _reset_arrival(self) -> None:
        self._arrivals.clear()
        self._arrival_n = 0


# ====================================================================================
# 3. the pipeline hook: a drop-in for PipelineParts.quality
# ====================================================================================


@dataclass(frozen=True)
class GatedQualityReport:
    """What :class:`IntegrityGate` returns: the quality monitor's verdict, forced to BAD
    while the stream gate is closed. Unknown attributes are read from the inner report."""

    overall: Any
    suppress_events: bool
    bad_during_update: bool
    integrity: IntegrityReport
    inner: Any = None
    integrity_closed: bool = False

    @property
    def integrity_reason(self) -> str:
        return self.integrity.reason() if self.integrity_closed else ""

    def __getattr__(self, name: str) -> Any:
        # Only reached for names the report does not have; never for its own fields, so
        # guard them too (a half-built instance must not recurse).
        if name.startswith("_") or name in _GATED_FIELDS:
            raise AttributeError(name)
        inner = self.__dict__.get("inner")
        if inner is None:
            raise AttributeError(name)
        return getattr(inner, name)


_GATED_FIELDS = frozenset({"overall", "suppress_events", "bad_during_update", "integrity",
                           "inner", "integrity_closed"})


class IntegrityGate:
    """``PipelineParts.quality`` replacement that adds the stream gate to the signal gate.

    ``update(block)`` runs the wrapped quality monitor (if any) and returns a
    :class:`GatedQualityReport` whose ``overall`` is ``"BAD"`` and ``suppress_events`` True
    whenever ``guard.gate_closed_for(block)`` — which is what
    ``BiosignalPipeline._quality_gate`` reads, so the pipeline drops events and releases a
    held squeeze without being changed. ``report`` and ``reset()`` are the wrapped
    monitor's, so ``cli_impl`` code reading ``parts.quality.report`` keeps working.

    If the wrapped monitor raises, it is dropped (logged once) and the integrity gate keeps
    working on its own; the pipeline would otherwise switch the whole gate off.
    """

    def __init__(self, guard: IntegrityGuard, inner: Any = None) -> None:
        self.guard = guard
        self.inner = inner

    @property
    def report(self) -> Any:
        return getattr(self.inner, "report", None) if self.inner is not None else None

    def reset(self) -> None:
        # Only the signal judgement: the stream's history is a fact about the device.
        if self.inner is not None:
            self.inner.reset()

    def update(self, block: SampleBlock) -> GatedQualityReport:
        inner_report = None
        if self.inner is not None:
            try:
                inner_report = self.inner.update(block)
            except Exception:
                log.warning("Biosignal quality monitor failed; the stream-integrity gate "
                            "stays on without it.", exc_info=True)
                self.inner = None
        closed = self.guard.gate_closed_for(block)
        integrity = self.guard.report
        if inner_report is None:
            overall: Any = "BAD" if closed else "GOOD"
            suppress = bad_during = closed
        else:
            overall = "BAD" if closed else getattr(inner_report, "overall", "unknown")
            suppress = closed or bool(getattr(inner_report, "suppress_events", False))
            bad_during = closed or bool(getattr(inner_report, "bad_during_update", False))
        return GatedQualityReport(overall, suppress, bad_during, integrity, inner_report, closed)


# ====================================================================================
# 4. optional: rate correction
# ====================================================================================


class LinearResampler:
    """Stream-continuous linear-interpolation resampler to a fixed output rate.

    A design choice for devices whose rate is close to, but not, one a calibration
    profile or detector default expects (e.g. a 256 Hz headset against 250 Hz settings).
    The output sample ``k`` sits at input position ``k * fs_in / fs_out`` counted from the
    first sample of the contiguous run, so the output is identical however the input is cut
    into blocks (spec invariant 10); the last input sample is carried across blocks.

    There is **no anti-alias filter**: decimating below ``MIN_DOWNSAMPLE_RATIO`` of the
    input rate is refused, because content above the new Nyquist would fold into the band.
    Linear interpolation also attenuates high frequencies slightly. A layout or rate change,
    or a ``t0`` discontinuity beyond the integrity tolerance, starts a new run. Pure.
    """

    def __init__(self, fs_out: float,
                 thresholds: IntegrityThresholds | None = None) -> None:
        fs_out = float(fs_out)
        if not math.isfinite(fs_out) or fs_out <= 0:
            raise ValueError("fs_out must be finite and > 0")
        self.fs_out = fs_out
        self._thr = thresholds or IntegrityThresholds()
        self.reset()

    def reset(self) -> None:
        self._key: tuple[Any, ...] | None = None
        self._run_t0 = 0.0          # t0 of input sample 0 of the current run
        self._consumed = 0          # input samples of the run before the current block
        self._carry: np.ndarray | None = None   # last input sample, (n_ch,)
        self._k = 0                 # next output sample index of the run
        self._expected_t: float | None = None

    def process(self, block: SampleBlock) -> SampleBlock | None:
        """Resampled block, or None when no output sample falls inside this input yet."""
        fs_in = float(block.fs)
        if fs_in == self.fs_out:
            return block
        if self.fs_out < fs_in * MIN_DOWNSAMPLE_RATIO:
            raise ValueError(
                f"refusing to resample {fs_in:g} -> {self.fs_out:g} Hz without an "
                f"anti-alias filter (minimum ratio {MIN_DOWNSAMPLE_RATIO})")
        data = np.asarray(block.data, dtype=np.float64)
        n = data.shape[1]
        if n == 0:
            return None
        key = (_layout(block.channels), fs_in)
        tol = self._thr.gap_tolerance(fs_in)
        if (key != self._key or self._expected_t is None
                or abs(float(block.t0) - self._expected_t) > tol):
            self.reset()
            self._key = key
            self._run_t0 = float(block.t0)
        self._expected_t = float(block.t0) + n / fs_in

        if self._carry is None:
            xs = np.arange(n, dtype=np.float64) + self._consumed
            values = data
        else:
            xs = np.arange(-1, n, dtype=np.float64) + self._consumed
            values = np.concatenate([self._carry[:, None], data], axis=1)
        last_x = self._consumed + n - 1
        ratio = fs_in / self.fs_out
        k_hi = math.floor(last_x / ratio + 1e-9)
        self._carry = data[:, -1].copy()
        self._consumed += n
        if k_hi < self._k:
            return None
        ks = np.arange(self._k, k_hi + 1, dtype=np.float64)
        pos = ks * ratio
        out = np.vstack([np.interp(pos, xs, row) for row in values])
        t0 = self._run_t0 + self._k / self.fs_out
        self._k = k_hi + 1
        return SampleBlock(data=out, fs=self.fs_out, channels=block.channels, t0=t0)
