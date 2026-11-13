# Spec: TextLink wire protocol (board-to-host text over a UART)

| Field | Value |
|---|---|
| **ID** | spec-textlink-wire-protocol |
| **Status** | **Draft**. **Unverified on hardware**: no board has ever sent a frame; everything below is exercised only by a software simulator on a PC |
| **Date** | 2026-11-13 |
| **Module** | none in `src/yazses/`. Reference code: `examples/maixcam2-text-link/textlink.py` (codec), `simulated_board.py`, `host_reader.py`, `board/maixpy_send.py` |
| **Related** | [ADR-030](../adr/adr-030-agent-era-direction.md) (new capabilities are frozen, which is why this is an example and not a feature), ADR-011 (offline by default) |

## Purpose and scope

A research question: can a Sipeed MaixCAM2 board, running Whisper-base on-device, send
the text it recognised to a desktop over a wired UART? This document fixes the byte
format of that link so a sender and a receiver written independently agree.

It specifies the **wire format and the receiver's validation rules**. It does not
specify what a consumer does with the text, and the reference reader only prints it.
It adds nothing to YazSes: no config key, no CLI command, no daemon wiring.

Key words MUST, MUST NOT, SHOULD and MAY are used as in RFC 2119.

## Physical layer

Asynchronous serial, **115200 baud, 8 data bits, no parity, 1 stop bit (8N1)**, no flow
control, one direction (board to host). Logic levels: check the logic level of your board
revision. Sipeed documents 3.3 V for MaixCAM and does not state it for MaixCAM2. The
adapter must match it. A conforming sender
MUST NOT use the board's system console UART for this link.

## Frame layout

All multi-byte integers are **big-endian**. A frame is the concatenation:

| Offset | Size | Field | Value |
|---|---|---|---|
| 0 | 2 | SYNC | `0x59 0x53` (ASCII `YS`) |
| 2 | 1 | VER | `0x01` |
| 3 | 1 | TYPE | `0x01` TEXT, `0x02` TRIGGER, `0x03` PING |
| 4 | 1 | SEQ | 0..255, +1 per frame sent, wraps 255 to 0 |
| 5 | 2 | LEN | payload length in bytes, `u16` |
| 7 | LEN | PAYLOAD | see below |
| 7+LEN | 2 | CRC16 | `u16`, over bytes 2 .. 6+LEN (VER through PAYLOAD) |

Header is 7 bytes, trailer 2, so a frame is `9 + LEN` bytes and the largest is
**521 bytes**.

| TYPE | Name | LEN | Payload |
|---|---|---|---|
| `0x01` | TEXT | 1..512 | UTF-8 text |
| `0x02` | TRIGGER | 0 | none: "start now" marker, no text |
| `0x03` | PING | 0 | none: heartbeat |

No frame of any type, known or not, may have LEN greater than **512**.

## CRC

CRC-16/CCITT-FALSE: polynomial `0x1021`, initial value `0xFFFF`, no input or output
reflection, final XOR `0x0000`. Check value: the CRC of the ASCII bytes `123456789` is
**`0x29B1`**. The CRC covers VER, TYPE, SEQ, LEN and PAYLOAD; it does not cover SYNC or
itself. It is sent high byte first.

Worked example for `hello`, SEQ 0: the covered bytes are
`01 01 00 00 05 68 65 6c 6c 6f`, the CRC is `0xE53C`, sent as `e5 3c`.

A CRC detects accidental corruption. It is **not** authentication: anyone who can write
to the wire can forge a valid frame.

## TEXT validation (receiver)

A receiver MUST apply these steps to a CRC-valid TEXT payload, in order, and on any
failure MUST drop the whole frame (never repair or truncate) and count it:

1. Decode as **strict UTF-8** (no replacement characters, no overlong forms, no
   surrogates, no code points above U+10FFFF).
2. **NFC-normalise.**
3. **Refuse** if the text contains any control character: C0 (`U+0000`-`U+001F`,
   including NUL, TAB, LF, CR and ESC), DEL (`U+007F`) or C1 (`U+0080`-`U+009F`).
   Multi-line text is therefore not representable.
4. **Refuse** U+2028 and U+2029, and the bidirectional controls U+202A-U+202E,
   U+2066-U+2069, U+200E, U+200F and U+061C. U+200C and U+200D (ZWNJ, ZWJ) are
   allowed: Persian and other scripts need them.
5. **Strip** surrounding whitespace; **refuse** if nothing remains.

The 512-byte limit applies to the wire payload; NFC may lengthen the decoded text
slightly. A sender SHOULD apply the same rules before sending, so that nothing it sends
is dropped. A sender whose recogniser output is too long SHOULD cut at a character
boundary at or below 512 bytes, or send several frames.

## Receiver state machine and resynchronisation

The receiver keeps a buffer. Its result MUST depend only on the concatenation of the
bytes received, never on how they were split across reads. Loop:

