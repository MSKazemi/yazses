# ADR-v04-003: EMG Backend USB Serial Protocol (YESP)

| Field | Value |
|---|---|
| **ID** | ADR-v04-003 |
| **Status** | Accepted |
| **Date** | 2026-05-17 |
| **Module** | `src/yazses/platform/emg/backend.py` |

---

## Context

Acoustic voice dictation is impractical in open-plan offices, shared workspaces, and meetings. Electromyography (EMG) devices — worn in a headphone-like form factor — can decode silent speech from facial muscle signals at reported accuracies of ~96% for vocabularies of 10 discrete commands. These devices enable voiceless triggering and command dispatch without producing audible speech.

The consumer and research EMG market is fragmented. Devices from different manufacturers expose different interfaces: USB HID, USB serial (CDC ACM), BLE GATT, and proprietary SDKs. YazSes cannot commit to a single vendor's API without creating a lock-in that limits the accessible hardware base.

A hardware-agnostic protocol layered over the lowest common denominator transport allows any EMG device — including custom research hardware based on Arduino or STM32 — to integrate with YazSes without per-device driver work.

---

## Decision

Define the **YazSes EMG Serial Protocol (YESP)**: USB CDC serial at 115200 baud, 8-N-1, newline-delimited ASCII messages.

The `EMGBackend` class in `src/yazses/platform/emg/backend.py` uses `pyserial >= 3.5` to read YESP messages on a background thread. It implements the `HotkeyBackend` protocol (duck typing) defined in `src/yazses/platform/base.py`, making it a drop-in replacement for the OS keyboard hotkey backend when `[emg] device_port` is configured. The daemon's wiring in `core/daemon.py` requires no changes to support EMG.

### YESP message set (v0.4.0)

| Message | Direction | Description |
|---|---|---|
| `HOLD_START` | Device → Daemon | Begin silent articulation; equivalent to hotkey press |
| `HOLD_END` | Device → Daemon | End silent articulation; equivalent to hotkey release |
| `COMMAND:<label>` | Device → Daemon | Device recognised a discrete command; `<label>` is an ASCII identifier |
| `TEXT:<string>` | Device → Daemon | Full-text decoded by device (deferred to v0.4.1) |
| `HEARTBEAT` | Device → Daemon | Alive signal; daemon acknowledges but takes no action |

Daemon-to-device messaging is out of scope for v0.4.0. The protocol is unidirectional.

---

## Rationale

**USB serial is the universal fallback.** Every platform with a USB stack supports CDC ACM virtual COM ports. `pyserial` provides a single cross-platform API across Linux (`/dev/ttyUSB*`, `/dev/ttyACM*`), macOS (`/dev/cu.usbmodem*`), and Windows (`COMx`). No kernel module beyond the standard CDC ACM driver is required.

**Plain ASCII is the minimal viable protocol.** Any microcontroller capable of running EMG inference can implement 2–5 ASCII messages over a UART. Human-readable messages simplify firmware debugging and allow users to verify device output with standard serial terminal tools (`screen`, `minicom`, PuTTY) before involving YazSes.

**`HotkeyBackend` duck typing avoids daemon modification.** `EMGBackend` exposes the same `on_hold_start(leaked)` / `on_hold_end()` callback surface as the existing evdev and OS keyboard backends. From the daemon's perspective, an EMG device is indistinguishable from a held keyboard key. This means the entire existing voice pipeline — VAD, Whisper, filters, injection — operates unchanged.

**Transport-agnostic message layer.** YESP messages are defined at the application layer. The same parsing and dispatch logic can be reused by BLE and WebSocket adapters in future releases. The message format imposes no transport assumptions.

---

## Alternatives Considered

| Alternative | Reason Rejected |
|---|---|
| **BLE (Bluetooth Low Energy)** | Platform BLE APIs are complex and inconsistent across Linux (BlueZ), macOS (CoreBluetooth), and Windows (WinRT). Deferred to v0.4.1 with the same YESP message protocol over BLE transport |
| **OpenBCI SDK** | Tied to a specific hardware vendor; does not generalise to the broader EMG device market |
| **Protocol Buffers / gRPC** | Overengineered for a 5-message protocol over a point-to-point serial link; requires a protobuf toolchain on firmware targets |
| **USB HID** | HID descriptor authoring is hardware-side complexity; HID reports are binary, not human-readable; platform host-side HID APIs vary more than CDC serial |

---

## Consequences

- **USB cable required.** BLE transport is deferred. Users must connect the EMG device via USB in v0.4.0.
- **Platform-specific port names.** The configured `device_port` is not portable across OSes. `yazses doctor` reports connection status and lists available serial ports to assist configuration.
- **No per-user calibration wizard.** EMG signal thresholds and classification are handled entirely on the device firmware side. YazSes has no insight into raw EMG signals and provides no calibration tooling in v0.4.0.
- **One new optional dep** (`pyserial`) under the `emg` extra. Not imported unless `[emg] device_port` is set.
- **Command map is user-configured.** The mapping from device label to command phrase is defined in `[emg.command_map]` in `config.toml`. No default map is provided; users must populate it to match their device's label vocabulary.

---

## Configuration

```toml
[emg]
device_port = "/dev/ttyUSB0"
baud_rate = 115200
mode = "command"          # "gate" (HOLD_START/END only) | "command" (COMMAND:<label>)

[emg.command_map]
save  = "save file"
undo  = "undo"
tests = "run tests"
```

`device_port` defaults to `""` (EMG backend disabled). When empty, the daemon uses the configured OS hotkey backend as normal.

---

## Dependency

Optional dep group `emg` in `pyproject.toml`:

```toml
[project.optional-dependencies]
emg = ["pyserial >= 3.5"]
```

Install with:

```bash
uv sync --extra emg
```
