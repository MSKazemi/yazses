"""Source conformance kit: does a new device driver keep the ``BlockSource`` contract?

Run :func:`check_source` against a driver before wiring it in. It drives the source for a
bounded time and returns one verdict per contract clause, each ``pass`` / ``fail`` /
``warn`` / ``skip`` with a plain-language reason, so a contributor sees *which* promise a
driver breaks instead of a detector misbehaving three layers later.

The contract is the one :mod:`yazses.biosignal.types` writes down and the in-tree sources
(:mod:`yazses.biosignal.sources`) keep:

=================== =================================================================
protocol            ``fs``, ``channels``, ``start``, ``read``, ``stop`` exist
stop_before_start   ``stop()`` on a never-started source is a no-op, not an error
start               ``start()`` does not raise (a missing device is a logged no-op)
declared_fs         after ``start()``, ``fs`` is finite and > 0
declared_channels   after ``start()``, ``channels`` is a non-empty tuple of
                    :class:`ChannelInfo` with unique, non-empty names
read_types          ``read()`` returns a ``SampleBlock`` or ``None``; the only exception
                    it may raise is ``EOFError`` (end of a finite source)
first_block         a block arrives within the run (a source that returns ``None``
                    forever is a stall, not a quiet device)
no_stall            no silence longer than ``stall_s`` (integrity ``STALL_S``) between blocks
block_structure     ``data`` is a 2-D real ndarray ``(n_channels, n_samples)``; ``fs`` and
                    ``t0`` finite; empty blocks are a warning (the contract prefers None)
block_layout        every block's ``fs`` and channels equal the declared ones, all run long
finite              no NaN / inf samples
t0                  strictly increasing and contiguous (no gap, no overlap) within the
                    integrity tolerance
rate_t0             samples per second of ``t0`` match ``fs`` (needs ``MIN_RATE_SPAN_S``)
rate_arrival        for a source paced in real time, samples per clock second match ``fs``
                    (skipped for a replay that runs faster than real time)
read_after_eof      after ``EOFError``, ``read()`` raises it again or returns ``None``
stop                ``stop()`` does not raise
stop_twice          a second ``stop()`` does not raise
read_after_stop     ``read()`` after ``stop()`` returns ``None`` or raises ``EOFError``;
                    still delivering data is a warning (the Protocol does not forbid it)
=================== =================================================================

The stream checks reuse :class:`~yazses.biosignal.integrity.StreamIntegrityChecker`, so a
driver that passes here is one the runtime :class:`~yazses.biosignal.integrity.IntegrityGuard`
will not keep tripping on. Tolerances are the integrity module's (design choices, untuned
on real hardware) plus the two run-length constants below.

Runs entirely on the injected ``clock`` and ``sleep``; pure apart from driving the source
it is given. It never opens a device itself.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from yazses.biosignal.integrity import (
    IntegrityReport,
    IntegrityThresholds,
    StreamIntegrityChecker,
    Violation,
    structural_problem,
)
from yazses.biosignal.types import BlockSource, ChannelInfo, SampleBlock, SignalKind

__all__ = [
    "DEFAULT_SECONDS",
    "MIN_RATE_SPAN_S",
    "REALTIME_FACTOR_MAX",
    "ClauseResult",
    "ConformanceReport",
    "check_source",
]

# How long a run lasts by default, in stream seconds (and at most this many clock
# seconds). Design choice: long enough to see many blocks and to measure the rate to about
# 1 %, short enough for a contributor to run it often.
DEFAULT_SECONDS = 5.0
# The t0 / arrival rate is only judged over at least this much stream. A 50 ms timestamp
# jitter is 2.5 % of 2 s, so a shorter span would make RATE_DRIFT_TOLERANCE meaningless.
MIN_RATE_SPAN_S = 2.0
# A source delivering stream time faster than this multiple of clock time is a replay,
# not a real-time device, and its arrival rate is not judged.
REALTIME_FACTOR_MAX = 1.5
# Hard cap on blocks read in one run, whatever the source does.
_MAX_BLOCKS = 200_000
_IDLE_SLEEP_S = 0.005

PASS, FAIL, WARN, SKIP = "pass", "fail", "warn", "skip"

_STRUCTURE_CODES = frozenset(Violation.UNUSABLE - {Violation.NOT_A_BLOCK})
_LAYOUT_CODES = frozenset({Violation.LAYOUT_CHANGED, Violation.FS_CHANGED})
_T0_CODES = frozenset({Violation.T0_BACKWARDS, Violation.GAP, Violation.OVERLAP})


@dataclass(frozen=True)
class ClauseResult:
    """The verdict on one contract clause."""

    clause: str
    status: str            # pass | fail | warn | skip
    detail: str = ""


@dataclass(frozen=True)
class ConformanceReport:
    """Everything :func:`check_source` found, one :class:`ClauseResult` per clause."""

    source: str
    clauses: tuple[ClauseResult, ...]
    blocks: int = 0
    samples: int = 0
    stream_s: float = 0.0
    elapsed_s: float = 0.0
    eof: bool = False
    integrity: IntegrityReport | None = None

    @property
    def passed(self) -> bool:
        """True when no clause failed (warnings and skips do not fail a source)."""
        return not self.failures

    @property
    def failures(self) -> tuple[ClauseResult, ...]:
        return tuple(c for c in self.clauses if c.status == FAIL)

    @property
    def warnings(self) -> tuple[ClauseResult, ...]:
        return tuple(c for c in self.clauses if c.status == WARN)

    def clause(self, name: str) -> ClauseResult:
        for c in self.clauses:
            if c.clause == name:
                return c
        raise KeyError(name)

    def format(self) -> str:
        """Human-readable report, one line per clause, for a contributor's terminal."""
        tally = {s: sum(1 for c in self.clauses if c.status == s)
                 for s in (PASS, WARN, FAIL, SKIP)}
        lines = [
            f"Source conformance: {self.source} — {'PASS' if self.passed else 'FAIL'} "
            f"({tally[PASS]} pass, {tally[WARN]} warn, {tally[FAIL]} fail, {tally[SKIP]} skip)",
            f"  ran {self.stream_s:.2f} s of stream in {self.elapsed_s:.2f} s; "
            f"{self.blocks} block(s), {self.samples} sample(s); "
            f"end of stream: {'yes' if self.eof else 'no'}",
        ]
        width = max((len(c.clause) for c in self.clauses), default=0)
        for c in self.clauses:
            text = f"  [{c.status.upper():<4}] {c.clause:<{width}}"
            lines.append(f"{text}  {c.detail}" if c.detail else text.rstrip())
        return "\n".join(lines)


