"""A simulated MaixCAM2 board: scripted TextLink byte streams for tests and demos.

Research example, not a YazSes feature, and **not a model of real hardware**: it plays
back what the wire protocol says a board *would* send, including the faults a real UART
link produces (garbage, truncation, bit errors, a reboot, a stall). Whether a real
board's UART behaves like this is untested.

Each :class:`Scenario` carries the bytes (as timed :class:`Event` chunks), the texts a
correct receiver must output, and the parser counters it must end with. The receiver's
output for the stream is the same however the bytes are chunked, which the tests check
at every split point.

Run it::

    python simulated_board.py --list
    python simulated_board.py --hex hostile          # the raw frames, as hex
    python simulated_board.py --pty                  # expose through a pseudo-terminal (POSIX)

``--pty`` prints the slave device path; point ``host_reader.py`` at it.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, TextIO


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
    from textlink import FrameType, crc16_ccitt_false, encode, encode_text
else:
    _tl = _sibling("textlink")
    FrameType, encode, encode_text = _tl.FrameType, _tl.encode, _tl.encode_text
    crc16_ccitt_false = _tl.crc16_ccitt_false


@dataclass(frozen=True)
class Event:
    """Bytes the board writes, after waiting ``delay_s`` seconds."""

    data: bytes
    delay_s: float = 0.0


@dataclass(frozen=True)
class Scenario:
    """A scripted run: what is sent, and what a correct receiver must make of it.

    ``expected_texts`` is ``(seq, text)`` for every text a receiver that drops
    immediate duplicates must output. ``expected_counters`` lists the parser counters
    that must have exactly these values at the end; counters not listed must be 0.
    """

    name: str
    description: str
    events: tuple[Event, ...]
    expected_texts: tuple[tuple[int, str], ...]
    expected_counters: Mapping[str, int] = field(default_factory=dict)

    @property
    def stream(self) -> bytes:
        """All bytes of the scenario, concatenated."""
        return b"".join(e.data for e in self.events)


def chunked(data: bytes, size: int) -> list[bytes]:
    """Split ``data`` into pieces of at most ``size`` bytes (``size >= 1``)."""
    return [data[i : i + size] for i in range(0, len(data), size)]


def _scenario(
    name: str,
    description: str,
    parts: Iterable[bytes | Event],
    texts: Sequence[tuple[int, str]],
    counters: Mapping[str, int],
) -> Scenario:
    events = tuple(p if isinstance(p, Event) else Event(p) for p in parts)
    return Scenario(name, description, events, tuple(texts), dict(counters))


def _raw_frame(
    version: int, ftype: int, seq: int, payload: bytes, *, good_crc: bool = True
) -> bytes:
    """Hand-build a frame that :func:`textlink.encode` would refuse to produce."""
    body = bytes((version, ftype, seq)) + len(payload).to_bytes(2, "big") + payload
    crc = crc16_ccitt_false(body) if good_crc else (crc16_ccitt_false(body) ^ 0x0101) & 0xFFFF
    return b"YS" + body + crc.to_bytes(2, "big")


def _text_raw(seq: int, payload: bytes) -> bytes:
    """A valid-CRC TEXT frame around *any* payload (the encoder would not validate it)."""
    return encode(FrameType.TEXT, seq, payload)


def _build() -> tuple[Scenario, ...]:
    out: list[Scenario] = []

    out.append(
        _scenario(
            "clean",
            "three plain sentences, one frame each",
            [
                encode_text("hello world", 0),
                encode_text("this is a test of the text link", 1),
                encode_text("the quick brown fox", 2),
            ],
            [
                (0, "hello world"),
                (1, "this is a test of the text link"),
                (2, "the quick brown fox"),
            ],
            {"frames_ok": 3},
        )
    )

    # One byte per event: every multi-byte character is split across reads.
    mb = [
        (0, "你好，世界"),
        (1, "Café déjà vu, naïve façade"),
        (2, "می‌خواهم یک چای"),  # Persian with ZWNJ, which must survive
        (3, "ça va 😀"),
    ]
    mb_frames = [encode_text(t, s) for s, t in mb]
    nfd = _text_raw(4, "école".encode())  # decomposed on the wire, NFC on arrival
    mb_stream = b"".join(mb_frames) + nfd
    out.append(
        _scenario(
            "multibyte_split",
            "Chinese, accented, Persian (ZWNJ), emoji and an NFD string, sent one byte per read",
            [mb_stream[i : i + 1] for i in range(len(mb_stream))],
            [*mb, (4, "école")],
            {"frames_ok": 5},
        )
    )

    garbage = b"\x00\xff\x7fnoise Y"  # ends in 0x59, immediately before the SYNC 'YS'
    mid = b"\x00\x00\x00"
    out.append(
        _scenario(
            "garbage_prefix",
            "line noise before the first frame, a lone 0x59 right before a SYNC, noise between frames",
            [garbage, encode_text("after the noise", 0), mid, encode_text("and again", 1)],
            [(0, "after the noise"), (1, "and again")],
            {"frames_ok": 2, "resync_bytes": len(garbage) + len(mid)},
        )
    )

    cut = encode_text("this one gets cut short by a glitch", 1)[:20]
    out.append(
        _scenario(
            "truncated_then_recovery",
            "frame 1 loses its tail; the receiver must recover the frames behind it",
            [
                encode_text("first sentence is fine", 0),
                cut,
                encode_text("recovered fine", 2),
                encode_text("and the next one", 3),
                encode_text("and one more", 4),
            ],
            [
                (0, "first sentence is fine"),
                (2, "recovered fine"),
                (3, "and the next one"),
                (4, "and one more"),
            ],
            {"frames_ok": 4, "bad_crc": 1, "resync_bytes": len(cut), "seq_gaps": 1},
        )
    )

    bad = bytearray(encode_text("a bit flipped on the wire", 1))
    bad[12] ^= 0x04
    out.append(
        _scenario(
            "bad_crc",
            "one payload bit flipped in transit; that frame is dropped, the rest survive",
            [encode_text("before", 0), bytes(bad), encode_text("after", 2)],
            [(0, "before"), (2, "after")],
            {"frames_ok": 2, "bad_crc": 1, "resync_bytes": len(bad), "seq_gaps": 1},
        )
    )

    over1 = b"YS\x01\x01\x01\x02\x01" + b"x" * 20  # LEN = 513
    over2 = b"YS\x01\x01\x02\xff\xff" + b"junk"  # LEN = 65535
    out.append(
        _scenario(
            "oversize",
            "LEN larger than 512: never trusted, never waited for",
            [encode_text("start", 0), over1, over2, encode_text("end", 1)],
            [(0, "start"), (1, "end")],
            {"frames_ok": 2, "oversize": 2, "resync_bytes": len(over1) + len(over2)},
        )
    )

    future = _raw_frame(2, 1, 9, b"a frame from a future wire version")
    out.append(
        _scenario(
            "bad_version",
            "a well-formed frame with VER 2 is skipped as noise, not interpreted",
            [encode_text("v1 one", 0), future, encode_text("v1 two", 1)],
            [(0, "v1 one"), (1, "v1 two")],
            {"frames_ok": 2, "bad_version": 1, "resync_bytes": len(future)},
        )
    )

    badlen = _raw_frame(1, int(FrameType.PING), 5, b"abc")
    out.append(
        _scenario(
            "bad_length",
            "a PING that claims a payload is a protocol violation",
            [encode_text("one", 0), badlen, encode_text("two", 1)],
            [(0, "one"), (1, "two")],
            {"frames_ok": 2, "bad_length": 1, "resync_bytes": len(badlen)},
        )
    )

    out.append(
        _scenario(
            "seq_skip",
            "SEQ jumps 1 -> 5: frames were lost somewhere; the texts that did arrive are kept",
            [
                encode_text("zero", 0),
                encode_text("one", 1),
                encode_text("five", 5),
                encode_text("six", 6),
            ],
            [(0, "zero"), (1, "one"), (5, "five"), (6, "six")],
            {"frames_ok": 4, "seq_gaps": 1},
        )
    )

    out.append(
        _scenario(
            "seq_replay",
            "an immediate exact repeat is dropped by the reader; a later replay is not detected",
            [
                encode_text("alpha", 0),
                encode_text("alpha", 0),
                encode_text("bravo", 1),
                encode_text("alpha", 0),
            ],
            [(0, "alpha"), (1, "bravo"), (0, "alpha")],
            {"frames_ok": 4, "duplicates": 1, "seq_gaps": 1},
        )
    )

    hostile: list[tuple[str, bytes]] = [
        ("newline", b"line one\nline two"),
        ("escape", b"\x1b[31mred\x1b[0m"),
        ("bidi override", "evil ‮txet".encode()),
        ("nul", b"nul\x00byte"),
        ("tab", b"tab\there"),
        ("line separator", "sep arator".encode()),
        ("c1 control", "c1\u0085next".encode()),
        ("del", b"del\x7fchar"),
        ("blank", "   ".encode()),
        ("invalid utf-8", b"\xff\xfe\xfd"),
        ("overlong", b"\xc0\xaf"),
        ("surrogate", b"\xed\xa0\x80"),
    ]
    hostile_frames = [_text_raw(i, p) for i, (_, p) in enumerate(hostile)]
    n = len(hostile)
    out.append(
        _scenario(
            "hostile",
            "payloads with newline, ESC, bidi override, NUL, tab, U+2028, C1, DEL, blank, bad UTF-8",
            [*hostile_frames, encode_text("safe text after the hostile ones", n)],
            [(n, "safe text after the hostile ones")],
            {"frames_ok": 1, "invalid_text": n},
        )
    )

    out.append(
        _scenario(
            "ping_heartbeats",
            "PING and TRIGGER frames interleaved with text; none of them is text",
            [
                encode(FrameType.PING, 0),
                encode_text("alive", 1),
                encode(FrameType.PING, 2),
                encode(FrameType.PING, 3),
                encode(FrameType.TRIGGER, 4),
                encode_text("done", 5),
            ],
            [(1, "alive"), (5, "done")],
            {"frames_ok": 6},
        )
    )

    out.append(
        _scenario(
            "reboot",
            "the board resets and SEQ restarts at 0: one discontinuity, nothing dropped",
            [
                encode_text("one", 0),
                encode_text("two", 1),
                encode_text("three", 2),
                encode_text("four after reboot", 0),
                encode_text("five", 1),
            ],
            [(0, "one"), (1, "two"), (2, "three"), (0, "four after reboot"), (1, "five")],
            {"frames_ok": 5, "seq_gaps": 1},
        )
    )

    whole = encode_text("this sentence is delivered with a long pause in the middle", 1)
    half = len(whole) // 2
    out.append(
        _scenario(
            "stall",
            "the line goes quiet in the middle of a frame, then continues",
            [
                encode_text("before the stall", 0),
                whole[:half],
                Event(whole[half:], 2.5),
                encode_text("after the stall", 2),
            ],
            [
                (0, "before the stall"),
                (1, "this sentence is delivered with a long pause in the middle"),
                (2, "after the stall"),
            ],
            {"frames_ok": 3},
        )
    )

    ascii512 = "a" * 512
    cjk = "漢" * 170  # 3 bytes each: 510 bytes
    out.append(
        _scenario(
            "max_length",
            "TEXT payloads at the 512-byte limit",
            [encode_text(ascii512, 0), encode_text(cjk, 1)],
            [(0, ascii512), (1, cjk)],
            {"frames_ok": 2},
        )
    )
    return tuple(out)


SCENARIOS: tuple[Scenario, ...] = _build()
SCENARIO_BY_NAME: dict[str, Scenario] = {s.name: s for s in SCENARIOS}


def serve_pty(
    scenarios: Sequence[Scenario] | None = None,
    *,
    delay_scale: float = 1.0,
    linger_s: float = 1.0,
    on_ready: Callable[[str], None] | None = None,
    out: TextIO | None = None,
) -> None:
    """Play scenarios through a pseudo-terminal (POSIX only).

    Prints the slave device path (one line, to ``out`` or stdout) and calls
    ``on_ready(path)``; a reader opens that path like a serial device. The slave is
    put in raw mode so bytes are not translated, and the server keeps its own slave
    descriptor open so the reader never sees a hang-up mid-run. Writes block if nobody
    reads (the pty buffer is small), which is the right behaviour for a demo. After
    the last byte it waits ``linger_s`` so the reader can drain, then closes.
    ``delay_scale`` multiplies each event's delay (0 disables stalls).
    """
    if sys.platform == "win32":
        raise RuntimeError("serve_pty needs a POSIX pseudo-terminal")
    import os
    import pty
    import tty

    chosen = SCENARIOS if scenarios is None else tuple(scenarios)
    master, slave = pty.openpty()
    try:
        tty.setraw(slave)
        path = os.ttyname(slave)
        print(path, file=out if out is not None else sys.stdout, flush=True)
        if on_ready is not None:
            on_ready(path)
        for scenario in chosen:
            for event in scenario.events:
                if event.delay_s and delay_scale:
                    time.sleep(event.delay_s * delay_scale)
                view = memoryview(event.data)
                while view:
                    view = view[os.write(master, view) :]
        time.sleep(linger_s)
    finally:
        os.close(master)
        os.close(slave)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Simulated MaixCAM2 TextLink board.")
    ap.add_argument("--list", action="store_true", help="list scenarios and exit")
    ap.add_argument("--hex", metavar="NAME", help="print a scenario's bytes as hex and exit")
    ap.add_argument("--pty", action="store_true", help="serve scenarios through a pseudo-terminal")
    ap.add_argument(
        "--scenario",
        action="append",
        metavar="NAME",
        help="with --pty: only this scenario (repeatable); default all",
    )
    ap.add_argument(
        "--delay-scale",
        type=float,
        default=1.0,
        help="with --pty: multiply stall delays (0 = no stalls)",
    )
    args = ap.parse_args(argv)
    if args.list:
        for s in SCENARIOS:
            print(f"{s.name:24s} {len(s.stream):5d} bytes  {s.description}")
        return 0
    if args.hex:
        if args.hex not in SCENARIO_BY_NAME:
            print(f"unknown scenario {args.hex!r}", file=sys.stderr)
            return 2
        print(SCENARIO_BY_NAME[args.hex].stream.hex(" "))
        return 0
    if args.pty:
        names = args.scenario or [s.name for s in SCENARIOS]
        unknown = [n for n in names if n not in SCENARIO_BY_NAME]
        if unknown:
            print(f"unknown scenario(s): {', '.join(unknown)}", file=sys.stderr)
            return 2
        try:
            serve_pty([SCENARIO_BY_NAME[n] for n in names], delay_scale=args.delay_scale)
        except KeyboardInterrupt:
            return 130
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
