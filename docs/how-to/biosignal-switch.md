---
title: Use a muscle, blink or jaw-clench switch
description: Drive hold-to-talk or a command from an EMG electrode or an EEG headband, check the signal with yazses biosignal doctor, calibrate it to you, measure how often it fires by mistake with yazses biosignal field-test, and keep its false-positive budget under control.
---

# Use a muscle, blink or jaw-clench switch

The **biosignal switch** reads raw electrode signals and turns a small set of physical events into the
same inputs a key press gives YazSes: a **squeeze** of a muscle, a **blink** or **double blink**, or a
**jaw clench**. A squeeze can hold the microphone open like the hold-to-talk key; the other events can
trigger a spoken-command label.

It is for people who cannot press or hold a key reliably, and for anyone whose hands are busy. It reads
**muscle and eye artifacts**, not thoughts. It does not decode what you are thinking, imagining or
looking at (the reasoning is on the
[research page](../research/muscle-brain-control.md)).

> **Experimental, off by default, and every threshold is yours to calibrate.** Nobody has yet measured
> how these switches behave over a full workday across people and electrode placements. A default
> install is unchanged until you set `[biosignal] enabled = true`.

## What hardware you need

Pick one. Both are read locally; nothing is sent anywhere.

| Hardware | How YazSes reads it | Best for |
|---|---|---|
| **A muscle sensor on a microcontroller**: MyoWare 2.0 or a BioAmp EXG Pill | The existing serial path (`[emg] device_port`, the YESP protocol). The microcontroller does the detection and sends `HOLD_START` / `HOLD_END`. See [the YESP spec](https://github.com/MSKazemi/yazses/blob/main/design/emg-protocol.md). | A squeeze as push-to-talk, cheapest, most reliable. |
| **A board BrainFlow supports**, such as an OpenBCI board or a Muse headband | BrainFlow streams raw samples to YazSes, which does the detection itself (the `emg-band` extra). | Raw-signal control, blink and jaw-clench switches, and measuring your own false-positive rate. |
| **Other devices**: a Lab Streaming Layer app (OpenBCI GUI, muse-lsl), a NeuroSky headset, a BITalino kit, a Myo armband | YazSes reads the raw samples directly (`lsl:`, `thinkgear:`, `bitalino:`, `myo:` sources) and does the detection itself. | The same as a BrainFlow board, with the device you already own. See [the hardware guide](biosignal-hardware.md#other-devices-and-recordings). |
| **No hardware** | The built-in `synthetic` source and `replay` of a recording file (CSV, `.npz`, EDF/BDF or XDF). | Trying the commands and learning the output. |

Put the electrode on the muscle you want to use, if you can. The research page explains why: a blink or
jaw clench seen through an EEG headband is the same activity measured through the skull, noisily, and a
dedicated electrode on the muscle is cleaner. [The hardware guide](biosignal-hardware.md) compares the two
paths, says where the repository documentation places electrodes, and covers the safety rules. This is not
a medical device.

## Install what it needs

The serial path needs the `emg` extra (`pyserial`); the BrainFlow path needs the `emg-band` extra
(`brainflow`). The other devices need: `lsl` for an `lsl:` stream, `emg` for a NeuroSky or BITalino
(`thinkgear:`, `bitalino:`), `ble` for a Myo armband (`myo:`), and `xdf` to replay an `.xdf`
recording. EDF and BDF files need nothing. With nothing installed the feature is simply off and the rest of YazSes is unchanged. For
the BrainFlow boards, install the extra into the environment YazSes runs from, using the command that
matches how you installed it:

```bash
pipx install 'yazses[emg-band]'            # a pipx install
uv tool install 'yazses[emg-band]@latest'  # a uv tool install (list every extra you already use)
```

If a library is missing, YazSes logs a message with the exact command for **your** install method, and
`yazses biosignal doctor` repeats it. Use that command if it differs from the two above. The pure
signal-processing code needs only NumPy, which a normal install already has.

## Turn it on

Add a section to your `config.toml` (`~/.config/yazses/config.toml` on Linux and macOS,
`%LOCALAPPDATA%\yazses\config.toml` on Windows). The example shows the shape of the section; the generated
[configuration reference](../configuration.md) is the authority for exact key names, values and defaults.

```toml
[biosignal]
enabled = true
source = "synthetic"          # start here; later "file:<path>" or "brainflow:<board>[:<port>]"
mains_hz = 50                 # 50 or 60 -- the mains frequency where you live
emg = true                    # squeeze detector
double_blink = true           # two quick blinks
jaw_clench = false            # off by default: chewing, talking and yawning all clench the jaw
max_cancelled_per_hour = 6.0  # the false-positive budget; 0 means never suspend
calibration_file = ""         # empty = the default file in the data directory
speech_guard = true           # suppress a jaw clench while you dictate
ledger_autosave_seconds = 60  # seconds between saves of the activation counters (5 to 3600)
calibration_max_age_days = 30 # a calibration older than this is not used (1 to 365)
watchdog_seconds = 1.5        # release a held squeeze if no samples arrive for this long (0.5 to 30)
min_event_confidence = 0.0    # drop detections below this confidence (0 to 1); 0 keeps them all

# What a squeeze does, by strength (light, hard, or on for a detector that reports none).
# A light squeeze types what you say; a hard one speaks a command.
mode_map = { light = "full_text", hard = "command" }

# Discrete events (double_blink, jaw_clench) become one command phrase from the command
# grammar, run through the activation confirmation gate. Undo is the default for a double blink.
intent_map = { double_blink = "undo" }
```

Then restart so the daemon picks it up:

```bash
yazses restart
```

`source` is empty by default, and with no source nothing starts even when `enabled` is true. A BrainFlow
source is `brainflow:<board_id>` with an optional serial port, where the board id is BrainFlow's integer
id for your board, for example `brainflow:0:/dev/ttyUSB0` for an OpenBCI Cyton. `yazses biosignal doctor`
shows what it can see, and `yazses biosignal boards` lists the boards. Only the listed boards open: any
other id is refused, and that includes boards that stream over a network, such as OpenBCI's Wi-Fi shield. The other source kinds
(`lsl:`, `thinkgear:`, `bitalino:`, `myo:`) are listed in
[the hardware guide](biosignal-hardware.md#other-devices-and-recordings); run
`yazses biosignal check-source <source>` once to see that a new device streams cleanly. An event
left out of `mode_map` or `intent_map` does nothing. The values in the example are the shipped defaults
except `source` and `enabled`; they are starting points, not tuned recommendations. Nobody has measured
any of them on a real person yet, which is why the next sections show you how to measure your own.

## The commands

Run `yazses biosignal --help` for exact options. The ones you will use first, in order:

1. **`yazses biosignal doctor`** checks the chain before you trust it: the extra is installed, the source
   opens, samples arrive at the expected rate, `mains_hz` matches the interference it sees, the signal is
   not flat or clipped, and a calibration profile exists and matches your channels. It takes the
   `synthetic`, `file:` and `brainflow:` sources. For an `lsl:`, `thinkgear:`, `bitalino:` or `myo:` source
   it reports "unknown source" and does not check the device; use `check-source` for those (see
   [Other devices](biosignal-hardware.md#other-devices-and-recordings)) and the system-wide `yazses doctor`
   row for their advice. Each problem comes with the reason and the fix, and the output ends with one
   **`Verdict:`** line: either that you are ready, or the single most important next step (pick a source,
   install a library, calibrate). Read that line first. Once `[biosignal] enabled = true`, a ready verdict
   points you to `yazses biosignal field-test`; while the feature is off, it tells you to set
   `enabled = true` and run `yazses restart`. Start here, and again after you move the electrode. The
   system-wide `yazses doctor` has a "Biosignal switch" row. It is skipped while the feature is off. Once
   the feature is on, it checks the configured source without opening it, and for each device source it
   names what is missing (the extra to install, a placeholder spec that still needs a serial port, LSL
   stream name or Bluetooth address) and the fix. A Windows COM port such as `COM3` is not a file, so the
   `[emg] device_port` row cannot check that it exists: it shows SKIP and says the port will be tried when
   YazSes starts.
2. **`yazses biosignal calibrate`** runs a short guided session: you **relax**, squeeze **lightly**,
   squeeze **hard**, **blink** three times, and **clench your jaw** three times. It skips a step your
   source has no channel for, and the blink and clench steps only run when those switches are enabled (or
   with `--blink` / `--clench`). It writes a small local profile, not your raw signal. It stops and writes
   nothing if the signal is bad, and it tells you which step failed.
3. **`yazses biosignal monitor`** shows the live signal quality, the events as they are detected, and your
   measured activation and cancel counts for the run. Use it to see, before you rely on a switch, what
   makes it fire. It does not apply your false-positive budget: the budget runs in the daemon, and
   `report` judges your rate against it. For a source that reports counts rather than microvolts (Myo,
   gForce), it says that the microvolt-absolute checks were skipped. When the stream itself is at fault (a
   timestamp went backwards, a packet was lost or repeated, or the stream stalled), it holds events and
   prints `Events HELD: the stream-integrity gate is closed. Reason: ...` with how much clean signal is
   still needed (`Cleared? not yet: ...`), then `Stream integrity: cleared (...)` once the hold ends.
4. **`yazses biosignal replay <recording>`** runs a saved recording through the same detectors with no
   hardware, so you can try a threshold change on yesterday's data or check a bug report.
5. **`yazses biosignal report`** summarises how often each event fired and how often you cancelled it,
   with a confidence interval, so you can judge the switch on evidence.
6. **`yazses biosignal field-test`** is the in-situ measurement of how often the switch fires when you did
   *not* mean it. See [Measure your own rate](#measure-your-own-rate).

Further commands, for working with recordings, your profile and the budget guard:

- **`yazses biosignal boards`** lists the boards the switches are known to work with and their BrainFlow
  ids, for the `source` setting. It needs no hardware.
- **`yazses biosignal record --out session.csv --seconds 60`** saves raw signal from your source to a file
  (`.csv` or `.npz`) for `replay` or `evaluate`. It writes only the file you name, readable only by you,
  and refuses to overwrite one without `--force` (see [Privacy](#privacy)).
- **`yazses biosignal evaluate`** scores the detectors against known events and reports precision, recall,
  latency and false alarms per hour. With no options it runs a scripted synthetic session, which shows the
  pipeline is wired correctly, not how it will do on your skin. For your own signal, record a session, label
  the events in a JSON file, and run `yazses biosignal evaluate --file session.csv --truth events.json`.
- **`yazses biosignal profile`** says which board and channels your calibration profile was made for
  and how old it is; it never prints a threshold. **`yazses biosignal profile-clear`** deletes it so you can
  start again. Without a profile the muscle-squeeze switch stays off.

A first-time sequence:

```bash
yazses biosignal doctor
yazses biosignal calibrate
yazses biosignal monitor      # squeeze, blink and talk; watch what it reports
yazses biosignal field-test   # how often does it fire by mistake, by activity?
yazses restart
```

## Try it with no hardware

Everything here uses the built-in `synthetic` source, a generated signal with scripted gestures. The output
below is from one run of this repository's code. It shows the code path works. It says nothing about how a
switch behaves on a person.

```bash
yazses biosignal doctor --source synthetic
yazses biosignal monitor --source synthetic --seconds 12 --clench
```

`doctor` runs a self-check through the real pipeline and ends with a verdict:

```text
Self-check (synthetic signal through the real pipeline):
  [OK]   scripted double blink detected
  [OK]   quality gate: degraded
Verdict: ready. Nothing is switched on yet; to use it, set [biosignal] enabled = true and run `yazses restart`.
```

`monitor` prints the signal quality and each detection as it happens. Its demo repeats scripted double
blinks, a jaw clench and a squeeze every 8 seconds. `--clench` turns the jaw-clench detector on for the
run, since it is off by default. From one 12-second run:

```text
Monitoring synthetic  (fs 500 Hz, 4 channels; detectors: emg, double_blink, jaw_clench).  Ctrl-C to stop.  Demo gestures are scripted every 8 s.
  Muscle squeeze: off until you calibrate (`yazses biosignal calibrate`).
       4.63s  double_blink   conf=0.53  ch=Fp1,Fp2
       7.02s  jaw_clench     conf=0.69  ch=Fp1,Fp2
...
Stopped (time limit reached) after 12.0 s, 299 blocks.
Detections:
  double_blink      1
  jaw_clench        1
```

The demo runs only inside `monitor`, and nothing it detects is typed or acted on. The daemon does not run
the demo script, so enabling the synthetic source does not make a running YazSes act on scripted gestures.

**The squeeze does not fire here.** The muscle-squeeze detector stays off until a calibration profile
exists, and `calibrate` cannot make one from the synthetic source. It stops with exit code 2:

```text
The synthetic source makes no deliberate gestures, so there is nothing to calibrate on. Use a board, or `file:<recording>` of a calibration session.
```

So a squeeze can be tried only with a real board, or with a recording of a real calibration session.

To replay a generated session through the same detectors:

```bash
yazses biosignal record --source synthetic --seconds 30 --out session.csv --truth-out truth.json
yazses biosignal replay session.csv
```

```text
      15.63s  double_blink   conf=0.53  ch=Fp1,Fp2

Done (end of recording).  Detections:
  double_blink      1
```

`record` writes the file owner-only (mode 0600), and `--truth-out` writes the scripted events, which
`evaluate --file session.csv --truth truth.json` can score. Its output on the generated signal, from a
60-second run of `yazses biosignal evaluate --seconds 60`:

```text
Evaluating synthetic:mixed (seed 0): 60 s, 8 known events, detectors: double_blink, jaw_clench, tolerance 0.3 s
  note: muscle squeeze not evaluated: no calibration profile (`yazses biosignal calibrate`)

kind          TP  FP  FN  precision  recall    F1  lat med ms  lat p95 ms  FP/hour
------------  --  --  --  ---------  ------  ----  ----------  ----------  -------
double_blink   4   0   0       1.00    1.00  1.00         -19          -4      0.0
jaw_clench     4   0   0       1.00    1.00  1.00          25          33      0.0
```

Its caveat line reads: `Caveat: results on synthetic signals prove the detection logic, not real-world
accuracy.` Treat every number above as the generated signal's, not yours.

## Measure your own rate

Whether a switch is livable depends on one number: how often it fires when you did not mean it. Nobody
has published that number for the muscle, blink and jaw switches in daily use, and the detectors here have
been tested only on generated signals. **Your own measurement is currently the best evidence there is, and
it is only evidence about you, your board and your electrode placement.**

```bash
yazses biosignal field-test                      # the standard guided session, about ten minutes
yazses biosignal field-test --minutes 20         # stretch it: the bounds tighten with more signal
yazses biosignal field-test --json --out ft.json # machine-readable, and keep the counts
```

The session prompts you on screen to sit still, talk, chew, type and use the mouse, and look around, one
activity at a time, with your real detectors running on your real signal. Then it asks you for each
gesture on cue (squeeze, double blink and jaw clench, whether or not you have that switch turned on; a
switch that is off cannot fire, so ignore the rows for the ones you are not using). **Nothing is typed or acted on, and no signal is saved.** Whatever a switch fires on
while you were not trying to trigger it is a *phantom activation*; the report gives those per hour of
usable signal for each activity, so you can see whether the trouble is the chewing, the talking or the
desk. A single natural blink is not counted as a phantom (it is not mapped to an action). Time the quality
gate rejected is left out of the denominator, so a bad contact cannot make the switch look quieter than it
is, and a phase with too little usable signal is marked inconclusive.

Read the **upper 95%** column, not the estimate. A few minutes of data bound a rate only loosely: *zero*
phantoms in N minutes still allows a rate of about 180 divided by N per hour (the "rule of three"), so a
single short session cannot show that a switch is quiet, only that it is not obviously loud. The report ends
with a verdict (`usable`, `promising`, `needs_tuning`, `do_not_enable` or `inconclusive`) and the reasons
for it. If you left a switch off, its gesture row will show no hits and can pull the verdict down: read the
rows of the switches you actually use. Those rungs and every number behind them are design choices that have not been validated on real
recordings, and the weighted "workday estimate" uses an assumed mix of activities that is illustrative, not
data. To tighten a result, repeat the test on different days and with the electrode re-seated, and compare
the sessions.

If you choose to share your result (for example in an
[issue](https://github.com/MSKazemi/yazses/issues)), share the JSON from `--json` or `--out` and add, in
words, your board, where the electrode was, and the YazSes version; the file carries none of those. The
file holds aggregate counts, whole-second durations, activity labels and cue-to-response times; it holds no
signal, no amplitudes, no thresholds and no timestamps of events. It is written readable only by you and
never over an existing file, and nothing sends it anywhere. Please do not attach a recording or a
screenshot of the live signal.

The field test cannot see the one failure that matters most in daily use, because it drives nothing: it
cannot tell you whether a stuck microphone is possible. The release watchdog and the stress cases in
[the validation protocol](https://github.com/MSKazemi/yazses/blob/main/design/specs/biosignal-validation-protocol.md)
address that, and so does watching `yazses biosignal report` after some days of real use.

## Calibration is per person

Calibration sets the thresholds for **blink, jaw clench and squeeze strength from your own signal**, not
from a population average: your relaxed baseline, how big your blink is on your electrode, how hard you
clench, and how a light squeeze differs from a hard one. Without a profile the muscle-squeeze switch stays
off and `doctor` says so. Re-run `calibrate` whenever you move or replace an electrode or change board or
channel; `yazses biosignal profile` tells you which board and channels the current profile was made
for and how old it is (in words, such as "3 days ago").

YazSes also checks the profile for you while it runs. A profile made for a different board, a different set
of channels or a different sampling rate is **not used**, and neither is one older than
`calibration_max_age_days` (30 by default). The switches that depend on it are held off, a held squeeze is
released, and `doctor` and the status say why in plain words. The muscle-squeeze switch has no built-in
defaults, so it stays off until you calibrate again; the blink and jaw-clench switches fall back to
conservative built-in values. Failing closed is deliberate: a calibration for a different electrode is a
guess, and a guess here opens the microphone.

## The speech guard

Speaking moves the muscles you clench with, so a jaw clench read while you talk is not a deliberate one.
With `speech_guard = true` (the default) a jaw clench is **suppressed while you are speaking**: while a
dictation turn is being recorded (including one a squeeze started) or a meeting is being captured, plus a
short moment after it. The guard follows what YazSes is doing, not an analysis of the signal. The trade is
deliberate: you may miss a clench made mid-sentence, but the guard is there so that talking is not mistaken
for a clench. It applies to the jaw clench only, and it has no effect while `jaw_clench` is off. Turn it off
only to measure the unguarded rate with `yazses biosignal report`.

## Pausing it

The biosignal switch takes part in the global hands-free pause when the global stop is on
(`[handsfree_safety] enabled`, which the hands-free preset sets; see
[Set up hands-free input](hands-free-setup.md)). With it on:

- `yazses handsfree pause` stops the switch along with the other hands-free inputs. A squeeze that is being
  held when you pause is released, so the microphone closes with the pause, and a squeeze is ignored while
  paused.
- It starts paused after each start of YazSes, once it has received its first samples, and
  `yazses handsfree resume` arms it. A pause is never undone by itself.
- If the samples stop arriving (a headset out of range, a cable out), the switch stops acting. A switch that
  only holds the microphone (no event labels in `intent_map`) re-arms itself shortly after samples return;
  after a pause or a fault, only `yazses handsfree resume` does.

Without `[handsfree_safety]`, the global pause is not in play and the switch is limited only by its own
budget guard.

## Tune the false-positive budget

A switch that fires when you did not mean it is worse than no switch, so YazSes counts its own mistakes.

- **What is counted.** Every activation is recorded locally. One you cancel, or that is followed by
  nothing, counts as a *cancelled* activation. That is a **proxy** for a false positive: it also counts
  an activation you cancelled for some other reason, and it misses a false positive you did not notice.
  `report` shows the rate with a confidence interval, because with only a few activations the number
  alone means little. The counters are saved to disk every `ledger_autosave_seconds` while YazSes
  runs (60 by default) and again when it stops cleanly, so a crash or power loss costs you at most that
  interval of the record.
- **`max_cancelled_per_hour`** is your budget (6.0 by default, a starting point and not a measured
  recommendation; 0 turns the guard off, so the rate is still counted but nothing is ever suspended).
- **What happens when you go over it.** The guard acts in two steps. First it **desensitizes** the
  detectors, so a stray movement has to be stronger to count. If the cancelled rate **stays above the
  budget**, it then **suspends** them and tells you, rather than keep misfiring. A suspension is not
  permanent: you can **release it with one action**, `yazses handsfree resume`. If you do nothing it lifts
  on its own after a pause (5 minutes to start, doubling on each repeat up to an hour), and the switch comes
  back at reduced sensitivity. It never re-enables itself at full sensitivity while the rate is still too
  high.
- **Choosing the budget.** Raise it only if the cancelled activations really are acceptable to you; lower
  it if a stray activation is costly (for example when you dictate into a terminal).
- **If it fires too often:** re-run `calibrate` (a re-seated electrode changes everything), check
  `monitor` for what is triggering it, make sure the electrode contact is good, and prefer a squeeze on
  a muscle you do not otherwise use while you are working.
- **If it misses you:** the signal may be below the threshold, the budget guard may have desensitized the
  detectors, or the quality gate may be suppressing events because the contact is poor. `monitor` shows
  which, and `doctor` names the cause.

There is no recommended setting yet. The community has not measured these rates over real workdays, and
your own `field-test` and `report` are currently the best evidence available. The guard is not a
substitute for either: it can only react to activations you notice and cancel.

Three further settings shape what reaches the microphone. `watchdog_seconds` releases a held squeeze when
no samples arrive for that long (a cable pulled, a Bluetooth stall), so a vanished device cannot leave the
microphone open. `min_event_confidence` drops weak detections before they act (raising it trades missed
presses for fewer false ones; releasing a held squeeze is never blocked by it). While the budget guard has
desensitized the switch, it raises its own effective floor on top of this.

## Honest limitations

- **Blink and jaw clench are artifacts, not brain signals.** On an EEG headband you are reading eye and
  muscle activity that leaks into the headband. The research page records a best measured blink switch of
  99.5% accuracy at 0.10 false positives per minute, which is about 50 stray activations in a workday
  without extra safeguards. That is why single blinks do nothing by default and a *double* blink is the
  gesture.
- **Talking confounds the jaw.** Speaking moves the same muscles as clenching. The speech guard
  suppresses a jaw clench while you dictate, which means it may miss one, but it is there so that talking
  is not mistaken for one. It cannot tell a clench from chewing or yawning, so check your own rate with
  `report` before you rely on a jaw clench.
- **It is personal.** Your skin, electrode placement and muscle differ from everyone else's. A profile
  made for one placement is wrong for another. Re-calibrate when you move or replace an electrode.
- **A bad signal means no events, on purpose.** A flat line, a clipped signal, strong mains hum, a
  drifting baseline or dropped samples all make YazSes ignore the channel and say why. That is the quality
  gate working, not a bug.
- **Unmeasured.** The detectors have been tested on synthetic and replayed signals. They have not been
  shown to work for any particular person, electrode or board, and their defaults are provisional. No
  real-hardware result has been collected yet; `field-test` is how that changes.
- **A squeeze is the recommended trigger.** A muscle electrode on a muscle you choose gives the cleanest
  signal. Blink and jaw clench are artifacts, and the jaw clench is off by default for that reason.
- **Electrode shifts and steps are not squeezes.** A sudden step in the signal (an electrode moving, a cable
  jolted) does not start a squeeze. A burst must keep its energy after its first moment, and a one-way level
  change does not count as a contraction. On the synthetic step fixture (steps of 300 to 5000 µV with a 25
  to 200 ms rise, 15 ms bumps and single-sample pops, 30 to 40 seeds per cell) no step was accepted as a
  squeeze. That fixture is white noise, not muscle, and a jolted cable on real skin has not been measured.
- **Mains hum on blink channels.** On an EOG (blink) channel the mains check reads the signal through the
  same low-pass the blink detector applies, so hum that the detector already filters out does not count
  against the channel. Synthetic, 500 double blinks: with 10 µV of hum added, 411 were still detected after
  this change (0 with the mains check on before it); with 50 µV, none were. The 10 µV fixture has no real
  recording behind it, so how much hum a real channel can carry is unmeasured.
- **A slow callback drops queued input.** A squeeze's transcription runs on the runner's own thread. After a
  callback of 1 second or more on a live device, the runner discards what the device queued in the meantime
  and resets the detectors, so a gesture made during that time is ignored rather than acted on late. The
  daemon logs `discarded N queued block(s) after a slow callback`. This does not happen while a squeeze is
  held. The count is `backlogs_discarded` in the runner's status snapshot; the `yazses status` output does
  not show it yet. Lost serial bytes during that time are unmeasured on a real device.
- **Count-unit devices.** A Myo, or a gForce armband through BrainFlow, reports raw counts. The quality gate
  skips its microvolt limits for those (see [the hardware guide](biosignal-hardware.md)). Its thresholds for
  counts are untuned.
- **Not thought control.** Decoding motor imagery, SSVEP or P300 is not in this feature, and EEG headbands
  here are only read for the eye and muscle activity on them.

## Privacy

Everything stays on your machine. The electrodes are read locally, and no network connection is made.
Your calibration profile and the activation log are local files; the profile is readable only by you.
A recording of your signal is **biometric-adjacent** data: it is written only when you ask for one, and
you should not paste one into a public issue. For a bug report, share the output of
`yazses biosignal doctor` instead, which contains no signal values.

## Troubleshooting

| Symptom | What to check |
|---|---|
| `doctor` says the library is missing | Install the `emg-band` (BrainFlow) or `emg` (serial) extra with the command it prints for your install method, then `yazses restart`. |
| `doctor` cannot open the source | The device is unplugged, in use by another program, or the serial port or board id is wrong. On Linux your user may need to be in the `dialout` group for a serial port. A missing device is a logged no-op, not a crash. |
| Nothing ever fires, `monitor` says the channel is untrusted | Flat line (no contact or a dead lead), clipping (gain too high), or strong mains noise. Re-seat the electrode, keep leads away from power cables, and check `mains_hz`. |
| Mains interference reported although the electrode is fine | `mains_hz` is the wrong frequency for where you are (50 or 60). |
| It fires when you chew or yawn | Expected to a degree on a jaw clench. Re-run `calibrate`, or use a squeeze on another muscle. The speech guard covers dictation, not chewing. |
| It fires constantly, then gets harder to trigger, then stops | The budget guard first desensitized the detectors and then suspended them. Check `report`, fix the cause (usually contact or placement), re-run `calibrate`, then run `yazses handsfree resume`. |
| It stopped responding after `yazses handsfree pause`, or does not act after a restart | The global pause covers it when `[handsfree_safety]` is on, and it starts paused. Run `yazses handsfree resume`. |
| `doctor` or the status says the calibration "is not used" | It was made for a different board, channels or rate, or it is older than `calibration_max_age_days`. Run `yazses biosignal calibrate`. The squeeze stays off until then. |
| It worked yesterday, not today | The electrode moved. Re-run `calibrate`. |
| Squeeze opens the mic but it will not close | The signal never fell below the release threshold; a watchdog ends such a hold on its own. Re-run `calibrate` and check contact. |
| Nothing is typed after a squeeze | That is the normal dictation path now; see [silent audio](silent-audio-discarding.md) and run `yazses doctor`. |
| A gesture made during a long transcription did nothing | By design: after a callback of 1 second or more, gestures made meanwhile are dropped, not acted on late. The daemon log says `discarded N queued block(s)`. See the slow-callback note under Honest limitations. |

## See also

- [Muscle and brain control: the honest hierarchy](../research/muscle-brain-control.md): why the
  switch reads muscle and eye artifacts, and what EEG can and cannot do.
- [Biosignal hardware guide](biosignal-hardware.md): the serial path against BrainFlow boards, electrode
  placement, mains frequency and safety.
- [Hands-free computing with a muscle switch](../use-cases/biosignal-hands-free.md): who this is for and
  how to start.
- [Set up hands-free input](hands-free-setup.md): the camera-based switches this one can sit beside.
- [Change the hold-to-talk key](change-hotkey.md): the key a squeeze stands in for.