class _Run:
    """Mutable state of one conformance run."""

    def __init__(self) -> None:
        self.clauses: list[ClauseResult] = []
        self.blocks = 0
        self.samples = 0
        self.stream_s = 0.0
        self.empty = 0
        self.eof = False
        self.read_error = ""
        self.not_blocks: list[str] = []
        self.violations: dict[str, list[str]] = {}
        self.declared_problems: list[str] = []
        self.first_arrival: float | None = None
        self.first_latency: float | None = None
        self.last_arrival: float | None = None
        self.max_silence = 0.0
        self.first_t0: float | None = None
        self.last_t0: float | None = None
        self.last_n = 0
        self.rate_fs = 0.0
        # Arrival times of the first and last usable block, and the first one's size.
        self.data_first_arrival: float | None = None
        self.data_last_arrival: float | None = None
        self.first_n = 0

    def add(self, clause: str, status: str, detail: str = "") -> None:
        self.clauses.append(ClauseResult(clause, status, detail))


def _call(fn: Callable[[], Any]) -> str:
    """'' if ``fn()`` returned, else ``"<Type>: <message>"``."""
    try:
        fn()
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return ""


def _name_of(source: Any) -> str:
    return type(source).__name__


def _first(items: list[str], more: int = 3) -> str:
    head = "; ".join(items[:more])
    return head + (f" (and {len(items) - more} more)" if len(items) > more else "")


