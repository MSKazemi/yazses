---
title: Hardware for the muscle, blink and jaw-clench switch
description: Choose between a DIY serial muscle sensor and a BrainFlow board, investigate a Bluetooth headset on Linux, run the first-use preflight in order, see which channels YazSes reads, set the mains frequency, and follow the safety rules for electrodes.
---

# Hardware for the muscle, blink and jaw-clench switch

This page helps you pick and connect the hardware for the
[biosignal switch](biosignal-switch.md). It is deliberately modest: YazSes has been tested on synthetic and
replayed signals, and **no specific board, electrode or placement has been shown to work for a particular
person**. Treat everything here as a starting point and check your own setup in the order given in
[First use, in order](#first-use-in-order).

!!! danger "Safety first"

    - **This is not a medical device.** YazSes is not designed, tested or approved to diagnose, monitor or
      treat anything, and it must not be relied on for safety-critical control.
    - **Never connect mains-powered equipment to electrodes.** Use only battery-powered or USB-isolated
      hardware that its maker sells for use with the body, and keep the person wearing electrodes away
      from any mains-connected device that is not isolated. A laptop charging from the wall is a
      reason to read your board's manual, not to improvise.
    - Do not place electrodes on broken or irritated skin, and stop if the skin reacts. If you have an
      implanted medical device, or any doubt, ask your clinician before using electrodes.
    - Follow your board's manual for everything that is not written here: electrode type, preparation, lead
      handling and cleaning.

## Choose a path

| | DIY serial sensor | BrainFlow board |
|---|---|---|
| **Examples** | SparkFun MyoWare 2.0, BioAmp EXG Pill, on a microcontroller | An OpenBCI board, a Muse headband, or another board from `yazses biosignal boards` |
| **Who does the detection** | The microcontroller. It sends `HOLD_START` / `HOLD_END` over USB serial (the YESP protocol). | YazSes. BrainFlow streams raw samples and the detectors run on your computer. |
| **Config** | `[emg] device_port` (and `baud_rate`, `mode`) | `[biosignal] source = "brainflow:<board_id>[:<port>]"` |
| **Extra to install** | `emg` | `emg-band` |
| **Gives you** | A squeeze as hold-to-talk. Cheap and the most dependable choice. | Squeeze, double blink and jaw clench from raw signal, plus `calibrate`, `monitor`, `replay`, `report`. |
| **Costs / limits** | You write or flash the detection firmware; there is no calibration or false-positive report from YazSes. The protocol is in [the YESP spec](https://github.com/MSKazemi/yazses/blob/main/design/emg-protocol.md). | More expensive, and what you get depends on the channels the board has (see below). |

The [research page](../research/muscle-brain-control.md) explains why the DIY sensor is the better trigger:
the same muscle signal is cleaner measured directly on the muscle than through the skull.

### The DIY serial path

Connect the sensor to a microcontroller that speaks YESP, plug it in over USB, and set the port:

```toml
[emg]
device_port = "/dev/ttyUSB0"   # empty means disabled; a Windows port looks like COM3
```

An empty `device_port` means the serial switch is off. Run `yazses restart` after you set it. On Windows a
COM port such as `COM3` is not a file, so `yazses doctor` cannot check that it exists: its row shows SKIP
and says the port will be tried when YazSes starts. A POSIX path such as `/dev/ttyUSB0` is checked for
existence. This path is
documented in [the configuration reference](../configuration.md) under `[emg]`. On Linux your user may
need to be in the `dialout` group to open a serial port. The `yazses biosignal` commands do not read this
path; they work on the BrainFlow, file and synthetic sources.

### The BrainFlow path

1. Install the extra into the environment YazSes runs from (`yazses[emg-band]`; see
   [the install section](biosignal-switch.md#install-what-it-needs)).
2. Find your board's integer id with `yazses biosignal boards`.
3. Set the source, for example `brainflow:0:/dev/ttyUSB0` for an OpenBCI Cyton on a serial dongle, and run
   `yazses biosignal doctor`.

A board that is unplugged or busy is logged and leaves the switch unavailable; YazSes carries on without it.

Two families report raw ADC counts instead of microvolts: the Myo armband (below) and the OYMotion gForce Pro
and Dual (Windows only). The `yazses biosignal boards` entry says so. For a count source the quality gate
skips the checks whose limits are in microvolts (the flat-line level, saturation level, drift amplitude and
EEG/EOG noise). A flat line is then only a channel with exactly zero variance. Still checked: missing samples,
packet loss, mains hum, clipping plateaus, lead-off steps and movement shared by every channel. Once it has
judged the signal, `monitor` says the absolute checks were skipped, and the system `yazses doctor` row says
the same. On a synthetic count stream, a live channel
of 0.4 counts was judged flat before this change and is good after it; a dead channel and a rail-clipped
channel are still bad. No real armband has been measured, so the count thresholds are untuned.

### Other devices and recordings

These sources do not go through BrainFlow. Each one is opened only when you name it, and each one
keeps its library optional.

| Source | Example | Extra | What it is for |
|---|---|---|---|
| `lsl:<stream name>` or `lsl:type=EEG` | `lsl:type=EEG` | `lsl` | Any app that publishes a [Lab Streaming Layer](https://labstreaminglayer.readthedocs.io/info/supported_devices.html) stream: OpenBCI GUI, muse-lsl or BlueMuse for a Muse, and many vendor tools. YazSes only looks on this computer, never on your network, and refuses a stream from another host. |
| `thinkgear:<port>` | `thinkgear:/dev/rfcomm0` | `emg` | A NeuroSky MindWave or other ThinkGear headset (one forehead electrode, so blinks). Only the raw signal is used, never the headset's own "attention" or "blink strength" scores. |
| `bitalino:<port>[:<options>]` | `bitalino:COM5:A1=emg,fs=1000` | `emg` | A PLUX BITalino (r)evolution kit with its EMG, EEG or EOG sensor on a chosen input. |
| `myo:<address>` | `myo:AA:BB:CC:DD:EE:FF` | `ble` | A Myo armband's raw 8-channel EMG over Bluetooth LE. The values are raw counts, not microvolts, so calibrate on the band itself. |
| `file:<recording>` | `file:session.edf` | none (`xdf` for `.xdf`) | Replay a CSV, `.npz`, EDF/EDF+/BDF or LabRecorder `.xdf` file. Annotations in an EDF+ file, or an XDF marker stream, are used as labels by `yazses biosignal evaluate`. |

`yazses biosignal record --out session.edf` (or `.bdf`) writes a file that EDFbrowser, MNE and most
vendor tools open. Before you rely on a new device, run `yazses biosignal check-source <source>`: it
opens the device for a few seconds and checks that the stream is well-formed (no dropped packets, a
steady sample rate, consistent channels). While the switch runs, a stream that breaks those rules
closes the switch the same way a bad electrode does.

`yazses biosignal doctor` describes these four device specs without opening them. Use `check-source` to test
the stream, and the system-wide `yazses doctor` "Biosignal switch" row for what is missing (the extra to
install, a placeholder that still needs a port, a stream name or an address).

None of these devices has been tested with YazSes on real hardware yet. They were built and tested
against their published protocol documents.

## Investigate a Bluetooth headset on Linux

This is a way to **find out** whether your unit offers a serial stream that Linux can open. It is not a
working recipe for any model: **YazSes does not promise that any headset exposes a Serial Port Profile
(SPP) or RFCOMM channel**, and none has been tried. A product that advertises Bluetooth may offer only a
profile that this path cannot read. It needs no vendor app and no account; if your unit does, stop here.

1. **Discover and pair** with your distribution's own Bluetooth tool, for example
   [`bluetoothctl`](https://manpages.debian.org/trixie/bluez/bluetoothctl.1.en.html): `power on`, `scan on`,
   wait for the device, `scan off`, then `pair <address>` and `trust <address>`. Use only a pairing code the
   product's own documentation gives.
2. **Look at what it offers**: `info <address>` lists service UUIDs. A serial stream is advertised as
   *Serial Port*, service class `0x1101`
   ([Bluetooth Assigned Numbers](https://www.bluetooth.com/specifications/assigned-numbers/)). If it is
   not listed, record that the raw transport is unavailable and stop.
3. **Bind a serial device** only if it is listed. [`rfcomm`](https://manpages.debian.org/experimental/bluez/rfcomm.1.en.html)
   `bind` creates a device node such as `/dev/rfcomm0`; binding does not connect, the connection is made
   when a program opens the node. The channel number depends on the device, so take it from the device's
   service record. Some distributions ship `rfcomm` in a separate package or not at all.
4. **Check permission** with `ls -l` on the node and use your distribution's normal mechanism (often a
   serial group). Do not make a device node world-writable.

Use your own port in the source spec, for example `thinkgear:/dev/rfcomm0`. Keep the device address and
any pairing code to yourself: neither belongs in an issue, a report or a commit.

## First use, in order

For a first headset, do not skip ahead. Each step answers one question, and a "no" is a result worth
reporting. Replace `<source>` with your spec.

| Step | Do | What it answers |
|---|---|---|
| 1 | Pair the device and confirm a local port or stream exists ([Linux Bluetooth](#investigate-a-bluetooth-headset-on-linux)). | Is there anything local to open? |
| 2 | Install the optional extra for your source, for a ThinkGear headset `yazses[emg]` ([how](biosignal-switch.md#install-what-it-needs)). | Can YazSes load the transport library? |
| 3 | `yazses biosignal doctor --source <source>` | Is the setup sensible? It does not open the device. |
| 4 | `yazses biosignal check-source <source> --seconds 30` | Do well-formed data arrive, and at what arrival rate? For ThinkGear, does the headset report contact? |
| 5 | `yazses biosignal monitor --source <source>`; lift an electrode and put it back | Is the signal usable, and are events held while contact is lost? Nothing is acted on. |
| 6 | Put the source in `[biosignal]`, leave `enabled = false`, then `yazses biosignal calibrate` | Can your thresholds be learned? |
| 7 | `yazses biosignal field-test` | How often does it fire by mistake, and does it catch your cued gestures? Nothing is acted on. |
| 8 | Only then set `enabled = true` and `yazses restart`, with the keyboard and your normal hotkey in reach. `yazses stop` ends YazSes. | Does it behave in real use? |

Stop at the first step that fails. On a ThinkGear headset, which has no muscle channel, also set
`emg = false`, and run only one of these commands at a time, because one program holds the port.

### What each result does and does not show

| Level | Shown by | Does not show |
|---|---|---|
| **Parser valid**: the packet format is decoded correctly | The project's tests on hand-built bytes; on your unit, accepted packets in `check-source` | That your unit behaves like those bytes in other respects |
| **Local transport accessible**: your computer opens the device and bytes arrive | `check-source` on your machine | That the data are the right data, or stay that way |
| **Waveform usable**: contact, stream and signal-quality gates all allow events | `check-source` and `monitor`, for the minutes you watched | That any gesture is detected, or tomorrow's seating |
| **Gesture validated**: your cued gestures are caught and false ones are rare enough | `field-test` and `report`, with their bounds, for **you**, that unit and that configuration | Anything about another person, unit or day |
| **General support**: the device is known to work for users | Nothing yet. It needs the wider [validation protocol](https://github.com/MSKazemi/yazses/blob/main/design/specs/biosignal-validation-protocol.md) on physical hardware | |

For a ThinkGear source, `check-source` ends with a **ThinkGear protocol health** block: reads that carried
bytes and how many were trusted, contact reports (zero, contaminated, no skin contact), the longest
stretch without one, accepted and rejected packets, why reads were held, and a result line. It holds
counts and reason codes only. A conformance `PASS` with `UNQUALIFIED` underneath is possible and means the
stream is well-formed but every event would be held. Lost samples are reported as unknown, because the
packets carry no sequence number, and `rate_t0` is not a throughput measurement for this source (its
timestamps count samples at the nominal 512 Hz); read `rate_arrival`.

## Which channels are read

What YazSes can detect depends on which channels your hardware gives it:

| Event | Where it is read from | Notes |
|---|---|---|
| **Squeeze** | An EMG channel on the muscle you squeeze: the configuration describes it as a forearm, jaw or face channel | The recommended trigger. Place the electrode on a muscle you can contract on purpose and do not otherwise use while you are working. |
| **Blink / double blink** | Frontal EEG or EOG channels. By default YazSes looks for channels named `Fp1`, `Fp2`, `AF7` and `AF8` | `AF7` and `AF8` are the frontal sites of a Muse-style headband. A blink is an artifact of eye movement on those channels, not a brain signal. |
| **Jaw clench** | Temporal or frontal channels. By default `T7`, `T8`, `TP9`, `TP10`, `F7`, `F8`, `AF7`, `AF8`, `Fp1`, `Fp2` | The jaw-closing muscle sits under the temporal sites; the frontal ones pick it up too. `TP9` and `TP10` are the behind-the-ear sites of a Muse-style headband. Off by default. |

If you do not have a channel for an event, that detector has nothing to read. `yazses biosignal doctor`
lists what a board declares without opening it, `monitor` shows the channels it actually reads, and
`calibrate` skips a step your source cannot support and says so.

### Where to put the electrodes

This repository documents the *kind* of site for each event (the table above) and nothing more specific.
For the exact position, electrode type, skin preparation and reference or ground placement, **consult your
board's manual**. Two practical points that apply whatever the hardware:

- **Good contact matters more than the exact spot.** A flat, clipped or noisy channel is ignored by the
  quality gate, on purpose, and `monitor` tells you which.
- **Re-calibrate after you move an electrode.** A profile made for one placement is wrong for another.

## Set the mains frequency

Powerline hum is far larger than the signals YazSes wants, so the filters place a notch on it. Set
`mains_hz` in `[biosignal]` to the frequency where you are:

- **50** for most of Europe, Africa, Asia and Oceania (the default);
- **60** for the Americas, South Korea, Taiwan and western Japan.

A wrong value leaves real hum in the signal and raises the false-positive rate. `yazses biosignal monitor`
reports interference it sees, so if it flags mains noise on an electrode that is well seated, check
`mains_hz` first. Keep leads away from power cables and power supplies.

On a blink (EOG) channel the mains check reads the signal through the same low-pass the blink detector
applies, so hum that the detector already removes is not counted against the channel. This is measured only
on synthetic signals; see [Honest limitations](biosignal-switch.md#honest-limitations) on the switch page.

## Check it before you rely on it

```bash
yazses biosignal doctor                   # setup and profile; does not open your device
yazses biosignal check-source <source>    # is the stream well-formed?
yazses biosignal monitor                  # signal quality, and what makes it fire
yazses biosignal calibrate                # your own thresholds
yazses biosignal field-test               # how often it fires by mistake, by activity
```

Start with `doctor` and read its last line, the **`Verdict:`**: it says either that you are ready or the one
thing to fix next (a missing library, a malformed source, a device still to be checked, no calibration). It
does not read your signal. The quality gate that `monitor` shows recognises an electrode that has lifted
off (an abrupt step followed by a flat line) and movement shared by every channel at once,
which usually points at the cable or your posture rather than one badly seated electrode.

### Measure your own rate

No board, electrode or placement has been shown to give a low false-activation rate for any particular
person. That is the honest state of the evidence, and it is why the last command above exists:
`yazses biosignal field-test` walks you through sitting still, talking, chewing, typing and looking around
with your real hardware connected, counts what fires when you did not mean it, and reports it per hour for
each activity, with an upper bound. Nothing is typed or acted on and no signal is saved. A short session
bounds a rate only loosely, so repeat it on different days and after re-seating the electrode before you
believe either a good or a bad result, and treat what you get as true of **your** board, **your** placement
and **your** day. Details, and what the numbers do and do not mean, are in
[Measure your own rate](biosignal-switch.md#measure-your-own-rate).

If you would like your result to count towards a wider picture, you may share the JSON the test writes
(`--out`) together with a sentence on your board and where the electrode sat. It holds counts and durations,
no signal. Do not share a recording.

Then keep judging the switch on your own numbers with `yazses biosignal report`. A recording of your signal
is sensitive data; see [Privacy](biosignal-switch.md#privacy).

## See also

- [Use a muscle, blink or jaw-clench switch](biosignal-switch.md): configuration, calibration, the speech
  guard and the false-positive budget.
- [Muscle and brain control: the honest hierarchy](../research/muscle-brain-control.md): what EMG and EEG can
  and cannot do.
- [Hands-free computing with a muscle switch](../use-cases/biosignal-hands-free.md).
