# YazSes EMG Serial Protocol (YESP)

This document specifies the communication protocol between EMG hardware devices and the YazSes daemon. It is intended for firmware developers implementing YESP on EMG hardware.

---

## Overview

YESP is a unidirectional, newline-delimited ASCII protocol carried over USB CDC ACM virtual serial at **115200 baud, 8 data bits, no parity, 1 stop bit (8-N-1)**. The device sends messages; the daemon reads them. There is no daemon-to-device messaging in v0.4.0.

The protocol is intentionally minimal. A device that sends only `HOLD_START` and `HOLD_END` is fully compliant and enables the core use case (voice-gate mode). Additional messages are optional.

---

## Physical Connection

The device must enumerate as a **USB CDC ACM virtual COM port**. This is the default USB serial class supported natively by Linux, macOS, and Windows without additional drivers.

Platform-specific port names:

| Platform | Example port name |
|---|---|
| Linux | `/dev/ttyUSB0`, `/dev/ttyACM0` |
| macOS | `/dev/cu.usbmodem14101` |
| Windows | `COM3` |

Configure the port in `~/.config/yazses/config.toml` (Linux/macOS) or `%APPDATA%\yazses\config.toml` (Windows):

```toml
[emg]
device_port = "/dev/ttyUSB0"
```

Run `yazses doctor` to list available serial ports and verify the configured port is reachable.

---

## Message Format

Each message is one ASCII line terminated by `\n` (LF). CR+LF (`\r\n`) is also accepted. Messages are case-sensitive. No framing header or checksum is required.

```
HOLD_START\n
HOLD_END\n
COMMAND:save\n
HEARTBEAT\n
```

Unknown message types are silently ignored by the daemon. Firmware may send additional diagnostic messages for development purposes without affecting daemon behaviour.

---

## Message Reference

| Message | Required | Description |
|---|---|---|
| `HOLD_START` | Yes (gate mode) | Signals the start of a silent articulation. Equivalent to pressing and holding the configured hotkey. The daemon opens the audio recording window. |
| `HOLD_END` | Yes (gate mode) | Signals the end of silent articulation. Equivalent to releasing the hotkey. The daemon closes the audio window and submits the buffer for transcription. |
| `COMMAND:<label>` | Optional | Device has recognised a discrete command. `<label>` is an ASCII identifier (letters, digits, underscore). The daemon maps the label to a command phrase via `[emg.command_map]` and dispatches it through the command grammar. |
| `TEXT:<string>` | Optional | Full text decoded entirely on-device. Deferred to v0.4.1; ignored in v0.4.0. |
| `HEARTBEAT` | Optional | Device alive signal. Daemon receives and discards; no response is sent. Useful for keepalive when using a USB-to-serial adapter that idles down. |

---

## Minimum Implementation

A device must implement at minimum `HOLD_START` and `HOLD_END` for **voice-gate mode**:

```
HOLD_START         ← user begins silent articulation
... (300–5000 ms) ...
HOLD_END           ← user stops
```

YazSes records audio between `HOLD_START` and `HOLD_END`, transcribes it with Whisper, and injects the result. The EMG device acts as a hands-free, silent hotkey.

A device with a **10-command vocabulary** that performs on-device classification sends only `COMMAND:<label>` messages. It does not need to send `HOLD_START` / `HOLD_END`. Configure `mode = "command"` to enable this path:

```toml
[emg]
mode = "command"
```

---

## Command Label Mapping

Labels in `COMMAND:<label>` messages are device-assigned identifiers. They are mapped to command phrases in `[emg.command_map]`. The mapped phrase is passed through the YazSes command grammar as if the user had spoken it.

```toml
[emg.command_map]
save     = "save file"
undo     = "undo"
redo     = "redo"
tests    = "run tests"
go_back  = "go back"
```

If a label arrives with no configured mapping, the daemon logs a warning and takes no action. Labels are case-sensitive and must be valid ASCII identifiers.

---

## Complete Configuration Example

```toml
[emg]
device_port = "/dev/ttyUSB0"
baud_rate = 115200
mode = "command"

[emg.command_map]
save    = "save file"
undo    = "undo"
tests   = "run tests"
go_back = "go back"
```

---

## Timing Constraints

| Parameter | Value |
|---|---|
| Baud rate | 115200 |
| Max message length | 256 bytes (including label and newline) |
| HOLD_START to HOLD_END | 100 ms minimum, 30 s maximum |
| HEARTBEAT interval | Any; 1 s recommended |

There is no hard minimum between consecutive messages, but the daemon processes messages on a background thread with no guaranteed real-time scheduling. Message bursts at intervals shorter than 10 ms may be coalesced by the OS serial buffer.

---

## Debugging

Use any serial terminal to inspect raw device output before connecting YazSes:

```bash
# Linux / macOS
screen /dev/ttyUSB0 115200
minicom -D /dev/ttyUSB0 -b 115200

# Linux (Python one-liner)
python3 -c "
import serial, sys
with serial.Serial('/dev/ttyUSB0', 115200, timeout=1) as s:
    while True:
        line = s.readline()
        if line:
            print(line.decode(errors='replace'), end='')
"
```

On Windows, use PuTTY (Connection type: Serial, Speed: 115200) or the Arduino Serial Monitor.

---

## Diagnostics

```bash
yazses doctor
```

`yazses doctor` checks:

- Whether `[emg] device_port` is configured.
- Whether the configured port exists on the system.
- Whether the port can be opened (permission check).
- Whether HEARTBEAT messages are being received (live check, 2 s timeout).

---

## Future Transport: BLE (v0.4.1)

v0.4.1 will add a Bluetooth Low Energy transport adapter. The YESP message protocol (HOLD\_START, HOLD\_END, COMMAND:\<label\>, etc.) will be identical. The adapter will wrap a BLE GATT characteristic that exposes the same newline-delimited ASCII stream. Firmware that exposes YESP over a BLE notify characteristic will be supported without changes to `[emg.command_map]` or daemon logic.