def check_source(
    source: BlockSource,
    *,
    seconds: float = DEFAULT_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    thresholds: IntegrityThresholds | None = None,
) -> ConformanceReport:
    """Drive ``source`` for up to ``seconds`` (stream time, and at most that much clock
    time) and judge every contract clause. Never raises because of the source: whatever it
    does is a finding. The source is left stopped.
    """
    if not (math.isfinite(seconds) and seconds > 0):
        raise ValueError("seconds must be finite and > 0")
    run = _Run()
    thr = thresholds or IntegrityThresholds()

    missing = [a for a in ("fs", "channels", "start", "read", "stop") if not hasattr(source, a)]
    if missing:
        run.add("protocol", FAIL, f"missing {', '.join(missing)}")
        return _report(source, run, 0.0, None)
    run.add("protocol", PASS)

    err = _call(source.stop)
    run.add("stop_before_start", FAIL if err else PASS,
            f"stop() before start() raised {err}" if err else "")

    t_begin = clock()
    err = _call(source.start)
    run.add("start", FAIL if err else PASS,
            f"start() raised {err}; a missing device should leave the source unavailable "
            "and read() returning None" if err else "")
    if err:
        _finish(source, run, after_eof=False)
        return _report(source, run, clock() - t_begin, None)

    declared_fs, declared_channels = _check_declared(source, run)
    checker = StreamIntegrityChecker(thr)
    _drive(source, run, checker, seconds, clock, sleep, t_begin,
           declared_fs, declared_channels)
    elapsed = clock() - t_begin
    _judge_stream(run, checker, elapsed, thr)
    _finish(source, run, after_eof=run.eof)
    return _report(source, run, elapsed, checker.report)


def _check_declared(
    source: BlockSource, run: _Run,
) -> tuple[float | None, tuple[ChannelInfo, ...] | None]:
    why = str(getattr(source, "last_error", "") or "")
    hint = f" (last_error: {why})" if why else ""
    fs: float | None
    try:
        fs = float(source.fs)
    except (TypeError, ValueError):
        fs = None
    if fs is None or not math.isfinite(fs) or fs <= 0:
        run.add("declared_fs", FAIL, f"fs is {getattr(source, 'fs', None)!r} after start(); "
                f"it must be finite and > 0{hint}")
        fs = None
    else:
        run.add("declared_fs", PASS, f"{fs:g} Hz")

    channels = getattr(source, "channels", None)
    problem = ""
    if not isinstance(channels, tuple) or not channels:
        problem = f"channels is {channels!r}; it must be a non-empty tuple after start()"
    elif not all(isinstance(c, ChannelInfo) and isinstance(c.kind, SignalKind) for c in channels):
        problem = "every channel must be a ChannelInfo with a SignalKind"
    elif not all(isinstance(c.name, str) and c.name.strip() for c in channels):
        problem = "every channel needs a non-empty name"
    else:
        names = [c.name for c in channels]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            problem = f"duplicate channel name(s) {dupes}"
    if problem:
        run.add("declared_channels", FAIL, problem + hint)
        return fs, None
    assert isinstance(channels, tuple)
    run.add("declared_channels", PASS,
            ", ".join(f"{c.name}:{c.kind.value}" for c in channels))
    return fs, channels


