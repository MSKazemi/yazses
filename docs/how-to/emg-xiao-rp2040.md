---
title: Muscle switch on a XIAO RP2040 (example firmware, not tested on hardware)
description: Example MicroPython firmware that turns a Seeed Grove EMG Detector on a Seeed XIAO RP2040 into a hold-to-talk muscle switch over USB serial, with wiring, the YazSes config, tuning, and what has and has not been tested.
---

# Muscle switch on a XIAO RP2040 (example firmware, not tested on hardware)

This page goes with a small example under
[`examples/emg-xiao-rp2040/`](https://github.com/MSKazemi/yazses/tree/main/examples/emg-xiao-rp2040):
MicroPython for a Seeed XIAO RP2040 that reads a Seeed Grove EMG Detector and sends `HOLD_START` and `HOLD_END` over USB
serial, so that squeezing a muscle works as hold-to-talk. It uses the existing serial path of the
[biosignal switch hardware](biosignal-hardware.md#the-diy-serial-path); the host side needs no change.

!!! warning "Status: simulated only. It has never run on a board."

    - **Tested:** the detector logic, on simulated signals (an idle band near 1.5 V, a deliberate squeeze, a twitch shorter
      than the debounce, slow drift, a signal pinned at the rail, noise), and that the firmware's output lines are
      accepted by YazSes's real serial reader. These are unit tests in `tests/test_emg_xiao_firmware_example.py`.
    - **Not tested:** a real sensor, a real XIAO RP2040, the wiring below, the default thresholds, the USB serial link
      between the two, and any real muscle. The thresholds are placeholders chosen from the voltages Seeed documents,
      not from a measurement.
    - Nothing here shows the sensor and the board work together. It is a starting point for someone who has both.

## What you need

- A Seeed XIAO RP2040 running MicroPython (the board's own page lists MicroPython support).
- A Seeed Grove EMG Detector and the electrodes and cable its manual specifies. This project does not say which
  electrodes to use or where to place them; follow the sensor's manual.
- A way to connect the sensor's Grove cable to the board: a Grove-compatible shield or expansion board, or jumper wires.
  Use the pin labels printed on your sensor, not an assumed order.
- `yazses` with the serial extra (`pyserial`): `pipx install 'yazses[emg]'` or the equivalent for your install method.

## Wiring

| Sensor | XIAO RP2040 |
|---|---|
| Signal (analog output) | `A0` (GPIO26, ADC0) |
| VCC | `3V3` |
| GND | `GND` |

- **Power the sensor from 3.3 V.** Seeed documents the sensor for 3.3 V or 5 V. The board's pins accept at most 3.3 V
  (Seeed warns that more than 3.3 V on a general I/O pin may damage the chip), so powering the sensor from 3.3 V is the
  choice that does not depend on the sensor's output staying in range on 5 V. The firmware reads with `read_u16()`, which
  maps 0 to 3.3 V onto 0 to 65535.
- Seeed's page also says the sensor's Grove connector goes to an analog input. Its pin order is not given on that page,
  so check your sensor.

### What the sensor documents, and what this example assumes

From [Seeed's Grove EMG Detector page](https://wiki.seeedstudio.com/Grove-EMG_Detector/) (read on 2026-11-12):
power supply 3.3 V to 5 V; in standby the output is 1.5 V; the output rises when muscle activity is detected, to a
maximum of 3.3 V; and the sensor "cannot be used for medical purposes".

The firmware assumes the output is a slowly varying level that sits near its idle value and rises with muscle tension.
Whether your unit's output is already a smoothed envelope or a faster raw-looking signal, how much noise it carries, and
how large a deliberate squeeze is on your muscle have not been measured by this project. That is what the debug output
below is for. If the output also swings below idle, set `rectify=True` on the detector.

## Put it on the board

1. Install MicroPython on the XIAO RP2040 following the board's and MicroPython's instructions.
2. Copy both files from `examples/emg-xiao-rp2040/` to the board, for example
   `mpremote cp emg_detector.py main.py :`. `main.py` runs at power-up.
3. Before you trust it with YazSes, read what it sends with any serial terminal (see
   [the protocol page](https://github.com/MSKazemi/yazses/blob/main/design/emg-protocol.md#debugging)). You should see a
   `HEARTBEAT` line about once a second, and `HOLD_START` and `HOLD_END` when you squeeze.

Keep the muscle relaxed for the first second after power-up: that is when the detector learns the idle level, and no
event is possible during it.

## Tune it with the debug output

Set `DEBUG = True` in `main.py`. Five times a second it then prints a line such as
`DEBUG level=240 baseline=29800 state=idle`. YazSes ignores unknown lines, so this is safe to leave on while testing.
`level` is the smoothed rise above the idle level and `baseline` is the idle level, both in raw ADC counts
(65535 is 3.3 V, so about 19.9 counts per millivolt).

1. Relax and note the largest `level` you see. That is your noise. Set `OFF_THRESHOLD` clearly above it.
2. Squeeze the way you intend to use it and note the typical `level`. Set `ON_THRESHOLD` clearly below it, and above
   `OFF_THRESHOLD`. The gap between the two is what stops it chattering.
3. Turn `DEBUG` off again.

The defaults (`ON_THRESHOLD` 0.15 V and `OFF_THRESHOLD` 0.08 V above idle) are untested placeholders.

## Connect it to YazSes

Find the serial port (on Linux usually `/dev/ttyACM0`, on Windows `COM3`; on Linux your user may need to be in the
`dialout` group), then in `config.toml`:

```toml
[emg]
device_port = "/dev/ttyACM0"
mode = "full_text"
```

`mode = "full_text"` makes a squeeze plain hold-to-talk dictation. The default, `command`, instead treats what you say
while squeezing as a command. Run `yazses restart`, then `yazses doctor`. The EMG source is off until `device_port` is set.

## How it decides

| Step | Behaviour (default) |
|---|---|
| Sampling | 200 samples per second |
| Idle level | learned in the first second, then follows slow drift (about 5 s time constant) and is frozen while the signal is rising |
| Start | the smoothed rise stays above `ON_THRESHOLD` for at least 40 ms; a shorter twitch is ignored |
| End | the smoothed rise stays below the lower `OFF_THRESHOLD` for 150 ms; a shorter dip does not end the hold |
| Limits | a hold lasts at least 100 ms and at most 30 s, the limits in the protocol; after a 30 s cut-off it waits for the signal to settle, and relearns the idle level after 5 s if it never does |

A signal pinned at the top of the range (a squeeze to the rail, or a fault) is treated like any other strong signal and
cut off at 30 s. A sensor that is unplugged or floating may read anything, and the detector cannot tell that apart from
a squeeze.

## Safety

This is general guidance from the YazSes project. It is not a statement from Seeed Studio, and nothing here has been
reviewed by a medical or electrical-safety professional.

- **Not a medical device.** Seeed says the sensor cannot be used for medical purposes, and YazSes is not designed or
  approved to diagnose, monitor or treat anything. Do not use it for anything where a false or missed trigger could
  hurt someone.
- **Mains-connected computers: an open question.** This setup puts electrodes on a person while the board is
  connected over USB to a computer that is often powered from the wall. This project has not established what isolation
  that needs, and has no answer from the sensor's maker about it. Do not assume it is safe. Until you have a clear answer
  from the maker's documentation, prefer a computer running on its own battery with the charger unplugged, and read the
  sensor's manual for what it says about electrodes and power.
- Do not put electrodes on broken or irritated skin, stop if the skin reacts, and ask a clinician first if you have an
  implanted medical device or any doubt.
- Keep leads away from mains cables, and follow the sensor's manual for electrode type, preparation and cleaning.

See also the general rules on the [biosignal hardware page](biosignal-hardware.md).

## Not affiliated

YazSes is not made, reviewed or endorsed by Seeed Studio. Seeed, XIAO and Grove are their names, used here only to say
which hardware the example is written for.

## If you try it

A result from real hardware, good or bad, is the most useful thing anyone can add: which sensor and board, the
`DEBUG` levels for relaxed and squeezed, and what the daemon did. Open an issue on the
[YazSes repository](https://github.com/MSKazemi/yazses/issues). Until such a result exists, the EMG switch has no row
in the [validation matrix](../validation-matrix.md).