1. Find the first `SYNC` in the buffer. Bytes before it are discarded and counted as
   `resync_bytes`. If none is found, discard everything except a trailing `0x59` (it
   may begin a SYNC split across reads) and wait.
2. If fewer than 7 bytes are present, wait.
3. If VER is not `0x01`: count `bad_version`, discard **one** byte (the first SYNC
   byte), go to 1.
4. If LEN is above 512: count `oversize`, discard one byte, go to 1. The receiver MUST
   NOT wait for LEN bytes.
5. If TYPE is TRIGGER or PING and LEN is not 0: count `bad_length`, discard one byte,
   go to 1.
6. If fewer than `9 + LEN` bytes are present, wait. At most 521 bytes are ever held.
7. If the CRC does not match: count `bad_crc`, discard **one** byte, go to 1.
8. The frame is authentic. Consume `9 + LEN` bytes, track SEQ (below), then: an unknown
   TYPE is counted (`unknown_type`) and ignored; a TEXT payload is validated; a TRIGGER
   or PING is reported as such.

Discarding a single byte on every error, and never trusting a corrupt LEN to skip
ahead, is what lets a truncated frame be followed by good frames without losing them.
Every iteration consumes at least one byte, so the loop terminates.

A receiver MAY give up on an incomplete frame after an idle period (the reference
reader uses 1 s): it then discards the head byte and rescans, which recovers complete
frames queued behind a dead one. This is the only timing-dependent behaviour.

## SEQ

SEQ lets a receiver measure loss; it never causes an authentic frame to be dropped
**except** an exact immediate repeat. For each authentic frame:

* if (SEQ, TYPE, PAYLOAD) equals the previous authentic frame's, it is a **duplicate**
  (counted, flagged; the reference reader does not print it);
* otherwise the number of skipped frames is `(SEQ - previous_SEQ - 1) mod 256`, and a
  non-zero value counts one `seq_gap`.

A board reboot restarts SEQ at 0 and therefore appears as one gap. A replay of an older
frame (not the immediately preceding one) is **not detected**; this protocol offers no
replay protection.

## Rate limit

The reference reader accepts text through a token bucket of **5 frames per second**
(burst 5) and **drops** excess frames; it never queues them. Spoken text is far slower,
so a burst is a fault or an attack, and delayed text is the wrong thing to release
later. The default is a reader setting, not part of the wire format.

## Versioning

* VER identifies the frame layout. A receiver MUST treat a VER it does not implement as
  noise (step 3: it cannot know the layout, so it rescans).
* A new VER is required for any change to SYNC, the header layout, the CRC, the
  endianness or the meaning of an existing TYPE.
* A new TYPE value MAY be added within VER `0x01`; receivers ignore unknown TYPEs whose
  CRC is valid. A new TYPE MUST NOT exceed LEN 512.
* This document is a draft. Until it is accepted, VER `0x01` may still change; nothing
  should be built on it that cannot be changed.

## Golden vectors

Produced by running `textlink.encode` and `textlink.encode_text` from the reference
code, and cross-checked against `binascii.crc_hqx(data, 0xFFFF)` (the same CRC) and an
independent bit-by-bit implementation in the tests.

| Frame | Bytes (hex) | Length | CRC |
|---|---|---|---|
| TEXT `hello`, SEQ 0 | `59 53 01 01 00 00 05 68 65 6c 6c 6f e5 3c` | 14 | `0xE53C` |
| TEXT `你好，世界`, SEQ 7 | `59 53 01 01 07 00 0f e4 bd a0 e5 a5 bd ef bc 8c e4 b8 96 e7 95 8c 37 61` | 24 | `0x3761` |
| TEXT `Café`, SEQ 255 | `59 53 01 01 ff 00 05 43 61 66 c3 a9 2c c2` | 14 | `0x2CC2` |
| TRIGGER, SEQ 1 | `59 53 01 02 01 00 00 61 05` | 9 | `0x6105` |
| PING, SEQ 255 | `59 53 01 03 ff 00 00 ef e2` | 9 | `0xEFE2` |
| PING, SEQ 0 (after the wrap) | `59 53 01 03 00 00 00 20 81` | 9 | `0x2081` |

The Chinese text is 15 bytes of UTF-8 (`0x0f`); `Café` is 5 bytes (`c3 a9` is the
precomposed é).

## What is not verified

* No MaixCAM2 board has sent a frame; the MaixPy sender is untested on hardware.
* Whether a real UART, a real USB-to-UART adapter and the board's driver deliver the
  byte stream as the simulator does (FIFO sizes, framing errors, loss under load).
* Whether 115200 baud is adequate (a 521-byte frame takes about 45 ms; text is far
  shorter) and whether a higher rate is reliable.
* Whisper's real output on the board and how a recording is triggered.
* Security beyond accident detection: there is no authentication, encryption or replay
  protection, and none is claimed.
