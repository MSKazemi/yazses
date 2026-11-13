"""TextLink: a tiny, checksummed frame codec for sending recognised text over a UART.

Research example, not a YazSes feature. Nothing under ``src/yazses/`` imports this
module and it is not wired into the daemon (ADR-030 freezes new capabilities). It is
the pure, dependency-free half of an experiment: could a Sipeed MaixCAM2 board that
runs Whisper-base on-device send the text it recognised to a desktop over a wire?
This module is the *wire format* and nothing else. It is **unverified on hardware**.

The normative description is ``design/specs/textlink-wire-protocol.md``. In short::

    8N1 UART, 115200 baud (a property of the link, not enforced here)

    SYNC    VER   TYPE  SEQ   LEN     PAYLOAD      CRC16
    'YS'    0x01  u8    u8    u16     LEN bytes    u16
    all multi-byte integers big-endian; CRC-16/CCITT-FALSE over VER..PAYLOAD

Design decisions, each deliberate:

* **Stdlib only.** The module imports nothing outside the standard library, so it can
  be copied onto a board or into a test without a dependency.
* **Never raise on content.** For any bytes-like input (``bytes``, ``bytearray``, any
  ``memoryview``), :meth:`FrameParser.feed` never raises whatever the bytes contain;
  damage is counted, not thrown. A ``str`` or other non-bytes-like argument is a caller
  error and raises :class:`TypeError`. (The *encoder* raises :class:`ValueError`, because a
  caller building a frame controls its input.)
* **Chunking is invisible.** The parser's output and counters depend only on the
  concatenation of the bytes fed, never on how they were split across ``feed`` calls
  (a UART read returns whatever happens to be in the FIFO). A UTF-8 character split
  across two reads is therefore harmless: UTF-8 is decoded only once a whole,
  CRC-checked payload is in hand.
* **Resynchronise by dropping one byte.** On any framing error (bad version, oversize or
  inconsistent length, bad CRC) the parser discards exactly the first byte of the
  suspect frame and scans for the next ``SYNC``. It never trusts a corrupt LEN to skip
  ahead, so a truncated frame cannot swallow the good frames behind it, and every
  iteration consumes at least one byte, so it cannot loop forever.
* **Bounded memory.** At most one incomplete frame (<= :data:`MAX_FRAME_LEN` bytes) is
  buffered, plus one 4096-byte input slice, however much is fed.
* **Text from a wire is untrusted.** A TEXT payload is accepted only if it is strict
  UTF-8, contains no control, format, line-separator, bidirectional-control or invisible
  character, has some visible content and stays within 512 bytes after NFC (see
  :func:`decode_text`). A refused frame is dropped and counted, never repaired. Mixed-script
  look-alike text is *not* handled; a consumer that types the text needs its own check.
* **SEQ is advisory and nothing is dropped because of it.** It exists to *measure* loss.
  The parser counts gaps (``seq_gaps``) and exact immediate repeats (``seq_repeats``) and
  delivers every CRC-valid frame. The protocol has no retransmission and no ACK, so a
  receiver cannot tell a retransmitted frame from a repeated utterance ("yes", "yes");
  replay protection is out of scope.
"""

from __future__ import annotations

import math
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum

__all__ = [
    "MAX_FRAME_LEN",
    "MAX_PAYLOAD",
    "MAX_TEXT_BYTES",
    "REFUSED_CHARS",
    "SYNC",
    "VERSION",
    "Frame",
    "FrameParser",
    "FrameType",
    "InvalidText",
    "RateLimiter",
    "crc16_ccitt_false",
    "decode_text",
    "encode",
    "encode_text",
]

SYNC = b"YS"  #: frame start marker, 0x59 0x53
VERSION = 0x01  #: the only wire version this module speaks
MAX_TEXT_BYTES = 512  #: longest TEXT payload on the wire, in UTF-8 bytes
MAX_PAYLOAD = 512  #: no frame of any type may carry more; larger LEN is a framing error
HEADER_LEN = 7  #: SYNC(2) + VER(1) + TYPE(1) + SEQ(1) + LEN(2)
CRC_LEN = 2
MAX_FRAME_LEN = HEADER_LEN + MAX_PAYLOAD + CRC_LEN  #: 521 bytes
_FEED_SLICE = 4096  #: feed() processes input in slices this big, bounding the buffer


