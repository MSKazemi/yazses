---
title: Hardware for the muscle, blink and jaw-clench switch
description: Choose between a DIY serial muscle sensor and a BrainFlow board, see which channels YazSes reads for squeeze, blink and jaw clench, set the mains frequency, and follow the safety rules for electrodes.
---

# Hardware for the muscle, blink and jaw-clench switch

This page helps you pick and connect the hardware for the
[biosignal switch](biosignal-switch.md). It is deliberately modest: YazSes has been tested on synthetic and
replayed signals, and **no specific board, electrode or placement has been shown to work for a particular
person**. Treat everything here as a starting point and check it with `yazses biosignal doctor` and
`yazses biosignal monitor`.

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
| **Examples** | SparkFun MyoWare 2.0, BioAmp EXG Pill, on a microcontroller | An OpenBCI board, a Muse headband, or another board BrainFlow supports |
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

An empty `device_port` means the serial switch is off. Run `yazses restart` after you set it. This path is
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

## Which channels are read

What YazSes can detect depends on which channels your hardware gives it:

| Event | Where it is read from | Notes |
|---|---|---|
| **Squeeze** | An EMG channel on the muscle you squeeze: the configuration describes it as a forearm, jaw or face channel | The recommended trigger. Place the electrode on a muscle you can contract on purpose and do not otherwise use while you are working. |
| **Blink / double blink** | Frontal EEG or EOG channels. By default YazSes looks for channels named `Fp1`, `Fp2`, `AF7` and `AF8` | `AF7` and `AF8` are the frontal sites of a Muse-style headband. A blink is an artifact of eye movement on those channels, not a brain signal. |
| **Jaw clench** | Temporal or frontal channels. By default `T7`, `T8`, `TP9`, `TP10`, `F7`, `F8`, `AF7`, `AF8`, `Fp1`, `Fp2` | The jaw-closing muscle sits under the temporal sites; the frontal ones pick it up too. `TP9` and `TP10` are the behind-the-ear sites of a Muse-style headband. Off by default. |

If you do not have a channel for an event, that detector has nothing to read. `yazses biosignal doctor`
reports the channels it found, and `calibrate` skips a step your source cannot support and says so.

### Where to put the electrodes

This repository documents the *kind* of site for each event (the table above) and nothing more specific.
For the exact position, electrode type, skin preparation and reference or ground placement, **consult your
board's manual**. Two practical points that apply whatever the hardware:

- **Good contact matters more than the exact spot.** A flat, clipped or noisy channel is ignored by the
  quality gate, on purpose, and `doctor` and `monitor` tell you which.
- **Re-calibrate after you move an electrode.** A profile made for one placement is wrong for another.

## Set the mains frequency

Powerline hum is far larger than the signals YazSes wants, so the filters place a notch on it. Set
`mains_hz` in `[biosignal]` to the frequency where you are:

- **50** for most of Europe, Africa, Asia and Oceania (the default);
- **60** for the Americas, South Korea, Taiwan and western Japan.

A wrong value leaves real hum in the signal and raises the false-positive rate. `yazses biosignal doctor`
and `monitor` report interference they see, so if they flag mains noise on an electrode that is well seated,
check `mains_hz` first. Keep leads away from power cables and power supplies.

## Check it before you rely on it

```bash
yazses biosignal doctor      # chain, sample rate, mains, flat or clipped channels, profile
yazses biosignal calibrate   # your own thresholds
yazses biosignal monitor     # what makes it fire
yazses biosignal field-test  # how often it fires by mistake, by activity
```

Start with `doctor` and read its last line, the **`Verdict:`**: it says either that you are ready or the one
thing to fix next (a missing library, a source that will not open, no calibration). It is the quickest way
to tell a hardware problem from a configuration one. The quality gate behind it also recognises an electrode
that has lifted off (an abrupt step followed by a flat line) and movement shared by every channel at once,
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