def _drive(
    source: BlockSource, run: _Run, checker: StreamIntegrityChecker, seconds: float,
    clock: Callable[[], float], sleep: Callable[[float], None], t_begin: float,
    declared_fs: float | None, declared_channels: tuple[ChannelInfo, ...] | None,
) -> None:
    while run.blocks < _MAX_BLOCKS:
        if clock() - t_begin >= seconds:
            return
        try:
            block: Any = source.read()
        except EOFError:
            run.eof = True
            return
        except Exception as exc:
            run.read_error = f"{type(exc).__name__}: {exc}"
            return
        now = clock()
        if block is None:
            sleep(_IDLE_SLEEP_S)
            continue
        run.blocks += 1
        if run.last_arrival is None:
            run.first_arrival = now
            run.first_latency = now - t_begin
        else:
            run.max_silence = max(run.max_silence, now - run.last_arrival)
        run.last_arrival = now

        if not isinstance(block, SampleBlock):
            run.not_blocks.append(type(block).__name__)
        verdict = checker.check(block)
        for v in verdict.violations:
            run.violations.setdefault(v.code, []).append(
                f"block {v.block}: {v.detail}")
        if structural_problem(block) is not None:
            continue
        n = block.n_samples
        if n == 0:
            run.empty += 1
            continue
        fs = float(block.fs)
        if declared_fs is not None and fs != declared_fs:
            run.declared_problems.append(
                f"block {run.blocks}: fs {fs:g} Hz, declared {declared_fs:g} Hz")
        if declared_channels is not None and block.channels != declared_channels:
            run.declared_problems.append(
                f"block {run.blocks}: channels "
                f"{','.join(c.name for c in block.channels)} differ from the declared "
                f"{','.join(c.name for c in declared_channels)}")
        run.samples += n
        run.stream_s += n / fs
        t0 = float(block.t0)
        if run.first_t0 is None:
            run.first_t0, run.first_n, run.data_first_arrival = t0, n, now
        run.data_last_arrival = now
        run.last_t0, run.last_n, run.rate_fs = t0, n, fs
        if run.stream_s >= seconds:
            return


def _judge_stream(run: _Run, checker: StreamIntegrityChecker, elapsed: float,
                  thr: IntegrityThresholds) -> None:
    v = run.violations
    if run.read_error:
        run.add("read_types", FAIL, f"read() raised {run.read_error}; only EOFError may "
                "escape (a device failure should make read() return None)")
    elif run.not_blocks:
        run.add("read_types", FAIL, f"read() returned {_first(sorted(set(run.not_blocks)))}; "
                "it must return a SampleBlock or None")
    else:
        run.add("read_types", PASS)

    if run.blocks == 0:
        run.add("first_block", FAIL, "no block in the whole run: read() only ever returned "
                "None" + (" before EOFError" if run.eof else " (a stall)"))
    elif run.first_latency is not None and run.first_latency > thr.startup_grace_s:
        run.add("first_block", WARN, f"first block after {run.first_latency:.2f} s")
    else:
        run.add("first_block", PASS)

    if run.blocks < 2:
        run.add("no_stall", SKIP, "fewer than two blocks")
    elif run.max_silence > thr.stall_s:
        run.add("no_stall", FAIL, f"{run.max_silence:.2f} s without a block "
                f"(limit {thr.stall_s:g} s)")
    else:
        run.add("no_stall", PASS, f"longest silence {run.max_silence:.3f} s")

    structure = [d for code in sorted(_STRUCTURE_CODES) for d in v.get(code, [])]
    if structure:
        run.add("block_structure", FAIL, _first(structure))
    elif run.blocks == 0:
        run.add("block_structure", SKIP, "no block")
    elif run.empty:
        run.add("block_structure", WARN, f"{run.empty} empty block(s); return None instead")
    else:
        run.add("block_structure", PASS)

    layout = run.declared_problems + [d for code in sorted(_LAYOUT_CODES)
                                      for d in v.get(code, [])]
    if layout:
        run.add("block_layout", FAIL, _first(layout))
    elif run.samples == 0:
        run.add("block_layout", SKIP, "no usable block")
    else:
        run.add("block_layout", PASS)

    if Violation.NON_FINITE in v:
        run.add("finite", FAIL, _first(v[Violation.NON_FINITE]))
    elif run.samples == 0:
        run.add("finite", SKIP, "no usable block")
    else:
        run.add("finite", PASS)

    timing = [f"{code}: {d}" for code in sorted(_T0_CODES) for d in v.get(code, [])]
    if timing:
        run.add("t0", FAIL, _first(timing))
    elif run.samples == 0:
        run.add("t0", SKIP, "no usable block")
    else:
        run.add("t0", PASS)

    _judge_rate(run, timing, elapsed, thr)


