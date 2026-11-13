"""Host-side TextLink reader: decode frames from a serial device and print the text.

Research example, not a YazSes feature, and **unverified on hardware**. It reads bytes
from a serial device (or a pseudo-terminal, or a recorded file), feeds them through
:class:`textlink.FrameParser`, applies a rate limiter, and prints each accepted text as
one line of JSON::

    {"seq": 3, "text": "hello world"}

What it deliberately does **not** do: type, paste, inject keystrokes, import
``yazses``, or open a network socket. Text that arrives over a wire is untrusted data;
this program only *shows* it, after the validation in :func:`textlink.decode_text`.
Anything that later consumes these lines must treat them as untrusted too.

Usage::

    python host_reader.py /dev/ttyUSB0                 # real adapter (pyserial if installed)
    python host_reader.py --replay capture.bin         # a recorded byte stream
    python host_reader.py --selftest                   # simulator through the parser, exit 0/1

Diagnostics (counters, dropped frames) go to stderr; stdout carries only the JSON lines.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import select
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any, TextIO


def _sibling(name: str) -> ModuleType:
    """Load a sibling example module by path (this folder is not a package)."""
    key = f"_maixcam2_text_link_{name}"
    cached = sys.modules.get(key)
    if cached is not None:
        return cached
    path = Path(__file__).resolve().with_name(f"{name}.py")
    spec = importlib.util.spec_from_file_location(key, path)
    if spec is None or spec.loader is None:  # pragma: no cover - broken checkout
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[key] = module
    spec.loader.exec_module(module)
    return module


if TYPE_CHECKING:  # mypy: run with MYPYPATH=examples/maixcam2-text-link
    from textlink import Frame, FrameParser, FrameType, RateLimiter
else:
    _tl = _sibling("textlink")
    Frame, FrameParser, FrameType, RateLimiter = (
        _tl.Frame,
        _tl.FrameParser,
        _tl.FrameType,
        _tl.RateLimiter,
    )

DEFAULT_BAUD = 115200
DEFAULT_RATE = 5.0  # accepted text frames per second; spoken text is far slower
READ_SIZE = 4096


def process(
    parser: FrameParser,
    chunk: bytes,
    limiter: RateLimiter | None = None,
    *,
    allow_duplicates: bool = False,
) -> list[tuple[int, str]]:
    """Feed one chunk; return ``(seq, text)`` for every text that should be shown.

    Drops, in order: PING and TRIGGER frames (not text), immediate duplicates (unless
    ``allow_duplicates``), and frames over the rate limit. Rate-limited frames are
    dropped, not delayed.
    """
    return _select(parser.feed(chunk), limiter, allow_duplicates)


def _select(
    frames: Sequence[Frame], limiter: RateLimiter | None, allow_duplicates: bool
) -> list[tuple[int, str]]:
    accepted: list[tuple[int, str]] = []
    for frame in frames:
        if frame.type != FrameType.TEXT or frame.text is None:
            continue
        if frame.duplicate and not allow_duplicates:
            continue
        if limiter is not None and not limiter.allow():
            continue
        accepted.append((frame.seq, frame.text))
    return accepted


def emit(items: Sequence[tuple[int, str]], out: TextIO) -> None:
    """Write one JSON object per accepted text; ``ensure_ascii`` keeps the line inert."""
    for seq, text in items:
        out.write(json.dumps({"seq": seq, "text": text}, ensure_ascii=True) + "\n")
    out.flush()


# -- byte sources ----------------------------------------------------------------


def iter_file(path: str, size: int = READ_SIZE) -> Iterator[bytes]:
    """Yield a recorded stream in chunks."""
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(size)
            if not chunk:
                return
            yield chunk


def _try_pyserial(path: str, baud: int) -> object | None:
    """Open with pyserial if it is installed, else return None. Imported lazily."""
    try:
        import serial  # type: ignore[import-not-found,import-untyped,unused-ignore]
    except ImportError:
        return None
    return serial.Serial(path, baud, bytesize=8, parity="N", stopbits=1, timeout=0.2)


def _configure_tty(fd: int, baud: int) -> None:
    """Best effort: raw 8N1 at ``baud`` on a tty file descriptor (POSIX)."""
    try:
        import termios
        import tty
    except ImportError:  # pragma: no cover - Windows
        return
    try:
        tty.setraw(fd, termios.TCSANOW)  # TCSAFLUSH (the default) would drop bytes already queued
        speed = getattr(termios, f"B{baud}", None)
        if speed is not None:
            attrs = termios.tcgetattr(fd)
            attrs[4] = attrs[5] = speed  # ispeed, ospeed
            termios.tcsetattr(fd, termios.TCSANOW, attrs)
    except (termios.error, OSError):
        pass


def iter_device(path: str, baud: int = DEFAULT_BAUD, idle_s: float = 1.0) -> Iterator[bytes | None]:
    """Yield chunks read from a serial device; yield ``None`` after ``idle_s`` of silence.

    ``None`` lets the caller call :meth:`FrameParser.flush_partial` when the board stalls
    mid-frame. The iterator ends on EOF or when the device disappears.
    """
    port = _try_pyserial(path, baud)
    if port is not None:
        try:
            last = time.monotonic()
            while True:
                chunk: bytes = port.read(READ_SIZE)  # type: ignore[attr-defined]
                if chunk:
                    last = time.monotonic()
                    yield chunk
                elif time.monotonic() - last >= idle_s:
                    last = time.monotonic()
                    yield None
        except OSError:
            return
        finally:
            port.close()  # type: ignore[attr-defined]
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOCTTY", 0))
    try:
        if os.isatty(fd):
            _configure_tty(fd, baud)
        if sys.platform == "win32":  # select() does not work on file descriptors there
            while True:
                chunk = os.read(fd, READ_SIZE)
                if not chunk:
                    return
                yield chunk
        while True:
            ready, _, _ = select.select([fd], [], [], idle_s)
            if not ready:
                yield None
                continue
            try:
                chunk = os.read(fd, READ_SIZE)
            except OSError:  # EIO: the pty/USB adapter went away
                return
            if not chunk:
                return
            yield chunk
    finally:
        os.close(fd)


def run(
    source: Iterator[bytes | None],
    out: TextIO,
    err: TextIO,
    *,
    rate: float = DEFAULT_RATE,
    allow_duplicates: bool = False,
    idle_exit_s: float | None = None,
    idle_tick_s: float = 1.0,
    clock: Callable[[], float] = time.monotonic,
) -> FrameParser:
    """Drive the parser from ``source`` until it ends; print accepted texts to ``out``.

    ``None`` items mean "``idle_tick_s`` of silence": the parser gives up on any frame
    stuck mid-way. With ``idle_exit_s`` set, that much cumulative silence ends the run.
    """
    parser = FrameParser()
    limiter = RateLimiter(rate, clock=clock) if rate > 0 else None
    silent = 0.0
    for chunk in source:
        if chunk is None:
            silent += idle_tick_s
            emit(_select(parser.flush_partial(), limiter, allow_duplicates), out)
            if idle_exit_s is not None and silent >= idle_exit_s:
                break
            continue
        silent = 0.0
        emit(process(parser, chunk, limiter, allow_duplicates=allow_duplicates), out)
    stats = {k: v for k, v in parser.stats().items() if v}
    if limiter is not None and limiter.dropped:
        stats["rate_limited"] = limiter.dropped
    print(f"textlink: {json.dumps(stats, sort_keys=True)}", file=err)
    return parser


# -- self-test -------------------------------------------------------------------


def selftest(out: TextIO | None = None, scenarios: Sequence[Any] | None = None) -> int:
    """Run every simulated scenario through the parser at several chunkings.

    Returns 0 when every text and every counter matches the scenario's expectation and
    the stream result is identical at every split point, else 1 (one line per mismatch).
    """
    sim = _sibling("simulated_board")
    chosen = sim.SCENARIOS if scenarios is None else scenarios
    out = out if out is not None else sys.stdout
    problems: list[str] = []

    def result(chunks: Sequence[bytes]) -> tuple[list[tuple[int, str]], dict[str, int]]:
        parser = FrameParser()
        texts: list[tuple[int, str]] = []
        for chunk in chunks:
            texts += process(parser, chunk)
        return texts, parser.stats()

    for scenario in chosen:
        stream = scenario.stream
        want_counters = {k: 0 for k in FrameParser.COUNTERS} | dict(scenario.expected_counters)
        want = (list(scenario.expected_texts), want_counters)
        got = result([stream])
        if got != want:
            problems.append(f"{scenario.name}: whole stream: got {got}, want {want}")
            continue
        strategies = [sim.chunked(stream, n) for n in (1, 2, 3, 7, 64)]
        stride = max(1, len(stream) // 256)  # every split point for short streams, sampled for long
        strategies += [[stream[:i], stream[i:]] for i in range(0, len(stream) + 1, stride)]
        for chunks in strategies:
            if result(chunks) != want:
                problems.append(
                    f"{scenario.name}: differs when split at {[len(c) for c in chunks][:2]}"
                )
                break

    clock_now = [0.0]
    limiter = RateLimiter(2.0, clock=lambda: clock_now[0])
    burst = [limiter.allow() for _ in range(4)]
    clock_now[0] += 0.5
    later = limiter.allow()
    if burst != [True, True, False, False] or later is not True or limiter.dropped != 2:
        problems.append(f"rate limiter: burst={burst} later={later} dropped={limiter.dropped}")

    for line in problems:
        print(f"SELFTEST FAIL {line}", file=out)
    if problems:
        return 1
    print(f"selftest ok: {len(chosen)} scenarios, chunkings identical", file=out)
    return 0


# -- CLI -------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Read TextLink frames from a serial device and print the text as JSON lines. "
        "Never types, never uses the network."
    )
    ap.add_argument("device", nargs="?", help="serial device or pty path, e.g. /dev/ttyUSB0")
    ap.add_argument("--baud", type=int, default=DEFAULT_BAUD, help="default 115200 (8N1)")
    ap.add_argument(
        "--replay", metavar="FILE", help="read a recorded byte stream instead of a device"
    )
    ap.add_argument(
        "--rate",
        type=float,
        default=None,
        help=f"max accepted text frames per second, excess dropped (0 = unlimited); "
        f"default {DEFAULT_RATE:g} for a device, unlimited for --replay",
    )
    ap.add_argument(
        "--allow-duplicates",
        action="store_true",
        help="also print an exact immediate repeat of the previous frame",
    )
    ap.add_argument(
        "--idle-exit",
        type=float,
        metavar="SECONDS",
        help="exit after this long with no bytes (default: run until the device closes)",
    )
    ap.add_argument(
        "--selftest",
        action="store_true",
        help="run the simulator through the parser; exit non-zero on any mismatch",
    )
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()
    if bool(args.replay) == bool(args.device):
        ap.error("give exactly one of DEVICE or --replay FILE")
    try:
        source: Iterator[bytes | None]
        if args.replay:
            source = iter_file(args.replay)
        else:
            source = iter_device(args.device, args.baud)
        run(
            source,
            sys.stdout,
            sys.stderr,
            rate=(0.0 if args.replay else DEFAULT_RATE) if args.rate is None else args.rate,
            allow_duplicates=args.allow_duplicates,
            idle_exit_s=args.idle_exit,
        )
    except KeyboardInterrupt:
        return 130
    except OSError as exc:
        print(f"host_reader: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