class FrameType(IntEnum):
    """Frame types of wire version 1."""

    TEXT = 0x01  #: UTF-8 text, LEN 1..512
    TRIGGER = 0x02  #: "start now" marker, LEN 0
    PING = 0x03  #: heartbeat, LEN 0


_EMPTY_TYPES = (FrameType.TRIGGER, FrameType.PING)
_KNOWN_TYPES = frozenset(int(t) for t in FrameType)

# What TEXT may not contain. Refused outright, by Unicode general category: Cc (C0, DEL,
# C1: a newline would press Enter, an ESC could start a terminal escape sequence), Cf
# (format characters: zero-width space, word joiner, BOM, tag characters, the bidirectional
# controls of the "Trojan Source" class, ...) and Cs (lone surrogates). The only Cf
# exceptions are U+200C and U+200D (ZWNJ, ZWJ): Persian, Arabic and Indic scripts need them
# to spell ordinary words, so they are allowed, but only when the text also contains a
# letter (see _validate_text).
#
# REFUSED_CHARS lists the characters that no category rule above covers: the line and
# paragraph separators, the noncharacters U+FFFE/U+FFFF, the replacement character
# U+FFFD, and the invisible fillers (braille blank and the Hangul fillers) that render as
# nothing. board/maixpy_send.py mirrors this set inline; a test compares the two.
REFUSED_CHARS = frozenset(
    chr(c)
    for c in (
        0x2028,  # LINE SEPARATOR
        0x2029,  # PARAGRAPH SEPARATOR
        0xFFFE,  # noncharacter
        0xFFFF,  # noncharacter
        0xFFFD,  # REPLACEMENT CHARACTER
        0x2800,  # BRAILLE PATTERN BLANK
        0x3164,  # HANGUL FILLER
        0xFFA0,  # HALFWIDTH HANGUL FILLER
        0x115F,  # HANGUL CHOSEONG FILLER
        0x1160,  # HANGUL JUNGSEONG FILLER
    )
)
_JOINERS = frozenset({chr(0x200C), chr(0x200D)})  # ZWNJ, ZWJ: Cf, allowed beside a letter
_REFUSED_CATEGORIES = frozenset({"Cc", "Cf", "Cs"})
_SEPARATORS = frozenset({chr(0x2028), chr(0x2029)})  # only to label the refusal reason
# Only to label the refusal reason "bidi" (all of these are category Cf as well).
_BIDI = frozenset(
    {chr(0x200E), chr(0x200F), chr(0x061C)}
    | {chr(c) for c in range(0x202A, 0x202F)}  # LRE RLE PDF LRO RLO
    | {chr(c) for c in range(0x2066, 0x206A)}  # LRI RLI FSI PDI
)


def _build_crc_table() -> tuple[int, ...]:
    table = []
    for byte in range(256):
        crc = byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
        table.append(crc)
    return tuple(table)


_CRC_TABLE = _build_crc_table()


def crc16_ccitt_false(data: bytes | bytearray | memoryview, crc: int = 0xFFFF) -> int:
    """CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF, no reflection, no xorout.

    Check value: ``crc16_ccitt_false(b"123456789") == 0x29B1``. Passing the previous
    result as ``crc`` continues a running checksum.
    """
    for byte in data:
        crc = ((crc << 8) & 0xFFFF) ^ _CRC_TABLE[(crc >> 8) ^ byte]
    return crc


class InvalidText(ValueError):
    """A TEXT payload (or a string offered to the encoder) failed validation.

    ``reason`` is a short stable token: ``utf8``, ``control``, ``separator``, ``bidi``,
    ``format``, ``invisible``, ``too_long`` or ``empty`` (no visible content).
    """

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