def _judge_rate(run: _Run, timing: list[str], elapsed: float,
                thr: IntegrityThresholds) -> None:
    v = run.violations
    span = (run.last_t0 - run.first_t0
            if run.first_t0 is not None and run.last_t0 is not None else 0.0)
    if Violation.RATE_DRIFT in v:
        run.add("rate_t0", FAIL, _first(v[Violation.RATE_DRIFT]))
    elif timing:
        run.add("rate_t0", SKIP, "t0 is not contiguous, so the rate cannot be read from it")
    elif span < MIN_RATE_SPAN_S:
        run.add("rate_t0", SKIP, f"only {span:.2f} s of t0 (needs {MIN_RATE_SPAN_S:g} s)")
    else:
        observed = (run.samples - run.last_n) / span
        drift = observed / run.rate_fs - 1.0
        detail = f"{observed:.2f} Hz from t0 for a declared {run.rate_fs:g} Hz ({drift:+.2%})"
        run.add("rate_t0", FAIL if abs(drift) > thr.rate_drift_tolerance else PASS, detail)

    first, last = run.data_first_arrival, run.data_last_arrival
    if first is None or last is None or last <= first:
        run.add("rate_arrival", SKIP, "fewer than two usable blocks")
        return
    wall = last - first
    if elapsed > 0 and run.stream_s / elapsed > REALTIME_FACTOR_MAX:
        run.add("rate_arrival", SKIP,
                f"delivered {run.stream_s:.2f} s of stream in {elapsed:.2f} s: a replay "
                "faster than real time, not judged")
    elif wall < MIN_RATE_SPAN_S:
        run.add("rate_arrival", SKIP, f"only {wall:.2f} s between the first and last block "
                f"(needs {MIN_RATE_SPAN_S:g} s)")
    else:
        # Samples that arrived after the first block, over the clock time they took.
        arriving = (run.samples - run.first_n) / wall
        drift = arriving / run.rate_fs - 1.0
        detail = (f"{arriving:.2f} samples/s arriving for a declared {run.rate_fs:g} Hz "
                  f"({drift:+.2%})")
        run.add("rate_arrival", FAIL if abs(drift) > thr.arrival_drift_tolerance else PASS,
                detail)


def _finish(source: BlockSource, run: _Run, *, after_eof: bool) -> None:
    if after_eof:
        try:
            again: Any = source.read()
        except EOFError:
            run.add("read_after_eof", PASS, "raises EOFError again")
        except Exception as exc:
            run.add("read_after_eof", FAIL, f"read() after EOFError raised "
                    f"{type(exc).__name__}: {exc}")
        else:
            if again is None:
                run.add("read_after_eof", PASS, "returns None")
            else:
                run.add("read_after_eof", FAIL, "read() after EOFError returned data")
    else:
        run.add("read_after_eof", SKIP, "the run ended before the stream did")

    err = _call(source.stop)
    run.add("stop", FAIL if err else PASS, f"stop() raised {err}" if err else "")
    err = _call(source.stop)
    run.add("stop_twice", FAIL if err else PASS,
            f"a second stop() raised {err}" if err else "")

    try:
        late: Any = source.read()
    except EOFError:
        run.add("read_after_stop", PASS, "raises EOFError")
    except Exception as exc:
        run.add("read_after_stop", FAIL, f"read() after stop() raised "
                f"{type(exc).__name__}: {exc}")
    else:
        if late is None:
            run.add("read_after_stop", PASS, "returns None")
        else:
            run.add("read_after_stop", WARN, "read() after stop() still returned data; "
                    "a stopped device should not stream")


def _report(source: Any, run: _Run, elapsed: float,
            integrity: IntegrityReport | None) -> ConformanceReport:
    return ConformanceReport(
        source=_name_of(source), clauses=tuple(run.clauses), blocks=run.blocks,
        samples=run.samples, stream_s=run.stream_s, elapsed_s=max(0.0, elapsed),
        eof=run.eof, integrity=integrity,
    )
