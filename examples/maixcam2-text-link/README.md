# MaixCAM2 text link (research example)

A device-free reference for one question: could a [Sipeed MaixCAM2](https://wiki.sipeed.com/)
board, running Whisper-base on-device (offline after the one-time online setup, which is
unmeasured), send a recognised text string to a
desktop over a wired UART?

This folder is the **wire format, a simulated board and a host reader**. It is an
example and a research artifact, not a YazSes feature: nothing under `src/yazses/`
imports it, it adds no dependency, config key or CLI command, and it never types
anything. [ADR-030](../../design/adr/adr-030-agent-era-direction.md) freezes new
capabilities, which is why it lives here and not in the daemon.

## What is verified, and what is not

| Claim | Status |
|---|---|
| The frame codec matches independently computed CRC and frame vectors | Verified by `tests/test_example_maixcam2_text_link.py` (CRC-16/CCITT-FALSE check value `0x29B1`, two independent implementations) |
| The parser gives the same result however the bytes are chunked, and recovers after garbage, truncation, bad CRC, oversize length and a wrong version | Verified in software against the simulator, at every split point |
| Hostile text (newline, ESC, NUL, bidi overrides, zero-width and other invisible characters, text with no visible content, NFC expansion past 512 bytes, bad UTF-8, ...) is refused, and the board script's cleaner and the host decoder agree on a table of code points | Verified in software |
| The host reader works against a real file descriptor | Verified with a pseudo-terminal and with `--replay`, on a PC |
| `board/maixpy_send.py` runs on a MaixCAM2 | **Not verified.** Never run on hardware. Its encoder is byte-compared to the host codec on a PC; the MaixPy calls follow the two Sipeed wiki pages and anything else is a `TODO(verify on device)` |
| A real board's UART, a real USB-to-UART adapter and Whisper's real output behave like the simulator | **Not verified.** No board exists in this repository |
| Recording audio on the board | **Not implemented**: the Sipeed Whisper page does not document recording, so `record_wav()` is a stub |
| Latency, power, accuracy, the right trigger (button, voice activity) | **Unknown** |

## Files

| File | Role |
|---|---|
| `textlink.py` | Pure stdlib codec: `encode`, `encode_text`, `FrameParser`, `RateLimiter`, `crc16_ccitt_false`. The wire format is specified in [`design/specs/textlink-wire-protocol.md`](../../design/specs/textlink-wire-protocol.md) (status: Draft) |
| `simulated_board.py` | Scripted byte streams (clean, split UTF-8, garbage, truncation, bad CRC, oversize, repeated frame, hostile text, heartbeats, reboot, stall) and `serve_pty()` |
| `host_reader.py` | Reads a serial device, a pty or a recorded file; prints one JSON line per accepted text |
| `board/maixpy_send.py` | The MaixPy script that would run on the board. Untested on hardware |

## Run it

From the repository root, with nothing to install (the example uses only the standard
library; `pyserial` is used for a real device only if it happens to be installed):

```sh
# The self-test: every simulated scenario through the parser, at several chunkings.
# Exits 0 when all texts and counters match, non-zero otherwise.
python examples/maixcam2-text-link/host_reader.py --selftest

# The unit tests for this example.
uv run python -m pytest tests/test_example_maixcam2_text_link.py -v

# List the scenarios, or dump one as hex.
python examples/maixcam2-text-link/simulated_board.py --list
python examples/maixcam2-text-link/simulated_board.py --hex hostile
```

### Pseudo-terminal demo (Linux and macOS)

Terminal 1 plays the simulated board and prints the slave device path:

```sh
python examples/maixcam2-text-link/simulated_board.py --pty --delay-scale 0
# /dev/pts/7
```

Terminal 2 reads it exactly as it would read a USB-to-UART adapter:

```sh
python examples/maixcam2-text-link/host_reader.py /dev/pts/7 --idle-exit 3
# {"seq": 0, "text": "hello world"}
# ...
# textlink: {"frames_ok": ..., "invalid_text": ..., ...}     (on stderr)
```

Start the reader promptly: the simulator blocks when the pty buffer fills. A recorded
stream replays with `host_reader.py --replay FILE`. There is no Windows pty; use
`--replay` there.

## Wiring a real board (untested)

Per Sipeed support (2026-11-09 email, not reproducible from this repository) the MaixCAM2's
USB port is a USB *function* port and **not** a serial bridge. According to the MaixPy
`README_MaixCAM2.md` the board appears on a PC as a USB *network* adapter, not as a serial
device, so a PC does not see a serial port just by plugging it in. Use a **USB-to-UART
adapter on the board's UART pins**:

| Board | Adapter |
|---|---|
| UART4 TX (pin A21) | RX |
| UART4 RX (pin A22) | TX (optional: this link is one-way, board to host) |
| GND | GND |

Check the logic level of your board revision. Sipeed documents 3.3 V for MaixCAM and
does not state it for MaixCAM2. The adapter must match it. Use 115200 baud, 8N1. Use UART4 (`/dev/ttyS4`); UART0 is the
system terminal and log port. Pin and device names are from the
[Sipeed UART page](https://wiki.sipeed.com/maixpy/doc/en/peripheral/uart.html); the
Whisper usage is from the
[Sipeed Whisper page](https://wiki.sipeed.com/maixpy/doc/en/mllm/asr_whisper.html).
Recheck both against your board's firmware version, as nothing here was run on one.

## Safety notes

* **Text from a wire is untrusted.** Anything on that wire may be wrong, malformed or
  hostile; a CRC detects accidents, not an adversary, and the link has no
  authentication. The parser refuses control characters (so a newline cannot press
  Enter and an ESC cannot start a terminal escape sequence), line separators, every
  Unicode format character (zero-width space, word joiner, BOM, tag characters,
  bidirectional controls; ZWNJ and ZWJ are allowed only beside a letter, as Persian needs
  them), noncharacters, the replacement character and the invisible fillers, text with no
  visible content, and text longer than 512 bytes after NFC, and accepts only strict
  UTF-8. That is a minimum, not a guarantee.
* **Not handled: mixed-script and homoglyph text.** A Cyrillic letter inside a Latin word
  passes every rule above. A consumer that types the text must apply its own confusable
  check.
* **Repeats are delivered, not dropped.** The reader counts gaps (`seq_gaps`) and exact
  immediate repeats (`seq_repeats`) and drops nothing. The receiver cannot tell a
  retransmission from a repeated utterance ("yes", "yes"), so replay protection is out of
  scope. The board script increments SEQ per frame sent.
* **This example never types the text.** The reader prints JSON lines and nothing else:
  no keystroke injection, no `yazses` import, no network socket. Anything you build on
  top must treat the text as untrusted input and keep its own consent and rate limits.
* The rate limiter drops excess frames instead of queueing them, so a stuck or
  malicious sender cannot build up a backlog that is released later. `--rate` must be a
  finite number above zero.
* YazSes is offline by design; this link keeps that property (a local wire, no network),
  but the board's own software and model downloads are outside this repository.