def _validate_text(text: str) -> str:
    """NFC-normalise, refuse forbidden characters, strip, require visible content, cap."""
    text = unicodedata.normalize("NFC", text)
    has_joiner = False
    has_letter = False
    for ch in text:
        category = unicodedata.category(ch)
        if category == "Cs":
            raise InvalidText("utf8", f"lone surrogate U+{ord(ch):04X}")
        if category == "Cc":  # C0 (incl. NUL, TAB, LF, CR, ESC), DEL, C1
            raise InvalidText("control", f"U+{ord(ch):04X}")
        if ch in _SEPARATORS:
            raise InvalidText("separator", f"U+{ord(ch):04X}")
        if ch in _BIDI:
            raise InvalidText("bidi", f"U+{ord(ch):04X}")
        if ch in _JOINERS:
            has_joiner = True
        elif category in _REFUSED_CATEGORIES:  # Cf: zero-width, BOM, tags, ...
            raise InvalidText("format", f"U+{ord(ch):04X}")
        elif ch in REFUSED_CHARS:  # noncharacters, U+FFFD, invisible fillers
            raise InvalidText("invisible", f"U+{ord(ch):04X}")
        if category[0] == "L":
            has_letter = True
    if has_joiner and not has_letter:
        raise InvalidText("format", "ZWNJ/ZWJ without a letter")
    text = text.strip()
    if not any(unicodedata.category(ch)[0] in "LNPS" for ch in text):
        raise InvalidText("empty", "no visible content")
    if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
        raise InvalidText("too_long", "more than 512 bytes after NFC")
    return text


def decode_text(payload: bytes | bytearray) -> str:
    """Turn a TEXT payload into text a consumer may safely look at, or raise.

    Steps, in this order; any failure refuses the whole payload (it is never
    "repaired" or partially kept):

    1. strict UTF-8 decode (no replacement characters, no surrogates, no overlong forms);
    2. NFC normalisation, so the same sentence always arrives as the same code points;
    3. refusal of every C0 control (including NUL, TAB, LF, CR, ESC), DEL and every C1
       control: a newline would press Enter and an ESC could start a terminal escape
       sequence if the text were ever typed or echoed. Multi-line text is not supported;
    4. refusal of U+2028/U+2029 and of every character of unicode category Cf (format:
       zero-width space, word joiner, BOM, tag characters, the bidirectional controls
       U+202A-202E, U+2066-2069, U+200E, U+200F and U+061C, ...). U+200C and U+200D are
       the exception, allowed only when the text also contains a letter;
    5. refusal of the noncharacters U+FFFE/U+FFFF, the replacement character U+FFFD and the
       invisible fillers U+2800, U+3164, U+FFA0, U+115F, U+1160 (:data:`REFUSED_CHARS`);
    6. surrounding whitespace is stripped, and text with no *visible content* afterwards
       is refused: at least one character of category L, N, P or S is required, so spaces
       only, a lone combining mark or a lone ZWNJ count as empty;
    7. the normalised, stripped text must still fit in :data:`MAX_TEXT_BYTES` bytes of
       UTF-8. NFC can *expand* text (U+0344 becomes two characters and doubles in size),
       so a payload that fit on the wire can be refused here.

    Not handled: mixed-script or homoglyph text (a Cyrillic letter inside a Latin word).
    A consumer that types the text must apply its own confusable check.
    """
    try:
        text = bytes(payload).decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise InvalidText("utf8", exc.reason) from None
    return _validate_text(text)


def encode(frame_type: int, seq: int, payload: bytes = b"") -> bytes:
    """Build one wire frame. Raises :class:`ValueError` on anything the wire cannot carry.

    ``seq`` must be 0..255 (callers wrap with ``(seq + 1) & 0xFF``). TEXT needs a
    payload of 1..512 bytes; TRIGGER and PING need an empty payload. This function does
    not validate TEXT *content*; use :func:`encode_text` for that.
    """
    try:
        ftype = FrameType(frame_type)
    except ValueError:
        raise ValueError(f"unknown frame type {frame_type!r}") from None
    if not 0 <= seq <= 0xFF:
        raise ValueError(f"seq must be 0..255, got {seq}")
    payload = bytes(payload)
    if ftype in _EMPTY_TYPES and payload:
        raise ValueError(f"{ftype.name} frames carry no payload")
    if ftype is FrameType.TEXT and not 1 <= len(payload) <= MAX_TEXT_BYTES:
        raise ValueError(f"TEXT payload must be 1..{MAX_TEXT_BYTES} bytes, got {len(payload)}")
    body = bytes((VERSION, ftype, seq)) + len(payload).to_bytes(2, "big") + payload
    return SYNC + body + crc16_ccitt_false(body).to_bytes(2, "big")


def encode_text(text: str, seq: int) -> bytes:
    """Build a TEXT frame, applying the same validation the receiver will apply.

    The text is NFC-normalised and stripped; a string the receiver would refuse
    (control, format or invisible characters, no visible content, more than 512 UTF-8
    bytes after normalisation) raises :class:`InvalidText`.
    """
    clean = _validate_text(text)
    return encode(FrameType.TEXT, seq, clean.encode("utf-8"))


@dataclass(frozen=True)
class Frame:
    """One CRC-valid frame handed out by :class:`FrameParser`.

    ``text`` is set for TEXT frames (already validated) and ``None`` otherwise.
    ``seq_skipped`` is how many frames the SEQ counter jumped over relative to the
    previous valid frame (0 when continuous or when this is the first frame). A board
    reboot restarts SEQ and therefore shows up as a (large) skip, not as an error.
    ``seq_repeat`` is true for an exact immediate repeat of the previous valid frame
    (same SEQ, TYPE and payload); the frame is delivered all the same, because a repeat
    cannot be told from a repeated utterance.
    """

    type: int
    seq: int
    payload: bytes
    text: str | None = None
    seq_skipped: int = 0
    seq_repeat: bool = False


class FrameParser:
    """Incremental, chunking-invariant frame parser. See the module docstring.

    Usage::

        parser = FrameParser()
        for chunk in serial_reads():
            for frame in parser.feed(chunk):
                ...

    ``feed`` returns the frames completed by this chunk: every CRC-valid frame of a
    known type, except TEXT frames whose payload fails :func:`decode_text`. Counters
    (plain ``int`` attributes, all start at 0):

    ``frames_ok``       CRC-valid frames of known type with a valid payload returned
    ``bad_crc``         frames whose CRC did not match (dropped; resynchronised)
    ``oversize``        frames whose LEN exceeded :data:`MAX_PAYLOAD`
    ``bad_version``     SYNC followed by a VER other than :data:`VERSION`
    ``bad_length``      TRIGGER/PING frames with a non-zero LEN
    ``resync_bytes``    bytes discarded while hunting for the next SYNC
    ``seq_gaps``        valid frames whose SEQ was not the expected next value
    ``seq_repeats``     exact immediate repeats of the previous valid frame (delivered)
    ``invalid_text``    CRC-valid TEXT frames refused by :func:`decode_text`
    ``unknown_type``    CRC-valid frames of a TYPE this version does not define (ignored)
    """

    COUNTERS = (
        "frames_ok",
        "bad_crc",
        "oversize",
        "bad_version",
        "bad_length",
        "resync_bytes",
        "seq_gaps",
        "seq_repeats",
        "invalid_text",
        "unknown_type",
    )

    def __init__(self) -> None:
        self._buf = bytearray()
        self._last: tuple[int, int, bytes] | None = None  # (seq, type, payload)
        self.frames_ok = 0
        self.bad_crc = 0
        self.oversize = 0
        self.bad_version = 0
        self.bad_length = 0
        self.resync_bytes = 0
        self.seq_gaps = 0
        self.seq_repeats = 0
        self.invalid_text = 0
        self.unknown_type = 0

    @property
    def buffered(self) -> int:
        """Bytes currently held back waiting for the rest of a frame (always <= 521)."""
        return len(self._buf)

    def stats(self) -> dict[str, int]:
        """A snapshot of every counter."""
        return {name: int(getattr(self, name)) for name in self.COUNTERS}

    def feed(self, chunk: bytes | bytearray | memoryview) -> list[Frame]:
        """Consume bytes, return the frames they completed.

        Accepts any bytes-like object, including a non-contiguous ``memoryview``, and never
        raises for such input whatever the bytes are. A ``str`` or any other object that is
        not bytes-like raises :class:`TypeError`.
        """
        out: list[Frame] = []
        view = memoryview(chunk)  # TypeError for a str, an int, None, ...
        try:
            view = view.cast("B")
        except TypeError:  # non-contiguous (strided) view: copy it into contiguous bytes
            view = memoryview(view.tobytes())
        for start in range(0, len(view), _FEED_SLICE):
            self._buf += view[start : start + _FEED_SLICE]
            self._drain(out, final=False)
        return out

    def flush_partial(self) -> list[Frame]:
        """Give up on an incomplete frame held at the head of the buffer.

        Call this when the line has been idle (the board stalled mid-frame) and when the
        input has ended (EOF, end of a replay). Bytes that cannot complete a frame are
        discarded and parsing resumes from the next SYNC, so complete frames queued
        *behind* a dead one are still recovered. This is the only entry point whose result
        depends on timing, which is why it is separate from :meth:`feed`. After it returns
        the buffer is empty.
        """
        out: list[Frame] = []
        self._drain(out, final=True)
        return out

    # -- internals ---------------------------------------------------------------

    def _drain(self, out: list[Frame], *, final: bool) -> None:
        buf = self._buf
        n = len(buf)
        pos = 0
        while True:
            idx = buf.find(SYNC, pos)
            if idx < 0:
                # Keep a trailing 'Y': it may be the first half of a SYNC split by the
                # chunk boundary. Anything else is garbage.
                keep = 1 if (n > pos and buf[n - 1] == SYNC[0] and not final) else 0
                self.resync_bytes += n - pos - keep
                pos = n - keep
                break
            if idx > pos:
                self.resync_bytes += idx - pos
                pos = idx
            avail = n - pos
            if avail < HEADER_LEN:
                if not final:
                    break
                self.resync_bytes += 1
                pos += 1
                continue
            version = buf[pos + 2]
            ftype = buf[pos + 3]
            length = (buf[pos + 5] << 8) | buf[pos + 6]
            if version != VERSION:
                self.bad_version += 1
                self.resync_bytes += 1
                pos += 1
                continue
            if length > MAX_PAYLOAD:
                self.oversize += 1
                self.resync_bytes += 1
                pos += 1
                continue
            if length and ftype in _EMPTY_TYPES:
                self.bad_length += 1
                self.resync_bytes += 1
                pos += 1
                continue
            total = HEADER_LEN + length + CRC_LEN
            if avail < total:
                if not final:
                    break
                self.resync_bytes += 1
                pos += 1
                continue
            body_end = pos + HEADER_LEN + length
            got = (buf[body_end] << 8) | buf[body_end + 1]
            if crc16_ccitt_false(memoryview(buf)[pos + 2 : body_end]) != got:
                self.bad_crc += 1
                self.resync_bytes += 1
                pos += 1
                continue
            self._accept(ftype, buf[pos + 4], bytes(buf[pos + HEADER_LEN : body_end]), out)
            pos += total
        del buf[:pos]

    def _accept(self, ftype: int, seq: int, payload: bytes, out: list[Frame]) -> None:
        key = (seq, ftype, payload)
        if key == self._last:
            self.seq_repeats += 1
            repeat, skipped = True, 0
        else:
            repeat = False
            skipped = 0 if self._last is None else (seq - self._last[0] - 1) & 0xFF
            if skipped:
                self.seq_gaps += 1
            self._last = key
        if ftype not in _KNOWN_TYPES:
            self.unknown_type += 1
            return
        text: str | None = None
        if ftype == FrameType.TEXT:
            try:
                text = decode_text(payload)
            except InvalidText:
                self.invalid_text += 1
                return
        self.frames_ok += 1
        out.append(Frame(ftype, seq, payload, text, skipped, repeat))


class RateLimiter:
    """A conservative token bucket: at most ``max_frames_per_second`` on average.

    Spoken text arrives at human speed; a burst far above that is a fault or an attack,
    and text that may end up typed is the wrong thing to queue and release later. So
    excess frames are **dropped, never delayed** (``dropped`` counts them).

    ``burst`` is the bucket capacity (default ``max(1, int(rate))``). ``clock`` is
    injectable so tests are deterministic.
    """

    def __init__(
        self,
        max_frames_per_second: float,
        burst: int | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not math.isfinite(max_frames_per_second) or max_frames_per_second <= 0:
            raise ValueError("max_frames_per_second must be a finite number > 0")
        self.rate = float(max_frames_per_second)
        self.capacity = float(burst if burst is not None else max(1, int(self.rate)))
        if self.capacity < 1:
            raise ValueError("burst must be >= 1")
        self._clock = clock
        self._tokens = self.capacity
        self._stamp = clock()
        self.dropped = 0

    def allow(self) -> bool:
        """Consume one token if available. ``False`` means drop this frame."""
        now = self._clock()
        elapsed = max(0.0, now - self._stamp)
        self._stamp = now
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        self.dropped += 1
        return False
